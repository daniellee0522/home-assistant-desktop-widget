"""The windows the program holds: the desktop widgets, the card, the panel and Settings; making and releasing
them, telling them things, and sizing them as they ask."""

import json
import threading

from app.startup import MIN_WINDOW_H, MIN_WINDOW_W
from nativeui import detail as native_detail, panel as native_panel
from winsys.win32 import get_hwnd, run_on_ui_thread
from winsys.windows import apply_window_shape, set_noactivate, set_window_pos, set_window_rect, set_window_size


class WindowsMixin:
    def _init_windows(self):
        # The desktop widgets: id -> window, in creation order. The first is also bound as _window, "main" to
        # the older code paths.
        self._window = None
        self._widgets = {}
        self._widget_pin_stops = {}
        # Called when a widget window is closed: hides everything to the tray.
        self._closing_handler = None
        # Whether the widget is currently shown on the desktop.
        self._desktop_visible = True
        # The tray panel and the detail card are made when first wanted and released after a while unused.
        self._overlay_lock = threading.Lock()
        self._fresh = set()           # overlays made just now, which have not yet drawn
        self._release_timers = {}

    @staticmethod
    def _widget_kind(widget_id):
        return "w:" + widget_id

    def _widget_kinds(self):
        return ["w:" + wid for wid in self._widgets]

    def _widget_id_of(self, kind):
        if kind and kind.startswith("w:"):
            return kind[2:]
        if kind == "main":
            return next(iter(self._widgets), None)
        return None

    def _bind_widget(self, widget_id, window):
        self._widgets[widget_id] = window
        if self._window is None:
            self._window = window

    # How long the panel or the card may stay unused before it is
    # released; the next use makes it again (a few tenths of a second).
    _OVERLAY_RELEASE_S = 120

    def _ensure_overlay(self, kind):
        """The popover or flyout window, made if it is not there."""
        with self._overlay_lock:
            self._cancel_release(kind)
            window = self._popover_window if kind == "popover" else self._flyout_window
            if window:
                return window
            self._fresh.add(kind)
            first = (self._cfg.get("widgets") or [{}])[0]
            if kind == "popover":
                # It numbers its resizes from 1 again.
                self._popover_last_resize_seq = -1
                window = native_detail.create_popover(
                    self, x=first.get("x", 200), y=first.get("y", 200))
                window.events.showing += lambda: apply_window_shape(window)
                window.events.shown += lambda: (
                    self._apply_capture_exclusion(), set_noactivate(window, True),
                    self._apply_system_glass())
                window.events.deactivated += lambda: threading.Thread(
                    target=self._close_detail_page, args=(window,), daemon=True).start()
                self._bind_popover_window(window)
            else:
                self._flyout_last_resize_seq = -1
                window = native_panel.create_panel(self)
                window.events.showing += lambda: apply_window_shape(window)
                window.events.shown += self._apply_capture_exclusion
                window.events.deactivated += lambda: threading.Thread(
                    target=self.dismiss_flyout, daemon=True).start()
                self._bind_flyout_window(window)
        return window

    @staticmethod
    def _close_detail_page(window):
        # Clicking anywhere else closes the card.
        window.send("close_card")

    def _cancel_release(self, kind):
        timer = self._release_timers.pop(kind, None)
        if timer:
            timer.cancel()

    def _schedule_release(self, kind):
        self._cancel_release(kind)
        timer = threading.Timer(self._OVERLAY_RELEASE_S, self._release_overlay, (kind,))
        timer.daemon = True
        self._release_timers[kind] = timer
        timer.start()

    def _release_overlay(self, kind):
        if (self._flyout_open if kind == "flyout" else "popover" in self._overlays_open):
            return
        with self._overlay_lock:
            window = self._popover_window if kind == "popover" else self._flyout_window
            if kind == "popover":
                self._popover_window = None
            else:
                self._flyout_window = None
            self._fresh.discard(kind)
        if window:
            try:
                window.dispose()
            except Exception:
                pass
            self._apply_capture_exclusion()

    def _bind_popover_window(self, window):
        self._popover_window = window

    def _bind_settings_window(self, window):
        self._settings_window = window

    def _bind_flyout_window(self, window):
        self._flyout_window = window

    def _window_for(self, kind):
        if kind and kind.startswith("w:"):
            return self._widgets.get(kind[2:])
        return {
            "popover": self._popover_window,
            "settings": self._settings_window,
            "flyout": self._flyout_window,
        }.get(kind, self._window if kind in (None, "main") else None)

    def _all_windows(self):
        widgets = list(self._widgets.values()) or ([self._window] if self._window else [])
        return [w for w in (*widgets, self._popover_window,
                            self._flyout_window, self._settings_window) if w]

    def _own_hwnds(self):
        windows = {h for h in (get_hwnd(w) for w in self._all_windows()) if h}
        from nativeui.widget_glass import hwnds
        windows.update(hwnds())
        # The compositor helper is our visible flyout while its native window
        # is transparent. It must not be mistaken for another app covering it.
        from nativeui import dcomp
        helper = dcomp._state["slider"]
        if helper is not None and helper.shown and helper.hwnd:
            windows.add(helper.hwnd)
        return windows

    def _own_hwnds_out_of_capture(self):
        """Our windows that a capture of the screen does not show (the widgets and their glass, the panel's compositor): these
        are not in a widget's picture of the desktop, so they are not taken out of it. Settings is left out of this set: it is
        drawn on the screen like any program's window, and over a widget it must not be in the widget's glass."""
        windows = self._own_hwnds()
        windows.discard(get_hwnd(self._settings_window) if self._settings_window else None)
        return windows

    def _broadcast(self, name, *args, windows=None):
        """Call `name` with `args` on every window (or on those given) that has it, without
        waiting. Each window is given its own copy of the arguments, so none can change what
        another holds, or the config they were read from."""
        text = json.dumps(args, ensure_ascii=False, separators=(",", ":"))
        for window in (self._all_windows() if windows is None else windows):
            if not window:
                continue
            try:
                window.send(name, *json.loads(text))
            except Exception:
                pass

    def resize_popover_window(self, phys_w, phys_h, seq=None, origin=None):
        # Where the popover goes depends on its size, so it is placed and
        # sized in one call and never shows at the old place for a frame.
        self._resize_native(
            self._popover_window, self._popover_resize_lock, "_popover_last_resize_seq",
            phys_w, phys_h, seq, origin=(lambda w, h: origin) if origin is not None else self._popover_origin,
        )

    def resize_flyout_window(self, phys_w, phys_h, seq=None):
        # Anchored to a screen corner, so growing it moves it as well.
        self._resize_native(
            self._flyout_window, self._flyout_resize_lock, "_flyout_last_resize_seq",
            phys_w, phys_h, seq, origin=self._flyout_origin,
            on_applied=lambda w, h: setattr(self, "_flyout_size", (w, h)),
        )

    def resize_settings_window(self, phys_w, phys_h, seq=None):
        self._resize_native(
            self._settings_window, self._settings_resize_lock, "_settings_last_resize_seq",
            phys_w, phys_h, seq,
        )

    def _resize_native(self, window, seq_lock, seq_attr, phys_w, phys_h, seq,
                       origin=None, on_applied=None):
        if not window:
            return
        if seq is not None:
            with seq_lock:
                if seq <= getattr(self, seq_attr):
                    # A newer resize already landed; applying this older,
                    # likely smaller size would clip content on screen.
                    return
                setattr(self, seq_attr, seq)
        hwnd = get_hwnd(window)
        if not hwnd:
            return
        w = max(MIN_WINDOW_W, int(phys_w))
        h = max(MIN_WINDOW_H, int(phys_h))

        def apply():
            # Request threads may queue UI work out of order; recheck on
            # the owning thread.
            if seq is not None and seq != getattr(self, seq_attr):
                return
            hwnd = get_hwnd(window)
            if not hwnd:
                return
            at = origin(w, h) if origin else None
            if at:
                set_window_rect(hwnd, at[0], at[1], w, h)
            else:
                set_window_size(hwnd, w, h)
            if on_applied:
                on_applied(w, h)
        run_on_ui_thread(window, apply)

    def move_window(self, screen_x, screen_y, window_kind="main"):
        # Physical screen pixels, from a widget being dragged.
        window = self._window_for(window_kind)
        if not window:
            return
        hwnd = get_hwnd(window)
        if not hwnd:
            return
        widget_id = self._widget_id_of(window_kind)
        if widget_id:
            screen_x, screen_y = self._snap_widget(
                widget_id, int(screen_x), int(screen_y))
        run_on_ui_thread(
            window, lambda: set_window_pos(
                hwnd, int(screen_x), int(screen_y)),
        )
