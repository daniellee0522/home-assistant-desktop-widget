"""The other kinds of desktop widget (nativeui/kinds.py): the weather, a camera, a chart, shortcuts. What
each shows of its devices, that it fetches what it needs besides states, what a tap does, and the editor
that chooses the kind."""
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
        self.assertEqual(len(kinds.shown("chart", tiles)), 3)
        self.assertEqual([t["entity"] for t in kinds.shown("shortcuts", tiles)], ["scene.x", "script.y"])
        self.assertEqual(kinds.shown("tiles", tiles), tiles)

    def test_every_kind_draws_in_every_size_light_and_dark(self):
        states = {"weather.home": {"state": "sunny", "attributes": {"temperature": 30}},
                  "sensor.a": {"state": "21.5", "attributes": {"unit_of_measurement": "°C"}}}
        tiles = [T("weather.home", "weather"), T("camera.c", "camera"), T("sensor.a", "sensor"), T("scene.x", "scene")]
        for kind in ("weather", "camera", "chart", "shortcuts"):
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

    def test_config_keeps_the_kind(self):
        w = config._clean_widget({"id": "a", "size": "2x2", "kind": "weather", "tiles": []})
        self.assertEqual(w["kind"], "weather")
        self.assertEqual(config._clean_widget({"id": "a", "kind": "nonsense"})["kind"], "tiles")


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

    def test_a_shortcut_runs_when_tapped(self):
        api, win, surf = make([T("scene.home", "scene", "回家"), T("light.a", "light")], "shortcuts", "2x2")
        self.assertEqual(len(surf.rects), 1)                 # the light is not a shortcut
        QTest.mouseClick(surf, Qt.LeftButton, pos=TW.centre(surf, 0))
        TW.pump(150)
        self.assertTrue([c for c in api.calls if c[0] == "service" and c[3] == "scene.home"])
        TW.done(win)


class InTheEditor(unittest.TestCase):
    def test_choosing_a_kind_keeps_what_it_shows_and_the_picker_follows(self):
        import test_native_settings as TS
        api, win, sc = TS.make()
        w = sc.settings_widget()
        w["tiles"] = [T("light.a", "light"), T("weather.home", "weather")]
        sc.open_editor(w["id"])
        TW.pump(100)
        sc.set_kind("weather")
        self.assertEqual(w["kind"], "weather")
        self.assertEqual([t["entity"] for t in w["tiles"]], ["weather.home"])
        self.assertFalse(sc.can_add())                       # one weather is all it takes
        sc.entities = [{"entity_id": "weather.x", "domain": "weather", "name": "W", "state": {}},
                       {"entity_id": "light.b", "domain": "light", "name": "L", "state": {}}]
        w["tiles"] = []
        from nativeui.ui import View
        host = View(0, 0, 300, 0)
        sc.fill_picker(host)
        offered = []

        def walk(v):
            if v.__class__.__name__ == "PickerRow":
                offered.append(v.e["entity_id"])
            for c in v.children:
                walk(c)
        walk(host)
        self.assertEqual(offered, ["weather.x"])
        win.dispose()


if __name__ == "__main__":
    unittest.main()
