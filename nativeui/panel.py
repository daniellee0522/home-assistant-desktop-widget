"""The tray panel (the page's #flyout window): the widget's tiles beside the taskbar, or the Home view.

main.py drives it as it drove the page (overlay.py): `arm()` while it is placed but hidden (size, data, the
backdrop), `flyout_enter()` to bring it in, `flyout_leave()` to send it away. It scales out of its tray
corner and back, never past its resting size, the glass and the card as one.
"""
import os
import threading
import time
import traceback

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter

from . import render, ui
from .actions import TileActions
from .homemodel import HomeModel
from .overlay import OverlayScene, create_overlay
from .ui import Label, ScrollView, TileView, View

PAD, CELL_W, CELL_H, GAP = 14, 152, 146, 14
HOLD_MS, HOLD_SLOP = 420, 8
FLYOUT_ZOOM = 0.5
BG_VEIL = {"dark": (12, 14, 18, 0.26), "light": (255, 255, 255, 0.2)}


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
        self.bg_tag = None
        self.bg_image = None
        self.arm_event = None
        self.hold_timer = QTimer(self)
        self.hold_timer.setSingleShot(True)
        self.hold_timer.timeout.connect(self._held)
        self.hold = None
        self.anim_alpha, self.anim_zoom = 0.0, 0.86          # until it is asked to come in
        self.home = None
        self.configure()
        self.retheme()
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

    def apply_prefs(self, prefs):
        before = (self.theme_raw, self.style, self.language, self.liquid_level, self.system_glass, self.mode,
                  repr((prefs.get("panel") or {}).get("bg_image")), (prefs.get("panel") or {}).get("bg_blur"))
        self.prefs = prefs
        self.configure()
        after = (self.theme_raw, self.style, self.language, self.liquid_level, self.system_glass, self.mode,
                 repr((self.prefs.get("panel") or {}).get("bg_image")), (self.prefs.get("panel") or {}).get("bg_blur"))
        if before[:4] != after[:4] or before[4:] != after[4:]:
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
        for f in list(self.fields):
            self.fields.remove(f)
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
        self.request_size()
        self.request_paint()

    def build_grid(self, scroll):
        tiles = self.panel_tiles()
        n = max(1, len(tiles))
        cols = max(1, min(4, n))
        rows_total = -(-n // cols)
        rows_shown = min(2, rows_total)
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
        target = (round(sv.offset / row) - (1 if delta > 0 else -1)) * row     # a row at a time, as the page snaps
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
        x, y = tv.abs_pos()
        from .widget import _rect
        rect = _rect(self._hwnd)
        if not rect:
            return
        s = self.scale
        sx, sy = rect[0] + round(x * s), rect[1] + round(y * s)
        threading.Thread(target=self.api.open_popover, args=(tile["id"], sx, sy, round(tv.w * s), round(tv.h * s),
                                                             "flyout"), daemon=True).start()

    # -- the glass behind the card ------------------------------------------------------------------------------------
    def glass_tiles(self):
        out = []
        if self.grid_scroll is None:
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
            self.bg_image = None
            self.bg_tag = None
            self.glass = None
            self.invalidate_glass()
            return
        panel = self.prefs.get("panel") or {}
        path = self.api._panel_bg_path()
        if not path or self.pw <= 1:
            return
        from PIL import Image, ImageFilter
        blur = (28 if panel.get("bg_blur") is None else panel["bg_blur"]) * self.dpi * FLYOUT_ZOOM
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
        super().update_metrics()
        if self.custom_bg():
            self.make_bg()

    # -- coming in and going away --------------------------------------------------------------------------------------
    def request_size(self):
        self.update_metrics()
        self.seq += 1
        seq, pw, ph = self.seq, self.pw, self.ph
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
        if self.mode == "home":
            if self.home is None:
                self.rebuild()
            self.home.load()
        else:
            self.rebuild(keep_scroll=True)
        self.start_glass()
        if self.custom_bg():
            self.make_bg()
            threading.Thread(target=self.api.backdrop_armed, daemon=True).start()
            return
        self.glass = None
        self.invalidate_glass()
        done = threading.Event()
        self.arm_event = done

        def wait():
            time.sleep(0.04)
            done.wait(0.3)
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
        self.tweens.animate(self, {"anim_zoom": 1.0}, 220, "out", None)
        # opacity is full by 55% of the way in
        self.tweens.animate(self, {"anim_alpha": 1.0}, 121, "out", None)

    def flyout_leave(self):
        self.tweens.animate(self, {"anim_alpha": 0.0, "anim_zoom": 0.92}, 130, "in", self._left)

    def _left(self):
        if self.home is not None:
            self.model.reset()

    def escape(self):
        pass



def create_panel(api):
    return create_overlay(api, "HA Widgets Panel", lambda facade: PanelScene(facade, api), 200, 200)
