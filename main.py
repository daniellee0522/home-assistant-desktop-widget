"""
HA Desktop Widgets (Qt edition)
===============================

A borderless desktop widget that mirrors Home Assistant accessories as a
tile grid, with realtime updates over Home Assistant's WebSocket API. It
lives at the bottom of the z-order like a desktop gadget and never takes
focus away from other applications.

Four windows share one page (web/index.html) and one Api instance:

  * main     - the widget on the desktop
  * popover  - an accessory's detail card, opened by right-click or hold
  * settings - connection, appearance and tile management
  * flyout   - the tray panel, opened by clicking the tray icon

Settings are saved to ha_widgets_config.json beside this script, or under
%APPDATA%\\HA Widgets for an installed build (see config.py). Closing the
widget hides it; use the tray menu's Quit to exit.

Run:  python main.py
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
    # Must happen before Qt creates anything. Per-monitor-v2 awareness keeps
    # every Win32 coordinate below in physical pixels on mixed-DPI setups.
    try:
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

import qtshell as webview  # noqa: E402

import config as cfgmod  # noqa: E402
from ha_client import HAClient  # noqa: E402
from tray import build_tray_icon  # noqa: E402

# Frozen, bundled data lives under PyInstaller's _MEIPASS while the
# executable's own folder is BASE_DIR.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    WEB_DIR = os.path.join(getattr(sys, "_MEIPASS", BASE_DIR), "web")
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    WEB_DIR = os.path.join(BASE_DIR, "web")

# Keep in step with --tile-w/--tile-h/--gap/--pad in style.css; used only
# for the window's size before the page has measured itself.
TILE_W, TILE_H, GAP, PAD = 152, 146, 12, 20

# The smallest size any window is set to.
MIN_WINDOW_W = 80
MIN_WINDOW_H = 60

class Api:
    """Served to the pages at /api/<method> (see qtshell.py).

    Only public methods are reachable from JavaScript; anything prefixed
    with `_` is internal. Every call arrives on its own request thread, so
    anything that touches a window is marshalled onto the GUI thread.
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
        # Whether the widget is currently shown on the desktop.
        self._desktop_visible = True
        # Idle dimming state; see _watch_for_idle.
        self._dimmed = False
        self._woke_at = 0.0
        self._off_desktop_since = 0.0
        self._dim_stop = threading.Event()

        # Native DWM glass, tracked per window by the HWND it was applied to.
        self._system_glass_hwnds = {}
        # The window kinds currently excluded from screen capture: exactly
        # the ones that may read the screen for their own backdrop.
        self._excluded_kinds = set()
        # DWM applies a capture-affinity change on its next composition, so
        # frames captured across such a change are dropped.
        self._capture_epoch = 0
        self._capture_transition_until = 0.0
        # The main window's latest screen capture. A liquid-mode popover over
        # the excluded widget restores this region instead of a black hole.
        self._main_backdrop_frame = None
        # Overlay windows currently open. While any overlaps the widget, the
        # widget stays capturable so it appears in the overlay's backdrop.
        self._overlays_open = set()

        self._flyout_window = None
        self._flyout_resize_lock = threading.Lock()
        self._flyout_last_resize_seq = -1
        self._flyout_open = False
        # (work area, notification area is on the right), fixed at open:
        # the pointer is only over the tray icon at the moment of the click.
        self._flyout_anchor = None
        # The size the panel's page last asked for. A hidden window's own
        # rectangle may not have caught up with it yet.
        self._flyout_size = None
        # Activation churns while a window is being shown; a Deactivate in
        # that moment is not the user clicking away.
        self._flyout_shown_at = 0.0
        # The window, if any, that is positioned but not yet shown and is
        # taking the backdrop of where it will appear; see _arm_backdrop.
        self._arming_kind = None
        self._armed = threading.Event()

        self._popover_window = None
        self._popover_resize_lock = threading.Lock()
        # The tile the popover belongs to (x, y, w, h in physical pixels)
        # and the last real size it took; see _popover_origin.
        self._popover_anchor = None
        self._popover_size = None
        self._popover_last_resize_seq = -1

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

    def _all_windows(self):
        return [w for w in (self._window, self._popover_window,
                            self._flyout_window, self._settings_window) if w]

    # ---------------------------------------------------------------
    # JS-callable API
    # ---------------------------------------------------------------

    def _prefs(self):
        """The preferences every page renders from."""
        return {
            "theme": self._cfg.get("theme", "auto"),
            "language": self._cfg.get("language", "zh-TW"),
            "glass_style": self._cfg.get("glass_style", "classic"),
            "columns": self._cfg.get("columns", 4),
            "lock_position": bool(self._cfg.get("lock_position", False)),
            "zoom": self._cfg.get("zoom", 100),
            "fixed_size": bool(self._cfg.get("fixed_size", False)),
            "fixed_width": self._cfg.get("fixed_width", 400),
            "fixed_height": self._cfg.get("fixed_height", 300),
            "glass_mode": self._cfg.get("glass_mode", "fast"),
            "system_glass_ok": bool(_SYSTEM_GLASS_SUPPORTED),
            "system_glass_active": self._system_glass_status(),
            "panel_theme": self._cfg.get("panel_theme", "follow"),
            "sample_fps": int(self._cfg.get("sample_fps", 16)),
            "dim_when_idle": bool(self._cfg.get("dim_when_idle", True)),
            "dim_after_sec": int(self._cfg.get("dim_after_sec", 120)),
            "tiles": self._cfg.get("tiles", []),
        }

    def bootstrap(self):
        # No network I/O here, so the grid renders immediately even when
        # Home Assistant is slow or unreachable; states follow separately
        # (fetch_initial_states) and then over the websocket.
        config = self._prefs()
        config.update({
            "ha_url": self._cfg.get("ha_url", ""),
            "ha_token": self._cfg.get("ha_token", ""),
            "start_on_boot": bool(self._cfg.get("start_on_boot", False)),
        })
        return {"config": config, "connected": self._connected}

    def fetch_initial_states(self):
        tiles = self._cfg.get("tiles", [])
        if not (self._cfg.get("ha_token") and tiles):
            return {}
        states = {}
        try:
            by_id = {s.get("entity_id"): s for s in self._client.get_states()}
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

    # How each preference is validated. Pages send only the keys they
    # changed, so one window's stale copy never overwrites another's edit.
    _PREF_CLEANERS = {
        "theme": lambda v: v if v in ("auto", "light", "dark") else "auto",
        "glass_style": lambda v: v if v in ("classic", "liquid", "windows") else "classic",
        "language": lambda v: v if v in ("zh-TW", "en") else "zh-TW",
        # "follow" uses the widget's theme for the tray panel.
        "panel_theme": lambda v: v if v in ("follow", "auto", "light", "dark") else "follow",
        "columns": lambda v: max(2, min(8, int(v))),
        "lock_position": bool,
        "zoom": lambda v: max(50, min(200, int(v))),
        "fixed_size": bool,
        "fixed_width": lambda v: max(120, int(v)),
        "fixed_height": lambda v: max(90, int(v)),
        "glass_mode": lambda v: v if v in ("system", "fast", "compat") else "fast",
        # Ceiling on the backdrop sample rate; the page paces itself below it.
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
        """Recent numeric values for a sensor as [[epoch seconds, value]].

        Non-numeric samples are dropped so an `unavailable` stretch leaves a
        gap instead of a dive to zero.
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
                continue
            stamp = row.get("last_changed") or row.get("last_updated") or ""
            try:
                text = stamp.replace("Z", "+00:00")
                when = datetime.datetime.fromisoformat(text).timestamp()
            except Exception:
                continue
            points.append([when, value])
        points.sort(key=lambda p: p[0])
        # The chart is a couple of hundred pixels wide; thin the series
        # before it crosses the bridge.
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

    # Sizes arrive in physical pixels: the page multiplies its CSS size by
    # its own devicePixelRatio, which avoids a second, disagreeing DPI
    # conversion on this side.

    def resize_window(self, phys_w, phys_h, seq=None):
        self._resize_native(
            self._window, self._resize_lock, "_last_resize_seq",
            phys_w, phys_h, seq,
        )

    def resize_popover_window(self, phys_w, phys_h, seq=None):
        # Where the popover goes depends on its size, so it is placed and
        # sized in one call and never shows at the old place for a frame.
        self._resize_native(
            self._popover_window, self._popover_resize_lock, "_popover_last_resize_seq",
            phys_w, phys_h, seq, origin=self._popover_origin,
        )

    def resize_flyout_window(self, phys_w, phys_h, seq=None):
        self._flyout_size = (max(MIN_WINDOW_W, int(phys_w)),
                             max(MIN_WINDOW_H, int(phys_h)))
        # Anchored to a screen corner, so growing it moves it as well.
        self._resize_native(
            self._flyout_window, self._flyout_resize_lock, "_flyout_last_resize_seq",
            phys_w, phys_h, seq, origin=self._flyout_origin,
        )

    def resize_settings_window(self, phys_w, phys_h, seq=None):
        self._resize_native(
            self._settings_window, self._settings_resize_lock, "_settings_last_resize_seq",
            phys_w, phys_h, seq,
        )

    def _resize_native(self, window, seq_lock, seq_attr, phys_w, phys_h, seq,
                       origin=None):
        if not window:
            return
        if seq is not None:
            with seq_lock:
                if seq <= getattr(self, seq_attr):
                    # A newer resize already landed; applying this older,
                    # likely smaller size would clip content on screen.
                    return
                setattr(self, seq_attr, seq)
        hwnd = _get_hwnd(window)
        if not hwnd:
            return
        w = max(MIN_WINDOW_W, int(phys_w))
        h = max(MIN_WINDOW_H, int(phys_h))

        def apply():
            # Request threads may queue UI work out of order; recheck on
            # the owning thread.
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

    # ---- tray flyout ----------------------------------------------------

    _FLYOUT_MARGIN = 12         # what Windows leaves around its own flyouts

    def backdrop_armed(self):
        """Called by a page once the backdrop it was asked to take is
        painted - see _arm_backdrop."""
        self._armed.set()
        return True

    def _arm_backdrop(self, kind, window):
        """Have a hidden, already-positioned window capture the backdrop of
        where it is about to appear, so it does not open showing a frosted
        picture of wherever it was last time."""
        self._arming_kind = kind
        self._armed.clear()
        try:
            window.evaluate_js(
                "window.__armBackdrop && window.__armBackdrop()")
        except Exception:
            pass
        # The timeout only guards against a page that never answers.
        self._armed.wait(0.3)
        # A moment for the compositor to put that frame on the surface.
        time.sleep(0.04)
        self._arming_kind = None

    def toggle_flyout(self):
        if self._flyout_open:
            self.hide_flyout()
        else:
            self.show_flyout()

    def _place_flyout(self, window, hwnd, size):
        at = self._flyout_origin(size[0], size[1])
        if at:
            _run_on_ui_thread(
                window, lambda: _set_window_rect(
                    hwnd, at[0], at[1], size[0], size[1]),
            )

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
            rect = _window_rect(hwnd) or (0, 0, 0, 0)
            size = (rect[2] - rect[0], rect[3] - rect[1])
        self._place_flyout(window, hwnd, size)
        # It sits over whatever is on screen, so the widget below has to stay
        # capturable to appear in its backdrop.
        self._overlays_open.add("flyout")
        self._arming_kind = "flyout"
        self._apply_capture_exclusion()
        # Shown before its backdrop is armed, unlike the popover: waiting up
        # to 300ms for the page after a tray click reads as a stutter, while
        # a stale first frame lasts only a frame or two.
        try:
            window.show()
        except Exception:
            pass
        # Let Qt finish the resize and DWM compose it.
        time.sleep(0.05)
        # The size the page asked for may have landed while it was hidden.
        if self._flyout_size:
            self._place_flyout(window, hwnd, self._flyout_size)
        self._apply_capture_exclusion()
        self._apply_system_glass("flyout")
        self._flyout_shown_at = time.monotonic()
        self._watch_flyout_focus()
        self._arm_backdrop("flyout", window)
        _bring_to_front(window)
        try:
            window.evaluate_js(
                "window.__flyoutEnter && window.__flyoutEnter()")
        except Exception:
            pass

    def dismiss_flyout(self):
        """Close the panel because focus moved elsewhere.

        Ignored right after it was shown (activation churn) and when focus
        went to another of this app's windows, such as a detail card opened
        from inside the panel.
        """
        if time.monotonic() - self._flyout_shown_at < 0.5:
            return
        # The activation change is still in flight when Deactivate fires.
        time.sleep(0.12)
        try:
            if _foreground_root() in self._own_hwnds():
                return
        except Exception:
            pass
        self.hide_flyout()

    # Keep in step with .flyout-leave in style.css.
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
            # On a thread: this can be called from the GUI thread, where
            # waiting out the animation would block it.
            try:
                window.evaluate_js(
                    "window.__flyoutLeave && window.__flyoutLeave()")
            except Exception:
                pass
            time.sleep(self._FLYOUT_LEAVE_S)
            if self._flyout_open:
                return          # opened again mid-fade
            try:
                window.hide()
            except Exception:
                pass

        threading.Thread(target=fade_then_hide, daemon=True).start()

    def _watch_flyout_focus(self):
        """Backstop for the Deactivate handler in main().

        Deactivate only fires if the panel got focus in the first place,
        and SetForegroundWindow can be refused. Polls while the panel is
        open and closes it once focus is elsewhere.
        """
        def watch():
            time.sleep(0.8)          # activation is not instant
            misses = 0
            while self._flyout_open:
                if _foreground_root() in self._own_hwnds():
                    misses = 0
                else:
                    misses += 1
                    if misses >= 2:
                        self.hide_flyout()
                        return
                time.sleep(0.25)

        threading.Thread(target=watch, daemon=True).start()

    def _tray_corner(self):
        """The work area under the pointer (which is over the tray icon at
        the moment of the click), and whether the notification area is on
        its right-hand side."""
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
        """Tuck the panel into the tray corner of the work area, beside the
        taskbar rather than over it."""
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
        # Remembered for the next open, which needs a size before its page
        # reports one. The collapsed minimum is the closing animation's.
        if w > MIN_WINDOW_W and h > MIN_WINDOW_H:
            self._popover_size = (w, h)
        return (
            _place_against(x, w, x, tw or w, work[0], work[2]),
            _place_against(y, h, y, th or h, work[1], work[3]),
        )

    def open_popover(self, tile_id, screen_x, screen_y, tile_w=0, tile_h=0):
        """Show the detail card over a tile. Coordinates are physical."""
        if not self._popover_window:
            return
        hwnd = _get_hwnd(self._popover_window)
        if hwnd:
            # Anchored at the tile's top-left, flipping at screen edges.
            self._popover_anchor = (int(screen_x), int(
                screen_y), int(tile_w), int(tile_h))
            # The window is still collapsed from its last close, so place it
            # with the last known size; resize_popover_window corrects it
            # once the page reports the real one.
            guess = self._popover_size
            if guess:
                at = self._popover_origin(guess[0], guess[1])
                if at:
                    screen_x, screen_y = at
            _run_on_ui_thread(
                self._popover_window,
                lambda: _set_window_pos(hwnd, int(screen_x), int(screen_y)),
            )
        # Registered before applying exclusions: the popover must be excluded
        # from capture (or it reads itself back in) and the widget below it
        # must stay capturable to appear in its backdrop.
        self._overlays_open.add("popover")
        self._arming_kind = "popover"
        self._apply_capture_exclusion()
        # Render the card, let it settle its size and place, and take the
        # backdrop there - all while the window is still hidden.
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
        # Its entrance played while hidden; replay it now that it is visible.
        try:
            self._popover_window.evaluate_js(
                "window.__popoverEnter && window.__popoverEnter()")
        except Exception:
            pass

    def open_settings_window(self):
        """Bring up Settings, centred on the widget's monitor."""
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
        # Forget the tile: the page shrinks the hidden window on the way out,
        # and that resize must not move it.
        self._popover_anchor = None
        self._overlays_open.discard("popover")
        self._apply_capture_exclusion()

    def set_popover_activatable(self, enabled):
        if self._popover_window:
            _set_noactivate(self._popover_window, not enabled)
            if enabled:
                _bring_to_front(self._popover_window)
        return True

    def get_desktop_backdrop(self, window_kind="main", last_hash=None, want_w=0, want_h=0,
                             at_x=None, at_y=None):
        """The desktop behind a window, blurred, as base64 JPEG data URLs.

        `last_hash` is the page's previous frame; an identical capture is
        answered with {"unchanged": True} and costs no encoding.
        `want_w`/`want_h` are the device-pixel size the page will draw at,
        used when it differs from the window by more than rounding (fixed
        size, zoom). `at_x`/`at_y` capture where a dragged window is going
        rather than where it still is.
        """
        is_popover = window_kind == "popover"
        window = self._window_for(window_kind)
        if not window:
            return None
        hwnd = _get_hwnd(window)
        if not hwnd:
            return None
        # Nothing to paint for a window that is hidden or fully covered -
        # which is most of the time, and most of the program's idle cost. A
        # window being armed is the exception (see _arm_backdrop).
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
                try:
                    x, y = int(at_x), int(at_y)
                except Exception:
                    pass
            if want_w and want_h:
                want_w, want_h = max(1, int(want_w)), max(1, int(want_h))
                # Within a few pixels the page's viewport arithmetic is just
                # rounding, and the window's real size is the accurate one.
                if abs(want_w - w) > 3 or abs(want_h - h) > 3:
                    w, h = want_w, want_h
            # Our own windows beneath an overlay, to draw into its backdrop.
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
            # A window may read the screen only while it is excluded from
            # capture, or it reads itself back in. Toggling the exclusion
            # around each read does not work: DWM applies it on its next
            # composition.
            can_read_screen = window_kind in self._excluded_kinds
            # A liquid-mode popover over the (still excluded) widget composes
            # the widget itself; see _apply_capture_exclusion.
            compose_widget = _popover_needs_compat(
                window_kind, self._cfg.get("glass_style"), self._excluded_kinds, over)
            if compose_widget:
                can_read_screen = False
            if window_kind == "flyout" and not can_read_screen:
                # Compatibility mode cannot read a screen containing itself;
                # render the windows beneath the panel over the wallpaper.
                over = _windows_below(hwnd, (x, y, x + w, y + h))
            from PIL import Image, ImageFilter
            widget = None
            raw = _desktop_capture.grab_screen(
                x, y, w, h) if can_read_screen or compose_widget else None
            if raw and compose_widget:
                widget = _grab_widget_rgba(self._window)
                frame = self._main_backdrop_frame
                raw = (_compose_popover_backdrop(raw, (x, y, w, h), frame, widget)
                       if frame and widget else None)
            if raw is None:
                # The fast path is off, unusable here, or failed.
                main_hwnd = _get_hwnd(self._window)
                raw = _compat_capture.grab(x, y, w, h,
                                           tuple(o for o in over if o != main_hwnd)
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
            # Decode BGRA straight to RGB, which both encoders need.
            img = Image.frombytes("RGB", (w, h), raw, "raw", "BGRX")

            # Blurred here at quarter scale (~1ms) rather than by the page:
            # a CSS backdrop-filter repainted the whole window on the GPU
            # every frame and doubled the cost of each capture.
            small = img.resize(
                (max(1, w // 4), max(1, h // 4)), Image.BILINEAR)
            # Blurring the source avoids the dark wedges a canvas blur leaves
            # in rounded corners by sampling past its edges.
            blur_radius = (0.75 if self._cfg.get("glass_style") == "liquid"
                           and not is_popover else 4)
            small = small.filter(ImageFilter.GaussianBlur(radius=blur_radius))
            blur_buf = io.BytesIO()
            small.save(blur_buf, format="JPEG", quality=80)

            # The liquid lens refracts the actual pixels behind the pane.
            lens_buf = None
            if self._cfg.get("glass_style") == "liquid" and not is_popover:
                lens_buf = io.BytesIO()
                # Full chroma: 4:2:0 subsampling turns fine patterns into
                # coloured moire once the lens displaces them.
                img.save(lens_buf, format="JPEG", quality=88, subsampling=0)

            if capture_epoch != self._capture_epoch:
                return {"skip": True, "retry_ms": 80}
            return {
                "system_glass": False,
                "blur_url": _jpeg_data_url(blur_buf),
                "lens_url": _jpeg_data_url(lens_buf) if lens_buf else None,
                "w": w,
                "h": h,
                "hash": digest,
                # The capture's own cost; the page paces itself from this
                # rather than from the bridge round trip.
                "ms": (time.perf_counter() - started) * 1000.0,
            }
        except Exception:
            return None

    def _own_hwnds(self):
        return {h for h in (_get_hwnd(w) for w in self._all_windows()) if h}

    def move_window(self, screen_x, screen_y, window_kind="main"):
        # Physical screen pixels from the page's own drag handling (see
        # installWindowDrag in app.js).
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
        # Lets a page convert on-page positions into screen positions.
        window = self._window_for(window_kind)
        hwnd = _get_hwnd(window) if window else None
        rect = _window_rect(hwnd) if hwnd else None
        if not rect:
            return {"x": 0, "y": 0}
        return {"x": rect[0], "y": rect[1]}

    # ---------------------------------------------------------------
    # internal
    # ---------------------------------------------------------------

    def _apply_capture_exclusion(self):
        """Decide, for each window, whether it is hidden from screen capture.

        A window must be excluded to read the screen for its own backdrop,
        or it reads itself back in. But an excluded window comes back black
        in anything captured on top of it, so a window is left capturable
        while another of ours overlaps it. Liquid mode keeps the widget
        excluded below the popover (switching its capture source changed
        the glass); the popover composes the widget itself instead.

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
        if accepted != self._excluded_kinds:
            self._capture_epoch += 1
            self._capture_transition_until = time.monotonic() + 0.2
        self._excluded_kinds = accepted

    # ---- glass ----------------------------------------------------------

    # Windows DWM may draw glass for. Settings keeps painting its own: it
    # is meant to be read, with a mostly opaque panel.
    _SYSTEM_GLASS_KINDS = ("main", "popover", "flyout")

    def _system_glass_wanted(self):
        return (_SYSTEM_GLASS_SUPPORTED and self._cfg.get("glass_mode") == "system"
                and self._cfg.get("glass_style") != "liquid")

    def _system_glass_on(self, kind=None):
        if not self._system_glass_wanted():
            return False
        if kind is None:
            return any(self._system_glass_on(k) for k in self._SYSTEM_GLASS_KINDS)
        hwnd = _get_hwnd(self._window_for(kind))
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
            if _set_system_glass(win, desired) and desired:
                self._system_glass_hwnds[k] = _get_hwnd(win)
        if before != self._system_glass_hwnds:
            self._push_prefs()

    # ---- dimming while the desktop is out of sight ------------------------

    def wake(self):
        """Called by the page when someone touches the widget."""
        # Held awake for a full idle period from here, so a click cannot be
        # answered by fading out from under the hand that made it.
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
        """Dim the widget once the desktop has been out of sight for
        dim_after_sec (immediately for a full-screen app), and restore it
        when the desktop comes back. Timed on what is in front, not on
        input: someone busy in a browser is not looking at the widget."""
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
                            self._off_desktop_since = 0.0
                            wanted = False
                        else:
                            if not self._off_desktop_since:
                                self._off_desktop_since = now
                            wanted = (now - self._off_desktop_since) >= after
                        if _fullscreen_app_present(mine):
                            wanted = True
                        elif wanted and (now - self._woke_at) < after:
                            wanted = False          # woken recently
                    if wanted != self._dimmed:
                        self._dimmed = wanted
                        self._push_dim()
                except Exception:
                    pass

        threading.Thread(target=loop, daemon=True).start()

    # ---- pushing to the pages ---------------------------------------------

    def _eval_all(self, script):
        for window in self._all_windows():
            try:
                window.evaluate_js(script)
            except Exception:
                pass

    def _push_prefs(self):
        """Send the current preferences to every page.

        Each window runs its own copy of app.js with its own CONFIG, and any
        of them can change something. __applyPrefs compares before acting,
        so the window that made the change is not disturbed.
        """
        if not self._cfg.get("tiles") and self._flyout_open:
            self.hide_flyout()
        payload = json.dumps(self._prefs(), ensure_ascii=False)
        self._eval_all("window.__applyPrefs && window.__applyPrefs(%s)" % payload)

    def _push_batch(self, items):
        # Hidden pages keep their state too, ready for their next opening.
        payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
        self._eval_all(
            'if (typeof window.__haPushBatch === "function") window.__haPushBatch(%s)' % payload)

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
        if self._ui_ready:
            self._eval_all(
                'if (typeof window.__haStatus === "function") window.__haStatus(%s)' % json.dumps(bool(connected)))
        if reconnected:
            self._refresh_now()

    def _on_moved(self, x, y):
        """Remember the widget's position in physical pixels, read back from
        the window: the event's logical pixels depend on the monitor's DPI
        and would drift across restarts on mixed-DPI setups."""
        rect = _window_rect(_get_hwnd(self._window)) if self._window else None
        if rect:
            x, y = rect[0], rect[1]
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


def _jpeg_data_url(buf):
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _startup_command():
    """The command line for the "start with Windows" Run key."""
    if getattr(sys, "frozen", False):
        return '"%s"' % sys.executable
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    return '"%s" "%s"' % (pythonw, os.path.abspath(__file__))


# ---------------------------------------------------------------------
# Win32
# ---------------------------------------------------------------------

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOPMOST = 0x00000008
SW_HIDE = 0
HWND_BOTTOM = 1
HWND_TOP = 0
GW_HWNDLAST = 1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010

# Serialises every native call that repositions or restyles one of our
# windows. Concurrent SetWindowPos calls against the same HWND from several
# threads have corrupted the web view's resize handling before.
_hwnd_lock = threading.Lock()

# Private WinDLL instances rather than ctypes.windll, so the argtypes
# declared here cannot change calls other libraries make through the shared
# handles. HWNDs are pointer-sized; undeclared, ctypes would truncate them.
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
_dwmapi.DwmGetWindowAttribute.argtypes = [
    ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint,
]
_dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
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
BLACKNESS = 0x00000042
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
    """Screen and wallpaper capture into reusable GDI bitmaps.

    grab_screen reads the composed screen (fast; the caller's windows must
    be excluded from capture). grab renders the wallpaper with
    PrintWindow(PW_RENDERFULLCONTENT) instead, which also catches animated
    wallpaper drawn into the desktop window.

    PrintWindow always draws at the destination's origin and ignores DC
    transforms, so a whole surface is rendered and the wanted rectangle
    blitted out of it. Progman spans the entire virtual desktop, so
    _pick_surface looks for the smallest descendant that covers the target
    and renders the same picture, falling back to Progman itself.
    """

    # Mean absolute difference per byte below which a candidate surface
    # agrees with Progman. Animated wallpaper moves between the two renders;
    # a wrong region scores several times this.
    _AGREE_THRESHOLD = 28

    def __init__(self):
        self._lock = threading.Lock()
        self._dc = None
        self._bmp = None
        self._size = (0, 0)
        self._out_dc = None
        self._out_bmp = None
        self._out_size = (0, 0)
        # Separate scratch for windows drawn over the desktop, so it never
        # forces the monitor-sized surface bitmap to be reallocated.
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
            r = _window_rect(hwnd)
            if r and _covers(r, x, y, w, h):
                found.append((hwnd, r[0], r[1], r[2] - r[0], r[3] - r[1]))
            return 1

        try:
            _user32.EnumChildWindows(progman, _ENUM_WINDOWS_PROC(visit), None)
        except Exception:
            found = []
        found.sort(key=lambda c: c[3] * c[4])
        r = _window_rect(progman) or (0, 0, 0, 0)
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
        if not _gdi32.PatBlt(self._out_dc, 0, 0, w, h, BLACKNESS):
            return None
        if not _gdi32.BitBlt(self._out_dc, 0, 0, w, h,
                             self._dc, x - sx, y - sy, SRCCOPY):
            return None
        return self._read_out(w, h)

    @staticmethod
    def _disagreement(a, b):
        # Sampled: this only has to tell "the same view, a moment apart"
        # from "somewhere else entirely".
        step = max(4, (len(a) // 4096) * 4)
        n = total = 0
        for i in range(0, min(len(a), len(b)), step):
            total += abs(a[i] - b[i])
            n += 1
        return (total / n) if n else 999

    def _pick_surface(self, x, y, w, h):
        # Cached until it stops covering the target (the widget moved to
        # another monitor); re-picking renders every candidate.
        if self._surface:
            hwnd = self._surface[0]
            r = _window_rect(hwnd) if _user32.IsWindowVisible(hwnd) else None
            if r and _covers(r, x, y, w, h):
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
        """Throw away every cached DC, bitmap and surface choice.

        They belong to the display configuration they were made for, which
        routinely changes across a suspend. The next capture rebuilds them.
        """
        with self._lock:
            for dc, bmp in (("_dc", "_bmp"), ("_out_dc", "_out_bmp"), ("_ov_dc", "_ov_bmp")):
                self._release(dc, bmp)
            self._size = self._out_size = self._ov_size = (0, 0)
            self._surface = None

    # -- the capture itself ----------------------------------------------

    def grab_screen(self, x, y, w, h):
        """BGRA for a screen rectangle, read straight off the composed
        desktop (~9ms against ~45ms for PrintWindow). The caller's windows
        must be excluded from capture (see _set_capture_exclusion)."""
        if w <= 0 or h <= 0:
            return None
        # Only the on-screen part can be read, and it has to land at its
        # own offset: BitBlt would slide it against the corner instead.
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
            # Clear off-screen pixels left from a previous frame.
            if not _gdi32.PatBlt(self._out_dc, 0, 0, w, h, BLACKNESS):
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

    def _paint_windows(self, hwnds, x, y):
        """Render `hwnds` into the output bitmap at their screen positions."""
        for hwnd in hwnds:
            r = _window_rect(hwnd) if hwnd else None
            if not r:
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

    def grab(self, x, y, w, h, over=()):
        """BGRA for the wallpaper under (x, y, w, h), or None.

        `over` lists windows between the desktop and the caller, drawn in
        that order - e.g. the widget beneath a detail popover.
        """
        if w <= 0 or h <= 0:
            return None
        with self._lock:
            surface = self._pick_surface(x, y, w, h)
            if not surface:
                return None
            raw = self._render(surface, x, y, w, h)
            if raw is None:
                # The surface has gone (monitor change, wallpaper tool
                # restarted). Re-pick once rather than fail.
                self._surface = None
                surface = self._pick_surface(x, y, w, h)
                if not surface:
                    return None
                raw = self._render(surface, x, y, w, h)
            if raw is None or not over:
                return raw
            self._paint_windows(over, x, y)
            return self._read_out(w, h) or raw


_desktop_capture = _DesktopCapture()
_compat_capture = CaptureWorker()


def _get_hwnd(window):
    try:
        return window.hwnd()
    except Exception:
        return None


def _run_on_ui_thread(window, fn):
    """Run fn on the thread that owns this window, and wait for it."""
    try:
        return window.run_on_ui_thread(fn)
    except Exception:
        return fn()


def _window_rect(hwnd):
    """(left, top, right, bottom) of a window, or None."""
    try:
        r = (ctypes.c_long * 4)()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
        return (r[0], r[1], r[2], r[3])
    except Exception:
        return None


def _covers(rect, x, y, w, h):
    return rect[0] <= x and rect[1] <= y and rect[2] >= x + w and rect[3] >= y + h


def _class_name(hwnd, size=64):
    buf = ctypes.create_unicode_buffer(size)
    _user32.GetClassNameW(hwnd, buf, size)
    return buf.value


def _set_window_pos_raw(hwnd, x, y, w, h, flags):
    """SetWindowPos without touching z-order. GUI thread only."""
    with _hwnd_lock:
        try:
            _user32.SetWindowPos(hwnd, None, x, y, w, h,
                                 flags | SWP_NOZORDER | SWP_NOACTIVATE)
        except Exception:
            pass


def _set_window_rect(hwnd, x, y, w, h):
    # Position and size in one call, so a window that moves because it
    # resized never shows at the old place for a frame.
    _set_window_pos_raw(hwnd, x, y, w, h, 0)


def _set_window_pos(hwnd, x, y):
    _set_window_pos_raw(hwnd, x, y, 0, 0, SWP_NOSIZE)


def _set_window_size(hwnd, w, h):
    _set_window_pos_raw(hwnd, 0, 0, w, h, SWP_NOMOVE)


DWMWA_TRANSITIONS_FORCEDISABLED = 3
DWMWA_CLOAKED = 14
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMWCP_DONOTROUND = 1
DWMWA_COLOR_NONE = 0xFFFFFFFE
DWMSBT_NONE = 1
DWMSBT_TRANSIENTWINDOW = 3          # acrylic: a blur of whatever is behind

# Native DWM glass is opt-in (HA_WIDGET_SYSTEM_GLASS) until its appearance
# is verified with Qt across Windows/GPU configurations. Success is tracked
# per HWND; failures fall back to the captured backdrop.
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


# Which of this app's windows can end up on top of which.
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
        r = _window_rect(_get_hwnd(window))
        if not r:
            return None
        from PIL import Image
        rgba = Image.frombytes('RGBA', (image.width(), image.height()),
                               image.bits().tobytes(), 'raw', 'RGBA',
                               image.bytesPerLine(), 1)
        size = (r[2] - r[0], r[3] - r[1])
        if rgba.size != size:
            rgba = rgba.resize(size, Image.Resampling.BILINEAR)
        return rgba, r

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
    return _window_rect(hwnd)


def _rects_overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _windows_below(target, rect):
    """Visible top-level windows below `target` that intersect `rect`, in
    paint order (bottom first)."""
    found = []
    below = False

    def visit(hwnd, _):
        nonlocal below
        if hwnd == target:
            below = True
            return 1
        if not below or not _user32.IsWindowVisible(hwnd) or _user32.IsIconic(hwnd):
            return 1
        if _class_name(hwnd, 128) in ("Progman", "WorkerW"):
            return 1
        cloaked = ctypes.c_uint()
        if (_dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked),
                                          ctypes.sizeof(cloaked)) == 0 and cloaked.value):
            return 1
        bounds = _window_rect(hwnd)
        if bounds and _rects_overlap(rect, bounds):
            found.append(hwnd)
        return 1

    _user32.EnumWindows(_ENUM_WINDOWS_PROC(visit), 0)
    return tuple(reversed(found))


def _set_capture_exclusion(window, excluded):
    """Take this window out of (or back into) screen captures.

    While excluded, reading the screen where the window is returns what is
    behind it - the cheap way to keep the backdrop live. The window is also
    missing from screenshots and recordings, which is why compatibility
    mode exists. Requires Windows 10 2004 or later.
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


# These take a POINT by value, so they are declared after the struct.
_user32.MonitorFromPoint.argtypes = [_POINT, ctypes.c_uint]
_user32.WindowFromPoint.argtypes = [_POINT]
_user32.WindowFromPoint.restype = ctypes.c_void_p


GA_ROOT = 2


_SHELL_CLASSES = {"Progman", "WorkerW",
                  "Shell_TrayWnd", "Windows.UI.Core.CoreWindow"}


def _monitor_info(mon):
    if not mon:
        return None
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
    if not _user32.GetMonitorInfoW(mon, ctypes.byref(info)):
        return None
    return info


def _foreground_root():
    """The top-level window that has the foreground, or None."""
    fg = _user32.GetForegroundWindow()
    if not fg:
        return None
    return _user32.GetAncestor(fg, GA_ROOT) or fg


def _desktop_is_front(ours=()):
    """True when the desktop itself (or one of our windows) has the user's
    attention."""
    try:
        root = _foreground_root()
        if not root or root in ours:
            return True
        return _class_name(root) in _SHELL_CLASSES
    except Exception:
        return True


def _fullscreen_app_present(ours=()):
    """True when the foreground window covers its whole monitor."""
    try:
        root = _foreground_root()
        if not root or root in ours or _class_name(root) in _SHELL_CLASSES:
            return False
        r = _window_rect(root)
        info = _monitor_info(
            _user32.MonitorFromWindow(root, MONITOR_DEFAULTTONEAREST)) if r else None
        if not info:
            return False
        m = info.rcMonitor
        return (r[0] <= m[0] and r[1] <= m[1] and r[2] >= m[2] and r[3] >= m[3])
    except Exception:
        return False


def _nothing_visible_of(hwnd, ours):
    """True when every sampled point of this window is covered by some
    window other than ours. The widget sits at the bottom of the z-order,
    so it is usually covered, and a covered frame need not be captured."""
    try:
        r = _window_rect(hwnd)
        if not r:
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
        info = _monitor_info(_user32.MonitorFromPoint(
            _POINT(int(x), int(y)), MONITOR_DEFAULTTONEAREST))
        if not info:
            return None
        w = info.rcWork
        return (w[0], w[1], w[2], w[3])
    except Exception:
        return None


def _place_against(start, extent, span_start, span_extent, limit_lo, limit_hi):
    """Where to put an `extent`-long box that wants to start at `start`.

    Aligned to the near edge of its anchor, or to the far edge if that would
    run past `limit_hi` (the way a menu flips at the bottom of the screen),
    and finally clamped into view.
    """
    if start + extent <= limit_hi:
        pos = start
    else:
        pos = span_start + span_extent - extent
    return max(limit_lo, min(pos, limit_hi - extent))


def _centre_on_window_monitor(anchor_window, hwnd_to_place):
    """Top-left that centres hwnd_to_place in anchor_window's work area."""
    try:
        anchor = _get_hwnd(anchor_window) if anchor_window else None
        info = _monitor_info(_user32.MonitorFromWindow(
            anchor or hwnd_to_place, MONITOR_DEFAULTTONEAREST))
        if not info:
            return None
        r = _window_rect(hwnd_to_place) or (0, 0, 0, 0)
        w, h = r[2] - r[0], r[3] - r[1]
        work = info.rcWork
        return (
            work[0] + max(0, (work[2] - work[0] - w) // 2),
            work[1] + max(0, (work[3] - work[1] - h) // 2),
        )
    except Exception:
        return None


def _apply_window_shape(window):
    """Turn off DWM's rounding, border and show animation for a window.

    Every outline and animation here is the page's own; DWM's rounding also
    brings a shadow. Showing a window restores DWM's defaults, so this runs
    on every show (events.showing). Windows 10 ignores these attributes.
    """
    hwnd = _get_hwnd(window)
    if not hwnd:
        return

    def _apply():
        with _hwnd_lock:
            for attr, value in (
                    (DWMWA_TRANSITIONS_FORCEDISABLED, ctypes.c_int(1)),
                    (DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.c_int(DWMWCP_DONOTROUND)),
                    (DWMWA_BORDER_COLOR, ctypes.c_uint(DWMWA_COLOR_NONE))):
                try:
                    _dwmapi.DwmSetWindowAttribute(
                        hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
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


def _send_to_bottom(window):
    hwnd = _get_hwnd(window)
    if not hwnd:
        return

    def _apply():
        with _hwnd_lock:
            try:
                # GW_HWNDLAST only compares windows of the same type, so
                # a topmost window must still be demoted explicitly.
                if (not (_user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)
                        and _user32.GetWindow(hwnd, GW_HWNDLAST) == hwnd):
                    return
                _user32.SetWindowPos(
                    hwnd, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
                )
            except Exception:
                pass

    _run_on_ui_thread(window, _apply)


def _bring_to_front(window):
    hwnd = _get_hwnd(window)
    if not hwnd:
        return

    def _apply():
        with _hwnd_lock:
            try:
                _user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0,
                                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                _user32.SetForegroundWindow(hwnd)
            except Exception:
                pass

    _run_on_ui_thread(window, _apply)


def _bottom_pin_loop(window, stop_event):
    # Normal window-manager activity can shuffle the widget up again, so
    # re-assert the bottom position at a cheap interval.
    while not stop_event.is_set():
        _send_to_bottom(window)
        stop_event.wait(2.0)


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------

def _hide_own_console():
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
        # Same column math as renderGrid in app.js.
        cols = max(1, min(cfg.get("columns", 4), n))
        rows = math.ceil(n / cols)
        w = PAD * 2 + cols * TILE_W + (cols - 1) * GAP
        h = PAD * 2 + rows * TILE_H + (rows - 1) * GAP

    # The page renders inside a CSS zoom.
    try:
        zoom = max(50, min(200, int(cfg.get("zoom", 100)))) / 100.0
    except Exception:
        zoom = 1.0
    return max(MIN_WINDOW_W, int(w * zoom)), max(MIN_WINDOW_H, int(h * zoom))


def _create_overlay_window(api, title, role, width, height, **kw):
    """A hidden, reusable window for the page in `role`."""
    window = webview.create_window(
        title,
        url=os.path.join(WEB_DIR, "index.html") + "#" + role,
        js_api=api,
        width=width,
        height=height,
        transparent=True,
        hidden=True,
        **kw,
    )
    window.events.showing += lambda: _apply_window_shape(window)
    # A reloaded page (e.g. after a renderer crash) has lost its view
    # state; keep the window hidden until it is asked for again.
    window.events.loaded += lambda: window.hide()

    def on_closing():
        window.hide()
        return False        # reused, never destroyed

    window.events.closing += on_closing
    return window


def main():
    _hide_own_console()

    api = Api()
    webview.prepare(WEB_DIR, api, log_dir=BASE_DIR)

    # Only the size until the page's first measurement; close is better.
    init_w, init_h = _initial_window_size(api._cfg)

    window = webview.create_window(
        "HA Widgets",
        url=os.path.join(WEB_DIR, "index.html"),
        js_api=api,
        width=init_w,
        height=init_h,
        # Qt scales these by the creation monitor's DPI; on_shown restores
        # the saved position in physical pixels.
        x=api._cfg.get("window_x", 200),
        y=api._cfg.get("window_y", 200),
        transparent=True,
    )
    api._bind_window(window)
    window.events.moved += api._on_moved

    bottom_pin_stop = threading.Event()

    def on_shown():
        api._apply_capture_exclusion()
        _set_noactivate(window, True)
        saved_x, saved_y = api._cfg.get("window_x"), api._cfg.get("window_y")
        if saved_x is not None and saved_y is not None:
            hwnd = _get_hwnd(window)
            if hwnd:
                _run_on_ui_thread(
                    window, lambda: _set_window_pos(
                        hwnd, int(saved_x), int(saved_y)),
                )
        _send_to_bottom(window)
        # Last: DWM drops a window's backdrop when its styles change.
        api._apply_system_glass()
        threading.Thread(
            target=_bottom_pin_loop, args=(window, bottom_pin_stop), daemon=True,
        ).start()

    window.events.shown += on_shown
    window.events.showing += lambda: _apply_window_shape(window)

    popover_window = _create_overlay_window(
        api, "HA Widget Detail", "popover", 260, 336,
        x=api._cfg.get("window_x", 200), y=api._cfg.get("window_y", 200))
    api._bind_popover_window(popover_window)

    def on_popover_deactivate():
        # Clicking anywhere else closes the card. Deactivate fires on the GUI
        # thread, so the page is called from another one.
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
        api._apply_system_glass()

    popover_window.events.shown += on_popover_shown
    popover_window.events.deactivated += on_popover_deactivate

    # Settings is focusable (it has text fields) and ignores the widget's
    # zoom.
    settings_window = _create_overlay_window(
        api, "HA Widgets Settings", "settings", 420, 640)
    api._bind_settings_window(settings_window)
    settings_window.events.shown += api._apply_capture_exclusion

    # The tray panel is focusable so that losing focus can dismiss it.
    flyout_window = _create_overlay_window(
        api, "HA Widgets Panel", "flyout", init_w, init_h, x=200, y=200)
    api._bind_flyout_window(flyout_window)
    flyout_window.events.shown += api._apply_capture_exclusion
    flyout_window.events.deactivated += lambda: threading.Thread(
        target=api.dismiss_flyout, daemon=True).start()

    def hide_desktop():
        window.hide()
        popover_window.hide()
        settings_window.hide()
        api._desktop_visible = False

    def show_desktop():
        window.show()
        api._apply_system_glass("main")
        api._desktop_visible = True

    def on_closing():
        api.hide_flyout()
        hide_desktop()
        return False  # keep running in the tray

    window.events.closing += on_closing

    def toggle_visibility(icon=None, item=None):
        api.hide_flyout()
        if api._desktop_visible:
            hide_desktop()
        else:
            show_desktop()

    def activate(icon=None, item=None):
        api.toggle_flyout()

    def open_settings(icon=None, item=None):
        if not api._desktop_visible:
            show_desktop()
        api.open_settings_window()

    def toggle_theme(icon=None, item=None):
        order = ["light", "dark", "auto"]
        cur = api._cfg.get("theme", "auto")
        nxt = order[(order.index(cur) + 1) %
                    len(order)] if cur in order else "light"
        api.save_prefs({"theme": nxt})

    def refresh_now(icon=None, item=None):
        api._refresh_now()

    def quit_action(icon=None, item=None):
        api._quit()

    def on_resume():
        """Rebuild what a suspend invalidates: GDI objects made for the old
        display, DWM attributes, capture exclusion, and the websocket."""
        _desktop_capture.reset()
        _compat_capture.close()
        for win in api._all_windows():
            try:
                _apply_window_shape(win)
            except Exception:
                pass
        try:
            api._apply_capture_exclusion()
        except Exception:
            pass
        # A connection open across a suspend is usually half-open, and
        # recv() on it can block for minutes. Reconnect now.
        try:
            api._client._kick()
        except Exception:
            pass
        # Every page's backdrop and frame hash describe the old screen.
        api._eval_all(
            "window.__invalidateBackdrop && window.__invalidateBackdrop()")

    webview.on_resume(on_resume)

    api._watch_for_idle()

    tray_icon = build_tray_icon(activate, toggle_visibility, open_settings,
                                toggle_theme, refresh_now, quit_action)
    api._tray_icon = tray_icon
    tray_icon.run_detached()

    webview.start()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
