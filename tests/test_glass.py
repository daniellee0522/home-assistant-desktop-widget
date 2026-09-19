"""Glass lifecycle and fallback checks, without starting Qt or contacting HA."""
import ast
import ctypes
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import Mock, patch

from capture_worker import CaptureWorker


def definitions(*names, **scope):
    tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef))
             and n.name in names]
    scope.update(ctypes=ctypes, threading=threading)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'main.py', 'exec'), scope)
    return scope


def test_worker(connection):
    """A real subprocess that can simulate an unresponsive PrintWindow."""
    connection.send(True)
    try:
        while True:
            args = connection.recv()
            if args[0] == 'hang':
                time.sleep(60)
            connection.send(b'frame')
    except (EOFError, OSError):
        pass


class GlassTests(unittest.TestCase):
    def test_bottom_pin_does_not_reposition_already_bottom_window(self):
        user = Mock()
        user.GetWindow.return_value = 123
        user.GetWindowLongW.return_value = 0
        scope = definitions('_send_to_bottom', _user32=user,
                            _get_hwnd=lambda w: 123, _hwnd_lock=threading.Lock(),
                            _run_on_ui_thread=lambda w, fn: fn(), GWL_EXSTYLE=-20,
                            HWND_BOTTOM=1, SWP_NOMOVE=2, SWP_NOSIZE=1, SWP_NOACTIVATE=16)
        scope['_send_to_bottom'](object())
        user.SetWindowPos.assert_not_called()
        user.GetWindow.return_value = 456
        scope['_send_to_bottom'](object())
        self.assertEqual(user.SetWindowPos.call_count, 1)
        user.GetWindow.return_value = 123
        user.GetWindowLongW.return_value = 8
        scope['_send_to_bottom'](object())
        self.assertEqual(user.SetWindowPos.call_count, 2)

    def test_capture_affinity_skips_unchanged_but_retries_failed_read(self):
        user = Mock()
        def read(hwnd, output):
            output._obj.value = 0x11
            return True
        user.GetWindowDisplayAffinity.side_effect = read
        scope = definitions('_set_capture_exclusion', _user32=user,
                            _get_hwnd=lambda w: 123, _hwnd_lock=threading.Lock(),
                            _run_on_ui_thread=lambda w, fn: fn(),
                            WDA_EXCLUDEFROMCAPTURE=0x11, WDA_NONE=0)
        self.assertTrue(scope['_set_capture_exclusion'](object(), True))
        user.SetWindowDisplayAffinity.assert_not_called()
        self.assertTrue(scope['_set_capture_exclusion'](object(), False))
        user.SetWindowDisplayAffinity.assert_called_with(123, 0)
        user.GetWindowDisplayAffinity.side_effect = lambda *args: False
        user.SetWindowDisplayAffinity.return_value = False
        self.assertFalse(scope['_set_capture_exclusion'](object(), True))
        user.SetWindowDisplayAffinity.assert_called_with(123, 0x11)

    def capture(self):
        gdi, user = Mock(), Mock()
        user.GetDC.return_value = 10
        gdi.CreateCompatibleDC.return_value = 20
        gdi.CreateCompatibleBitmap.return_value = 30
        gdi.SelectObject.return_value = 40
        scope = definitions('_DesktopCapture', '_BITMAPINFOHEADER',
                            _gdi32=gdi, _user32=user, SRCCOPY=0x00CC0020,
                            SM_XVIRTUALSCREEN=76, SM_YVIRTUALSCREEN=77,
                            SM_CXVIRTUALSCREEN=78, SM_CYVIRTUALSCREEN=79)
        return scope['_DesktopCapture'](), gdi, user

    def test_deselect_before_read_and_release(self):
        capture, gdi, _ = self.capture()
        self.assertTrue(capture._ensure('_out_dc', '_out_bmp', '_out_size', 2, 2))
        selected = [30]
        def select(dc, obj):
            previous, selected[0] = selected[0], obj
            return previous
        def read(*args):
            self.assertEqual(selected[0], 40)
            return 2
        def delete(obj):
            self.assertNotEqual(selected[0], obj)
            return 1
        gdi.SelectObject.side_effect = select
        gdi.GetDIBits.side_effect = read
        gdi.DeleteObject.side_effect = delete
        self.assertEqual(len(capture._read_out(2, 2)), 16)
        self.assertEqual(selected[0], 30)
        capture.reset()
        gdi.DeleteObject.assert_called_once_with(30)
        gdi.DeleteDC.assert_called_once_with(20)

    def test_partial_read_is_rejected_and_bitmap_restored(self):
        capture, gdi, _ = self.capture()
        capture._ensure('_out_dc', '_out_bmp', '_out_size', 2, 2)
        gdi.GetDIBits.return_value = 1
        self.assertIsNone(capture._read_out(2, 2))
        gdi.SelectObject.assert_called_with(20, 30)

    def test_clipped_capture_clears_old_pixels_before_blit(self):
        capture, gdi, user = self.capture()
        user.GetSystemMetrics.side_effect = lambda metric: {76: 0, 77: 0, 78: 100, 79: 100}[metric]
        gdi.GetDIBits.return_value = 10
        self.assertIsNotNone(capture.grab_screen(-5, 0, 10, 10))
        calls = [call[0] for call in gdi.mock_calls]
        self.assertLess(calls.index('PatBlt'), calls.index('BitBlt'))
        gdi.PatBlt.assert_called_once_with(20, 0, 0, 10, 10, 0x42)
        gdi.BitBlt.assert_called_once_with(20, 5, 0, 5, 10, 10, 0, 0, 0x00CC0020)

    def test_system_failure_rolls_back_and_reports_false(self):
        dwm = Mock()
        dwm.DwmExtendFrameIntoClientArea.return_value = 0
        dwm.DwmSetWindowAttribute.return_value = -1
        scope = definitions('_MARGINS', '_set_system_glass',
                            _SYSTEM_GLASS_SUPPORTED=True, _get_hwnd=lambda w: 123,
                            _hwnd_lock=threading.Lock(), _dwmapi=dwm, webview=Mock(),
                            DWMSBT_TRANSIENTWINDOW=3, DWMSBT_NONE=1,
                            DWMWA_SYSTEMBACKDROP_TYPE=38, DWMWA_BORDER_COLOR=34,
                            DWMWA_COLOR_NONE=0xfffffffe)
        window = Mock()
        window.run_on_ui_thread.side_effect = lambda fn: fn()
        self.assertFalse(scope['_set_system_glass'](window, True))
        self.assertEqual(dwm.DwmExtendFrameIntoClientArea.call_count, 2)
        dwm.DwmSetWindowAttribute.return_value = 0
        self.assertTrue(scope['_set_system_glass'](window, True))

    def test_system_mode_does_not_capture_pixels(self):
        scope = definitions('Api', _SYSTEM_GLASS_SUPPORTED=True,
                            _get_hwnd=lambda w: 123, _user32=Mock(),
                            _nothing_visible_of=lambda *a: False)
        api = scope['Api'].__new__(scope['Api'])
        api._window_for = Mock(return_value=Mock())
        api._own_hwnds = Mock(return_value=())
        api._arming_kind = None
        api._cfg = {'glass_mode': 'system'}
        api._system_glass_hwnds = {'main': 123}
        result = api.get_desktop_backdrop()
        self.assertTrue(result['system_glass'])
        scope['_user32'].GetWindowRect.assert_not_called()
        api._system_glass_hwnds['main'] = 456
        self.assertFalse(api._system_glass_on('main'))

    def test_closed_popover_cannot_leave_widget_in_screen_capture(self):
        affinity = Mock(return_value=True)
        windows = {kind: object() for kind in ('main', 'flyout', 'popover', 'settings')}
        scope = definitions('Api', time=time,
                            _WINDOWS_ABOVE={'main': ('flyout', 'popover', 'settings'),
                                            'flyout': ('popover', 'settings'),
                                            'popover': (), 'settings': ()},
                            _visible_rect=lambda *args: (0, 0, 100, 100),
                            _rects_overlap=lambda *args: True,
                            _set_capture_exclusion=affinity)
        api = scope['Api'].__new__(scope['Api'])
        api._window_for = lambda kind: windows[kind]
        api._cfg = {'glass_mode': 'fast', 'glass_style': 'liquid'}
        api._arming_kind = None
        api._overlays_open = set()
        api._excluded_kinds = set()
        api._capture_epoch = 0
        api._capture_transition_until = 0
        api._capture_excluded = False
        api._apply_capture_exclusion()
        self.assertIn('main', api._excluded_kinds)
        affinity.assert_any_call(windows['main'], True)
        api._overlays_open.add('popover')
        api._apply_capture_exclusion()
        self.assertNotIn('main', api._excluded_kinds)

    def test_worker_timeout_restarts_without_blocking_next_capture(self):
        with patch('capture_worker._serve', test_worker):
            worker = CaptureWorker(timeout=0.15)
            try:
                self.assertEqual(worker.grab('ok'), b'frame')
                started = time.monotonic()
                self.assertIsNone(worker.grab('hang'))
                self.assertLess(time.monotonic() - started, 3)
                self.assertIsNone(worker._process)
                worker.close()  # reset clears the retry cooldown
                self.assertEqual(worker.grab('ok'), b'frame')
            finally:
                worker.close()


if __name__ == '__main__':
    unittest.main()
