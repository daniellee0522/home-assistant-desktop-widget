"""The controls of the detail screen, after Home Assistant's own more-info dialogs: a tall slider and a tall
switch to drag or tap, a dial for a thermostat, a bar of modes, rows of presets, a mode card that opens
its choices in a menu floating over the screen, a cover picture and a progress bar for media, and how long
ago something changed.

Views of nativeui/ui.py, in the detail's units (see detail.py); colours are scene tokens or CSS colours.
"""
import datetime
import math
import threading
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainterPath, QPen

from . import render, style, ui
from .ui import View


def ago(iso):
    """How long ago an ISO time was, as Home Assistant says it ("10 分鐘前", "5 hours ago"); "" if unknown."""
    try:
        then = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return ""
    s = max(0, time.time() - then)
    en = render._language == "en"
    for size, zh, one, many in ((86400, "天", "day", "days"), (3600, "小時", "hour", "hours"),
                                (60, "分鐘", "minute", "minutes")):
        if s >= size:
            n = int(s // size)
            return ("%d %s ago" % (n, one if n == 1 else many)) if en else "%d %s前" % (n, zh)
    return "just now" if en else "剛剛"


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def kelvin_rgb(k):
    """The colour of white light at k kelvin (Tanner Helland's fit), as (r, g, b)."""
    t = max(1000.0, min(40000.0, float(k))) / 100.0
    r = 255 if t <= 66 else 329.698727446 * (t - 60) ** -0.1332047592
    g = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * (t - 60) ** -0.0755148492
    b = 255 if t >= 66 else (0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307)
    return tuple(int(max(0, min(255, c))) for c in (r, g, b))


def _text(p, text, f, color, x, y, align="l", w=0.0):
    """One line of text with its top at y."""
    fm = ui.QFontMetricsF(f)
    tw = ui.text_width(text, f)
    if align == "c":
        x += (w - tw) / 2
    elif align == "r":
        x += w - tw
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawPath(render.text_path(QPointF(0, 0), f, text, x, y + fm.ascent() / 10))
    return tw


class TallSlider(View):
    """A tall rounded bar filled from the bottom to the value (a light's brightness, a fan's speed, a
    cover's opening), with a short line at the top of the fill. Drag or press anywhere on it."""
    cursor = Qt.PointingHandCursor

    def __init__(self, w, h, value, lo, hi, color, on_input=None, on_commit=None, step=1, gradient=None):
        super().__init__(0, 0, w, h)
        self.interactive = True
        self.value, self.lo, self.hi, self.step = value, lo, hi, step
        self.color, self.gradient = color, gradient          # gradient: [(t, colour)] bottom to top
        self.on_input_, self.on_commit = on_input, on_commit
        self.dragging = False
        self.on_press, self.on_move, self.on_release = self._press, self._move, self._release

    def _t(self):
        return (self.value - self.lo) / max(1e-9, self.hi - self.lo)

    def _set_from(self, y):
        t = max(0.0, min(1.0, 1 - y / max(1.0, self.h)))
        v = self.lo + t * (self.hi - self.lo)
        v = max(self.lo, min(self.hi, round(v / self.step) * self.step))
        if v != self.value:
            self.value = v
            if self.on_input_:
                self.on_input_(v)
            self.changed()

    def _press(self, e):
        self.dragging = True
        self.scene.capture = self
        self._set_from(e.y)
        return True

    def _move(self, e):
        if self.dragging:
            self._set_from(e.y)
        return True

    def _release(self, e):
        if self.dragging:
            self.dragging = False
            if self.on_commit:
                self.on_commit(self.value)
        return True

    def paint(self, p):
        r = min(self.w / 2, 44)
        shape = QPainterPath()
        shape.addRoundedRect(QRectF(0, 0, self.w, self.h), r, r)
        p.setPen(Qt.NoPen)
        p.setBrush(ui.resolve(self.scene, "btn_fill"))
        p.drawPath(shape)
        t = self._t()
        p.save()
        p.setClipPath(shape)
        if self.gradient:
            from PySide6.QtGui import QLinearGradient
            g = QLinearGradient(0, self.h, 0, 0)
            for at, c in self.gradient:
                g.setColorAt(at, ui.resolve(self.scene, c))
            p.setBrush(g)
            p.drawRect(QRectF(0, 0, self.w, self.h))
        else:
            p.setBrush(ui.resolve(self.scene, self.color))
            p.drawRect(QRectF(0, self.h * (1 - t), self.w, self.h * t + 1))
        p.restore()
        # the handle: a short line at the value
        y = max(10, min(self.h - 10, self.h * (1 - t) + 10))
        p.setBrush(QColor(255, 255, 255, 235))
        p.drawRoundedRect(QRectF(self.w / 2 - 22, y - 2.5, 44, 5), 2.5, 2.5)


class TallSwitch(View):
    """Binary control: direct drag, endpoint commit, or a faster tap along the same path."""
    cursor = Qt.PointingHandCursor

    def __init__(self, w, h, on, color, icon, on_click):
        super().__init__(0, 0, w, h)
        self.interactive = True
        self.on, self.color, self.icon = on, color, icon
        self.position = float(on)
        self.activate = on_click
        self.dragging = self.moved = self.skip_click = False
        self.press_y = self.start_position = 0.0
        self.motion_samples = []
        self.on_press, self.on_move, self.on_release = self._press, self._move, self._release
        self.on_click = self._click

    def contains(self, x, y):
        path = QPainterPath()
        r = min(self.w/2, 44)
        path.addRoundedRect(QRectF(0, 0, self.w, self.h), r, r)
        return path.contains(QPointF(x, y))

    def _press(self, e):
        self.stop_animation()
        self.scene.capture = self
        self.dragging = True
        self.moved = self.skip_click = False
        self.press_y, self.start_position = e.y, self.position
        self.motion_samples = [(time.monotonic(), e.y)]
        return True

    def _move(self, e):
        if self.dragging:
            now = time.monotonic()
            self.motion_samples = [(t, y) for t, y in self.motion_samples if now-t <= .12]
            self.motion_samples.append((now, e.y))
            delta = e.y - self.press_y
            self.moved |= abs(delta) > 6
            if self.moved:
                self.position = max(0.0, min(1.0, self.start_position - delta / max(1, self.h/2-8)))
                self.changed()
        return True

    def _set(self, target, response):
        self.on = bool(target)
        self.animate(response, "spring", position=float(target))
        self.activate()

    def _release(self, e):
        if not self.dragging:
            return True
        self._move(e)
        self.dragging = False
        self.skip_click = self.moved
        if self.moved:
            velocity = 0.0
            if len(self.motion_samples) > 1:
                t0, y0 = self.motion_samples[0]
                t1, y1 = self.motion_samples[-1]
                velocity = -(y1-y0) / max(.008, t1-t0) / max(1, self.h/2-8)
            target = velocity > 0 if abs(velocity) > 2.5 else self.position >= .5
            if target != self.on:
                self._set(target, 320)
            else:
                self.animate(320, "spring", position=float(self.on))
        return True

    def _click(self, e):
        if not self.skip_click:
            self._set(not self.on, 180)
        self.skip_click = False
        return True

    @staticmethod
    def _blend(a, b, t):
        return QColor.fromRgbF(*(x+(y-x)*t for x,y in zip(a.getRgbF(), b.getRgbF())))

    def paint(self, p):
        t = max(0.0, min(1.0, self.position))
        r = min(self.w/2, 44)
        accent = ui.resolve(self.scene, self.color)
        on_track = QColor(accent)
        on_track.setAlphaF(.22)
        track = self._blend(ui.resolve(self.scene, "btn_fill"), on_track, t)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, self.w, self.h), r, r)
        pad, bh = 8, self.h/2-8
        top = (self.h-pad-bh) * (1-t) + pad*t
        block = QRectF(pad, top, self.w-2*pad, bh)
        p.setBrush(self._blend(ui.resolve(self.scene, "btn_fill_strong"), accent, t))
        p.drawRoundedRect(block, r-pad, r-pad)
        icon_color = self._blend(ui.resolve(self.scene, "ink2"), QColor("#ffffff"), t)
        render.draw_icon(p, self.icon, (icon_color.red(), icon_color.green(), icon_color.blue(), icon_color.alphaF()),
                         QRectF(block.center().x()-13, block.center().y()-13, 26, 26))


