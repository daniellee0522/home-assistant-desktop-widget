"""Recipe: days until a date. Settings (a name and a date), a ring that fills as the day comes, nothing to fetch, redrawn
every hour. Copy it, rename `id`, change what is drawn."""
import datetime

from PySide6.QtCore import QRectF

from widgetkit import charts
from widgetkit.definition import Field, WidgetDef
from widgetkit.theme import paragraph, text

PAD = 24


def days_left(ctx):
    """Whole days from today to the date in the settings (negative once it has passed), or None if it is not a date."""
    try:
        target = datetime.date.fromisoformat(ctx.config["date"].strip())
    except ValueError:
        return None
    return (target - datetime.datetime.fromtimestamp(ctx.now).date()).days


def draw(p, th, W, H, ctx):
    left = days_left(ctx)
    area = QRectF(PAD, PAD, W - 2 * PAD, H - 2 * PAD)
    if left is None:
        paragraph(p, th, "secondary", "Set a date like 2026-12-31 in the settings", area, "c", max_lines=3)
        return
    horizon = max(1, int(ctx.config["horizon"]))
    inside = charts.ring(p, th, QRectF(area.center().x() - area.height() * 0.5, area.top(), area.height(), area.height()),
                         1 - min(1.0, max(0, left) / horizon), th.accent(ctx.config["color"]))
    text(p, th, "display", str(max(0, left)), inside.left(), inside.center().y() - 34, inside.width(), "c")
    text(p, th, "caption", "days" if left != 1 else "day", inside.left(), inside.center().y() + 14, inside.width(), "c")
    text(p, th, "label", ctx.config["name"], PAD, H - PAD - 16, W - 2 * PAD, "c")


WIDGET = WidgetDef(
    id="example.countdown", name={"en": "Countdown", "zh": "倒數日"}, size="2x2", sizes=("2x4",),
    config=[Field("name", "text", "Holiday", {"en": "Name", "zh": "名稱"}),
            Field("date", "text", "2026-12-31", {"en": "Date (YYYY-MM-DD)", "zh": "日期 (YYYY-MM-DD)"}),
            Field("horizon", "number", 100, {"en": "The ring fills over (days)", "zh": "圓環用幾天填滿"}, minimum=1, maximum=3650),
            Field("color", "choice", "blue", {"en": "Colour", "zh": "顏色"}, options=("blue", "green", "red", "teal", "yellow"),
                  choices={"blue": {"en": "Blue", "zh": "藍"}, "green": {"en": "Green", "zh": "綠"}, "red": {"en": "Red", "zh": "紅"},
                           "teal": {"en": "Teal", "zh": "青"}, "yellow": {"en": "Yellow", "zh": "黃"}})],
    sources=[], draw=draw, tick=3600)
