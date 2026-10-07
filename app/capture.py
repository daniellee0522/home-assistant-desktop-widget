"""The program's three ways of reading the screen, made once: Desktop Duplication (GPU, the fast path), a worker
process doing GDI/PrintWindow (the compatibility path), and the in-process GDI grab."""

from winsys import qtshell
from winsys.capture_worker import CaptureWorker
from winsys.dxgi_capture import DesktopDuplication
from winsys.gdi_capture import DesktopCapture


desktop_capture = DesktopCapture()
compat_capture = CaptureWorker()
screen_duplication = DesktopDuplication()
screen_duplication.set_logger(qtshell.log)
# How long a read waits for the screen under a window to change before
# answering "unchanged", so the window can notice it has been hidden.
DUPLICATION_WAIT_SECS = 0.5

# Per-channel difference, out of 255, below which two blurred backdrops
# look the same.
BACKDROP_NOISE = 3
