"""The detail card: what a hold or a right-click on a tile opens (the page's #popover window).

The controls of each kind of device, the readout and history of a sensor, and the small edit panel
(icon, name, room, label). main.py drives it the way it drove the page (see overlay.py): it is told
which tile to show, taken to its place by Api.open_popover, and closed again when focus leaves it.
"""
import json
import threading
import time
import traceback

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen

from . import render, ui
from .overlay import OverlayScene, create_overlay
from .ui import Button, IconView, Label, Rect, ScrollView, Slider, TextField, View

CARD_W = 288
BODY_X, BODY_W = 14, 260
BODY_MAX = 520
HISTORY_HOURS = 24

ICON_PLAY = "path:M8 5v14l11-7z"
ICON_PAUSE = "path:M7 5h4v14H7zM13 5h4v14h-4z"
ICON_PREV = "path:M6 6h2v12H6zM20 6L10 12l10 6z"
ICON_NEXT = "path:M16 6h2v12h-2zM4 6l10 6-10 6z"
ICON_GEAR = ("path:M12 8.5a3.5 3.5 0 100 7 3.5 3.5 0 000-7zm9 3.5c0 .64-.07 1.26-.19 1.86l2.03 1.58a.75.75 0 01.17.96"
             "l-1.92 3.32a.75.75 0 01-.91.32l-2.39-.96c-.98.75-1.44.99-2.36 1.32l-.36 2.54a.75.75 0 01-.74.64h-3.84a.75.75"
             " 0 01-.74-.64l-.36-2.54c-.93-.33-1.38-.57-2.36-1.32l-2.39.96a.75.75 0 01-.91-.32l-1.92-3.32a.75.75 0 01.17-.96"
             "l2.03-1.58C3.07 13.26 3 12.64 3 12s.07-1.26.19-1.86L1.16 8.56a.75.75 0 01-.17-.96l1.92-3.32a.75.75 0 01.91-.32"
             "l2.39.96c.98-.75 1.44-.99 2.36-1.32l.36-2.54A.75.75 0 019.67 0h3.84c.37 0 .68.27.74.64l.36 2.54c.93.33 1.38.57"
             " 2.36 1.32l2.39-.96a.75.75 0 01.91.32l1.92 3.32a.75.75 0 01-.17.96l-2.03 1.58c.12.6.19 1.22.19 1.86z")
ICON_CHOICES = ["light", "switch", "mdi:air-conditioner", "fan", "mdi:blinds", "mdi:curtains", "media", "monitor",
                "lock", "door", "mdi:robot-vacuum", "mdi:palette", "script", "mdi:robot",
                "thermometer", "humidity", "sensor"]
HVAC_LABELS = {"off": "關閉", "cool": "冷氣", "heat": "暖氣", "heat_cool": "自動", "auto": "自動",
               "dry": "除濕", "fan_only": "送風"}


def trim_number(n):
    return str(round(n * 10) / 10).rstrip("0").rstrip(".") if round(n * 10) / 10 != int(round(n * 10) / 10) else str(int(round(n * 10) / 10))


class Stack:
    """Blocks one under another with the margins of CSS block flow: the space between two is the
    larger of the one below the first and the one above the second."""

    def __init__(self, parent, x, y, w):
        self.parent, self.x, self.y, self.w = parent, x, y, w
        self.prev_mb = None

    def place(self, view, mt=0, mb=0):
        gap = mt if self.prev_mb is None else max(self.prev_mb, mt)
        view.x, view.y = self.x, self.y + gap
        self.y = view.y + view.h
        self.prev_mb = mb
        self.parent.add(view)
        return view

    def end(self):
        return self.y + (self.prev_mb or 0)


