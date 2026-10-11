"""How the tray panel comes and goes (panel.py): a picture slid by the desktop compositor, or drawn by the panel itself\nwhere the compositor cannot be had."""
import time

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter

from . import dcomp, render, screens

# Like the system's own flyouts: it slides in from behind the bottom edge and out again, with no fade.
ENTER_CURVE, LEAVE_CURVE = (0.2, 0.75, 0.25, 1.0), (0.5, 0.0, 1.0, 1.0)
ENTER_MS, LEAVE_MS = 250, 150


class PanelSlide:
    """How the tray panel comes and goes (panel.py): a picture slid by the desktop compositor, or drawn by the panel itself\nwhere the compositor cannot be had"""

    def _vsync_motion(self):
        """The panel's coming and going is paced by the desktop's compositions; everything else keeps its clock."""
        self.tweens.timer.vsync = True

    def _cancel_compositor(self):
        """Discard the previous presentation before changing its appearance or showing again."""
        self._slide_timer.stop()
        if self._sliding is not None or self._compositor_resting:
            slider = self._compositor_slider or dcomp.slider()
            if slider is not None:
                slider.hide()
        self._sliding = None
        self._compositor_resting = False
        self._compositor_geometry = None
        self._compositor_slider = None
        self._compositor_capture = None
        self._compositor_epoch += 1
        self._compositor_raw = None
        self._flyout_picture = self._flyout_glass = None
        self._deferred_glass = False
        self.moving = False
        self.tweens.cancel(self)

    def _slide_layers(self, size, at=None):
        """Separate desktop glass and foreground pictures in physical window pixels."""
        def picture(image):
            image = image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(1.0)          # (its pixels are the window's, whatever scale it was made at)
            if (image.width(), image.height()) != size:
                # (the window can be a pixel larger than what is drawn: it is drawn from the corner, not stretched)
                canvas = QImage(size[0], size[1], QImage.Format_ARGB32_Premultiplied)
                canvas.fill(Qt.transparent)
                painter = QPainter(canvas)
                painter.drawImage(0, 0, image)
                painter.end()
                image = canvas
            return image
        # self.glass is already cut to the resting card. It must never be the
        # stationary animation background: its old bottom corners would remain
        # visible inside the moving card even with a correct outer clip.
        source = self.latest if self.custom_bg() or not self._liquid_glass() else self.raw_latest
        if source is None:
            source = self.glass
        glass = None
        source_height = self.ph
        if (at is not None and (size[1] > self.ph or self._liquid_glass())
                and not self.custom_bg() and not self.system_glass):
            capture = getattr(self.api, "get_desktop_backdrop", None)
            try:
                shot = capture("flyout", None, size[0], size[1], at[0], at[1], 0) if capture else None
            except Exception:
                shot = None
            if shot and shot.get("blur_raw"):
                source = QImage(shot["blur_raw"], shot["blur_w"], shot["blur_h"],
                                shot["blur_w"] * 3, QImage.Format_RGB888).copy()
                source_height = size[1]
                self._compositor_background = ((*at, *size), source)
            else:
                cached = self._compositor_background
                if cached is not None and cached[0] == (*at, *size):
                    source, source_height = cached[1], size[1]
        if source is not None and not self.system_glass:
            glass = QImage(size[0], size[1], QImage.Format_ARGB32_Premultiplied)
            glass.fill(Qt.transparent)
            painter = QPainter(glass)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawImage(QRectF(0, 0, self.pw, source_height), source)
            if source_height < size[1]:
                # A capture may still be arming. Keep an opaque blurred continuation
                # until the screen edge instead of reusing the old rounded mask.
                painter.drawImage(QRectF(0, source_height, self.pw, size[1] - source_height), source,
                                  QRectF(0, source.height() - 1, source.width(), 1))
            painter.end()
        card = picture(self.content_image())
        return glass, card

    def _time_slide(self, milliseconds):
        self._slide_deadline = time.monotonic() + milliseconds / 1000
        self._slide_timer.start(milliseconds)

    def _finish_slide_if_due(self):
        remaining = self._slide_deadline - time.monotonic()
        if self._sliding is None:
            return
        if remaining > 0:
            self._slide_timer.start(max(1, int(remaining * 1000) + 1))
            return
        self._finish_slide()

    def _refresh_compositor_background(self):
        """Refresh screen pixels while retaining surfaces and the motion curve."""
        rect, slider = self._compositor_capture, self._compositor_slider
        if rect is None or slider is None or slider.material is None:
            return
        self._compositor_epoch += 1
        self._compositor_raw = None
        slider.pending_glass = None
        self._compositor_presented_at = time.monotonic()
        capture = getattr(self.api, "get_desktop_backdrop", None)
        try:
            shot = capture("flyout", None, rect[2], rect[3], rect[0], rect[1], 0) if capture else None
        except Exception:
            shot = None
        if shot and shot.get("blur_raw"):
            image = QImage(shot["blur_raw"], shot["blur_w"], shot["blur_h"],
                           shot["blur_w"] * 3, QImage.Format_RGB888).copy()
            self._compositor_background = (rect, image)
            self._compositor_presented_at = time.monotonic()
            slider.queue_glass(image)
        self.force.set()
        self.sample_now.set()

    def _reverse_compositor(self, entering):
        slider = self._compositor_slider
        kind = self._sliding
        if (kind is None or kind[0] not in ("enter", "leave")
                or slider is None or not slider.shown):
            return False
        desired = "enter" if entering else "leave"
        self._refresh_compositor_background()
        if kind[0] == desired:
            return True
        offset = slider.motion_offset()
        far = slider.size[1] + 24
        target = 0.0 if entering else far
        base = ENTER_MS if entering else LEAVE_MS
        duration = max(25, round(base * min(1, abs(target - offset) / far)))
        self._slide_timer.stop()
        slider.slide(offset, target, duration / 1000, ENTER_CURVE if entering else LEAVE_CURVE)
        self._sliding = (desired, duration)
        self._time_slide(duration + 30)
        return True

    def _compositor_slide(self, entering):
        """Slide the panel in or out by the compositor. False where that cannot be (the caller draws it itself)."""
        if self._reverse_compositor(entering):
            return True
        slider = None if self.system_glass else dcomp.slider()     # (a glass the desktop draws is not in a picture)
        hwnd = self.cache_hwnd()
        rect = dcomp.window_rect(hwnd) if hwnd else None
        if slider is None or rect is None or rect[2] < 2 or rect[3] < 2:
            return False
        self._finish_slide()                                        # one already going is taken to its end
        self._compositor_slider = slider
        self._compositor_resting = False
        try:
            monitor = screens.monitor_at(rect[0] + rect[2] / 2, rect[1] + rect[3] / 2)
            if monitor is not None:
                # Extend only to the work area's edge, leaving the taskbar uncovered.
                # The panel keeps its resting size throughout state updates.
                rect = (rect[0], rect[1], rect[2], max(rect[3], monitor.work[3] - rect[1]))
            glass, card = self._slide_layers((rect[2], rect[3]), at=rect[:2])
            radius = min(self.card_radius(), self.css_w / 2, self.css_h / 2) * self.scale
            outline = render.squircle(0, 0, self.css_w * self.scale, self.css_h * self.scale, radius)
            columns = dcomp.outline_columns([(p.x(), p.y()) for p in outline.toFillPolygon()],
                                            self.css_w * self.scale, self.css_h * self.scale, radius)
            far = rect[3] + 24                                      # behind the taskbar and the screen's edge
            material = None
            if glass is not None and self._liquid_glass() and not self.custom_bg():
                material = dict(size=(self.css_w * self.scale, self.css_h * self.scale), radius=radius,
                                level=self.liquid_level, scale=self.scale, tiles=self.glass_tiles())
            self.moving = True                                      # the glass sampler leaves the processor alone
            self._compositor_capture = rect if material is not None else None
            self._compositor_epoch += 1
            self._compositor_since = time.monotonic()
            self._compositor_presented_at = self._compositor_since
            self._compositor_raw = None
            self.sample_now.set()
            if entering:
                # A reused native window may still hold the previous resting
                # bitmap. Clear it before the moving compositor is shown.
                self.anim_alpha = 0.0
                self.repaint()
                slider.show(rect, glass, card, far, radius, above=hwnd, columns=columns, liquid=material)
                slider.slide(far, 0.0, ENTER_MS / 1000, ENTER_CURVE)
                self._sliding = ("enter", ENTER_MS)
            else:
                # Commit the helper and clear the native foreground before
                # waiting for a desktop frame: waiting between them doubles tint.
                slider.show(rect, glass, card, 0.0, radius, above=hwnd, columns=columns,
                            liquid=material, wait=False)
                self.anim_alpha = 0.0
                self.repaint()
                slider.slide(0.0, far, LEAVE_MS / 1000, LEAVE_CURVE)
                self._sliding = ("leave", LEAVE_MS)
        except Exception:
            import traceback
            dcomp.disable(traceback.format_exc())
            self._sliding = None
            self._compositor_capture = None
            self.moving = False
            return False
        self._time_slide(self._sliding[1] + 30)
        return True

    def _finish_slide(self):
        """Finish motion; live liquid glass keeps the same compositor beneath native controls."""
        kind = self._sliding
        if kind is None:
            return
        self._sliding = None
        if kind[0] != "enter":
            self._compositor_capture = None
            self._compositor_epoch += 1
            self._compositor_raw = None
            self.force.set()
        self._slide_timer.stop()
        slider = self._compositor_slider or dcomp.slider()
        if kind[0] == "enter":
            if slider is not None and slider.material is not None and self._compositor_capture is not None:
                self._compositor_resting = True
                self._compositor_geometry = self._resting_geometry()
                self.anim_alpha, self.anim_dy = 1.0, 0.0
                self._settled()
                self.repaint()
                slider.settle_glass(self.cache_hwnd())
                return
            self.anim_alpha, self.anim_dy = 1.0, 0.0
            self._settled()                                         # apply deferred glass before exposing the resting window
            self.repaint()                                          # under the helper, which goes once this is there
            if slider is not None:
                slider.next_composition()
                slider.fade_out(.060)
                self._sliding = ("handoff", 60)
                self._time_slide(75)
        else:
            if slider is not None:
                slider.hide()
            if kind[0] != "handoff":
                self._left()
