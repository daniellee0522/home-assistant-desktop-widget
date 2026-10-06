"""The panel's liquid material takes the desktop on the GPU: a copy that matches the screen, the blurs it makes
from it, and the rule that a still desktop is not made again."""
import ctypes as C
import time
import unittest

from PIL import Image, ImageChops, ImageFilter
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QWidget

from test_native_widget import app, pump

import dxgi_capture as dc
from nativeui import dcomp, dcomp_liquid as dl
from nativeui.widget_capture import DesktopFrame

X, Y, W, H = 300, 100, 400, 600


class Backdrop(QWidget):
    """A stripe pattern that stays as it is, over the part of the screen the panel would read."""
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setGeometry(X, Y, W, H)

    def paintEvent(self, event):
        p = QPainter(self)
        for i in range(0, H, 20):
            p.fillRect(0, i, W, 20, QColor((i * 7) % 256, 90, 255 - (i * 5) % 256))
        p.end()


def mean_difference(a, b):
    histogram = ImageChops.difference(a, b).convert('L').histogram()
    return sum(count * level for level, count in enumerate(histogram)) / (a.width * a.height)


class PanelMaterialOnTheGpu(unittest.TestCase):
    def setUp(self):
        slider = dcomp.slider()
        if slider is None:
            self.skipTest('no compositor')
        self.slider = slider
        slider._make_surfaces(W, H)
        self.screen = Backdrop()
        self.screen.show()
        pump(400)
        self.capture = dc.DesktopDuplication()
        self.addCleanup(self.screen.close)
        self.addCleanup(self.release_capture)
        self.capture.grab(X, Y, W, H, None, 2.0, pixels=False)
        time.sleep(.3)

    def release_capture(self):
        """Let the duplication go before the next test makes its own."""
        with self.capture._lock:
            self.capture._interest.clear()
        self.capture._wake.set()
        end = time.monotonic() + 3
        while self.capture._outputs and time.monotonic() < end:
            time.sleep(.02)

    def material(self, level=50):
        image = QImage(W, H, QImage.Format_RGB888)
        image.fill(0x808080)
        material = dl.Material(self.slider, image, size=(W, H), radius=40, level=level, scale=1.25, tiles=[])
        self.addCleanup(material.close)
        return material

    def read(self, texture, w, h):
        desc = dl.TextureDesc(w, h, 1, 1, 87, 1, 0, 3, 0, 0x20000, 0)
        staging = dl._new(self.slider.device, 5, (dl.P, dl.P), C.byref(desc), None)
        try:
            dl._void(self.slider.context, 47, (dl.P, dl.P), staging, texture)
            mapped = dc._MAPPED()
            dl._call(self.slider.context, 14, (dl.P, dl.U, dl.U, dl.U, dl.P), staging, 0, 1, 0, C.byref(mapped))
            data = C.string_at(mapped.pData, mapped.RowPitch * h)
            dl._void(self.slider.context, 15, (dl.P, dl.U), staging, 0)
        finally:
            dl._release(staging)
        return Image.frombuffer('RGBA', (mapped.RowPitch // 4, h), data, 'raw', 'BGRA', 0, 1).crop((0, 0, w, h)).convert('RGB')

    def test_the_copy_is_the_screen_and_the_blurs_follow_the_cpu_ones(self):
        material = self.material()
        frame = DesktopFrame((X, Y, W, H), 0, self.capture.copy_region)
        self.assertEqual(material.update(frame), 'changed')
        backdrop = material.backdrop
        sharp = self.read(backdrop.copies[backdrop.shown][0], W, H)
        got = self.capture.grab(X, Y, W, H, None, 1.0)
        screen = Image.frombytes('RGB', (W, H), got[1], 'raw', 'BGRX')
        self.assertEqual(mean_difference(sharp, screen), 0)
        small = screen.resize((W // 4, H // 4), Image.BILINEAR)
        sigma = (22 * .5 + 8 + 4 * .5) * 1.25 / 4
        blurred = self.read(backdrop.targets['blur'][0], W // 4, H // 4)
        self.assertLess(mean_difference(blurred, small.filter(ImageFilter.GaussianBlur(sigma))), 4)
        frost = self.read(backdrop.targets['frost'][0], W // 4, H // 4)
        self.assertLess(mean_difference(frost, small.filter(ImageFilter.GaussianBlur(22 * .5 * 1.25 / 4))), 4)
        material.draw(0.0)

    def test_a_still_desktop_is_not_made_again_and_a_picture_from_the_processor_takes_over(self):
        material = self.material()
        frame = DesktopFrame((X, Y, W, H), 0, self.capture.copy_region)
        self.assertEqual(material.update(frame), 'changed')
        self.assertEqual(material.update(frame), 'static')
        self.assertIsNotNone(material.gpu_views)
        image = QImage(W, H, QImage.Format_RGB888)
        image.fill(0x204060)
        self.assertIsNone(material.update(image))                  # (a picture made on the processor)
        self.assertIsNone(material.gpu_views)
        material.draw(0.0)
        self.assertEqual(material.update(frame), 'changed')        # compared with nothing, not with a stale copy

    def test_a_desktop_that_cannot_be_copied_asks_for_the_processor(self):
        material = self.material()
        frame = DesktopFrame((X, Y, W, H), 0, lambda *args: None)
        self.assertIsNone(material.update(frame))


if __name__ == '__main__':
    unittest.main()
