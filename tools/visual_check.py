"""Pictures of every screen and widget for looking at them before a change is called done (CLAUDE.md).

python tools/visual_check.py [outdir]     (default: visual/, which git ignores)

Writes, each at twice its size so misplaced pixels show:
  widgets.png   every kind of widget in light, dark and dimmed, and the tiles in every size
  editor.png    the widget editor, with the pointer over a tile (its remove badge)
  details.png   the detail of each kind of device, and of a switch shown as a lamp and as a lock
  home.png      the Home panel in edit mode (its badges)
Look for: text off-centre in its shape, uneven rows, badges and icons off their marks, words cut off,
anything unreadable on its background.

The screen sheets show content only. glass/ contains separate native-window captures through
the actual glass worker, with controlled bright, dark, busy and fine-pattern desktops.
"""
import datetime
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtCore import QRectF, Qt                                             # noqa: E402
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter              # noqa: E402
from PySide6.QtWidgets import QApplication                                        # noqa: E402

app = QApplication.instance() or QApplication([])

from nativeui import detail, kinds, panel, render, settings                      # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "visual"
K = 2                                     # pictures at twice their size
NOW = datetime.datetime(2026, 10, 4, 9, 41)
AGO = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=12)).isoformat()


def pump(ms):
    end = time.monotonic() + ms / 1000.0
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def backdrop(w, h):
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0, QColor("#5d7bb5"))
    g.setColorAt(1, QColor("#c28fa8"))
    p.fillRect(0, 0, w, h, g)
    p.end()
    return img


def sheet(images, cols, gap=24):
    """Pictures in a grid on a backdrop."""
    rows = [images[i:i + cols] for i in range(0, len(images), cols)]
    widths = [sum(i.width() for i in r) + gap * (len(r) + 1) for r in rows]
    heights = [max(i.height() for i in r) for r in rows]
    out = backdrop(max(widths), sum(heights) + gap * (len(rows) + 1))
    p = QPainter(out)
    y = gap
    for r, h in zip(rows, heights):
        x = gap
        for img in r:
            p.drawImage(x, y, img)
            x += img.width() + gap
        y += h + gap
    p.end()
    return out


TILES = [{"id": "t%d" % i, "entity": e, "domain": e.split(".")[0], "room": n, "label": "", "icon": ic}
         for i, (e, n, ic) in enumerate((("light.desk", "Desk lamp", ""), ("climate.ac", "Living room", ""),
                                         ("fan.office", "Office fan", ""), ("lock.front", "Front door", ""),
                                         ("switch.plug", "Kettle", "mdi:kettle"), ("cover.blinds", "Blinds", ""),
                                         ("sensor.t", "Temperature", ""), ("sensor.h", "Humidity", "")))]
STATES = {"light.desk": {"state": "on", "attributes": {"brightness": 180}},
          "climate.ac": {"state": "cool", "attributes": {"temperature": 24}},
          "fan.office": {"state": "on", "attributes": {"percentage": 65}},
          "lock.front": {"state": "locked", "attributes": {}}, "switch.plug": {"state": "on", "attributes": {}},
          "cover.blinds": {"state": "open", "attributes": {"current_position": 40}},
          "sensor.t": {"state": "27.5", "attributes": {"unit_of_measurement": "°C"}},
          "sensor.h": {"state": "61", "attributes": {"unit_of_measurement": "%"}},
          "weather.home": {"state": "partlycloudy", "attributes": {"temperature": 24}},
          "media_player.s": {"state": "playing", "attributes": {
              "media_title": "Golden Hour", "media_artist": "Demo Artist", "media_duration": 214,
              "media_position": 96, "media_position_updated_at": AGO, "supported_features": 16435}}}


