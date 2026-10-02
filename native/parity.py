"""Renders the same demo widget with the web page and with native/render.py
and compares them: python native/parity.py [outdir]

Both draw on the same picture (a generated gradient with some texture), so
what differs is the card, the tiles and the text.
"""
import base64
import io
import json
import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "native"))

from PySide6.QtCore import QTimer, Qt, QUrl                      # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter                # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView             # noqa: E402
from PySide6.QtWidgets import QApplication                        # noqa: E402

import liquid                                                     # noqa: E402
import render                                                     # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "native", "out")
os.makedirs(OUT, exist_ok=True)
W4, H4 = render.widget_size("4x4")
SIZE = (W4 + 40, H4 + 40)          # a margin of picture around the card, as on a desktop
ORIGIN = 20

TILES = [
    {"id": "light", "entity": "light.desk", "domain": "light", "room": "Desk lamp", "label": ""},
    {"id": "climate", "entity": "climate.living", "domain": "climate", "room": "Living room", "label": "Cooling"},
    {"id": "fan", "entity": "fan.office", "domain": "fan", "room": "Office fan", "label": ""},
    {"id": "cover", "entity": "cover.bedroom", "domain": "cover", "room": "Blinds", "label": ""},
    {"id": "lock", "entity": "lock.front", "domain": "lock", "room": "Front door", "label": ""},
    {"id": "vacuum", "entity": "vacuum.home", "domain": "vacuum", "room": "Vacuum", "label": "Cleaning"},
    {"id": "sensor", "entity": "sensor.temperature", "domain": "sensor", "room": "Temperature", "label": ""},
    {"id": "media", "entity": "media_player.speaker", "domain": "media_player", "room": "書房", "label": ""},
]
STATES = {
    "light.desk": {"state": "on", "attributes": {"brightness": 180}},
    "climate.living": {"state": "cool", "attributes": {"temperature": 24, "current_temperature": 27}},
    "fan.office": {"state": "on", "attributes": {"percentage": 65}},
    "cover.bedroom": {"state": "closed", "attributes": {}},
    "lock.front": {"state": "unlocked", "attributes": {}},
    "vacuum.home": {"state": "cleaning", "attributes": {}},
    "sensor.temperature": {"state": "27.5", "attributes": {"device_class": "temperature", "unit_of_measurement": "°C"}},
    "media_player.speaker": {"state": "paused", "attributes": {"media_title": "Tiny Giant", "media_artist": "Sãn"}},
}


def backdrop_png():
    img = Image.new("RGB", SIZE)
    d = ImageDraw.Draw(img)
    for x in range(SIZE[0]):
        t = x / SIZE[0]
        d.line([(x, 0), (x, SIZE[1])], fill=(int(120 + 100 * t), int(150 + 60 * (1 - t)), int(190 - 40 * t)))
    for i in range(0, SIZE[0], 90):
        d.ellipse([i, 40 + (i % 3) * 60, i + 120, 160 + (i % 3) * 60], fill=(240, 200 - i % 80, 150 + i % 60))
    return img


os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")
app = QApplication([])
bg = backdrop_png()
buf = io.BytesIO()
bg.save(buf, "PNG")
bg_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
bg_qimage = QImage.fromData(buf.getvalue())
# (name, widget size, how many of the demo tiles, theme, dimmed)
SCENES = []
for style in ("classic", "liquid"):
    for theme in ("light", "dark"):
        for dim in (False, True):
            tag = ("liquid-" if style == "liquid" else "") + theme + ("-dim" if dim else "")
            SCENES += [("small-" + tag, "2x4", 8, theme, dim, style), ("bar-" + tag, "2x4", 4, theme, dim, style),
                       ("big-" + tag, "2x4", 2, theme, dim, style), ("4x4-" + tag, "4x4", 16, theme, dim, style)]
ONLY = sys.argv[2].split(",") if len(sys.argv) > 2 else None
if ONLY:
    SCENES = [sc for sc in SCENES if any(o in sc[0] for o in ONLY)]
state = {"i": 0, "web": {}, "native": {}}

view = QWebEngineView()
view.setAttribute(Qt.WA_DontShowOnScreen, True)
view.resize(*SIZE)
view.page().setBackgroundColor(QColor("#000000"))


def tiles_for(count):
    return [dict(TILES[i % len(TILES)], id="t%d" % i) for i in range(count)]


