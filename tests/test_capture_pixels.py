import unittest
from PIL import Image
from PIL import ImageFilter
from capture_pixels import within_noise, within_noise_bgrx


class CapturePixelsTests(unittest.TestCase):
    def test_prefilter_fast_path_matches_exact_filtered_noise_detection(self):
        original = Image.merge('RGB', tuple(Image.effect_noise((35, 31), 90) for _ in range(3)))
        raw = original.tobytes('raw', 'BGRX')
        for sigma in (.075, .135):
            for delta in (0, 3, 4, 20, 200):
                changed = original.copy()
                changed.putpixel((5, 7), (delta, 100, 100))
                expected = within_noise(original.filter(ImageFilter.GaussianBlur(sigma)),
                                        changed.filter(ImageFilter.GaussianBlur(sigma)), 3)
                self.assertEqual(within_noise_bgrx(raw, changed.tobytes('raw', 'BGRX'), original.size,
                                                 3, sigma), expected)
    def test_unsampled_change_cannot_freeze_glass(self):
        original = Image.new('RGB', (13, 17), (40, 50, 60))
        changed = original.copy()
        changed.putpixel((3, 4), (44, 50, 60))
        self.assertFalse(within_noise(original, changed, 3))

    def test_noise_boundary_and_channels(self):
        original = Image.new('RGB', (13, 17), (40, 50, 60))
        for point in ((0, 0), (3, 4), (12, 16)):
            for channel in range(3):
                for delta in (-4, -3, 3, 4):
                    changed = original.copy()
                    pixel = list(original.getpixel(point))
                    pixel[channel] += delta
                    changed.putpixel(point, tuple(pixel))
                    self.assertEqual(within_noise(original, changed, 3), abs(delta) <= 3)
        self.assertFalse(within_noise(original, original.resize((12, 17)), 3))

    def test_direct_capture_matches_rgb_noise_detection_ignoring_unused_alpha(self):
        original = Image.new('RGB', (13, 17), (40, 50, 60))
        raw = original.tobytes('raw', 'BGRX')
        for point in ((0, 0), (3, 4), (12, 16)):
            for delta in (-4, -3, 3, 4):
                changed = original.copy()
                changed.putpixel(point, (40, 50, 60 + delta))
                actual = bytearray(changed.tobytes('raw', 'BGRX'))
                actual[3::4] = bytes([173]) * (13 * 17)
                self.assertEqual(within_noise_bgrx(raw, actual, original.size, 3),
                                 within_noise(original, changed, 3))
