"""End-to-end native widgets on an animated controlled desktop, CPU vs GPU."""
import json
import sys
import threading
import time
import statistics
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from PySide6.QtCore import QObject, QEvent, QEventLoop, QTimer
from nativeui import widget, widget_glass
from nativeui.animation_clock import FrameTimer
from test_native_widget import FakeApi, app, tile
from test_glass import definitions
from PIL import Image, ImageFilter
from capture_pixels import within_noise, within_noise_bgrx

liquid_params = definitions('_liquid_params')['_liquid_params']


class Api(FakeApi):
    def __init__(self, count, gpu):
        super().__init__([tile(0, 'light')], '2x2', glass_style='liquid', glass_sampling='live')
        self.count, self.gpu = count, gpu
        self.rate, self.static = 180, None
        self.wait = threading.Event()
        self.source_waiter = None
        self.widget_glass_clock_paced = False
        self.previous = {}
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='bench-pixels')

    def _prefs(self):
        return dict(self.prefs, widgets=[dict(id=f'w{i}', size='2x2', tiles=self.tiles)
                                        for i in range(self.count)])

    def gpu_widget_glass_allowed(self, kind):
        return self.gpu

    def frame(self):
        return self.static if self.static is not None else int(time.perf_counter() * self.rate)

    def shot(self, digest, w, h, frame, kind='single'):
        if digest == frame:
            return dict(unchanged=True, paced=True, hash=digest)
        # Include the real CPU capture preparation, rather than handing the
        # renderer ready-made RGB bytes and hiding this cost from the result.
        raw = bytes((80, 40 + frame * 11 % 180, 30 + frame * 7 % 200, 255)) * w * h
        scale, preblur, _ = liquid_params(self.prefs.get('liquid_blur', 0) / 100)
        if self.gpu and scale == 1:
            previous = self.previous.get(kind)
            if previous is not None:
                within_noise_bgrx(previous, raw, (w, h), 3, preblur)
            self.previous[kind] = raw
            zlib.crc32(raw)
            return dict(w=w, h=h, blur_w=w, blur_h=h, blur_raw=raw, hash=frame,
                        paced=True, pixel_format='BGRX', pre_blur=preblur)
        if scale == 1:
            image = Image.frombytes('RGB', (w, h), raw, 'raw', 'BGRX')
        else:
            image = Image.frombuffer('RGBA', (w, h), raw, 'raw', 'RGBA', 0, 1)
            image = image.reduce(2) if not (w % 2 or h % 2) else image.resize(
                (max(1, round(w / 2)), max(1, round(h / 2))), Image.Resampling.BOX)
            image = Image.frombytes('RGB', image.size, image.tobytes(), 'raw', 'BGRX')
        if preblur:
            image = image.filter(ImageFilter.GaussianBlur(preblur))
        if scale > 2:
            image = image.resize((max(1, round(w / scale)), max(1, round(h / scale))),
                                 Image.Resampling.HAMMING)
        previous = self.previous.get(kind)
        if previous is not None:
            within_noise(previous, image, 3)
        self.previous[kind] = image
        direct_pixels = self.gpu and scale == 1 and not preblur
        raw = raw if direct_pixels else image.tobytes()
        zlib.crc32(raw)
        sw, sh = image.size
        return dict(w=w, h=h, blur_w=sw, blur_h=sh, blur_raw=raw, hash=frame, paced=True,
                    pixel_format='BGRX' if direct_pixels else 'RGB')

    def get_desktop_backdrop(self, kind, digest, w, h, *args):
        frame = self.frame()
        if self.static is not None and digest == frame:
            self.wait.wait(.05)
        return self.shot(digest, w, h, frame, kind)

    def widget_glass_frames(self, requests, after):
        if self.source_waiter is not None:
            self.source_waiter()
        frame = self.frame()
        if self.static is not None and frame == after:
            self.wait.wait(.05)
        def prepare(request):
            return self.shot(request[1], request[2], request[3], frame, request[0])
        if self.prefs.get('liquid_blur', 0) and len(requests) > 1:
            shots = list(self.pool.map(prepare, requests))
        else:
            shots = []
            for request in requests:
                shots.append(prepare(request))
                if len(requests) > 1:
                    time.sleep(0)
        return frame, shots


class Paints(QObject):
    count = 0
    def eventFilter(self, watched, event):
        if event.type() == QEvent.Paint:
            self.count += 1
        return False


def pump(seconds):
    loop = QEventLoop()
    QTimer.singleShot(max(1, round(seconds * 1000)), loop.quit)
    loop.exec()


