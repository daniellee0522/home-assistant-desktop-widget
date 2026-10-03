"""The house style (nativeui/style.py): every scrolling box fades where there is more, and the screens' text
comes from its roles."""
import os
import re
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from nativeui import style, ui  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Style(unittest.TestCase):
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
