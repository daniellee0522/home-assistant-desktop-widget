"""A small retained-mode toolkit for the natively drawn windows (the detail card, the tray panel).

Views are placed in CSS pixels, as the stylesheet's numbers are, and painted by one QWidget (a Scene)
scaled to the screen; text is drawn as outlines like the widget's. A Scene is also where the mouse is
routed, where things are animated, and where the glass behind the card is made (glass.py).

Only what the two screens need: labels, capsule and round buttons, icons, sliders, scrolling boxes,
tiles, a chart, and a text field (a real line editor laid over the scene).
"""
import math
import re
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QBrush, QColor, QCursor, QFont, QFontMetricsF, QGuiApplication, QImage,
                           QLinearGradient, QPainter, QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import QLineEdit, QWidget

from . import render
from .glass import GlassMixin

# ---------------------------------------------------------------------------------------
# colours
# ---------------------------------------------------------------------------------------

INK = {
    "light": {"ink1": "#1d1d1f", "ink2": "#4d4d55", "btn_fill": (0, 0, 0, 0.08), "btn_fill_strong": (0, 0, 0, 0.14),
              "btn_text": "#1d1d1f", "input_bg": (255, 255, 255, 0.6), "input_border": (0, 0, 0, 0.12),
              "panel_solid": "#d6e4f1", "scrollbar": (0, 0, 0, 0.18)},
    "dark": {"ink1": "#f5f5f7", "ink2": "#b6b6bb", "btn_fill": (255, 255, 255, 0.12),
             "btn_fill_strong": (255, 255, 255, 0.2), "btn_text": "#f5f5f7", "input_bg": (0, 0, 0, 0.25),
             "input_border": (255, 255, 255, 0.14), "panel_solid": "#1c1f25", "scrollbar": (255, 255, 255, 0.2)},
}
LIQUID_INK = {"light": {"ink1": "#16222e", "ink2": "#405566"}, "dark": {"ink1": "#f7fcff", "ink2": "#d7eaf1"}}


def ui_tokens(theme, style="classic", dim=False):
    """Every colour a screen uses, by name: the widget's tile tokens (render.tokens) and the screens' own."""
    t = render.tokens(theme, dim, style)
    t.update(INK[theme])
    if style == "liquid":
        t.update(LIQUID_INK[theme])
    t["white"] = "#ffffff"
    t["accent_blue"] = render.ACCENT["blue"]
    t["accent_green"] = render.ACCENT["green"]
    t["accent_red"] = render.ACCENT["red"]
    t["accent_teal"] = render.ACCENT["teal"]
    t["accent_cyan"] = render.ACCENT["cyan"]
    t["accent_yellow"] = render.ACCENT["yellow"]
    return t


# ---------------------------------------------------------------------------------------
# fonts and text
# ---------------------------------------------------------------------------------------

_fonts = {}


def font(px, weight=QFont.Normal, spacing=0.0):
    key = (px, int(getattr(weight, "value", weight)), spacing)
    f = _fonts.get(key)
    if f is None:
        f = _fonts[key] = render.font(px, weight, spacing)
    return f


def text_width(text, f):
    return QFontMetricsF(f).horizontalAdvance(text) / 10 * render.HSCALE


_NO_LINE_START = set("。，、；：！？）」』〉》】,.;:!?)")


def wrap_lines(text, f, width, any_break=False):
    """`text` broken into lines no wider than `width`: at spaces (or anywhere, for a long unbroken
    string), and between CJK characters."""
    fm = QFontMetricsF(f)
    lines = []
    for para in str(text).split("\n"):
        cur = ""
        tokens = re.findall(r"\s+|[(\[]*[A-Za-z0-9_.,'\-:/]+[)\]!?;%]*|.", para) if not any_break else list(para)
        for token in tokens:
            trial = cur + token
            if cur and fm.horizontalAdvance(trial.rstrip()) / 10 * render.HSCALE > width:
                if token in _NO_LINE_START and len(cur.rstrip()) > 1:
                    # A line never starts with a closing mark: the character before it goes down with it.
                    cur = cur.rstrip()
                    lines.append(cur[:-1])
                    cur = cur[-1] + token
                    continue
                lines.append(cur.rstrip())
                cur = token.lstrip()
            else:
                cur = trial
        lines.append(cur.rstrip())
    return lines or [""]


def ellipsize(text, f, width):
    if text_width(text, f) <= width:
        return text
    while text and text_width(text + "…", f) > width:
        text = text[:-1]
    return text + "…"


def resolve(scene, color):
    """A colour as a QColor: a token name ('ink1'), a CSS colour, an rgba tuple, or a QColor."""
    if color is None:
        return QColor(0, 0, 0, 0)
    if isinstance(color, str) and color in scene.t:
        color = scene.t[color]
    return render.parse_color(color)


# ---------------------------------------------------------------------------------------
# views
# ---------------------------------------------------------------------------------------

class Ev:
    """A pointer event: x, y in the receiving view; gx, gy in the scene (CSS px)."""

    def __init__(self, x, y, gx, gy, button=Qt.NoButton, buttons=Qt.NoButton):
        self.x, self.y, self.gx, self.gy, self.button, self.buttons = x, y, gx, gy, button, buttons


