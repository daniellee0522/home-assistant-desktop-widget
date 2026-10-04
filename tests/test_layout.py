"""Layout rules (nativeui/style.py, CLAUDE.md): things centred by what is drawn, grids even, sizes that line
up, and no hand-tuned centring left in the screens."""
import os
import re
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from nativeui import render, style  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def ink_box(img, test):
    xs, ys = [], []
    for y in range(img.height()):
        for x in range(img.width()):
            if test(img.pixelColor(x, y)):
                xs.append(x)
                ys.append(y)
    return (min(xs) + max(xs) + 1) / 2, (min(ys) + max(ys) + 1) / 2


class Centring(unittest.TestCase):
    def test_long_names_use_the_original_fade_without_elision(self):
        from unittest.mock import patch
        from nativeui import ui
        from types import SimpleNamespace
        for text in ("客廳靠窗的閱讀燈與間接照明", "Living room reading light beside the window"):
            button = ui.Button(text, w=120, h=36)
            button.scene = SimpleNamespace(t=ui.ui_tokens("light"))
            image = QImage(120, 36, QImage.Format_ARGB32_Premultiplied)
            image.fill(0)
            p = QPainter(image)
            with patch.object(render, "draw_text_fade", wraps=render.draw_text_fade) as fade:
                button.paint(p)
                self.assertEqual(fade.call_args.args[1], text)
            p.end()

    def test_a_number_is_centred_in_its_box_by_its_ink(self):
        rect = QRectF(10, 20, 40, 40)
        for text in ("4", "31", "1", "88"):
            box = style.text_path(text, render.font(17, QFont.DemiBold), rect, "ink").boundingRect()
            self.assertAlmostEqual(box.center().x(), rect.center().x(), delta=0.01, msg=text)
            self.assertAlmostEqual(box.center().y(), rect.center().y(), delta=0.01, msg=text)

    def test_words_in_a_row_keep_one_baseline(self):
        f = render.font(15, QFont.DemiBold)
        rect = QRectF(0, 0, 30, 30)
        bottoms = {t: style.text_path(t, f, rect).boundingRect().bottom() for t in ("S", "M", "1", "8")}
        self.assertLess(max(bottoms.values()) - min(bottoms.values()), 0.6, bottoms)

    def test_the_remove_badges_cross_sits_in_its_middle(self):
        img = QImage(64, 64, QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        style.remove_badge(p, QRectF(8, 8, 48, 48), shadow=False)
        p.end()
        cx, cy = ink_box(img, lambda c: c.red() > 240 and c.green() > 240 and c.blue() > 240 and c.alpha() > 200)
        self.assertAlmostEqual(cx, 32, delta=1.0)
        self.assertAlmostEqual(cy, 32, delta=1.0)


class Grids(unittest.TestCase):
    def test_a_grid_is_even(self):
        rows = style.grid(QRectF(0, 0, 300, 200), 7, 6, 2, 3)
        heights = {round(r[0].height(), 6) for r in rows}
        pitches = {round(rows[i + 1][0].top() - rows[i][0].top(), 6) for i in range(len(rows) - 1)}
        self.assertEqual(len(heights), 1)
        self.assertEqual(len(pitches), 1)
        self.assertAlmostEqual(rows[-1][-1].right(), 300)
        self.assertAlmostEqual(rows[-1][-1].bottom(), 200)

    def test_two_of_a_size_and_a_gap_make_the_next(self):
        g = render.WIDGET_GAP
        w1, h1 = render.widget_size("1x1")
        w2, h2 = render.widget_size("2x2")
        w4, h4 = render.widget_size("2x4")
        w8, h8 = render.widget_size("4x4")
        self.assertAlmostEqual(2 * w1 + g, w2)
        self.assertAlmostEqual(2 * h1 + g, h2)
        self.assertAlmostEqual(2 * w2 + g, w4)
        self.assertAlmostEqual(h2, h4)
        self.assertAlmostEqual(2 * h4 + g, h8)


class NoHandTuning(unittest.TestCase):
    def test_no_cross_drawn_as_a_character_or_baseline_guessed_by_halves(self):
        for path in (ROOT / "nativeui").glob("*.py"):
            src = path.read_text(encoding="utf-8")
            self.assertNotIn('"\\u2715"', src, path.name)
            self.assertNotIn('"✕"', src, path.name)
            self.assertFalse(re.search(r"fm\.height\(\) / 20 \+ fm\.ascent\(\) / 10 - fm\.height\(\) / 20", src),
                             path.name)


if __name__ == "__main__":
    unittest.main()
