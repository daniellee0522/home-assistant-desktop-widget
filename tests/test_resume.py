"""Resume recovery without suspending the test machine or starting Qt."""
import ast
import ctypes
from ctypes import wintypes
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock


def extract(path, name, scope):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, "exec"), scope)
    return scope[name]


class ResumeTests(unittest.TestCase):
    def test_hidden_surface_defers_recovery_until_shown(self):
        refresh = extract("qtshell.py", "_refresh_display", {})
        native = Mock()
        native.size.return_value.width.return_value = 300
        native.size.return_value.height.return_value = 200
        native.isVisible.return_value = False
        refresh(native)
        self.assertTrue(native._display_dirty)
        native.resize.assert_not_called()
        native.view.show.assert_not_called()
        native.isVisible.return_value = True
        refresh(native)
        self.assertFalse(native._display_dirty)
        self.assertEqual(native.resize.call_count, 2)
        native.view.hide.assert_called_once()
        native.view.show.assert_called_once()
        native._window.evaluate_js.assert_called_once_with(
            "window.__recoverDisplay && window.__recoverDisplay()")

    def test_flyout_origin_uses_current_monitor_work_area(self):
        work_area = Mock(return_value=(0, 0, 1920, 1040))
        origin = extract("main.py", "_flyout_origin", {"_work_area_at": work_area})
        api = Mock(_flyout_anchor=((0, 0, 2560, 1400), True), _FLYOUT_MARGIN=12)
        self.assertEqual(origin(api, 300, 200), (1608, 828))
        work_area.assert_called_once_with(2559, 1399)

    def test_old_resize_cannot_poison_flyout_size_cache(self):
        scope = {"MIN_WINDOW_W": 1, "MIN_WINDOW_H": 1,
                 "_get_hwnd": lambda w: 123, "_set_window_rect": Mock(),
                 "_set_window_size": Mock(), "_run_on_ui_thread": lambda w, fn: fn()}
        resize = extract("main.py", "_resize_native", scope)
        resize_flyout = extract("main.py", "resize_flyout_window", scope)
        api = Mock(_flyout_size=(100, 100), _flyout_last_resize_seq=10,
                   _flyout_resize_lock=threading.Lock())
        api._flyout_origin.return_value = (5, 5)
        api._resize_native = lambda *a, **kw: resize(api, *a, **kw)
        resize_flyout(api, 300, 200, 11)
        self.assertEqual(api._flyout_size, (300, 200))
        resize_flyout(api, 100, 100, 9)
        self.assertEqual(api._flyout_size, (300, 200))
        scope["_set_window_rect"].assert_called_once_with(123, 5, 5, 300, 200)

    def test_tray_recovery_posts_to_icon_thread_even_if_logically_visible(self):
        native = Mock()
        native.windll.user32.PostMessageW.return_value = 1
        restore = extract("tray.py", "restore_tray_icon", {
            "ctypes": native, "wintypes": wintypes})
        icon = Mock(_hwnd=123, visible=True)
        self.assertTrue(restore(icon))
        native.windll.user32.PostMessageW.assert_called_once_with(123, 0x007E, 0, 0)
        icon.stop.assert_not_called()
        self.assertFalse(restore(None))
        native.windll.user32.PostMessageW.return_value = 0
        self.assertFalse(restore(icon))

    def test_tray_recovery_is_independent_of_hidden_desktop(self):
        api = Mock(_desktop_visible=False)
        restore_icon = Mock(return_value=True)
        restore = extract("main.py", "restore_tray", {
            "api": api, "restore_tray_icon": restore_icon, "webview": Mock()})
        restore()
        restore_icon.assert_called_once_with(api._tray_icon)

    def test_native_resume_signals_worker_without_consuming_message(self):
        pending = threading.Event()
        callback = extract("qtshell.py", "nativeEventFilter", {
            "wintypes": wintypes, "_resume_pending": pending})
        for event in (0x0007, 0x0012):
            pending.clear()
            msg = wintypes.MSG()
            msg.message, msg.wParam = 0x0218, event
            self.assertEqual(callback(None, b"windows_generic_MSG",
                                      ctypes.addressof(msg)), (False, 0))
            self.assertTrue(pending.is_set())
        pending.clear()
        msg.wParam = 0x0004  # suspend is not resume
        callback(None, b"windows_generic_MSG", ctypes.addressof(msg))
        self.assertFalse(pending.is_set())
        callback(None, b"other_platform", 0)

    def test_restore_rechecks_visibility_and_restores_native_state(self):
        window, api = Mock(), Mock()
        api._all_windows.return_value = [window]
        scope = {"window": window, "api": api, "webview": Mock()}
        for name in ("_set_noactivate", "_apply_window_shape", "_send_to_bottom"):
            scope[name] = Mock()
        restore = extract("main.py", "restore_window", scope)
        api._desktop_visible = True
        restore()
        window.native.showNormal.assert_called_once()
        window.native._cache_hwnd.assert_called_once()
        scope["_send_to_bottom"].assert_called_once_with(window)
        api._apply_system_glass.assert_called_once_with()
        window.refresh_display.assert_called_once()
        api._desktop_visible = False
        restore()  # a delayed retry must respect a subsequent tray hide
        window.native.showNormal.assert_called_once()

    def test_short_sleep_power_notification_runs_resume_hook(self):
        pending = threading.Event()
        pending.set()
        clock = Mock()
        clock.monotonic.side_effect = [100, 101]
        clock.sleep.side_effect = [None, InterruptedError]
        hook = Mock()
        scope = {"time": clock, "_resume_pending": pending,
                 "_SUSPEND_SECS": 20, "_STALL_SECS": 10,
                 "_alive_at": [100], "_hang_logged": [False],
                 "_resume_hooks": [hook], "log": Mock()}
        watchdog = extract("qtshell.py", "_watchdog", scope)
        with self.assertRaises(InterruptedError):
            watchdog()
        hook.assert_called_once()
        self.assertFalse(pending.is_set())


if __name__ == "__main__":
    unittest.main()
