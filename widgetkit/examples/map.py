"""A map you can drag and zoom, from tiles on the web (OpenStreetMap by default, with the credit its licence asks for)."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor

from nativeui import render, style

from widgetkit import controls, geo, media
from widgetkit.definition import Field, WidgetDef
from widgetkit.sources import ImageSource, fill
from widgetkit.theme import text

TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"


def view(ctx):
    """(lat, lon, zoom): where the user left it (dragged, zoomed), else what was set."""
    c = ctx.config
    return (ctx.state.get("lat", c["lat"]), ctx.state.get("lon", c["lon"]), int(ctx.state.get("zoom", c["zoom"])))


def tiles_wanted(inputs):
    cfg, state = inputs, inputs.get("state") or {}
    W, H = inputs.get("size", (678, 334))
    lat, lon, zoom = state.get("lat", cfg["lat"]), state.get("lon", cfg["lon"]), int(state.get("zoom", cfg["zoom"]))
    return [fill(cfg["tile_url"], z=zoom, x=tx, y=ty) for tx, ty, _, _ in geo.tile_grid(lat, lon, zoom, W, H)]


def draw(p, th, W, H, ctx):
    lat, lon, zoom = view(ctx)
    grid = geo.tile_grid(lat, lon, zoom, W, H)
    have = ctx.data.get("tiles") or {}                              # {address: picture bytes}
    p.save()
    p.setClipPath(render.squircle(0, 0, W, H, th.tokens["radius_panel"]))          # the map takes the card's shape
    for tx, ty, px, py in grid:
        img = have.get(fill(ctx.config["tile_url"], z=zoom, x=tx, y=ty))
        if img:
            media.picture(p, img, QRectF(round(px), round(py), geo.TILE + 1, geo.TILE + 1), "fill")   # a pixel over: no seams
    p.restore()
    ctx.hits.add(QRectF(0, 0, W, H), "map")
    controls.icon(p, "mdi:map-marker", QColor("#ff3b30"), QRectF(W / 2 - 24, H / 2 - 44, 48, 48), 44)
    for i, (id, icon) in enumerate((("zoom_in", "mdi:plus"), ("zoom_out", "mdi:minus"))):
        backed_button(p, QRectF(W - 64, 16 + i * 58, 46, 46), icon, ctx.pressed == id)
        ctx.hits.add(QRectF(W - 64, 16 + i * 58, 46, 46), id)
    credit = "\u00a9 OpenStreetMap contributors"
    from widgetkit.theme import role_font
    from nativeui import ui
    cw = ui.text_width(credit, role_font("tiny")) + 20
    backing(p, QRectF(14, H - 14 - 24, cw, 24))
    text(p, th, "tiny", credit, 24, H - 14 - 24 + 5, cw, color=QColor(40, 44, 52))


def backing(p, rect):
    """Words and buttons over a picture stand on a light pill (CLAUDE.md: words over glass stand on a backing)."""
    p.save()
    style.shadow(p, rect, rect.height() / 2, ((6, 10), (2, 16)), dy=1)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 235))
    p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
    p.restore()


def backed_button(p, rect, icon, pressed):
    backing(p, rect.adjusted(2, 2, -2, -2) if pressed else rect)
    controls.icon(p, icon, QColor(40, 44, 52), rect, 24)


def on_tap(id, ctx):
    lat, lon, zoom = view(ctx)
    if id == "zoom_in":
        ctx.set_state(zoom=min(18, zoom + 1))
    elif id == "zoom_out":
        ctx.set_state(zoom=max(2, zoom - 1))


def on_drag(id, move, ctx):
    if id == "map":
        lat, lon, zoom = view(ctx)
        lat, lon = geo.pan(lat, lon, zoom, move.dx, move.dy)
        ctx.set_state(lat=lat, lon=lon)


WIDGET = WidgetDef(
    id="example.map", name="Map", size="2x4",
    config=[Field("lat", "number", 25.0330, "Latitude", minimum=-85, maximum=85, step=0.01),
            Field("lon", "number", 121.5654, "Longitude", minimum=-180, maximum=180, step=0.01),
            Field("zoom", "number", 14, "Zoom", minimum=2, maximum=18),
            Field("tile_url", "text", TILE_URL, "Tile address")],
    sizes=("2x2", "4x4"), sources=[ImageSource("tiles", urls=tiles_wanted, every=3600)],
    draw=draw, on_tap=on_tap, on_drag=on_drag, permissions=("network:tile.openstreetmap.org",))
