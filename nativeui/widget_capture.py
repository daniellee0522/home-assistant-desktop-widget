"""One capture worker for GPU widgets; one desktop-frame wait, newest images only."""
import threading
import time
import traceback

from PySide6.QtGui import QImage
from PySide6.QtCore import QObject, Qt, Signal

_lock = threading.Lock()
_wake = threading.Event()
_members = {}
_thread = None
_signals = None
_packet_lock = threading.Lock()
_packets = None
_queued = False
_jobs = {}
_job_ready = threading.Condition()
_prep_thread = None
_pool = None


class DesktopFrame:
    """A window's part of the desktop that stays on the GPU: the renderer copies it itself."""
    def __init__(self, rect, pre_blur, copy, divide=1, rotation=None, covers=None, wallpaper=None):
        self.rect = tuple(rect)
        self.wallpaper = wallpaper        # () -> the desktop here without any window, as BGRA bytes (or None): used once, when a window is
                                          # over the widget before any picture without one has been drawn
        self.covers = covers              # () -> screen rectangles (l, t, r, b) of other programs' windows over it now; None: not asked
        self.w, self.h = rect[2], rect[3]
        self._pre_blur = pre_blur
        self.divide = divide              # how much smaller the frost is blurred than the desktop is
        self.rotation = rotation          # of the screen it was taken from (DXGI's value); None if not asked
        self.copy = copy

    def copy_into(self, texture, device, context):
        if self.rotation is None:
            return self.copy(self.rect, texture, device, context) is not None
        return self.copy(self.rect, texture, device, context, self.rotation) is not None


    def cover_boxes(self):
        """The parts of this frame that other programs' windows are over *now*, as (l, t, r, b) in the frame's own pixels. The copy
        is of the desktop as it is when the renderer takes it, not as it was when the frame was planned, so what lies over the widget
        is asked when it is copied; the renderer fills those parts from the last picture that had no window in it, on the GPU."""
        if self.covers is None:
            return []
        x, y, w, h = self.rect
        boxes = []
        for l, t, r, b in self.covers():
            l, t, r, b = max(0, int(l) - x), max(0, int(t) - y), min(w, int(r) - x), min(h, int(b) - y)
            if r > l and b > t:
                boxes.append((l, t, r, b))
        return boxes


class Signals(QObject):
    ready = Signal()


def deliver():
    global _packets, _queued
    with _packet_lock:
        packets, _packets, _queued = _packets or (), None, False
    clocks = set()
    for surface, image, generation in packets:
        if (surface._stop.is_set() or not surface._gpu_shared_capture
                or surface._gpu_receiver is None or generation != surface._glass_generation):
            continue
        surface.raw_latest = image
        surface.latest, surface._latest_generation = image, generation
        surface._gpu_receiver.queue(image, paced=True)
        clocks.add(surface._gpu_receiver.clock)
    # DXGI has already paced the packet. Waiting for another vblank here
    # adds a full refresh of latency and can discard an otherwise timely frame.
    for clock in clocks:
        if not clock.animations:
            clock.flush()


def submit(packets):
    global _packets, _queued
    if not packets:
        return
    with _packet_lock:
        _packets = tuple(packets)  # replace, never append stale full frames
        notify = not _queued
        _queued = True
    if notify:
        _signals.ready.emit()


class Reader:
    def __init__(self, surface):
        self.surface = surface
        self.digest = None
        self.generation = -1
        self.taken = False
        self.next_try = 0
        self.quiet = 0


def register(surface):
    global _thread, _signals
    if _signals is None:
        _signals = Signals()
        _signals.ready.connect(deliver, Qt.QueuedConnection)
    with _lock:
        _members.setdefault(surface, Reader(surface))
        surface._gpu_shared_capture = True
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=run, daemon=True, name='widget-capture')
            _thread.start()
    _wake.set()


def remove(surface):
    with _lock:
        _members.pop(surface, None)
        surface._gpu_shared_capture = False
    _wake.set()


def request():
    _wake.set()


