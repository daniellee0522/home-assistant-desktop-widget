"""The natively drawn desktop widget (nativeui/widget.py): what a tap, a hold, a drag, a wheel,
a dimmed widget and a push of preferences do. The Api is a stand-in that records its calls; the
window is real (a Qt widget), the pointer is Qt's own test input.
"""
import os
import sys
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QPoint, Qt                                  # noqa: E402
from PySide6.QtTest import QTest                                       # noqa: E402
from PySide6.QtWidgets import QApplication                             # noqa: E402

app = QApplication.instance() or QApplication([])

from nativeui import render, widget as nw                              # noqa: E402


def tile(i, domain, entity=None, **kw):
    return dict({"id": "t%d" % i, "domain": domain, "entity": entity or "%s.e%d" % (domain, i),
                 "room": "T%d" % i, "label": ""}, **kw)


class FakeApi:
    def __init__(self, tiles, size="2x4", **prefs):
        self.tiles = tiles
        self.size = size
        self.prefs = dict({"theme": "light", "language": "zh-TW", "glass_style": "classic", "zoom": 100,
                           "glass_sampling": "still", "lock_position": False, "liquid_blur": 0,
                           "system_glass_active": {}}, **prefs)
        self.calls = []
        self._cfg = {"widgets": [{"id": "w1"}], "ha_token": "x"}

    def _prefs(self):
        return dict(self.prefs, widgets=[{"id": "w1", "size": self.size, "tiles": self.tiles}])

    @staticmethod
    def _widget_kind(wid):
        return "w:" + wid

    def _all_tiles(self):
        return self.tiles

    def call_service(self, domain, service, entity, extra=None):
        self.calls.append(("service", domain, service, entity, extra))
        return {"ok": True}

    def open_popover(self, tile_id, x, y, w, h, kind):
        self.calls.append(("popover", tile_id, x, y, w, h, kind))

    def open_settings_window(self):
        self.calls.append(("settings",))

    def wake(self):
        self.calls.append(("wake",))
        return True

    def move_window(self, x, y, kind):
        self.calls.append(("move", x, y, kind))

    def get_desktop_backdrop(self, *a, **k):
        return {"skip": True, "retry_ms": 60000}

    def fetch_initial_states(self):
        return {}

    def ui_ready(self, kind=None):
        return True


def pump(ms=60):
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def make(tiles, size="2x4", states=None, **prefs):
    api = FakeApi(tiles, size, **prefs)
    win = nw.NativeWidget(api, "w1")
    surf = win.native
    surf.move(100, 100)
    surf.relayout()
    surf.show()
    pump()
    surf.relayout()
    if states:
        surf.push_states(list(states.items()))
        pump()
    return api, win, surf


def centre(surf, i):
    x, y, w, h = surf.rects[i]
    s = surf.scale / surf.devicePixelRatioF()
    return QPoint(round((x + w / 2) * s), round((y + h / 2 - surf.scroll) * s))


def done(win):
    win.native.stop()
    win.native.close()
    pump(20)


class TileForms(unittest.TestCase):
    def test_form_by_count(self):
        for count, form in ((8, "small"), (4, "bar"), (2, "big"), (1, "big")):
            tiles = [tile(i, "light") for i in range(count)]
            _, win, surf = make(tiles)
            self.assertEqual(surf.form, form, count)
            done(win)

    def test_window_has_the_widgets_size(self):
        _, win, surf = make([tile(0, "light")], zoom=100)
        cw, ch = render.widget_size("2x4")
        self.assertEqual((surf.pw, surf.ph), (round(cw * surf.dpi), round(ch * surf.dpi)))
        done(win)


