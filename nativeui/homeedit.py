"""Editing the Home view: tiles are pulled to a new place (the others make way, shoved the way the pull
goes), pulled by a corner to another shape, removed; rooms are pulled into a new order. The page's
attachHomeDrag, attachHomeResize and attachRoomReorder."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen

from . import render, ui
from .homemodel import OTHER_ROOM, home_layout
from .ui import Button, Label, Rect, View

TILE_W, TILE_H, GAP = 152, 146, 14
SPAN_W = TILE_W + GAP
SPAN_H = TILE_H + GAP


class Ghost(Rect):
    """Where a tile will land, or the shape it is being given: translucent light grey, solid."""

    def __init__(self, w, h, radius):
        super().__init__(0, 0, w, h, (232, 234, 238, 0.22), radius, (232, 234, 238, 0.65), 2, shape="squircle")

    def path(self):
        return render.squircle(0, 0, self.w, self.h, self.radius_)

    def paint(self, p):
        p.setPen(Qt.NoPen)
        p.setBrush(render.rgba(self.fill))
        p.drawPath(self.path())
        p.setPen(QPen(render.rgba(self.ring), 2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(render.squircle(1, 1, self.w - 2, self.h - 2, self.radius_))


class ResizeHandle(View):
    """The pill at a tile's corner: pull it to make the tile a square, a bar or a large square."""
    cursor = Qt.SizeFDiagCursor

    def __init__(self, z):
        super().__init__(0, 0, 58 * z, 34 * z)
        self.interactive = True

    def paint(self, p):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, round(255 * 0.82)))
        p.drawRoundedRect(QRectF(0, 0, self.w, self.h), self.h / 2, self.h / 2)
        # a diagonal line
        k = self.w / 58
        p.setPen(QPen(QColor(0x4a, 0x4a, 0x52), 3.2 * k, Qt.SolidLine, Qt.RoundCap))
        cx, cy = self.w / 2, self.h / 2
        p.drawLine(QPointF(cx - 6 * k, cy - 6 * k), QPointF(cx + 6 * k, cy + 6 * k))


class RemoveButton(View):
    cursor = Qt.PointingHandCursor

    def __init__(self, z, on_click):
        super().__init__(0, 0, 34 * z, 34 * z)
        self.interactive = True
        self.on_press = lambda e: True
        self.on_click = lambda e: on_click()
        self.z = z

    def paint(self, p):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawEllipse(QRectF(0, 2 * self.z, self.w, self.h))
        p.setBrush(QColor(255, 91, 74, round(255 * 0.96)))
        p.drawEllipse(QRectF(0, 0, self.w, self.h))
        f = ui.font(17 * self.z, QFont.Bold)
        fm = ui.QFontMetricsF(f)
        tw = ui.text_width("✕", f)
        p.setBrush(QColor(255, 255, 255))
        p.drawPath(render.text_path(QPointF(0, 0), f, "✕", (self.w - tw) / 2,
                                    (self.h - fm.height() / 10) / 2 + fm.ascent() / 10))


