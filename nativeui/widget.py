"""A desktop widget drawn natively: no browser page, a QWidget painted with QPainter.

It stands where the page-based widget stood (main.py's `_create_widget_window`): the same
window interface (hwnd, show, hide, dispose, events, run_on_ui_thread, evaluate_js), the same
Api behind it (states, preferences, service calls, the detail card, the desktop capture and
its exclusion, dimming, snapping). What it does itself is what the page did itself: draw the
tiles, take the touches, ask for the glass.

Threads: the Qt widget lives on the GUI thread; the glass is made on its own thread from
what `Api.get_desktop_backdrop` answers, and only the newest picture ever reaches the GUI.
"""
import ctypes
import json
import os
import re
import threading
import time
import traceback
from ctypes import wintypes

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, Signal, QObject
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

import qtshell

from . import render
from .actions import TileActions
from .glass import GlassMixin

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetDpiForWindow.argtypes = [ctypes.c_void_p]
_user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
_user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
_user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_uint]

HOLD_MS = 420                 # how long a press is held to open the detail card
HOLD_SLOP_PX = 8              # moving further than this cancels the hold
DRAG_PX = 5                   # moving further than this drags the widget
SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x2, 0x4, 0x10
WHEEL_STEP = 100              # CSS px a notch of the wheel scrolls
EASE_DIM_MS, EASE_WAKE_MS = 700, 260


class _Signals(QObject):
    states = Signal()                     # tiles changed: draw them again


def _cursor():
    pt = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def _rect(hwnd):
    r = wintypes.RECT()
    if hwnd and _user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return r.left, r.top, r.right, r.bottom
    return None


