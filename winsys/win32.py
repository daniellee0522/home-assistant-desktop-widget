"""The Win32 calls this program makes: the DLLs with their argument types, the constants and structures, and the small
questions (a window's rectangle, the monitors, which window has the foreground) that everything else asks. Private
DLL handles rather than ctypes.windll, so the argument types declared here cannot change calls other libraries make
through the shared ones. HWNDs are pointer-sized; undeclared, ctypes would truncate them."""

import ctypes
import threading


GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x2
SW_HIDE = 0
HWND_BOTTOM = 1
HWND_TOP = 0
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
GW_HWNDLAST = 1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010


# Serialises every native call that repositions or restyles one of our
# windows. Concurrent SetWindowPos calls against the same HWND from several
# threads have corrupted the web view's resize handling before.
hwnd_lock = threading.Lock()


# Private WinDLL instances rather than ctypes.windll, so the argtypes
# declared here cannot change calls other libraries make through the shared
# handles. HWNDs are pointer-sized; undeclared, ctypes would truncate them.
user32 = ctypes.WinDLL("user32")
dwmapi = ctypes.WinDLL("dwmapi")

user32.SetWindowPos.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, ctypes.c_uint,
]
user32.SetWindowPos.restype = ctypes.c_int
user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.GetWindow.restype = ctypes.c_void_p
user32.SetWindowLongW.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long
user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
user32.GetDC.argtypes = [ctypes.c_void_p]
user32.GetDC.restype = ctypes.c_void_p
user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
user32.FindWindowW.restype = ctypes.c_void_p
user32.FindWindowExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
user32.FindWindowExW.restype = ctypes.c_void_p
user32.PrintWindow.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]

gdi32 = ctypes.WinDLL("gdi32")
gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
gdi32.CreateCompatibleBitmap.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32.SelectObject.restype = ctypes.c_void_p
gdi32.BitBlt.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
]
gdi32.GetDIBits.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
]
gdi32.PatBlt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                          ctypes.c_int, ctypes.c_int, ctypes.c_uint]
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
user32.EnumChildWindows.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
user32.EnumWindows.argtypes = [ctypes.c_void_p, ctypes.c_ssize_t]
user32.IsIconic.argtypes = [ctypes.c_void_p]
user32.GetLayeredWindowAttributes.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
user32.GetClassNameW.argtypes = [
    ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.MonitorFromWindow.restype = ctypes.c_void_p
user32.MonitorFromPoint.restype = ctypes.c_void_p
user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.SetWindowDisplayAffinity.restype = ctypes.c_int
user32.GetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]
user32.GetWindowDisplayAffinity.restype = ctypes.c_int
user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.GetAncestor.restype = ctypes.c_void_p
user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.GetCursorPos.argtypes = [ctypes.c_void_p]
dwmapi.DwmSetWindowAttribute.argtypes = [
    ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint,
]
dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
dwmapi.DwmGetWindowAttribute.argtypes = [
    ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint,
]
dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
dwmapi.DwmExtendFrameIntoClientArea.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p]
dwmapi.DwmExtendFrameIntoClientArea.restype = ctypes.c_long


class MARGINS(ctypes.Structure):
    _fields_ = [
        ("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
        ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int),
    ]


ENUM_WINDOWS_PROC = ctypes.WINFUNCTYPE(
    ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011
PW_RENDERFULLCONTENT = 0x00000002
SRCCOPY = 0x00CC0020
BLACKNESS = 0x00000042
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


DWMWA_TRANSITIONS_FORCEDISABLED = 3
DWMWA_CLOAKED = 14
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMWCP_DONOTROUND = 1
DWMWA_COLOR_NONE = 0xFFFFFFFE
DWMSBT_NONE = 1
DWMSBT_TRANSIENTWINDOW = 3          # acrylic: a blur of whatever is behind


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("rcMonitor", ctypes.c_long * 4),
        ("rcWork", ctypes.c_long * 4),
        ("dwFlags", ctypes.c_uint32),
    ]


MONITOR_DEFAULTTONEAREST = 2


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


# These take a POINT by value, so they are declared after the struct.
user32.MonitorFromPoint.argtypes = [POINT, ctypes.c_uint]
user32.WindowFromPoint.argtypes = [POINT]
user32.WindowFromPoint.restype = ctypes.c_void_p


GA_ROOT = 2


MONITORENUMPROC = ctypes.WINFUNCTYPE(
    ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
user32.EnumDisplayMonitors.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, MONITORENUMPROC, ctypes.c_void_p]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetDpiForWindow.argtypes = [ctypes.c_void_p]
VK_LBUTTON = 0x01


def get_hwnd(window):
    try:
        return window.hwnd()
    except Exception:
        return None


def run_on_ui_thread(window, fn):
    """Run fn on the thread that owns this window, and wait for it."""
    try:
        return window.run_on_ui_thread(fn)
    except Exception:
        return fn()


def window_rect(hwnd):
    """(left, top, right, bottom) of a window, or None."""
    try:
        r = (ctypes.c_long * 4)()
        if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
        return (r[0], r[1], r[2], r[3])
    except Exception:
        return None


def covers(rect, x, y, w, h):
    return rect[0] <= x and rect[1] <= y and rect[2] >= x + w and rect[3] >= y + h


def class_name(hwnd, size=64):
    buf = ctypes.create_unicode_buffer(size)
    user32.GetClassNameW(hwnd, buf, size)
    return buf.value


def rects_overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def visible_rect(window, even_if_hidden=False):
    """This window's screen rectangle, or None if it is not on screen."""
    hwnd = get_hwnd(window) if window else None
    if not hwnd or (not even_if_hidden and not user32.IsWindowVisible(hwnd)):
        return None
    return window_rect(hwnd)


def monitor_info(mon):
    if not mon:
        return None
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(mon, ctypes.byref(info)):
        return None
    return info


def monitors():
    """Every monitor as {x, y, w, h, work: (l, t, r, b)}, physical pixels."""
    found = []

    def visit(hmon, hdc, rect, lparam):
        info = monitor_info(hmon)
        if info:
            m, wk = info.rcMonitor, info.rcWork
            found.append({"x": m[0], "y": m[1], "w": m[2] - m[0], "h": m[3] - m[1],
                          "work": (wk[0], wk[1], wk[2], wk[3])})
        return 1

    try:
        user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(visit), None)
    except Exception:
        pass
    return found


def dpi_scale(hwnd):
    try:
        return max(1.0, user32.GetDpiForWindow(hwnd) / 96.0)
    except Exception:
        return 1.0


def work_area_at(x, y):
    """The usable screen rectangle around a point, as (l, t, r, b)."""
    try:
        info = monitor_info(user32.MonitorFromPoint(
            POINT(int(x), int(y)), MONITOR_DEFAULTTONEAREST))
        if not info:
            return None
        w = info.rcWork
        return (w[0], w[1], w[2], w[3])
    except Exception:
        return None


def foreground_root():
    """The top-level window that has the foreground, or None."""
    fg = user32.GetForegroundWindow()
    if not fg:
        return None
    return user32.GetAncestor(fg, GA_ROOT) or fg
