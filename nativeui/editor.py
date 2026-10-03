"""The widget editor of Settings: the sizes to drag onto the desktop, a map of the desktop, the selected
widget as it will look (tiles drag to reorder), and its list of devices. The page's openEditor and its
renderers."""
import threading
import time
import traceback
import uuid

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPixmap, QPen

from . import render, ui
from .ui import Button, CheckRow, Label, Rect, ScrollView, TextField, View

PANEL_ID = "__panel"
SIZES = ["1x1", "2x2", "2x4", "4x4"]
PALETTE_SCALE = 0.19
SOFT_LIMIT = 6
EDITOR_W = 800
LEFT_X, LEFT_W = 18, 300
RIGHT_X = LEFT_X + LEFT_W + 22
RIGHT_W = EDITOR_W - 18 - RIGHT_X


def new_tile_id():
    return str(uuid.uuid4())


class PreviewBackdrop(View):
    """The picture the preview stands on."""

    def __init__(self, x, y, w, h):
        super().__init__(x, y, w, h)

    def paint(self, p):
        g = QLinearGradient(0, 0, self.w, self.h)
        g.setColorAt(0, QColor(0x7f, 0x94, 0xdc))
        g.setColorAt(0.55, QColor(0xc8, 0xa2, 0xde))
        g.setColorAt(1, QColor(0xf2, 0xb9, 0xa3))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(QRectF(0, 0, self.w, self.h), 22, 22)


class Chip(Button):
    """A widget chip: a capsule that turns blue when it is the selected one."""

    def __init__(self, text, active, on_click):
        super().__init__(text, size=12, weight=QFont.Normal, h=28, pad=12, active=active, on_click=on_click)


class Palette(View):
    """The sizes, drawn in proportion; pressing one makes a real widget that follows the pointer."""

    def __init__(self, scene_ref, on_press_size):
        super().__init__(0, 0, LEFT_W, 0)
        x = y = 0
        row_h = 0
        items = []
        for size in SIZES:
            cols, rows = render.SIZES[size]
            w, h = render.widget_size(size)
            bw, bh = round(w * PALETTE_SCALE), round(h * PALETTE_SCALE)
            items.append((size, cols, rows, bw, bh))
        # placed in rows, bottoms aligned
        line, line_w = [], 0
        lines = []
        for it in items:
            if line and line_w + it[3] > LEFT_W:
                lines.append(line)
                line, line_w = [], 0
            line.append(it)
            line_w += it[3] + 16
        lines.append(line)
        y = 0
        for ln in lines:
            lh = max(it[4] for it in ln) + 6 + 14
            x = 0
            for size, cols, rows, bw, bh in ln:
                item = PaletteItem(size, cols, rows, bw, bh, on_press_size)
                item.x, item.y = x, y + lh - item.h
                self.add(item)
                x += bw + 16
            y += lh + 14
        self.h = y - 14


class PaletteItem(View):
    cursor = Qt.OpenHandCursor

    def __init__(self, size, cols, rows, bw, bh, on_press_size):
        super().__init__(0, 0, bw, bh + 6 + 14)
        self.interactive = True
        self.size_key, self.cols, self.rows, self.bw, self.bh = size, cols, rows, bw, bh
        self.on_press = lambda e: (on_press_size(size), True)[1]

    def paint(self, p):
        up = -2 if self.hovered else 0
        p.setPen(Qt.NoPen)
        p.setBrush(ui.resolve(self.scene, "btn_fill_strong" if self.hovered else "btn_fill"))
        p.drawRoundedRect(QRectF(0, up, self.bw, self.bh), 14, 14)
        p.setPen(QPen(render.rgba(self.scene.t["card_edge"]), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.5, up + 0.5, self.bw - 1, self.bh - 1), 14, 14)
        pad, gap = 5, 3
        cw = (self.bw - 2 * pad - gap * (self.cols - 1)) / self.cols
        ch = (self.bh - 2 * pad - gap * (self.rows - 1)) / self.rows
        col = ui.resolve(self.scene, "btn_text")
        col.setAlphaF(0.28)
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        for r in range(self.rows):
            for c in range(self.cols):
                p.drawRoundedRect(QRectF(pad + c * (cw + gap), up + pad + r * (ch + gap), cw, ch), 6, 6)
        f = ui.font(12)
        fm = ui.QFontMetricsF(f)
        tw = ui.text_width(self.size_key, f)
        p.setBrush(ui.resolve(self.scene, "ink2"))
        p.drawPath(render.text_path(QPointF(0, 0), f, self.size_key, (self.bw - tw) / 2,
                                    self.bh + 6 + (14 - fm.height() / 10) / 2 + fm.ascent() / 10))


