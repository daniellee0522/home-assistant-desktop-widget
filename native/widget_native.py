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

from PySide6.QtCore import (QElapsedTimer, QObject, QPoint, QPointF, QRectF, Qt, QTimer,  # noqa: E402
                            Signal)
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget                       # noqa: E402

import config as cfgmod                                                   # noqa: E402
import idle                                                               # noqa: E402
import liquid                                                             # noqa: E402
import render                                                             # noqa: E402
from ha_client import HAClient                                            # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
WDA_EXCLUDEFROMCAPTURE = 0x11


class Bridge(QObject):
    states = Signal(object)            # {entity: state}
    backdrop = Signal(object)          # QImage, the small blurred picture
    dim = Signal(bool)                 # the desktop is out of sight (or back)
    frame = Signal(object)             # QImage, the finished liquid glass


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
        # Windows glass is not drawn here yet: it shows as the classic one.
        self.style = "liquid" if os.environ.get("NATIVE_STYLE", cfg.get("glass_style")) == "liquid" else "classic"
        self.tcol = render.tokens(theme, False, self.style)
        self.frame_img = None          # liquid: the whole glass, made off the GUI thread
        self.backdrop_img = None
        self.overlay = None            # the card tint and the tiles, drawn once per change
        self.overlay_dim = None        # the same in its dimmed colours, made when first needed
        self.dim_t, self.dim_from, self.dim_target = 0.0, 0.0, False   # 0 lit, 1 dimmed
        self.dim_clock = QElapsedTimer()
        self.dim_timer = QTimer(self)
        self.dim_timer.setInterval(16)
        self.dim_timer.timeout.connect(self.step_dim)
        self.mix = QImage(self.px_w, self.px_h, QImage.Format_ARGB32_Premultiplied)
        self.form, self.rects = render.tile_layout(self.size_key, len(self.tiles))
        self.setMouseTracking(True)
        self.mask = None               # the card's shape, to cut the backdrop to
        self.frame = QImage(self.px_w, self.px_h, QImage.Format_ARGB32_Premultiplied)
        self._press = None
        self.dragging = False
        self.latest = None
        self.frame_queued = threading.Event()
        self.sample_now = threading.Event()        # tells a 'still' glass to look again
        self.sampling = os.environ.get("NATIVE_SAMPLING", cfg.get("glass_sampling", "live"))
        bridge.states.connect(self.on_states)
        bridge.backdrop.connect(self.on_backdrop)
        bridge.dim.connect(self.set_dim)
        bridge.frame.connect(self.on_frame)

    # -- what is drawn ----------------------------------------------------
    def build_overlay(self, dim=False):
        img = QImage(self.px_w, self.px_h, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        render.draw_widget(p, self.size_key, self.tiles, self.states, self.theme, None, self.scale, dim, self.style)
        p.end()
        pix = QPixmap.fromImage(img)
        if self.mask is None:
            m = QImage(self.px_w, self.px_h, QImage.Format_ARGB32_Premultiplied)
            m.fill(Qt.transparent)
            q = QPainter(m)
            q.setRenderHint(QPainter.Antialiasing)
            q.scale(self.scale, self.scale)
            cw, ch = render.widget_size(self.size_key)
            q.setPen(Qt.NoPen)
            q.setBrush(QColor(0, 0, 0))
            q.drawPath(render.squircle(0, 0, cw, ch, self.tcol["radius_panel"]))
            q.end()
            self.mask = m
        return pix

    # -- dimming ----------------------------------------------------------
    def set_dim(self, on):
        if on == self.dim_target:
            return
        self.dim_target = on
        self.dim_from = self.dim_t
        self.dim_clock.start()
        self.dim_timer.start()

    def step_dim(self):
        # 700 ms to dim, 260 ms to come back, eased as the page's transitions are.
        dur = 700 if self.dim_target else 260
        k = min(1.0, self.dim_clock.elapsed() / dur)
        k = k * k * (3 - 2 * k)
        goal = 1.0 if self.dim_target else 0.0
        self.dim_t = self.dim_from + (goal - self.dim_from) * k
        if k >= 1.0:
            self.dim_t = goal
            self.dim_timer.stop()
            if not self.dim_target:
                self.overlay_dim = None            # lit again: its picture is not kept
        self.update()

    def wake(self):
        if self.dim_target and watcher:
            watcher.wake()
            return True
        return False

    def paintEvent(self, event):
        if self.overlay is None:
            self.overlay = self.build_overlay()
        if self.dim_t > 0 and self.overlay_dim is None:
            self.overlay_dim = self.build_overlay(True)
        p = QPainter(self)
        if self.style == "liquid":
            if self.frame_img is not None:
                p.drawImage(0, 0, self.frame_img)
        elif self.backdrop_img is not None:
            f = QPainter(self.frame)
            f.setCompositionMode(QPainter.CompositionMode_Source)
            f.fillRect(self.frame.rect(), Qt.transparent)
            f.setRenderHint(QPainter.SmoothPixmapTransform)
            f.drawImage(QRectF(0, 0, self.px_w, self.px_h), self.backdrop_img)
            f.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            f.drawImage(0, 0, self.mask)
            f.end()
            p.drawImage(0, 0, self.frame)
        if self.dim_t <= 0:
            p.drawPixmap(0, 0, self.overlay)
        elif self.dim_t >= 1:
            p.drawPixmap(0, 0, self.overlay_dim)
        else:
            # A cross-fade: (1 - t) of the lit picture plus t of the dimmed one.
            m = QPainter(self.mix)
            m.setCompositionMode(QPainter.CompositionMode_Source)
            m.fillRect(self.mix.rect(), Qt.transparent)
            m.setCompositionMode(QPainter.CompositionMode_SourceOver)
            m.setOpacity(1 - self.dim_t)
            m.drawPixmap(0, 0, self.overlay)
            m.setCompositionMode(QPainter.CompositionMode_Plus)
            m.setOpacity(self.dim_t)
            m.drawPixmap(0, 0, self.overlay_dim)
            m.end()
            p.drawImage(0, 0, self.mix)
        p.end()

    def on_states(self, changed):
        self.states.update(changed)
        self.sample_now.set()
        self.overlay = self.overlay_dim = None
        self.update()

    def on_frame(self, _):
        self.frame_img = self.latest
        self.frame_queued.clear()
        self.update()

    def on_backdrop(self, image):
        self.backdrop_img = image
        self.update()

    # -- the mouse --------------------------------------------------------
    def tile_at(self, pos):
        """(tile, +1/-1 when a climate button was hit) at a window position."""
        x, y = pos.x() / self.scale, pos.y() / self.scale
        zoom = render.BIG_ZOOM if self.form == "big" else 1.0
        for tile, (tx, ty, tw, th) in zip(self.tiles, self.rects):
            if tx <= x < tx + tw and ty <= y < ty + th:
                st = self.states.get(tile["entity"])
                if tile["domain"] == "climate" and st and st.get("state") != "off":
                    local = QPointF((x - tx) / zoom, (y - ty) / zoom)
                    for rect, sign in render.mini_buttons(self.form, tw / zoom, th / zoom):
                        if rect.contains(local):
                            return tile, sign
                return tile, 0
        return None, 0

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self.wake():                    # the waking touch goes no further
                self._press = None
                return
            hit = self.tile_at(e.position().toPoint())
            self._press = (e.globalPosition().toPoint(), self.pos(), hit, False)

    def mouseMoveEvent(self, e):
        if not e.buttons():
            self.wake()
            return
        if self._press and e.buttons() & Qt.LeftButton:
            start, origin, hit, moved = self._press
            d = e.globalPosition().toPoint() - start
            if moved or abs(d.x()) + abs(d.y()) > 6:
                self.dragging = True
                self._press = (start, origin, hit, True)
                self.move(origin + QPoint(d.x(), d.y()))

    def mouseReleaseEvent(self, e):
        if self.dragging:
            self.dragging = False
            self.sample_now.set()                  # a still glass takes the picture where it was dropped
        if e.button() == Qt.RightButton and self.preview:
            QApplication.quit()
            return
        if self._press and not self._press[3] and self._press[2][0]:
            tile, sign = self._press[2]
            threading.Thread(target=quick_action, args=(tile, self.states, sign), daemon=True).start()
        self._press = None

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            QApplication.quit()


client = None
watcher = None


def quick_action(tile, states, step=0):
    domain, entity = tile["domain"], tile["entity"]
    try:
        if domain == "climate":
            st = states.get(entity) or {}
            attrs = st.get("attributes") or {}
            if step:                            # the round - and + on a long or big tile
                if attrs.get("temperature") is not None:
                    delta = step * float(tile.get("temp_step") or 1)
                    client.call_service("climate", "set_temperature", entity,
                                        {"temperature": round((attrs["temperature"] + delta) * 10) / 10})
            else:
                mode = "off" if st.get("state") != "off" else (tile.get("on_mode") or "cool")
                client.call_service("climate", "set_hvac_mode", entity, {"hvac_mode": mode})
        elif domain == "vacuum":
            cleaning = (states.get(entity) or {}).get("state") in ("cleaning", "returning")
            client.call_service("vacuum", "pause" if cleaning else "start", entity)
        elif domain in ("scene", "script"):
            client.call_service(domain, "turn_on", entity)
        elif domain == "automation":
            client.call_service("automation", "trigger", entity)
        elif domain in ("light", "switch", "fan", "input_boolean"):
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
    lens = None
    if win.style == "liquid":
        lens = liquid.Lens(win.px_w, win.px_h, win.tcol["radius_panel"] * win.scale)
        card = lens.card_mask()
        s = win.scale
        tiles = [(round(x * s), round(y * s), round(w * s), round(h * s), round(win.tcol["radius_tile"] * s))
                 for x, y, w, h in win.rects]
    after, last, sent = None, 0.0, None
    taken, covered_at, covered = False, 0.0, False
    while not stop.is_set():
        hwnd = int(win.winId())
        # Nothing to refresh while other windows hide the whole widget.
        if time.monotonic() - covered_at > 0.4:
            covered_at, covered = time.monotonic(), (not win.preview and idle.nothing_visible_of(hwnd))
        if covered:
            time.sleep(0.5)
            continue
        # A 'still' glass takes the desktop once and again only when told (dropped, changed);
        # while the widget is dragged it follows the screen.
        if win.sampling == "still" and taken and not win.dragging:
            if not win.sample_now.wait(1.0):
                continue
            after = None
        win.sample_now.clear()
        # The pace is set before the look, not after it: the picture is as fresh as can be.
        wait = 1 / 60 - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        last = time.monotonic()
        x, y, w, h = win.x(), win.y(), win.px_w, win.px_h
        got = dup.grab(x, y, w, h, after, 0.25) if dup.available() else None
        if not got:
            time.sleep(0.25)
            continue
        after = got[0]
        if got[1] is None:
            continue
        taken = True
        full = Image.frombuffer("RGBA", (w, h), got[1], "raw", "RGBA", 0, 1)
        if lens:
            # The liquid glass keeps 1/4 of the detail (main.py, the same steps).
            small = Image.frombytes("RGB", full.size, full.tobytes(), "raw", "BGRX")
            probe = small.reduce(8) if not (w % 8 or h % 8) else small.resize((max(1, round(w / 8)), max(1, round(h / 8))), Image.BOX)
        else:
            small = full.reduce(8) if not (w % 8 or h % 8) else full.resize((max(1, round(w / 8)), max(1, round(h / 8))), Image.BOX)
            small = Image.frombytes("RGB", small.size, small.tobytes(), "raw", "BGRX")
            probe = small
        if sent is not None and sent.size == probe.size and max(
                hi for _, hi in ImageChops.difference(sent, probe).getextrema()) <= 3:
            continue
        sent = probe
        if lens:
            out = lens.frame(liquid.picture(small), card, tiles, 8 * win.scale)
            win.latest = QImage(out.tobytes(), out.width, out.height, out.width * 4,
                                QImage.Format_RGBA8888).copy()
            if not win.frame_queued.is_set():           # only the newest is ever painted
                win.frame_queued.set()
                bridge.frame.emit(None)
            continue
        small = small.filter(ImageFilter.GaussianBlur(2))
        img = QImage(small.tobytes(), small.width, small.height, small.width * 3, QImage.Format_RGB888).copy()
        bridge.backdrop.emit(img)


def main():
    global client, watcher
    cfg = cfgmod.load_config()
    widget = cfg["widgets"][0]
    # NATIVE_SIZE=4x4 / NATIVE_TILES=4: look at other sizes and tile forms.
    if os.environ.get("NATIVE_SIZE") or os.environ.get("NATIVE_TILES"):
        tiles = widget["tiles"] * 4
        widget = dict(widget, size=os.environ.get("NATIVE_SIZE", widget["size"]),
                      tiles=tiles[:int(os.environ.get("NATIVE_TILES", len(widget["tiles"])))])
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    bridge = Bridge()
    win = NativeWidget(widget, cfg, bridge)
    win.show()
    hwnd = int(win.winId())
    user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
    # Windows 11 rounds the corners, outlines and shadows the window itself: none of it.
    dwm = ctypes.WinDLL("dwmapi")
    for attr, val in ((33, 1), (34, 0xFFFFFFFE), (2, 2)):    # no rounding, no border, no NC rendering
        v = ctypes.c_uint(val)
        dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), attr, ctypes.byref(v), 4)
    stop = threading.Event()
    watcher = idle.IdleWatcher(lambda: cfg.get("dim_when_idle", True), lambda: cfg.get("dim_after_sec", 120),
                               lambda: {hwnd}, bridge.dim.emit)
    watcher.start()
    # NATIVE_DIM=n: dim n seconds after the start (light again after 2n with NATIVE_DIM_BACK).
    if os.environ.get("NATIVE_DIM"):
        n = float(os.environ["NATIVE_DIM"])
        QTimer.singleShot(int(n * 1000), lambda: win.set_dim(True))
        if os.environ.get("NATIVE_DIM_BACK"):
            QTimer.singleShot(int(2 * n * 1000), lambda: win.set_dim(False))

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
    watcher.stop()
    client.stop()


if __name__ == "__main__":
    main()