class View:
    cursor = None                       # a Qt.CursorShape while the pointer is over it

    def __init__(self, x=0.0, y=0.0, w=0.0, h=0.0):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.children, self.parent, self.scene = [], None, None
        self.visible = True
        self.alpha = 1.0
        self.dx = self.dy = 0.0         # offsets that animate, on top of x, y
        self.zoom = 1.0                 # about the view's centre
        self.scale = 1.0                # its content drawn this much larger, from its top-left: one of its
                                        # own px is `scale` of its parent's (w and h are its own px)
        self.blur = 0.0                 # CSS px; drawn through an offscreen picture while above 0
        self.clip = False
        self.radius = None              # a squircle clip when set (with clip)
        self.on_press = self.on_release = self.on_move = self.on_click = None
        self.on_enter = self.on_leave = self.on_wheel = self.on_dblclick = None
        self.interactive = False        # takes the pointer (otherwise the pointer goes through)
        self.hovered = self.pressed = False
        self.no_hit = False             # the pointer goes through it (a layer that is out of sight)
        self.lifted = False

    # -- tree ------------------------------------------------------------------------
    def add(self, *views):
        for v in views:
            if v.parent is not None:
                v.parent.children.remove(v)
            v.parent = self
            self.children.append(v)
            v._adopt(self.scene)
        self.changed()
        return views[0] if len(views) == 1 else views

    def _adopt(self, scene):
        self.scene = scene
        for c in self.children:
            c._adopt(scene)

    def remove(self, *views):
        for v in views:
            if v in self.children:
                self.children.remove(v)
                v.parent = None
                scene = v.scene
                v._adopt(None)
                if scene is not None:
                    scene.fields[:] = [f for f in scene.fields if f.edit is not None]
        self.changed()

    def clear(self):
        self.remove(*list(self.children))

    def changed(self):
        if self.scene:
            self.scene.request_paint()

    def in_scene(self):
        """(x, y, k): the view's top-left in the scene, and how many scene px one of its own px is
        (every offset and scale on the way up undone; zoom, which only animates, is not)."""
        if self.parent is None:
            px, py, pk = 0.0, 0.0, 1.0
        else:
            px, py, pk = self.parent.in_scene()
        return px + pk * (self.x + self.dx), py + pk * (self.y + self.dy), pk * self.scale

    def abs_pos(self):
        """The view's top-left in the scene."""
        x, y, _ = self.in_scene()
        return x, y

    # -- painting -----------------------------------------------------------------------
    def paint(self, p):
        pass

    def paint_tree(self, p):
        if not self.visible or self.alpha <= 0:
            return
        if self.blur > 0.5 and self.scene is not None:
            self.scene.paint_blurred(self, p)
            return
        p.save()
        p.translate(self.x + self.dx, self.y + self.dy)
        if self.zoom != 1.0:
            p.translate(self.w / 2, self.h / 2)
            p.scale(self.zoom, self.zoom)
            p.translate(-self.w / 2, -self.h / 2)
        if self.scale != 1.0:
            p.scale(self.scale, self.scale)
        if self.alpha < 1.0:
            p.setOpacity(p.opacity() * self.alpha)
        if self.clip:
            if self.radius:
                p.setClipPath(render.squircle(0, 0, self.w, self.h, self.radius))
            else:
                p.setClipRect(QRectF(0, 0, self.w, self.h))
        self.paint(p)
        for c in self.children:
            c.paint_tree(p)
        p.restore()

    # -- the pointer ----------------------------------------------------------------------
    def contains(self, x, y):
        return 0 <= x < self.w and 0 <= y < self.h

    def hit(self, x, y):
        """The deepest interactive view at (x, y) in this view's own space, or None."""
        if not self.visible or self.alpha <= 0 or self.no_hit:
            return None
        lx, ly = x - self.x - self.dx, y - self.y - self.dy
        if self.zoom != 1.0:
            lx = (lx - self.w / 2) / self.zoom + self.w / 2
            ly = (ly - self.h / 2) / self.zoom + self.h / 2
        if self.scale != 1.0:
            lx, ly = lx / self.scale, ly / self.scale
        if self.clip and not self.contains(lx, ly):
            return None
        for c in reversed(self.children):
            got = c.hit(lx, ly)
            if got is not None:
                return got
        if self.interactive and self.contains(lx, ly):
            return self
        return None

    def to_local(self, gx, gy):
        x, y, k = self.in_scene()
        return (gx - x) / k, (gy - y) / k

    # -- animation ------------------------------------------------------------------------
    def animate(self, ms=200, ease="out", done=None, **props):
        if self.scene is None:
            for k, v in props.items():
                setattr(self, k, v)
            if done:
                done()
            return
        self.scene.tweens.animate(self, props, ms, ease, done)

    def stop_animation(self):
        if self.scene:
            self.scene.tweens.cancel(self)


class Rect(View):
    """A filled shape: a rounded rectangle, a capsule, a circle, a squircle."""

    def __init__(self, x=0, y=0, w=0, h=0, fill=None, radius=0, ring=None, ring_width=1, shape="round"):
        super().__init__(x, y, w, h)
        self.fill, self.radius_, self.ring, self.ring_width, self.shape = fill, radius, ring, ring_width, shape

    def path(self):
        if self.shape == "squircle":
            return render.squircle(0, 0, self.w, self.h, self.radius_)
        path = QPainterPath()
        r = self.h / 2 if self.radius_ == "full" else self.radius_
        path.addRoundedRect(QRectF(0, 0, self.w, self.h), r, r)
        return path

    def paint(self, p):
        if self.fill is None and self.ring is None:
            return
        path = self.path()
        if self.fill is not None:
            p.setPen(Qt.NoPen)
            p.setBrush(resolve(self.scene, self.fill))
            p.drawPath(path)
        if self.ring is not None:
            p.setPen(QPen(resolve(self.scene, self.ring), self.ring_width))
            p.setBrush(Qt.NoBrush)
            inset = self.ring_width / 2
            ring_path = QPainterPath()
            r = self.h / 2 if self.radius_ == "full" else self.radius_
            ring_path.addRoundedRect(QRectF(inset, inset, self.w - 2 * inset, self.h - 2 * inset), r, r)
            p.drawPath(ring_path)


