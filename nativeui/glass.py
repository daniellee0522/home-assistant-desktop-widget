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
import math
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
        self.raw_latest = None             # unmasked desktop, for a moving card's backdrop
        self._compositor_capture = None
        self._compositor_raw = None
        self._compositor_epoch = 0
        self._compositor_since = 0.0
        self._compositor_presented_at = 0.0
        self.glass_queued = threading.Event()
        self.sample_now = threading.Event()
        self.force = threading.Event()    # the next picture must not be taken for the last one
        self._glass_fit = None            # what the glass was made for: see fit_glass
        self._glass_generation = 0
        self._latest_generation = 0
        self.dragging = False
        self._stop = threading.Event()
        self._glass_thread = None
        self._glass_refresh_rate = 60.0
        self._glass_screen = None
        self._glass_window = None
        self._gpu_receiver = None
        self._gpu_shared_capture = False
        self.glass_signals = GlassSignals()
        self.glass_signals.glass.connect(self._on_glass)

    def start_glass(self):
        if self.kind == 'main' or self.kind.startswith('w:'):
            # Read Qt's screen on the GUI thread, never from the capture worker.
            handle = self.windowHandle()
            if handle is not self._glass_window:
                if self._glass_window is not None:
                    self._glass_window.screenChanged.disconnect(self._bind_glass_screen)
                self._glass_window = handle
                if handle is not None:
                    handle.screenChanged.connect(self._bind_glass_screen)
            self._bind_glass_screen(self.screen())
        if self._gpu_receiver is not None:
            from .widget_capture import register
            register(self)
            return
        if self._glass_thread is None:
            self._glass_thread = threading.Thread(target=self._glass_loop, daemon=True,
                                                  name="glass-" + str(self.kind))
            self._glass_thread.start()

    def _set_glass_refresh_rate(self, rate):
        rate = float(rate)
        self._glass_refresh_rate = rate if math.isfinite(rate) and rate > 0 else 60.0

    def _bind_glass_screen(self, screen):
        if screen is not self._glass_screen:
            if self._glass_screen is not None:
                try:
                    self._glass_screen.refreshRateChanged.disconnect(self._set_glass_refresh_rate)
                except RuntimeError:  # the old monitor may already have been removed
                    pass
            self._glass_screen = screen
            if screen is not None:
                screen.refreshRateChanged.connect(self._set_glass_refresh_rate)
        self._set_glass_refresh_rate(screen.refreshRate() if screen is not None else 60.0)

    def _glass_pace(self):
        if self.kind == 'main' or self.kind.startswith('w:'):
            return 1.0 / self._glass_refresh_rate
        if self.kind == 'flyout':
            return 1 / 120 if getattr(self, '_gpu_polling', False) else 1 / 60    # (a poll on the GPU is cheap)
        return 1 / 30

    def stop(self):
        if self._gpu_receiver is not None:
            self._gpu_receiver.close()
            self._gpu_receiver = None
        self._stop.set()
        self.sample_now.set()

    def invalidate_glass(self):
        self._glass_generation += 1
        self.force.set()
        self.sample_now.set()
        if self._gpu_shared_capture:
            from .widget_capture import request
            request()

    def reset_glass(self):
        """The style changed: nothing made before fits, not even the last picture."""
        self.mask = None
        self.glass = None
        self.latest = None
        self.raw_latest = None
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
        if (self.latest is not None and self._gpu_receiver is None and not self._liquid_glass()
                and self._make_glass()):
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

    def wants_glass(self):
        """Whether anything of the desktop shows through the card now. A card whose face is solid (a clock, a
        player...) asks for no pictures of the desktop until it is clear glass again."""
        return True

    def _on_glass(self):
        self.glass_queued.clear()
        if self._latest_generation != self._glass_generation:
            return
        if self._gpu_receiver is not None:
            self._gpu_receiver.queue(self.latest)
            return
        if self._make_glass():
            self.glass_changed()

    def _make_glass(self):
        """self.glass from the last picture. False when there is none."""
        img = self.latest
        if img is None or not isinstance(img, QImage):    # (a desktop frame is the GPU's to draw)
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
                if self._gpu_shared_capture:
                    self._stop.wait(.25)
                    continue
                if self.force.is_set():
                    self.force.clear()
                    last_hash, taken, quiet = None, False, 0
                capture_rect = self._compositor_capture
                capture_epoch = self._compositor_epoch
                still = (self.sampling == "still" and not self.dragging
                         and (capture_rect is None or getattr(self, "_compositor_resting", False)))
                if still and taken and not self.sample_now.is_set():
                    self.sample_now.wait(0.5)
                    continue
                if (getattr(self, "moving", False) or getattr(self, "animation_active", False)) and capture_rect is None:
                    time.sleep(0.02)             # the window is coming in or going away: not now
                    continue
                if not self.wants_glass():       # nothing of the desktop shows: no looks at it until it does
                    taken = False
                    last_hash = None
                    self.sample_now.wait(1.0)
                    self.sample_now.clear()      # (else a stray request would spin this round)
                    continue
                self.sample_now.clear()
                # Widgets follow their current monitor. DXGI still waits for
                # actual changes, and identical pictures never reach painting.
                # Pace before capture; never queue work to catch up a late frame.
                pace = self._glass_pace()
                due = last + pace
                wait = due - time.monotonic()
                if wait > 0:
                    # Python's high-resolution sleep on Windows can pace above
                    # 60 Hz; Event.wait uses the coarser system wait timeout.
                    time.sleep(wait)
                now = time.monotonic()
                # Keep a steady deadline so small sleep overruns don't lower
                # the rate. Drop missed deadlines after a slow frame or idle.
                last = due if now - due < pace else now
                pw, ph = self.pw, self.ph
                cx = cy = None
                if capture_rect is not None:
                    cx, cy, pw, ph = capture_rect
                generation = self._glass_generation
                capture_started = time.monotonic()
                shot = api.get_desktop_backdrop(kind, last_hash, pw, ph, cx, cy,
                                                0 if still else None,
                                                **({"gpu": True} if kind == "flyout" and capture_rect is not None
                                                   and getattr(api, "flyout_gpu_backdrop", False) else {}))
                if not shot:
                    last_hash = None
                    self.sample_now.wait(0.25)
                    continue
                if shot.get("skip"):
                    taken = False
                    # Hidden or covered: asked again later, but at once when the window is shown or must look again.
                    self.sample_now.wait((shot.get("retry_ms") or 500) / 1000.0)
                    continue
                if not shot.get("paced") and shot.get("unchanged"):
                    # A flyout must notice a desktop that starts moving immediately,
                    # including after a quiet stretch. Only background widgets back off.
                    self.sample_now.wait(1 / 60 if kind == "flyout" else
                                         (pace if quiet < 4 else 3.0))
                if generation != self._glass_generation:
                    last_hash, taken = None, False
                    continue
                if shot.get("unchanged"):
                    quiet += 1
                    taken = True
                    continue
                quiet = 0
                if shot.get("gpu") and capture_rect is not None:
                    # The compositor copies the picture on the GPU itself; only which one is wanted is sent.
                    if capture_rect != self._compositor_capture or capture_epoch != self._compositor_epoch:
                        last_hash, taken = None, False
                        continue
                    from .widget_capture import DesktopFrame
                    self._compositor_raw = (capture_rect, DesktopFrame(shot["gpu"], 0, shot["copy"]),
                                            capture_epoch, capture_started)
                    last_hash, taken = shot.get("hash"), True
                    self._gpu_polling = True
                    if not self.glass_queued.is_set():
                        self.glass_queued.set()
                        self.glass_signals.glass.emit()
                    continue
                self._gpu_polling = False
                raw = shot.get("blur_raw")
                if not raw:
                    continue
                if abs(shot["w"] - pw) > 3 or abs(shot["h"] - ph) > 3:
                    last_hash = None
                    continue
                if capture_rect is not None:
                    if capture_rect != self._compositor_capture or capture_epoch != self._compositor_epoch:
                        last_hash, taken = None, False
                        continue
                    self._compositor_raw = (capture_rect, QImage(raw, shot["blur_w"], shot["blur_h"],
                                                               shot["blur_w"] * 3, QImage.Format_RGB888).copy(),
                                            capture_epoch, capture_started)
                    last_hash, taken = shot.get("hash"), True
                    if not self.glass_queued.is_set():
                        self.glass_queued.set()
                        self.glass_signals.glass.emit()
                    continue
                # Keep a capture already in flight, including its hash. Discarding
                # it would force another full capture on a still desktop.
                if capture_rect != self._compositor_capture:
                    last_hash, taken = None, False
                    continue
                while (getattr(self, "moving", False) or getattr(self, "animation_active", False)) and self._compositor_capture is None and not self._stop.is_set():
                    self._stop.wait(0.02)
                if capture_rect != self._compositor_capture:
                    last_hash, taken = None, False
                    continue
                if self._stop.is_set():
                    break
                if generation != self._glass_generation:
                    last_hash, taken = None, False
                    continue
                picture = Image.frombytes("RGB", (shot["blur_w"], shot["blur_h"]), raw)
                raw_latest = QImage(raw, picture.width, picture.height,
                                    picture.width * 3, QImage.Format_RGB888).copy()
                last_hash = shot.get("hash")
                taken = True
                if self._gpu_receiver is not None and self._liquid_glass():
                    latest = raw_latest
                elif self._liquid_glass():
                    t = max(0, min(100, int(self.liquid_level))) / 100.0
                    cw, ch, radius = self.glass_card()
                    want = (pw, ph, radius, self.scale)
                    if key != want:
                        lens = liquid.Lens(pw, ph, radius * self.scale)
                        card = lens.card_mask()
                        key = want
                    out = lens.frame(picture, card, self.glass_tiles(), (8 + 4 * t) * self.scale,
                                     frost=22.0 * t * self.scale)
                    latest = QImage(out.tobytes(), out.width, out.height, out.width * 4,
                                         QImage.Format_RGBA8888).copy()
                    latest.setDevicePixelRatio(self.dpi)
                else:
                    latest = QImage(picture.tobytes(), picture.width, picture.height,
                                         picture.width * 3, QImage.Format_RGB888).copy()
                if generation != self._glass_generation:
                    last_hash, taken = None, False
                    continue
                self.raw_latest = raw_latest
                self.latest, self._latest_generation = latest, generation
                if not self.glass_queued.is_set():           # only the newest is ever painted
                    self.glass_queued.set()
                    self.glass_signals.glass.emit()
            except Exception:
                traceback.print_exc()
                time.sleep(0.5)
