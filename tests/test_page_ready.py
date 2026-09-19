"""Exercise page load gating without importing Qt."""
import ast
from collections import deque
from pathlib import Path
import unittest
from unittest.mock import Mock


class PageReadyTests(unittest.TestCase):
    def test_push_waits_for_its_own_page_and_survives_failed_load(self):
        tree = ast.parse(Path('qtshell.py').read_text(encoding='utf-8'))
        methods = {}
        for cls in tree.body:
            if isinstance(cls, ast.ClassDef):
                for method in cls.body:
                    if isinstance(method, ast.FunctionDef) and method.name in {
                        'evaluate_js', '_on_load', '_on_load_started',
                    }:
                        methods[method.name] = method
        scope = {'_invoke': lambda widget, fn: fn(), 'log': Mock()}
        exec(compile(ast.Module(body=list(methods.values()), type_ignores=[]),
                     'qtshell.py', 'exec'), scope)
        window = Mock()
        window.title = 'Test page'
        window._page_loaded = False
        window._pending_scripts = deque(maxlen=512)
        native = window._native
        native._window = window
        page = native.view.page.return_value
        scope['evaluate_js'](window, 'window.__haPushBatch([])')
        page.runJavaScript.assert_not_called()
        scope['_on_load'](native, False)
        page.runJavaScript.assert_not_called()
        window.events.loaded.fire.assert_not_called()
        scope['_on_load'](native, True)
        page.runJavaScript.assert_called_once_with('window.__haPushBatch([])')
        self.assertFalse(window._pending_scripts)
        scope['_on_load_started'](native)
        scope['evaluate_js'](window, 'window.__haStatus(true)')
        self.assertEqual(page.runJavaScript.call_count, 1)
        scope['_on_load'](native, True)
        page.runJavaScript.assert_called_with('window.__haStatus(true)')


if __name__ == '__main__':
    unittest.main()
