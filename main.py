"""
HA Desktop Widgets (Qt edition)
=======================================

A borderless desktop widget that mirrors your Home Assistant accessories as
an Apple Home / Prism-Desktop style tile grid, with realtime updates pushed
over Home Assistant's WebSocket API. It behaves like a desktop gadget, not
a normal window: it's pinned to the *bottom* of the z-order (behind other
apps, never fighting for focus) and only becomes a normal frontmost window
while Settings is open, so you can type into it.

Run:
    python main.py

First run opens the in-widget Settings panel (gear icon, top-right on
hover) to configure your Home Assistant URL + long-lived access token and
pick which accessories to show. Everything after that - including the
token, theme, column count, tile layout, and the toggles below - is saved
to ha_widgets_config.json next to this script.

Drag the widget by its background to move it (or lock its position in
Settings); it remembers where you left it. Left-click a tile to toggle it;
press-and-hold - or right-click - any tile to open its detail card, which
carries whatever controls that accessory has (brightness, temperature,
speed, position, volume...) and, behind the gear, its name and icon. Tiles
with nothing to operate - sensors, and anything with no controls yet -
open the same card showing their reading, so they can be renamed too.
Settings also has a "start with Windows" toggle. Right-click the system tray icon for
Settings, theme switching, a manual refresh, or Quit. Closing the widget
(Alt+F4) just hides it - use tray "Quit" to actually exit.

Requires: PySide6, pystray, Pillow, websocket-client.
Install with: pip install -r requirements.txt
"""

import base64
import ctypes
import datetime
import io
import json
import math
import multiprocessing
import os
import sys
import threading
import time
import zlib

from capture_worker import CaptureWorker

if sys.platform == "win32":
    # Must happen before pywebview creates any window / calls its own
    # (older, system-only) SetProcessDPIAware(). Per-monitor-v2 awareness
    # keeps Win32's own DPI queries (which pywebview's resize() math relies
    # on) consistent with reality on a multi-monitor, mixed-scale setup.
    try:
        # A private WinDLL instance, not ctypes.windll.user32, for the same
        # reason as the one further down: argtypes set on the shared handle
        # would apply to pywebview's calls through it too.
        _set_ctx = ctypes.WinDLL("user32").SetProcessDpiAwarenessContext
        _set_ctx.argtypes = [ctypes.c_void_p]
        _set_ctx.restype = ctypes.c_int
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if not _set_ctx(ctypes.c_void_p(-4)):
            raise OSError("SetProcessDpiAwarenessContext failed")
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(
                2)  # PROCESS_PER_MONITOR_DPI_AWARE
        except Exception:
            pass

# Let Qt and Chromium negotiate their default graphics backend. Forcing
# --disable-gpu caused repeated GLES shared-context failures on this Qt
# build, even with QT_QUICK_BACKEND=software. Preserve caller-provided
# graphics environment variables for diagnostics.
# Import Qt only after setting DPI awareness above.
import qtshell as webview  # noqa: E402

import config as cfgmod  # noqa: E402
from ha_client import HAClient  # noqa: E402
from tray import build_tray_icon  # noqa: E402

# Where this program's own files are. Frozen, that is the folder the
# executable sits in - PyInstaller puts the bundled data under _internal
# beside it, and __file__ points inside the bundle rather than at
# anything on disk.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    WEB_DIR = os.path.join(getattr(sys, "_MEIPASS", BASE_DIR), "web")
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    WEB_DIR = os.path.join(BASE_DIR, "web")

TILE_W, TILE_H, GAP, PAD = 152, 146, 12, 20


# The smallest a window is ever made. Windows below roughly this size
# stop laying their content out sensibly, and a window collapsed to it
# is one whose page has nothing to show rather than one anybody sees.
MIN_WINDOW_W = 80
MIN_WINDOW_H = 60


