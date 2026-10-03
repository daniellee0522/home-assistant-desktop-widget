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
        self.assertEqual(type(sc.detail_view).__name__, "Backing")
        win.dispose()

    def test_a_small_panel_grows_for_it_and_shrinks_back(self):
        api, win, sc = self.open_speaker(n=2)
        base = sc.base_css
        self.assertGreater(sc.css_w, base[0])                       # two tiles are narrower than the card
        self.assertGreaterEqual(sc.css_h, base[1])
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
        self.assertTrue(1.5 < k <= 2.0, k)
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

    def test_resized_card_is_given_glass_at_once_and_a_new_picture(self):
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
        card.set_edit(True)                        # a taller card
        self.assertIsNotNone(card.glass)           # the last picture, stretched, until the new one
        self.assertEqual((card.glass.width(), card.glass.height()), (card.pw, card.ph))
        pump(400)
        self.assertGreater(shots.count(None), looks)   # and a new picture was taken for the new size
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


if __name__ == "__main__":
    unittest.main()
