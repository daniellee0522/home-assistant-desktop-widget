"""The window layer: frameless, transparent Qt web views plus the bridge.

A Qt window can be genuinely transparent, so outside the card's rounded
corners the desktop shows through unpainted. The interface loosely follows
pywebview's (create_window, window.events, evaluate_js), which is why the
page still calls `window.pywebview.api`.

The bridge: the page's own origin (a loopback HTTP server) answers
POST /api/<name> by calling that method on the api object, and
web/bridge.js builds `window.pywebview.api` out of fetch(). Anything
positional is done by HWND in physical pixels, as in main.py.
"""

import faulthandler
import json
import os
import threading
import time
import traceback
from collections import deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow

_app = None
_heartbeat = None
_windows = []
_server = None
_server_port = 0
_web_dir = None


# ---------------------------------------------------------------------
# Watchdog: hang reports and resume detection
# ---------------------------------------------------------------------
# Windows closes a program whose GUI thread stops answering without leaving
# any record. The GUI thread stamps a heartbeat every half second; if it
# goes stale, every Python stack is written to the log first.
_LOG_PATH = None
_alive_at = [0.0]
_hang_logged = [False]
_resume_hooks = []

# How long the GUI thread may go without answering before it counts as stuck.
_STALL_SECS = 10.0
# A one-second watchdog tick that took this long means the machine slept.
_SUSPEND_SECS = 20.0


def log(line):
    """A line in the program's own log, timestamped. Never raises."""
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        if _LOG_PATH:
            with open(_LOG_PATH, "a", encoding="utf-8") as f:
                f.write("%s  %s\n" % (stamp, line))
        else:
            print("%s  %s" % (stamp, line))
    except Exception:
        pass


def on_resume(fn):
    """Call fn after the machine has been suspended and come back.

    Detected by the watchdog's clock rather than WM_POWERBROADCAST, which
    needs no native event filter in the message loop.
    """
    _resume_hooks.append(fn)


def _dump_stacks(why):
    try:
        with open(_LOG_PATH or "hang_report.txt", "a", encoding="utf-8") as f:
            f.write("\n==== %s  %s ====\n" % (why, time.strftime("%Y-%m-%d %H:%M:%S")))
            faulthandler.dump_traceback(file=f, all_threads=True)
            f.flush()
    except Exception:
        traceback.print_exc()


def _watchdog():
    last = time.monotonic()
    while True:
        time.sleep(1.0)
        now = time.monotonic()
        slept = now - last
        last = now
        if slept > _SUSPEND_SECS:
            log("resumed after %.0fs suspended" % slept)
            _alive_at[0] = now
            _hang_logged[0] = False
            for fn in list(_resume_hooks):
                try:
                    fn()
                except Exception:
                    log("resume hook failed: " + traceback.format_exc())
            continue
        stalled = now - _alive_at[0]
        if stalled > _STALL_SECS:
            if not _hang_logged[0]:
                _hang_logged[0] = True
                log("GUI thread has not answered for %.0fs - dumping stacks" % stalled)
                _dump_stacks("GUI THREAD STALLED %.0fs" % stalled)
        elif _hang_logged[0]:
            _hang_logged[0] = False
            log("GUI thread answering again")


# ---------------------------------------------------------------------
# Events: `window.events.shown += handler`
# ---------------------------------------------------------------------
class _Event:
    def __init__(self):
        self._handlers = []

    def __iadd__(self, fn):
        self._handlers.append(fn)
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
        self.shown = _Event()           # first show only
        # Every show, synchronously inside it. Showing a window restores
        # DWM's rounding and border, so undoing them must run each time
        # and before the first frame is presented.
        self.showing = _Event()
        self.loaded = _Event()
        self.closing = _Event()
        self.moved = _Event()
        self.deactivated = _Event()


