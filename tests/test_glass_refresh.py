"""Monitor-paced glass must stay idle on unchanged frames and wake on changes."""
import threading
import time
import unittest

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget

from nativeui.glass import GlassMixin

app = QApplication.instance() or QApplication([])


class Screen(QObject):
    refreshRateChanged = Signal(float)

    def __init__(self, rate):
        super().__init__()
        self.rate = rate

    def refreshRate(self):
        return self.rate


class Surface(GlassMixin, QWidget):
    def __init__(self):
        super().__init__()
        self.kind, self.style, self.sampling = 'w:test', 'classic', 'live'
        self.pw = self.ph = 8
        self.scale = self.dpi = 1
        self.init_glass()
        self.paints = 0

    def glass_card(self):
        return (8, 8, 2)

    def glass_changed(self):
        self.paints += 1


def until(predicate, timeout=2):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        app.processEvents()
        time.sleep(.001)
    return predicate()


class GlassRefreshTests(unittest.TestCase):
    def test_monitor_switch_refresh_change_and_rebuild_keep_monitor_pace(self):
        surface = Surface()
        try:
            first, second = Screen(144), Screen(240)
            surface._bind_glass_screen(first)
            self.assertAlmostEqual(surface._glass_pace(), 1 / 144)
            first.refreshRateChanged.emit(120)
            self.assertAlmostEqual(surface._glass_pace(), 1 / 120)
            surface._bind_glass_screen(second)
            first.refreshRateChanged.emit(60)
            surface.fit_glass()
            self.assertAlmostEqual(surface._glass_pace(), 1 / 240)
            second.refreshRateChanged.emit(59.94)
            self.assertAlmostEqual(surface._glass_pace(), 1 / 59.94)
            second.refreshRateChanged.emit(0)
            self.assertAlmostEqual(surface._glass_pace(), 1 / 60)
            surface._bind_glass_screen(None)
        finally:
            surface.close()

    def test_unchanged_desktop_is_not_repainted_then_changes_resume(self):
        surface = Surface()
        changed, blocked = threading.Event(), threading.Event()
        count = [0]
        def capture(kind, last_hash, *args):
            count[0] += 1
            if count[0] == 1 or changed.is_set():
                changed.clear()
                return dict(paced=True, hash=count[0], w=8, h=8, blur_w=8, blur_h=8,
                            blur_raw=bytes([count[0] % 256, 80, 90]) * 64)
            blocked.set()
            changed.wait(.08)  # model DXGI waiting for an actual desktop change
            return dict(paced=True, unchanged=True, hash=last_hash)
        surface.api = type('Api', (), {'get_desktop_backdrop': staticmethod(capture)})()
        surface.show()
        surface.start_glass()
        try:
            self.assertAlmostEqual(surface._glass_pace(), 1 / surface.screen().refreshRate())
            self.assertTrue(until(lambda: surface.paints == 1 and blocked.is_set()))
            until(lambda: count[0] >= 3)
            self.assertEqual(surface.paints, 1)
            surface.fit_glass()  # rebuild/invalidation still accepts a fresh frame
            changed.set()
            self.assertTrue(until(lambda: surface.paints == 2))
            until(lambda: count[0] >= 6)
            self.assertEqual(surface.paints, 2)
        finally:
            surface.stop()
            changed.set()
            surface._glass_thread.join(1)
            surface.close()


if __name__ == '__main__':
    unittest.main()
