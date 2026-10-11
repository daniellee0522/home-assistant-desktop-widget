"""For looking at the tray panel's first opening in the running program (HA_WIDGET_OPEN_PANEL=<folder>): opens it
after a pause and writes a picture of it every 0.25 s into the folder named. Further switches pick other probes:
HA_WIDGET_PROBE_MOTION (tools/live_panel_review), HA_WIDGET_PROBE_DIM, HA_WIDGET_PROBE_FPS,
HA_WIDGET_PROBE_CYCLES. HA_WIDGET_SPIKES=<file> catches the seconds when the program's processor use jumps (below)."""

import os
import threading
import time

from winsys import qtshell
from winsys.win32 import get_hwnd, window_rect


def start_probe(api):
    threading.Thread(target=_probe, args=(api,), daemon=True).start()


def _probe(api):
    folder = os.environ["HA_WIDGET_OPEN_PANEL"]
    os.makedirs(folder, exist_ok=True)
    time.sleep(6)
    api.dismiss_flyout = lambda: None
    if os.environ.get("HA_WIDGET_PROBE_MOTION"):
        from tools.live_panel_review import run
        run(api, folder)
        return
    if os.environ.get("HA_WIDGET_PROBE_DIM"):
        _dim_cycles(api)
    started = time.time()
    api.toggle_flyout()
    if os.environ.get("HA_WIDGET_PROBE_FPS"):
        _glass_rate(api)
    qtshell.log("probe: toggle returned after %.2fs" % (time.time() - started))
    if os.environ.get("HA_WIDGET_PROBE_CYCLES"):
        _open_close_cycles(api)
    _pictures(api, folder, started)


def _dim_cycles(api):
    for _ in range(2):
        api._dimmed = True
        api._push_dim()
        time.sleep(2.0)
        api.wake()
        time.sleep(2.0)
    os._exit(0)


def _glass_rate(api):
    time.sleep(1.0)
    scene = api._flyout_window.native
    count = [0]
    inner = scene._on_glass
    scene.glass_signals.glass.disconnect()
    scene.glass_signals.glass.connect(lambda: (count.__setitem__(0, count[0] + 1), inner()))
    time.sleep(5.0)
    qtshell.log("probe: panel glass %.1f pictures/s" % (count[0] / 5.0))
    os._exit(0)


def _timed(api, name):
    inner = getattr(api, name)

    def run(*a, **k):
        t = time.time()
        try:
            return inner(*a, **k)
        finally:
            qtshell.log("probe:   %s %.3fs" % (name, time.time() - t))
    setattr(api, name, run)


def _open_close_cycles(api):
    """Opens and closes the panel again and again, timing each (no pictures)."""
    for name in ("close_popover", "_sync_client_entities", "_apply_capture_exclusion", "_ensure_overlay",
                 "_place_flyout", "_arm_backdrop", "_apply_system_glass", "_tray_corner"):
        _timed(api, name)
    for n in range(3):
        t1 = time.time()
        api.toggle_flyout()
        t2 = time.time()
        time.sleep(1.5)
        t3 = time.time()
        api.toggle_flyout()
        t4 = time.time()
        time.sleep(1.5)
        qtshell.log("probe: cycle %d open call %.2fs close call %.2fs" % (n, t2 - t1, t4 - t3))
    os._exit(0)


def _pictures(api, folder, started):
    from PIL import ImageGrab
    for i in range(32):
        w = api._flyout_window
        if w:
            ms = int((time.time() - started) * 1000)
            w.run_on_ui_thread(lambda i=i: w.native.grab().save(os.path.join(folder, "p%02d_%04d.png" % (i, ms))))
            rect = window_rect(get_hwnd(w))
            qtshell.log("probe: %d ms rect=%s want=%s scene=%dx%d opacity=%.2f" % (
                ms, rect, api._flyout_origin(rect[2] - rect[0], rect[3] - rect[1]) if rect else None,
                w.native.pw, w.native.ph, w.native.windowOpacity()))
            try:
                ImageGrab.grab(all_screens=True).save(os.path.join(folder, "s%02d_%04d.png" % (i, ms)))
            except Exception:
                pass
        time.sleep(0.25)
    os._exit(0)


def start_sampler(path):
    """HA_WIDGET_SAMPLE=<file>: after 30 s, 20 s of stack samples of every busy thread, with each thread's
    processor time, written to the file. For finding what a running build spends its processor on."""
    threading.Thread(target=_sample, args=(path,), daemon=True, name="sampler").start()


