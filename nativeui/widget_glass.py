"""One latest-frame presentation clock for all GPU desktop widgets.

Qt remains the input/state owner. Each click-through compositor window draws
its own glass and native foreground, at the owner's exact z-order. No clock
keeps running after unchanged capture stops submitting work.
"""
import ctypes as C
import os
import threading
import time
import traceback

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QImage

from . import dcomp
from .animation_clock import FrameTimer
from .gpu_glass import Renderer

_scheduler = None
_schedulers = {}
_controllers = set()


def hwnds():
    return {c.hwnd for controller in tuple(_controllers)
            if (c := controller.compositor) is not None and c.shown}


def output_for(surface, compositor):
    """IDXGIOutput on the owner's monitor, held independently of the renderer."""
    from winsys.dxgi_capture import _OUTPUT_DESC
    dcomp._user32.MonitorFromWindow.argtypes = [C.c_void_p, C.c_uint]
    dcomp._user32.MonitorFromWindow.restype = C.c_void_p
    monitor = dcomp._user32.MonitorFromWindow(surface.cache_hwnd(), 2)
    adapter = dcomp._new(compositor.dxgi_device, 7, ())
    try:
        index = 0
        while True:
            output = C.c_void_p()
            try:
                dcomp._call(adapter, 7, (C.c_uint, C.c_void_p), index, C.byref(output))
            except OSError:
                return None
            desc = _OUTPUT_DESC()
            dcomp._call(output.value, 7, (C.c_void_p,), C.byref(desc))
            if desc.Monitor == monitor:
                return output.value
            dcomp._release(output.value)
            index += 1
    finally:
        dcomp._release(adapter)


class Scheduler(QObject):
    def __init__(self, output=None, rate=60):
        super().__init__()
        self.pending = {}
        self.timer = FrameTimer(self)
        self.timer.vsync = True
        self.output = output
        self.timer.setInterval(max(1, round(1000 / rate)))
        if output is not None:
            self.timer.vsync_waiter = lambda: dcomp._call(output, 10, ())
        self.animations = set()
        self._ticking = False
        self.timer.timeout.connect(self.tick)
        self.idle = 0
        self.scheduled = False

    def subscribe(self, animation):
        self.animations.add(animation)
        self.timer.start()

    def unsubscribe(self, animation):
        self.animations.discard(animation)
        if not self.animations:
            self.timer.stop()
            if self.pending and not self._ticking and not self.scheduled:
                self.scheduled = True
                QTimer.singleShot(0, self.flush)

    def tick(self):
        self._ticking = True
        try:
            for animation in tuple(self.animations):
                if animation.isActive():
                    animation.timeout.emit()
            self.flush()
        finally:
            self._ticking = False

    def submit(self, controller, image=None, foreground=False, paced=False):
        previous = self.pending.get(controller, (None, False))
        self.pending[controller] = (image if image is not None else previous[0],
                                    foreground or previous[1])
        self.idle = 0
        # Desktop packets and dim animations already have a refresh clock.
        # Batch other UI updates in one GUI turn without a second vsync worker.
        if not paced and not self.animations and not self.scheduled:
            self.scheduled = True
            QTimer.singleShot(0, self.flush)

    def flush(self):
        self.scheduled = False
        work, self.pending = self.pending, {}
        if not work:
            self.idle += 1
            # Brief packet gaps should not tear down and restart the vblank
            # thread; a truly static desktop still stops the clock after 60 ms.
            if not self.animations and self.idle >= max(2, round(60 / self.timer.interval())):
                self.timer.stop()
            return
        self.idle = 0
        compositions = set()
        for controller, (image, foreground) in work.items():
            renderer = controller.renderer
            if renderer is not None and hasattr(image, 'copy_into') and controller.key == controller.configuration():
                try:
                    renderer.issue_desktop(image)   # every widget starts before any waits for its result
                except Exception:
                    renderer.issued = None
        # Making a card's face again paints it twice: one a tick, so that a dozen cards
        # waking at once spread over a few frames instead of holding up one.
        rebuilds, deferred = 0, {}
        for controller, (image, foreground) in work.items():
            if (foreground or not controller.visible) and controller.renderer is not None:
                if rebuilds >= 1:
                    deferred[controller] = (image, foreground)
                    continue
                rebuilds += 1
            try:
                controller.present(image, foreground, commit=False)
                if controller.compositor is not None:
                    compositions.add(controller.compositor.composition)
            except Exception:
                controller.fail(traceback.format_exc())
        for composition in compositions:
            dcomp._call(composition, 3, ())
        for controller, held in deferred.items():
            self.pending.setdefault(controller, held)
        if deferred and not self.animations and not self.scheduled:
            self.scheduled = True
            QTimer.singleShot(0, self.flush)

    def remove(self, controller):
        self.pending.pop(controller, None)
        if not self.pending and not self.animations:
            self.timer.stop()


