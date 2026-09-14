"""
HA Desktop Widgets (pywebview edition)
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

Requires: pywebview, pystray, Pillow, websocket-client (pip install
pywebview pystray Pillow websocket-client). On Windows these pull in
pythonnet automatically to drive the EdgeWebView2 control.
"""

import base64
import ctypes
import io
import json
import math
import os
import sys
import threading
import zlib

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
        if not _set_ctx(ctypes.c_void_p(-4)):  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            raise OSError("SetProcessDpiAwarenessContext failed")
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        except Exception:
            pass

import webview

import config as cfgmod
from ha_client import HAClient
from tray import build_tray_icon

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")

TILE, GAP, PAD = 130, 12, 20


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

        # The detail popover lives in its own separate OS window (see the
        # IS_POPOVER_WINDOW comment in app.js for why) - it shares this
        # same Api instance (same config, same HA connection) but needs
        # its own window handle and its own independent resize/sequencing
        # state, since it resizes on its own schedule, unrelated to the
        # main grid window's.
        self._popover_window = None
        self._popover_resize_lock = threading.Lock()
        self._popover_last_resize_seq = -1

        self._client = HAClient(on_event=self._on_ha_event, on_status=self._on_ha_status)
        self._client.configure(
            self._cfg.get("ha_url", ""), self._cfg.get("ha_token", ""),
            self._cfg.get("poll_fallback_sec", 30),
        )
        self._client.set_entities([t["entity"] for t in self._cfg.get("tiles", []) if t.get("entity")])
        self._client.start()

    def _bind_window(self, window):
        self._window = window

    def _bind_popover_window(self, window):
        self._popover_window = window

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
                "columns": self._cfg.get("columns", 4),
                "lock_position": bool(self._cfg.get("lock_position", False)),
                "start_on_boot": bool(self._cfg.get("start_on_boot", False)),
                "zoom": self._cfg.get("zoom", 100),
                "fixed_size": bool(self._cfg.get("fixed_size", False)),
                "fixed_width": self._cfg.get("fixed_width", 400),
                "fixed_height": self._cfg.get("fixed_height", 300),
                "opacity": self._cfg.get("opacity", 100),
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
            self._cfg["ha_url"], self._cfg["ha_token"], self._cfg.get("poll_fallback_sec", 30),
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

    def save_prefs(self, theme, columns, lock_position=None,
                   zoom=None, fixed_size=None, fixed_width=None, fixed_height=None,
                   opacity=None):
        self._cfg["theme"] = theme or "auto"
        try:
            self._cfg["columns"] = max(2, min(8, int(columns)))
        except Exception:
            self._cfg["columns"] = 4
        if lock_position is not None:
            self._cfg["lock_position"] = bool(lock_position)
        if zoom is not None:
            try:
                self._cfg["zoom"] = max(50, min(200, int(zoom)))
            except Exception:
                self._cfg["zoom"] = 100
        if fixed_size is not None:
            self._cfg["fixed_size"] = bool(fixed_size)
        if fixed_width is not None:
            try:
                self._cfg["fixed_width"] = max(120, int(fixed_width))
            except Exception:
                pass
        if fixed_height is not None:
            try:
                self._cfg["fixed_height"] = max(90, int(fixed_height))
            except Exception:
                pass
        if opacity is not None:
            try:
                self._cfg["opacity"] = max(0, min(100, int(opacity)))
            except Exception:
                pass
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
                    winreg.SetValueEx(key, "HAWidgets", 0, winreg.REG_SZ, _startup_command())
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
        # sequence counter and lock - everything else is identical to the
        # grid window's path above.
        self._resize_native(
            self._popover_window, self._popover_resize_lock, "_popover_last_resize_seq",
            phys_w, phys_h, seq, "resize_popover_window",
        )

    def _resize_native(self, window, seq_lock, seq_attr, phys_w, phys_h, seq, tag):
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
        w = max(80, int(phys_w))
        h = max(60, int(phys_h))

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
        _run_on_ui_thread(window, lambda: _set_window_size(hwnd, w, h))

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

    def open_popover(self, tile_id, screen_x, screen_y):
        # Moves the (normally hidden) popover window to sit exactly where
        # the clicked tile is on screen, shows it, and asks its own page
        # (already running the full shared bootstrap - same config, same
        # tile list) to render that one tile's detail view.
        if not self._popover_window:
            return
        hwnd = _get_hwnd(self._popover_window)
        if hwnd:
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
        try:
            self._popover_window.show()
        except Exception:
            pass
        _bring_to_front(self._popover_window)
        try:
            self._popover_window.evaluate_js(
                "window.__showPopoverForTile && window.__showPopoverForTile(%s)" % json.dumps(tile_id)
            )
        except Exception:
            pass

    def close_popover(self):
        if self._popover_window:
            try:
                self._popover_window.hide()
            except Exception:
                pass

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

    def get_desktop_backdrop(self, window_kind="main", last_hash=None):
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
        """
        is_popover = window_kind == "popover"
        window = self._popover_window if is_popover else self._window
        if not window:
            return None
        hwnd = _get_hwnd(window)
        if not hwnd:
            return None
        try:
            r = (ctypes.c_long * 4)()
            _user32.GetWindowRect(hwnd, ctypes.byref(r))
            x, y, w, h = r[0], r[1], r[2] - r[0], r[3] - r[1]
            # The popover opens on top of the widget, so the widget is part
            # of what is behind it.
            over = ()
            if is_popover and self._window:
                main_hwnd = _get_hwnd(self._window)
                if main_hwnd:
                    over = (main_hwnd,)
            raw = _desktop_capture.grab(x, y, w, h, over)
            if not raw:
                return None
            digest = zlib.crc32(raw) & 0xFFFFFFFF
            if last_hash is not None and int(last_hash) == digest:
                return {"unchanged": True, "hash": digest}
            from PIL import Image
            img = Image.frombuffer("RGBA", (w, h), raw, "raw", "BGRA", 0, 1).convert("RGB")
            buf = io.BytesIO()
            # JPEG, not PNG: this is a photo-like backdrop that is about to
            # be blurred, and encoding it costs ~0.4ms against PNG's ~4.6ms
            # - the difference between tracking a moving wallpaper and not.
            # Quality is high enough that the unblurred margin around the
            # card still matches the desktop pixel for pixel by eye.
            img.save(buf, format="JPEG", quality=88, subsampling=0)
            return {
                "url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii"),
                "w": w,
                "h": h,
                "hash": digest,
            }
        except Exception:
            return None

    def move_window(self, screen_x, screen_y):
        # Absolute physical screen pixels, from the page's own drag
        # handling (see startDrag in app.js). pywebview's built-in
        # drag-region support is deliberately not used: it moves the window
        # on the first mousemove after *any* mousedown on the region, with
        # no threshold, so a plain click - the way the detail popover is
        # dismissed - dragged the widget out from under the pointer. It
        # also feeds pywebview's move(), which takes logical pixels and
        # rescales them, so on a display where devicePixelRatio and the
        # OS scale disagree the window jumped rather than followed.
        if not self._window:
            return
        hwnd = _get_hwnd(self._window)
        if not hwnd:
            return
        _run_on_ui_thread(
            self._window, lambda: _set_window_pos(hwnd, int(screen_x), int(screen_y)),
        )

    def get_window_pos(self):
        # Lets the main window's JS convert a tile's own on-page position
        # into an absolute screen position for open_popover above.
        hwnd = _get_hwnd(self._window) if self._window else None
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
        payload = json.dumps({
            "theme": self._cfg.get("theme", "auto"),
            "columns": self._cfg.get("columns", 4),
            "zoom": self._cfg.get("zoom", 100),
            "fixed_size": bool(self._cfg.get("fixed_size", False)),
            "fixed_width": self._cfg.get("fixed_width", 400),
            "fixed_height": self._cfg.get("fixed_height", 300),
            "lock_position": bool(self._cfg.get("lock_position", False)),
            "opacity": self._cfg.get("opacity", 100),
            "tiles": self._cfg.get("tiles", []),
        }, ensure_ascii=False)
        script = "window.__applyPrefs && window.__applyPrefs(%s)" % payload
        for win in (self._window, self._popover_window):
            if not win:
                continue
            try:
                win.evaluate_js(script)
            except Exception:
                pass

    def _push_batch(self, items):
        if not self._window:
            return
        payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
        try:
            self._window.evaluate_js("window.__haPushBatch(%s)" % payload)
        except Exception:
            pass
        # The popover window keeps its own STATES copy from its own
        # bootstrap/fetch_initial_states call, but has no live websocket of
        # its own (it shares this Api/HAClient instance, whose push
        # callbacks otherwise only ever target the main window) - without
        # this it would go stale the moment something changes elsewhere
        # while it's open. Only worth reaching if it's actually showing
        # something.
        if self._popover_window:
            try:
                self._popover_window.evaluate_js("window.__haPushBatch(%s)" % payload)
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
        self._connected = connected
        if self._window and self._ui_ready:
            try:
                self._window.evaluate_js("window.__haStatus(%s)" % json.dumps(bool(connected)))
            except Exception:
                pass

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
        self._move_timer = threading.Timer(0.6, lambda: cfgmod.save_config(self._cfg))
        self._move_timer.daemon = True
        self._move_timer.start()

    def _refresh_now(self):
        def go():
            for t in self._cfg.get("tiles", []):
                try:
                    st = self._client.get_state(t["entity"])
                    if st:
                        self._on_ha_event(t["entity"], st)
                except Exception:
                    pass
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
        os._exit(0)


# ---------------------------------------------------------------------
# "Start with Windows" (Run key) helper
# ---------------------------------------------------------------------

def _startup_command():
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


# Window shape and the frosted-glass backdrop.
#
# The widget is meant to sit on the desktop like a Rainmeter skin:
# frosted, softly rounded, no drop shadow, no taskbar button. Only the
# last two of those are done natively:
#
#   No shadow: DWMWA_WINDOW_CORNER_PREFERENCE is pinned to
#   DWMWCP_DONOTROUND. That is not about shape - the rounded outline is
#   the page's - but about what DWM attaches to rounding. On Windows 11
#   asking for *any* corner rounding also gets the standard window drop
#   shadow, and a shadow is what makes something read as an application
#   floating above the desktop rather than a widget stuck to it. Measured
#   on a flat grey backdrop, capturing with the window shown and hidden:
#   rounding of either size puts a ~20px darkening ramp under the window,
#   DONOTROUND leaves it perfectly flat. Nothing separates the two, and
#   once DWM has granted the shadow it does not take it back when the
#   preference changes at runtime - so anything measuring this has to
#   compare separate runs or it will read its own leftovers.
#
#   No taskbar button: see _hide_from_taskbar.
#
# Everything visual is the page's, drawn over a live picture of the
# desktop that _DesktopCapture takes from behind the window. That
# indirection is not a shortcut - it is the only thing that works here.
# This window cannot be see-through at all, which was established by
# measurement rather than assumption: the panel's colour came out
# identical with the widget over a dark purple region of the wallpaper
# and over a pink one, for every one of these:
#
#   - DWMWA_SYSTEMBACKDROP_TYPE (Mica/Acrylic) with its extended frame.
#   - SetWindowCompositionAttribute, both ACCENT_ENABLE_ACRYLICBLURBEHIND
#     and ACCENT_ENABLE_BLURBEHIND.
#   - pywebview's transparent=True, which composites the page's
#     transparent pixels against the WinForms form's opaque background.
#   - WS_EX_LAYERED colour-keyed on the page's background or the form's;
#     the key never matches what Chromium actually paints.
#
# Two near misses worth recording, because they look like solutions:
# WS_EX_LAYERED with LWA_ALPHA *does* make the window genuinely
# translucent, but only under --disable-gpu-compositing, and only
# uniformly - tiles and text go translucent with it. And SetWindowRgn does
# clip the window's shape, but the area it excludes composites to opaque
# black instead of revealing the desktop (a plain WinForms form with the
# same region reveals it fine - it is the WebView2 child that breaks it),
# which is where the black frame around the card came from.
#
# Painting the backdrop ourselves sidesteps all of it: the page draws the
# captured desktop edge to edge, blurs it behind the card with
# backdrop-filter, and leaves it unblurred outside the card's rounded
# corners so those corners read as a real cutout. Tiles stay fully opaque,
# because nothing about the window is translucent.


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
_user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
_user32.SetWindowLongW.restype = ctypes.c_long
_user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
_user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
_user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
_user32.GetDC.argtypes = [ctypes.c_void_p]
_user32.GetDC.restype = ctypes.c_void_p
_user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
_user32.FindWindowW.restype = ctypes.c_void_p
_user32.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]

_gdi32 = ctypes.WinDLL("gdi32")
_gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
_gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
_gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
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
_gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
_gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
_user32.EnumChildWindows.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
_user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
_dwmapi.DwmSetWindowAttribute.argtypes = [
    ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint,
]
_dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long


_ENUM_WINDOWS_PROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
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
        self._surface = None          # (hwnd, x, y, w, h) of the surface we render

    # -- scratch surfaces ------------------------------------------------

    def _ensure(self, attr_dc, attr_bmp, attr_size, w, h):
        if getattr(self, attr_dc) and getattr(self, attr_size) == (w, h):
            return True
        old_dc, old_bmp = getattr(self, attr_dc), getattr(self, attr_bmp)
        if old_bmp:
            _gdi32.DeleteObject(old_bmp)
        if old_dc:
            _gdi32.DeleteDC(old_dc)
        setattr(self, attr_dc, None)
        setattr(self, attr_bmp, None)
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
            _gdi32.SelectObject(dc, bmp)
            setattr(self, attr_dc, dc)
            setattr(self, attr_bmp, bmp)
            setattr(self, attr_size, (w, h))
            return True
        finally:
            _user32.ReleaseDC(None, screen_dc)

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
        _gdi32.BitBlt(self._out_dc, 0, 0, w, h, self._dc, x - sx, y - sy, SRCCOPY)
        hdr = _BITMAPINFOHEADER(
            ctypes.sizeof(_BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0,
        )
        buf = ctypes.create_string_buffer(w * h * 4)
        if not _gdi32.GetDIBits(self._out_dc, self._out_bmp, 0, h, buf, ctypes.byref(hdr), 0):
            return None
        return buf.raw

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
            if _user32.IsWindowVisible(hwnd) and _user32.GetWindowRect(hwnd, ctypes.byref(r))                     and r[0] <= x and r[1] <= y and r[2] >= x + w and r[3] >= y + h:
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

    # -- the capture itself ----------------------------------------------

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
                _gdi32.BitBlt(self._out_dc, r[0] - x, r[1] - y, ow, oh, self._ov_dc, 0, 0, SRCCOPY)
            hdr = _BITMAPINFOHEADER(
                ctypes.sizeof(_BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0,
            )
            buf = ctypes.create_string_buffer(w * h * 4)
            if not _gdi32.GetDIBits(self._out_dc, self._out_bmp, 0, h, buf, ctypes.byref(hdr), 0):
                return raw
            return buf.raw


_desktop_capture = _DesktopCapture()


def _get_hwnd(window):
    try:
        # ToInt64, not ToInt32: an HWND is pointer-sized, and ToInt32
        # raises OverflowException on any handle above 2^31.
        return window.native.Handle.ToInt64()
    except Exception:
        return None


def _run_on_ui_thread(window, fn):
    """Run fn (no-arg callable) on the WinForms UI thread that owns this
    window's HWND, blocking until it completes. Every js_api call arrives
    on its own throwaway Python thread (see webview.util.js_bridge_call),
    so any code that touches the HWND directly - SetWindowPos,
    SetWindowLongW - must be marshaled over like this or it races WinForms'
    own UI-thread-driven layout/paint pipeline for the docked WebView2
    control. This mirrors the InvokeRequired/Invoke pattern pywebview uses
    internally for its own native calls (see platforms/winforms.py).
    """
    native = getattr(window, "native", None)
    if native is None:
        fn()
        return
    try:
        if native.InvokeRequired:
            from System import Func, Type
            native.Invoke(Func[Type](fn))
        else:
            fn()
    except Exception:
        try:
            fn()
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


def _apply_window_shape(window):
    """Stop DWM rounding this window, and so stop it shadowing the window.

    The visible rounded outline is the page's, not the window's (see the
    note above) - this is purely about the shadow that comes attached to
    any DWM rounding. Windows 10 doesn't know the attribute and fails the
    call harmlessly; its windows are square anyway.
    """
    hwnd = _get_hwnd(window)
    if not hwnd:
        return

    def _apply():
        with _hwnd_lock:
            v = ctypes.c_int(DWMWCP_DONOTROUND)
            try:
                _dwmapi.DwmSetWindowAttribute(
                    hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(v), ctypes.sizeof(v),
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
                style = (style | WS_EX_NOACTIVATE) if enable else (style & ~WS_EX_NOACTIVATE)
                _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            except Exception:
                pass

    _run_on_ui_thread(window, _apply)


def _hide_from_taskbar(window):
    """Keep this window out of the taskbar and Alt+Tab.

    Two flags, not one. Setting WS_EX_TOOLWINDOW alone was not enough:
    WinForms puts WS_EX_APPWINDOW on any form whose ShowInTaskbar is true
    (the default), and APPWINDOW *overrides* TOOLWINDOW - the widget kept
    its taskbar button the whole time. Clearing it is the other half.

    Neither flag is set through WinForms' own ShowInTaskbar property:
    changing that after the handle exists makes WinForms recreate the
    handle, the same hazard that made AllowTransparency briefly lose the
    window entirely during testing.

    The shell only re-reads these flags when a window is shown, so a
    window that is already visible has to be hidden and shown again for
    the button to actually go away. SW_SHOWNA re-shows it without
    activating it, which matters for a widget that must never steal focus.
    """
    hwnd = _get_hwnd(window)
    if not hwnd:
        return

    def _apply():
        with _hwnd_lock:
            try:
                style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                wanted = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
                if wanted == style:
                    return
                visible = bool(_user32.IsWindowVisible(hwnd))
                if visible:
                    _user32.ShowWindow(hwnd, SW_HIDE)
                _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, wanted)
                if visible:
                    _user32.ShowWindow(hwnd, SW_SHOWNA)
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
                _user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                _user32.SetForegroundWindow(hwnd)
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


# Keep in step with --panel in web/style.css. The page paints over all of
# this within a frame or two of starting, so these only ever show during
# that first frame - but they are what it looks like, so it should be the
# right colour rather than an arbitrary default.
PANEL_COLOR = {"light": "#D2E2F0", "dark": "#24282E"}


def _startup_background(theme):
    if theme not in PANEL_COLOR:
        # "auto" follows the OS, the same way the page's own
        # prefers-color-scheme rule does.
        theme = "light" if _os_prefers_light() else "dark"
    return PANEL_COLOR[theme]


def _os_prefers_light():
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        try:
            return bool(winreg.QueryValueEx(key, "AppsUseLightTheme")[0])
        finally:
            winreg.CloseKey(key)
    except Exception:
        return True


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
        w = PAD * 2 + cols * TILE + (cols - 1) * GAP
        h = PAD * 2 + rows * TILE + (rows - 1) * GAP

    # The page renders inside a CSS `zoom`, so its tiles are not TILE px on
    # screen - they are TILE * zoom. Leaving this out opened the window at
    # double its real size on a 50% zoom, which then visibly snapped down
    # as soon as the page measured itself.
    try:
        zoom = max(50, min(200, int(cfg.get("zoom", 100)))) / 100.0
    except Exception:
        zoom = 1.0
    return max(80, int(w * zoom)), max(60, int(h * zoom))


def main():
    _hide_own_console()

    api = Api()

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
        # Not transparent=True. It cannot make this window see-through
        # (see the note above) - all it does is leave the form's
        # background unset and hand WebView2 a transparent default, so any
        # part of the window the page hasn't painted shows raw,
        # never-initialised surface as black. An opaque background makes
        # the worst case a frame of flat panel colour instead.
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
        _apply_window_shape(window)
        _set_noactivate(window, True)
        # Position it before _hide_from_taskbar, which hides and re-shows
        # the window: that way the correction happens while it is hidden
        # and there is nothing to see jump.
        saved_x, saved_y = api._cfg.get("window_x"), api._cfg.get("window_y")
        if saved_x is not None and saved_y is not None:
            hwnd = _get_hwnd(window)
            if hwnd:
                _run_on_ui_thread(
                    window, lambda: _set_window_pos(hwnd, int(saved_x), int(saved_y)),
                )
        _hide_from_taskbar(window)
        _send_to_bottom(window)
        threading.Thread(
            target=_bottom_pin_loop, args=(window, bottom_pin_stop, api._pin_enabled), daemon=True,
        ).start()

    window.events.shown += on_shown

    visible = {"v": True}

    def on_closing():
        window.hide()
        popover_window.hide()
        visible["v"] = False
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
        url=os.path.join(WEB_DIR, "popover.html"),
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

    def on_popover_deactivate(sender, args):
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
                popover_window.evaluate_js("window.closeDetail && window.closeDetail()")
            except Exception:
                pass

        threading.Thread(target=_close, daemon=True).start()

    def on_popover_shown():
        _apply_window_shape(popover_window)
        _set_noactivate(popover_window, True)
        _hide_from_taskbar(popover_window)
        # .native only exists once the underlying native window has
        # actually been created, which happens right before this event
        # fires - not yet at the point create_window() above returns.
        try:
            popover_window.native.Deactivate += on_popover_deactivate
        except Exception:
            pass

    popover_window.events.shown += on_popover_shown

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

    def toggle_visibility(icon=None, item=None):
        if visible["v"]:
            window.hide()
            popover_window.hide()
        else:
            window.show()
        visible["v"] = not visible["v"]

    def open_settings(icon=None, item=None):
        if not visible["v"]:
            window.show()
            visible["v"] = True
        try:
            window.evaluate_js("window.__openSettingsFromTray && window.__openSettingsFromTray()")
        except Exception:
            pass

    def toggle_theme(icon=None, item=None):
        order = ["light", "dark", "auto"]
        cur = api._cfg.get("theme", "auto")
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "light"
        api._cfg["theme"] = nxt
        cfgmod.save_config(api._cfg)
        api._push_prefs()
        try:
            window.evaluate_js("window.__setThemeFromTray && window.__setThemeFromTray(%s)" % json.dumps(nxt))
        except Exception:
            pass

    def refresh_now(icon=None, item=None):
        api._refresh_now()

    def quit_action(icon=None, item=None):
        api._quit()

    tray_icon = build_tray_icon(toggle_visibility, open_settings, toggle_theme, refresh_now, quit_action)
    api._tray_icon = tray_icon
    tray_icon.run_detached()

    if os.environ.get("HA_WIDGET_DEBUG_OPEN_SETTINGS"):
        threading.Timer(3.0, open_settings).start()

    webview.start()


if __name__ == "__main__":
    main()
