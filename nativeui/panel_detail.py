"""The detail card opened from a tile of the tray panel (panel.py): laid over the tiles, fitted to the panel, closed again."""

from PySide6.QtCore import QPointF, QRectF, Qt

from . import render, ui
from . import controls, style
from .detail import CARD_W
from .ui import ScrollView, View

FLYOUT_ZOOM = 0.5


# Details fit inside the panel's existing bounds. State updates and navigation never resize the glass.
DETAIL_SCALE = 1 / FLYOUT_ZOOM
DETAIL_MARGIN = 14


DETAIL_MS = 320


class Backing(View):
    """What a detail stands on in the panel: the panel's shape, tinted so its words read over any desktop."""

    def __init__(self, x, y, w, h, panel):
        super().__init__(x, y, w, h)
        self.panel = panel

    def paint(self, p):
        p.setPen(Qt.NoPen)
        p.setBrush(style.readable_backing(self.scene.theme))
        p.drawPath(render.squircle(0, 0, self.w, self.h, self.panel.card_radius()))


class MorphBacking(Backing):
    """A source tile expands into the detail; text stays at its final size behind the moving clip."""
    def __init__(self, x, y, w, h, panel, origin):
        super().__init__(x, y, w, h, panel)
        self.origin = origin
        self.progress = 1.0

    def frame(self):
        t = max(0.0, min(1.0, self.progress))
        source = self.origin[0] if self.origin else QRectF(self.w * .01, self.h * .01, self.w * .98, self.h * .98)
        return QRectF(source.x() * (1-t), source.y() * (1-t),
                      source.width() + (self.w-source.width()) * t,
                      source.height() + (self.h-source.height()) * t)

    def paint_tree(self, p):
        if not self.visible:
            return
        t = max(0.0, min(1.0, self.progress))
        rect = self.frame()
        radius = min(32, rect.height() / 2) * (1-t) + self.panel.card_radius() * t
        p.save()
        p.translate(self.x, self.y)
        p.setClipPath(render.squircle(rect.x(), rect.y(), rect.width(), rect.height(), radius))
        opacity = p.opacity()
        if self.origin and not self.origin[1].isNull() and t < 1:
            p.setOpacity(opacity * max(0.0, 1-4*t))
            p.drawImage(rect, self.origin[1])
        p.setOpacity(opacity * t)
        p.setPen(Qt.NoPen)
        p.setBrush(style.readable_backing(self.scene.theme))
        p.drawPath(render.squircle(rect.x(), rect.y(), rect.width(), rect.height(), radius))
        for child in self.children:
            child.paint_tree(p)
        p.restore()

    def hit(self, x, y):
        got = super().hit(x, y)
        if got is not self and not self.frame().contains(QPointF(x-self.x, y-self.y)):
            return self if not self.no_hit else None
        return got