def scheduler(surface=None, compositor=None):
    global _scheduler
    if surface is not None:
        screen = surface.screen()
        key = screen.name() if screen is not None else ''
        if key not in _schedulers:
            try:
                output = output_for(surface, compositor) if compositor is not None else None
            except OSError:
                output = None
            _schedulers[key] = Scheduler(output, surface._glass_refresh_rate)
        _scheduler = _schedulers[key]
        return _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler


class Controller:
    def __init__(self, surface):
        self.surface = surface
        self.compositor = None
        self.renderer = None
        self.last_image = None
        self.visible = False
        self.key = None
        self.frames = 0
        self.checked, self.owed = 0.0, False      # the last desktop picture looked at; one left unlooked at
        self.clock = None
        try:
            shared = next((c.compositor for c in _controllers if c.compositor is not None), None)
            self.compositor = dcomp.Slider(shared=shared)
            # Owned popup z-order follows the source even when it is sent to
            # the desktop bottom without a move or a Qt repaint.
            set_owner = dcomp._user32.SetWindowLongPtrW
            set_owner.argtypes = [C.c_void_p, C.c_int, C.c_ssize_t]
            set_owner.restype = C.c_ssize_t
            set_owner(self.compositor.hwnd, -8, surface.cache_hwnd())
            _controllers.add(self)
        except Exception:
            self.close()
            raise

    def configuration(self):
        s = self.surface
        return (s.pw, s.ph, s.glass_card()[2] * s.scale, s.scale,
                s.liquid_level, tuple(s.glass_tiles()))

    def warm(self):
        """Make the renderer of a card that has no glass yet, so that dimming it does not wait for one."""
        s, c = self.surface, self.compositor
        if self.renderer is not None or c is None or s.wants_glass() or not allowed(s):
            return
        key = self.configuration()
        w, h, radius, scale, level, tiles = key
        c._make_surfaces(w, h)
        self.renderer = Renderer(c, (w, h), radius, scale, level, tiles)
        dcomp._call(c.glass_visual, 13, (C.c_void_p,), None)
        dcomp._call(c.card_visual, 15, (C.c_void_p,), None)
        self.key = key

    def queue(self, image=None, foreground=False, paced=False):
        if image is not None:
            self.last_image = image
        clock = scheduler(self.surface, self.compositor)
        if self.clock is not None and self.clock is not clock:
            self.clock.remove(self)
        self.clock = clock
        clock.submit(self, image, foreground, paced)
        if image is None:
            from .widget_capture import request
            request()

    def present(self, image, foreground, commit=True):
        s, c = self.surface, self.compositor
        if c is None or not s.isVisible() or not s.wants_glass():
            self.hide()
            return
        if not allowed(s):
            self.close()
            s._gpu_receiver = None
            s.reset_glass()
            s.invalidate_glass()
            s.start_glass()
            s.update()
            return
        key = self.configuration()
        if key != self.key:
            if self.renderer is not None:
                self.renderer.close()
            w, h, radius, scale, level, tiles = key
            c._make_surfaces(w, h)
            self.renderer = Renderer(c, (w, h), radius, scale, level, tiles)
            dcomp._call(c.glass_visual, 13, (C.c_void_p,), None)
            dcomp._call(c.card_visual, 15, (C.c_void_p,), None)
            self.key = key
            image = image if image is not None else self.last_image
            foreground = True
        # While the card fades, its own redraws make the desktop report changes: look at the desktop
        # at most 30 times a second then, and once more as soon as the fade lets it.
        now = time.monotonic()
        fading = s.dim_timer.isActive()
        desktop = hasattr(image, 'copy_into')
        if desktop and fading and now - self.checked < 1 / 30:
            self.owed, image, desktop = True, None, False
        elif (image is None and self.owed and hasattr(self.last_image, 'copy_into')
                and (not fading or now - self.checked >= 1 / 30)):
            image, desktop = self.last_image, True
        if desktop:
            self.checked, self.owed = now, False
        unchanged = False
        if image is not None:
            if hasattr(image, 'copy_into'):
                outcome = self.renderer.update_desktop(image)
                if outcome is None:
                    # The desktop can't be copied on the GPU (rebuilt, moved to another screen):
                    # ask for the same picture through the CPU.
                    s._gpu_direct_after = time.monotonic() + 1.0
                    s.invalidate_glass()
                unchanged = outcome == 'static'
            else:
                self.renderer.update(image)
                self.renderer.shown = None   # the next desktop picture is compared with nothing older
        if self.renderer.result is None:
            return
        if unchanged and not foreground and self.visible and self.renderer.dim_mix == s.dim_t:
            return                           # the desktop didn't change: what is drawn is still right
        if foreground or not self.visible:
            self.foreground_image, self.dim_image = s._gpu_foreground_layers()
            self.mask_image = s._gpu_card_mask()
            self.renderer.set_layers(self.foreground_image, self.dim_image)
            self.renderer.card.upload(self.mask_image.constBits().tobytes(), self.mask_image.bytesPerLine())
        self.renderer.dim_mix = s.dim_t
        self.renderer.draw()
        self.frames += 1
        if commit:
            dcomp._call(c.composition, 3, ())
        rect = s._gpu_window_rect()
        if rect is None:
            return
        x, y, right, bottom = rect
        above = s.cache_hwnd()
        behind = dcomp._user32.GetWindow(C.c_void_p(above), dcomp._GW_HWNDPREV)
        flags = dcomp._SWP_NOACTIVATE | dcomp._SWP_SHOWWINDOW
        if behind == c.hwnd:
            flags |= dcomp._SWP_NOZORDER
        if not c.shown or rect != getattr(self, '_position', None) or behind != c.hwnd:
            dcomp._user32.SetWindowPos(c.hwnd, C.c_void_p(behind or dcomp._HWND_TOP),
                                      x, y, right - x, bottom - y, flags)
            self._position = rect
        c.shown = True
        if not self.visible:
            self.visible = True
            s.update()  # clear the former native background underneath

    def snapshot(self, hidden_tile=None):
        if hidden_tile is not None:
            foreground = self.surface._paint_image(hidden_tile, gpu_snapshot=False)
            mask = self.surface._gpu_card_mask(hidden_tile)
            self.renderer.set_foreground(foreground)
            self.renderer.card.upload(mask.constBits().tobytes(), mask.bytesPerLine())
        try:
            image = self.renderer.readback()
        finally:
            if hidden_tile is not None:
                self.renderer.set_layers(self.foreground_image, self.dim_image)
                self.renderer.dim_mix = self.surface.dim_t
                self.renderer.card.upload(self.mask_image.constBits().tobytes(), self.mask_image.bytesPerLine())
        image.setDevicePixelRatio(self.surface.dpi)
        return image

    def hide(self):
        was_visible = self.visible
        self.visible = False
        if was_visible and self.surface.isVisible() and not self.surface.wants_glass():
            # Paint the solid face synchronously underneath the last GPU
            # frame before removing it. A queued update leaves a clear frame.
            self.surface.repaint()
        if self.compositor is not None and self.compositor.shown:
            dcomp._user32.ShowWindow(self.compositor.hwnd, 0)
            self.compositor.shown = False
        if self.clock is not None:
            self.clock.remove(self)
        if was_visible:
            self.surface.update()

    def fail(self, reason):
        self.close()
        s = self.surface
        s._gpu_failed = True
        s._gpu_receiver = None
        s.reset_glass()
        s.invalidate_glass()
        s.start_glass()
        s.update()
        dcomp._log('Widget GPU glass unavailable; using native glass:\n' + reason)

    def close(self):
        from .widget_capture import remove
        remove(self.surface)
        if self.clock is not None:
            self.clock.remove(self)
        _controllers.discard(self)
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None
        if self.compositor is not None:
            self.compositor.close()
            self.compositor = None
        self.visible = False


