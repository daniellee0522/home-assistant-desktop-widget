"""The widget editor of Settings: the widgets to drag onto the desktop (the tiles in their four sizes and the
other kinds, each in its own size), a map of the desktop, the selected widget as it will look (tiles drag to
reorder, the others making room as they will), and its list of devices. The page's openEditor and its
renderers."""
import threading
import time
import traceback
import uuid

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen

from . import kinds, render, style, ui
from .ui import Button, CheckRow, Rect, TextField, View

PANEL_ID = "__panel"
SIZES = ["1x1", "2x2", "2x4", "4x4"]
PALETTE_SCALE = 0.19
SOFT_LIMIT = 6
EDITOR_W = 800
LEFT_X, LEFT_W = 18, 300
RIGHT_X = LEFT_X + LEFT_W + 22
RIGHT_W = EDITOR_W - 18 - RIGHT_X
ROW_STEP = 46                    # a device row and the space under it
# what the list of devices is called, and its button, by the widget's kind
LIST_TITLE = {"tiles": "配件", "weather": "天氣", "camera": "攝影機", "chart": "感測器", "media": "播放器"}
ADD_TEXT = {"tiles": "+ 新增配件", "weather": "選擇天氣", "camera": "選擇攝影機", "chart": "+ 新增感測器",
            "media": "選擇播放器"}


def new_tile_id():
    return str(uuid.uuid4())