class AccessoryTile(View):
    """The large tile at the top of a device's detail: glance, and tap to toggle. On, a colour rises
    from the bottom (to the brightness, for a light)."""
    cursor = Qt.PointingHandCursor

    def __init__(self, w, icon, on, pct, color, state_text, on_click):
        super().__init__(0, 0, w, 150)
        self.interactive = True
        self.icon, self.on, self.color, self.state_text = icon, on, color, state_text
        self.fill = (max(6, pct) if on else 0) / 100.0
        self.on_click = lambda e: on_click()
        self.on_press = lambda e: True

    def paint(self, p):
        t = self.scene.t
        r = t["radius_tile"] - 26
        shape = render.squircle(0, 0, self.w, self.h, r)
        p.setPen(Qt.NoPen)
        p.setBrush(render.rgba(t["tile_off"]))
        p.drawPath(shape)
        p.save()
        p.setClipPath(shape)
        if self.fill > 0:
            p.setBrush(ui.resolve(self.scene, self.color))
            p.drawRect(QRectF(0, self.h * (1 - self.fill), self.w, self.h * self.fill))
        p.restore()
        render.inner_shadow(p, shape, render.rgba(t["edge"]))
        if t["edge_top"]:
            render.inner_shadow(p, shape, render.rgba(t["edge_top"]), dy=1, spread=0)
        render.draw_icon(p, self.icon, "#ffffff", QRectF(16, 16, 36, 36))
        f = ui.font(17, QFont.DemiBold)
        fm = ui.QFontMetricsF(f)
        base = self.h - 14 - fm.descent() / 10 - (1.2 * 17 - fm.height() / 10) / 2
        p.setBrush(QColor(255, 255, 255))
        p.drawPath(render.text_path(QPointF(0, 0), f, render.tr(self.state_text), 16, base))


class ToggleSlab(View):
    """A switch or a lock: the tile is the track, a half-height slab rides from the lower half to the
    upper, turning white, when on."""
    cursor = Qt.PointingHandCursor

    def __init__(self, w, icon, on, on_click):
        super().__init__(0, 0, w, 150)
        self.interactive = True
        self.icon, self.on = icon, on
        self.up = 1.0 if on else 0.0          # 0 low, 1 high; eased when it changes
        self.on_click = lambda e: on_click()
        self.on_press = lambda e: True

    def paint(self, p):
        t = self.scene.t
        r = t["radius_tile"] - 26
        shape = render.squircle(0, 0, self.w, self.h, r)
        p.setPen(Qt.NoPen)
        p.setBrush(render.rgba(t["tile_off"]))
        p.drawPath(shape)
        slab_h = self.h / 2 - 12
        low, high = self.h - 8 - slab_h, self.h / 2 - 4 - slab_h
        top = low + (high - low) * self.up
        rect = QRectF(8, top, self.w - 16, slab_h)
        k = self.up
        fill = QColor(round(255 * k), round(255 * k), round(255 * k), round(255 * (0.42 * (1 - k) + k)))
        fill = QColor(round(255 * k), round(255 * k), round(255 * k)) if k >= 1 else fill
        p.setBrush(QColor(255, 255, 255) if k >= 1 else QColor(0, 0, 0, round(255 * 0.42 * (1 - k)) + round(255 * k)) if False else fill)
        p.drawPath(render.squircle(rect.x(), rect.y(), rect.width(), rect.height(), max(4, r - 15)))
        ink = round(255 - (255 - 29) * k)
        render.draw_icon(p, self.icon, "#%02x%02x%02x" % (ink, ink, ink if k < 1 else 31),
                         QRectF(rect.center().x() - 17, rect.center().y() - 17, 34, 34))
        render.inner_shadow(p, shape, render.rgba(t["edge"]))
        if t["edge_top"]:
            render.inner_shadow(p, shape, render.rgba(t["edge_top"]), dy=1, spread=0)