class Label(View):
    """Text: one line (clipped, faded or ellipsised) or wrapped to its width."""

    def __init__(self, text="", size=14, weight=QFont.Normal, color="ink1", x=0, y=0, w=0, align="l",
                 lh=1.2, wrap=False, overflow="clip", spacing=0.0, any_break=False, opacity=1.0):
        super().__init__(x, y, w, 0)
        self._text, self.size, self.weight, self.color = text, size, weight, color
        self.align, self.lh, self.wrap, self.overflow, self.spacing = align, lh, wrap, overflow, spacing
        self.any_break = any_break
        self.text_alpha = opacity
        self._paths = None
        self._lines = None
        self.fit_width = w == 0
        self.measure()

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        if value != self._text:
            self._text = value
            self.measure()

    def font(self):
        return font(self.size, self.weight, self.spacing)

    def set_width(self, w):
        self.w = w
        self.fit_width = False
        self.measure()

    def measure(self):
        f = self.font()
        text = render.tr(self._text) if self._text else ""
        if self.wrap and self.w > 0:
            self._lines = wrap_lines(text, f, self.w, self.any_break)
        else:
            self._lines = [text]
            if self.fit_width:
                self.w = text_width(text, f)
        self.h = len(self._lines) * self.lh * self.size
        self._paths = None
        self.changed()

    def line_width(self, i=0):
        return text_width(self._lines[i], self.font())

    def paint(self, p):
        if not self._lines or not any(self._lines):
            return
        f = self.font()
        fm = QFontMetricsF(f)
        lh = self.lh * self.size
        col = resolve(self.scene, self.color)
        if self.text_alpha < 1:
            col.setAlphaF(col.alphaF() * self.text_alpha)
        if self._paths is None:
            self._paths = []
            for i, line in enumerate(self._lines):
                if self.overflow == "ellipsis" and not self.wrap:
                    line = ellipsize(line, f, self.w)
                lw = text_width(line, f)
                x = 0 if self.align == "l" else (self.w - lw) / 2 if self.align == "c" else self.w - lw
                base = i * lh + (lh - fm.height() / 10) / 2 + fm.ascent() / 10
                self._paths.append((render.text_path(QPointF(0, 0), f, line, x, base), lw))
        brush = QBrush(col)
        if self.overflow == "fade" and not self.wrap and self._paths[0][1] > self.w - 16 and self.w > 16:
            g = QLinearGradient(0, 0, self.w, 0)
            g.setColorAt(0, col)
            g.setColorAt(max(0.0, (self.w - 16) / self.w), col)
            clear = QColor(col)
            clear.setAlpha(0)
            g.setColorAt(1, clear)
            brush = QBrush(g)
        p.setPen(Qt.NoPen)
        p.setBrush(brush)
        if self.overflow in ("fade", "clip") and not self.wrap:
            p.save()
            p.setClipRect(QRectF(0, -2, self.w, self.h + 4))
        for path, _ in self._paths:
            p.drawPath(path)
        if self.overflow in ("fade", "clip") and not self.wrap:
            p.restore()

    def invalidate(self):
        self._paths = None
        self.changed()


class IconView(View):
    def __init__(self, name, color="ink1", x=0, y=0, size=24):
        super().__init__(x, y, size, size)
        self.name, self.color = name, color

    def paint(self, p):
        c = resolve(self.scene, self.color)
        render.draw_icon(p, self.name, (c.red(), c.green(), c.blue(), c.alphaF()), QRectF(0, 0, self.w, self.h))


class Button(View):
    """A capsule or round button: a fill that darkens on hover, a label or an icon, shrinks a little when pressed."""
    cursor = Qt.PointingHandCursor

    def __init__(self, text="", x=0, y=0, w=0, h=0, size=14, weight=QFont.Bold, color="btn_text", fill="btn_fill",
                 hover_fill="btn_fill_strong", radius="full", icon=None, icon_size=18, pad=0, on_click=None,
                 active=False, active_fill="accent_blue", active_color="white", ring=None, shape="round"):
        super().__init__(x, y, w, h)
        self.interactive = True
        self.text, self.size, self.weight, self.color = text, size, weight, color
        self.fill, self.hover_fill, self.radius_, self.icon, self.icon_size = fill, hover_fill, radius, icon, icon_size
        self.active, self.active_fill, self.active_color, self.ring, self.shape = active, active_fill, active_color, ring, shape
        self.on_click = on_click
        self.pad = pad
        self.label = None
        if text and w == 0:
            self.w = text_width(render.tr(text), font(size, weight)) + 2 * pad
        self.on_enter = lambda e: self._hover(True)
        self.on_leave = lambda e: self._hover(False)
        self.on_press = lambda e: self._press(True)
        self.on_release = lambda e: self._press(False)

    def _hover(self, on):
        self.hovered = on
        self.changed()

    def _press(self, on):
        self.pressed = on
        self.zoom = 0.96 if on else 1.0
        self.changed()
        return True

    def paint(self, p):
        fill = self.active_fill if self.active else (self.hover_fill if self.hovered else self.fill)
        shape = Rect(0, 0, self.w, self.h, fill, self.radius_, self.ring, shape=self.shape)
        shape.scene = self.scene
        shape.paint(p)
        color = self.active_color if self.active else self.color
        if self.icon:
            c = resolve(self.scene, color)
            render.draw_icon(p, self.icon, (c.red(), c.green(), c.blue(), c.alphaF()),
                             QRectF((self.w - self.icon_size) / 2, (self.h - self.icon_size) / 2,
                                    self.icon_size, self.icon_size))
        elif self.text:
            f = font(self.size, self.weight)
            fm = QFontMetricsF(f)
            tw = text_width(render.tr(self.text), f)
            base = (self.h - fm.height() / 10) / 2 + fm.ascent() / 10
            p.setPen(Qt.NoPen)
            p.setBrush(resolve(self.scene, color))
            left = 10 if getattr(self, "align_left", False) else (self.w - tw) / 2
            p.drawPath(render.text_path(QPointF(0, 0), f, render.tr(self.text), left, base))


