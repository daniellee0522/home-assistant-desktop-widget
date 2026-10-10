"""Things that are pressed or typed into: buttons, toggles, a field, a slider, segments, a stepper, icons.

Each draws into a rect in a `state` ("", "hover", "pressed", "disabled", and for a field "focus") and, when given a
`hits` map and an `id`, records where it is so a host can tell what a click landed on:

    hits = HitMap()
    button(p, th, rect, "Start", color, hits=hits, id="start")
    hits.at(x, y)        # -> "start" (the topmost thing there), or None

Feedback is at pointer-down: a pressed control shrinks a little about its centre (PRESS_SCALE). Anything small is
still pressed within MIN_HIT of it (HitMap). Words and thin marks use `th.legible(colour)`, fills use the colour.
"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPen

from nativeui import style, ui

from .theme import MIN_HIT, line_height, localize, role_font, text

PRESS_SCALE = 0.96
KNOB_SHADOW = ((3, 14), (1, 26))


class HitMap:
    """Rects with names, in the order they were drawn: the last one drawn over a point is what the point is on."""

    def __init__(self):
        self.items = []
        self.drawn = []                 # (rect as drawn, id): before it was made big enough to press

    def add(self, rect, id):
        """Recorded no smaller than MIN_HIT each way (a small drawn thing is still easy to press)."""
        if id is not None:
            self.drawn.append((QRectF(rect), id))
            r = QRectF(rect)
            dx, dy = max(0.0, (MIN_HIT - r.width()) / 2), max(0.0, (MIN_HIT - r.height()) / 2)
            self.items.append((r.adjusted(-dx, -dy, dx, dy), id))

    def at(self, x, y):
        for rect, id in reversed(self.items):
            if rect.contains(QPointF(x, y)):
                return id
        return None

    def clear(self):
        self.items.clear()
        self.drawn.clear()


def _input_line(p, th, x, mid, w, value, caret, preedit, focused, color, caret_color):
    """The text of an input in the room x..x+w, centred on `mid`: the caret after `caret` characters, the text still
    being composed underlined at the caret, and the line shifted left so the caret is always in view."""
    f = role_font("body")
    before, after = value[:caret], value[caret:]
    wb, wp = ui.text_width(before, f), ui.text_width(preedit, f)
    shift = max(0.0, wb + wp - w + 4) if focused else 0.0
    top = mid - line_height("body") / 2
    p.save()
    p.setClipRect(QRectF(x - 2, mid - 24, w + 4, 48))
    text(p, th, "body", before + preedit + after, x - shift, top, color=color)
    if preedit:
        p.fillRect(QRectF(x - shift + wb, top + line_height("body") + 1, wp, 1.5), color)
    if focused:
        p.fillRect(QRectF(x - shift + wb + wp + 1, mid - 11, 2, 22), caret_color)
    p.restore()


def _press(p, rect, state):
    """Open a group drawn pressed (scaled about the centre of `rect`). Always pair with p.restore()."""
    p.save()
    if state == "pressed":
        c = rect.center()
        p.translate(c)
        p.scale(PRESS_SCALE, PRESS_SCALE)
        p.translate(-c)


def _shade(color, state):
    """The colour a control takes while it is hovered, pressed or disabled."""
    c = QColor(color)
    if state == "pressed":
        return c.darker(112)
    if state == "hover":
        return c.lighter(108)
    if state == "disabled":
        c.setAlphaF(0.35)
    return c


def _faded(color, state):
    c = QColor(color)
    if state == "disabled":
        c.setAlphaF(0.4)
    return c


def _wash(th, color, state):
    return th.faint(color, {"pressed": 0.30, "hover": 0.24}.get(state, 0.16))


def _icon(p, name, color, rect, size=None):
    c = QColor(color)
    style.center_icon(p, name, (c.red(), c.green(), c.blue(), c.alphaF()), rect, size)


def icon(p, name, color, rect, size=None):
    """An icon ("mdi:...") centred in `rect`, `size` across."""
    _icon(p, name, color, rect, size)


def icon_badge(p, name, color, rect, glyph=None):
    """An icon in a coloured disc: a shortcut, a device, a status."""
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawEllipse(rect)
    p.restore()
    _icon(p, name, QColor(255, 255, 255), rect, glyph or rect.width() * 0.56)


def button(p, th, rect, label, color, kind="filled", icon_name=None, state="", hits=None, id=None,
           role="body", glyph=20):
    """kind: "filled" (white words on the colour), "tinted" (the colour's words on a wash of it), "plain" (words
    only). A capsule as tall as `rect` (BUTTON_H is the usual)."""
    r = rect.height() / 2
    _press(p, rect, state)
    p.setPen(Qt.NoPen)
    fg = th.on_accent
    if kind == "filled":
        p.setBrush(_shade(color, state))
        p.drawRoundedRect(rect, r, r)
    else:
        if kind == "tinted":
            p.setBrush(_wash(th, color, state))
            p.drawRoundedRect(rect, r, r)
        fg = th.legible(color)
    fg = _faded(fg, state)
    f = role_font(role)
    label = localize(label)
    gap, isz = (10, glyph) if icon_name else (0, 0)
    w = ui.text_width(label, f) + (isz + gap)
    left = rect.center().x() - w / 2
    if icon_name:
        _icon(p, icon_name, fg, QRectF(left, rect.top(), isz, rect.height()), isz)
    style.center_text(p, label, f, fg, QRectF(left + isz + gap, rect.top(), w - isz - gap, rect.height()), "line")
    p.restore()
    if state != "disabled" and hits is not None:
        hits.add(rect, id)


def icon_button(p, th, rect, name, color, filled=False, state="", hits=None, id=None, glyph=0.5):
    """A round button holding only an icon."""
    _press(p, rect, state)
    p.setPen(Qt.NoPen)
    p.setBrush(_shade(color, state) if filled else _wash(th, color, state))
    p.drawEllipse(rect)
    fg = th.on_accent if filled else th.legible(color)
    _icon(p, name, _faded(fg, state), rect, rect.width() * glyph)
    p.restore()
    if state != "disabled" and hits is not None:
        hits.add(rect, id)


def search_bar(p, th, rect, label, icon_name, trailing_icon=None, state="", hits=None, id=None, trailing_id=None,
               value="", focused=False, caret=0, preedit="", dim_label=False):
    """A capsule asking for something: an icon, its words, and an icon at the far end (a microphone). The whole bar is
    recorded as `id`, and the end icon, drawn over it, as `trailing_id`. Made an input with `**ctx.text_input(id)`:
    then `label` is what it shows while empty, and typed text, a caret and composing text replace it."""
    h, r = rect.height(), rect.height() / 2
    _press(p, rect, state)
    ring = th.accent("blue") if focused else None
    p.setPen(QPen(ring or th.faint(None, 0.34), 3 if focused else 2))
    p.setBrush(th.faint(None, 0.2 if state == "pressed" else 0.12))
    p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), r - 1, r - 1)
    pad = h * 0.18
    _icon(p, icon_name, th.ink1, QRectF(rect.left() + pad, rect.top(), h * 0.5, h), h * 0.4)
    x = rect.left() + pad + h * 0.5 + 8
    end = rect.right() - pad - h * 0.5 - 8 if trailing_icon else rect.right() - pad
    if value or preedit or focused:
        _input_line(p, th, x, rect.center().y(), end - x, value, caret, preedit, focused, th.ink1, ring or th.ink1)
        if not value and not preedit:
            text(p, th, "launcher_label", label, x + 4, rect.center().y() - line_height("launcher_label") / 2, end - x - 4,
                 color=th.ink2)
    else:
        text(p, th, "launcher_label", label, x, rect.center().y() - line_height("launcher_label") / 2, end - x,
             color=th.ink2 if dim_label else None)
    tr = QRectF(rect.right() - pad - h * 0.5, rect.top(), h * 0.5, h)
    if trailing_icon:
        _icon(p, trailing_icon, th.ink1, tr, h * 0.36)
    p.restore()
    if hits is not None:
        hits.add(rect, id)
        if trailing_icon and trailing_id is not None:
            hits.add(tr, trailing_id)


def drop_zone(p, th, rect, active, label, icon_name="mdi:image-plus-outline", radius=28, color=None):
    """Where files may be dropped: a dashed outline that fills with the accent while files are dragged over it."""
    color = color or th.accent("blue")
    p.save()
    if active:
        p.setPen(Qt.NoPen)
        p.setBrush(th.faint(color, 0.24))
        p.drawRoundedRect(rect, radius, radius)
    pen = QPen(color if active else th.faint(None, 0.5), 2, Qt.DashLine)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius, radius)
    p.restore()
    cy = rect.center().y()
    _icon(p, icon_name, th.legible(color) if active else th.ink2, QRectF(rect.left(), cy - 40, rect.width(), 44), 38)
    text(p, th, "label", label, rect.left() + 10, cy + 10, rect.width() - 20, "c",
         th.legible(color) if active else th.ink2)


def toggle(p, th, rect, on, color, state="", hits=None, id=None):
    """A switch: a capsule and a knob at the end it is set to; the knob stretches while pressed. `rect` is the
    capsule (about 52 x 32)."""
    h = rect.height()
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(_shade(color, state) if on else th.faint(None, 0.3))
    p.drawRoundedRect(rect, h / 2, h / 2)
    k = h - 6
    kw = k + (4 if state == "pressed" else 0)
    x = rect.right() - 3 - kw if on else rect.left() + 3
    knob = QRectF(x, rect.top() + 3, kw, k)
    style.shadow(p, knob, k / 2, KNOB_SHADOW, dy=1.5)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 120 if state == "disabled" else 255))
    p.drawRoundedRect(knob, k / 2, k / 2)
    p.restore()
    if state != "disabled" and hits is not None:
        hits.add(rect, id)


def segmented(p, th, rect, labels, selected, color=None, hits=None, id=None):
    """Choices side by side in a track, the selected one raised on a soft shadow. Each choice is recorded as
    (id, index) when `id` is given."""
    n = len(labels)
    cw = (rect.width() - 4) / n
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(th.faint(None, 0.16))
    p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
    pill = QRectF(rect.left() + 2 + selected * cw, rect.top() + 2, cw, rect.height() - 4)
    if not color:
        style.shadow(p, pill, pill.height() / 2, ((3, 10), (1, 18)), dy=1)
    p.setPen(Qt.NoPen)
    p.setBrush(color or (QColor(255, 255, 255, 245) if th.name == "light" else QColor(255, 255, 255, 70)))
    p.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
    p.restore()
    f = role_font("label")
    for i, s in enumerate(labels):
        s = localize(s)
        on = i == selected
        fg = (th.on_accent if color else th.ink1) if on else th.ink2
        cell = QRectF(rect.left() + 2 + i * cw, rect.top(), cw, rect.height())
        style.center_text(p, s, f, fg, cell, "line")
        if hits is not None:
            hits.add(cell, (id, i))


def slider(p, th, rect, value, color, state="", hits=None, id=None):
    """A track with a knob; the knob stays inside `rect` (its ends are the value's 0 and 1). `rect` is as tall as
    the knob; the track runs across its middle."""
    k = rect.height()
    track = QRectF(rect.left() + k / 2, rect.center().y() - 3, rect.width() - k, 6)
    x = track.left() + track.width() * max(0.0, min(1.0, value))
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(th.faint(None, 0.22))
    p.drawRoundedRect(track, 3, 3)
    p.setBrush(color)
    p.drawRoundedRect(QRectF(track.left(), track.top(), x - track.left(), 6), 3, 3)
    d = k - 2 + (2 if state == "pressed" else 0)
    knob = QRectF(x - d / 2, rect.center().y() - d / 2, d, d)
    style.shadow(p, knob, d / 2, KNOB_SHADOW, dy=1.5)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255))
    p.drawEllipse(knob)
    p.restore()
    if hits is not None:
        hits.add(rect, id)


def field(p, th, rect, value="", placeholder="", state="", icon_name=None, color=None, hits=None, id=None,
          caret=None, preedit="", focused=None):
    """A one-line text field (FIELD_H tall). Focused (state "focus", or focused=True) it has its ring and a caret at
    `caret` (the end by default); `preedit` is text an input method is still composing. A press on it is recorded
    as `id`; typing is the host's business (it owns the string)."""
    focused = (state == "focus") if focused is None else focused
    color = color or th.accent("blue")
    r = min(rect.height() / 2, 14)
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 150) if th.name == "light" else QColor(0, 0, 0, 70))
    p.drawRoundedRect(rect, r, r)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(color if focused else th.faint(None, 0.22), 2 if focused else 1))
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), r, r)
    p.restore()
    x = rect.left() + 14
    if icon_name:
        _icon(p, icon_name, th.ink2, QRectF(x, rect.top(), 20, rect.height()), 18)
        x += 28
    mid = rect.center().y()
    if value or preedit or focused:
        _input_line(p, th, x, mid, rect.right() - 14 - x, value, len(value) if caret is None else caret, preedit,
                    focused, th.ink1, color)
        if not value and not preedit:
            text(p, th, "body", placeholder, x + 4, mid - line_height("body") / 2, rect.right() - 14 - x - 4,
                 color=th.ink2)
    else:
        text(p, th, "body", placeholder, x, mid - line_height("body") / 2, rect.right() - 14 - x, color=th.ink2)
    if state != "disabled" and hits is not None:
        hits.add(rect, id)


