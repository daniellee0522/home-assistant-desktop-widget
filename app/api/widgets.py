"""The widgets on the desktop: their tiles, sizes and places; adding, removing, dragging and snapping them."""

import ctypes
import os
import threading
import time

from app.geometry import snap_rect
from app.startup import widget_initial_size
from app.widget_windows import create_widget_window
from core import config as cfgmod, local_media
from winsys import qtshell
from winsys.win32 import (
    dpi_scale, get_hwnd, monitors, POINT, run_on_ui_thread, user32, VK_LBUTTON, window_rect, work_area_at)
from winsys.windows import set_window_pos


class WidgetsMixin:
    def _init_widgets(self):
        self._widget_move_timers = {}

    def _widget_cfg(self, widget_id):
        for w in self._cfg.get("widgets", []):
            if w["id"] == widget_id:
                return w
        return None

    def _all_tiles(self):
        """Every tile of every widget, plus the panel's own if it has any."""
        tiles = []
        for w in self._cfg.get("widgets", []):
            tiles.extend(w.get("tiles", []))
        panel_tiles = (self._cfg.get("panel") or {}).get("tiles")
        if panel_tiles:
            tiles.extend(panel_tiles)
        return tiles

    def _watched_entities(self):
        """The tiles' entities, each once, in order."""
        return list(dict.fromkeys(t["entity"] for t in self._all_tiles() if t.get("entity")))

    @staticmethod
    def _clean_tiles(tiles):
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
                # The Home panel's layout: spans in tile cells, removed, order.
                **cfgmod.tile_layout(t),
            })
        return clean

    def _tiles_changed(self):
        cfgmod.save_config(self._cfg)
        self._sync_client_entities()
        self._push_prefs()

    def save_widgets(self, widgets):
        """Update the tiles of existing widgets (and the panel's own list,
        if it has one). Positions and sizes are owned by this side."""
        for incoming in (widgets or []):
            mine = self._widget_cfg(incoming.get("id"))
            if mine is not None:
                mine["tiles"] = self._clean_tiles(incoming.get("tiles"))
        self._tiles_changed()
        return True

    def save_panel(self, panel):
        """Set the tray panel's mode and its own tile list (None follows
        the widgets)."""
        if not isinstance(panel, dict):
            return False
        self._cfg["panel"] = cfgmod.clean_panel(panel, self._clean_tiles)
        self._tiles_changed()
        return True

    # The editor suggests no more widgets than this (each has its own glass to keep).
    WIDGET_SOFT_LIMIT = 6

    def add_widget(self, size="2x4", kind="tiles"):
        kind = kind if kind in cfgmod.WIDGET_KINDS else "tiles"
        size = cfgmod.KIND_SIZE.get(kind) or (size if size in cfgmod.WIDGET_SIZES else cfgmod.DEFAULT_WIDGET_SIZE)
        widgets = self._cfg.setdefault("widgets", [])
        x, y = self._next_widget_position()
        widget = {"id": cfgmod.new_widget_id(), "size": size,
                  "x": x, "y": y, "tiles": self._first_of_kind(kind), "kind": kind}
        widgets.append(widget)
        cfgmod.save_config(self._cfg)
        create_widget_window(self, widget, show=True)
        self._push_prefs()
        return {"id": widget["id"], "soft_limit": self.WIDGET_SOFT_LIMIT,
                "count": len(widgets)}

    def _first_of_kind(self, kind):
        """What a new widget of this kind starts with: a weather or a camera shows the first there is (the
        editor changes it); the others start empty."""
        if kind == "media" and self._local_media is not None:     # a player starts with this computer
            return self._clean_tiles([{"id": os.urandom(4).hex(), "entity": local_media.ENTITY,
                                       "domain": "local_media", "room": local_media.NAME}])
        domain = {"weather": "weather", "camera": "camera", "media": "media_player"}.get(kind)
        if not domain or not self._cfg.get("ha_token"):
            return []
        try:
            states = self._client.get_states()
        except Exception:
            return []
        for s in sorted(states, key=lambda s: s.get("entity_id", "")):
            eid = s.get("entity_id", "")
            if cfgmod.domain_of(eid) == domain:
                name = (s.get("attributes") or {}).get("friendly_name") or eid
                return self._clean_tiles([{"id": os.urandom(4).hex(), "entity": eid, "domain": domain,
                                           "room": name}])
        return []

    def _next_widget_position(self):
        """Beside the newest widget, or below the row when that runs off
        the screen. Physical pixels."""
        rect = None
        for window in reversed(list(self._widgets.values())):
            hwnd = get_hwnd(window)
            rect = window_rect(hwnd) if hwnd else None
            if rect:
                break
        if not rect:
            return 200, 200
        gap = 12
        x, y = rect[2] + gap, rect[1]
        work = work_area_at(rect[2], rect[1])
        if work and x + (rect[2] - rect[0]) > work[2]:
            x, y = rect[0], rect[3] + gap
        return int(x), int(y)

    def _snap_widget(self, widget_id, x, y):
        """Where widget `widget_id` ends up when dragged to (x, y)."""
        window = self._widgets.get(widget_id)
        hwnd = get_hwnd(window) if window else None
        rect = window_rect(hwnd) if hwnd else None
        if not rect:
            return int(x), int(y)
        scale = dpi_scale(hwnd) * max(50, int(self._cfg.get("zoom", 100))) / 100.0
        gap = int(round(12 * scale))
        others = []
        for other_id, other in self._widgets.items():
            if other_id == widget_id:
                continue
            other_hwnd = get_hwnd(other)
            other_rect = window_rect(other_hwnd) if other_hwnd else None
            if other_rect and user32.IsWindowVisible(other_hwnd):
                others.append(other_rect)
        areas = [m["work"] for m in monitors()]
        return snap_rect((x, y, x + rect[2] - rect[0], y + rect[3] - rect[1]),
                         others, areas, int(round(16 * scale)), gap)

    def move_widget(self, widget_id, x, y):
        """Move a widget (snapped) and remember where it ended up."""
        window = self._widgets.get(widget_id)
        hwnd = get_hwnd(window) if window else None
        if not hwnd:
            return None
        x, y = self._snap_widget(widget_id, int(x), int(y))
        run_on_ui_thread(window, lambda: set_window_pos(hwnd, x, y))
        self._on_widget_moved(widget_id)
        return {"x": x, "y": y}

    def get_layout(self):
        """The monitors and every widget's rectangle, physical pixels - what
        the editor's map draws."""
        widgets = []
        for w in self._cfg.get("widgets", []):
            window = self._widgets.get(w["id"])
            hwnd = get_hwnd(window) if window else None
            rect = window_rect(hwnd) if hwnd else None
            if rect:
                x, y, width, height = rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]
            else:
                width, height = widget_initial_size(w["size"], self._cfg.get("zoom", 100))
                x, y = w["x"], w["y"]
            widgets.append({"id": w["id"], "size": w["size"], "x": x, "y": y,
                            "w": width, "h": height,
                            "visible": bool(hwnd and user32.IsWindowVisible(hwnd))})
        return {"monitors": [{k: m[k] for k in ("x", "y", "w", "h")} for m in monitors()],
                "widgets": widgets}

    def begin_widget_drag(self, size="2x4", kind="tiles"):
        """Make a widget under the pointer and carry it along, snapping, until
        the left button is released - so it can be dragged from the editor
        straight onto the desktop."""
        added = self.add_widget(size, kind)
        threading.Thread(target=self._carry_widget, args=(added["id"],),
                         daemon=True).start()
        return added

    def _carry_widget(self, widget_id):
        deadline = time.monotonic() + 2.0
        window = self._widgets.get(widget_id)
        hwnd = None
        while time.monotonic() < deadline and not hwnd:
            hwnd = get_hwnd(window) if window else None
            time.sleep(0.02)
        pt = POINT(0, 0)
        told = 0.0
        while hwnd and user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000:
            user32.GetCursorPos(ctypes.byref(pt))
            rect = window_rect(hwnd)
            if rect:
                w, h = rect[2] - rect[0], rect[3] - rect[1]
                x, y = self._snap_widget(widget_id, pt.x - w // 2, pt.y - h // 2)
                widget = self._widget_cfg(widget_id)
                if widget:
                    widget["x"], widget["y"] = x, y
                run_on_ui_thread(window, lambda: set_window_pos(hwnd, x, y))
                if time.monotonic() - told > 0.08:
                    told = time.monotonic()
                    self._tell_widget_moved(window)
            time.sleep(0.012)
        self._on_widget_moved(widget_id)
        cfgmod.save_config(self._cfg)
        self._push_prefs()

    def open_widget_editor(self, widget_id=None):
        """Settings, opened on the visual widget editor."""
        self.open_settings_window()
        if self._settings_window:
            self._settings_window.send("enter_editor", widget_id)

    def remove_widget(self, widget_id):
        widgets = self._cfg.get("widgets", [])
        if len(widgets) <= 1 or self._widget_cfg(widget_id) is None:
            return False
        self._cfg["widgets"] = [w for w in widgets if w["id"] != widget_id]
        window = self._widgets.pop(widget_id, None)
        stop = self._widget_pin_stops.pop(widget_id, None)
        if stop:
            stop.set()
        kind = self._widget_kind(widget_id)
        for table in (self._backdrop_sent,
                      self._duplication_after, self._system_glass_hwnds,
                      self._widget_frames):
            table.pop(kind, None)
        self._excluded_kinds.discard(kind)
        if self._window is window:
            self._window = next(iter(self._widgets.values()), None)
        if window:
            try:
                window.dispose()
            except Exception:
                pass
        self._tiles_changed()
        return True

    def set_widget_size(self, widget_id, size):
        widget = self._widget_cfg(widget_id)
        if widget is None or size not in cfgmod.WIDGET_SIZES or widget.get("kind", "tiles") != "tiles":
            return False                  # the other kinds keep their own size
        widget["size"] = size
        cfgmod.save_config(self._cfg)
        self._push_prefs()
        return True

    def set_widget_source(self, widget_id, entity_id):
        """A player widget shows another player (its only device)."""
        widget = self._widget_cfg(widget_id)
        if widget is None or widget.get("kind") != "media":
            return False
        name = next((s["name"] for s in self.get_media_sources() if s["entity_id"] == entity_id), entity_id)
        widget["tiles"] = self._clean_tiles([{"id": os.urandom(4).hex(), "entity": entity_id,
                                              "domain": cfgmod.domain_of(entity_id), "room": name}])
        self._tiles_changed()
        return True

    def set_widget_font(self, widget_id, font):
        """A clock's digits in a font installed here ({"file", "name"}), or the default (None)."""
        widget = self._widget_cfg(widget_id)
        if widget is None or widget.get("kind") != "clock":
            return False
        widget.pop("font", None)
        widget.update({k: v for k, v in cfgmod._clean_widget(dict(widget, font=font)).items() if k == "font"})
        cfgmod.save_config(self._cfg)
        self._push_prefs()
        return True

    def _on_widget_moved(self, widget_id):
        """Remember a widget's position in physical pixels, read back from
        the window: the event's logical pixels depend on the monitor's DPI
        and would drift across restarts on mixed-DPI setups."""
        window = self._widgets.get(widget_id)
        widget = self._widget_cfg(widget_id)
        if not window or widget is None:
            return
        if qtshell.display_unsettled():
            # Windows moved it (a TDR, a monitor gone or back): not the user's doing, so the remembered
            # place stays, and restore_window puts the widget back there.
            return
        rect = window_rect(get_hwnd(window))
        if not rect:
            return
        widget["x"], widget["y"] = int(rect[0]), int(rect[1])
        timer = self._widget_move_timers.get(widget_id)
        if timer:
            timer.cancel()
        timer = threading.Timer(0.6, lambda: cfgmod.save_config(self._cfg))
        timer.daemon = True
        self._widget_move_timers[widget_id] = timer
        timer.start()
        self._tell_widget_moved(window)

    def _tell_widget_moved(self, window):
        """A widget on 'still' sampling only looks at the desktop again when
        told it moved; one on 'live' follows the screen by itself."""
        if self._cfg.get("glass_sampling") != "still":
            return
        window.send("widget_moved")