def native_render(scene):
    name, size, count, theme, dim, style = scene
    img = QImage(SIZE[0], SIZE[1], QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.drawImage(0, 0, bg_qimage)
    p.translate(ORIGIN, ORIGIN)
    if style == "liquid":
        W, H = render.widget_size(size)
        tcol = render.tokens(theme, dim, style)
        form, rects = render.tile_layout(size, count)
        crop = bg.crop((ORIGIN, ORIGIN, ORIGIN + W, ORIGIN + H)).reduce(8).filter(ImageFilter.GaussianBlur(2))
        lens = liquid.Lens(W, H, tcol["radius_panel"], 4)
        frame = lens.frame(crop, lens.card_mask(), [(x, y, w, h, tcol["radius_tile"]) for x, y, w, h in rects], 12)
        qf = QImage(frame.tobytes(), W, H, W * 4, QImage.Format_RGBA8888)
        p.drawImage(0, 0, qf)
    render.draw_widget(p, size, tiles_for(count), STATES, theme, None, 1.0, dim, style)
    p.end()
    return img


def small_url(size):
    """The picture the lens refracts: the card's part of the backdrop, as the capture makes it."""
    W, H = render.widget_size(size)
    small = bg.crop((ORIGIN, ORIGIN, ORIGIN + W, ORIGIN + H)).reduce(8).filter(ImageFilter.GaussianBlur(2))
    b = io.BytesIO()
    small.save(b, "PNG")
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()


def next_theme():
    if state["i"] >= len(SCENES):
        report()
        return
    scene = SCENES[state["i"]]
    name, size, count, theme, dim, style = scene
    W, H = render.widget_size(size)
    script = """
      CONFIG = Object.assign(CONFIG, {widgets: [{id: 'w1', size: %s, tiles: %s}],
        glass_style: %s, theme: %s, language: 'zh-TW', zoom: 100, dim_when_idle: false});
      STATES = %s;
      window.pywebview.api = new Proxy({}, {get: () => () => Promise.resolve(null)});
      resolveWindowTiles(); applyTheme(); renderGrid();
      document.documentElement.classList.toggle('is-dimmed', %s);
      document.documentElement.style.zoom = '1';
      document.body.style.background = 'url(%s) 0 0 / auto no-repeat';
      document.querySelector('#stage').style.cssText = 'margin: %dpx 0 0 %dpx';
      document.querySelector('#backdrop-glass').style.display = 'none';
      if (%s) {
        const W = %d, H = %d, O = %d;
        document.body.style.background = 'transparent';
        const glass = document.querySelector('#backdrop-glass');
        glass.style.display = 'block';
        const img = new Image();
        img.onload = () => {
          const full = document.createElement('canvas');
          full.width = %d; full.height = %d;
          const c = full.getContext('2d');
          c.fillStyle = '#000'; c.fillRect(0, 0, full.width, full.height);
          c.imageSmoothingEnabled = true; c.imageSmoothingQuality = 'high';
          c.drawImage(img, O, O, W, H);
          glassCtx = null; restingCard = null;
          paintBackdrop(full, full.width, full.height);
        };
        img.src = '%s';
      }
    """ % (json.dumps(size), json.dumps(tiles_for(count)), json.dumps(style), json.dumps(theme), json.dumps(STATES),
           "true" if dim else "false", bg_url, ORIGIN, ORIGIN,
           "true" if style == "liquid" else "false", W, H, ORIGIN, SIZE[0], SIZE[1], small_url(size))
    view.page().runJavaScript(script)

    def grab():
        state["web"][name] = view.grab().toImage()
        state["native"][name] = native_render(scene)
        state["i"] += 1
        QTimer.singleShot(50, next_theme)
    QTimer.singleShot(1300, grab)


def to_pil(qimg):
    qimg = qimg.convertToFormat(QImage.Format_RGBA8888)
    return Image.frombytes("RGBA", (qimg.width(), qimg.height()), bytes(qimg.constBits())).convert("RGB")


def report():
    for name, size, count, theme, dim, style in SCENES:
        W, H = render.widget_size(size)
        web, nat = to_pil(state["web"][name]), to_pil(state["native"][name])
        web.save(os.path.join(OUT, "web-%s.png" % name))
        nat.save(os.path.join(OUT, "native-%s.png" % name))
        diff = ImageChops.difference(web, nat)
        d = diff.crop((ORIGIN, ORIGIN, ORIGIN + W, ORIGIN + H))
        px = list(d.getdata())
        mean = sum(sum(p) / 3 for p in px) / len(px)
        big = sum(1 for p in px if max(p) > 24) / len(px) * 100
        side = Image.new("RGB", (W * 2 + 50, H + 40))
        side.paste(web.crop((0, 0, W + 40, H + 40)), (0, 0))
        side.paste(nat.crop((0, 0, W + 40, H + 40)), (W + 50, 0))
        side.save(os.path.join(OUT, "side-%s.png" % name))
        d.point(lambda v: min(255, v * 4)).save(os.path.join(OUT, "diff-%s.png" % name))
        print("%-14s mean abs difference %.2f / 255, pixels off by more than 24: %.1f%%" % (name, mean, big))
    app.quit()


def loaded(ok):
    if not ok:
        raise SystemExit("could not load the page")
    QTimer.singleShot(1000, next_theme)


view.loadFinished.connect(loaded)
view.load(QUrl.fromLocalFile(os.path.join(ROOT, "web", "index.html")))
view.show()
QTimer.singleShot(120000, app.quit)
app.exec()
