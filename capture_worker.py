"""Keep blocking PrintWindow calls outside the UI/server process."""

import atexit
import multiprocessing
import threading
import time


def _serve(connection):
    from main import _DesktopCapture

    capture = _DesktopCapture()
    try:
        connection.send(True)
        while True:
            args = connection.recv()
            connection.send(capture.grab(*args))
    except (EOFError, BrokenPipeError, OSError):
        pass
    finally:
        capture.reset()
        connection.close()


class CaptureWorker:
    def __init__(self, timeout=1.5, startup_timeout=8.0):
        self.timeout = timeout
        self.startup_timeout = startup_timeout
        self._lock = threading.Lock()
        self._process = None
        self._connection = None
        self._retry_at = 0.0
        atexit.register(self.close)

    def _stop(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if self._process is not None:
            if self._process.pid is not None:
                if self._process.is_alive():
                    self._process.terminate()
                self._process.join(timeout=1)
            if self._process.is_alive():
                # Keep ownership so the next cleanup can retry.
                raise RuntimeError('capture worker did not terminate')
            self._process.close()
            self._process = None

    def grab(self, *args):
        # Other windows keep their last frame instead of queuing behind
        # an unresponsive external application.
        if not self._lock.acquire(timeout=0.05):
            return None
        try:
            if time.monotonic() < self._retry_at:
                return None
            if self._process is None:
                ctx = multiprocessing.get_context('spawn')
                self._connection, child = ctx.Pipe()
                self._process = ctx.Process(target=_serve, args=(child,), daemon=True)
                try:
                    self._process.start()
                finally:
                    child.close()
                if not self._connection.poll(self.startup_timeout):
                    raise TimeoutError('capture worker startup')
                self._connection.recv()
            self._connection.send(args)
            if not self._connection.poll(self.timeout):
                raise TimeoutError('PrintWindow capture')
            return self._connection.recv()
        except (EOFError, OSError, TimeoutError):
            self._stop()
            self._retry_at = time.monotonic() + 2.0
            return None
        finally:
            self._lock.release()

    def close(self):
        with self._lock:
            self._stop()
            self._retry_at = 0.0