class Api:
    """Exposed to the page as window.pywebview.api.<method>.

    IMPORTANT: pywebview discovers callable methods by walking `dir(self)`
    and *recursing into every non-callable attribute it finds* (to support
    nested api objects). That means any plain data we stash on `self` -
    including the native pywebview Window, once bound - gets walked too,
    and recursing into the native window's .NET object graph blows the
    stack. Every non-method attribute here is therefore prefixed with `_`,
    which this walk skips outright.
    """

    def __init__(self):
        self._cfg = cfgmod.load_config()
        self._window = None
        self._tray_icon = None
        self._connected = False
        self._ui_ready = False
        self._pending = []
        self._pending_lock = threading.Lock()
        self._move_timer = None
        self._resize_lock = threading.Lock()
        self._last_resize_seq = -1
        self._pin_enabled = threading.Event()
        self._pin_enabled.set()
        # Whether the widget is currently sitting on the desktop. The
        # tray flyout is a window of its own and tracks itself.
        self._desktop_visible = True
        # Whether the widget is currently faded back into the desktop, and
        # the thread watching for the moments it should be - see
        # _watch_for_idle.
        self._dimmed = False
        # When someone last asked for it back (see wake), and since when
        # the desktop has been out of sight (see _watch_for_idle).
        self._woke_at = 0.0
        self._off_desktop_since = 0.0
        self._dim_stop = threading.Event()

        # The detail popover lives in its own separate OS window (see the
        # IS_POPOVER_WINDOW comment in app.js for why) - it shares this
        # same Api instance (same config, same HA connection) but needs
        # its own window handle and its own independent resize/sequencing
        # state, since it resizes on its own schedule, unrelated to the
        # main grid window's.
        # Whether both windows are currently hidden from screen capture,
        # which is what makes the cheap backdrop path safe to use.
        self._capture_excluded = False
        self._system_glass_hwnds = {}
        # The window kinds currently hidden from screen captures, which is
        # exactly the set that may read the screen for their own backdrop
        # (see _apply_capture_exclusion).
        self._excluded_kinds = set()
        # Drop a backdrop captured while an overlay changes which of our
        # windows are visible to screen capture. DWM applies that change
        # on its next composition, not at the instant of the API call.
        self._capture_epoch = 0
        self._capture_transition_until = 0.0
        # The main window's latest real screen pixels. A popover above an
        # excluded widget can restore this region without a slow wallpaper
        # re-render or a black capture-affinity hole.
        self._main_backdrop_frame = None
        # Which overlay windows are open. While any of them is, the grid
        # window is deliberately left capturable, because it is part of
        # what is behind them and so part of their frosted backdrop.
        self._overlays_open = set()

        # The tray flyout: a fourth window showing the same tile grid,
        # which comes up beside the clock when the tray icon is clicked
        # and goes away again when it loses focus - the way the volume and
        # network panels behave. Separate from the desktop widget so that
        # summoning it neither moves nor disturbs the one the user has
        # placed.
        self._flyout_window = None
        self._flyout_resize_lock = threading.Lock()
        self._flyout_last_resize_seq = -1
        self._flyout_open = False
        # The work area it was summoned into, and which side of it the
        # notification area is on. Fixed when it opens rather than read
        # per resize: the pointer is over the tray at the moment of the
        # click and somewhere else entirely a second later.
        self._flyout_anchor = None
        # The size its page last asked for. The window's own rectangle is
        # not a reliable answer while it is hidden: WinForms holds a
        # pending size back until the form is shown, so a freshly created
        # panel still measures at its creation size right up until the
        # moment it appears - and the backdrop captured for it in that
        # moment is of the wrong piece of screen.
        self._flyout_size = None
        # When it was last put on screen. Windows shuffles activation
        # around while a window is being shown, and the Deactivate that
        # comes out of that churn is not the user clicking away.
        self._flyout_shown_at = 0.0
        # True for the moment between moving the panel into place and
        # actually showing it, during which it is allowed to capture the
        # backdrop it is about to sit on - see show_flyout.
        # Which window, if any, is being armed: positioned and rendered
        # but not yet shown, taking the backdrop of the place it is about
        # to cover. See _arm_backdrop.
        self._arming_kind = None
        self._armed = threading.Event()

        self._popover_window = None
        self._popover_resize_lock = threading.Lock()
        # The tile the popover belongs to (x, y, w, h in physical
        # pixels) and the last real size it took, both needed to place
        # it - see _popover_origin.
        self._popover_anchor = None
        self._popover_size = None
        self._popover_last_resize_seq = -1

        # Settings is a third window for the same reasons the popover is
        # one: it needs to take keyboard focus, it must not be scaled by
        # the widget's zoom, and it should not drag the grid's size around
        # while it is open. Same page, same Api - only the URL fragment
        # differs (see WINDOW_ROLE in app.js).
        self._settings_window = None
        self._settings_resize_lock = threading.Lock()
        self._settings_last_resize_seq = -1

        self._client = HAClient(
            on_event=self._on_ha_event, on_status=self._on_ha_status)
        self._client.configure(
            self._cfg.get("ha_url", ""), self._cfg.get("ha_token", ""),
            self._cfg.get("poll_fallback_sec", 30),
        )
        self._client.set_entities(
            [t["entity"] for t in self._cfg.get("tiles", []) if t.get("entity")])
        self._client.start()

    def _bind_window(self, window):
        self._window = window

    def _bind_popover_window(self, window):
        self._popover_window = window

    def _bind_settings_window(self, window):
        self._settings_window = window

    def _bind_flyout_window(self, window):
        self._flyout_window = window

    def _window_for(self, kind):
        return {
            "popover": self._popover_window,
            "settings": self._settings_window,
            "flyout": self._flyout_window,
        }.get(kind, self._window)

    # ---------------------------------------------------------------
    # JS-callable API (exposed as window.pywebview.api.<method>)
    # ---------------------------------------------------------------

    def bootstrap(self):
        # Deliberately does *no* network I/O: it only reads the already-
        # loaded local config, so the page can render the tile grid
        # immediately regardless of whether Home Assistant is reachable.
        # Initial per-tile state is fetched separately (fetch_initial_states)
        # after that first render, and real-time updates arrive over the
        # websocket/poll fallback the same way either way - blocking the
        # very first paint on a REST round-trip just means a slow or
        # unreachable HA (wrong URL, server restart, VPN not up yet) stalls
        # the whole widget for as long as that request's timeout.
        tiles = self._cfg.get("tiles", [])
        return {
            "config": {
                "ha_url": self._cfg.get("ha_url", ""),
                "ha_token": self._cfg.get("ha_token", ""),
                "theme": self._cfg.get("theme", "auto"),
                "language": self._cfg.get("language", "zh-TW"),
                "glass_style": self._cfg.get("glass_style", "classic"),
                "columns": self._cfg.get("columns", 4),
                "lock_position": bool(self._cfg.get("lock_position", False)),
                "start_on_boot": bool(self._cfg.get("start_on_boot", False)),
                "zoom": self._cfg.get("zoom", 100),
                "fixed_size": bool(self._cfg.get("fixed_size", False)),
                "fixed_width": self._cfg.get("fixed_width", 400),
                "fixed_height": self._cfg.get("fixed_height", 300),
                "opacity": self._cfg.get("opacity", 100),
                "glass_mode": self._cfg.get("glass_mode", "fast"),
                "system_glass_ok": bool(_SYSTEM_GLASS_SUPPORTED),
                "system_glass_active": self._system_glass_status(),
                "panel_theme": self._cfg.get("panel_theme", "follow"),
                "sample_fps": int(self._cfg.get("sample_fps", 16)),
                "dim_when_idle": bool(self._cfg.get("dim_when_idle", True)),
                "dim_after_sec": int(self._cfg.get("dim_after_sec", 120)),
                "tiles": tiles,
            },
            "connected": self._connected,
        }

    def fetch_initial_states(self):
        tiles = self._cfg.get("tiles", [])
        if not (self._cfg.get("ha_token") and tiles):
            return {}
        states = {}
        try:
            all_states = self._client.get_states()
            by_id = {s.get("entity_id"): s for s in all_states}
            for t in tiles:
                if t["entity"] in by_id:
                    states[t["entity"]] = by_id[t["entity"]]
        except Exception:
            pass
        return states

    def ui_ready(self):
        self._ui_ready = True
        with self._pending_lock:
            pending, self._pending = self._pending, []
        if pending:
            self._push_batch(pending)
        return True

    def get_entities(self):
        try:
            states = self._client.get_states()
        except Exception:
            return []
        out = []
        for s in states:
            eid = s.get("entity_id", "")
            domain = cfgmod.domain_of(eid)
            if domain not in cfgmod.SUPPORTED_DOMAINS:
                continue
            out.append({
                "entity_id": eid,
                "domain": domain,
                "name": (s.get("attributes") or {}).get("friendly_name") or eid,
                "state": s,
            })
        out.sort(key=lambda e: (e["domain"], e["name"]))
        return out

    def test_connection(self, url, token):
        tmp = HAClient()
        tmp.configure(url, token)
        ok, detail = tmp.test_connection()
        return {"ok": ok, "detail": detail}

    def save_ha_config(self, url, token):
        self._cfg["ha_url"] = (url or "").rstrip("/")
        self._cfg["ha_token"] = token or ""
        cfgmod.save_config(self._cfg)
        self._client.configure(
            self._cfg["ha_url"], self._cfg["ha_token"], self._cfg.get(
                "poll_fallback_sec", 30),
        )
        return True

    def save_tiles(self, tiles):
        clean = []
        for t in (tiles or []):
            entity = (t.get("entity") or "").strip()
            if not entity:
                continue
            clean.append({
                "id": t.get("id") or entity,
                "entity": entity,
                "domain": t.get("domain") or cfgmod.domain_of(entity),
                "room": (t.get("room") or "").strip(),
                "label": (t.get("label") or "").strip(),
                "icon": (t.get("icon") or "").strip(),
                "on_mode": t.get("on_mode") or "cool",
                "temp_step": t.get("temp_step", 1),
            })
        self._cfg["tiles"] = clean
        cfgmod.save_config(self._cfg)
        self._client.set_entities([t["entity"] for t in clean])
        self._push_prefs()
        return True

    # How each preference is cleaned up on the way in. The page sends only
    # the keys it changed (see savePref in app.js) and everything else is
    # left exactly as it was, which is the point: four windows each hold
    # their own copy of the config, and the old call - every preference,
    # positionally, from whichever window happened to have a control on it
    # - wrote one window's stale copy over everyone else's changes. That
    # is what "the settings don't stick" was.
    _PREF_CLEANERS = {
        "theme": lambda v: v if v in ("auto", "light", "dark") else "auto",
        "glass_style": lambda v: v if v in ("classic", "liquid", "windows") else "classic",
        "language": lambda v: v if v in ("zh-TW", "en") else "zh-TW",
        # The tray panel sits over other windows rather than on the
        # wallpaper, so what looks right there is not what looks right on
        # the desktop; "follow" means don't have an opinion.
        "panel_theme": lambda v: v if v in ("follow", "auto", "light", "dark") else "follow",
        "columns": lambda v: max(2, min(8, int(v))),
        "lock_position": bool,
        "zoom": lambda v: max(50, min(200, int(v))),
        "fixed_size": bool,
        "fixed_width": lambda v: max(120, int(v)),
        "fixed_height": lambda v: max(90, int(v)),
        "opacity": lambda v: max(0, min(100, int(v))),
        "glass_mode": lambda v: v if v in ("system", "fast", "compat") else "fast",
        # How often the desktop behind the widget is re-read, in frames a
        # second. The page paces itself from what a frame actually costs
        # (see BACKDROP_DUTY in app.js); this is the ceiling on that pace.
        "sample_fps": lambda v: max(2, min(30, int(v))),
        "dim_when_idle": bool,
        "dim_after_sec": lambda v: max(10, min(3600, int(v))),
    }

    def save_prefs(self, changes):
        """Merge `changes` into the config, clean, save and broadcast."""
        if not isinstance(changes, dict):
            return False
        touched = set()
        for key, value in changes.items():
            clean = self._PREF_CLEANERS.get(key)
            if clean is None or value is None:
                continue
            try:
                self._cfg[key] = clean(value)
            except Exception:
                continue
            touched.add(key)
        if "glass_mode" in touched or "glass_style" in touched:
            # Both of these read the mode, and both have to be told: one
            # decides which windows hide from screen capture, the other
            # who paints the glass.
            self._apply_capture_exclusion()
            self._apply_system_glass()
        if "dim_when_idle" in touched and not self._cfg["dim_when_idle"] and self._dimmed:
            self._dimmed = False
            self._push_dim()
        cfgmod.save_config(self._cfg)
        self._push_prefs()
        return True

    def set_start_on_boot(self, enabled):
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE,
            )
            try:
                if enabled:
                    winreg.SetValueEx(key, "HAWidgets", 0,
                                      winreg.REG_SZ, _startup_command())
                else:
                    try:
                        winreg.DeleteValue(key, "HAWidgets")
                    except FileNotFoundError:
                        pass
            finally:
                winreg.CloseKey(key)
            self._cfg["start_on_boot"] = bool(enabled)
            cfgmod.save_config(self._cfg)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_history(self, entity_id, hours=24):
        """Recent recorded values for a sensor, thinned for drawing.

        Returned as [[seconds since the epoch, value], ...] with the
        non-numeric samples dropped - a sensor that goes `unavailable` for
        a while should leave a gap in the line rather than a dive to zero.
        """
        try:
            raw = self._client.get_history(entity_id, hours=hours)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        points = []
        for row in raw or []:
            try:
                value = float(row.get("state"))
            except (TypeError, ValueError):
                continue        # unknown / unavailable / a text state
            stamp = row.get("last_changed") or row.get("last_updated") or ""
            try:
                # "2026-09-15T01:02:03.456789+00:00"; the fraction and the
                # zone are both optional in practice.
                text = stamp.replace("Z", "+00:00")
                when = datetime.datetime.fromisoformat(text).timestamp()
            except Exception:
                continue
            points.append([when, value])
        points.sort(key=lambda p: p[0])
        # A day of a sensor that reports every few seconds is tens of
        # thousands of points for a chart a couple of hundred pixels wide;
        # keep one in every nth rather than sending all of them through
        # the bridge to be thrown away by the renderer.
        limit = 240
        if len(points) > limit:
            step = len(points) / float(limit)
            points = [points[min(len(points) - 1, int(i * step))]
                      for i in range(limit)]
        return {"ok": True, "points": points, "hours": hours}

    def call_service(self, domain, service, entity_id, extra):
        try:
            self._client.call_service(domain, service, entity_id, extra or {})
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def resize_window(self, phys_w, phys_h, seq=None):
        # phys_w/phys_h are already-physical pixels: the JS side multiplies
        # its CSS measurement by window.devicePixelRatio itself. pywebview's
        # own resize() does that same conversion internally using Win32's
        # GetDpiForWindow, but on this project's dev machine that disagreed
        # with WebView2's real devicePixelRatio (a Windows text-scaling
        # setting layered on top of normal monitor scaling was the
        # reproducible cause) - resulting in a window sized for the wrong
        # physical pixel count and real content clipped at its edge with no
        # scrollbar to reveal it. Bypassing resize() and setting the raw
        # physical size directly removes that whole translation step.
        self._resize_native(
            self._window, self._resize_lock, "_last_resize_seq",
            phys_w, phys_h, seq, "resize_window",
        )

    def resize_popover_window(self, phys_w, phys_h, seq=None):
        # The detail popover is a separate OS window (see IS_POPOVER_WINDOW
        # in app.js) that resizes on its own schedule, so it needs its own
        # sequence counter and lock. It is also the one window that is
        # *moved* by its resize: where it goes depends on how big it is
        # (a card that fits below its tile hangs off the bottom of the
        # screen once it grows taller), and the size is only known here,
        # once its page has laid the detail out. Doing both in one call
        # also keeps it from showing at the old place for a frame.
        self._resize_native(
            self._popover_window, self._popover_resize_lock, "_popover_last_resize_seq",
            phys_w, phys_h, seq, "resize_popover_window",
            origin=self._popover_origin,
        )

    def resize_flyout_window(self, phys_w, phys_h, seq=None):
        self._flyout_size = (max(MIN_WINDOW_W, int(phys_w)),
                             max(MIN_WINDOW_H, int(phys_h)))
        # The flyout is anchored to a screen corner rather than to a
        # top-left position, so growing it has to move it as well - hence
        # its own origin function, exactly as the detail popover has.
        self._resize_native(
            self._flyout_window, self._flyout_resize_lock, "_flyout_last_resize_seq",
            phys_w, phys_h, seq, "resize_flyout_window",
            origin=self._flyout_origin,
        )

    def resize_settings_window(self, phys_w, phys_h, seq=None):
        # Same as the grid window's path above, with its own sequence
        # counter - Settings resizes as its sections expand, on a schedule
        # of its own.
        self._resize_native(
            self._settings_window, self._settings_resize_lock, "_settings_last_resize_seq",
            phys_w, phys_h, seq, "resize_settings_window",
        )

    def _resize_native(self, window, seq_lock, seq_attr, phys_w, phys_h, seq, tag,
                       origin=None):
        if not window:
            return
        if seq is not None:
            with seq_lock:
                if seq <= getattr(self, seq_attr):
                    # A resize call issued later by JS finished executing
                    # (on its own thread) before this older one got here -
                    # applying this stale, likely-smaller size would clip
                    # content that's already on screen. Drop it.
                    return
                setattr(self, seq_attr, seq)
        hwnd = _get_hwnd(window)
        if not hwnd:
            return
        w = max(MIN_WINDOW_W, int(phys_w))
        h = max(MIN_WINDOW_H, int(phys_h))

        if os.environ.get("HA_WIDGET_DEBUG"):
            with open(os.path.join(BASE_DIR, "resize_trace.txt"), "a", encoding="utf-8") as f:
                f.write("%s w=%r h=%r seq=%r\n" % (tag, w, h, seq))

        # pywebview runs every js_api call (this one included) on a fresh,
        # throwaway Python thread so a slow call can't block the UI (see
        # webview.util.js_bridge_call) - it is *not* the WinForms UI thread
        # that owns this HWND. Calling SetWindowPos straight from there
        # races the docked WebView2 child control's own Dock=Fill relayout
        # and repaint, which WinForms drives on its UI thread's message
        # loop. Marshaling onto that thread via Invoke (the same mechanism
        # pywebview itself uses for every other native call - see
        # InvokeRequired/Invoke throughout platforms/winforms.py) makes
        # this synchronous with the relayout instead of racing it.
        def apply():
            # Request threads may queue UI work in a different order from
            # their sequence check above. Recheck on the owning thread.
            if seq is not None and seq != getattr(self, seq_attr):
                return
            at = origin(w, h) if origin else None
            if at:
                _set_window_rect(hwnd, at[0], at[1], w, h)
            else:
                _set_window_size(hwnd, w, h)
        _run_on_ui_thread(window, apply)

    def quit_app(self):
        self._quit()

    def set_activatable(self, enabled):
        # The widget normally can't be activated/focused (WS_EX_NOACTIVATE)
        # so clicking a tile never yanks it above other windows, and it's
        # continually pinned to the bottom of the z-order. Settings has
        # real text fields though, so while that view is open it needs to
        # be a normal, focusable, frontmost window instead.
        if self._window:
            _set_noactivate(self._window, not enabled)
            if enabled:
                self._pin_enabled.clear()
                _bring_to_front(self._window)
            else:
                self._pin_enabled.set()
                _send_to_bottom(self._window)
        return True

    # ---- tray flyout ----------------------------------------------------

    _FLYOUT_MARGIN = 12         # what Windows leaves around its own flyouts

    def backdrop_armed(self):
        """Called by a window's page once the backdrop it was asked to
        take has been painted - see _arm_backdrop."""
        self._armed.set()
        return True

    def _arm_backdrop(self, kind, window):
        """Have a window take the backdrop of where it is about to appear,
        while it is still hidden.

        Shown first and refreshed afterwards, a window arrives carrying a
        frosted picture of wherever it was last time, replaced a frame or
        two later once the new capture lands: that replacement is the
        flash. Hidden is the ideal moment for the read - the window is
        already over exactly what it is about to cover, and cannot read
        itself in - so the only thing that has to be lifted for it is the
        check that skips windows which are not on screen.
        """
        self._arming_kind = kind
        self._armed.clear()
        try:
            window.evaluate_js(
                "window.__armBackdrop && window.__armBackdrop()")
        except Exception:
            pass
        # The page calls backdrop_armed when it has painted it; the
        # timeout is only there so a page that never answers cannot leave
        # the window unopenable.
        self._armed.wait(0.3)
        # And a moment for the compositor to put that on the window's
        # surface, or the first thing shown is whatever was on it when it
        # was last hidden.
        time.sleep(0.04)
        self._arming_kind = None

    def toggle_flyout(self):
        if self._flyout_open:
            self.hide_flyout()
        else:
            self.show_flyout()

    def show_flyout(self):
        if not self._cfg.get("tiles"):
            self.open_settings_window()
            return
        window = self._flyout_window
        hwnd = _get_hwnd(window) if window else None
        if not hwnd:
            return
        self._flyout_open = True
        self._flyout_anchor = self._tray_corner()
        size = self._flyout_size
        if not size:
            r = (ctypes.c_long * 4)()
            _user32.GetWindowRect(hwnd, ctypes.byref(r))
            size = (r[2] - r[0], r[3] - r[1])
        at = self._flyout_origin(size[0], size[1])
        if at:
            # Position *and* size, so the window is exactly where and what
            # it is about to be before anything is captured for it.
            _run_on_ui_thread(
                window, lambda: _set_window_rect(
                    hwnd, at[0], at[1], size[0], size[1]),
            )
        # Registered as an overlay for the same reason the popover is: it
        # sits over whatever is on screen, so the widget below has to stay
        # capturable to appear in its frosted backdrop.
        self._overlays_open.add("flyout")
        self._arming_kind = "flyout"
        self._apply_capture_exclusion()
        # On screen first, and the backdrop afterwards - the other way
        # round from the widget and the popover, and deliberately.
        #
        # _arm_backdrop blocks for up to a third of a second waiting for
        # the page to say it has painted the capture, and that wait is in
        # front of the panel appearing at all: the tray icon is clicked
        # and nothing happens, which is the stutter. What it buys is the
        # first frame being a picture of the right place rather than of
        # wherever the panel was last time. Measured against each other
        # here, the stale frame lasts a frame or two and the wait lasts
        # 300ms, so the panel opens now and corrects itself.
        try:
            window.show()
        except Exception:
            pass
        # A moment for Qt to finish the resize and DWM to compose it, so
        # what follows is applied to the window's real rectangle.
        time.sleep(0.05)
        # Which is why the rect goes on again here: the size the page
        # asked for may have landed while the window was still hidden.
        size = self._flyout_size
        if size:
            at = self._flyout_origin(size[0], size[1])
            if at:
                _run_on_ui_thread(
                    window, lambda: _set_window_rect(
                        hwnd, at[0], at[1], size[0], size[1]),
                )
        self._apply_capture_exclusion()
        self._apply_system_glass("flyout")
        self._flyout_shown_at = time.monotonic()
        self._watch_flyout_focus()
        self._arm_backdrop("flyout", window)
        # HWND_TOP, not HWND_TOPMOST. Topmost keeps the panel over
        # everything while it is open, but it is a state the window has to
        # be talked back out of on the way out (see hide_flyout), and
        # leaving it out is what keeps the glass from hitching as the card
        # scales in.
        _bring_to_front(window, stay_on_top=False)
        try:
            window.evaluate_js(
                "window.__flyoutEnter && window.__flyoutEnter()")
        except Exception:
            pass

    def dismiss_flyout(self):
        """Close it because attention moved elsewhere - as opposed to
        hide_flyout, which closes it because something asked.

        Two things do not count as moving away. One is the moment right
        after it was shown: putting a window on screen and handing it the
        foreground is several activation changes, and one of them reads as
        a deactivation from the window's own point of view. The other is
        focus going to one of this app's own windows - opening an
        accessory's detail card from inside the panel is not leaving it,
        and without this the card's own activation closed the panel out
        from under itself.
        """
        if time.monotonic() - self._flyout_shown_at < 0.5:
            return
        # The activation change is still in flight when Deactivate fires;
        # let it land before asking who has the foreground now.
        time.sleep(0.12)
        try:
            fg = _user32.GetForegroundWindow()
            root = _user32.GetAncestor(fg, GA_ROOT) if fg else None
            if root and root in self._own_hwnds():
                return
        except Exception:
            pass
        self.hide_flyout()

    # How long the panel's leaving animation runs for, in seconds; keep
    # in step with .flyout-leave in style.css.
    _FLYOUT_LEAVE_S = 0.16

    def hide_flyout(self):
        if not self._flyout_open:
            return
        self._flyout_open = False
        self.close_popover()
        window = self._flyout_window
        self._overlays_open.discard("flyout")
        self._apply_capture_exclusion()
        if not window:
            return

        def fade_then_hide():
            # Let it play its way out before the window actually goes.
            # On a thread because this is called from the UI thread as
            # well (the window's own Deactivate, and on_closing), and
            # evaluate_js from there deadlocks - see
            # on_popover_deactivate for that story.
            try:
                window.evaluate_js(
                    "window.__flyoutLeave && window.__flyoutLeave()")
            except Exception:
                pass
            time.sleep(self._FLYOUT_LEAVE_S)
            if self._flyout_open:
                return          # opened again mid-fade; leave it alone
            try:
                window.hide()
            except Exception:
                pass
            # show_flyout does not put it in the topmost band any more,
            # so this is only here to get it out of one it was left in -
            # a hidden panel outranking everything the next time
            # something asks about z-order. A no-op otherwise.
            _drop_topmost(window)

        threading.Thread(target=fade_then_hide, daemon=True).start()

    def _watch_flyout_focus(self):
        """Backstop for the Deactivate handler in main().

        That handler is the real mechanism and fires the moment focus
        moves away - but it can only fire if the window was focused in the
        first place, and SetForegroundWindow is refused outright when
        another process owns the foreground. A tray click makes this
        process the foreground so it normally succeeds; when it does not,
        the panel would otherwise sit there for good. Polled four times a
        second, only while it is open, and only until it closes.
        """
        def watch():
            time.sleep(0.8)          # activation is not instant
            misses = 0
            while self._flyout_open:
                fg = _user32.GetForegroundWindow()
                root = _user32.GetAncestor(fg, GA_ROOT) if fg else None
                if root and root in self._own_hwnds():
                    misses = 0
                else:
                    misses += 1
                    if misses >= 2:
                        self.hide_flyout()
                        return
                time.sleep(0.25)

        threading.Thread(target=watch, daemon=True).start()

    def _tray_corner(self):
        """Which work area the tray icon was just clicked in, and which
        side of it the notification area sits on.

        Read from the pointer, which is over that icon at the moment of
        the click - so this lands on the monitor that was clicked, and on
        a taskbar that has been moved to the left of the screen the panel
        comes up on the left as Windows' own do."""
        try:
            pt = _POINT(0, 0)
            _user32.GetCursorPos(ctypes.byref(pt))
            work = _work_area_at(pt.x, pt.y)
            if not work:
                return None
            return (work, pt.x - work[0] > (work[2] - work[0]) / 2)
        except Exception:
            return None

    def _flyout_origin(self, w, h):
        """Where the panel goes: tucked into the corner of the work area,
        which already excludes the taskbar, so it sits beside it rather
        than over it."""
        anchor = self._flyout_anchor
        if not anchor or w <= 0 or h <= 0:
            return None
        work, near_right = anchor
        m = self._FLYOUT_MARGIN
        x = work[2] - w - m if near_right else work[0] + m
        return (
            max(work[0] + m, min(x, work[2] - w - m)),
            max(work[1] + m, work[3] - h - m),
        )

    def _popover_origin(self, w, h):
        """Where a w*h popover goes for the tile that opened it, or None if
        there is nothing open to place."""
        anchor = self._popover_anchor
        if not anchor:
            return None
        x, y, tw, th = anchor
        work = _work_area_at(x, y)
        if not work or w <= 0 or h <= 0:
            return None
        # Remember what it settled at: the next open needs a size to place
        # against before its page has had a chance to report one. Not the
        # collapsed minimum though - that is the closing animation's
        # parting shot, not a card anyone saw.
        if w > MIN_WINDOW_W and h > MIN_WINDOW_H:
            self._popover_size = (w, h)
        return (
            _place_against(x, w, x, tw or w, work[0], work[2]),
            _place_against(y, h, y, th or h, work[1], work[3]),
        )

    def open_popover(self, tile_id, screen_x, screen_y, tile_w=0, tile_h=0):
        # Moves the (normally hidden) popover window to sit exactly where
        # the clicked tile is on screen, shows it, and asks its own page
        # (already running the full shared bootstrap - same config, same
        # tile list) to render that one tile's detail view.
        if not self._popover_window:
            return
        hwnd = _get_hwnd(self._popover_window)
        if hwnd:
            # Default placement is the tile's own top-left corner, so the
            # card appears to grow out of what was pressed. Near a screen
            # edge that would push it off, so it flips to align with the
            # tile's opposite edge instead - see _place_against.
            self._popover_anchor = (int(screen_x), int(
                screen_y), int(tile_w), int(tile_h))
            # This window is still collapsed to its minimum right now (it
            # shrinks when it closes, and its page only reports a size once
            # it has rendered the tile), so asking the OS how big it is
            # would place a 80x60 card. The size it took last time is the
            # best guess available; resize_popover_window corrects it a
            # moment later with the real one.
            guess = self._popover_size
            if guess:
                at = self._popover_origin(guess[0], guess[1])
                if at:
                    screen_x, screen_y = at
            # Deliberately not self._popover_window.move(): pywebview's
            # move() takes *logical* pixels and scales them by
            # GetDpiForWindow (see platforms/winforms.py), but screen_x/y
            # arrive here already in physical pixels - the page builds them
            # from get_window_pos (a raw GetWindowRect) plus a client rect
            # multiplied by its own devicePixelRatio. Handing physical
            # pixels to move() scaled them a second time, landing the
            # popover hundreds of pixels away from the tile that opened it
            # (far enough off-screen to be unreachable on this machine's
            # 125% display). Setting the position raw skips that
            # conversion, the same way resize_window does for size.
            _run_on_ui_thread(
                self._popover_window,
                lambda: _set_window_pos(hwnd, int(screen_x), int(screen_y)),
            )
        # Re-assert the exclusions here as well as on `shown`: that event
        # fires during window creation, while this window is still hidden
        # and zero-ish, and the affinity did not stick. Without it this
        # window is not excluded from screen capture and the cheap backdrop
        # path reads the popover into its own backdrop - an infinite
        # mirror. Registering the overlay first also lifts the grid
        # window's exclusion, so the popover's backdrop can contain it.
        self._overlays_open.add("popover")
        self._arming_kind = "popover"
        self._apply_capture_exclusion()
        # Everything below happens while the window is still hidden: the
        # card is rendered, which settles its size, which settles where it
        # goes (resize_popover_window places it), and only then is the
        # backdrop of that place taken. Shown first and filled in
        # afterwards, it arrived carrying a frosted picture of whichever
        # tile it was opened on last - the flash.
        try:
            self._popover_window.evaluate_js(
                "window.__showPopoverForTile && window.__showPopoverForTile(%s)" % json.dumps(
                    tile_id)
            )
        except Exception:
            pass
        self._arm_backdrop("popover", self._popover_window)
        try:
            self._popover_window.show()
        except Exception:
            pass
        self._apply_capture_exclusion()
        _bring_to_front(self._popover_window)
        self._apply_system_glass("popover")
        # Its entrance played while it was still hidden; run it again now
        # that there is someone to see it.
        try:
            self._popover_window.evaluate_js(
                "window.__popoverEnter && window.__popoverEnter()")
        except Exception:
            pass

    def open_settings_window(self):
        """Bring up Settings, centred on whichever screen the widget is on.

        It is a real window rather than a view swapped into the grid: it
        has text fields that need focus, it is shown at 100% however the
        widget itself is scaled, and swapping it in used to resize the
        grid window out from under whatever was on screen.
        """
        if not self._settings_window:
            return
        hwnd = _get_hwnd(self._settings_window)
        if hwnd:
            pos = _centre_on_window_monitor(self._window, hwnd)
            if pos:
                _run_on_ui_thread(
                    self._settings_window, lambda: _set_window_pos(
                        hwnd, pos[0], pos[1]),
                )
        # Same reasoning as the popover: Settings sits over the widget, so
        # the widget is part of its backdrop and has to stay capturable
        # while it is up.
        self._overlays_open.add("settings")
        self._apply_capture_exclusion()
        try:
            self._settings_window.show()
        except Exception:
            pass
        _bring_to_front(self._settings_window)
        try:
            self._settings_window.evaluate_js(
                "window.__enterSettings && window.__enterSettings()"
            )
        except Exception:
            pass

    def close_settings_window(self):
        if self._settings_window:
            try:
                self._settings_window.hide()
            except Exception:
                pass
        self._overlays_open.discard("settings")
        self._apply_capture_exclusion()

    def close_popover(self):
        if self._popover_window:
            try:
                self._popover_window.hide()
            except Exception:
                pass
        # The grid window can go back to being hidden from capture, which
        # puts its own backdrop back on the cheap path - unless Settings is
        # still up and needs to see it.
        # Forget the tile it belonged to: the page shrinks this window
        # back to nothing on the way out, and that resize must not drag an
        # already-hidden window around.
        self._popover_anchor = None
        self._overlays_open.discard("popover")
        self._apply_capture_exclusion()

    def set_popover_activatable(self, enabled):
        # No bottom-of-z-order pinning here (unlike set_activatable above)
        # - the popover window is only ever shown for an active
        # interaction, so it should simply come to the front, not be
        # pushed back down once that interaction ends (it just hides).
        if self._popover_window:
            _set_noactivate(self._popover_window, not enabled)
            if enabled:
                _bring_to_front(self._popover_window)
        return True

    def get_desktop_backdrop(self, window_kind="main", last_hash=None, want_w=0, want_h=0,
                             want_corner=0, at_x=None, at_y=None, want_blur=True,
                             want_sharp=True):
        """A JPEG of whatever is behind this window, base64'd.

        The page draws it edge to edge and blurs it behind the card (see
        #backdrop and .card-bg in style.css), which is how this widget gets
        a frosted backdrop at all - the window itself cannot be translucent
        (see the note further down). Returned at the window's exact
        physical pixel size, so the page lays it out 1:1 and the unblurred
        margin around the card lines up with what is really behind it.

        `last_hash` is the caller's previous frame. Most desktops are a
        still image, and answering "same as before" costs only the grab,
        so the page can poll fast enough to track an animated wallpaper
        without paying the encode when there is nothing to send.

        `want_corner` says the page only needs the desktop *sharp* in the
        four corner wedges outside its card, and how big (in device
        pixels) each of those wedges is. The card covers the whole window
        and everything under it is drawn from the blurred copy, so the
        full-size sharp frame was ~250KB of JPEG per frame - all but a few
        hundred pixels of it painted over immediately. The four corners
        pack into one small square instead. Zero means send the whole
        thing, which is what happens if the card ever stops filling the
        window.

        `want_w`/`want_h` are the size the page will actually draw this at,
        in device pixels, and they are not always the window's size: at a
        fractional devicePixelRatio WebView2's viewport rounds to a
        slightly different number of device pixels than the HWND has (687
        against 686, measured). Capturing the window's size and letting CSS
        stretch it to the viewport's resampled every frame, which softened
        the whole image and showed up as ragged edges where the card's
        rounded corners meet the unblurred desktop. Capturing what the page
        asks for keeps it one image pixel per device pixel.
        """
        is_popover = window_kind == "popover"
        window = self._window_for(window_kind)
        if not window:
            return None
        hwnd = _get_hwnd(window)
        if not hwnd:
            return None
        # Nothing to paint for a window that is not on screen. Both of
        # these are cheap enough to run before every frame, and they are
        # the whole of this program's idle cost: measured, the capture
        # loop is ~100% of what it burns, and two of the three windows are
        # hidden almost all of the time (the detail popover and Settings)
        # while the third is usually behind something.
        # A window being armed is the one case where one that is not on
        # screen still has a backdrop worth taking (see _arm_backdrop),
        # and where nothing can be covering it either.
        if window_kind != self._arming_kind:
            if not _user32.IsWindowVisible(hwnd):
                return {"skip": True, "retry_ms": 1000}
            if _nothing_visible_of(hwnd, self._own_hwnds()):
                return {"skip": True, "retry_ms": 400}
        if self._system_glass_on(window_kind):
            return {"skip": True, "retry_ms": 1000, "system_glass": True}
        if (window_kind == "main" and
                time.monotonic() < self._capture_transition_until):
            return {"skip": True, "retry_ms": 80}
        capture_epoch = self._capture_epoch
        started = time.perf_counter()
        try:
            r = (ctypes.c_long * 4)()
            _user32.GetWindowRect(hwnd, ctypes.byref(r))
            x, y, w, h = r[0], r[1], r[2] - r[0], r[3] - r[1]
            if at_x is not None and at_y is not None:
                # Where the window is going, rather than where it is. A
                # drag moves the window by asking Python to move it, so
                # the page knows the new position before the window is
                # there; capturing what it is about to be over takes a
                # round trip of lag out of the glass, which is the
                # difference between it following the window and trailing
                # behind it.
                try:
                    x, y = int(at_x), int(at_y)
                except Exception:
                    pass
            if want_w and want_h:
                want_w, want_h = max(1, int(want_w)), max(1, int(want_h))
                # The page's own arithmetic - its viewport in CSS pixels
                # times its devicePixelRatio - lands a pixel either side
                # of the window's real size, because the viewport is a
                # rounded number of CSS pixels. Where it is that close the
                # window is the truthful answer: its client area is what
                # the viewport is mapped onto, so a capture of exactly
                # that, drawn edge to edge, lines up everywhere. Taking
                # the page's number instead squeezed the image into a
                # window a pixel narrower, which is nothing in the middle
                # and a whole pixel out by the far corner - and the
                # corners are the one place the backdrop is shown
                # unblurred against the real desktop, where a pixel shows.
                # Further apart than that and the page knows something
                # this does not (a fixed size, a zoom), so it wins.
                if abs(want_w - w) > 3 or abs(want_h - h) > 3:
                    w, h = want_w, want_h
        # The popover opens on top of the widget, so the widget is part
        # of what is behind it. Liquid mode composites its Qt image with
        # alpha below; other modes use the usual capture path.
            over = ()
            if window_kind in ("popover", "settings"):
                below = []
                for kind in ("main", "flyout"):
                    win = self._window_for(kind)
                    below_hwnd = _get_hwnd(win) if win else None
                    below_rect = _visible_rect(win) if below_hwnd else None
                    if below_rect and _rects_overlap(
                            below_rect, (x, y, x + w, y + h)):
                        below.append(below_hwnd)
                over = tuple(below)
            # Reading the screen only shows what this process has not
            # excluded from capture, so which window is excluded decides
            # what a read is good for:
            #
            #   popover open  - the grid window is deliberately left
            #     capturable (it is part of the popover's backdrop), so
            #     the popover may read the screen, but the grid may not:
            #     it would read itself back in, an infinite mirror. The
            #     grid falls back to rendering the wallpaper directly for
            #     as long as the popover is up.
            #   otherwise     - the grid is excluded and reads the screen.
            #
            # Toggling the exclusion around each individual read was tried
            # first and does not work: display affinity is applied by DWM
            # when it next composes, so a read taken immediately after
            # clearing it still shows the window missing.
            can_read_screen = self._capture_excluded and window_kind in self._excluded_kinds
            compose_widget = _popover_needs_compat(
                window_kind, self._cfg.get("glass_style"), self._excluded_kinds, over)
            if compose_widget:
                can_read_screen = False
            if window_kind == "flyout" and not can_read_screen:
                # Compatibility mode cannot read the screen containing
                # itself. Render intersecting windows beneath the panel
                # back-to-front over the wallpaper instead.
                over = _windows_below(hwnd, (x, y, x + w, y + h))
            corner = max(0, min(int(want_corner or 0), w // 2, h // 2))
            from PIL import Image, ImageFilter
            # Once DWM is drawing the glass, the four corner wedges are the
            # entire remaining job - a twentieth of the window's pixels -
            # and reading only those looks like the obvious saving. It is
            # not: a blit off the screen costs about 5ms whatever its size,
            # so four small ones measured 20ms against 8ms for one blit of
            # the whole 512x258 window. One blit, then; what the corners
            # save is in what gets encoded and sent, below.
            raw = _desktop_capture.grab_screen(
                x, y, w, h) if can_read_screen or compose_widget else None
            if raw and compose_widget:
                widget = _grab_widget_rgba(self._window)
                frame = getattr(self, '_main_backdrop_frame', None)
                raw = (_compose_popover_backdrop(raw, (x, y, w, h), frame, widget)
                       if frame and widget else None)
            if raw is None:
                # Either the fast path is off or unusable here, or it
                # failed - the slow one always works.
                raw = _compat_capture.grab(x, y, w, h,
                                           tuple(h for h in over if h != _get_hwnd(self._window))
                                           if compose_widget else over)
                if raw and compose_widget:
                    widget = widget or _grab_widget_rgba(self._window)
                    if widget:
                        image, rect = widget
                        raw = _composite_rgba_window(raw, (w, h), image,
                                                     (rect[0] - x, rect[1] - y))
                    else:
                        raw = _compat_capture.grab(x, y, w, h, over)
            if not raw:
                return None
            if capture_epoch != self._capture_epoch:
                return {"skip": True, "retry_ms": 80}
            if window_kind == 'main' and can_read_screen:
                self._main_backdrop_frame = (x, y, w, h, raw)
            digest = zlib.crc32(raw) & 0xFFFFFFFF
            cost_ms = (time.perf_counter() - started) * 1000.0
            if last_hash is not None and int(last_hash) == digest:
                return {"unchanged": True, "hash": digest, "ms": cost_ms,
                        "system_glass": False}
            img = Image.frombuffer("RGBA", (w, h), raw,
                                   "raw", "BGRA", 0, 1).convert("RGB")

            # The frosted copy is blurred here rather than by the page.
            # backdrop-filter did it on the GPU every frame, over the whole
            # window, and that repainting contended with this capture badly
            # enough to double what a frame costs (19ms idle against 41ms
            # while the page was drawing) - which is paid straight back as
            # lag in the corners. Blurring a quarter-scale copy costs ~1ms
            # and the browser scales it back up for free; at this blur
            # radius the downscale is invisible, because a 20px blur throws
            # away far more detail than a 4x downscale does.
            #
            # None of it is needed when DWM is drawing the glass itself
            # (see _set_system_glass): then the only thing the page still
            # wants from here is the sharp corners, and a blurred copy
            # would be painted over the real thing.
            # The blurred copy is only asked for every few frames (see
            # BLUR_EVERY_MS in app.js). Behind the card it is blurred past
            # the point where being a frame or two old can be seen, and
            # leaving it out is most of what a frame costs here - which
            # buys back latency for the corners, where staleness is the
            # one thing that *is* visible.
            blur_buf = None
            if want_blur and not self._system_glass_on(window_kind):
                small = img.resize(
                    (max(1, w // 4), max(1, h // 4)), Image.BILINEAR)
                # Blur the source before it reaches Canvas. Blurring a
                # window-sized canvas samples transparent black beyond its
                # edges and leaves dark wedges in rounded corners.
                blur_radius = (0.75 if self._cfg.get("glass_style") == "liquid"
                               and not is_popover else 4)
                small = small.filter(ImageFilter.GaussianBlur(radius=blur_radius))
                blur_buf = io.BytesIO()
                small.save(blur_buf, format="JPEG", quality=80)

            # A lens needs the actual pixels behind the pane. The normal
            # sharp payload contains only the transparent corner wedges.
            lens_buf = None
            if (want_blur and not self._system_glass_on(window_kind)
                    and self._cfg.get("glass_style") == "liquid"
                    and not is_popover):
                lens_buf = io.BytesIO()
                # Preserve full chroma resolution: 4:2:0 JPEG subsampling
                # can turn fine desktop patterns into coloured moire after
                # the tile lens displaces them.
                img.save(lens_buf, format="JPEG", quality=88, subsampling=0)

            # The sharp copy, cut down to the only part of it anyone ever
            # sees: the four wedges outside the card's rounded corners.
            # Packed clockwise from the top left into one 2r square.
            if corner:
                atlas = Image.new("RGB", (corner * 2, corner * 2))
                atlas.paste(img.crop((0, 0, corner, corner)), (0, 0))
                atlas.paste(img.crop((w - corner, 0, w, corner)), (corner, 0))
                atlas.paste(img.crop((0, h - corner, corner, h)), (0, corner))
                atlas.paste(
                    img.crop((w - corner, h - corner, w, h)), (corner, corner))
                img = atlas

            sharp_buf = None
            if want_sharp:
                sharp_buf = io.BytesIO()
                # JPEG, not PNG: this is a photo-like backdrop that is
                # about to be blurred, and encoding it costs ~0.4ms
                # against PNG's ~4.6ms - the difference between tracking a
                # moving wallpaper and not.
                img.save(sharp_buf, format="JPEG", quality=88, subsampling=0)
            if capture_epoch != self._capture_epoch:
                return {"skip": True, "retry_ms": 80}
            return {
                "url": ("data:image/jpeg;base64,"
                        + base64.b64encode(sharp_buf.getvalue()
                                           ).decode("ascii")
                        ) if sharp_buf else None,
                "system_glass": False,
                "blur_url": ("data:image/jpeg;base64,"
                             + base64.b64encode(blur_buf.getvalue()
                                                ).decode("ascii")
                             ) if blur_buf else None,
                "lens_url": ("data:image/jpeg;base64,"
                             + base64.b64encode(lens_buf.getvalue()).decode("ascii")
                             ) if lens_buf else None,
                "w": w,
                "h": h,
                "corner": corner,
                "hash": digest,
                # What this frame actually cost *here*. The page paces
                # itself from this rather than from its own round-trip
                # time: most of the round trip is the js bridge waiting,
                # not work, and pacing off the wall clock throttled the
                # capture to a fraction of the rate the CPU budget allows.
                "ms": (time.perf_counter() - started) * 1000.0,
            }
        except Exception:
            return None

    def _own_hwnds(self):
        out = set()
        for win in (self._window, self._popover_window, self._settings_window,
                    self._flyout_window):
            if win:
                h = _get_hwnd(win)
                if h:
                    out.add(h)
        return out

    def move_window(self, screen_x, screen_y, window_kind="main"):
        # Absolute physical screen pixels, from the page's own drag
        # handling (see startDrag in app.js). pywebview's built-in
        # drag-region support is deliberately not used: it moves the window
        # on the first mousemove after *any* mousedown on the region, with
        # no threshold, so a plain click - the way the detail popover is
        # dismissed - dragged the widget out from under the pointer. It
        # also feeds pywebview's move(), which takes logical pixels and
        # rescales them, so on a display where devicePixelRatio and the
        # OS scale disagree the window jumped rather than followed.
        window = self._window_for(window_kind)
        if not window:
            return
        hwnd = _get_hwnd(window)
        if not hwnd:
            return
        _run_on_ui_thread(
            window, lambda: _set_window_pos(
                hwnd, int(screen_x), int(screen_y)),
        )

    def get_window_pos(self, window_kind="main"):
        # Lets a window's JS convert an on-page position into an absolute
        # screen position - for open_popover above, and for dragging.
        window = self._window_for(window_kind)
        hwnd = _get_hwnd(window) if window else None
        if not hwnd:
            return {"x": 0, "y": 0}
        try:
            r = (ctypes.c_long * 4)()
            _user32.GetWindowRect(hwnd, ctypes.byref(r))
            return {"x": r[0], "y": r[1]}
        except Exception:
            return {"x": 0, "y": 0}

    # ---------------------------------------------------------------
    # internal
    # ---------------------------------------------------------------

    def _apply_capture_exclusion(self):
        """Decide, for each window, whether it is hidden from screen
        captures - which is what makes the cheap backdrop path usable.

        A window has to be hidden from capture to read the screen for its
        own backdrop, or it reads itself back in: an infinite mirror. But
        it has to be *visible* to capture for anything drawn on top of it
        to include it in theirs - and a window excluded from capture does
        not simply vanish from a screen read, it comes back black. That is
        where the black edge around the detail card came from when it was
        opened over the tray panel.

        A window is usually excluded unless another of ours overlaps it.
        Liquid mode keeps the main widget excluded even below the detail
        popover: switching its capture source changed the glass image.
        The popover instead composes the widget through compatibility
        capture. Other overlapping windows still use the normal rule.

        Only claims the mode is on if the OS actually accepted it on the
        main window - on an older build the call fails and the slower
        PrintWindow path has to keep being used, silently rather than
        showing the widget its own reflection.
        """
        # Liquid mode needs live pixels even when the user previously
        # selected native glass. Use the fast capture path in that case;
        # explicit compatibility mode still keeps its requested behavior.
        mode = self._cfg.get("glass_mode", "fast")
        wanted = mode == "fast" or (mode == "system" and
                                    self._cfg.get("glass_style") == "liquid")
        # A window being armed is already sitting at the rectangle it is
        # about to appear in - it is only the showing that has not
        # happened yet - so it counts as present here. Left out, the
        # window it is about to cover stays hidden from capture, and the
        # backdrop taken for it in that moment has a hole where that
        # window is.
        # hide() can complete after this call. Once an overlay has been
        # closed, its stale visible HWND must not keep the widget capturable
        # and make the next screen grab read the widget back into itself.
        rects = {
            kind: (_visible_rect(self._window_for(kind), kind == self._arming_kind)
                   if kind == "main" or kind in self._overlays_open
                   or kind == self._arming_kind else None)
            for kind in ("main", "flyout", "popover", "settings")
        }
        excluded = {}
        for kind, above in _WINDOWS_ABOVE.items():
            mine = rects.get(kind)
            covered = bool(mine) and any(
                rects.get(other) and _rects_overlap(mine, rects[other])
                and not (kind == "main" and other == "popover"
                         and self._cfg.get("glass_style") == "liquid")
                for other in above
            )
            excluded[kind] = wanted and not covered
        accepted = set()
        for kind in ("main", "popover", "settings", "flyout"):
            win = self._window_for(kind)
            if win:
                ok = _set_capture_exclusion(win, excluded[kind])
                if ok and excluded[kind]:
                    accepted.add(kind)
        # Which windows may read the screen for their own backdrop: the
        # ones that are not in it.
        if accepted != self._excluded_kinds:
            self._capture_epoch += 1
            self._capture_transition_until = time.monotonic() + 0.2
        self._excluded_kinds = accepted
        self._capture_excluded = bool(accepted)

    # ---- glass ----------------------------------------------------------

    # The windows DWM can do the glass for: the ones created with
    # transparent=True, which is what gives WebView2 a surface with real
    # alpha for the backdrop to show through. Settings is not one of them
    # - it is a normal focusable window with a background colour to fall
    # back on while its page loads - so it goes on painting its own.
    #
    # The tray panel is here for a second reason: it is the one window
    # that is not over the wallpaper but over whatever the user had open,
    # and a captured backdrop of that is only ever as fresh as the last
    # read. Scroll a browser behind it and the glass lagged the page by
    # however long the capture took. DWM's does not lag, because DWM is
    # what drew both.
    _SYSTEM_GLASS_KINDS = ("main", "popover", "flyout")

    def _system_glass_on(self, kind=None):
        if not (_SYSTEM_GLASS_SUPPORTED and self._cfg.get("glass_mode") == "system"
                and self._cfg.get("glass_style") != "liquid"):
            return False
        if kind is None:
            return any(self._system_glass_on(k) for k in self._SYSTEM_GLASS_KINDS)
        hwnd = _get_hwnd(self._window_for(kind))
        return bool(hwnd and self._system_glass_hwnds.get(kind) == hwnd)

    def _system_glass_status(self):
        return {k: self._system_glass_on(k) for k in self._SYSTEM_GLASS_KINDS}

    def _apply_system_glass(self, kind=None):
        desired = (_SYSTEM_GLASS_SUPPORTED and self._cfg.get("glass_mode") == "system"
                   and self._cfg.get("glass_style") != "liquid")
        before = dict(self._system_glass_hwnds)
        for k in ((kind,) if kind else self._SYSTEM_GLASS_KINDS):
            if k not in self._SYSTEM_GLASS_KINDS:
                continue
            win = self._window_for(k)
            if not win:
                continue
            self._system_glass_hwnds.pop(k, None)
            if _set_system_glass(win, desired) and desired:
                self._system_glass_hwnds[k] = _get_hwnd(win)
        if before != self._system_glass_hwnds:
            self._push_prefs()

    def debug_capturable(self, on=True):
        """Put the windows back into screen captures, for development.

        The fast glass path works by hiding them from capture, which also
        hides them from any screenshot taken to check what they look like -
        including the ones this project's own testing takes. Off unless
        HA_WIDGET_DEBUG is set in the environment, and undone by the next
        thing that touches the exclusion.
        """
        if not os.environ.get("HA_WIDGET_DEBUG"):
            return False
        for kind in ("main", "popover", "settings", "flyout"):
            win = self._window_for(kind)
            if win:
                _set_capture_exclusion(win, not on)
        return True

    def debug_eval(self, kind, script):
        """Run a script in one of the windows and hand back what it says.

        For this project's own testing only, and only when HA_WIDGET_DEBUG
        is set. It exists because QtWebEngine's devtools endpoint is not
        dependable here - it refuses connections at random - and measuring
        the page from outside is how everything in this program has been
        decided.
        """
        if not os.environ.get("HA_WIDGET_DEBUG"):
            return None
        win = self._window_for(kind)
        if not win:
            return None
        return win.evaluate_js_result(script)

    def debug_stall(self, seconds=12.0, kind="main"):
        """Block the GUI thread, on purpose, for this project's testing.

        The watchdog in qtshell.py is only worth having if it fires, and
        the thing it is meant to catch - the GUI thread going away while
        the machine wakes up - is not something that can be asked for.
        This is the same shape: a GUI thread that stops answering.
        """
        if not os.environ.get("HA_WIDGET_DEBUG"):
            return None
        win = self._window_for(kind)
        if not win:
            return None
        threading.Thread(
            target=lambda: win.run_on_ui_thread(
                lambda: time.sleep(float(seconds))),
            daemon=True,
        ).start()
        return True

    def debug_resume(self):
        """Run the resume hooks without suspending the machine."""
        if not os.environ.get("HA_WIDGET_DEBUG"):
            return None
        import qtshell
        for fn in list(qtshell._resume_hooks):
            fn()
        return True

    # ---- fading out while nobody is there --------------------------------

    def wake(self):
        """Called by the page when someone touches the widget."""
        # Held awake for a full idle period from here, rather than left to
        # the input clock: a click on the widget is a request to see it,
        # and it should not be able to fade out from under the hand that
        # asked - which is what happened when the click landed at the end
        # of a long quiet spell and the idle counter was still reading
        # minutes.
        self._woke_at = time.monotonic()
        self._off_desktop_since = 0.0
        if self._dimmed:
            self._dimmed = False
            self._push_dim()
        return True

    def _push_dim(self):
        if not self._window:
            return
        try:
            self._window.evaluate_js(
                "window.__setDimmed && window.__setDimmed(%s)"
                % ("true" if self._dimmed else "false")
            )
        except Exception:
            pass

    def _watch_for_idle(self):
        """Fade the widget down once the desktop has been out of sight for
        long enough, and bring it back when the desktop returns.

        Not on the input clock. A widget lying on the desktop is only
        worth looking at when the desktop is what you are looking at, and
        whether someone is typing says nothing about that: they can be
        busy in a browser for an hour, in which case it should fade, or
        sitting still looking straight at it, in which case it should not.
        So the thing being timed is how long something else has been in
        front, and the desktop coming back is what ends it.

        Polled once a second rather than hooked: there is no event for
        "still not the desktop", and a second either way does not matter
        for something measured in minutes.
        """
        def loop():
            while not self._dim_stop.wait(1.0):
                try:
                    if not self._cfg.get("dim_when_idle", True):
                        wanted = False
                    else:
                        after = max(
                            10, int(self._cfg.get("dim_after_sec", 120)))
                        mine = self._own_hwnds()
                        now = time.monotonic()
                        if _desktop_is_front(mine):
                            # Home. The clock stops and resets, and
                            # anything faded comes back.
                            self._off_desktop_since = 0.0
                            wanted = False
                        else:
                            if not self._off_desktop_since:
                                self._off_desktop_since = now
                            wanted = (now - self._off_desktop_since) >= after
                        # Something full screen is not a matter of time.
                        if _fullscreen_app_present(mine):
                            wanted = True
                        elif wanted and (now - self._woke_at) < after:
                            wanted = False          # asked for, recently
                    if wanted != self._dimmed:
                        self._dimmed = wanted
                        self._push_dim()
                except Exception:
                    pass

        threading.Thread(target=loop, daemon=True).start()

    def _push_prefs(self):
        """Send the current preferences to the popover window's page.

        Both windows run their own copy of app.js with their own CONFIG,
        each populated once at startup, and either can be the one that
        changes something: Settings changes zoom and the tile list, the
        detail card's edit panel changes a tile's name and icon. Without
        this the other window never hears about it - the detail card kept
        rendering at whatever zoom it booted with, and a tile renamed from
        the detail card kept its old name in the grid and in Settings.
        __applyPrefs compares before it acts, so the window that made the
        change is not disturbed by getting its own change back.
        """
        if not self._cfg.get("tiles") and self._flyout_open:
            self.hide_flyout()
        payload = json.dumps({
            "theme": self._cfg.get("theme", "auto"),
            "glass_style": self._cfg.get("glass_style", "classic"),
            "columns": self._cfg.get("columns", 4),
            "zoom": self._cfg.get("zoom", 100),
            "fixed_size": bool(self._cfg.get("fixed_size", False)),
            "fixed_width": self._cfg.get("fixed_width", 400),
            "fixed_height": self._cfg.get("fixed_height", 300),
            "lock_position": bool(self._cfg.get("lock_position", False)),
            "opacity": self._cfg.get("opacity", 100),
            "glass_mode": self._cfg.get("glass_mode", "fast"),
            "system_glass_ok": bool(_SYSTEM_GLASS_SUPPORTED),
            "system_glass_active": self._system_glass_status(),
            "panel_theme": self._cfg.get("panel_theme", "follow"),
            "sample_fps": int(self._cfg.get("sample_fps", 16)),
            "dim_when_idle": bool(self._cfg.get("dim_when_idle", True)),
            "dim_after_sec": int(self._cfg.get("dim_after_sec", 120)),
            "tiles": self._cfg.get("tiles", []),
        }, ensure_ascii=False)
        script = "window.__applyPrefs && window.__applyPrefs(%s)" % payload
        for win in (self._window, self._popover_window, self._settings_window,
                    self._flyout_window):
            if not win:
                continue
            try:
                win.evaluate_js(script)
            except Exception:
                pass

    def _push_batch(self, items):
        payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
        # Hidden pages also retain their own state for the next opening.
        for window in (self._window, self._popover_window,
                       self._flyout_window, self._settings_window):
            if not window:
                continue
            try:
                window.evaluate_js(
                    'if (typeof window.__haPushBatch === "function") window.__haPushBatch(%s)' % payload)
            except Exception:
                pass

    def _on_ha_event(self, entity_id, new_state):
        if not self._ui_ready or not self._window:
            with self._pending_lock:
                self._pending.append([entity_id, new_state])
                if len(self._pending) > 500:
                    self._pending = self._pending[-500:]
            return
        self._push_batch([[entity_id, new_state]])

    def _on_ha_status(self, connected, detail=""):
        reconnected = connected and not self._connected
        self._connected = connected
        for window in (self._window, self._popover_window,
                       self._flyout_window, self._settings_window):
            if not window or not self._ui_ready:
                continue
            try:
                window.evaluate_js(
                    'if (typeof window.__haStatus === "function") window.__haStatus(%s)' % json.dumps(bool(connected)))
            except Exception:
                pass
        if reconnected:
            self._refresh_now()

    def _on_moved(self, x, y):
        """Remember the window's position - in physical screen pixels, and
        read back from the window rather than taken from this event.

        The x/y pywebview reports here are logical pixels, divided by the
        DPI scale of whatever monitor the window is on. Restoring them
        multiplies by the scale of whatever monitor the window is created
        on, which is not the same one - so a widget parked on a 100% screen
        came back 25% further out each restart, and looked like the
        position simply was not being saved. Physical pixels are the same
        number on both sides of a restart, whatever the monitor.
        """
        hwnd = _get_hwnd(self._window) if self._window else None
        if hwnd:
            try:
                r = (ctypes.c_long * 4)()
                _user32.GetWindowRect(hwnd, ctypes.byref(r))
                x, y = r[0], r[1]
            except Exception:
                pass
        self._cfg["window_x"] = int(x)
        self._cfg["window_y"] = int(y)
        if self._move_timer:
            self._move_timer.cancel()
        self._move_timer = threading.Timer(
            0.6, lambda: cfgmod.save_config(self._cfg))
        self._move_timer.daemon = True
        self._move_timer.start()

    def _refresh_now(self):
        def go():
            wanted = {t["entity"] for t in self._cfg.get("tiles", [])}
            try:
                if not self._cfg.get("ha_token"):
                    raise RuntimeError("not configured")
                states = {s["entity_id"]: s for s in self._client.get_states()}
            except Exception as exc:
                states = {}
                self._on_ha_status(False, str(exc))
            for entity in wanted:
                self._on_ha_event(entity, states.get(entity) or {
                    "entity_id": entity, "state": "unavailable", "attributes": {},
                })
        threading.Thread(target=go, daemon=True).start()

    def _quit(self):
        try:
            self._client.stop()
        except Exception:
            pass
        try:
            if self._tray_icon:
                self._tray_icon.stop()
        except Exception:
            pass
        try:
            if self._window:
                self._window.destroy()
        except Exception:
            pass
        _compat_capture.close()
        os._exit(0)


# ---------------------------------------------------------------------
# "Start with Windows" (Run key) helper
# ---------------------------------------------------------------------

def _startup_command():
    if getattr(sys, "frozen", False):
        # An installed build is its own executable; there is no
        # interpreter to name and no script to hand it.
        return '"%s"' % sys.executable
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    return '"%s" "%s"' % (pythonw, os.path.abspath(__file__))


# ---------------------------------------------------------------------
# Keep the widget pinned behind normal windows (desktop-widget style)
# instead of stealing focus or floating above everything.
# ---------------------------------------------------------------------

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
SW_HIDE = 0
SW_SHOWNA = 8
HWND_BOTTOM = 1
HWND_TOP = 0
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010

# All native calls that touch this window's HWND - resizing, z-order,
# activation style - must be serialized. They land on whatever thread
# happens to call them (each pywebview API call gets its own thread, and
# the bottom-pin loop is a separate background thread again), and issuing
# SetWindowPos concurrently from multiple threads against the same HWND
# was observed to corrupt WebView2's resize handling badly enough that
# window.innerWidth/innerHeight would freeze at a stale value and never
# update again for the rest of the session.
_hwnd_lock = threading.Lock()


# Qt provides transparent window corners; the page clips a pre-blurred
# desktop image to its card. Fast mode reads the screen with the widget
# excluded from capture. Compatibility mode uses an isolated PrintWindow
# worker. Confirmed native DWM glass bypasses image capture entirely.


# Declared signatures for every native call below that takes an HWND. A
# window handle is pointer-sized, and ctypes defaults an undeclared
# argument to a 32-bit C int - which silently truncates any handle that
# doesn't fit, and passes garbage for arguments that aren't supplied at
# all. Declaring them once here is what makes the calls safe.
# Private WinDLL instances, deliberately not ctypes.windll.user32.
# ctypes.windll caches one shared object per DLL for the whole process,
# and the argtypes declared below live on that object's function
# attributes - so declaring them there would have changed the calls
# *pywebview* makes through the same handle. It did: pywebview's own
# move() (the window-drag path) passes None for the cx/cy it isn't using,
# which a declared c_int argument rejects, and dragging the widget started
# raising TypeError from inside pywebview.
_user32 = ctypes.WinDLL("user32")
_dwmapi = ctypes.WinDLL("dwmapi")

_user32.SetWindowPos.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, ctypes.c_uint,
]
_user32.SetWindowPos.restype = ctypes.c_int
_user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
_user32.GetWindowLongW.restype = ctypes.c_long
_user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
_user32.GetWindow.restype = ctypes.c_void_p
_user32.SetWindowLongW.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
_user32.SetWindowLongW.restype = ctypes.c_long
_user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
_user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
_user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
_user32.GetDC.argtypes = [ctypes.c_void_p]
_user32.GetDC.restype = ctypes.c_void_p
_user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
_user32.FindWindowW.restype = ctypes.c_void_p
_user32.PrintWindow.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]

_gdi32 = ctypes.WinDLL("gdi32")
_gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
_gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
_gdi32.CreateCompatibleBitmap.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
_gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
_gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_gdi32.SelectObject.restype = ctypes.c_void_p
_gdi32.BitBlt.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
]
_gdi32.GetDIBits.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
]
_gdi32.PatBlt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                            ctypes.c_int, ctypes.c_int, ctypes.c_uint]
_gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
# A region handle is pointer-sized; undeclared, ctypes would hand back a
# truncated 32-bit int and the handle would be freed from the wrong place.
_gdi32.CreateRectRgn.restype = ctypes.c_void_p
_dwmapi.DwmEnableBlurBehindWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_dwmapi.DwmEnableBlurBehindWindow.restype = ctypes.c_long
_gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
_user32.EnumChildWindows.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
_user32.EnumWindows.argtypes = [ctypes.c_void_p, ctypes.c_ssize_t]
_user32.IsIconic.argtypes = [ctypes.c_void_p]
_user32.GetClassNameW.argtypes = [
    ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
_user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
_user32.MonitorFromWindow.restype = ctypes.c_void_p
_user32.MonitorFromPoint.restype = ctypes.c_void_p
_user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint]
_user32.SetWindowDisplayAffinity.restype = ctypes.c_int
_user32.GetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]
_user32.GetWindowDisplayAffinity.restype = ctypes.c_int
_user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
_user32.GetAncestor.restype = ctypes.c_void_p
_user32.GetForegroundWindow.restype = ctypes.c_void_p
_user32.GetCursorPos.argtypes = [ctypes.c_void_p]
_dwmapi.DwmSetWindowAttribute.argtypes = [
    ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint,
]
_dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
_dwmapi.DwmExtendFrameIntoClientArea.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p]
_dwmapi.DwmExtendFrameIntoClientArea.restype = ctypes.c_long


