"""Render the README screenshots with demo devices, drawn by the program's own windows (nativeui/).

python packaging/render_readme.py [outdir]   (default: docs/)

No Home Assistant and no desktop capture: the widgets' glass is made from a generated wallpaper the
same way the windows make it from the screen. The detail-card pictures (docs/detail-*.png) are not
made here.
"""
import os
from pathlib import Path
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFilter                      # noqa: E402
from PySide6.QtCore import QRectF, Qt                               # noqa: E402
from PySide6.QtGui import QImage, QPainter                          # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402

app = QApplication.instance() or QApplication([])

from nativeui import liquid, panel, render, settings               # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs"
MARGIN = 21                                         # wallpaper around the card, as on a desktop

TILES = [
    {"id": "light", "entity": "light.desk", "domain": "light", "room": "Desk lamp", "label": ""},
    {"id": "climate", "entity": "climate.living", "domain": "climate", "room": "Living room", "label": "Cooling"},
    {"id": "fan", "entity": "fan.office", "domain": "fan", "room": "Office fan", "label": ""},
    {"id": "cover", "entity": "cover.bedroom", "domain": "cover", "room": "Blinds", "label": ""},
    {"id": "lock", "entity": "lock.front", "domain": "lock", "room": "Front door", "label": ""},
    {"id": "vacuum", "entity": "vacuum.home", "domain": "vacuum", "room": "Vacuum", "label": "Cleaning"},
    {"id": "sensor", "entity": "sensor.temperature", "domain": "sensor", "room": "Temperature", "label": ""},
    {"id": "humidity", "entity": "sensor.humidity", "domain": "sensor", "room": "Humidity", "label": ""},
]
STATES = {
    "light.desk": {"state": "on", "attributes": {"brightness": 180, "rgb_color": [255, 190, 108]}},
    "climate.living": {"state": "cool", "attributes": {"temperature": 24, "current_temperature": 27}},
    "fan.office": {"state": "on", "attributes": {"percentage": 65}},
    "cover.bedroom": {"state": "closed", "attributes": {}},
    "lock.front": {"state": "locked", "attributes": {}},
    "vacuum.home": {"state": "cleaning", "attributes": {}},
    "sensor.temperature": {"state": "27.5", "attributes": {"device_class": "temperature",
                                                           "unit_of_measurement": "°C"}},
    "sensor.humidity": {"state": "75", "attributes": {"device_class": "humidity", "unit_of_measurement": "%"}},
}
WALLPAPER = {"light": ((166, 190, 210), (228, 237, 242), (140, 171, 197)),
             "dark": ((41, 51, 68), (82, 105, 124), (29, 40, 56))}


def wallpaper(size, theme):
    """A diagonal gradient with a few soft shapes, so the glass has something to show."""
    w, h = size
    a, b, c = WALLPAPER[theme]
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for x in range(-h, w):
        t = (x + h) / (w + h)
        lo, hi, k = (a, b, t / 0.58) if t < 0.58 else (b, c, (t - 0.58) / 0.42)
        d.line([(x, 0), (x + h, h)], fill=tuple(round(lo[i] + (hi[i] - lo[i]) * k) for i in range(3)), width=2)
    for i, x in enumerate(range(0, w, 150)):
        d.ellipse([x, 30 + (i % 3) * 70, x + 130, 150 + (i % 3) * 70],
                  fill=(240, 200 - i * 9 % 80, 150 + i * 13 % 60) if theme == "light" else (90, 70 + i * 7 % 40, 120))
    return img.filter(ImageFilter.GaussianBlur(3))


def to_qimage(img):
    img = img.convert("RGBA")
    return QImage(img.tobytes(), img.width, img.height, img.width * 4, QImage.Format_RGBA8888).copy()


