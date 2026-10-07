"""A desktop widget's window: made, pinned to the bottom of the z-order, put back where it was left."""

import threading

from nativeui import widget as native_widget
from winsys.win32 import get_hwnd, monitors, run_on_ui_thread, window_rect
from winsys.windows import apply_window_shape, bottom_pin_loop, send_to_bottom, set_noactivate, set_window_pos


def restore_widget_place(api, window):
    """Put a widget back where the user left it, once the displays have settled. Only when that place is on a
    monitor that exists now: with its monitor gone, Windows' own choice stands and the remembered place waits."""
    widget_id = next((i for i, w in api._widgets.items() if w is window), None)
    mine = api._widget_cfg(widget_id) if widget_id else None
    hwnd = get_hwnd(window)
    rect = window_rect(hwnd) if hwnd else None
    if not mine or not rect:
        return
    x, y = int(mine["x"]), int(mine["y"])
    cx, cy = x + (rect[2] - rect[0]) // 2, y + (rect[3] - rect[1]) // 2
    if not any(m["x"] <= cx < m["x"] + m["w"] and m["y"] <= cy < m["y"] + m["h"] for m in monitors()):
        return
    if (rect[0], rect[1]) != (x, y):
        set_window_pos(hwnd, x, y)


def create_widget_window(api, widget, show=False):
    """One desktop widget: its own window, pinned to the bottom of the
    z-order, bound into the api under its id."""
    widget_id = widget["id"]
    window = native_widget.create_widget(api, widget)
    api._bind_widget(widget_id, window)
    window.events.moved += lambda x, y: api._on_widget_moved(widget_id)
    stop = threading.Event()
    api._widget_pin_stops[widget_id] = stop

    def on_shown():
        api._apply_capture_exclusion()
        set_noactivate(window, True)
        mine = api._widget_cfg(widget_id)
        hwnd = get_hwnd(window)
        if mine and hwnd:
            run_on_ui_thread(
                window, lambda: set_window_pos(hwnd, int(mine["x"]), int(mine["y"])))
        send_to_bottom(window)
        # Last: DWM drops a window's backdrop when its styles change.
        api._apply_system_glass()
        threading.Thread(
            target=bottom_pin_loop, args=(window, stop), daemon=True,
        ).start()

    window.events.shown += on_shown
    window.events.showing += lambda: apply_window_shape(window)
    window.events.closing += lambda: (
        api._closing_handler() if api._closing_handler else False)
    if show:
        window.show()
    return window