class _Surface(GlassMixin, QWidget):
    """The Qt window of one widget."""

    def __init__(self, facade, api, widget_id):
        super().__init__()
        self.facade, self.api, self.widget_id = facade, api, widget_id
        self.kind = "w:" + widget_id
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setMouseTracking(True)
        self._hwnd = 0
        self._shown_once = False
        self.prefs = {}
        self.states = {}
        self.tiles = []
        self.size_key = "2x4"
        self.zoom = 100
        self.theme_raw = "auto"
        self.theme = "light"
        self.style = "classic"
        self.language = "zh-TW"
        self.liquid_level = 0
        self.sampling = "live"
        self.locked = False
        self.system_glass = False
        self.dpi = 1.0
        self.scale = 1.0
        self.pw = self.ph = 1
        self.form, self.rects = "small", []
        self.scroll, self.scroll_max = 0.0, 0.0
        self.tcol = render.tokens("light")
        # What is drawn.
        self.overlay = self.overlay_dim = None
        self.mix = None
        self.init_glass()
        self.dim_t, self.dim_from, self.dim_target = 0.0, 0.0, False
        self.dim_clock = QElapsedTimer()
        self.dim_timer = QTimer(self)
        self.dim_timer.setInterval(16)
        self.dim_timer.timeout.connect(self._step_dim)
        self.flash = {}                           # tile index -> started (monotonic)
        self.flash_timer = QTimer(self)
        self.flash_timer.setInterval(33)
        self.flash_timer.timeout.connect(self._step_flash)
        self.hover = -1
        self.pressed = -1
        self._wake_sent = 0.0
        # The pointer.
        self._press = None
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(self._held)
        self.empty_button = None
        self.signals = _Signals()
        self.signals.states.connect(self._redraw_tiles, Qt.QueuedConnection)
        self._redraw_pending = False
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda *_: self._theme_changed())

    # ---- the window --------------------------------------------------------
    def cache_hwnd(self):
        try:
            self._hwnd = int(self.winId())
        except Exception:
            self._hwnd = 0
        return self._hwnd

    _cache_hwnd = cache_hwnd          # the name main.py knows from the page windows

    def showEvent(self, e):
        super().showEvent(e)
        self.cache_hwnd()
        self.facade.events.showing.fire()
        if not self._shown_once:
            self._shown_once = True
            QTimer.singleShot(0, self._first_shown)
        self.sample_now.set()

    def _first_shown(self):
        self.facade.events.shown.fire()
        self.relayout()
        self.start_glass()

    def moveEvent(self, e):
        super().moveEvent(e)
        pos = e.pos()
        self.facade.events.moved.fire(pos.x(), pos.y())
        if self._hwnd:
            dpi = _user32.GetDpiForWindow(self._hwnd) / 96.0
            if dpi and abs(dpi - self.dpi) > 0.01:
                self.relayout()

    def closeEvent(self, e):
        keep = self.facade.events.closing.fire()
        if keep is False:
            e.ignore()
        else:
            e.accept()

    # ---- what to draw --------------------------------------------------------
    def configure(self, prefs):
        """Take the preferences (Api._prefs). Returns what changed, as a set of names."""
        mine = next((w for w in prefs.get("widgets", []) if w["id"] == self.widget_id), None)
        if mine is None and prefs.get("widgets"):
            mine = prefs["widgets"][0]
        mine = mine or {"size": "2x4", "tiles": []}
        new = {
            "tiles": mine["tiles"], "size_key": mine["size"], "zoom": prefs.get("zoom", 100),
            "theme_raw": prefs.get("theme", "auto"), "style": prefs.get("glass_style", "classic"),
            "language": prefs.get("language", "zh-TW"), "liquid_level": prefs.get("liquid_blur", 0),
            "sampling": prefs.get("glass_sampling", "live"), "locked": bool(prefs.get("lock_position")),
        }
        if new["style"] not in ("classic", "liquid", "windows"):
            new["style"] = "classic"
        changed = {k for k, v in new.items() if getattr(self, k) != v}
        for k, v in new.items():
            setattr(self, k, v)
        glass = (prefs.get("system_glass_active") or {}).get(self.kind) is True
        if glass != self.system_glass:
            self.system_glass = glass
            changed.add("system_glass")
        self.prefs = prefs
        return changed

    def _resolve_theme(self):
        theme = self.theme_raw
        if theme == "auto":
            dark = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
            theme = "dark" if dark else "light"
        return theme

    def _theme_changed(self):
        if self.theme_raw == "auto" and self._resolve_theme() != self.theme:
            self.rebuild(all_=True)

    def apply(self, prefs):
        changed = self.configure(prefs)
        if not changed:
            return
        render.set_language(self.language)
        if changed & {"size_key", "zoom", "tiles"}:
            self.relayout()
        elif changed & {"theme_raw", "style", "language", "system_glass"}:
            self.rebuild(all_=True)
        if changed & {"style", "liquid_level", "size_key", "zoom", "system_glass"}:
            self.reset_glass()
            self.facade.invalidate_backdrop()
        if "sampling" in changed:
            self.sample_now.set()

    def relayout(self):
        """Size, scale and the tiles' places: after a change of size, zoom, tiles or monitor."""
        hwnd = self.cache_hwnd()
        self.dpi = (_user32.GetDpiForWindow(hwnd) / 96.0) if hwnd else (self.devicePixelRatioF() or 1.0)
        self.dpi = self.dpi or 1.0
        self.scale = max(0.5, min(2.0, self.zoom / 100.0)) * self.dpi
        cw, ch = render.widget_size(self.size_key)
        self.pw, self.ph = round(cw * self.scale), round(ch * self.scale)
        self.form, self.rects = render.tile_layout(self.size_key, len(self.tiles))
        self.scroll_max = render.scroll_range(self.size_key, len(self.tiles))
        self.scroll = max(0.0, min(self.scroll, self.scroll_max))
        if hwnd:
            _user32.SetWindowPos(hwnd, None, 0, 0, self.pw, self.ph, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE)
        self.reset_glass()
        self.rebuild(all_=True)
        self.facade.invalidate_backdrop()

    def rebuild(self, all_=False):
        self.theme = self._resolve_theme()
        self.tcol = render.tokens(self.theme, False, self.style)
        render.set_language(self.language)
        self.overlay = self.overlay_dim = None
        self.update()

    def _ui(self):
        now = time.monotonic()
        flash = {i: max(0.0, 1 - (now - t) / 0.6) for i, t in self.flash.items()}
        return {"hover": self.hover, "pressed": self.pressed, "flash": flash, "scroll": self.scroll}

    def _draw(self, dim):
        img = QImage(self.pw, self.ph, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        self.empty_button = render.draw_widget(p, self.size_key, self.tiles, self.states, self.theme, None,
                                               self.scale, dim, self.style, self._ui(), self.theme_raw)
        p.end()
        pix = QPixmap.fromImage(img)
        pix.setDevicePixelRatio(self.dpi)
        return pix

    # -- the glass (nativeui/glass.py) asks what the card is -------------------------
    def glass_card(self):
        cw, ch = render.widget_size(self.size_key)
        return cw, ch, self.tcol["radius_panel"]

    def glass_tiles(self):
        s, off, H = self.scale, self.scroll, render.widget_size(self.size_key)[1]
        return [(round(x * s), round((y - off) * s), round(w * s), round(h * s), round(self.tcol["radius_tile"] * s))
                for x, y, w, h in self.rects if 0 <= y - off and y - off + h <= H]

    def paintEvent(self, event):
        if self.overlay is None:
            self.overlay = self._draw(False)
        if self.dim_t > 0 and self.overlay_dim is None:
            self.overlay_dim = self._draw(True)
        p = QPainter(self)
        if self.glass is not None and not self.system_glass:
            p.drawImage(0, 0, self.glass)
        if self.dim_t <= 0:
            p.drawPixmap(0, 0, self.overlay)
        elif self.dim_t >= 1:
            p.drawPixmap(0, 0, self.overlay_dim)
        else:
            # A cross-fade: (1 - t) of the lit picture plus t of the dimmed one.
            if self.mix is None or self.mix.width() != self.pw or self.mix.height() != self.ph:
                self.mix = QImage(self.pw, self.ph, QImage.Format_ARGB32_Premultiplied)
                self.mix.setDevicePixelRatio(self.dpi)
            m = QPainter(self.mix)
            m.setCompositionMode(QPainter.CompositionMode_Source)
            m.fillRect(self.mix.rect(), Qt.transparent)
            m.setCompositionMode(QPainter.CompositionMode_SourceOver)
            m.setOpacity(1 - self.dim_t)
            m.drawPixmap(0, 0, self.overlay)
            m.setCompositionMode(QPainter.CompositionMode_Plus)
            m.setOpacity(self.dim_t)
            m.drawPixmap(0, 0, self.overlay_dim)
            m.end()
            p.drawImage(0, 0, self.mix)
        p.end()

    # ---- the states -----------------------------------------------------------
    def push_states(self, items):
        for entity, state in items:
            self.states[entity] = state
        self._schedule_redraw()

    def _schedule_redraw(self):
        if not self._redraw_pending:
            self._redraw_pending = True
            self.signals.states.emit()

    def _redraw_tiles(self):
        self._redraw_pending = False
        self.overlay = self.overlay_dim = None
        self.update()

    def optimistic(self, entity, patch):
        st = self.states.get(entity)
        if st is None:
            return
        self.states[entity] = dict(st, **patch)
        self._schedule_redraw()

    # ---- dimming ---------------------------------------------------------------
    def set_dim(self, on):
        if on == self.dim_target:
            return
        self.dim_target = on
        self.dim_from = self.dim_t
        self.dim_clock.start()
        self.dim_timer.start()

    def _step_dim(self):
        dur = EASE_DIM_MS if self.dim_target else EASE_WAKE_MS
        k = min(1.0, self.dim_clock.elapsed() / dur)
        k = k * k * (3 - 2 * k)
        goal = 1.0 if self.dim_target else 0.0
        self.dim_t = self.dim_from + (goal - self.dim_from) * k
        if k >= 1.0:
            self.dim_t = goal
            self.dim_timer.stop()
            if not self.dim_target:
                self.overlay_dim = None
        self.update()

    def _wake(self):
        """The first touch of a dimmed widget only wakes it, every widget at once."""
        if not self.dim_target:
            return False
        now = time.monotonic()
        if now - self._wake_sent > 0.6:            # once, not for every mouse move that follows
            self._wake_sent = now
            threading.Thread(target=self.api.wake, daemon=True).start()
            # Should Python never answer, wake this one on its own.
            QTimer.singleShot(600, lambda: self.set_dim(False) if self.dim_target else None)
        return True

    # ---- the pointer -----------------------------------------------------------
    def _point(self, e):
        """The pointer in CSS px of the widget (the scroll undone for the tiles) and physical px."""
        pos = e.position()
        px, py = pos.x() * self.devicePixelRatioF(), pos.y() * self.devicePixelRatioF()
        return px / self.scale, py / self.scale, px, py

    def _tile_at(self, x, y):
        y += self.scroll
        for i, (tx, ty, tw, th) in enumerate(self.rects):
            if tx <= x < tx + tw and ty <= y < ty + th:
                return i
        return -1

    def _hit_mini(self, i, x, y):
        """+1 / -1 for a press on a climate button of tile i, 0 otherwise."""
        tile = self.tiles[i]
        st = self.states.get(tile["entity"])
        if tile["domain"] != "climate" or not st or st.get("state") == "off":
            return 0
        tx, ty, tw, th = self.rects[i]
        zoom = render.BIG_ZOOM if self.form == "big" else 1.0
        local = QPointF((x - tx) / zoom, (y + self.scroll - ty) / zoom)
        if self.form == "small" and self.hover != i:
            return 0
        for rect, sign in render.mini_buttons(self.form, tw / zoom, th / zoom):
            if rect.contains(local):
                return sign
        return 0

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self._wake():
            self._press = None
            return
        x, y, px, py = self._point(e)
        i = self._tile_at(x, y)
        cursor = _cursor()
        if i < 0:
            self._press = {"tile": -1, "cursor": cursor, "drag": None, "moved": False, "pos": (px, py),
                           "button": self._button_at(x, y)}
            if not self.locked and not self._press["button"]:
                rect = _rect(self._hwnd)
                if rect:
                    self._press["drag"] = (rect[0], rect[1])
            return
        sign = self._hit_mini(i, x, y)
        self._press = {"tile": i, "cursor": cursor, "drag": None, "moved": False, "fired": False,
                       "mini": sign, "pos": (px, py)}
        if sign:
            return
        domain = self.tiles[i]["domain"]
        self.pressed = i
        self._invalidate_overlay()
        if has_hold(domain):
            self._hold.start(HOLD_MS)

    def _button_at(self, x, y):
        r = self.empty_button
        return bool(r and not self.tiles and r.contains(QPointF(x, y)))

    def _held(self):
        if self._press and self._press.get("tile", -1) >= 0 and not self._press.get("moved"):
            self._press["fired"] = True
            self.pressed = -1
            self._invalidate_overlay()
            self.facade.popover(self.tiles[self._press["tile"]])

    def mouseMoveEvent(self, e):
        x, y, px, py = self._point(e)
        if not e.buttons():
            self._wake()
            i = self._tile_at(x, y)
            if i != self.hover:
                old, self.hover = self.hover, i
                if any(j >= 0 and self.tiles[j]["domain"] == "climate" for j in (old, i)) and self.form == "small":
                    self._invalidate_overlay()
            return
        press = self._press
        if not press:
            return
        cx, cy = _cursor()
        dx, dy = cx - press["cursor"][0], cy - press["cursor"][1]
        if press["tile"] >= 0:
            if abs(dx) > HOLD_SLOP_PX or abs(dy) > HOLD_SLOP_PX:
                self._hold.stop()
            return
        if press.get("drag") is None:
            return
        if not press["moved"] and (dx * dx + dy * dy) ** 0.5 < DRAG_PX:
            return
        press["moved"] = True
        self.dragging = True
        ox, oy = press["drag"]
        self.api.move_window(ox + dx, oy + dy, self.kind)

    def mouseReleaseEvent(self, e):
        x, y, px, py = self._point(e)
        press, self._press = self._press, None
        self._hold.stop()
        if e.button() == Qt.RightButton:
            i = self._tile_at(x, y)
            if i >= 0:
                self.facade.popover(self.tiles[i])
            return
        if e.button() != Qt.LeftButton or not press:
            return
        if self.dragging:
            self.dragging = False
            self.sample_now.set()                 # a still glass takes the picture where it was dropped
        i = press["tile"]
        self.pressed = -1
        self._invalidate_overlay()
        if i < 0:
            if press.get("button") and self._button_at(x, y):
                threading.Thread(target=self.api.open_settings_window, daemon=True).start()
            return
        if i >= len(self.tiles) or press.get("fired"):
            return
        tile = self.tiles[i]
        if press.get("mini"):
            if self._tile_at(x, y) == i and self._hit_mini(i, x, y) == press["mini"]:
                self.facade.climate_step(tile, press["mini"])
            return
        if self._tile_at(x, y) != i:
            return                                # let go somewhere else: cancelled
        if render.is_readonly(tile["domain"]):
            return
        self.facade.quick_action(tile, i)

    def leaveEvent(self, e):
        self._hold.stop()
        if self.hover >= 0:
            self.hover = -1
            self._invalidate_overlay()
        if self.pressed >= 0:
            self.pressed = -1
            self._invalidate_overlay()

    def wheelEvent(self, e):
        if self.scroll_max <= 0:
            return
        step = -e.angleDelta().y() / 120.0 * WHEEL_STEP
        new = max(0.0, min(self.scroll + step, self.scroll_max))
        if new != self.scroll:
            self.scroll = new
            self._invalidate_overlay()

    def _invalidate_overlay(self):
        # The pointer, a scroll, a flash: what is dimmed does not show them, so the dimmed picture stays
        # (it is the one fading out when a touch wakes the widget, which must not stall to draw twice).
        self.overlay = None
        self.update()

    # ---- flashes of the momentary tiles -------------------------------------------
    def flash_tile(self, i):
        self.flash[i] = time.monotonic()
        self.flash_timer.start()

    def _step_flash(self):
        now = time.monotonic()
        self.flash = {i: t for i, t in self.flash.items() if now - t < 0.6}
        if not self.flash:
            self.flash_timer.stop()
        self._invalidate_overlay()



def has_hold(domain):
    """A press held on it opens the detail card: the devices with controls, and the read-only ones."""
    return render.has_detail_on_hold(domain) or render.is_readonly(domain)


class NativeWidget:
    """What main.py holds for a widget: the qtshell.Window's interface over a _Surface."""

    is_native_widget = True

    def __init__(self, api, widget_id):
        self.title = "HA Widgets"
        self.url = None
        self.js_api = api
        self.api = api
        self.widget_id = widget_id
        self.events = qtshell._Events()
        self._hidden = False
        self._native = _Surface(self, api, widget_id)
        self.actions = TileActions(api, lambda: self._native.states, self._native.optimistic)
        self._native.configure(api._prefs())
        render.set_language(self._native.language)

    # -- the window interface ---------------------------------------------------
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

    def refresh_display(self):
        qtshell._invoke(self._native, self._native.relayout)

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

    # -- what main.py sends to a page, as script, is taken here -----------------
    _CALLS = (
        (re.compile(r"__applyPrefs\((.*)\)\s*$", re.S), "_apply_prefs"),
        (re.compile(r"__haPushBatch\((.*)\)\s*$", re.S), "_push_states"),
        (re.compile(r"__setDimmed\((true|false)\)"), "_set_dim"),
        (re.compile(r"__widgetMoved\(\)"), "_moved"),
        (re.compile(r"__invalidateBackdrop\(\)"), "_invalidate"),
    )

    def evaluate_js(self, script):
        for pattern, name in self._CALLS:
            m = pattern.search(script)
            if m:
                try:
                    getattr(self, name)(m.group(1) if m.groups() else None)
                except Exception:
                    traceback.print_exc()
                return None
        return None

    def _apply_prefs(self, text):
        prefs = json.loads(text)
        qtshell._invoke(self._native, lambda: self._native.apply(prefs))

    def _push_states(self, text):
        items = json.loads(text)
        qtshell._invoke(self._native, lambda: self._native.push_states(items))

    def _set_dim(self, text):
        on = text == "true"
        qtshell._invoke(self._native, lambda: self._native.set_dim(on))

    def _moved(self, _):
        self._native.sample_now.set()

    def _invalidate(self, _=None):
        self.invalidate_backdrop()

    def invalidate_backdrop(self):
        self._native.force.set()
        self._native.sample_now.set()

    # -- actions -------------------------------------------------------------------
    def popover(self, tile):
        """The detail card over this tile (a page, in the popover window)."""
        surf = self._native
        rect = _rect(surf._hwnd)
        if not rect:
            return
        i = next((j for j, t in enumerate(surf.tiles) if t["id"] == tile["id"]), -1)
        if i < 0:
            return
        x, y, w, h = surf.rects[i]
        sx = rect[0] + round(x * surf.scale)
        sy = rect[1] + round((y - surf.scroll) * surf.scale)
        threading.Thread(target=self.api.open_popover, args=(
            tile["id"], sx, sy, round(w * surf.scale), round(h * surf.scale), self.api._widget_kind(self.widget_id)),
            daemon=True).start()

    def quick_action(self, tile, index):
        """What a tap does (nativeui.actions), with the guess shown at once."""
        self.actions.quick_action(tile, flash=lambda: self._native.flash_tile(index))

    def climate_step(self, tile, sign):
        self.actions.climate_step(tile, sign)

    # -- the first moments ------------------------------------------------------------
    def boot(self):
        """Once the window is up: the states, and the first run's settings."""
        if self.api._dimmed:                  # made while the others are dimmed: starts dimmed too
            self.run_on_ui_thread(lambda: self._native.set_dim(True))

        def go():
            try:
                states = self.api.fetch_initial_states()
                if states:
                    self.run_on_ui_thread(lambda: self._native.push_states(list(states.items())))
            except Exception:
                traceback.print_exc()
            try:
                self.api.ui_ready(self.api._widget_kind(self.widget_id))
            except Exception:
                pass
            dump = os.environ.get("HA_WIDGET_DUMP")        # a picture of the widget, for looking at it in tests
            if dump:
                time.sleep(float(os.environ.get("HA_WIDGET_DUMP_AFTER", "8")))
                self.run_on_ui_thread(lambda: self._native.grab().save(dump))
            cfg = self.api._cfg
            first = (cfg.get("widgets") or [{}])[0]
            if (first.get("id") == self.widget_id and not cfg.get("ha_token") and not self.api._all_tiles()):
                time.sleep(0.15)
                self.api.open_settings_window()
        threading.Thread(target=go, daemon=True).start()


def create_widget(api, widget):
    """A native desktop widget in place of a web window; same position rules as qtshell.create_window."""
    def make():
        win = NativeWidget(api, widget["id"])
        win._native.resize(*render.widget_size(widget["size"]))
        win._native.move(int(widget["x"]), int(widget["y"]))
        win._native.relayout()
        return win
    win = qtshell._invoke(None, make, wait=True)
    if win is None:
        raise RuntimeError("native widget could not be created")
    qtshell._windows.append(win)
    win.events.shown += win.boot
    return win