def device_image(p, w, h, draw):
    """A picture of w x h of the painter's units at the device's resolution: draw(q) paints it in those units."""
    k = p.transform().m11() or 1.0
    img = QImage(max(1, round(w * k) + 2), max(1, round(h * k) + 2), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    q = QPainter(img)
    q.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
    q.scale(k, k)
    try:
        draw(q)
    finally:
        q.end()                          # (a painter left open on a picture brings Qt down when it is freed)
    return img


def put_image(p, img, x, y):
    """A device_image at (x, y) of the painter's units, on whole device pixels (crisp)."""
    ox, oy, _, _ = ui.on_pixels(p, x, y)
    ui.draw_device_image(p, img, ox, oy)


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
    """What can be dragged onto the desktop: a widget of tiles in each size (drawn in proportion), then the other
    kinds of widget (drawn as they look). Pressing one makes a real widget that follows the pointer."""

    def __init__(self, scene_ref, on_press_size, on_press_kind=None):
        super().__init__(0, 0, LEFT_W, 0)
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
        if on_press_kind is not None:
            self.add(style.label("hint", "時鐘、日曆、天氣、攝影機、圖表與播放器", x=0, y=y - 4))
            y += 14 + 8
            # drawn at the sizes' own scale, so a 2x2 clock is as large as the 2x2 of tiles; in rows, bottoms aligned
            line, lines, line_w = [], [], 0
            for kind in kinds.KINDS[1:]:
                cw, _ = render.widget_size(kinds.KIND_SIZE[kind])
                item = KindItem(kind, round(cw * PALETTE_SCALE), on_press_kind)
                if line and line_w + item.w > LEFT_W:
                    lines.append(line)
                    line, line_w = [], 0
                line.append(item)
                line_w += item.w + 16
            lines.append(line)
            for ln in lines:
                lh = max(it.h for it in ln)
                x = 0
                for item in ln:
                    item.x, item.y = x, y + lh - item.h
                    self.add(item)
                    x += item.w + 16
                y += lh + 14
        self.h = y - 14


class KindItem(View):
    """A kind of widget in the palette, drawn as it looks (with made-up devices), its name under it."""
    cursor = Qt.OpenHandCursor

    def __init__(self, kind, w, on_press_kind):
        self.kind, self.size_key = kind, kinds.KIND_SIZE[kind]
        cw, ch = render.widget_size(self.size_key)
        self.bw, self.bh = w, round(w * ch / cw)
        super().__init__(0, 0, w, self.bh + 6 + 14)
        self.interactive = True
        self.on_press = lambda e: (on_press_kind(kind), True)[1]
        self.on_enter = self.on_leave = lambda e: self.changed()
        self.pic = None

    def paint(self, p):
        up = -2 if self.hovered else 0
        sc = self.scene
        key = (sc.theme, sc.style, render._language, p.transform().m11())
        if self.pic is None or self.pic[0] != key:
            cw, _ = render.widget_size(self.size_key)
            tiles, states, extras = kinds.sample(self.kind)

            def draw(q):
                q.scale(self.bw / cw, self.bw / cw)
                kinds.draw_widget(q, self.kind, self.size_key, tiles, states, sc.theme, 1.0, False, sc.style, None,
                                  sc.theme_raw, extras, False)
            self.pic = (key, device_image(p, self.bw, self.bh, draw))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 34 if self.hovered else 20))
        p.drawPath(render.squircle(0, up + 2, self.bw, self.bh, 14))
        p.setBrush(ui.resolve(sc, "btn_fill_strong"))
        p.drawPath(render.squircle(0, up, self.bw, self.bh, 14))
        put_image(p, self.pic[1], 0, up)
        f = ui.font(12)
        fm = ui.QFontMetricsF(f)
        text = render.tr(kinds.KIND_LABELS[self.kind])
        tw = ui.text_width(text, f)
        p.setBrush(ui.resolve(sc, "ink1" if self.hovered else "ink2"))
        p.drawPath(render.text_path(QPointF(0, 0), f, text, (self.w - tw) / 2,
                                    self.bh + 6 + (14 - fm.height() / 10) / 2 + fm.ascent() / 10))


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
        # (the editor is built again for a new selection when the button is let go: built now, this box
        # would be gone from under the pointer)
        self.mm.editor.editor_dragging = True
        self.drag = {"start": (e.gx, e.gy), "origin": (self.x, self.y), "base": (self.wd["x"], self.wd["y"]),
                     "moved": False}
        return True

    def _move(self, e):
        d = self.drag
        if not d:
            return True
        dx, dy = e.gx - d["start"][0], e.gy - d["start"][1]
        if not d["moved"]:
            if (dx * dx + dy * dy) ** 0.5 < 5:          # a click that trembles moves nothing
                return True
            d["moved"] = True
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
        ed = self.mm.editor
        ed.editor_dragging = False
        if ed.widget_id != self.wd["id"]:
            ed.select_widget(self.wd["id"])
        ed.refresh_layout()
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
    """The selected widget as it will look on the desktop. A tile dragged follows the pointer and the others
    make room for it where they will be (sliding there); a cross removes one. A weather, a camera or a chart is
    one picture."""

    def __init__(self, editor, widget, zoom, form):
        self.editor, self.widget, self.form_override = editor, widget, form
        size = "2x4" if widget.get("panel") else widget["size"]
        self.size_key = size
        self.kind = "tiles" if widget.get("panel") else (widget.get("kind") or "tiles")
        w, h = render.widget_size(size)
        self.zoom_k = zoom
        super().__init__(0, 0, round(w * zoom), round(h * zoom))
        self.interactive = True
        self.cw, self.ch = w, h
        n = len(widget["tiles"])
        if self.kind == "tiles":
            self.form, self.rects = render.tile_layout(size, n, form)
        else:
            self.form, self.rects = "small", []
        # only the tiles in sight take the pointer and the drop
        self.slots = [i for i, r in enumerate(self.rects) if r[1] + r[3] <= h - render.PAD + 1]
        self.press = None
        self.hover = -1
        self.cache = None                    # the card (or the whole of a weather, a camera, a chart)
        self.pics = {}                       # each tile's picture
        # where each tile is drawn, sliding to its place: a drop leaves them where they were seen
        self.pos = dict(getattr(editor, "preview_landing", None) or {})
        editor.preview_landing = None
        self.on_press = self._press
        self.on_move = self._move
        self.on_release = self._release
        self.on_leave = lambda e: self._set_hover(-1)

    def invalidate(self):
        self.cache = None
        self.pics.clear()
        self.changed()

    def tile_at(self, x, y):
        x, y = x / self.zoom_k, y / self.zoom_k
        for i in self.slots:
            tx, ty, tw, th = self.rects[i]
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

    def dragging(self):
        return bool(self.press and self.press["dragging"])

    def order(self):
        """The tiles as they will be: the one dragged where it would be dropped."""
        tiles = list(self.widget["tiles"])
        if self.dragging():
            t = tiles.pop(self.press["i"])
            tiles.insert(self.press["to"], t)
        return tiles

    def _press(self, e):
        i = self.tile_at(e.x, e.y)
        if i < 0:
            return True
        if self.remove_hit(i, e.x, e.y):
            self.editor.remove_tile_at(i)
            return True
        tx, ty, _, _ = self.rects[i]
        self.press = {"i": i, "to": i, "start": (e.gx, e.gy), "dragging": False,
                      "grab": (e.x / self.zoom_k - tx, e.y / self.zoom_k - ty), "at": (e.x, e.y)}
        return True

    def _move(self, e):
        pr = self.press
        if not pr:
            return True
        if not pr["dragging"]:
            if ((e.gx - pr["start"][0]) ** 2 + (e.gy - pr["start"][1]) ** 2) ** 0.5 < 6:
                return True
            pr["dragging"] = True
            self.hover = -1
        pr["at"] = (e.x, e.y)
        # the place whose middle is nearest the middle of the tile carried
        _, _, tw, th = self.rects[pr["i"]]
        cx = e.x / self.zoom_k - pr["grab"][0] + tw / 2
        cy = e.y / self.zoom_k - pr["grab"][1] + th / 2
        pr["to"] = min(self.slots, key=lambda j: (self.rects[j][0] + self.rects[j][2] / 2 - cx) ** 2
                       + (self.rects[j][1] + self.rects[j][3] / 2 - cy) ** 2)
        self.changed()
        return True

    def _release(self, e):
        pr, self.press = self.press, None
        if pr and pr["dragging"] and pr["to"] != pr["i"]:
            self.editor.preview_landing = dict(self.pos)   # the next preview slides on from here
            self.editor.move_tile(pr["i"], pr["to"])
            return True
        self.changed()
        return True

    def _card(self, p):
        sc = self.scene
        tiles = self.widget["tiles"]
        whole = self.kind != "tiles"
        key = (sc.theme, sc.style, self.kind, self.zoom_k, p.transform().m11(), render._language,
               repr(tiles) if whole else None,
               repr({t["entity"]: self.editor.states.get(t["entity"]) for t in tiles}) if whole else None,
               time.strftime("%Y%m%d%H%M") if self.kind in kinds.NO_DEVICES else None,   # a clock's minute
               repr(self.widget.get("font")))
        if self.cache is None or self.cache[0] != key:
            z = self.zoom_k

            def draw(q):
                q.scale(z, z)
                if self.kind == "tiles":
                    render.draw_widget(q, self.size_key, [], {}, sc.theme, None, 1.0, False, sc.style, None,
                                       sc.theme_raw, self.form_override, False)
                else:
                    kinds.draw_widget(q, self.kind, self.size_key, tiles if whole else [], self.editor.states,
                                      sc.theme, 1.0, False, sc.style, None, sc.theme_raw,
                                      {"font": self.widget.get("font")}, False)
            self.cache = (key, device_image(p, self.w, self.h, draw))
        return self.cache[1]

    def _tile_pic(self, p, tile, slot, w, h):
        sc = self.scene
        st = self.editor.states.get(tile["entity"])
        key = (repr(tile), repr(st), sc.theme, sc.style, self.form, self.zoom_k, p.transform().m11())
        pic = self.pics.get(key)
        if pic is None:
            z = self.zoom_k

            def draw(q):
                q.scale(z, z)
                render.draw_tile(q, tile, st, 0, 0, w, h, sc.theme, render.tokens(sc.theme, False, sc.style),
                                 self.form)
            if len(self.pics) > 64:
                self.pics.clear()
            pic = self.pics[key] = device_image(p, w * z, h * z, draw)
        return pic

    def paint(self, p):
        z = self.zoom_k
        put_image(p, self._card(p), 0, 0)
        if self.kind != "tiles":
            return
        pr = self.press if self.dragging() else None
        moving = False
        p.save()
        p.setClipRect(QRectF(render.PAD * z, render.PAD * z, (self.cw - 2 * render.PAD) * z,
                             (self.ch - 2 * render.PAD) * z))
        for j, tile in enumerate(self.order()):
            if j >= len(self.rects):
                break
            tx, ty, tw, th = self.rects[j]
            if pr and j == pr["to"]:
                # where the tile carried will land
                col = ui.resolve(self.scene, "white" if self.scene.theme == "dark" else "ink2")
                col.setAlphaF(0.6)
                p.setPen(QPen(col, 1.5, Qt.DashLine))
                fill = QColor(col)
                fill.setAlphaF(0.10)
                p.setBrush(fill)
                p.drawPath(render.squircle(tx * z + 1, ty * z + 1, tw * z - 2, th * z - 2, 62 * z))
                continue
            at = self.pos.get(tile["id"])
            if at is None or (abs(at[0] - tx) < 0.5 and abs(at[1] - ty) < 0.5):
                at = [tx, ty]
            else:
                at = [at[0] + (tx - at[0]) * 0.3, at[1] + (ty - at[1]) * 0.3]
                moving = True
            self.pos[tile["id"]] = at
            put_image(p, self._tile_pic(p, tile, j, tw, th), at[0] * z, at[1] * z)
        p.restore()
        if pr:
            # the tile carried, a little larger, over the others
            tile = self.widget["tiles"][pr["i"]]
            _, _, tw, th = self.rects[pr["i"]]
            x, y = pr["at"][0] / z - pr["grab"][0], pr["at"][1] / z - pr["grab"][1]
            self.pos[tile["id"]] = [x, y]
            pic, k = self._tile_pic(p, tile, pr["to"], tw, th), p.transform().m11() or 1.0
            p.save()
            p.translate((x + tw / 2) * z, (y + th / 2) * z)
            p.scale(1.05, 1.05)
            p.translate(-tw / 2 * z, -th / 2 * z)
            p.setPen(Qt.NoPen)
            for spread, a in ((12, 16), (6, 26)):
                p.setBrush(QColor(0, 0, 0, a))
                p.drawPath(render.squircle(-spread / 2, spread / 2, tw * z + spread, th * z + spread, 66 * z))
            p.drawImage(QRectF(0, 0, pic.width() / k, pic.height() / k), pic)
            p.restore()
        if moving:
            QTimer.singleShot(16, self.changed)
        if self.hover in self.slots and not pr:
            tx, ty, tw, th = self.rects[self.hover]
            cx, cy = (tx + tw - 8 - 12) * z, (ty + 8 + 12) * z
            style.remove_badge(p, QRectF(cx - 12 * z, cy - 12 * z, 24 * z, 24 * z))