class Chart(View):
    """The last day of a sensor: its line, the area under it, and a dot at the end."""

    def __init__(self, w, h=64):
        super().__init__(0, 0, w, h)
        self.points = None
        self.message = "載入中…"

    def paint(self, p):
        if not self.points:
            f = ui.font(12)
            tw = ui.text_width(render.tr(self.message), f)
            fm = ui.QFontMetricsF(f)
            p.setPen(Qt.NoPen)
            p.setBrush(ui.resolve(self.scene, "ink2"))
            p.drawPath(render.text_path(QPointF(0, 0), f, render.tr(self.message), (self.w - tw) / 2,
                                        (self.h - fm.height() / 10) / 2 + fm.ascent() / 10))
            return
        pts = self.points
        t0, t1 = pts[0][0], pts[-1][0] or pts[0][0] + 1
        span = max(1, t1 - t0)
        lo, hi = min(v for _, v in pts), max(v for _, v in pts)
        if hi - lo < 0.5:
            mid = (hi + lo) / 2
            lo, hi = mid - 0.5, mid + 0.5
        pad = 3
        xy = [((t - t0) / span * self.w, pad + (1 - (v - lo) / (hi - lo)) * (self.h - 2 * pad)) for t, v in pts]
        line = QPainterPath()
        line.moveTo(*xy[0])
        for x, y in xy[1:]:
            line.lineTo(x, y)
        area = QPainterPath(line)
        area.lineTo(self.w, self.h)
        area.lineTo(0, self.h)
        area.closeSubpath()
        blue = ui.resolve(self.scene, "accent_blue")
        p.setPen(Qt.NoPen)
        fillc = QColor(blue)
        fillc.setAlphaF(0.16)
        p.setBrush(fillc)
        p.drawPath(area)
        p.setPen(QPen(blue, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPath(line)
        p.setPen(QPen(QColor(255, 255, 255), 1.2))
        p.setBrush(blue)
        p.drawEllipse(QPointF(*xy[-1]), 2.5, 2.5)


class ColorRow(View):
    """'Colour' and a swatch that opens the colour dialog."""

    def __init__(self, w, rgb, on_pick):
        super().__init__(0, 0, w, 32)
        self.interactive = True
        self.rgb, self.on_pick = rgb, on_pick
        self.cursor = Qt.PointingHandCursor
        self.on_click = lambda e: self._pick()

    def _pick(self):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(QColor(*self.rgb), self.scene, render.tr("顏色"))
        if c.isValid():
            self.rgb = (c.red(), c.green(), c.blue())
            self.on_pick(list(self.rgb))
            self.changed()

    def paint(self, p):
        f = ui.font(13)
        fm = ui.QFontMetricsF(f)
        p.setPen(Qt.NoPen)
        p.setBrush(ui.resolve(self.scene, "ink1"))
        p.drawPath(render.text_path(QPointF(0, 0), f, render.tr("顏色"), 0, (self.h - fm.height() / 10) / 2 + fm.ascent() / 10))
        box = QRectF(self.w - 44, 0, 44, 32)
        p.setBrush(ui.resolve(self.scene, "input_bg"))
        p.setPen(QPen(ui.resolve(self.scene, "input_border"), 1))
        p.drawRoundedRect(box, 8, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(*self.rgb))
        p.drawRoundedRect(box.adjusted(3, 3, -3, -3), 5, 5)


class DetailCard(OverlayScene):
    def __init__(self, facade, api):
        super().__init__(facade, api, "popover")
        self.lensed = False                       # the lens belongs to the widget: this is a quiet pane
        self.prefs = api._prefs()
        self.states = {}
        self.tile = None
        self.owner = None
        self.edit = False
        self.seq = 0
        self.history_token = 0
        self.arm_event = None
        self.sampling = "live"
        self.configure()
        self.retheme()
        threading.Thread(target=self._load_states, daemon=True).start()

    def _load_states(self):
        try:
            for _ in range(200):                    # the facade is still being made
                if getattr(self.facade, "_native", None) is not None:
                    break
                time.sleep(0.01)
            states = self.api.fetch_initial_states()
            if states:
                self.facade.run_on_ui_thread(lambda: self.push_states(list(states.items())))
        except Exception:
            traceback.print_exc()

    # -- preferences ----------------------------------------------------------------------------
    def configure(self):
        prefs = self.prefs
        panel_theme = prefs.get("panel_theme", "follow")
        own = self.owner == "flyout" and panel_theme != "follow"
        self.theme_raw = panel_theme if own else prefs.get("theme", "auto")
        self.style = prefs.get("glass_style", "classic")
        if self.style not in ("classic", "liquid", "windows"):
            self.style = "classic"
        self.language = prefs.get("language", "zh-TW")
        self.liquid_level = prefs.get("liquid_blur", 0)
        self.zoom_css = max(0.5, min(2.0, prefs.get("zoom", 100) / 100.0))
        self.system_glass = (prefs.get("system_glass_active") or {}).get("popover") is True

    def apply_prefs(self, prefs):
        before = (self.theme_raw, self.style, self.language, self.zoom_css, self.system_glass)
        keep = self.tile["id"] if self.tile else None
        self.prefs = prefs
        self.configure()
        if before != (self.theme_raw, self.style, self.language, self.zoom_css, self.system_glass):
            self.retheme()
            self.update_metrics()
            self.invalidate_glass()
        if keep:
            self.tile = self.find_tile(keep)
            if self.tile and not self.edit:
                self.rebuild()

    def themed(self):
        if self.tile:
            self.rebuild()

    def card_radius(self):
        return self.t["radius_tile"]

    def paint_card(self, p):
        render.draw_card_bg(p, self.css_w, self.css_h, self.t, self.style, self.theme,
                            radius=self.t["radius_tile"], plain=True)

    def set_owner(self, kind):
        if kind != self.owner:
            self.owner = kind
            self.configure()
            self.retheme()

    # -- tiles and states -----------------------------------------------------------------------------
    def find_tile(self, tile_id):
        for w in self.prefs.get("widgets", []):
            for t in w.get("tiles", []):
                if t.get("id") == tile_id:
                    return t
        panel = self.prefs.get("panel") or {}
        for key in ("tiles", "home_tiles"):
            for t in panel.get(key) or []:
                if t.get("id") == tile_id:
                    return t
        if tile_id.startswith("home:"):
            entity = tile_id[5:]
            st = self.states.get(entity)
            return {"id": tile_id, "entity": entity, "domain": entity.split(".")[0],
                    "room": ((st or {}).get("attributes") or {}).get("friendly_name") or entity,
                    "label": "", "icon": "", "on_mode": "cool", "temp_step": 1}
        return None

    def push_states(self, items):
        for entity, state in items:
            self.states[entity] = state
        if self.tile and not self.edit and any(e == self.tile["entity"] for e, _ in items):
            self.rebuild()

    def optimistic(self, entity, patch):
        st = self.states.get(entity)
        if st is not None:
            self.states[entity] = dict(st, **patch)
            if self.tile and not self.edit:
                self.rebuild()

    def call(self, domain, service, entity, extra=None):
        def go():
            try:
                self.api.call_service(domain, service, entity, extra or {})
            except Exception:
                traceback.print_exc()
        threading.Thread(target=go, daemon=True).start()

    # -- opening and closing --------------------------------------------------------------------------------
    def open_tile(self, tile_id):
        tile = self.find_tile(tile_id)
        if tile is None:
            return
        self.tile = tile
        self.edit = False
        self.root.stop_animation()
        self.root.alpha, self.root.dy = 0.0, 6.0
        self.rebuild()
        threading.Thread(target=lambda: self.api.set_popover_activatable(True), daemon=True).start()

    def enter(self):
        self.root.animate(150, "out", alpha=1.0, dy=0.0)

    def close_card(self):
        if self.tile is None:
            return
        self.tile = None
        threading.Thread(target=lambda: self.api.set_popover_activatable(False), daemon=True).start()
        self.root.animate(150, "out", alpha=0.0, dy=6.0)

        def finish():
            if self.tile is None:
                threading.Thread(target=self.api.close_popover, daemon=True).start()
        QTimer.singleShot(170, finish)

    def escape(self):
        if self.edit:
            self.set_edit(False)
        else:
            self.close_card()

    def arm(self):
        """The window is placed but hidden: take the backdrop of where it will appear, then say so."""
        self.glass = None
        self.invalidate_glass()
        done = threading.Event()
        self.arm_event = done

        def wait():
            done.wait(0.25)
            self.api.backdrop_armed()
        threading.Thread(target=wait, daemon=True).start()
        self.start_glass()

    def glass_changed(self):
        super().glass_changed()
        if self.arm_event is not None:
            self.arm_event.set()
            self.arm_event = None

    def shown_up(self):
        self.start_glass()

    # -- building the card ---------------------------------------------------------------------------------
    def set_edit(self, on):
        self.edit = on
        self.rebuild()

    def request_size(self):
        self.update_metrics()
        self.seq += 1
        seq, pw, ph = self.seq, self.pw, self.ph
        threading.Thread(target=lambda: self.api.resize_popover_window(pw, ph, seq), daemon=True).start()

    def rebuild(self):
        tile = self.tile
        if tile is None:
            return
        self.root.clear()
        for f in list(self.fields):
            self.fields.remove(f)
        state = self.states.get(tile["entity"])
        title = tile.get("room") or ((state or {}).get("attributes") or {}).get("friendly_name") or tile["entity"]
        self.root.add(Label(title, 19.5, QFont.Bold, "ink1", x=18, y=16, w=CARD_W - 18 - 16 - 32 - 8,
                            overflow="ellipsis"))
        self.root.add(Label(state["state"] if state else "無法連線", 14.5, QFont.Normal, "ink2", x=18, y=16 + 23.4))
        gear = Button(x=CARD_W - 16 - 32, y=16 + (40.8 - 32) / 2, w=32, h=32, icon=ICON_GEAR, icon_size=18,
                      on_click=lambda e: self.set_edit(not self.edit), active=self.edit, active_fill="btn_fill_strong",
                      active_color="btn_text")
        self.root.add(gear)
        top = 16 + 40.8 + 10
        body = View(0, 0, BODY_W, 0)
        stack = Stack(body, 0, 4, BODY_W)
        if self.edit:
            self.build_edit(stack)
        else:
            DETAIL.get(tile["domain"], build_readout)(self, stack, tile, state)
        content_h = stack.end() + 14
        body.h = content_h
        shown_h = min(content_h, BODY_MAX)
        scroll = ScrollView(BODY_X, top, BODY_W, shown_h - 0)
        body.x = 0
        scroll.add(body)
        scroll.content.w, scroll.content.h = BODY_W, content_h
        self.root.add(scroll)
        self.body_scroll = scroll
        self.set_css_size(CARD_W, top + shown_h)
        self.request_size()
        for f in self.fields:
            f.place()
        self.request_paint()

    # -- helpers for the builders ------------------------------------------------------------------------------
    def slider_block(self, stack, label, value, lo, hi, unit, on_commit, step=1):
        block = View(0, 0, BODY_W, 20 + 6 + 12)
        value_label = Label("%s%s" % (trim_number(value), unit), 15, QFont.Normal, "ink2", w=BODY_W, align="r")
        block.add(Label(label, 15, QFont.Normal, "ink2", w=BODY_W))
        block.add(value_label)
        for lab in block.children:
            lab.y = 0
        slider = Slider(0, 20 + 6 - 5, BODY_W, value, lo, hi, step,
                        on_input=lambda v: setattr(value_label, "text", "%s%s" % (trim_number(v), unit)),
                        on_commit=on_commit)
        block.add(slider)
        stack.place(block, 14, 14)

    def seg_row(self, stack, items):
        """items: [(label, on_click, active)]: equal capsules in a row."""
        n = len(items)
        gap = 8
        w = (BODY_W - gap * (n - 1)) / n
        row = View(0, 0, BODY_W, 38)
        for i, (label, click, active) in enumerate(items):
            row.add(Button(label, x=i * (w + gap), y=0, w=w, h=38, size=15.5, weight=QFont.Normal, active=active,
                           on_click=lambda e, c=click: c()))
        stack.place(row, 10, 10)

    def build_edit(self, stack):
        tile = self.tile
        stack.place(Label("圖示", 14.5, QFont.Bold, "ink2", w=BODY_W, spacing=0.4), 0, 8)
        # the swatches
        picker = View(0, 0, BODY_W, 0)
        current = tile.get("icon") or render.DEFAULT_ICON.get(tile["domain"], "sensor")
        x = y = 0
        for name in ICON_CHOICES:
            if x + 34 > BODY_W:
                x, y = 0, y + 34 + 8
            b = Button(x=x, y=y, w=34, h=34, icon=name, icon_size=18, ring="accent_blue" if name == current else None,
                       fill="btn_fill_strong" if name == current else "btn_fill",
                       on_click=lambda e, n=name: self.set_icon(n))
            b.ring_width = 2
            picker.add(b)
            x += 34 + 8
        picker.h = y + 34
        stack.place(picker, 8, 14)
        panel = self.prefs.get("panel") or {}
        home = tile["id"].startswith("home:")
        self.field(stack, "MDI 圖示名稱", tile.get("icon") if (tile.get("icon") or "").startswith("mdi:") else "",
                   "例如 mdi:air-conditioner", self.set_mdi, 80)
        self.field(stack, "名稱", tile.get("room") or "", "", self.set_room)
        if home:
            overrides = panel.get("room_overrides") or {}
            self.field(stack, "房間", overrides.get(tile["entity"], ""), "沿用 Home Assistant 的區域", self.set_area)
        self.field(stack, "類別名稱", tile.get("label") or "", "", self.set_label)
        done = Button("完成", size=15, pad=18, h=34, on_click=lambda e: self.set_edit(False), fill="accent_blue",
                      hover_fill="accent_blue", color="white")
        done.x = BODY_W - done.w
        row = View(0, 0, BODY_W, 34)
        row.add(done)
        done.x = BODY_W - done.w
        stack.place(row, 8, 0)

    def field(self, stack, label, value, placeholder, on_done, max_length=40):
        block = View(0, 0, BODY_W, 20 + 4 + 38)
        block.add(Label(label, 14.5, QFont.Normal, "ink2", w=BODY_W))
        block.add(TextField(0, 24, BODY_W, 38, value, placeholder, 15.5, on_done, max_length))
        stack.place(block, 0, 10)

    # -- edits --------------------------------------------------------------------------------------------------
    def persist(self):
        prefs = self.prefs

        def go():
            try:
                self.api.save_widgets(prefs.get("widgets"))
                if prefs.get("panel"):
                    self.api.save_panel(prefs["panel"])
            except Exception:
                traceback.print_exc()
        threading.Thread(target=go, daemon=True).start()

    def set_icon(self, name):
        self.tile["icon"] = name
        self.persist()
        self.rebuild()

    def set_mdi(self, text):
        value = text.strip().lower()
        if value and (not render.re.fullmatch(r"mdi:[a-z0-9-]+", value) or not render.mdi_path(value[4:])):
            for f in self.fields:
                if f.placeholder.startswith("例如"):
                    f.set_text(self.tile.get("icon") if (self.tile.get("icon") or "").startswith("mdi:") else "")
            return
        self.tile["icon"] = value
        self.persist()
        self.rebuild()

    def set_room(self, text):
        self.tile["room"] = text.strip() or self.tile["entity"]
        self.persist()

    def set_area(self, text):
        panel = self.prefs.setdefault("panel", {})
        overrides = dict(panel.get("room_overrides") or {})
        value = text.strip()
        if value:
            overrides[self.tile["entity"]] = value
        else:
            overrides.pop(self.tile["entity"], None)
        panel["room_overrides"] = overrides
        self.persist()

    def set_label(self, text):
        self.tile["label"] = text.strip()
        self.persist()


# ------------------------------------------------------------------------------------------------------------
# what each kind of device shows
# ------------------------------------------------------------------------------------------------------------

def _attrs(state):
    return (state or {}).get("attributes") or {}


def _toggle(domain):
    def build(card, stack, tile, state):
        on = bool(state) and state.get("state") == "on"
        icon = render.icon_name(tile, state)
        slab = ToggleSlab(BODY_W, icon, on, lambda: (card.optimistic(tile["entity"], {"state": "off" if on else "on"}),
                                                    card.call(domain, "toggle", tile["entity"])))
        stack.place(slab, 8, 16)
    return build


def build_light(card, stack, tile, state):
    attrs = _attrs(state)
    on = bool(state) and state.get("state") == "on"
    pct = round(attrs["brightness"] / 255 * 100) if attrs.get("brightness") is not None else 100
    color = "rgb(%d,%d,%d)" % tuple(attrs["rgb_color"][:3]) if isinstance(attrs.get("rgb_color"), list) else "accent_yellow"
    icon = tile.get("icon") or render.DEFAULT_ICON["light"]
    stack.place(AccessoryTile(BODY_W, icon, on, pct, color, ("%d%%" % pct) if on else "關閉",
                              lambda: (card.optimistic(tile["entity"], {"state": "off" if on else "on"}),
                                       card.call("light", "toggle", tile["entity"]))), 8, 16)
    if not on:
        return
    if attrs.get("brightness") is not None:
        card.slider_block(stack, "亮度", pct, 1, 100, "%",
                          lambda v: card.call("light", "turn_on", tile["entity"], {"brightness_pct": int(v)}))
    modes = attrs.get("supported_color_modes") or []
    if "color_temp" in modes:
        try:
            lo, hi = float(attrs["min_color_temp_kelvin"]), float(attrs["max_color_temp_kelvin"])
        except (KeyError, TypeError, ValueError):
            lo = hi = 0
        if lo > 0 and hi > lo:
            cur = attrs.get("color_temp_kelvin")
            val = cur if isinstance(cur, (int, float)) and lo <= cur <= hi else round((lo + hi) / 2)
            card.slider_block(stack, "色溫", val, lo, hi, "K",
                              lambda v: card.call("light", "turn_on", tile["entity"], {"color_temp_kelvin": int(v)}))
    if any(m in modes for m in ("hs", "rgb", "rgbw", "rgbww", "xy")):
        rgb = tuple(attrs.get("rgb_color") or (255, 255, 255))[:3]
        stack.place(ColorRow(BODY_W, rgb, lambda c: card.call("light", "turn_on", tile["entity"], {"rgb_color": c})), 10, 10)


def build_fan(card, stack, tile, state):
    attrs = _attrs(state)
    on = bool(state) and state.get("state") == "on"
    pct = attrs.get("percentage") if attrs.get("percentage") is not None else 100
    icon = tile.get("icon") or render.DEFAULT_ICON["fan"]
    stack.place(AccessoryTile(BODY_W, icon, on, pct, "accent_blue", ("%d%%" % pct) if on else "關閉",
                              lambda: (card.optimistic(tile["entity"], {"state": "off" if on else "on"}),
                                       card.call("fan", "toggle", tile["entity"]))), 8, 16)
    if on and attrs.get("percentage") is not None:
        card.slider_block(stack, "風速", attrs["percentage"], 0, 100, "%",
                          lambda v: card.call("fan", "set_percentage", tile["entity"], {"percentage": int(v)}), 10)


def build_lock(card, stack, tile, state):
    open_ = render.is_unlocked(state)
    slab = ToggleSlab(BODY_W, render.icon_name(tile, state), open_,
                      lambda: (card.optimistic(tile["entity"], {"state": "locked" if open_ else "unlocked"}),
                               card.call("lock", "lock" if open_ else "unlock", tile["entity"])))
    stack.place(slab, 8, 16)


def build_climate(card, stack, tile, state):
    attrs = _attrs(state)
    modes = attrs.get("hvac_modes") or ["off", "cool", "heat", "auto"]
    target, current = attrs.get("temperature"), attrs.get("current_temperature")
    big = Label("%s°" % (trim_number(target) if target is not None else "--"), 40, QFont.Bold, "ink1", w=BODY_W, align="c")
    stack.place(big, 4, 4)
    stack.place(Label(("目前 %s°" % trim_number(current)) if current is not None else "", 12.5, QFont.Normal, "ink2",
                      w=BODY_W, align="c"), 0, 10)
    step = float(tile.get("temp_step") or 1)

    def stepper(delta):
        if target is None:
            return
        nxt = round((target + delta) * 10) / 10
        card.optimistic(tile["entity"], {"attributes": dict(attrs, temperature=nxt)})
        card.call("climate", "set_temperature", tile["entity"], {"temperature": nxt})
    row = View(0, 0, BODY_W, 46)
    row.add(Button("−", x=BODY_W / 2 - 11 - 46, w=46, h=46, size=22, on_click=lambda e: stepper(-step)))
    row.add(Button("+", x=BODY_W / 2 + 11, w=46, h=46, size=22, on_click=lambda e: stepper(step)))
    stack.place(row, 8, 16)
    card.seg_row(stack, [(HVAC_LABELS.get(m, m),
                          (lambda m=m: (card.optimistic(tile["entity"], {"state": m}),
                                        card.call("climate", "set_hvac_mode", tile["entity"], {"hvac_mode": m}))),
                          bool(state) and state.get("state") == m) for m in modes])


def build_cover(card, stack, tile, state):
    attrs = _attrs(state)
    s = state.get("state") if state else ""
    card.seg_row(stack, [
        ("開", lambda: card.call("cover", "open_cover", tile["entity"]), s == "open"),
        ("停", lambda: card.call("cover", "stop_cover", tile["entity"]), False),
        ("關", lambda: card.call("cover", "close_cover", tile["entity"]), s == "closed")])
    if attrs.get("current_position") is not None:
        card.slider_block(stack, "開合程度", attrs["current_position"], 0, 100, "%",
                          lambda v: card.call("cover", "set_cover_position", tile["entity"], {"position": int(v)}))


def build_media(card, stack, tile, state):
    attrs = _attrs(state)
    if attrs.get("media_title"):
        stack.place(Label(" · ".join(x for x in (attrs.get("media_title"), attrs.get("media_artist")) if x),
                          12.5, QFont.Normal, "ink2", w=BODY_W, align="c", wrap=True), 0, 10)
    playing = bool(state) and state.get("state") == "playing"
    row = View(0, 0, BODY_W, 56)
    centre = BODY_W / 2
    row.add(Button(x=centre - 28 - 18 - 40, y=8, w=40, h=40, icon=ICON_PREV, icon_size=20,
                   on_click=lambda e: card.call("media_player", "media_previous_track", tile["entity"])))
    row.add(Button(x=centre - 28, y=0, w=56, h=56, icon=ICON_PAUSE if playing else ICON_PLAY, icon_size=24,
                   on_click=lambda e: card.call("media_player", "media_play_pause", tile["entity"])))
    row.add(Button(x=centre + 28 + 18, y=8, w=40, h=40, icon=ICON_NEXT, icon_size=20,
                   on_click=lambda e: card.call("media_player", "media_next_track", tile["entity"])))
    stack.place(row, 8, 16)
    if attrs.get("volume_level") is not None:
        card.slider_block(stack, "音量", round(attrs["volume_level"] * 100), 0, 100, "%",
                          lambda v: card.call("media_player", "volume_set", tile["entity"], {"volume_level": v / 100}))


def build_vacuum(card, stack, tile, state):
    s = state.get("state") if state else ""
    cleaning = s == "cleaning"
    card.seg_row(stack, [
        ("暫停" if cleaning else "開始",
         lambda: card.call("vacuum", "pause" if cleaning else "start", tile["entity"]), cleaning),
        ("回充", lambda: card.call("vacuum", "return_to_base", tile["entity"]), s == "returning")])


def build_readout(card, stack, tile, state):
    """Devices with no controls: the reading, large, and its history when it is a number."""
    text = (render.value_text(tile["domain"], state) or state["state"]) if state else "無法連線"
    stack.place(Label(text, 38, QFont.Bold, "ink1", w=BODY_W - 8, align="c", wrap=True, any_break=True), 22, 0)
    stack.place(Label(tile["entity"], 13, QFont.Normal, "ink2", w=BODY_W - 8, align="c", wrap=True, any_break=True), 6, 8)
    stack.y += 0
    try:
        numeric = bool(state) and float(state["state"]) == float(state["state"])
    except (TypeError, ValueError):
        numeric = False
    if numeric:
        block = View(0, 0, BODY_W, 16 + 4 + 64)
        block.add(Label("過去 %d 小時" % HISTORY_HOURS, 12, QFont.Normal, "ink2", w=BODY_W))
        rng = Label("", 12, QFont.Normal, "ink2", w=BODY_W, align="r")
        block.add(rng)
        chart = Chart(BODY_W)
        chart.y = 20
        block.add(chart)
        stack.place(block, 10, 0)
        card.history_token += 1
        token = card.history_token

        def load():
            try:
                res = card.api.get_history(tile["entity"], HISTORY_HOURS)
            except Exception:
                res = None

            def apply():
                if token != card.history_token:
                    return
                if not res or not res.get("ok") or len(res.get("points") or []) < 2:
                    chart.message = "沒有紀錄"
                else:
                    chart.points = res["points"]
                    vs = [v for _, v in res["points"]]
                    rng.text = "%s – %s" % (trim_number(min(vs)), trim_number(max(vs)))
                chart.changed()
            card.facade.run_on_ui_thread(apply)
        threading.Thread(target=load, daemon=True).start()


DETAIL = {"light": build_light, "fan": build_fan, "switch": _toggle("switch"), "input_boolean": _toggle("input_boolean"),
          "lock": build_lock, "climate": build_climate, "cover": build_cover, "media_player": build_media,
          "vacuum": build_vacuum}


def create_popover(api, x=200, y=200):
    return create_overlay(api, "HA Widget Detail", lambda facade: DetailCard(facade, api), x, y)
