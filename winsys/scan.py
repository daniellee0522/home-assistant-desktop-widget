"""Looking at the desktop's windows: which ones lie over a rectangle, whether the desktop or an app has the user's
attention, whether a full-screen app is in front."""

import ctypes

from winsys.win32 import (
    class_name, dwmapi, DWMWA_CLOAKED, ENUM_WINDOWS_PROC, foreground_root, GA_ROOT, GWL_EXSTYLE, LWA_ALPHA,
    MONITOR_DEFAULTTONEAREST, monitor_info, POINT, rects_overlap, user32, window_rect, WS_EX_LAYERED)


DESKTOP_CLASSES = {"Progman", "WorkerW"}
SHELL_CLASSES = DESKTOP_CLASSES | {
    "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Windows.UI.Core.CoreWindow",
    "TopLevelWindowForOverflowXamlIsland", "XamlExplorerHostIslandWindow",
    "NotifyIconOverflowWindow"}


# A window's shadow reaches past its rectangle (most of it lies in the invisible resize border already).
SHADOW_PX = 12


def windows_below(target, rect):
    """Visible top-level windows below `target` that intersect `rect`, in
    paint order (bottom first)."""
    found = []
    below = False

    def visit(hwnd, _):
        nonlocal below
        if hwnd == target:
            below = True
            return 1
        if not below or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return 1
        if class_name(hwnd, 128) in ("Progman", "WorkerW"):
            return 1
        cloaked = ctypes.c_uint()
        if (dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked),
                                          ctypes.sizeof(cloaked)) == 0 and cloaked.value):
            return 1
        bounds = window_rect(hwnd)
        if bounds and rects_overlap(rect, bounds):
            found.append(hwnd)
        return 1

    user32.EnumWindows(ENUM_WINDOWS_PROC(visit), 0)
    return tuple(reversed(found))


def window_snapshot():
    """Every top-level window in z-order, top first, as (hwnd, rect): the rectangle (with room for its
    shadow) of those that can be seen, None for the rest. One pass serves every widget of a frame."""
    found = []

    def visit(hwnd, _):
        rect = None
        if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            invisible = False
            if style & WS_EX_LAYERED:
                alpha, flags = ctypes.c_ubyte(255), ctypes.c_uint(0)
                invisible = bool(user32.GetLayeredWindowAttributes(
                    hwnd, None, ctypes.byref(alpha), ctypes.byref(flags))
                    and flags.value & LWA_ALPHA and alpha.value == 0)
            cloaked = ctypes.c_uint()
            if not invisible and not (dwmapi.DwmGetWindowAttribute(
                    hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0
                    and cloaked.value):
                r = window_rect(hwnd)
                if r and r[2] > r[0] and r[3] > r[1]:
                    rect = (r[0] - SHADOW_PX, r[1] - SHADOW_PX, r[2] + SHADOW_PX, r[3] + SHADOW_PX)
        found.append((hwnd, rect))
        return 1

    user32.EnumWindows(ENUM_WINDOWS_PROC(visit), 0)
    return found


def windows_over(target, rect, ours, snapshot=None):
    """Rectangles, as (l, t, r, b) on screen, of the windows not ours that sit above `target` and cross
    `rect`: what a capture of the screen there shows instead of the desktop. Windows that can't be seen
    (hidden, minimised, cloaked or fully transparent) are left out. A click-through window may still
    be visible in capture; WS_EX_TRANSPARENT controls input/paint order, not its opacity."""
    if snapshot is not None:
        found = []
        for hwnd, r in snapshot:
            if hwnd == target:
                break                             # the rest are below it
            if r is not None and hwnd not in ours and rects_overlap(rect, r):
                found.append(r)
        return found
    found = []

    def visit(hwnd, _):
        if hwnd == target:
            return 0                              # the rest are below it
        if hwnd in ours or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return 1
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if style & WS_EX_LAYERED:
            alpha, flags = ctypes.c_ubyte(255), ctypes.c_uint(0)
            if (user32.GetLayeredWindowAttributes(hwnd, None, ctypes.byref(alpha), ctypes.byref(flags))
                    and flags.value & LWA_ALPHA and alpha.value == 0):
                return 1
        cloaked = ctypes.c_uint()
        if (dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked),
                                          ctypes.sizeof(cloaked)) == 0 and cloaked.value):
            return 1
        r = window_rect(hwnd)
        if r and r[2] > r[0] and r[3] > r[1]:
            r = (r[0] - SHADOW_PX, r[1] - SHADOW_PX, r[2] + SHADOW_PX, r[3] + SHADOW_PX)
            if rects_overlap(rect, r):
                found.append(r)
        return 1

    try:
        user32.EnumWindows(ENUM_WINDOWS_PROC(visit), 0)
    except Exception:
        return []
    return found


def desktop_is_front(main=0, ours=()):
    """Whether the desktop has the user's attention: True when the desktop
    or one of the widgets (`main`: an HWND or a set of them) is in front,
    False when some other app is, and None when the foreground is only
    passing through (taskbar, Start menu, our own panel) and says nothing
    either way."""
    try:
        root = foreground_root()
        widgets = main if isinstance(main, (set, frozenset, tuple, list)) else (main,)
        if not root or root in widgets:
            return True
        if root in ours:
            return None
        name = class_name(root)
        if name in DESKTOP_CLASSES:
            return True
        return None if name in SHELL_CLASSES else False
    except Exception:
        return True


def fullscreen_app_present(ours=()):
    """True when the foreground window covers its whole monitor."""
    try:
        root = foreground_root()
        if not root or root in ours or class_name(root) in SHELL_CLASSES:
            return False
        r = window_rect(root)
        info = monitor_info(
            user32.MonitorFromWindow(root, MONITOR_DEFAULTTONEAREST)) if r else None
        if not info:
            return False
        m = info.rcMonitor
        return (r[0] <= m[0] and r[1] <= m[1] and r[2] >= m[2] and r[3] >= m[3])
    except Exception:
        return False


def nothing_visible_of(hwnd, ours):
    """True when every sampled point of this window is covered by some
    window other than ours. The widget sits at the bottom of the z-order,
    so it is usually covered, and a covered frame need not be captured."""
    try:
        r = window_rect(hwnd)
        if not r:
            return False
        w, h = r[2] - r[0], r[3] - r[1]
        if w <= 0 or h <= 0:
            return False
        for fy in (0.08, 0.35, 0.65, 0.92):
            for fx in (0.04, 0.3, 0.55, 0.8, 0.96):
                pt = POINT(int(r[0] + w * fx), int(r[1] + h * fy))
                top = user32.WindowFromPoint(pt)
                if not top:
                    continue
                root = user32.GetAncestor(top, GA_ROOT) or top
                if root in ours:
                    return False
        return True
    except Exception:
        return False
