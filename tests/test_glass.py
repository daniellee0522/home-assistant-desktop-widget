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
    def test_close_restores_source_and_hides_popover_in_one_composition(self):
        events=[]
        source=Mock()
        source.native.set_transition_tile.side_effect=lambda value: events.append("restore")
        popover=Mock()
        popover.native.hide.side_effect=lambda: events.append("hide")
        dwm=Mock()
        dwm.DwmFlush.side_effect=lambda: events.append("commit")
        scope=definitions("Api", _run_on_ui_thread=lambda window,fn: fn(), _dwmapi=dwm)
        api=scope["Api"].__new__(scope["Api"])
        api._popover_owner="w:a"
        api._window_for=lambda kind: source
        api._popover_window=popover
        api._overlays_open={"popover"}
        api._schedule_release=Mock()
        api._apply_capture_exclusion=Mock()
        api._close_popover()
        self.assertEqual(events,["restore","hide","commit"])
    def test_bottom_pin_does_not_reposition_already_bottom_window(self):
        user = Mock()
        user.GetWindow.return_value = 123
        user.GetWindowLongW.return_value = 0
        scope = definitions('_send_to_bottom', _user32=user,
                            _get_hwnd=lambda w: 123, _hwnd_lock=threading.Lock(),
                            _run_on_ui_thread=lambda w, fn: fn(), GWL_EXSTYLE=-20,
                            HWND_BOTTOM=1, SWP_NOMOVE=2, SWP_NOSIZE=1, SWP_NOACTIVATE=16,
                            WS_EX_TOPMOST=8, GW_HWNDLAST=1)
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
                            _gdi32=gdi, _user32=user, SRCCOPY=0x00CC0020, BLACKNESS=0x42,
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
                            _hwnd_lock=threading.Lock(), _dwmapi=dwm, qtshell=Mock(),
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
        scope = definitions('Api', '_is_widget_kind', time=time, _SYSTEM_GLASS_SUPPORTED=True,
                            _get_hwnd=lambda w: 123, _user32=Mock(),
                            _nothing_visible_of=lambda *a: False)
        api = scope['Api'].__new__(scope['Api'])
        api._window_for = Mock(return_value=Mock())
        api._own_hwnds = Mock(return_value=())
        api._arming_kind = None
        api._cfg = {'glass_mode': 'system'}
        api._system_glass_hwnds = {'main': 123}
        api._hidden_cache = {}
        result = api.get_desktop_backdrop()
        self.assertTrue(result['system_glass'])
        scope['_user32'].GetWindowRect.assert_not_called()
        api._system_glass_hwnds['main'] = 456
        self.assertFalse(api._system_glass_on('main'))

    def test_closed_popover_cannot_leave_widget_in_screen_capture(self):
        affinity = Mock(return_value=True)
        windows = {kind: object() for kind in ('w:a', 'w:b', 'flyout', 'popover', 'settings')}
        scope = definitions('Api', '_is_widget_kind', time=time,
                            _WINDOWS_ABOVE={'main': ('flyout', 'popover'),
                                            'flyout': ('popover', 'settings'),
                                            'popover': (), 'settings': ()},
                            _visible_rect=lambda *args: (0, 0, 100, 100),
                            _rects_overlap=lambda *args: True,
                            _set_capture_exclusion=affinity)
        api = scope['Api'].__new__(scope['Api'])
        api._window_for = lambda kind: windows[kind]
        api._widgets = {'a': windows['w:a'], 'b': windows['w:b']}
        api._cfg = {'glass_mode': 'fast', 'glass_style': 'liquid'}
        api._arming_kind = None
        api._overlays_open = set()
        api._excluded_kinds = set()
        api._capture_epoch = 0
        api._capture_transition_until = 0
        api._apply_capture_exclusion()
        # Every widget reads the screen for its own backdrop.
        self.assertTrue({'w:a', 'w:b'} <= api._excluded_kinds)
        affinity.assert_any_call(windows['w:a'], True)
        affinity.assert_any_call(windows['w:b'], True)
        epoch = api._capture_epoch
        api._overlays_open.add('popover')
        api._apply_capture_exclusion()
        self.assertTrue({'w:a', 'w:b'} <= api._excluded_kinds)
        self.assertEqual(api._capture_epoch, epoch)
        # Settings paints no glass, so opening it over a widget leaves that
        # widget on the fast capture path, and settings itself stays visible
        # to screen capture.
        api._overlays_open = {'settings'}
        api._apply_capture_exclusion()
        self.assertTrue({'w:a', 'w:b'} <= api._excluded_kinds)
        self.assertNotIn('settings', api._excluded_kinds)
        api._cfg["glass_style"]="classic"
        api._overlays_open={"popover"}
        epoch=api._capture_epoch
        api._apply_capture_exclusion()
        self.assertTrue({'w:a', 'w:b'} <= api._excluded_kinds)
        self.assertEqual(api._capture_epoch,epoch)

    def test_popover_composites_excluded_widget_in_both_glass_styles(self):
        scope = definitions('_popover_needs_compat')
        needs_compat = scope['_popover_needs_compat']
        self.assertTrue(needs_compat('popover', 'liquid', {'main', 'popover'}, (123,)))
        self.assertFalse(needs_compat('main', 'liquid', {'main'}, (123,)))
        self.assertTrue(needs_compat('popover', 'classic', {'main'}, (123,)))
        self.assertFalse(needs_compat('popover', 'liquid', {'popover'}, (123,)))

    def test_transparent_widget_keeps_popover_backdrop_color(self):
        from PIL import Image
        scope = definitions('_composite_rgba_window')
        background = Image.new('RGBA', (2, 1), (20, 40, 60, 0))
        widget = Image.new('RGBA', (2, 1), (200, 0, 0, 0))
        widget.putpixel((1, 0), (200, 0, 0, 128))
        raw = scope['_composite_rgba_window'](
            background.tobytes('raw', 'BGRA'), (2, 1), widget, (0, 0))
        result = Image.frombytes('RGBA', (2, 1), raw, 'raw', 'BGRA')
        self.assertEqual(result.getpixel((0, 0))[:3], (20, 40, 60))
        self.assertEqual(result.getpixel((1, 0))[:3], (110, 20, 30))

    def test_popover_reuses_main_screen_pixels_under_widget(self):
        from PIL import Image
        scope = definitions('_composite_rgba_window', '_compose_popover_backdrop')
        screen = Image.new('RGBA', (3, 1), (0, 0, 0, 0))
        main = Image.new('RGBA', (2, 1), (20, 40, 60, 0))
        widget = Image.new('RGBA', (2, 1), (200, 0, 0, 0))
        widget.putpixel((1, 0), (200, 0, 0, 128))
        raw = scope['_compose_popover_backdrop'](
            screen.tobytes('raw', 'BGRA'), (0, 0, 3, 1),
            (1, 0, 2, 1, main.tobytes('raw', 'BGRA')),
            (widget, (1, 0, 3, 1)))
        result = Image.frombytes('RGBA', (3, 1), raw, 'raw', 'BGRA')
        self.assertEqual(result.getpixel((1, 0))[:3], (20, 40, 60))
        self.assertEqual(result.getpixel((2, 0))[:3], (110, 20, 30))

    def test_windows_over_a_widget_are_those_above_it_that_can_be_seen(self):
        # z-order top first: 1 ours, 2 click-through, 3 cloaked, 4 a window over the widget, 5 elsewhere,
        # 9 the widget, 6 below it.
        user = Mock()
        user.IsWindowVisible.return_value = True
        user.IsIconic.return_value = False
        user.GetWindowLongW.side_effect = lambda h, i: 0x20 if h == 2 else 0
        rects = {2: (0, 0, 50, 50), 3: (0, 0, 50, 50), 4: (40, 40, 90, 90),
                 5: (500, 500, 600, 600), 6: (0, 0, 50, 50)}
        dwm = Mock()

        def cloak(h, attr, ref, size):
            ctypes.cast(ref, ctypes.POINTER(ctypes.c_uint)).contents.value = 1 if h == 3 else 0
            return 0
        dwm.DwmGetWindowAttribute.side_effect = cloak

        def enum(proc, _):
            for h in (1, 2, 3, 4, 5, 9, 6):
                if not proc(h, 0):
                    return
        user.EnumWindows.side_effect = enum
        scope = definitions('_windows_over', '_rects_overlap', _user32=user, _dwmapi=dwm,
                            _ENUM_WINDOWS_PROC=lambda f: f, _window_rect=rects.get, _SHADOW_PX=0,
                            GWL_EXSTYLE=-20, WS_EX_TRANSPARENT=0x20, WS_EX_LAYERED=0x80000, LWA_ALPHA=2,
                            DWMWA_CLOAKED=14)
        self.assertEqual(scope['_windows_over'](9, (0, 0, 100, 100), {1}), [(40, 40, 90, 90)])

    def test_a_window_over_a_widget_shows_the_desktop_last_seen_there(self):
        from PIL import Image
        scope = definitions('_patch_covered')
        rect = (100, 100, 4, 2)
        clean = Image.new('RGBA', (4, 2), (10, 20, 30, 255)).tobytes()
        shot = Image.new('RGBA', (4, 2), (200, 200, 200, 255))
        raw = scope['_patch_covered'](shot.tobytes(), rect, [(102, 90, 200, 200)], clean)
        out = Image.frombytes('RGBA', (4, 2), raw)
        self.assertEqual([out.getpixel((x, 0))[:3] for x in range(4)],
                         [(200, 200, 200)] * 2 + [(10, 20, 30)] * 2)

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