class Slider(View):
    """A range input: an 8 px track and a round white thumb; `on_input` while dragging, `on_commit` on release."""
    cursor = Qt.PointingHandCursor

    def __init__(self, x, y, w, value, lo, hi, step=1, on_input=None, on_commit=None):
        super().__init__(x, y, w, 22)
        self.interactive = True
        self.value, self.lo, self.hi, self.step = value, lo, hi, step
        self.on_input_, self.on_commit = on_input, on_commit
        self.dragging = False
        self.on_press = self._press
        self.on_move = self._move
        self.on_release = self._release

    def _set_from(self, x):
        t = max(0.0, min(1.0, (x - 11) / max(1, self.w - 22)))
        v = self.lo + t * (self.hi - self.lo)
        v = round(v / self.step) * self.step
        v = max(self.lo, min(self.hi, v))
        if v != self.value:
            self.value = v
            if self.on_input_:
                self.on_input_(v)
            self.changed()

    def _press(self, e):
        self.dragging = True
        self.scene.capture = self
        self._set_from(e.x)
        return True

    def _move(self, e):
        if self.dragging:
            self._set_from(e.x)
        return True

    def _release(self, e):
        if self.dragging:
            self.dragging = False
            if self.on_commit:
                self.on_commit(self.value)
        return True

    def paint(self, p):
        track = QRectF(0, (self.h - 8) / 2, self.w, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(resolve(self.scene, "btn_fill"))
        p.drawRoundedRect(track, 4, 4)
        t = (self.value - self.lo) / max(1e-9, self.hi - self.lo)
        cx = 11 + t * (self.w - 22)
        p.setBrush(QColor(0, 0, 0, 70))
        p.drawEllipse(QPointF(cx, self.h / 2 + 1.5), 11, 11)
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QPointF(cx, self.h / 2), 11, 11)


class ScrollView(View):
    """A clipped box whose content scrolls: the wheel, and scroll_to; no scroll bars."""

    def __init__(self, x, y, w, h, horizontal=False, fade=0):
        super().__init__(x, y, w, h)
        self.clip = True
        self.content = View(0, 0, w, h)
        self.horizontal = horizontal
        self.fade = fade
        self.offset = 0.0
        super().add(self.content)
        self.on_wheel = self._wheel
        self.interactive = True

    def add(self, *views):
        return self.content.add(*views)

    def clear(self):
        self.content.clear()

    def extent(self):
        """How long the content is along the scrolling axis."""
        return self.content.w if self.horizontal else self.content.h

    def max_offset(self):
        return max(0.0, self.extent() - (self.w if self.horizontal else self.h))

    def scroll_to(self, offset):
        self.offset = max(0.0, min(self.max_offset(), offset))
        if self.horizontal:
            self.content.dx = -self.offset
        else:
            self.content.dy = -self.offset
        self.changed()

    def _wheel(self, e, delta):
        if self.max_offset() <= 0:
            return False
        self.scroll_to(self.offset - delta / 120.0 * 100)
        return True

    def paint_tree(self, p):
        if self.fade and self.visible:
            self.scene.paint_faded(self, p)
        else:
            super().paint_tree(p)


class TextField(View):
    """A line of text to edit: a real QLineEdit laid over the scene where this view is."""

    def __init__(self, x, y, w, h, text="", placeholder="", size=15, on_done=None, max_length=40, fill="input_bg",
                 ring="input_border", radius=18, password=False, on_change=None):
        super().__init__(x, y, w, h)
        self.text, self.placeholder, self.size, self.on_done, self.max_length = text, placeholder, size, on_done, max_length
        self.fill, self.ring, self.radius_ = fill, ring, radius
        self.password, self.on_change = password, on_change
        self.edit = None

    def _adopt(self, scene):
        super()._adopt(scene)
        if scene is not None and self.edit is None:
            self.edit = QLineEdit(scene)
            self.edit.setMaxLength(self.max_length)
            self.edit.setText(self.text)
            self.edit.setFrame(False)
            self.edit.editingFinished.connect(self._finished)
            if self.password:
                self.edit.setEchoMode(QLineEdit.Password)
            if self.on_change:
                self.edit.textChanged.connect(lambda t: self.on_change(t))
            scene.fields.append(self)
            self.restyle()
        elif scene is None and self.edit is not None:
            self.edit.hide()
            self.edit.deleteLater()
            self.edit = None

    def restyle(self):
        if self.edit is None or self.scene is None:
            return
        s = self.scene.scale / self.scene.devicePixelRatioF() * self.in_scene()[2]
        ink = resolve(self.scene, "ink1").name()
        f = font(self.size, QFont.Normal)
        qf = QFont(f)
        qf.setPixelSize(max(6, round(self.size * s)))
        qf.setStyleStrategy(QFont.PreferAntialias)
        self.edit.setFont(qf)
        self.edit.setPlaceholderText(render.tr(self.placeholder))
        self.edit.setStyleSheet("QLineEdit { background: transparent; border: none; color: %s; "
                                "selection-background-color: #409cff; selection-color: white; }" % ink)

    def place(self):
        """Where the editor goes: this view's rectangle in the window, if it is showing."""
        if self.edit is None:
            return
        shown = self.visible_in_scene()
        if shown:
            x, y, k = self.in_scene()
            s = self.scene.scale / self.scene.devicePixelRatioF()
            pad = 12 * k
            self.edit.setGeometry(round((x + pad) * s), round(y * s), round((self.w * k - 2 * pad) * s),
                                  round(self.h * k * s))
        self.edit.setVisible(shown)

    def visible_in_scene(self):
        v = self
        while v is not None:
            if not v.visible or v.alpha <= 0:
                return False
            v = v.parent
        return True

    def paint(self, p):
        r = Rect(0, 0, self.w, self.h, self.fill, self.radius_, self.ring)
        r.scene = self.scene
        r.paint(p)

    def _finished(self):
        self.text = self.edit.text()
        if self.on_done:
            self.on_done(self.text)

    def value(self):
        return self.edit.text() if self.edit is not None else self.text

    def set_text(self, text):
        self.text = text
        if self.edit is not None:
            self.edit.setText(text)

    def focus(self):
        if self.edit is not None:
            self.edit.setFocus()
            self.edit.selectAll()


