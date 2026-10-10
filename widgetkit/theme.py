"""The colours and text a widget of the kit draws with: the program's own tokens, read and never changed."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter

from nativeui import render, style, ui

MIN_HIT = 44            # a thing that is pressed is at least this big to the pointer, however small it is drawn
BUTTON_H = 44
FIELD_H = 44


class Theme:
    """One look: a theme ("light"/"dark"), a glass style, and whether the widget is dimmed."""

    def __init__(self, theme="light", surface="classic", dim=False):
        self.name, self.surface, self.dim = theme, surface, dim
        self.tokens = render.tokens(theme, dim, surface)
        ink = ui.ui_tokens(theme, surface, dim)
        self.ink1, self.ink2 = render.parse_color(ink["ink1"]), render.parse_color(ink["ink2"])
        if dim:                                   # standby is clear glass over the desktop: ink is white, as the program's own is
            self.ink1, self.ink2 = QColor(255, 255, 255, 235), QColor(255, 255, 255, 150)
        self.on_accent = QColor(17, 17, 19, 235) if dim else QColor(255, 255, 255)   # what is drawn on a fill of an accent

    def accent(self, name):
        """A named accent ("blue", "green"...) or any CSS colour, as a QColor. In standby every accent is white (the
        program's standby look has one colour): do not tell two things apart by colour alone."""
        if self.dim:
            return QColor(255, 255, 255, 235)
        return render.parse_color(render.ACCENT.get(name, name))

    def legible(self, color):
        """`color` for words and thin marks: the accents are made for fills, so on light glass they are
        deepened until they can be read (the way iOS uses a darker system colour for text). White in standby."""
        if self.dim:
            return QColor(255, 255, 255, 235)
        c = QColor(color)
        return c.darker(150) if self.name == "light" else c.lighter(108)

    def faint(self, color=None, alpha=0.22):
        """A track or a rule: `color` (ink2 by default) made translucent."""
        c = QColor(color or self.ink2)
        c.setAlphaF(alpha)
        return c


def tracking(px):
    """Letter spacing for a size: large type is set tighter, small type a little looser (in px)."""
    if px >= 34:
        return -0.022 * px
    if px >= 24:
        return -0.014 * px
    if px >= 17:
        return -0.006 * px
    if px <= 13:
        return 0.01 * px
    return 0.0


# Roles the kit adds to the program's (nativeui/style.TEXT): where a screen of the kit needs a kind of text the
# program has none of. Same shape: (px, weight, colour token).
TEXT = {
    "launcher_label": (28, QFont.Medium, "ink1"),    # the words in a search bar
    "player_title": (27, QFont.Bold, "white"),       # a song's title over its cover's colour
    "player_artist": (20, QFont.Medium, "white"),
    "player_app": (16, QFont.DemiBold, "white"),     # where it plays
    "clock_day": (19, QFont.DemiBold, "ink2"),       # the day above a clock's time
    "calendar_month": (22, QFont.Bold, "ink1"),
    "calendar_head": (15, QFont.DemiBold, "ink2"),   # a weekday's letter
    "calendar_day": (17, QFont.DemiBold, "ink1"),
    "quote": (24, QFont.DemiBold, "ink1"),           # a ticker's name and its value
    "news_source": (17, QFont.Bold, "ink2"),     # who a headline is from
    "news_title": (22, QFont.Medium, "ink1"),        # the headline
}


MAX_LINE, MAX_PARAGRAPH = 1000, 4000    # characters of one line / one paragraph that are ever laid out (a feed may send more)

listeners = []                       # callbacks told when text had to be cut: cb(kind, role, wanted, shown, width)
drawn_listeners = []                 # callbacks told where every piece of text went: cb(role, text, QRectF)
pseudo = None                        # None, or a function str -> str applied to every word drawn (the studio's false languages)


def localize(s):
    """`s` as it is to be drawn: through the false language when one is on (see widgetkit.pseudo)."""
    return pseudo(s) if pseudo is not None and isinstance(s, str) else s


def _drawn(role, s, rect):
    for cb in list(drawn_listeners):
        cb(role, s, rect)


def _cut(kind, role, wanted, shown, width):
    for cb in list(listeners):
        cb(kind, role, wanted, shown, width)


def spec(role):
    return TEXT[role] if role in TEXT else style.TEXT[role]


def role_font(role):
    size, weight, _ = spec(role)
    return ui.font(size, weight, tracking(size))


def text(p, th, role, s, x, y, w=None, align="l", color=None):
    """One line of a text role (style.TEXT) with its top at y; `w` is the width it may take (cut with …) and
    what `align` ("l", "c", "r") is measured in. Returns the width drawn."""
    f = role_font(role)
    s = localize(s)[:MAX_LINE]
    color = color or {"ink1": th.ink1, "ink2": th.ink2, "white": QColor(255, 255, 255)}.get(spec(role)[2], th.ink2)
    if w is not None:
        full, s = s, fit(s, f, w)
        if s != full:
            _cut("line", role, full, s, w)
    tw = ui.text_width(s, f)
    if w is not None and align != "l":
        x += (w - tw) / (2 if align == "c" else 1)
    fm = render.QFontMetricsF(f)
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawPath(render.text_path(render.QPointF(0, 0), f, s, x, y + fm.ascent() / 10))
    p.restore()
    if drawn_listeners:
        _drawn(role, s, QRectF(x, y, tw, fm.height() / 10))
    return tw


def fit(s, f, width):
    if ui.text_width(s, f) <= width:
        return s
    while s and ui.text_width(s + "…", f) > width:
        s = s[:-1]
    return s + "…"


def line_height(role):
    return render.QFontMetricsF(role_font(role)).height() / 10


def smooth(p):
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)


def fit_text(p, th, s, rect, weight=QFont.Bold, color=None, max_px=240, font=None):
    """One line as large as fits `rect` (width and height of its ink), centred by its ink: the time on a clock face, a
    big number. `font(px)` gives another face (a narrow one for a clock's digits). For the size of ordinary text use a
    role (`text`)."""
    make = font or (lambda px: ui.font(px, weight))
    probe = render.text_path(render.QPointF(0, 0), make(100), s, 0, 0).boundingRect()
    if probe.width() <= 0 or probe.height() <= 0:
        return
    px = max(8.0, min(max_px, 100 * min(rect.width() / probe.width(), rect.height() / probe.height())))
    style.center_text(p, s, make(round(px * 2) / 2), color or th.ink1, rect, "ink")


def paragraph(p, th, role, s, rect, align="l", max_lines=None, color=None, leading=1.2):
    """Words wrapped to `rect`'s width (between Chinese characters too), `align` "l" or "c", cut at `max_lines`
    with … at the end of the last. Returns the height used."""
    f = role_font(role)
    s = localize(s)[:MAX_PARAGRAPH]
    lines = ui.wrap_lines(s, f, rect.width())
    if max_lines and len(lines) > max_lines:
        tail = (" " if " " in s else "").join(lines[max_lines - 1:])
        lines = lines[:max_lines - 1] + [ui.ellipsize(tail, f, rect.width())]
        _cut("lines", role, s, " / ".join(lines), rect.width())
    step = line_height(role) * leading
    for i, line in enumerate(lines):
        text(p, th, role, line, rect.left(), rect.top() + i * step, rect.width(), align, color)
    return step * len(lines)
