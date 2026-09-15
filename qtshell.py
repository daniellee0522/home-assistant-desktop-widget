"""A pywebview-shaped window layer built on Qt.

This exists for one reason: a Qt window can actually be transparent, and
the WinForms one this replaces cannot. That is not a matter of taste - it
decides whether the card's rounded corners are the desktop itself or a
photograph of it taken a moment ago, and a photograph next to the live
thing beside it is a seam you can see whenever anything moves.

Measured on this machine, with the window hidden and shown and the two
photographs subtracted: inside the window, outside the card's rounded
corner, the difference is *zero*. Nothing is painted there at all. The
card's own area comes back correlated with the desktop behind it (0.72),
which is what a translucent tint over the real thing looks like.

The shape of the API is pywebview's, method for method, so the rest of
the program does not have to know which one it is talking to. What is
deliberately not pywebview's:

  * The bridge. pywebview injects `window.pywebview.api` and marshals
    calls over its own channel; here the page's own origin serves an
    /api/<name> endpoint and web/bridge.js builds the same object out of
    fetch(). One transport for both directions of the same conversation,
    no QWebChannel, and the page cannot tell the difference.

  * Windows are addressed by their HWND for anything positional, because
    everything around this - the z-order pinning, the capture exclusion,
    the tray corner arithmetic - is already Win32 and already thinks in
    physical pixels.
"""

import ctypes
import json
import os
import threading
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow

_app = None
_windows = []
_server = None
_server_port = 0
_web_dir = None


# ---------------------------------------------------------------------
# Events, in pywebview's shape: `window.events.shown += handler`
# ---------------------------------------------------------------------
class _Event:
    def __init__(self):
        self._handlers = []

    def __iadd__(self, fn):
        self._handlers.append(fn)
        return self

    def __isub__(self, fn):
        if fn in self._handlers:
            self._handlers.remove(fn)
        return self

    def fire(self, *args):
        out = None
        for fn in list(self._handlers):
            try:
                r = fn(*args)
                if r is not None:
                    out = r
            except Exception:
                traceback.print_exc()
        return out


class _Events:
    def __init__(self):
        self.shown = _Event()
        self.loaded = _Event()
        self.closing = _Event()
        self.moved = _Event()
        # Not pywebview's. It exposes this as the native form's own
        # Deactivate; a Qt window has no equivalent to reach into, so the
        # shell raises it instead - see focusOutEvent below.
        self.deactivated = _Event()


# ---------------------------------------------------------------------
# The bridge: the page's own origin answers for the API
# ---------------------------------------------------------------------
class _Handler(SimpleHTTPRequestHandler):
    """Serves web/ and, at /api/<name>, the js_api object behind it."""

    # HTTP/1.1, so the pages keep one connection each instead of opening a
    # new one per call. The backdrop asks about twenty times a second per
    # window, and on HTTP/1.0 every one of those was a fresh TCP connection
    # *and* a fresh thread in the threading server - which is a lot of
    # churn to pay for a call that crosses no process boundary.
    protocol_version = "HTTP/1.1"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=_web_dir, **kw)

    def log_message(self, *a):
        pass                      # not a web server anyone is watching

    def do_POST(self):
        if not self.path.startswith("/api/"):
            self.send_error(404)
            return
        name = self.path[5:].split("?", 1)[0]
        api = getattr(self.server, "api", None)
        fn = getattr(api, name, None)
        if api is None or fn is None or name.startswith("_") or not callable(fn):
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            args = json.loads(self.rfile.read(length) or b"[]")
        except Exception:
            self.send_error(400)
            return
        # Every call gets its own thread, because this is a threading
        # server - which is what the API already expected, and why
        # anything it does to a window has to be marshalled onto the GUI
        # thread (see Window.run_on_ui_thread).
        try:
            value = fn(*args)
            body = json.dumps({"value": value}, ensure_ascii=False, default=str)
        except Exception as e:
            traceback.print_exc()
            body = json.dumps({"error": repr(e)})
        raw = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except Exception:
            pass                  # the page went away mid-call

    def end_headers(self):
        if self.command == "GET":
            self.send_header("Cache-Control", "no-store")
        super().end_headers()


def _start_server(web_dir, api):
    global _server, _server_port, _web_dir
    _web_dir = web_dir
    # Loopback only, and a port the OS picks: this is a private channel
    # between the program and its own pages, not a service.
    _server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    _server.daemon_threads = True
    _server.api = api
    _server_port = _server.server_address[1]
    threading.Thread(target=_server.serve_forever, daemon=True).start()
    return _server_port


# ---------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------
class _WebWindow(QMainWindow):
    """The Qt side. Kept separate from Window so the parts the rest of the
    program touches stay small and boring."""

    def __init__(self, window):
        super().__init__()
        self._window = window
        flags = Qt.FramelessWindowHint | Qt.Tool
        # Qt.Tool is what keeps these off the taskbar and out of Alt-Tab,
        # which the old build did by rewriting extended styles after the
        # fact and hiding and re-showing the window to make them stick.
        self.setWindowFlags(flags)
        if window.transparent:
            self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.view = QWebEngineView(self)
        page = self.view.page()
        if window.transparent:
            page.setBackgroundColor(Qt.transparent)
        elif window.background_color:
            page.setBackgroundColor(QColor(window.background_color))
        s = page.settings()
        s.setAttribute(QWebEngineSettings.ShowScrollBars, False)
        s.setAttribute(QWebEngineSettings.FocusOnNavigationEnabled, False)
        self.setCentralWidget(self.view)
        self.view.loadFinished.connect(self._on_load)
        self._shown_once = False

    def _on_load(self, ok):
        self._window.events.loaded.fire()

    def showEvent(self, e):
        super().showEvent(e)
        if not self._shown_once:
            self._shown_once = True
            # After the event loop has settled, so anything the handler
            # does to the window lands on a window that really is up.
            QTimer.singleShot(0, self._window.events.shown.fire)

    def moveEvent(self, e):
        super().moveEvent(e)
        # pywebview's signature, which the handler ignores anyway: it reads
        # the position back off the window in physical pixels, because
        # these are logical ones and the two disagree per monitor.
        pos = e.pos()
        self._window.events.moved.fire(pos.x(), pos.y())

    def closeEvent(self, e):
        keep = self._window.events.closing.fire()
        if keep is False:
            e.ignore()
        else:
            e.accept()

    def event(self, e):
        # WindowDeactivate is Qt's version of the native Deactivate the
        # popover and the tray panel dismiss themselves on.
        if e.type() == e.Type.WindowDeactivate:
            self._window.events.deactivated.fire()
        return super().event(e)


