"""A desktop widget, drawn natively: a QWidget painted with QPainter.

the Api holds a `NativeWidget` for each: the window's interface (hwnd, show, hide, dispose, events,
run_on_ui_thread, send) over a `_Surface`, with the Api behind it (states, preferences, service calls,
the detail card, the desktop capture and its exclusion, dimming, snapping). What the widget does
itself: draw the tiles, take the touches, ask for the glass.

Threads: the Qt widget lives on the GUI thread; the glass is made on its own thread from
what `Api.get_desktop_backdrop` answers, and only the newest picture ever reaches the GUI.
"""
import datetime
import os
import threading
import time
import traceback

from PySide6.QtCore import QElapsedTimer, QPointF, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtWidgets import QWidget

from core import diag
from winsys import qtshell

from . import kinds, render
from .actions import TileActions
from .customview import CustomHost
from .glass import GlassMixin
from .animation_clock import FrameTimer
from .widget_common import DETAIL_KINDS, DRAG_PX, EASE_DIM_MS, EASE_WAKE_MS, HOLD_MS, HOLD_SLOP_PX, SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOZORDER, _Signals, _cursor, _rect, _user32, has_hold
from .widget_input import SurfaceInput
from .widget_media import SurfaceMedia
from .widget_paint import SurfacePaint

