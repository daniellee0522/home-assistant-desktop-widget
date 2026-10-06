"""Real GPU glass pixels and native widget lifecycle/interaction."""
import ctypes
import threading
import time
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageChops, ImageStat
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest

from nativeui import dcomp, liquid, widget_glass, widget_capture
from nativeui.gpu_glass import Renderer
from nativeui.animation_clock import FrameTimer
from test_native_widget import app, FakeApi, make, tile, done, centre


def until(predicate, timeout=4):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(.002)
    return predicate()


def idle():
    clock = widget_glass.scheduler()
    return not clock.pending and not clock.scheduled and not widget_capture._queued


class GpuPixels(unittest.TestCase):
    def test_desktop_prefilter_on_gpu_matches_cpu_without_losing_refraction_or_frost(self):
        from PIL import ImageFilter
        compositor = dcomp.Slider()
        size = (96, 80)
        try:
            compositor._make_surfaces(*size)
            renderer = Renderer(compositor, size, 25, 1, 25, [(8, 8, 36, 60, 10)])
            try:
                source = Image.merge('RGB', tuple(Image.effect_noise(size, 90) for _ in range(3)))
                foreground = QImage(*size, QImage.Format_ARGB32_Premultiplied)
                foreground.fill(0)
                renderer.set_foreground(foreground)
                for sigma in (.075, .135):
                    filtered = source.filter(ImageFilter.GaussianBlur(sigma))
                    raw = filtered.tobytes()
                    image = QImage(raw, *size, size[0] * 3, QImage.Format_RGB888)
                    renderer.update(image)
                    expected_image = renderer.readback()
                    expected = expected_image.constBits().tobytes()
                    direct = source.tobytes('raw', 'BGRX')
                    image = QImage(direct, *size, size[0] * 4, QImage.Format_RGB32)
                    image._pre_blur = sigma
                    image._capture_bytes = direct
                    with patch.object(renderer.source, 'upload', wraps=renderer.source.upload) as upload:
                        renderer.update(image)
                        self.assertIs(upload.call_args.args[0], direct)
                    actual = renderer.readback()
                    self.assertEqual(actual.constBits().tobytes(), expected)
            finally:
                renderer.close()
        finally:
            compositor.close()

    def test_compute_blur_matches_six_passes_exactly_at_edges_and_group_boundaries(self):
        compositor = dcomp.Slider()
        try:
            for size in ((1, 1), (7, 5), (265, 37)):
                compositor._make_surfaces(*size)
                renderer = Renderer(compositor, size, 20, 1, 0, ())
                try:
                    if renderer.cs is None:
                        self.skipTest('Compute shader is unavailable on this GPU')
                    source = renderer._temporary('test-source', size)
                    picture = Image.merge('RGB', tuple(Image.effect_noise(size, 70) for _ in range(3)))
                    source.upload(picture.convert('RGBA').tobytes('raw', 'BGRA'), size[0] * 4)
                    foreground = QImage(*size, QImage.Format_ARGB32_Premultiplied)
                    foreground.fill(0)
                    renderer.set_foreground(foreground)
                    renderer.card.upload(bytes([255]) * (size[0] * size[1] * 4), size[0] * 4)
                    for sigma in (.2, 4, 22, 130):
                        with self.subTest(size=size, sigma=sigma):
                            with patch.object(renderer, 'cs', None):
                                renderer.result = renderer._blur(source, sigma, 'reference')
                                reference_image = renderer.readback()
                                expected = reference_image.constBits().tobytes()
                            renderer.result = renderer._blur(source, sigma, 'compute')
                            actual_image = renderer.readback()
                            actual = actual_image.constBits().tobytes()
                            self.assertEqual(actual, expected)
                finally:
                    renderer.close()
        finally:
            compositor.close()

    def test_original_refraction_blur_alpha_and_encoded_foreground_blend(self):
        compositor = dcomp.Slider()
        try:
            size = (180, 160)
            compositor._make_surfaces(*size)
            source = Image.merge('RGB', tuple(Image.effect_noise((45, 40), 35) for _ in range(3)))
            raw = source.tobytes()
            image = QImage(raw, 45, 40, 135, QImage.Format_RGB888).copy()
            foreground = QImage(*size, QImage.Format_ARGB32_Premultiplied)
            foreground.fill(0)
            p = QPainter(foreground)
            p.fillRect(50, 40, 60, 70, QColor(235, 180, 70, 100))
            p.end()
            tiles = [(12, 20, 70, 60, 12), (90, 50, 70, 90, 12)]
            for level in (0, 50, 100):
                with self.subTest(level=level):
                    lens = liquid.Lens(*size, 40)
                    before = lens.frame(source, lens.card_mask(), tiles,
                                        8 + 4 * level / 100, 22 * level / 100)
                    base = QImage(before.tobytes(), *size, size[0]*4, QImage.Format_RGBA8888).copy()
                    p = QPainter(base)
                    p.drawImage(0, 0, foreground)
                    p.end()
                    base = base.convertToFormat(QImage.Format_RGBA8888)
                    before = Image.frombytes('RGBA', size, base.constBits().tobytes())
                    renderer = Renderer(compositor, size, 40, 1, level, tiles)
                    try:
                        renderer.update(image)
                        renderer.set_foreground(foreground)
                        result = renderer.readback().convertToFormat(QImage.Format_RGBA8888)
                        after = Image.frombytes('RGBA', size, result.constBits().tobytes())
                        # Desktop BGRX's unused byte may be zero. It must not
                        # change the refraction or glass opacity on direct upload.
                        direct = source.tobytes('raw', 'BGRX')
                        direct_image = QImage(direct, 45, 40, 180, QImage.Format_RGB32)
                        renderer.update(direct_image)
                        direct_result = renderer.readback().convertToFormat(QImage.Format_RGBA8888)
                        self.assertEqual(direct_result.constBits().tobytes(), result.constBits().tobytes())
                        self.assertEqual(ImageChops.difference(before.getchannel('A'), after.getchannel('A')).getbbox(), None)
                        background = Image.new('RGBA', size, (30, 30, 30, 255))
                        a = Image.alpha_composite(background, before).convert('RGB')
                        b = Image.alpha_composite(background, after).convert('RGB')
                        diff = ImageChops.difference(a, b)
                        self.assertLessEqual(max(hi for _, hi in diff.getextrema()), 4)
                        self.assertLess(max(ImageStat.Stat(diff).mean), .5)
                    finally:
                        renderer.close()
        finally:
            compositor.close()


