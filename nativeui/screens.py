"""The monitors, as the windows need to know them: where one is, how much of it is usable, its DPI.

Physical pixels throughout (the program is per-monitor DPI aware; see main.py).
"""
import ctypes
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32")
_user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
_user32.MonitorFromPoint.restype = ctypes.c_void_p
_user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_user32.GetMonitorInfoW.restype = wintypes.BOOL
try:
    _shcore = ctypes.WinDLL("shcore")
    _shcore.GetDpiForMonitor.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_uint),
                                         ctypes.POINTER(ctypes.c_uint)]
    _shcore.GetDpiForMonitor.restype = ctypes.c_long
except OSError:                                    # before Windows 8.1
    _shcore = None

MONITOR_DEFAULTTONEAREST = 2
MDT_EFFECTIVE_DPI = 0


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


class Monitor:
    """rect and work as (left, top, right, bottom); scale is the DPI over 96."""

    def __init__(self, rect, work, scale):
        self.rect, self.work, self.scale = rect, work, scale

    def logical_short_side(self):
        """The monitor's shorter side in the logical pixels everything on it is laid out in."""
        l, t, r, b = self.rect
        return min(r - l, b - t) / self.scale


def monitor_at(x, y):
    """The monitor at (or nearest to) a point, or None."""
    try:
        mon = _user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), MONITOR_DEFAULTTONEAREST)
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not mon or not _user32.GetMonitorInfoW(mon, ctypes.byref(info)):
            return None
        scale = 1.0
        if _shcore is not None:
            dx, dy = ctypes.c_uint(96), ctypes.c_uint(96)
            if _shcore.GetDpiForMonitor(mon, MDT_EFFECTIVE_DPI, ctypes.byref(dx), ctypes.byref(dy)) >= 0:
                scale = (dx.value / 96.0) or 1.0
        m, w = info.rcMonitor, info.rcWork
        return Monitor((m.left, m.top, m.right, m.bottom), (w.left, w.top, w.right, w.bottom), scale)
    except Exception:
        return None
