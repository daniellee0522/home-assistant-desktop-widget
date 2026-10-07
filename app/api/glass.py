"""Which windows are hidden from screen capture (so they may read the screen for their own glass) and the
system's own glass (DWM)."""

import threading
import time

from app.geometry import is_widget_kind, WINDOWS_ABOVE
from winsys.win32 import get_hwnd, rects_overlap, visible_rect
from winsys.windows import set_capture_exclusion, set_system_glass, SYSTEM_GLASS_SUPPORTED


class GlassMixin:
    def _init_glass(self):
        # The last small backdrop sent to each window: (hash, image).
        self._backdrop_sent = {}
        self._backdrop_direct = {}
        self._hidden_cache = {}
        # Native DWM glass, tracked per window by the HWND it was applied to.
        self._system_glass_hwnds = {}
        # The window kinds currently excluded from screen capture: exactly the ones that may read the screen for
        # their own backdrop.
        self._excluded_kinds = set()
        # DWM applies a capture-affinity change on its next composition, so frames captured across such a
        # change are dropped.
        self._capture_epoch = 0
        # Per window kind: (rectangle, frame) last answered through Desktop Duplication, so the next read waits
        # for that rectangle to change.
        self._duplication_after = {}
        self._capture_transition_until = 0.0
        # Each widget's latest screen capture, by kind. A liquid-mode popover over an excluded widget restores
        # this region instead of a black hole; _popover_owner says which widget the popover belongs to.
        self._widget_frames = {}
        # Each widget's last picture of the desktop with nothing over it, by kind: (rect, BGRA). Where another
        # program's window lies over a widget, its glass shows this instead of that window.
        self._clean_backdrops = {}
        self._widget_snaps = {}
        # The desktop's windows looked at once for every widget of a frame (see widget_glass_frames).
        self._shared_windows = None
        self._backdrop_pool = None
        # Overlay windows currently open. While any overlaps the widget, the widget stays capturable so it
        # appears in the overlay's backdrop.
        self._overlays_open = set()
        # The window, if any, that is positioned but not yet shown and is taking the backdrop of where it will
        # appear; see _arm_backdrop.
        self._arming_kind = None
        self._armed = threading.Event()

    def _apply_capture_exclusion(self):
        """Decide, for each window, whether it is hidden from screen capture.

        A window must be excluded to read the screen for its own backdrop,
        or it reads itself back in. An excluded window comes back black in
        captures above it, so overlays compose widgets over their cached
        desktop pixels. Widgets keep the same capture source beneath a
        popover in both glass styles to avoid flashes during handoff.

        A kind only counts as excluded if the OS accepted the call; older
        builds fall back to the slower PrintWindow path.
        """
        # Liquid mode needs live pixels even if native glass was selected.
        mode = self._cfg.get("glass_mode", "fast")
        wanted = mode == "fast" or (mode == "system" and
                                    self._cfg.get("glass_style") == "liquid")
        # A window being armed already sits where it will appear, so it
        # counts as present. Closed overlays do not, even if their hide()
        # has not completed yet.
        widget_kinds = self._widget_kinds() or ["main"]
        kinds = (*widget_kinds, "flyout", "popover", "settings")
        rects = {
            kind: (visible_rect(self._window_for(kind), kind == self._arming_kind)
                   if is_widget_kind(kind) or kind in self._overlays_open
                   or kind == self._arming_kind else None)
            for kind in kinds
        }
        excluded = {}
        for kind in kinds:
            above = (WINDOWS_ABOVE[kind] if kind in WINDOWS_ABOVE
                     else WINDOWS_ABOVE["main"])
            mine = rects.get(kind)
            covered = bool(mine) and any(
                rects.get(other) and rects_overlap(mine, rects[other])
                and not (is_widget_kind(kind) and (other == "popover" or
                         (other == "flyout" and self._cfg.get("glass_style") == "liquid")))
                for other in above
            )
            # Settings reads nothing from the screen, so it need not hide.
            excluded[kind] = wanted and not covered and kind != "settings"
        accepted = set()
        for kind in (*widget_kinds, "popover", "settings", "flyout"):
            win = self._window_for(kind)
            if win:
                ok = set_capture_exclusion(win, excluded[kind])
                if ok and excluded[kind]:
                    accepted.add(kind)
        if {k for k in accepted if is_widget_kind(k)} != {k for k in self._excluded_kinds if is_widget_kind(k)}:
            self._capture_epoch += 1
            self._capture_transition_until = time.monotonic() + 0.2
        self._excluded_kinds = accepted

    # Windows DWM may draw glass for. Settings keeps painting its own: it
    # is meant to be read, with a mostly opaque panel.
    _SYSTEM_GLASS_OVERLAYS = ("popover", "flyout")

    @property
    def _SYSTEM_GLASS_KINDS(self):
        return (*(self._widget_kinds() or ["main"]), *self._SYSTEM_GLASS_OVERLAYS)

    def _system_glass_wanted(self):
        return (SYSTEM_GLASS_SUPPORTED and self._cfg.get("glass_mode") == "system"
                and self._cfg.get("glass_style") != "liquid")

    def _system_glass_on(self, kind=None):
        if not self._system_glass_wanted():
            return False
        if kind is None:
            return any(self._system_glass_on(k) for k in self._SYSTEM_GLASS_KINDS)
        hwnd = get_hwnd(self._window_for(kind))
        return bool(hwnd and self._system_glass_hwnds.get(kind) == hwnd)

    def _system_glass_status(self):
        return {k: self._system_glass_on(k) for k in self._SYSTEM_GLASS_KINDS}

    def _apply_system_glass(self, kind=None):
        desired = self._system_glass_wanted()
        before = dict(self._system_glass_hwnds)
        for k in ((kind,) if kind else self._SYSTEM_GLASS_KINDS):
            if k not in self._SYSTEM_GLASS_KINDS:
                continue
            win = self._window_for(k)
            if not win:
                continue
            self._system_glass_hwnds.pop(k, None)
            if set_system_glass(win, desired) and desired:
                self._system_glass_hwnds[k] = get_hwnd(win)
        if before != self._system_glass_hwnds:
            self._push_prefs()
