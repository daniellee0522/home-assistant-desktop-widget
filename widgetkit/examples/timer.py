"""A countdown timer: start, pause, reset. The widget's state keeps it right across restarts."""
from PySide6.QtCore import QRectF

from widgetkit import charts, controls
from widgetkit.definition import Field, WidgetDef
from widgetkit.theme import text

PAD = 24


def remaining(ctx):
    """Seconds left: the minutes set, less what ran before, less what has run since it was started."""
    total = ctx.config["minutes"] * 60
    ran = ctx.state.get("ran", 0.0)
    started = ctx.state.get("started_at")
    if started:
        ran += ctx.now - started
    return max(0.0, total - ran), total


def draw(p, th, W, H, ctx):
    left, total = remaining(ctx)
    done = left <= 0
    side = H - 2 * PAD
    box = QRectF(PAD, PAD, side, side)
    color = th.accent("green" if done else "yellow")
    inner = charts.ring(p, th, box, left / total if total else 0, color, side * 0.09)
    m, s = divmod(int(left + 0.999), 60)
    text(p, th, "display", "%d:%02d" % (m, s), inner.left(), inner.center().y() - 25, inner.width(), "c")
    x = PAD + side + 34
    text(p, th, "eyebrow", "DONE" if done else ("RUNNING" if ctx.state.get("started_at") else "PAUSED"), x, PAD + 6)
    running = bool(ctx.state.get("started_at"))
    row = [("toggle", "mdi:pause" if running else "mdi:play", True), ("reset", "mdi:restart", False)]
    for i, (id, icon, filled) in enumerate(row):
        controls.icon_button(p, th, QRectF(x + i * 84, H / 2 - 12, 68, 68), icon, th.accent("blue"), filled=filled,
                             state="pressed" if ctx.pressed == id else "", hits=ctx.hits, id=id, glyph=0.5)


def on_tap(id, ctx):
    started = ctx.state.get("started_at")
    if id == "toggle":
        if started:                                                    # pause: what ran so far is kept
            ctx.set_state(ran=ctx.state.get("ran", 0.0) + ctx.now - started, started_at=None)
        elif remaining(ctx)[0] > 0:
            ctx.set_state(started_at=ctx.now)
    elif id == "reset":
        ctx.set_state(ran=0.0, started_at=None)


WIDGET = WidgetDef(
    id="example.timer", name="Timer", size="2x4",
    config=[Field("minutes", "number", 5, "Minutes", minimum=1, maximum=180)],
    sources=[], draw=draw, on_tap=on_tap, tick=0.25)
