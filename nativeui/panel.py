"""The tray panel: the widget's tiles beside the taskbar, or the Home view.

the Api drives it (overlay.py): `arm()` while it is placed but hidden (size, data, the
backdrop), `flyout_enter()` to bring it in, `flyout_leave()` to send it away. It slides up from its tray
corner and back down, the glass and the card as one, keeping its resting size.
"""
import threading
import time
import traceback

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QCursor, QImage, QPainter

from . import dcomp, render, screens, ui
from .actions import TileActions
from . import controls, style
from .detail import CARD_W, DetailContent
from .homemodel import HomeModel
from .overlay import OverlayScene, create_overlay
from .ui import ScrollView, TileView, View


PAD, CELL_W, CELL_H, GAP = 14, 152, 146, 14
GRID_ROWS = 3                          # rows of tiles shown; more scroll
HOLD_MS, HOLD_SLOP = 420, 8
FLYOUT_ZOOM = 0.5
# The panel takes about the same share of any monitor: drawn at FLYOUT_ZOOM on one whose shorter side is
# FIT_SIDE logical px (1080p), larger or smaller by that side on others, within FIT_RANGE; and never larger
# than the work area holds, less FIT_MARGIN physical px all round.
FIT_SIDE = 1080
FIT_RANGE = (0.8, 1.5)
FIT_MARGIN = 12
# Like the system's own flyouts: it slides in from behind the bottom edge and out again, with no fade.
ENTER_CURVE, LEAVE_CURVE = (0.2, 0.75, 0.25, 1.0), (0.5, 0.0, 1.0, 1.0)
ENTER_MS, LEAVE_MS = 250, 150
BG_VEIL = {"dark": (12, 14, 18, 0.26), "light": (255, 255, 255, 0.2)}
# Details fit inside the panel's existing bounds. State updates and navigation never resize the glass.
DETAIL_SCALE = 1 / FLYOUT_ZOOM
DETAIL_MARGIN = 14
DETAIL_MAX_H = 900                     # as tall as the Home panel
DETAIL_MS = 320


