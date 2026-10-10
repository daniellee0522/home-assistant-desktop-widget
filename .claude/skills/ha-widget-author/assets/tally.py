"""Recipe: a counter you press. State kept between runs (`ctx.state`), taps (`on_tap` with ids registered in `ctx.hits`), a
spring that eases the number's ring, a layout that follows the size. Copy it for a habit, a score, a stock of something."""
from PySide6.QtCore import QRectF

from widgetkit import charts, controls
from widgetkit.definition import Field, WidgetDef
from widgetkit.theme import text

PAD = 22


def draw(p, th, W, H, ctx):
    count, goal = ctx.state.get("count", 0), ctx.config["goal"]
    color = th.accent("green")
    shown = ctx.spring("ring", min(1.0, count / goal))                    # eases when the count changes
    wide = W > H * 1.5                                                    # a 2x4: the ring left, the buttons right
    side = H - 2 * PAD if wide else min(W - 2 * PAD, H - 2 * PAD - 54)    # a ring is as wide as it is tall
    ring_box = QRectF(PAD if wide else (W - side) / 2, PAD, side, side)
    inside = charts.ring(p, th, ring_box, shown, color)
    text(p, th, "display", str(count), inside.left(), inside.center().y() - 40, inside.width(), "c")
    text(p, th, "caption", "/ %d  %s" % (goal, ctx.config["unit"]), inside.left(), inside.center().y() + 14, inside.width(), "c")
    row_y = ring_box.center().y() - 22 if wide else H - PAD - 44
    x0 = ring_box.right() + PAD * 2 if wide else W / 2 - 52
    controls.icon_button(p, th, QRectF(x0, row_y, 44, 44), "mdi:minus", color, state="pressed" if ctx.pressed == "minus" else "",
                         hits=ctx.hits, id="minus")
    controls.icon_button(p, th, QRectF(x0 + 60, row_y, 44, 44), "mdi:plus", color, filled=True,
                         state="pressed" if ctx.pressed == "plus" else "", hits=ctx.hits, id="plus")


def on_tap(id, ctx):
    ctx.set_state(count=max(0, ctx.state.get("count", 0) + (1 if id == "plus" else -1)))


WIDGET = WidgetDef(
    id="example.tally", name={"en": "Tally", "zh": "計數器"}, size="2x2", sizes=("2x4",),
    config=[Field("goal", "number", 8, {"en": "Goal", "zh": "目標"}, minimum=1, maximum=999),
            Field("unit", "text", "times", {"en": "Unit", "zh": "單位"})],
    sources=[], draw=draw, on_tap=on_tap)
