"""A tutorial widget: count the glasses of water drunk today. Small enough to read in one go, and it uses most of what a
widget can declare: settings, state kept between runs, taps, a spring, and a layout for each of four sizes.

    1. say what it is and what a person can change     -> WIDGET (id, name, sizes, config)
    2. keep its memory in `ctx.state`                    -> today(), history()
    3. draw it for the room it is given                  -> draw() chooses a layout by `ctx.size_name()`
    4. say what a press does                             -> on_tap()
"""
import datetime

from PySide6.QtCore import QRectF

from widgetkit import charts, controls
from widgetkit.definition import Field, WidgetDef
from widgetkit.theme import text

PAD = 22
BLUE = "blue"
# icon style -> (a glass drunk, a glass still to drink); "none" draws no glasses
STYLES = {"cup": ("mdi:cup-water", "mdi:cup-outline"), "drop": ("mdi:water", "mdi:water-outline"),
          "bottle": ("mdi:bottle-tonic-outline", "mdi:bottle-tonic-outline")}


# ---- 2. memory: today's count, and the days before it ---------------------------------------------------------------
def day_of(ctx):
    return datetime.datetime.fromtimestamp(ctx.now).date().isoformat()


def today(ctx):
    """Glasses drunk today (a new day starts at zero without anyone resetting anything)."""
    s = ctx.state
    return s.get("count", 0) if s.get("day") == day_of(ctx) else 0


def history(ctx, days=7):
    """[(date, glasses)] for the last `days` days ending today."""
    here = datetime.datetime.fromtimestamp(ctx.now).date()
    past = ctx.state.get("history", {})
    out = []
    for i in range(days - 1, -1, -1):
        d = here - datetime.timedelta(days=i)
        out.append((d, today(ctx) if i == 0 else past.get(d.isoformat(), 0)))
    return out


def add(ctx, n):
    """Change today's count by n (never below zero), moving yesterday's total into the history on the first change of a day."""
    s = ctx.state
    hist = dict(s.get("history", {}))
    if s.get("day") and s["day"] != day_of(ctx):
        hist[s["day"]] = s.get("count", 0)
        s = {"day": day_of(ctx), "count": 0}
    ctx.set_state(day=day_of(ctx), count=max(0, s.get("count", 0) + n),
                  history=dict(sorted(hist.items())[-60:]))


# ---- 3. drawing: one picture of the progress, laid out for the size ------------------------------------------------
def ring(p, th, ctx, rect, width_share=0.12):
    goal = ctx.config["goal"]
    shown = ctx.spring("ring", min(1.0, today(ctx) / goal))                  # eases when the count changes
    return charts.ring(p, th, rect, shown, th.accent(BLUE), rect.width() * width_share)


def plus_minus(p, th, ctx, x, y, d=56):
    for i, (id, icon, filled) in enumerate((("minus", "mdi:minus", False), ("plus", "mdi:plus", True))):
        controls.icon_button(p, th, QRectF(x + i * (d + 14), y, d, d), icon, th.accent(BLUE), filled=filled,
                             state="pressed" if ctx.pressed == id else "", hits=ctx.hits, id=id)


