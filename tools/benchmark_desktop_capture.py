"""Measure real DXGI readback for six distinct animated widget rectangles."""
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QWidget
import dxgi_capture as dc


class Source(QWidget):
    tick = 0
    def paintEvent(self, event):
        p = QPainter(self)
        for i in range(6):
            p.fillRect(i * 120, 0, 120, 240, QColor(30 + i * 25, 40 + self.tick % 100, 80))
        p.end()


def main():
    app = QApplication.instance() or QApplication([])
    source = Source()
    source.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
    source.setGeometry(100, 100, 720, 240)
    source.show()
    app.processEvents()
    # Logical placement above is converted to physical capture coordinates.
    scale = source.devicePixelRatioF()
    point = source.mapToGlobal(source.rect().topLeft())
    rects = [(round((point.x() + i * 120) * scale), round(point.y() * scale),
              round(120 * scale), round(240 * scale)) for i in range(6)]
    capture = dc.DesktopDuplication()
    original_call = dc._call
    try:
        for batched in (False, True):
            maps, costs, previous = [], [], None
            def counted(obj, slot, *args, **kwargs):
                if kwargs.get('what') == 'Map':
                    maps.append(1)
                return original_call(obj, slot, *args, **kwargs)
            batch = dc._Output.read_batch if batched else lambda *args: None
            with patch.object(dc._Output, 'read_batch', batch), patch.object(dc, '_call', counted):
                # Remove cached atlas from the preceding mode.
                with capture._gpu:
                    for out in capture._outputs:
                        out._batch_seq, out._batch = None, {}
                for frame in range(25):
                    source.tick += 1
                    source.repaint()
                    app.processEvents()
                    start = time.perf_counter()
                    first = capture.grab(*rects[0], after=previous, timeout=.5)
                    if first is None or first[1] is None:
                        raise RuntimeError('No fresh DXGI frame for the synthetic animation')
                    previous = first[0]
                    images = [first] + [capture.grab(*rect) for rect in rects[1:]]
                    elapsed = (time.perf_counter() - start) * 1000
                    for i, got in enumerate(images):
                        if got is None or got[1] is None or got[1][:3:2] != bytes((80, 30 + i * 25)):
                            raise AssertionError('Widget rectangles were mixed or captured incorrectly')
                    if frame >= 5:
                        costs.append(elapsed)
            print(f'{"batched" if batched else "individual"}: six reads mean {sum(costs)/len(costs):.2f} ms, '
                  f'{len(maps)} GPU Maps; independent pixels verified', flush=True)
    finally:
        source.close()
        # The duplication worker releases itself after its interest expires.


if __name__ == '__main__':
    main()
