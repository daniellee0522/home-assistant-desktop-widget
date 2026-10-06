"""Moving texture -> real shared DXGI capture -> native refracted/frosted widgets.

Use --desktop to capture the visible desktop (including Wallpaper Engine)
instead of the repeatable moving texture. No wallpaper settings are changed.
"""
import ast
import ctypes
import json
import sys
import time
import zlib
import statistics
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from PIL import Image, ImageFilter
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QWidget
from nativeui import dcomp
from nativeui.animation_clock import FrameTimer
from capture_pixels import within_noise, within_noise_bgrx
import dxgi_capture as dc
from tools.benchmark_widget_gpu import Api, measure, app, liquid_params
from tools.glass_review import desktop
from test_glass import definitions

capture = dc.DesktopDuplication()
user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint]
user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
scope = definitions('Api', _screen_duplication=capture, time=time,
                    _get_hwnd=lambda win: win.native.cache_hwnd())
batch = scope['Api'].widget_glass_frames
tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
prepare = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'prepare_pixels')
pixel_code = compile(ast.Module(body=[prepare], type_ignores=[]), 'main.py', 'exec')


class MovingDesktop(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setGeometry(0, 0, 960, 720)
        image = desktop(self.width() + 112, self.height(), 'busy')
        self.picture = QImage(image.tobytes(), image.width, image.height,
                              image.width * 3, QImage.Format_RGB888).copy()
        self.timer = FrameTimer(self)
        self.timer.setInterval(max(1, round(1000 / app.primaryScreen().refreshRate())))
        self.timer.timeout.connect(self.update)
        self.paints = 0
        self.costs = []
        self.frozen_phase = None
        self.phase = 0
        self.show()
        self.timer.start()

    def paintEvent(self, event):
        start = time.perf_counter()
        p = QPainter(self)
        self.phase = self.frozen_phase if self.frozen_phase is not None else int(
            time.perf_counter() * app.primaryScreen().refreshRate() * 2) % 112
        p.drawImage(-self.phase, 0, self.picture)
        p.end()
        self.paints += 1
        self.costs.append((time.perf_counter() - start) * 1000)

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)