def measure(count, gpu, dim=False, level=0, tiles=1, transition=False, legacy=False, api_factory=None):
    api = (api_factory or Api)(count, gpu)
    api.prefs['liquid_blur'] = level
    api.tiles = [tile(i, 'light') for i in range(tiles)]
    windows, clocks = [], []
    original_start = FrameTimer.start
    if legacy:
        def independent(timer):
            shared, timer.shared_clock = timer.shared_clock, None
            try:
                original_start(timer)
            finally:
                timer.shared_clock = shared
        FrameTimer.start = independent
    try:
        for i in range(count):
            win = widget.NativeWidget(api, f'w{i}')
            windows.append(win)
            if hasattr(api, 'bind'):
                api.bind(win)
            surface = win.native
            surface.move(20 + (i % 3) * 270, 20 + (i // 3) * 270)
            clock = Paints(surface)
            surface.installEventFilter(clock)
            clocks.append(clock)
            surface.show()
        api.rate = windows[0].native.screen().refreshRate()
        pump(1)
        ready_until = time.perf_counter() + 5
        while gpu and any(w.native._gpu_receiver is None or not w.native._gpu_receiver.visible for w in windows) \
                and time.perf_counter() < ready_until:
            pump(.1)
        if gpu and any(w.native._gpu_receiver is None or not w.native._gpu_receiver.visible for w in windows):
            raise RuntimeError('GPU widget did not become ready')
        if gpu:
            api.source_waiter = windows[0].native._gpu_receiver.clock.timer.vsync_waiter
            api.widget_glass_clock_paced = api.source_waiter is not None
            if hasattr(api, 'sync_source'):
                api.sync_source(api.source_waiter)
        if dim and not transition:
            for win in windows:
                win.native.set_dim(True)
            pump(1)
        timings = {'update': [], 'draw': [], 'foreground': []}
        presented = [[] for _ in windows]
        if gpu:
            def timed(method, name, index):
                def call(*args, **kwargs):
                    started = time.perf_counter()
                    result = method(*args, **kwargs)
                    timings[name].append((time.perf_counter() - started) * 1000)
                    if name == 'draw':
                        presented[index].append(time.perf_counter())
                    return result
                return call
            for index, win in enumerate(windows):
                renderer = win.native._gpu_receiver.renderer
                renderer.update = timed(renderer.update, 'update', index)
                renderer.draw = timed(renderer.draw, 'draw', index)
                renderer.set_layers = timed(renderer.set_layers, 'foreground', index)
        def frames():
            return [w.native._gpu_receiver.frames for w in windows] if gpu else [c.count for c in clocks]
        before = frames()
        cpu, start = time.process_time(), time.perf_counter()
        if transition:
            for win in windows:
                win.native.set_dim(True)
                QTimer.singleShot(900, lambda s=win.native: s.set_dim(False))
                QTimer.singleShot(1250, lambda s=win.native: s.set_dim(True))
        pump(2)
        elapsed, cpu = time.perf_counter() - start, time.process_time() - cpu
        after = frames()
        gaps = [[(b-a)*1000 for a,b in zip(values, values[1:])] for values in presented]
        static_redraws = None
        if getattr(api, 'can_freeze', True):
            api.static = api.frame()
            if hasattr(api, 'freeze'):
                api.freeze()
            pump(.3)
            still = frames()
            pump(.3)
            static_redraws = [b-a for a,b in zip(still,frames())]
            if any(static_redraws):
                raise AssertionError('An unchanged desktop continued repainting')
        record = dict(widgets=count, renderer='gpu' if gpu else 'cpu', monitor_hz=api.rate,
                      standby=dim, blur=level, tiles=tiles,
                      transition=transition, independent_animation_clocks=legacy,
                      frame_gap_ms=[dict(median=round(statistics.median(values), 2),
                                         p95=round(sorted(values)[int(len(values)*.95)], 2),
                                         maximum=round(max(values), 2),
                                         redundant=sum(v < 500 / api.rate for v in values))
                                    for values in gaps if values],
                      dim_timer_active=[w.native.dim_timer.isActive() for w in windows],
                      gpu_mean_ms={name: round(statistics.mean(values), 3) if values else 0
                                   for name, values in timings.items()},
                      frames_per_second=[round((b-a)/elapsed,1) for a,b in zip(before,after)],
                      process_cpu_percent=round(cpu/elapsed*100,1), static_redraws=static_redraws,
                      size=[windows[0].native.pw, windows[0].native.ph])
        if hasattr(api, 'evidence'):
            record['capture'] = api.evidence()
        print(json.dumps(record), flush=True)
        return record
    finally:
        FrameTimer.start = original_start
        api.wait.set()
        for win in windows:
            win.native.stop()
            win.dispose()
        pump(.1)
        api.pool.shutdown(wait=True)


def main():
    if '--transitions' in sys.argv:
        records = [measure(6, True, True, level, tiles, transition=True, legacy=legacy)
                   for level, tiles in ((0, 1), (50, 4)) for legacy in (True, False)]
        target = Path('visual/gpu-glass/transition-performance.json')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(records, indent=2), encoding='utf-8')
        return
    if '--standby' in sys.argv:
        records = [measure(count, True, True, level, tiles)
                   for level, tiles in ((0, 1), (50, 4)) for count in (1, 6)]
        target = Path('visual/gpu-glass/standby-performance.json')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(records, indent=2), encoding='utf-8')
        return
    records = [measure(1,False)]
    records.extend(measure(count,True) for count in (1,2,4,6))
    records.append(measure(6,False))
    target=Path('visual/gpu-glass/performance.json')
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(records,indent=2),encoding='utf-8')
    if '--check' in sys.argv:
        gpu = [r for r in records if r['renderer'] == 'gpu']
        reference = gpu[0]['frames_per_second'][0]
        for record in gpu:
            rates = record['frames_per_second']
            if max(rates) - min(rates) > 1 or min(rates) < reference * .97:
                raise AssertionError(f'Widget count reduced refresh rate: {record}')


if __name__ == '__main__':
    main()