def publish(reader, shot, generation):
    s = reader.surface
    if not shot:
        reader.digest = None
        reader.next_try = time.monotonic() + .25
        return
    if generation != s._glass_generation or s._stop.is_set() or not s._gpu_shared_capture:
        reader.digest, reader.taken = None, False
        return
    if shot.get('skip'):
        reader.taken = False
        reader.next_try = time.monotonic() + (shot.get('retry_ms') or 500) / 1000
        return
    if shot.get('unchanged'):
        reader.quiet += 1
        reader.taken = True
        return
    if shot.get('gpu'):
        if abs(shot['w'] - s.pw) > 3 or abs(shot['h'] - s.ph) > 3:
            reader.digest = None
            return
        reader.digest, reader.taken, reader.quiet = shot.get('hash'), True, 0
        return s, DesktopFrame(shot['gpu'], shot.get('pre_blur', 0), shot['copy'], shot.get('divide', 1),
                                         shot.get('rotation'), shot.get('covers'), shot.get('wallpaper')), generation
    raw = shot.get('blur_raw')
    if not raw or abs(shot['w'] - s.pw) > 3 or abs(shot['h'] - s.ph) > 3:
        reader.digest = None
        return
    bgrx = shot.get('pixel_format') == 'BGRX'
    decoded = QImage(raw, shot['blur_w'], shot['blur_h'], shot['blur_w'] * (4 if bgrx else 3),
                     QImage.Format_RGB32 if bgrx else QImage.Format_RGB888)
    image = decoded
    image._capture_bytes = raw
    image._pre_blur = shot.get('pre_blur', 0)
    reader.digest, reader.taken, reader.quiet = shot.get('hash'), True, 0
    return s, image, generation


def finish(api, shots):
    """Run the deferred per-widget pixel work of one desktop frame."""
    def one(shot):
        try:
            return shot() if callable(shot) else shot
        except Exception:
            return None
    cfg = getattr(api, '_cfg', None) or getattr(api, 'prefs', None) or {}
    callables = [s for s in shots if callable(s)]
    if int(cfg.get('liquid_blur', 0)) > 0 and len(callables) > 1:
        global _pool
        if _pool is None:
            from concurrent.futures import ThreadPoolExecutor
            _pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='glass-pixels')
        try:
            return list(_pool.map(one, shots))
        except RuntimeError:       # the interpreter is shutting down
            return [None] * len(shots)
    finished = []
    for shot in shots:
        finished.append(one(shot))
        if len(callables) > 1:
            time.sleep(0)  # let the GUI submit the preceding frame
    return finished


def hand_over(api, group, generations, shots):
    """Queue a frame's pixel work for the prep thread, one slot per widget.

    A widget's newer frame replaces its older one that has not started; other
    widgets' pending frames are kept, so no widget is left showing stale glass.
    """
    global _prep_thread
    with _job_ready:
        for reader, generation, shot in zip(group, generations, shots):
            _jobs[reader] = (api, generation, shot)
        if _prep_thread is None or not _prep_thread.is_alive():
            _prep_thread = threading.Thread(target=prepare, daemon=True, name='widget-glass-prep')
            _prep_thread.start()
        _job_ready.notify()


def prepare():
    """Finish deferred frames while the capture thread waits for the next one."""
    global _prep_thread
    while True:
        with _job_ready:
            if not _jobs and not _job_ready.wait(5.0) and not _jobs:
                _prep_thread = None
                return
            taken = dict(_jobs)
            _jobs.clear()
        try:
            batches = {}
            for reader, (api, generation, shot) in taken.items():
                batches.setdefault(api, []).append((reader, generation, shot))
            packets = []
            for api, items in batches.items():
                shots = finish(api, [shot for _, _, shot in items])
                for (reader, generation, _), shot in zip(items, shots):
                    packet = publish(reader, shot, generation)
                    if packet is not None:
                        packets.append(packet)
            submit(packets)
        except Exception:
            traceback.print_exc()


# A desktop that changes at every frame for longer than STEADY_AFTER_S (a video, an animated wallpaper, a window
# being scrolled for a long time) is followed at STEADY_PACE instead of the display's rate: the frost is blurred
# well past what 100+ pictures a second can show, and each one costs a capture, a window scan and a blur.
STEADY_AFTER_S = 1.5
STEADY_PACE = 1 / 30


def steady_pace(api):
    """Seconds between pictures of a desktop that keeps changing: the user's `glass_rate` (30, 20 or 15 a second)."""
    cfg = getattr(api, '_cfg', None) or {}
    try:
        rate = int(cfg.get('glass_rate', 30))
    except (TypeError, ValueError):
        rate = 30
    return 1 / rate if rate in (30, 20, 15) else STEADY_PACE


