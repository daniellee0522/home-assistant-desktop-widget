"""The tray panel: the widget's tiles beside the taskbar, or the Home view.

main.py drives it (overlay.py): `arm()` while it is placed but hidden (size, data, the
backdrop), `flyout_enter()` to bring it in, `flyout_leave()` to send it away. It scales out of its tray
corner and back, never past its resting size, the glass and the card as one.
"""
import threading
import time
import traceback

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QCursor, QImage

from . import render, screens
from .actions import TileActions
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
ENTER_CURVE, LEAVE_CURVE = (0.12, 0.9, 0.2, 1.0), (0.5, 0.0, 0.9, 0.35)
BG_VEIL = {"dark": (12, 14, 18, 0.26), "light": (255, 255, 255, 0.2)}
# A tile's detail is shown over the panel's own tiles, as a capsule's devices are: at the size of the detail
# card beside a widget at 100 % (its units are DETAIL_SCALE of the panel's), with DETAIL_MARGIN around it.
# A panel too small for it (a row or two of tiles) grows while it is shown, up to DETAIL_MAX_H.
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
        self.arm_event = None
        self.hold_timer = QTimer(self)
        self.hold_timer.setSingleShot(True)
        self.hold_timer.timeout.connect(self._held)
        self.hold = None
        self.anim_alpha, self.anim_zoom = 0.0, 0.86          # until it is asked to come in
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
        render.draw_card_bg(p, self.css_w, self.css_h, self.t, self.style, self.theme)

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
        sv = ScrollView(PAD, PAD, w - 2 * PAD, view_h)
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
        self.open_detail(tile["id"])

    # -- a tile's detail, over the tiles ------------------------------------------------------------------------------
    def open_detail(self, tile_id):
        if not self.detail.open(tile_id):
            return
        opening = self.detail_view is None
        self.layout_detail()
        if opening:
            # the tiles recede and the detail comes forward, as a capsule's devices do
            self.root.no_hit = True
            self.root.animate(DETAIL_MS, "out", alpha=0.0, zoom=0.94, blur=10.0)
            v = self.detail_view
            v.alpha, v.zoom, v.blur = 0.0, 1.06, 10.0
            v.animate(DETAIL_MS, "out", alpha=1.0, zoom=1.0, blur=0.0)
            self.invalidate_glass()               # the liquid glass no longer blurs behind each tile

    def layout_detail(self):
        """(Re)build the detail over the tiles, and size the panel for it."""
        if self.detail.tile is None:
            return
        old = self.detail_view
        k, m = DETAIL_SCALE, DETAIL_MARGIN
        base_w, base_h = self.base_css or (self.css_w, self.css_h)
        content = self.detail.build(max_h=(max(base_h, DETAIL_MAX_H) - 2 * m) / k)
        w = max(base_w, CARD_W * k + 2 * m)
        h = max(base_h, content.h * k + 2 * m)
        overlay = View(0, 0, w, h)
        overlay.interactive = True                # the empty space around it goes back
        overlay.on_press = lambda e: True
        overlay.on_click = lambda e: self.close_detail()
        holder = View((w - CARD_W * k) / 2, m, CARD_W, content.h)
        holder.scale = k
        holder.interactive = True                 # but not the empty space inside it, nor a click that a
        holder.on_press = lambda e: True          # control in it (a slider) leaves unhandled
        holder.on_click = lambda e: True
        holder.add(content)
        overlay.add(holder)
        if old is not None:
            overlay.alpha, overlay.zoom, overlay.blur = old.alpha, old.zoom, old.blur
            old.stop_animation()
            self.layer.remove(old)
        self.layer.add(overlay)
        self.detail_view = overlay
        self.detail_css = (w, h)
        if (w, h) != (self.css_w, self.css_h):
            self.set_css_size(w, h)
            self.request_size()
        self.request_paint()

    def close_detail(self, animate=True):
        v = self.detail_view
        if v is None:
            return
        self.detail.tile = None
        self.detail_view = None
        self.root.no_hit = False

        def gone():
            self.layer.remove(v)
            if self.base_css and self.base_css != (self.css_w, self.css_h):
                self.set_css_size(*self.base_css)
                self.request_size()
            self.request_paint()
        if animate:
            v.no_hit = True
            v.animate(DETAIL_MS, "out", alpha=0.0, zoom=1.06, blur=10.0, done=gone)
            self.root.animate(DETAIL_MS, "out", alpha=1.0, zoom=1.0, blur=0.0)
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
        self.anim_alpha, self.anim_zoom = 0.0, 0.86
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
            time.sleep(0.04)
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

    def flyout_enter(self):
        self.anim_origin = self.origin()
        self.anim_alpha, self.anim_zoom = 0.0, 0.86
        self.moving = True                   # the glass sampler leaves the processor to the animation
        self.tweens.animate(self, {"anim_zoom": 1.0}, 220, ENTER_CURVE, self._settled)
        # opacity is full by 55% of the way in
        self.tweens.animate(self, {"anim_alpha": 1.0}, 121, ENTER_CURVE, None)

    def flyout_leave(self):
        self.moving = True
        self.tweens.animate(self, {"anim_alpha": 0.0, "anim_zoom": 0.92}, 130, LEAVE_CURVE, self._left)

    def _settled(self):
        self.moving = False
        self.sample_now.set()

    def _left(self):
        self.moving = False
        self.close_detail(animate=False)          # the next opening shows the tiles
        if self.home is not None:
            self.model.reset()

    def escape(self):
        if self.detail_view is None:
            return
        if self.detail.edit:
            self.detail.set_edit(False)
        else:
            self.close_detail()



def create_panel(api):
    return create_overlay(api, "HA Widgets Panel", lambda facade: PanelScene(facade, api), 200, 200)
