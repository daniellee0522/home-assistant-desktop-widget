"""Animation ticks without Windows' ~15.6 ms window-timer quantisation.

The worker only waits and queues one wakeup. All animation and painting remains
on Qt's GUI thread. Older Windows versions fall back to a precise QTimer.
"""
import ctypes
import os
import threading

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
        self._wake.connect(self._dispatch, Qt.QueuedConnection)
        # Destruction must also stop the worker without touching a deleted QObject.
        self._owner = [None]
        owner = self._owner
        self.destroyed.connect(lambda *_: owner[0].stopped.set() if owner[0] is not None else None)

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
        return self._ticker is not None or self._fallback.isActive()

    def start(self):
        if self.isActive():
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
