"""Clocks for several places. Drawn straight with the painter: the kit does not need to have a clock for one to be made."""
import datetime
import math
from zoneinfo import ZoneInfo

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPen

from widgetkit.definition import Field, WidgetDef
from widgetkit.theme import text

PAD = 22


def hand(p, c, r, angle, length, width, color):
    a = math.radians(angle - 90)
    p.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(c, QPointF(c.x() + math.cos(a) * r * length, c.y() + math.sin(a) * r * length))


def face(p, th, rect, now, label, offset_days):
    r = min(rect.width(), rect.height() - 52) / 2
    c = QPointF(rect.center().x(), rect.top() + r)
    p.save()
    p.setPen(QPen(th.faint(None, 0.4), 2))
    p.setBrush(th.faint(None, 0.1))
    p.drawEllipse(c, r, r)
    for i in range(12):                                         # the hours
        a = math.radians(i * 30 - 90)
        p.drawLine(QPointF(c.x() + math.cos(a) * r * 0.86, c.y() + math.sin(a) * r * 0.86),
                   QPointF(c.x() + math.cos(a) * r * 0.94, c.y() + math.sin(a) * r * 0.94))
    h, m, s = now.hour % 12, now.minute, now.second + now.microsecond / 1e6
    hand(p, c, r, (h + m / 60) * 30, 0.5, 5, th.ink1)
    hand(p, c, r, (m + s / 60) * 6, 0.78, 3.5, th.ink1)
    hand(p, c, r, s * 6, 0.86, 1.6, th.accent("yellow"))
    p.setPen(Qt.NoPen)
    p.setBrush(th.accent("yellow"))
    p.drawEllipse(c, 4, 4)
    p.restore()
    text(p, th, "body", label, rect.left(), rect.top() + 2 * r + 8, rect.width(), "c")
    day = {0: "", 1: " +1", -1: " -1"}.get(offset_days, "")
    text(p, th, "caption", now.strftime("%H:%M") + day, rect.left(), rect.top() + 2 * r + 30, rect.width(), "c")


def draw(p, th, W, H, ctx):
    zones = ctx.config["zones"][:4] or ["UTC"]
    here = datetime.datetime.fromtimestamp(ctx.now).astimezone()
    w = (W - 2 * PAD - 14 * (len(zones) - 1)) / len(zones)
    for i, z in enumerate(zones):
        key, _, name = z.partition("=")
        try:
            now = datetime.datetime.fromtimestamp(ctx.now, ZoneInfo(key.strip()))
        except Exception:                                       # a name that is not a time zone
            now, name = datetime.datetime.fromtimestamp(ctx.now, datetime.timezone.utc), key + " ?"
        diff = (now.date() - here.date()).days
        face(p, th, QRectF(PAD + i * (w + 14), PAD, w, H - 2 * PAD), now, name.strip() or key.split("/")[-1], diff)


WIDGET = WidgetDef(
    id="example.worldclock", name="World clock", size="2x4",
    config=[Field("zones", "list", ["Asia/Taipei=Taipei", "Europe/London=London", "America/New_York=New York",
                                    "Asia/Tokyo=Tokyo"], "Places", help="A time zone, or ZONE=Name (e.g. Asia/Tokyo=Tokyo).")],
    sources=[], draw=draw, tick=1)
