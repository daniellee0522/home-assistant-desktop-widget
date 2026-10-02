"""When the widget dims: the same rule as main.py's _watch_for_idle.

Dim once the desktop has been out of sight for dim_after_sec (at once when a
full-screen app is in front) and restore it when the desktop comes back. It is
timed on what is in front, not on input: someone busy in a browser is not
looking at the widget.
"""
import ctypes
import threading
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.GetAncestor.restype = ctypes.c_void_p
user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.MonitorFromWindow.restype = ctypes.c_void_p
user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

GA_ROOT = 2
MONITOR_DEFAULTTONEAREST = 2
DESKTOP_CLASSES = {"Progman", "WorkerW"}
SHELL_CLASSES = DESKTOP_CLASSES | {
    "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Windows.UI.Core.CoreWindow",
    "TopLevelWindowForOverflowXamlIsland", "XamlExplorerHostIslandWindow",
    "NotifyIconOverflowWindow"}


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


user32.WindowFromPoint.argtypes = [POINT]
user32.WindowFromPoint.restype = ctypes.c_void_p


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", ctypes.c_uint32)]


def _foreground_root():
    fg = user32.GetForegroundWindow()
    if not fg:
        return None
    return user32.GetAncestor(fg, GA_ROOT) or fg


def _class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def desktop_is_front(widgets, ours):
    """True when the desktop or a widget has the user's attention, False when
    another app does, None when the foreground only passes through."""
    try:
        root = _foreground_root()
        if not root or root in widgets:
            return True
        if root in ours:
            return None
        name = _class_name(root)
        if name in DESKTOP_CLASSES:
            return True
        return None if name in SHELL_CLASSES else False
    except Exception:
        return True


def fullscreen_app_present(ours):
    """True when the foreground window covers its whole monitor."""
    try:
        root = _foreground_root()
        if not root or root in ours or _class_name(root) in SHELL_CLASSES:
            return False
        r = wintypes.RECT()
        if not user32.GetWindowRect(root, ctypes.byref(r)):
            return False
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(user32.MonitorFromWindow(root, MONITOR_DEFAULTTONEAREST),
                                      ctypes.byref(info)):
            return False
        m = info.rcMonitor
        return r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom
    except Exception:
        return False


def nothing_visible_of(hwnd):
    """True when every sampled point of this window is covered by some other
    window: the widget sits at the bottom of the z-order, so it is often
    covered, and a covered glass need not be refreshed."""
    try:
        r = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return False
        w, h = r.right - r.left, r.bottom - r.top
        if w <= 0 or h <= 0:
            return False
        for fy in (0.08, 0.35, 0.65, 0.92):
            for fx in (0.04, 0.3, 0.55, 0.8, 0.96):
                top = user32.WindowFromPoint(POINT(int(r.left + w * fx), int(r.top + h * fy)))
                if not top:
                    continue
                if (user32.GetAncestor(top, GA_ROOT) or top) == hwnd:
                    return False
        return True
    except Exception:
        return False


class IdleWatcher:
    def __init__(self, enabled, after_sec, hwnds, on_change):
        self.enabled, self.after_sec, self.hwnds, self.on_change = enabled, after_sec, hwnds, on_change
        self.dimmed = False
        self._since = 0.0
        self._woke_at = 0.0
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._stop.set()

    def wake(self):
        """Someone touched the widget: held awake for a full idle period."""
        self._woke_at = time.monotonic()
        self._since = 0.0
        if self.dimmed:
            self.dimmed = False
            self.on_change(False)

    def _loop(self):
        while not self._stop.wait(1.0):
            try:
                if not self.enabled():
                    wanted = False
                else:
                    after = max(10, int(self.after_sec()))
                    mine = set(self.hwnds())
                    now = time.monotonic()
                    front = desktop_is_front(mine, mine)
                    if front:
                        self._since = 0.0
                        wanted = False
                    elif front is None:
                        wanted = self.dimmed
                    else:
                        if not self._since:
                            self._since = now
                        wanted = (now - self._since) >= after
                    if fullscreen_app_present(mine):
                        wanted = True
                    elif wanted and (now - self._woke_at) < after:
                        wanted = False
                if wanted != self.dimmed:
                    self.dimmed = wanted
                    self.on_change(wanted)
            except Exception:
                pass
