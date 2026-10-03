"""The global shortcut (hotkey.py) and the notifications about locks and safety sensors (alerts.py)."""
import ast
import ctypes
import json
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import alerts                                                           # noqa: E402
import config                                                           # noqa: E402
import hotkey                                                           # noqa: E402


def st(state, **attrs):
    return {"state": state, "attributes": attrs}


class Shortcuts(unittest.TestCase):
    def test_written_one_way(self):
        self.assertEqual(hotkey.normalise("Alt+Control+H"), "ctrl+alt+h")
        self.assertEqual(hotkey.normalise("win+shift+f5"), "shift+win+f5")
        self.assertEqual(hotkey.normalise(""), "")
        self.assertEqual(hotkey.label("ctrl+alt+h"), "Ctrl + Alt + H")
        self.assertEqual(hotkey.label("shift+win+f5"), "Shift + Win + F5")
        self.assertEqual(hotkey.label("ctrl+alt+space"), "Ctrl + Alt + Space")

    def test_what_is_not_a_shortcut(self):
        for text in ("h", "shift+h", "ctrl+", "ctrl+alt+bogus", "hyper+h", "ctrl+alt+f25"):
            self.assertIsNone(hotkey.parse(text), text)
            self.assertIsNone(hotkey.normalise(text), text)
        self.assertEqual(hotkey.parse("ctrl+alt+h"), (hotkey.MOD_CONTROL | hotkey.MOD_ALT, ord("H")))
        self.assertEqual(hotkey.parse("alt+f1"), (hotkey.MOD_ALT, 0x70))

    def test_default_is_set(self):
        self.assertEqual(config.DEFAULT_CONFIG["hotkey"], hotkey.DEFAULT)
        self.assertFalse(config.DEFAULT_CONFIG["alert_sensors"])
        self.assertFalse(config.DEFAULT_CONFIG["alert_locks"])

    def test_a_registered_shortcut_is_heard(self):
        """Registers a shortcut nobody uses and presses it with synthetic keys: pressed once, and released
        again when cleared. While it is registered the keys go to it, not to any other program."""
        pressed = threading.Event()
        hk = hotkey.GlobalHotkey(pressed.set)
        combo = "ctrl+alt+shift+f12"
        if not hk.set(combo):
            self.skipTest("the shortcut is taken on this machine")
        user32 = ctypes.WinDLL("user32")
        keys = (0x11, 0x12, 0x10, 0x7B)            # Ctrl, Alt, Shift, F12
        for vk in keys:
            user32.keybd_event(vk, 0, 0, 0)
        for vk in reversed(keys):
            user32.keybd_event(vk, 0, 2, 0)
        self.assertTrue(pressed.wait(2.0))
        self.assertTrue(hk.set(""))                 # none wanted is fine
        self.assertTrue(hk.set(combo))              # and it can be taken again
        hk.set("")