class _MARGINS(ctypes.Structure):
    _fields_ = [
        ("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
        ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int),
    ]


_ENUM_WINDOWS_PROC = ctypes.WINFUNCTYPE(
    ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011
PW_RENDERFULLCONTENT = 0x00000002
SRCCOPY = 0x00CC0020
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class _DesktopCapture:
    """A live picture of what is behind a window, for it to use as a backdrop.

    Taken with PrintWindow(PW_RENDERFULLCONTENT) against the desktop
    rather than by reading the wallpaper file, because the wallpaper file
    is often not what is on screen: with an animated wallpaper tool
    running, SPI_GETDESKWALLPAPER returns a small placeholder image while
    the real, moving wallpaper is drawn into the desktop window.
    PrintWindow gets what is actually being drawn, animation included -
    and unlike a screen grab it renders a chosen window alone, so a window
    never ends up inside its own backdrop.

    PrintWindow always draws a window at the destination DC's origin, and
    it ignores the DC's transform: SetViewportOrgEx and SetWindowOrgEx are
    both silently disregarded, so there is no way to ask it for just the
    piece of the desktop a widget covers. (Both were tried as an
    optimisation and both produced a perfectly plausible picture of
    entirely the wrong part of the wallpaper - which is worth stating
    plainly, because "the image looks fine" does not catch it. Anything
    changed here must be checked against a real screen grab taken with the
    widget hidden.) So the whole surface is rendered and the piece we want
    is blitted out of it.

    Which surface is what makes that affordable. Progman spans the entire
    virtual desktop - 3640x1920 here, ~40ms a frame - but the shell and
    wallpaper tools put per-monitor surfaces underneath it, and rendering
    only the one the widget sits on costs proportionally less (~16ms for a
    1080x1920 monitor). _pick_surface finds the smallest descendant of
    Progman that covers the target and still renders the same thing
    Progman does; anything that comes back blank or different is skipped,
    and Progman itself is the fallback that always works.
    """

    # A candidate has to agree with Progman this closely, as a mean
    # absolute difference per byte, to be trusted. Generous on purpose:
    # an animated wallpaper moves between the two captures, so some
    # disagreement is expected. A wrong *region* scores several times this.
    _AGREE_THRESHOLD = 28

    def __init__(self):
        self._lock = threading.Lock()
        self._dc = None
        self._bmp = None
        self._size = (0, 0)
        self._out_dc = None
        self._out_bmp = None
        self._out_size = (0, 0)
        # Separate scratch for the windows drawn over the desktop: sharing
        # the desktop's would resize it away and force a fresh
        # monitor-sized bitmap on every popover frame.
        self._ov_dc = None
        self._ov_bmp = None
        self._ov_size = (0, 0)
        # (hwnd, x, y, w, h) of the surface we render
        self._surface = None
        self._original_bitmaps = {}

    # -- scratch surfaces ------------------------------------------------

    def _ensure(self, attr_dc, attr_bmp, attr_size, w, h):
        if getattr(self, attr_dc) and getattr(self, attr_size) == (w, h):
            return True
        self._release(attr_dc, attr_bmp)
        setattr(self, attr_size, (0, 0))
        screen_dc = _user32.GetDC(None)
        if not screen_dc:
            return False
        try:
            dc = _gdi32.CreateCompatibleDC(screen_dc)
            bmp = _gdi32.CreateCompatibleBitmap(screen_dc, w, h)
            if not dc or not bmp:
                if bmp:
                    _gdi32.DeleteObject(bmp)
                if dc:
                    _gdi32.DeleteDC(dc)
                return False
            original = _gdi32.SelectObject(dc, bmp)
            if not original or original == ctypes.c_void_p(-1).value:
                _gdi32.DeleteObject(bmp)
                _gdi32.DeleteDC(dc)
                return False
            self._original_bitmaps[attr_dc] = original
            setattr(self, attr_dc, dc)
            setattr(self, attr_bmp, bmp)
            setattr(self, attr_size, (w, h))
            return True
        finally:
            _user32.ReleaseDC(None, screen_dc)

    def _release(self, attr_dc, attr_bmp):
        dc, bmp = getattr(self, attr_dc), getattr(self, attr_bmp)
        original = self._original_bitmaps.pop(attr_dc, None)
        if dc and original:
            _gdi32.SelectObject(dc, original)
        if bmp:
            _gdi32.DeleteObject(bmp)
        if dc:
            _gdi32.DeleteDC(dc)
        setattr(self, attr_dc, None)
        setattr(self, attr_bmp, None)

    # -- choosing which surface to render --------------------------------

    def _candidates(self, x, y, w, h):
        """Visible descendants of Progman that fully cover the rect,
        smallest first, with Progman itself last as the fallback."""
        progman = _user32.FindWindowW("Progman", None)
        if not progman:
            return []
        found = []

        def visit(hwnd, _lparam):
            if not _user32.IsWindowVisible(hwnd):
                return 1
            r = (ctypes.c_long * 4)()
            if not _user32.GetWindowRect(hwnd, ctypes.byref(r)):
                return 1
            if r[0] <= x and r[1] <= y and r[2] >= x + w and r[3] >= y + h:
                found.append((hwnd, r[0], r[1], r[2] - r[0], r[3] - r[1]))
            return 1

        try:
            _user32.EnumChildWindows(progman, _ENUM_WINDOWS_PROC(visit), None)
        except Exception:
            found = []
        found.sort(key=lambda c: c[3] * c[4])
        r = (ctypes.c_long * 4)()
        _user32.GetWindowRect(progman, ctypes.byref(r))
        found.append((progman, r[0], r[1], r[2] - r[0], r[3] - r[1]))
        return found

    def _render(self, surface, x, y, w, h):
        """Render `surface` and return the requested rect as BGRA, or None."""
        hwnd, sx, sy, sw, sh = surface
        if not self._ensure("_dc", "_bmp", "_size", sw, sh):
            return None
        if not _user32.PrintWindow(hwnd, self._dc, PW_RENDERFULLCONTENT):
            return None
        if not self._ensure("_out_dc", "_out_bmp", "_out_size", w, h):
            return None
        if not _gdi32.PatBlt(self._out_dc, 0, 0, w, h, 0x00000042):  # BLACKNESS
            return None
        if not _gdi32.BitBlt(self._out_dc, 0, 0, w, h,
                            self._dc, x - sx, y - sy, SRCCOPY):
            return None
        return self._read_out(w, h)

    @staticmethod
    def _disagreement(a, b):
        # Sampled rather than exhaustive: this only has to tell "the same
        # view, a moment apart" from "somewhere else entirely", and those
        # are orders of magnitude apart.
        step = max(4, (len(a) // 4096) * 4)
        n = total = 0
        for i in range(0, min(len(a), len(b)), step):
            total += abs(a[i] - b[i])
            n += 1
        return (total / n) if n else 999

    def _pick_surface(self, x, y, w, h):
        # Cached until it stops covering the widget - which is what
        # happens when the widget is dragged onto another monitor, and
        # nothing else. Re-picking costs a full Progman render plus one
        # per candidate, so doing it on every move would undo the point.
        if self._surface:
            hwnd = self._surface[0]
            r = (ctypes.c_long * 4)()
            if _user32.IsWindowVisible(hwnd) and _user32.GetWindowRect(hwnd, ctypes.byref(r)) and r[0] <= x and r[1] <= y and r[2] >= x + w and r[3] >= y + h:
                return (hwnd, r[0], r[1], r[2] - r[0], r[3] - r[1])
            self._surface = None
        cands = self._candidates(x, y, w, h)
        if not cands:
            return None
        reference = self._render(cands[-1], x, y, w, h)      # Progman
        chosen = cands[-1]
        if reference:
            for cand in cands[:-1]:
                shot = self._render(cand, x, y, w, h)
                if shot and self._disagreement(shot, reference) <= self._AGREE_THRESHOLD:
                    chosen = cand
                    break
        self._surface = chosen
        return chosen

    def reset(self):
        """Throw away every cached DC and bitmap.

        They are compatible with a screen that existed when they were
        made. Waking from sleep is routinely waking to a different set of
        monitors - a laptop that slept docked, a display that renegotiated
        its mode - and a bitmap made compatible with the old one reads
        back as garbage or as nothing at all, silently. Cheap to rebuild:
        the next capture makes what it needs.
        """
        with self._lock:
            for dc, bmp in (("_dc", "_bmp"), ("_out_dc", "_out_bmp"), ("_ov_dc", "_ov_bmp")):
                self._release(dc, bmp)
            self._size = self._out_size = self._ov_size = (0, 0)
            # Which window under Progman actually holds the wallpaper is
            # also a fact about the old display arrangement.
            self._surface = None

    # -- the capture itself ----------------------------------------------

    def grab_screen(self, x, y, w, h):
        """BGRA for a screen rectangle, read straight off the composed
        desktop instead of re-rendering the wallpaper.

        Five times cheaper than the PrintWindow path (~9ms against ~45ms)
        because nothing has to be drawn for it - the pixels are already
        there. It only works because the caller has taken its own windows
        out of screen capture (see _set_capture_exclusion); without that
        this reads the widget's own backdrop back into itself.
        """
        if w <= 0 or h <= 0:
            return None
        # Only the part of the rectangle that is actually on a monitor can
        # be read, and it has to land at its own offset in the result. A
        # window dragged so a corner hangs off the screen asks for a
        # rectangle that starts outside the desktop, and BitBlt answers
        # that by sliding what it *can* read up against the corner - so
        # the backdrop came back shifted by however far off the edge the
        # window was, which is what showed at the corners.
        vx = _user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        vy = _user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        sx, sy = max(x, vx), max(y, vy)
        ex = min(x + w, vx + _user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
        ey = min(y + h, vy + _user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
        if ex <= sx or ey <= sy:
            return None
        with self._lock:
            if not self._ensure("_out_dc", "_out_bmp", "_out_size", w, h):
                return None
            # Clear pixels outside the virtual screen before blurring;
            # otherwise they contain a previous frame from this shared DC.
            if not _gdi32.PatBlt(self._out_dc, 0, 0, w, h, 0x00000042):
                return None
            screen_dc = _user32.GetDC(None)
            if not screen_dc:
                return None
            try:
                if not _gdi32.BitBlt(self._out_dc, sx - x, sy - y, ex - sx, ey - sy,
                                     screen_dc, sx, sy, SRCCOPY):
                    return None
            finally:
                _user32.ReleaseDC(None, screen_dc)
            return self._read_out(w, h)

    def _read_out(self, w, h):
        hdr = _BITMAPINFOHEADER(
            ctypes.sizeof(_BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0,
        )
        buf = ctypes.create_string_buffer(w * h * 4)
        original = self._original_bitmaps["_out_dc"]
        selected = _gdi32.SelectObject(self._out_dc, original)
        if not selected or selected == ctypes.c_void_p(-1).value:
            return None
        try:
            rows = _gdi32.GetDIBits(self._out_dc, self._out_bmp, 0, h,
                                   buf, ctypes.byref(hdr), 0)
            return buf.raw if rows == h else None
        finally:
            _gdi32.SelectObject(self._out_dc, self._out_bmp)

    def draw_over(self, hwnds, x, y, w, h):
        """Paint `hwnds` into the last grab, at their screen positions."""
        with self._lock:
            if not self._out_dc:
                return None
            for hwnd in hwnds:
                if not hwnd:
                    continue
                r = (ctypes.c_long * 4)()
                if not _user32.GetWindowRect(hwnd, ctypes.byref(r)):
                    continue
                ow, oh = r[2] - r[0], r[3] - r[1]
                if ow <= 0 or oh <= 0:
                    continue
                if not self._ensure("_ov_dc", "_ov_bmp", "_ov_size", ow, oh):
                    continue
                if not _user32.PrintWindow(hwnd, self._ov_dc, PW_RENDERFULLCONTENT):
                    continue
                _gdi32.BitBlt(
                    self._out_dc, r[0] - x, r[1] - y, ow, oh, self._ov_dc, 0, 0, SRCCOPY)
            return self._read_out(w, h)

    def grab(self, x, y, w, h, over=()):
        """BGRA bytes for the screen rectangle (x, y, w, h), or None.

        `over` is a list of HWNDs that sit above the desktop and below the
        window asking for this, drawn in that order. The detail popover
        needs it: it opens on top of the widget, so a backdrop of the
        desktop alone left the widget missing from underneath it, and the
        popover's rounded corners - which show the backdrop unblurred -
        showed desktop where the widget actually was.
        """
        if w <= 0 or h <= 0:
            return None
        with self._lock:
            surface = self._pick_surface(x, y, w, h)
            if not surface:
                return None
            raw = self._render(surface, x, y, w, h)
            if raw is None:
                # The surface we picked has gone (monitor change, wallpaper
                # tool restarted). Re-pick once rather than fail.
                self._surface = None
                surface = self._pick_surface(x, y, w, h)
                if not surface:
                    return None
                raw = self._render(surface, x, y, w, h)
            if raw is None or not over:
                return raw
            # Draw the windows that sit between the desktop and the caller
            # into the same output bitmap, then read it back again.
            for hwnd in over:
                if not hwnd:
                    continue
                r = (ctypes.c_long * 4)()
                if not _user32.GetWindowRect(hwnd, ctypes.byref(r)):
                    continue
                ow, oh = r[2] - r[0], r[3] - r[1]
                if ow <= 0 or oh <= 0:
                    continue
                if not self._ensure("_ov_dc", "_ov_bmp", "_ov_size", ow, oh):
                    continue
                if not _user32.PrintWindow(hwnd, self._ov_dc, PW_RENDERFULLCONTENT):
                    continue
                _gdi32.BitBlt(
                    self._out_dc, r[0] - x, r[1] - y, ow, oh, self._ov_dc, 0, 0, SRCCOPY)
            return self._read_out(w, h) or raw


_desktop_capture = _DesktopCapture()
_compat_capture = CaptureWorker()


def _get_hwnd(window):
    try:
        return window.hwnd()
    except Exception:
        return None


def _run_on_ui_thread(window, fn):
    """Run fn (no-arg callable) on the thread that owns this window.

    Every API call arrives on its own request thread (see _Handler in
    qtshell.py), so anything that touches a window directly -
    SetWindowPos, SetWindowLongW - has to be marshalled over or it races
    the GUI thread's own layout and paint.
    """
    try:
        return window.run_on_ui_thread(fn)
    except Exception:
        return fn()


def _set_window_rect(hwnd, x, y, w, h):
    """Set position and size together, leaving z-order alone. One call so a
    window that moves because it resized never shows up at the old place
    for a frame. Callers must already be on the UI thread.
    """
    with _hwnd_lock:
        try:
            _user32.SetWindowPos(hwnd, None, x, y, w, h,
                                 SWP_NOZORDER | SWP_NOACTIVATE)
        except Exception:
            pass


def _set_window_pos(hwnd, x, y):
    """Set the window's top-left in physical screen pixels, leaving size
    and z-order alone. Callers must already be on the UI thread.
    """
    with _hwnd_lock:
        try:
            _user32.SetWindowPos(
                hwnd, None, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
            )
        except Exception:
            pass


def _set_window_size(hwnd, w, h):
    """Set the window's physical pixel size, leaving position and z-order
    alone. Callers must already be on the UI thread (see _run_on_ui_thread).
    """
    with _hwnd_lock:
        try:
            _user32.SetWindowPos(
                hwnd, None, 0, 0, w, h, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE,
            )
        except Exception:
            pass


DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_DONOTROUND = 1
DWMWA_TRANSITIONS_FORCEDISABLED = 3
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMSBT_NONE = 1
DWMSBT_TRANSIENTWINDOW = 3          # acrylic: a blur of whatever is behind
DWMWA_BORDER_COLOR = 34
DWMWA_COLOR_NONE = 0xFFFFFFFE

# The other way to ask DWM for glass, through the undocumented accent
# policy that every Windows customisation tool uses. It is the one worth
# having, because it takes the tint as an argument: DWMWA_SYSTEMBACKDROP_TYPE
# comes with the system's own recipe, and in light mode that recipe is
# nearly white - measured on this widget, bare glass over a wallpaper at
# RGB(103,106,152) came out at (238,239,242), which is not a window you
# can see through. The same measurement with an accent tint of zero alpha
# leaves the colour where the wallpaper had it and only blurs.
WCA_ACCENT_POLICY = 19
ACCENT_ENABLE_BLURBEHIND = 3
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
ACCENT_FLAG_MODERN_ACRYLIC_RECIPE = 1 << 1      # Windows 11 22H2+
DWM_BB_ENABLE = 0x01
DWM_BB_BLURREGION = 0x02
DWM_BB_TRANSITIONONMAXIMIZED = 0x04


class _ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_uint), ("AccentFlags", ctypes.c_uint),
        ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_uint),
    ]


class _WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [
        ("Attrib", ctypes.c_uint), ("pvData", ctypes.c_void_p),
        ("cbData", ctypes.c_size_t),
    ]


class _DWM_BLURBEHIND(ctypes.Structure):
    _fields_ = [
        ("dwFlags", ctypes.c_uint), ("fEnable", ctypes.c_int),
        ("hRgnBlur", ctypes.c_void_p), ("fTransitionOnMaximized", ctypes.c_int),
    ]


_SetWindowCompositionAttribute = getattr(
    _user32, "SetWindowCompositionAttribute", None)
if _SetWindowCompositionAttribute is not None:
    _SetWindowCompositionAttribute.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p]
    _SetWindowCompositionAttribute.restype = ctypes.c_int

# Native glass remains opt-in until its appearance is verified with Qt
# across supported Windows/GPU configurations. API success is tracked per
# HWND; failures fall back to the captured background.
_SYSTEM_GLASS_SUPPORTED = (
    sys.getwindowsversion().build >= 22621
    and bool(os.environ.get("HA_WIDGET_SYSTEM_GLASS"))
)


def _set_system_glass(window, on):
    """Apply DWM glass on Qt's GUI thread; report actual API success."""
    if not _SYSTEM_GLASS_SUPPORTED:
        return False

    def _apply():
        hwnd = _get_hwnd(window)
        if not hwnd:
            return False
        with _hwnd_lock:
            def set_backdrop(value):
                v = ctypes.c_uint(value)
                return _dwmapi.DwmSetWindowAttribute(
                    hwnd, DWMWA_SYSTEMBACKDROP_TYPE, ctypes.byref(v), ctypes.sizeof(v))

            try:
                m = _MARGINS(-1, -1, -1, -1) if on else _MARGINS(0, 0, 0, 0)
                frame = _dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(m))
                backdrop = set_backdrop(DWMSBT_TRANSIENTWINDOW if on else DWMSBT_NONE)
                if frame < 0 or backdrop < 0:
                    raise OSError("DWM glass failed: frame=%s backdrop=%s" % (frame, backdrop))
                border = ctypes.c_uint(DWMWA_COLOR_NONE)
                _dwmapi.DwmSetWindowAttribute(
                    hwnd, DWMWA_BORDER_COLOR, ctypes.byref(border), ctypes.sizeof(border))
                return True
            except Exception as exc:
                webview.log(str(exc))
                # Undo partial activation before using the software backdrop.
                try:
                    set_backdrop(DWMSBT_NONE)
                    m = _MARGINS(0, 0, 0, 0)
                    _dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(m))
                except Exception:
                    pass
                return False

    return bool(window.run_on_ui_thread(_apply))


