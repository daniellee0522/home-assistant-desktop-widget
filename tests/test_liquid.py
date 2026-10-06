"""The straight-edge batching must preserve the curved lens and its pixels."""
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops
from nativeui import liquid
from tools.benchmark_liquid import ReferenceLens


class LiquidTests(unittest.TestCase):
    def test_batched_mesh_preserves_pixels_and_reduces_dispatches(self):
        for w, h, radius in ((320, 320, 48), (641, 479, 48), (180, 120, 60)):
            with self.subTest(size=(w, h)):
                with patch.object(liquid, '_strip_mesh', lambda mesh: mesh):
                    old = ReferenceLens(w, h, radius)
                new = liquid.Lens(w, h, radius)
                self.assertLess(len(new.mesh), len(old.mesh))
                source = Image.effect_noise((w // 2, h // 2), 80).convert('RGB')
                card = new.card_mask()
                for frost in (0, 14):
                    tiles = ((12, 20, 80, 60, 12),)
                    a = old.frame(source, card, tiles, frost=frost)
                    b = new.frame(source, card, tiles, frost=frost)
                    delta = ImageChops.difference(a, b).getextrema()
                    self.assertEqual(max(hi for _, hi in delta), 0)


if __name__ == '__main__':
    unittest.main()