class Taps(unittest.TestCase):
    def test_tap_toggles_a_light_and_shows_it_at_once(self):
        t = tile(0, "light", "light.desk")
        api, win, surf = make([t], states={"light.desk": {"state": "off", "attributes": {}}})
        QTest.mouseClick(surf, Qt.LeftButton, pos=centre(surf, 0))
        pump(100)
        self.assertIn(("service", "light", "toggle", "light.desk", {}), api.calls)
        self.assertEqual(surf.states["light.desk"]["state"], "on")
        done(win)

    def test_tap_on_a_lock_locks_and_unlocks(self):
        t = tile(0, "lock", "lock.door")
        api, win, surf = make([t], states={"lock.door": {"state": "locked", "attributes": {}}})
        QTest.mouseClick(surf, Qt.LeftButton, pos=centre(surf, 0))
        pump(100)
        self.assertIn(("service", "lock", "unlock", "lock.door", {}), api.calls)
        done(win)

    def test_a_sensor_does_nothing_when_tapped(self):
        t = tile(0, "sensor", "sensor.temp")
        api, win, surf = make([t], states={"sensor.temp": {"state": "21", "attributes": {}}})
        QTest.mouseClick(surf, Qt.LeftButton, pos=centre(surf, 0))
        pump(100)
        self.assertFalse([c for c in api.calls if c[0] == "service"])
        done(win)

    def test_scene_calls_turn_on_and_flashes(self):
        t = tile(0, "scene", "scene.movie")
        api, win, surf = make([t], states={"scene.movie": {"state": "scening", "attributes": {}}})
        QTest.mouseClick(surf, Qt.LeftButton, pos=centre(surf, 0))
        pump(100)
        self.assertIn(("service", "scene", "turn_on", "scene.movie", {}), api.calls)
        self.assertTrue(surf.flash)
        done(win)

    def test_climate_tap_switches_the_mode(self):
        t = tile(0, "climate", "climate.ac", on_mode="heat")
        api, win, surf = make([t, tile(1, "light")] * 1,
                              states={"climate.ac": {"state": "off", "attributes": {}}})
        QTest.mouseClick(surf, Qt.LeftButton, pos=centre(surf, 0))
        pump(100)
        self.assertIn(("service", "climate", "set_hvac_mode", "climate.ac", {"hvac_mode": "heat"}), api.calls)
        done(win)

    def test_climate_buttons_on_a_bar_step_the_temperature(self):
        t = tile(0, "climate", "climate.ac", temp_step=0.5)
        tiles = [t, tile(1, "light"), tile(2, "light"), tile(3, "light")]       # four tiles: bars
        api, win, surf = make(tiles, states={"climate.ac": {"state": "cool",
                                                              "attributes": {"temperature": 24}}})
        self.assertEqual(surf.form, "bar")
        x, y, w, h = surf.rects[0]
        for rect, sign in render.mini_buttons("bar", w, h):
            if sign > 0:
                s = surf.scale / surf.devicePixelRatioF()
                QTest.mouseClick(surf, Qt.LeftButton, pos=QPoint(round((x + rect.center().x()) * s),
                                                                 round((y + rect.center().y()) * s)))
        pump(100)
        self.assertIn(("service", "climate", "set_temperature", "climate.ac", {"temperature": 24.5}), api.calls)
        self.assertFalse([c for c in api.calls if c[2:3] == ("set_hvac_mode",)])
        done(win)


class Holds(unittest.TestCase):
    def test_hold_opens_the_detail_card_and_does_not_toggle(self):
        t = tile(0, "light", "light.desk")
        api, win, surf = make([t, tile(1, "light")], states={"light.desk": {"state": "off", "attributes": {}}})
        QTest.mousePress(surf, Qt.LeftButton, pos=centre(surf, 0))
        pump(600)
        QTest.mouseRelease(surf, Qt.LeftButton, pos=centre(surf, 0))
        pump(150)
        popovers = [c for c in api.calls if c[0] == "popover"]
        self.assertEqual(len(popovers), 1)
        self.assertEqual(popovers[0][1], "t0")
        self.assertEqual(popovers[0][6], "w:w1")
        self.assertFalse([c for c in api.calls if c[0] == "service"])
        done(win)

    def test_right_click_opens_the_detail_card(self):
        t = tile(0, "lock", "lock.door")
        api, win, surf = make([t, tile(1, "light")], states={"lock.door": {"state": "locked", "attributes": {}}})
        QTest.mouseClick(surf, Qt.RightButton, pos=centre(surf, 0))
        pump(150)
        self.assertEqual([c[1] for c in api.calls if c[0] == "popover"], ["t0"])
        done(win)

    def test_a_lock_is_not_opened_by_holding(self):
        t = tile(0, "lock", "lock.door")
        api, win, surf = make([t, tile(1, "light")], states={"lock.door": {"state": "locked", "attributes": {}}})
        QTest.mousePress(surf, Qt.LeftButton, pos=centre(surf, 0))
        pump(600)
        QTest.mouseRelease(surf, Qt.LeftButton, pos=centre(surf, 0))
        pump(150)
        self.assertFalse([c for c in api.calls if c[0] == "popover"])
        done(win)