def widget_picture(size, tiles, theme, style):
    """A widget over the wallpaper, its glass made as nativeui/glass.py makes it from a capture."""
    W, H = render.widget_size(size)
    bg = wallpaper((W + 2 * MARGIN, H + 2 * MARGIN), theme)
    behind = bg.crop((MARGIN, MARGIN, MARGIN + W, MARGIN + H))
    tcol = render.tokens(theme, False, style)
    out = QImage(bg.width, bg.height, QImage.Format_ARGB32_Premultiplied)
    p = QPainter(out)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    p.drawImage(0, 0, to_qimage(bg))
    p.translate(MARGIN, MARGIN)
    if style == "liquid":
        lens = liquid.Lens(W, H, tcol["radius_panel"])
        _, rects = render.tile_layout(size, len(tiles))
        frame = lens.frame(liquid.picture(behind), lens.card_mask(),
                           [(x, y, w, h, tcol["radius_tile"]) for x, y, w, h in rects], 8)
        p.drawImage(0, 0, to_qimage(frame))
    else:
        glass = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
        glass.fill(Qt.transparent)
        g = QPainter(glass)
        g.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        g.setClipPath(render.squircle(0, 0, W, H, tcol["radius_panel"]))
        g.drawImage(QRectF(0, 0, W, H), to_qimage(behind.reduce(8).filter(ImageFilter.GaussianBlur(2))))
        g.end()
        p.drawImage(0, 0, glass)
    render.draw_widget(p, size, tiles, STATES, theme, None, 1.0, False, style)
    p.end()
    return out


def save(image, name):
    target = OUT / name
    image.save(str(target))
    print(target, image.width(), image.height())


def pump(ms):
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


class DemoApi:
    """What the panel and Settings ask of main.py's Api, answered with the demo devices."""

    _flyout_anchor = None                          # the panel opens at no tray: its own monitor

    def __init__(self, theme="light", style="classic"):
        self.theme, self.style = theme, style

    def _prefs(self):
        return {"theme": self.theme, "language": "en", "glass_style": self.style, "zoom": 100,
                "panel_theme": "follow", "liquid_blur": 0, "glass_mode": "fast", "glass_sampling": "live",
                "dim_when_idle": True, "dim_after_sec": 120, "lock_position": False, "system_glass_ok": False,
                "widgets": [{"id": "w1", "size": "2x4", "tiles": TILES},
                            {"id": "w2", "size": "2x2", "tiles": TILES[:4]}],
                "panel": {"mode": "grid", "tiles": None, "home_tiles": []}}

    def bootstrap(self):
        return {"config": {"ha_url": "http://homeassistant.local:8123", "ha_token": "", "start_on_boot": False},
                "connected": True}

    def fetch_initial_states(self):
        return dict(STATES)

    def get_layout(self):
        return {"monitors": [{"x": 0, "y": 0, "w": 1920, "h": 1080}],
                "widgets": [{"id": "w1", "size": "2x4", "x": 1200, "y": 90, "w": 678, "h": 334, "visible": True},
                            {"id": "w2", "size": "2x2", "x": 1500, "y": 480, "w": 344, "h": 332, "visible": True}]}

    def get_entities(self):
        return [{"entity_id": e, "domain": e.split(".")[0], "name": e, "state": s} for e, s in STATES.items()]

    def get_desktop_backdrop(self, *a, **k):
        return {"skip": True, "retry_ms": 60000}

    def _panel_bg_path(self):
        return None

    def __getattr__(self, name):                   # anything else the windows may call: nothing to do
        return lambda *a, **k: None


def panel_picture():
    api = DemoApi("dark", "liquid")
    win = panel.create_panel(api)
    sc = win.native
    pump(150)
    sc.anim_alpha = sc.anim_zoom = 1
    sc.rebuild()
    sc.push_states(list(STATES.items()))
    sc.show()
    pump(300)
    card = sc.grab().toImage()
    bg = wallpaper((card.width() + 2 * MARGIN, card.height() + 2 * MARGIN), "dark")
    out = to_qimage(bg)
    p = QPainter(out)
    p.drawImage(MARGIN, MARGIN, card)
    p.end()
    win.dispose()
    return out


def settings_pictures():
    api = DemoApi()
    win = settings.create_settings(api)
    sc = win.native

    def shot():
        pump(500)
        # main.py sizes the window to what it asks for (Api.resize_settings_window); here it is done directly.
        ratio = sc.devicePixelRatioF() or 1.0
        sc.resize(round(sc.pw / ratio), round(sc.ph / ratio))
        pump(300)
        return sc.grab().toImage()

    pump(150)
    sc.layout = api.get_layout()
    sc.build()
    sc.show()
    sc.enter_settings()
    yield "settings-english.png", shot()
    sc.enter_editor("w1")
    yield "widget-editor.png", shot()
    win.dispose()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    render.set_language("en")
    for style in ("classic", "liquid", "windows"):
        for theme in ("light", "dark"):
            save(widget_picture("2x4", TILES, theme, style), "theme-%s-%s.png" % (style, theme))
    save(panel_picture(), "tray-panel.png")
    for name, image in settings_pictures():
        save(image, name)


if __name__ == "__main__":
    main()