class TileView(View):
    """One of the widget's tiles, in any of its forms, with its taps (drawn through render.draw_tile and cached)."""
    cursor = Qt.PointingHandCursor

    def __init__(self, tile, state, form, x=0, y=0, w=152, h=146, dim=False):
        super().__init__(x, y, w, h)
        self.tile, self.state, self.form, self.dim = tile, state, form, dim
        self.interactive = True
        self.flash = 0.0
        self._cache = None
        self._key = None
        self.on_enter = lambda e: self._hover(True)
        self.on_leave = lambda e: self._hover(False)

    def _hover(self, on):
        if self.hovered != on:
            self.hovered = on
            self.invalidate()

    def invalidate(self):
        self._cache = None
        self.changed()

    def set_state(self, state):
        self.state = state
        self.invalidate()

    def paint(self, p):
        s = self.scene.scale
        key = (self.scene.theme, self.scene.style, self.state and repr(self.state), self.form, self.dim, self.hovered,
               round(self.flash, 2), self.w, self.h, s, self.tile.get("icon"), self.tile.get("room"),
               self.tile.get("label"), render.tr("x"))
        if self._cache is None or self._key != key:
            img = QImage(round(self.w * s + 2), round(self.h * s + 2), QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            q = QPainter(img)
            q.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
            q.scale(s, s)
            render.draw_tile(q, self.tile, self.state, 0, 0, self.w, self.h, self.scene.theme,
                             render.tokens(self.scene.theme, self.dim, self.scene.style), self.form, self.dim,
                             hover=self.hovered, flash=self.flash)
            q.end()
            self._cache = QPixmap.fromImage(img)
            self._cache.setDevicePixelRatio(s)
            self._key = key
        if self.lifted:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 80))
            p.drawPath(render.squircle(0, 18, self.w, self.h, self.scene.t["radius_tile"]))
        p.drawPixmap(0, 0, self._cache)


class CheckRow(View):
    """A checkbox and its words."""
    cursor = Qt.PointingHandCursor

    def __init__(self, text, checked, w, on_change=None, size=12.5):
        super().__init__(0, 0, w, 0)
        self.interactive = True
        self.text, self.checked, self.size, self.on_change = text, checked, size, on_change
        self.lines = wrap_lines(render.tr(text), font(size), w - 26)
        self.h = max(18, len(self.lines) * size * 1.35)
        self.enabled = True
        self.on_press = lambda e: True
        self.on_click = self._toggle

    def _toggle(self, e):
        if not self.enabled:
            return True
        self.checked = not self.checked
        self.changed()
        if self.on_change:
            self.on_change(self.checked)
        return True

    def paint(self, p):
        box = QRectF(0, (self.size * 1.35 - 16) / 2, 16, 16)
        p.setPen(QPen(resolve(self.scene, "input_border" if not self.checked else "accent_blue"), 1.2))
        p.setBrush(resolve(self.scene, "accent_blue" if self.checked else "input_bg"))
        p.drawRoundedRect(box, 4, 4)
        if self.checked:
            p.setPen(QPen(QColor(255, 255, 255), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            path = QPainterPath()
            path.moveTo(box.x() + 3.6, box.y() + 8.4)
            path.lineTo(box.x() + 6.8, box.y() + 11.4)
            path.lineTo(box.x() + 12.4, box.y() + 4.8)
            p.drawPath(path)
        f = font(self.size)
        fm = QFontMetricsF(f)
        p.setPen(Qt.NoPen)
        col = resolve(self.scene, "ink1")
        if not self.enabled:
            col.setAlphaF(0.5)
        p.setBrush(col)
        lh = self.size * 1.35
        for i, line in enumerate(self.lines):
            p.drawPath(render.text_path(QPointF(0, 0), f, line, 26, i * lh + (lh - fm.height() / 10) / 2 + fm.ascent() / 10))


class Menu(View):
    """The list a Select opens."""

    def __init__(self, options, value, w, on_pick):
        super().__init__(0, 0, w, 8 + len(options) * 34)
        self.interactive = True
        self.on_press = lambda e: True
        for i, (val, label) in enumerate(options):
            item = Button(label, x=4, y=4 + i * 34, w=w - 8, h=34, size=13, weight=QFont.Normal, color="ink1",
                          fill="panel_solid" if val != value else "btn_fill", hover_fill="btn_fill_strong", radius=11,
                          on_click=lambda e, v=val: on_pick(v))
            item.align_left = True
            self.add(item)

    def paint(self, p):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawRoundedRect(QRectF(0, 4, self.w, self.h), 18, 18)
        p.setBrush(resolve(self.scene, "panel_solid"))
        p.setPen(QPen(resolve(self.scene, "input_border"), 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.w - 1, self.h - 1), 18, 18)


class Select(View):
    """A closed list: the choice shown in a field, a menu when pressed."""
    cursor = Qt.PointingHandCursor

    def __init__(self, x, y, w, options, value, on_change, h=36, size=13):
        super().__init__(x, y, w, h)
        self.interactive = True
        self.options, self.value, self.on_change, self.size = options, value, on_change, size
        self.on_press = lambda e: True
        self.on_click = lambda e: self.open()

    def label(self):
        return next((l for v, l in self.options if v == self.value), "")

    def open(self):
        gx, gy = self.abs_pos()
        menu = Menu(self.options, self.value, self.w, self.pick)
        menu.x, menu.y = gx, gy + self.h + 2
        if menu.y + menu.h > self.scene.css_h:
            menu.y = max(0, gy - menu.h - 2)
        self.scene.open_popup(menu)

    def pick(self, value):
        self.scene.close_popup()
        if value != self.value:
            self.value = value
            self.changed()
            self.on_change(value)

    def paint(self, p):
        p.setPen(QPen(resolve(self.scene, "input_border"), 1))
        p.setBrush(resolve(self.scene, "input_bg"))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.w - 1, self.h - 1), self.h / 2, self.h / 2)
        f = font(self.size)
        fm = QFontMetricsF(f)
        p.setPen(Qt.NoPen)
        p.setBrush(resolve(self.scene, "ink1"))
        text = ellipsize(render.tr(self.label()), f, self.w - 40)
        p.drawPath(render.text_path(QPointF(0, 0), f, text, 12, (self.h - fm.height() / 10) / 2 + fm.ascent() / 10))
        c = QPointF(self.w - 16, self.h / 2)
        tri = QPainterPath()
        tri.moveTo(c.x() - 4, c.y() - 2)
        tri.lineTo(c.x() + 4, c.y() - 2)
        tri.lineTo(c.x(), c.y() + 3)
        tri.closeSubpath()
        p.setBrush(resolve(self.scene, "ink2"))
        p.drawPath(tri)


