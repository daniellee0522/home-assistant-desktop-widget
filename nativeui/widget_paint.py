"""How a desktop widget's surface is painted (widget.py): its card and tiles, the glass under them, the picture a detail\ncard grows from, and the clock's ring of seconds."""
import datetime

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPixmap


from . import kinds, render
from .widget_common import SECOND_FRAME_MS, _rect

class SurfacePaint:
    """How a desktop widget's surface is painted (widget.py): its card and tiles, the glass under them, the picture a detail\ncard grows from, and the clock's ring of seconds"""

    def _draw(self, dim):
        img = QImage(self.pw, self.ph, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        if self.wkind == "custom":
            self.kit.draw(p, dim)
        elif self.wkind == "tiles":
            self.empty_button = render.draw_widget(p, self.size_key, self.tiles, self.states, self.theme, None,
                                                   self.scale, dim, self.style, self._ui(), self.theme_raw)
        else:
            extras = self.extras
            if self.wkind == "clock":                     # its ring is drawn live, in paintEvent
                now = self._face_time or datetime.datetime.now()
                if self._face_time is None:
                    self._drawn_minute = now.replace(second=0, microsecond=0)
                extras = dict(extras, live_ticks=True, now=now, font=self.clock_font)
            got = kinds.draw_widget(p, self.wkind, self.size_key, self.tiles, self.states, self.theme,
                                    self.scale, dim, self.style, self._ui(), self.theme_raw, extras)
            self.kind_buttons = got if isinstance(got, list) else []
            self.empty_button = None if isinstance(got, list) else got
        p.end()
        pix = QPixmap.fromImage(img)
        pix.setDevicePixelRatio(self.dpi)
        return pix

    # -- the glass (nativeui/glass.py) asks what the card is -------------------------
    def glass_card(self):
        cw, ch = render.widget_size(self.size_key)
        return cw, ch, self.tcol["radius_panel"]

    def glass_tiles(self):
        if self.wkind != "tiles":                # the other kinds draw over their glass themselves
            return []
        s, off, H = self.scale, self.scroll, render.widget_size(self.size_key)[1]
        return [(round(x * s), round((y - off) * s), round(w * s), round(h * s), round(self.tcol["radius_tile"] * s))
                for x, y, w, h in self.rects if 0 <= y - off and y - off + h <= H]

    def set_transition_tile(self, tile_id=None):
        self.transition_tile = tile_id
        if tile_id is None:
            self.capture_transition_tile = None
            self.transition_cover = None
        self.repaint()

    def prepare_transition(self, tile_id):
        self.capture_transition_tile = tile_id

    def set_transition_cover(self, rect):
        if rect != getattr(self, "transition_cover", None):
            self.transition_cover = rect
            self.update()

    def _tile_path(self, tile_id):
        index = next((i for i,t in enumerate(self.tiles) if t["id"] == tile_id), -1)
        if index < 0 or index >= len(self.rects):
            return None
        x,y,w,h = self.rects[index]
        ratio = self.scale/self.dpi
        return render.squircle(x*ratio, (y-self.scroll)*ratio, w*ratio, h*ratio,
                               self.tcol["radius_tile"]*ratio)

    def _paint_image(self, hidden_tile=None, gpu_snapshot=True):
        if gpu_snapshot and self._gpu_receiver is not None and self._gpu_receiver.visible:
            return self._gpu_receiver.snapshot(hidden_tile)
        image = QImage(self.pw,self.ph,QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        image.setDevicePixelRatio(self.dpi)
        painter = QPainter(image)
        hole = (self._tile_path(hidden_tile) if hidden_tile is not None else
                self._transition_hole() if not gpu_snapshot else None)
        if hole is not None:
            outer = QPainterPath()
            outer.addRect(QRectF(0,0,self.pw/self.dpi,self.ph/self.dpi))
            painter.setClipPath(outer.subtracted(hole))
        self._paint_contents(painter, include_glass=gpu_snapshot)
        painter.end()
        return image

    def backdrop_image(self):
        """Capture without the lifted tile, while the visible source can stay in place."""
        return self._paint_image(getattr(self,"capture_transition_tile",None))

    def transition_image(self, tile_id):
        """The live source tile, rendered offscreen even while its on-screen copy is hidden."""
        index = next((i for i, tile in enumerate(self.tiles) if tile["id"] == tile_id), -1)
        if index < 0 or index >= len(self.rects):
            return None
        x, y, w, h = self.rects[index]
        self.overlay = self.overlay_dim = None
        image = self._paint_image()
        return image.copy(round(x*self.scale), round((y-self.scroll)*self.scale),
                          round(w*self.scale), round(h*self.scale))

    def _transition_hole(self):
        hole = self._tile_path(getattr(self, "transition_tile", None))
        cover = getattr(self, 'transition_cover', None)
        source_rect = _rect(self._hwnd) if cover is not None else None
        if hole is not None and source_rect:
            covered = render.squircle((cover.x()-source_rect[0])/self.dpi,
                                       (cover.y()-source_rect[1])/self.dpi,
                                       cover.width()/self.dpi, cover.height()/self.dpi,
                                       self.tcol['radius_tile']*self.scale/self.dpi)
            hole = hole.intersected(covered)
        return hole

    def _qt_paintEvent(self, event):
        if self._gpu_receiver is not None and self._gpu_receiver.visible:
            p = QPainter(self)
            p.setCompositionMode(QPainter.CompositionMode_Source)
            p.fillRect(self.rect(), Qt.transparent)
            # A completely transparent layered HWND has no native hit-test
            # pixels. Keep a one-byte alpha input backing under the compositor.
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 1))
            p.scale(self.scale / self.devicePixelRatioF(), self.scale / self.devicePixelRatioF())
            cw, ch = render.widget_size(self.size_key)
            p.drawPath(render.squircle(0, 0, cw, ch, self.tcol['radius_panel']))
            p.end()
            self._gpu_receiver.queue(foreground=True)
            return
        if self._gpu_receiver is not None and self.wants_glass():
            self._gpu_receiver.queue(foreground=True)
        p = QPainter(self)
        p.scale(self.dpi/(self.devicePixelRatioF() or 1), self.dpi/(self.devicePixelRatioF() or 1))
        hole = self._transition_hole()
        if hole is not None:
            outer = QPainterPath()
            outer.addRect(QRectF(0, 0, self.pw/self.dpi, self.ph/self.dpi))
            p.setClipPath(outer.subtracted(hole))
        self._paint_contents(p)
        p.end()

    def _paint_contents(self, p, include_glass=True):
        if self.overlay is None and self.dim_t < 1:     # fully dimmed, the lit face is not on show
            self.overlay = self._draw(False)
        if self.dim_t > 0 and self.overlay_dim is None:
            self.overlay_dim = self._draw(True)
        if include_glass and self.glass is not None and not self.system_glass:
            p.drawImage(0, 0, self.glass)
        if self.dim_t <= 0:
            p.drawPixmap(0, 0, self.overlay)
        elif self.dim_t >= 1:
            p.drawPixmap(0, 0, self.overlay_dim)
        else:
            # A cross-fade: (1 - t) of the lit picture plus t of the dimmed one.
            if self.mix is None or self.mix.width() != self.pw or self.mix.height() != self.ph:
                self.mix = QImage(self.pw, self.ph, QImage.Format_ARGB32_Premultiplied)
                self.mix.setDevicePixelRatio(self.dpi)
            m = QPainter(self.mix)
            m.setCompositionMode(QPainter.CompositionMode_Source)
            m.fillRect(self.mix.rect(), Qt.transparent)
            m.setCompositionMode(QPainter.CompositionMode_SourceOver)
            m.setOpacity(1 - self.dim_t)
            m.drawPixmap(0, 0, self.overlay)
            m.setCompositionMode(QPainter.CompositionMode_Plus)
            m.setOpacity(self.dim_t)
            m.drawPixmap(0, 0, self.overlay_dim)
            m.end()
            p.drawImage(0, 0, self.mix)
        if self.wkind == "clock":
            self._paint_ticks(p)

    def _paint_ticks(self, p):
        now = datetime.datetime.now()
        hand = kinds.clock_hand(now, not self.dim_target)
        W, H = render.widget_size(self.size_key)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(self.scale / self.dpi, self.scale / self.dpi)
        for dim, weight in ((False, 1 - self.dim_t), (True, self.dim_t)):
            if weight > 0.001:
                p.setOpacity(weight)
                kinds.draw_clock_ticks(p, W, H, kinds.clock_ink(self.theme, dim), None if dim else hand,
                                       self.tcol["radius_panel"])
        p.restore()

    def _warm_next_minute(self, now):
        """The coming minute's digits are made in the background while this one is on show, so that changing to it is not a stall."""
        cw, ch = render.widget_size(self.size_key)
        kinds.warm_clock_digits(cw, ch, now.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1), self.clock_font)

    def _second(self):
        if not self.isVisible() or self.wkind != "clock":
            self.second_timer.stop()
            return
        now = datetime.datetime.now()
        self._warm_next_minute(now)
        minute = now.replace(second=0, microsecond=0)
        if self._drawn_minute is not None and minute != self._drawn_minute:
            self.overlay = None                             # a new minute: the digits again
            ahead, self._ahead = self._ahead, None
            self.overlay_dim = ahead[1] if ahead is not None and ahead[0] == minute else None
        elif self.dim_target and now.second >= 58 and self._ahead is None and self._drawn_minute is not None:
            # Dimmed, the next minute's face is drawn now, a moment before it is needed, instead of in
            # the frame the minute changes.
            coming = minute + datetime.timedelta(minutes=1)
            self._face_time = coming
            try:
                self._ahead = (coming, self._draw(True))
            finally:
                self._face_time = None
        self.update()
        self._next_second(now)

    def _next_second(self, now=None):
        """The next frame of the ring: soon while the hand moves, else at the next second. Dimmed, the ring is
        still: the next frame is only the coming minute's face, drawn ahead at :58 and shown at :00."""
        now = now or datetime.datetime.now()
        ms = now.microsecond / 1000
        if self.dim_target:
            into_minute = now.second * 1000 + ms
            ahead_at = 58000 if self._ahead is None and into_minute < 58000 else 60000
            self.second_timer.start(int(ahead_at - into_minute) + 2)
            return
        moving = ms < kinds.HAND_MOVE_S * 1000
        self.second_timer.start(int(min(SECOND_FRAME_MS, kinds.HAND_MOVE_S * 1000 - ms) + 1) if moving
                                else int(1000 - ms) + 2)
