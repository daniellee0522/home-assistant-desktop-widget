"""Review the real native glass worker/compositor with controlled desktop captures.

These are fixture desktops, not live screen captures. Unlike visual_check's content-only
images, every shot waits for GlassMixin's worker, lens, tile blur and native paintEvent.
python tools/glass_review.py [output-directory]
"""
import ast
import json
import os
from pathlib import Path
import sys
import time
import zlib

os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from PIL import Image, ImageDraw, ImageFilter
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication
from nativeui import render, widget
from test_native_widget import FakeApi

app = QApplication.instance() or QApplication([])
# Use the production capture's own liquid sampling parameters without starting main.py.
node = next(n for n in ast.parse((ROOT / "main.py").read_text(encoding="utf-8")).body
            if isinstance(n, ast.FunctionDef) and n.name == "_liquid_params")
scope = {}
exec(compile(ast.Module(body=[node], type_ignores=[]), "main.py", "exec"), scope)

TILES = [dict(id=str(i), entity=f"light.{i}", domain="light", room=name, label="")
         for i, name in enumerate(("客廳閱讀燈", "臥室床頭燈", "Living room reading light", "走廊燈光"))]
STATES = {t["entity"]: {"state": "on" if i % 2 == 0 else "off", "attributes": {"brightness": 180}}
          for i, t in enumerate(TILES)}


def desktop(w, h, pattern):
    bg = Image.new("RGB", (w, h), "#f2efea" if pattern == "bright" else "#172031")
    d = ImageDraw.Draw(bg)
    if pattern == "busy":
        for y in range(0, h, 28):
            for x in range(0, w, 28):
                d.rectangle((x, y, x + 27, y + 27), fill="#e6d2a8" if (x // 28 + y // 28) % 2 else "#283d60")
    elif pattern == "fine":
        for x in range(-h, w, 4):
            d.line((x, 0, x + h, h), fill="#d9dde2", width=1)
    else:
        d.ellipse((w // 3, -h // 2, w + w // 3, h), fill="#c8d7e3" if pattern == "bright" else "#574c72")
    return bg


class CaptureApi(FakeApi):
    def __init__(self, style="classic", theme="light", pattern="busy", level=0, zoom=100):
        super().__init__(TILES, "2x2", theme=theme, glass_style=style, liquid_blur=level,
                         zoom=zoom, lock_position=True)
        self.pattern, self.captures = pattern, 0
        self.cache = {}

    def get_desktop_backdrop(self, kind, last_hash, w, h, *args):
        self.captures += 1
        key = (w, h)
        if key not in self.cache:
            bg = desktop(w, h, self.pattern)
            if self.prefs["glass_style"] == "liquid":
                level = self.prefs["liquid_blur"] / 100
                scale, pre, post = scope["_liquid_params"](level)
                small = bg if scale == 1 else bg.resize((max(1, round(w / 2)), max(1, round(h / 2))), Image.Resampling.BOX)
                small = small.filter(ImageFilter.GaussianBlur(pre))
                if scale > 2:
                    small = small.resize((max(1, round(w / scale)), max(1, round(h / scale))), Image.Resampling.HAMMING)
            else:
                small = bg.resize((max(1, round(w / 8)), max(1, round(h / 8))), Image.Resampling.BOX)
                post = 2
            if post:
                small = small.filter(ImageFilter.GaussianBlur(post))
            raw = small.tobytes()
            self.cache[key] = dict(w=w, h=h, blur_w=small.width, blur_h=small.height,
                                   blur_raw=raw, hash=zlib.crc32(raw), paced=True)
        return self.cache[key]


def pump_until(predicate, timeout=5):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    raise RuntimeError("Native glass worker did not produce a frame")


def create(style="classic", theme="light", pattern="busy", level=0, zoom=100, gpu=False):
    api = CaptureApi(style, theme, pattern, level, zoom)
    if gpu:
        api.gpu_widget_glass_allowed = lambda kind: True
        capture = api.get_desktop_backdrop
        def changed_only(kind, last_hash, w, h, *args):
            result = capture(kind, last_hash, w, h, *args)
            if result['hash'] == last_hash:
                return dict(unchanged=True, paced=True, hash=last_hash)
            return result
        api.get_desktop_backdrop = changed_only
    win = widget.NativeWidget(api, "w1")
    surface = win.native
    surface.move(100, 100)
    surface.relayout()
    surface.push_states(list(STATES.items()))
    surface.show()
    ready = (lambda: surface._gpu_receiver is not None and surface._gpu_receiver.visible) if gpu else \
            (lambda: surface.glass is not None and surface.glass.width() == surface.pw)
    pump_until(ready)
    if not ready():
        close(win)
        raise RuntimeError('Glass did not become ready')
    return api, win, surface


def close(win):
    surface = win.native
    surface.stop()
    if surface._glass_thread is not None:
        surface._glass_thread.join(1)
    surface.close()
    app.processEvents()


def shot(surface, pattern):
    raw = desktop(surface.pw, surface.ph, pattern)
    image = QImage(raw.tobytes(), raw.width, raw.height, raw.width * 3, QImage.Format_RGB888).copy()
    p = QPainter(image)
    receiver = getattr(surface, '_gpu_receiver', None)
    foreground = receiver.snapshot() if receiver is not None and receiver.visible else surface.grab().toImage()
    p.drawImage(QRectF(0, 0, raw.width, raw.height), foreground)
    p.end()
    return image


def main(out=None):
    out = Path(out) if out is not None else (Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "visual/glass-review")
    out.mkdir(parents=True, exist_ok=True)
    records, pictures = [], []
    for pattern in ("bright", "dark", "busy", "fine"):
        for theme in ("light", "dark"):
            for style, level in (("classic", 0), ("liquid", 0), ("liquid", 50), ("liquid", 100)):
                api, win, sc = create(style, theme, pattern, level)
                try:
                    img = shot(sc, pattern)
                    name = f"{pattern}-{theme}-{style}-{level}.png"
                    img.save(str(out / name))
                    pictures.append(img)
                    records.append(dict(file=name, captures=api.captures, glass=[sc.glass.width(), sc.glass.height()],
                                        scale=sc.scale, radius=sc.tcol["radius_panel"]))
                finally:
                    close(win)
    overview = QImage(4 * pictures[0].width(), 8 * pictures[0].height(), QImage.Format_RGB32)
    p = QPainter(overview)
    for i, img in enumerate(pictures):
        p.drawImage((i % 4) * img.width(), (i // 4) * img.height(), img)
    p.end()
    overview.save(str(out / "overview.png"))
    (out / "captures.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"{len(records)} native glass captures: {out}")


if __name__ == "__main__":
    main()
