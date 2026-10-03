"""The frosted glass behind a natively drawn window: the picture of the desktop, on its own thread.

A window that has glass (the desktop widgets, the detail card, the tray panel) mixes this in. It
asks `Api.get_desktop_backdrop` for the picture (so hidden or covered windows,
the capture exclusion, the compatibility capture and the 'still' sampling all behave as before),
makes the glass from it (the picture stretched over the card, or the liquid lens round its edge) and
hands the newest one to the GUI thread.

What the host provides: api, kind, pw, ph (device pixels), dpi, scale, style, tcol, liquid_level,
sampling, system_glass, dragging, and the methods glass_card() and glass_tiles(); and it calls
init_glass() first and start_glass() once it is shown.
"""
import threading
import time
import traceback

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter

from . import liquid, render

PROFILE = False


class GlassSignals(QObject):
    glass = Signal()                      # a new picture of the desktop is ready


class GlassMixin:
    lensed = True                         # the liquid style bends the picture at the card's edge

    # -- what the host says about the card --------------------------------------
    def glass_card(self):
        """(width, height, corner radius) of the card the glass fills, in CSS px."""
        raise NotImplementedError

    def glass_tiles(self):
        """[(x, y, w, h, radius)] in device px of the tiles whose back is blurred (liquid glass)."""
        return []

    # -- set up --------------------------------------------------------------------
    def init_glass(self):
        self.glass = None                 # the finished picture, device px
        self.mask = None
        self.latest = None
        self.glass_queued = threading.Event()
        self.sample_now = threading.Event()
        self.force = threading.Event()    # the next picture must not be taken for the last one
        self._glass_fit = None            # what the glass was made for: see fit_glass
        self.dragging = False
        self._stop = threading.Event()
        self._glass_thread = None
        self.glass_signals = GlassSignals()
        self.glass_signals.glass.connect(self._on_glass)

    def start_glass(self):
        if self._glass_thread is None:
            self._glass_thread = threading.Thread(target=self._glass_loop, daemon=True,
                                                  name="glass-" + str(self.kind))
            self._glass_thread.start()

    def stop(self):
        self._stop.set()
        self.sample_now.set()

    def invalidate_glass(self):
        self.force.set()
        self.sample_now.set()

    def reset_glass(self):
        """The style changed: nothing made before fits, not even the last picture."""
        self.mask = None
        self.glass = None
        self.latest = None
        self._glass_fit = None

    def fit_glass(self):
        """The card was measured again (every rebuild does it). Nothing happens unless its size or shape
        changed; then the glass is made again at once from the last picture (the classic glass is that
        picture stretched over the card), and a new picture is asked for.

        It used to be dropped at every measurement, and on a still desktop no new picture came to replace
        it: a detail card lost its blur each time the device it shows changed (the volume moved, a light
        went on), and the tray panel each time the preferences did."""
        key = (self.pw, self.ph, self.dpi, self.glass_card()[2], self._liquid_glass())
        if key == self._glass_fit:
            return
        self._glass_fit = key
        self.mask = None
        if self.latest is not None and not self._liquid_glass() and self._make_glass():
            self.update()
        else:
            self.glass = None             # the lens is made for one size only
        self.invalidate_glass()

    # -- the picture -----------------------------------------------------------------
    def _card_mask(self):
        cw, ch, radius = self.glass_card()
        m = QImage(self.pw, self.ph, QImage.Format_ARGB32_Premultiplied)
        m.fill(Qt.transparent)
        q = QPainter(m)
        q.setRenderHint(QPainter.Antialiasing)
        q.scale(self.scale, self.scale)
        q.setPen(Qt.NoPen)
        q.setBrush(QColor(0, 0, 0))
        q.drawPath(render.squircle(0, 0, cw, ch, radius))
        q.end()
        return m

    def _liquid_glass(self):
        return self.style == "liquid" and self.lensed

    def _on_glass(self):
        self.glass_queued.clear()
        if self._make_glass():
            self.glass_changed()

    def _make_glass(self):
        """self.glass from the last picture. False when there is none."""
        img = self.latest
        if img is None:
            return False
        if self._liquid_glass():
            self.glass = img
        else:
            # The small blurred picture stretched over the card, cut to its shape.
            if self.mask is None:
                self.mask = self._card_mask()
            out = QImage(self.pw, self.ph, QImage.Format_ARGB32_Premultiplied)
            out.fill(Qt.transparent)
            f = QPainter(out)
            f.setRenderHint(QPainter.SmoothPixmapTransform)
            f.drawImage(QRectF(0, 0, self.pw, self.ph), img)
            f.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            f.drawImage(0, 0, self.mask)
            f.end()
            out.setDevicePixelRatio(self.dpi)
            self.glass = out
        return True

    def glass_changed(self):
        """A new picture is in self.glass."""
        self.update()

    def _glass_loop(self):
        from PIL import Image
        api, kind = self.api, self.kind
        last_hash, quiet, taken = None, 0, False
        lens = card = key = None
        last = 0.0
        while not self._stop.is_set():
            try:
                if self.force.is_set():
                    self.force.clear()
                    last_hash, taken = None, False
                still = self.sampling == "still" and not self.dragging
                if still and taken and not self.sample_now.is_set():
                    self.sample_now.wait(0.5)
                    continue
                if getattr(self, "moving", False):
                    time.sleep(0.02)             # the window is coming in or going away: not now
                    continue
                self.sample_now.clear()
                # At most 30 looks a second: an animated wallpaper behind the
                # window otherwise keeps the program busy for pictures nobody can tell apart. The pace
                # is kept before the look, not after it, so the picture is as fresh as can be.
                # The tray panel, while it is open, gets as many looks as it can take (the cost of one, about
                # 25 ms, sets the pace); the widgets keep their own 30 a second whatever else is open.
                pace = 1 / 60 if kind == "flyout" else 1 / 30
                wait = pace - (time.monotonic() - last)
                if wait > 0:
                    time.sleep(wait)
                last = time.monotonic()
                pw, ph = self.pw, self.ph
                shot = api.get_desktop_backdrop(kind, last_hash, pw, ph, None, None,
                                                0 if still else None)
                if not shot:
                    last_hash = None
                    time.sleep(0.25)
                    continue
                if shot.get("skip"):
                    taken = False
                    # Hidden or covered: asked again later, but at once when the window is shown or must look again.
                    self.sample_now.wait((shot.get("retry_ms") or 500) / 1000.0)
                    continue
                if not shot.get("paced"):
                    time.sleep(max(0.016, (shot.get("ms") or 0) * 4 / 1000.0) if quiet < 4 else 3.0)
                if shot.get("unchanged"):
                    quiet += 1
                    taken = True
                    continue
                quiet = 0
                raw = shot.get("blur_raw")
                if not raw:
                    continue
                if abs(shot["w"] - pw) > 3 or abs(shot["h"] - ph) > 3:
                    last_hash = None
                    continue
                picture = Image.frombytes("RGB", (shot["blur_w"], shot["blur_h"]), raw)
                last_hash = shot.get("hash")
                taken = True
                if self._liquid_glass():
                    t = max(0, min(100, int(self.liquid_level))) / 100.0
                    cw, ch, radius = self.glass_card()
                    want = (pw, ph, radius, self.scale)
                    if key != want:
                        lens = liquid.Lens(pw, ph, radius * self.scale)
                        card = lens.card_mask()
                        key = want
                    out = lens.frame(picture, card, self.glass_tiles(), (8 + 4 * t) * self.scale,
                                     frost=22.0 * t * self.scale)
                    self.latest = QImage(out.tobytes(), out.width, out.height, out.width * 4,
                                         QImage.Format_RGBA8888).copy()
                    self.latest.setDevicePixelRatio(self.dpi)
                else:
                    self.latest = QImage(picture.tobytes(), picture.width, picture.height,
                                         picture.width * 3, QImage.Format_RGB888).copy()
                if not self.glass_queued.is_set():           # only the newest is ever painted
                    self.glass_queued.set()
                    self.glass_signals.glass.emit()
            except Exception:
                traceback.print_exc()
                time.sleep(0.5)
