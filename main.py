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
press-and-hold - or right-click - a light/climate/fan/cover/media
player/vacuum tile to open its detailed controls (brightness, temperature,
speed, position, volume...). Right-click on a plain on/off tile does
nothing (no duplicate action, no native context menu). Settings also has a
"start with Windows" toggle. Right-click the system tray icon for
Settings, theme switching, a manual refresh, or Quit. Closing the widget
(Alt+F4) just hides it - use tray "Quit" to actually exit.

Requires: pywebview, pystray, Pillow, websocket-client (pip install
pywebview pystray Pillow websocket-client). On Windows these pull in
pythonnet automatically to drive the EdgeWebView2 control.
"""

import ctypes
import json
import math
import os
import sys
import threading

if sys.platform == "win32":
    # Must happen before pywebview creates any window / calls its own
    # (older, system-only) SetProcessDPIAware(). Per-monitor-v2 awareness
    # keeps Win32's own DPI queries (which pywebview's resize() math relies
    # on) consistent with reality on a multi-monitor, mixed-scale setup.
    try:
        _set_ctx = ctypes.windll.user32.SetProcessDpiAwarenessContext
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
        return True

    def save_prefs(self, theme, columns, lock_position=None,
                   zoom=None, fixed_size=None, fixed_width=None, fixed_height=None):
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
        cfgmod.save_config(self._cfg)
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

    def resize_window(self, phys_w, phys_h, seq=None, rects=None):
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
        if not self._window:
            return
        if seq is not None:
            with self._resize_lock:
                if seq <= self._last_resize_seq:
                    # A resize call issued later by JS finished executing
                    # (on its own thread) before this older one got here -
                    # applying this stale, likely-smaller size would clip
                    # content that's already on screen. Drop it.
                    return
                self._last_resize_seq = seq
        hwnd = _get_hwnd(self._window)
        if not hwnd:
            return
        w = max(80, int(phys_w))
        h = max(60, int(phys_h))

        def _apply():
            with _hwnd_lock:
                try:
                    ctypes.windll.user32.SetWindowPos(
                        hwnd, 0, 0, 0, w, h, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE,
                    )
                except Exception:
                    pass
                # True per-pixel desktop transparency turned out to need the
                # hosting framework to build its top-level window on
                # DirectComposition from the start (how Electron/Chromium do
                # it) - not something fixable after the fact by calling a
                # couple of DWM APIs on a WinForms-created HWND (tried three
                # standard ones; none stuck, one even made the window
                # disappear, and one fought visibly with this region clip -
                # see the removed _enable_desktop_transparency/_enable_backdrop
                # above). Failing that, at least clip the *window itself* to
                # the same rounded-rect shape(s) as the CSS card(s) actually
                # on screen, so corners are a real cutout to the desktop
                # instead of square opaque corners poking out past the
                # rounded card underneath. More than one card can be visible
                # at once (the grid plus a floating detail popover beside it),
                # so this unions one rounded-rect region per card rather than
                # using a single rect for the whole window - a single rect
                # was tried instead (simpler, and avoided the gap between
                # pieces ever being a real hole in the window's shape) but it
                # meant painting that gap with a filler color whenever the
                # popover didn't line up with the grid, which looked like an
                # unwanted solid block stuck onto the widget - explicitly not
                # what was wanted here. Any gap between the grid and popover
                # is a real hole again, showing the desktop through it.
                if rects:
                    _apply_window_region(hwnd, rects)

        # pywebview runs every js_api call (this one included) on a fresh,
        # throwaway Python thread so a slow call can't block the UI (see
        # webview.util.js_bridge_call) - it is *not* the WinForms UI thread
        # that owns this HWND. Calling SetWindowPos/SetWindowRgn straight
        # from there races the docked WebView2 child control's own
        # Dock=Fill relayout and repaint, which WinForms drives on its UI
        # thread's message loop: the region could land before WebView2's
        # surface has actually resized to match, exposing raw unpainted
        # canvas (black) or the bare WinForms Form background (white)
        # until it catches up - intermittently, depending on scheduling.
        # Marshaling onto the UI thread via Invoke (the same mechanism
        # pywebview itself uses for every other native call - see
        # InvokeRequired/Invoke throughout platforms/winforms.py) makes
        # this synchronous with that relayout instead of racing it.
        _run_on_ui_thread(self._window, _apply)

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

    def resize_popover_window(self, phys_w, phys_h, seq=None, rects=None):
        # Same logic/reasoning as resize_window above (DPI-safe sizing,
        # UI-thread marshaling, per-card rounded-rect region) but for the
        # separate popover window - see IS_POPOVER_WINDOW in app.js for
        # why the detail popover has its own window at all rather than
        # sharing the grid's.
        if not self._popover_window:
            return
        if seq is not None:
            with self._popover_resize_lock:
                if seq <= self._popover_last_resize_seq:
                    return
                self._popover_last_resize_seq = seq
        hwnd = _get_hwnd(self._popover_window)
        if not hwnd:
            return
        w = max(80, int(phys_w))
        h = max(60, int(phys_h))

        def _apply():
            with _hwnd_lock:
                try:
                    ctypes.windll.user32.SetWindowPos(
                        hwnd, 0, 0, 0, w, h, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE,
                    )
                except Exception:
                    pass
                if rects:
                    _apply_window_region(hwnd, rects)

        _run_on_ui_thread(self._popover_window, _apply)

    def open_popover(self, tile_id, screen_x, screen_y):
        # Moves the (normally hidden) popover window to sit exactly where
        # the clicked tile is on screen, shows it, and asks its own page
        # (already running the full shared bootstrap - same config, same
        # tile list) to render that one tile's detail view.
        if not self._popover_window:
            return
        try:
            self._popover_window.move(int(screen_x), int(screen_y))
        except Exception:
            pass
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

    def get_window_pos(self):
        # Lets the main window's JS convert a tile's own on-page position
        # into an absolute screen position for open_popover above.
        hwnd = _get_hwnd(self._window) if self._window else None
        if not hwnd:
            return {"x": 0, "y": 0}
        try:
            r = (ctypes.c_long * 4)()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
            return {"x": r[0], "y": r[1]}
        except Exception:
            return {"x": 0, "y": 0}

    # ---------------------------------------------------------------
    # internal
    # ---------------------------------------------------------------

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
        self._cfg["window_x"] = x
        self._cfg["window_y"] = y
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


# Both DwmExtendFrameIntoClientArea(-1,-1,-1,-1) and DwmSetWindowAttribute
# with DWMWA_SYSTEMBACKDROP_TYPE were tried here to chase real desktop
# transparency; neither made the window see-through (verified with a real
# screen capture - the desktop behind it stayed a plain opaque rectangle),
# and DwmExtendFrameIntoClientArea specifically fought with the
# SetWindowRgn corner-clip below: DWM composites the "glass" frame it
# creates on a layer that doesn't respect the window's region, producing a
# square, misaligned ghost rectangle behind the properly-rounded clipped
# window. Removed rather than left in for no benefit and a visible cost.


def _get_hwnd(window):
    try:
        return window.native.Handle.ToInt32()
    except Exception:
        return None


def _run_on_ui_thread(window, fn):
    """Run fn (no-arg callable) on the WinForms UI thread that owns this
    window's HWND, blocking until it completes. Every js_api call arrives
    on its own throwaway Python thread (see webview.util.js_bridge_call),
    so any code that touches the HWND directly - SetWindowPos, SetWindowRgn,
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