class Minimap(View):
    """Every monitor, with the widgets where they are; a box dragged moves the real widget."""

    def __init__(self, editor, layout, w):
        self.editor, self.layout = editor, layout
        mons = layout["monitors"]
        self.minx = min(m["x"] for m in mons)
        self.miny = min(m["y"] for m in mons)
        maxx = max(m["x"] + m["w"] for m in mons)
        maxy = max(m["y"] + m["h"] for m in mons)
        pad = 8
        self.pad = pad
        self.k = min((w - 2 * pad) / (maxx - self.minx), 210 / (maxy - self.miny))
        super().__init__(0, 0, w, round((maxy - self.miny) * self.k + 2 * pad))
        self.boxes = []
        for i, wd in enumerate(layout["widgets"]):
            box = MapBox(self, wd, i)
            self.boxes.append(box)
            self.add(box)

    def at(self, x, y):
        return (round((x - self.minx) * self.k + self.pad), round((y - self.miny) * self.k + self.pad))

    def paint(self, p):
        p.setPen(Qt.NoPen)
        p.setBrush(ui.resolve(self.scene, "btn_fill"))
        p.drawRoundedRect(QRectF(0, 0, self.w, self.h), 14, 14)
        for m in self.layout["monitors"]:
            x, y = self.at(m["x"], m["y"])
            w, h = round(m["w"] * self.k), round(m["h"] * self.k)
            g = QLinearGradient(x, y, x + w, y + h)
            g.setColorAt(0, QColor(120, 140, 220, round(255 * 0.35)))
            g.setColorAt(1, QColor(220, 160, 200, round(255 * 0.3)))
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawRoundedRect(QRectF(x, y, w, h), 6, 6)
            p.setPen(QPen(ui.resolve(self.scene, "ink2"), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(x + 0.75, y + 0.75, w - 1.5, h - 1.5), 6, 6)

    def clip_tree(self):
        return True


class MapBox(View):
    cursor = Qt.OpenHandCursor

    def __init__(self, mm, wd, index):
        super().__init__(0, 0, max(14, round(wd["w"] * mm.k)), max(14, round(wd["h"] * mm.k)))
        self.mm, self.wd, self.index = mm, wd, index
        self.x, self.y = mm.at(wd["x"], wd["y"])
        self.interactive = True
        self.drag = None
        self.on_press = self._press
        self.on_move = self._move
        self.on_release = self._release

    def _press(self, e):
        ed = self.mm.editor
        if ed.widget_id != self.wd["id"]:
            ed.select_widget(self.wd["id"], keep_drag=True)
        ed.editor_dragging = True
        self.drag = {"start": (e.gx, e.gy), "origin": (self.x, self.y), "base": (self.wd["x"], self.wd["y"])}
        return True

    def _move(self, e):
        d = self.drag
        if not d:
            return True
        dx, dy = e.gx - d["start"][0], e.gy - d["start"][1]
        self.x, self.y = d["origin"][0] + dx, d["origin"][1] + dy
        k = self.mm.k
        try:
            r = self.mm.editor.facade.api.move_widget(self.wd["id"], round(d["base"][0] + dx / k), round(d["base"][1] + dy / k))
        except Exception:
            r = None
        if r:
            self.x = round(d["origin"][0] + (r["x"] - d["base"][0]) * k)
            self.y = round(d["origin"][1] + (r["y"] - d["base"][1]) * k)
        self.changed()
        return True

    def _release(self, e):
        self.drag = None
        self.mm.editor.editor_dragging = False
        self.mm.editor.refresh_layout()
        return True

    def paint(self, p):
        sel = self.wd["id"] == self.mm.editor.selected_id()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawRoundedRect(QRectF(0, 2, self.w, self.h), 7, 7)
        p.setBrush(ui.resolve(self.scene, "panel_solid"))
        p.drawRoundedRect(QRectF(0, 0, self.w, self.h), 7, 7)
        p.setPen(QPen(ui.resolve(self.scene, "accent_blue" if sel else "ink2"), 2 if sel else 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(1, 1, self.w - 2, self.h - 2), 7, 7)
        text = "#%d" % (self.index + 1)
        f = ui.font(11, QFont.Bold)
        fm = ui.QFontMetricsF(f)
        tw = ui.text_width(text, f)
        col = ui.resolve(self.scene, "ink1")
        if not self.wd.get("visible", True):
            col.setAlphaF(0.45)
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawPath(render.text_path(QPointF(0, 0), f, text, (self.w - tw) / 2, (self.h - fm.height() / 10) / 2 + fm.ascent() / 10))


class Preview(View):
    """The selected widget as it will look on the desktop; tiles drag to reorder, a cross removes one."""

    def __init__(self, editor, widget, zoom, form):
        self.editor, self.widget, self.form_override = editor, widget, form
        size = "2x4" if widget.get("panel") else widget["size"]
        self.size_key = size
        w, h = render.widget_size(size)
        self.zoom_k = zoom
        super().__init__(0, 0, round(w * zoom), round(h * zoom))
        self.interactive = True
        self.cw, self.ch = w, h
        self.form, self.rects = render.tile_layout(size, len(widget["tiles"]), form)
        self.press = None
        self.drop = None
        self.hover = -1
        self.cache = None
        self.on_press = self._press
        self.on_move = self._move
        self.on_release = self._release
        self.on_leave = lambda e: self._set_hover(-1)

    def invalidate(self):
        self.cache = None
        self.changed()

    def tile_at(self, x, y):
        x, y = x / self.zoom_k, y / self.zoom_k
        for i, (tx, ty, tw, th) in enumerate(self.rects):
            if tx <= x < tx + tw and ty <= y < ty + th:
                return i
        return -1

    def remove_hit(self, i, x, y):
        tx, ty, tw, th = self.rects[i]
        cx, cy = (tx + tw - 8 - 12) * self.zoom_k, (ty + 8 + 12) * self.zoom_k
        return abs(x - cx) <= 12 * self.zoom_k + 2 and abs(y - cy) <= 12 * self.zoom_k + 2

    def _set_hover(self, i):
        if i != self.hover:
            self.hover = i
            self.changed()
        return True

    def hovered_move(self, x, y):
        self._set_hover(self.tile_at(x, y))

    def _press(self, e):
        i = self.tile_at(e.x, e.y)
        if i < 0:
            return True
        if self.remove_hit(i, e.x, e.y):
            self.editor.remove_tile_at(i)
            return True
        self.press = {"i": i, "start": (e.gx, e.gy), "dragging": False}
        return True

    def _move(self, e):
        pr = self.press
        if not pr:
            return True
        if not pr["dragging"]:
            if ((e.gx - pr["start"][0]) ** 2 + (e.gy - pr["start"][1]) ** 2) ** 0.5 < 6:
                return True
            pr["dragging"] = True
        j = self.tile_at(e.x, e.y)
        if j >= 0:
            tx, ty, tw, th = self.rects[j]
            before = e.x / self.zoom_k < tx + tw / 2
            self.drop = (j, before)
        self.changed()
        return True

    def _release(self, e):
        pr, drop = self.press, self.drop
        self.press = self.drop = None
        if pr and pr["dragging"] and drop:
            j, before = drop
            to = j + (0 if before else 1)
            frm = pr["i"]
            if frm < to:
                to -= 1
            if to != frm:
                self.editor.move_tile(frm, to)
        self.changed()
        return True

    def paint(self, p):
        s = self.scene.scale / self.scene.dpi
        key = (self.scene.theme, self.scene.style, repr(self.widget["tiles"]), self.zoom_k,
               repr({t["entity"]: self.editor.states.get(t["entity"]) for t in self.widget["tiles"]}), self.hover)
        if self.cache is None or self.cache[0] != key:
            img = QImage(round(self.w * s) + 2, round(self.h * s) + 2, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            q = QPainter(img)
            q.scale(s * self.zoom_k, s * self.zoom_k)
            render.draw_widget(q, self.size_key, self.widget["tiles"], self.editor.states, self.scene.theme, None, 1.0,
                               False, self.scene.style, None, self.scene.theme_raw, self.form_override, False)
            q.end()
            pix = QPixmap.fromImage(img)
            pix.setDevicePixelRatio(s)
            self.cache = (key, pix)
        p.drawPixmap(0, 0, self.cache[1])
        z = self.zoom_k
        if self.press and self.press["dragging"]:
            tx, ty, tw, th = self.rects[self.press["i"]]
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 90))
            p.drawPath(render.squircle(tx * z, ty * z, tw * z, th * z, 62 * z))
        if self.drop:
            j, before = self.drop
            tx, ty, tw, th = self.rects[j]
            p.setPen(Qt.NoPen)
            p.setBrush(ui.resolve(self.scene, "accent_blue"))
            x = tx * z if before else (tx + tw) * z - 6
            p.drawRoundedRect(QRectF(x, ty * z + 8 * z, 6, th * z - 16 * z), 3, 3)
        if 0 <= self.hover < len(self.rects) and not (self.press and self.press["dragging"]):
            tx, ty, tw, th = self.rects[self.hover]
            cx, cy = (tx + tw - 8 - 12) * z, (ty + 8 + 12) * z
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, round(255 * 0.45)))
            p.drawEllipse(QPointF(cx, cy), 12 * z, 12 * z)
            f = ui.font(13 * z)
            fm = ui.QFontMetricsF(f)
            tw2 = ui.text_width("✕", f)
            p.setBrush(QColor(255, 255, 255))
            p.drawPath(render.text_path(QPointF(0, 0), f, "✕", cx - tw2 / 2, cy - fm.height() / 20 + fm.ascent() / 10 - fm.height() / 20))


