"""What a desktop widget does for a widget written with the widget kit (widgetkit/): it holds the kit's runtime, draws it
over the card, hands it the pointer, the keyboard, the wheel and files dropped on it, and keeps its timers.

The window (`widget._Surface`) calls in here when what it shows is `wkind == "custom"`; the glass behind it, the dimming
and the window's place are the window's, as for every other kind (a widget of the kit never draws glass: it says in its
definition whether it covers the card, `WidgetDef.background`, and the window asks for the glass accordingly).
"""
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QKeySequence, QGuiApplication, QPainter

from winsys import qtshell

from . import render, style
from .ui import font, text_width

KEYS = {Qt.Key_Backspace: "Backspace", Qt.Key_Delete: "Delete", Qt.Key_Left: "Left", Qt.Key_Right: "Right",
        Qt.Key_Home: "Home", Qt.Key_End: "End", Qt.Key_Return: "Enter", Qt.Key_Enter: "Enter",
        Qt.Key_Escape: "Escape"}
WHEEL_PX = 40                     # what a notch of the wheel is to a widget's on_scroll
DRAG_PX = 5                       # a press that moves further than this on an empty place drags the window


def draw_missing(p, W, H, th):
    """A widget whose package is gone (or no longer loads): the card says so instead of staying blank."""
    render.draw_icon(p, "mdi:puzzle-remove-outline", th.ink2.name(), QRectF(W / 2 - 22, H / 2 - 44, 44, 44))
    size, weight, _ = style.TEXT["secondary"]
    f = font(size, weight)
    style.center_text(p, render.tr("這個 Widget 無法使用"), f, th.ink2, QRectF(0, H / 2 + 8, W, 28), align="line")


def paint(p, rt, size_key, theme, surface, dim=False):
    """The card and the widget at (0, 0) of `p`, in the widget's own units (the painter is scaled by the caller). `rt` is
    its runtime, or None when it cannot be had. `dim`: the widget as it looks in standby."""
    from widgetkit.theme import Theme, smooth
    W, H = render.widget_size(size_key)
    th = Theme(theme, surface, dim)
    render.draw_card_bg(p, W, H, th.tokens, surface, theme)
    if rt is None:
        draw_missing(p, W, H, th)
        return
    smooth(p)
    was, rt.standby, rt.ctx.standby = rt.standby, dim, dim            # a dimmed picture is drawn with the standby look
    rt.size_px = (W, H)
    try:
        rt.draw(p, th, W, H)
    finally:
        rt.standby, rt.ctx.standby = was, was