# ---------------------------------------------------------------------
# The bridge: the page's own origin answers for the API
# ---------------------------------------------------------------------
class _Handler(SimpleHTTPRequestHandler):
    """Serves web/ and, at /api/<name>, the api object behind it."""

    # Keep-alive: the backdrop alone calls ~20 times a second per window.
    protocol_version = "HTTP/1.1"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=_web_dir, **kw)

    def log_message(self, *a):
        pass

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
        # Each call runs on its own server thread; the api marshals window
        # work onto the GUI thread itself (see Window.run_on_ui_thread).
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
    # Loopback only, on a port the OS picks.
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
    """The Qt widget behind a Window."""

    def __init__(self, window):
        super().__init__()
        self._window = window
        # Qt.Tool keeps these windows off the taskbar and out of Alt-Tab.
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        if window.transparent:
            self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.view = QWebEngineView(self)
        page = self.view.page()
        if window.transparent:
            page.setBackgroundColor(Qt.transparent)
        s = page.settings()
        s.setAttribute(QWebEngineSettings.ShowScrollBars, False)
        s.setAttribute(QWebEngineSettings.FocusOnNavigationEnabled, False)
        self.setCentralWidget(self.view)
        self.view.loadStarted.connect(self._on_load_started)
        self.view.loadFinished.connect(self._on_load)
        page.renderProcessTerminated.connect(self._on_renderer_terminated)
        self._shown_once = False
        self._renderer_failures = 0
        self._renderer_reload_pending = False
        # The HWND is cached on the GUI thread and refreshed on WinIdChange.
        # Calling winId() from request threads races Qt recreating native
        # windows after a display change (e.g. on resume) and has wedged
        # the GUI thread before.
        self._hwnd = 0
        self._cache_hwnd()

    def _cache_hwnd(self):
        """GUI thread only."""
        try:
            self._hwnd = int(self.winId())
        except Exception:
            self._hwnd = 0
        return self._hwnd

    def _on_load_started(self):
        self._window._page_loaded = False

    def _on_renderer_terminated(self, status, exit_code):
        self._window._page_loaded = False
        log("Renderer terminated: %s status=%s exit=%s" % (
            self._window.title, getattr(status, 'name', str(status)), exit_code))
        if self._renderer_reload_pending:
            return
        self._renderer_reload_pending = True
        self._renderer_failures += 1
        delay = min(1000 * (2 ** min(self._renderer_failures - 1, 4)), 16000)
        QTimer.singleShot(delay, self._reload_renderer)

    def _reload_renderer(self):
        self._renderer_reload_pending = False
        if self._window.url:
            log("Reloading renderer: " + self._window.title)
            self.view.load(QUrl(self._window.url))

    def _on_load(self, ok):
        self._window._page_loaded = bool(ok)
        if not ok:
            log("Page load failed: " + self._window.title)
            return
        self._renderer_failures = 0
        # Scripts queued before this page could run them.
        while self._window._pending_scripts:
            self.view.page().runJavaScript(self._window._pending_scripts.popleft())
        self._window.events.loaded.fire()

    def showEvent(self, e):
        super().showEvent(e)
        self._cache_hwnd()
        self._window.events.showing.fire()
        if not self._shown_once:
            self._shown_once = True
            # Once the event loop has settled and the window is really up.
            QTimer.singleShot(0, self._window.events.shown.fire)

    def moveEvent(self, e):
        super().moveEvent(e)
        # Logical pixels; handlers needing physical ones read the HWND.
        pos = e.pos()
        self._window.events.moved.fire(pos.x(), pos.y())

    def closeEvent(self, e):
        keep = self._window.events.closing.fire()
        if keep is False:
            e.ignore()
        else:
            e.accept()

    def event(self, e):
        t = e.type()
        if t == QEvent.Type.WindowDeactivate:
            self._window.events.deactivated.fire()
        elif t == QEvent.Type.WinIdChange:
            self._cache_hwnd()
        return super().event(e)


class Window:
    def __init__(self, title, url=None, js_api=None, width=800, height=600,
                 x=None, y=None, transparent=False, hidden=False):
        self.title = title
        self.url = url
        self.js_api = js_api
        self.transparent = transparent
        self.events = _Events()
        self._page_loaded = False
        self._pending_scripts = deque(maxlen=512)
        self._native = _WebWindow(self)
        self._native.setWindowTitle(title)
        self._native.resize(int(width), int(height))
        if x is not None and y is not None:
            self._native.move(int(x), int(y))
        self._hidden = hidden
        if url:
            self._native.view.load(QUrl(url))

    @property
    def native(self):
        return self._native

    def hwnd(self):
        # Safe from any thread; see _WebWindow.__init__.
        h = self._native._hwnd
        if h:
            return h
        try:
            return _invoke(self._native, self._native._cache_hwnd, wait=True) or None
        except Exception:
            return None

    def show(self):
        _invoke(self._native, self._native.show)

    def hide(self):
        _invoke(self._native, self._native.hide)

    def destroy(self):
        _invoke(self._native, self._native.close)

    def evaluate_js(self, script):
        def run():
            if self._page_loaded:
                self._native.view.page().runJavaScript(script)
            else:
                self._pending_scripts.append(script)
        _invoke(self._native, run)
        return None

    def run_on_ui_thread(self, fn):
        """Run fn on the GUI thread and wait for its result."""
        return _invoke(self._native, fn, wait=True)


class _Marshal(QObject):
    """Carries a call from a request thread onto the GUI thread.

    A queued signal on an object living there; QTimer.singleShot from a
    thread without an event loop silently never fires.
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
        # A slow frame is not a hang, but a hang must not take the caller
        # with it.
        done.wait(5.0)
    return box.get("value")


# ---------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------
def create_window(title, url=None, **kw):
    """`url` may be a path to a file in the web directory; it is served
    from the bridge's origin so API calls are same-origin."""
    if url and not url.startswith("http"):
        path, _, frag = url.partition("#")
        name = os.path.basename(path)
        url = "http://127.0.0.1:%d/%s%s" % (_server_port, name, ("#" + frag) if frag else "")
    win = Window(title, url=url, **kw)
    _windows.append(win)
    return win


def start():
    """Show the windows not created hidden and run the event loop."""
    app = QApplication.instance() or QApplication([])
    for win in _windows:
        if not win._hidden:
            win.native.show()
    app.exec()


def prepare(web_dir, api, log_dir=None):
    """Create the application and the bridge, before any window exists."""
    global _app, _marshal, _LOG_PATH, _heartbeat
    if log_dir:
        _LOG_PATH = os.path.join(log_dir, "widget.log")
        try:
            # Hard crashes (access violations) get their Python stacks logged.
            faulthandler.enable(open(_LOG_PATH, "a", encoding="utf-8"))
        except Exception:
            pass
    _app = QApplication.instance() or QApplication([])
    _app.setQuitOnLastWindowClosed(False)
    log("Started pid=%s" % os.getpid())
    _app.screenAdded.connect(lambda screen: log("Display added: " + screen.name()))
    _app.screenRemoved.connect(lambda screen: log("Display removed: " + screen.name()))
    # Created on the GUI thread, which is where its queued calls then run.
    _marshal = _Marshal()
    _alive_at[0] = time.monotonic()
    # The heartbeat the watchdog reads: one assignment twice a second.
    _heartbeat = QTimer()
    _heartbeat.timeout.connect(lambda: _alive_at.__setitem__(0, time.monotonic()))
    _heartbeat.start(500)
    threading.Thread(target=_watchdog, daemon=True, name="watchdog").start()
    _start_server(web_dir, api)
    return _server_port