def stepper(p, th, rect, color, hits=None, id=None):
    """A − and a + side by side in one capsule; recorded as (id, -1) and (id, 1)."""
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(th.faint(None, 0.16))
    p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
    p.setBrush(th.faint(None, 0.3))
    p.drawRect(QRectF(rect.center().x() - 0.5, rect.top() + 7, 1, rect.height() - 14))
    p.restore()
    halves = (QRectF(rect.left(), rect.top(), rect.width() / 2, rect.height()),
              QRectF(rect.center().x(), rect.top(), rect.width() / 2, rect.height()))
    for half, name, delta in zip(halves, ("mdi:minus", "mdi:plus"), (-1, 1)):
        _icon(p, name, th.legible(color), half, 18)
        if hits is not None:
            hits.add(half, (id, delta))


def checkbox(p, th, rect, on, color, hits=None, id=None):
    """A round tick box."""
    p.save()
    p.setPen(Qt.NoPen)
    if on:
        p.setBrush(color)
        p.drawEllipse(rect)
        p.restore()
        _icon(p, "mdi:check", th.on_accent, rect, rect.width() * 0.66)
    else:
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(th.faint(None, 0.5), 2))
        p.drawEllipse(rect.adjusted(1, 1, -1, -1))
        p.restore()
    if hits is not None:
        hits.add(rect, id)