class EditMixin:
    # -- the corners and the buttons ---------------------------------------------------------------------
    def decorate_tile(self, tv, e):
        z = render.BIG_ZOOM if tv.form == "big" else 1.0
        tv.editing = True
        tv.cursor = Qt.OpenHandCursor
        handle = ResizeHandle(z)
        handle.x, handle.y = tv.w - 10 * z - handle.w, tv.h - 10 * z - handle.h
        handle.on_press = lambda ev, tv=tv, e=e: self.resize_press(tv, e, ev)
        handle.on_move = lambda ev, tv=tv: self.resize_move(tv, ev)
        handle.on_release = lambda ev, tv=tv: self.resize_release(tv)
        tv.add(handle)
        tv.on_press = lambda ev, tv=tv, e=e: self.drag_press(tv, e, ev)
        tv.on_move = lambda ev, tv=tv: self.drag_move(tv, ev)
        tv.on_release = lambda ev, tv=tv: self.drag_release(tv)
        tv.on_click = None
        if not self.m.room:
            off = (4 if tv.form == "big" else 6) * z
            rb = RemoveButton(z, lambda e=e: self.remove_device(e))
            rb.x, rb.y = tv.w - rb.w + off, -off
            tv.add(rb)

    def remove_device(self, e):
        self.m.ensure_record(e["entity_id"])["hidden"] = True
        self.persist()
        self.build()
        self.apply_category_state(animate=False)

    # -- resizing --------------------------------------------------------------------------------------------
    def resize_press(self, tv, e, ev):
        grid = tv.parent
        span = self.m.span(self.m.record(e["entity_id"]))
        ghost = Ghost(span[0] * TILE_W + (span[0] - 1) * GAP, span[1] * TILE_H + (span[1] - 1) * GAP,
                      self.panel.t["radius_tile"])
        ghost.x, ghost.y = tv.x, tv.y
        grid.add(ghost)
        gx, gy = tv.abs_pos()
        self.resizing = {"tv": tv, "e": e, "span": span, "ghost": ghost, "origin": (gx, gy), "grid": grid}
        return True

    def resize_move(self, tv, ev):
        r = getattr(self, "resizing", None)
        if not r:
            return True
        ox, oy = r["origin"]
        cols = max(1, min(2, round(((ev.gx - ox) + GAP) / SPAN_W)))
        rows = max(1, min(2, round(((ev.gy - oy) + GAP) / SPAN_H)))
        span = (2, 2) if (rows == 2 and cols == 2) else (2, 1) if cols == 2 else (1, 1)       # the three shapes
        r["span"] = span
        g = r["ghost"]
        g.w, g.h = span[0] * TILE_W + (span[0] - 1) * GAP, span[1] * TILE_H + (span[1] - 1) * GAP
        g.changed()
        return True

    def resize_release(self, tv):
        r = getattr(self, "resizing", None)
        self.resizing = None
        if not r:
            return True
        e, span = r["e"], r["span"]
        room = r["grid"].room
        items = self.m.items([x for x in self.m.entities if self.m.visible(x) and self.m.room_key(x.get("area")) == room])
        now = home_layout(items).get(e["entity_id"])
        self.m.save_layout(home_layout(items, {"id": e["entity_id"], "x": now["x"], "y": now["y"], "w": span[0], "h": span[1]}))
        self.persist()
        self.build()
        self.apply_category_state(animate=False)
        return True

    # -- a capsule screen's own sizes: apart from the rooms' ---------------------------------------------------
    def add_cat_handle(self, tv, e):
        z = render.BIG_ZOOM if tv.form == "big" else 1.0
        handle = ResizeHandle(z)
        handle.x, handle.y = tv.w - 10 * z - handle.w, tv.h - 10 * z - handle.h
        handle.on_press = lambda ev, tv=tv, e=e: self.cat_resize_press(tv, e, ev)
        handle.on_move = lambda ev: self.resize_move(tv, ev)
        handle.on_release = lambda ev, e=e: self.cat_resize_release(e)
        tv.add(handle)

    def cat_resize_press(self, tv, e, ev):
        span = self.m.cat_span(self.m.record(e["entity_id"]))
        ghost = Ghost(tv.w, tv.h, self.panel.t["radius_tile"])
        ghost.x, ghost.y = tv.x, tv.y
        tv.parent.add(ghost)
        self.resizing = {"tv": tv, "e": e, "span": span, "ghost": ghost, "origin": tv.abs_pos(), "grid": tv.parent}
        return True

    def cat_resize_release(self, e):
        r = getattr(self, "resizing", None)
        self.resizing = None
        if not r:
            return True
        rec = self.m.ensure_record(e["entity_id"])
        span = r["span"]
        for key in ("cat_w", "cat_h"):
            rec.pop(key, None)
        if span[0] == 2:
            rec["cat_w"] = 2
        if span[1] == 2:
            rec["cat_h"] = 2
        self.persist()
        self.build()
        self.apply_category_state(animate=False)
        return True

    # -- dragging a tile -----------------------------------------------------------------------------------------
    def drag_press(self, tv, e, ev):
        self.drag = {"tv": tv, "e": e, "start": (ev.gx, ev.gy), "lifted": False}
        return True

    def content_point(self, gx, gy):
        return self.body.content.to_local(gx, gy)

    def drag_move(self, tv, ev):
        d = getattr(self, "drag", None)
        if not d or d["tv"] is not tv:
            return True
        if not d["lifted"]:
            if ((ev.gx - d["start"][0]) ** 2 + (ev.gy - d["start"][1]) ** 2) ** 0.5 < 6:
                return True
            self.lift(d, ev)
        # near the top or bottom edge the list scrolls
        bx, by = self.body.to_local(ev.gx, ev.gy)
        if by < 36:
            self.body.scroll_to(self.body.offset - 14)
        elif by > self.body.h - 36:
            self.body.scroll_to(self.body.offset + 14)
        self.place_lifted(d, ev)
        self.relayout_drag(d, ev)
        return True

    def lift(self, d, ev):
        tv, e = d["tv"], d["e"]
        d["lifted"] = True
        grid0 = tv.parent
        d["grid0"] = grid0
        d["room0"] = grid0.room
        d["target"] = grid0
        # the tile leaves its room's grid for the list itself, where it follows the pointer anywhere
        ax, ay = tv.abs_pos()
        cx, cy = self.content_point(ax, ay) if False else (ax - self.body.content.abs_pos()[0], ay - self.body.content.abs_pos()[1])
        px, py = self.content_point(ev.gx, ev.gy)
        d["grab"] = (px - cx, py - cy)
        grid0.remove(tv)
        tv.x, tv.y = cx, cy
        tv.lifted = True
        tv.zoom = 1.03
        self.body.content.add(tv)
        d["span"] = self.m.span(self.m.record(e["entity_id"]))
        d["slot"] = Ghost(d["span"][0] * TILE_W + (d["span"][0] - 1) * GAP, d["span"][1] * TILE_H + (d["span"][1] - 1) * GAP,
                          self.panel.t["radius_tile"])
        grid0.add(d["slot"])
        mine = home_layout(self.m.items([x for x in self.m.entities if self.m.visible(x)
                                         and self.m.room_key(x.get("area")) == d["room0"]])).get(e["entity_id"])
        d["cell"] = (mine["x"], mine["y"]) if mine else None
        d["push"] = {"x": 0, "y": 1}
        d["final"] = None
        tv.invalidate()

    def place_lifted(self, d, ev):
        px, py = self.content_point(ev.gx, ev.gy)
        tv = d["tv"]
        tv.x, tv.y = px - d["grab"][0], py - d["grab"][1]
        tv.changed()

    def grid_origin(self, grid):
        """A grid's top-left in the list's own space."""
        gx, gy = grid.abs_pos()
        cx, cy = self.body.content.abs_pos()
        return gx - cx, gy - cy

    def others(self, grid, skip):
        return [x for x in self.m.entities if self.m.visible(x) and self.m.room_key(x.get("area")) == grid.room
                and x["entity_id"] != skip]

    def apply_layout(self, grid, layout, hide=None, extra_rows=0, animate=True):
        rows = 0
        for v in grid.children:
            if not hasattr(v, "entity"):
                continue
            r = layout.get(v.entity["entity_id"])
            if r is None or getattr(v, "lifted", False):
                continue
            tx, ty = r["x"] * SPAN_W, r["y"] * SPAN_H
            v.animate(220 if animate else 0, "out", x=tx, y=ty)
            rows = max(rows, r["y"] + r["h"])
        for r in layout.values():
            rows = max(rows, r["y"] + r["h"])
        rows = max(rows, extra_rows)
        grid.h = rows * SPAN_H - GAP if rows else grid.h
        grid.parent.h = 48 + grid.h
        self.restack()

    def restack(self):
        y = 18
        for s in self.sections:
            s.y = y
            y += s.h + 18
        self.body.content.h = max(y - 18, 0)
        self.body.scroll_to(self.body.offset)
        self.body.changed()

    def relayout_drag(self, d, ev):
        tv, e = d["tv"], d["e"]
        px, py = self.content_point(ev.gx, ev.gy)
        target = d["target"]
        over = None
        for s in self.sections:
            g = getattr(s, "grid", None)
            if g is None:
                continue
            ox, oy = self.grid_origin(g)
            if ox <= px <= ox + 650 and oy - 10 <= py <= oy + g.h + 10:
                over = g
                break
        if over is not None and over is not target:
            was = target
            d["target"] = over
            self.apply_layout(was, home_layout(self.m.items(self.others(was, e["entity_id"]))))
            was.remove(d["slot"])
            over.add(d["slot"])
            target = over
        ox, oy = self.grid_origin(target)
        left = (px - ox) - d["grab"][0]
        top = (py - oy) - d["grab"][1]
        x = round(left / SPAN_W)
        y = max(0, round(top / SPAN_H))
        if d["cell"] and (x != d["cell"][0] or y != d["cell"][1]):
            dx, dy = x - d["cell"][0], y - d["cell"][1]
            d["push"] = {"x": -(1 if dx > 0 else -1 if dx < 0 else 0), "y": 0} if abs(dx) >= abs(dy) \
                else {"x": 0, "y": -(1 if dy > 0 else -1 if dy < 0 else 0)}
            d["cell"] = (x, y)
        span = d["span"]
        final = home_layout(self.m.items(self.others(target, e["entity_id"])),
                            {"id": e["entity_id"], "x": x, "y": y, "w": span[0], "h": span[1], "dir": d["push"]})
        d["final"] = final
        mine = final[e["entity_id"]]
        hide = dict(final)
        hide.pop(e["entity_id"], None)
        self.apply_layout(target, hide, extra_rows=mine["y"] + mine["h"])
        slot = d["slot"]
        slot.animate(120, "out", x=mine["x"] * SPAN_W, y=mine["y"] * SPAN_H)

    def drag_release(self, tv):
        d = getattr(self, "drag", None)
        self.drag = None
        if not d or d["tv"] is not tv or not d["lifted"]:
            return True
        tv.lifted = False
        tv.zoom = 1.0
        target, e = d["target"], d["e"]
        room = target.room
        if d.get("final"):
            if room != d["room0"] and room != OTHER_ROOM:
                overrides = dict(self.m.panel.get("room_overrides") or {})
                overrides[e["entity_id"]] = room
                self.m.panel["room_overrides"] = overrides
                e["area"] = room
            self.m.save_layout(d["final"])
            self.persist()
        self.build()
        self.apply_category_state(animate=False)
        return True

    # -- the order of the rooms ----------------------------------------------------------------------------------------------------
    def attach_room_reorder_chip(self, chip):
        chip.on_press = lambda ev, chip=chip: self.reorder_press(chip, ev, "x")
        chip.on_move = lambda ev, chip=chip: self.reorder_move(chip, ev)
        chip.on_release = lambda ev, chip=chip: self.reorder_release(chip)

    def attach_room_reorder_section(self, row):
        row.interactive = True
        row.cursor = Qt.OpenHandCursor
        row.on_press = lambda ev, row=row: self.reorder_press(row, ev, "y")
        row.on_move = lambda ev, row=row: self.reorder_move(row, ev)
        row.on_release = lambda ev, row=row: self.reorder_release(row)

    def reorder_press(self, el, ev, axis):
        # a section is moved by its heading, the section itself is what moves
        moving = el.parent if axis == "y" else el
        self.reorder = {"el": el, "moving": moving, "axis": axis, "start": ev.gx if axis == "x" else ev.gy,
                        "dragging": False, "grab": 0.0}
        return True

    def reorder_move(self, el, ev):
        r = getattr(self, "reorder", None)
        if not r or r["el"] is not el:
            return True
        x = r["axis"] == "x"
        p = ev.gx if x else ev.gy
        moving = r["moving"]
        container = moving.parent
        siblings = [c for c in container.children if c is not moving and getattr(c, "key", None) is not None
                    and getattr(c, "key") not in ("", OTHER_ROOM)] if x else \
                   [c for c in container.children if c is not moving and getattr(c, "room", None) not in (None, OTHER_ROOM)]
        if not r["dragging"]:
            if abs(p - r["start"]) < 8:
                return True
            r["dragging"] = True
            pos = moving.x if x else moving.y
            r["grab"] = (self.content_axis(container, ev, x)) - pos
        cur = self.content_axis(container, ev, x)
        new = cur - r["grab"]
        if x:
            moving.x = new
        else:
            moving.y = new
        mid = (moving.x + moving.w / 2) if x else (moving.y + moving.h / 2)
        for other in siblings:
            omid = (other.x + other.w / 2) if x else (other.y + other.h / 2)
            idx_m, idx_o = container.children.index(moving), container.children.index(other)
            if idx_m > idx_o and mid < omid:
                self.swap_in(container, moving, other, x, before=True, new=new)
                break
            if idx_m < idx_o and mid > omid:
                self.swap_in(container, moving, other, x, before=False, new=new)
                break
        container.changed()
        return True

    def content_axis(self, container, ev, x):
        lx, ly = container.to_local(ev.gx, ev.gy)
        return lx if x else ly

    def swap_in(self, container, moving, other, x, before, new):
        """The dragged one takes the other's place: the others slide to make room."""
        kids = container.children
        kids.remove(moving)
        i = kids.index(other)
        kids.insert(i if before else i + 1, moving)
        # re-place everything but the one being held
        pos = 0.0
        gap = 10 if x else 18
        ordered = [c for c in kids if self._orderable(c, x)]
        for c in ordered:
            size = c.w if x else c.h
            if c is not moving:
                c.animate(160, "out", **({"x": pos} if x else {"y": pos}))
            pos += size + gap
        if not x:
            pass
        container.changed()

    @staticmethod
    def _orderable(c, x):
        if x:
            return getattr(c, "text", None) is not None or hasattr(c, "key")
        return getattr(c, "room", None) is not None

    def reorder_release(self, el):
        r = getattr(self, "reorder", None)
        self.reorder = None
        if not r or not r["dragging"]:
            return True
        container = r["moving"].parent
        x = r["axis"] == "x"
        shown = [c.key for c in container.children if getattr(c, "key", None) not in (None, "", OTHER_ROOM)] if x else \
                [c.room for c in container.children if getattr(c, "room", None) not in (None, OTHER_ROOM)]
        full = [k for k in self.m.room_names() if k != OTHER_ROOM]
        it = iter(shown)
        self.m.panel["room_order"] = [next(it) if k in shown else k for k in full]
        self.persist()
        self.build()
        self.apply_category_state(animate=False)
        return True
