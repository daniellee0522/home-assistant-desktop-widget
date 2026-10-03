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

from . import render, ui
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
    """A tall track with a block in its top half when on (a lock locked, a switch on), its bottom half
    when off; tap to change. The block carries the icon."""
    cursor = Qt.PointingHandCursor

    def __init__(self, w, h, on, color, icon, on_click):
        super().__init__(0, 0, w, h)
        self.interactive = True
        self.on, self.color, self.icon = on, color, icon
        self.on_press = lambda e: True
        self.on_click = lambda e: on_click()

    def paint(self, p):
        r = min(self.w / 2, 44)
        track = ui.resolve(self.scene, self.color if self.on else "btn_fill")
        if self.on:
            track = QColor(track)
            track.setAlphaF(0.22)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, self.w, self.h), r, r)
        pad = 8
        bh = self.h / 2 - pad
        top = pad if self.on else self.h - pad - bh
        block = QRectF(pad, top, self.w - 2 * pad, bh)
        p.setBrush(ui.resolve(self.scene, self.color) if self.on else ui.resolve(self.scene, "btn_fill_strong"))
        p.drawRoundedRect(block, r - pad, r - pad)
        render.draw_icon(p, self.icon, "#ffffff" if self.on else ui.resolve(self.scene, "ink2").name(),
                         QRectF(block.center().x() - 13, block.center().y() - 13, 26, 26))


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
    a light's effect). Pressed, its choices open in a menu over it (ChoiceMenu); the screen stays as it is."""
    cursor = Qt.PointingHandCursor

    def __init__(self, w, icon, title, value, options=None, on_pick=None, current=None):
        """options: [(value, label)]; on_pick(value) when one is chosen; current: the value chosen now."""
        super().__init__(0, 0, w, 62)
        self.interactive = True
        self.icon, self.title, self.value = icon, title, value
        self.options, self.on_pick, self.current = options or [], on_pick, current
        self.open = False
        self.on_press = lambda e: True
        self.on_click = lambda e: self.show_menu()
        self.on_enter = lambda e: self.changed()
        self.on_leave = lambda e: self.changed()

    def show_menu(self):
        if not self.options or self.scene is None:
            return

        def closed():
            self.open = False
            self.changed()
        self.open = True
        open_menu(self, self.options, self.current, self.on_pick, closed)

    def paint(self, p):
        fill = "btn_fill_strong" if (self.hovered or self.open) else "btn_fill"
        p.setPen(Qt.NoPen)
        p.setBrush(ui.resolve(self.scene, fill))
        p.drawRoundedRect(QRectF(0, 0, self.w, self.h), 16, 16)
        render.draw_icon(p, self.icon, ui.resolve(self.scene, "ink1").name(), QRectF(14, (self.h - 24) / 2, 24, 24))
        x = 14 + 24 + 12
        _text(p, render.tr(self.title), ui.font(13, QFont.Medium), ui.resolve(self.scene, "ink2"), x, 11)
        f = ui.font(16, QFont.DemiBold)
        _text(p, ui.ellipsize(render.tr(self.value), f, self.w - x - 10), f, ui.resolve(self.scene, "ink1"), x, 31)


