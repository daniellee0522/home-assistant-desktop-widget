"""Network/window regression checks with no live HA credentials or desktop."""
import ast
import ctypes
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import config


def api_type():
    tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
    api = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Api')
    names = {'_push_batch', '_on_ha_status', '_refresh_now', 'show_flyout',
             '_eval_all', '_all_windows'}
    api.body = [n for n in api.body if isinstance(n, ast.FunctionDef) and n.name in names]
    scope = {'json': json, 'threading': threading}
    exec(compile(ast.Module(body=[api], type_ignores=[]), 'main.py', 'exec'), scope)
    return scope['Api']


class Regressions(unittest.TestCase):
    def setUp(self):
        self.api = api_type()()
        for attr in ('_window', '_popover_window', '_flyout_window', '_settings_window'):
            setattr(self.api, attr, Mock())
        self.api._ui_ready = True
        self.api._connected = True

    def test_push_reaches_all_windows_even_if_main_is_missing(self):
        self.api._window = None
        self.api._push_batch([['switch.test', {'state': 'on'}]])
        for attr in ('_popover_window', '_flyout_window', '_settings_window'):
            getattr(self.api, attr).evaluate_js.assert_called_once()

    def test_status_reaches_panel_and_settings(self):
        self.api._on_ha_status(False)
        self.api._flyout_window.evaluate_js.assert_called_once_with('if (typeof window.__haStatus === "function") window.__haStatus(false)')
        self.api._settings_window.evaluate_js.assert_called_once_with('if (typeof window.__haStatus === "function") window.__haStatus(false)')

    def test_refresh_marks_missing_or_failed_entities_unavailable(self):
        for failure in (False, True):
            with self.subTest(failure=failure):
                self.api._cfg = {'ha_token': 'test', 'tiles': [{'entity': 'switch.test'}]}
                self.api._client = Mock()
                self.api._client.get_states.return_value = []
                if failure:
                    self.api._client.get_states.side_effect = RuntimeError('offline')
                done = threading.Event()
                received = []
                self.api._on_ha_event = lambda *args: (received.append(args), done.set())
                self.api._refresh_now()
                self.assertTrue(done.wait(2))
                self.assertEqual(received[0][1]['state'], 'unavailable')
                self.api._client.get_states.assert_called_once()

    def test_empty_panel_opens_settings(self):
        self.api._cfg = {'tiles': []}
        self.api.open_settings_window = Mock()
        self.api.show_flyout()
        self.api.open_settings_window.assert_called_once()
        self.api._flyout_window.show.assert_not_called()

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