# Which of this app's windows can end up on top of which. A window has
# to come out of hiding from screen captures only for the ones above it,
# and only when one of those is actually overlapping it.
_WINDOWS_ABOVE = {
    "main": ("flyout", "popover", "settings"),
    "flyout": ("popover", "settings"),
    "popover": (),
    "settings": (),
}


def _popover_needs_compat(kind, style, excluded, below):
    return (kind == "popover" and style == "liquid"
            and "main" in excluded and bool(below))


def _grab_widget_rgba(window):
    """Capture the Qt widget with its transparent corner alpha intact."""
    if not window:
        return None

    def grab():
        from PySide6.QtGui import QImage
        pixmap = window.native.grab()
        image = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
        if image.isNull():
            return None
        r = (ctypes.c_long * 4)()
        if not _user32.GetWindowRect(_get_hwnd(window), ctypes.byref(r)):
            return None
        from PIL import Image
        rgba = Image.frombytes('RGBA', (image.width(), image.height()),
                               image.bits().tobytes(), 'raw', 'RGBA',
                               image.bytesPerLine(), 1)
        size = (r[2] - r[0], r[3] - r[1])
        if rgba.size != size:
            rgba = rgba.resize(size, Image.Resampling.BILINEAR)
        return rgba, (r[0], r[1], r[2], r[3])

    try:
        return window.run_on_ui_thread(grab)
    except Exception:
        return None