class Drag(unittest.TestCase):
    def test_a_press_in_the_gap_drags(self):
        api, win, surf = make([tile(i, "light") for i in range(8)])
        s = surf.scale / surf.devicePixelRatioF()
        gap = QPoint(round((render.PAD + render.CELL_W + render.GAP / 2) * s), round(render.PAD * s / 2 + 2))
        QTest.mousePress(surf, Qt.LeftButton, pos=gap)
        pump(30)
        self.assertTrue(win.hwnd())
        done(win)

    def test_locked_widget_does_not_drag(self):
        api, win, surf = make([tile(i, "light") for i in range(8)], lock_position=True)
        self.assertTrue(surf.locked)
        done(win)


class Dimming(unittest.TestCase):
    def test_dim_eases_in_and_the_first_touch_only_wakes(self):
        t = tile(0, "light", "light.desk")
        api, win, surf = make([t, tile(1, "light")], states={"light.desk": {"state": "off", "attributes": {}}})
        win.send("set_dim", True)
        pump(900)
        self.assertEqual(surf.dim_t, 1.0)
        QTest.mouseClick(surf, Qt.LeftButton, pos=centre(surf, 0))
        pump(100)
        self.assertIn(("wake",), api.calls)
        self.assertFalse([c for c in api.calls if c[0] == "service"])
        win.send("set_dim", False)
        pump(500)
        self.assertEqual(surf.dim_t, 0.0)
        done(win)


class Wheel(unittest.TestCase):
    def test_more_tiles_than_fit_scroll(self):
        tiles = [tile(i, "light") for i in range(12)]
        api, win, surf = make(tiles)
        self.assertGreater(surf.scroll_max, 0)
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QWheelEvent
        ev = QWheelEvent(QPointF(50, 50), QPointF(50, 50), QPoint(0, 0), QPoint(0, -120),
                         Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        app.sendEvent(surf, ev)
        self.assertGreater(surf.scroll, 0)
        done(win)


class Preferences(unittest.TestCase):
    def test_pushed_prefs_change_size_theme_and_tiles(self):
        api, win, surf = make([tile(i, "light") for i in range(8)])
        prefs = dict(api._prefs(), theme="dark", glass_style="liquid", zoom=150)
        prefs["widgets"] = [{"id": "w1", "size": "4x4", "tiles": [tile(i, "light") for i in range(3)]}]
        win.send("apply_prefs", prefs)
        pump(100)
        self.assertEqual((surf.size_key, surf.zoom, surf.theme, surf.style), ("4x4", 150, "dark", "liquid"))
        self.assertEqual(surf.form, "big")                     # three tiles in sixteen cells
        cw, ch = render.widget_size("4x4")
        self.assertEqual(surf.pw, round(cw * 1.5 * surf.dpi))
        done(win)

    def test_push_batch_updates_the_states(self):
        api, win, surf = make([tile(0, "light", "light.desk")])
        win.send("push_states", [["light.desk", {"state": "on", "attributes": {}}]])
        win.send("no_such_thing", 1)                  # what a window has no use for is ignored
        pump(100)
        self.assertEqual(surf.states["light.desk"]["state"], "on")
        done(win)

    def test_empty_widget_button_opens_settings(self):
        api, win, surf = make([])
        pump(100)
        self.assertIsNotNone(surf.empty_button)
        r = surf.empty_button
        s = surf.scale / surf.devicePixelRatioF()
        QTest.mouseClick(surf, Qt.LeftButton, pos=QPoint(round(r.center().x() * s), round(r.center().y() * s)))
        pump(150)
        self.assertIn(("settings",), api.calls)
        done(win)


class Drawing(unittest.TestCase):
    def test_every_style_theme_and_form_draws(self):
        from PySide6.QtGui import QImage, QPainter
        states = {"light.e0": {"state": "on", "attributes": {}},
                  "climate.e1": {"state": "cool", "attributes": {"temperature": 24}}}
        for style in ("classic", "liquid", "windows"):
            for theme in ("light", "dark"):
                for count in (8, 4, 2, 1, 0):
                    tiles = [tile(0, "light"), tile(1, "climate")] + [tile(i, "sensor") for i in range(2, 8)]
                    tiles = tiles[:count]
                    img = QImage(678, 334, QImage.Format_ARGB32_Premultiplied)
                    img.fill(0)
                    p = QPainter(img)
                    render.draw_widget(p, "2x4", tiles, states, theme, None, 1.0, False, style)
                    render.draw_widget(p, "2x4", tiles, states, theme, None, 1.0, True, style)
                    p.end()
                    self.assertNotEqual(img.pixelColor(300, 5).alpha(), -1)

    def test_unknown_domains_are_read_only(self):
        self.assertTrue(render.is_readonly("weather"))
        self.assertFalse(render.is_readonly("light"))


if __name__ == "__main__":
    unittest.main()