class GpuScheduling(unittest.TestCase):
    def test_dim_widgets_share_one_clock_and_one_presentation_batch(self):
        clock = widget_glass.Scheduler()
        controllers = [Mock(compositor=None) for _ in range(4)]
        animations = [FrameTimer(None) for _ in controllers]
        with patch.object(clock.timer, 'start') as start, patch.object(clock.timer, 'stop'):
            for animation, controller in zip(animations, controllers):
                animation.shared_clock = clock
                animation.timeout.connect(lambda c=controller: clock.submit(c))
                animation.start()
                self.assertIsNone(animation._ticker)
            self.assertEqual(len(clock.animations), 4)
            clock.tick()
            for controller in controllers:
                controller.present.assert_called_once_with(None, False, commit=False)
            self.assertFalse(clock.scheduled)
            for animation in animations:
                animation.stop()
            self.assertFalse(clock.animations)
            self.assertTrue(all(not a.isActive() for a in animations))

    def test_one_desktop_packet_presents_latest_images_without_a_second_refresh_clock(self):
        clock = widget_glass.Scheduler()
        first, second = Mock(compositor=None), Mock(compositor=None)
        clock.submit(first, 'old', foreground=True, paced=True)
        clock.submit(first, 'latest', paced=True)
        clock.submit(second, 'second', paced=True)
        self.assertFalse(clock.timer.isActive())
        self.assertFalse(clock.scheduled)
        clock.flush()
        first.present.assert_called_once_with('latest', True, commit=False)
        second.present.assert_called_once_with('second', False, commit=False)
        app.processEvents()
        self.assertFalse(clock.pending)
        self.assertFalse(clock.timer.isActive())
        first.fail.assert_not_called()
        second.fail.assert_not_called()


