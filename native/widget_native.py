"""A desktop widget drawn natively (no browser): python native/widget_native.py

A prototype of what main.py does with a web page per widget. It reads the same
settings file, shows the first widget at its saved place with its tiles live
from Home Assistant, and its frosted glass is the same captured, blurred
picture of the desktop behind it. Click toggles, drag moves, Esc or the tray
of the console quits.
"""
import ctypes
import os
import sys
import threading
import time

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")     # coordinates are physical pixels
# Glyphs from the font files, not from DirectWrite, which copies a whole CJK
# font (about 40 MB) into the process the first time one is used.
os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QObject, QPoint, QRectF, Qt, QTimer, Signal   # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget                       # noqa: E402

import config as cfgmod                                                   # noqa: E402
import render                                                             # noqa: E402
from ha_client import HAClient                                            # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
WDA_EXCLUDEFROMCAPTURE = 0x11


class Bridge(QObject):
    states = Signal(object)            # {entity: state}
    backdrop = Signal(object)          # QImage, the small blurred picture


class NativeWidget(QWidget):
    def __init__(self, widget, cfg, bridge):
        super().__init__()
        self.widget, self.cfg, self.bridge = widget, cfg, bridge
        self.tiles = widget["tiles"]
        self.states = {}
        self.size_key = widget["size"]
        screen = QGuiApplication.primaryScreen()
        dpr = screen.logicalDotsPerInch() / 96.0
        self.scale = max(0.5, min(2.0, cfg.get("zoom", 100) / 100.0)) * dpr
        cw, ch = render.widget_size(self.size_key)
        self.px_w, self.px_h = round(cw * self.scale), round(ch * self.scale)
        # NATIVE_PREVIEW=1: on top, in the middle of the screen, so it can be looked
        # at without touching the real widgets; right-click quits.
        self.preview = os.environ.get("NATIVE_PREVIEW") == "1"
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool
                            | (Qt.WindowStaysOnTopHint if self.preview else Qt.WindowStaysOnBottomHint)
                            | Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(self.px_w, self.px_h)
        if self.preview:
            geo = screen.geometry()
            self.move(geo.x() + (geo.width() - self.px_w) // 2, geo.y() + (geo.height() - self.px_h) // 2)
        else:
            self.move(widget["x"], widget["y"])
        theme = cfg.get("theme", "auto")
        if theme == "auto":
            theme = "dark" if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
        self.theme = theme
        self.backdrop_img = None
        self.overlay = None            # the card tint and the tiles, drawn once per change
        self.mask = None               # the card's shape, to cut the backdrop to
        self.frame = QImage(self.px_w, self.px_h, QImage.Format_ARGB32_Premultiplied)
        self._press = None
        bridge.states.connect(self.on_states)
        bridge.backdrop.connect(self.on_backdrop)

    # -- what is drawn ----------------------------------------------------
    def build_overlay(self):
        img = QImage(self.px_w, self.px_h, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        render.draw_widget(p, self.size_key, self.tiles, self.states, self.theme, None, self.scale)
        p.end()
        self.overlay = QPixmap.fromImage(img)
        if self.mask is None:
            m = QImage(self.px_w, self.px_h, QImage.Format_ARGB32_Premultiplied)
            m.fill(Qt.transparent)
            q = QPainter(m)
            q.setRenderHint(QPainter.Antialiasing)
            q.scale(self.scale, self.scale)
            cw, ch = render.widget_size(self.size_key)
            q.setPen(Qt.NoPen)
            q.setBrush(QColor(0, 0, 0))
            q.drawPath(render.squircle(0, 0, cw, ch, render.RADIUS_PANEL))
            q.end()
            self.mask = m

    def paintEvent(self, event):
        if self.overlay is None:
            self.build_overlay()
        p = QPainter(self)
        if self.backdrop_img is not None:
            f = QPainter(self.frame)
            f.setCompositionMode(QPainter.CompositionMode_Source)
            f.fillRect(self.frame.rect(), Qt.transparent)
            f.setRenderHint(QPainter.SmoothPixmapTransform)
            f.drawImage(QRectF(0, 0, self.px_w, self.px_h), self.backdrop_img)
            f.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            f.drawImage(0, 0, self.mask)
            f.end()
            p.drawImage(0, 0, self.frame)
        p.drawPixmap(0, 0, self.overlay)
        p.end()

    def on_states(self, changed):
        self.states.update(changed)
        self.overlay = None
        self.update()

    def on_backdrop(self, image):
        self.backdrop_img = image
        self.update()

    # -- the mouse --------------------------------------------------------
    def tile_at(self, pos):
        x, y = pos.x() / self.scale, pos.y() / self.scale
        cols = render.SIZES[self.size_key][0]
        for i, tile in enumerate(self.tiles[: cols * render.SIZES[self.size_key][1]]):
            tx = render.PAD + (i % cols) * (render.CELL_W + render.GAP)
            ty = render.PAD + (i // cols) * (render.CELL_H + render.GAP)
            if tx <= x < tx + render.CELL_W and ty <= y < ty + render.CELL_H:
                return tile
        return None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = (e.globalPosition().toPoint(), self.pos(), self.tile_at(e.position().toPoint()), False)

    def mouseMoveEvent(self, e):
        if self._press and e.buttons() & Qt.LeftButton:
            start, origin, tile, moved = self._press
            d = e.globalPosition().toPoint() - start
            if moved or abs(d.x()) + abs(d.y()) > 6:
                self._press = (start, origin, tile, True)
                self.move(origin + QPoint(d.x(), d.y()))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.RightButton and self.preview:
            QApplication.quit()
            return
        if self._press and not self._press[3] and self._press[2]:
            threading.Thread(target=quick_action, args=(self._press[2], self.states), daemon=True).start()
        self._press = None

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            QApplication.quit()


client = None


def quick_action(tile, states):
    domain, entity = tile["domain"], tile["entity"]
    try:
        if domain in ("light", "switch", "fan", "input_boolean"):
            client.call_service(domain, "toggle", entity)
        elif domain == "lock":
            locked = (states.get(entity) or {}).get("state") == "locked"
            client.call_service("lock", "unlock" if locked else "lock", entity)
        elif domain == "media_player":
            client.call_service("media_player", "media_play_pause", entity)
        elif domain == "cover":
            open_ = (states.get(entity) or {}).get("state") == "open"
            client.call_service("cover", "close_cover" if open_ else "open_cover", entity)
    except Exception:
        pass


def backdrop_loop(win, bridge, stop):
    """The glass: the picture behind the window, as the app's capture hub
    makes it (1/8 scale, blurred), whenever the screen there changes."""
    import dxgi_capture
    from PIL import Image, ImageChops, ImageFilter
    dup = dxgi_capture.DesktopDuplication()
    after, last, sent = None, 0.0, None
    while not stop.is_set():
        x, y, w, h = win.x(), win.y(), win.px_w, win.px_h
        got = dup.grab(x, y, w, h, after, 0.25) if dup.available() else None
        if not got:
            time.sleep(0.25)
            continue
        after = got[0]
        if got[1] is None:
            continue
        wait = 1 / 30 - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        last = time.monotonic()
        small = Image.frombuffer("RGBA", (w, h), got[1], "raw", "RGBA", 0, 1)
        small = small.reduce(8) if not (w % 8 or h % 8) else small.resize((max(1, round(w / 8)), max(1, round(h / 8))), Image.BOX)
        small = Image.frombytes("RGB", small.size, small.tobytes(), "raw", "BGRX")
        if sent is not None and sent.size == small.size and max(
                hi for _, hi in ImageChops.difference(sent, small).getextrema()) <= 3:
            continue
        sent = small
        small = small.filter(ImageFilter.GaussianBlur(2))
        img = QImage(small.tobytes(), small.width, small.height, small.width * 3, QImage.Format_RGB888).copy()
        bridge.backdrop.emit(img)


def main():
    global client
    cfg = cfgmod.load_config()
    widget = cfg["widgets"][0]
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    bridge = Bridge()
    win = NativeWidget(widget, cfg, bridge)
    win.show()
    hwnd = int(win.winId())
    user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
    stop = threading.Event()

    client = HAClient(on_event=lambda eid, st: bridge.states.emit({eid: st}))
    client.configure(cfg["ha_url"], cfg["ha_token"])
    client.set_entities([t["entity"] for t in widget["tiles"]])
    client.start()

    def initial():
        try:
            wanted = {t["entity"] for t in widget["tiles"]}
            bridge.states.emit({s["entity_id"]: s for s in client.get_states() if s["entity_id"] in wanted})
        except Exception:
            pass
    threading.Thread(target=initial, daemon=True).start()
    if os.environ.get("NATIVE_NO_GLASS") != "1":
        threading.Thread(target=backdrop_loop, args=(win, bridge, stop), daemon=True).start()
    if os.environ.get("NATIVE_DUMP"):
        QTimer.singleShot(9000, lambda: win.grab().save(os.environ["NATIVE_DUMP"]))
    if os.environ.get("NATIVE_RUN_SECONDS"):
        QTimer.singleShot(int(float(os.environ["NATIVE_RUN_SECONDS"]) * 1000), app.quit)
    app.exec()
    stop.set()
    client.stop()


if __name__ == "__main__":
    main()