class DesktopApi(Api):
    widget_glass_frames = batch
    widget_glass_deferred = True

    def __init__(self, count, gpu):
        super().__init__(count, gpu)
        self._cfg = self.prefs
        self._capture_epoch = 0
        self._backdrop_sent = {}
        self.windows = {}
        self.seen = {}
        self.regions = {}
        self.raws = {}
        self.widget_glass_clock_paced = True
        self.sequences = set()
        self.snapshots = False

    def bind(self, win):
        self.windows[win.native.kind] = win
        hwnd = win.native.cache_hwnd()
        if not user32.SetWindowDisplayAffinity(hwnd, 0x11):
            raise RuntimeError('Could not exclude the native test widget from capture')
        user32.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(-1), 0, 0, 0, 0, 0x13)

    def _window_for(self, kind):
        return self.windows.get(kind)

    def _capture_rect(self, hwnd, w, h, *args):
        class Rect(ctypes.Structure):
            _fields_ = [(name, ctypes.c_long) for name in ('left', 'top', 'right', 'bottom')]
        rect = Rect()
        user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect))
        return rect.left, rect.top, w, h

    def get_desktop_backdrop(self, kind, digest, w, h, x=None, y=None, wait=0, defer=False):
        window = self._window_for(kind)
        x, y, w, h = self._capture_rect(window.native.cache_hwnd(), w, h)
        receiver = window.native._gpu_receiver
        scale, pre_blur, _ = liquid_params(self.prefs.get('liquid_blur', 0) / 100)
        if (defer and scale == 1 and receiver is not None and receiver.compositor is not None
                and capture.gpu_source((x, y, w, h), receiver.compositor.device)):
            seen = self.seen.get(kind)
            after = seen[1] if seen and seen[0] == (x, y, w, h) and digest is not None else None
            got = capture.grab(x, y, w, h, after, 0, pixels=False)
            if got is not None:
                self.seen[kind] = ((x, y, w, h), got[0])
                self.regions[kind] = (x, y, w, h)
                self.sequences.add(got[0])
                if got[1] is None:
                    return dict(unchanged=True, hash=digest, paced=True)
                return dict(gpu=(x, y, w, h), copy=capture.copy_region, pre_blur=pre_blur, w=w, h=h,
                            paced=True, hash=hash(got[0]) & 0x7FFFFFFF)
        got = capture.grab(x, y, w, h, timeout=0)
        if got is None or got[1] is None:
            return None
        self.sequences.add(got[0])
        self.raws[kind] = got[1]
        env = dict(self=self, window=window, window_kind=kind, last_hash=digest,
                   w=w, h=h, raw=got[1], is_popover=False, paced=True,
                   capture_epoch=0, started=time.perf_counter(), time=time, zlib=zlib,
                   Image=Image, ImageFilter=ImageFilter, _liquid_params=liquid_params,
                   within_noise=within_noise, within_noise_bgrx=within_noise_bgrx,
                   _BACKDROP_NOISE=3)
        exec(pixel_code, env)
        return env['prepare_pixels'] if defer else env['prepare_pixels']()

    def freeze(self):
        self.background.frozen_phase = self.background.phase
        self.background.timer.stop()

    def sync_source(self, waiter):
        if self.background is not None and waiter is not None:
            timer = self.background.timer
            timer.stop()
            timer.vsync = True
            timer.vsync_waiter = waiter
            timer.start()

    def evidence(self):
        if not self.snapshots:
            out = Path('visual/gpu-glass/desktop-shared')
            out.mkdir(parents=True, exist_ok=True)
            for kind, win in self.windows.items():
                surface = win.native
                raw = self.raws.get(kind)
                if raw is None and kind in self.regions:
                    got = capture.grab(*self.regions[kind], timeout=0)
                    raw = got[1] if got else None
                if raw is None:
                    continue
                image = QImage(raw, surface.pw, surface.ph, surface.pw * 4, QImage.Format_RGB32).copy()
                image.save(str(out / f'{kind.replace(":", "-")}-source.png'))
                p = QPainter(image)
                foreground = surface._gpu_receiver.snapshot()
                foreground.setDevicePixelRatio(1)
                p.drawImage(0, 0, foreground)
                p.end()
                image.save(str(out / f'{kind.replace(":", "-")}-glass.png'))
            self.snapshots = True
        return dict(real_dxgi=True, production_batch=True, production_pixel_filters=True,
                    distinct_regions=len(self.raws) or len(self.regions), distinct_desktop_frames=len(self.sequences),
                    background='visible desktop' if '--desktop' in sys.argv else 'moving checker texture')


def main():
    background = None if '--desktop' in sys.argv else MovingDesktop()
    maps = [0]
    map_costs = []
    original = dc._call
    def counted(*args, **kwargs):
        if kwargs.get('what') == 'Map':
            maps[0] += 1
            start = time.perf_counter()
            result = original(*args, **kwargs)
            map_costs.append((time.perf_counter() - start) * 1000)
            return result
        return original(*args, **kwargs)
    try:
        with patch.object(dc, '_call', counted):
            records = []
            for transition in (False, True):
                before = maps[0]
                def factory(count, gpu):
                    api = DesktopApi(count, gpu)
                    api.background = background
                    api.can_freeze = background is not None
                    if background is not None:
                        background.frozen_phase = None
                        background.timer.start()
                    return api
                result = measure(4, True, True, 25, 4, transition=transition, api_factory=factory)
                result['capture']['gpu_maps'] = maps[0] - before
                result['capture']['map_mean_ms'] = statistics.mean(map_costs) if map_costs else 0
                if background is not None:
                    result['capture']['source_paint_mean_ms'] = statistics.mean(background.costs)
                records.append(result)
        target = Path('visual/gpu-glass/desktop-performance.json')
        target.write_text(json.dumps(records, indent=2), encoding='utf-8')
    finally:
        if background is not None:
            background.close()


if __name__ == '__main__':
    main()