class GpuWidgetLifecycle(unittest.TestCase):
    def test_media_wake_reversal_and_state_update_keep_a_solid_handoff(self):
        prefs = FakeApi._prefs
        def media_prefs(api):
            result = prefs(api)
            result['widgets'][0]['kind'] = 'media'
            return result
        def capture(kind, digest, w, h, *args):
            if digest == 1:
                time.sleep(.02)
                return dict(unchanged=True, paced=True, hash=1)
            return dict(w=w, h=h, blur_w=w, blur_h=h,
                        blur_raw=bytes((70, 90, 110)) * w * h, hash=1, paced=True)
        with patch.object(FakeApi, '_prefs', media_prefs), \
                patch.object(FakeApi, 'gpu_widget_glass_allowed', lambda *args: True, create=True), \
                patch.object(FakeApi, 'get_desktop_backdrop', staticmethod(capture)):
            _, win, surface = make([tile(0, 'media_player')], glass_style='liquid',
                                    states={'media_player.e0': {'state': 'playing', 'attributes': {
                                        'media_title': 'Before', 'supported_features': 16435}}})
            try:
                surface.set_dim(True)
                self.assertTrue(until(lambda: surface._gpu_receiver.visible and not surface.dim_timer.isActive()))
                receiver, renderer = surface._gpu_receiver, surface._gpu_receiver.renderer
                surface.set_dim(False)
                self.assertTrue(until(lambda: 0 < surface.dim_t < .8))
                self.assertTrue(receiver.visible)
                surface.set_dim(True)
                surface.push_states([('media_player.e0', {'state': 'paused', 'attributes': {
                    'media_title': 'After', 'supported_features': 16435}})])
                self.assertTrue(until(lambda: not surface.dim_timer.isActive()))
                surface.set_dim(False)
                self.assertTrue(until(lambda: not receiver.visible and not surface.dim_timer.isActive()))
                self.assertIs(receiver.renderer, renderer)
                self.assertFalse(surface.wants_glass())
                face = surface.grab().toImage()
                self.assertGreater(face.pixelColor(face.width() // 2, face.height() // 2).alpha(), 200)
            finally:
                done(win)

    def test_solid_face_is_painted_before_wake_hides_gpu_layer(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        surface = Mock()
        surface.isVisible.return_value = True
        surface.wants_glass.return_value = False
        controller = widget_glass.Controller.__new__(widget_glass.Controller)
        controller.surface = surface
        controller.visible = True
        controller.clock = None
        controller.compositor = SimpleNamespace(shown=True, hwnd=123)
        events = []
        surface.repaint.side_effect = lambda: events.append(('paint', controller.visible))
        with patch.object(dcomp._user32, 'ShowWindow', side_effect=lambda *args: events.append(('hide', None))):
            controller.hide()
        self.assertEqual(events, [('paint', False), ('hide', None)])

    def test_static_state_push_hide_show_transition_and_native_hit_testing(self):
        unblock = threading.Event()
        generation = [1]
        def capture(kind, last_hash, w, h, *args):
            if last_hash == generation[0]:
                unblock.wait(.05)
                return dict(unchanged=True, paced=True, hash=last_hash)
            sw, sh = max(1, w // 4), max(1, h // 4)
            return dict(w=w, h=h, blur_w=sw, blur_h=sh,
                        blur_raw=bytes((50, 80, 120)) * sw * sh,
                        paced=True, hash=generation[0])
        with patch.object(FakeApi, 'gpu_widget_glass_allowed', lambda *args: True, create=True), \
                patch.object(FakeApi, 'get_desktop_backdrop', staticmethod(capture)):
            api, win, surface = make([tile(0, 'light')], size='2x2',
                                     states={'light.e0': {'state': 'on', 'attributes': {}}},
                                     glass_style='liquid', glass_sampling='live')
            try:
                self.assertTrue(until(lambda: surface._gpu_receiver is not None and surface._gpu_receiver.visible))
                receiver = surface._gpu_receiver
                renderer = receiver.renderer
                self.assertTrue(until(lambda: idle() and widget_capture._members[surface].quiet > 0))
                original = receiver.snapshot()
                with patch.object(renderer, 'update', wraps=renderer.update) as update:
                    surface.push_states([('light.e0', {'state': 'off', 'attributes': {}})])
                    self.assertTrue(until(lambda: surface.overlay is not None and
                                          idle()))
                    self.assertIs(receiver.renderer, renderer)
                    update.assert_not_called()
                self.assertNotEqual(original, receiver.snapshot())
                with patch.object(renderer, 'set_layers', wraps=renderer.set_layers) as layers:
                    surface.set_dim(True)
                    self.assertTrue(until(lambda: not surface.dim_timer.isActive()))
                    self.assertEqual(surface.dim_t, 1)
                    self.assertLessEqual(layers.call_count, 3)
                    resting_lit = receiver.foreground_image
                    with patch.object(renderer, 'set_foreground', wraps=renderer.set_foreground) as upload:
                        surface.push_states([('light.e0', {'state': 'on', 'attributes': {}})])
                        self.assertTrue(until(lambda: idle() and surface.overlay_dim is not None))
                        self.assertIs(receiver.foreground_image, resting_lit)
                        upload.assert_not_called()
                    surface.set_dim(False)
                    self.assertTrue(until(lambda: not surface.dim_timer.isActive()))
                    self.assertEqual(surface.dim_t, 0)
                    self.assertIsNot(receiver.foreground_image, resting_lit)
                    self.assertIs(receiver.renderer, renderer)
                # Native Windows hit testing must reach the Qt owner, not the
                # click-through GPU visual or the desktop behind a clear HWND.
                point = surface.mapToGlobal(centre(surface, 0))
                class Point(ctypes.Structure):
                    _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]
                hit = ctypes.windll.user32.WindowFromPoint
                hit.argtypes, hit.restype = [Point], ctypes.c_void_p
                self.assertEqual(hit(Point(point.x(), point.y())), surface.cache_hwnd())
                QTest.mouseClick(surface, Qt.LeftButton, pos=centre(surface, 0))
                self.assertTrue(any(call[0] == 'service' for call in api.calls))
                surface.hide()
                self.assertFalse(receiver.visible)
                surface.show()
                self.assertTrue(until(lambda: receiver.visible))
                snapshot = surface._paint_image('t0')
                self.assertEqual(snapshot.pixelColor(snapshot.width() // 2, snapshot.height() // 2).alpha(), 0)
                surface.set_transition_tile('t0')
                self.assertTrue(until(idle))
                self.assertEqual(receiver.snapshot().pixelColor(snapshot.width() // 2, snapshot.height() // 2).alpha(), 0)
                generation[0] += 1
                surface.sample_now.set()
                self.assertTrue(until(lambda: surface._latest_generation == surface._glass_generation))
                surface.set_transition_tile(None)
            finally:
                unblock.set()
                done(win)
                self.assertNotIn(receiver, widget_glass._controllers)


if __name__ == '__main__':
    unittest.main()
