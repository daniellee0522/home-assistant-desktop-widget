"""Animation caches retain artwork, but update when content or scrolling changes."""
import unittest

from PySide6.QtCore import QRectF, Qt
import shiboken6

import test_native_panel as T
from nativeui import ui


class Painted(ui.View):
    def __init__(self, w=40, h=40):
        super().__init__(0, 0, w, h)
        self.paints = 0
        self.color = Qt.red

    def paint(self, painter):
        self.paints += 1
        painter.fillRect(QRectF(0, 0, self.w, self.h), self.color)


class AnimationCache(unittest.TestCase):
    def setUp(self):
        self.scene = ui.Scene(None, "cache-test")
        self.scene.set_css_size(80, 80)

    def tearDown(self):
        self.scene.tweens.timer.stop()
        self.scene.close()
        T.app.processEvents()
        shiboken6.delete(self.scene)
        T.app.processEvents()

    def test_outer_fade_reuses_artwork_and_descendant_update_repaints(self):
        holder = ui.CachedView(0, 0, 40, 40)
        child = Painted()
        holder.add(child)
        self.scene.root.add(holder)
        self.scene.content_image()
        image = holder._page_cache
        holder.animate(100, "linear", alpha=0.5)
        tween = self.scene.tweens.running[0]
        tween["t0"] -= 0.05
        self.scene.tweens.tick()
        self.scene.content_image()
        self.assertIs(holder._page_cache, image)
        self.assertEqual(child.paints, 1)
        child.color = Qt.blue
        child.changed()
        updated = self.scene.content_image()
        self.assertEqual(child.paints, 2)
        self.assertGreater(updated.pixelColor(5, 5).blue(), updated.pixelColor(5, 5).red())

    def test_unscoped_paint_request_refreshes_direct_content_changes(self):
        child = Painted()
        self.scene.root.add(child)
        self.scene.content_image()
        child.color = Qt.blue
        self.scene.request_paint()
        updated = self.scene.content_image()
        self.assertEqual(child.paints, 2)
        self.assertGreater(updated.pixelColor(5, 5).blue(), updated.pixelColor(5, 5).red())

    def test_scroll_fade_reuses_pixels_for_opacity_but_repaints_for_scroll_and_child_motion(self):
        scroll = ui.ScrollView(0, 0, 40, 40, fade=8)
        child = Painted(40, 80)
        scroll.add(child)
        scroll.content.h = 80
        self.scene.root.add(scroll)
        self.scene.content_image()
        image = scroll._fade_cache[1]
        scroll.animate(100, "linear", alpha=0.5)
        self.scene.tweens.running[0]["t0"] -= 0.05
        self.scene.tweens.tick()
        self.scene.content_image()
        self.assertIs(scroll._fade_cache[1], image)
        self.assertEqual(child.paints, 1)
        scroll.scroll_to(15)
        self.scene.content_image()
        self.assertEqual(child.paints, 2)
        child.animate(100, "linear", dy=10)
        self.scene.tweens.tick()
        self.scene.content_image()
        self.assertEqual(child.paints, 3)

    def test_glass_arriving_mid_animation_is_applied_after_the_last_tick(self):
        from PySide6.QtGui import QImage
        child = Painted()
        self.scene.root.add(child)
        old = QImage(self.scene.pw, self.scene.ph, QImage.Format_ARGB32_Premultiplied)
        old.fill(Qt.red)
        self.scene.glass = old
        new = old.copy()
        new.fill(Qt.blue)
        self.scene.latest = new
        self.scene._latest_generation = self.scene._glass_generation
        child.animate(100, "linear", dx=10)
        self.scene._on_glass()
        self.assertIs(self.scene.glass, old)
        self.scene.tweens.running[0]["t0"] -= 0.2
        self.scene.tweens.tick()
        self.assertFalse(self.scene.animation_active)
        self.assertFalse(self.scene._deferred_animation_glass)
        self.assertGreater(self.scene.glass.pixelColor(20, 20).blue(), 200)
