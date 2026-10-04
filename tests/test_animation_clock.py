"""Frame wakes stay on the GUI thread, coalesce, and cannot survive their owner."""
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")
from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtWidgets import QApplication, QWidget
import shiboken6

from nativeui import animation_clock as clock

app = QApplication.instance() or QApplication([])


class AnimationClock(unittest.TestCase):
    def test_worker_coalesces_wakes_and_closes_its_handle(self):
        wake = Mock()
        ticker = clock._Ticker(123, wake, 5)
        calls = []

        def wait(*_):
            calls.append(1)
            if len(calls) == 4:
                ticker.stopped.set()
            return 0

        kernel = Mock()
        kernel.WaitForSingleObject.side_effect = wait
        with patch.object(clock, "_kernel", kernel):
            ticker.run()
        wake.assert_called_once_with(ticker)
        kernel.CloseHandle.assert_called_once_with(123)

    def test_new_animation_does_not_restart_active_clock_and_stale_wakes_are_ignored(self):
        owner = QWidget()
        timer = clock.FrameTimer(owner)
        kernel = Mock()
        kernel.CreateWaitableTimerExW.return_value = 123
        kernel.SetWaitableTimer.return_value = 1
        ticks = []
        timer.timeout.connect(lambda: ticks.append(1))
        try:
            with patch.object(clock, "_kernel", kernel), patch.object(clock.threading, "Thread"):
                timer.start()
                old = timer._ticker
                timer.start()
                self.assertIs(timer._ticker, old)
                kernel.CreateWaitableTimerExW.assert_called_once()
                timer.stop()
                timer.start()
                timer._dispatch(old)
                self.assertEqual(ticks, [])
                timer._dispatch(timer._ticker)
                self.assertEqual(ticks, [1])
                current = timer._ticker
                shiboken6.delete(owner)
                self.assertTrue(current.stopped.is_set())
                self.assertTrue(old.stopped.is_set())
        finally:
            if shiboken6.isValid(owner):
                shiboken6.delete(owner)

    def test_native_creation_or_arming_failure_uses_qt_fallback(self):
        for handle, armed in ((None, 0), (123, 0)):
            owner = QWidget()
            timer = clock.FrameTimer(owner)
            kernel = Mock()
            kernel.CreateWaitableTimerExW.return_value = handle
            kernel.SetWaitableTimer.return_value = armed
            try:
                with patch.object(clock, "_kernel", kernel):
                    timer.start()
                    self.assertTrue(timer._fallback.isActive())
                    if handle:
                        kernel.CloseHandle.assert_called_once_with(handle)
                    timer.stop()
                    self.assertFalse(timer.isActive())
            finally:
                shiboken6.delete(owner)

    def test_ticks_reach_gui_thread_and_stop_without_queued_tail(self):
        owner = QWidget()
        timer = clock.FrameTimer(owner)
        timer.setInterval(5)
        threads = []
        loop = QEventLoop()

        def tick():
            threads.append(QThread.currentThread())
            if len(threads) >= 5:
                timer.stop()
                loop.quit()

        timer.timeout.connect(tick)
        guard = QTimer()
        guard.setSingleShot(True)
        guard.timeout.connect(loop.quit)
        try:
            guard.start(1000)
            timer.start()
            loop.exec()
            app.processEvents()
            self.assertEqual(len(threads), 5)
            self.assertTrue(all(thread is app.thread() for thread in threads))
            self.assertFalse(timer.isActive())
        finally:
            timer.stop()
            guard.stop()
            shiboken6.delete(owner)
