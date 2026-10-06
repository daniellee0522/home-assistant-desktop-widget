"""Network/window regression checks with no live HA credentials or desktop."""
import ast
import ctypes
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import config


def api_type():
    tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
    api = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Api')
    names = {'_push_batch', '_on_ha_status', '_refresh_now', 'show_flyout',
             '_broadcast', '_all_windows', '_all_tiles', '_watched_entities',
             'hide_flyout', '_drive_flyout_toggles', '_home_mode', '_on_ha_event', '_on_ha_events', '_clean_tiles', 'toggle_flyout'}
    api.body = [n for n in api.body if isinstance(n, ast.FunctionDef) and n.name in names]
    scope = {'json': json, 'threading': threading, 'cfgmod': config, 'time': time, 'qtshell': Mock(), 'traceback': __import__('traceback')}
    exec(compile(ast.Module(body=[api], type_ignores=[]), 'main.py', 'exec'), scope)
    return scope['Api']


class Regressions(unittest.TestCase):
    def setUp(self):
        self.api = api_type()()
        for attr in ('_window', '_popover_window', '_flyout_window', '_settings_window'):
            setattr(self.api, attr, Mock())
        self.api._ui_ready = True
        self.api._connected = True
        self.api._known_states = {}
        self.api._widgets = {}

    def test_tray_release_after_the_press_closed_the_panel_is_the_same_click(self):
        api = self.api
        api._SAME_CLICK_S = 0.4
        api._flyout_open = False
        api.show_flyout, api.hide_flyout = Mock(), Mock()
        api._flyout_dismissed_at = time.monotonic()           # the press took the focus and the panel closed itself
        api.toggle_flyout()
        api.show_flyout.assert_not_called()
        api.toggle_flyout(True)                               # (the shortcut is never the release of a click)
        api._flyout_toggle_thread.join(2)
        api.show_flyout.assert_called_once_with(True)
        api.show_flyout.reset_mock()
        api._flyout_dismissed_at = time.monotonic() - 1.0     # a click on the icon later: opens it
        api.toggle_flyout()
        api._flyout_toggle_thread.join(2)
        api.show_flyout.assert_called_once_with(False)
        api._flyout_open = True                               # open: the icon closes it
        api.toggle_flyout()
        api._flyout_toggle_thread.join(2)
        api.hide_flyout.assert_called_once()

    def test_rapid_clicks_coalesce_while_opening_is_busy(self):
        api = self.api
        api._flyout_open = False
        api._flyout_dismissed_at = -1e9
        api._SAME_CLICK_S = .4
        started, release = threading.Event(), threading.Event()
        calls = []
        def show(from_key):
            calls.append("show")
            started.set()
            release.wait(2)
            api._flyout_open = True
        def hide():
            calls.append("hide")
            api._flyout_open = False
        api.show_flyout, api.hide_flyout = show, hide
        api.toggle_flyout(True)
        self.assertTrue(started.wait(1))
        for _ in range(101):
            api.toggle_flyout(True)
        self.assertEqual(calls, ["show"])
        release.set()
        api._flyout_toggle_thread.join(2)
        self.assertEqual(calls, ["show", "hide"])
        self.assertFalse(api._flyout_open)
        self.assertFalse(api._flyout_toggle_running)

    def test_second_tray_click_after_dismiss_is_not_swallowed(self):
        api = self.api
        api._SAME_CLICK_S = .4
        api._flyout_open = False
        api._flyout_dismissed_at = time.monotonic()
        api.show_flyout = Mock()
        api.toggle_flyout()
        api.show_flyout.assert_not_called()
        api.toggle_flyout()
        api._flyout_toggle_thread.join(2)
        api.show_flyout.assert_called_once_with(False)

    def test_desktop_capture_remains_open_until_the_panel_is_hidden(self):
        api = self.api
        window = Mock(is_native_overlay=True)
        api._flyout_window = window
        api._flyout_open = True
        api._flyout_serial = 1
        api._sync_client_entities = Mock()
        api.close_popover = Mock()
        api._overlays_open = {"flyout"}
        api._apply_capture_exclusion = Mock()
        api._schedule_release = Mock()
        api.hide_flyout()
        self.assertIn("flyout", api._overlays_open)
        api._apply_capture_exclusion.assert_not_called()
        finished = window.leave_and_hide.call_args.args[2]
        finished()
        self.assertNotIn("flyout", api._overlays_open)
        api._apply_capture_exclusion.assert_called_once()
        api._schedule_release.assert_called_once_with("flyout")

    def test_old_exit_cannot_hide_a_new_opening_or_later_exit(self):
        api = self.api
        window = Mock(is_native_overlay=True)
        api._flyout_window = window
        api._flyout_open = True
        api._flyout_serial = 1
        api._sync_client_entities = Mock()
        api.close_popover = Mock()
        api._overlays_open = {"flyout"}
        api._apply_capture_exclusion = Mock()
        api._schedule_release = Mock()
        api.hide_flyout()
        valid = window.leave_and_hide.call_args.args[0]
        self.assertTrue(valid())
        api._flyout_serial += 1
        api._flyout_open = True
        self.assertFalse(valid())
        api.hide_flyout()
        self.assertFalse(valid())
        self.assertTrue(window.leave_and_hide.call_args.args[0]())

    def test_push_reaches_all_windows_even_if_main_is_missing(self):
        self.api._window = None
        self.api._widgets = {}
        self.api._push_batch([['switch.test', {'state': 'on'}]])
        for attr in ('_popover_window', '_flyout_window', '_settings_window'):
            getattr(self.api, attr).send.assert_called_once_with('push_states', [['switch.test', {'state': 'on'}]])

    def test_home_only_events_reach_only_the_panel_and_its_card(self):
        self.api._cfg = {'widgets': [{'id': 'w', 'tiles': [{'entity': 'light.on_a_tile'}]}]}
        self.api._home_states = {'sensor.only_in_home': {}}
        self.api._pending = []
        self.api._pending_lock = threading.Lock()
        self.api._on_ha_event('sensor.only_in_home', {'state': '1'})
        self.api._flyout_window.send.assert_called_once()
        self.api._popover_window.send.assert_called_once()
        self.api._window.send.assert_not_called()
        self.api._settings_window.send.assert_not_called()
        self.assertEqual(self.api._home_states['sensor.only_in_home'], {'state': '1'})
        # A device on a tile still reaches every window.
        self.api._flyout_window.send.reset_mock()
        self.api._window.send.reset_mock()
        self.api._on_ha_event('light.on_a_tile', {'state': 'on'})
        self.api._flyout_window.send.assert_called_once()

    def test_home_tile_layout_fields_survive_cleaning(self):
        tiles = self.api._clean_tiles([
            {'id': 'home:a', 'entity': 'light.a', 'w': 2, 'h': 2, 'order': 3, 'hidden': True},
            {'id': 'home:b', 'entity': 'light.b', 'w': 7, 'h': 'x', 'order': 'later'},
            {'id': 'plain', 'entity': 'light.c'}])
        self.assertEqual((tiles[0]['w'], tiles[0]['h'], tiles[0]['order'], tiles[0]['hidden']), (2, 2, 3.0, True))
        self.assertEqual((tiles[1]['w'], tiles[1]['h']), (1, 1))
        self.assertNotIn('order', tiles[1])
        self.assertNotIn('hidden', tiles[1])
        self.assertNotIn('w', tiles[2])

    def test_status_reaches_panel_and_settings(self):
        self.api._on_ha_status(False)
        self.api._flyout_window.send.assert_called_once_with('set_connected', False)
        self.api._settings_window.send.assert_called_once_with('set_connected', False)

    def test_refresh_marks_missing_or_failed_entities_unavailable(self):
        for failure in (False, True):
            with self.subTest(failure=failure):
                self.api._cfg = {'ha_token': 'test', 'widgets': [
                    {'id': 'w', 'tiles': [{'entity': 'switch.test'}]}]}
                self.api._client = Mock()
                self.api._client.get_states.return_value = []
                if failure:
                    self.api._client.get_states.side_effect = RuntimeError('offline')
                done = threading.Event()
                received = []
                self.api._on_ha_events = lambda items: (received.extend(items), done.set())
                self.api._refresh_now()
                self.assertTrue(done.wait(2))
                self.assertEqual(received[0][1]['state'], 'unavailable')
                self.api._client.get_states.assert_called_once()

    def test_empty_panel_opens_settings(self):
        self.api._cfg = {'widgets': [{'id': 'w', 'tiles': []}]}
        self.api.open_settings_window = Mock()
        self.api.show_flyout()
        self.api.open_settings_window.assert_called_once()
        self.api._flyout_window.show.assert_not_called()

    def test_panel_open_arms_once_without_fixed_waits(self):
        for cold in (True, False):
            with self.subTest(cold=cold):
                api = api_type()()
                clock = Mock()
                clock.monotonic.return_value = 1
                api.show_flyout.__globals__.update(time=clock, _get_hwnd=lambda w: 1,
                    _tray_point=lambda: None, _bring_to_front=Mock())
                window = Mock()
                api._all_tiles = lambda: [1]
                api._ensure_overlay = Mock(return_value=window)
                api._sync_client_entities = Mock()
                api._tray_corner = Mock(return_value=(0, 0))
                api._flyout_size = (450, 600)
                api._place_flyout = Mock()
                api._overlays_open = set()
                api._fresh = {'flyout'} if cold else set()
                api._apply_capture_exclusion = Mock()
                api._apply_system_glass = Mock()
                api._watch_flyout_focus = Mock()
                api._arm_backdrop = Mock()
                api.show_flyout(from_key=True)
                api._arm_backdrop.assert_called_once_with('flyout', window,
                    timeout=6.0 if cold else .12, settle=False)
                clock.sleep.assert_not_called()
                window.send.assert_called_once_with('flyout_enter')

    def test_save_uses_config_directory_not_install_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = str(Path(folder) / 'config.json')
            with patch.object(config, 'CONFIG_FILE', dest), patch.object(config, 'BASE_DIR', 'Z:/unwritable'):
                config.save_config({'tiles': []})
            self.assertEqual(json.loads(Path(dest).read_text()), {'tiles': []})
            self.assertEqual(len(list(Path(folder).iterdir())), 1)

    def test_compat_capture_only_composes_windows_below_panel(self):
        tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                     and n.name in {'_windows_below', '_rects_overlap', '_window_rect', '_class_name'}]
        user32 = Mock()
        user32.EnumWindows.side_effect = lambda visit, _: [visit(h, 0) for h in [1, 2, 3, 4, 5]]
        user32.IsWindowVisible.return_value = True
        user32.IsIconic.side_effect = lambda h: h == 4
        user32.GetWindowRect.side_effect = lambda h, p: fill_rect(p)
        dwm = Mock()
        dwm.DwmGetWindowAttribute.return_value = 0
        scope = {'ctypes': ctypes, '_user32': user32, '_dwmapi': dwm,
                 '_ENUM_WINDOWS_PROC': lambda f: f, 'DWMWA_CLOAKED': 14}
        exec(compile(ast.Module(body=functions, type_ignores=[]), 'main.py', 'exec'), scope)
        self.assertEqual(scope['_windows_below'](2, (0, 0, 10, 10)), (5, 3))


def fill_rect(pointer):
    pointer._obj[:] = (0, 0, 20, 20)
    return True


if __name__ == '__main__':
    unittest.main()