class Window:
    def __init__(self, title, url=None, js_api=None, width=800, height=600,
                 x=None, y=None, frameless=False, easy_drag=False,
                 transparent=False, shadow=True, confirm_close=False,
                 hidden=False, min_size=(0, 0), background_color=None,
                 **ignored):
        self.title = title
        self.url = url
        self.js_api = js_api
        self.transparent = transparent
        self.background_color = background_color
        self.events = _Events()
        self._native = _WebWindow(self)
        self._native.setWindowTitle(title)
        self._native.resize(int(width), int(height))
        if x is not None and y is not None:
            self._native.move(int(x), int(y))
        self._hidden = hidden
        if url:
            self._native.view.load(QUrl(url))

    # -- what the rest of the program uses ----------------------------
    @property
    def native(self):
        return self._native

    def hwnd(self):
        try:
            return int(self._native.winId())
        except Exception:
            return None

    def show(self):
        _invoke(self._native, self._native.show)

    def hide(self):
        _invoke(self._native, self._native.hide)

    def destroy(self):
        _invoke(self._native, self._native.close)

    def evaluate_js(self, script):
        _invoke(self._native, lambda: self._native.view.page().runJavaScript(script))
        return None

    def evaluate_js_result(self, script, timeout=4.0):
        """evaluate_js, but waiting for what the page returns.

        Qt hands the result to a callback rather than returning it, so this
        is the callback turned back into a return value. Used by the
        project's own testing, which needs to ask the page questions -
        QtWebEngine's devtools endpoint refuses connections often enough
        here that it cannot be relied on for that.
        """
        box = {}
        done = threading.Event()

        def run():
            def got(value):
                box["value"] = value
                done.set()
            try:
                self._native.view.page().runJavaScript(script, 0, got)
            except Exception:
                traceback.print_exc()
                done.set()

        _invoke(self._native, run)
        done.wait(timeout)
        return box.get("value")

    def run_on_ui_thread(self, fn):
        """Run fn on the GUI thread and wait for it.

        Everything the API does arrives on a request thread (see
        _Handler), and everything it does to a window has to happen where
        the window lives.
        """
        return _invoke(self._native, fn, wait=True)


class _Marshal(QObject):
    """Carries a call from a request thread onto the GUI thread.

    It has to be a signal on an object that lives there. QTimer.singleShot
    from another thread looks like it works and does not: the timer is
    created on the calling thread, which has no event loop to fire it, so
    the call is simply dropped - silently, which is how the first version
    of this ended up with a window that never heard anything the API told
    it.
    """

    _call = Signal(object)

    def __init__(self):
        super().__init__()
        self._call.connect(self._run, Qt.QueuedConnection)

    def _run(self, fn):
        try:
            fn()
        except Exception:
            traceback.print_exc()

    def post(self, fn):
        self._call.emit(fn)


_marshal = None


def _invoke(widget, fn, wait=False):
    """Marshal fn onto the GUI thread."""
    app = QApplication.instance()
    if app is None or _marshal is None or threading.current_thread() is threading.main_thread():
        return fn()
    box = {}
    done = threading.Event()

    def run():
        try:
            box["value"] = fn()
        except Exception:
            traceback.print_exc()
        finally:
            done.set()

    _marshal.post(run)
    if wait:
        # Long enough that a slow frame is not mistaken for a hang, short
        # enough that a genuine one does not take the page with it.
        done.wait(5.0)
    return box.get("value")


# ---------------------------------------------------------------------
# The pywebview-shaped entry points
# ---------------------------------------------------------------------
def create_window(title, url=None, **kw):
    """`url` may be a path to a file in the web directory; it is served
    from the page's own origin so that the bridge is same-origin."""
    if url and not url.startswith("http"):
        path, _, frag = url.partition("#")
        name = os.path.basename(path)
        url = "http://127.0.0.1:%d/%s%s" % (_server_port, name, ("#" + frag) if frag else "")
    win = Window(title, url=url, **kw)
    _windows.append(win)
    return win


def start(func=None, web_dir=None, api=None, **kw):
    """Runs the GUI. `web_dir` and `api` replace pywebview's implicit
    wiring of the two - they are what the bridge serves."""
    app = QApplication.instance() or QApplication([])
    for win in _windows:
        if not win._hidden:
            win.native.show()
    if func:
        QTimer.singleShot(0, func)
    app.exec()


def prepare(web_dir, api):
    """Create the application and the bridge, before any window exists."""
    global _app, _marshal
    _app = QApplication.instance() or QApplication([])
    _app.setQuitOnLastWindowClosed(False)
    # Created here, on the GUI thread, which is what gives it the thread
    # affinity that makes the queued connection land in the right place.
    _marshal = _Marshal()
    _start_server(web_dir, api)
    return _server_port
