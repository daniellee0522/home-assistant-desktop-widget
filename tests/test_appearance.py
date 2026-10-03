"""What a tile is shown as (nativeui/appearance.py): its icon's family when its kind of device can take it,
and the colour, the words and the detail that follow from that, the same everywhere."""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from nativeui import appearance as A, detail, render  # noqa: E402


def T(domain, icon=""):
    return {"id": "t", "entity": domain + ".x", "domain": domain, "room": "X", "label": "old label", "icon": icon}


ON = {"state": "on", "attributes": {}}


class Families(unittest.TestCase):
    def test_a_switch_takes_the_family_of_its_icon(self):
        self.assertEqual(A.family(T("switch")), "switch")
        self.assertEqual(A.family(T("switch", "mdi:floor-lamp")), "light")
        self.assertEqual(A.family(T("switch", "mdi:lock-smart")), "lock")
        self.assertEqual(A.family(T("switch", "mdi:cctv")), "switch")         # not an on/off thing: only a picture
        self.assertEqual(A.family(T("switch", "mdi:abacus")), "switch")       # a typed MDI name: only a picture

    def test_other_devices_keep_their_own_family(self):
        self.assertEqual(A.family(T("light", "mdi:power-socket-us")), "light")
        self.assertTrue(A.supports(T("light"), "mdi:ceiling-light"))
        self.assertFalse(A.supports(T("light"), "mdi:fan"))

    def test_colour_and_words_follow_the_family(self):
        tc = render.tokens("dark")
        lamp = T("switch", "mdi:floor-lamp")
        self.assertEqual(render.icon_color(lamp, ON, True, "dark", tc), render.ACCENT["yellow"])
        self.assertEqual(render.icon_color(T("switch"), ON, True, "dark", tc), render.ACCENT["blue"])
        lock = T("switch", "mdi:lock-smart")
        self.assertEqual(render.state_text(lock, ON), "已解鎖")
        self.assertEqual(render.icon_name(lock, ON), "mdi:lock-open-variant")   # its open shape
        self.assertEqual(render.state_text(T("switch"), {"state": "off"}), "關閉")

    def test_the_words_under_a_tile_are_its_state_not_a_label(self):
        self.assertEqual(render.state_text(T("light"), {"state": "on", "attributes": {"brightness": 128}}), "50%")
        self.assertEqual(render.state_text(T("climate"), {"state": "cool", "attributes": {}}), "冷氣")
        self.assertEqual(render.state_text(T("lock"), {"state": "locked"}), "已上鎖")

    def test_every_icon_offered_exists(self):
        for fam, (_, icons) in A.FAMILIES.items():
            for icon in icons:
                ok = render.mdi_path(icon[4:]) if icon.startswith("mdi:") else icon in render._icon_table()
                self.assertTrue(ok, icon)


class EditPanel(unittest.TestCase):
    def setUp(self):
        import test_native_panel as TP
        self.TP = TP
        api = TP.FakeApi()
        api.tiles = [T("switch")]
        self.win = detail.create_popover(api)
        self.card = self.win.native
        TP.pump(100)
        self.card.push_states([("switch.x", {"state": "on", "attributes": {"friendly_name": "書房開關"}})])
        self.card.open_tile("t")
        self.card.content.set_edit(True)
        TP.pump(100)

    def tearDown(self):
        self.win.dispose()

    def texts(self):
        out = []

        def walk(v):
            if hasattr(v, "text") and isinstance(getattr(v, "text"), str):
                out.append(v.text)
            for c in v.children:
                walk(c)
        walk(self.card.root)
        return out

    def test_it_parts_what_changes_the_look_from_what_is_only_a_picture(self):
        texts = self.texts()
        self.assertIn("外觀", texts)
        self.assertIn("其他圖示", texts)
        self.assertNotIn("類別名稱", texts)
        self.assertIn("重置", texts)

    def test_choosing_a_lamp_makes_it_a_lamp_and_reset_brings_it_back(self):
        content = self.card.content
        content.set_icon("mdi:floor-lamp")
        self.assertEqual(A.family(content.tile), "light")
        content.tile["room"] = "我的燈"
        content.reset()
        self.assertEqual(content.tile["icon"], "")
        self.assertEqual(content.tile["room"], "書房開關")


if __name__ == "__main__":
    unittest.main()