def _steady_pause(shots, moving_since, cycle_at, pace=STEADY_PACE):
    """Keeps a desktop that has changed at every cycle for STEADY_AFTER_S to `pace`. Returns the state to
    pass in next time: when the changing began (None if it stopped) and when this cycle began."""
    now = time.monotonic()
    if not any(callable(shot) or (shot and not shot.get('unchanged')) for shot in shots):
        return None, now
    moving_since = moving_since or now
    if now - moving_since > STEADY_AFTER_S:
        wait = cycle_at + pace - now
        if wait > 0:
            time.sleep(wait)
    return moving_since, time.monotonic()


def run():
    global _thread
    cursors = {}
    due = 0
    moving_since, cycle_at = None, 0.0
    while True:
        with _lock:
            readers = list(_members.values())
            if not readers:
                _thread = None
                return
        _wake.clear()
        try:
            groups = {}
            now = time.monotonic()
            for reader in readers:
                s = reader.surface
                if s._stop.is_set() or not s._gpu_shared_capture:
                    continue
                if s.force.is_set() or reader.generation != s._glass_generation:
                    s.force.clear()
                    reader.digest, reader.taken, reader.next_try, reader.quiet = None, False, 0, 0
                    reader.generation = s._glass_generation
                if reader.next_try > now and not s.sample_now.is_set():
                    continue
                if not s.wants_glass():
                    continue
                if s.sampling == 'still' and not s.dragging and reader.taken and not s.sample_now.is_set():
                    continue
                s.sample_now.clear()
                groups.setdefault(s.api, []).append(reader)
            if not groups:
                # Asleep until the first widget that waits is due again, not for a fixed half second.
                due_at = [r.next_try for r in readers if r.next_try > now and r.surface.wants_glass()]
                _wake.wait(min(.5, max(.01, min(due_at) - time.monotonic())) if due_at else .5)
                continue
            pace = min(r.surface._glass_pace() for group in groups.values() for r in group)
            # A real batch waits on DXGI desktop frames itself. Adding another
            # independently phased sleep loses refreshes and makes beat judder.
            if not all(getattr(api, 'widget_glass_clock_paced', False) for api in groups):
                due += pace
                wait = due - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                now = time.monotonic()
                if now - due >= pace:
                    due = now
            all_shots = []
            answers = []
            packets = []
            for api, group in groups.items():
                requests = [(r.surface.kind, r.digest, r.surface.pw, r.surface.ph) for r in group]
                generations = [r.surface._glass_generation for r in group]
                signature = tuple((kind, w, h) for kind, _, w, h in requests)
                cursor = cursors.get(api)
                after = cursor[1] if cursor and cursor[0] == signature else None
                batch = getattr(api, 'widget_glass_frames', None)
                if batch is not None and getattr(api, 'widget_glass_deferred', False):
                    frame, shots = batch(requests, after, True)
                    cursors[api] = (signature, frame)
                    answers.extend(shots)
                    hand_over(api, group, generations, shots)
                    continue
                if batch is not None:
                    frame, shots = batch(requests, after)
                    cursors[api] = (signature, frame)
                else:  # controlled capture APIs used by native visual/tests
                    shots = [api.get_desktop_backdrop(kind, digest, w, h, None, None, 0)
                             for kind, digest, w, h in requests]
                for reader, shot, generation in zip(group, shots, generations):
                    packet = publish(reader, shot, generation)
                    if packet is not None:
                        packets.append(packet)
                all_shots.extend(shots)
                answers.extend(shots)
            submit(packets)
            moving_since, cycle_at = _steady_pause(answers, moving_since, cycle_at, min(steady_pace(a) for a in groups))
            # DXGI's wait is the static detector. Sources without one retain
            # the original quiet backoff instead of polling at monitor speed.
            if all_shots and all(not shot or not shot.get('paced') for shot in all_shots):
                if all(shot and shot.get('unchanged') for shot in all_shots):
                    quiet = min(r.quiet for group in groups.values() for r in group)
                    _wake.wait(3.0 if quiet >= 4 else pace)
        except Exception:
            traceback.print_exc()
            _wake.wait(.25)
