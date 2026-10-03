"""The natively drawn Settings window (nativeui/settings.py, editor.py): the connection fields, the choices, the
widget editor and the picker, against a stand-in Api."""
import os
import sys
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication                             # noqa: E402

app = QApplication.instance() or QApplication([])

from nativeui import settings                                           # noqa: E402


class FakeApi:
    def __init__(self):
        self.calls = []

    def _prefs(self):
        tiles = [{"id": "t%d" % i, "entity": "light.l%d" % i, "domain": "light", "room": "L%d" % i, "label": ""}
                 for i in range(3)]
        return {"theme": "light", "language": "zh-TW", "glass_style": "classic", "zoom": 100, "panel_theme": "follow",
                "liquid_blur": 0, "glass_mode": "fast", "glass_sampling": "live", "dim_when_idle": True,
                "dim_after_sec": 120, "lock_position": False, "system_glass_ok": False,
                "widgets": [{"id": "w1", "size": "2x4", "tiles": tiles}, {"id": "w2", "size": "2x2", "tiles": []}],
                "panel": {"mode": "grid", "tiles": None, "home_tiles": []}}

    def bootstrap(self):
        return {"config": {"ha_url": "http://ha:8123", "ha_token": "tok", "start_on_boot": False}, "connected": True}

    def get_layout(self):
        return {"monitors": [{"x": 0, "y": 0, "w": 1920, "h": 1080}],
                "widgets": [{"id": "w1", "size": "2x4", "x": 100, "y": 100, "w": 440, "h": 217, "visible": True}]}

    def fetch_initial_states(self):
        return {"light.l0": {"state": "on", "attributes": {}}}

    def get_entities(self):
        return [{"entity_id": "light.x", "domain": "light", "name": "客廳燈", "state": {"state": "on"}}]

    def resize_settings_window(self, *a):
        pass

    def backdrop_armed(self):
        pass

    def save_prefs(self, c):
        self.calls.append(("prefs", c))

    def save_panel(self, p):
        self.calls.append(("panel", p))

    def save_widgets(self, w):
        self.calls.append(("widgets", w))

    def test_connection(self, u, t):
        return {"ok": True, "detail": ""}

    def save_ha_config(self, u, t):
        self.calls.append(("ha", u, t))

    def close_settings_window(self):
        self.calls.append(("close",))

    def set_widget_size(self, i, s):
        self.calls.append(("size", i, s))

    def remove_widget(self, i):
        self.calls.append(("remove", i))

    def move_widget(self, i, x, y):
        return {"x": x, "y": y}

    def begin_widget_drag(self, s, kind="tiles"):
        self.calls.append(("drag", s) if kind == "tiles" else ("drag", s, kind))
        return {"id": "w9"}

    def set_start_on_boot(self, on):
        self.calls.append(("boot", on))
        return {"ok": True}


def pump(ms=80):
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def make():
    api = FakeApi()
    win = settings.create_settings(api)
    sc = win.native
    pump(100)
    sc.layout = api.get_layout()
    sc.build()
    sc.show()
    pump()
    return api, win, sc


def find(view, cls_name, pred=lambda v: True):
    out = []

    def walk(v):
        if v.__class__.__name__ == cls_name and pred(v):
            out.append(v)
        for c in v.children:
            walk(c)
    walk(view)
    return out


class Screens(unittest.TestCase):
    def test_choices_are_saved(self):
        api, win, sc = make()
        selects = find(sc.root, "Select")
        theme = next(s for s in selects if s.value == "light")
        theme.pick("dark")
        pump(100)
        self.assertIn(("prefs", {"theme": "dark"}), api.calls)
        win.dispose()

    def test_checkbox_and_slider(self):
        api, win, sc = make()
        lock = next(c for c in find(sc.root, "CheckRow") if "鎖定" in c.text)
        lock._toggle(None)
        pump(100)
        self.assertIn(("prefs", {"lock_position": True}), api.calls)
        zoom = next(s for s in find(sc.root, "Slider") if s.lo == 50)
        zoom.on_commit(150)
        pump(100)
        self.assertIn(("prefs", {"zoom": 150}), api.calls)
        win.dispose()

    def test_connection_is_saved_on_close(self):
        api, win, sc = make()
        sc.url_field.set_text("http://other:8123")
        sc.close_settings()
        pump(150)
        self.assertIn(("ha", "http://other:8123", "tok"), api.calls)
        self.assertIn(("close",), api.calls)
        win.dispose()

    def test_liquid_blur_slider_only_for_liquid(self):
        api, win, sc = make()
        self.assertFalse([s for s in find(sc.root, "Slider") if s.hi == 100 and s.step == 5])
        sc.set_glass_style("liquid")
        pump(100)
        self.assertTrue([s for s in find(sc.root, "Slider") if s.hi == 100 and s.step == 5])
        win.dispose()


class Editor(unittest.TestCase):
    def test_sizes_remove_and_reorder(self):
        api, win, sc = make()
        sc.open_editor("")
        pump(100)
        sc.layout = api.get_layout()
        sc.build()
        self.assertEqual(sc.page, "editor")
        self.assertEqual(sc.css_w, 800)
        sc.set_size("4x4")
        pump(100)
        self.assertIn(("size", "w1", "4x4"), api.calls)
        sc.move_tile(0, 2)
        self.assertEqual([t["id"] for t in sc.current_tiles()], ["t1", "t2", "t0"])
        sc.remove_tile_at(0)
        self.assertEqual([t["id"] for t in sc.current_tiles()], ["t2", "t0"])
        pump(100)
        self.assertTrue([c for c in api.calls if c[0] == "widgets"])
        win.dispose()

    def test_palette_makes_a_widget(self):
        api, win, sc = make()
        sc.open_editor("")
        sc.drag_new_widget("2x2")
        pump(700)
        self.assertIn(("drag", "2x2"), api.calls)
        sc.drag_new_kind("camera")
        pump(700)
        self.assertIn(("drag", "2x4", "camera"), api.calls)
        win.dispose()

    def test_panel_list_is_its_own(self):
        api, win, sc = make()
        sc.open_editor("")
        sc.select_widget("__panel")
        pump(100)
        self.assertIsInstance(sc.prefs["panel"]["tiles"], list)
        self.assertEqual(len(sc.prefs["panel"]["tiles"]), 3)
        sc.follow_widgets()
        self.assertIsNone(sc.prefs["panel"]["tiles"])
        win.dispose()

    def test_picker_adds_a_tile(self):
        api, win, sc = make()
        sc.open_editor("")
        sc.entities = api.get_entities()
        sc.return_page = "editor"
        sc.page = "picker"
        sc.build()
        self.assertEqual(sc.css_w, 340)
        sc.add_entity(sc.entities[0])
        self.assertEqual(sc.page, "editor")
        self.assertIn("light.x", [t["entity"] for t in sc.current_tiles()])
        win.dispose()


if __name__ == "__main__":
    unittest.main()
