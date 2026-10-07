"""Dimming the widgets while the desktop is out of sight."""

import threading
import time

from winsys.scan import desktop_is_front, fullscreen_app_present
from winsys.win32 import get_hwnd


class IdleMixin:
    def _init_idle(self):
        self._dimmed = False
        self._woke_at = 0.0
        self._off_desktop_since = 0.0
        self._dim_stop = threading.Event()

    def wake(self):
        """Called by a widget when someone touches it."""
        # Held awake for a full idle period from here, so a click cannot be
        # answered by fading out from under the hand that made it.
        self._woke_at = time.monotonic()
        self._off_desktop_since = 0.0
        # Every widget at once, from here, rather than each waking itself
        # and the rest following later. Sent even when this side thinks
        # nothing was dimmed, which repairs a widget that disagreed.
        self._dimmed = False
        self._push_dim()
        return True

    def _push_dim(self):
        self._broadcast("set_dim", bool(self._dimmed),
                        windows=list(self._widgets.values()) or [self._window])
        self._sync_local_media()

    def _idle_wanted(self, now=None):
        """Whether the widgets should be dimmed now: the desktop has been out of sight for dim_after_sec
        (at once for a full-screen app), and nobody has touched a widget for as long."""
        if not self._cfg.get("dim_when_idle", True):
            return False
        after = max(10, int(self._cfg.get("dim_after_sec", 120)))
        mine = self._own_hwnds()
        now = time.monotonic() if now is None else now
        front = desktop_is_front({get_hwnd(w) for w in self._widgets.values()}, mine)
        if front:
            self._off_desktop_since = 0.0
            wanted = False
        elif front is None:
            # Taskbar, Start menu, our panel: neither a reason to wake nor to start counting.
            wanted = self._dimmed
        else:
            if not self._off_desktop_since:
                self._off_desktop_since = now
            wanted = (now - self._off_desktop_since) >= after
        if fullscreen_app_present(mine):
            return True
        if wanted and (now - self._woke_at) < after:
            return False                  # woken recently
        return wanted

    def _watch_for_idle(self):
        """Dim the widget once the desktop has been out of sight for dim_after_sec (immediately for a
        full-screen app), and restore it when the desktop comes back. Timed on what is in front, not on input:
        someone busy in a browser is not looking at the widget."""
        def loop():
            while not self._dim_stop.wait(1.0):
                try:
                    wanted = self._idle_wanted()
                    if wanted != self._dimmed:
                        self._dimmed = wanted
                        self._push_dim()
                except Exception:
                    pass

        threading.Thread(target=loop, daemon=True).start()
