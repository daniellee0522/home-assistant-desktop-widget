"""How the tray panel comes and goes (panel.py): a picture slid by the desktop compositor, or drawn by the panel itself\nwhere the compositor cannot be had."""
import time

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter

from . import dcomp, render, screens

# What is on the classic card from this opacity (of 255) is blended over the glass by the panel (_over_glass); fainter
# pixels (the card's trace, a soft shadow's tail) are left to the desktop.
OPAQUE_FROM = 8

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
        if self._compositor_resting:
            self._content_dirty = True                          # (a classic card's tint returns to it)
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
        glass = self._glass_layer(size, at)
        if glass is not None and not self._liquid_glass():
            card = picture(self._content_without_fill())
            if at is not None:                                  # (the compositor's two layers)
                self._slide_card, self._rest_glass = card, glass
                card = self._over_glass(card, glass)
        else:
            card = picture(self.content_image())
        return glass, card

    def _over_glass(self, content, glass):
        """`content` (premultiplied, in the window's pixels) with what is seen of it blended over `glass` here, by Qt's
        rule, and so opaque there; its clear and nearly clear pixels are left for the desktop to blend. The desktop
        blends in linear light where automatic colour management is on: a white tile's antialiased edge over dark
        glass came out much brighter and its curve looked stepped, and translucent buttons changed colour where the
        slide ended. The glass under them is the card's at rest, which the moving card carries: a button's worth.
        So is a band along the card's outline, with the glass cut there by the card's smooth mask: the compositor's
        clip is one-pixel columns inside the outline, and the card's edge was stepped."""
        w, h = content.width(), content.height()
        mask, faint = self._opaque_parts(content)
        out = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        out.fill(Qt.transparent)
        painter = QPainter(out)
        painter.drawImage(0, 0, glass, 0, 0, w, h)
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        painter.drawImage(0, 0, self._outline_mask())
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.drawImage(0, 0, content)
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        painter.drawImage(0, 0, mask)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.drawImage(0, 0, faint)
        painter.end()
        return out

    def _outline_mask(self):
        """The card's shape, antialiased, in the window's pixels (glass.py's mask)."""
        if self.mask is None:
            self.mask = self._card_mask()
        return self.mask

    def _outline_band(self):
        """A band two pixels wide along the card's outline (as an L picture): its partly covered pixels and those the
        compositor's columns may leave out."""
        outline = self._outline_mask()
        key = outline.cacheKey()
        held = getattr(self, "_band_held", None)
        if held is not None and held[0] == key:
            return held[1]
        from PIL import Image, ImageFilter
        w, h = outline.width(), outline.height()
        coverage = Image.frombytes("RGBA", (w, h), outline.constBits().tobytes()).getchannel(3)
        band = coverage.point([255 if 0 < a < 255 else 0 for a in range(256)]).filter(ImageFilter.MaxFilter(5))
        self._band_held = (key, band)
        return band

    def _opaque_parts(self, content):
        """(where `content` is blended here, as an alpha picture; the rest of it), kept for the same picture."""
        band = self._outline_band()
        key = (content.cacheKey(), content.width(), content.height(), id(band))
        held = getattr(self, "_opaque_held", None)
        if held is not None and held[0] == key:
            return held[1]
        from PIL import Image, ImageChops
        w, h = content.width(), content.height()
        alpha = Image.frombytes("RGBA", (w, h), content.constBits().tobytes()).getchannel(3)
        cut = alpha.point([255 if a >= OPAQUE_FROM else 0 for a in range(256)])
        edge = Image.new("L", (w, h), 0)
        edge.paste(band, (0, 0))
        cut = ImageChops.lighter(cut, edge).tobytes()
        mask = QImage(cut, w, h, w, QImage.Format_Alpha8).copy()
        faint = content.copy()
        painter = QPainter(faint)
        painter.setCompositionMode(QPainter.CompositionMode_DestinationOut)
        painter.drawImage(0, 0, mask)
        painter.end()
        self._opaque_held = (key, (mask, faint))
        return mask, faint

    def _glass_layer(self, size, at=None, shot=None):
        """The compositor's still layer: the desktop's picture over `size` (physical px) and, but for the liquid
        style, the card's tint blended into it. None when there is no picture yet, or the desktop draws the glass.
        `shot`: a picture of the desktop under the whole layer, taken while it slides (panel._on_glass)."""
        # self.glass is already cut to the resting card. It must never be the
        # stationary animation background: its old bottom corners would remain
        # visible inside the moving card even with a correct outer clip.
        source = self.latest if self.custom_bg() or not self._liquid_glass() else self.raw_latest
        if source is None:
            source = self.glass
        glass = None
        source_height = self.ph
        if shot is not None:
            source, source_height = shot, size[1]
        elif (at is not None and (size[1] > self.ph or self._liquid_glass())
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
            if not self._liquid_glass():
                # The card's tint is one colour, so it looks the same carried by the card or lying in the glass, which
                # shows only inside the card's moving outline. The glass keeps it at rest too (_finish_slide).
                painter.setCompositionMode(QPainter.CompositionMode_SourceAtop)    # (only where there is glass)
                painter.fillRect(glass.rect(), render.rgba(self.card_tokens()["panel"]))
            painter.end()
        return glass

    def _content_without_fill(self):
        """The card's picture with its tint left out (it is in the glass), the resting one made again after."""
        self.fill_in_glass, self._content_dirty = True, True
        try:
            return self.content_image().copy()
        finally:
            self.fill_in_glass, self._content_dirty = False, True

    def _rest_over_compositor(self, slider):
        """The classic panel comes to rest over the compositor's still glass, as the liquid one does over its
        material: the window draws only what is on the card. The desktop blends translucent layers by its own
        rule (dcomp.py; with automatic colour management, in linear light), not Qt's, so a card drawn with its glass
        by the panel had its buttons and rims change colour where the slide ended. Over the compositor's glass both
        are blended by the desktop. The glass follows the desktop at rest through panel._push_resting_glass."""
        self._compositor_resting = True
        self._compositor_geometry = self._resting_geometry()
        # The glass under it is the slide's, and it goes on being taken over the same area as while it moved: a
        # picture of the panel's own window (shorter than the layer, which reaches the taskbar) is blurred over other
        # cells, and the glass shifted where the slide ended (a flash), as it did when an older picture took its place.
        shot = self._resting_shot()
        self._resting_glass_from = (shot if shot is not None else self.latest, self.card_tokens()["panel"], slider.size)
        self._content_dirty = True
        self.anim_alpha, self.anim_dy = 1.0, 0.0
        self._settled()
        # The window shows the card first, and the compositor's card goes only once the desktop has taken that in:
        # the window's picture can reach the screen a frame after the compositor's, and taking the card away with it
        # showed bare glass for a frame. Both show the card's contents opaque and alike (_over_glass), so for the
        # frames they lie one over the other nothing changes.
        self.repaint()
        slider.next_composition()
        slider.next_composition()
        slider.settle_glass(self.cache_hwnd())

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
        if self._compositor_resting:
            self._content_dirty = True
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
            # The glass is taken live while the card moves: the liquid style's into its material, the classic one's
            # into the still layer (panel._on_glass). A picture of its own behind the panel does not change.
            live = glass is not None and (material is not None or not (self._liquid_glass() or self.custom_bg()))
            self._compositor_capture = rect if live else None
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
                # The liquid card is translucent: commit the helper and clear the native foreground before waiting
                # for a desktop frame, as waiting between them doubles its tint. The classic card's contents are
                # opaque and alike in both (_over_glass): the window clears once the desktop shows the helper's,
                # else a frame of bare glass could come between them.
                opaque = glass is not None and not self._liquid_glass()
                slider.show(rect, glass, card, 0.0, radius, above=hwnd, columns=columns,
                            liquid=material, wait=opaque)
                if opaque:
                    slider.next_composition()
                    slider.next_composition()
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
            if slider is not None and slider.shown and not self._liquid_glass() and not self.system_glass:
                self._rest_over_compositor(slider)
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
