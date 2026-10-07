"""The house style of every screen, in one place: what a piece of text is (its role, and so its size, weight
and colour), how a scrolling box fades at its ends, how deep a shadow is, how a floating pane looks, the
backing that keeps words readable over glass, and how things are placed: centred in a box by what is
actually drawn, laid on an even grid, and the one remove badge.

Screens ask for a role, never for a size: `style.label("title", text)`. A new screen or control uses these
and, when it needs something new, adds it here first. (CLAUDE.md lists the rules.)
"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPen

from . import render



# role: (px, weight, colour token). Colour tokens are the scene's (nativeui/ui.py INK): ink1 is for what is
# read, ink2 for what is said about it; never lighter than ink2, never on less than a READABLE backing.
TEXT = {
    "title": (19.5, QFont.Bold, "ink1"),          # what a screen or a card is about
    "detail_title": (22, QFont.Bold, "ink1"),
    "home_pill": (23, QFont.Bold, "ink1"),
    "home_pill_sub": (19, QFont.Medium, "ink2"),
    "home_chip": (22, QFont.DemiBold, "ink1"),
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
    "empty": (15, QFont.Normal, "white"),         # a message over a picture (an empty preview)

    # Settings and the widget editor: a denser window, read close up
    "header": (15, QFont.Bold, "ink1"),           # the window's title
    "header_sub": (11.5, QFont.Normal, "ink2"),   # under it: connected, what the page is for
    "group": (12, QFont.Bold, "ink2"),            # a heading over a group of settings or a column
    "field": (12, QFont.Normal, "ink2"),          # what a field, a slider or a choice sets
    "hint": (11.5, QFont.Normal, "ink2"),         # a note, a result, nothing found
    "tiny": (10.5, QFont.Normal, "ink2"),         # a unit beside a small field

    # The Home panel, drawn in its own units (half a px each: the sizes are twice the others')
    "home_title": (38, QFont.ExtraBold, "ink1"),  # 我的家
    "home_category": (32, QFont.ExtraBold, "ink1"),   # the open capsule's title
    "home_sheet": (30, QFont.Bold, "ink1"),       # a sheet's title
    "home_room": (27, QFont.Bold, "ink1"),        # a room's heading
    "home_status": (21, QFont.DemiBold, "ink2"),  # beside it: its temperature and humidity
    "home_body": (24, QFont.Normal, "ink2"),      # a message in the room list
    "home_hint": (20, QFont.Medium, "ink2"),      # how to use what is shown
    "home_section": (20, QFont.Bold, "ink2"),     # a heading in a sheet
}

# A box that scrolls fades out over this many of its px at an end with more beyond it, everywhere.
SCROLL_FADE = 24

# Floating panes (menus, a carried row or tile): their corners and their shadow, layered soft rectangles.
POPUP_RADIUS = 16
SHADOW = ((24, 9), (18, 9), (12, 9), (6, 9))      # (spread, alpha) from the outside in
LIFT_SHADOW = ((12, 16), (6, 26))

# What lies under words drawn over glass (the panel's detail): enough that ink2 reads on any desktop.
READABLE = {"dark": (22, 24, 28, 0.62), "light": (246, 247, 249, 0.66)}


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


# ---------------------------------------------------------------------------------- placing things
# Nothing is centred by hand-tuned baselines: these place text and icons by what is drawn.

def text_path(text, f, rect, align="cap"):
    """The outline of `text` in font `f` centred in `rect`:
    align="cap"  across by its ink, down by the font's capital height: words or numbers in a row of cells
                 (a calendar's days, a weekday row) keep one baseline and sit in the middle of their cells;
    align="ink"  by its ink both ways: one mark alone in a shape (a number in a circle, a badge);
    align="line" by its line box, as a text field or a button's words are."""
    path = render.text_path(QPointF(0, 0), f, text, 0, 0)
    ink = path.boundingRect()
    fm = QFontMetricsF(f)
    if align == "line":
        dx = rect.left() + (rect.width() - fm.horizontalAdvance(text) / 10 * render.HSCALE) / 2
        dy = rect.top() + (rect.height() - fm.height() / 10) / 2 + fm.ascent() / 10
    else:
        dx = rect.center().x() - ink.center().x()
        dy = rect.center().y() - ink.center().y() if align == "ink" else rect.center().y() + fm.capHeight() / 20
    path.translate(dx, dy)
    return path


def center_text(p, text, f, color, rect, align="cap"):
    """Draw `text` centred in `rect` (see text_path); returns the box of its ink."""
    path = text_path(text, f, rect, align)
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(color if isinstance(color, QColor) else render.parse_color(color))
    p.drawPath(path)
    p.restore()
    return path.boundingRect()


def center_icon(p, name, color, rect, size=None):
    """An icon in the middle of `rect`, `size` across (the smaller side of rect by default)."""
    size = size or min(rect.width(), rect.height())
    render.draw_icon(p, name, color, QRectF(rect.center().x() - size / 2, rect.center().y() - size / 2,
                                            size, size))


def grid(rect, cols, rows, gap_x=0.0, gap_y=0.0):
    """`rect` cut into rows x cols cells of one size, gap_x / gap_y between them: [[QRectF] per row]."""
    cw = (rect.width() - gap_x * (cols - 1)) / cols
    ch = (rect.height() - gap_y * (rows - 1)) / rows
    return [[QRectF(rect.left() + c * (cw + gap_x), rect.top() + r * (ch + gap_y), cw, ch) for c in range(cols)]
            for r in range(rows)]


REMOVE_FILL = QColor(255, 91, 74, 245)               # a remove badge's red


def remove_badge(p, rect, fill=REMOVE_FILL, shadow=True):
    """The one remove badge (a cross in a disc, or in a capsule when rect is wider than tall), its cross an
    icon centred by its own box, never a cross character placed by a baseline."""
    p.save()
    p.setPen(Qt.NoPen)
    r = min(rect.width(), rect.height()) / 2
    if shadow:
        p.setBrush(QColor(0, 0, 0, 50))
        p.drawRoundedRect(rect.translated(0, r * 0.12), r, r)
    p.setBrush(fill)
    p.drawRoundedRect(rect, r, r)
    center_icon(p, "mdi:close", "#ffffff", rect, r * 1.2)
    p.restore()