def _composite_rgba_window(base_bgra, size, layer, offset):
    """Place a translucent window over a BGRA backdrop without black corners."""
    from PIL import Image
    # GDI's fourth byte is often zero even for an opaque desktop bitmap.
    # Treat the backdrop as opaque before applying the Qt window's alpha.
    base = Image.frombytes('RGBA', size, base_bgra, 'raw', 'BGRA').convert('RGB').convert('RGBA')
    left, top = max(0, offset[0]), max(0, offset[1])
    right = min(size[0], offset[0] + layer.width)
    bottom = min(size[1], offset[1] + layer.height)
    if right > left and bottom > top:
        clipped = layer.crop((left - offset[0], top - offset[1],
                              right - offset[0], bottom - offset[1]))
        base.alpha_composite(clipped, (left, top))
    return base.tobytes('raw', 'BGRA')


def _compose_popover_backdrop(screen_bgra, popover_rect, main_frame, widget):
    """Restore pixels hidden by capture affinity, then blend the Qt widget."""
    from PIL import Image
    x, y, w, h = popover_rect
    mx, my, mw, mh, main_bgra = main_frame
    image, rect = widget
    if (abs(mx - rect[0]) > 3 or abs(my - rect[1]) > 3 or
            abs(mw - (rect[2] - rect[0])) > 3 or
            abs(mh - (rect[3] - rect[1])) > 3):
        return None
    left, top = max(x, mx), max(y, my)
    right, bottom = min(x + w, mx + mw), min(y + h, my + mh)
    if right <= left or bottom <= top:
        return screen_bgra
    base = Image.frombytes('RGBA', (w, h), screen_bgra, 'raw', 'BGRA').convert('RGB')
    main = Image.frombytes('RGBA', (mw, mh), main_bgra, 'raw', 'BGRA').convert('RGB')
    base.paste(main.crop((left - mx, top - my, right - mx, bottom - my)),
               (left - x, top - y))
    return _composite_rgba_window(base.convert('RGBA').tobytes('raw', 'BGRA'),
                                  (w, h), image, (rect[0] - x, rect[1] - y))


