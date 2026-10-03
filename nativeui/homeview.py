"""The Home view of the tray panel: capsules for the kinds of device, the rooms as capsules, and the
accessories under each room in the widget's own shapes.

The rules are homemodel.py's; the editing (moving, resizing, removing, reordering) is homeedit.py's.
Sizes are in the panel's own pre-zoom CSS pixels, as the stylesheet's are.
"""
import threading
import traceback

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF

from . import render, ui
from .homeedit import EditMixin
from .homemodel import OTHER_ROOM, CATEGORIES
from .ui import Button, Label, Rect, ScrollView, TextField, TileView, View

W, H = 678, 604
PAD = 14
TILE_W, TILE_H, GAP = 152, 146, 14
STAGE_Y, STAGE_H = PAD + 66 + 70, 440
HOME_SPAN = TILE_W * 4 + GAP * 3                 # 650: a room is a grid four cells wide
TINT = {"cyan": "accent_cyan", "yellow": "accent_yellow", "green": "accent_green", "blue": "accent_blue",
        "red": "accent_red", "teal": "accent_teal"}


class Pill(View):
    """A capsule of the header: an icon in a disc, a title and a line of status."""
    cursor = Qt.PointingHandCursor

    def __init__(self, cat, info, on_click):
        super().__init__(0, 0, 100, 70)
        self.interactive = True
        self.cat, self.info, self.active = cat, info, False
        self.on_click = lambda e: on_click(cat["id"])
        self.on_press = lambda e: self._press(True)
        self.on_release = lambda e: self._press(False)
        self.measure()

    def _press(self, on):
        self.zoom = 0.96 if on else 1.0
        self.changed()
        return True

    def measure(self):
        tw = max(ui.text_width(render.tr(self.cat["title"]), ui.font(23, QFont.Bold)),
                 ui.text_width(render.tr(self.info["sub"]), ui.font(19, QFont.Medium)))
        self.w = 9 + 52 + 14 + tw + 30

    def set_info(self, info, active):
        if info != self.info or active != self.active:
            self.info, self.active = info, active
            self.measure()
            self.changed()

    def paint(self, p):
        t = self.scene.t
        shape = Rect(0, 0, self.w, self.h, "tile_on" if self.active else "tile_off", "full")
        shape.scene = self.scene
        shape.paint(p)
        path = ui.QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.w, self.h), 35, 35)
        ring = render.rgba(t["edge_on"]) if self.active else render.rgba(t["edge"])
        render.inner_shadow(p, path, ring)
        if not self.active and t["edge_top"]:
            render.inner_shadow(p, path, render.rgba(t["edge_top"]), dy=1, spread=0)
        # the disc and its icon
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(14, 18, 24, round(255 * (0.08 if self.active else 0.28))))
        p.drawEllipse(QRectF(9, 9, 52, 52))
        tint = ui.resolve(self.scene, TINT.get(self.info.get("tint"), "accent_blue"))
        render.draw_icon(p, self.info.get("icon") or self.cat["icon"], (tint.red(), tint.green(), tint.blue(), 1.0),
                         QRectF(9 + 12, 9 + 12, 28, 28))
        c1 = t["on_text1"] if self.active else t["off_text1"]
        title_f, sub_f = ui.font(23, QFont.Bold), ui.font(19, QFont.Medium)
        tm, sm = QFontMetricsF(title_f), QFontMetricsF(sub_f)
        th, sh = 23 * 1.15, 19 * 1.2
        top = (self.h - th - sh) / 2
        p.setBrush(ui.resolve(self.scene, c1))
        p.drawPath(render.text_path(QPointF(0, 0), title_f, render.tr(self.cat["title"]), 9 + 52 + 14,
                                    top + (th - tm.height() / 10) / 2 + tm.ascent() / 10))
        col = ui.resolve(self.scene, c1)
        col.setAlphaF(0.8)
        p.setBrush(col)
        p.drawPath(render.text_path(QPointF(0, 0), sub_f, render.tr(self.info["sub"]), 9 + 52 + 14,
                                    top + th + (sh - sm.height() / 10) / 2 + sm.ascent() / 10))


