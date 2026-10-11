"""The widget editor of Settings: the widgets to drag onto the desktop (the tiles in their four sizes and the
other kinds, each in its own size), a map of the desktop, the selected widget as it will look (tiles drag to
reorder, the others making room as they will), and its list of devices. The page's openEditor and its
renderers."""
import threading
import time
import traceback
import uuid

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont

from . import kinds, render, style
from .editor_custom import CustomEditorMixin
from .ui import Button, CheckRow, Rect, View
from .editor_views import Chip, LEFT_W, LEFT_X, Minimap, Palette, Preview, PreviewBackdrop, ROW_STEP, SIZES, TileRow

PANEL_ID = "__panel"
SOFT_LIMIT = 6
EDITOR_W = 800
RIGHT_X = LEFT_X + LEFT_W + 22
RIGHT_W = EDITOR_W - 18 - RIGHT_X
# what the list of devices is called, and its button, by the widget's kind
LIST_TITLE = {"tiles": "配件", "weather": "天氣", "camera": "攝影機", "chart": "感測器", "media": "播放器"}
ADD_TEXT = {"tiles": "+ 新增配件", "weather": "選擇天氣", "camera": "選擇攝影機", "chart": "+ 新增感測器",
            "media": "選擇播放器"}


def new_tile_id():
    return str(uuid.uuid4())