def _visible_rect(window, even_if_hidden=False):
    """This window's screen rectangle, or None if it is not on screen."""
    hwnd = _get_hwnd(window) if window else None
    if not hwnd or (not even_if_hidden and not _user32.IsWindowVisible(hwnd)):
        return None
    try:
        r = (ctypes.c_long * 4)()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
        return (r[0], r[1], r[2], r[3])
    except Exception:
        return None


def _rects_overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _windows_below(target, rect):
    """Visible intersecting top-level windows, in paint order."""
    found = []
    below = False

    def visit(hwnd, _):
        nonlocal below
        if hwnd == target:
            below = True
            return 1
        if not below or not _user32.IsWindowVisible(hwnd) or _user32.IsIconic(hwnd):
            return 1
        name = ctypes.create_unicode_buffer(128)
        _user32.GetClassNameW(hwnd, name, len(name))
        if name.value in ("Progman", "WorkerW"):
            return 1
        cloaked = ctypes.c_uint()
        if (_dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked),
                                        ctypes.sizeof(cloaked)) == 0 and cloaked.value):
            return 1
        bounds = (ctypes.c_long * 4)()
        if _user32.GetWindowRect(hwnd, ctypes.byref(bounds)) and _rects_overlap(rect, bounds):
            found.append(hwnd)
        return 1

    _user32.EnumWindows(_ENUM_WINDOWS_PROC(visit), 0)
    return tuple(reversed(found))


