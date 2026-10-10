"""This computer's battery, memory and disk, from the system source."""
from PySide6.QtCore import QRectF

from widgetkit import charts
from widgetkit.definition import Field, WidgetDef
from widgetkit.sources import SystemSource
from widgetkit.theme import text

PAD = 24


def gauge(p, th, rect, name, percent, color, note=""):
    side = min(rect.width(), rect.height() - 40)
    box = QRectF(rect.center().x() - side / 2, rect.top(), side, side)
    inner = charts.ring(p, th, box, (percent or 0) / 100, color, side * 0.13)
    text(p, th, "title", "--" if percent is None else "%d%%" % percent, inner.left(), inner.center().y() - 13,
         inner.width(), "c")
    text(p, th, "body", name, rect.left(), box.bottom() + 10, rect.width(), "c")
    if note:
        text(p, th, "caption", note, rect.left(), box.bottom() + 32, rect.width(), "c")


def draw(p, th, W, H, ctx):
    bat = ctx.data.get("battery") or {}
    mem = ctx.data.get("memory") or {}
    disk = ctx.data.get("disk") or {}
    note = "charging" if bat.get("charging") else ("plugged in" if bat.get("plugged") else "")
    bp = bat.get("percent")
    color = th.accent("green" if bp is None or bp > 30 else ("yellow" if bp > 15 else "red"))
    w = (W - 2 * PAD - 2 * 18) / 3
    h = H - 2 * PAD
    gauge(p, th, QRectF(PAD, PAD, w, h), "Battery" if bp is not None else "Power", bp, color, note or "no battery")
    gauge(p, th, QRectF(PAD + w + 18, PAD, w, h), "Memory", mem.get("percent"), th.accent("blue"))
    gauge(p, th, QRectF(PAD + 2 * (w + 18), PAD, w, h), "Disk %s" % ctx.config["drive"], disk.get("percent"),
          th.accent("teal"))


def widget_sources():
    return [SystemSource("battery", "battery", every=30), SystemSource("memory", "memory", every=10),
            SystemSource("disk", "disk", every=120, path_key="drive")]


WIDGET = WidgetDef(
    id="example.battery", name="Battery and memory", size="2x4",
    config=[Field("drive", "text", "C:/", "Disk")],
    sources=widget_sources(), draw=draw, permissions=("system",))