def preserve_controls(scene, old, new):
    """Rebuilding during a gesture or spring transfers presentation and pointer ownership."""
    def controls(view):
        found = [view] if isinstance(view, (TallSwitch, TallSlider, Dial, ui.Slider, ui.Button)) else []
        return found + [control for child in view.children for control in controls(child)]
    before, after = controls(old), controls(new)
    for old_control, new_control in zip(before, after):
        if type(old_control) is not type(new_control):
            continue
        if isinstance(old_control, ui.Button):
            new_control.zoom = old_control.zoom
            new_control.pressed = old_control.pressed
        elif isinstance(old_control, TallSwitch):
            for name in ("position", "dragging", "moved", "skip_click", "press_y", "start_position", "motion_samples"):
                setattr(new_control, name, getattr(old_control, name))
        elif getattr(old_control, "dragging", False):
            new_control.dragging, new_control.value = True, old_control.value
            callback = getattr(new_control, "on_input_", None)
            if callback: callback(new_control.value)
        scene.tweens.replace_view(old_control, new_control)
        if isinstance(new_control, TallSwitch) and not new_control.dragging and old_control.on != new_control.on:
            scene.tweens.animate(new_control, {"position": float(new_control.on)}, 180, "spring", None)
        for name in ("capture", "press_view", "hover_view"):
            if getattr(scene, name, None) is old_control:
                setattr(scene, name, new_control)