class TileRow(View):
    """One device of the list: a handle, its icon, its name and entity, the temperature step of a climate, a cross."""

    def __init__(self, editor, tile, index, w):
        super().__init__(0, index * ROW_STEP, w, 40)
        self.editor, self.tile, self.index = editor, tile, index
        self.goal = self.y
        self.interactive = True
        self.cursor = Qt.OpenHandCursor
        self.press = None
        self.on_press = self._press
        self.on_move = self._move
        self.on_release = self._release
        self.on_dblclick = self._rename
        self.step = None
        right = w - 8 - 24
        self.add(Button(x=right, y=8, w=24, h=24, icon="mdi:close", icon_size=15,
                        on_click=lambda e: editor.delete_tile(index)))
        right -= 6
        if tile["domain"] == "climate":
            self.step = TextField(right - 40, 8, 40, 24, str(float(tile.get("temp_step") or 1)).rstrip("0").rstrip("."),
                                  "", 11, self._step_done, 4, radius=11)
            self.add(self.step)
            self.add(style.label("tiny", "±", x=right - 40 - 14, y=(40 - 12.6) / 2))
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
        self.press = {"start": (e.gx, e.gy), "dragging": False, "grab": e.y, "to": self.index}
        return True

    def _move(self, e):
        pr = self.press
        if not pr:
            return True
        host = self.parent
        if not pr["dragging"]:
            if abs(e.gy - pr["start"][1]) < 6:
                return True
            pr["dragging"] = True
            self.lifted = True
            host.children.remove(self)              # over the others
            host.children.append(self)
            self.cursor = Qt.ClosedHandCursor
        rows = [c for c in host.children if isinstance(c, TileRow)]
        ly = host.to_local(e.gx, e.gy)[1]
        self.stop_animation()
        self.y = max(-8.0, min((len(rows) - 1) * ROW_STEP + 8.0, ly - pr["grab"]))
        to = max(0, min(len(rows) - 1, round(self.y / ROW_STEP)))
        pr["to"] = to
        slot = 0
        for r in sorted((r for r in rows if r is not self), key=lambda r: r.index):
            if slot == to:
                slot += 1
            if r.goal != slot * ROW_STEP:
                r.goal = slot * ROW_STEP
                r.animate(160, "out", y=r.goal)
            slot += 1
        host.changed()
        return True

    def _release(self, e):
        pr, self.press = self.press, None
        if not pr or not pr["dragging"]:
            return True
        self.cursor = Qt.OpenHandCursor
        if pr["to"] != self.index:
            self.editor.move_tile(self.index, pr["to"])
        else:
            self.lifted = False
            self.animate(160, "out", y=self.index * ROW_STEP)
        return True

    def paint(self, p):
        if self.lifted:
            p.setPen(Qt.NoPen)
            for spread, a in ((10, 14), (4, 22)):
                p.setBrush(QColor(0, 0, 0, a))
                p.drawRoundedRect(QRectF(-spread / 2, spread / 2 + 2, self.w + spread, self.h + spread / 2), 22, 22)
        p.setPen(QPen(ui.resolve(self.scene, "accent_blue" if self.lifted else "input_border"), 1))
        p.setBrush(ui.resolve(self.scene, "panel_solid" if self.lifted else "input_bg"))
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


class EditorMixin:
    def editor_init(self):
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

    def drag_new_widget(self, size, kind="tiles"):
        self.editor_dragging = True

        def go():
            try:
                r = self.facade.api.begin_widget_drag(size, kind)
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
        y = self.editor_widget_chips(body, widget, on_panel)
        kind = self.current_kind()
        y = self.editor_preview(body, y, widget, on_panel, kind)
        y = self.editor_tools(body, y, widget, on_panel, kind, panel)
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
            what = w["size"] if kind == "tiles" else render.tr(kinds.KIND_LABELS[kind])
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
            if not widget["tiles"] and kind not in kinds.NO_DEVICES:
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
