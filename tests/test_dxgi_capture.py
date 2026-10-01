"""Desktop Duplication bookkeeping that needs no GPU."""
import unittest

import dxgi_capture as dc


class RotationMapping(unittest.TestCase):
    # A 1080x1920 portrait desktop whose image is stored 1920x1080.
    W, H = 1080, 1920

    def test_identity_is_unchanged(self):
        self.assertEqual(dc.desktop_to_texture((10, 20, 30, 40), dc.ROTATE_IDENTITY, 100, 50),
                         (10, 20, 30, 40))

    def test_rotations_keep_size_and_stay_inside(self):
        rect = (100, 200, 400, 260)                  # 300 x 60 on the desktop
        for rotation in (dc.ROTATE_90, dc.ROTATE_270):
            l, t, r, b = dc.desktop_to_texture(rect, rotation, self.W, self.H)
            self.assertEqual((r - l, b - t), (60, 300))
            self.assertTrue(0 <= l < r <= self.H and 0 <= t < b <= self.W)
        l, t, r, b = dc.desktop_to_texture(rect, dc.ROTATE_180, self.W, self.H)
        self.assertEqual((l, t, r, b), (680, 1660, 980, 1720))

    def test_whole_desktop_maps_to_whole_texture(self):
        whole = (0, 0, self.W, self.H)
        for rotation in (dc.ROTATE_90, dc.ROTATE_270):
            self.assertEqual(dc.desktop_to_texture(whole, rotation, self.W, self.H),
                             (0, 0, self.H, self.W))


class ChangeTracking(unittest.TestCase):
    def output(self):
        out = dc._Output.__new__(dc._Output)
        out.seq, out.history = 0, []
        return out

    def push(self, out, *rects):
        out.seq += 1
        out.history.append((out.seq, list(rects)))

    def test_only_changes_under_the_reader_count(self):
        out = self.output()
        self.push(out, (0, 0, 10, 10))
        self.assertTrue(out.changed_since((5, 5, 20, 20), 0))
        self.assertFalse(out.changed_since((50, 50, 60, 60), 0))
        self.assertFalse(out.changed_since((5, 5, 20, 20), 1))

    def test_unknown_or_expired_frame_counts_as_changed(self):
        out = self.output()
        self.assertTrue(out.changed_since((0, 0, 1, 1), None))
        for _ in range(dc._HISTORY + 5):
            self.push(out, (900, 900, 901, 901))
        del out.history[:-dc._HISTORY]
        self.assertTrue(out.changed_since((0, 0, 1, 1), 1))
        self.assertFalse(out.changed_since((0, 0, 1, 1), out.seq - 1))


if __name__ == "__main__":
    unittest.main()
