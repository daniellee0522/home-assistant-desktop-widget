"""What the desktop widget's surface and its mixins share (widget.py): the Win32 calls it makes, its timings and distances,\nand the signal its tiles redraw by."""
import ctypes
from ctypes import wintypes

from PySide6.QtCore import Signal, QObject


from . import render


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetDpiForWindow.argtypes = [ctypes.c_void_p]
_user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
_user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
_user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_uint]

HOLD_MS = 420                 # how long a press is held to open the detail card
# How often what a widget of another kind shows besides states is fetched again (seconds).
EXTRAS_EVERY = {"weather": 1200, "camera": 10, "chart": 300, "media": 3}
# the kinds whose detail a tap opens (a player has its controls on itself)
# The pace of a clock's ring while its hand moves (kinds.HAND_MOVE_S at the start of each second).
SECOND_FRAME_MS = 33
DETAIL_KINDS = ("weather", "camera", "chart")
HOLD_SLOP_PX = 8              # moving further than this cancels the hold
DRAG_PX = 5                   # moving further than this drags the widget
SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x2, 0x4, 0x10
WHEEL_STEP = 100              # CSS px a notch of the wheel scrolls
EASE_DIM_MS, EASE_WAKE_MS = 700, 260


class _Signals(QObject):
    states = Signal()                     # tiles changed: draw them again


def _cursor():
    pt = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def _rect(hwnd):
    r = wintypes.RECT()
    if hwnd and _user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return r.left, r.top, r.right, r.bottom
    return None


def has_hold(domain):
    """A press held on it opens the detail card: the devices with controls, and the read-only ones."""
    return render.has_detail_on_hold(domain) or render.is_readonly(domain)