class _Surface(SurfacePaint, SurfaceMedia, SurfaceInput, GlassMixin, QWidget):
    """The Qt window of one widget."""

    # Qt virtuals handled by SurfacePaint (taken by name here: Shiboken does not see an override in a plain mixin)
    paintEvent = SurfacePaint._qt_paintEvent


    # Qt virtuals handled by SurfaceInput (taken by name here: Shiboken does not see an override in a plain mixin)
    leaveEvent = SurfaceInput._qt_leaveEvent
    wheelEvent = SurfaceInput._qt_wheelEvent
    keyPressEvent = SurfaceInput._qt_keyPressEvent
    inputMethodEvent = SurfaceInput._qt_inputMethodEvent
    inputMethodQuery = SurfaceInput._qt_inputMethodQuery
    focusOutEvent = SurfaceInput._qt_focusOutEvent
    dragEnterEvent = SurfaceInput._qt_dragEnterEvent
    dragMoveEvent = SurfaceInput._qt_dragMoveEvent
    dragLeaveEvent = SurfaceInput._qt_dragLeaveEvent
    dropEvent = SurfaceInput._qt_dropEvent


    def __init__(self, facade, api, widget_id):
        super().__init__()
        self.facade, self.api, self.widget_id = facade, api, widget_id
        self.kind = "w:" + widget_id
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)                   # (a widget of the kit may take files; the others refuse them)
        self.setAttribute(Qt.WA_InputMethodEnabled, True)
        self.setFocusPolicy(Qt.StrongFocus)
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
        self.wkind = "tiles"                      # what it shows: tiles, weather, camera, chart
        self.clock_font = None                    # a clock's digits' font ({"file", "name"}; None: the default)
        self.custom = None                        # a widget of the kit: {"widget": package id, "config", "granted"}
        self.kit = CustomHost(self)               # ... and what runs it (nativeui/customview.py)
        self.extras, self._extras_at, self._fetching = {}, {}, set()
        self.extras_timer = QTimer(self)
        self.extras_timer.setInterval(5000)
        self.extras_timer.timeout.connect(self.refresh_extras)
        self.kind_buttons = []                    # a player's buttons: [(rect, action)]
        # a clock is drawn again on the minute, a playing song's place every second
        self.tick_timer = QTimer(self)
        self.tick_timer.setSingleShot(True)
        self.tick_timer.timeout.connect(self._tick)
        # a clock's ring of ticks follows the seconds: turned smoothly while it can be seen; while dimmed it
        # is still (every tick equally faint), while hidden it is not drawn. Only the ring is drawn each time (over the face, kept).
        self.second_timer = QTimer(self)
        self.second_timer.setSingleShot(True)
        self.second_timer.timeout.connect(self._second)
        self._drawn_minute = None
        self.scroll, self.scroll_max = 0.0, 0.0
        self.tcol = render.tokens("light")
        # What is drawn.
        self.overlay = self.overlay_dim = None
        self.mix = None
        self.init_glass()
        self.dim_t, self.dim_from, self.dim_target = 0.0, 0.0, False
        self._face_time, self._ahead = None, None      # the clock's next minute, drawn ahead (see _second)
        self.dim_clock = QElapsedTimer()
        self.dim_timer = FrameTimer(self)
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

    _cache_hwnd = cache_hwnd          # the name the Api uses

    def showEvent(self, e):
        super().showEvent(e)
        self.cache_hwnd()
        self.facade.events.showing.fire()
        if not self._shown_once:
            self._shown_once = True
            QTimer.singleShot(0, self._first_shown)
        self.sample_now.set()
        if self._gpu_receiver is not None:
            self._gpu_receiver.queue(foreground=True)
        self._schedule_tick()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.dim_timer.stop()
        self.dim_t = 1.0 if self.dim_target else 0.0
        if self._gpu_receiver is not None:
            self._gpu_receiver.hide()
        self.second_timer.stop()

    def _first_shown(self):
        self.facade.events.shown.fire()
        self.relayout()
        self._prepare_gpu_glass()
        self.start_glass()
        self.extras_timer.start()
        QTimer.singleShot(0, self.refresh_extras)

    def moveEvent(self, e):
        super().moveEvent(e)
        pos = e.pos()
        self.facade.events.moved.fire(pos.x(), pos.y())
        if self._gpu_receiver is not None:
            self._gpu_receiver.queue(foreground=True)
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
        wkind = mine.get("kind") if mine.get("kind") in kinds.KINDS + ("custom",) else "tiles"
        new = {
            # a widget of another kind holds only the devices it shows (the first weather, two sensors...)
            "tiles": mine["tiles"] if wkind == "tiles" else [] if wkind == "custom" else kinds.shown(wkind, mine["tiles"]),
            "custom": mine.get("custom") if wkind == "custom" else None,
            "wkind": wkind, "size_key": mine["size"], "zoom": prefs.get("zoom", 100),
            "theme_raw": prefs.get("theme", "auto"), "style": prefs.get("glass_style", "classic"),
            "language": prefs.get("language", "zh-TW"), "liquid_level": prefs.get("liquid_blur", 0),
            "sampling": prefs.get("glass_sampling", "live"), "locked": bool(prefs.get("lock_position")),
            "clock_font": mine.get("font") if wkind == "clock" else None,
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
            self.rebuild()

    def apply_prefs(self, prefs):
        changed = self.configure(prefs)
        if not changed:
            return
        render.set_language(self.language)
        if changed & {"tiles", "wkind", "custom"}:
            self.extras, self._extras_at = {}, {}
            if "custom" in changed:
                self.kit.changed()
            QTimer.singleShot(0, self.refresh_extras)
        if changed & {"size_key", "zoom", "tiles", "wkind"}:
            self.relayout()
        elif changed & {"theme_raw", "style", "language", "system_glass", "clock_font", "custom"}:
            self.rebuild()
        if changed & {"style", "liquid_level", "size_key", "zoom", "system_glass"}:
            self.reset_glass()
            self.facade.invalidate_backdrop()
        if "sampling" in changed:
            self.sample_now.set()
        self._prepare_gpu_glass()

    def relayout(self):
        """Size, scale and the tiles' places: after a change of size, zoom, tiles or monitor."""
        hwnd = self.cache_hwnd()
        self.dpi = (_user32.GetDpiForWindow(hwnd) / 96.0) if hwnd else (self.devicePixelRatioF() or 1.0)
        self.dpi = self.dpi or 1.0
        self.scale = max(0.5, min(2.0, self.zoom / 100.0)) * self.dpi
        cw, ch = render.widget_size(self.size_key)
        self.pw, self.ph = round(cw * self.scale), round(ch * self.scale)
        if self.wkind == "tiles":
            self.form, self.rects = render.tile_layout(self.size_key, len(self.tiles))
            self.scroll_max = render.scroll_range(self.size_key, len(self.tiles))
        else:                                    # one picture: no tiles to press, nothing to scroll
            self.form, self.rects, self.scroll_max = "small", [], 0.0
        self.scroll = max(0.0, min(self.scroll, self.scroll_max))
        if hwnd:
            _user32.SetWindowPos(hwnd, None, 0, 0, self.pw, self.ph, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE)
        self.fit_glass()
        self.rebuild()
        self.facade.invalidate_backdrop()             # the tiles may have moved: the liquid glass blurs behind each

    def rebuild(self):
        self.theme = self._resolve_theme()
        self.tcol = render.tokens(self.theme, False, self.style)
        render.set_language(self.language)
        self.overlay = self.overlay_dim = None
        self._prepare_gpu_glass()
        self.update()

    def _prepare_gpu_glass(self):
        from .widget_glass import prepare
        prepare(self)

    def _gpu_window_rect(self):
        return _rect(self.cache_hwnd())

    def _gpu_foreground_image(self):
        # The native foreground remains the source of all words, icons and
        # controls. Only its final blend with the glass is moved to the GPU.
        return self._paint_image(gpu_snapshot=False)

    def _gpu_foreground_layers(self):
        previous = self.dim_t
        try:
            receiver = self._gpu_receiver
            lit = getattr(receiver, 'foreground_image', None)
            # At rest only the dim face is visible. Clock/state updates need
            # not paint the hidden solid face too. A wake regenerates it before
            # the first blended frame, including all states received at rest.
            if not (self.dim_target and previous == 1.0 and lit is not None
                    and lit.width() == self.pw and lit.height() == self.ph):
                self.dim_t = 0.0
                lit = self._gpu_foreground_image()
                if receiver is not None:
                    receiver.lit_stale = False
            elif receiver is not None:
                receiver.lit_stale = True
            self.dim_t = 1.0
            dim = self._gpu_foreground_image()
            return lit, dim
        finally:
            self.dim_t = previous

    def _gpu_card_mask(self, hidden_tile=None):
        hole = self._tile_path(hidden_tile) if hidden_tile is not None else self._transition_hole()
        key = (self.pw, self.ph, self.glass_card()[2] * self.scale, self.dpi)
        if hole is None and getattr(self, "_card_mask_made", (None,))[0] == key:
            return self._card_mask_made[1]
        image = QImage(self.pw, self.ph, QImage.Format_ARGB32)
        image.fill(0)
        p = QPainter(image)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(Qt.white)
        p.drawPath(render.squircle(0, 0, self.pw, self.ph, self.glass_card()[2] * self.scale))
        if hole is not None:
            p.scale(self.dpi, self.dpi)
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.drawPath(hole)
        p.end()
        if hole is None:
            self._card_mask_made = (key, image)
        return image

    def _ui(self):
        now = time.monotonic()
        flash = {i: max(0.0, 1 - (now - t) / 0.6) for i, t in self.flash.items()}
        return {"hover": self.hover, "pressed": self.pressed, "flash": flash, "scroll": self.scroll}

    def widget_moved(self):
        """Moved (Api._on_widget_moved): a still glass takes its picture again."""
        self.sample_now.set()

    # ---- the states -----------------------------------------------------------
    def push_states(self, items):
        for entity, state in items:
            self.states[entity] = state
        if self.wkind == "media" and self.tiles and any(e == self.tiles[0]["entity"] for e, _ in items):
            QTimer.singleShot(0, self.refresh_extras)    # a new song: its cover
        self._schedule_redraw()

    def _schedule_redraw(self):
        if not self._redraw_pending:
            self._redraw_pending = True
            self.signals.states.emit()

    def _redraw_tiles(self):
        self._redraw_pending = False
        self.overlay = self.overlay_dim = None
        self.update()
        self._schedule_tick()

    def wants_glass(self):
        """The tiles and a chart stand on glass; a clock, a calendar, the weather, a camera and a player have a
        solid face of their own, and want the desktop's picture only while dimmed (clear glass then) or when
        they are empty (the bare card)."""
        if self.wkind == "custom":                 # as it says: glass, or a face of its own (and glass again when dimmed)
            return self.dim_target or self.dim_t > 0 or self.kit.wants_glass()
        if self.wkind in ("tiles", "chart") or self.dim_target or self.dim_t > 0:
            return True
        return self.wkind not in kinds.NO_DEVICES and not kinds.shown(self.wkind, self.tiles)

    def _schedule_tick(self):
        if self.wkind == "custom":
            ms = self.kit.tick_ms() if self.isVisible() else None
            if ms is None:
                self.tick_timer.stop()
            else:
                self.tick_timer.start(ms)
            return
        if self.wkind == "clock":
            self.tick_timer.stop()
            if self.isVisible():
                self._warm_next_minute(datetime.datetime.now())      # (dimmed, the clock is only woken at :58 and :00)
                self._next_second()
            return
        if self.wkind == "calendar":
            ms = (60 - time.time() % 60) * 1000 + 30
        elif self.wkind == "media" and self.tiles and not self.dim_target and \
                (self.states.get(self.tiles[0]["entity"]) or {}).get("state") == "playing":
            ms = 1000
        else:
            return
        self.tick_timer.start(int(ms))

    def _tick(self):
        if self.isVisible():
            self._redraw_tiles()
        else:
            self._schedule_tick()

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
        self.kit.set_standby(on)
        if self._gpu_receiver is not None:
            receiver = self._gpu_receiver
            receiver.queue(foreground=(not receiver.visible or self.wkind == 'clock'
                                       or getattr(receiver, 'lit_stale', False)))
        self.dim_from = self.dim_t
        self.dim_clock.start()
        receiver = self._gpu_receiver
        self.dim_timer.vsync = receiver is not None
        clock = receiver.clock if receiver is not None else None
        if self.dim_timer.shared_clock is not clock:
            self.dim_timer.stop()
        if receiver is not None and receiver.clock is not None:
            self.dim_timer.vsync_waiter = receiver.clock.timer.vsync_waiter
            self.dim_timer.shared_clock = receiver.clock
        else:
            self.dim_timer.shared_clock = None
        self.dim_timer.setInterval(max(1, round(1000 / self._glass_refresh_rate)))
        self.dim_timer.start()
        if on:
            self.sample_now.set()                 # a solid face turning to glass: a picture of the desktop now
        if on and self.wkind == "media":
            self.tick_timer.stop()                # dimmed, a song's place is not drawn again each second
        elif on and self.wkind == "clock":
            self._schedule_tick()                 # dimmed, the clock's ring is still: only its minute is looked after
        elif not on:
            self._schedule_tick()
            QTimer.singleShot(0, self.refresh_extras)
        if self.wkind == "custom":
            self._schedule_tick()                 # dimmed or lit, at the pace the widget asked for

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
        if self._gpu_receiver is not None and self._gpu_receiver.visible:
            self._gpu_receiver.queue()
        else:
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

    def mousePressEvent(self, e):
        if self.wkind == "custom":
            if e.button() == Qt.LeftButton:
                self.kit.mouse_press(e)
            return
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
                           "button": self._button_at(x, y), "action": self._action_at(x, y)}
            if not self.locked and not self._press["button"] and not self._press["action"]:
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

    def mouseMoveEvent(self, e):
        if self.wkind == "custom":
            self.kit.mouse_move(e)
            return
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
        if press.get("action") == "seek":
            self._seek_to(x)
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
        if self.wkind == "custom":
            self.kit.mouse_release(e)
            return
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
        moved = self.dragging or press.get("moved")
        if self.dragging:
            self.dragging = False
            self.sample_now.set()                 # a still glass takes the picture where it was dropped
        i = press["tile"]
        self.pressed = -1
        self._invalidate_overlay()
        if i < 0:
            if press.get("button") and self._button_at(x, y) and not moved:
                wid = self.widget_id              # an empty widget: the editor, on it
                threading.Thread(target=lambda: self.api.open_widget_editor(wid), daemon=True).start()
            elif press.get("action") == "seek" and self.tiles:
                at = self._seek_to(x)
                self.extras.pop("seek_to", None)
                if at is not None:
                    self._seek(at)
            elif press.get("action") and self.tiles and not moved:
                self._play(press["action"])
            elif self.wkind in DETAIL_KINDS and self.tiles and not moved:
                self.facade.popover(self.tiles[0])        # a weather, a camera, a chart: its detail
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
        if self.form == "bar":
            tx, ty, tw, th = self.rects[i]
            if not render.bar_icon_rect(tw, th).contains(QPointF(x - tx, y + self.scroll - ty)):
                self.facade.popover(tile)
                return
        if render.is_readonly(tile["domain"]):
            if self.form == "bar":
                self.facade.popover(tile)
            return
        self.facade.quick_action(tile, i)

    def stop(self):
        self.kit.close()
        super().stop()

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