def allowed(surface):
    return (os.name == 'nt' and os.environ.get('HA_WIDGET_GPU') != '0'
            and surface.style == 'liquid' and not surface.system_glass
            and not getattr(surface, '_gpu_failed', False)
            and getattr(surface.api, 'gpu_widget_glass_allowed', lambda kind: False)(surface.kind))


_warmed = set()


def prewarm(surface):
    """A card with a solid face has no glass until it is dimmed, and then makes its lens, which costs a few
    hundred milliseconds of Python. Make it now, in the background, so the dim fade does not wait for it."""
    scale = surface.scale
    key = ((surface.pw, surface.ph), surface.glass_card()[2] * scale,
           22 * max(0, min(100, surface.liquid_level)) / 100 * scale)
    if key not in _warmed:
        _warmed.add(key)
        from .gpu_glass import shape_data
        from winsys import qtshell

        def work():
            shape_data(*key)
            if qtshell._marshal is not None:        # then the renderer, on the GUI thread
                qtshell._marshal.post(lambda: surface._gpu_receiver and surface._gpu_receiver.warm())
        threading.Thread(target=work, daemon=True, name='glass-lens').start()


def prepare(surface):
    receiver = surface._gpu_receiver
    if allowed(surface):
        if not surface.wants_glass():
            prewarm(surface)
        if receiver is None:
            try:
                surface._gpu_receiver = Controller(surface)
                surface.invalidate_glass()
                if surface.isVisible():
                    from .widget_capture import register
                    register(surface)
            except Exception:
                surface._gpu_failed = True
                dcomp._log('Widget compositor unavailable:\n' + traceback.format_exc())
        else:
            receiver.queue(foreground=True)
    elif receiver is not None:
        receiver.close()
        surface._gpu_receiver = None
        surface.reset_glass()
        surface.invalidate_glass()
        surface.start_glass()