class PanelDetail:
    """The detail card opened from a tile of the tray panel (panel.py): laid over the tiles, fitted to the panel, closed again"""

    def popover(self, tv, tile):
        """A hold or a right click: the tile's detail, over the panel."""
        self.open_detail(tile["id"], source=tv)

    # -- a tile's detail, over the tiles ------------------------------------------------------------------------------
    def open_detail(self, tile_id, source=None):
        if self.detail_view is None and getattr(self, "closing_detail", None) is None:
            if source is None:
                candidates = self.home.tile_views() if self.home else self.tiles_views
                source = next((v for v in candidates if v.tile["id"] == tile_id), None)
            self.detail_origin = None
            if source is not None:
                x, y, k = source.in_scene()
                rect = QRectF(x, y, source.w * k, source.h * k)
                image = self.grab().toImage()
                crop = QRectF(rect.x() * self.scale, rect.y() * self.scale,
                              rect.width() * self.scale, rect.height() * self.scale).toAlignedRect()
                self.detail_origin = (rect, image.copy(crop))
                self.detail_source_id = tile_id
                source.transition_hidden = True
        if not self.detail.open(tile_id):
            return
        opening = self.detail_view is None
        closing = getattr(self, "closing_detail", None)
        if closing is not None:
            self.detail_view = closing
            closing.no_hit = False
            self.closing_detail = None
        self.detail_k = DETAIL_SCALE
        self.layout_detail()
        if opening:
            # the tiles recede and the detail comes forward, as a capsule's devices do
            self.root.no_hit = True
            self.root.animate(DETAIL_MS, "spring", alpha=0.0, zoom=1.0, blur=0.0)
            v = self.detail_view
            if closing is None:
                v.alpha, v.zoom, v.blur, v.progress = 0.0, 1.0, 0.0, 0.0
            v.animate(DETAIL_MS, "spring", alpha=1.0, zoom=1.0, blur=0.0, progress=1.0)
            self.invalidate_glass()               # the liquid glass no longer blurs behind each tile

    def layout_detail(self):
        """(Re)build the detail over the tiles, and size the panel for it."""
        if self.detail.tile is None:
            return
        old = self.detail_view
        k, m = DETAIL_SCALE, DETAIL_MARGIN
        base_w, base_h = self.base_css or (self.css_w, self.css_h)
        room = max(1, base_h - 2 * m)
        k = min(getattr(self, "detail_k", k), k, max(1, base_w - 2 * m) / CARD_W,
                room / (72 + 150))
        content = self.detail.build(max_h=room / k, fit=True)
        # as large as fits, and no larger than it was while this device is shown: a new state (a longer
        # song title) does not make it jump
        k = self.detail_k = min(getattr(self, "detail_k", k), k, room / content.h,
                              max(1, base_w - 2 * m) / CARD_W)
        w, h = base_w, base_h
        overlay = MorphBacking(0, 0, w, h, self, getattr(self, "detail_origin", None))
        overlay.interactive = True                # the empty space around it goes back
        overlay.on_press = lambda e: True
        overlay.on_click = lambda e: self.close_detail()
        holder = ui.CachedView((w - CARD_W * k) / 2, m, CARD_W, content.h)
        holder.scale = k
        holder.interactive = True                 # but not the empty space inside it, nor a click that a
        holder.on_press = lambda e: True          # control in it (a slider) leaves unhandled
        holder.on_click = lambda e: self.detail_background_click(e)
        holder.add(content)
        overlay.add(holder)
        if old is not None:
            controls.preserve_controls(self, old, overlay)
            overlay.alpha, overlay.zoom, overlay.blur = old.alpha, old.zoom, old.blur
            overlay.progress = old.progress
            self.tweens.replace_view(old, overlay)
            self.layer.remove(old)
        candidates = self.home.tile_views() if self.home else self.tiles_views
        for tile in candidates:
            tile.transition_hidden = tile.tile["id"] == getattr(self, "detail_source_id", None)
        self.layer.add(overlay)
        self.detail_view = overlay
        self.detail_css = (w, h)
        if (w, h) != (self.css_w, self.css_h):
            self.set_css_size(w, h)
            self.request_size()
        controls.reattach_menu(self, overlay)
        self.request_paint()

    def detail_background_click(self, event):
        target = self.press_view
        while target is not None and target is not self.detail_view:
            if target.interactive and type(target) not in (View, ui.CachedView) and not isinstance(target, ScrollView):
                return True
            target = target.parent
        self.close_detail()
        return True

    def close_detail(self, animate=True):
        v = self.detail_view
        if v is None:
            return
        self.detail.tile = None
        self.detail_view = None
        self.closing_detail = v
        self.root.no_hit = False
        self.close_popup()

        def gone():
            if self.detail_view is None:
                candidates = self.home.tile_views() if self.home else self.tiles_views
                for tile in candidates:
                    tile.transition_hidden = False
            if getattr(self, "closing_detail", None) is v:
                self.closing_detail = None
            self.layer.remove(v)
            if self.detail_view is None and self.base_css and self.base_css != (self.css_w, self.css_h):
                self.set_css_size(*self.base_css)
                self.request_size()
            self.request_paint()
        if animate:
            v.no_hit = True
            v.animate(DETAIL_MS, "spring", alpha=0.0, zoom=1.0, blur=0.0, progress=0.0, done=gone)
            self.root.animate(DETAIL_MS, "spring", alpha=1.0, zoom=1.0, blur=0.0)
        else:
            v.stop_animation()
            self.root.stop_animation()
            self.root.alpha, self.root.zoom, self.root.blur = 1.0, 1.0, 0.0
            gone()
        self.invalidate_glass()

    def _area_of(self, entity_id):
        """The room a device is in, as the Home panel knows it ("" in the tile panel)."""
        e = self.model.entity_by_id(entity_id)
        return (e or {}).get("area") or ""

    def _in_detail(self, view):
        v = view
        while v is not None:
            if v is self.detail_view:
                return True
            v = v.parent
        return False