def _set_capture_exclusion(window, excluded):
    """Take this window out of (or back into) screen captures.

    With it out, reading the screen where the window is gives what is
    *behind* it, which is the cheap way to keep the frosted backdrop
    live - no re-rendering the wallpaper, ~9ms a frame instead of ~45ms.
    The cost is literal: while this is on, the widget is absent from
    screenshots and screen recordings too. That is why it is a setting
    rather than just how this works.

    Only works on windows this process owns, and only on Windows 10 2004
    and later; older builds fail the call and keep the slower path.
    """
    hwnd = _get_hwnd(window)
    if not hwnd:
        return False
    ok = [False]

    def _apply():
        with _hwnd_lock:
            try:
                desired = WDA_EXCLUDEFROMCAPTURE if excluded else WDA_NONE
                current = ctypes.c_uint()
                if (_user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(current))
                        and current.value == desired):
                    ok[0] = True
                    return
                ok[0] = bool(_user32.SetWindowDisplayAffinity(
                    hwnd, desired,
                ))
            except Exception:
                ok[0] = False

    _run_on_ui_thread(window, _apply)
    return ok[0]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("rcMonitor", ctypes.c_long * 4),
        ("rcWork", ctypes.c_long * 4),
        ("dwFlags", ctypes.c_uint32),
    ]


MONITOR_DEFAULTTONEAREST = 2


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


# Declared here rather than with the others above: these take their POINT
# by value, so the struct has to exist first.
_user32.MonitorFromPoint.argtypes = [_POINT, ctypes.c_uint]
_user32.WindowFromPoint.argtypes = [_POINT]
_user32.WindowFromPoint.restype = ctypes.c_void_p


GA_ROOT = 2


_SHELL_CLASSES = {"Progman", "WorkerW",
                  "Shell_TrayWnd", "Windows.UI.Core.CoreWindow"}


def _desktop_is_front(ours=()):
    """True when what has the user's attention is the desktop itself.

    Which is the only place a widget lying on the desktop is worth being
    at full strength for: anything else in front - a browser, an editor -
    is what the person is actually looking at.
    """
    try:
        fg = _user32.GetForegroundWindow()
        if not fg:
            return True                     # nothing in front of anything
        root = _user32.GetAncestor(fg, GA_ROOT) or fg
        if root in ours:
            return True
        buf = ctypes.create_unicode_buffer(64)
        _user32.GetClassNameW(root, buf, 64)
        return buf.value in _SHELL_CLASSES
    except Exception:
        return True


def _fullscreen_app_present(ours=()):
    """True when the foreground window covers its whole monitor.

    Games and video players, in other words - the moments when a widget
    on the desktop is both invisible and unwanted.
    """
    try:
        fg = _user32.GetForegroundWindow()
        if not fg:
            return False
        root = _user32.GetAncestor(fg, GA_ROOT) or fg
        if root in ours:
            return False
        buf = ctypes.create_unicode_buffer(64)
        _user32.GetClassNameW(root, buf, 64)
        if buf.value in _SHELL_CLASSES:
            return False
        r = (ctypes.c_long * 4)()
        if not _user32.GetWindowRect(root, ctypes.byref(r)):
            return False
        mon = _user32.MonitorFromWindow(root, MONITOR_DEFAULTTONEAREST)
        if not mon:
            return False
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not _user32.GetMonitorInfoW(mon, ctypes.byref(info)):
            return False
        m = info.rcMonitor
        return (r[0] <= m[0] and r[1] <= m[1] and r[2] >= m[2] and r[3] >= m[3])
    except Exception:
        return False


def _nothing_visible_of(hwnd, ours):
    """True when every part of this window is behind some other window.

    Sampled rather than computed: the exact answer means unioning the
    rectangles of every window above this one in z-order, and the question
    being asked is only "is there any point in painting this". A point
    counts as ours if a click there would land on one of our own windows,
    which is what WindowFromPoint answers.

    It matters because this widget is pinned to the bottom of the z-order,
    so it spends most of its life completely covered - and every frame
    captured while it is covered is a frame nobody can see.
    """
    try:
        r = (ctypes.c_long * 4)()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return False
        w, h = r[2] - r[0], r[3] - r[1]
        if w <= 0 or h <= 0:
            return False
        for fy in (0.08, 0.35, 0.65, 0.92):
            for fx in (0.04, 0.3, 0.55, 0.8, 0.96):
                pt = _POINT(int(r[0] + w * fx), int(r[1] + h * fy))
                top = _user32.WindowFromPoint(pt)
                if not top:
                    continue
                root = _user32.GetAncestor(top, GA_ROOT) or top
                if root in ours:
                    return False
        return True
    except Exception:
        return False


def _work_area_at(x, y):
    """The usable screen rectangle around a point, as (l, t, r, b)."""
    try:
        mon = _user32.MonitorFromPoint(
            _POINT(int(x), int(y)), MONITOR_DEFAULTTONEAREST)
        if not mon:
            return None
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not _user32.GetMonitorInfoW(mon, ctypes.byref(info)):
            return None
        w = info.rcWork
        return (w[0], w[1], w[2], w[3])
    except Exception:
        return None


def _place_against(start, extent, span_start, span_extent, limit_lo, limit_hi):
    """Where to put a `extent`-long box that wants to start at `start`.

    Aligned to the near edge of the thing it belongs to by default; if
    that would run past `limit_hi`, aligned to its far edge instead - the
    same flip a menu does when it reaches the bottom of the screen. Only
    if neither side fits does it give up and slide into view, because a
    popover half off-screen is worse than one slightly off its anchor.
    """
    if start + extent <= limit_hi:
        pos = start
    else:
        pos = span_start + span_extent - extent
    return max(limit_lo, min(pos, limit_hi - extent))


