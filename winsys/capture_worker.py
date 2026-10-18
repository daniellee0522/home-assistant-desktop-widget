"""Keep blocking PrintWindow calls outside the UI/server process."""

import atexit
import multiprocessing
import threading
import time


def _serve(connection):
    from winsys.gdi_capture import DesktopCapture

    capture = DesktopCapture()
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


_MAX_STUCK = 3


class CaptureWorker:
    def __init__(self, timeout=1.5, startup_timeout=8.0):
        self.timeout = timeout
        self.startup_timeout = startup_timeout
        self._lock = threading.Lock()
        self._process = None
        self._connection = None
        self._stuck = []            # workers that would not end when told to, ended again at every stop
        self._retry_at = 0.0
        atexit.register(self.close)

    def _stop(self):
        """End the worker. Never raises: one that will not end (stuck in a call to a hung window) is put aside
        and ended again later, and the next grab starts a new one. It used to be kept, with its pipe closed, and
        every grab after it failed until the program was started again: the widgets' glass was gone."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        process, self._process = self._process, None
        if process is not None and process.pid is not None and process.is_alive():
            process.terminate()
            process.join(timeout=1)
        if process is not None:
            self._stuck.append(process)
        for process in list(self._stuck):
            try:
                if process.pid is not None and process.is_alive():
                    process.terminate()
                    continue
                process.close()
            except (OSError, ValueError):
                pass
            self._stuck.remove(process)

    def grab(self, *args):
        # Other windows keep their last frame instead of queuing behind
        # an unresponsive external application.
        if not self._lock.acquire(timeout=0.05):
            return None
        try:
            if time.monotonic() < self._retry_at:
                return None
            if self._process is None:
                if len(self._stuck) >= _MAX_STUCK:
                    self._stop()            # a new one only once one of these has ended
                    if len(self._stuck) >= _MAX_STUCK:
                        self._retry_at = time.monotonic() + 2.0
                        return None
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
