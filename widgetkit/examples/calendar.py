"""The program's calendar, remade with the kit; a press anywhere on it opens the Windows Calendar app."""
import calendar as pycal
import datetime

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor

from nativeui import style
from widgetkit import faces
from widgetkit.definition import Field, WidgetDef, open_app
from widgetkit.theme import role_font, text

PAD = 26
RED = QColor("#ff3b30")
APP = "outlookcal:"                           # the Calendar app (Mail and Calendar); "app:outlookcal" is what it asks for


def month_cells(today, first_weekday):
    """(weeks, [(row, column, day)]) of the month `today` is in; columns start on `first_weekday` (0 Monday .. 6 Sunday)."""
    cal = pycal.Calendar(firstweekday=first_weekday)
    weeks = cal.monthdayscalendar(today.year, today.month)
    return len(weeks), [(r, c, d) for r, week in enumerate(weeks) for c, d in enumerate(week) if d]


def draw(p, th, W, H, ctx):
    ink, ink2 = faces.solid(p, th, W, H)
    today = datetime.datetime.fromtimestamp(ctx.now).date()
    zh = ctx.lang.startswith("zh")
    first = 6 if ctx.config["week_starts"] == "sun" else 0
    month = "%d月" % today.month if zh else today.strftime("%B")
    text(p, th, "calendar_month", month, PAD + 4, PAD - 2, W - 2 * PAD, color=RED)
    letters = "一二三四五六日" if zh else "MTWTFSS"
    heads = [letters[(first + i) % 7] for i in range(7)]
    weeks, days = month_cells(today, first)
    cells = style.grid(QRectF(PAD, PAD + 34, W - 2 * PAD, H - 2 * PAD - 34 + 6), 7, 1 + weeks)
    for c, h in enumerate(heads):
        style.center_text(p, h, role_font("calendar_head"), ink2, cells[0][c])
    df = role_font("calendar_day")
    disc = min(cells[1][0].width(), cells[1][0].height()) * 0.46
    for r, c, d in days:
        cell = cells[1 + r][c]
        weekend = (first + c) % 7 in (5, 6)
        if d == today.day:
            p.setPen(Qt.NoPen)
            p.setBrush(ink)
            p.drawEllipse(cell.center(), disc, disc)
            style.center_text(p, str(d), df, QColor(255, 255, 255) if ink.lightness() < 128 else QColor(17, 17, 19), cell, "ink")
        else:
            style.center_text(p, str(d), df, ink2 if weekend else ink, cell)
    ctx.hits.add(QRectF(0, 0, W, H), "open")
    if ctx.pressed == "open":                                           # the whole card gives a little
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 22) if th.name == "light" else QColor(255, 255, 255, 18))
        p.drawPath(faces.card_path(th, W, H))
        p.restore()


def on_tap(id, ctx):
    if id == "open":
        return open_app(APP)


WIDGET = WidgetDef(
    id="example.calendar", name={"en": "Calendar", "zh": "行事曆"}, size="2x2",
    config=[Field("week_starts", "choice", "sun", {"en": "Week starts on", "zh": "每週從"}, options=("sun", "mon"),
                  choices={"sun": {"en": "Sunday", "zh": "週日"}, "mon": {"en": "Monday", "zh": "週一"}})],
    sources=[], draw=draw, on_tap=on_tap, permissions=("app:outlookcal",), tick=30, background="solid")
