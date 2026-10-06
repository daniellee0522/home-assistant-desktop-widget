"""Animation ticks without Windows' ~15.6 ms window-timer quantisation.

The worker only waits and queues one wakeup. All animation and painting remains
on Qt's GUI thread. Older Windows versions fall back to a precise QTimer.
"""
import ctypes
import os
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot


try:
    _kernel = ctypes.WinDLL("kernel32", use_last_error=True) if os.name == "nt" else None
    if _kernel is not None:
        _kernel.CreateWaitableTimerExW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_uint]
        _kernel.CreateWaitableTimerExW.restype = ctypes.c_void_p
        _kernel.SetWaitableTimer.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_longlong), ctypes.c_long,
                                           ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
        _kernel.SetWaitableTimer.restype = ctypes.c_int
        _kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        _kernel.WaitForSingleObject.restype = ctypes.c_uint
        _kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        _kernel.CloseHandle.restype = ctypes.c_int
except (OSError, AttributeError):
    _kernel = None


class _Ticker:
    def __init__(self, handle, wake, interval):
        self.handle, self.wake, self.interval = handle, wake, interval
        self.stopped = threading.Event()
        self.pending = threading.Event()

    def run(self):
        try:
            while not self.stopped.is_set():
                status = _kernel.WaitForSingleObject(self.handle, max(100, self.interval * 2))
                if status == 0 and not self.stopped.is_set() and not self.pending.is_set():
                    self.pending.set()
                    try:
                        self.wake(self)
                    except RuntimeError:       # the Qt owner has already been destroyed
                        break
                elif status not in (0, 258):   # WAIT_OBJECT_0 / WAIT_TIMEOUT
                    break
        finally:
            _kernel.CloseHandle(self.handle)


try:
    _dwm_flush = ctypes.windll.dwmapi.DwmFlush if os.name == "nt" else None
except (OSError, AttributeError):
    _dwm_flush = None


class _VsyncTicker:
    """Wakes once per desktop composition (DwmFlush returns just after one), so a frame painted on each wake
    reaches the screen at the next composition, one to a refresh. A clock that merely runs near the refresh
    rate beats against it: some refreshes get two frames, one of which is never seen, and some none, which
    shows as a stutter. Where DwmFlush fails or comes back at once (no composition to wait for) it waits
    `interval` ms instead."""

    def __init__(self, wake, interval, waiter=None):
        self.wake, self.interval = wake, interval
        self.stopped = threading.Event()
        self.pending = threading.Event()
        self.waiter = waiter

    def run(self):
        quick = 0
        while not self.stopped.is_set():
            started = time.perf_counter()
            try:
                failed = (self.waiter or _dwm_flush)() != 0
            except OSError:
                failed = True
            if failed or time.perf_counter() - started < 0.001:
                quick += 1
            else:
                quick = 0
            if failed or quick >= 3:
                self.stopped.wait(self.interval / 1000)
            if self.stopped.is_set():
                break
            if not self.pending.is_set():
                self.pending.set()
                try:
                    self.wake(self)
                except RuntimeError:           # the Qt owner has already been destroyed
                    break


class FrameTimer(QObject):
    timeout = Signal()
    _wake = Signal(object)

    def __init__(self, parent):
        super().__init__(parent)
        self._fallback = QTimer(self)
        self._fallback.setTimerType(Qt.PreciseTimer)
        self._fallback.setInterval(16)
        self._fallback.timeout.connect(self.timeout)
        self._ticker = None
        self.vsync = False          # wake on each desktop composition (see _VsyncTicker)
        self.vsync_waiter = None   # an output-specific vblank, for multi-monitor GPU widgets
        self.shared_clock = None
        self._shared_active = False
        self._wake.connect(self._dispatch, Qt.QueuedConnection)
        # Destruction must also stop the worker without touching a deleted QObject.
        self._owner = [None]
        owner = self._owner
        self.destroyed.connect(lambda *_: owner[0].stopped.set() if owner[0] is not None else None)
        self.destroyed.connect(lambda *_: self.shared_clock.unsubscribe(self)
                               if self._shared_active else None)

    def interval(self):
        return self._fallback.interval()

    def setInterval(self, ms):
        if ms == self.interval():
            return
        active = self.isActive()
        self.stop()
        self._fallback.setInterval(ms)
        if active:
            self.start()

    def isActive(self):
        return self._shared_active or self._ticker is not None or self._fallback.isActive()

    def start(self):
        if self.isActive():
            return
        if self.shared_clock is not None:
            self._shared_active = True
            self.shared_clock.subscribe(self)
            return
        if self.vsync and _dwm_flush is not None:
            ticker = _VsyncTicker(self._wake.emit, self.interval(), self.vsync_waiter)
            self._ticker = self._owner[0] = ticker
            threading.Thread(target=ticker.run, daemon=True, name="animation-clock").start()
            return
        handle = _kernel.CreateWaitableTimerExW(None, None, 2, 0x100002) if _kernel is not None else None
        if handle:
            due = ctypes.c_longlong(-self.interval() * 10000)
            if _kernel.SetWaitableTimer(handle, ctypes.byref(due), self.interval(), None, None, False):
                ticker = _Ticker(handle, self._wake.emit, self.interval())
                self._ticker = self._owner[0] = ticker
                threading.Thread(target=ticker.run, daemon=True, name="animation-clock").start()
                return
            _kernel.CloseHandle(handle)
        self._fallback.start()

    def stop(self):
        if self._shared_active:
            self._shared_active = False
            self.shared_clock.unsubscribe(self)
        ticker = self._ticker
        self._ticker = self._owner[0] = None
        if ticker is not None:
            ticker.stopped.set()
        self._fallback.stop()

    @Slot(object)
    def _dispatch(self, ticker):
        if ticker is self._ticker and not ticker.stopped.is_set():
            try:
                self.timeout.emit()
            finally:
                ticker.pending.clear()
