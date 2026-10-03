"""The house style of every screen, in one place: what a piece of text is (its role, and so its size, weight
and colour), how a scrolling box fades at its ends, how deep a shadow is, how a floating pane looks, and
the backing that keeps words readable over glass.

Screens ask for a role, never for a size: `style.label("title", text)`. A new screen or control uses these
and, when it needs something new, adds it here first. (CLAUDE.md lists the rules.)
"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPen



# role: (px, weight, colour token). Colour tokens are the scene's (nativeui/ui.py INK): ink1 is for what is
# read, ink2 for what is said about it; never lighter than ink2, never on less than a READABLE backing.
TEXT = {
    "title": (19.5, QFont.Bold, "ink1"),          # what a screen or a card is about
    "eyebrow": (12.5, QFont.Medium, "ink2"),      # above a title: where it is
    "hero": (52, QFont.Light, "ink1"),            # the weather's temperature, alone and large
    "display": (40, QFont.Normal, "ink1"),        # the one big reading of a detail (24°, 60 %, 已上鎖)
    "meta": (13.5, QFont.DemiBold, "ink2"),       # under the display: 10 分鐘前
    "headline": (19, QFont.Bold, "ink1"),         # a song's title, a reading in a row
    "body": (15, QFont.Medium, "ink1"),           # rows of a list, a forecast's days
    "secondary": (14, QFont.Normal, "ink2"),      # under a headline: the artist
    "label": (13, QFont.Medium, "ink2"),          # what a value is (目前溫度, 模式)
    "value": (16, QFont.DemiBold, "ink1"),        # a value under its label (冷氣, 自動)
    "section": (14.5, QFont.Bold, "ink2"),        # a heading over a group of fields
    "caption": (12, QFont.Medium, "ink2"),        # small print: times under a bar, a range
    "menu": (15, QFont.Normal, "ink1"),           # a choice in a menu
}

# A box that scrolls fades out over this many of its px at an end with more beyond it, everywhere.
SCROLL_FADE = 24

# Floating panes (menus, a carried row or tile): their corners and their shadow, layered soft rectangles.
POPUP_RADIUS = 16
SHADOW = ((24, 9), (18, 9), (12, 9), (6, 9))      # (spread, alpha) from the outside in
LIFT_SHADOW = ((12, 16), (6, 26))

# What lies under words drawn over glass (the panel's detail): enough that ink2 reads on any desktop.
READABLE = {"dark": (22, 24, 28, 0.62), "light": (246, 247, 249, 0.66)}


def text_style(role):
    return TEXT[role]


def label(role, text="", **kw):
    """A Label of a role; kw are Label's own (x, y, w, align, wrap, overflow...); color= overrides."""
    from .ui import Label
    size, weight, color = TEXT[role]
    color = kw.pop("color", color)
    return Label(text, size, weight, color, **kw)


def font(role):
    from . import ui
    size, weight, _ = TEXT[role]
    return ui.font(size, weight)


def shadow(p, rect, radius, layers=SHADOW, dy=6):
    """A soft shadow under a rounded rectangle (rect: QRectF), a little below it."""
    p.save()
    p.setPen(Qt.NoPen)
    for spread, a in layers:
        p.setBrush(QColor(0, 0, 0, a))
        p.drawRoundedRect(QRectF(rect.x() - spread / 2, rect.y() - spread / 2 + dy, rect.width() + spread,
                                 rect.height() + spread), radius + spread / 2, radius + spread / 2)
    p.restore()


def popup_pane(p, scene, w, h, radius=POPUP_RADIUS):
    """A floating pane: its shadow, a solid fill and a hairline rim."""
    from . import ui
    shadow(p, QRectF(0, 0, w, h), radius)
    p.setBrush(ui.resolve(scene, "panel_solid"))
    p.setPen(QPen(ui.resolve(scene, "input_border"), 1))
    p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), radius, radius)


def readable_backing(theme):
    r, g, b, a = READABLE["dark" if theme == "dark" else "light"]
    return QColor(r, g, b, round(255 * a))