class Dial(View):
    """A thermostat's dial: a 270 degree arc with the set temperature on it to drag, a dot where the room
    is, and in the middle the mode and the set temperature."""
    cursor = Qt.PointingHandCursor
    START, SWEEP = 225.0, 270.0

    def __init__(self, size, value, lo, hi, step, current, mode_text, color, on_input=None, on_commit=None):
        super().__init__(0, 0, size, size)
        self.interactive = True
        self.value, self.lo, self.hi, self.step = value, lo, hi, step
        self.current, self.mode_text, self.color = current, mode_text, color
        self.on_input_, self.on_commit = on_input, on_commit
        self.dragging = False
        self.on_press, self.on_move, self.on_release = self._press, self._move, self._release

    def _geo(self):
        stroke = 24
        return self.w / 2, self.h / 2, self.w / 2 - stroke / 2 - 4, stroke

    def _t(self, v):
        return max(0.0, min(1.0, (v - self.lo) / max(1e-9, self.hi - self.lo)))

    def _point(self, t):
        cx, cy, r, _ = self._geo()
        a = math.radians(self.START - self.SWEEP * t)
        return QPointF(cx + r * math.cos(a), cy - r * math.sin(a))

    def _set_from(self, x, y):
        if self.value is None:
            return
        cx, cy, _, _ = self._geo()
        a = math.degrees(math.atan2(cy - y, x - cx))
        d = (self.START - a) % 360
        if d > self.SWEEP:
            d = 0.0 if d > self.SWEEP + (360 - self.SWEEP) / 2 else self.SWEEP
        v = self.lo + d / self.SWEEP * (self.hi - self.lo)
        v = round(round(v / self.step) * self.step, 1)
        v = max(self.lo, min(self.hi, v))
        if v != self.value:
            self.value = v
            if self.on_input_:
                self.on_input_(v)
            self.changed()

    def _press(self, e):
        thumb = self._point(self._t(self.value)) if self.value is not None else None
        if thumb is None or (e.x - thumb.x()) ** 2 + (e.y - thumb.y()) ** 2 > 30 ** 2:
            cx, cy, r, stroke = self._geo()
            dist = math.hypot(e.x - cx, e.y - cy)
            if abs(dist - r) > stroke:                  # not on the ring: nothing to drag
                return True
        self.dragging = True
        self.scene.capture = self
        self._set_from(e.x, e.y)
        return True

    def _move(self, e):
        if self.dragging:
            self._set_from(e.x, e.y)
        return True

    def _release(self, e):
        if self.dragging:
            self.dragging = False
            if self.on_commit:
                self.on_commit(self.value)
        return True

    def paint(self, p):
        cx, cy, r, stroke = self._geo()
        box = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        pen = QPen(ui.resolve(self.scene, "btn_fill"), stroke, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(box, int((self.START - self.SWEEP) * 16), int(self.SWEEP * 16))
        if self.value is not None:
            t = self._t(self.value)
            if self.color:
                pen.setColor(ui.resolve(self.scene, self.color))
                p.setPen(pen)
                p.drawArc(box, int((self.START - self.SWEEP * t) * 16), int(self.SWEEP * t * 16))
        p.setPen(Qt.NoPen)
        if self.current is not None:
            dot = self._point(self._t(self.current))
            p.setBrush(ui.resolve(self.scene, "ink2"))
            p.drawEllipse(dot, 4, 4)
        if self.value is not None:
            thumb = self._point(self._t(self.value))
            p.setBrush(QColor(0, 0, 0, 60))
            p.drawEllipse(QPointF(thumb.x(), thumb.y() + 1.5), stroke / 2 + 2, stroke / 2 + 2)
            p.setBrush(QColor(255, 255, 255))
            p.drawEllipse(thumb, stroke / 2 + 1, stroke / 2 + 1)
            p.setPen(QPen(ui.resolve(self.scene, "btn_fill_strong"), 3))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(thumb, stroke / 2 - 1, stroke / 2 - 1)
            p.setPen(Qt.NoPen)
        ink1, ink2 = ui.resolve(self.scene, "ink1"), ui.resolve(self.scene, "ink2")
        _text(p, render.tr(self.mode_text), ui.font(16, QFont.Medium), ink2, 0, cy - 56, "c", self.w)
        big = ui.font(58, QFont.Normal)
        num = "--" if self.value is None else ("%g" % self.value)
        tw = ui.text_width(num, big)
        x = (self.w - tw) / 2 - 6
        _text(p, num, big, ink1, x, cy - 30)
        _text(p, "°", ui.font(22), ink1, x + tw + 2, cy - 22)


class ModeBar(View):
    """A capsule of round icon buttons, one of them chosen (a light's power, brightness and colour)."""

    def __init__(self, items, size=52):
        """items: [(icon, chosen, on_click)]."""
        n = len(items)
        super().__init__(0, 0, n * size + (n - 1) * 6 + 12, size + 12)
        self.items = items
        for i, (icon, chosen, click) in enumerate(items):
            b = ui.Button(x=6 + i * (size + 6), y=6, w=size, h=size, icon=icon, icon_size=size * 0.46,
                          fill=None, hover_fill="btn_fill", active=chosen, active_fill="white",
                          active_color="#1d1d1f", on_click=lambda e, c=click: c())
            self.add(b)

    def paint(self, p):
        p.setPen(Qt.NoPen)
        p.setBrush(ui.resolve(self.scene, "btn_fill"))
        p.drawRoundedRect(QRectF(0, 0, self.w, self.h), self.h / 2, self.h / 2)


class Swatches(View):
    """A row of round colours to pick from (a light's presets)."""
    cursor = Qt.PointingHandCursor

    def __init__(self, w, colors, on_pick, size=46, chosen=None):
        """colors: [(css colour, value)]."""
        super().__init__(0, 0, w, size + 8)
        self.interactive = True
        self.colors, self.on_pick_, self.size, self.chosen = colors, on_pick, size, chosen
        self.on_press = lambda e: True
        self.on_click = self._click

    def _xs(self):
        n = len(self.colors)
        gap = min(22.0, (self.w - n * self.size) / max(1, n - 1))
        start = (self.w - (n * self.size + (n - 1) * gap)) / 2
        return [start + i * (self.size + gap) for i in range(n)]

    def _click(self, e):
        for x, (_, value) in zip(self._xs(), self.colors):
            if x <= e.x <= x + self.size:
                self.on_pick_(value)
                return True
        return True

    def paint(self, p):
        for x, (color, value) in zip(self._xs(), self.colors):
            rect = QRectF(x, 4, self.size, self.size)
            p.setPen(Qt.NoPen)
            if color == "rainbow":
                from PySide6.QtGui import QConicalGradient
                g = QConicalGradient(rect.center(), 90)
                for i, c in enumerate(("#ff3b30", "#ffcc00", "#34c759", "#5ac8fa", "#007aff", "#af52de", "#ff3b30")):
                    g.setColorAt(i / 6, QColor(c))
                p.setBrush(g)
            else:
                p.setBrush(ui.resolve(self.scene, color))
            p.drawEllipse(rect)
            if value == self.chosen:
                p.setPen(QPen(ui.resolve(self.scene, "ink1"), 2.5))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(rect.adjusted(-4, -4, 4, 4))


class ModeCard(View):
    """A small card with an icon, what it sets and what it is set to (a thermostat's mode, a fan speed,
    a light's effect). Pressed, its choices open in a menu over it (ChoiceMenu); the screen stays as it is.
    `key` names it, so a menu open over it stays open over the card that replaces it when the screen is
    built again (reattach_menu)."""
    cursor = Qt.PointingHandCursor

    def __init__(self, w, icon, title, value, options=None, on_pick=None, current=None, compact=False):
        """options: [(value, label)]; on_pick(value) when one is chosen; current: the value chosen now."""
        super().__init__(0, 0, w, 54 if compact else 62)
        self.interactive = True
        self.icon, self.title, self.value, self.key = icon, title, value, title
        self.options, self.on_pick, self.current = options or [], on_pick, current
        self.open = False
        self.on_press = lambda e: True
        self.on_click = lambda e: self.show_menu()
        self.on_enter = lambda e: self.changed()
        self.on_leave = lambda e: self.changed()

    def show_menu(self):
        if self.options and self.scene is not None:
            open_menu(self, self.options, self.current, self.on_pick)

    def paint(self, p):
        fill = "btn_fill_strong" if (self.hovered or self.open) else "btn_fill"
        p.setPen(Qt.NoPen)
        p.setBrush(ui.resolve(self.scene, fill))
        p.drawRoundedRect(QRectF(0, 0, self.w, self.h), 16, 16)
        render.draw_icon(p, self.icon, ui.resolve(self.scene, "ink1").name(), QRectF(14, (self.h - 24) / 2, 24, 24))
        x = 14 + 24 + 12
        size, weight, color = style.TEXT["label"]
        f = ui.font(size, weight)
        render.draw_text_fade(p, render.tr(self.title), f, ui.resolve(self.scene, color),
                              QRectF(x, (self.h - 42) / 2, self.w - x - 10, 18), False)
        size, weight, color = style.TEXT["value"]
        f = ui.font(size, weight)
        render.draw_text_fade(p, render.tr(self.value), f, ui.resolve(self.scene, color),
                              QRectF(x, (self.h - 42) / 2 + 20, self.w - x - 10, 22), False)


class ChoiceMenu(View):
    """The choices of a mode card, as iOS shows a menu: a floating pane over everything, a row for each choice
    and a tick by the one chosen now; long lists scroll (fading at their ends, as every scrolling box does)."""
    ROW = 42
    MAX_ROWS = 7

    def __init__(self, options, current, w, on_pick, key=None):
        f = style.font("menu")
        widest = max([ui.text_width(render.tr(lab), f) for _, lab in options] or [0])
        w = max(w, min(320, widest + 16 + 40))
        shown = min(len(options), self.MAX_ROWS)
        super().__init__(0, 0, w, shown * self.ROW + 12)
        self.interactive = True
        self.on_press = lambda e: True
        self.on_click = lambda e: True
        self.options, self.current, self.on_pick, self.key = options, current, on_pick, key
        self.anchor = None
        self.on_closed = None                     # called by the scene when it closes it
        sv = ui.ScrollView(0, 6, w, shown * self.ROW)
        for i, (val, lab) in enumerate(options):
            sv.add(_ChoiceRow(i, w, lab, val == current, lambda v=val: on_pick(v), i < len(options) - 1))
        sv.content.w, sv.content.h = w, len(options) * self.ROW
        chosen = next((i for i, (val, _) in enumerate(options) if val == current), 0)
        sv.scroll_to((chosen - shown // 2) * self.ROW)       # the one chosen now in sight
        self.add(sv)

    def paint(self, p):
        style.popup_pane(p, self.scene, self.w, self.h)


class _ChoiceRow(View):
    cursor = Qt.PointingHandCursor

    def __init__(self, i, w, label, chosen, pick, line):
        super().__init__(6, i * ChoiceMenu.ROW, w - 12, ChoiceMenu.ROW)
        self.interactive = True
        self.label, self.chosen, self.line = label, chosen, line
        self.on_press = lambda e: True
        self.on_click = lambda e: pick()
        self.on_enter = self.on_leave = lambda e: self.changed()

    def paint(self, p):
        if self.hovered:
            p.setPen(Qt.NoPen)
            p.setBrush(ui.resolve(self.scene, "btn_fill"))
            p.drawRoundedRect(QRectF(0, 1, self.w, self.h - 2), 11, 11)
        size, weight, color = style.TEXT["menu"]
        f = ui.font(size, QFont.DemiBold if self.chosen else weight)
        fm = ui.QFontMetricsF(f)
        _text(p, ui.ellipsize(render.tr(self.label), f, self.w - 12 - 34), f,
              ui.resolve(self.scene, "accent_blue" if self.chosen else color), 12, (self.h - fm.height() / 10) / 2)
        if self.chosen:
            render.draw_icon(p, "mdi:check", ui.resolve(self.scene, "accent_blue").name(),
                             QRectF(self.w - 10 - 20, (self.h - 20) / 2, 20, 20))
        if self.line and not self.hovered:
            p.setPen(Qt.NoPen)
            p.setBrush(ui.resolve(self.scene, "input_border"))
            p.drawRect(QRectF(12, self.h - 0.5, self.w - 24, 0.5))


class ColorMenu(View):
    """A light's colours to choose from, in a floating pane (in place of a colour dialog, which would take
    the panel's focus and leave it waiting)."""
    COLORS = ("#ff3b30", "#ff9500", "#ffcc00", "#34c759", "#00c7be", "#5ac8fa",
              "#007aff", "#5856d6", "#af52de", "#ff2d55", "#ffd6a5", "#ffffff")
    SIZE, GAP, PAD = 40, 12, 14

    def __init__(self, current, on_pick, key=None):
        cols = 6
        rows = (len(self.COLORS) + cols - 1) // cols
        w = 2 * self.PAD + cols * self.SIZE + (cols - 1) * self.GAP
        super().__init__(0, 0, w, 2 * self.PAD + rows * self.SIZE + (rows - 1) * self.GAP)
        self.interactive = True
        self.on_press = lambda e: True
        self.on_click = self._click
        self.current, self.on_pick, self.key = current, on_pick, key
        self.anchor = self.on_closed = None
        self.cursor = Qt.PointingHandCursor

    def _cells(self):
        for i, c in enumerate(self.COLORS):
            r, k = divmod(i, 6)
            yield c, QRectF(self.PAD + k * (self.SIZE + self.GAP), self.PAD + r * (self.SIZE + self.GAP),
                            self.SIZE, self.SIZE)

    def _click(self, e):
        for c, rect in self._cells():
            if rect.adjusted(-4, -4, 4, 4).contains(QPointF(e.x, e.y)):
                q = QColor(c)
                self.on_pick((q.red(), q.green(), q.blue()))
        return True

    def paint(self, p):
        style.popup_pane(p, self.scene, self.w, self.h)
        cur = QColor(*self.current).name() if self.current else None
        for c, rect in self._cells():
            p.setPen(QPen(ui.resolve(self.scene, "input_border"), 1))
            p.setBrush(QColor(c))
            p.drawEllipse(rect)
            if c == cur:
                p.setPen(QPen(ui.resolve(self.scene, "ink1"), 2.5))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(rect.adjusted(-4, -4, 4, 4))


def _place(anchor, pane):
    """A floating pane under its anchor (over it when there is no room below), as large as the anchor is
    drawn, inside the window."""
    scene = anchor.scene
    ax, ay, k = anchor.in_scene()
    anchor_k = k
    bounds = scene.popup_bounds()
    k = min(k, max(1, bounds.width() - 12) / pane.w, max(1, bounds.height() - 12) / pane.h)
    pane.scale = k
    mw, mh = pane.w * k, pane.h * k
    x = min(max(bounds.left() + 6, ax + (anchor.w * anchor_k - mw) / 2), bounds.right() - mw - 6)
    y = ay + anchor.h * anchor_k + 6 * k
    if y + mh > bounds.bottom() - 6:
        y = ay - 6 * k - mh
    pane.x, pane.y = x, max(bounds.top() + 6, min(y, bounds.bottom() - mh - 6))


def _unopen(pane):
    """The menu was closed: its card no longer looks open."""
    if pane.anchor is not None:
        pane.anchor.open = False
        pane.anchor.changed()


def _show(anchor, pane):
    scene = anchor.scene
    pane.anchor, pane.on_closed = anchor, lambda: _unopen(pane)
    anchor.open = True
    _place(anchor, pane)
    pane.alpha, pane.dy, pane.zoom = 0.0, -6.0, 0.98
    pane.zoom_origin = (0.5, 0 if pane.y >= anchor.in_scene()[1] else 1)
    scene.open_popup(pane)
    pane.animate(260, "spring", alpha=1.0, dy=0.0, zoom=1.0)
    return pane


def open_menu(anchor, options, current, on_pick):
    """A ChoiceMenu for `anchor` (a ModeCard); choosing closes it and then calls on_pick."""
    scene = anchor.scene

    def pick(value):
        scene.close_popup()
        on_pick(value)
    return _show(anchor, ChoiceMenu(options, current, anchor.w, pick, getattr(anchor, "key", None)))


def open_colors(anchor, current, on_pick):
    """A ColorMenu for `anchor`; choosing closes it and then calls on_pick((r, g, b))."""
    scene = anchor.scene

    def pick(rgb):
        scene.close_popup()
        on_pick(rgb)
    return _show(anchor, ColorMenu(current, pick, getattr(anchor, "key", "colors")))


def reattach_menu(scene, tree):
    """The screen was built again under a menu that is open: it stays, over the card that took the old one's
    place (marked open), and shows the choices as they are now. With no such card it closes."""
    pane = scene.popup
    if not isinstance(pane, (ChoiceMenu, ColorMenu)) or pane.key is None:
        return
    found = []

    def walk(v):
        if getattr(v, "key", None) == pane.key and v is not pane and not isinstance(v, (ChoiceMenu, ColorMenu)):
            found.append(v)
        for c in v.children:
            walk(c)
    walk(tree)
    if not found:
        scene.close_popup()
        return
    card = found[0]
    if isinstance(pane, ChoiceMenu) and (card.options != pane.options or card.current != pane.current):
        new = ChoiceMenu(card.options, card.current, card.w, pane.on_pick, pane.key)
        # A state can arrive while the pane is appearing: carry its displayed position
        # and remaining animation into the replacement, without jumping to fully open.
        new.alpha, new.dy, new.zoom = pane.alpha, pane.dy, pane.zoom
        new.zoom_origin = pane.zoom_origin
        scene.tweens.replace_view(pane, new)
        new.on_closed = lambda: _unopen(new)
        scene.layer.remove(pane)
        scene.layer.add(new)
        scene.popup = pane = new
    pane.anchor = card
    card.open = True
    _place(card, pane)
    scene.request_paint()


class Picture(View):
    """A picture from Home Assistant (a song's cover, a camera), fetched off the GUI thread through
    `fetch(url) -> bytes` and kept for the next time; rounded corners, an icon until it comes."""
    _cache = {}                      # url -> QImage, the last few

    def __init__(self, w, h, url, fetch, run_on_ui_thread, icon="mdi:music", radius=14):
        super().__init__(0, 0, w, h)
        self.url, self.fetch, self.run, self.icon, self.radius = url, fetch, run_on_ui_thread, icon, radius
        self.image = Picture._cache.get(url)
        self._asked = False

    def _load(self):
        self._asked = True
        url = self.url

        def go():
            try:
                data = self.fetch(url)
            except Exception:
                data = None
            img = QImage.fromData(data) if data else None

            def done():
                if img is not None and not img.isNull():
                    Picture._cache[url] = img
                    while len(Picture._cache) > 8:
                        Picture._cache.pop(next(iter(Picture._cache)))
                    self.image = img
                    self.changed()
            self.run(done)
        threading.Thread(target=go, daemon=True).start()

    def paint(self, p):
        if self.image is None and self.url and not self._asked:
            self._load()
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.w, self.h), self.radius, self.radius)
        p.setPen(Qt.NoPen)
        if self.image is None:
            p.setBrush(ui.resolve(self.scene, "btn_fill"))
            p.drawPath(path)
            s = min(self.w, self.h) * 0.3
            render.draw_icon(p, self.icon, ui.resolve(self.scene, "ink2").name(),
                             QRectF((self.w - s) / 2, (self.h - s) / 2, s, s))
            return
        p.save()
        p.setClipPath(path)
        img = self.image
        k = max(self.w / img.width(), self.h / img.height())          # fill the box, centred
        w, h = img.width() * k, img.height() * k
        p.drawImage(QRectF((self.w - w) / 2, (self.h - h) / 2, w, h), img)
        p.restore()


def _clock(s):
    s = max(0, int(s))
    return "%d:%02d:%02d" % (s // 3600, s // 60 % 60, s % 60) if s >= 3600 else "%02d:%02d" % (s // 60, s % 60)


class Progress(View):
    """Where a song is: a bar with a knob, the time gone and the length; it moves on by itself while playing
    (the position comes with the time it was taken). With on_seek it can be dragged, or pressed anywhere along
    it: the time shown follows, and on_seek(seconds) is called when it is let go. The knob stays inside."""
    cursor = Qt.PointingHandCursor
    KNOB = 7

    def __init__(self, w, position, updated_at, duration, playing, on_seek=None):
        super().__init__(0, 0, w, 44)
        self.position, self.duration, self.playing = position or 0.0, duration or 0.0, playing
        try:
            self.taken = datetime.datetime.fromisoformat(str(updated_at).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            self.taken = time.time()
        self._ticking = False
        self.seeking = None                      # seconds, while dragged
        self.on_seek = on_seek
        self.interactive = on_seek is not None and self.duration > 0
        self.on_press = self._press
        self.on_move = self._move
        self.on_release = self._release

    def now(self):
        if self.seeking is not None:
            return self.seeking
        pos = self.position + ((time.time() - self.taken) if self.playing else 0.0)
        return max(0.0, min(self.duration or pos, pos))

    def _at(self, x):
        k = self.KNOB
        return max(0.0, min(1.0, (x - k) / max(1.0, self.w - 2 * k))) * self.duration

    def _press(self, e):
        self.seeking = self._at(e.x)
        self.changed()
        return True

    def _move(self, e):
        if self.seeking is not None:
            self.seeking = self._at(e.x)
            self.changed()
        return True

    def _release(self, e):
        if self.seeking is None:
            return True
        at, self.seeking = self._at(e.x), None
        self.position, self.taken = at, time.time()
        self.changed()
        self.on_seek(at)
        return True

    def _tick(self):
        self._ticking = False
        if self.scene is not None and self.scene.isVisible():
            self.changed()

    def paint(self, p):
        pos = self.now()
        t = pos / self.duration if self.duration else 0.0
        k = self.KNOB
        track = QRectF(k, 10 - 2, self.w - 2 * k, 4)
        p.setPen(Qt.NoPen)
        p.setBrush(ui.resolve(self.scene, "btn_fill_strong"))
        p.drawRoundedRect(track, 2, 2)
        accent = ui.resolve(self.scene, "accent_blue")
        p.setBrush(accent)
        p.drawRoundedRect(QRectF(k, 8, track.width() * t, 4), 2, 2)
        r = k + (2 if self.seeking is not None else 0)
        p.drawEllipse(QPointF(k + track.width() * t, 10), r, r)
        size, weight, color = style.TEXT["caption"]
        f, ink2 = ui.font(size, weight), ui.resolve(self.scene, color)
        _text(p, _clock(pos), f, ink2, k - 2, 24)
        if self.duration:
            _text(p, _clock(self.duration), f, ink2, 0, 24, "r", self.w - k + 2)
        if self.playing and self.seeking is None and not self._ticking:
            self._ticking = True
            QTimer.singleShot(1000, self._tick)


class Switch(View):
    """The on/off switch of iOS: a capsule track that turns green, a white knob that slides (and can be dragged), a spring in
    between. `on_change(bool)` is called once the knob has arrived, so what is built again from the answer shows it settled."""
    cursor = Qt.PointingHandCursor
    W, H = 46, 28

    def __init__(self, on, on_change, color="accent_green", enabled=True):
        super().__init__(0, 0, self.W, self.H)
        self.interactive = enabled
        self.on, self.color, self.change = bool(on), color, on_change
        self.position = float(self.on)                     # 0 = off .. 1 = on, where the knob is drawn
        self.dragging = self.moved = self.skip_click = False
        self.press_x = self.start_position = 0.0
        self.on_press, self.on_move, self.on_release, self.on_click = self._press, self._move, self._release, self._click

    def _press(self, e):
        self.stop_animation()
        self.scene.capture = self
        self.dragging, self.moved, self.skip_click = True, False, False
        self.press_x, self.start_position = e.x, self.position
        return True

    def _move(self, e):
        if self.dragging:
            dx = e.x - self.press_x
            self.moved |= abs(dx) > 4
            if self.moved:
                self.position = max(0.0, min(1.0, self.start_position + dx / (self.W - self.H)))
                self.changed()
        return True

    def _settle(self, target, ms):
        changed = bool(target) != self.on
        self.on = bool(target)
        self.animate(ms, "spring", position=float(target), done=(lambda: self.change(self.on)) if changed else None)

    def _release(self, e):
        if not self.dragging:
            return True
        self._move(e)
        self.dragging = False
        self.skip_click = self.moved
        if self.moved:
            self._settle(self.position >= 0.5, 260)
        return True

    def _click(self, e):
        if not self.skip_click:
            self._settle(not self.on, 220)
        self.skip_click = False
        return True

    def paint(self, p):
        t = max(0.0, min(1.0, self.position))
        track_off, track_on = ui.resolve(self.scene, "btn_fill_strong"), ui.resolve(self.scene, self.color)
        track = QColor.fromRgbF(*(a + (b - a) * t for a, b in zip(track_off.getRgbF(), track_on.getRgbF())))
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, self.W, self.H), self.H / 2, self.H / 2)
        d = self.H - 4
        x = 2 + (self.W - self.H) * t
        for spread, alpha in ((2.5, 18), (1.2, 26)):       # the knob's shadow
            p.setBrush(QColor(0, 0, 0, alpha))
            p.drawEllipse(QRectF(x - spread / 2, 2 + 1.2 - spread / 2, d + spread, d + spread))
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QRectF(x, 2, d, d))