class CustomHost:
    def __init__(self, surface):
        self.s = surface
        self.rt = None
        self.pkg = None                         # the package the runtime was made for
        self.press = None
        self.missing = False                    # its package is gone or does not load

    # -- the runtime ---------------------------------------------------------------------------------------------------
    def runtime(self):
        """The widget's runtime, made on first use (and again when the copy is of another package); None when its package
        will not load."""
        s = self.s
        want = (s.custom or {}).get("widget")
        if self.rt is not None and self.pkg == want:
            return self.rt
        self.close()
        self.pkg = want
        self.missing = False
        rt = s.api.custom_runtime(s.widget_id, invalidate=s._schedule_redraw, on_focus=self._input_mode)
        if rt is None:
            self.missing = True
            return None
        rt.sv.gui = lambda fn: qtshell._invoke(s, fn)
        rt.size_px = tuple(render.widget_size(s.size_key))
        rt.standby = rt.ctx.standby = bool(s.dim_target)
        self.rt = rt
        QTimer.singleShot(0, rt.refresh_async)
        return rt

    def close(self):
        if self.rt is not None:
            rt, self.rt = self.rt, None
            rt.close()
        self.pkg = None

    def changed(self):
        """The preferences changed what this copy is (its package, its settings, what it was allowed, its size)."""
        s = self.s
        if self.rt is None:
            return
        if self.pkg != (s.custom or {}).get("widget"):
            self.close()
            return
        self.rt.size_px = tuple(render.widget_size(s.size_key))
        self.rt.set_config((s.custom or {}).get("config", {}))
        self.rt.refresh_async()

    # -- drawing -------------------------------------------------------------------------------------------------------
    def draw(self, p, dim):
        """The widget at (0, 0) of `p` (a picture of the window's size in device px), lit or dimmed."""
        s = self.s
        p.save()
        p.scale(s.scale, s.scale)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        rt = self.runtime()
        paint(p, rt, s.size_key, s.theme, s.style, dim)
        p.restore()
        if rt is not None and dim == bool(s.dim_target):          # (the picture that is on show decides when the next is due)
            wait = 16 if rt.animating else None if rt.redraw_in is None else max(16, int(rt.redraw_in * 1000))
            if wait is not None:
                QTimer.singleShot(wait, s._redraw_tiles)

    def wants_glass(self):
        rt = self.rt
        return True if rt is None else rt.needs_glass()

    # -- time ----------------------------------------------------------------------------------------------------------
    def tick_ms(self):
        """When to draw again by itself, or None: the widget's `tick` (or its `standby_tick` while dimmed)."""
        rt = self.runtime()
        if rt is None:
            return None
        seconds = rt.widget.standby_interval() if self.s.dim_target else rt.widget.tick
        return max(50, int(seconds * 1000)) if seconds else None

    def refresh(self):
        """Ask the widget's sources again (each answers only when it is due)."""
        rt = self.runtime()
        if rt is not None:
            rt.refresh_async()

    def set_standby(self, on):
        rt = self.rt
        if rt is not None:
            rt.set_standby(on)

    # -- the pointer -----------------------------------------------------------------------------------------------------
    def mouse_press(self, e):
        s = self.s
        if s._wake():
            self.press = None
            return
        x, y, px, py = s._point(e)
        rt = self.runtime()
        hit = rt.press(x, y) if rt is not None else None
        self.press = {"cursor": s_cursor(), "hit": hit, "moved": False, "origin": None}
        if hit is None and not s.locked:
            from .widget import _rect
            rect = _rect(s._hwnd)
            if rect:
                self.press["origin"] = (rect[0], rect[1])

    def mouse_move(self, e):
        s = self.s
        x, y, _, _ = s._point(e)
        rt = self.rt
        press = self.press
        if not e.buttons():
            s._wake()
            if rt is not None:
                rt.move(x, y)
            return
        if not press:
            return
        if press["origin"] is None:
            if rt is not None:
                rt.move(x, y)                                  # a drag the widget wanted (a slider, a card)
            return
        cx, cy = s_cursor()
        dx, dy = cx - press["cursor"][0], cy - press["cursor"][1]
        if not press["moved"] and (dx * dx + dy * dy) ** 0.5 < DRAG_PX:
            return
        press["moved"] = True
        s.dragging = True
        s.api.move_window(press["origin"][0] + dx, press["origin"][1] + dy, s.kind)

    def mouse_release(self, e):
        s = self.s
        x, y, _, _ = s._point(e)
        press, self.press = self.press, None
        if e.button() == Qt.RightButton:
            if self.rt is not None and self.rt.context(x, y):  # the widget has a use for it
                return
            import threading                                    # else the editor, on this widget
            wid = s.widget_id
            threading.Thread(target=lambda: s.api.open_widget_editor(wid), daemon=True).start()
            return
        if e.button() != Qt.LeftButton or not press:
            return
        if s.dragging:
            s.dragging = False
            s.sample_now.set()                                  # a still glass takes the picture where it was dropped
        if self.rt is not None:
            self.rt.release(x, y)

    def leave(self):
        if self.rt is not None:
            self.rt.leave()

    def wheel(self, e):
        rt = self.rt
        if rt is None:
            return False
        x, y, _, _ = self.s._point(e)
        return bool(rt.wheel(x, y, -e.angleDelta().y() / 120.0 * WHEEL_PX))

    # -- the keyboard and the input method -----------------------------------------------------------------------------------
    def _input_mode(self, on):
        """An input of the widget has the caret (on) or has lost it: the window takes focus, and gives it back."""
        s = self.s
        from winsys.windows import set_noactivate
        set_noactivate(s.facade, not on)
        if on:
            s.activateWindow()
            s.setFocus(Qt.OtherFocusReason)

    def wants_keyboard(self):
        return self.rt is not None and self.rt.wants_keyboard

    def key_press(self, e):
        rt = self.rt
        if not self.wants_keyboard():
            return False
        if e.matches(QKeySequence.Paste):
            rt.text(QGuiApplication.clipboard().text())
        elif e.key() in KEYS:
            rt.key(KEYS[e.key()])
        elif e.text() and not (e.modifiers() & (Qt.ControlModifier | Qt.AltModifier)):
            rt.text(e.text())
        return True

    def input_method(self, e):
        rt = self.rt
        if rt is None:
            return
        if e.commitString():
            rt.text(e.commitString())
        rt.set_preedit(e.preeditString())

    def input_query(self, query):
        """What the input method asks of the window: whether it is typing, and where (for its candidate window)."""
        rt, s = self.rt, self.s
        if query == Qt.ImEnabled:
            return self.wants_keyboard()
        if query == Qt.ImCursorRectangle and rt is not None:
            for rect, id in rt.ctx.hits.items:
                if id == rt.ctx.focus:
                    k = s.scale / (s.dpi or 1.0)
                    return QRectF(rect.left() * k, rect.top() * k, 2, rect.height() * k).toRect()
        return None

    def focus_out(self):
        if self.wants_keyboard():
            self.rt.blur()

    # -- files dropped on it -----------------------------------------------------------------------------------------------------
    @staticmethod
    def paths(e):
        import os
        return [os.path.normpath(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]

    def drag_move(self, e):
        s, rt = self.s, self.rt
        if rt is None:
            return False
        x, y, _, _ = s._point(e)
        return bool(rt.drag_move(x, y, self.paths(e)))

    def drag_leave(self):
        if self.rt is not None:
            self.rt.drag_leave()

    def drop(self, e):
        rt = self.rt
        if rt is None:
            return False
        x, y, _, _ = self.s._point(e)
        return bool(rt.drop(x, y, self.paths(e)))


def s_cursor():
    from .widget import _cursor
    return _cursor()