RGN_OR = 2


def _apply_window_region(hwnd, rects):
    # rects: iterable of (x, y, w, h, radius), all already in physical
    # pixels relative to the window's own top-left. Builds one rounded-rect
    # region per entry and unions them (CombineRgn/RGN_OR) into a single
    # region for SetWindowRgn - a plain rectangular union of the boxes
    # would put square corners back exactly where this is trying to
    # remove them, so each piece keeps its own rounded corners in the
    # final combined shape.
    try:
        create_rgn = ctypes.windll.gdi32.CreateRoundRectRgn
        create_rgn.restype = ctypes.c_void_p
        combine_rgn = ctypes.windll.gdi32.CombineRgn
        combine_rgn.restype = ctypes.c_int

        combined = None
        for x, y, w, h, r in rects:
            x, y, w, h, r = int(x), int(y), int(w), int(h), max(0, int(r))
            part = create_rgn(x, y, x + w + 1, y + h + 1, r * 2, r * 2)
            if not part:
                continue
            if combined is None:
                combined = part
                continue
            # A zero-size placeholder region as CombineRgn's destination:
            # CombineRgn fully overwrites whatever hDest previously held,
            # so its initial shape doesn't matter - only that it's a valid
            # region handle. CreateRoundRectRgn needs all 6 args or ctypes
            # (no argtypes declared) passes garbage for the missing ones.
            merged = create_rgn(0, 0, 1, 1, 0, 0)
            combine_rgn(merged, combined, part, RGN_OR)
            ctypes.windll.gdi32.DeleteObject(combined)
            ctypes.windll.gdi32.DeleteObject(part)
            combined = merged

        if combined and not ctypes.windll.user32.SetWindowRgn(hwnd, combined, True):
            ctypes.windll.gdi32.DeleteObject(combined)
    except Exception:
        pass


