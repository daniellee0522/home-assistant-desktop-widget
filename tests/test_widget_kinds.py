"""The other kinds of desktop widget (nativeui/kinds.py): the weather, a camera, a chart. What
each shows of its devices, that it fetches what it needs besides states, what a tap does, and the editor:
a kind is dragged from its palette, keeps its size and its devices, and its picker offers what it shows."""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QPoint, Qt                                  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter                      # noqa: E402
from PySide6.QtTest import QTest                                        # noqa: E402
from PySide6.QtWidgets import QApplication                              # noqa: E402

app = QApplication.instance() or QApplication([])

import config                                                           # noqa: E402
import test_native_widget as TW                                         # noqa: E402
from nativeui import kinds, render                                      # noqa: E402


def T(entity, domain, name="X"):
    return {"id": entity, "entity": entity, "domain": domain, "room": name, "label": "", "icon": ""}


class KindApi(TW.FakeApi):
    def __init__(self, tiles, kind, size="2x4"):
        super().__init__(tiles, size)
        self.kind = kind

    def _prefs(self):
        p = super()._prefs()
        p["widgets"][0]["kind"] = self.kind
        return p

    def get_forecast(self, entity):
        self.calls.append(("forecast", entity))
        return [{"datetime": "2026-10-03T04:00:00+00:00", "condition": "rainy", "temperature": 27, "templow": 24}]

    def get_picture(self, path):
        self.calls.append(("picture", path))
        img = QImage(32, 18, QImage.Format_RGB32)
        img.fill(QColor(40, 90, 140))
        from PySide6.QtCore import QBuffer, QByteArray
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QBuffer.WriteOnly)
        img.save(buf, "PNG")
        return bytes(data)

    def get_history(self, entity, hours=24):
        self.calls.append(("history", entity))
        return {"ok": True, "points": [[i * 60.0, 20 + i % 5] for i in range(50)]}


def make(tiles, kind, size="2x4"):
    api = KindApi(tiles, kind, size)
    win = TW.nw.NativeWidget(api, "w1")
    surf = win.native
    surf.move(100, 100)
    surf.relayout()
    surf.show()
    TW.pump(150)
    return api, win, surf


