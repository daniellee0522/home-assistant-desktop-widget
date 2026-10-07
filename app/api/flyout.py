"""The tray panel's coming and going: toggling, placing at the tray corner, closing when focus leaves."""

import ctypes
import threading
import time
import traceback

from winsys import qtshell
from winsys.win32 import foreground_root, get_hwnd, POINT, run_on_ui_thread, user32, window_rect, work_area_at
from winsys.windows import bring_to_front, set_window_rect, tray_point


class FlyoutMixin:
    def _init_flyout(self):
        self._flyout_window = None
        self._flyout_resize_lock = threading.Lock()
        self._flyout_last_resize_seq = -1
        self._flyout_open = False
        self._flyout_serial = 0
        self._flyout_toggle_lock = threading.Lock()
        self._flyout_toggle_thread = None
        self._flyout_toggle_running = False
        self._flyout_toggle_target = False
        self._flyout_toggle_from_key = False
        self._flyout_toggle_revision = 0
        # (work area, notification area is on the right), fixed at open: the pointer is only over the tray icon
        # at the moment of the click.
        self._flyout_anchor = None
        # The size the panel last asked for. A hidden window's own rectangle may not have caught up with it yet.
        self._flyout_size = None
        # Activation churns while a window is being shown; a Deactivate in that moment is not the user clicking
        # away.
        self._flyout_shown_at = 0.0
        self._flyout_dismissed_at = -1e9         # (when the panel last closed itself for lost focus)

    _FLYOUT_MARGIN = 12         # what Windows leaves around its own flyouts

    def backdrop_armed(self):
        """Called by a window once the backdrop it was asked to take is
        painted - see _arm_backdrop."""
        self._armed.set()
        return True

    def _arm_backdrop(self, kind, window, timeout=0.3, settle=True):
        """Have a hidden, already-positioned window capture the backdrop of
        where it is about to appear, so it does not open showing a frosted
        picture of wherever it was last time."""
        self._arming_kind = kind
        self._armed.clear()
        window.send("arm")
        # The timeout only guards against a window that never answers.
        self._armed.wait(timeout)
        # A moment for the compositor to put that frame on the surface.
        if settle:
            time.sleep(0.04)
        self._arming_kind = None

    # A click on the tray icon is two events: the press takes the focus from the panel (which closes it), the release
    # is the icon's own toggle. The release, within this long of the panel having closed itself, is the same click.
    _SAME_CLICK_S = 0.4

    def toggle_flyout(self, from_key=False):
        # Only intent changes under this lock. No GUI waits or captures hold it.
        with self._flyout_toggle_lock:
            current = self._flyout_toggle_target if self._flyout_toggle_running else self._flyout_open
            if (not current and not from_key
                    and time.monotonic() - self._flyout_dismissed_at <= self._SAME_CLICK_S):
                self._flyout_dismissed_at = -1e9
                return
            self._flyout_toggle_target = not current
            self._flyout_toggle_from_key = from_key
            self._flyout_toggle_revision += 1
            if self._flyout_toggle_running:
                return
            self._flyout_toggle_running = True
            worker = threading.Thread(target=self._drive_flyout_toggles, daemon=True)
            self._flyout_toggle_thread = worker
        worker.start()

    def _drive_flyout_toggles(self):
        while True:
            with self._flyout_toggle_lock:
                revision = self._flyout_toggle_revision
                target = self._flyout_toggle_target
                from_key = self._flyout_toggle_from_key
            try:
                if target:
                    self.show_flyout(from_key)
                else:
                    self.hide_flyout()
            except Exception:
                qtshell.log(traceback.format_exc())
            with self._flyout_toggle_lock:
                if revision == self._flyout_toggle_revision:
                    self._flyout_toggle_running = False
                    return

    def _place_flyout(self, window, hwnd, size):
        at = self._flyout_origin(size[0], size[1])
        if at:
            run_on_ui_thread(
                window, lambda: set_window_rect(
                    get_hwnd(window), at[0], at[1], size[0], size[1]),
            )

    def show_flyout(self, from_key=False):
        """`from_key`: opened by the shortcut, so the pointer says nothing about where the tray is."""
        if not self._all_tiles() and not self._home_mode():
            self.open_settings_window()
            return
        self._flyout_serial += 1
        serial = self._flyout_serial
        self._flyout_open = True
        window = self._ensure_overlay("flyout")
        if serial != self._flyout_serial or not self._flyout_open:
            return
        resuming = window.prepare_for_show() is True if window else False
        hwnd = get_hwnd(window) if window else None
        if not hwnd:
            self._flyout_open = False
            return
        if serial != self._flyout_serial or not self._flyout_open:
            return
        self._sync_client_entities()
        self._flyout_anchor = self._tray_corner(tray_point() if from_key else None)
        size = self._flyout_size
        if not size:
            rect = window_rect(hwnd) or (0, 0, 0, 0)
            size = (rect[2] - rect[0], rect[3] - rect[1])
        self._place_flyout(window, hwnd, size)
        # It sits over whatever is on screen, so the widget below has to stay
        # capturable to appear in its backdrop.
        self._overlays_open.add("flyout")
        self._arming_kind = "flyout"
        self._apply_capture_exclusion()
        cold = "flyout" in self._fresh
        if cold:
            # A panel just made has drawn nothing and does not know its size yet; shown now it
            # would open blank and then jump. Let it size itself, fetch its data and take its
            # backdrop while it is still hidden, as the detail card does.
            self._fresh.discard("flyout")
            # A hidden window does not draw, so it is shown, at no opacity, while it does.
            window.set_opacity(0.0)
            try:
                window.show()
                self._arm_backdrop("flyout", window, timeout=6.0, settle=False)
            finally:
                window.set_opacity(1.0)
            if self._flyout_size:
                self._place_flyout(window, hwnd, self._flyout_size)
            self._arming_kind = "flyout"
        if serial != self._flyout_serial or not self._flyout_open:
            return
        # Reused windows can be shown immediately; cold windows were already
        # shown transparently and armed above.
        try:
            window.show()
        except Exception:
            pass
        # arm() sizes on the GUI thread and acknowledges the background; no fixed sleep is needed.
        # The size the panel asked for may have landed while it was hidden.
        if self._flyout_size:
            self._place_flyout(window, hwnd, self._flyout_size)
        self._apply_capture_exclusion()
        self._apply_system_glass("flyout")
        self._flyout_shown_at = time.monotonic()
        self._watch_flyout_focus()
        if not cold and not resuming:
            self._arm_backdrop("flyout", window, timeout=0.12, settle=False)
        if serial != self._flyout_serial or not self._flyout_open:
            return
        bring_to_front(window, topmost=True)
        def enter_current():
            if serial == self._flyout_serial and self._flyout_open:
                window.native.flyout_enter()
        if getattr(window, "is_native_overlay", False) is True:
            window.run_on_ui_thread(enter_current)
        else:
            window.send("flyout_enter")

    def dismiss_flyout(self):
        """Close the panel because focus moved elsewhere.

        Ignored right after it was shown (activation churn) and when focus
        went to another of this app's windows, such as a detail card opened
        from inside the panel.
        """
        if time.monotonic() - self._flyout_shown_at < 0.5:
            return
        serial = self._flyout_serial
        # The activation change is still in flight when Deactivate fires: the foreground window is none for a
        # moment. Closed as soon as it is another program's; given up on waiting after the same 0.12 s as before.
        for _ in range(8):
            if serial != self._flyout_serial or not self._flyout_open:
                return
            try:
                foreground = foreground_root()
                if foreground in self._own_hwnds():
                    return
                if foreground:
                    break
            except Exception:
                pass
            time.sleep(0.015)
        if serial != self._flyout_serial or not self._flyout_open:
            return
        self._flyout_dismissed_at = time.monotonic()
        self.hide_flyout()

    # Keep in step with the panel's own exit (nativeui/panel.py flyout_leave).
    _FLYOUT_LEAVE_S = 0.17

    def hide_flyout(self):
        if (self._flyout_toggle_running
                and threading.current_thread() is not self._flyout_toggle_thread):
            with self._flyout_toggle_lock:
                self._flyout_toggle_target = False
                self._flyout_toggle_revision += 1
        if not self._flyout_open:
            return
        self._flyout_open = False
        self._flyout_serial += 1
        serial = self._flyout_serial
        self._sync_client_entities()
        self.close_popover()
        window = self._flyout_window
        if not window:
            self._overlays_open.discard("flyout")
            self._apply_capture_exclusion()
            return

        def valid_exit():
            return serial == self._flyout_serial and not self._flyout_open

        def closed_current():
            if valid_exit():
                # The desktop beneath the moving card remains capturable until
                # the card is actually hidden, including an interrupted exit.
                self._overlays_open.discard("flyout")
                self._apply_capture_exclusion()
                self._schedule_release("flyout")

        if getattr(window, "is_native_overlay", False) is True:
            # Time the hide from the actual GUI start, not from a worker's send.
            window.leave_and_hide(valid_exit, 210, closed_current)
            return

        def fade_then_hide():
            # On a thread: this can be called from the GUI thread, where
            # waiting out the animation would block it.
            if not valid_exit():
                return
            window.send("flyout_leave")
            time.sleep(self._FLYOUT_LEAVE_S)
            if not valid_exit():
                return          # opened again mid-fade
            try:
                window.hide()
            except Exception:
                pass
            closed_current()

        threading.Thread(target=fade_then_hide, daemon=True).start()

    def _watch_flyout_focus(self):
        """Backstop for the Deactivate handler in main().

        Deactivate only fires if the panel got focus in the first place,
        and SetForegroundWindow can be refused. Polls while the panel is
        open and closes it once focus is elsewhere.
        """
        serial = self._flyout_serial
        def watch():
            time.sleep(0.5)          # activation is not instant (the same grace dismiss_flyout gives it)
            misses = 0
            while self._flyout_open and serial == self._flyout_serial:
                try:
                    foreground = foreground_root()
                    if foreground and foreground not in self._own_hwnds():
                        misses += 1
                    else:
                        misses = 0       # (none, in the middle of a change: neither here nor there)
                except Exception:
                    misses = 0
                if misses >= 2 and serial == self._flyout_serial:
                    self._flyout_dismissed_at = time.monotonic()
                    self.hide_flyout()
                    return
                time.sleep(0.03)

        threading.Thread(target=watch, daemon=True).start()

    def _tray_corner(self, at=None):
        """The work area under the pointer (which is over the tray icon at
        the moment of the click), or under the point `at`, and whether the
        notification area is on its right-hand side."""
        try:
            pt = POINT(0, 0)
            if at:
                pt.x, pt.y = at
            else:
                user32.GetCursorPos(ctypes.byref(pt))
            work = work_area_at(pt.x, pt.y)
            if not work:
                return None
            return (work, pt.x - work[0] > (work[2] - work[0]) / 2)
        except Exception:
            return None

    def _flyout_origin(self, w, h):
        """Tuck the panel into the tray corner of the work area, beside the
        taskbar rather than over it."""
        anchor = self._flyout_anchor
        if not anchor or w <= 0 or h <= 0:
            return None
        work, near_right = anchor
        # A monitor can disappear and return with a different work area on
        # resume. Never position against the rectangle cached before sleep.
        work = work_area_at(work[2] - 1 if near_right else work[0], work[3] - 1) or work
        m = self._FLYOUT_MARGIN
        x = work[2] - w - m if near_right else work[0] + m
        return (
            max(work[0] + m, min(x, work[2] - w - m)),
            max(work[1] + m, work[3] - h - m),
        )
