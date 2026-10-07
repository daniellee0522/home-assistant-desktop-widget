"""What is done to this program's own windows: placing, sizing, shaping, z-order, capture exclusion, DWM glass.
Everything that repositions or restyles an HWND goes through `hwnd_lock`; concurrent SetWindowPos calls against
one HWND from several threads have corrupted resize handling before."""

import ctypes
import os
import sys

from winsys import qtshell
from winsys.win32 import (
    dwmapi, DWMSBT_NONE, DWMSBT_TRANSIENTWINDOW, DWMWA_BORDER_COLOR, DWMWA_COLOR_NONE,
    DWMWA_SYSTEMBACKDROP_TYPE, DWMWA_TRANSITIONS_FORCEDISABLED, DWMWA_WINDOW_CORNER_PREFERENCE,
    DWMWCP_DONOTROUND, get_hwnd, GW_HWNDLAST, GWL_EXSTYLE, HWND_BOTTOM, hwnd_lock, HWND_NOTOPMOST,
    HWND_TOPMOST, MARGINS, MONITOR_DEFAULTTONEAREST, monitor_info, run_on_ui_thread, SW_HIDE,
    SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER, user32, WDA_EXCLUDEFROMCAPTURE, WDA_NONE,
    window_rect, WS_EX_NOACTIVATE, WS_EX_TOPMOST)


def set_window_pos_raw(hwnd, x, y, w, h, flags):
    """SetWindowPos without touching z-order. GUI thread only."""
    if not flags & SWP_NOMOVE:
        # Onto another monitor, the Qt window has to be told (see qtshell.follow_screen); the centre
        # decides, as it does for Windows.
        if flags & SWP_NOSIZE:
            rect = window_rect(hwnd)
            w, h = (rect[2] - rect[0], rect[3] - rect[1]) if rect else (0, 0)
        try:
            qtshell.follow_screen(hwnd, x + w // 2, y + h // 2)
        except Exception:
            pass
        if flags & SWP_NOSIZE:
            w = h = 0
    with hwnd_lock:
        try:
            user32.SetWindowPos(hwnd, None, x, y, w, h,
                                 flags | SWP_NOZORDER | SWP_NOACTIVATE)
        except Exception:
            pass


def set_window_rect(hwnd, x, y, w, h):
    # Position and size in one call, so a window that moves because it
    # resized never shows at the old place for a frame.
    set_window_pos_raw(hwnd, x, y, w, h, 0)


def set_window_pos(hwnd, x, y):
    set_window_pos_raw(hwnd, x, y, 0, 0, SWP_NOSIZE)


def set_window_size(hwnd, w, h):
    set_window_pos_raw(hwnd, 0, 0, w, h, SWP_NOMOVE)


# Native DWM glass is opt-in (HA_WIDGET_SYSTEM_GLASS) until its appearance
# is verified with Qt across Windows/GPU configurations. Success is tracked
# per HWND; failures fall back to the captured backdrop.
SYSTEM_GLASS_SUPPORTED = (
    sys.getwindowsversion().build >= 22621
    and bool(os.environ.get("HA_WIDGET_SYSTEM_GLASS"))
)


def set_system_glass(window, on):
    """Apply DWM glass on Qt's GUI thread; report actual API success."""
    if not SYSTEM_GLASS_SUPPORTED:
        return False

    def _apply():
        hwnd = get_hwnd(window)
        if not hwnd:
            return False
        with hwnd_lock:
            def set_backdrop(value):
                v = ctypes.c_uint(value)
                return dwmapi.DwmSetWindowAttribute(
                    hwnd, DWMWA_SYSTEMBACKDROP_TYPE, ctypes.byref(v), ctypes.sizeof(v))

            try:
                m = MARGINS(-1, -1, -1, -1) if on else MARGINS(0, 0, 0, 0)
                frame = dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(m))
                backdrop = set_backdrop(DWMSBT_TRANSIENTWINDOW if on else DWMSBT_NONE)
                if frame < 0 or backdrop < 0:
                    raise OSError("DWM glass failed: frame=%s backdrop=%s" % (frame, backdrop))
                border = ctypes.c_uint(DWMWA_COLOR_NONE)
                dwmapi.DwmSetWindowAttribute(
                    hwnd, DWMWA_BORDER_COLOR, ctypes.byref(border), ctypes.sizeof(border))
                return True
            except Exception as exc:
                qtshell.log(str(exc))
                # Undo partial activation before using the software backdrop.
                try:
                    set_backdrop(DWMSBT_NONE)
                    m = MARGINS(0, 0, 0, 0)
                    dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(m))
                except Exception:
                    pass
                return False

    return bool(window.run_on_ui_thread(_apply))