class WhatEachShows(unittest.TestCase):
    def test_only_the_devices_its_kind_takes(self):
        tiles = [T("light.a", "light"), T("weather.home", "weather"), T("weather.two", "weather"),
                 T("sensor.a", "sensor"), T("sensor.b", "sensor"), T("sensor.c", "sensor"), T("sensor.d", "sensor"),
                 T("scene.x", "scene"), T("script.y", "script")]
        self.assertEqual([t["entity"] for t in kinds.shown("weather", tiles)], ["weather.home"])
        self.assertEqual(len(kinds.shown("chart", tiles)), 2)
        self.assertEqual(kinds.shown("tiles", tiles), tiles)

    def test_every_kind_draws_in_every_size_light_and_dark(self):
        states = {"weather.home": {"state": "sunny", "attributes": {"temperature": 30}},
                  "sensor.a": {"state": "21.5", "attributes": {"unit_of_measurement": "°C"}}}
        tiles = [T("weather.home", "weather"), T("camera.c", "camera"), T("sensor.a", "sensor"), T("scene.x", "scene")]
        for kind in ("weather", "camera", "chart"):
            for size in render.SIZES:
                for theme in ("light", "dark"):
                    w, h = render.widget_size(size)
                    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
                    img.fill(0)
                    p = QPainter(img)
                    kinds.draw_widget(p, kind, size, tiles, states, theme, extras={"history": {}})
                    p.end()
                    centre = img.pixelColor(w // 2, h // 2)
                    self.assertGreater(centre.alpha(), 0, (kind, size, theme))

    def test_config_keeps_the_kind_in_its_own_size(self):
        w = config._clean_widget({"id": "a", "size": "4x4", "kind": "weather", "tiles": []})
        self.assertEqual((w["kind"], w["size"]), ("weather", config.KIND_SIZE["weather"]))
        self.assertEqual(config._clean_widget({"id": "a", "kind": "nonsense"})["kind"], "tiles")
        self.assertEqual(config._clean_widget({"id": "a", "size": "4x4"})["size"], "4x4")
        self.assertEqual(kinds.KIND_SIZE, config.KIND_SIZE)

    def test_an_empty_one_asks_for_its_devices_and_is_its_button(self):
        for kind in ("weather", "camera", "chart"):
            w, h = render.widget_size(kinds.KIND_SIZE[kind])
            img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
            img.fill(0)
            p = QPainter(img)
            button = kinds.draw_widget(p, kind, kinds.KIND_SIZE[kind], [], {}, "dark")
            p.end()
            self.assertEqual((button.width(), button.height()), (w, h), kind)


class OnTheDesktop(unittest.TestCase):
    def test_weather_fetches_its_forecast_and_a_tap_opens_its_detail(self):
        api, win, surf = make([T("light.a", "light"), T("weather.home", "weather")], "weather")
        TW.pump(300)
        self.assertEqual([t["entity"] for t in surf.tiles], ["weather.home"])
        self.assertIn(("forecast", "weather.home"), api.calls)
        self.assertEqual(surf.extras["forecast"][0]["condition"], "rainy")
        self.assertEqual(surf.glass_tiles(), [])
        s = surf.scale / surf.devicePixelRatioF()
        at = QPoint(round(100 * s), round(100 * s))
        QTest.mouseClick(surf, Qt.LeftButton, pos=at)
        TW.pump(150)
        self.assertTrue([c for c in api.calls if c[0] == "popover" and c[1] == "weather.home"])
        n = len([c for c in api.calls if c[0] == "forecast"])
        surf.refresh_extras()                                # not again before it is due
        TW.pump(100)
        self.assertEqual(len([c for c in api.calls if c[0] == "forecast"]), n)
        TW.done(win)

    def test_camera_takes_pictures_but_not_while_dimmed(self):
        api, win, surf = make([T("camera.c", "camera")], "camera")
        TW.pump(300)
        self.assertIsNotNone(surf.extras.get("picture"))
        surf._extras_at.clear()
        surf.set_dim(True)
        n = len([c for c in api.calls if c[0] == "picture"])
        surf.refresh_extras()
        TW.pump(100)
        self.assertEqual(len([c for c in api.calls if c[0] == "picture"]), n)
        TW.done(win)

    def test_chart_reads_each_sensors_day(self):
        api, win, surf = make([T("sensor.a", "sensor"), T("sensor.b", "sensor")], "chart")
        TW.pump(300)
        self.assertEqual(sorted(surf.extras["history"]), ["sensor.a", "sensor.b"])
        TW.done(win)

    def test_a_scene_is_a_tile_of_an_ordinary_widget_and_runs_when_tapped(self):
        self.assertEqual(config._clean_widget({"id": "a", "kind": "shortcuts", "size": "2x4",
                                               "tiles": [T("scene.home", "scene")]})["kind"], "tiles")
        api, win, surf = make([T("scene.home", "scene", "回家"), T("light.a", "light")], "tiles", "2x2")
        self.assertEqual(len(surf.rects), 2)
        QTest.mouseClick(surf, Qt.LeftButton, pos=TW.centre(surf, 0))
        TW.pump(150)
        self.assertTrue([c for c in api.calls if c[0] == "service" and c[3] == "scene.home"])
        TW.done(win)

    def test_dimmed_every_kind_is_clear_glass(self):
        """While dimmed the weather's sky and the camera's picture give way to clear glass, as tiles do."""
        states = {"weather.home": {"state": "sunny", "attributes": {"temperature": 30}}}
        w, h = render.widget_size("2x4")
        for kind, tile in (("weather", T("weather.home", "weather")), ("camera", T("camera.c", "camera"))):
            out = []
            for dim in (False, True):
                img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
                img.fill(0)
                p = QPainter(img)
                kinds.draw_widget(p, kind, "2x4", [tile], states, "dark", dim=dim, extras={})
                p.end()
                out.append(img.pixelColor(w // 2, h - 40).alpha())
            self.assertGreater(out[0], 200, kind)               # the sky, the dark of a camera
            self.assertLess(out[1], 160, kind)                  # glass to see through


class ClockCalendarPlayer(unittest.TestCase):
    def test_a_clock_and_a_calendar_need_no_devices(self):
        for kind in ("clock", "calendar"):
            w, h = render.widget_size(kinds.KIND_SIZE[kind])
            img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
            img.fill(0)
            p = QPainter(img)
            button = kinds.draw_widget(p, kind, kinds.KIND_SIZE[kind], [], {}, "light")
            p.end()
            self.assertIsNone(button, kind)                     # not an empty widget asking for devices
            self.assertGreater(img.pixelColor(30, h // 2).alpha(), 200, kind)   # its solid face

    def test_the_clocks_ring_turns_without_a_jump(self):
        import datetime
        def ring(now):
            hand = kinds.clock_hand(now)
            return [kinds.tick_alpha((hand - i) % 60) for i in range(60)]
        base = datetime.datetime(2026, 10, 4, 9, 41, 20)
        end_of_last = ring(base - datetime.timedelta(microseconds=1))
        start = ring(base)
        self.assertLess(max(abs(a - b) for a, b in zip(end_of_last, start)), 0.01)   # a second begins: no jump
        settled = ring(base + datetime.timedelta(seconds=kinds.HAND_MOVE_S + 0.05))
        self.assertAlmostEqual(settled[20], 1.0)                 # this second's tick the darkest
        self.assertAlmostEqual(settled[21], 0.12)                # the coming one the lightest
        steps = [ring(base + datetime.timedelta(seconds=kinds.HAND_MOVE_S * k / 10))[20] for k in range(11)]
        self.assertTrue(all(b >= a for a, b in zip(steps, steps[1:])))              # it darkens smoothly
        self.assertLess(max(b - a for a, b in zip(steps, steps[1:])), 0.2)

    def test_a_clock_takes_any_font_installed_and_keeps_its_digits_inside_the_ring(self):
        from nativeui import fonts
        W, H = render.widget_size("2x2")
        chosen = [f for f in fonts.installed() if f["name"] in ("Segoe UI Bold", "Arial", "Consolas")]
        self.assertTrue(chosen)
        for f in chosen:
            self.assertIsNotNone(kinds.clock_face(f), f["name"])
            box = kinds.clock_digits(W, H, "10:29", f).boundingRect()
            self.assertAlmostEqual(box.center().x(), W / 2, delta=2, msg=f["name"])
            self.assertLess(box.width(), W - 100, f["name"])                # inside the ring
        gone = {"file": "C:/nowhere/gone.ttf", "name": "Gone"}
        self.assertEqual(kinds.clock_face(gone), kinds.clock_face(None))  # a font gone: the default again

    def test_a_clocks_font_is_kept_in_its_settings(self):
        f = {"file": "C:/Windows/Fonts/arial.ttf", "name": "Arial"}
        self.assertEqual(config._clean_widget({"id": "a", "kind": "clock", "font": f})["font"], f)
        self.assertNotIn("font", config._clean_widget({"id": "a", "kind": "tiles", "font": f}))
        self.assertNotIn("font", config._clean_widget({"id": "a", "kind": "clock", "font": "x"}))

    def test_a_clock_on_the_desktop_draws_only_its_ring_each_second(self):
        api, win, surf = make([], "clock", "2x2")
        TW.pump(300)
        drawn = []
        real = surf._draw
        surf._draw = lambda dim: drawn.append(dim) or real(dim)
        TW.pump(2200)
        self.assertTrue(surf.second_timer.isActive())
        self.assertLessEqual(len(drawn), 1)                      # the face and digits: once a minute at most
        surf.hide()
        TW.pump(100)
        self.assertFalse(surf.second_timer.isActive())           # hidden: no more frames
        TW.done(win)

    def test_the_player_plays_and_skips_from_the_desktop(self):
        st = {"media_player.s": {"state": "paused", "attributes": {"media_title": "T", "media_duration": 100,
                                                                   "media_position": 10}}}
        api, win, surf = make([T("media_player.s", "media_player")], "media")
        surf.push_states(list(st.items()))
        TW.pump(200)
        actions = {a: r for r, a in surf.kind_buttons}
        self.assertEqual(sorted(actions), ["next", "play_pause", "previous", "source"])
        s = surf.scale / surf.devicePixelRatioF()
        for action in ("play_pause", "next"):
            c = actions[action].center()
            QTest.mouseClick(surf, Qt.LeftButton, pos=QPoint(round(c.x() * s), round(c.y() * s)))
            TW.pump(150)
        services = [c[2] for c in api.calls if c[0] == "service"]
        self.assertEqual(services, ["media_play_pause", "media_next_track"])
        self.assertEqual(surf.states["media_player.s"]["state"], "playing")     # shown at once
        self.assertFalse([c for c in api.calls if c[0] == "popover"])           # a button is not a tap
        TW.done(win)


class PlayerOnTheDesktop(unittest.TestCase):
    def test_with_nothing_playing_its_buttons_are_inert(self):
        self.assertEqual(kinds.media_controls({"state": "off", "attributes": {}}), set())
        self.assertEqual(kinds.media_controls({"state": "idle", "attributes": {"supported_features": 16 | 32 | 1}}),
                         set())
        self.assertEqual(kinds.media_controls({"state": "paused", "attributes": {"supported_features": 1 | 32}}),
                         {"play_pause", "next"})                   # and only what the player can do
        api, win, surf = make([T("media_player.s", "media_player")], "media")
        surf.push_states([("media_player.s", {"state": "off", "attributes": {}})])
        TW.pump(200)
        self.assertEqual([a for _, a in surf.kind_buttons], ["source"])
        TW.done(win)

    def test_play_takes_the_place_now_so_the_bar_does_not_jump(self):
        import datetime
        long_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=30)).isoformat()
        st = {"state": "paused", "attributes": {"media_duration": 300, "media_position": 40,
                                                "media_position_updated_at": long_ago}}
        patch = kinds.play_pause_patch(st)
        now = dict(st, **patch)
        self.assertEqual(now["state"], "playing")
        self.assertAlmostEqual(kinds.media_position(now)[0], 40, delta=1)      # not 40 s + half an hour

    def test_the_bar_is_dragged_to_a_place_and_a_tap_opens_nothing(self):
        st = {"state": "playing", "attributes": {"media_title": "T", "media_duration": 200, "media_position": 0,
                                                 "supported_features": 2}}
        api, win, surf = make([T("media_player.s", "media_player")], "media")
        surf.push_states([("media_player.s", st)])
        for _ in range(40):                                    # until it has been drawn (the suite runs busy)
            TW.pump(50)
            if any(a == "seek" for _, a in surf.kind_buttons):
                break
        bar = next(r for r, a in surf.kind_buttons if a == "seek")
        s = surf.scale / surf.devicePixelRatioF()
        y = round(bar.center().y() * s)
        QTest.mousePress(surf, Qt.LeftButton, pos=QPoint(round((bar.x() + 4) * s), y))
        QTest.mouseMove(surf, QPoint(round((bar.x() + bar.width() * 0.75) * s), y))
        TW.pump(50)
        self.assertAlmostEqual(surf.extras["seek_to"], 150, delta=6)         # shown while dragged
        QTest.mouseRelease(surf, Qt.LeftButton, pos=QPoint(round((bar.x() + bar.width() * 0.75) * s), y))
        TW.pump(150)
        seek = [c for c in api.calls if c[0] == "service" and c[2] == "media_seek"]
        self.assertAlmostEqual(seek[-1][4]["seek_position"], 150, delta=6)
        QTest.mouseClick(surf, Qt.LeftButton, pos=QPoint(round(60 * s), round(60 * s)))   # on the cover
        TW.pump(150)
        self.assertFalse([c for c in api.calls if c[0] == "popover"])
        TW.done(win)


class InTheEditor(unittest.TestCase):
    def setUp(self):
        import test_native_settings as TS
        self.TS = TS
        self.api, self.win, self.sc = TS.make()

    def tearDown(self):
        self.win.dispose()

    def walk(self, view, cls):
        out = []

        def go(v):
            if v.__class__.__name__ == cls:
                out.append(v)
            for c in v.children:
                go(c)
        go(view)
        return out

    def offer(self, ents):
        self.api.get_entities = lambda: ents
        self.sc.open_picker()
        TW.pump(200)
        self.assertEqual(self.sc.entities, ents)

    def kind_widget(self, kind, tiles):
        w = {"id": "k1", "size": kinds.KIND_SIZE[kind], "kind": kind, "tiles": tiles, "x": 0, "y": 0}
        self.sc.prefs["widgets"].append(w)
        self.sc.open_editor("k1")
        TW.pump(100)
        return w

    def test_each_kind_is_dragged_from_the_palette(self):
        sc = self.sc
        sc.open_editor("")
        TW.pump(100)
        items = {v.kind: v for v in self.walk(sc.root, "KindItem")}
        self.assertEqual(sorted(items), sorted(kinds.KINDS[1:]))
        sc.body_scroll.scroll_to(items["weather"].abs_pos()[1] - 100)
        TW.pump(50)
        x, y, k = items["weather"].in_scene()
        s = sc.scale / sc.devicePixelRatioF()
        QTest.mousePress(sc, Qt.LeftButton, pos=QPoint(round((x + 30) * s), round((y + 20) * s)))
        TW.pump(700)
        QTest.mouseRelease(sc, Qt.LeftButton, pos=QPoint(round((x + 30) * s), round((y + 20) * s)))
        self.assertIn(("drag", "2x4", "weather"), self.api.calls)

    def test_a_kind_keeps_its_size_and_offers_no_other(self):
        sc = self.sc
        w = self.kind_widget("weather", [T("weather.home", "weather")])
        self.assertFalse([c for c in self.walk(sc.root, "Chip") if c.text in ("1x1", "4x4")])
        sc.set_size("4x4")
        self.assertEqual(w["size"], kinds.KIND_SIZE["weather"])
        self.assertFalse([c for c in self.api.calls if c[0] == "size"])

    def test_one_weather_chosen_takes_the_place_of_the_last(self):
        sc = self.sc
        w = self.kind_widget("weather", [T("weather.home", "weather")])
        self.assertTrue(sc.can_add())                         # its button changes the weather
        self.offer([{"entity_id": "weather.x", "domain": "weather", "name": "W", "state": {}},
                    {"entity_id": "light.b", "domain": "light", "name": "L", "state": {}}])
        rows = self.walk(sc.root, "PickerRow")
        self.assertEqual([r.e["entity_id"] for r in rows], ["weather.x"])
        rows[0].on_click(None)                                # chosen at once
        self.assertEqual(sc.page, "editor")
        self.assertEqual([t["entity"] for t in w["tiles"]], ["weather.x"])

    def test_the_picker_ticks_several_up_to_what_fits(self):
        sc = self.sc
        w = self.kind_widget("chart", [])
        self.offer([{"entity_id": "sensor.%s" % c, "domain": "sensor", "name": c, "state": {}} for c in "abc"])
        rows = self.walk(sc.root, "PickerRow")
        for r in rows:
            r.on_click(None)
        self.assertEqual([e["entity_id"] for e in sc.picker_sel], ["sensor.a", "sensor.b"])   # a chart shows two
        rows[0].on_click(None)                                # ticked again: not any more
        self.assertEqual([e["entity_id"] for e in sc.picker_sel], ["sensor.b"])
        self.assertTrue(sc.picker_add.interactive)
        sc.picker_add.on_click(None)
        self.assertEqual(sc.page, "editor")
        self.assertEqual([t["entity"] for t in w["tiles"]], ["sensor.b"])

    def test_select_all_of_a_group(self):
        sc = self.sc
        sc.open_editor("w1")
        self.offer([{"entity_id": "switch.%s" % c, "domain": "switch", "name": c, "state": {}} for c in "abc"])
        every = [b for b in self.walk(sc.root, "Button") if b.text == "全選"]
        self.assertEqual(len(every), 1)
        every[0].on_click(None)
        self.assertEqual(len(sc.picker_sel), 3)
        before = len(sc.current_tiles())
        sc.picker_add.on_click(None)
        self.assertEqual(len(sc.current_tiles()), before + 3)


class TheMap(unittest.TestCase):
    def test_a_click_on_a_widget_of_the_map_selects_it_and_moves_nothing(self):
        import test_native_settings as TS
        api, win, sc = TS.make()
        moved = []
        api.move_widget = lambda i, x, y: moved.append((i, x, y)) or {"x": x, "y": y}
        sc.open_editor("w2")
        sc.layout = api.get_layout()
        sc.build()
        TW.pump(150)
        box = [v for v in InTheEditor.walk(None, sc.root, "MapBox") if v.wd["id"] == "w1"][0]
        sc.body_scroll.scroll_to(box.abs_pos()[1] - 150)
        TW.pump(50)
        s = sc.scale / sc.devicePixelRatioF()
        x, y, k = box.in_scene()
        at = QPoint(round((x + box.w * k / 2) * s), round((y + box.h * k / 2) * s))
        QTest.mousePress(sc, Qt.LeftButton, pos=at)
        QTest.mouseMove(sc, QPoint(at.x() + 2, at.y() + 1))       # a hand that trembles
        QTest.mouseRelease(sc, Qt.LeftButton, pos=at)
        TW.pump(150)
        self.assertEqual(moved, [])
        self.assertEqual(sc.widget_id, "w1")
        win.dispose()


class DraggingInTheEditor(unittest.TestCase):
    """A tile carried in the preview, or a row of the list, shows where it will go before it is let go."""

    def setUp(self):
        import test_native_settings as TS
        self.api, self.win, self.sc = TS.make()
        self.sc.open_editor("w1")
        TW.pump(150)
        self.s = self.sc.scale / self.sc.devicePixelRatioF()

    def tearDown(self):
        self.win.dispose()

    def at(self, view, x, y):
        vx, vy, k = view.in_scene()
        return QPoint(round((vx + x * k) * self.s), round((vy + y * k) * self.s))

    def test_the_preview_makes_room_while_a_tile_is_carried(self):
        sc = self.sc
        pv = sc.preview
        z = pv.zoom_k
        r0, r2 = pv.rects[0], pv.rects[2]
        QTest.mousePress(sc, Qt.LeftButton, pos=self.at(pv, (r0[0] + 60) * z, (r0[1] + 60) * z))
        for f in (0.5, 1.0):
            QTest.mouseMove(sc, self.at(pv, (r0[0] + 60 + (r2[0] - r0[0]) * f) * z,
                                        (r0[1] + 60 + (r2[1] - r0[1]) * f) * z))
            TW.pump(40)
        self.assertTrue(pv.dragging())
        self.assertEqual(pv.press["to"], 2)
        self.assertEqual([t["id"] for t in pv.order()], ["t1", "t2", "t0"])      # as it will be
        self.assertEqual([t["id"] for t in sc.current_tiles()], ["t0", "t1", "t2"])   # not yet
        QTest.mouseRelease(sc, Qt.LeftButton, pos=self.at(pv, (r2[0] + 60) * z, (r2[1] + 60) * z))
        TW.pump(100)
        self.assertEqual([t["id"] for t in sc.current_tiles()], ["t1", "t2", "t0"])

    def test_a_row_carried_down_the_list_moves_the_others_up(self):
        sc = self.sc
        rows = sorted(self.walk(sc.root), key=lambda r: r.index)
        first = rows[0]
        QTest.mousePress(sc, Qt.LeftButton, pos=self.at(first, 120, 20))
        for dy in (20, 60, 100):
            QTest.mouseMove(sc, self.at(first, 120, 20 + dy))
            TW.pump(40)
        self.assertTrue(first.lifted)
        self.assertEqual(first.press["to"], 2)
        TW.pump(250)
        self.assertEqual([r.goal for r in rows[1:]], [0, 46])                   # they made room
        QTest.mouseRelease(sc, Qt.LeftButton, pos=self.at(first, 120, 20))
        TW.pump(100)
        self.assertEqual([t["id"] for t in sc.current_tiles()], ["t1", "t2", "t0"])

    def walk(self, view):
        out = []

        def go(v):
            if v.__class__.__name__ == "TileRow":
                out.append(v)
            for c in v.children:
                go(c)
        go(view)
        return out


if __name__ == "__main__":
    unittest.main()
