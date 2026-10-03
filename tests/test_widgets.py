"""Multi-widget config migration and per-widget window bookkeeping."""
import ast
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import config


def api_class(*names, **scope):
    """The named methods of Api (plus module helpers) without starting Qt."""
    tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
    api = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Api')
    api.body = [n for n in api.body
                if (isinstance(n, ast.FunctionDef) and n.name in names)]
    helpers = [n for n in tree.body if isinstance(n, ast.FunctionDef)
               and n.name in scope.pop('_helpers', ())]
    scope.update(json=json, threading=threading)
    exec(compile(ast.Module(body=helpers + [api], type_ignores=[]), 'main.py', 'exec'), scope)
    return scope['Api']


class ConfigMigration(unittest.TestCase):
    def load(self, saved):
        with tempfile.TemporaryDirectory() as folder:
            dest = str(Path(folder) / 'config.json')
            if saved is not None:
                Path(dest).write_text(json.dumps(saved), encoding='utf-8')
            with patch.object(config, 'CONFIG_FILE', dest), \
                    patch.object(config, 'BASE_DIR', folder):
                return config.load_config()

    def test_single_widget_config_becomes_one_widget(self):
        tiles = [{'entity': 'light.%d' % i} for i in range(3)]
        cfg = self.load({'tiles': tiles, 'window_x': 10, 'window_y': 20})
        self.assertEqual(len(cfg['widgets']), 1)
        widget = cfg['widgets'][0]
        self.assertEqual((widget['size'], widget['x'], widget['y']), ('2x2', 10, 20))
        self.assertEqual([t['entity'] for t in widget['tiles']],
                         [t['entity'] for t in tiles])
        self.assertIsNone(cfg['panel']['tiles'])

    def test_size_follows_tile_count(self):
        for count, size in ((1, '1x1'), (4, '2x2'), (5, '2x4'), (8, '2x4'), (9, '4x4'), (30, '4x4')):
            self.assertEqual(config.size_for_count(count), size)

    def test_fresh_install_has_an_empty_default_widget(self):
        cfg = self.load(None)
        self.assertEqual(len(cfg['widgets']), 1)
        self.assertEqual(cfg['widgets'][0]['size'], config.DEFAULT_WIDGET_SIZE)
        self.assertEqual(cfg['widgets'][0]['tiles'], [])

    def test_existing_widgets_are_kept_and_cleaned(self):
        cfg = self.load({'widgets': [
            {'id': 'a', 'size': '1x1', 'x': 1, 'y': 2, 'tiles': [{'entity': 'light.a'}]},
            {'id': 'b', 'size': 'bogus', 'x': 'oops', 'tiles': []},
        ], 'panel': {'mode': 'home', 'tiles': [{'entity': 'light.a'}]}})
        self.assertEqual([w['id'] for w in cfg['widgets']], ['a', 'b'])
        self.assertEqual(cfg['widgets'][1]['size'], config.DEFAULT_WIDGET_SIZE)
        self.assertEqual(cfg['panel']['mode'], 'home')
        self.assertEqual(cfg['panel']['tiles'][0]['entity'], 'light.a')

    def test_save_mirrors_first_widget_for_downgrade(self):
        cfg = self.load({'widgets': [
            {'id': 'a', 'size': '2x2', 'x': 5, 'y': 6, 'tiles': [{'entity': 'light.a'}]}]})
        with tempfile.TemporaryDirectory() as folder:
            dest = str(Path(folder) / 'config.json')
            with patch.object(config, 'CONFIG_FILE', dest):
                config.save_config(cfg)
            saved = json.loads(Path(dest).read_text(encoding='utf-8'))
        self.assertEqual(saved['tiles'][0]['entity'], 'light.a')
        self.assertEqual((saved['window_x'], saved['window_y']), (5, 6))

    def test_sides_are_whole_cells(self):
        cols, rows = config.widget_grid('2x4')
        self.assertEqual((cols, rows), (4, 2))
        self.assertEqual(config.widget_grid('4x4'), (4, 4))
        self.assertEqual(config.widget_grid('nope'), config.widget_grid('2x4'))


class WidgetWindows(unittest.TestCase):
    def test_window_lookup_is_strict_for_unknown_kinds(self):
        Api = api_class('_window_for')
        api = Api()
        api._widgets = {'a': 'window-a'}
        api._window = 'primary'
        api._popover_window = 'popover'
        api._settings_window = 'settings'
        api._flyout_window = 'flyout'
        self.assertEqual(api._window_for('w:a'), 'window-a')
        self.assertIsNone(api._window_for('w:gone'))
        self.assertEqual(api._window_for('main'), 'primary')
        self.assertEqual(api._window_for('popover'), 'popover')
        self.assertIsNone(api._window_for('nonsense'))

    def test_widget_kinds(self):
        scope = {}
        tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == '_is_widget_kind')
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'main.py', 'exec'), scope)
        check = scope['_is_widget_kind']
        self.assertTrue(check('main'))
        self.assertTrue(check('w:abc'))
        self.assertFalse(check('popover'))
        self.assertFalse(check(None))


def snap_function():
    tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'snap_rect')
    scope = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'main.py', 'exec'), scope)
    return scope['snap_rect']


class Snapping(unittest.TestCase):
    OTHERS = [(100, 100, 400, 300)]
    AREAS = [(0, 0, 1920, 1080)]

    def snap(self, rect):
        return snap_function()(rect, self.OTHERS, self.AREAS, 16, 12)

    def test_sits_beside_a_neighbour_one_gap_away(self):
        self.assertEqual(self.snap((415, 110, 715, 310)), (412, 100))

    def test_stacks_below_a_neighbour_one_gap_away(self):
        self.assertEqual(self.snap((110, 305, 410, 505)), (100, 312))

    def test_aligns_edges_with_a_neighbour(self):
        x, y = self.snap((108, 600, 408, 800))
        self.assertEqual(x, 100)

    def test_far_from_everything_is_left_alone(self):
        self.assertEqual(self.snap((1000, 500, 1300, 700)), (1000, 500))

    def test_clings_to_the_screen_edge_with_a_gap(self):
        self.assertEqual(self.snap((1615, 20, 1915, 220)), (1608, 12))

    def test_never_lands_on_another_widget(self):
        x, y = self.snap((200, 150, 500, 350))
        right, bottom = x + 300, y + 200
        overlap = x < 400 and right > 100 and y < 300 and bottom > 100
        self.assertFalse(overlap)

    def test_only_snaps_to_neighbours_it_is_beside(self):
        # Far above the neighbour: no side-by-side magnet, only edge alignment.
        x, y = self.snap((415, 700, 715, 900))
        self.assertEqual((x, y), (415, 700))


if __name__ == '__main__':
    unittest.main()
