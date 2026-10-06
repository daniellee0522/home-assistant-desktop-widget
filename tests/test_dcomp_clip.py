"""The moving glass clip keeps the card's full height, including its bottom corners."""
import unittest
from unittest.mock import patch

from nativeui import dcomp


class GlassClip(unittest.TestCase):
    def test_compositor_helper_passes_pointer_hits_through(self):
        procedure = dcomp._window_procedure()
        self.assertEqual(procedure(0, 0x84, 0, 0), -1)
        self.assertEqual(procedure(0, 0x21, 0, 0), 3)

    def test_settling_keeps_the_same_glass_and_puts_native_content_above_it(self):
        from unittest.mock import Mock
        slider = object.__new__(dcomp.Slider)
        slider.material = Mock()
        material = slider.material
        slider.card_visual, slider.glass_visual, slider.composition, slider.hwnd = 1, 2, 3, 4
        slider.mask_contents = [5, 6]
        with patch.object(dcomp, '_call') as call, patch.object(dcomp, '_user32') as user:
            slider.settle_glass(7)
        self.assertIs(slider.material, material)
        self.assertFalse(slider.handoff_active)
        self.assertTrue(any(c.args[:2] == (1, 15) and c.args[3] is None for c in call.call_args_list))
        self.assertFalse(any(c.args[:2] == (2, 15) for c in call.call_args_list))
        self.assertEqual(user.SetWindowPos.call_args.args[1].value, 7)
        material.close.assert_not_called()

    def test_background_capture_only_queues_until_the_next_refresh(self):
        from unittest.mock import Mock
        slider = object.__new__(dcomp.Slider)
        slider.shown, slider.material = True, Mock()
        with patch.object(slider, '_start_material') as start:
            slider.queue_glass('old')
            slider.queue_glass('new')
        self.assertEqual(slider.pending_glass, 'new')
        slider.material.update.assert_not_called()
        slider.material.draw.assert_not_called()
        self.assertEqual(start.call_count, 2)

    def test_handoff_finishes_material_and_blends_the_complete_compositor(self):
        from unittest.mock import Mock
        slider = object.__new__(dcomp.Slider)
        slider.material, slider.material_timer = Mock(), Mock()
        slider.handoff_effect = None
        slider.composition, slider.root = 1, 2
        with patch.object(dcomp, '_new', side_effect=[3, 4]), patch.object(dcomp, '_call') as call, \
                patch.object(dcomp, '_release'), patch.object(slider, '_start_material') as start:
            slider.fade_out(.06)
        slider.material.draw.assert_called_once_with(0.0)
        start.assert_called_once()
        self.assertTrue(any(c.args[:2] == (2, 10) and c.args[3] == 3 for c in call.call_args_list))
        cubic = next(c.args[3:] for c in call.call_args_list if c.args[:2] == (4, 5))
        _, a, b, c, d = cubic
        self.assertEqual(a, 1)
        self.assertAlmostEqual(a + .06 * (b + .06 * (c + .06 * d)), 0)
        self.assertAlmostEqual(b + 2*c*.06 + 3*d*.06**2, 0)

    def test_liquid_refresh_keeps_compositor_motion_and_stops_when_hidden(self):
        from unittest.mock import Mock
        slider = object.__new__(dcomp.Slider)
        slider.shown = True
        slider.material = Mock()
        slider.material_timer = Mock()
        slider.composition = 1
        slider.material_start = 10
        slider.material_qpc_start = 10
        slider.pending_glass = 'newest desktop'
        slider.material_duration, slider.material_end = .2, 0
        slider.material_curve = dcomp.cubic_pieces(400, 0, .2, (.2, 0, .2, 1))
        with patch.object(dcomp, 'next_frame_time', return_value=10.1), patch.object(dcomp, '_call') as call:
            slider._material_frame()
            slider.material.update.assert_called_once_with('newest desktop')
            self.assertIsNone(slider.pending_glass)
            offset = slider.material.draw.call_args.args[0]
            self.assertGreater(offset, 0)
            self.assertLess(offset, 400)
            self.assertEqual(len(call.call_args_list), 1)  # commit only, no changed visual positions
        slider.shown = False
        slider.material.draw.reset_mock()
        slider._material_frame()
        slider.material.draw.assert_not_called()
        slider.material_timer.stop.assert_called()
        material = slider.material
        slider._stop_material()
        material.close.assert_called_once()
        self.assertIsNone(slider.material)

    def test_outline_columns_follow_the_card_curve_without_moving_glass(self):
        slider = object.__new__(dcomp.Slider)
        slider.composition, slider.card_visual, slider.glass_visual = 1, 2, 3
        slider.mask_clips = [30, 31]
        slider.mask_contents = [40, 41]
        slider.mask_columns = [(0, 1, 5, 395), (1, 2, 4, 396)]
        for start, end in ((424, 0), (0, 424)):
            with self.subTest(start=start), patch.object(dcomp, "_new", side_effect=[10, 11]), \
                    patch.object(dcomp, "_call") as call, patch.object(dcomp, "_release"):
                slider.slide(start, end, .2, (.2, 0, .2, 1))
                calls = call.call_args_list
                self.assertTrue(any(c.args[:2] == (2, 5) and c.args[3] == 10 for c in calls))
                self.assertTrue(any(c.args[:2] == (3, 5) and c.args[3] == 10 for c in calls))
                forward = [c.args[4:] for c in calls if c.args[:2] == (10, 5)]
                inverse = [c.args[4:] for c in calls if c.args[:2] == (11, 5)]
                self.assertEqual(len(forward), 16)
                for a, b in zip(forward, inverse):
                    self.assertEqual(a, tuple(-v for v in b))
                for content in slider.mask_contents:
                    self.assertTrue(any(c.args[:2] == (content, 5) and c.args[3] == 11 for c in calls))
                self.assertFalse(any(c.args[0] in slider.mask_clips for c in calls))

    def test_only_the_moving_glass_clip_is_configured(self):
        slider = object.__new__(dcomp.Slider)
        slider.size = (300, 400)
        slider.hwnd, slider.composition = 1, 2
        slider.glass_surface, slider.card_surface = 3, 4
        slider.card_visual, slider.clip = 5, 6
        slider.root, slider.handoff_effect = 7, 8
        for offset in (0, 100, 424):
            with self.subTest(offset=offset), patch.object(slider, "_upload"), \
                    patch.object(dcomp, "_call") as call, patch.object(dcomp, "_user32"), \
                    patch.object(dcomp, "plain_window"):
                slider.show((0, 0, 300, 400), object(), object(), offset, 30)
                values = {c.args[1]: c.args[3] for c in call.call_args_list if c.args[0] == 6}
                self.assertEqual(values[10], 400 + offset)
                self.assertEqual([values[i] for i in (20, 22, 24, 26)], [30] * 4)
                self.assertFalse(any(c.args[1] == 13 for c in call.call_args_list))
                self.assertTrue(any(c.args[:2] == (7, 10) and c.args[3] is None
                                    for c in call.call_args_list))

    def test_both_edges_animate_with_the_same_height_in_both_directions(self):
        slider = object.__new__(dcomp.Slider)
        slider.composition, slider.card_visual, slider.clip = 1, 2, 3
        slider.size = (300, 400)
        for start, end in ((424, 0), (0, 424)):
            with self.subTest(start=start), patch.object(dcomp, "_new", side_effect=[10, 11]), \
                    patch.object(dcomp, "_call") as call, patch.object(dcomp, "_release"):
                slider.slide(start, end, .2, (.2, 0, .2, 1))
                calls = call.call_args_list
                top = [c.args[4:] for c in calls if c.args[:2] == (10, 5)]
                bottom = [c.args[4:] for c in calls if c.args[:2] == (11, 5)]
                self.assertEqual(len(top), 16)
                for upper, lower in zip(top, bottom):
                    self.assertAlmostEqual(lower[0] - upper[0], 400)
                    self.assertEqual(upper[1:], lower[1:])
                self.assertTrue(any(c.args[:2] == (3, 5) and c.args[3] == 10 for c in calls))
                self.assertTrue(any(c.args[:2] == (3, 9) and c.args[3] == 11 for c in calls))


if __name__ == "__main__":
    unittest.main()