def _set_noactivate(window, enable):
    hwnd = _get_hwnd(window)
    if not hwnd:
        return

    def _apply():
        with _hwnd_lock:
            try:
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                style = (style | WS_EX_NOACTIVATE) if enable else (style & ~WS_EX_NOACTIVATE)
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            except Exception:
                pass

    _run_on_ui_thread(window, _apply)


def _hide_from_taskbar(window):
    # WS_EX_TOOLWINDOW (not WinForms' ShowInTaskbar property - changing
    # that after the handle already exists risks the same handle-recreate
    # hazard that made AllowTransparency briefly hide the window entirely
    # during testing) excludes the window from the taskbar and Alt+Tab.
    hwnd = _get_hwnd(window)
    if not hwnd:
        return

    def _apply():
        with _hwnd_lock:
            try:
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW)
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
                ctypes.windll.user32.SetWindowPos(
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
                ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                ctypes.windll.user32.SetForegroundWindow(hwnd)
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

def main():
    api = Api()

    n = len(api._cfg.get("tiles", []))
    if n:
        # Match the JS grid's own column math (renderGrid in app.js): never
        # reserve more columns than there are tiles to fill them, or the
        # window opens with a dead strip on the right before the page's
        # own resize corrects it.
        cols = max(1, min(api._cfg.get("columns", 4), n))
        rows = math.ceil(n / cols)
        init_w = PAD * 2 + cols * TILE + (cols - 1) * GAP
        init_h = PAD * 2 + rows * TILE + (rows - 1) * GAP
    else:
        init_w, init_h = 300, 150

    window = webview.create_window(
        "HA Widgets",
        url=os.path.join(WEB_DIR, "index.html"),
        js_api=api,
        width=init_w,
        height=init_h,
        x=api._cfg.get("window_x", 200),
        y=api._cfg.get("window_y", 200),
        frameless=True,
        easy_drag=False,
        transparent=True,
        shadow=False,
        confirm_close=False,
    )
    api._bind_window(window)
    window.events.moved += api._on_moved

    bottom_pin_stop = threading.Event()

    def on_shown():
        _set_noactivate(window, True)
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
        min_size=(50, 50),
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

    # pywebview has a hardcoded workaround for transparent windows: on
    # *every* navigation start, it force-shows (and activates!) the form
    # regardless of the `hidden` the window was created with (see
    # on_navigation_start in platforms/edgechromium.py - its own comment
    # calls it "no idea why this works"). That's fine for the main window
    # (meant to be visible anyway) but defeats starting the popover window
    # hidden - it briefly, then persistently, shows up at whatever
    # transient size the page happened to be mid-layout at. `loaded` fires
    # once navigation actually finishes, after that forced show - hiding
    # it there puts it back the way it was asked to start. Only needed
    # once: this window navigates exactly one time (it's reused via
    # show/hide, never re-created or re-navigated).
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

    webview.start()


if __name__ == "__main__":
    main()