class Alerts(unittest.TestCase):
    def test_locks(self):
        self.assertEqual(alerts.news("lock.front", st("locked"), st("unlocked")), ("已解鎖", "unlocked"))
        self.assertEqual(alerts.news("lock.front", st("locked"), st("jammed"))[1], "jammed")
        self.assertIsNone(alerts.news("lock.front", st("unlocked"), st("locked")))      # locking is not news
        self.assertIsNone(alerts.news("lock.front", st("locked"), st("unlocked"), locks=False))

    def test_sensors(self):
        door = lambda s: st(s, device_class="door")                                   # noqa: E731
        self.assertEqual(alerts.news("binary_sensor.d", door("off"), door("on"))[1], "opened")
        self.assertEqual(alerts.news("binary_sensor.l", st("off", device_class="moisture"),
                                     st("on", device_class="moisture"))[1], "water leak detected")
        self.assertIsNone(alerts.news("binary_sensor.d", door("on"), door("off")))       # closing is not news
        self.assertIsNone(alerts.news("binary_sensor.m", st("off", device_class="motion"),
                                      st("on", device_class="motion")))                 # too chatty
        self.assertIsNone(alerts.news("binary_sensor.d", door("off"), door("on"), sensors=False))
        self.assertIsNone(alerts.news("light.x", st("off"), st("on")))

    def test_baseline_and_unknown_say_nothing(self):
        self.assertIsNone(alerts.news("lock.front", None, st("unlocked")))              # the first state seen
        self.assertIsNone(alerts.news("lock.front", st("unavailable"), st("unlocked")))
        self.assertIsNone(alerts.news("lock.front", st("unlocked"), st("unlocked")))

    def test_once_a_minute_in_the_language_chosen(self):
        sent, now = [], [100.0]
        a = alerts.Alerts(lambda title, text: sent.append(text), clock=lambda: now[0])
        old, new = st("locked"), st("unlocked", friendly_name="Front door")
        self.assertTrue(a.check("lock.front", old, new, True, True, "en"))
        self.assertFalse(a.check("lock.front", old, new, True, True, "en"))
        now[0] += 61
        self.assertTrue(a.check("lock.front", old, new, True, True, "zh-TW"))
        self.assertEqual(sent, ["Front door unlocked", "Front door 已解鎖"])


def api_type():
    tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
    api = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Api")
    names = {"_on_ha_events", "_watched_entities", "_all_tiles", "_push_batch", "_broadcast", "_all_windows"}
    api.body = [n for n in api.body if isinstance(n, ast.FunctionDef) and n.name in names]
    scope = {"json": json, "threading": threading}
    exec(compile(ast.Module(body=[api], type_ignores=[]), "main.py", "exec"), scope)
    return scope["Api"]


class AlertsFromTheApi(unittest.TestCase):
    def make(self, **cfg):
        api = api_type()()
        api._cfg = dict({"widgets": [{"id": "w", "tiles": [{"entity": "lock.front"}]}]}, **cfg)
        api._known_states, api._home_states = {}, {}
        api._ui_ready, api._widgets, api._window = True, {}, Mock()
        api._popover_window = api._flyout_window = api._settings_window = None
        api._alerts = Mock()
        return api

    def test_only_when_chosen_and_only_for_the_tiles(self):
        api = self.make()
        api._on_ha_events([["lock.front", st("locked")]])
        api._on_ha_events([["lock.front", st("unlocked")]])
        api._alerts.check.assert_not_called()                      # off by default
        api = self.make(alert_locks=True)
        api._on_ha_events([["lock.front", st("locked")], ["lock.back", st("locked")]])
        api._on_ha_events([["lock.front", st("unlocked")], ["lock.back", st("unlocked")]])
        checked = [c.args[0] for c in api._alerts.check.call_args_list]
        self.assertNotIn("lock.back", checked)                     # not on a tile
        last = api._alerts.check.call_args_list[-1].args
        self.assertEqual((last[0], last[1]["state"], last[2]["state"]), ("lock.front", "locked", "unlocked"))


class SettingsCapture(unittest.TestCase):
    def test_pressing_keys_sets_the_shortcut(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        import test_native_settings as T
        api, win, sc = T.make()
        sc.capture_shortcut()
        self.assertTrue(sc.capturing)
        sc.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Control, Qt.ControlModifier))   # a modifier alone waits
        self.assertTrue(sc.capturing)
        sc.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_J, Qt.ControlModifier | Qt.AltModifier))
        T.pump(100)
        self.assertFalse(sc.capturing)
        self.assertIn(("prefs", {"hotkey": "ctrl+alt+j"}), api.calls)
        sc.capture_shortcut()
        sc.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_J, Qt.ShiftModifier))           # Shift alone is refused
        self.assertIsNotNone(sc.shortcut_error)
        sc.capture_shortcut()
        sc.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Backspace, Qt.NoModifier))      # Backspace clears
        T.pump(100)
        self.assertIn(("prefs", {"hotkey": ""}), api.calls)
        win.dispose()


if __name__ == "__main__":
    unittest.main()
