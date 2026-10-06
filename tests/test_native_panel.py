"""The natively drawn tray panel and detail card (nativeui/panel.py, homeview.py, homeedit.py, detail.py),
against a stand-in Api: taps and holds on tiles, the capsules, the rooms, editing, the card's controls."""
import os
import sys
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")
os.environ["HA_WIDGET_DCOMP"] = "0"        # the tests below follow the panel's own drawing; the compositor's has its own
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt                                          # noqa: E402
from PySide6.QtWidgets import QApplication                             # noqa: E402

app = QApplication.instance() or QApplication([])

from nativeui import dcomp, detail, panel, ui                           # noqa: E402
from nativeui.ui import Ev                                              # noqa: E402


def ent(eid, dom, name, area, state, attrs=None):
    return {"entity_id": eid, "domain": dom, "name": name, "area": area,
            "state": {"entity_id": eid, "state": state, "attributes": attrs or {}}}


HOME = {"rooms": ["客廳", "臥室"],
        "entities": [ent("light.a", "light", "吸頂燈", "客廳", "on"), ent("light.b", "light", "落地燈", "客廳", "off"),
                     ent("climate.ac", "climate", "冷氣", "客廳", "cool", {"temperature": 24}),
                     ent("lock.d", "lock", "大門", "", "unlocked"), ent("light.c", "light", "床頭燈", "臥室", "on")],
        "sensors": [{"entity_id": "sensor.t", "kind": "temperature", "name": "T", "area": "客廳",
                     "state": {"entity_id": "sensor.t", "state": "26.3", "attributes": {}}}]}


class FakeApi:
    _flyout_anchor = (None, True)

    def __init__(self, mode="home", tiles=None):
        self.calls = []
        self.saved = None
        self.mode, self.tiles = mode, tiles or []
        self.panel = {"mode": mode, "tiles": None, "home_tiles": []}

    def _prefs(self):
        return {"theme": "light", "language": "zh-TW", "glass_style": "classic", "zoom": 100, "panel_theme": "follow",
                "widgets": [{"id": "w1", "size": "2x4", "tiles": self.tiles}], "panel": self.panel}

    def fetch_initial_states(self):
        return {}

    def get_home(self):
        return HOME

    def save_panel(self, p):
        self.saved = p

    def save_widgets(self, w):
        self.calls.append(("save_widgets",))

    def resize_flyout_window(self, *a):
        pass

    def resize_popover_window(self, *a, **kw):
        pass

    def set_popover_activatable(self, v):
        pass

    def close_popover(self):
        self.calls.append(("close_popover",))

    def backdrop_armed(self):
        pass

    def get_desktop_backdrop(self, *a, **k):
        return {"skip": True, "retry_ms": 60000}

    def open_popover(self, *a):
        self.calls.append(("popover", a))

    def call_service(self, *a):
        self.calls.append(a)
        return {"ok": True}

    def get_picture(self, path):
        return None

    def get_history(self, e, h):
        return {"ok": True, "points": [[i, 20 + i] for i in range(10)]}

    def _panel_bg_path(self):
        return None


def pump(ms=60):
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def make_panel(api):
    win = panel.create_panel(api)
    sc = win.native
    pump(100)
    sc.anim_alpha = sc.anim_zoom = 1
    sc.anim_dy = 0
    sc.rebuild()
    sc.show()
    pump()
    if sc.home:
        sc.home.loaded(HOME)
    pump(50)
    return win, sc


def ev(view, x=5, y=5, button=Qt.LeftButton):
    gx, gy = view.abs_pos()
    return Ev(x, y, gx + x, gy + y, button)


def tiles_of(n):
    return [{"id": "t%d" % i, "entity": "light.l%d" % i, "domain": "light", "room": "L%d" % i, "label": ""}
            for i in range(n)]


class GridMode(unittest.TestCase):
    def test_tap_toggles_and_hold_opens_the_detail_over_the_tiles(self):
        api = FakeApi("grid", tiles_of(3))
        win, sc = make_panel(api)
        tv = sc.tiles_views[0]
        sc.push_states([("light.l0", {"state": "off", "attributes": {}})])
        sc._tile_press(tv, tv.tile, ev(tv))
        sc._tile_release(tv)
        sc._tile_click(tv, tv.tile, ev(tv))
        pump(80)
        self.assertIn(("light", "toggle", "light.l0", {}), api.calls)
        sc._tile_press(tv, tv.tile, ev(tv))
        pump(600)
        self.assertFalse([c for c in api.calls if c[0] == "popover"])     # no window of its own
        self.assertIsNotNone(sc.detail_view)
        self.assertEqual(sc.detail.tile["entity"], "light.l0")
        win.dispose()

    def test_more_than_two_rows_scroll_a_row_at_a_time(self):
        win, sc = make_panel(FakeApi("grid", tiles_of(14)))
        sv = sc.grid_scroll
        self.assertGreater(sv.max_offset(), 0)
        sc._grid_wheel(sv, -120)
        self.assertEqual(sv.offset, sv.row)
        win.dispose()


class HomeMode(unittest.TestCase):
    def test_category_tiles_rise_then_fade_in_place_and_room_changes_animate(self):
        from nativeui.ui import TileView
        win, sc = make_panel(FakeApi())
        try:
            h = sc.home
            size = (sc.css_w, sc.css_h)
            h.toggle_category("light")
            tiles = [v for v in h.cat_view.content.children if isinstance(v, TileView)]
            self.assertTrue(all(v.dy == 120 and v.alpha == 0 for v in tiles))
            pump(100)
            self.assertTrue(any(0 < v.dy < 120 for v in tiles))
            dy = [v.dy for v in tiles]
            h.toggle_category("light")
            pump(60)
            self.assertEqual([v.dy for v in tiles], dy)
            pump(400)
            h.chip_click("臥室")
            room_tiles = [v for section in h.sections for v in getattr(section, "grid").children if isinstance(v, TileView)]
            self.assertTrue(all(v.dy == 120 and v.alpha == 0 for v in room_tiles))
            sc.push_states([("light.c", {"state": "off", "attributes": {}})])
            self.assertTrue(all(v.dy == 120 for v in room_tiles))
            pump(650)
            self.assertTrue(all(v.dy == 0 and v.alpha == 1 for v in room_tiles))
            self.assertEqual((sc.css_w, sc.css_h), size)
        finally:
            win.dispose()

    def test_tile_morph_rebuild_keeps_geometry_and_corner_hits_follow_shape(self):
        win, sc = make_panel(FakeApi())
        try:
            tile = sc.home.tile_views()[0]
            self.assertFalse(tile.contains(1, 1))
            self.assertTrue(tile.contains(tile.w/2, tile.h/2))
            sc.popover(tile, tile.tile)
            source_rect = sc.detail_origin[0]
            self.assertEqual(sc.detail_view.frame(), source_rect)
            pump(70)
            before = (sc.detail_view.progress, sc.detail_view.frame())
            sc.push_states([(tile.tile["entity"], {"state": "off", "attributes": {}})])
            self.assertEqual((sc.detail_view.progress, sc.detail_view.frame()), before)
            sc.close_detail()
            pump(500)
            self.assertFalse(tile.transition_hidden)
        finally:
            win.dispose()

    def test_category_reverses_without_jump_or_delayed_tile_bounce(self):
        win, sc = make_panel(FakeApi())
        try:
            h = sc.home
            h.toggle_category("light")
            self.assertEqual((h.main.alpha, h.cat_view.alpha), (1, 0))
            pump(80)
            before = (h.main.alpha, h.cat_view.alpha, h.cat_view.zoom)
            tiles = [v for v in h.cat_view.content.children if hasattr(v, "tile")]
            self.assertTrue(tiles)
            h.toggle_category("light")
            self.assertEqual(before, (h.main.alpha, h.cat_view.alpha, h.cat_view.zoom))
            self.assertTrue(all(v in h.cat_view.content.children for v in tiles))
            pump(400)
            self.assertEqual((h.main.alpha, h.cat_view.alpha), (1, 0))
            self.assertTrue(all(v.zoom == 1 for v in tiles))
            self.assertFalse(sc.tweens.timer.isActive())
        finally:
            win.dispose()

    def test_spring_reversal_preserves_velocity_and_fixed_panel_size(self):
        win, sc = make_panel(FakeApi())
        try:
            h = sc.home
            size = (sc.css_w, sc.css_h)
            h.chip_click("客廳")
            self.assertEqual((sc.css_w, sc.css_h), size)
            h.toggle_category("light")
            tween = next(t for t in sc.tweens.running if t["view"] is h.cat_view)
            tween["t0"] = time.monotonic() - 0.06
            sc.tweens.tick()
            velocity = tween["velocity"]["alpha"]
            self.assertGreater(velocity, 0)
            self.assertEqual((sc.css_w, sc.css_h), size)
            size = (sc.css_w, sc.css_h)
            sc.push_states([("light.a", {"state": "off", "attributes": {}})])
            self.assertEqual((sc.css_w, sc.css_h), size)
            h.toggle_category("light")
            reverse = next(t for t in sc.tweens.running if t["view"] is h.cat_view)
            self.assertEqual(reverse["initial_velocity"]["alpha"], velocity)
            pump(450)
            self.assertEqual((h.main.alpha, h.cat_view.alpha), (1, 0))
        finally:
            win.dispose()

    def test_category_rebuild_keeps_current_animation(self):
        win, sc = make_panel(FakeApi())
        try:
            h = sc.home
            h.toggle_category("light")
            pump(60)
            before = (h.main.alpha, h.cat_view.alpha, h.cat_view.zoom)
            h.build()
            self.assertEqual(before, (h.main.alpha, h.cat_view.alpha, h.cat_view.zoom))
            sc.push_states([("light.a", {"state": "off", "attributes": {}})])
            self.assertEqual(before, (h.main.alpha, h.cat_view.alpha, h.cat_view.zoom))
            pump(350)
            self.assertEqual((h.main.alpha, h.cat_view.alpha), (0, 1))
        finally:
            win.dispose()

    def test_capsules_and_open_category(self):
        win, sc = make_panel(FakeApi())
        h = sc.home
        self.assertEqual([c["id"] for c, _, _ in h.m.visible_categories()], ["env", "light", "security"])
        h.toggle_category("light")
        self.assertEqual(h.m.category, "light")
        self.assertTrue(h.main.no_hit and not h.cat_view.no_hit)
        h.toggle_category("light")
        self.assertIsNone(h.m.category)
        win.dispose()

    def test_summary_state_change_keeps_capsule_widths_and_window_size(self):
        win, sc = make_panel(FakeApi())
        try:
            widths = {key: pill.w for key, pill in sc.home.pills.items()}
            size = (sc.css_w, sc.css_h)
            sc.push_states([("light.a", {"state": "off", "attributes": {}}),
                            ("lock.d", {"state": "locked", "attributes": {}})])
            self.assertEqual({key: pill.w for key, pill in sc.home.pills.items()}, widths)
            sc.home.build()
            self.assertEqual({key: pill.w for key, pill in sc.home.pills.items()}, widths)
            self.assertEqual((sc.css_w, sc.css_h), size)
        finally:
            win.dispose()

    def test_sheet_cancel_reopen_preserves_motion_and_releases_hit_layer(self):
        win, sc = make_panel(FakeApi())
        try:
            h = sc.home
            h.open_sheet()
            pump(70)
            h.close_sheet()
            before = (h.sheet_view.alpha, h.sheet_view.zoom)
            h.open_sheet()
            self.assertEqual((h.sheet_view.alpha, h.sheet_view.zoom), before)
            self.assertFalse(h.sheet_view.no_hit)
            pump(450)
            h.close_sheet()
            pump(450)
            self.assertIsNone(h.sheet_view)
            self.assertFalse(sc.tweens.timer.isActive())
        finally:
            win.dispose()

    def test_room_chip_and_hidden_room(self):
        api = FakeApi()
        win, sc = make_panel(api)
        h = sc.home
        h.chip_click("客廳")
        self.assertEqual(h.m.room, "客廳")
        self.assertEqual([s.room for s in h.sections], ["客廳"])
        h.chip_click("")
        h.m.editing = True
        h.toggle_room_hidden("臥室", False)
        self.assertIn("臥室", api.saved["hidden_rooms"])
        win.dispose()

    def test_remove_and_restore(self):
        api = FakeApi()
        win, sc = make_panel(api)
        h = sc.home
        h.remove_device(HOME["entities"][1])
        self.assertTrue(h.m.record("light.b")["hidden"])
        h.open_sheet()
        self.assertTrue(h.m.sheet)
        h.restore_device(HOME["entities"][1])
        self.assertNotIn("hidden", h.m.record("light.b"))
        win.dispose()

    def test_add_room_goes_last(self):
        api = FakeApi()
        win, sc = make_panel(api)
        h = sc.home
        h.m.adding_room = True
        h.build()
        h.room_field.set_text("書房")
        h.finish_adding_room(True)
        self.assertIn("書房", api.saved["custom_rooms"])
        self.assertEqual(api.saved["room_order"][-1], "書房")
        win.dispose()

    def test_drag_a_tile_left_pushes_the_others_right(self):
        api = FakeApi()
        win, sc = make_panel(api)
        h = sc.home
        h.m.editing = True
        h.build()
        grid = next(s.grid for s in h.sections if s.room == "客廳")
        tvs = {v.entity["entity_id"]: v for v in grid.children if hasattr(v, "entity")}
        mover = tvs["climate.ac"]
        gx, gy = mover.abs_pos()
        h.drag_press(mover, mover.entity, Ev(5, 5, gx + 5, gy + 5, Qt.LeftButton))
        first = tvs["light.a"].abs_pos()
        for step in range(1, 8):
            h.drag_move(mover, Ev(0, 0, gx + 5 + (first[0] - gx) * step / 7, gy + 5, Qt.LeftButton, Qt.LeftButton))
        h.drag_release(mover)
        rec = h.m.record("climate.ac")
        self.assertEqual((rec["x"], rec["y"]), (0, 0))
        self.assertEqual(h.m.record("light.a")["x"], 1)
        win.dispose()

    def test_resize_to_a_bar(self):
        api = FakeApi()
        win, sc = make_panel(api)
        h = sc.home
        h.m.editing = True
        h.build()
        grid = next(s.grid for s in h.sections if s.room == "客廳")
        tv = next(v for v in grid.children if hasattr(v, "entity") and v.entity["entity_id"] == "light.b")
        h.resize_press(tv, tv.entity, Ev(0, 0, 0, 0, Qt.LeftButton))
        ox, oy = tv.abs_pos()
        h.resize_move(tv, Ev(0, 0, ox + 300, oy + 100, Qt.LeftButton))
        h.resize_release(tv)
        rec = h.m.record("light.b")
        self.assertEqual((rec["w"], rec["h"]), (2, 1))
        win.dispose()