def widget(kind, size, theme, dim, surface="classic"):
    w, h = render.widget_size(size)
    img = QImage(round(w * K), round(h * K), QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    if kind == "tiles":
        render.draw_widget(p, size, TILES, STATES, theme, None, K, dim, surface)
    else:
        tiles = {"weather": [{"id": "w", "entity": "weather.home", "domain": "weather", "room": "Home"}],
                 "camera": [{"id": "c", "entity": "camera.door", "domain": "camera", "room": "Door"}],
                 "chart": TILES[6:8],
                 "media": [{"id": "m", "entity": "media_player.s", "domain": "media_player", "room": "Study"}]}.get(kind, [])
        kinds.draw_widget(p, kind, size, tiles, STATES, theme, K, dim, surface, None, theme, {"now": NOW})
    p.end()
    return img


def widgets():
    images = []
    for theme, dim in (("light", False), ("dark", False), ("dark", True)):
        images += [widget(k, kinds.KIND_SIZE[k], theme, dim) for k in kinds.KINDS[1:]]
    images += [widget("tiles", s, "light", False) for s in render.SIZES]
    return sheet(images, 6)


def details(theme="light"):
    import test_native_panel as T
    shots = []
    cases = [("light.desk", "light", ""), ("climate.ac", "climate", ""), ("media_player.s", "media_player", ""),
             ("lock.front", "lock", ""), ("switch.plug", "switch", "mdi:floor-lamp"),
             ("switch.plug", "switch", "lock"), ("cover.blinds", "cover", ""), ("sensor.t", "sensor", "")]
    for entity, domain, icon in cases:
        api = T.FakeApi()
        original_prefs = api._prefs
        api._prefs = lambda: dict(original_prefs(), theme=theme)
        api.tiles = [{"id": "t", "entity": entity, "domain": domain, "room": entity, "label": "", "icon": icon}]
        win = detail.create_popover(api)
        card = win.native
        pump(80)
        card.push_states([(entity, dict(STATES[entity], last_changed=AGO))])
        card.open_tile("t")
        card.root.alpha, card.root.dy = 1, 0
        card.show()
        pump(250)
        img = card.content_image().copy()
        img.setDevicePixelRatio(1)
        shots.append(img)
        win.dispose()
    return sheet(shots, 4)


def desktop_detail_bounds(theme="light"):
    """The whole desktop detail and settings on a narrow work area at each zoom."""
    import test_desktop_popup_bounds as TB
    shots = []
    for zoom in (100, 150, 200):
        win, card = TB.DesktopPopupBounds().make_card(zoom)
        try:
            prefs = card.api._prefs()
            card.api._prefs = lambda: dict(prefs, theme=theme)
            card.apply_prefs(card.api._prefs())
            for editing in (False, True):
                card.set_edit(editing)
                pump(450)
                img = card.content_image().copy()
                img.setDevicePixelRatio(1)
                shots.append(img)
        finally:
            win.dispose()
    return sheet(shots, 2)


def editor(theme="light"):
    import test_native_settings as TS
    api = TS.FakeApi()
    original_prefs = api._prefs
    api._prefs = lambda: dict(original_prefs(), theme=theme)
    win = settings.create_settings(api)
    sc = win.native
    pump(100)
    sc.layout = api.get_layout()
    sc.open_editor("w1")
    sc.show()
    pump(300)
    sc.preview.hover = 0                  # the pointer over the first tile: its remove badge
    sc.preview.changed()
    pump(100)
    img = sc.content_image().copy()
    img.setDevicePixelRatio(1)
    win.dispose()
    return img


def home(theme="light"):
    import test_native_panel as T
    api = T.FakeApi("home", T.tiles_of(6))
    original_prefs = api._prefs
    api._prefs = lambda: dict(original_prefs(), theme=theme)
    win, sc = T.make_panel(api)
    pump(300)
    if sc.home is not None:
        sc.home.toggle_editing()
    pump(400)
    img = sc.content_image().copy()
    img.setDevicePixelRatio(1)
    win.dispose()
    return img


def categories(theme="light"):
    import test_native_panel as T
    api = T.FakeApi()
    original = api._prefs
    api._prefs = lambda: dict(original(), theme=theme)
    win, sc = T.make_panel(api)
    shots = []
    try:
        for category in ("env", "light", "security"):
            sc.home.toggle_category(category)
            pump(700)
            for editing in (False, True):
                if editing:
                    sc.home.toggle_editing()
                image = sc.content_image().copy()
                image.setDevicePixelRatio(1)
                shots.append(image)
        return sheet(shots, 3)
    finally:
        win.dispose()


def materials():
    """Backing/text swatches only; these do not exercise desktop capture, blur or refraction."""
    from nativeui import style, ui
    img = QImage(960, 360, QImage.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    for row, theme in enumerate(("light", "dark")):
        for col, desktop in enumerate(("#ffffff", "#000000")):
            box = QRectF(col * 480, row * 180, 480, 180)
            p.fillRect(box, QColor(desktop))
            pane = box.adjusted(16, 16, -16, -16)
            p.setPen(Qt.NoPen)
            p.setBrush(style.readable_backing(theme))
            p.drawRoundedRect(pane, 18, 18)
            colors = ui.ui_tokens(theme)
            for i, (role, text) in enumerate((("title", "客廳 Living room"),
                                             ("display", "24°"), ("secondary", "目前溫度 · Current temperature"))):
                style.center_text(p, text, style.font(role), render.parse_color(colors[style.TEXT[role][2]]),
                                  QRectF(pane.x(), pane.y() + 10 + i * 42, pane.width(), 42), "line")
    p.end()
    return img


def surfaces():
    return sheet([widget("tiles", "2x2", theme, dim, surface)
                  for surface in ("classic", "liquid", "windows")
                  for theme, dim in (("light", False), ("dark", False), ("dark", True))], 3)


def panel_glass_clip():
    """Compositor's stationary glass and moving foreground, over contrasting desktops."""
    import test_native_panel as T
    images = []
    for theme in ("light", "dark"):
        api = T.FakeApi("grid", T.tiles_of(1))
        prefs = dict(api._prefs(), theme=theme)
        api._prefs = lambda: prefs
        win, sc = T.make_panel(api)
        try:
            sc.latest = QImage(8, 8, QImage.Format_RGB888)
            sc.latest.fill(QColor("#b4cfdf" if theme == "light" else "#263c50"))
            sc._make_glass()
            extent = sc.ph + round(sc.ph * .4)
            glass, card = sc._slide_layers((sc.pw, extent))
            for background in ("#ffffff", "#101010"):
                for offset in (0, round(sc.ph * .35)):
                    image = QImage(sc.pw, extent, QImage.Format_ARGB32_Premultiplied)
                    image.fill(QColor(background))
                    p = QPainter(image)
                    p.setRenderHint(QPainter.Antialiasing)
                    from PySide6.QtGui import QPainterPath
                    clip = QPainterPath()
                    radius = min(sc.card_radius(), sc.css_w / 2, sc.css_h / 2) * sc.scale
                    outline = render.squircle(0, 0, sc.css_w * sc.scale, sc.css_h * sc.scale, radius)
                    columns = panel.dcomp.outline_columns([(p.x(), p.y()) for p in outline.toFillPolygon()],
                                                          sc.css_w * sc.scale, sc.css_h * sc.scale, radius)
                    for left, right, top, bottom in columns:
                        clip.addRect(QRectF(left, top + offset, right - left, bottom - top))
                    p.save()
                    p.setClipPath(clip)
                    p.drawImage(0, 0, glass)
                    p.restore()
                    p.drawImage(0, offset, card)
                    p.end()
                    images.append(image)
        finally:
            win.dispose()
    return sheet(images, 4)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    render.set_language("en")
    failed = []
    for name, make in (("widgets", widgets), ("details", details), ("editor", editor), ("home", home),
                       ("panel-glass-clip", panel_glass_clip),
                       ("desktop-detail-bounds", desktop_detail_bounds),
                       ("desktop-detail-bounds-dark", lambda: desktop_detail_bounds("dark")),
                       ("details-dark", lambda: details("dark")), ("editor-dark", lambda: editor("dark")),
                       ("home-dark", lambda: home("dark")), ("categories", categories),
                       ("categories-dark", lambda: categories("dark")), ("materials", materials), ("surfaces", surfaces)):
        try:
            img = make()
        except Exception as e:                 # one screen failing does not keep the others from being seen
            print(name, "failed:", e)
            failed.append(name)
            continue
        target = OUT / (name + ".png")
        img.save(str(target))
        print(target, img.width(), img.height())
    from tools import glass_review
    glass_review.main(OUT / "glass")
    from tools import gpu_glass_review
    gpu_glass_review.main()
    from tools import settings_review
    settings_review.main(OUT / "settings-review")
    from tools import panel_motion_review
    panel_motion_review.main()
    if failed:
        raise SystemExit("Failed visual checks: " + ", ".join(failed))


if __name__ == "__main__":
    main()
