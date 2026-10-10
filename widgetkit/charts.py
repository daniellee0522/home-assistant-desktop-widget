"""Progress and statistics: rings, gauges, bars, columns, lines, donuts. Each draws into a rect and takes colours
from the caller; none draws text of its own except where a chart has labels (those come from the text roles)."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainterPath, QPen

from .theme import text


def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def _arc(p, rect, start, span, color, width, cap=Qt.RoundCap):
    """An arc of an ellipse inside `rect`: start/span in degrees, 0 at the top, clockwise."""
    p.setPen(QPen(color, width, Qt.SolidLine, cap))
    p.setBrush(Qt.NoBrush)
    p.drawArc(rect, round((90 - start) * 16), round(-span * 16))


def _inset(rect, width):
    return rect.adjusted(width / 2, width / 2, -width / 2, -width / 2)


def ring(p, th, rect, value, color, width=None):
    """A progress ring: the track all round, the value over it from the top. 0..1."""
    width = width or rect.width() * 0.13
    r = _inset(rect, width)
    p.save()
    _arc(p, r, 0, 359.99, th.faint(color, 0.22), width)
    if value > 0:
        _arc(p, r, 0, 360 * _clamp(value) if value < 1 else 359.99, color, width)
    p.restore()
    return r.adjusted(width / 2, width / 2, -width / 2, -width / 2)       # the room inside it


def rings(p, th, rect, values, colors, width=None, gap=None):
    """Concentric rings, the first outermost (an activity ring)."""
    width = width or rect.width() * 0.11
    gap = width * 0.18 if gap is None else gap
    for v, c in zip(values, colors):
        rect = ring(p, th, rect, v, c, width).adjusted(gap, gap, -gap, -gap)
    return rect


def gauge(p, th, rect, value, color, width=None, sweep=250):
    """A dial open at the bottom: 0..1 along `sweep` degrees."""
    width = width or rect.width() * 0.12
    r = _inset(rect, width)
    start = -sweep / 2
    p.save()
    _arc(p, r, start, sweep, th.faint(color, 0.22), width)
    if value > 0:
        _arc(p, r, start, sweep * _clamp(value), color, width)
    p.restore()


def bar(p, th, rect, value, color):
    """A horizontal progress bar as tall as `rect`, the value filling it from the left."""
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(th.faint(color, 0.22))
    p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
    w = max(rect.height(), rect.width() * _clamp(value)) if value > 0 else 0
    if w:
        p.setBrush(color)
        p.drawRoundedRect(QRectF(rect.left(), rect.top(), w, rect.height()), rect.height() / 2, rect.height() / 2)
    p.restore()


def segments(p, th, rect, value, color, count=10, gap=4):
    """A bar cut into `count` cells, the first `value` of them lit."""
    cw = (rect.width() - gap * (count - 1)) / count
    lit = round(_clamp(value) * count)
    p.save()
    p.setPen(Qt.NoPen)
    for i in range(count):
        p.setBrush(color if i < lit else th.faint(color, 0.22))
        p.drawRoundedRect(QRectF(rect.left() + i * (cw + gap), rect.top(), cw, rect.height()), 3, 3)
    p.restore()


def columns(p, th, rect, values, color, labels=None, mark=None, gap=None, label_role="caption"):
    """Vertical bars from a common floor. `labels` sit under them; the bar at index `mark` takes `color`
    and the rest are faint (today among the week)."""
    n = len(values)
    gap = gap if gap is not None else rect.width() / n * 0.28
    bw = (rect.width() - gap * (n - 1)) / n
    floor = rect.bottom() - (18 if labels else 0)
    top = max(max(values), 1e-9)
    p.save()
    p.setPen(Qt.NoPen)
    for i, v in enumerate(values):
        h = max(bw, (floor - rect.top()) * v / top)
        c = color if mark is None or i == mark else th.faint(color, 0.35)
        p.setBrush(c)
        x = rect.left() + i * (bw + gap)
        p.drawRoundedRect(QRectF(x, floor - h, bw, h), bw * 0.34, bw * 0.34)
        if labels:
            text(p, th, label_role, labels[i], x - gap / 2, floor + 4, bw + gap, "c")
    p.restore()


def _points(rect, values, lo, hi):
    n = len(values)
    return [QPointF(rect.left() + rect.width() * i / max(1, n - 1),
                    rect.top() + rect.height() * (1 - (v - lo) / (hi - lo))) for i, v in enumerate(values)]


def _curve(pts):
    path = QPainterPath(pts[0])
    for a, b in zip(pts, pts[1:]):
        mid = (a.x() + b.x()) / 2
        path.cubicTo(mid, a.y(), mid, b.y(), b.x(), b.y())
    return path


def line(p, th, rect, series, colors, fill=True, grid=3, labels=None, smooth=True, dot=True):
    """Lines over a shared range. `series`: lists of numbers (one line each). `grid` faint rules with their
    values at the left; `labels` along the foot. Returns the plot's rect."""
    allv = [v for s in series for v in s]
    lo, hi = min(allv), max(allv)
    if hi - lo < 1e-9:
        lo, hi = lo - 0.5, hi + 0.5
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad
    plot = QRectF(rect)
    if grid:
        plot.setLeft(rect.left() + 38)
    if labels:
        plot.setBottom(rect.bottom() - 18)
    p.save()
    for g in range(grid):
        y = plot.top() + plot.height() * g / max(1, grid - 1)
        p.setPen(QPen(th.faint(None, 0.18), 1, Qt.DashLine))
        p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        v = hi - (hi - lo) * g / max(1, grid - 1)
        text(p, th, "caption", ("%.0f" if hi - lo > 8 else "%.1f") % v, rect.left(), y - 17, 32, "r")
    if labels:
        for i, s in enumerate(labels):
            x = plot.left() + plot.width() * i / max(1, len(labels) - 1)
            text(p, th, "caption", s, x - 30, plot.bottom() + 4, 60, "c")
    for s, c in zip(series, colors):
        pts = _points(plot, s, lo, hi)
        path = _curve(pts) if smooth else QPainterPath(pts[0])
        if not smooth:
            for q in pts[1:]:
                path.lineTo(q)
        if fill:
            area = QPainterPath(path)
            area.lineTo(pts[-1].x(), plot.bottom())
            area.lineTo(pts[0].x(), plot.bottom())
            area.closeSubpath()
            g = QLinearGradient(0, plot.top(), 0, plot.bottom())
            top, bottom = QColor(c), QColor(c)
            top.setAlphaF(0.32)
            bottom.setAlphaF(0.0)
            g.setColorAt(0, top)
            g.setColorAt(1, bottom)
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawPath(area)
        p.setPen(QPen(c, 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        if dot:
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawEllipse(pts[-1], 4.5, 4.5)
    p.restore()
    return plot


def sparkline(p, th, rect, values, color, fill=True):
    """A line with no axes, for beside a number."""
    line(p, th, rect, [values], [color], fill=fill, grid=0, dot=True)


def donut(p, th, rect, parts, width=None, gap=3.0):
    """Shares of a whole as arcs, from the top clockwise. `parts`: [(value, color)]. Returns the room inside."""
    width = width or rect.width() * 0.16
    r = _inset(rect, width)
    total = sum(v for v, _ in parts) or 1.0
    # a gap between arcs is the cap's own length too: shorten each arc by it
    cap = math.degrees(width / 2 / (r.width() / 2))
    angle = 0.0
    p.save()
    _arc(p, r, 0, 359.99, th.faint(None, 0.12), width)
    for v, c in parts:
        span = 360 * v / total
        draw = span - gap - 2 * cap
        if draw > 0.5:
            _arc(p, r, angle + gap / 2 + cap, draw, c, width)
        angle += span
    p.restore()
    return r.adjusted(width / 2, width / 2, -width / 2, -width / 2)
