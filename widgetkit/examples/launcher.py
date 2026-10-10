"""A launcher: a search bar and a row of round shortcuts. What each opens is the user's to set."""
from PySide6.QtCore import QRectF

from nativeui import style
from widgetkit import controls
from widgetkit.definition import Field, WidgetDef, open_url

PAD = 22
BAR_H = 124
URL = "https://gemini.google.com/app"
BUTTONS = [{"icon": "mdi:camera-outline", "url": URL, "label": "Camera"},
           {"icon": "mdi:paperclip", "url": URL, "label": "Attach"},
           {"icon": "mdi:image-plus-outline", "url": URL, "label": "Image"},
           {"icon": "mdi:waveform", "url": URL, "label": "Live"}]


def draw(p, th, W, H, ctx):
    cfg, hits = ctx.config, ctx.hits
    controls.search_bar(p, th, QRectF(PAD, PAD, W - 2 * PAD, BAR_H), cfg["prompt"], "mdi:star-four-points",
                        "mdi:microphone-outline", "pressed" if ctx.pressed == "ask" else "", hits, "ask", "voice")
    below = QRectF(PAD, PAD + BAR_H + 14, W - 2 * PAD, H - 2 * PAD - BAR_H - 14)
    cells = style.grid(below, max(1, len(cfg["buttons"])), 1, 12)[0]
    for i, (cell, b) in enumerate(zip(cells, cfg["buttons"])):
        d = min(cell.width(), cell.height())
        circle = QRectF(cell.center().x() - d / 2, cell.center().y() - d / 2, d, d)
        controls.icon_button(p, th, circle, b["icon"], th.ink1, state="pressed" if ctx.pressed == ("btn", i) else "",
                             hits=hits, id=("btn", i), glyph=0.42)


def on_tap(id, ctx):
    cfg = ctx.config
    if id in ("ask", "voice"):
        return open_url(cfg["url"])
    if isinstance(id, tuple) and id[0] == "btn":
        return open_url(cfg["buttons"][id[1]]["url"])


WIDGET = WidgetDef(
    id="example.launcher", name="Launcher", size="2x4",
    config=[Field("prompt", "text", "Ask Gemini", "Words in the bar"),
            Field("url", "text", URL, "Bar opens"),
            Field("buttons", "launchers", BUTTONS, "Shortcuts")],
    sources=[], draw=draw, on_tap=on_tap)
