"""The views of the widget editor (editor.py): the palette of widgets to drag, the map of the desktop, the preview of the
selected widget and its rows of devices."""
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen

from . import customview, kinds, render, style, ui
from .ui import Button, TextField, View

SIZES = ["1x1", "2x2", "2x4", "4x4"]
PALETTE_SCALE = 0.19
LEFT_X, LEFT_W = 18, 300
ROW_STEP = 46                    # a device row and the space under it


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
            self.add(style.label("group", "時鐘、日曆、天氣、攝影機、圖表與播放器", x=0, y=y - 4))
            y += 14.4 + 8
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
        self.tick_wait = False               # a widget of the kit that draws on its own has its next drawing waiting
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

    def _custom_card(self, p):
        """A widget of the kit: drawn from its runtime, again whenever what it shows has changed."""
        sc, ed = self.scene, self.editor
        rt = ed.custom_preview(self.widget)
        key = (sc.theme, sc.style, self.zoom_k, p.transform().m11(), render._language, ed.custom_rev,
               repr((ed.custom_now or {}).get("config")), self.size_key)
        if self.cache is None or self.cache[0] != key:
            z = self.zoom_k

            def draw(q):
                q.scale(z, z)
                customview.paint(q, rt, self.size_key, sc.theme, sc.style)
            self.cache = (key, device_image(p, self.w, self.h, draw))
        if rt is not None:                      # what moves on its own is drawn again when it should be
            wait = 16 if rt.animating else (max(0.25, min(rt.widget.tick, 60)) * 1000 if rt.widget.tick else 0)
            if rt.redraw_in is not None and not rt.animating:
                wait = min(wait or 1e9, max(16, rt.redraw_in * 1000))
            if wait and not self.tick_wait:
                self.tick_wait = True
                QTimer.singleShot(int(wait), self._retick)
        return self.cache[1]

    def _retick(self):
        self.tick_wait = False
        if self.scene is not None:
            self.invalidate()

    def _card(self, p):
        if self.kind == "custom":
            return self._custom_card(p)
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