class Chip(View):
    """A room capsule (and the add chip)."""
    cursor = Qt.PointingHandCursor

    def __init__(self, text, key, on_click, active=False, off=False, add=False, x_button=None):
        super().__init__(0, 0, 0, 46)
        self.interactive = True
        self.text, self.key, self.active, self.off, self.add = text, key, active, off, add
        self.on_x = None
        self.on_click = lambda e: (self.on_x(key) if self.x_button and self.hit_x(e.x, e.y) and self.on_x else on_click(key))
        self.on_press = lambda e: True
        self.w = ui.text_width(render.tr(text), ui.font(22, QFont.DemiBold)) + 44
        self.x_button = x_button
        if x_button:
            self.w += 12 + 40
        self.alpha = 0.5 if off else 1.0

    def paint(self, p):
        if self.add:
            p.setPen(ui.QPen(render.rgba(self.scene.t["card_edge"]), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(1, 1, self.w - 2, self.h - 2), 22, 22)
        else:
            fill = "ink1" if self.active else ("btn_fill_strong" if self.hovered else "btn_fill")
            shape = Rect(0, 0, self.w, self.h, fill, "full")
            shape.scene = self.scene
            shape.paint(p)
        color = "panel_solid" if self.active else "ink1"
        f = ui.font(22, QFont.DemiBold)
        fm = QFontMetricsF(f)
        p.setPen(Qt.NoPen)
        p.setBrush(ui.resolve(self.scene, color))
        base = (self.h - fm.height() / 10) / 2 + fm.ascent() / 10
        p.drawPath(render.text_path(QPointF(0, 0), f, render.tr(self.text), 22, base))
        if self.x_button:
            p.setBrush(QColor(255, 91, 74, round(255 * 0.9)))
            p.drawRoundedRect(QRectF(self.w - 22 - 40, 8, 40, 30), 15, 15)
            xf = ui.font(16)
            xm = QFontMetricsF(xf)
            p.setBrush(QColor(255, 255, 255))
            p.drawPath(render.text_path(QPointF(0, 0), xf, "✕", self.w - 22 - 40 + (40 - ui.text_width("✕", xf)) / 2,
                                        8 + (30 - xm.height() / 10) / 2 + xm.ascent() / 10))

    def hit_x(self, x, y):
        return self.x_button and self.w - 62 <= x <= self.w - 22 and 8 <= y <= 38


class HomeView(EditMixin, View):
    def __init__(self, panel):
        super().__init__(0, 0, W, H)
        self.panel = panel
        self.m = panel.model
        self.m.panel = panel.prefs.get("panel") or self.m.panel
        self.m.states = panel.states
        self.pills = {}
        self.sig = ""
        self.loading = False
        self.data_loaded = bool(self.m.entities)
        self.body_scroll_keep = 0.0
        self.cat_scroll_keep = 0.0
        self.build()

    # -- data ---------------------------------------------------------------------------------------------
    def load(self):
        """Fetch the rooms and devices (Api.get_home), off the GUI thread, and redraw if they changed."""
        if self.loading:
            return
        self.loading = True

        def go():
            try:
                data = self.panel.api.get_home()
            except Exception:
                data = None
                traceback.print_exc()
            self.panel.facade.run_on_ui_thread(lambda: self.loaded(data))
        threading.Thread(target=go, daemon=True).start()

    def loaded(self, data):
        self.loading = False
        if not data or data.get("error"):
            if not self.m.entities:
                self.build()
            return
        for s in data["sensors"]:
            s["domain"] = "sensor"
        sig = repr([data["rooms"], [(e["entity_id"], e.get("area"), e.get("name")) for e in data["entities"]],
                    [(x["entity_id"], x.get("area"), x.get("name"), x.get("kind")) for x in data["sensors"]]])
        changed = []
        for e in [*data["entities"], *data["sensors"]]:
            if self.panel.states.get(e["entity_id"]) != e["state"]:
                changed.append(e["entity_id"])
            self.panel.states[e["entity_id"]] = e["state"]
            self.m.states[e["entity_id"]] = e["state"]
        self.m.entities, self.m.sensors, self.m.rooms = data["entities"], data["sensors"], data["rooms"]
        if sig != self.sig:
            self.sig = sig
            self.build()
        else:
            self.states_changed(changed)

    def persist(self):
        panel = self.m.panel

        def go():
            try:
                self.panel.api.save_panel(panel)
            except Exception:
                traceback.print_exc()
        threading.Thread(target=go, daemon=True).start()

    # -- states -----------------------------------------------------------------------------------------------------
    def states_changed(self, entities):
        for tv in self.tile_views():
            if tv.tile["entity"] in entities:
                tv.set_state(self.panel.states.get(tv.tile["entity"]))
        self.refresh_status()

    def tile_views(self):
        out = []

        def walk(v):
            if isinstance(v, TileView):
                out.append(v)
            for c in v.children:
                walk(c)
        walk(self)
        return out

    def refresh_status(self):
        """The capsules change as devices do, often; they are updated where they stand."""
        wanted = self.m.visible_categories()
        ids = [c["id"] for c, _, _ in wanted]
        if ids != list(self.pills.keys()):
            self.build_summary()
            return
        for cat, _, info in wanted:
            self.pills[cat["id"]].set_info(info, self.m.category == cat["id"])
        for lab in getattr(self, "status_labels", []):
            lab[0].text = self.m.readings_text(self.m.sensors_in(lab[1]))
        self.layout_summary()

    # -- building -------------------------------------------------------------------------------------------------------
    def keep_scrolls(self):
        body = getattr(self, "body", None)
        cat = getattr(self, "cat_view", None)
        if body is not None:
            self.body_scroll_keep = body.offset
        if cat is not None:
            self.cat_scroll_keep = cat.offset

    def build(self):
        self.keep_scrolls()
        self.clear()
        self.pills = {}
        self.status_labels = []
        m = self.m
        hidden = m.hidden_chips()
        names = m.room_names()
        if m.room and (m.room in hidden or m.room not in names):
            m.room = ""
        self.add(Rect(0, 0, W, H, None))                       # nothing: the card paints itself
        # the top: the title and the tools
        self.add(Label("我的家", 38, QFont.ExtraBold, "ink1", x=PAD + 4, y=PAD + (52 - 38 * 1.15) / 2, spacing=-0.5, lh=1.15))
        editing = m.cat_editing if m.category else m.editing
        done = Button("完成" if editing else "編輯", size=23, weight=QFont.Bold, h=52, pad=24, active=editing,
                      on_click=lambda e: self.toggle_editing())
        plus = Button("＋", size=23, weight=QFont.Bold, h=52, pad=24, on_click=lambda e: self.open_sheet())
        done.x, done.y = W - PAD - 4 - done.w, PAD
        plus.x, plus.y = done.x - 10 - plus.w, PAD
        self.add(plus, done)
        # the capsules
        self.summary = ScrollView(PAD, PAD + 66, W - 2 * PAD, 70, horizontal=True, fade=44)
        self.add(self.summary)
        self.build_summary()
        # the stage: rooms in front, a capsule's devices behind
        self.stage = View(2, STAGE_Y, W - 4, STAGE_H)
        self.stage.clip = True
        self.stage.radius = 28
        self.add(self.stage)
        self.main = View(0, 0, W - 4, STAGE_H)
        self.stage.add(self.main)
        self.build_rooms_row(names, hidden)
        self.build_body()
        self.cat_view = ScrollView(0, 0, W - 4, STAGE_H)
        self.cat_view.on_press = lambda e: True
        self.cat_view.on_click = lambda e: self.cat_background_click()
        self.stage.add(self.cat_view)
        self.build_category()
        self.apply_category_state(animate=False)
        if m.sheet:
            self.build_sheet()
        self.refresh_status()
        self.panel.request_paint()

    def apply_category_state(self, animate=True):
        on = bool(self.m.category)
        ms = 320 if animate else 0
        self.main.interactive = False
        self.cat_view.interactive = False
        if on:
            self.main.animate(ms, "out", alpha=0.0, zoom=0.94, blur=10.0)
            self.cat_view.visible = True
            self.cat_view.animate(ms, "out", alpha=1.0, zoom=1.0, blur=0.0)
        else:
            self.main.animate(ms, "out", alpha=1.0, zoom=1.0, blur=0.0)
            self.cat_view.animate(ms, "out", alpha=0.0, zoom=1.06, blur=10.0)
        self.main.no_hit = on
        self.cat_view.no_hit = not on

    # hit tests: the view behind is not touched
    def hit(self, x, y):
        if getattr(self, "sheet_view", None) is not None and self.sheet_view.visible:
            got = self.sheet_view.hit(x - self.x - self.dx, y - self.y - self.dy)
            if got is not None:
                return got
        got = super().hit(x, y)
        return got

    def build_summary(self):
        self.pills = {}
        self.summary.clear()
        for cat, members, info in self.m.visible_categories():
            pill = Pill(cat, info, self.toggle_category)
            pill.set_info(info, self.m.category == cat["id"])
            self.pills[cat["id"]] = pill
            self.summary.add(pill)
        self.layout_summary()

    def layout_summary(self):
        x = 0
        for pill in self.pills.values():
            pill.x, pill.y = x, 0
            x += pill.w + 12
        self.summary.content.w = max(0, x - 12)
        self.summary.scroll_to(self.summary.offset)
        self.summary.changed()

    def build_rooms_row(self, names, hidden):
        m = self.m
        self.rooms_row = ScrollView(12, 14, W - 4 - 24, 46, horizontal=True, fade=44)
        self.main.add(self.rooms_row)
        chips = []

        def add_chip(key, label, off):
            has_x = m.editing and key not in ("", OTHER_ROOM)          # any room but all and uncategorised
            text = ("◌ " if off else "● ") + label if (m.editing and key != "") else label
            chip = Chip(text, key, self.chip_click, active=(not m.editing and m.room == key), off=off,
                        x_button=has_x)
            chip.on_x = self.delete_room
            chips.append(chip)
            self.rooms_row.add(chip)
            if m.editing and key not in ("", OTHER_ROOM):
                self.attach_room_reorder_chip(chip)
        add_chip("", "全部", False)
        for key in names:
            if not m.editing and key in hidden:
                continue
            add_chip(key, m.room_label(key), key in hidden)
        # the last one: a plus that turns into a field for a new room's name
        if not m.adding_room:
            add = Chip("＋ 房間", "", lambda _: self.start_adding_room(), add=True)
            self.rooms_row.add(add)
            chips.append(add)
        else:
            self.room_field = TextField(0, 0, 190, 46, "", "房間名稱", 22, None, 40, fill="input_bg", ring="accent_blue",
                                        radius=23)
            self.rooms_row.add(self.room_field)
            chips.append(self.room_field)
            self.room_field.edit_done = self.finish_adding_room
            QTimer.singleShot(30, lambda: self.focus_room_field())
        x = 0
        for c in chips:
            c.x, c.y = x, 0
            x += c.w + 10
        self.rooms_row.content.w = max(0, x - 10)
        self.rooms_row.scroll_to(self.rooms_row.offset)
        self.chips = chips

    def delete_room(self, key):
        """Delete a room: its devices are uncategorised. One with devices can be brought back from the add
        sheet (the devices moved into it go back too); an empty room of the user's own just goes."""
        m, p = self.m, self.m.panel
        members = [e for e in (*m.entities, *m.sensors) if e.get("area") == key]
        for name in ("custom_rooms", "room_order", "hidden_rooms", "hidden_chips"):
            p[name] = [r for r in p.get(name) or [] if r != key]
        if members or key in m.rooms:
            p["deleted_rooms"] = list(dict.fromkeys([*(p.get("deleted_rooms") or []), key]))
        for e in members:                           # at once; Api.get_home says the same next time
            e["area"] = ""
        m.rooms = [r for r in m.rooms if r != key]
        if m.room == key:
            m.room = ""
        self.persist()
        self.build()
        self.apply_category_state(animate=False)

    def restore_room(self, key):
        p = self.m.panel
        p["deleted_rooms"] = [r for r in p.get("deleted_rooms") or [] if r != key]
        self.persist()
        self.load()                                 # its devices' rooms come from Home Assistant again

    def focus_room_field(self):
        f = getattr(self, "room_field", None)
        if f is not None and f.edit is not None:
            f.edit.editingFinished.disconnect()
            f.edit.editingFinished.connect(lambda: QTimer.singleShot(220, lambda: self.finish_adding_room(True)))
            f.edit.returnPressed.connect(lambda: self.finish_adding_room(True))
            f.focus()
            self.panel.request_paint()

    def room_title_row(self, key, entities, stub):
        """A room's heading: its name, its status, and when editing a button to switch it off or on."""
        m = self.m
        row = View(0, 0, HOME_SPAN, 38)
        name = Label(m.room_label(key), 27, QFont.Bold, "ink1", x=8, y=0, lh=1.3)
        row.add(name)
        status = Label("", 21, QFont.DemiBold, "ink2", x=8 + name.w + 14, y=4, lh=1.3)
        self.status_labels.append((status, key))
        row.add(status)
        row.name_label, row.key = name, key
        if m.editing and not m.room:
            off = key in m.hidden_rooms()
            btn = Button("顯示房間" if off else "隱藏房間", size=18, weight=QFont.Bold, h=38, pad=20,
                         on_click=lambda e, key=key, off=off: self.toggle_room_hidden(key, off))
            btn.x = HOME_SPAN - btn.w
            row.add(btn)
            if key != OTHER_ROOM:
                self.attach_room_reorder_section(row)
        return row

    def build_body(self):
        m = self.m
        self.body = ScrollView(12, 74, W - 4 - 24, STAGE_H - 74)
        self.body.interactive = True
        self.main.add(self.body)
        self.sections = []
        y = 18
        groups = m.groups()
        if not groups:
            text = "正在載入配件…" if not m.entities else ("這個房間還沒有配件" if m.room else "沒有可顯示的配件")
            lab = Label(text, 24, QFont.Normal, "ink2", x=8, y=y + 40, lh=1.3)
            self.body.add(lab)
            y += 120
        for key, entities, stub in groups:
            section = View(0, y, HOME_SPAN, 0)
            title = self.room_title_row(key, entities, stub)
            section.add(title)
            sy = 38 + 10
            if stub:
                section.add(Rect(0, 0, 0, 0))
                section.h = sy - 10 + 4
                section.alpha = 1.0
                title.alpha = 0.5
            else:
                grid = View(0, sy, HOME_SPAN, 0)
                grid.room = key
                section.grid = grid
                if entities:
                    layout = m.room_layout(key) if False else self.layout_for(entities)
                    for e in entities:
                        r = layout.get(e["entity_id"])
                        if r is None:
                            continue
                        tv = self.make_tile(e, m.editing)
                        tv.x, tv.y = r["x"] * (TILE_W + GAP), r["y"] * (TILE_H + GAP)
                        grid.add(tv)
                    rows = max(r["y"] + r["h"] for r in layout.values()) if layout else 1
                    grid.h = rows * (TILE_H + GAP) - GAP
                else:
                    grid.h = TILE_H * 0.7
                    grid.empty = True
                    lab = Label("把配件拖曳到這裡", 22, QFont.Normal, "ink2", w=HOME_SPAN, align="c", lh=1.3)
                    lab.y = (grid.h - lab.h) / 2
                    grid.add(lab)
                section.add(grid)
                section.h = sy + grid.h
            section.room = key
            self.body.add(section)
            self.sections.append(section)
            y += section.h + 18
        self.body.content.w, self.body.content.h = HOME_SPAN, max(y - 18, 0) + 0
        self.body.scroll_to(self.body_scroll_keep)

    def layout_for(self, entities):
        from .homemodel import home_layout
        return home_layout(self.m.items(entities))

    def make_tile(self, e, editing, plain=False, cat=False):
        tile = self.m.tile_for(e)
        rec = self.m.record(e["entity_id"])
        span = self.m.cat_span(rec) if cat else self.m.span(rec)
        form = self.m.form(span)
        w = span[0] * TILE_W + (span[0] - 1) * GAP
        h = span[1] * TILE_H + (span[1] - 1) * GAP
        tv = TileView(tile, self.panel.states.get(e["entity_id"]), form, 0, 0, w, h)
        tv.entity = e
        if editing:
            self.decorate_tile(tv, e)
        else:
            self.panel.wire_tile(tv, tile)
        return tv

    # -- the capsule's own screen -----------------------------------------------------------------------------------------
    def category_node(self, e):
        tv = self.make_tile(e, False, plain=self.m.cat_editing, cat=True)
        if not self.m.cat_editing:
            return tv
        self.add_cat_handle(tv, e)
        chosen = self.m.category_chosen(e)
        tv.interactive = True
        tv.on_press = lambda ev: True
        tv.on_click = lambda ev: True
        tv.alpha = 1.0 if chosen else 0.4
        btn = Button("−" if chosen else "＋", size=17, weight=QFont.Bold, w=34, h=34, fill="accent_red" if chosen else "accent_green",
                     hover_fill="accent_red" if chosen else "accent_green", color="white",
                     on_click=lambda ev, e=e, chosen=chosen: self.toggle_cat_member(e, chosen))
        btn.fill = (255, 91, 74, 0.96) if chosen else (52, 199, 89, 0.96)
        btn.hover_fill = btn.fill
        btn.x, btn.y = tv.w - 34 + 6, -6
        tv.add(btn)
        return tv

    def build_category(self):
        m = self.m
        cv = self.cat_view
        cv.clear()
        cat = next((c for c in CATEGORIES if c["id"] == m.category), None)
        if cat is None:
            return
        title = cat["title"] + ("　" + m.room_label(m.room) if m.room else "")
        t = Label(render.tr(title), 32, QFont.ExtraBold, "ink1", x=12 + 8, y=6 + 4, lh=1.3, spacing=-0.3)
        cv.add(t)
        if m.cat_editing:
            cv.add(Label("按 − 不顯示該配件，按 ＋ 加回", 20, QFont.Medium, "ink2", x=12 + 8 + t.w + 16, y=6 + 12, lh=1.3))
        everyone = [e for e in m.category_all(cat) if (not m.room or m.room_key(e.get("area")) == m.room)] \
            if m.cat_editing else m.category_members(cat)
        groups = {}
        for e in everyone:
            groups.setdefault(m.room_key(e.get("area")), []).append(e)
        y = 6 + 4 + 32 * 1.3 + 16
        n = 0
        for key in sorted(groups, key=m.room_sort_key):
            title = Label(m.room_label(key), 27, QFont.Bold, "ink1", x=12 + 8, y=y, lh=1.3)
            cv.add(title)
            y += 38 + 10
            # a grid four cells wide, dense: tiles as they come, in their shapes
            layout = self.layout_for_dense(m.ordered(groups[key]))
            rows = 0
            for e in m.ordered(groups[key]):
                r = layout[e["entity_id"]]
                tv = self.category_node(e)
                tv.x, tv.y = 12 + r["x"] * (TILE_W + GAP), y + r["y"] * (TILE_H + GAP)
                tv.alpha, tv.zoom = 0.0, 0.82
                tv.pop_index = n
                n += 1
                cv.add(tv)
                rows = max(rows, r["y"] + r["h"])
            y += rows * (TILE_H + GAP) - GAP + 18
        cv.content.w, cv.content.h = W - 4, y
        cv.scroll_to(self.cat_scroll_keep)
        self.pop_in()

    def layout_for_dense(self, entities):
        """grid-auto-flow: dense: each tile in the first free place, in order, ignoring saved places."""
        from .homemodel import home_layout
        items = []
        for i, e in enumerate(entities):
            w, h = self.m.cat_span(self.m.record(e["entity_id"]))
            items.append({"id": e["entity_id"], "w": w, "h": h, "order": i, "x": None, "y": None})
        return home_layout(items)

    def pop_in(self):
        if not self.m.category:
            return
        for v in self.cat_view.content.children:
            i = getattr(v, "pop_index", None)
            if i is None:
                continue
            target = 0.4 if (self.m.cat_editing and not self.m.category_chosen(v.entity)) else 1.0
            QTimer.singleShot(60 + i * 28, lambda v=v, target=target: v.animate(360, "back", alpha=target, zoom=1.0))

    def toggle_category(self, cat_id):
        m = self.m
        m.cat_editing = False
        if m.category == cat_id:
            m.category = None
        else:
            m.category = cat_id
            m.editing = False
            m.sheet = False
        self.cat_scroll_keep = 0.0
        self.build()
        self.apply_category_state(animate=True)

    def cat_background_click(self):
        """The empty space around a capsule's devices: leaves editing, or the capsule."""
        if self.m.cat_editing:
            self.m.cat_editing = False
            self.build()
            self.apply_category_state(animate=False)
        elif self.m.category:
            self.toggle_category(self.m.category)
        return True

    def toggle_cat_member(self, e, chosen):
        rec = self.m.ensure_record(e["entity_id"])
        if chosen:
            rec["cat_hidden"] = True
        else:
            rec.pop("cat_hidden", None)
        self.persist()
        self.build()
        self.apply_category_state(animate=False)

    def toggle_editing(self):
        m = self.m
        if m.category:
            m.cat_editing = not m.cat_editing
        else:
            m.editing = not m.editing
        self.build()
        self.apply_category_state(animate=False)

    def chip_click(self, key):
        m = self.m
        if m.editing and key != "":
            s = m.hidden_chips()
            if key in s:
                s.discard(key)
            else:
                s.add(key)
            m.panel["hidden_chips"] = sorted(s)
            self.persist()
        else:
            m.room = key
        self.build()
        self.apply_category_state(animate=False)

    def toggle_room_hidden(self, key, off):
        if key == OTHER_ROOM:
            self.m.panel["show_other"] = bool(off)
            self.persist()
            self.build()
            self.apply_category_state(animate=False)
            return
        s = self.m.hidden_rooms() - {OTHER_ROOM}
        if off:
            s.discard(key)
        else:
            s.add(key)
        self.m.panel["hidden_rooms"] = sorted(s)
        self.persist()
        self.build()
        self.apply_category_state(animate=False)

    # -- adding a room ---------------------------------------------------------------------------------------------------------
    def start_adding_room(self):
        self.m.adding_room = True
        self.build()
        self.apply_category_state(animate=False)

    def finish_adding_room(self, commit):
        m = self.m
        if not m.adding_room:
            return
        m.adding_room = False
        field = getattr(self, "room_field", None)
        name = (field.value() if field is not None else "").strip()
        if commit and name:
            m.panel["deleted_rooms"] = [r for r in m.panel.get("deleted_rooms") or [] if r != name]
            rooms = list(m.panel.get("custom_rooms") or [])
            if name not in rooms and name not in m.rooms:
                rooms.append(name)
                order = [r for r in m.room_names() if r != OTHER_ROOM]
                m.panel["room_order"] = list(dict.fromkeys([*order, name]))
            m.panel["custom_rooms"] = rooms
            m.room = name
            self.persist()
        self.build()
        self.apply_category_state(animate=False)

    # -- the add sheet: devices that were removed -----------------------------------------------------------------------------------
    def open_sheet(self):
        self.m.sheet = True
        self.build()
        self.apply_category_state(animate=False)

    def close_sheet(self):
        self.m.sheet = False
        self.build()
        self.apply_category_state(animate=False)

    def build_sheet(self):
        m = self.m
        self.sheet_view = sheet = View(0, 0, W, H)
        sheet.interactive = True
        sheet.on_press = lambda e: True
        sheet.add(Rect(0, 0, W, H, "panel_solid", self.panel.t["radius_panel"], shape="squircle"))
        sheet.add(Label("新增配件", 30, QFont.Bold, "ink1", x=26, y=22, lh=1.3))
        done = Button("完成", size=23, weight=QFont.Bold, h=52, pad=24, on_click=lambda e: self.close_sheet())
        done.x, done.y = W - 26 - done.w, 22 - 4
        sheet.add(done)
        lst = ScrollView(26, 22 + 52 + 14, W - 52, H - (22 + 52 + 14) - 26)
        sheet.add(lst)
        y = 0
        hidden_now = [r for r in sorted(m.hidden_rooms()) if r in m.room_names()]
        if hidden_now:
            lst.add(Label("主畫面隱藏的房間", 20, QFont.Bold, "ink2", x=4, y=y + 6, lh=1.3))
            y += 6 + 26 + 10
            for room in hidden_now:
                count = sum(1 for e in m.entities if m.room_key(e.get("area")) == room)
                y = self.sheet_row(lst, y, m.room_label(room), "%d 個配件　顯示" % count,
                                   lambda e, room=room: self.show_hidden_room(room))
        deleted = list(m.panel.get("deleted_rooms") or [])
        if deleted:
            lst.add(Label("已刪除的房間", 20, QFont.Bold, "ink2", x=4, y=y + 6, lh=1.3))
            y += 6 + 26 + 10
            for room in deleted:
                y = self.sheet_row(lst, y, room, "還原", lambda e, room=room: self.restore_room(room))
        lst.add(Label("已移除的配件", 20, QFont.Bold, "ink2", x=4, y=y + 6, lh=1.3))
        y += 6 + 26 + 10
        gone = [e for e in m.entities if (m.record(e["entity_id"]) or {}).get("hidden")]
        if not gone:
            lab = Label("沒有已移除的配件。被移除的配件會列在這裡，按一下加回。", 24, QFont.Normal, "ink2", x=0, y=y + 40,
                        w=W - 52, wrap=True, lh=1.3)
            lst.add(lab)
            y += 40 + lab.h
        for e in gone:
            y = self.sheet_row(lst, y, e["name"], m.room_label(m.room_key(e.get("area"))),
                               lambda ev, e=e: self.restore_device(e))
        lst.content.w, lst.content.h = W - 52, y
        self.add(sheet)

    def sheet_row(self, lst, y, left, right, on_click):
        row = Button("", x=0, y=y, w=W - 52, h=56, on_click=on_click)
        row.left_text, row.right_text = left, right
        row.paint = self._sheet_row_painter(row)
        lst.add(row)
        return y + 56 + 10

    @staticmethod
    def _sheet_row_painter(row):
        base = Button.paint

        def paint(p):
            base(row, p)
            f1, f2 = ui.font(23, QFont.DemiBold), ui.font(19, QFont.Medium)
            m1, m2 = QFontMetricsF(f1), QFontMetricsF(f2)
            p.setPen(Qt.NoPen)
            p.setBrush(ui.resolve(row.scene, "ink1"))
            p.drawPath(render.text_path(QPointF(0, 0), f1, ui.ellipsize(render.tr(row.left_text), f1, row.w - 220), 26,
                                        (row.h - m1.height() / 10) / 2 + m1.ascent() / 10))
            p.setBrush(ui.resolve(row.scene, "ink2"))
            rt = render.tr(row.right_text)
            p.drawPath(render.text_path(QPointF(0, 0), f2, rt, row.w - 26 - ui.text_width(rt, f2),
                                        (row.h - m2.height() / 10) / 2 + m2.ascent() / 10))
        return paint

    def show_hidden_room(self, room):
        if room == OTHER_ROOM:
            self.m.panel["show_other"] = True
        self.m.panel["hidden_rooms"] = [r for r in self.m.panel.get("hidden_rooms") or [] if r != room]
        self.persist()
        self.build()
        self.apply_category_state(animate=False)

    def restore_device(self, e):
        rec = self.m.ensure_record(e["entity_id"])
        rec.pop("hidden", None)
        rec["order"] = 1e6
        self.persist()
        self.build()
        self.apply_category_state(animate=False)