# ---------------------------------------------------------------------------------------
# animation
# ---------------------------------------------------------------------------------------

def _bezier(x1, y1, x2, y2, t):
    """CSS cubic-bezier(x1, y1, x2, y2) at time t."""
    def at(a, b, u):
        return 3 * a * u * (1 - u) ** 2 + 3 * b * u * u * (1 - u) + u ** 3
    lo, hi = 0.0, 1.0
    for _ in range(24):
        mid = (lo + hi) / 2
        if at(x1, x2, mid) < t:
            lo = mid
        else:
            hi = mid
    return at(y1, y2, (lo + hi) / 2)


def _ease(name, t):
    if isinstance(name, tuple):
        return _bezier(*name, t)
    if name == "linear":
        return t
    if name == "in":
        return t * t * t
    if name == "inout":
        return t * t * (3 - 2 * t)
    if name == "back":                      # a pop: a little overshoot
        c1 = 1.70158
        t -= 1
        return 1 + t * t * ((c1 + 1) * t + c1)
    return 1 - (1 - t) ** 3                 # "out" (and "ease")


class Tweens:
    def __init__(self, scene):
        self.scene = scene
        self.running = []
        self.timer = QTimer(scene)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)

    def animate(self, view, props, ms, ease, done):
        # Starting over on a property replaces its old tween.
        for t in self.running:
            if t["view"] is view:
                for k in props:
                    t["props"].pop(k, None)
        self.running = [t for t in self.running if t["props"]]
        start = {k: getattr(view, k) for k in props}
        if ms <= 0:
            for k, v in props.items():
                setattr(view, k, v)
            self.scene.request_paint()
            if done:
                done()
            return
        self.running.append({"view": view, "props": dict(props), "start": start, "ms": ms, "ease": ease,
                             "t0": time.monotonic(), "done": done})
        self.timer.start()

    def cancel(self, view):
        self.running = [t for t in self.running if t["view"] is not view]

    def tick(self):
        now = time.monotonic()
        finished = []
        for t in self.running:
            k = min(1.0, (now - t["t0"]) * 1000 / t["ms"])
            e = _ease(t["ease"], k)
            for name, goal in t["props"].items():
                setattr(t["view"], name, t["start"][name] + (goal - t["start"][name]) * e)
            if k >= 1.0:
                finished.append(t)
        for t in finished:
            if t in self.running:
                self.running.remove(t)
            if t["done"]:
                t["done"]()
        if not self.running:
            self.timer.stop()
        # only the window's own fade and scale moved: what is drawn in it did not
        self.scene.request_paint(content=any(t["view"] is not self.scene for t in self.running + finished))


# ---------------------------------------------------------------------------------------
# the window
# ---------------------------------------------------------------------------------------

