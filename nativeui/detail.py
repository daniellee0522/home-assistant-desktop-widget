"""The detail of a tile: what a hold or a right-click on it opens.

The controls of each kind of device, the readout and history of a sensor, and the small edit panel
(icon, name, room, label), as DetailContent. A desktop widget's tile opens it in a window of its own
(DetailCard: main.py tells it which tile to show, Api.open_popover takes it to its place, and it closes
when focus leaves it); the tray panel shows it over its own tiles (panel.py).
"""
import threading
import time
import traceback

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainterPath, QPen

from . import appearance, controls, kinds, render, style, ui
from .overlay import OverlayScene, create_overlay
from .ui import Button, ScrollView, Slider, TextField, View

CARD_W = 320
BODY_X, BODY_W = 14, 292
BODY_MAX = 560
CARD_MAX_H = 760                     # the tallest the detail card beside a widget is made
HISTORY_HOURS = 24

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


class DetailContent:
    """What the detail of one tile shows, as views: its name and state, the gear for the edit panel, and the
    controls of its kind of device (DETAIL) or the edit panel. The detail card window (DetailCard) holds one,
    and so does the tray panel, which shows it over its own tiles.

    host: the Scene it is drawn in (its fields, its api). prefs: a callable giving the preferences now.
    states: the host's states, by entity. rebuilt: called when what is shown must be built again.
    on_close: what the x at the top-left does. area_of: the room of an entity, said above its name."""

    def __init__(self, host, prefs, states, rebuilt, on_close=None, area_of=None):
        self.host, self.api = host, host.api
        self._prefs, self.states, self.rebuilt = prefs, states, rebuilt
        self.on_close, self.area_of = on_close, area_of
        self.tile = None
        self.edit = False
        self.history_token = 0
        self.light_view = "brightness"      # what a light's tall slider sets: brightness or "temp"
        self.tall = TALL_H                  # how tall the tall controls are (less where there is less room)
        self.body_scroll = None
        self._built_for = None              # (tile, edit panel) last built: built again, it keeps its scroll

    @property
    def prefs(self):
        return self._prefs()

    def run_on_ui_thread(self, fn):
        self.host.facade.run_on_ui_thread(fn)

    # -- the tile ------------------------------------------------------------------------------------------
    def find_tile(self, tile_id):
        prefs = self.prefs
        for w in prefs.get("widgets", []):
            for t in w.get("tiles", []):
                if t.get("id") == tile_id:
                    return t
        panel = prefs.get("panel") or {}
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

    def open(self, tile_id):
        """Show this tile (False when there is no such tile)."""
        self.tile = self.find_tile(tile_id)
        self.edit = False
        self.light_view = "brightness"
        self._built_for = None
        self.tall_fit = TALL_H
        self.host.close_popup()
        return self.tile is not None

    def set_light_view(self, view):
        self.light_view = view
        self.rebuilt()

    def prefs_changed(self):
        """The preferences were replaced: the tile is read again. True when it should be built again (not
        while its edit panel is open, whose fields would lose what is being typed)."""
        if self.tile is None:
            return False
        self.tile = self.find_tile(self.tile["id"])
        return self.tile is not None and not self.edit

    def concerns(self, items):
        """Whether these new states change what is shown."""
        return bool(self.tile) and not self.edit and any(e == self.tile["entity"] for e, _ in items)

    def optimistic(self, entity, patch):
        st = self.states.get(entity)
        if st is not None:
            self.states[entity] = dict(st, **patch)
            if self.tile and not self.edit:
                self.rebuilt()

    def call(self, domain, service, entity, extra=None):
        def go():
            try:
                self.api.call_service(domain, service, entity, extra or {})
            except Exception:
                traceback.print_exc()
        threading.Thread(target=go, daemon=True).start()

    # -- the views -----------------------------------------------------------------------------------------
    def build(self, max_h=BODY_MAX + 67, fit=False):
        """The content, CARD_W wide and as tall as it needs up to max_h: the rest scrolls, or, with `fit`, the
        tall controls are made shorter until it all fits (and it is as tall as it needs: the tray panel scales
        it to its room). Built again for the same tile, it keeps where it was scrolled to."""
        if not fit or self.edit:                # (the edit panel scrolls: it has every icon)
            self.tall = TALL_H
            return self._build(max_h)
        self.tall = getattr(self, "tall_fit", TALL_H)
        out = self._build(float("inf"))
        for _ in range(3):                      # (a control or two follow the tall one's height loosely)
            if out.h <= max_h + 0.01 or self.tall <= TALL_MIN:
                break
            self.tall = max(TALL_MIN, self.tall - (out.h - max_h))
            out = self._build(float("inf"))
        self.tall_fit = self.tall               # no taller again while this device is shown: no jumping
        return out

    def _build(self, max_h):
        tile = self.tile
        same = self._built_for == (tile["id"], self.edit)
        keep = self.body_scroll.offset if (same and self.body_scroll is not None) else 0.0
        self._built_for = (tile["id"], self.edit)
        out = View(0, 0, CARD_W, 0)
        state = self.states.get(tile["entity"])
        title = tile.get("room") or ((state or {}).get("attributes") or {}).get("friendly_name") or tile["entity"]
        # the header: close, where it is and what it is, the edit panel
        left = 18
        if self.on_close is not None:
            out.add(Button(x=10, y=12, w=36, h=36, icon="mdi:close", icon_size=22, fill=None, hover_fill="btn_fill",
                           on_click=lambda e: self.on_close()))
            left = 10 + 36 + 6
        area = self.area_of(tile["entity"]) if self.area_of else ""
        tw = CARD_W - left - 10 - 36 - 8
        if area:
            out.add(style.label("eyebrow", area, x=left, y=10, w=tw, overflow="ellipsis"))
        out.add(style.label("title", title, x=left, y=26 if area else 18, w=tw, overflow="ellipsis"))
        out.add(Button(x=CARD_W - 10 - 36, y=12, w=36, h=36, icon="mdi:cog", icon_size=20, fill=None,
                       hover_fill="btn_fill", on_click=lambda e: self.set_edit(not self.edit), active=self.edit,
                       active_fill="btn_fill_strong", active_color="btn_text"))
        top = 60
        body = View(0, 0, BODY_W, 0)
        stack = Stack(body, 0, 4, BODY_W)
        if self.edit:
            self.build_edit(stack)
        else:
            DETAIL.get(tile["domain"], build_readout)(self, stack, tile, state)
        content_h = stack.end() + 14
        body.h = content_h
        shown_h = max(60, min(content_h, max_h - top))
        scroll = ScrollView(BODY_X, top, BODY_W, shown_h, fade=24 if content_h > shown_h else 0)
        scroll.add(body)
        scroll.content.w, scroll.content.h = BODY_W, content_h
        scroll.scroll_to(keep)
        out.add(scroll)
        out.h = top + shown_h
        self.body_scroll = scroll
        return out

    # -- the edit panel ----------------------------------------------------------------------------------------
    def set_edit(self, on):
        self.edit = on
        self.rebuilt()

    def build_edit(self, stack):
        """The edit panel: every icon, those that also change what the tile is shown as (its colours, its words,
        this screen) apart from those that only change its picture; an MDI name for any other; its name (and
        room); a reset."""
        tile = self.tile
        own, can = appearance.domain_families(tile["domain"])
        current = tile.get("icon") or appearance.own_icon(tile)
        onoff = len(can) > 1
        stack.place(style.label("section", "外觀" if onoff else "圖示", w=BODY_W, spacing=0.4), 0, 2)
        stack.place(style.label("caption", "選這些會一併改變顏色、狀態文字與控制畫面" if onoff else
                                "同類型的不同造型", w=BODY_W, wrap=True), 2, 8)
        for fam in can:
            if onoff:
                stack.place(style.label("label", appearance.FAMILIES[fam][0], w=BODY_W), 4, 4)
            stack.place(self.icon_grid(appearance.FAMILIES[fam][1], current, 36), 2, 8)
        others = [i for fam, (_, icons) in appearance.FAMILIES.items() if fam not in can for i in icons]
        stack.place(style.label("section", "其他圖示", w=BODY_W, spacing=0.4), 12, 2)
        stack.place(style.label("caption", "只換圖示，不改變樣式；更多圖示請在下方輸入 MDI 名稱", w=BODY_W, wrap=True), 2, 8)
        stack.place(self.icon_grid(others, current, 30), 2, 8)
        panel = self.prefs.get("panel") or {}
        home = tile["id"].startswith("home:")
        mdi = current if current.startswith("mdi:") and not appearance.family_of_icon(current) else ""
        self.field(stack, "MDI 圖示名稱", mdi, "例如 mdi:air-conditioner", self.set_mdi, 80)
        self.field(stack, "名稱", tile.get("room") or "", "", self.set_room)
        if home:
            overrides = panel.get("room_overrides") or {}
            self.field(stack, "房間", overrides.get(tile["entity"], ""), "沿用 Home Assistant 的區域", self.set_area)
        row = View(0, 0, BODY_W, 34)
        reset = Button("重置", size=15, pad=18, h=34, on_click=lambda e: self.reset(), color="accent_red")
        done = Button("完成", size=15, pad=18, h=34, on_click=lambda e: self.set_edit(False), fill="accent_blue",
                      hover_fill="accent_blue", color="white")
        row.add(reset, done)
        done.x = BODY_W - done.w
        stack.place(row, 10, 0)

    def icon_grid(self, icons, current, size):
        grid = View(0, 0, BODY_W, 0)
        gap = 8
        per = max(1, int((BODY_W + gap) // (size + gap)))
        for i, name in enumerate(icons):
            r, c = divmod(i, per)
            chosen = name == current
            b = Button(x=c * (size + gap), y=r * (size + gap), w=size, h=size, icon=name, icon_size=size * 0.52,
                       ring="accent_blue" if chosen else None, fill="btn_fill_strong" if chosen else "btn_fill",
                       on_click=lambda e, n=name: self.set_icon(n))
            b.ring_width = 2
            grid.add(b)
        grid.h = ((len(icons) + per - 1) // per) * (size + gap) - gap if icons else 0
        return grid

    def reset(self):
        """Back to what Home Assistant says: the family's own icon and the device's own name."""
        st = self.states.get(self.tile["entity"])
        self.tile["icon"] = ""
        self.tile["room"] = ((st or {}).get("attributes") or {}).get("friendly_name") or self.tile["entity"]
        self.persist()
        self.rebuilt()

    def field(self, stack, label, value, placeholder, on_done, max_length=40):
        block = View(0, 0, BODY_W, 20 + 4 + 38)
        block.add(style.label("section", label, w=BODY_W))
        block.add(TextField(0, 24, BODY_W, 38, value, placeholder, 15.5, on_done, max_length))
        stack.place(block, 0, 10)

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
        self.rebuilt()

    def set_mdi(self, text):
        value = text.strip().lower()
        if value and (not render.re.fullmatch(r"mdi:[a-z0-9-]+", value) or not render.mdi_path(value[4:])):
            for f in self.host.fields:
                if f.placeholder.startswith("例如"):
                    f.set_text(self.tile.get("icon") if (self.tile.get("icon") or "").startswith("mdi:") else "")
            return
        self.tile["icon"] = value
        self.persist()
        self.rebuilt()

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



class DetailCard(OverlayScene):
    """The detail card as a window of its own, over a desktop widget's tile."""

    def __init__(self, facade, api):
        super().__init__(facade, api, "popover")
        self.lensed = False                       # the lens belongs to the widget: this is a quiet pane
        self.prefs = api._prefs()
        self.states = {}
        self.content = DetailContent(self, lambda: self.prefs, self.states, self.rebuild, on_close=self.close_card)
        self.owner = None
        self.seq = 0
        self.arm_event = None
        self.sampling = "live"
        self.configure()
        self.retheme()
        threading.Thread(target=self._load_states, daemon=True).start()

    @property
    def tile(self):
        return self.content.tile

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
        self.prefs = prefs
        self.configure()
        if before != (self.theme_raw, self.style, self.language, self.zoom_css, self.system_glass):
            self.retheme()
            self.update_metrics()
            self.invalidate_glass()
        if self.content.prefs_changed():
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
        return self.content.find_tile(tile_id)

    def push_states(self, items):
        for entity, state in items:
            self.states[entity] = state
        if self.content.concerns(items):
            self.rebuild()

    def optimistic(self, entity, patch):
        self.content.optimistic(entity, patch)

    # -- opening and closing --------------------------------------------------------------------------------
    def open_tile(self, tile_id):
        if not self.content.open(tile_id):
            return
        self.root.stop_animation()
        self.root.alpha, self.root.dy = 0.0, 6.0
        self.rebuild()
        threading.Thread(target=lambda: self.api.set_popover_activatable(True), daemon=True).start()

    def enter(self):
        self.root.animate(150, "out", alpha=1.0, dy=0.0)

    def close_card(self):
        if self.tile is None:
            return
        self.content.tile = None
        self.close_popup()
        threading.Thread(target=lambda: self.api.set_popover_activatable(False), daemon=True).start()
        self.root.animate(150, "out", alpha=0.0, dy=6.0)

        def finish():
            if self.tile is None:
                threading.Thread(target=self.api.close_popover, daemon=True).start()
        QTimer.singleShot(170, finish)

    def escape(self):
        if self.popup is not None:
            self.close_popup()
        elif self.content.edit:
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
        self.content.set_edit(on)

    def set_icon(self, name):
        self.content.set_icon(name)

    def set_room(self, text):
        self.content.set_room(text)

    def request_size(self):
        """The window takes the card's size now, on this thread: asked from another, it could land after the
        window was shown at its old size, the bottom of the card cut off."""
        self.update_metrics()
        self.seq += 1
        try:
            self.api.resize_popover_window(self.pw, self.ph, self.seq)
        except Exception:
            traceback.print_exc()

    def room(self):
        """How tall the card can be, in its own px: the work area of its screen, less a margin."""
        screen = self.screen()
        if screen is None or not self.scale:
            return BODY_MAX + 67
        return max(320.0, screen.availableGeometry().height() * screen.devicePixelRatio() / self.scale - 24)

    def rebuild(self):
        if self.tile is None:
            return
        self.root.clear()
        for f in list(self.fields):
            self.fields.remove(f)
        # all of it shown, as in the tray panel: the tall controls made shorter, then smaller if it must be
        room = min(self.room(), CARD_MAX_H)
        view = self.content.build(max_h=room, fit=True)
        k = min(1.0, room / view.h)
        holder = View(0, 0, CARD_W * k, view.h * k)
        view.scale = k
        holder.add(view)
        self.root.add(holder)
        controls.reattach_menu(self, view)      # a menu open over it stays, over the new card
        self.body_scroll = self.content.body_scroll
        self.set_css_size(CARD_W * k, view.h * k)
        self.request_size()
        for f in self.fields:
            f.place()
        self.request_paint()


# ------------------------------------------------------------------------------------------------------------
# what each kind of device shows (after Home Assistant's more-info dialogs)
# ------------------------------------------------------------------------------------------------------------

STATE_TEXT = {
    "lock": {"locked": "已上鎖", "unlocked": "已解鎖", "jammed": "卡住了", "locking": "上鎖中", "unlocking": "解鎖中",
             "open": "已開啟", "opening": "開啟中"},
    "cover": {"open": "開啟", "closed": "關閉", "opening": "開啟中", "closing": "關閉中"},
    "vacuum": {"cleaning": "清掃中", "docked": "已回充", "returning": "回充中", "paused": "已暫停", "idle": "待命",
               "error": "錯誤"},
}
TALL_W, TALL_H = 120, 220
TALL_MIN = 150                       # the shortest a tall control is made to fit the tray panel


def _attrs(state):
    return (state or {}).get("attributes") or {}


def centered(stack, view, mt=0, mb=0):
    """A view in the middle of the body's width."""
    row = View(0, 0, BODY_W, view.h)
    view.x, view.y = (BODY_W - view.w) / 2, 0
    row.add(view)
    return stack.place(row, mt, mb)


def big_value(stack, text, state, mt=6):
    """The state, large, and how long ago it changed; the label is returned to follow a slider."""
    label = style.label("display", text, w=BODY_W, align="c")
    stack.place(label, mt, 2)
    since = controls.ago((state or {}).get("last_changed"))
    if since:
        stack.place(style.label("meta", since, w=BODY_W, align="c"), 0, 14)
    return label


def cards(card, stack, items):
    """Mode cards two to a row; pressed, one opens its choices in a menu over the screen.
    items: [(icon, title, current label, [(value, label)], on_pick)]."""
    if not items:
        return
    gap = 10
    w = (BODY_W - gap) / 2 if len(items) > 1 else min(BODY_W, 190)
    for i in range(0, len(items), 2):
        row = View(0, 0, BODY_W, 62)
        pair = items[i:i + 2]
        left = (BODY_W - (len(pair) * w + (len(pair) - 1) * gap)) / 2
        for j, (icon, title, value, options, pick) in enumerate(pair):
            current = next((v for v, lab in options if lab == value), None)
            mc = controls.ModeCard(w, icon, title, value, options, pick, current)
            mc.x = left + j * (w + gap)
            row.add(mc)
        stack.place(row, 8, 8)


def build_onoff(card, stack, tile, state):
    """A thing switched on and off, shown as its family (appearance.py): its words, its colour, its icon; as a
    lock, the lock's own screen."""
    if appearance.family(tile) == "lock":
        return build_lock(card, stack, tile, state)
    on = bool(state) and state.get("state") == "on"
    on_words, off_words = appearance.words(tile)
    big_value(stack, on_words if on else off_words, state)
    color = "accent_" + appearance.COLORS.get(appearance.family(tile), "blue")
    if appearance.family(tile) == "light":
        color = render.light_color(state if tile["domain"] == "light" else None, "dark")
    centered(stack, controls.TallSwitch(TALL_W, card.tall, on, color, render.icon_name(tile, state),
                                        lambda: (card.optimistic(tile["entity"], {"state": "off" if on else "on"}),
                                                 card.call(tile["domain"], "toggle", tile["entity"]))), 4, 16)


def build_light(card, stack, tile, state):
    attrs = _attrs(state)
    on = bool(state) and state.get("state") == "on"
    entity = tile["entity"]
    pct = round(attrs["brightness"] / 255 * 100) if attrs.get("brightness") is not None else (100 if on else 0)
    modes = attrs.get("supported_color_modes") or []
    rgb = attrs.get("rgb_color") if isinstance(attrs.get("rgb_color"), list) else None
    color = "rgb(%d,%d,%d)" % tuple(rgb[:3]) if rgb else "accent_yellow"
    temps = "color_temp" in modes
    try:
        lo_k, hi_k = float(attrs["min_color_temp_kelvin"]), float(attrs["max_color_temp_kelvin"])
    except (KeyError, TypeError, ValueError):
        lo_k = hi_k = 0.0
    temps = temps and lo_k > 0 and hi_k > lo_k
    view = card.light_view if (card.light_view != "temp" or (temps and on)) else "brightness"
    label = big_value(stack, ("%d%%" % pct) if on else "關閉", state)
    if view == "temp":
        cur = attrs.get("color_temp_kelvin")
        val = cur if isinstance(cur, (int, float)) and lo_k <= cur <= hi_k else round((lo_k + hi_k) / 2)
        warm, cool = kelvin_css(lo_k), kelvin_css(hi_k)
        slider = controls.TallSlider(TALL_W, card.tall, val, lo_k, hi_k, color, step=50,
                                     gradient=[(0, warm), (1, cool)],
                                     on_input=lambda v: setattr(label, "text", "%dK" % v),
                                     on_commit=lambda v: card.call("light", "turn_on", entity, {"color_temp_kelvin": int(v)}))
    else:
        def commit(v):
            if v <= 0:
                card.optimistic(entity, {"state": "off"})
                card.call("light", "turn_off", entity)
            else:
                card.call("light", "turn_on", entity, {"brightness_pct": int(v)})
        slider = controls.TallSlider(TALL_W, card.tall, pct if on else 0, 0, 100, color,
                                     on_input=lambda v: setattr(label, "text", ("%d%%" % v) if v else render.tr("關閉")),
                                     on_commit=commit)
    centered(stack, slider, 4, 14)
    bar = [("mdi:power", False, lambda: (card.optimistic(entity, {"state": "off" if on else "on"}),
                                        card.call("light", "toggle", entity))),
           ("mdi:brightness6", view == "brightness", lambda: card.set_light_view("brightness"))]
    if temps and on:
        bar.append(("mdi:thermometer", view == "temp", lambda: card.set_light_view("temp")))
    centered(stack, controls.ModeBar(bar), 4, 14)
    swatches = []
    if temps:
        for k in (2700, 3500, 4500, 6000):
            k = max(lo_k, min(hi_k, k))
            swatches.append((kelvin_css(k), ("k", int(k))))
    if any(m in modes for m in ("hs", "rgb", "rgbw", "rgbww", "xy")):
        swatches.append(("rainbow", ("pick", None)))

    def pick(value):
        kind, v = value
        if kind == "k":
            card.call("light", "turn_on", entity, {"color_temp_kelvin": v})
        else:
            controls.open_colors(sw, tuple(rgb[:3]) if rgb else None,
                                 lambda c: card.call("light", "turn_on", entity, {"rgb_color": list(c)}))
    if swatches:
        sw = controls.Swatches(BODY_W, swatches, pick)
        sw.key, sw.open = "colors", False
        stack.place(sw, 4, 14)
    effects = attrs.get("effect_list") or []
    if effects and on:
        cards(card, stack, [("mdi:auto-fix", "特效", attrs.get("effect") or "無",
                             [(e, e) for e in effects],
                             lambda v: card.call("light", "turn_on", entity, {"effect": v}))])


def kelvin_css(k):
    return "rgb(%d,%d,%d)" % controls.kelvin_rgb(k)


def build_fan(card, stack, tile, state):
    attrs = _attrs(state)
    on = bool(state) and state.get("state") == "on"
    entity = tile["entity"]
    if attrs.get("percentage") is None:
        return build_onoff(card, stack, tile, state)
    pct = attrs["percentage"] if on else 0
    label = big_value(stack, ("%d%%" % pct) if on else "關閉", state)

    def commit(v):
        if v <= 0:
            card.optimistic(entity, {"state": "off"})
            card.call("fan", "turn_off", entity)
        else:
            card.call("fan", "set_percentage", entity, {"percentage": int(v)})
    step = attrs.get("percentage_step") or 1
    centered(stack, controls.TallSlider(TALL_W, card.tall, pct, 0, 100, "accent_blue", step=step,
                                        on_input=lambda v: setattr(label, "text", ("%d%%" % v) if v else render.tr("關閉")),
                                        on_commit=commit), 4, 14)
    centered(stack, controls.ModeBar([("mdi:power", on, lambda: (card.optimistic(entity, {"state": "off" if on else "on"}),
                                                                 card.call("fan", "toggle", entity)))]), 4, 14)
    presets = attrs.get("preset_modes") or []
    if presets:
        cards(card, stack, [("mdi:fan", "預設模式", attrs.get("preset_mode") or "無",
                             [(p, p) for p in presets],
                             lambda v: card.call("fan", "set_preset_mode", entity, {"preset_mode": v}))])


def build_lock(card, stack, tile, state):
    """A lock, and anything shown as one (a switch given a lock's icon): the same screen. The tall switch is
    up and green when locked; its words are the tile's (render.state_text)."""
    s = (state or {}).get("state")
    entity = tile["entity"]
    if tile["domain"] == "lock":
        locked = s == "locked"
        act = lambda: (card.optimistic(entity, {"state": "unlocked" if locked else "locked"}),
                       card.call("lock", "unlock" if locked else "lock", entity))
    else:                                   # a switch shown as a lock: on is unlocked (appearance.WORDS)
        locked = s != "on"
        act = lambda: (card.optimistic(entity, {"state": "on" if locked else "off"}),
                       card.call(tile["domain"], "toggle", entity))
    big_value(stack, render.state_text(tile, state) if state else "無法連線", state)
    centered(stack, controls.TallSwitch(TALL_W, card.tall, locked, "accent_green", render.icon_name(tile, state),
                                        act), 4, 16)


def build_climate(card, stack, tile, state):
    attrs = _attrs(state)
    entity = tile["entity"]
    mode = (state or {}).get("state") or "off"
    target, current = attrs.get("temperature"), attrs.get("current_temperature")
    humidity = attrs.get("current_humidity")
    # the room: temperature and humidity, side by side
    readings = [(lab, val) for lab, val in (("目前溫度", None if current is None else "%s°" % trim_number(current)),
                                            ("目前濕度", None if humidity is None else "%s%%" % trim_number(humidity)))
                if val is not None]
    if readings:
        row = View(0, 0, BODY_W, 44)
        w = BODY_W / len(readings)
        for i, (lab, val) in enumerate(readings):
            row.add(style.label("label", lab, x=i * w, y=0, w=w, align="c"))
            row.add(style.label("headline", val, x=i * w, y=18, w=w, align="c"))
        stack.place(row, 2, 8)
    step = float(attrs.get("target_temp_step") or tile.get("temp_step") or 1)
    lo, hi = float(attrs.get("min_temp") or 7), float(attrs.get("max_temp") or 35)

    def commit(v):
        card.optimistic(entity, {"attributes": dict(attrs, temperature=v)})
        card.call("climate", "set_temperature", entity, {"temperature": v})
    dial = controls.Dial(card.tall + 16, target, lo, hi, step, current, HVAC_LABELS.get(mode, mode),
                         None if mode == "off" else render.HVAC_COLORS.get(mode, "accent_cyan"), on_commit=commit)
    centered(stack, dial, 0, 0)

    def stepper(delta):
        if target is not None:
            commit(max(lo, min(hi, round((target + delta) * 10) / 10)))
    row = View(0, 0, BODY_W, 52)
    for i, (sign, delta) in enumerate((("mdi:minus", -step), ("mdi:plus", step))):
        b = Button(x=BODY_W / 2 + (-12 - 52 if i == 0 else 12), y=0, w=52, h=52, icon=sign, icon_size=22,
                   fill=None, ring="ink2", hover_fill="btn_fill", on_click=lambda e, d=delta: stepper(d))
        row.add(b)
    stack.place(row, 0, 14)
    items = [("mdi:power" if mode == "off" else "mdi:thermostat", "模式", HVAC_LABELS.get(mode, mode),
              [(m, HVAC_LABELS.get(m, m)) for m in (attrs.get("hvac_modes") or ["off", "cool", "heat", "auto"])],
              lambda m: (card.optimistic(entity, {"state": m}),
                         card.call("climate", "set_hvac_mode", entity, {"hvac_mode": m})))]
    if attrs.get("fan_modes"):
        items.append(("mdi:fan", "風速模式", FAN_LABELS.get(attrs.get("fan_mode"), attrs.get("fan_mode") or "無"),
                      [(m, FAN_LABELS.get(m, m)) for m in attrs["fan_modes"]],
                      lambda m: card.call("climate", "set_fan_mode", entity, {"fan_mode": m})))
    if attrs.get("preset_modes"):
        items.append(("mdi:tune-variant", "預設模式", attrs.get("preset_mode") or "無",
                      [(m, m) for m in attrs["preset_modes"]],
                      lambda m: card.call("climate", "set_preset_mode", entity, {"preset_mode": m})))
    cards(card, stack, items)


FAN_LABELS = {"auto": "自動", "low": "低", "medium": "中", "high": "高", "middle": "中", "silent": "靜音",
              "quiet": "靜音", "turbo": "強力", "strong": "強"}


def build_cover(card, stack, tile, state):
    attrs = _attrs(state)
    entity = tile["entity"]
    s = (state or {}).get("state") or ""
    pos = attrs.get("current_position")
    label = big_value(stack, ("%d%%" % pos) if pos is not None else STATE_TEXT["cover"].get(s, s or "無法連線"), state)
    if pos is not None:
        centered(stack, controls.TallSlider(TALL_W, card.tall, pos, 0, 100, "accent_blue",
                                            on_input=lambda v: setattr(label, "text", "%d%%" % v),
                                            on_commit=lambda v: card.call("cover", "set_cover_position", entity,
                                                                         {"position": int(v)})), 4, 14)
    centered(stack, controls.ModeBar([
        ("mdi:arrow-up", s == "open", lambda: card.call("cover", "open_cover", entity)),
        ("mdi:stop", False, lambda: card.call("cover", "stop_cover", entity)),
        ("mdi:arrow-down", s == "closed", lambda: card.call("cover", "close_cover", entity))]), 4, 14)


def build_media(card, stack, tile, state):
    attrs = _attrs(state)
    entity = tile["entity"]
    s = (state or {}).get("state") or ""
    playing = s == "playing"
    art = attrs.get("entity_picture")
    side = card.tall - 24
    centered(stack, controls.Picture(side, side, art, card.api.get_picture, card.run_on_ui_thread), 4, 16)
    title = attrs.get("media_title") or STATE_TEXT.get("media", {}).get(s) or s
    stack.place(style.label("headline", title, w=BODY_W, overflow="ellipsis"), 0, 2)
    artist = attrs.get("media_artist") or attrs.get("app_name") or ""
    if artist:
        stack.place(style.label("secondary", artist, w=BODY_W, overflow="ellipsis"), 0, 10)
    if attrs.get("media_duration"):
        def seek(s):
            card.optimistic(entity, {"attributes": dict(attrs, media_position=s,
                                                        media_position_updated_at=controls.now_iso())})
            card.call("media_player", "media_seek", entity, {"seek_position": round(s, 1)})
        can_seek = int(attrs.get("supported_features") or 0) & 2      # MediaPlayerEntityFeature.SEEK
        stack.place(controls.Progress(BODY_W, attrs.get("media_position"), attrs.get("media_position_updated_at"),
                                      attrs.get("media_duration"), playing, on_seek=seek if can_seek else None), 6, 6)
    row = View(0, 0, BODY_W, 64)
    buttons = []
    if "shuffle" in attrs:
        buttons.append((40, "mdi:shuffle-variant" if attrs.get("shuffle") else "mdi:shuffle-disabled",
                        lambda: card.call("media_player", "shuffle_set", entity, {"shuffle": not attrs.get("shuffle")})))
    buttons.append((44, "mdi:skip-previous", lambda: card.call("media_player", "media_previous_track", entity)))
    buttons.append((64, "mdi:pause" if playing else "mdi:play",
                    lambda: (card.optimistic(entity, kinds.play_pause_patch(state)),
                             card.call("media_player", "media_play_pause", entity))))
    buttons.append((44, "mdi:skip-next", lambda: card.call("media_player", "media_next_track", entity)))
    if "repeat" in attrs:
        nxt = {"off": "all", "all": "one", "one": "off"}.get(attrs.get("repeat"), "off")
        buttons.append((40, {"one": "mdi:repeat-once", "all": "mdi:repeat"}.get(attrs.get("repeat"), "mdi:repeat-off"),
                        lambda: card.call("media_player", "repeat_set", entity, {"repeat": nxt})))
    gap = 12
    x = (BODY_W - (sum(b[0] for b in buttons) + gap * (len(buttons) - 1))) / 2
    can = kinds.media_controls(state)
    needs = {"mdi:skip-previous": "previous", "mdi:skip-next": "next", "mdi:pause": "play_pause",
             "mdi:play": "play_pause"}
    for size, icon, click in buttons:
        big = size == 64
        b = Button(x=x, y=(64 - size) / 2, w=size, h=size, icon=icon, icon_size=28 if big else 22,
                   fill="accent_blue" if big else None, hover_fill="accent_blue" if big else "btn_fill",
                   color="white" if big else "ink1", on_click=lambda e, c=click: c())
        if icon in needs and needs[icon] not in can:     # nothing playing, or the player cannot: inert
            b.alpha, b.interactive = 0.35, False
        row.add(b)
        x += size + gap
    stack.place(row, 8, 8)
    if attrs.get("volume_level") is not None:
        vol = View(0, 0, BODY_W, 30)
        muted = attrs.get("is_volume_muted")
        vol.add(Button(x=0, y=0, w=30, h=30, icon="mdi:volume-off" if muted else "mdi:volume-high", icon_size=18, fill=None,
                       hover_fill="btn_fill",
                       on_click=lambda e: card.call("media_player", "volume_mute", entity, {"is_volume_muted": not muted})))
        vol.add(Slider(40, 4, BODY_W - 40, round(attrs["volume_level"] * 100), 0, 100, 1,
                       on_commit=lambda v: card.call("media_player", "volume_set", entity, {"volume_level": v / 100})))
        stack.place(vol, 6, 10)
    items = []
    if attrs.get("source_list"):
        items.append(("mdi:import", "來源", attrs.get("source") or "無", [(x, x) for x in attrs["source_list"]],
                      lambda v: card.call("media_player", "select_source", entity, {"source": v})))
    off = s in ("off", "standby", "")
    items.append(("mdi:power", "電源", "關閉" if off else "開啟", [("on", "開啟"), ("off", "關閉")],
                  lambda v: card.call("media_player", "turn_on" if v == "on" else "turn_off", entity)))
    cards(card, stack, items)


def build_vacuum(card, stack, tile, state):
    s = state.get("state") if state else ""
    cleaning = s == "cleaning"
    big_value(stack, STATE_TEXT["vacuum"].get(s, s or "無法連線"), state)
    centered(stack, controls.ModeBar([
        ("mdi:pause" if cleaning else "mdi:play", cleaning,
         lambda: card.call("vacuum", "pause" if cleaning else "start", tile["entity"])),
        ("mdi:home-import-outline", s == "returning", lambda: card.call("vacuum", "return_to_base", tile["entity"]))]),
        8, 14)


def build_readout(card, stack, tile, state):
    """Devices with no controls: the reading, large, and its history when it is a number."""
    text = (render.value_text(tile["domain"], state) or state["state"]) if state else "無法連線"
    stack.place(style.label("display", text, w=BODY_W - 8, align="c", wrap=True, any_break=True), 22, 0)
    since = controls.ago((state or {}).get("last_changed"))
    stack.place(style.label("meta", since or tile["entity"], w=BODY_W - 8, align="c", wrap=True,
                      any_break=True), 6, 8)
    try:
        numeric = bool(state) and float(state["state"]) == float(state["state"])
    except (TypeError, ValueError):
        numeric = False
    if numeric:
        block = View(0, 0, BODY_W, 16 + 4 + 64)
        block.add(style.label("caption", "過去 %d 小時" % HISTORY_HOURS, w=BODY_W))
        rng = style.label("caption", "", w=BODY_W, align="r")
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
            card.run_on_ui_thread(apply)
        threading.Thread(target=load, daemon=True).start()


def build_weather(card, stack, tile, state):
    """Now, large, and the coming days, each with its low and high (fetched once, then kept on the card)."""
    from . import kinds
    attrs = _attrs(state)
    icon, text = kinds.condition(state)
    centered(stack, ui.IconView(icon, "ink1", size=52), 4, 0)
    stack.place(style.label("hero", "%s°" % trim_number(attrs["temperature"]) if attrs.get("temperature") is not None
                            else "--", w=BODY_W, align="c"), 0, 0)
    stack.place(style.label("headline", text, w=BODY_W, align="c"), 2, 4)
    extra = " · ".join(x for x in (("%s %s%%" % (render.tr("濕度"), trim_number(attrs["humidity"])))
                                   if attrs.get("humidity") is not None else "",
                                   controls.ago((state or {}).get("last_changed"))) if x)
    if extra:
        stack.place(style.label("meta", extra, w=BODY_W, align="c"), 0, 14)
    kept = getattr(card, "forecast", None)
    if not kept or kept[0] != tile["entity"]:
        stack.place(style.label("meta", "載入中…", w=BODY_W, align="c"), 6, 8)
        entity = tile["entity"]

        def load():
            try:
                days = card.api.get_forecast(entity)
            except Exception:
                days = []

            def apply():
                card.forecast = (entity, days)
                if card.tile and card.tile["entity"] == entity:
                    card.rebuilt()
            card.run_on_ui_thread(apply)
        threading.Thread(target=load, daemon=True).start()
        return
    days = kept[1][:7]
    if not days:
        stack.place(style.label("meta", "沒有預報", w=BODY_W, align="c"), 6, 8)
    for i, d in enumerate(days):
        r = View(0, 0, BODY_W, 40)
        r.add(style.label("body", kinds._day(d.get("datetime"), i), x=4, y=10, w=80))
        r.add(ui.IconView("mdi:" + kinds.CONDITIONS.get(d.get("condition"), ("weather-cloudy",))[0], "ink1",
                          x=96, y=7, size=26))
        lo = d.get("templow")
        r.add(style.label("body", ("%s°" % trim_number(lo)) if lo is not None else "", color="ink2", x=BODY_W - 120,
                    y=10, w=50, align="r"))
        r.add(style.label("body", "%s°" % trim_number(d.get("temperature")) if d.get("temperature") is not None else "--",
                                 x=BODY_W - 60, y=10, w=56, align="r"))
        stack.place(r, 0, 2)


def build_camera(card, stack, tile, state):
    """The camera's view, large; a new one each time the card is built."""
    attrs = _attrs(state)
    url = attrs.get("entity_picture") or "/api/camera_proxy/" + tile["entity"]
    url += ("&" if "?" in url else "?") + "_=%d" % (time.time() // 5)
    stack.place(controls.Picture(BODY_W, round(BODY_W * 9 / 16), url, card.api.get_picture, card.run_on_ui_thread,
                                 icon="mdi:cctv"), 4, 10)
    since = controls.ago((state or {}).get("last_changed"))
    stack.place(style.label("meta", " · ".join(x for x in ((state or {}).get("state") or "", since) if x),
                      w=BODY_W, align="c"), 0, 10)


DETAIL = {"light": build_light, "fan": build_fan, "switch": build_onoff, "input_boolean": build_onoff,
          "lock": build_lock, "climate": build_climate, "cover": build_cover, "media_player": build_media,
          "vacuum": build_vacuum, "weather": build_weather, "camera": build_camera}


def create_popover(api, x=200, y=200):
    return create_overlay(api, "HA Widget Detail", lambda facade: DetailCard(facade, api), x, y)
