"""The natively drawn tray panel and detail card (nativeui/panel.py, homeview.py, homeedit.py, detail.py),
against a stand-in Api: taps and holds on tiles, the capsules, the rooms, editing, the card's controls."""
import os
import sys
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt                                          # noqa: E402
from PySide6.QtWidgets import QApplication                             # noqa: E402

app = QApplication.instance() or QApplication([])

from nativeui import detail, panel                                      # noqa: E402
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

    def resize_popover_window(self, *a):
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
    def test_tap_toggles_and_hold_opens_the_card(self):
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
        popovers = [c for c in api.calls if c[0] == "popover"]
        self.assertTrue(popovers)
        self.assertEqual(popovers[0][1][5], "flyout")
        win.dispose()

    def test_more_than_two_rows_scroll_a_row_at_a_time(self):
        win, sc = make_panel(FakeApi("grid", tiles_of(14)))
        sv = sc.grid_scroll
        self.assertGreater(sv.max_offset(), 0)
        sc._grid_wheel(sv, -120)
        self.assertEqual(sv.offset, sv.row)
        win.dispose()


class HomeMode(unittest.TestCase):
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
    def make(self, tile, state):
        api = FakeApi()
        api.tiles = [tile]
        win = detail.create_popover(api)
        card = win.native
        pump(100)
        card.push_states([(tile["entity"], state)])
        card.open_tile(tile["id"])
        card.show()
        pump(50)
        return api, win, card

    def test_light_card_brightness(self):
        t = {"id": "t1", "entity": "light.a", "domain": "light", "room": "燈", "label": ""}
        api, win, card = self.make(t, {"state": "on", "attributes": {"brightness": 128}})
        sliders = []

        def walk(v):
            if v.__class__.__name__ == "Slider":
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


if __name__ == "__main__":
    unittest.main()
