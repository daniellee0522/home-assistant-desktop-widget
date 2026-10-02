"""The windows main.py used to make from web pages (the detail card, the tray panel, Settings), made natively.

`NativeOverlay` is what main.py holds: the qtshell.Window interface over an `OverlayScene`, a Scene that
also tells main.py when it is shown, moved, closed or deactivated. What main.py sent to a page as script
(`window.__showPopoverForTile(...)`, `__flyoutEnter()`, ...) is read here and turned into a call on the
scene, so main.py needs no second code path.
"""
import json
import re
import threading
import traceback

from PySide6.QtCore import QEvent, Qt, QTimer

import qtshell

from . import render
from .ui import Scene

# script -> method of the scene (given the script's argument, parsed, when it has one)
_CALLS = (
    (re.compile(r"__applyPrefs\((.*)\)\s*$", re.S), "apply_prefs", True),
    (re.compile(r"__haPushBatch\((.*)\)\s*$", re.S), "push_states", True),
    (re.compile(r"__haStatus\((true|false)\)"), "set_connected", True),
    (re.compile(r"__popoverOwner\((.*)\)\s*$", re.S), "set_owner", True),
    (re.compile(r"__showPopoverForTile\((.*)\)\s*$", re.S), "open_tile", True),
    (re.compile(r"__popoverEnter\(\)"), "enter", False),
    (re.compile(r"closeDetail\(\)"), "close_card", False),
    (re.compile(r"__armBackdrop\(\)"), "arm", False),
    (re.compile(r"__flyoutEnter\(\)"), "flyout_enter", False),
    (re.compile(r"__flyoutLeave\(\)"), "flyout_leave", False),
    (re.compile(r"__enterSettings\(\)"), "enter_settings", False),
    (re.compile(r"__enterEditor\((.*)\)\s*$", re.S), "enter_editor", True),
    (re.compile(r"__invalidateBackdrop\(\)"), "invalidate_glass", False),
    (re.compile(r"__recoverDisplay\(\)"), "update_metrics", False),
)


class OverlayScene(Scene):
    """A Scene that is a window of the program: its events go to the facade."""

    def __init__(self, facade, api, kind):
        super().__init__(api, kind)
        self.facade = facade
        self._shown_once = False

    def showEvent(self, e):
        super().showEvent(e)
        self.cache_hwnd()
        self.facade.events.showing.fire()
        if not self._shown_once:
            self._shown_once = True
            QTimer.singleShot(0, self.facade.events.shown.fire)
        self.sample_now.set()
        self.shown_up()

    def shown_up(self):
        """The window was shown."""

    def moveEvent(self, e):
        super().moveEvent(e)
        pos = e.pos()
        self.facade.events.moved.fire(pos.x(), pos.y())

    def closeEvent(self, e):
        keep = self.facade.events.closing.fire()
        if keep is False:
            e.ignore()
        else:
            e.accept()

    def event(self, e):
        if e.type() == QEvent.Type.WindowDeactivate:
            self.facade.events.deactivated.fire()
        elif e.type() == QEvent.Type.WinIdChange:
            self.cache_hwnd()
        return super().event(e)

    # What main.py may send; a scene overrides the ones it has.
    def apply_prefs(self, prefs):
        pass

    def push_states(self, items):
        pass

    def set_connected(self, on):
        pass

    def set_owner(self, kind):
        pass

    def open_tile(self, tile_id):
        pass

    def enter(self):
        pass

    def close_card(self):
        pass

    def arm(self):
        """Take the backdrop where the window will appear, then say so (Api.backdrop_armed)."""
        self.facade.api.backdrop_armed()

    def flyout_enter(self):
        pass

    def flyout_leave(self):
        pass

    def enter_settings(self):
        pass

    def enter_editor(self, widget_id):
        pass


class NativeOverlay:
    """What main.py holds for a native detail card, tray panel or settings window."""

    is_native_overlay = True

    def __init__(self, api, title, make_scene):
        self.title = title
        self.url = None
        self.js_api = api
        self.api = api
        self.events = qtshell._Events()
        self._hidden = True
        self._native = make_scene(self)

    @property
    def native(self):
        return self._native

    def hwnd(self):
        h = self._native._hwnd
        if h:
            return h
        return qtshell._invoke(self._native, self._native.cache_hwnd, wait=True) or None

    def show(self):
        qtshell._invoke(self._native, self._native.show)

    def hide(self):
        qtshell._invoke(self._native, self._native.hide)

    def set_opacity(self, value):
        qtshell._invoke(self._native, lambda: self._native.setWindowOpacity(value), wait=True)

    def refresh_display(self):
        qtshell._invoke(self._native, self._native.update_metrics)

    def prepare_for_show(self):
        pass

    def destroy(self):
        qtshell._invoke(self._native, self._native.close)

    def dispose(self):
        def run():
            self.events.closing._handlers.clear()
            self._native.stop()
            self._native.close()
            self._native.deleteLater()
        qtshell._invoke(self._native, run, wait=True)
        try:
            qtshell._windows.remove(self)
        except ValueError:
            pass

    def run_on_ui_thread(self, fn):
        return qtshell._invoke(self._native, fn, wait=True)

    def push_frame(self, text):
        pass

    def evaluate_js(self, script):
        for pattern, name, takes in _CALLS:
            m = pattern.search(script)
            if not m:
                continue
            method = getattr(self._native, name, None)
            if method is None:
                return None
            try:
                arg = json.loads(m.group(1)) if takes and m.groups() else None
            except ValueError:
                arg = m.group(1)
            qtshell._invoke(self._native, (lambda: method(arg)) if takes else method)
            return None
        return None


def create_overlay(api, title, make_scene, x=200, y=200):
    """A native overlay window, registered with qtshell like the page windows were."""
    def make():
        win = NativeOverlay(api, title, make_scene)
        win._native.move(int(x), int(y))
        return win
    win = qtshell._invoke(None, make, wait=True)
    if win is None:
        raise RuntimeError("native window could not be created")
    qtshell._windows.append(win)
    return win
