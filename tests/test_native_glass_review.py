"""Exercise the actual glass worker, including a state arriving over an existing frame."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import glass_review as review


class NativeGlass(unittest.TestCase):
    def test_real_glass_frame_survives_new_state_in_both_materials(self):
        for style in ("classic", "liquid"):
            for theme in ("light", "dark"):
                with self.subTest(style=style, theme=theme):
                    api, win, surface = review.create(style, theme)
                    try:
                        frame, fit = surface.glass, surface._glass_fit
                        self.assertGreater(api.captures, 0)
                        self.assertFalse(frame.isNull())
                        self.assertEqual((frame.width(), frame.height()), (surface.pw, surface.ph))
                        self.assertEqual(frame.pixelColor(0, 0).alpha(), 0)
                        before = review.shot(surface, "busy")
                        surface.push_states([("light.0", {"state": "off", "attributes": {}})])
                        review.app.processEvents()
                        surface.rebuild()
                        self.assertIs(surface.glass, frame)
                        self.assertEqual(surface._glass_fit, fit)
                        self.assertNotEqual(before, review.shot(surface, "busy"))
                    finally:
                        review.close(win)


if __name__ == "__main__":
    unittest.main()