class NativeWidget:
    """What the Api holds for a widget: the window's interface (as NativeOverlay's) over a _Surface."""

    is_native_widget = True

    def __init__(self, api, widget_id):
        self.title = "HA Widgets"
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

    def send(self, name, *args):
        """Call the window's `name` with `args` on the GUI thread, without waiting for it. What the Api
        tells every window (the preferences, new states, ...), so one a window has no use for is ignored."""
        method = getattr(self._native, name, None)
        if method is not None:
            qtshell._invoke(self._native, lambda: method(*args))

    def invalidate_backdrop(self):
        self._native.force.set()
        self._native.sample_now.set()

    # -- actions -------------------------------------------------------------------
    def popover(self, tile):
        """The detail card over this tile."""
        surf = self._native
        rect = _rect(surf._hwnd)
        if not rect:
            return
        i = next((j for j, t in enumerate(surf.tiles) if t["id"] == tile["id"]), -1)
        if i < 0:
            return
        if i < len(surf.rects):
            x, y, w, h = surf.rects[i]
        else:                                    # a widget of one picture: the card itself
            (w, h), x, y = render.widget_size(surf.size_key), 0, surf.scroll
        sx = rect[0] + round(x * surf.scale)
        sy = rect[1] + round((y - surf.scroll) * surf.scale)
        source_image = surf.transition_image(tile["id"])
        if source_image is None:
            source_image = surf.grab().toImage().copy(round(x * surf.scale), round((y - surf.scroll) * surf.scale),
                                                    round(w * surf.scale), round(h * surf.scale))
        threading.Thread(target=self.api.open_popover, args=(
            tile["id"], sx, sy, round(w * surf.scale), round(h * surf.scale), self.api._widget_kind(self.widget_id), source_image),
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
                diag.note("telling the program a widget is ready")
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
    """A desktop widget, placed where the config says (physical pixels; the Api puts it there again once shown)."""
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