class TileRow(View):
    """One device of the list: a handle, its icon, its name and entity, the temperature step of a climate, a cross."""

    def __init__(self, editor, tile, index, w):
        super().__init__(0, 0, w, 40)
        self.editor, self.tile, self.index = editor, tile, index
        self.interactive = True
        self.cursor = Qt.OpenHandCursor
        self.press = None
        self.on_press = self._press
        self.on_move = self._move
        self.on_release = self._release
        self.on_dblclick = self._rename
        self.step = None
        right = w - 8 - 24
        self.add(Button("✕", x=right, y=8, w=24, h=24, size=12, on_click=lambda e: editor.delete_tile(index)))
        right -= 6
        if tile["domain"] == "climate":
            self.step = TextField(right - 40, 8, 40, 24, str(float(tile.get("temp_step") or 1)).rstrip("0").rstrip("."),
                                  "", 11, self._step_done, 4, radius=11)
            self.add(self.step)
            self.add(Label("±", 10.5, QFont.Normal, "ink2", x=right - 40 - 14, y=(40 - 12.6) / 2))
            right -= 40 + 18
        self.text_w = right - 70
        self.rename = None

    def _step_done(self, text):
        try:
            v = float(text)
        except ValueError:
            v = 1.0
        self.tile["temp_step"] = v if v > 0 else 1.0
        self.editor.persist()

    def _rename(self, e):
        if e.x < 70 or e.x > 70 + self.text_w:
            return True
        self.rename = TextField(66, 6, self.text_w + 8, 28, self.tile.get("room") or "", "", 12.5,
                                self._rename_done, 40, radius=11)
        self.add(self.rename)
        self.rename.focus()
        return True

    def _rename_done(self, text):
        if self.rename is None:
            return
        self.tile["room"] = text.strip() or self.tile["entity"]
        self.rename = None
        self.editor.persist()
        self.editor.build()

    def _press(self, e):
        self.press = {"start": (e.gx, e.gy), "dragging": False}
        return True

    def _move(self, e):
        pr = self.press
        if not pr:
            return True
        if not pr["dragging"]:
            if abs(e.gy - pr["start"][1]) < 6:
                return True
            pr["dragging"] = True
        host = self.parent
        ly = host.to_local(e.gx, e.gy)[1]
        self.editor.list_drop = max(0, min(len(host.children) - 1, int(ly // 46)))
        host.changed()
        return True

    def _release(self, e):
        pr, self.press = self.press, None
        drop = getattr(self.editor, "list_drop", None)
        self.editor.list_drop = None
        if pr and pr["dragging"] and drop is not None and drop != self.index:
            self.editor.move_tile(self.index, drop)
        return True

    def paint(self, p):
        p.setPen(QPen(ui.resolve(self.scene, "input_border"), 1))
        p.setBrush(ui.resolve(self.scene, "input_bg"))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.w - 1, self.h - 1), 20, 20)
        ink2 = ui.resolve(self.scene, "ink2")
        f = ui.font(13)
        fm = ui.QFontMetricsF(f)
        p.setPen(Qt.NoPen)
        p.setBrush(ink2)
        p.drawPath(render.text_path(QPointF(0, 0), f, "⠿", 10, (self.h - fm.height() / 10) / 2 + fm.ascent() / 10))
        render.draw_icon(p, render.icon_name(self.tile, None), (ink2.red(), ink2.green(), ink2.blue(), ink2.alphaF()),
                         QRectF(32, 9, 22, 22))
        if self.rename is None:
            f1, f2 = ui.font(12.5, QFont.DemiBold), ui.font(10.5)
            m1, m2 = ui.QFontMetricsF(f1), ui.QFontMetricsF(f2)
            p.setBrush(ui.resolve(self.scene, "ink1"))
            p.drawPath(render.text_path(QPointF(0, 0), f1, ui.ellipsize(self.tile.get("room") or self.tile["entity"], f1, self.text_w), 66,
                                        5 + (15 - m1.height() / 10) / 2 + m1.ascent() / 10))
            p.setBrush(ink2)
            p.drawPath(render.text_path(QPointF(0, 0), f2, ui.ellipsize(self.tile["entity"], f2, self.text_w), 66,
                                        21 + (13 - m2.height() / 10) / 2 + m2.ascent() / 10))
        d = getattr(self.editor, "list_drop", None)
        if d is not None and self.press and self.press["dragging"] is False:
            pass


class EditorMixin:
    def editor_init(self):
        self.editor_dragging = False
        self.layout = None
        self.list_drop = None
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
        self.go("editor")
        self.layout_timer.start()
        self.refresh_layout()

    def close_editor(self, e=None):
        self.layout_timer.stop()
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
        tile = {"id": new_tile_id(), "entity": e["entity_id"], "domain": e["domain"], "room": e.get("name") or e["entity_id"],
                "label": "", "icon": "", "on_mode": "cool", "temp_step": 1}
        w = self.settings_widget()
        if w is not None:
            w["tiles"].append(tile)
        if e.get("state") and e["entity_id"] not in self.states:
            self.states[e["entity_id"]] = e["state"]
        self.persist()
        self.page = self.return_page
        self.build()

    def set_size(self, size):
        w = self.settings_widget()
        if not w or w.get("panel") or w["size"] == size:
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

    def drag_new_widget(self, size):
        self.editor_dragging = True

        def go():
            try:
                r = self.facade.api.begin_widget_drag(size)
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

        # the left column
        y = 2
        body.add(Label("拖曳到桌面新增", 12, QFont.DemiBold, "ink2", x=LEFT_X, y=y))
        y += 14.4 + 8
        pal = Palette(self, self.drag_new_widget)
        pal.x, pal.y = LEFT_X, y
        body.add(pal)
        y += pal.h
        body.add(Label("桌面配置（拖曳移動）", 12, QFont.DemiBold, "ink2", x=LEFT_X, y=y + 12))
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
            hint = Label("已超過 %d 個 Widget，每多一個都會多用一份記憶體。" % SOFT_LIMIT, 11.5, QFont.Normal, "ink2",
                         x=LEFT_X, y=y + 6, w=LEFT_W, wrap=True, lh=1.4)
            body.add(hint)
            y += 6 + hint.h
        left_h = y

        # the right column
        y = 2
        body.add(Label("我的 Widget", 12, QFont.DemiBold, "ink2", x=RIGHT_X, y=y))
        y += 14.4 + 8
        x = 0
        row_y = y
        chips = []
        for i, w in enumerate(self.widgets()):
            chips.append(Chip("#%d · %s" % (i + 1, w["size"]), (widget and w["id"] == widget["id"]),
                              lambda e, wid=w["id"]: self.select_widget(wid)))
        chips.append(Chip("系統匣面板", on_panel, lambda e: self.select_widget(PANEL_ID)))
        for c in chips:
            if x and x + c.w > RIGHT_W:
                x, row_y = 0, row_y + 28 + 6
            c.x, c.y = RIGHT_X + x, row_y
            body.add(c)
            x += c.w + 6
        y = row_y + 28
        body.add(Label("預覽（拖曳配件調整順序）", 12, QFont.DemiBold, "ink2", x=RIGHT_X, y=y + 12))
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
            if not widget["tiles"]:
                body.add(Label("尚無配件，按下方「新增配件」", 15, QFont.Normal, "white", x=RIGHT_X + 20, y=y + box_h / 2 - 10,
                               w=RIGHT_W - 40, align="c"))
            y += box_h
        # the tools
        ty = y + 12
        tx = RIGHT_X
        if not on_panel:
            for size in SIZES:
                c = Chip(size, bool(widget and widget["size"] == size), lambda e, s=size: self.set_size(s))
                c.x, c.y = tx, ty
                body.add(c)
                tx += c.w + 6
            tx += 6
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
        # the devices
        tiles = widget["tiles"] if widget else []
        body.add(Label("配件 (%d)" % len(tiles), 12, QFont.Bold, "ink2", x=RIGHT_X, y=y + 5, spacing=0.36))
        add = Button("+ 新增配件", size=12, weight=QFont.DemiBold, h=28, pad=12, fill="accent_blue", hover_fill="accent_blue",
                     color="white", on_click=lambda e: self.open_picker())
        add.x, add.y = EDITOR_W - 18 - add.w, y
        body.add(add)
        y += 28 + 8
        lst = ScrollView(RIGHT_X, y, RIGHT_W, min(190, max(0, len(tiles) * 46 - 6)))
        for i, t in enumerate(tiles):
            row = TileRow(self, t, i, RIGHT_W)
            row.y = i * 46
            lst.add(row)
        lst.content.w, lst.content.h = RIGHT_W, max(0, len(tiles) * 46 - 6)
        body.add(lst)
        y += lst.h
        body.h = max(left_h, y) + 18
        return body

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
        # the rest of the left column follows it: when the layout arrives after the page was built, build again
        if self.mm_built is not None and self.mm_built != mm.h:
            QTimer.singleShot(0, self.build)
        self.request_paint()
