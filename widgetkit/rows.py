"""Rows that lists and feeds are made of: a ticker, a headline."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainterPath

from nativeui import ui

from .theme import line_height, paragraph, role_font, text


def _triangle(p, color, cx, cy, size, up):
    h = size * 0.86
    path = QPainterPath()
    if up:
        path.moveTo(cx, cy - h / 2)
        path.lineTo(cx + size / 2, cy + h / 2)
        path.lineTo(cx - size / 2, cy + h / 2)
    else:
        path.moveTo(cx, cy + h / 2)
        path.lineTo(cx + size / 2, cy - h / 2)
        path.lineTo(cx - size / 2, cy - h / 2)
    path.closeSubpath()
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawPath(path)
    p.restore()


def quote_row(p, th, rect, name, value, up=True, color=None):
    """A ticker: a ▲ or ▼, its name, and its value at the right edge."""
    color = color or th.ink1
    mid = rect.center().y()
    _triangle(p, color, rect.left() + 7, mid, 12, up)
    lh = line_height("quote")
    vw = text(p, th, "quote", value, rect.left(), mid - lh / 2, rect.width(), "r")
    text(p, th, "quote", name, rect.left() + 22, mid - lh / 2, rect.width() - 22 - vw - 10)


def news_item(p, th, rect, source, headline, max_lines=2):
    """Who it is from over what it says (cut at `max_lines`). Returns the height used."""
    text(p, th, "news_source", source, rect.left(), rect.top(), rect.width())
    y = line_height("news_source") + 2
    return y + paragraph(p, th, "news_title", headline, QRectF(rect.left(), rect.top() + y, rect.width(), 999),
                         max_lines=max_lines, leading=1.08)


def news_height(width, headline, max_lines=2):
    """What `news_item` will take, to know before drawing whether another fits."""
    n = min(max_lines, len(ui.wrap_lines(headline, role_font("news_title"), width)))
    return line_height("news_source") + 2 + n * line_height("news_title") * 1.08
