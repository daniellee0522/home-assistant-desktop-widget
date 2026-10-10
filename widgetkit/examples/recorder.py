"""A voice recorder: one button, a live level, the length, and where the sound was saved."""
import os

from PySide6.QtCore import QRectF

from widgetkit import charts, controls
from widgetkit.definition import Field, WidgetDef, copy, record_start, record_stop
from widgetkit.theme import paragraph, text

PAD = 24


def draw(p, th, W, H, ctx):
    rec = ctx.state.get("clip_recording")
    side = 112
    box = QRectF(PAD, H / 2 - side / 2, side, side)
    controls.icon_button(p, th, box, "mdi:stop" if rec else "mdi:microphone", th.accent("red"), filled=True,
                         state="pressed" if ctx.pressed == "rec" else "", hits=ctx.hits, id="rec", glyph=0.46)
    x = PAD + side + 26
    w = W - x - PAD
    text(p, th, "eyebrow", "RECORDING" if rec else "VOICE RECORDER", x, PAD + 4, w)
    charts.bar(p, th, QRectF(x, PAD + 34, w, 12), ctx.state.get("clip_level", 0.0) if rec else 0.0, th.accent("red"))
    clip, error = ctx.state.get("clip"), ctx.state.get("clip_error")
    if error:
        paragraph(p, th, "secondary", error, QRectF(x, PAD + 64, w, 80), max_lines=3)
    elif clip and not rec:
        text(p, th, "headline", "%.1f s saved" % ctx.state.get("clip_seconds", 0), x, PAD + 64, w)
        text(p, th, "caption", os.path.basename(clip), x, PAD + 92, w)
        controls.button(p, th, QRectF(x, H - PAD - 44, min(w, 200), 44), "Copy path", th.accent("blue"), "tinted",
                        icon_name="mdi:content-copy", state="pressed" if ctx.pressed == "copy" else "",
                        hits=ctx.hits, id="copy")
    else:
        text(p, th, "secondary", "Tap to stop" if rec else "Tap to start", x, PAD + 64, w)


def on_tap(id, ctx):
    if id == "rec":
        if ctx.state.get("clip_recording"):
            return record_stop("clip")
        return record_start("clip", ctx.config["max_seconds"])
    if id == "copy" and ctx.state.get("clip"):
        return copy(ctx.state["clip"])


WIDGET = WidgetDef(
    id="example.recorder", name="Voice recorder", size="2x4",
    config=[Field("max_seconds", "number", 60, "Longest recording (seconds)", minimum=5, maximum=600, step=5)],
    sources=[], draw=draw, on_tap=on_tap, permissions=("microphone", "clipboard"))