class PanelScene(OverlayScene):
    def __init__(self, facade, api):
        super().__init__(facade, api, "flyout")
        self.prefs = api._prefs()
        self.states = {}
        self.model = HomeModel()
        self.actions = TileActions(api, lambda: self.states, self.optimistic)
        self.zoom_css = FLYOUT_ZOOM
        self.sampling = "live"
        self.seq = 0
        self.mode = "grid"
        self.tiles_views = []
        self.grid_scroll = None
        self._bg_made = None                 # (what it was made from, the picture): see make_bg
        self._card_picture = None
        self.arm_event = None
        self.moving = False
        self._sliding = None                 # ("enter" or "leave", ms) while the compositor moves the panel
        self._compositor_resting = False
        self._compositor_geometry = None
        self._compositor_background = None
        self._compositor_slider = None
        self._slide_timer = QTimer(self)
        self._slide_timer.setSingleShot(True)
        self._slide_deadline = 0.0
        self._slide_timer.timeout.connect(self._finish_slide_if_due)
        self.hold_timer = QTimer(self)
        self.hold_timer.setSingleShot(True)
        self.hold_timer.timeout.connect(self._held)
        self.hold = None
        self.anim_alpha, self.anim_zoom = 0.0, 1.0
        self.anim_dy = self.css_h
        self._flyout_picture = None
        self._flyout_glass = None
        self._deferred_glass = False
        self.home = None
        # The detail shown over the tiles (open_detail), and the panel's own size without it.
        self.detail = DetailContent(self, lambda: self.prefs, self.states, self.layout_detail,
                                    on_close=self.close_detail, area_of=self._area_of)
        self.detail_view = None
        self.base_css = None
        self.configure()
        self.retheme()
        self.rebuild()                       # so it has its size before it is ever shown
        threading.Thread(target=self._load_states, daemon=True).start()

    # -- preferences ---------------------------------------------------------------------------------
    def configure(self):
        prefs = self.prefs
        panel = prefs.get("panel") or {}
        theme = prefs.get("panel_theme", "follow")
        self.theme_raw = prefs.get("theme", "auto") if theme == "follow" else theme
        self.style = prefs.get("glass_style", "classic")
        if self.style not in ("classic", "liquid", "windows"):
            self.style = "classic"
        self.language = prefs.get("language", "zh-TW")
        self.liquid_level = prefs.get("liquid_blur", 0)
        self.system_glass = (prefs.get("system_glass_active") or {}).get("flyout") is True
        self.mode = "home" if panel.get("mode") == "home" else "grid"
        self.model.panel = panel if panel else self.model.panel

    def _look(self):
        """What, when it changes, the panel is themed, measured and given its glass again for."""
        panel = self.prefs.get("panel") or {}
        return (self.theme_raw, self.style, self.language, self.liquid_level, self.system_glass, self.mode,
                panel.get("bg_image"), panel.get("bg_blur"))

    def apply_prefs(self, prefs):
        before = self._look()
        self.prefs = prefs
        self.configure()
        if self._look() != before:
            entering = self._sliding is not None and self._sliding[0] in ("enter", "handoff")
            self._cancel_compositor()
            if entering and self.isVisible():
                self.anim_alpha, self.anim_dy = 1.0, 0.0
            self._card_picture = None
            self._content = None
            self._content_dirty = True
            self.retheme()
            self.update_metrics()
            self.invalidate_glass()
            self.make_bg()
        self.rebuild(keep_scroll=True)

    def themed(self):
        self.rebuild(keep_scroll=True)

    def card_radius(self):
        return self.t["radius_panel"]

    def paint_card(self, p):
        key = (self.pw, self.ph, self.scale, self.css_w, self.css_h, self.theme, self.style, id(self.t))
        if self._card_picture is None or self._card_picture[0] != key:
            image = QImage(self.pw, self.ph, QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.transparent)
            painter = QPainter(image)
            painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
            painter.scale(self.scale, self.scale)
            try:
                render.draw_card_bg(painter, self.css_w, self.css_h, self.t, self.style, self.theme)
            finally:
                painter.end()
            self._card_picture = (key, image)
        p.drawImage(QRectF(0, 0, self.pw / self.scale, self.ph / self.scale), self._card_picture[1])

    # -- states -----------------------------------------------------------------------------------------
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

    def push_states(self, items):
        changed = []
        for entity, state in items:
            if self.states.get(entity) != state:
                changed.append(entity)
            self.states[entity] = state
            self.model.states[entity] = state
        for v in self.tiles_views:
            if v.tile["entity"] in changed:
                v.set_state(self.states.get(v.tile["entity"]))
        if self.home is not None and changed:
            self.home.states_changed(changed)
        if self.detail_view is not None and self.detail.concerns([(e, None) for e in changed]):
            self.layout_detail()

    def optimistic(self, entity, patch):
        st = self.states.get(entity)
        if st is not None:
            self.push_states([(entity, dict(st, **patch))])

    # -- what it shows -----------------------------------------------------------------------------------------
    def panel_tiles(self):
        panel = self.prefs.get("panel") or {}
        if isinstance(panel.get("tiles"), list):
            return panel["tiles"]
        seen, out = set(), []
        for w in self.prefs.get("widgets", []):
            for t in w.get("tiles", []):
                if t.get("entity") not in seen:
                    seen.add(t.get("entity"))
                    out.append(t)
        return out

    def rebuild(self, keep_scroll=False):
        scroll = self.grid_scroll.offset if (keep_scroll and self.grid_scroll is not None) else 0.0
        self.root.clear()
        # the detail's own fields stay (its edit panel may be in the middle of a name)
        self.fields[:] = [f for f in self.fields if self._in_detail(f)]
        self.tiles_views = []
        self.grid_scroll = None
        self.home = None
        if self.mode == "home":
            from .homeview import HomeView
            self.home = HomeView(self)
            self.root.add(self.home)
            self.set_css_size(self.home.w, self.home.h)
        else:
            self.build_grid(scroll)
        self.base_css = (self.css_w, self.css_h)
        if self.detail_view is not None:
            if self.detail.prefs_changed():
                self.layout_detail()
            else:
                self.set_css_size(*self.detail_css)
        self.request_size()
        self.request_paint()

    def build_grid(self, scroll):
        tiles = self.panel_tiles()
        n = max(1, len(tiles))
        cols = max(1, min(4, n))
        rows_total = -(-n // cols)
        rows_shown = min(GRID_ROWS, rows_total)
        w = cols * CELL_W + (cols - 1) * GAP + 2 * PAD
        view_h = rows_shown * CELL_H + (rows_shown - 1) * GAP
        h = view_h + 2 * PAD
        sv = ScrollView(PAD, PAD, w - 2 * PAD, view_h, fade=0)   # (each tile's own glass would not fade)
        sv.row = CELL_H + GAP
        content_h = rows_total * CELL_H + (rows_total - 1) * GAP
        sv.content.w, sv.content.h = w - 2 * PAD, content_h
        for i, tile in enumerate(tiles):
            tv = TileView(tile, self.states.get(tile["entity"]), "small", (i % cols) * (CELL_W + GAP),
                          (i // cols) * (CELL_H + GAP), CELL_W, CELL_H)
            self.wire_tile(tv, tile)
            sv.add(tv)
            self.tiles_views.append(tv)
        sv.on_wheel = lambda e, delta, sv=sv: self._grid_wheel(sv, delta)
        self.root.add(sv)
        self.grid_scroll = sv
        sv.scroll_to(scroll)
        self.set_css_size(w, h)

    def _grid_wheel(self, sv, delta):
        if sv.max_offset() <= 0:
            return False
        row = sv.row
        target = (round(sv.offset / row) - (1 if delta > 0 else -1)) * row     # a row at a time
        sv.scroll_to(max(0, min(sv.max_offset(), target)))
        return True

    # -- tiles: the tap, the hold, the right click ----------------------------------------------------------------
    def wire_tile(self, tv, tile):
        tv.on_press = lambda e, tv=tv: self._tile_press(tv, tile, e)
        tv.on_move = lambda e, tv=tv: self._tile_move(tv, e)
        tv.on_release = lambda e, tv=tv: self._tile_release(tv)
        tv.on_click = lambda e, tv=tv: self._tile_click(tv, tile, e)

    def _tile_press(self, tv, tile, e):
        if e.button == Qt.RightButton:
            return True
        tv.zoom = 0.95 if (render.has_detail_on_hold(tile["domain"]) or render.is_readonly(tile["domain"])) else 0.96
        tv.changed()
        self.hold = {"view": tv, "tile": tile, "at": (e.gx, e.gy), "fired": False}
        if render.has_detail_on_hold(tile["domain"]) or render.is_readonly(tile["domain"]):
            self.hold_timer.start(HOLD_MS)
        return True

    def _tile_move(self, tv, e):
        if self.hold and (abs(e.gx - self.hold["at"][0]) > HOLD_SLOP or abs(e.gy - self.hold["at"][1]) > HOLD_SLOP):
            self.hold_timer.stop()
        return True

    def _tile_release(self, tv):
        tv.zoom = 1.0
        tv.changed()
        self.hold_timer.stop()
        return True

    def _held(self):
        if self.hold and not self.hold["fired"]:
            self.hold["fired"] = True
            self.popover(self.hold["view"], self.hold["tile"])

    def _tile_click(self, tv, tile, e):
        if e.button == Qt.RightButton:
            self.popover(tv, tile)
            return True
        if self.hold and self.hold.get("fired"):
            self.hold = None
            return True
        self.hold = None
        sign = self.mini_hit(tv, e.x, e.y)
        if sign:
            self.actions.climate_step(tile, sign)
        elif tv.form == "bar" and not render.bar_icon_rect(tv.w, tv.h).contains(QPointF(e.x, e.y)):
            self.popover(tv, tile)
        elif not render.is_readonly(tile["domain"]):
            self.actions.quick_action(tile, flash=lambda: self.flash(tv))
        return True

    @staticmethod
    def mini_hit(tv, x, y):
        st = tv.state
        if tv.tile["domain"] != "climate" or not st or st.get("state") == "off":
            return 0
        if tv.form == "small" and not tv.hovered:
            return 0
        zoom = render.BIG_ZOOM if tv.form == "big" else 1.0
        for rect, sign in render.mini_buttons(tv.form, tv.w / zoom, tv.h / zoom):
            if rect.contains(QPointF(x / zoom, y / zoom)):
                return sign
        return 0

    def flash(self, tv):
        t0 = time.monotonic()

        def step():
            k = (time.monotonic() - t0) / 0.6
            tv.flash = max(0.0, 1 - k)
            tv.invalidate()
            if k < 1:
                QTimer.singleShot(33, step)
        step()

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

    # -- the glass behind the card ------------------------------------------------------------------------------------
    def glass_tiles(self):
        out = []
        if self.grid_scroll is None or self.detail_view is not None:
            return out
        s = self.scale
        sv = self.grid_scroll
        for v in self.tiles_views:
            x, y = v.abs_pos()
            if y >= PAD - 0.5 and y + v.h <= PAD + sv.h + 0.5:
                out.append((round(x * s), round(y * s), round(v.w * s), round(v.h * s), round(self.t["radius_tile"] * s)))
        return out

    def custom_bg(self):
        panel = self.prefs.get("panel") or {}
        return bool(panel.get("bg_image")) and not self.system_glass

    def make_bg(self):
        """The panel's own picture, blurred, in place of the desktop's glass."""
        if not self.custom_bg():
            self._bg_made = None
            self.glass = None
            self.invalidate_glass()
            return
        panel = self.prefs.get("panel") or {}
        path = self.api._panel_bg_path()
        if not path or self.pw <= 1:
            return
        blur = (28 if panel.get("bg_blur") is None else panel["bg_blur"]) * self.dpi * self.zoom_css
        # Decoding and blurring the picture takes tens of ms, and the panel is measured again at every
        # rebuild: the same picture for the same size is made once.
        made_from = (path, panel.get("bg_image"), blur, self.pw, self.ph, self.theme)
        if self._bg_made is not None and self._bg_made[0] == made_from:
            self.latest = self._bg_made[1]
            self._on_glass_custom()
            return
        from PIL import Image, ImageFilter
        over = int(2 * blur) + 1
        w, h = self.pw, self.ph
        try:
            with Image.open(path) as im:
                im = im.convert("RGB")
                k = max((w + 2 * over) / im.width, (h + 2 * over) / im.height)
                big = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.BILINEAR)
        except Exception:
            return
        left, top = (big.width - w) // 2, (big.height - h) // 2
        canvas = big.crop((left, top, left + w, top + h)) if blur <= 0 else \
            big.filter(ImageFilter.GaussianBlur(blur)).crop((left, top, left + w, top + h))
        veil = BG_VEIL["dark" if self.theme == "dark" else "light"]
        overlay = Image.new("RGB", canvas.size, veil[:3])
        canvas = Image.blend(canvas, overlay, veil[3])
        qimg = QImage(canvas.convert("RGBA").tobytes(), w, h, w * 4, QImage.Format_RGBA8888).copy()
        self._bg_made = (made_from, qimg)
        self.latest = qimg
        self._on_glass_custom()

    def _on_glass_custom(self):
        saved = self.style
        self.style = "classic"                  # stretched and cut to the card: no lens on a picture
        try:
            self._on_glass()
        finally:
            self.style = saved

    def start_glass(self):
        if self.custom_bg():
            return
        super().start_glass()

    def update_metrics(self):
        self.zoom_css = FLYOUT_ZOOM * self.fit()
        super().update_metrics()
        if self.custom_bg():
            self.make_bg()

    def monitor(self):
        """The monitor the panel opens on: the one whose tray was clicked (Api._flyout_anchor), else the
        one under the pointer."""
        anchor = getattr(self.api, "_flyout_anchor", None)
        work = anchor[0] if anchor else None
        if work:
            return screens.monitor_at((work[0] + work[2]) / 2, (work[1] + work[3]) / 2)
        pos = QCursor.pos()
        ratio = self.devicePixelRatioF() or 1.0
        return screens.monitor_at(pos.x() * ratio, pos.y() * ratio)

    def fit(self):
        """How much larger (or smaller) than at FLYOUT_ZOOM the panel is drawn on its monitor."""
        mon = self.monitor()
        if mon is None:
            return 1.0
        k = max(FIT_RANGE[0], min(FIT_RANGE[1], mon.logical_short_side() / FIT_SIDE))
        # A full Home panel on a small screen (or a tall one turned on its side) still fits.
        l, t, r, b = mon.work
        css_w, css_h = self.css_w * FLYOUT_ZOOM * mon.scale, self.css_h * FLYOUT_ZOOM * mon.scale
        if css_w > 1 and css_h > 1:
            k = min(k, (r - l - 2 * FIT_MARGIN) / css_w, (b - t - 2 * FIT_MARGIN) / css_h)
        return max(0.3, k)

    def display_changed(self):
        """A monitor was added, removed or rescaled: measured again, and put at its corner again."""
        self.request_size()

    # -- coming in and going away --------------------------------------------------------------------------------------
    def request_size(self, sync=False):
        self.update_metrics()
        # The window is that size at once; Api.resize_flyout_window then puts it at its tray corner. Until
        # then it would be Qt's default, many times too big, and open showing that.
        ratio = self.devicePixelRatioF() or 1.0
        self.resize(max(1, round(self.pw / ratio)), max(1, round(self.ph / ratio)))
        self.seq += 1
        seq, pw, ph = self.seq, self.pw, self.ph
        if sync:
            self.api.resize_flyout_window(pw, ph, seq)
        else:
            threading.Thread(target=lambda: self.api.resize_flyout_window(pw, ph, seq), daemon=True).start()

    def origin(self):
        anchor = getattr(self.api, "_flyout_anchor", None)
        near_right = anchor[1] if anchor else True
        return (1.0 if near_right else 0.0, 1.0)

    def arm(self):
        """Placed but hidden: size itself, fetch its data and take its backdrop, held out of sight, then say so."""
        if not self.isVisible() or self.anim_alpha <= 0:
            self.anim_alpha, self.anim_dy = 0.0, self.css_h
        self.anim_zoom = 1.0
        self.anim_origin = self.origin()
        self.tweens.cancel(self)
        self.moving = False
        if self.mode == "home":
            if self.home is None:
                self.rebuild()
            self.request_size(sync=True)         # it is put at its tray corner before it is shown
            self.home.load()
        else:
            self.rebuild(keep_scroll=True)
            self.request_size(sync=True)
        self.start_glass()
        if self.anim_alpha <= 0:
            self.anim_dy = self.css_h       # final fitted height, completely behind the bottom edge
        if self.custom_bg():
            self.make_bg()
            threading.Thread(target=self.api.backdrop_armed, daemon=True).start()
            return
        # What it showed last time is kept (same size, same place) and stands in for a moment; only a window with
        # no picture yet waits for one.
        patient = 0.3 if self.glass is None else 0.05
        self.invalidate_glass()
        done = threading.Event()
        self.arm_event = done

        def wait():
            done.wait(patient)
            self.api.backdrop_armed()
        threading.Thread(target=wait, daemon=True).start()

    def glass_changed(self):
        super().glass_changed()
        if self.arm_event is not None:
            self.arm_event.set()
            self.arm_event = None

    def shown_up(self):
        self.start_glass()

    def _vsync_motion(self):
        """The panel's coming and going is paced by the desktop's compositions; everything else keeps its clock."""
        self.tweens.timer.vsync = True

    # -- the slide done by the desktop's compositor (nativeui/dcomp.py) ---------------------------------------------

    def _cancel_compositor(self):
        """Discard the previous presentation before changing its appearance or showing again."""
        self._slide_timer.stop()
        if self._sliding is not None or self._compositor_resting:
            slider = self._compositor_slider or dcomp.slider()
            if slider is not None:
                slider.hide()
        self._sliding = None
        self._compositor_resting = False
        self._compositor_geometry = None
        self._compositor_slider = None
        self._compositor_capture = None
        self._compositor_epoch += 1
        self._compositor_raw = None
        self._flyout_picture = self._flyout_glass = None
        self._deferred_glass = False
        self.moving = False
        self.tweens.cancel(self)

    def prepare_for_show(self):
        if (self._sliding is not None and self._sliding[0] in ("enter", "leave")
                and self._compositor_slider is not None and self._compositor_slider.shown):
            return True
        self._cancel_compositor()
        self.anim_alpha, self.anim_dy = 0.0, self.css_h
        self.anim_zoom = 1.0
        self.repaint()

    def hideEvent(self, event):
        self._cancel_compositor()
        super().hideEvent(event)

    def stop(self):
        self._cancel_compositor()
        super().stop()

    def _slide_layers(self, size, at=None):
        """Separate desktop glass and foreground pictures in physical window pixels."""
        def picture(image):
            image = image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(1.0)          # (its pixels are the window's, whatever scale it was made at)
            if (image.width(), image.height()) != size:
                # (the window can be a pixel larger than what is drawn: it is drawn from the corner, not stretched)
                canvas = QImage(size[0], size[1], QImage.Format_ARGB32_Premultiplied)
                canvas.fill(Qt.transparent)
                painter = QPainter(canvas)
                painter.drawImage(0, 0, image)
                painter.end()
                image = canvas
            return image
        # self.glass is already cut to the resting card. It must never be the
        # stationary animation background: its old bottom corners would remain
        # visible inside the moving card even with a correct outer clip.
        source = self.latest if self.custom_bg() or not self._liquid_glass() else self.raw_latest
        if source is None:
            source = self.glass
        glass = None
        source_height = self.ph
        if (at is not None and (size[1] > self.ph or self._liquid_glass())
                and not self.custom_bg() and not self.system_glass):
            capture = getattr(self.api, "get_desktop_backdrop", None)
            try:
                shot = capture("flyout", None, size[0], size[1], at[0], at[1], 0) if capture else None
            except Exception:
                shot = None
            if shot and shot.get("blur_raw"):
                source = QImage(shot["blur_raw"], shot["blur_w"], shot["blur_h"],
                                shot["blur_w"] * 3, QImage.Format_RGB888).copy()
                source_height = size[1]
                self._compositor_background = ((*at, *size), source)
            else:
                cached = self._compositor_background
                if cached is not None and cached[0] == (*at, *size):
                    source, source_height = cached[1], size[1]
        if source is not None and not self.system_glass:
            glass = QImage(size[0], size[1], QImage.Format_ARGB32_Premultiplied)
            glass.fill(Qt.transparent)
            painter = QPainter(glass)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawImage(QRectF(0, 0, self.pw, source_height), source)
            if source_height < size[1]:
                # A capture may still be arming. Keep an opaque blurred continuation
                # until the screen edge instead of reusing the old rounded mask.
                painter.drawImage(QRectF(0, source_height, self.pw, size[1] - source_height), source,
                                  QRectF(0, source.height() - 1, source.width(), 1))
            painter.end()
        card = picture(self.content_image())
        return glass, card

    def _time_slide(self, milliseconds):
        self._slide_deadline = time.monotonic() + milliseconds / 1000
        self._slide_timer.start(milliseconds)

    def _finish_slide_if_due(self):
        remaining = self._slide_deadline - time.monotonic()
        if self._sliding is None:
            return
        if remaining > 0:
            self._slide_timer.start(max(1, int(remaining * 1000) + 1))
            return
        self._finish_slide()

    def _refresh_compositor_background(self):
        """Refresh screen pixels while retaining surfaces and the motion curve."""
        rect, slider = self._compositor_capture, self._compositor_slider
        if rect is None or slider is None or slider.material is None:
            return
        self._compositor_epoch += 1
        self._compositor_raw = None
        slider.pending_glass = None
        self._compositor_presented_at = time.monotonic()
        capture = getattr(self.api, "get_desktop_backdrop", None)
        try:
            shot = capture("flyout", None, rect[2], rect[3], rect[0], rect[1], 0) if capture else None
        except Exception:
            shot = None
        if shot and shot.get("blur_raw"):
            image = QImage(shot["blur_raw"], shot["blur_w"], shot["blur_h"],
                           shot["blur_w"] * 3, QImage.Format_RGB888).copy()
            self._compositor_background = (rect, image)
            self._compositor_presented_at = time.monotonic()
            slider.queue_glass(image)
        self.force.set()
        self.sample_now.set()

    def _reverse_compositor(self, entering):
        slider = self._compositor_slider
        kind = self._sliding
        if (kind is None or kind[0] not in ("enter", "leave")
                or slider is None or not slider.shown):
            return False
        desired = "enter" if entering else "leave"
        self._refresh_compositor_background()
        if kind[0] == desired:
            return True
        offset = slider.motion_offset()
        far = slider.size[1] + 24
        target = 0.0 if entering else far
        base = ENTER_MS if entering else LEAVE_MS
        duration = max(25, round(base * min(1, abs(target - offset) / far)))
        self._slide_timer.stop()
        slider.slide(offset, target, duration / 1000, ENTER_CURVE if entering else LEAVE_CURVE)
        self._sliding = (desired, duration)
        self._time_slide(duration + 30)
        return True

    def _compositor_slide(self, entering):
        """Slide the panel in or out by the compositor. False where that cannot be (the caller draws it itself)."""
        if self._reverse_compositor(entering):
            return True
        slider = None if self.system_glass else dcomp.slider()     # (a glass the desktop draws is not in a picture)
        hwnd = self.cache_hwnd()
        rect = dcomp.window_rect(hwnd) if hwnd else None
        if slider is None or rect is None or rect[2] < 2 or rect[3] < 2:
            return False
        self._finish_slide()                                        # one already going is taken to its end
        self._compositor_slider = slider
        self._compositor_resting = False
        try:
            monitor = screens.monitor_at(rect[0] + rect[2] / 2, rect[1] + rect[3] / 2)
            if monitor is not None:
                # Extend only to the work area's edge, leaving the taskbar uncovered.
                # The panel keeps its resting size throughout state updates.
                rect = (rect[0], rect[1], rect[2], max(rect[3], monitor.work[3] - rect[1]))
            glass, card = self._slide_layers((rect[2], rect[3]), at=rect[:2])
            radius = min(self.card_radius(), self.css_w / 2, self.css_h / 2) * self.scale
            outline = render.squircle(0, 0, self.css_w * self.scale, self.css_h * self.scale, radius)
            columns = dcomp.outline_columns([(p.x(), p.y()) for p in outline.toFillPolygon()],
                                            self.css_w * self.scale, self.css_h * self.scale, radius)
            far = rect[3] + 24                                      # behind the taskbar and the screen's edge
            material = None
            if glass is not None and self._liquid_glass() and not self.custom_bg():
                material = dict(size=(self.css_w * self.scale, self.css_h * self.scale), radius=radius,
                                level=self.liquid_level, scale=self.scale, tiles=self.glass_tiles())
            self.moving = True                                      # the glass sampler leaves the processor alone
            self._compositor_capture = rect if material is not None else None
            self._compositor_epoch += 1
            self._compositor_since = time.monotonic()
            self._compositor_presented_at = self._compositor_since
            self._compositor_raw = None
            self.sample_now.set()
            if entering:
                # A reused native window may still hold the previous resting
                # bitmap. Clear it before the moving compositor is shown.
                self.anim_alpha = 0.0
                self.repaint()
                slider.show(rect, glass, card, far, radius, above=hwnd, columns=columns, liquid=material)
                slider.slide(far, 0.0, ENTER_MS / 1000, ENTER_CURVE)
                self._sliding = ("enter", ENTER_MS)
            else:
                # Commit the helper and clear the native foreground before
                # waiting for a desktop frame: waiting between them doubles tint.
                slider.show(rect, glass, card, 0.0, radius, above=hwnd, columns=columns,
                            liquid=material, wait=False)
                self.anim_alpha = 0.0
                self.repaint()
                slider.slide(0.0, far, LEAVE_MS / 1000, LEAVE_CURVE)
                self._sliding = ("leave", LEAVE_MS)
        except Exception:
            import traceback
            dcomp.disable(traceback.format_exc())
            self._sliding = None
            self._compositor_capture = None
            self.moving = False
            return False
        self._time_slide(self._sliding[1] + 30)
        return True

    def _finish_slide(self):
        """Finish motion; live liquid glass keeps the same compositor beneath native controls."""
        kind = self._sliding
        if kind is None:
            return
        self._sliding = None
        if kind[0] != "enter":
            self._compositor_capture = None
            self._compositor_epoch += 1
            self._compositor_raw = None
            self.force.set()
        self._slide_timer.stop()
        slider = self._compositor_slider or dcomp.slider()
        if kind[0] == "enter":
            if slider is not None and slider.material is not None and self._compositor_capture is not None:
                self._compositor_resting = True
                self._compositor_geometry = self._resting_geometry()
                self.anim_alpha, self.anim_dy = 1.0, 0.0
                self._settled()
                self.repaint()
                slider.settle_glass(self.cache_hwnd())
                return
            self.anim_alpha, self.anim_dy = 1.0, 0.0
            self._settled()                                         # apply deferred glass before exposing the resting window
            self.repaint()                                          # under the helper, which goes once this is there
            if slider is not None:
                slider.next_composition()
                slider.fade_out(.060)
                self._sliding = ("handoff", 60)
                self._time_slide(75)
        else:
            if slider is not None:
                slider.hide()
            if kind[0] != "handoff":
                self._left()

    def flyout_enter(self):
        if self._compositor_slide(True):
            return
        self._vsync_motion()
        self._prepare_flyout_picture()
        self.anim_origin = self.origin()
        self.anim_zoom = 1.0
        self.moving = True                   # the glass sampler leaves the processor to the animation
        if self.anim_alpha <= 0.01:
            self.anim_dy = self.css_h        # (a window already coming in or going away is taken from where it is)
        self.anim_alpha = 1.0
        self.tweens.animate(self, {"anim_dy": 0.0}, ENTER_MS, ENTER_CURVE, self._settled)

    def flyout_leave(self):
        if self._compositor_slide(False):
            return
        self._vsync_motion()
        self._prepare_flyout_picture()
        self.moving = True
        self.tweens.animate(self, {"anim_dy": self.css_h}, LEAVE_MS, LEAVE_CURVE, self._left)

    def _settled(self):
        self.moving = False
        self._flyout_picture = None
        self._flyout_glass = None
        if self._deferred_glass:
            self._deferred_glass = False
            super()._on_glass()
        self.request_paint()
        self.sample_now.set()

    def _left(self):
        self.moving = False
        self._flyout_picture = None
        self._flyout_glass = None
        self.close_detail(animate=False)          # the next opening shows the tiles
        if self.home is not None:
            self.model.reset()

    def _prepare_flyout_picture(self):
        """Cache foreground separately: desktop sampling stays at its original screen coordinates."""
        if self._flyout_picture is not None:
            return
        glass, picture = self._slide_layers((self.pw, self.ph))
        self._flyout_picture = picture
        self._flyout_glass = glass

    def _on_glass(self):
        held = self._compositor_raw
        if held is not None and self._compositor_capture is not None:
            self.glass_queued.clear()
            self._compositor_raw = None
            if (held[0] == self._compositor_capture and held[2] == self._compositor_epoch
                    and held[3] >= self._compositor_presented_at):
                self._compositor_presented_at = held[3]
                if isinstance(held[1], QImage):       # (a picture kept on the GPU has nothing to keep)
                    self._compositor_background = (held[0], held[1])
                slider = self._compositor_slider or dcomp.slider()
                if slider is not None and slider.material is not None:
                    slider.queue_glass(held[1])
            return
        if getattr(self, "moving", False):
            self.glass_queued.clear()
            self._deferred_glass = True
            return
        super()._on_glass()

    def _paint_now(self):
        self._paint_pending = False
        for field in self.fields:
            field.place()
        if self._compositor_resting:
            self._sync_resting_glass()
        if getattr(self, "moving", False) and self._flyout_picture is not None:
            # QWidget.update merges frames on Windows; this short cached transition follows the timer.
            self.repaint()
        else:
            self.update()

    def paintEvent(self, event):
        if self._compositor_resting:
            # Draw only the foreground over the unchanged compositor material.
            # Native editors, caret, menus and state updates remain native.
            glass = self.glass
            self.glass = None
            try:
                return super().paintEvent(event)
            finally:
                self.glass = glass
        picture = self._flyout_picture
        if picture is None or not self.moving:
            return super().paintEvent(event)
        painter = QPainter(self)
        painter.setOpacity(self.fade_alpha * self.anim_alpha)
        ratio = self.devicePixelRatioF() or 1.0
        # Moved by whole physical pixels: a fraction of one makes every frame resample the picture, which softens
        # the words while it moves and sharpens them where it stops, and the tail of the curve crawls.
        dy = round(self.anim_dy * self.scale)
        painter.save()
        painter.scale(self.scale / ratio, self.scale / ratio)
        painter.setClipPath(render.squircle(0, dy / self.scale, self.css_w, self.css_h, self.card_radius()),
                            Qt.ReplaceClip)
        painter.scale(ratio / self.scale, ratio / self.scale)
        if self._flyout_glass is not None:
            painter.drawImage(QRectF(0, 0, self.pw / ratio, self.ph / ratio), self._flyout_glass)
        painter.translate(0, dy / ratio)
        painter.drawImage(QRectF(0, 0, self.pw / ratio, self.ph / ratio), picture)
        painter.restore()
        painter.end()

    def _resting_geometry(self):
        return (dcomp.window_rect(self.cache_hwnd()), self.css_w, self.css_h, self.scale, self.card_radius())

    def _sync_resting_glass(self):
        slider = self._compositor_slider or dcomp.slider()
        if slider is None or slider.material is None:
            return
        geometry = self._resting_geometry()
        if geometry != self._compositor_geometry:
            rect = geometry[0]
            if rect is None:
                return
            monitor = screens.monitor_at(rect[0] + rect[2] / 2, rect[1] + rect[3] / 2)
            if monitor is not None:
                rect = (*rect[:3], max(rect[3], monitor.work[3] - rect[1]))
            glass, card = self._slide_layers(rect[2:], at=rect[:2])
            radius = min(self.card_radius(), self.css_w / 2, self.css_h / 2) * self.scale
            outline = render.squircle(0, 0, self.css_w * self.scale, self.css_h * self.scale, radius)
            columns = dcomp.outline_columns([(p.x(), p.y()) for p in outline.toFillPolygon()],
                                           self.css_w * self.scale, self.css_h * self.scale, radius)
            slider.show(rect, glass, card, 0, radius, above=self.cache_hwnd(), columns=columns,
                        liquid=dict(size=(self.css_w * self.scale, self.css_h * self.scale), radius=radius,
                                    level=self.liquid_level, scale=self.scale, tiles=self.glass_tiles()))
            slider.settle_glass(self.cache_hwnd())
            self._compositor_capture = rect
            self._compositor_epoch += 1
            self._compositor_presented_at = time.monotonic()
            self._compositor_geometry = geometry
            self.force.set()
        slider.material.tiles = list(self.glass_tiles())[:64]

    def moveEvent(self, event):
        super().moveEvent(event)
        if getattr(self, '_compositor_resting', False):
            self.request_paint(content=False)

    def escape(self):
        if self.popup is not None:
            self.close_popup()
            return
        if self.detail_view is None:
            return
        if self.detail.edit:
            self.detail.set_edit(False)
        else:
            self.close_detail()



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


def create_panel(api):
    return create_overlay(api, "HA Widgets Panel", lambda facade: PanelScene(facade, api), 200, 200)
