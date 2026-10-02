"""Tries font settings against the web pictures parity.py saved (out/web-*.png)."""
import itertools, os, sys
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
from PIL import Image, ImageDraw
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
app = QApplication([])
from nativeui import render
import parity_data
W, H = render.widget_size("2x4")
SIZE = (W + 40, H + 40)
img = Image.new("RGB", SIZE); d = ImageDraw.Draw(img)
for x in range(SIZE[0]):
    t = x / SIZE[0]; d.line([(x, 0), (x, SIZE[1])], fill=(int(120 + 100 * t), int(150 + 60 * (1 - t)), int(190 - 40 * t)))
for i in range(0, SIZE[0], 90):
    d.ellipse([i, 40 + (i % 3) * 60, i + 120, 160 + (i % 3) * 60], fill=(240, 200 - i % 80, 150 + i % 60))
import io
buf = io.BytesIO(); img.save(buf, "PNG"); bg = QImage.fromData(buf.getvalue())
webs = {t: np.asarray(Image.open(os.path.join(ROOT, "native", "out", "web-%s.png" % t)).convert("RGB"), float) for t in ("light", "dark")}


def score():
    tot = 0
    for theme in ("light", "dark"):
        q = QImage(SIZE[0], SIZE[1], QImage.Format_ARGB32_Premultiplied); q.fill(Qt.transparent)
        p = QPainter(q); p.drawImage(0, 0, bg); p.translate(20, 20)
        render.draw_widget(p, "2x4", parity_data.TILES, parity_data.STATES, theme); p.end()
        q = q.convertToFormat(QImage.Format_RGBA8888)
        a = np.frombuffer(bytes(q.constBits()), np.uint8).reshape(q.height(), q.width(), 4)[:, :, :3].astype(float)
        tot += np.abs(a - webs[theme])[20:20 + H, 20:20 + W].mean()
    return tot / 2


for woff, hs, emb in itertools.product((40, 60, 80), (0.97, 0.985, 1.0), (0.0, 0.25)):
    render.WOFF, render.HSCALE, render.EMBOLDEN = woff, hs, emb
    print("weight +%-3d hscale %.3f embolden %.2f  ->  %.3f" % (woff, hs, emb, score()), flush=True)