def glasses(p, th, ctx, rect, size, limit=12):
    """One icon for each glass of the goal (at most `limit`): the ones drunk in the accent, the rest faint, in rows that
    fit `rect`. Returns the height used."""
    style = ctx.config["icons"]
    if style not in STYLES:
        return 0
    drunk_icon, left_icon = STYLES[style]
    goal, n = ctx.config["goal"], today(ctx)
    shown = min(goal, limit)
    per_row = max(1, int(rect.width() // (size + 6)))
    for i in range(shown):
        r, c = divmod(i, per_row)
        cell = QRectF(rect.left() + c * (size + 6), rect.top() + r * (size + 6), size, size)
        done = i < n
        color = th.accent(BLUE) if done else th.faint(None, 0.5)
        controls.icon(p, drunk_icon if done else left_icon, color, cell, size)
    if goal > limit:                                       # more glasses than room: say how many more
        text(p, th, "caption", "+%d" % (goal - limit), rect.left() + (shown % per_row) * (size + 6), rect.top() + (shown // per_row) * (size + 6) + 4, 40)
    return ((shown - 1) // per_row + 1) * (size + 6)


def drop_in_ring(p, th, inner, size):
    """A water drop at the top of the ring's hollow, above the number."""
    controls.icon(p, "mdi:water", th.accent(BLUE), QRectF(inner.center().x() - size / 2, inner.top() + inner.height() * 0.13,
                                                        size, size), size)


def week_columns(p, th, ctx, rect, days):
    """The last `days` days as columns, today's the bright one."""
    data = history(ctx, days)
    labels = [d.strftime("%a")[:1] if not ctx.lang.startswith("zh") else "一二三四五六日"[d.weekday()] for d, _ in data]
    charts.columns(p, th, rect, [max(n, 0.001) for _, n in data] or [0], th.accent(BLUE), labels, mark=len(data) - 1)


def draw(p, th, W, H, ctx):
    size, goal, n = ctx.size_name(), ctx.config["goal"], today(ctx)
    if size == "1x1":                                       # one thing: the ring and the number in it; a press adds one
        inner = ring(p, th, ctx, QRectF(14, 14, W - 28, H - 28), 0.13)
        drop_in_ring(p, th, inner, 16)
        text(p, th, "title", str(n), inner.left(), inner.center().y() - 5, inner.width(), "c")
        ctx.hits.add(QRectF(0, 0, W, H), "plus")
    elif size == "2x2":                                     # the ring, what it counts, and the two buttons
        side = 190
        inner = ring(p, th, ctx, QRectF((W - side) / 2, PAD, side, side))
        drop_in_ring(p, th, inner, 26)
        text(p, th, "display", str(n), inner.left(), inner.center().y() - 24, inner.width(), "c")
        text(p, th, "caption", "/ %d" % goal, inner.left(), inner.center().y() + 28, inner.width(), "c")
        plus_minus(p, th, ctx, W / 2 - 63, H - PAD - 56)
    elif size == "2x4":                                     # the ring at the left; words, buttons and the week at the right
        side = H - 2 * PAD
        inner = ring(p, th, ctx, QRectF(PAD, PAD, side, side))
        drop_in_ring(p, th, inner, 30)
        text(p, th, "display", str(n), inner.left(), inner.center().y() - 22, inner.width(), "c")
        x = PAD + side + 30
        text(p, th, "eyebrow", "WATER TODAY" if not ctx.lang.startswith("zh") else "今天喝水", x, PAD + 4, W - x - PAD)
        text(p, th, "headline", ("%d of %d glasses" if not ctx.lang.startswith("zh") else "%d / %d 杯") % (n, goal), x,
             PAD + 24, W - x - PAD)
        used = glasses(p, th, ctx, QRectF(x, PAD + 56, W - x - PAD, 60), 22)
        week_columns(p, th, ctx, QRectF(x, PAD + 64 + used, W - x - PAD - 164, H - 2 * PAD - 64 - used), 7)
        plus_minus(p, th, ctx, W - PAD - 126, H - PAD - 56, 56)
    else:                                                   # 4x4: all of that, taller, with the month
        side = 250
        inner = ring(p, th, ctx, QRectF(PAD, PAD, side, side))
        drop_in_ring(p, th, inner, 34)
        text(p, th, "hero", str(n), inner.left(), inner.center().y() - 28, inner.width(), "c")
        text(p, th, "secondary", "of %d glasses" % goal if not ctx.lang.startswith("zh") else "目標 %d 杯" % goal,
             inner.left(), inner.center().y() + 40, inner.width(), "c")
        x = PAD + side + 30
        text(p, th, "title", "Water" if not ctx.lang.startswith("zh") else "喝水", x, PAD + 6, W - x - PAD)
        pct = round(100 * min(1.0, n / goal))
        text(p, th, "secondary", ("%d%% of today's goal" if not ctx.lang.startswith("zh") else "已達今日目標的 %d%%") % pct,
             x, PAD + 36, W - x - PAD)
        plus_minus(p, th, ctx, x, PAD + 80, 64)
        glasses(p, th, ctx, QRectF(x, PAD + 160, W - x - PAD, 90), 30)
        week_columns(p, th, ctx, QRectF(PAD, PAD + side + 34, W - 2 * PAD, H - 2 * PAD - side - 34), 14)


# ---- 4. a press -----------------------------------------------------------------------------------------------------
def on_tap(id, ctx):
    if id == "plus":
        add(ctx, 1)
    elif id == "minus":
        add(ctx, -1)


# ---- 1. what it is -------------------------------------------------------------------------------------------------
WIDGET = WidgetDef(
    id="example.water", name={"en": "Water", "zh": "喝水"},
    size="2x2",                                             # the size it is added at,
    sizes=("1x1", "2x4", "4x4"),                            # and the others a person may resize it to
    config=[Field("goal", "number", 8, {"en": "Daily goal (glasses)", "zh": "每日目標(杯)"}, minimum=1, maximum=30),
            Field("icons", "choice", "cup", {"en": "Glass icons", "zh": "杯子圖示"}, options=("cup", "drop", "bottle", "none"),
                  choices={"cup": {"en": "Cups", "zh": "杯子"}, "drop": {"en": "Drops", "zh": "水滴"},
                           "bottle": {"en": "Bottles", "zh": "瓶子"}, "none": {"en": "None", "zh": "不顯示"}})],
    sources=[], draw=draw, on_tap=on_tap)
