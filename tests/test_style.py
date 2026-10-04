"""The house style (nativeui/style.py): every scrolling box fades where there is more, and the screens' text
comes from its roles."""
import os
import re
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from types import SimpleNamespace

app = QApplication.instance() or QApplication([])

from nativeui import controls, style, ui  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Style(unittest.TestCase):
    def test_short_room_names_never_fade_and_long_names_still_do(self):
        from nativeui import render
        scene = SimpleNamespace(t=ui.ui_tokens("light"))
        for text in ("入口", "客廳", "臥室", "Entry"):
            images = []
            width = ui.text_width(text, style.font("home_room")) + 2
            for overflow in ("fade", "clip"):
                label = style.label("home_room", text, w=width, overflow=overflow)
                label.scene = scene
                image = QImage(180, 60, QImage.Format_ARGB32_Premultiplied)
                image.fill(0)
                painter = QPainter(image)
                label.paint(painter)
                painter.end()
                images.append(image)
            self.assertEqual(images[0], images[1], text)
        images = []
        for overflow in ("fade", "clip"):
            label = style.label("home_room", "客廳靠窗的閱讀區", w=90, overflow=overflow)
            label.scene = scene
            image = QImage(180, 60, QImage.Format_ARGB32_Premultiplied)
            image.fill(0)
            painter = QPainter(image)
            label.paint(painter)
            painter.end()
            images.append(image)
        self.assertNotEqual(images[0], images[1])

    def test_fixed_size_choices_do_not_apply_auto_width_padding_twice(self):
        scene = SimpleNamespace(t=ui.ui_tokens("light"))
        for text in ("1x1", "2x2", "2x4", "4x4"):
            images = []
            for pad in (0, 14):
                button = ui.Button(text, w=42, h=30, size=12, pad=pad)
                button.scene = scene
                image = QImage(42, 30, QImage.Format_ARGB32_Premultiplied)
                image.fill(0)
                p = QPainter(image)
                button.paint(p)
                p.end()
                images.append(image)
            self.assertEqual(images[0], images[1], text)

    def test_long_mode_titles_and_button_labels_stay_inside_their_bounds(self):
        for title in ("客廳所有燈具的預設運作模式", "Living room lighting operation mode"):
            for theme in ("light", "dark"):
                scene = SimpleNamespace(t=ui.ui_tokens(theme))
                for view in (controls.ModeCard(140, "mdi:fan", title, title),
                             ui.Button(title, w=140, h=36)):
                    view.scene = scene
                    image = QImage(300, 80, QImage.Format_ARGB32_Premultiplied)
                    image.fill(0)
                    p = QPainter(image)
                    view.paint(p)
                    p.end()
                    self.assertFalse(any(image.pixelColor(x, y).alpha()
                                         for x in range(141, 300) for y in range(80)), title)

    def test_a_scrolling_box_fades_only_where_there_is_more(self):
        sv = ui.ScrollView(0, 0, 100, 100)
        sv.content.h = 80
        self.assertEqual(sv.fade_px(), 0)
        sv.content.h = 300
        self.assertEqual(sv.fade_px(), style.SCROLL_FADE)
        self.assertEqual(ui.ScrollView(0, 0, 10, 10, fade=0).fade_px(), 0)

    def test_the_detail_asks_for_roles_not_sizes(self):
        """No Label in the detail screen is given a size of its own: a new one takes a role (CLAUDE.md)."""
        with open(os.path.join(HERE, "nativeui", "detail.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertFalse(re.findall(r"\bLabel\(", src))

    def test_no_dialog_takes_the_panel_away(self):
        for name in ("detail.py", "controls.py", "panel.py"):
            with open(os.path.join(HERE, "nativeui", name), encoding="utf-8") as fh:
                src = fh.read()
            self.assertNotIn("QColorDialog", src, name)
            self.assertNotIn("QMessageBox", src, name)


if __name__ == "__main__":
    unittest.main()