class EditorMixin(CustomEditorMixin):
    def editor_init(self):
        self.custom_init()
        self.editor_dragging = False
        self.layout = None
        self.preview_landing = None
        self.layout_timer = QTimer(self)
        self.layout_timer.setInterval(900)
        self.layout_timer.timeout.connect(self._poll_layout)

    # -- which widget ------------------------------------------------------------------------------------------------
    def widgets(self):
        return self.prefs.get("widgets") or []

    def panel_target(self):
        panel = self.prefs.get("panel") or {}
        return {"id": PANEL_ID, "size": "2x4", "panel": True,
                "tiles": panel["tiles"] if isinstance(panel.get("tiles"), list) else []}

    def settings_widget(self):
        if self.widget_id == PANEL_ID:
            return self.panel_target()
        ws = self.widgets()
        return next((w for w in ws if w["id"] == self.widget_id), None) or (ws[0] if ws else None)

    def selected_id(self):
        w = self.settings_widget()
        return w["id"] if w else ""

    def current_tiles(self):
        w = self.settings_widget()
        return w["tiles"] if w else []

    def current_kind(self):
        w = self.settings_widget()
        return (w.get("kind") or "tiles") if w and not w.get("panel") else "tiles"

    def room_left(self):
        """How many more devices the widget takes (None: any number)."""
        kind = self.current_kind()
        return None if kind not in kinds.KIND_MAX else max(0, kinds.KIND_MAX[kind] - len(self.current_tiles()))

    def can_add(self):
        """Whether its button adds (a weather or a camera full is changed instead: one in place of the other)."""
        left = self.room_left()
        return left is None or left > 0 or kinds.KIND_MAX.get(self.current_kind()) == 1

    def own_panel_tiles(self):
        panel = self.prefs.setdefault("panel", {"mode": "grid", "tiles": None, "home_tiles": []})
        if isinstance(panel.get("tiles"), list):
            return
        seen, copies = set(), []
        for w in self.widgets():
            for t in w.get("tiles", []):
                if t["entity"] not in seen:
                    seen.add(t["entity"])
                    copies.append(dict(t, id=new_tile_id()))
        panel["tiles"] = copies

    def select_widget(self, wid, keep_drag=False):
        self.widget_id = wid
        if wid == PANEL_ID:
            self.own_panel_tiles()
            self.persist()
        if not keep_drag:
            self.build()
        else:
            self.build()

    # -- opening and closing -----------------------------------------------------------------------------------------------
    def open_editor(self, widget_id):
        if widget_id:
            self.widget_id = widget_id
        w = self.settings_widget()
        if w:
            self.widget_id = w["id"]
        self.reload_customs()
        self.go("editor")
        self.layout_timer.start()
        self.refresh_layout()

    def close_editor(self, e=None):
        self.layout_timer.stop()
        self.close_custom_runtimes()
        self.go("settings")

    def _poll_layout(self):
        if self.page != "editor":
            self.layout_timer.stop()
        elif not self.editor_dragging:
            self.refresh_layout()

    def refresh_layout(self):
        def go():
            try:
                layout = self.facade.api.get_layout()
            except Exception:
                return
            self.facade.run_on_ui_thread(lambda: self.layout_loaded(layout))
        threading.Thread(target=go, daemon=True).start()

    def layout_loaded(self, layout):
        if self.page != "editor":
            return
        changed = repr(layout) != repr(self.layout)
        self.layout = layout
        if changed and not self.editor_dragging and self.minimap_host is not None:
            self.fill_minimap()

    def editor_states_changed(self):
        if getattr(self, "preview", None) is not None:
            self.preview.invalidate()

    # -- editing ----------------------------------------------------------------------------------------------------------------
    def persist(self):
        widgets = self.widgets()
        panel = self.prefs.get("panel")

        def go():
            try:
                self.facade.api.save_widgets(widgets)
                if panel:
                    self.facade.api.save_panel(panel)
            except Exception:
                traceback.print_exc()
        threading.Thread(target=go, daemon=True).start()

    def remove_tile_at(self, i):
        tiles = self.current_tiles()
        if 0 <= i < len(tiles):
            del tiles[i]
            self.persist()
            self.build()

    delete_tile = remove_tile_at

    def move_tile(self, frm, to):
        tiles = self.current_tiles()
        if 0 <= frm < len(tiles):
            t = tiles.pop(frm)
            tiles.insert(max(0, min(len(tiles), to)), t)
            self.persist()
            self.build()

    def add_entity(self, e):
        self.add_entities([e])

    def add_entities(self, ents):
        """The devices chosen in the picker, at the end of the widget's (a weather's or a camera's in place of
        the one it had); back to the page the picker came from."""
        w = self.settings_widget()
        if w is not None and ents:
            if kinds.KIND_MAX.get(self.current_kind()) == 1:
                w["tiles"] = []
            for e in ents:
                w["tiles"].append({"id": new_tile_id(), "entity": e["entity_id"], "domain": e["domain"],
                                   "room": e.get("name") or e["entity_id"], "label": "", "icon": "",
                                   "on_mode": "cool", "temp_step": 1})
                if e.get("state") and e["entity_id"] not in self.states:
                    self.states[e["entity_id"]] = e["state"]
            self.persist()
        self.page = self.return_page
        self.build()

    def font_card(self, widget):
        """A clock's font: a card that opens the fonts installed on this computer in a menu."""
        from . import controls, fonts
        default = fonts.default()
        default_text = render.tr("預設") + (" (%s)" % fonts.DEFAULT_NAME if default else "")
        chosen = widget.get("font") or {}
        options = [("", default_text)] + [(f["file"] + "|" + f["name"], f["name"]) for f in fonts.installed()]
        current = (chosen["file"] + "|" + chosen.get("name", "")) if chosen.get("file") else ""
        value = chosen.get("name") or default_text
        if chosen.get("file") and kinds.clock_face(chosen) is None:
            value = render.tr("無法使用：") + value                # gone, or without digits: the default shows
        return controls.ModeCard(RIGHT_W, "mdi:format-font", "時鐘字體", value, options,
                                 lambda v, wid=widget["id"]: self.set_font(wid, v), current)

    def set_font(self, widget_id, value):
        widget = next((w for w in self.widgets() if w["id"] == widget_id), None)
        if widget is None:
            return
        file, _, name = value.partition("|")
        font = {"file": file, "name": name} if file else None
        if font and kinds.clock_face(font) is None:
            return                                # can't be read, or has no digits: kept as it was
        if font:
            widget["font"] = font
        else:
            widget.pop("font", None)
        self.close_popup()

        def go():
            try:
                self.facade.api.set_widget_font(widget["id"], font)
            except Exception:
                traceback.print_exc()
        threading.Thread(target=go, daemon=True).start()
        self.build()

    def set_size(self, size):
        w = self.settings_widget()
        if not w or w.get("panel") or w["size"] == size or (w.get("kind") or "tiles") != "tiles":
            return
        w["size"] = size

        def go():
            try:
                self.facade.api.set_widget_size(w["id"], size)
            except Exception:
                traceback.print_exc()
        threading.Thread(target=go, daemon=True).start()
        self.build()
        QTimer.singleShot(350, self.refresh_layout)

    def remove_widget(self):
        w = self.settings_widget()
        if not w or w.get("panel") or len(self.widgets()) <= 1:
            return
        self.widget_id = ""

        def go():
            try:
                self.facade.api.remove_widget(w["id"])
            except Exception:
                traceback.print_exc()
        threading.Thread(target=go, daemon=True).start()
        self.prefs["widgets"] = [x for x in self.widgets() if x["id"] != w["id"]]
        self.build()
        QTimer.singleShot(200, self.refresh_layout)

    def follow_widgets(self):
        panel = dict(self.prefs.get("panel") or {}, tiles=None)
        self.prefs["panel"] = panel
        self.widget_id = ""

        def go():
            try:
                self.facade.api.save_panel(panel)
            except Exception:
                traceback.print_exc()
        threading.Thread(target=go, daemon=True).start()
        self.build()

    def drag_new_kind(self, kind):
        self.drag_new_widget(kinds.KIND_SIZE[kind], kind)

    def drag_new_widget(self, size, kind="tiles", package=None):
        self.editor_dragging = True

        def go():
            try:
                r = self.facade.api.begin_widget_drag(size, kind, package) if package else \
                    self.facade.api.begin_widget_drag(size, kind)
                if r and r.get("id"):
                    self.facade.run_on_ui_thread(lambda: setattr(self, "widget_id", r["id"]))
            except Exception:
                self.facade.run_on_ui_thread(lambda: self.toast("新增 Widget 失敗"))

            def done():
                self.editor_dragging = False
                self.refresh_layout()
                self.build()
            time.sleep(0.4)
            self.facade.run_on_ui_thread(done)
        threading.Thread(target=go, daemon=True).start()

    # -- building ---------------------------------------------------------------------------------------------------------------
    def build_editor_body(self):
        body = View(0, 0, EDITOR_W, 0)
        self.preview = None
        self.minimap_host = None
        widget = self.settings_widget()
        on_panel = bool(widget and widget.get("panel"))
        panel = self.prefs.get("panel") or {}
        left_h = self.editor_left_column(body)
        self.load_custom_now(widget)
        y = self.editor_widget_chips(body, widget, on_panel)
        kind = self.current_kind()
        y = self.editor_preview(body, y, widget, on_panel, kind)
        y = self.editor_tools(body, y, widget, on_panel, kind, panel)
        if kind == "custom":                     # a widget of the kit: its own settings and permissions
            y = self.editor_custom(body, y, widget)
            body.h = max(left_h, y) + 18
            return body
        if kind in kinds.NO_DEVICES:             # a clock, a calendar: no devices to choose
            body.h = max(left_h, y) + 18
            return body
        y = self.editor_devices(body, y, widget, kind)
        body.h = max(left_h, y) + 18
        return body

    def editor_left_column(self, body):
        """The palette, the map of the desktop and the lock; returns where the column ends."""
        y = 2
        body.add(style.label("group", "拖曳到桌面新增", x=LEFT_X, y=y))
        y += 14.4 + 8
        pal = Palette(self, self.drag_new_widget, self.drag_new_kind)
        pal.x, pal.y = LEFT_X, y
        body.add(pal)
        y += pal.h
        body.add(style.label("group", "匯入的 Widget", x=LEFT_X, y=y + 12))
        y += 12 + 14.4 + 8
        shelf = self.custom_shelf(LEFT_W)
        shelf.x, shelf.y = LEFT_X, y
        body.add(shelf)
        y += shelf.h
        body.add(style.label("group", "桌面配置（拖曳移動）", x=LEFT_X, y=y + 12))
        y += 12 + 14.4 + 8
        self.minimap_host = View(LEFT_X, y, LEFT_W, 120)
        body.add(self.minimap_host)
        self.mm_built = None
        self.fill_minimap()
        self.mm_built = self.minimap_host.h              # what the rows below were placed for
        y += self.minimap_host.h + 10
        lock = CheckRow("鎖定位置 (桌面上無法拖曳移動)", bool(self.prefs.get("lock_position")), LEFT_W,
                        lambda on: self.save_pref({"lock_position": on}))
        lock.x, lock.y = LEFT_X, y
        body.add(lock)
        y += lock.h
        if len(self.widgets()) > SOFT_LIMIT:
            hint = style.label("hint", "已超過 %d 個 Widget，每多一個都會多用一份記憶體。" % SOFT_LIMIT,
                         x=LEFT_X, y=y + 6, w=LEFT_W, wrap=True, lh=1.4)
            body.add(hint)
            y += 6 + hint.h
        return y

    def editor_widget_chips(self, body, widget, on_panel):
        """The row of chips that choose which widget (or the tray panel) is being edited; returns the y below it."""
        y = 2
        body.add(style.label("group", "我的 Widget", x=RIGHT_X, y=y))
        y += 14.4 + 8
        x = 0
        row_y = y
        chips = []
        for i, w in enumerate(self.widgets()):
            kind = w.get("kind") or "tiles"
            what = w["size"] if kind == "tiles" else self.custom_name(w) if kind == "custom" else render.tr(kinds.KIND_LABELS[kind])
            chips.append(Chip("#%d · %s" % (i + 1, what), (widget and w["id"] == widget["id"]),
                              lambda e, wid=w["id"]: self.select_widget(wid)))
        chips.append(Chip("系統匣面板", on_panel, lambda e: self.select_widget(PANEL_ID)))
        for c in chips:
            if x and x + c.w > RIGHT_W:
                x, row_y = 0, row_y + 28 + 6
            c.x, c.y = RIGHT_X + x, row_y
            body.add(c)
            x += c.w + 6
        y = row_y + 28
        return y

    def editor_preview(self, body, y, widget, on_panel, kind):
        """The widget as it will look, on a backdrop; returns the y below it."""
        body.add(style.label("group", "預覽（拖曳配件調整順序）" if kind == "tiles" else "預覽", x=RIGHT_X, y=y + 12))
        y += 12 + 14.4 + 8
        if widget:
            w, h = render.widget_size("2x4" if on_panel else widget["size"])
            zoom = min(1.0, max(120, RIGHT_W - 36) / w)
            prev = Preview(self, widget, zoom, "small" if on_panel else None)
            box_h = max(120, prev.h + 36)
            body.add(PreviewBackdrop(RIGHT_X, y, RIGHT_W, box_h))
            prev.x, prev.y = RIGHT_X + (RIGHT_W - prev.w) / 2, y + 18
            body.add(prev)
            self.preview = prev
            if not widget["tiles"] and kind not in kinds.NO_DEVICES and kind != "custom":
                body.add(style.label("empty", "尚無配件，按下方「%s」" % render.tr(ADD_TEXT[kind].lstrip("+ ")), x=RIGHT_X + 20, y=y + box_h / 2 - 10, w=RIGHT_W - 40, align="c"))
            y += box_h
        return y

    def editor_tools(self, body, y, widget, on_panel, kind, panel):
        """Sizes, delete, and what the tray panel can do; a clock's font. Returns the y below them."""
        ty = y + 12
        tx = RIGHT_X
        if not on_panel and kind == "tiles":
            for size in SIZES:
                c = Chip(size, bool(widget and widget["size"] == size), lambda e, s=size: self.set_size(s))
                c.x, c.y = tx, ty
                body.add(c)
                tx += c.w + 6
            tx += 6
        elif not on_panel and kind == "custom":
            tx = self.custom_sizes(body, tx, ty, widget)
        elif not on_panel:
            note = style.label("field", "%s Widget · %s" % (render.tr(kinds.KIND_LABELS[kind]), widget["size"]), x=tx, y=ty + 6)
            body.add(note)
            tx += note.w + 14
        if not on_panel:
            rm = Button("刪除此 Widget", size=12, weight=QFont.DemiBold, h=28, pad=12, color="accent_red",
                        on_click=lambda e: self.remove_widget())
            if len(self.widgets()) <= 1:
                rm.alpha = 0.4
                rm.interactive = False
            rm.x, rm.y = tx, ty
            body.add(rm)
            tx += rm.w + 6
        if on_panel or isinstance(panel.get("tiles"), list):
            fo = Button("改為顯示所有 Widget 的配件", size=12, weight=QFont.DemiBold, h=28, pad=12,
                        on_click=lambda e: self.follow_widgets())
            if tx + fo.w > EDITOR_W - 18:
                tx, ty = RIGHT_X, ty + 28 + 6
            fo.x, fo.y = tx, ty
            body.add(fo)
        y = ty + 28 + 10
        if kind == "clock" and widget and not on_panel:      # its digits' font
            body.add(style.label("group", "字體", x=RIGHT_X, y=y + 5, spacing=0.36))
            y += 5 + 14.4 + 8
            card = self.font_card(widget)
            card.x, card.y = RIGHT_X, y
            body.add(card)
            y += card.h + 10
        return y

    def editor_devices(self, body, y, widget, kind):
        """The list of the widget's devices with its add button; returns the y below it."""
        tiles = widget["tiles"] if widget else []
        cap = kinds.KIND_MAX.get(kind)
        count = ("%d/%d" % (len(tiles), cap)) if cap and cap > 1 else "%d" % len(tiles)
        body.add(style.label("group", "%s (%s)" % (render.tr(LIST_TITLE[kind]), count), x=RIGHT_X, y=y + 5,
                       spacing=0.36))
        text = ADD_TEXT[kind]
        if cap == 1 and tiles:
            text = {"weather": "更換天氣", "camera": "更換攝影機", "media": "更換播放器"}[kind]
        add = Button(text, size=12, weight=QFont.DemiBold, h=28, pad=12, fill="accent_blue", hover_fill="accent_blue",
                     color="white", on_click=lambda e: self.open_picker())
        if not self.can_add():                   # a chart: two sensors
            add.alpha, add.interactive = 0.4, False
        add.x, add.y = EDITOR_W - 18 - add.w, y
        body.add(add)
        y += 28 + 8
        # every row shown (the page scrolls), so one can be dragged from the first place to the last
        lst = View(RIGHT_X, y, RIGHT_W, max(0, len(tiles) * ROW_STEP - 6))
        for i, t in enumerate(tiles):
            lst.add(TileRow(self, t, i, RIGHT_W))
        body.add(lst)
        y += lst.h
        return y

    def fill_minimap(self):
        host = self.minimap_host
        host.clear()
        if not self.layout or not self.layout.get("monitors"):
            host.h = 120
            host.add(Rect(0, 0, LEFT_W, 120, "btn_fill", 14))
            return
        mm = Minimap(self, self.layout, LEFT_W)
        host.add(mm)
        host.h = mm.h
        # the rest of the left column follows it: when the layout arrives after the editor was built, build again
        if self.mm_built is not None and self.mm_built != mm.h:
            QTimer.singleShot(0, self.build)
        self.request_paint()
