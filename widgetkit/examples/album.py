"""A photo: dropped on the widget, chosen with a button, or (if the user gives an address) fetched from the web."""
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor

from widgetkit import controls, media
from widgetkit.definition import Field, WidgetDef, pick_file
from widgetkit.sources import ImageSource

RADIUS = 34


def draw(p, th, W, H, ctx):
    area = QRectF(0, 0, W, H)
    over = ctx.drop_target("photo", area, accepts=("image",))
    chosen = ctx.state.get("photo")
    picture = chosen or ctx.data.get("remote")
    if picture:
        # In standby the photo is white and clear where it is dark: colour would fight the program's clear glass.
        media.caption_card(p, th, picture, area, ctx.config["caption"], "", th.tokens["radius_panel"], mono=th.dim)
        controls.icon_button(p, th, QRectF(W - 62, 14, 46, 46), "mdi:image-edit-outline", QColor(255, 255, 255),
                             filled=False, state="pressed" if ctx.pressed == "change" else "", hits=ctx.hits, id="change")
        if chosen:
            controls.icon_button(p, th, QRectF(W - 116, 14, 46, 46), "mdi:close", QColor(255, 255, 255), filled=False,
                                 state="pressed" if ctx.pressed == "clear" else "", hits=ctx.hits, id="clear")
    else:
        controls.drop_zone(p, th, area.adjusted(18, 18, -18, -18), over, "Drop a photo here, or tap to choose")
        ctx.hits.add(area, "zone")
    if over and picture:
        controls.drop_zone(p, th, area.adjusted(18, 18, -18, -18), True, "Drop to replace")


def on_tap(id, ctx):
    if id in ("zone", "change"):
        return pick_file("photo", "image")
    if id == "clear":
        ctx.set_state(photo=None)


def on_drop(id, files, ctx):
    ctx.set_state(photo=files[0])


WIDGET = WidgetDef(
    id="example.album", name="Photo", size="2x2",
    config=[Field("caption", "text", "", "Caption"),
            Field("image_url", "text", "", "Or a picture from the web", help="Leave empty to use your own photo.")],
    sources=[ImageSource("remote", url="{image_url}", every=1800)],
    draw=draw, on_tap=on_tap, on_drop=on_drop, permissions=("network:*",))