class Scene(GlassMixin, QWidget):
    """A frameless translucent window holding a tree of views, with glass behind its card."""

    def __init__(self, api, kind):
        super().__init__()
        self.api, self.kind = api, kind
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.root = View()
        self.root.scene = self
        self.layer = View()               # above the root: menus and the toast
        self.layer.scene = self
        self.popup = None
        self.fields = []
        self.tweens = Tweens(self)
        self.capture = None
        self.hover_view = None
        self.press_view = None
        self.theme_raw, self.theme, self.style = "auto", "light", "classic"
        self.language, self.liquid_level, self.sampling = "zh-TW", 0, "live"
        self.system_glass = False
        self.zoom_css = 1.0              # this window's own zoom (the card scale)
        self.dpi, self.scale = 1.0, 1.0
        self.pw = self.ph = 1
        self.css_w = self.css_h = 1.0
        self.t = ui_tokens("light")
        self.fade_alpha = 1.0            # the whole window's opacity (entrances and exits)
        self.anim_alpha, self.anim_zoom, self.anim_origin = 1.0, 1.0, (1.0, 1.0)   # the glass and card as one
        self.init_glass()
        self._hwnd = 0
        self._paint_pending = False
        self._content, self._content_dirty, self._content_at = None, True, 0.0
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda *_: self._system_theme_changed())

    # -- theme and size ----------------------------------------------------------------------
    def resolve_theme(self):
        theme = self.theme_raw
        if theme == "auto":
            theme = "dark" if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
        return theme

    def _system_theme_changed(self):
        if self.theme_raw == "auto" and self.resolve_theme() != self.theme:
            self.retheme()

    def retheme(self):
        self.theme = self.resolve_theme()
        self.t = ui_tokens(self.theme, self.style)
        render.set_language(self.language)
        for f in self.fields:
            f.restyle()
        self.themed()
        self.request_paint()

    def themed(self):
        """The theme or style changed: rebuild what is made from them."""

    def set_css_size(self, w, h):
        """The card's size in CSS px; the window follows in physical pixels."""
        self.css_w, self.css_h = w, h
        self.root.w, self.root.h = w, h
        self.update_metrics()

    def update_metrics(self):
        hwnd = self.cache_hwnd()
        self.dpi = ((_dpi(hwnd) / 96.0) if hwnd else (self.devicePixelRatioF() or 1.0)) or 1.0
        self.scale = self.zoom_css * self.dpi
        self.pw, self.ph = max(1, round(self.css_w * self.scale)), max(1, round(self.css_h * self.scale))
        self.fit_glass()
        for f in self.fields:
            f.restyle()
            f.place()
        self.request_paint()

    def cache_hwnd(self):
        try:
            self._hwnd = int(self.winId())
        except Exception:
            self._hwnd = 0
        return self._hwnd

    _cache_hwnd = cache_hwnd

    # -- glass: the card is the window ----------------------------------------------------------
    def glass_card(self):
        return self.css_w, self.css_h, self.card_radius()

    def card_radius(self):
        return self.t["radius_panel"]

    # -- painting ---------------------------------------------------------------------------------
    def request_paint(self, content=True):
        """`content`: what is drawn changed (not only the window's own fade or scale)."""
        if content:
            self._content_dirty = True
        if not self._paint_pending:
            self._paint_pending = True
            QTimer.singleShot(0, self._paint_now)

    def _paint_now(self):
        self._paint_pending = False
        for f in self.fields:
            f.place()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        if self.fade_alpha * self.anim_alpha < 1:
            p.setOpacity(self.fade_alpha * self.anim_alpha)
        if self.anim_zoom != 1.0:
            ox, oy = self.anim_origin[0] * self.width(), self.anim_origin[1] * self.height()
            p.translate(ox, oy)
            p.scale(self.anim_zoom, self.anim_zoom)
            p.translate(-ox, -oy)
        if self.glass is not None and not self.system_glass:
            p.drawImage(0, 0, self.glass)
        # What is on the card is drawn once into a picture and that picture is what is painted: the glass
        # behind it changes up to sixty times a second while the views do not, and drawing them again for
        # each new glass costs a few ms where the picture costs a tenth of one. Coming in or going away
        # also only scales and fades that picture.
        p.drawImage(0, 0, self.content_image())
        p.end()

    def glass_changed(self):
        # A view changed without asking to be drawn again shows at the latest within a quarter second,
        # as it did when every new glass drew the views again.
        if time.monotonic() - self._content_at > 0.25:
            self._content_dirty = True
        super().glass_changed()

    def content_image(self):
        img = self._content
        if img is None or self._content_dirty or img.width() != self.pw or img.height() != self.ph:
            img = QImage(self.pw, self.ph, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            q = QPainter(img)
            q.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
            q.scale(self.scale, self.scale)
            self.paint_card(q)
            self.root.paint_tree(q)
            self.layer.paint_tree(q)
            q.end()
            img.setDevicePixelRatio(self.dpi)
            self._content, self._content_dirty, self._content_at = img, False, time.monotonic()
        return img

    def paint_card(self, p):
        """The card's own tint and rims, under everything."""

    def paint_blurred(self, view, p):
        """A view drawn through a blur: the subtree goes to a picture, the picture is blurred."""
        from PIL import Image, ImageFilter
        s = self.scale / self.dpi
        pad = math.ceil(view.blur * 2)
        w, h = round((view.w + 2 * pad) * s), round((view.h + 2 * pad) * s)
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        q = QPainter(img)
        q.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        q.scale(s, s)
        q.translate(pad - view.x - view.dx, pad - view.y - view.dy)
        saved = view.blur
        view.blur = 0
        view.paint_tree(q)
        view.blur = saved
        q.end()
        pil = Image.frombuffer("RGBA", (w, h), bytes(img.constBits()), "raw", "BGRA", img.bytesPerLine(), 1)
        pil = pil.filter(ImageFilter.GaussianBlur(view.blur * s))
        out = QImage(pil.tobytes("raw", "BGRA"), w, h, QImage.Format_ARGB32_Premultiplied).copy()
        p.save()
        p.scale(1 / s, 1 / s)
        p.drawImage(round((view.x + view.dx - pad) * s), round((view.y + view.dy - pad) * s), out)
        p.restore()

    def paint_faded(self, view, p):
        """A scrolling row whose ends fade out (the capsule rows)."""
        s = self.scale / self.dpi
        w, h = round(view.w * s), round(view.h * s)
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        q = QPainter(img)
        q.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        q.scale(s, s)
        q.translate(-view.x - view.dx, -view.y - view.dy)
        saved = view.fade
        view.fade = 0
        view.paint_tree(q)
        view.fade = saved
        q.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        edge = min(0.45, view.fade / max(1.0, view.w if view.horizontal else view.h))
        left = view.offset > 0.5
        right = view.offset < view.max_offset() - 0.5
        q.resetTransform()
        grad = QLinearGradient(0, 0, w if view.horizontal else 0, 0 if view.horizontal else h)
        grad.setColorAt(0, QColor(0, 0, 0, 0 if left else 255))
        grad.setColorAt(edge, QColor(0, 0, 0, 255))
        grad.setColorAt(1 - edge, QColor(0, 0, 0, 255))
        grad.setColorAt(1, QColor(0, 0, 0, 0 if right else 255))
        q.fillRect(0, 0, w, h, QBrush(grad))
        q.end()
        p.save()
        p.scale(1 / s, 1 / s)
        p.drawImage(round((view.x + view.dx) * s), round((view.y + view.dy) * s), img)
        p.restore()

    # -- the pointer ----------------------------------------------------------------------------------
    def _css(self, e):
        pos = e.position()
        k = self.devicePixelRatioF() / self.scale
        return pos.x() * k, pos.y() * k

    def view_at(self, gx, gy):
        return self.layer.hit(gx, gy) or self.root.hit(gx, gy)

    def _ev(self, view, gx, gy, e):
        lx, ly = view.to_local(gx, gy) if view else (gx, gy)
        return Ev(lx, ly, gx, gy, e.button() if hasattr(e, "button") else Qt.NoButton,
                  e.buttons() if hasattr(e, "buttons") else Qt.NoButton)

    def _bubble(self, view, handler, ev_fn):
        """Offer an event to a view, then its parents, until one handles it."""
        while view is not None:
            fn = getattr(view, handler)
            if fn is not None:
                r = ev_fn(view, fn)
                if r is not False:
                    return view
            view = view.parent
        return None

    def open_popup(self, view):
        self.close_popup()
        self.popup = view
        self.layer.add(view)
        self.request_paint()

    def close_popup(self):
        if self.popup is not None:
            self.layer.remove(self.popup)
            self.popup = None
            self.request_paint()

    def toast(self, text):
        """A short message at the bottom of the window."""
        f = font(12)
        w = text_width(render.tr(text), f) + 28
        v = Rect((self.css_w - w) / 2, self.css_h - 14 - 30, w, 30, (20, 22, 26, 0.88), "full")
        v.add(Label(text, 12, QFont.Normal, "white", x=14, y=(30 - 12 * 1.2) / 2))
        v.alpha = 0.0
        self.layer.add(v)
        v.animate(250, "out", alpha=1.0)

        def away():
            v.animate(250, "out", alpha=0.0, done=lambda: self.layer.remove(v))
        QTimer.singleShot(2200, away)

    def mousePressEvent(self, e):
        gx, gy = self._css(e)
        target = self.view_at(gx, gy)
        if self.popup is not None:
            inside = target is not None and (target is self.popup or self.popup in set(self._chain(target)))
            if not inside:
                self.close_popup()
                return
        self.press_view = target
        self.press_at = (gx, gy)
        self.press_button = e.button()
        if target is None:
            self.pressed_nothing(gx, gy, e)
            return
        for v in self._chain(target):
            v.pressed = True
        self.request_paint()
        handled = self._bubble(target, "on_press", lambda v, fn: fn(self._ev(v, gx, gy, e)))
        if handled is not None and self.capture is None and handled is not target:
            self.press_view = handled

    def pressed_nothing(self, gx, gy, e):
        """A press that landed on nothing."""

    def _chain(self, view):
        while view is not None:
            yield view
            view = view.parent

    def mouseMoveEvent(self, e):
        gx, gy = self._css(e)
        if e.buttons() and (self.capture or self.press_view):
            owner = self.capture or self.press_view
            if owner.on_move is not None:
                owner.on_move(self._ev(owner, gx, gy, e))
            return
        target = self.view_at(gx, gy)
        if target is not self.hover_view:
            old = self.hover_view
            self.hover_view = target
            for v in self._chain(old):
                if v not in set(self._chain(target)):
                    v.hovered = False
                    if v.on_leave:
                        v.on_leave(Ev(0, 0, gx, gy))
            for v in self._chain(target):
                if not v.hovered:
                    v.hovered = True
                    if v.on_enter:
                        v.on_enter(Ev(0, 0, gx, gy))
            cursor = None
            for v in self._chain(target):
                if v.cursor is not None:
                    cursor = v.cursor
                    break
            self.setCursor(QCursor(cursor) if cursor is not None else QCursor(Qt.ArrowCursor))
            self.request_paint()
        self.hovered_over(target, gx, gy, e)

    def hovered_over(self, target, gx, gy, e):
        """The pointer moved with no button down."""
        v = target
        while v is not None:
            if getattr(v, "hovered_move", None):
                lx, ly = v.to_local(gx, gy)
                v.hovered_move(lx, ly)
                break
            v = v.parent

    def leaveEvent(self, e):
        for v in self._chain(self.hover_view):
            v.hovered = False
            if v.on_leave:
                v.on_leave(Ev(0, 0, 0, 0))
        self.hover_view = None

    def mouseReleaseEvent(self, e):
        gx, gy = self._css(e)
        owner = self.capture or self.press_view
        self.capture = None
        target = self.view_at(gx, gy)
        if owner is not None:
            for v in self._chain(owner):
                v.pressed = False
            if owner.on_release is not None:
                owner.on_release(self._ev(owner, gx, gy, e))
            inside = target is not None and (target is owner or owner in set(self._chain(target)))
            if inside and e.button() in (Qt.LeftButton, Qt.RightButton):
                self._bubble(owner, "on_click", lambda v, fn: fn(self._ev(v, gx, gy, e)))
        self.press_view = None
        self.released(gx, gy, e)
        self.request_paint()

    def released(self, gx, gy, e):
        """A button was let go (after the views had it)."""

    def mouseDoubleClickEvent(self, e):
        gx, gy = self._css(e)
        target = self.view_at(gx, gy)
        self._bubble(target, "on_dblclick", lambda v, fn: fn(self._ev(v, gx, gy, e)))

    def wheelEvent(self, e):
        gx, gy = self._css(e)
        target = self.view_at(gx, gy)
        delta = e.angleDelta().y() or e.angleDelta().x()
        self._bubble(target, "on_wheel", lambda v, fn: fn(self._ev(v, gx, gy, e), delta))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.escape()
        else:
            super().keyPressEvent(e)

    def escape(self):
        """Escape was pressed."""


def _dpi(hwnd):
    import ctypes
    try:
        return ctypes.WinDLL("user32").GetDpiForWindow(ctypes.c_void_p(hwnd))
    except Exception:
        return 96
