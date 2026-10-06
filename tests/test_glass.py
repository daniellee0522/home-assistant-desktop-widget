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
    def test_clear_gpu_capture_preserves_raw_pixels_and_exact_static_detection(self):
        from types import SimpleNamespace
        import zlib
        from PIL import Image
        from capture_pixels import within_noise_bgrx
        tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
        prepare = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                       and node.name == 'prepare_pixels')
        api = SimpleNamespace(_cfg={'glass_style': 'liquid', 'liquid_blur': 0}, _capture_epoch=1)
        scope = dict(self=api, window=SimpleNamespace(native=SimpleNamespace(_gpu_shared_capture=True)),
                     window_kind='w:a', is_popover=False, w=13, h=17, capture_epoch=1,
                     last_hash=None, paced=True, started=time.perf_counter(), time=time, zlib=zlib,
                     within_noise_bgrx=within_noise_bgrx, _BACKDROP_NOISE=3,
                     _liquid_params=definitions('_liquid_params')['_liquid_params'])
        original = Image.new('RGB', (13, 17), (40, 50, 60))
        scope['raw'] = original.tobytes('raw', 'BGRX')
        exec(compile(ast.Module(body=[prepare], type_ignores=[]), 'main.py', 'exec'), scope)
        result = scope['prepare_pixels']()
        self.assertIs(result['blur_raw'], scope['raw'])
        self.assertEqual(result['pixel_format'], 'BGRX')
        scope['last_hash'] = result['hash']
        self.assertTrue(scope['prepare_pixels']()['unchanged'])
        changed = original.copy()
        changed.putpixel((3, 4), (44, 50, 60))
        scope['raw'] = changed.tobytes('raw', 'BGRX')
        self.assertNotEqual(scope['prepare_pixels']()['hash'], result['hash'])

    def test_liquid_sampling_keeps_clear_detail_and_reduces_with_frost(self):
        params = definitions('_liquid_params')['_liquid_params']
        self.assertEqual(params(0), (1, 0, 0))
        scales = [params(level / 100)[0] for level in range(101)]
        self.assertEqual(scales, sorted(scales))
        self.assertEqual(params(.4)[0], 1)
        self.assertEqual(params(.8)[0], 2)
        self.assertEqual(scales[-1], 3)

    def test_gpu_widgets_read_one_locked_frame_and_moving_rect_resets_cursor(self):
        from types import SimpleNamespace
        output = SimpleNamespace(name='display', seq=42,
                                 texture_rect=lambda rect: (rect, rect))
        duplication = SimpleNamespace(_gpu=threading.RLock(), _outputs=[output],
                                      grab=Mock(return_value=((('display', 42),), b'')))
        scope = definitions('Api', _screen_duplication=duplication, _get_hwnd=lambda window: window,
                            time=time)
        api = scope['Api'].__new__(scope['Api'])
        api._cfg = {}
        api._window_for=lambda kind: kind
        position=[10]
        api._capture_rect=lambda hwnd,w,h: (position[0] if hwnd=='w:a' else 100,20,w,h)
        def capture(kind,digest,w,h,x,y,wait,defer=False):
            self.assertTrue(duplication._gpu._is_owned())
            self.assertEqual(wait,0)
            saved = output.seq
            def prepare():
                self.assertFalse(duplication._gpu._is_owned())
                self.assertTrue(duplication._gpu.acquire(blocking=False))
                duplication._gpu.release()
                return {'kind':kind,'frame':saved}
            self.assertTrue(defer)
            return prepare
        api.get_desktop_backdrop=capture
        requests=[('w:a',1,30,40),('w:b',2,30,40)]
        cursor,shots=api.widget_glass_frames(requests)
        self.assertEqual([s['frame'] for s in shots],[42,42])
        self.assertIsNone(duplication.grab.call_args.args[4])
        api._cfg['liquid_blur'] = 50
        api.widget_glass_frames(requests,cursor)
        self.assertEqual(duplication.grab.call_args.args[4],(('display',42),))
        position[0]=11
        api.widget_glass_frames(requests,cursor)
        self.assertIsNone(duplication.grab.call_args.args[4])
        api._backdrop_pool.shutdown(wait=True)

    def test_widget_takes_the_desktop_on_the_gpu_only_for_clear_and_lightly_frosted_liquid_glass(self):
        from types import SimpleNamespace
        duplication = SimpleNamespace(gpu_source=Mock(return_value=((), ())))
        scope = definitions('Api', _screen_duplication=duplication, time=time,
                            _liquid_params=definitions('_liquid_params')['_liquid_params'])
        api = scope['Api'].__new__(scope['Api'])
        api._cfg = {'glass_style': 'liquid', 'liquid_blur': 25}
        native = SimpleNamespace(_gpu_shared_capture=True,
                                 _gpu_receiver=SimpleNamespace(compositor=SimpleNamespace(device=5)))
        window = SimpleNamespace(native=native)
        rect = (0, 0, 100, 100)
        self.assertEqual(api._gpu_direct_frame(window, 'w:a', rect, 1), .3 * .25)
        api._cfg['liquid_blur'] = 80                       # frosted: the CPU shrinks the picture first
        self.assertIsNone(api._gpu_direct_frame(window, 'w:a', rect, 1))
        api._cfg.update(liquid_blur=25, glass_style='classic')
        self.assertIsNone(api._gpu_direct_frame(window, 'w:a', rect, 1))
        api._cfg['glass_style'] = 'liquid'
        native._gpu_direct_after = time.monotonic() + 5    # the renderer just gave the GPU copy up
        self.assertIsNone(api._gpu_direct_frame(window, 'w:a', rect, 1))
        native._gpu_direct_after = 0
        duplication.gpu_source.return_value = None         # across screens, rotated, another adapter
        self.assertIsNone(api._gpu_direct_frame(window, 'w:a', rect, 1))

    def test_the_panel_takes_only_widgets_under_it_and_not_again_while_they_have_not_drawn(self):
        from types import SimpleNamespace
        taken = []
        rects = {'w:a': (0, 0, 100, 100), 'w:b': (500, 500, 600, 600)}
        receivers = {k: SimpleNamespace(frames=1) for k in rects}
        windows = {k: SimpleNamespace(native=SimpleNamespace(_gpu_receiver=receivers[k])) for k in rects}
        scope = definitions('Api', time=time, _visible_rect=lambda window: next(
                                rects[k] for k, w in windows.items() if w is window),
                            _rects_overlap=definitions('_rects_overlap')['_rects_overlap'],
                            _grab_widget_rgba=lambda window: taken.append(window) or ('picture', 1))
        api = scope['Api'].__new__(scope['Api'])
        api._window_for = windows.get
        panel = (50, 50, 300, 300)
        self.assertEqual(api._widget_under('w:a', panel), ('picture', 1))
        self.assertIsNone(api._widget_under('w:b', panel))        # not under the panel: never taken
        self.assertEqual(len(taken), 1)
        time.sleep(.08)                                            # old enough to be looked at again...
        api._widget_under('w:a', panel)
        self.assertEqual(len(taken), 1)                            # ...but it has not drawn since
        receivers['w:a'].frames = 2
        api._widget_under('w:a', panel)
        self.assertEqual(len(taken), 2)
        rects['w:a'] = (10, 10, 110, 110)                          # moved: its picture no longer fits
        api._widget_under('w:a', panel)
        self.assertEqual(len(taken), 3)

    def test_the_panel_takes_the_desktop_on_the_gpu_only_when_no_widget_lies_under_it(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from nativeui import dcomp
        duplication = SimpleNamespace(gpu_source=Mock(return_value=((), ())))
        shown = {'w:a': (900, 900, 1000, 1000)}
        scope = definitions('Api', _screen_duplication=duplication, time=time,
                            _visible_rect=lambda window: shown[window],
                            _rects_overlap=definitions('_rects_overlap')['_rects_overlap'])
        api = scope['Api'].__new__(scope['Api'])
        api._cfg = {'glass_style': 'liquid'}
        api._widget_kinds = lambda: ['w:a']
        api._excluded_kinds = {'w:a', 'flyout'}
        api._window_for = lambda kind: kind
        helper = SimpleNamespace(material=object(), shown=True, direct_after=0, device=7)
        rect = (100, 100, 300, 600)
        with patch.dict(dcomp._state, {'slider': helper}):
            self.assertEqual(api._flyout_direct(rect), 0.0)
            shown['w:a'] = (250, 300, 450, 500)               # a widget under the panel: drawn into its picture
            self.assertIsNone(api._flyout_direct(rect))
            shown['w:a'] = (900, 900, 1000, 1000)
            helper.direct_after = time.monotonic() + 5       # the GPU copy just failed
            self.assertIsNone(api._flyout_direct(rect))
            helper.direct_after, helper.material = 0, None   # not a material on the compositor
            self.assertIsNone(api._flyout_direct(rect))
            helper.material, api._cfg['glass_style'] = object(), 'classic'
            self.assertIsNone(api._flyout_direct(rect))
            api._cfg['glass_style'] = 'liquid'
            duplication.gpu_source.return_value = None
            self.assertIsNone(api._flyout_direct(rect))

    def test_a_covered_widget_is_looked_at_again_within_a_tenth_of_a_second(self):
        from types import SimpleNamespace
        covered = [True]
        scope = definitions('Api', time=time, _is_widget_kind=lambda kind: True,
                            _user32=SimpleNamespace(IsWindowVisible=lambda hwnd: True),
                            _nothing_visible_of=lambda hwnd, ours: covered[0])
        api = scope['Api'].__new__(scope['Api'])
        api._hidden_cache = {}
        api._own_hwnds = lambda: set()
        first = api._hidden_answer('w:a', 1)
        self.assertEqual(first['retry_ms'], 100)
        covered[0] = False                       # the cover goes
        self.assertIs(api._hidden_answer('w:a', 1), first)       # (still the answer just given)
        time.sleep(.1)
        self.assertIsNone(api._hidden_answer('w:a', 1))          # looked at again: capture resumes

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

    def test_live_panel_does_not_swap_capture_source_for_a_missing_frame(self):
        duplication = Mock()
        duplication.grab.return_value = None
        duplication.available.return_value = True
        desktop = Mock()
        scope = definitions('Api', '_is_widget_kind', time=time,
            _get_hwnd=lambda w: 123, _screen_duplication=duplication,
            _desktop_capture=desktop, _DUPLICATION_WAIT_SECS=.05,
            _popover_needs_compat=lambda *a: False)
        api = scope['Api'].__new__(scope['Api'])
        api._cfg = {'glass_style': 'liquid'}
        api._panel_bg_path = lambda: None
        api._window_for = Mock(return_value=Mock())
        api._arming_kind = 'flyout'
        api._system_glass_on = lambda kind: False
        api._capture_epoch = 1
        api._excluded_kinds = {'flyout'}
        api._popover_owner = 'w:a'
        api._capture_rect = lambda *a: (100, 200, 400, 600)
        previous = ((100, 200, 400, 600), (('monitor', 42),))
        api._duplication_after = {'flyout': previous}
        result = api.get_desktop_backdrop('flyout', 123)
        self.assertTrue(result['skip'])
        self.assertEqual(result['retry_ms'], 16)
        desktop.grab_screen.assert_not_called()
        self.assertEqual(api._duplication_after['flyout'], (previous[0], None))
        # The next source frame is retained normally; a quiet source is not a failure.
        duplication.grab.return_value = ((('monitor', 43),), None)
        result = api.get_desktop_backdrop('flyout', 123)
        self.assertTrue(result['unchanged'])
        self.assertIsNone(duplication.grab.call_args.args[4])
        desktop.grab_screen.assert_not_called()

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

    def test_compositor_helper_counts_as_our_window_for_live_capture(self):
        from nativeui import dcomp
        scope = definitions('Api', _get_hwnd=lambda w: w)
        api = scope['Api'].__new__(scope['Api'])
        api._all_windows = lambda: [101]
        helper = Mock(shown=True, hwnd=202)
        with patch.dict(dcomp._state, slider=helper):
            self.assertEqual(api._own_hwnds(), {101, 202})
            helper.shown = False
            self.assertEqual(api._own_hwnds(), {101})

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
        api._overlays_open = {'flyout'}
        api._apply_capture_exclusion()
        self.assertTrue({'w:a', 'w:b'} <= api._excluded_kinds)
        self.assertEqual(api._capture_epoch, epoch)
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
        # z-order top first: 1 ours, 2 visible but click-through, 3 cloaked, 4 over the widget, 5 elsewhere,
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
        self.assertEqual(scope['_windows_over'](9, (0, 0, 100, 100), {1}),
                         [(0, 0, 50, 50), (40, 40, 90, 90)])

    def test_occluded_capture_is_never_published_without_clean_pixels(self):
        capture = Mock()
        scope = definitions('Api', _windows_over=lambda *args: [],
                            _compat_capture=capture, _patch_covered=Mock())
        api = scope['Api'].__new__(scope['Api'])
        api._clean_backdrops = {}
        rect = (10, 20, 2, 2)
        raw = bytes([200] * 16)
        for unavailable in (None, bytes(4)):
            capture.grab.return_value = unavailable
            self.assertIsNone(api._without_windows_over('w:a', 1, rect, raw,
                                                       [(10, 20, 12, 22)], set()))
            self.assertEqual(api._clean_backdrops, {})
        scope['_patch_covered'].assert_not_called()

    def test_occlusion_arriving_during_capture_uses_previous_clean_backdrop(self):
        from PIL import Image
        scope = definitions('Api', '_patch_covered',
                            _windows_over=lambda *args: [(11, 20, 12, 22)],
                            _compat_capture=Mock())
        api = scope['Api'].__new__(scope['Api'])
        rect = (10, 20, 2, 2)
        clean = Image.new('RGBA', (2, 2), (10, 20, 30, 255)).tobytes()
        raw = Image.new('RGBA', (2, 2), (200, 210, 220, 255)).tobytes()
        api._clean_backdrops = {'w:a': (rect, clean)}
        result = api._without_windows_over('w:a', 1, rect, raw, [], set())
        image = Image.frombytes('RGBA', (2, 2), result)
        self.assertEqual(image.getpixel((1, 0)), (10, 20, 30, 255))
        self.assertEqual(image.getpixel((0, 0)), (200, 210, 220, 255))
        scope['_compat_capture'].grab.assert_not_called()

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