class Card(unittest.TestCase):
    def test_repeated_right_edge_opens_restore_cached_canvas_position(self):
        from PySide6.QtGui import QImage
        from test_glass import definitions
        place = definitions("_place_against")["_place_against"]
        tile = dict(id="t", entity="switch.a", domain="switch", room="插座", label="")
        api = FakeApi("grid", [tile])
        anchor = (1870, 900, 40, 50)
        api._popover_origin = lambda w,h: (place(anchor[0],w,anchor[0],anchor[2],0,1920),
                                         place(anchor[1],h,anchor[1],anchor[3],0,1080))
        win = detail.create_popover(api)
        card = win.native
        def resize(pw,ph,seq,origin=None):
            ratio=card.devicePixelRatioF()
            card.resize(round(pw/ratio),round(ph/ratio))
            if origin: card.move(round(origin[0]/ratio),round(origin[1]/ratio))
        api.resize_popover_window=resize
        try:
            image = QImage(40,50,QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.white)
            origins=[]
            for _ in range(4):
                card.move(anchor[0],anchor[1])
                card.set_transition_source(anchor,image,"t",source_dpi=1.0)
                card.open_tile("t")
                card.show(); card.enter(); pump(500)
                target=card.page_targets[False]
                x=card.pos().x()*card.devicePixelRatioF()+target.x()*card.scale
                self.assertLessEqual(x+target.width()*card.scale,1920)
                self.assertLess(x,anchor[0])
                origins.append((card.canvas_origin,x))
                card.set_edit(True); pump(40)
                card.set_edit(False); pump(400)
                card.close_card(); pump(500); card.hide()
            self.assertEqual(len(set(origins)),1)
        finally:
            win.dispose()

    def test_first_open_uses_source_dpi_before_settings_and_keeps_it(self):
        from unittest.mock import patch
        from PySide6.QtGui import QImage
        tile = dict(id="t", entity="light.a", domain="light", room="燈", label="")
        api = FakeApi("grid", [tile])
        api._popover_origin = lambda w,h: (300, 200)
        win = detail.create_popover(api)
        card = win.native
        try:
            image = QImage(480, 210, QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.white)
            card.set_transition_source((300, 200, 480, 210), image, "t", source_dpi=1.5)
            with patch("nativeui.ui._dpi", return_value=96):
                card.open_tile("t")
                card.enter()
                card.show()
                pump(600)
                width = card.transition_frame().width()
                pixels = card.pw, card.ph
                self.assertEqual(card.scale, 1.5)
                self.assertEqual(card.transition_bounds[0].width(), 320)
                card.set_edit(True)
                pump(600)
                self.assertEqual(card.transition_frame().width(), width)
                self.assertEqual((card.pw, card.ph), pixels)
                self.assertEqual(card.scale, 1.5)
                card.set_edit(False)
                pump(600)
                self.assertEqual(card.transition_frame().width(), width)
                self.assertEqual(card.scale, 1.5)
        finally:
            win.dispose()

    def test_rapid_settings_reversal_retains_presented_frame_and_content(self):
        tile = dict(id="t", entity="switch.a", domain="switch", room="插座", label="")
        api, win, card = self.make(tile, {"state": "off", "attributes": {}})
        try:
            pump(200)
            width = card.transition_frame().width()
            for on in (True, False, True, False):
                before = card.transition_frame()
                card.set_edit(on)
                self.assertEqual(card.transition_frame(), before)
                self.assertTrue(any(isinstance(v, detail.PageSnapshot) and v.alpha == 1 for v in card.root.children))
                pump(65)
                self.assertEqual(card.transition_frame().width(), width)
            pump(600)
            self.assertFalse(any(isinstance(v, detail.PageSnapshot) for v in card.root.children))
            self.assertEqual(card.transition_frame(), card.page_targets[False])
        finally:
            win.dispose()

    def test_settings_use_one_height_keep_width_and_allow_scrolling_to_done(self):
        from PySide6.QtCore import QPoint, QPointF
        from PySide6.QtGui import QWheelEvent
        sizes = []
        for domain in ("light", "switch", "lock", "sensor"):
            tile = dict(id="t", entity=domain+".a", domain=domain, room="測試", label="")
            api, win, card = self.make(tile, {"state": "off", "attributes": {}})
            try:
                before = card.transition_frame()
                scale = card.page_holder.children[0].scale
                card.set_edit(True)
                self.assertEqual(card.transition_frame(), before)
                self.assertEqual(card.page_targets[True].width(), before.width())
                self.assertEqual(card.page_holder.children[0].scale, scale)
                old = next(v for v in card.root.children if isinstance(v, detail.PageSnapshot))
                self.assertEqual((old.alpha, card.page_holder.alpha), (1, 0))
                pump(70)
                self.assertAlmostEqual(old.alpha+card.page_holder.alpha, 1, places=2)
                frame = card.transition_frame()
                self.assertEqual(frame.width(), before.width())
                card.set_icon("mdi:lamp")
                self.assertEqual(card.transition_frame(), frame)
                self.assertIn(old, card.root.children)
                pump(600)
                sizes.append((card.page_targets[True].width(), card.page_targets[True].height()))
                scroll = card.body_scroll
                if domain == "switch":
                    self.assertGreater(scroll.max_offset(), 0)
                x, y, k = scroll.in_scene()
                ratio = card.scale/card.devicePixelRatioF()
                pos = QPointF((x+scroll.w*k*.5)*ratio, (y+scroll.h*k*.5)*ratio)
                event = QWheelEvent(pos, card.mapToGlobal(pos.toPoint()), QPoint(), QPoint(0,-2400),
                                    Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
                app.sendEvent(card, event)
                pump(40)
                self.assertEqual(scroll.offset, scroll.max_offset())
                self.assertTrue(all(f.edit.isVisible() for f in card.fields))
                done = next(v for v in self.walk(scroll) if isinstance(v, ui.Button) and v.text == "完成")
                dx, dy, dk = done.in_scene()
                self.assertLessEqual(dy+done.h*dk, y+scroll.h*k)
                card.set_edit(False)
                pump(600)
                self.assertEqual(card.transition_frame(), before)
            finally:
                win.dispose()
        self.assertEqual(len(set(sizes)), 1)

    @staticmethod
    def walk(view):
        return [view]+[item for child in view.children for item in Card.walk(child)]

    def test_settings_in_small_work_area_keep_control_width_and_restore_fit(self):
        tile = dict(id="t", entity="light.a", domain="light", room="燈", label="")
        api = FakeApi("grid", [tile])
        win = detail.create_popover(api)
        card = win.native
        try:
            card.room = lambda: 220
            card.open_tile("t")
            card.enter()
            card.show()
            pump(200)
            original = card.transition_frame()
            fitted = card.detail_fit
            self.assertLess(fitted[2], 1)
            card.set_edit(True)
            pump(600)
            self.assertEqual(card.transition_frame().width(), original.width())
            self.assertEqual(card.page_holder.children[0].scale, fitted[2])
            card.body_scroll.scroll_to(card.body_scroll.max_offset())
            pump(30)
            self.assertTrue(card.fields[-1].edit.isVisible())
            card.set_edit(False)
            pump(600)
            self.assertEqual(card.detail_fit, fitted)
            self.assertEqual(card.transition_frame(), original)
        finally:
            win.dispose()

    def test_other_icons_are_two_rows_and_keep_the_current_custom_choice(self):
        tile = dict(id="t", entity="light.a", domain="light", room="燈", label="", icon="mdi:weather-night")
        api, win, card = self.make(tile, {"state": "off", "attributes": {}})
        try:
            card.set_edit(True)
            body = card.body_scroll.content.children[0]
            index = next(i for i,v in enumerate(body.children) if getattr(v,"text",None)=="其他圖示")
            icons = body.children[index+2].children
            self.assertLessEqual(len(icons), 14)
            self.assertIn(tile["icon"], [v.icon for v in icons])
        finally:
            win.dispose()

    def make(self, tile, state):
        api = FakeApi()
        api.tiles = [tile]
        win = detail.create_popover(api)
        card = win.native
        def resize(pw,ph,seq,origin=None):
            ratio=card.devicePixelRatioF()
            card.resize(round(pw/ratio),round(ph/ratio))
            if origin: card.move(round(origin[0]/ratio),round(origin[1]/ratio))
        api.resize_popover_window=resize
        pump(100)
        card.push_states([(tile["entity"], state)])
        card.open_tile(tile["id"])
        card.show()
        card.enter()
        pump(50)
        return api, win, card

    def test_light_card_brightness(self):
        t = {"id": "t1", "entity": "light.a", "domain": "light", "room": "燈", "label": ""}
        api, win, card = self.make(t, {"state": "on", "attributes": {"brightness": 128}})
        sliders = []

        def walk(v):
            if v.__class__.__name__ == "TallSlider":
                sliders.append(v)
            for c in v.children:
                walk(c)
        walk(card.root)
        self.assertEqual(len(sliders), 1)
        sliders[0].on_commit(70)
        pump(80)
        self.assertIn(("light", "turn_on", "light.a", {"brightness_pct": 70}), api.calls)
        win.dispose()

    def test_edit_the_name_and_icon(self):
        t = {"id": "t1", "entity": "light.a", "domain": "light", "room": "燈", "label": ""}
        api, win, card = self.make(t, {"state": "off", "attributes": {}})
        card.set_edit(True)
        card.set_room("客廳燈")
        card.set_icon("mdi:lamp")
        pump(100)
        self.assertEqual(card.tile["room"], "客廳燈")
        self.assertEqual(card.tile["icon"], "mdi:lamp")
        self.assertIn(("save_widgets",), api.calls)
        win.dispose()

    def test_close_asks_main_to_hide_it(self):
        t = {"id": "t1", "entity": "lock.d", "domain": "lock", "room": "門", "label": ""}
        api, win, card = self.make(t, {"state": "locked", "attributes": {}})
        card.close_card()
        pump(400)
        self.assertIn(("close_popover",), api.calls)
        win.dispose()


class DeletingRooms(unittest.TestCase):
    def test_delete_a_room_and_bring_it_back(self):
        api = FakeApi("home")
        win, sc = make_panel(api)
        hv = sc.home
        import copy
        hv.loaded(copy.deepcopy(HOME))                       # its own copy: deleting changes the devices' rooms
        hv.m.editing = True
        hv.build()
        chip = next(c for c in hv.chips if getattr(c, "key", None) == "客廳")
        self.assertTrue(chip.x_button)                       # a room from Home Assistant can be deleted too
        hv.delete_room("客廳")
        pump(50)
        panel = api.saved
        self.assertIn("客廳", panel["deleted_rooms"])
        self.assertNotIn("客廳", hv.m.room_names())
        moved = [e["entity_id"] for e in hv.m.entities if e.get("area") == ""]
        self.assertIn("light.a", moved)                      # its devices are uncategorised
        self.assertIn("climate.ac", moved)
        hv.m.editing = False
        hv.build()
        shown = [e["entity_id"] for _, es, _ in hv.m.groups() for e in es]
        self.assertNotIn("light.a", shown)                   # and uncategorised is off the main screen
        hv.open_sheet()
        pump(50)
        rows = [v for v in hv.sheet_view.children[-1].content.children if getattr(v, "left_text", None) == "客廳"]
        self.assertTrue(rows)                                # the sheet offers it back
        hv.restore_room("客廳")
        pump(50)
        self.assertNotIn("客廳", api.saved["deleted_rooms"])
        win.dispose()


class DetailOverThePanel(unittest.TestCase):
    """A hold or a right click shows the tile's detail inside the panel, as a capsule's devices are shown."""

    def find(self, view, cls_name):
        out = []

        def walk(v):
            if v.__class__.__name__ == cls_name:
                out.append(v)
            for c in v.children:
                walk(c)
        walk(view)
        return out

    def open_speaker(self, mode="grid", n=2):
        api = FakeApi(mode, [{"id": "sp", "entity": "media_player.s", "domain": "media_player", "room": "喇叭",
                              "label": ""}] + tiles_of(n - 1))
        win, sc = make_panel(api)
        sc.push_states([("media_player.s", {"state": "playing", "attributes": {"volume_level": 0.3}})])
        sc.open_detail("sp")
        pump(500)
        return api, win, sc

    def test_it_fits_the_panel_without_scrolling(self):
        """A light has the most to show: its tall slider is made shorter, and the rest drawn smaller."""
        api = FakeApi("grid", [{"id": "l", "entity": "light.l", "domain": "light", "room": "燈", "label": ""}])
        win, sc = make_panel(api)
        sc.push_states([("light.l", {"state": "on", "attributes": {
            "brightness": 200, "supported_color_modes": ["color_temp", "hs"], "min_color_temp_kelvin": 2700,
            "max_color_temp_kelvin": 6500, "effect_list": ["a", "b"], "effect": "a"}})])
        sc.open_detail("l")
        pump(500)
        self.assertEqual(sc.detail.body_scroll.max_offset(), 0)
        holder = sc.detail_view.children[0]
        self.assertLessEqual(holder.h * holder.scale + 2 * panel.DETAIL_MARGIN, panel.DETAIL_MAX_H + 0.5)
        win.dispose()

    def test_first_menu_and_rebuild_use_the_same_scale_inside_the_window(self):
        from nativeui import controls
        from nativeui.ui import View
        win, sc = make_panel(FakeApi("grid", tiles_of(1)))
        try:
            holder = View(0, 0, 320, 300)
            holder.scale = 2
            card = controls.ModeCard(140, "mdi:fan", "模式", "自動",
                                     [(i, str(i)) for i in range(20)], lambda _: None, 0)
            holder.add(card)
            sc.layer.add(holder)
            card.show_menu()
            pane = sc.popup
            scale = pane.scale
            self.assertGreaterEqual(pane.x, 6)
            self.assertGreaterEqual(pane.y, 6)
            self.assertLessEqual(pane.x + pane.w * scale, sc.css_w - 6 + 0.01)
            self.assertLessEqual(pane.y + pane.h * scale, sc.css_h - 6 + 0.01)
            controls.reattach_menu(sc, holder)
            self.assertEqual(sc.popup.scale, scale)
        finally:
            win.dispose()

    def test_a_mode_card_opens_a_menu_over_it_and_leaves_the_screen_as_it_is(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        api = FakeApi("grid", [{"id": "ac", "entity": "climate.ac", "domain": "climate", "room": "冷氣", "label": ""}])
        win, sc = make_panel(api)
        sc.push_states([("climate.ac", {"state": "off", "attributes": {
            "temperature": 24, "hvac_modes": ["off", "cool", "heat"], "fan_modes": ["auto", "low"], "fan_mode": "auto"}})])
        sc.open_detail("ac")
        pump(500)
        card = self.find(sc.detail_view, "ModeCard")[0]
        built = sc.detail_view
        s = sc.scale / sc.devicePixelRatioF()
        x, y, k = card.in_scene()
        QTest.mouseClick(sc, Qt.LeftButton, pos=QPoint(round((x + card.w * k / 2) * s), round((y + 20 * k) * s)))
        pump(300)
        self.assertIsNotNone(sc.popup)
        self.assertIs(sc.detail_view, built)                         # nothing was built again
        self.assertAlmostEqual(sc.popup.scale, k)                    # as large as the card is drawn
        rows = sc.popup.children[0].content.children
        rx, ry, rk = rows[1].in_scene()
        QTest.mouseClick(sc, Qt.LeftButton, pos=QPoint(round((rx + 40 * rk) * s), round((ry + 20 * rk) * s)))
        pump(200)
        self.assertIsNone(sc.popup)
        self.assertIn(("climate", "set_hvac_mode", "climate.ac", {"hvac_mode": "cool"}), api.calls)
        win.dispose()

    def test_built_again_it_stays_where_it_was_scrolled(self):
        from nativeui import detail
        api = FakeApi("grid", [{"id": "l", "entity": "light.l", "domain": "light", "room": "燈", "label": ""}])
        win, sc = make_panel(api)
        content = detail.DetailContent(sc, lambda: sc.prefs, sc.states, lambda: None)
        content.open("l")
        content.build(max_h=200)
        content.body_scroll.scroll_to(60)
        content.build(max_h=200)                                     # a new state came
        self.assertEqual(content.body_scroll.offset, 60)
        content.open("l")                                            # opened again: from the top
        content.build(max_h=200)
        self.assertEqual(content.body_scroll.offset, 0)
        win.dispose()

    def test_a_menu_open_while_a_new_state_comes_stays_open_over_the_new_card(self):
        api = FakeApi("grid", [{"id": "ac", "entity": "climate.ac", "domain": "climate", "room": "冷氣", "label": ""}])
        win, sc = make_panel(api)
        st = {"state": "off", "attributes": {"temperature": 24, "hvac_modes": ["off", "cool"], "fan_modes": ["auto", "low"],
                                             "fan_mode": "auto"}}
        sc.push_states([("climate.ac", st)])
        sc.open_detail("ac")
        pump(400)
        self.find(sc.detail_view, "ModeCard")[1].show_menu()             # the fan speeds
        pump(200)
        sc.push_states([("climate.ac", dict(st, attributes=dict(st["attributes"], fan_mode="low")))])
        pump(300)
        cards = self.find(sc.detail_view, "ModeCard")
        self.assertIsNotNone(sc.popup)
        self.assertEqual([c.open for c in cards], [False, True])        # the new card looks open
        self.assertEqual(sc.popup.current, "low")                        # and the menu says what is chosen now
        sc.close_popup()
        self.assertFalse(cards[1].open)
        win.dispose()

    def test_binary_switch_drag_half_flick_and_fast_tap_share_animated_control(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        api = FakeApi("home", [dict(id="sw", entity="switch.s", domain="switch", room="插座", label="")])
        win, sc = make_panel(api)
        try:
            sc.push_states([("switch.s", {"state": "off", "attributes": {}})])
            sc.open_detail("sw")
            pump(500)
            def control(): return self.find(sc.detail_view, "TallSwitch")[0]
            def point(view, y):
                x0,y0,k = view.in_scene()
                ratio=sc.scale/sc.devicePixelRatioF()
                return QPoint(round((x0+view.w*k/2)*ratio), round((y0+y*k)*ratio))
            toggle=control()
            QTest.mouseClick(sc, Qt.LeftButton, pos=point(toggle, toggle.h*.75))
            replacement=control()
            self.assertLess(replacement.position, 1)
            tween=next(t for t in sc.tweens.running if t["view"] is replacement and "position" in t["props"])
            self.assertEqual(tween["ms"], 180)
            pump(300)
            self.assertEqual(replacement.position, 1)
            for distance, pause, expected in ((.4, 180, True), (.6, 180, False), (.25, 20, True)):
                toggle=control()
                on=toggle.on
                start=toggle.h*(.25 if on else .75)
                direction=1 if on else -1
                end=start+direction*(toggle.h/2-8)*distance
                QTest.mousePress(sc,Qt.LeftButton,pos=point(toggle,start))
                pump(180 if pause==180 else 5)
                QTest.mouseMove(sc,point(toggle,end))
                # An arriving state must not steal pointer capture or reset the handle.
                before=toggle.position
                sc.push_states([("switch.s",dict(sc.states["switch.s"]))])
                replacement=control()
                self.assertEqual(replacement.position,before)
                self.assertIs(sc.capture,replacement)
                pump(pause)
                QTest.mouseRelease(sc,Qt.LeftButton,pos=point(replacement,end))
                pump(450)
                self.assertEqual(control().on,expected)
                self.assertIsNotNone(sc.detail_view)
            self.assertEqual(len([c for c in api.calls if c[:2]==("switch","toggle")]),3)
            toggle=control()
            QTest.mouseClick(sc, Qt.LeftButton, pos=point(toggle, toggle.h*.25))
            returning=control()
            self.assertFalse(returning.on)
            self.assertGreater(returning.position, 0)
            pump(380)
            self.assertEqual(control().position, 0)
            QTest.mouseClick(sc, Qt.LeftButton, pos=point(control(), control().h*.75))
            pump(70)
            before=control().position
            sc.push_states([("switch.s", {"state": "off", "attributes": {}})])
            self.assertEqual(control().position, before)
            pump(300)
            self.assertEqual(control().position, 0)
        finally:
            win.dispose()

    def test_detail_blank_space_closes_but_controls_keep_it_open(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        win, sc = make_panel(FakeApi())
        try:
            sc.open_detail("home:climate.ac")
            pump(500)
            holder=sc.detail_view.children[0]
            x,y,k=holder.in_scene()
            ratio=sc.scale/sc.devicePixelRatioF()
            QTest.mouseClick(sc,Qt.LeftButton,pos=QPoint(round((x+holder.w*k*.95)*ratio),round((y+holder.h*k*.5)*ratio)))
            self.assertIsNone(sc.detail_view)
        finally:
            win.dispose()

    def test_first_home_detail_and_reopen_have_identical_scale_and_fixed_bounds(self):
        win, sc = make_panel(FakeApi())
        try:
            size = (sc.css_w, sc.css_h)
            geometries = []
            for _ in range(2):
                sc.open_detail("home:climate.ac")
                pump(450)
                holder = sc.detail_view.children[0]
                self.find(sc.detail_view, "ModeCard")[0].show_menu()
                pane = sc.popup
                geometries.append((holder.scale, holder.h, pane.scale, pane.x, pane.y))
                self.assertEqual((sc.css_w, sc.css_h), size)
                sc.close_detail()
                pump(450)
                self.assertEqual((sc.css_w, sc.css_h), size)
            self.assertEqual(geometries[0], geometries[1])
        finally:
            win.dispose()

    def test_desktop_detail_morph_uses_source_bounds_and_can_reverse(self):
        from PySide6.QtGui import QImage
        api = FakeApi("grid", tiles_of(1))
        api._popover_origin = lambda w, h: (100, 120)
        win = detail.create_popover(api)
        sc = win.native
        try:
            image = QImage(200, 146, QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.white)
            sc.room = lambda: 220
            sc.set_transition_source((140, 140, 200, 146), image, "t0")
            sc.open_tile("t0")
            sc.enter()
            self.assertEqual(sc.transition_frame(), sc.transition_bounds[0])
            size = (sc.css_w, sc.css_h)
            fitted = sc.detail_fit
            self.assertLess(fitted[2], 1)
            pump(80)
            before = (sc.progress, sc.transition_frame())
            sc.push_states([("light.l0", {"state": "off", "attributes": {}})])
            self.assertEqual((sc.progress, sc.transition_frame()), before)
            self.assertEqual((sc.css_w, sc.css_h), size)
            self.assertEqual(sc.detail_fit, fitted)
            sc.close_card()
            pump(60)
            progress = sc.progress
            sc.set_transition_source((140, 140, 200, 146), image, "t0")
            sc.open_tile("t0")
            sc.enter()
            self.assertEqual(sc.progress, progress)
            pump(500)
            self.assertEqual(sc.progress, 1)
        finally:
            win.dispose()

    def test_detail_can_reverse_closing_without_resize_or_presentation_jump(self):
        win, sc = make_panel(FakeApi("grid", tiles_of(1)))
        try:
            sc.open_detail("t0")
            pump(450)
            size = (sc.css_w, sc.css_h)
            sc.close_detail()
            pump(60)
            old = sc.closing_detail
            before = (old.alpha, old.zoom)
            sc.open_detail("t0")
            self.assertEqual((sc.detail_view.alpha, sc.detail_view.zoom), before)
            pump(450)
            self.assertEqual((sc.css_w, sc.css_h), size)
            self.assertEqual(sc.detail_view.alpha, 1)
            self.assertFalse(sc.tweens.timer.isActive())
        finally:
            win.dispose()

    def test_new_state_during_detail_entrance_does_not_freeze_it_half_open(self):
        api = FakeApi("grid", [{"id": "ac", "entity": "climate.ac", "domain": "climate", "room": "冷氣", "label": ""}])
        win, sc = make_panel(api)
        try:
            st = {"state": "cool", "attributes": {"temperature": 24, "hvac_modes": ["off", "cool"]}}
            sc.push_states([("climate.ac", st)])
            sc.open_detail("ac")
            old = sc.detail_view
            tween = next(t for t in sc.tweens.running if t["view"] is old)
            tween["t0"] = time.monotonic() - 0.04
            sc.tweens.tick()
            presentation = (old.alpha, old.zoom, old.blur)
            self.assertGreater(old.alpha, 0)
            self.assertLess(old.alpha, 1)
            sc.push_states([("climate.ac", dict(st, attributes=dict(st["attributes"], temperature=25)))])
            self.assertIsNot(sc.detail_view, old)
            self.assertEqual((sc.detail_view.alpha, sc.detail_view.zoom, sc.detail_view.blur), presentation)
            self.assertIs(tween["view"], sc.detail_view)
            pump(400)
            self.assertEqual((sc.detail_view.alpha, sc.detail_view.zoom, sc.detail_view.blur), (1, 1, 0))
        finally:
            win.dispose()

    def test_new_state_during_menu_entrance_keeps_its_current_position_and_animation(self):
        api = FakeApi("grid", [{"id": "ac", "entity": "climate.ac", "domain": "climate", "room": "冷氣", "label": ""}])
        win, sc = make_panel(api)
        try:
            st = {"state": "off", "attributes": {"temperature": 24, "hvac_modes": ["off", "cool"],
                                                   "fan_modes": ["auto", "low"], "fan_mode": "auto"}}
            sc.push_states([("climate.ac", st)])
            sc.open_detail("ac")
            pump(400)
            self.find(sc.detail_view, "ModeCard")[1].show_menu()
            old = sc.popup
            tween = next(t for t in sc.tweens.running if t["view"] is old)
            tween["t0"] = time.monotonic() - 0.04
            sc.tweens.tick()
            alpha, dy = old.alpha, old.dy
            self.assertGreater(alpha, 0)
            self.assertLess(alpha, 1)
            sc.push_states([("climate.ac", dict(st, attributes=dict(st["attributes"], fan_mode="low")))])
            self.assertIsNot(sc.popup, old)
            self.assertEqual((sc.popup.alpha, sc.popup.dy), (alpha, dy))
            self.assertIs(tween["view"], sc.popup)
            self.assertEqual(sc.popup.current, "low")
            pump(350)
            self.assertEqual((sc.popup.alpha, sc.popup.dy), (1, 0))
            self.assertFalse(any(t["view"] is old for t in sc.tweens.running))
            sc.close_popup()
            self.assertFalse(sc.tweens.timer.isActive())
        finally:
            win.dispose()

    def test_the_song_can_be_dragged_to_a_new_place(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        api = FakeApi("grid", [{"id": "sp", "entity": "media_player.s", "domain": "media_player", "room": "喇叭",
                                "label": ""}])
        win, sc = make_panel(api)
        sc.push_states([("media_player.s", {"state": "paused", "attributes": {
            "media_title": "T", "media_duration": 200, "media_position": 0, "supported_features": 2}})])
        sc.open_detail("sp")
        pump(500)
        bar = self.find(sc.detail_view, "Progress")[0]
        x, y, k = bar.in_scene()
        s = sc.scale / sc.devicePixelRatioF()
        QTest.mousePress(sc, Qt.LeftButton, pos=QPoint(round((x + 20 * k) * s), round((y + 10 * k) * s)))
        QTest.mouseMove(sc, QPoint(round((x + bar.w / 2 * k) * s), round((y + 10 * k) * s)))
        pump(50)
        self.assertAlmostEqual(bar.now(), 100, delta=4)                 # the time shown follows
        QTest.mouseRelease(sc, Qt.LeftButton, pos=QPoint(round((x + bar.w / 2 * k) * s), round((y + 10 * k) * s)))
        pump(100)
        seek = [c for c in api.calls if c[:2] == ("media_player", "media_seek")]
        self.assertTrue(seek)
        self.assertAlmostEqual(seek[-1][3]["seek_position"], 100, delta=4)
        win.dispose()

    def test_its_words_stand_on_a_backing_that_keeps_them_readable(self):
        api = FakeApi("grid", [{"id": "l", "entity": "light.l", "domain": "light", "room": "燈", "label": ""}])
        win, sc = make_panel(api)
        sc.open_detail("l")
        pump(400)
        self.assertIsInstance(sc.detail_view, panel.Backing)
        win.dispose()

    def test_a_small_panel_keeps_its_size_for_detail_and_close(self):
        api, win, sc = self.open_speaker(n=2)
        base = sc.base_css
        self.assertEqual((sc.css_w, sc.css_h), base)
        self.assertTrue(sc.root.no_hit)
        self.assertEqual(sc.root.alpha, 0.0)                         # the tiles receded
        sc.close_detail()
        pump(500)
        self.assertIsNone(sc.detail_view)
        self.assertEqual((sc.css_w, sc.css_h), base)
        self.assertEqual(sc.root.alpha, 1.0)
        win.dispose()

    def test_the_volume_slider_answers_where_it_is_drawn(self):
        """The detail is drawn at up to twice the panel's units (less when it has more to show than fits): a
        press three quarters along the slider, in the window, sets three quarters of the volume."""
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        api, win, sc = self.open_speaker()
        slider = self.find(sc.detail_view, "Slider")[0]
        x, y, k = slider.in_scene()
        self.assertTrue(0 < k <= 2.0, k)
        self.assertLessEqual(sc.detail_view.children[0].h * k + 2 * panel.DETAIL_MARGIN, sc.css_h + 0.01)
        s = sc.scale / sc.devicePixelRatioF()
        at = QPoint(round((x + slider.w * k * 0.75) * s), round((y + slider.h * k / 2) * s))
        QTest.mousePress(sc, Qt.LeftButton, pos=at)
        QTest.mouseRelease(sc, Qt.LeftButton, pos=at)
        pump(150)
        volume = [c for c in api.calls if c[:2] == ("media_player", "volume_set")]
        self.assertTrue(volume)
        self.assertAlmostEqual(volume[-1][3]["volume_level"], 0.75, delta=0.06)
        self.assertIsNotNone(sc.detail_view)                         # pressing inside does not go back
        win.dispose()

    def test_new_states_rebuild_it_and_the_space_around_it_goes_back(self):
        api, win, sc = self.open_speaker(mode="grid", n=4)
        first = sc.detail_view
        sc.push_states([("media_player.s", {"state": "paused", "attributes": {"volume_level": 0.5}})])
        pump(50)
        self.assertIsNot(sc.detail_view, first)
        self.assertEqual(sc.detail_view.alpha, 1.0)                  # rebuilt where it was, not faded in again
        sc.detail_view.on_click(ev(sc.detail_view, 2, 2))
        pump(500)
        self.assertIsNone(sc.detail_view)
        win.dispose()

    def test_its_edit_panel_fields_sit_on_the_scaled_detail(self):
        api, win, sc = self.open_speaker()
        sc.detail.set_edit(True)
        pump(100)
        fields = self.find(sc.detail_view, "TextField")
        self.assertTrue(fields)
        f = fields[0]
        x, y, k = f.in_scene()
        s = sc.scale / sc.devicePixelRatioF()
        g = f.edit.geometry()
        self.assertAlmostEqual(g.width(), (f.w * k - 2 * 12 * k) * s, delta=2)
        self.assertAlmostEqual(g.y(), y * s, delta=2)
        sc.apply_prefs(dict(sc.prefs))                               # a save comes back while typing
        pump(50)
        self.assertIs(self.find(sc.detail_view, "TextField")[0], f)  # the field is kept
        sc.escape()                                                  # Esc leaves the edit panel, then the detail
        pump(50)
        self.assertFalse(sc.detail.edit)
        sc.escape()
        pump(500)
        self.assertIsNone(sc.detail_view)
        win.dispose()

    def test_home_panel_shows_it_without_growing(self):
        api, win, sc = self.open_speaker(mode="home")
        sc.open_detail("home:light.a")
        pump(500)
        self.assertEqual((sc.css_w, sc.css_h), sc.base_css)
        self.assertEqual(sc.detail.tile["entity"], "light.a")
        win.dispose()


class GlassStaysOnAStillDesktop(unittest.TestCase):
    def test_live_panel_notices_motion_after_several_unchanged_captures(self):
        calls = []
        api = FakeApi("grid", tiles_of(1))
        def backdrop(kind, last_hash, pw, ph, *args):
            calls.append(time.monotonic())
            if 1 < len(calls) < 9:
                return {"unchanged": True, "hash": 1, "paced": False, "ms": 0}
            color = (20, 40, 60) if len(calls) == 1 else (80, 160, 120)
            return dict(w=pw, h=ph, blur_w=8, blur_h=8, blur_raw=bytes(color) * 64,
                        hash=len(calls), paced=False, ms=0)
        api.get_desktop_backdrop = backdrop
        win, sc = make_panel(api)
        try:
            sc.sampling = "live"
            boundary = time.monotonic()
            sc.start_glass()
            pump(450)
            self.assertGreaterEqual(len(calls), 9)
            self.assertEqual(sc.raw_latest.pixelColor(0, 0).getRgb()[:3], (80, 160, 120))
            recent = [t for t in calls if t >= boundary]
            self.assertLess(max(b-a for a,b in zip(recent,recent[1:])), .15)
        finally:
            win.dispose()

    def test_compositor_accepts_new_desktop_frames_while_the_panel_moves(self):
        from unittest.mock import patch, Mock
        from nativeui import dcomp
        from PySide6.QtGui import QImage
        calls = []
        api = FakeApi("grid", tiles_of(1))
        def backdrop(kind, last_hash, pw, ph, x, y, *args):
            calls.append((pw, ph, x, y))
            return dict(w=pw, h=ph, blur_w=8, blur_h=8, blur_raw=bytes([40, 80, 120]) * 64,
                        hash=len(calls), paced=True)
        api.get_desktop_backdrop = backdrop
        win, sc = make_panel(api)
        try:
            sc.style, sc.sampling, sc.moving = "liquid", "live", True
            sc._compositor_capture = (100, 200, sc.pw, sc.ph + 80)
            slider = Mock()
            with patch.object(dcomp, 'slider', return_value=slider):
                sc.start_glass()
                pump(150)
                self.assertGreaterEqual(len(calls), 3)
                slider.queue_glass.assert_called()
                self.assertIsInstance(slider.queue_glass.call_args.args[0], QImage)
                self.assertGreaterEqual(slider.queue_glass.call_count, 2)
                self.assertTrue(all(c == (sc.pw, sc.ph + 80, 100, 200) for c in calls[-3:]))
        finally:
            sc._compositor_capture = None
            win.dispose()

    def test_in_flight_old_backdrop_cannot_become_the_first_new_glass(self):
        import threading
        from PIL import Image
        entered, release=threading.Event(),threading.Event()
        calls=[]
        api=FakeApi("grid",[dict(id="t",entity="switch.a",domain="switch",room="插座",label="")])
        def backdrop(kind,last_hash,pw,ph,*args):
            index=len(calls)
            calls.append(index)
            if index==0:
                entered.set()
                release.wait(2)
            color=(200,20,20) if index==0 else (20,180,60)
            image=Image.new("RGB",(8,8),color)
            return dict(w=pw,h=ph,blur_w=8,blur_h=8,blur_raw=image.tobytes(),hash=str(index),paced=True)
        api.get_desktop_backdrop=backdrop
        win=detail.create_popover(api)
        card=win.native
        try:
            card.open_tile("t"); card.show(); card.start_glass()
            self.assertTrue(entered.wait(1))
            card.invalidate_glass()
            release.set()
            pump(300)
            self.assertIsNotNone(card.glass)
            self.assertEqual(card.latest.pixelColor(0,0).getRgb()[:3],(20,180,60))
            self.assertEqual(card._latest_generation,card._glass_generation)
        finally:
            release.set()
            card.stop()
            if card._glass_thread: card._glass_thread.join(1)
            win.dispose()
    """A window rebuilt at the same size keeps its glass even when no new picture of the desktop comes
    (a still desktop): the detail card lost its blur each time the volume of the speaker it shows moved."""

    def still_desktop(self, api):
        frame = {"blur_raw": bytes([90, 120, 160]) * (12 * 10), "blur_w": 12, "blur_h": 10, "hash": 7, "paced": True}
        shots = []

        def backdrop(kind, last_hash, pw, ph, *a, **k):
            shots.append(last_hash)
            if last_hash is None:                  # the first look, or one that was forced
                return dict(frame, w=pw, h=ph)
            time.sleep(0.05)
            return {"unchanged": True, "hash": 7, "paced": True}
        api.get_desktop_backdrop = backdrop
        return shots

    def test_card_keeps_its_glass_when_the_volume_changes(self):
        api = FakeApi()
        t = {"id": "t1", "entity": "media_player.s", "domain": "media_player", "room": "喇叭", "label": ""}
        api.tiles = [t]
        self.still_desktop(api)
        win = detail.create_popover(api)
        card = win.native
        pump(100)
        card.push_states([("media_player.s", {"state": "playing", "attributes": {"volume_level": 0.3}})])
        card.open_tile("t1")
        card.show()
        card.start_glass()
        pump(400)
        self.assertIsNotNone(card.glass)
        size = (card.pw, card.ph)
        for level in (0.35, 0.4, 0.45):            # Home Assistant answering the slider
            card.push_states([("media_player.s", {"state": "playing", "attributes": {"volume_level": level}})])
            pump(150)
            self.assertEqual((card.pw, card.ph), size)
            self.assertIsNotNone(card.glass)
        win.dispose()

    def test_settings_height_morph_keeps_the_existing_glass_canvas(self):
        api = FakeApi()
        t = {"id": "t1", "entity": "light.a", "domain": "light", "room": "燈", "label": ""}
        api.tiles = [t]
        shots = self.still_desktop(api)
        win = detail.create_popover(api)
        card = win.native
        pump(100)
        card.push_states([("light.a", {"state": "on", "attributes": {"brightness": 128}})])
        card.open_tile("t1")
        card.show()
        card.start_glass()
        pump(400)
        looks = shots.count(None)
        size = (card.pw, card.ph)
        original = card.glass
        before = card.transition_frame()
        card.set_edit(True)
        self.assertEqual(card.transition_frame(), before)
        self.assertEqual((card.pw, card.ph), size)
        self.assertIs(card.glass, original)
        self.assertEqual((card.glass.width(), card.glass.height()), (card.pw, card.ph))
        pump(600)
        self.assertEqual(card.transition_frame(), card.page_targets[True])
        self.assertEqual(card.transition_frame().width(), before.width())
        self.assertEqual(shots.count(None), looks)
        win.dispose()

    def test_panel_keeps_its_glass_when_the_preferences_are_pushed(self):
        api = FakeApi("grid", tiles_of(8))
        self.still_desktop(api)
        win, sc = make_panel(api)
        sc.start_glass()
        pump(400)
        self.assertIsNotNone(sc.glass)
        sc.apply_prefs(dict(api._prefs()))         # another window saved something
        pump(200)
        self.assertIsNotNone(sc.glass)
        win.dispose()


class FitsItsMonitor(unittest.TestCase):
    """The panel takes about the same share of any monitor, and never more than its work area."""

    def panel_on(self, w, h, scale, work_h=None, mode="home"):
        from unittest.mock import patch
        from nativeui import screens
        work_h = h - 48 * scale if work_h is None else work_h
        mon = screens.Monitor((0, 0, w, h), (0, 0, w, work_h), scale)
        with patch.object(screens, "monitor_at", lambda x, y: mon):
            win, sc = make_panel(FakeApi(mode, tiles_of(8)))
            sc.update_metrics()
            zoom, height = sc.zoom_css, sc.css_h * sc.zoom_css * scale
        win.dispose()
        return zoom, height

    def test_same_share_of_the_screen(self):
        self.assertAlmostEqual(self.panel_on(1920, 1080, 1.0)[0], panel.FLYOUT_ZOOM)
        # 1440p at 125 % is 1152 logical px high: a little larger, the same share of the screen
        zoom, height = self.panel_on(2560, 1440, 1.25)
        self.assertAlmostEqual(zoom, panel.FLYOUT_ZOOM * 1152 / 1080)
        self.assertAlmostEqual(height / 1440, self.panel_on(1920, 1080, 1.0)[1] / 1080, places=3)
        # a portrait monitor goes by its shorter side, as a landscape one does
        self.assertAlmostEqual(self.panel_on(1080, 1920, 1.0)[0], panel.FLYOUT_ZOOM)

    def test_within_limits(self):
        self.assertAlmostEqual(self.panel_on(3840, 2160, 1.0)[0], panel.FLYOUT_ZOOM * panel.FIT_RANGE[1])
        self.assertAlmostEqual(self.panel_on(1366, 768, 1.0)[0], panel.FLYOUT_ZOOM * panel.FIT_RANGE[0])

    def test_never_taller_than_the_work_area(self):
        zoom, height = self.panel_on(1920, 1080, 1.0, work_h=200)
        self.assertLessEqual(height, 200 - 2 * panel.FIT_MARGIN + 0.5)


class HeaderAndFlyout(unittest.TestCase):
    def test_reversal_refreshes_changed_desktop_pixels_without_replacing_material(self):
        from unittest.mock import patch
        from nativeui import dcomp
        api = FakeApi("home")
        color, captures = [40], []
        def backdrop(kind, last_hash, pw, ph, *args):
            captures.append(color[0])
            return dict(w=pw, h=ph, blur_w=8, blur_h=8,
                        blur_raw=bytes([color[0], 80, 110]) * 64,
                        hash=color[0], paced=True)
        api.get_desktop_backdrop = backdrop
        win, sc = make_panel(api)
        try:
            with patch.dict(os.environ, {"HA_WIDGET_DCOMP": "1"}):
                sc.style = "liquid"
                sc.sampling = "still"
                sc.flyout_enter()
                slider = sc._compositor_slider
                if slider is None:
                    self.skipTest("no DirectComposition here")
                material = slider.material
                with patch.object(material, 'update', wraps=material.update) as upload:
                    pump(60)
                    color[0] = 130
                    sc.flyout_leave()
                    self.assertEqual(sc._compositor_background[1].pixelColor(0, 0).red(), 130)
                    pump(25)
                    self.assertTrue(any(c.args[0].pixelColor(0, 0).red() == 130 for c in upload.call_args_list))
                    color[0] = 210
                    sc.flyout_enter()
                    self.assertEqual(sc._compositor_background[1].pixelColor(0, 0).red(), 210)
                    pump(400)
                    self.assertTrue(sc._compositor_resting)
                    self.assertIs(slider.material, material)
                    self.assertTrue(any(c.args[0].pixelColor(0, 0).red() == 210 for c in upload.call_args_list))
                before = len(captures)
                pump(120)
                self.assertLessEqual(len(captures) - before, 1)
        finally:
            win.dispose()

    def test_rapid_reversal_keeps_the_same_live_material(self):
        from unittest.mock import patch
        from nativeui import dcomp
        from PySide6.QtGui import QImage, QColor
        win, sc = make_panel(FakeApi("home"))
        try:
            with patch.dict(os.environ, {"HA_WIDGET_DCOMP": "1"}):
                sc.style = "liquid"
                sc.raw_latest = QImage(8, 8, QImage.Format_RGB888)
                sc.raw_latest.fill(QColor(60, 80, 100))
                sc.flyout_enter()
                slider = sc._compositor_slider
                if slider is None:
                    self.skipTest("no DirectComposition here")
                material = slider.material
                # A pump of 20 ms lasts 31 ms where Windows' timer keeps its 15.6 ms steps; a reversal's
                # short slide must not be finished by the clock meanwhile.
                sc._time_slide = lambda ms, real=sc._time_slide: real(ms * 10)
                with patch.object(slider, 'show', wraps=slider.show) as show:
                    bounds = sc.size()
                    for cycle in range(12):
                        pump(20)
                        sc.flyout_leave()
                        pump(20)
                        self.assertTrue(win.prepare_for_show())
                        sc.flyout_enter()
                        if cycle == 5:
                            sc.push_states([("light.a", {"state": "off", "attributes": {}})])
                            self.assertEqual(sc.size(), bounds)
                            self.assertEqual(sc._sliding[0], "enter")
                        self.assertIs(slider.material, material)
                    show.assert_not_called()
                del sc._time_slide                          # the last slide ends on its own clock again
                sc._time_slide(sc._sliding[1] + 30)
                pump(400)
                self.assertTrue(sc._compositor_resting)
                self.assertTrue(slider.shown)
                self.assertTrue(sc.isVisible())
                self.assertIs(slider.material, material)
        finally:
            win.dispose()

    def test_reopening_invalidates_native_exit_timer(self):
        from unittest.mock import patch
        from nativeui import dcomp
        win, sc = make_panel(FakeApi("home"))
        token = [1]
        finished = []
        try:
            with patch.dict(os.environ, {"HA_WIDGET_DCOMP": "1"}):
                sc.flyout_enter()
                pump(60)
                win.leave_and_hide(lambda: token[0] == 1, 210, lambda: finished.append(1))
                pump(35)
                token[0] = 2
                win.prepare_for_show()
                win.show()
                sc.flyout_enter()
                pump(420)
                self.assertTrue(sc.isVisible())
                self.assertEqual(finished, [])
                self.assertIsNone(sc._sliding)
                win.leave_and_hide(lambda: token[0] == 2, 210, lambda: finished.append(2))
                pump(250)
                self.assertFalse(sc.isVisible())
                self.assertEqual(finished, [2])
        finally:
            win.dispose()

    def test_opening_captures_fresh_background_at_exact_window_height(self):
        from unittest.mock import Mock
        from PySide6.QtGui import QImage, QColor
        win, sc = make_panel(FakeApi("home"))
        try:
            sc.style = "liquid"
            sc.raw_latest = QImage(8, 8, QImage.Format_RGB888)
            sc.raw_latest.fill(QColor(10, 20, 30))
            sc.api.get_desktop_backdrop = Mock(return_value=dict(
                w=sc.pw, h=sc.ph, blur_w=8, blur_h=8,
                blur_raw=bytes([90, 100, 110]) * 64))
            glass, card = sc._slide_layers((sc.pw, sc.ph), at=(100, 200))
            self.assertEqual(glass.pixelColor(sc.pw // 2, sc.ph // 2).red(), 90)
            sc.api.get_desktop_backdrop.assert_called_once()
            sc.raw_latest = sc.glass = None
            glass, card = sc._slide_layers((sc.pw, sc.ph), at=(100, 200))
            self.assertIsNotNone(glass)
            self.assertEqual(glass.pixelColor(sc.pw // 2, sc.ph // 2).red(), 90)
            sc._compositor_capture = (100, 200, sc.pw, sc.ph)
            fresh = QImage(8, 8, QImage.Format_RGB888)
            fresh.fill(QColor(130, 140, 150))
            sc._compositor_raw = (sc._compositor_capture, fresh, sc._compositor_epoch, time.monotonic())
            sc._on_glass()
            sc.api.get_desktop_backdrop.return_value = {"skip": True}
            glass, _ = sc._slide_layers((sc.pw, sc.ph), at=(100, 200))
            self.assertEqual(glass.pixelColor(sc.pw // 2, sc.ph // 2).red(), 130)
        finally:
            win.dispose()

    def test_late_background_from_previous_open_is_rejected(self):
        from unittest.mock import Mock
        from PySide6.QtGui import QImage
        win, sc = make_panel(FakeApi("home"))
        try:
            sc._compositor_capture = (100, 100, 400, 700)
            sc._compositor_epoch = 7
            sc._compositor_presented_at = 20.0
            slider = Mock()
            sc._compositor_slider = slider
            image = QImage(8, 8, QImage.Format_RGB888)
            for epoch, captured in [(6, 21.0), (7, 19.0)]:
                sc._compositor_raw = (sc._compositor_capture, image, epoch, captured)
                sc._on_glass()
                slider.queue_glass.assert_not_called()
            sc._compositor_raw = (sc._compositor_capture, image, 7, 22.0)
            sc._on_glass()
            slider.queue_glass.assert_called_once_with(image)
            self.assertEqual(sc._compositor_presented_at, 22.0)
        finally:
            win.dispose()

    def test_animated_backdrop_does_not_change_renderer_at_the_end(self):
        from unittest.mock import patch
        from nativeui import dcomp
        from PySide6.QtGui import QImage, QColor
        from PIL import Image, ImageChops
        from dxgi_capture import DesktopDuplication
        api = FakeApi("home")
        settings = dict(api._prefs(), glass_style="liquid", theme="dark")
        api._prefs = lambda: settings
        frozen = [False]
        calls = []
        def backdrop(kind, last_hash, pw, ph, *args):
            calls.append(time.monotonic())
            value = 70 if frozen[0] else 40 + len(calls) % 5 * 20
            return dict(w=pw, h=ph, blur_w=8, blur_h=8, blur_raw=bytes([value, 80, 110]) * 64,
                        hash=len(calls), paced=True)
        api.get_desktop_backdrop = backdrop
        win, sc = make_panel(api)
        try:
            with patch.dict(os.environ, {"HA_WIDGET_DCOMP": "1"}):
                slider = dcomp.slider()
                if slider is None:
                    self.skipTest("no DirectComposition here")
                sc.move(100, 100)
                dcomp._user32.SetWindowPos(sc.cache_hwnd(), -1, 0, 0, 0, 0, 0x13)
                sc.prepare_for_show()
                sc.flyout_enter()
                sc._slide_timer.stop()
                pump(210)
                frozen[0] = True
                pump(90)
                material = slider.material
                dcomp._user32.SetWindowDisplayAffinity(slider.hwnd, 0)
                capture = DesktopDuplication()
                rect = dcomp.window_rect(sc.cache_hwnd())
                def frame():
                    raw = capture.grab(*rect)[1]
                    img = QImage(raw, rect[2], rect[3], rect[2] * 4, QImage.Format_ARGB32).copy()
                    img = img.copy(30, sc.ph // 2, sc.pw - 60, sc.ph // 3)
                    return Image.frombytes('RGBA', (img.width(), img.height()), img.constBits().tobytes())
                before = frame()
                sc._finish_slide()
                pump(60)
                after = frame()
                self.assertTrue(sc._compositor_resting)
                self.assertIs(slider.material, material)
                self.assertTrue(slider.shown)
                self.assertGreater(len(calls), 8)
                self.assertLessEqual(max(hi for lo, hi in ImageChops.difference(before, after).getextrema()), 3)
        finally:
            dcomp._user32.SetWindowDisplayAffinity(slider.hwnd, 0x11) if slider is not None else None
            win.dispose()

    def test_live_compositor_glass_keeps_native_fields_and_rebuilds_working(self):
        from unittest.mock import patch
        from nativeui import dcomp
        from PySide6.QtGui import QImage, QColor
        api = FakeApi("home", [{"id": "sp", "entity": "media_player.s", "domain": "media_player", "room": "喇叭", "label": ""}])
        win, sc = make_panel(api)
        try:
            with patch.dict(os.environ, {"HA_WIDGET_DCOMP": "1"}):
                if dcomp.slider() is None:
                    self.skipTest("no DirectComposition here")
                sc.style = "liquid"
                sc.raw_latest = QImage(8, 8, QImage.Format_RGB888)
                sc.raw_latest.fill(QColor(60, 80, 100))
                sc.flyout_enter()
                pump(panel.ENTER_MS + 150)
                self.assertTrue(sc._compositor_resting)
                sc.open_detail("sp")
                pump(400)
                sc.detail.set_edit(True)
                pump(250)
                field = next(f for f in sc.fields if f.edit is not None and f.edit.isVisible())
                field.edit.setFocus()
                field.edit.setText("玻璃測試")
                material = dcomp.slider().material
                sc.push_states([("media_player.s", {"state": "playing", "attributes": {"volume_level": .3}})])
                pump(80)
                self.assertEqual(field.edit.text(), "玻璃測試")
                self.assertTrue(field.edit.isVisible())
                self.assertTrue(sc._compositor_resting)
                self.assertIs(dcomp.slider().material, material)
                win.hide()
                self.assertFalse(dcomp.slider().shown)
                self.assertIsNone(sc._compositor_capture)
        finally:
            win.dispose()

    def test_first_open_after_theme_change_starts_hidden_with_fresh_artwork(self):
        from unittest.mock import patch
        from nativeui import dcomp
        from PySide6.QtGui import QImage, QColor
        api = FakeApi("grid", tiles_of(1))
        win, sc = make_panel(api)
        try:
            with patch.dict(os.environ, {"HA_WIDGET_DCOMP": "1"}):
                if dcomp.slider() is None:
                    self.skipTest("no DirectComposition here")
                previous = None
                for theme in ("dark", "light", "dark"):
                    win.hide()
                    sc.apply_prefs(dict(api._prefs(), theme=theme, panel_theme="follow", glass_style="liquid"))
                    sc.raw_latest = QImage(8, 8, QImage.Format_RGB888)
                    sc.raw_latest.fill(QColor(60, 80, 100))
                    win.prepare_for_show()
                    self.assertEqual(sc.anim_alpha, 0)
                    self.assertIsNone(sc._sliding)
                    win.show()
                    sc.flyout_enter()
                    self.assertEqual(sc._sliding[0], "enter")
                    self.assertEqual(sc.anim_alpha, 0)
                    self.assertTrue(dcomp.slider().visible())
                    frame = sc.content_image()
                    if previous is not None:
                        self.assertNotEqual(frame.cacheKey(), previous.cacheKey())
                    previous = frame
                    self.assertEqual(sc._card_picture[0][5], theme)
                    pump(panel.ENTER_MS + 150)
                    self.assertIsNone(sc._sliding)
                    self.assertTrue(dcomp.slider().shown)
                    self.assertTrue(sc._compositor_resting)
        finally:
            win.dispose()

    def test_added_effects_keep_the_active_frame_clock(self):
        from unittest.mock import patch
        win, sc = make_panel(FakeApi("home"))
        try:
            with patch.object(sc.tweens.timer, "start", wraps=sc.tweens.timer.start) as start:
                sc.flyout_enter()
                sc.flyout_leave()
                sc.flyout_enter()
                start.assert_called_once()
        finally:
            win.dispose()

    def test_hidden_animation_pauses_and_state_rebuild_keeps_it_for_resume(self):
        win, sc = make_panel(FakeApi("home"))
        try:
            sc.home.toggle_category("light")
            pump(40)
            sc.hide()
            before = sc.home.cat_view.alpha, sc.home.cat_view.zoom
            self.assertFalse(sc.tweens.timer.isActive())
            pump(60)
            sc.push_states([("light.a", {"state": "off", "attributes": {}})])
            self.assertEqual((sc.home.cat_view.alpha, sc.home.cat_view.zoom), before)
            self.assertFalse(sc.tweens.timer.isActive())
            sc.show()
            self.assertEqual((sc.home.cat_view.alpha, sc.home.cat_view.zoom), before)
            self.assertTrue(sc.tweens.timer.isActive())
            pump(650)
            self.assertEqual(sc.home.cat_view.alpha, 1)
            self.assertFalse(sc.tweens.timer.isActive())
        finally:
            win.dispose()

    def test_cached_flyout_submits_its_frame_before_returning_to_event_loop(self):
        win, sc = make_panel(FakeApi("home"))
        try:
            sc._prepare_flyout_picture()
            sc.moving = True
            paints = []
            original = sc.paintEvent
            def paint(event):
                paints.append(event)
                original(event)
            sc.paintEvent = paint
            sc._paint_now()
            self.assertEqual(len(paints), 1)
        finally:
            win.dispose()

    def test_animation_timer_tracks_monitor_refresh_without_restarting_position(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        win, sc = make_panel(FakeApi("home"))
        try:
            for rate, interval in ((180,5), (100,10), (60,16)):
                with patch.object(sc, "screen", return_value=SimpleNamespace(refreshRate=lambda: rate)):
                    sc.flyout_leave()
                    before = sc.anim_dy, sc.anim_alpha
                    self.assertEqual(sc.tweens.timer.interval(), interval)
                    sc.flyout_enter()
                    self.assertEqual((sc.anim_dy, sc.anim_alpha), before)
            pump(410)
            self.assertFalse(sc.tweens.timer.isActive())
        finally:
            win.dispose()

    def test_glass_stays_fixed_inside_exact_moving_card_without_bottom_mask(self):
        from PySide6.QtGui import QImage, QPainter, QColor
        win, sc = make_panel(FakeApi("home"))
        try:
            glass = QImage(sc.pw, sc.ph, QImage.Format_ARGB32_Premultiplied)
            painter = QPainter(glass)
            for y in range(glass.height()):
                painter.fillRect(0, y, glass.width(), 1, QColor(y % 251, 50, 180))
            painter.end()
            sc.glass = glass
            from unittest.mock import patch
            foreground = QImage(sc.pw, sc.ph, QImage.Format_ARGB32_Premultiplied)
            foreground.fill(Qt.transparent)
            with patch.object(sc, "content_image", return_value=foreground):
                sc._prepare_flyout_picture()
            self.assertEqual(sc._flyout_glass, glass)
            sc.anim_alpha, sc.moving = 1, True
            shots = []
            for distance in (.1, .25):
                sc.anim_dy = sc.css_h * distance
                shots.append(sc.grab().toImage())
            x, y = int(shots[0].width()*.5), int(shots[0].height()*.65)
            self.assertGreater(shots[0].pixelColor(x,y).alpha(), 0)
            self.assertEqual(shots[0].pixelColor(x,y), shots[1].pixelColor(x,y))
            self.assertEqual(shots[1].pixelColor(x,int(shots[1].height()*.1)).alpha(), 0)
            self.assertGreater(shots[1].pixelColor(0, shots[1].height() - 1).alpha(), 0)
            top = round(sc.anim_dy * sc.scale)  # grab's QImage is in physical pixels
            self.assertEqual(shots[1].pixelColor(0, top).alpha(), 0)
            self.assertGreater(shots[1].pixelColor(x, top + 2).alpha(), 0)
        finally:
            win.dispose()

    def test_device_headers_share_scale_and_controls_have_primary_weight(self):
        from nativeui import controls, style
        win, sc = make_panel(FakeApi("home"))
        def walk(view):
            yield view
            for child in view.children:
                yield from walk(child)
        try:
            headers = []
            for entity in ("light.a", "climate.ac", "lock.d"):
                sc.open_detail("home:" + entity)
                holder = sc.detail_view.children[0]
                nodes = list(walk(holder))
                heading = next(v for v in holder.children[0].children
                               if isinstance(v, ui.Label) and v.size == style.TEXT["detail_title"][0])
                headers.append((heading.in_scene()[1], heading.in_scene()[2], heading.h))
                if entity == "light.a":
                    slider = next(v for v in nodes if isinstance(v, controls.TallSlider))
                    bar = next(v for v in nodes if isinstance(v, controls.ModeBar))
                    self.assertLess(bar.h, slider.h * .3)
                if entity == "climate.ac":
                    dial = next(v for v in nodes if isinstance(v, controls.Dial))
                    self.assertGreaterEqual(dial.w, 240)
                    steppers = [v for v in nodes if isinstance(v, ui.Button) and v.icon in ("mdi:minus", "mdi:plus")]
                    self.assertTrue(steppers)
                    self.assertTrue(all(v.h <= dial.h * .16 for v in steppers))
                sc.close_detail(animate=False)
            self.assertEqual(headers, [headers[0]] * 3)
        finally:
            win.dispose()

    def test_flyout_reuses_one_composite_even_when_state_and_glass_arrive(self):
        win, sc = make_panel(FakeApi("grid", tiles_of(1)))
        try:
            sc.anim_dy, sc.anim_alpha = sc.css_h, 0
            sc.flyout_enter()
            picture = sc._flyout_picture
            self.assertIsNotNone(picture)
            sc.push_states([("light.l0", {"state": "on", "attributes": {}})])
            sc._on_glass()
            self.assertIs(sc._flyout_picture, picture)
            self.assertTrue(sc._deferred_glass)
            sc.flyout_leave()
            sc.flyout_enter()
            self.assertIs(sc._flyout_picture, picture)
            pump(panel.ENTER_MS + 160)
            self.assertIsNone(sc._flyout_picture)
            self.assertFalse(sc._deferred_glass)
            self.assertEqual(sc.states["light.l0"]["state"], "on")
        finally:
            win.dispose()

    def test_flyout_slides_in_and_out_from_behind_the_bottom_edge_without_fading(self):
        win, sc = make_panel(FakeApi("grid", tiles_of(1)))
        try:
            sc.anim_dy, sc.anim_alpha = sc.css_h, 0
            sc.flyout_enter()
            self.assertEqual((sc.anim_dy, sc.anim_alpha), (sc.css_h, 1))
            pump(panel.ENTER_MS + 80)
            self.assertEqual((sc.anim_dy, sc.anim_alpha), (0, 1))
            sc.flyout_leave()
            pump(45)
            self.assertGreater(sc.anim_dy, 0)
            self.assertEqual(sc.anim_alpha, 1)
            pump(panel.LEAVE_MS + 60)
            self.assertEqual((sc.anim_dy, sc.anim_alpha), (sc.css_h, 1))
        finally:
            win.dispose()

    def test_animation_uses_raw_backdrop_instead_of_the_resting_glass_mask(self):
        from PySide6.QtGui import QColor, QImage
        from unittest.mock import Mock
        win, sc = make_panel(FakeApi("grid", tiles_of(1)))
        try:
            raw = QImage(8, 8, QImage.Format_RGB888)
            raw.fill(QColor(20, 40, 60))
            sc.latest = raw
            sc.mask = None
            sc._make_glass()
            self.assertEqual(sc.glass.pixelColor(0, sc.ph - 1).alpha(), 0)
            old_size = sc.size()
            for glass_style in ("classic", "windows", "liquid"):
                sc.style = glass_style
                sc.raw_latest = raw
                glass, card = sc._slide_layers((sc.pw, sc.ph + 80))
                self.assertEqual(glass.pixelColor(0, sc.ph - 1).alpha(), 255)
                self.assertEqual(glass.pixelColor(0, sc.ph + 40).getRgb(), (20, 40, 60, 255))
                self.assertEqual(card.pixelColor(sc.pw // 2, sc.ph + 40).alpha(), 0)
                self.assertEqual(sc.size(), old_size)
            sc.api.get_desktop_backdrop = Mock(return_value={"blur_raw": bytes([90, 80, 70]) * 4,
                                                            "blur_w": 2, "blur_h": 2})
            glass, _ = sc._slide_layers((sc.pw, sc.ph + 80), at=(100, 200))
            self.assertEqual(glass.pixelColor(0, sc.ph + 40).getRgb(), (90, 80, 70, 255))
            sc.api.get_desktop_backdrop.assert_called_once_with("flyout", None, sc.pw, sc.ph + 80, 100, 200, 0)
        finally:
            win.dispose()

    def test_glass_compositor_keeps_original_motion_and_uses_an_inner_corner_clip(self):
        from PySide6.QtGui import QImage
        from unittest.mock import Mock, patch
        win, sc = make_panel(FakeApi("grid", tiles_of(1)))
        try:
            for theme in ("light", "dark"):
                for glass_style in ("classic", "liquid", "windows"):
                    sc.theme, sc.style = theme, glass_style
                    sc.t = panel.render.tokens(theme, style=glass_style)
                    sc.glass = QImage(sc.pw, sc.ph, QImage.Format_ARGB32_Premultiplied)
                    sc.glass.fill(Qt.white)
                    original = sc.glass.copy()
                    glass, card = sc._slide_layers((sc.pw + 1, sc.ph + 1))
                    self.assertEqual(glass.pixelColor(0, sc.ph - 1).alpha(), 255)
                    self.assertEqual(glass.pixelColor(sc.pw, sc.ph).alpha(), 0)
                    slider = Mock()
                    with patch.object(dcomp, "slider", return_value=slider), \
                            patch.object(dcomp, "window_rect", return_value=(0, 0, sc.pw, sc.ph)), \
                            patch.object(panel.screens, "monitor_at", return_value=Mock(
                                rect=(0, 0, sc.pw, sc.ph + 160), work=(0, 0, sc.pw, sc.ph + 80))), \
                            patch.object(sc, "cache_hwnd", return_value=1):
                        self.assertTrue(sc._compositor_slide(True))
                        self.assertEqual(slider.show.call_args.args[0][3], sc.ph + 80)
                        radius = slider.show.call_args.args[4]
                        self.assertEqual(radius, min(sc.card_radius(), sc.css_w / 2, sc.css_h / 2) * sc.scale)
                        columns = slider.show.call_args.kwargs["columns"]
                        path = panel.render.squircle(0, 0, sc.css_w * sc.scale, sc.css_h * sc.scale, radius)
                        from PySide6.QtCore import QPointF
                        for left, right, top, bottom in columns:
                            for x in (left + .001, right - .001):
                                self.assertTrue(path.contains(QPointF(x, top + .001)))
                                self.assertTrue(path.contains(QPointF(x, bottom - .001)))
                        slider.slide.assert_called_with(sc.ph + 80 + 24, 0.0, panel.ENTER_MS / 1000, panel.ENTER_CURVE)
                        sc._finish_slide()
                        slider.next_composition.reset_mock()
                        self.assertTrue(sc._compositor_slide(False))
                        slider.slide.assert_called_with(0.0, sc.ph + 80 + 24, panel.LEAVE_MS / 1000, panel.LEAVE_CURVE)
                        self.assertFalse(slider.show.call_args.kwargs["wait"])
                        slider.next_composition.assert_not_called()
                        sc._finish_slide()
                    self.assertEqual(sc.glass, original)
        finally:
            win.dispose()

    def test_compositor_slide_hands_the_panel_over_and_back(self):
        from unittest import mock
        with mock.patch.dict(os.environ, {"HA_WIDGET_DCOMP": "1"}):
            win, sc = make_panel(FakeApi("grid", tiles_of(1)))
            try:
                dcomp._state["failed"] = False
                slider = dcomp.slider()
                if slider is None:
                    self.skipTest("no DirectComposition here")
                from PySide6.QtGui import QColor, QImage
                sc.style = "liquid"
                sc.raw_latest = QImage(8, 8, QImage.Format_RGB888)
                sc.raw_latest.fill(QColor(80, 120, 160))
                sc.anim_dy, sc.anim_alpha = sc.css_h, 0
                sc.flyout_enter()
                self.assertEqual(sc._sliding[0], "enter")
                self.assertTrue(slider.shown)
                self.assertIsNotNone(slider.material)
                material = slider.material
                self.assertTrue(sc.moving)
                columns = list(slider.mask_columns)
                bounds = sc.size()
                sc.states["light.l0"] = {"state": "on", "attributes": {}}
                sc.rebuild()
                self.assertEqual(sc._sliding[0], "enter")
                self.assertEqual(slider.mask_columns, columns)
                self.assertEqual(sc.size(), bounds)
                self.assertIs(slider.material, material)
                pump(panel.ENTER_MS + 35)
                self.assertIsNotNone(sc._compositor_capture)  # keep sampling through the final blend
                pump(115)
                self.assertIsNone(sc._sliding)
                self.assertIsNotNone(sc._compositor_capture)
                self.assertTrue(sc._compositor_resting)
                self.assertTrue(slider.shown)
                self.assertIs(slider.material, material)
                self.assertFalse(slider.material_timer.isActive())
                self.assertEqual((sc.anim_dy, sc.anim_alpha), (0, 1))
                self.assertFalse(sc.moving)
                sc.flyout_leave()
                self.assertEqual(sc._sliding[0], "leave")
                self.assertTrue(slider.shown)
                pump(panel.LEAVE_MS + 150)
                self.assertIsNone(sc._sliding)
                self.assertFalse(slider.shown)
                self.assertEqual(sc.anim_alpha, 0)
                self.assertFalse(sc.moving)
                for kind, start in (("enter", sc.flyout_enter), ("leave", sc.flyout_leave),
                                    ("enter", sc.flyout_enter), ("leave", sc.flyout_leave)):
                    start()                             # (the helper, hidden, lies where it was last put)
                    self.assertEqual(sc._sliding[0], kind)
                    self.assertTrue(slider.visible(), kind)
                    pump(panel.ENTER_MS + 150)
                    self.assertEqual(slider.shown, kind == "enter")
                sc.flyout_enter()                       # reversed before it ends: the first is taken to its end
                sc.flyout_leave()
                self.assertEqual(sc._sliding[0], "leave")
                pump(panel.LEAVE_MS + 150)
                self.assertFalse(slider.shown)
            finally:
                win.dispose()

    def test_header_controls_and_title_share_a_row_after_state_rebuild(self):
        from nativeui import style
        win, sc = make_panel(FakeApi("grid", tiles_of(1)))
        try:
            content = detail.DetailContent(sc, lambda: sc.prefs, sc.states, lambda: None,
                                           on_close=lambda: None)
            content.open("t0")
            for area in ("", "客廳"):
                content.area_of = lambda entity: area
                for edit in (False, True):
                    content.edit = edit
                    for update in range(2):
                        sc.states["light.l0"] = {"state": "on" if update else "off", "attributes": {}}
                        tree = content.build(max_h=560, fit=True)
                        buttons = [v for v in tree.children if isinstance(v, ui.Button)]
                        heading = next(v for v in tree.children if isinstance(v, ui.Label) and v.text == "L0")
                        self.assertEqual(len(buttons), 2)
                        self.assertEqual([b.icon_size for b in buttons], [22, 22])
                        for button in buttons:
                            self.assertEqual(button.y + button.h / 2, heading.y + heading.h / 2)
                        self.assertEqual(heading.size, style.TEXT["detail_title"][0])
                        self.assertLessEqual(heading.x + heading.w, buttons[-1].x - 8)
        finally:
            win.dispose()

    def test_flyout_reversal_and_state_updates_keep_current_position_and_size(self):
        win, sc = make_panel(FakeApi("grid", tiles_of(1)))
        try:
            size = (sc.width(), sc.height(), sc.css_w, sc.css_h)
            sc.flyout_leave()
            pump(45)
            self.assertGreater(sc.anim_dy, 0)
            current = sc.anim_dy, sc.anim_alpha
            sc.flyout_enter()
            self.assertEqual((sc.anim_dy, sc.anim_alpha), current)
            sc.states["light.l0"] = {"state": "on", "attributes": {}}
            sc.rebuild()
            self.assertEqual((sc.anim_dy, sc.anim_alpha), current)
            self.assertEqual(sc.anim_zoom, 1)
            self.assertEqual((sc.width(), sc.height(), sc.css_w, sc.css_h), size)
            pump(panel.ENTER_MS + 120)
            self.assertAlmostEqual(sc.anim_dy, 0)
            self.assertAlmostEqual(sc.anim_alpha, 1)
            self.assertFalse(sc.moving)
        finally:
            win.dispose()


if __name__ == "__main__":
    unittest.main()