def set_capture_exclusion(window, excluded):
    """Take this window out of (or back into) screen captures.

    While excluded, reading the screen where the window is returns what is
    behind it - the cheap way to keep the backdrop live. The window is also
    missing from screenshots and recordings, which is why compatibility
    mode exists. Requires Windows 10 2004 or later.
    """
    hwnd = get_hwnd(window)
    if not hwnd:
        return False
    ok = [False]

    def _apply():
        with hwnd_lock:
            try:
                desired = WDA_EXCLUDEFROMCAPTURE if excluded else WDA_NONE
                current = ctypes.c_uint()
                if (user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(current))
                        and current.value == desired):
                    ok[0] = True
                    return
                ok[0] = bool(user32.SetWindowDisplayAffinity(
                    hwnd, desired,
                ))
            except Exception:
                ok[0] = False

    run_on_ui_thread(window, _apply)
    return ok[0]


def centre_on_window_monitor(anchor_window, hwnd_to_place):
    """Top-left that centres hwnd_to_place in anchor_window's work area."""
    try:
        anchor = get_hwnd(anchor_window) if anchor_window else None
        info = monitor_info(user32.MonitorFromWindow(
            anchor or hwnd_to_place, MONITOR_DEFAULTTONEAREST))
        if not info:
            return None
        r = window_rect(hwnd_to_place) or (0, 0, 0, 0)
        w, h = r[2] - r[0], r[3] - r[1]
        work = info.rcWork
        return (
            work[0] + max(0, (work[2] - work[0] - w) // 2),
            work[1] + max(0, (work[3] - work[1] - h) // 2),
        )
    except Exception:
        return None


def apply_window_shape(window):
    """Turn off DWM's rounding, border and show animation for a window.

    Every outline and animation here is the window's own; DWM's rounding also
    brings a shadow. Showing a window restores DWM's defaults, so this runs
    on every show (events.showing). Windows 10 ignores these attributes.
    """
    hwnd = get_hwnd(window)
    if not hwnd:
        return

    def _apply():
        with hwnd_lock:
            for attr, value in (
                    (DWMWA_TRANSITIONS_FORCEDISABLED, ctypes.c_int(1)),
                    (DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.c_int(DWMWCP_DONOTROUND)),
                    (DWMWA_BORDER_COLOR, ctypes.c_uint(DWMWA_COLOR_NONE))):
                try:
                    dwmapi.DwmSetWindowAttribute(
                        hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
                except Exception:
                    pass

    run_on_ui_thread(window, _apply)


def set_noactivate(window, enable):
    hwnd = get_hwnd(window)
    if not hwnd:
        return

    def _apply():
        with hwnd_lock:
            try:
                style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                style = (style | WS_EX_NOACTIVATE) if enable else (
                    style & ~WS_EX_NOACTIVATE)
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            except Exception:
                pass

    run_on_ui_thread(window, _apply)


def send_to_bottom(window):
    hwnd = get_hwnd(window)
    if not hwnd:
        return

    def _apply():
        with hwnd_lock:
            try:
                # GW_HWNDLAST only compares windows of the same type, so
                # a topmost window must still be demoted explicitly.
                if (not (user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)
                        and user32.GetWindow(hwnd, GW_HWNDLAST) == hwnd):
                    return
                user32.SetWindowPos(
                    hwnd, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
                )
            except Exception:
                pass

    run_on_ui_thread(window, _apply)


def bring_to_front(window, topmost=False):
    """To the front, and the window the user is working in. `topmost`: and above whatever is clicked next, as the
    system's own flyouts are, so that closing it can still be seen (the panel and the card opened from it)."""
    hwnd = get_hwnd(window)
    if not hwnd:
        return

    def _apply():
        with hwnd_lock:
            try:
                user32.SetWindowPos(hwnd, HWND_TOPMOST if topmost else HWND_NOTOPMOST, 0, 0, 0, 0,
                                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                user32.SetForegroundWindow(hwnd)
            except Exception:
                pass

    run_on_ui_thread(window, _apply)


def bottom_pin_loop(window, stop_event):
    # Normal window-manager activity can shuffle the widget up again, so
    # re-assert the bottom position at a cheap interval.
    while not stop_event.is_set():
        send_to_bottom(window)
        stop_event.wait(2.0)


def tray_point():
    """The middle of the notification area on the main taskbar, physical pixels, or None."""
    tray = user32.FindWindowW("Shell_TrayWnd", None)
    notify = user32.FindWindowExW(tray, None, "TrayNotifyWnd", None) if tray else None
    rect = window_rect(notify or tray) if (notify or tray) else None
    if not rect:
        return None
    return ((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)


def hide_own_console():
    """Hide the console window when it was created for this process alone
    (e.g. double-clicking main.py), but not a shared terminal someone is
    running from."""
    try:
        kernel32 = ctypes.windll.kernel32
        hwnd = kernel32.GetConsoleWindow()
        if not hwnd:
            return
        pids = (ctypes.c_ulong * 8)()
        count = kernel32.GetConsoleProcessList(pids, 8)
        if count == 1:
            user32.ShowWindow(ctypes.c_void_p(hwnd), SW_HIDE)
    except Exception:
        pass