class ChoiceMenu(View):
    """The choices of a mode card, as iOS shows a menu: a rounded pane over everything, a row for each choice
    and a tick by the one chosen now; long lists scroll."""
    ROW = 42
    MAX_ROWS = 7

    def __init__(self, options, current, w, on_pick):
        f = ui.font(15)
        widest = max([ui.text_width(render.tr(lab), f) for _, lab in options] or [0])
        w = max(w, min(320, widest + 16 + 40))
        shown = min(len(options), self.MAX_ROWS)
        super().__init__(0, 0, w, shown * self.ROW + 12)
        self.interactive = True
        self.on_press = lambda e: True
        self.on_click = lambda e: True
        self.on_closed = None
        sv = ui.ScrollView(0, 6, w, shown * self.ROW)
        for i, (val, lab) in enumerate(options):
            sv.add(_ChoiceRow(i, w, lab, val == current, lambda v=val: on_pick(v), i < len(options) - 1))
        sv.content.w, sv.content.h = w, len(options) * self.ROW
        chosen = next((i for i, (val, _) in enumerate(options) if val == current), 0)
        sv.scroll_to((chosen - shown // 2) * self.ROW)       # the one chosen now in sight
        self.add(sv)

    def paint(self, p):
        p.setPen(Qt.NoPen)
        for spread in (24, 18, 12, 6):                # a soft shadow, a little below
            p.setBrush(QColor(0, 0, 0, 9))
            p.drawRoundedRect(QRectF(-spread / 2, -spread / 2 + 6, self.w + spread, self.h + spread),
                              16 + spread / 2, 16 + spread / 2)
        p.setBrush(ui.resolve(self.scene, "panel_solid"))
        p.setPen(QPen(ui.resolve(self.scene, "input_border"), 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.w - 1, self.h - 1), 16, 16)


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
        f = ui.font(15, QFont.DemiBold if self.chosen else QFont.Normal)
        fm = ui.QFontMetricsF(f)
        _text(p, ui.ellipsize(render.tr(self.label), f, self.w - 12 - 34), f,
              ui.resolve(self.scene, "accent_blue" if self.chosen else "ink1"), 12, (self.h - fm.height() / 10) / 2)
        if self.chosen:
            render.draw_icon(p, "mdi:check", ui.resolve(self.scene, "accent_blue").name(),
                             QRectF(self.w - 10 - 20, (self.h - 20) / 2, 20, 20))
        if self.line and not self.hovered:
            c = ui.resolve(self.scene, "input_border")
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawRect(QRectF(12, self.h - 0.5, self.w - 24, 0.5))


def open_menu(anchor, options, current, on_pick, closed=None):
    """A ChoiceMenu for `anchor`, under it (over it when there is no room below), as large as the anchor is
    drawn; choosing closes it and then calls on_pick."""
    scene = anchor.scene
    ax, ay, k = anchor.in_scene()

    def pick(value):
        scene.close_popup()
        on_pick(value)
    menu = ChoiceMenu(options, current, anchor.w, pick)
    menu.scale = k
    mw, mh = menu.w * k, menu.h * k
    x = min(max(6.0, ax + (anchor.w * k - mw) / 2), scene.css_w - mw - 6)
    y = ay + (anchor.h + 6) * k
    if y + mh > scene.css_h - 6:
        y = ay - 6 * k - mh
    menu.x, menu.y = x, max(6.0, min(y, scene.css_h - mh - 6))
    menu.alpha, menu.dy = 0.0, -6.0
    scene.open_popup(menu)
    menu.animate(160, "out", alpha=1.0, dy=0.0)
    if closed is not None:
        _when_gone(scene, menu, closed)
    return menu


def _when_gone(scene, menu, closed):
    """closed() once the menu is no longer the scene's popup (chosen, pressed outside, Escape)."""
    def check():
        if scene.popup is menu:
            QTimer.singleShot(120, check)
        else:
            closed()
    QTimer.singleShot(120, check)


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
    """Where a song is: a thin bar with a dot, the time gone and the length; it moves on by itself while
    playing (the position comes with the time it was taken)."""

    def __init__(self, w, position, updated_at, duration, playing):
        super().__init__(0, 0, w, 40)
        self.position, self.duration, self.playing = position or 0.0, duration or 0.0, playing
        try:
            self.taken = datetime.datetime.fromisoformat(str(updated_at).replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            self.taken = time.time()
        self._ticking = False

    def now(self):
        pos = self.position + ((time.time() - self.taken) if self.playing else 0.0)
        return max(0.0, min(self.duration or pos, pos))

    def _tick(self):
        self._ticking = False
        if self.scene is not None:
            self.changed()

    def paint(self, p):
        pos = self.now()
        t = pos / self.duration if self.duration else 0.0
        p.setPen(Qt.NoPen)
        p.setBrush(ui.resolve(self.scene, "btn_fill_strong"))
        p.drawRoundedRect(QRectF(0, 8, self.w, 4), 2, 2)
        accent = ui.resolve(self.scene, "accent_blue")
        p.setBrush(accent)
        p.drawRoundedRect(QRectF(0, 8, self.w * t, 4), 2, 2)
        p.drawEllipse(QPointF(self.w * t, 10), 7, 7)
        f, ink2 = ui.font(12), ui.resolve(self.scene, "ink2")
        _text(p, _clock(pos), f, ink2, 0, 22)
        if self.duration:
            _text(p, _clock(self.duration), f, ink2, 0, 22, "r", self.w)
        if self.playing and not self._ticking:
            self._ticking = True
            QTimer.singleShot(1000, self._tick)
