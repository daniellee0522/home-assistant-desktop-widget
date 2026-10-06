"""Desktop Duplication bookkeeping that needs no GPU."""
import unittest
import ctypes
from unittest.mock import patch

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


class BatchedReadback(unittest.TestCase):
    def test_metadata_wait_does_not_read_pixels(self):
        output = dc._Output.__new__(dc._Output)
        output.name, output.seq, output.copy, output.valid = 'display', 1, 1, (0,0,100,100)
        output.texture_rect=lambda rect: (rect,rect)
        capture=dc.DesktopDuplication()
        capture._outputs=[output]
        reader=dc._Read((0,0,10,10),None,.5,pixels=False)
        with patch.object(capture,'_compose') as compose:
            self.assertTrue(capture._answer(reader,False))
            self.assertEqual(reader.result,((('display',1),),b''))
            compose.assert_not_called()
    def test_one_map_keeps_each_rectangle_exact_and_refreshes_next_frame(self):
        out = dc._Output.__new__(dc._Output)
        out.seq = 1
        out.copy, out.context, out.staging = 1, 2, 3
        out.valid = (0, 0, 100, 100)
        out.staging_size = (3, 2)
        out._batch_seq, out._batch = None, {}
        a, b = (10, 20, 12, 22), (40, 50, 41, 51)
        # Atlas row pitch includes padding; the second rectangle is shorter.
        pixels = b'AAAA' + b'BBBB' + b'CCCC' + b'pad!' + b'DDDD' + b'EEEE' + b'FFFF' + b'pad!'
        storage = ctypes.create_string_buffer(pixels)
        def call(obj, slot, *args, **kwargs):
            if slot == 14:
                mapped = ctypes.cast(args[4], ctypes.POINTER(dc._MAPPED)).contents
                mapped.pData, mapped.RowPitch = ctypes.addressof(storage), 16
            return 0
        with patch.object(dc, '_call', side_effect=call) as calls:
            out.read_batch([a, b, a])
            self.assertEqual(out.read(a), (b'AAAABBBBDDDDEEEE', 8, 2, 2))
            self.assertEqual(out.read(b), (b'CCCC', 4, 1, 1))
            out.read_batch([a, b])
            self.assertEqual([c.args[1] for c in calls.call_args_list], [46, 46, 14, 15])
            out.seq += 1
            out.read_batch([a, b])
            self.assertEqual(sum(c.args[1] == 14 for c in calls.call_args_list), 2)

    def test_oversized_atlas_falls_back_without_allocating(self):
        out = dc._Output.__new__(dc._Output)
        out.seq, out.copy, out.valid = 1, 1, (0, 0, 20000, 100)
        out._batch_seq, out._batch = None, {}
        with patch.object(dc, '_call') as calls:
            out.read_batch([(0, 0, 9000, 1), (9000, 0, 18000, 1)])
            calls.assert_not_called()
            self.assertIsNone(out._batch_seq)


class SharedDesktopCopy(unittest.TestCase):
    def output(self, **overrides):
        out = dc._Output.__new__(dc._Output)
        out.name, out.seq, out.rotation = 'display', 7, dc.ROTATE_IDENTITY
        out.desktop = (0, 0, 1000, 800)
        out.copy, out.valid, out.context = 1, (0, 0, 1000, 800), 2
        out.mutex, out.handle, out.luid, out.opened = 3, 4, (1, 0), {}
        for key, value in overrides.items():
            setattr(out, key, value)
        return out

    def duplication(self, out):
        capture = dc.DesktopDuplication()
        capture._outputs = [out]
        capture._luids[99] = (1, 0)
        return capture

    def test_only_an_unrotated_shared_copy_on_the_readers_adapter_is_taken_on_the_gpu(self):
        rect = (10, 20, 100, 50)
        self.assertIsNotNone(self.duplication(self.output()).gpu_source(rect, 99))
        for change in (dict(mutex=None), dict(handle=None), dict(luid=(2, 0)),
                       dict(rotation=dc.ROTATE_90), dict(valid=(0, 0, 50, 50))):
            self.assertIsNone(self.duplication(self.output(**change)).gpu_source(rect, 99), change)
        # A window across the edge of the output needs both screens: read back instead.
        self.assertIsNone(self.duplication(self.output()).gpu_source((950, 20, 100, 50), 99))
        self.assertIsNone(self.duplication(self.output()).gpu_source(rect, None))

    def test_copy_is_issued_between_the_mutex_acquire_and_release(self):
        out = self.output(opened={99: (5, 6)})
        capture = self.duplication(out)
        calls = []
        def call(obj, slot, *args, **kwargs):
            calls.append((obj, slot))
            return 0
        with patch.object(dc, '_call', side_effect=call):
            cursor = capture.copy_region((10, 20, 100, 50), 11, 99, 12)
        self.assertEqual(cursor, (('display', 7),))
        self.assertEqual(calls, [(6, 8), (12, 46), (6, 9)])

    def test_a_busy_mutex_is_not_waited_for_and_asks_for_the_cpu_path(self):
        out = self.output(opened={99: (5, 6)})
        with patch.object(dc, '_call', return_value=0x102):
            self.assertIsNone(self.duplication(out).copy_region((10, 20, 100, 50), 11, 99, 12))


if __name__ == "__main__":
    unittest.main()