def _centre_on_window_monitor(anchor_window, hwnd_to_place):
    """Top-left that centres hwnd_to_place on anchor_window's monitor.

    Centred on the *widget's* screen rather than the primary one: on a
    multi-monitor desk the widget is often parked on a secondary screen,
    and having its Settings open somewhere else entirely is disorienting.
    """
    try:
        anchor = _get_hwnd(anchor_window) if anchor_window else None
        mon = _user32.MonitorFromWindow(
            anchor or hwnd_to_place, MONITOR_DEFAULTTONEAREST)
        if not mon:
            return None
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not _user32.GetMonitorInfoW(mon, ctypes.byref(info)):
            return None
        r = (ctypes.c_long * 4)()
        _user32.GetWindowRect(hwnd_to_place, ctypes.byref(r))
        w, h = r[2] - r[0], r[3] - r[1]
        work = info.rcWork
        return (
            work[0] + max(0, (work[2] - work[0] - w) // 2),
            work[1] + max(0, (work[3] - work[1] - h) // 2),
        )
    except Exception:
        return None


def _apply_window_shape(window):
    """Stop DWM rounding this window, and so stop it shadowing the window.

    The visible rounded outline is the page's, not the window's (see the
    note above) - this is purely about the shadow that comes attached to
    any DWM rounding. Windows 10 doesn't know the attribute and fails the
    call harmlessly; its windows are square anyway.

    None of this stays put. Showing the window hands the corner
    preference back to DWM's default, so this runs on every show and not
    just the first - which is why it is hung off events.showing rather
    than events.shown, and why the panel and Settings wore a border and a
    shadow the second time they were opened and not the first.
    """
    hwnd = _get_hwnd(window)
    if not hwnd:
        return

    def _apply():
        with _hwnd_lock:
            # Windows plays its own fade-and-scale over a window the first
            # time it is shown, and again on every show after a hide. For
            # the tray panel that lands on top of the page's own entrance
            # and the two fight: the system's animation is presenting
            # frames of the window while the page is still animating its
            # card, which reads as the picture warping and the panel
            # flickering. The page's animation is the one we want.
            off = ctypes.c_int(1)
            try:
                _dwmapi.DwmSetWindowAttribute(
                    hwnd, DWMWA_TRANSITIONS_FORCEDISABLED, ctypes.byref(
                        off), ctypes.sizeof(off),
                )
            except Exception:
                pass
            v = ctypes.c_int(DWMWCP_DONOTROUND)
            try:
                _dwmapi.DwmSetWindowAttribute(
                    hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(
                        v), ctypes.sizeof(v),
                )
            except Exception:
                pass
            # And no border either. Windows 11 draws its standard hairline
            # around a window while that window is active - which the
            # widget never is, but the tray panel and Settings both are,
            # so a pale rectangle appeared around their rounded cards and
            # sometimes outlasted them on screen. Every outline here is
            # the page's.
            try:
                border = ctypes.c_uint(DWMWA_COLOR_NONE)
                _dwmapi.DwmSetWindowAttribute(
                    hwnd, DWMWA_BORDER_COLOR, ctypes.byref(
                        border), ctypes.sizeof(border),
                )
            except Exception:
                pass

    _run_on_ui_thread(window, _apply)


def _set_noactivate(window, enable):
    hwnd = _get_hwnd(window)
    if not hwnd:
        return

    def _apply():
        with _hwnd_lock:
            try:
                style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                style = (style | WS_EX_NOACTIVATE) if enable else (
                    style & ~WS_EX_NOACTIVATE)
                _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            except Exception:
                pass

    _run_on_ui_thread(window, _apply)


def _hide_from_taskbar(window):
    """Nothing to do: these windows are created as tool windows (see
    qtshell.py), which is what keeps them off the taskbar and out of
    Alt-Tab. The old build had to rewrite the extended styles after the
    window existed and hide and re-show it to make them take, which is
    also what kept undoing everything else set on the window.
    """
    return


def _send_to_bottom(window):
    hwnd = _get_hwnd(window)
    if not hwnd:
        return

    def _apply():
        with _hwnd_lock:
            try:
                # GW_HWNDLAST only compares windows of the same type, so
                # a topmost window must still be demoted explicitly.
                if (not (_user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & 0x00000008)
                        and _user32.GetWindow(hwnd, 1) == hwnd):
                    return
                _user32.SetWindowPos(
                    hwnd, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
                )
            except Exception:
                pass

    _run_on_ui_thread(window, _apply)


def _bring_to_front(window, stay_on_top=False):
    hwnd = _get_hwnd(window)
    if not hwnd:
        return

    def _apply():
        with _hwnd_lock:
            try:
                # HWND_TOP is not enough for the tray panel. It cannot take
                # the foreground for itself (WS_EX_NOACTIVATE), and
                # SetForegroundWindow from a process that is not already
                # the foreground one is refused - so the window that *was*
                # in front stays in front, and the panel opens behind it.
                # Behind a maximised browser that means it is not on screen
                # at all: invisible, and skipping its backdrop every frame
                # because nothing of it can be seen.
                where = HWND_TOPMOST if stay_on_top else HWND_TOP
                _user32.SetWindowPos(hwnd, where, 0, 0, 0, 0,
                                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                _user32.SetForegroundWindow(hwnd)
            except Exception:
                pass

    _run_on_ui_thread(window, _apply)


def _drop_topmost(window):
    """Put a window back into the ordinary z-order."""
    hwnd = _get_hwnd(window)
    if not hwnd:
        return

    def _apply():
        with _hwnd_lock:
            try:
                _user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            except Exception:
                pass

    _run_on_ui_thread(window, _apply)


def _bottom_pin_loop(window, stop_event, pin_enabled):
    # A one-time SetWindowPos(HWND_BOTTOM) can still get shuffled up by
    # normal window-manager activity (things opening/closing/minimizing),
    # so keep re-asserting it at a cheap, infrequent interval instead of
    # hooking window messages. Paused while Settings is open and the
    # window has deliberately been brought forward for typing.
    while not stop_event.is_set():
        if pin_enabled.is_set():
            _send_to_bottom(window)
        stop_event.wait(2.0)


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------

def _hide_own_console():
    """Hide the console window, but only when it is ours alone.

    Double-clicking main.py (or launching it via `python main.py` from
    Explorer) gets the script its own console, and that console is a real
    taskbar button reading "python" - which is half of why this was
    showing up in the taskbar at all, the other half being the widget
    window's own WS_EX_APPWINDOW (see _hide_from_taskbar).

    GetConsoleProcessList is the discriminator: a console with only this
    process attached was created for this process and is pure noise, while
    a console shared with a shell is the terminal someone is deliberately
    running from, and closing that out from under them would hide the
    traceback they are waiting for. Launching with pythonw.exe avoids the
    console existing in the first place, which is what the "start with
    Windows" entry does (see _startup_command).
    """
    try:
        kernel32 = ctypes.windll.kernel32
        hwnd = kernel32.GetConsoleWindow()
        if not hwnd:
            return
        pids = (ctypes.c_ulong * 8)()
        count = kernel32.GetConsoleProcessList(pids, 8)
        if count == 1:
            _user32.ShowWindow(ctypes.c_void_p(hwnd), SW_HIDE)
    except Exception:
        pass


def _initial_window_size(cfg):
    if cfg.get("fixed_size"):
        w = max(120, int(cfg.get("fixed_width", 400) or 400))
        h = max(90, int(cfg.get("fixed_height", 300) or 300))
    else:
        n = len(cfg.get("tiles", []))
        if not n:
            return 300, 150
        # Match the JS grid's own column math (renderGrid in app.js): never
        # reserve more columns than there are tiles to fill them, or the
        # window opens with a dead strip on the right before the page's
        # own resize corrects it.
        cols = max(1, min(cfg.get("columns", 4), n))
        rows = math.ceil(n / cols)
        w = PAD * 2 + cols * TILE_W + (cols - 1) * GAP
        h = PAD * 2 + rows * TILE_H + (rows - 1) * GAP

    # The page renders inside a CSS `zoom`, so its tiles are not TILE_W px
    # across on screen - they are TILE_W * zoom. Leaving this out opened
    # the window at double its real size on a 50% zoom, which then visibly
    # snapped down as soon as the page measured itself.
    try:
        zoom = max(50, min(200, int(cfg.get("zoom", 100)))) / 100.0
    except Exception:
        zoom = 1.0
    return max(MIN_WINDOW_W, int(w * zoom)), max(MIN_WINDOW_H, int(h * zoom))


def main():
    _hide_own_console()

    api = Api()
    # The application and the page's own origin, before any window exists:
    # windows are loaded from that origin so the bridge is same-origin
    # (see qtshell.py).
    webview.prepare(WEB_DIR, api, log_dir=BASE_DIR)

    # Only the *first* size, used for the moment between the window
    # appearing and the page's own first syncWindowSize measuring the real
    # thing. Worth getting close anyway: whatever is wrong here is visible
    # as the window snapping to a different size right after it opens.
    init_w, init_h = _initial_window_size(api._cfg)

    window = webview.create_window(
        "HA Widgets",
        url=os.path.join(WEB_DIR, "index.html"),
        js_api=api,
        width=init_w,
        height=init_h,
        # Deliberately not the saved position: pywebview scales x/y by the
        # DPI of the monitor the window is created on, which mangles a
        # position saved on a differently-scaled monitor. on_shown puts it
        # where it belongs, in physical pixels, while it is still hidden.
        x=api._cfg.get("window_x", 200),
        y=api._cfg.get("window_y", 200),
        frameless=True,
        easy_drag=False,
        # The whole reason this build exists. A Qt window with this set
        # is genuinely see-through: measured with the window hidden and
        # shown and the two pictures subtracted, the area inside the
        # window but outside the card's rounded corner differs by zero.
        # Nothing is painted there - it *is* the desktop - so there is
        # nothing to lag behind it.
        transparent=True,
        shadow=False,
        confirm_close=False,
        # pywebview's default minimum (200x100 logical) is bigger than
        # this widget legitimately gets: a four-tile grid at 50% zoom is
        # 98 physical px tall, and MinimumSize silently held the window at
        # 125, leaving a strip of window below the content that belongs to
        # nothing. Harmless while the page was opaque, a visible band of
        # bare backdrop now that it isn't.
        min_size=(0, 0),
    )
    api._bind_window(window)
    window.events.moved += api._on_moved

    bottom_pin_stop = threading.Event()

    def on_shown():
        api._apply_capture_exclusion()
        _set_noactivate(window, True)
        # Position it before _hide_from_taskbar, which hides and re-shows
        # the window: that way the correction happens while it is hidden
        # and there is nothing to see jump.
        saved_x, saved_y = api._cfg.get("window_x"), api._cfg.get("window_y")
        if saved_x is not None and saved_y is not None:
            hwnd = _get_hwnd(window)
            if hwnd:
                _run_on_ui_thread(
                    window, lambda: _set_window_pos(
                        hwnd, int(saved_x), int(saved_y)),
                )
        _hide_from_taskbar(window)
        _send_to_bottom(window)
        # Last, and it has to be last. Everything above rewrites the
        # window's extended styles or hides and re-shows it, and DWM drops
        # a window's blur region and backdrop when that happens - so
        # applied any earlier this was being granted and then quietly
        # taken away again, and the card came back as the form's own
        # background colour: the flat near-white that looked like the
        # glass simply not being transparent.
        api._apply_system_glass()
        threading.Thread(
            target=_bottom_pin_loop, args=(
                window, bottom_pin_stop, api._pin_enabled), daemon=True,
        ).start()

    window.events.shown += on_shown
    # Every show, where on_shown is the first one only: showing a window
    # is what undoes this, so this is what has to be redone.
    window.events.showing += lambda: _apply_window_shape(window)

    def on_closing():
        api.hide_flyout()
        window.hide()
        popover_window.hide()
        settings_window.hide()
        api._desktop_visible = False
        return False  # cancel the actual close; keep running in the tray

    window.events.closing += on_closing

    # The detail popover is a second, independent top-level window (see
    # IS_POPOVER_WINDOW in app.js) rather than sharing the main widget's -
    # starts hidden, gets moved to sit over whatever tile was clicked and
    # shown on demand (Api.open_popover), then hidden again on close
    # rather than destroyed, so reopening it doesn't pay page-load cost
    # every time.
    popover_window = webview.create_window(
        "HA Widget Detail",
        url=os.path.join(WEB_DIR, "index.html") + "#popover",
        js_api=api,
        width=260,
        height=336,
        x=api._cfg.get("window_x", 200),
        y=api._cfg.get("window_y", 200),
        frameless=True,
        easy_drag=False,
        transparent=True,
        shadow=False,
        confirm_close=False,
        hidden=True,
        min_size=(0, 0),
    )
    api._bind_popover_window(popover_window)

    def on_popover_deactivate():
        # In the old shared-window design, the popover floated over a
        # visible backdrop that covered whatever of the window *wasn't*
        # the popover card - clicking that empty space closed it. Now
        # that the popover is its own window sized exactly to its own
        # card, there is no such empty space left inside it to click. The
        # native "click anywhere else" dismissal a real popup/context
        # menu gets for free comes from losing activation - Form.Deactivate
        # is a plain WinForms/.NET event, not one of pywebview's own, so
        # it's wired directly on .native rather than through window.events.
        #
        # Deactivate fires *synchronously* on the UI thread as part of
        # Windows' own WM_ACTIVATE handling. evaluate_js needs that same
        # thread's message loop to keep pumping to get its result back
        # (it's a round trip into the WebView2 control and back) - calling
        # it directly from here blocks the UI thread on a result that can
        # only ever arrive by that same thread continuing to run,
        # deadlocking the whole app (reproduced: the window became
        # permanently unresponsive the moment this fired). Dispatching to
        # a throwaway thread breaks that cycle, matching how pywebview
        # dispatches every js-to-Python call for exactly this reason (see
        # webview.util.js_bridge_call).
        def _close():
            try:
                popover_window.evaluate_js(
                    "window.closeDetail && window.closeDetail()")
            except Exception:
                pass

        threading.Thread(target=_close, daemon=True).start()

    def on_popover_shown():
        api._apply_capture_exclusion()
        _set_noactivate(popover_window, True)
        _hide_from_taskbar(popover_window)
        api._apply_system_glass()          # after the style surgery, not before
        # .native only exists once the underlying native window has
        # actually been created, which happens right before this event
        # fires - not yet at the point create_window() above returns.
        try:
            popover_window.events.deactivated += on_popover_deactivate
        except Exception:
            pass

    popover_window.events.shown += on_popover_shown
    popover_window.events.showing += lambda: _apply_window_shape(popover_window)

    # Belt and braces on `hidden=True`. pywebview force-shows (and
    # activates!) a form on *every* navigation start when the window was
    # created transparent, regardless of the `hidden` it was asked for
    # (see on_navigation_start in platforms/edgechromium.py - its own
    # comment calls it "no idea why this works"); that used to leave this
    # window sitting on screen at whatever transient size the page
    # happened to be mid-layout at. It no longer applies now that both
    # windows are opaque, but hiding once navigation has actually finished
    # costs nothing and keeps this window's "starts hidden" guarantee from
    # depending on a detail of pywebview's internals. Only needed once:
    # this window navigates exactly one time (it's reused via show/hide,
    # never re-created or re-navigated).
    popover_window.events.loaded += lambda: popover_window.hide()

    def on_popover_closing():
        popover_window.hide()
        return False  # never actually destroy it - see the comment above

    popover_window.events.closing += on_popover_closing

    # Settings: a third window on the same page (#settings). Unlike the
    # other two it is a normal, focusable window - it is full of text
    # fields - and it deliberately ignores the widget's zoom, so a widget
    # shrunk to 50% still gets readable settings.
    settings_window = webview.create_window(
        "HA Widgets Settings",
        url=os.path.join(WEB_DIR, "index.html") + "#settings",
        js_api=api,
        width=420,
        height=640,
        frameless=True,
        easy_drag=False,
        # Translucent like the other three. It used to be opaque, back
        # when the page painted its own copy of the desktop behind the
        # card and the corners were a cutout in that; the copy went when
        # the windows became see-through (see #backdrop in style.css) and
        # this was the one window that did not, which left its rounded
        # card sitting on a flat rectangle of startup colour. The panel is
        # 90% opaque in the stylesheet by design - Settings is read, not
        # glanced at - so what this buys is the corners and a hint of what
        # is behind, not a form full of wallpaper.
        transparent=True,
        shadow=False,
        confirm_close=False,
        hidden=True,
        min_size=(0, 0),
    )
    api._bind_settings_window(settings_window)

    def on_settings_shown():
        # No _set_noactivate here, unlike the other two: this window exists
        # to be typed into.
        _hide_from_taskbar(settings_window)
        api._apply_capture_exclusion()

    settings_window.events.shown += on_settings_shown
    settings_window.events.showing += lambda: _apply_window_shape(settings_window)
    settings_window.events.loaded += lambda: settings_window.hide()

    def on_settings_closing():
        settings_window.hide()
        return False        # reused, never destroyed - as with the popover

    settings_window.events.closing += on_settings_closing

    # The tray flyout: a fourth window on the same page, showing the same
    # tile grid as the desktop widget. It is focusable - it has to be, so
    # that losing focus is what dismisses it - and it starts hidden, like
    # the other two.
    flyout_window = webview.create_window(
        "HA Widgets Panel",
        url=os.path.join(WEB_DIR, "index.html") + "#flyout",
        js_api=api,
        width=init_w,
        height=init_h,
        x=200,
        y=200,
        frameless=True,
        easy_drag=False,
        transparent=True,
        shadow=False,
        confirm_close=False,
        hidden=True,
        min_size=(0, 0),
    )
    api._bind_flyout_window(flyout_window)

    def on_flyout_deactivate():
        # Click anywhere else and it goes, the way every taskbar flyout
        # does. Deactivate fires synchronously on the UI thread inside
        # Windows' own WM_ACTIVATE handling, so the actual hiding is
        # dispatched off it - see on_popover_deactivate for the deadlock
        # that calling into the webview from here causes.
        threading.Thread(target=api.dismiss_flyout, daemon=True).start()

    def on_flyout_shown():
        api._apply_capture_exclusion()
        _hide_from_taskbar(flyout_window)
        try:
            flyout_window.events.deactivated += on_flyout_deactivate
        except Exception:
            pass

    flyout_window.events.shown += on_flyout_shown
    flyout_window.events.showing += lambda: _apply_window_shape(flyout_window)
    flyout_window.events.loaded += lambda: flyout_window.hide()

    def on_flyout_closing():
        flyout_window.hide()
        return False        # reused, never destroyed - as with the others

    flyout_window.events.closing += on_flyout_closing

    def toggle_visibility(icon=None, item=None):
        api.hide_flyout()
        if api._desktop_visible:
            window.hide()
            popover_window.hide()
            settings_window.hide()
        else:
            window.show()
            api._apply_system_glass("main")
        api._desktop_visible = not api._desktop_visible

    def activate(icon=None, item=None):
        # The left click. Runs on pystray's own thread.
        api.toggle_flyout()

    def open_settings(icon=None, item=None):
        if not api._desktop_visible:
            window.show()
            api._apply_system_glass("main")
            api._desktop_visible = True
        api.open_settings_window()

    def toggle_theme(icon=None, item=None):
        order = ["light", "dark", "auto"]
        cur = api._cfg.get("theme", "auto")
        nxt = order[(order.index(cur) + 1) %
                    len(order)] if cur in order else "light"
        api._cfg["theme"] = nxt
        cfgmod.save_config(api._cfg)
        api._push_prefs()
        try:
            window.evaluate_js(
                "window.__setThemeFromTray && window.__setThemeFromTray(%s)" % json.dumps(nxt))
        except Exception:
            pass

    def refresh_now(icon=None, item=None):
        api._refresh_now()

    def quit_action(icon=None, item=None):
        api._quit()

    def on_resume():
        """Put back everything a suspend invalidates.

        Called from the watchdog thread once the machine has been away
        (see qtshell.on_resume). None of this is about the widget's state -
        that is all in the config and the websocket, which look after
        themselves - and all of it is about handles: GDI objects made
        against the old display, DWM attributes that a window may have
        been recreated without, and the capture exclusion that makes the
        whole backdrop work.
        """
        _desktop_capture.reset()
        _compat_capture.close()
        for kind in ("main", "popover", "settings", "flyout"):
            win = api._window_for(kind)
            if not win:
                continue
            try:
                _apply_window_shape(win)
            except Exception:
                pass
        try:
            api._apply_capture_exclusion()
        except Exception:
            pass
        # The websocket to Home Assistant is almost certainly dead: a TCP
        # connection that was open when the machine went to sleep is
        # usually half-open when it comes back - the other end gave up and
        # said so to nobody - and recv() on one of those blocks until the
        # OS gets bored, which is minutes. Dropping it here makes the
        # reconnect loop start over now rather than then, which is the
        # difference between tiles that are live when the screen comes on
        # and tiles that are live a few minutes later.
        try:
            api._client._kick()
        except Exception:
            pass
        # Every page is holding a backdrop of a screen that has since been
        # switched off and on again, and comparing new captures against
        # its hash. Tell them to start over.
        for kind in ("main", "popover", "settings", "flyout"):
            win = api._window_for(kind)
            if not win:
                continue
            try:
                win.evaluate_js(
                    "window.__invalidateBackdrop && window.__invalidateBackdrop()")
            except Exception:
                pass

    webview.on_resume(on_resume)

    api._watch_for_idle()

    tray_icon = build_tray_icon(activate, toggle_visibility, open_settings,
                                toggle_theme, refresh_now, quit_action)
    api._tray_icon = tray_icon
    tray_icon.run_detached()

    if os.environ.get("HA_WIDGET_DEBUG_OPEN_SETTINGS"):
        threading.Timer(3.0, open_settings).start()

    webview.start()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