def _thread_seconds(native_id):
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32")
    kernel.OpenThread.restype = wintypes.HANDLE
    handle = kernel.OpenThread(0x40, False, native_id)
    if not handle:
        return 0.0
    times = [wintypes.FILETIME() for _ in range(4)]
    kernel.GetThreadTimes(handle, *[ctypes.byref(t) for t in times])
    kernel.CloseHandle(handle)
    return sum(((t.dwHighDateTime << 32) | t.dwLowDateTime) / 1e7 for t in times[2:])


def _sample(path):
    import collections
    import sys
    import traceback
    time.sleep(30)
    me = threading.get_ident()
    cpu = lambda: {t.ident: (t.name, _thread_seconds(t.native_id)) for t in threading.enumerate() if t.native_id}
    before, started = cpu(), time.time()
    stacks = collections.Counter()
    while time.time() - started < 20:
        names = {t.ident: t.name for t in threading.enumerate()}
        for ident, frame in sys._current_frames().items():
            if ident == me:
                continue
            stack = traceback.extract_stack(frame)
            if stack[-1].name in ("wait", "acquire", "sleep", "select", "_poll", "_worker", "get"):
                continue
            stacks[(names.get(ident, "?"), " < ".join("%s:%d %s" % (os.path.basename(s.filename), s.lineno, s.name)
                                                       for s in reversed(stack[-5:])))] += 1
        time.sleep(0.01)
    after, span = cpu(), time.time() - started
    with open(path, "w", encoding="utf-8") as f:
        for ident, (name, secs) in sorted(after.items(), key=lambda kv: -kv[1][1]):
            used = (secs - before.get(ident, (name, 0.0))[1]) / span
            if used > 0.02:
                f.write("%.2f cores  %s\n" % (used, name))
        for (name, stack), n in stacks.most_common(25):
            f.write("%d  %s  %s\n" % (n, name, stack))


_IDLE_FRAMES = ("wait", "acquire", "sleep", "select", "_poll", "_worker", "get")


def start_spike_log(path):
    """HA_WIDGET_SPIKES=<file>: for as long as the program runs, every second whose processor use is above
    HA_WIDGET_SPIKE_CORES (default 0.12), the file gets that second's time, the processor use of the program and of its
    busiest Python threads, and the stacks those threads were found in. For catching what a build does when its use
    jumps now and then, which a single window of samples (HA_WIDGET_SAMPLE) usually misses."""
    threading.Thread(target=_spikes, args=(path,), daemon=True, name="spikes").start()


def _process_seconds():
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.c_void_p] * 4
    times = [wintypes.FILETIME() for _ in range(4)]
    kernel.GetProcessTimes(kernel.GetCurrentProcess(), *[ctypes.byref(t) for t in times])
    return sum(((t.dwHighDateTime << 32) | t.dwLowDateTime) / 1e7 for t in times[2:])


def _spikes(path, step=0.02, limit=2_000_000):
    import collections
    import sys
    threshold = float(os.environ.get("HA_WIDGET_SPIKE_CORES", "0.12"))
    me = threading.get_ident()
    cpu = lambda: {t.ident: (t.name, _thread_seconds(t.native_id)) for t in threading.enumerate() if t.native_id}
    before, whole, started = cpu(), _process_seconds(), time.time()
    stacks = collections.Counter()
    written = 0
    while True:
        names = {t.ident: t.name for t in threading.enumerate()}
        for ident, frame in sys._current_frames().items():
            if ident == me or frame.f_code.co_name in _IDLE_FRAMES:
                continue
            chain, depth = [], frame
            while depth is not None and len(chain) < 5:      # walked by hand: reading the source lines is what costs
                chain.append("%s:%d %s" % (os.path.basename(depth.f_code.co_filename), depth.f_lineno, depth.f_code.co_name))
                depth = depth.f_back
            stacks[(names.get(ident, "?"), " < ".join(chain))] += 1
        time.sleep(step)
        span = time.time() - started
        if span < 1.0:
            continue
        after, now = cpu(), _process_seconds()
        used = (now - whole) / span
        if used > threshold and written < limit:
            busy = sorted(((secs - before.get(ident, (name, 0.0))[1]) / span, name)
                          for ident, (name, secs) in after.items())[::-1][:4]
            lines = ["%s  %.2f cores  %s" % (time.strftime("%H:%M:%S"), used,
                                             "  ".join("%s %.2f" % (n, u) for u, n in busy if u > 0.01))]
            active = {n for u, n in busy if u > 0.02}             # a thread waiting in a call is not what spiked
            lines += ["    %d  %s  %s" % (n, name, stack) for (name, stack), n in stacks.most_common()
                      if name in active][:8]
            text = "\n".join(lines) + "\n"
            with open(path, "a", encoding="utf-8") as f:
                f.write(text)
            written += len(text)
        before, whole, started, stacks = after, now, time.time(), collections.Counter()
