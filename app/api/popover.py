"""The detail card over a tile, and the Settings window: opened, placed, closed."""

import threading

from app.geometry import place_against
from app.startup import MIN_WINDOW_H, MIN_WINDOW_W
from nativeui import settings as native_settings
from winsys.win32 import dwmapi, get_hwnd, run_on_ui_thread, work_area_at
from winsys.windows import (
    apply_window_shape, bring_to_front, centre_on_window_monitor, set_noactivate, set_window_pos)


class PopoverMixin:
    def _init_popover(self):
        self._popover_window = None
        self._popover_owner = None
        self._popover_resize_lock = threading.Lock()
        self._popover_open_lock = threading.RLock()
        self._popover_generation = 0
        # The tile the popover belongs to (x, y, w, h in physical pixels) and the last real size it took; see
        # _popover_origin.
        self._popover_anchor = None
        self._popover_size = None
        self._popover_last_resize_seq = -1
        self._settings_window = None
        self._settings_lock = threading.Lock()
        self._settings_resize_lock = threading.Lock()
        self._settings_last_resize_seq = -1

    def _popover_origin(self, w, h):
        """Where a w*h popover goes for the tile that opened it, or None if
        there is nothing open to place."""
        anchor = self._popover_anchor
        if not anchor:
            return None
        x, y, tw, th = anchor
        work = work_area_at(x, y)
        if not work or w <= 0 or h <= 0:
            return None
        # Remembered for the next open, which needs a size before the card
        # reports one. The collapsed minimum is the closing animation's.
        if w > MIN_WINDOW_W and h > MIN_WINDOW_H:
            self._popover_size = (w, h)
        return (
            place_against(x, w, x, tw or w, work[0], work[2]),
            place_against(y, h, y, th or h, work[1], work[3]),
        )

    def open_popover(self, tile_id, screen_x, screen_y, tile_w=0, tile_h=0,
                     owner_kind=None, source_image=None):
        with self._popover_open_lock:
            self._popover_generation += 1
            return self._open_popover(tile_id, screen_x, screen_y, tile_w, tile_h, owner_kind, source_image)

    def _open_popover(self, tile_id, screen_x, screen_y, tile_w=0, tile_h=0,
                      owner_kind=None, source_image=None):
        """Show the detail card over a tile. Coordinates are physical.
        `owner_kind` is the window the tile is in."""
        if not self._ensure_overlay("popover"):
            return
        self._popover_owner = owner_kind
        owner_window = self._window_for(owner_kind)
        if source_image is not None and owner_window is not None:
            run_on_ui_thread(owner_window, lambda: owner_window.native.prepare_transition(tile_id))
        # The card takes the theme of the window it opens from (the panel has
        # its own).
        self._popover_window.send("set_owner", owner_kind)
        if tile_id.startswith("home:"):
            state = self._home_states.get(tile_id[5:])
            if state:
                self._broadcast("push_states", [[tile_id[5:], state]], windows=(self._popover_window,))
        self._popover_anchor = (int(screen_x), int(screen_y), int(tile_w), int(tile_h))
        hwnd = get_hwnd(self._popover_window)
        if hwnd:
            # Anchored at the tile's top-left, flipping at screen edges.
            # The window is still collapsed from its last close, so place it
            # with the last known size; resize_popover_window corrects it
            # once the card reports the real one.
            run_on_ui_thread(
                self._popover_window,
                lambda: set_window_pos(hwnd, int(screen_x), int(screen_y)),
            )
        # The widget keeps its capture source. Its offscreen image is composed
        # into the popover backdrop without the tile being lifted.
        self._overlays_open.add("popover")
        self._arming_kind = "popover"
        self._apply_capture_exclusion()
        # Render the card, let it settle its size and place, and take the
        # backdrop there - all while the window is still hidden.
        def prepare():
            scene = self._popover_window.native
            scene.source_surface = owner_window.native if owner_window and hasattr(owner_window.native,"set_transition_cover") else None
            source_dpi = getattr(owner_window.native, "dpi", None) if owner_window else None
            scene.set_transition_source(self._popover_anchor, source_image, tile_id, self._popover_generation,
                                        source_dpi=source_dpi, source_work=work_area_at(screen_x, screen_y))
            scene.open_tile(tile_id)
        run_on_ui_thread(self._popover_window, prepare)
        self._capture_epoch += 1
        self._duplication_after.pop("popover", None)
        self._arm_backdrop("popover", self._popover_window)
        try:
            def show_morph():
                scene = self._popover_window.native
                scene.sync_source_cover()
                if source_image is not None and owner_window is not None:
                    owner_window.native.set_transition_tile(tile_id)
                scene.show()
                scene.enter()
            run_on_ui_thread(self._popover_window, show_morph)
        except Exception:
            pass
        self._apply_capture_exclusion()
        bring_to_front(self._popover_window, topmost=self._flyout_open)
        self._apply_system_glass("popover")

    def _ensure_settings_window(self):
        """Settings is seldom open, so it is made when asked for and released
        when closed."""
        with self._settings_lock:
            if self._settings_window:
                return self._settings_window
            # It numbers its resizes from 1 again.
            self._settings_last_resize_seq = -1
            window = native_settings.create_settings(self)
            window.events.showing += lambda: apply_window_shape(window)
            window.events.shown += self._apply_capture_exclusion
            self._bind_settings_window(window)
            return window

    def open_settings_window(self):
        """Bring up Settings, centred on the widget's monitor."""
        try:
            self._ensure_settings_window()
        except Exception:
            return
        hwnd = get_hwnd(self._settings_window)
        if hwnd:
            pos = centre_on_window_monitor(self._window, hwnd)
            if pos:
                run_on_ui_thread(
                    self._settings_window, lambda: set_window_pos(
                        hwnd, pos[0], pos[1]),
                )
        self._overlays_open.add("settings")
        self._apply_capture_exclusion()
        try:
            self._settings_window.show()
        except Exception:
            pass
        bring_to_front(self._settings_window)
        self._settings_window.send("enter_settings")

    def close_settings_window(self):
        window, self._settings_window = self._settings_window, None
        self._overlays_open.discard("settings")
        if window:
            try:
                window.hide()
                window.dispose()
            except Exception:
                pass
        self._apply_capture_exclusion()

    def close_popover(self, expected_generation=None):
        with self._popover_open_lock:
            if expected_generation is not None and expected_generation != self._popover_generation:
                return False
            return self._close_popover()

    def _close_popover(self):
        owner = self._window_for(self._popover_owner)
        def handoff():
            restore = getattr(owner.native,"set_transition_tile",None) if owner else None
            if restore is not None:
                restore(None)
            if self._popover_window:
                self._popover_window.native.hide()
        if self._popover_window:
            try:
                run_on_ui_thread(self._popover_window,handoff)
                dwmapi.DwmFlush()
            except Exception:
                pass
            self._schedule_release("popover")
        # Placement of a closed card cannot keep referring to its source tile.
        self._popover_anchor = None
        self._overlays_open.discard("popover")
        self._apply_capture_exclusion()

    def get_popover_source_image(self, tile_id):
        owner = self._window_for(self._popover_owner)
        snapshot = getattr(owner.native, "transition_image", None) if owner else None
        return run_on_ui_thread(owner, lambda: snapshot(tile_id)) if snapshot else None

    def set_popover_activatable(self, enabled):
        if self._popover_window:
            set_noactivate(self._popover_window, not enabled)
            if enabled:
                bring_to_front(self._popover_window, topmost=self._flyout_open)
        return True
