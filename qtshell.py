"""What every window of the program shares, whatever draws it (nativeui/).

The Qt application and its event loop; calls carried onto the GUI thread from any other (`_invoke`);
the window events main.py listens to (`window.events.shown += handler`); the program's log; and the
watchdog that writes every stack to it when the GUI thread stops answering, and that notices the
machine coming back from sleep and screens being added, removed or rescaled.
"""

import faulthandler
from ctypes import wintypes
import os
import threading
import time
import traceback

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QFileDialog

_app = None
_heartbeat = None
_windows = []             # every window made, for start() to show those not made hidden


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
_resume_pending = threading.Event()
_power_filter = None
_display_hooks = []
_display_timer = None


def on_display_change(fn):
    """Run fn on the GUI thread once a burst of screen changes settles."""
    _display_hooks.append(fn)


def _display_changed(*args):
    if _display_timer is not None:
        _display_timer.start(500)


def _notify_display_change():
    for fn in list(_display_hooks):
        try:
            fn()
        except Exception:
            log("display recovery failed: " + traceback.format_exc())


def _watch_screen(screen):
    screen.geometryChanged.connect(_display_changed)
    screen.availableGeometryChanged.connect(_display_changed)
    screen.logicalDotsPerInchChanged.connect(_display_changed)


def _screen_added(screen):
    log("Display added: " + screen.name())
    _watch_screen(screen)
    _display_changed()


class _PowerFilter(QAbstractNativeEventFilter):
    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0218 and msg.wParam in (0x0007, 0x0012):
                # Only signal here: recovery can block and must not run inside
                # Windows' synchronous power broadcast on the GUI thread.
                _resume_pending.set()
        return False, 0

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

    Runs on the watchdog thread, from Windows power notifications with a
    clock-gap fallback. Hooks must marshal window work to the GUI thread.
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
        notified = _resume_pending.is_set()
        _resume_pending.clear()
        if notified or slept > _SUSPEND_SECS:
            log("resume recovery (power=%s, clock gap=%.0fs)" % (notified, slept))
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
        self.closing = _Event()
        self.moved = _Event()
        self.deactivated = _Event()


# ---------------------------------------------------------------------
# Calls onto the GUI thread
# ---------------------------------------------------------------------
class _Marshal(QObject):
    """Carries a call from another thread onto the GUI thread.

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


def choose_image_file(title):
    """A native open-file dialog for a picture; the path, or "" if cancelled."""
    def ask():
        path, _ = QFileDialog.getOpenFileName(
            None, title, "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        return path or ""
    return _invoke(None, ask, wait=True) or ""


def ensure_marshal():
    """The GUI thread's queue of calls from other threads, made (on the GUI thread) if start() has not made
    it: windows made without start(), as in the tests, would otherwise be built from worker threads."""
    global _marshal
    if _marshal is None and QApplication.instance() is not None             and threading.current_thread() is threading.main_thread():
        _marshal = _Marshal()


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


def follow_screen(hwnd, x, y):
    """Before a window of ours is moved by its HWND to physical (x, y): put its Qt window on the screen there.

    Qt does not notice a move made with SetWindowPos: it keeps the old screen's device pixel ratio, and a
    window taken from a 125 % monitor to a 100 % one goes on drawing everything 1.25 times too large. GUI
    thread only."""
    app = QApplication.instance()
    if app is None:
        return
    target = None
    for screen in app.screens():
        # Each screen's top-left is in physical pixels, its size in its own logical ones.
        g, ratio = screen.geometry(), screen.devicePixelRatio()
        if g.x() <= x < g.x() + g.width() * ratio and g.y() <= y < g.y() + g.height() * ratio:
            target = screen
            break
    if target is None:
        return
    for widget in app.topLevelWidgets():
        handle = widget.windowHandle()
        if handle is not None and int(widget.winId()) == int(hwnd):
            if handle.screen() is not target:
                handle.setScreen(target)
            return


# ---------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------
def start():
    """Show the windows not created hidden and run the event loop."""
    app = QApplication.instance() or QApplication([])
    for win in _windows:
        if not win._hidden:
            win.native.show()
    app.exec()


def prepare(log_dir=None):
    """Create the application, before any window exists."""
    global _app, _marshal, _LOG_PATH, _heartbeat, _power_filter, _display_timer
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
    _display_timer = QTimer()
    _display_timer.setSingleShot(True)
    _display_timer.timeout.connect(_notify_display_change)
    _app.screenAdded.connect(_screen_added)
    _app.screenRemoved.connect(lambda screen: (log("Display removed: " + screen.name()), _display_changed()))
    for screen in _app.screens():
        _watch_screen(screen)
    # Created on the GUI thread, which is where its queued calls then run.
    _marshal = _Marshal()
    if os.name == "nt":
        _power_filter = _PowerFilter()
        _app.installNativeEventFilter(_power_filter)
    _alive_at[0] = time.monotonic()
    # The heartbeat the watchdog reads: one assignment twice a second.
    _heartbeat = QTimer()
    _heartbeat.timeout.connect(lambda: _alive_at.__setitem__(0, time.monotonic()))
    _heartbeat.start(500)
    threading.Thread(target=_watchdog, daemon=True, name="watchdog").start()
