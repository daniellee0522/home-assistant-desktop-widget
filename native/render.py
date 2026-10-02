"""Native drawing of a desktop widget: the same card and tiles as web/ draws,
painted with QPainter instead of a browser page.

Everything here is in CSS pixels (the widget is 678 x 334 for 2x4) and is
scaled to the screen by one factor, as the page's zoom does. The numbers are
the stylesheet's (web/style.css), the logic is app.js's (iconColorFor,
valueTextFor, defaultLabel...).
"""
import json
import math
import mmap
import os

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPolygonF, QTransform)
from PySide6.QtSvg import QSvgRenderer

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(os.path.dirname(HERE), "web")

CELL_W, CELL_H, PAD, GAP = 152, 146, 14, 14
RADIUS_TILE = 70
RADIUS_PANEL = RADIUS_TILE + PAD
SIZES = {"1x1": (1, 1), "2x2": (2, 2), "2x4": (4, 2), "4x4": (4, 4)}

THEMES = {
    "light": {
        "panel": (214, 228, 241, 0.4), "tile_off": (58, 66, 80, 0.42), "tile_on": (255, 255, 255, 1),
        "on_text1": "#1d1d1f", "on_text2": "#6e6e73", "off_text1": "#ffffff", "off_text2": "#ffffff",
        "edge": (255, 255, 255, 0.38), "edge_top": (255, 255, 255, 0.55), "edge_on": (0, 0, 0, 0.07),
    },
    "dark": {
        "panel": (28, 31, 37, 0.44), "tile_off": (30, 34, 41, 0.45), "tile_on": (255, 255, 255, 1),
        "on_text1": "#1d1d1f", "on_text2": "#6e6e73", "off_text1": "#f5f5f7", "off_text2": "#cfcfd4",
        "edge": (255, 255, 255, 0.14), "edge_top": (255, 255, 255, 0.22), "edge_on": (0, 0, 0, 0.1),
    },
}
# html.is-dimmed: the widget recedes by restyling its tokens, not fading a layer.
DIM = {"panel": (104, 120, 140, 0.26), "tile_on": (255, 255, 255, 0.30),
       "on_text1": (255, 255, 255, 0.95), "on_text2": (255, 255, 255, 0.74),
       "tile_off": (150, 160, 176, 0.18), "off_text1": (255, 255, 255, 0.85),
       "off_text2": (255, 255, 255, 0.64), "edge": (255, 255, 255, 0.14),
       "edge_on": (255, 255, 255, 0.22)}


def tokens(theme, dim=False):
    t = dict(THEMES[theme])
    if dim:
        t.update(DIM)
    return t


ACCENT = {"yellow": "#ffb320", "blue": "#409cff", "cyan": "#48aaff", "green": "#34c759",
          "teal": "#2fd0c2", "red": "#ff5b4a"}
LIGHT_THEME_BULB = "#ffbe6c"
HVAC_COLORS = {"cool": "#3fa9f5", "heat": "#ff7a45", "heat_cool": "#34c759",
               "auto": "#34c759", "dry": "#f0b429", "fan_only": "#8e9aaf"}
EMBOLDEN = float(os.environ.get('NATIVE_EMBOLDEN', '0'))
FAMILIES = ["Segoe UI Variable", "Segoe UI", "Microsoft JhengHei UI", "Microsoft JhengHei"]


def parse_color(c):
    """A CSS colour ('#rrggbb', 'rgb(r,g,b)') or an (r, g, b[, a]) tuple as a QColor."""
    if isinstance(c, QColor):
        return c
    if isinstance(c, tuple):
        return rgba(c)
    if c.startswith("rgb("):
        r, g, b = (int(v) for v in c[4:-1].split(",")[:3])
        return QColor(r, g, b)
    return QColor(c)


def rgba(c, alpha=None):
    r, g, b, a = (c if len(c) == 4 else (*c, 1))
    return QColor(r, g, b, round(255 * (a if alpha is None else alpha)))


# ---------------------------------------------------------------- shapes

def squircle(x, y, w, h, r, steps=16):
    """The fourth-power superellipse corner every radius in the page uses
    (corner-shape: superellipse(2)); same points as traceSuperellipse."""
    r = min(r, w / 2, h / 2)
    pts = []
    for cx, cy, start in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0),
                          (x + r, y + h - r, 90), (x + r, y + r, 180)):
        for i in range(steps + 1):
            a = math.radians(start) + i * math.pi / 2 / steps
            c, s = math.cos(a), math.sin(a)
            pts.append(QPointF(cx + r * math.copysign(abs(c) ** 0.5, c),
                               cy + r * math.copysign(abs(s) ** 0.5, s)))
    path = QPainterPath()
    path.addPolygon(QPolygonF(pts))
    path.closeSubpath()
    return path


def inner_shadow(p, shape, color, dy=0.0, spread=1.0):
    """CSS `inset 0 dy 0 spread`: the shape's inside minus itself moved by
    (0, dy) and shrunk by `spread` on every side, in `color`."""
    ring = QPainterPath(shape)
    box = shape.boundingRect()
    sx, sy = (box.width() - 2 * spread) / box.width(), (box.height() - 2 * spread) / box.height()
    t = QTransform()
    t.translate(box.center().x(), box.center().y() + dy)
    t.scale(sx, sy)
    t.translate(-box.center().x(), -box.center().y())
    hole = t.map(shape)
    p.save()
    p.setClipPath(shape)
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawPath(ring.subtracted(hole))
    p.restore()


# ----------------------------------------------------------------- icons

_icons = None
_mdi_file = None
_svg_cache = {}


def _icon_table():
    global _icons
    if _icons is None:
        with open(os.path.join(HERE, "icon_paths.json"), encoding="utf-8") as f:
            _icons = json.load(f)
    return _icons


def mdi_path(name):
    """One icon's path from the 2.7 MB file, without reading it all in."""
    global _mdi_file
    if _mdi_file is None:
        f = open(os.path.join(WEB, "mdi-paths.js"), "rb")
        _mdi_file = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    key = b'"' + name.encode() + b'":"'
    i = _mdi_file.find(key)
    if i < 0:
        return None
    start = i + len(key)
    return _mdi_file[start:_mdi_file.find(b'"', start)].decode()


LEGACY_MDI = {"climate": "air-conditioner", "cover": "blinds", "curtain": "curtains",
              "vacuum": "robot-vacuum", "scene": "palette", "automation": "robot"}


def svg_renderer(name, color):
    key = (name, color)
    r = _svg_cache.get(key)
    if r is None:
        mdi = name[4:] if name.startswith("mdi:") else LEGACY_MDI.get(name)
        d = mdi_path(mdi) if mdi else None
        body = '<path d="%s"/>' % d if d else _icon_table().get(name) or _icon_table()["sensor"]
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="%s">%s</svg>'
               % (color, body))
        r = _svg_cache[key] = QSvgRenderer(QByteArray(svg.encode()))
    return r


# ------------------------------------------------------- tile semantics

def is_unlocked(st):
    s = st and st.get("state")
    return bool(s) and s not in ("locked", "locking", "unavailable", "unknown")


def is_on(domain, st):
    if not st:
        return False
    s = st.get("state")
    if domain == "climate":
        return bool(s) and s != "off"
    if domain == "cover":
        return s == "open"
    if domain == "lock":
        return is_unlocked(st)
    if domain == "media_player":
        return s == "playing"
    if domain == "vacuum":
        return s in ("cleaning", "returning")
    return s == "on"


MOMENTARY = ("scene", "script", "automation")
READONLY = ("sensor", "binary_sensor")
DEFAULT_ICON = {"light": "light", "switch": "switch", "input_boolean": "switch",
                "climate": "mdi:air-conditioner", "fan": "fan", "cover": "mdi:blinds",
                "media_player": "media", "lock": "lock", "vacuum": "mdi:robot-vacuum",
                "scene": "mdi:palette", "script": "script", "automation": "mdi:robot",
                "sensor": "sensor", "binary_sensor": "sensor"}


def icon_name(tile, st):
    if tile.get("icon"):
        return tile["icon"]
    attrs = (st or {}).get("attributes") or {}
    ha = attrs.get("icon")
    if isinstance(ha, str) and ha.startswith("mdi:") and mdi_path(ha[4:]):
        return ha
    domain = tile["domain"]
    if domain == "lock" and is_unlocked(st):
        return "lock-open"
    if domain == "sensor":
        unit = attrs.get("unit_of_measurement") or ""
        if attrs.get("device_class") == "temperature" or unit.startswith("°"):
            return "thermometer"
        if attrs.get("device_class") == "humidity" or unit == "%":
            return "humidity"
    return DEFAULT_ICON.get(domain, "sensor")


def icon_color(tile, st, on, theme, tcol):
    domain = tile["domain"]
    attrs = (st or {}).get("attributes") or {}
    off = tcol["off_text1"]
    if domain == "light":
        if not on:
            return off
        if isinstance(attrs.get("rgb_color"), list) and attrs.get("color_mode") in ("hs", "rgb", "rgbw", "rgbww", "xy"):
            return "rgb(%d,%d,%d)" % tuple(attrs["rgb_color"][:3])
        return ACCENT["yellow"] if theme == "dark" else LIGHT_THEME_BULB
    if domain in ("switch", "input_boolean", "fan", "cover", "vacuum"):
        return ACCENT["blue"] if on else off
    if domain == "climate":
        return ACCENT["cyan"] if on else off
    if domain == "media_player":
        return ACCENT["green"] if on else off
    if domain == "lock":
        return ACCENT["teal"] if is_unlocked(st) else off
    if domain in MOMENTARY:
        return ACCENT["blue"]
    if domain == "binary_sensor":
        return ACCENT["green"] if st and st.get("state") == "on" else off
    return off


def value_text(domain, st):
    if not st:
        return ""
    attrs = st.get("attributes") or {}
    if domain == "climate":
        if st.get("state") != "off" and attrs.get("temperature") is not None:
            return "%s°" % attrs["temperature"]
        return ""
    if domain == "sensor":
        unit = attrs.get("unit_of_measurement") or ""
        return st["state"] + (unit if unit.startswith("°") else (" " + unit if unit else ""))
    if domain == "binary_sensor":
        return "偵測到" if st.get("state") == "on" else "正常"
    return ""


def media_label(st):
    s = st.get("state", "")
    attrs = st.get("attributes") or {}
    track = " · ".join(x for x in (attrs.get("media_title"), attrs.get("media_artist")) if x)
    if s == "playing":
        return track or attrs.get("app_name") or "播放中"
    if s == "paused":
        return "已暫停" + (" · " + track if track else "")
    return {"off": "關閉", "idle": "待機", "standby": "待機", "unavailable": "無法連線"}.get(s, s)


def default_label(domain, st):
    s = st.get("state", "") if st else ""
    words = {"locked": "已上鎖", "locking": "上鎖中", "unlocked": "未上鎖", "unlocking": "解鎖中",
             "open": "已開啟", "opening": "開啟中", "jammed": "卡住了",
             "unavailable": "無法連線", "unknown": "狀態不明"}
    return {
        "light": "燈光", "switch": "插座", "input_boolean": "虛擬開關", "climate": s, "fan": "風扇",
        "cover": "開啟" if s == "open" else "關閉" if s == "closed" else s,
        "media_player": media_label(st or {}), "lock": words.get(s, "未上鎖"),
        "vacuum": s, "scene": "場景", "script": "腳本", "automation": "自動化",
        "binary_sensor": "偵測到" if s == "on" else "正常",
    }.get(domain, s)


def climate_badge(st, on):
    attrs = (st or {}).get("attributes") or {}
    temp = attrs.get("temperature", attrs.get("current_temperature"))
    try:
        temp = float(temp)
    except (TypeError, ValueError):
        return None
    text = ("%g" % (round(temp * 10) / 10)) + "°"
    return {"text": text, "bg": HVAC_COLORS.get(st.get("state"), ACCENT["cyan"]) if on else "#ffffff",
            "fg": "#ffffff" if on else "#1d1d1f"}


# --------------------------------------------------------------- drawing

_app_font = None
WOFF = int(os.environ.get('NATIVE_WOFF', '40'))


def _variable_font():
    """Segoe UI Variable from its file, so the weight and optical size can be
    set as the page's text has them (the system's own registration hides the
    axes). Only with Qt's FreeType font engine (see widget_native.py)."""
    global _app_font
    if _app_font is None:
        _app_font = ""
        path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "SegUIVar.ttf")
        if os.path.exists(path):
            from PySide6.QtGui import QFontDatabase
            fid = QFontDatabase.addApplicationFont(path)
            fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
            _app_font = fams[0] if fams else ""
    return _app_font


def font(px, weight, spacing=0.0):
    f = QFont()
    var = _variable_font()
    f.setFamilies(([var] if var else []) + FAMILIES)
    # Drawn ten times too big and scaled back, so 19.5 px is 19.5 px.
    f.setPixelSize(max(10, round(px * 10)))
    f.setWeight(weight)
    if var:
        f.setVariableAxis(QFont.Tag("wght"), min(900, int(getattr(weight, "value", weight)) + WOFF))
        f.setVariableAxis(QFont.Tag("opsz"), px)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing * 10)
    f.setStyleStrategy(QFont.PreferAntialias | QFont.NoSubpixelAntialias)
    f.setHintingPreference(QFont.PreferNoHinting)
    return f


HSCALE = float(os.environ.get("NATIVE_HSCALE", "1.0"))


def text_path(origin, f, text, x, y):
    """The text as an outline at (x, y) on its baseline, from a font ten times
    the size and scaled back (and narrowed by HSCALE: Chrome sets this font a
    little tighter than Qt does)."""
    path = QPainterPath()
    path.addText(origin, f, text)
    t = QTransform()
    t.translate(x, y)
    t.scale(0.1 * HSCALE, 0.1)
    return t.map(path)


def draw_text_fade(p, text, f, color, rect, shadow):
    """One line of text, clipped at the tile's edge with the same 16 px fade
    the page's mask gives it, and the page's text shadow when the tile is
    dark."""
    p.save()
    p.setClipRect(rect)
    fm = QFontMetricsF(f)
    width = fm.horizontalAdvance(text) / 10 * HSCALE
    base = QPointF(0, (fm.height() / 10 * 0 + 0))
    # position of the text's baseline inside its line box (centred)
    base_y = rect.top() + (rect.height() - fm.height() / 10) / 2 + fm.ascent() / 10
    if shadow:
        # A tight edge and a wide halo: 0 1px 2px .55 and 0 0 7px .45.
        halo = text_path(base, f, text, rect.left(), base_y)
        for width_px, alpha, dy in ((7, 0.045, 0), (4.5, 0.06, 0), (2.5, 0.12, 1)):
            pen = QPen(QColor(0, 0, 0, round(255 * alpha)), width_px, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.save()
            p.translate(0, dy)
            p.drawPath(halo)
            p.restore()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 100))
        p.save()
        p.translate(0, 1)
        p.drawPath(halo)
        p.restore()
    col = parse_color(color)
    # The page's mask always fades the last 16 px of the box, whatever the text.
    g = QLinearGradient(rect.left(), 0, rect.right(), 0)
    g.setColorAt(0, col)
    g.setColorAt(max(0.0, (rect.width() - 16) / rect.width()), col)
    clear = QColor(col)
    clear.setAlpha(0)
    g.setColorAt(1, clear)
    brush = QBrush(g)
    # As outlines, which are anti-aliased in greys (the page's text is); Qt's
    # own glyph drawing would colour the edges (ClearType).
    path = text_path(base, f, text, rect.left(), base_y)
    p.setPen(Qt.NoPen)
    p.setBrush(brush)
    p.drawPath(path)
    if EMBOLDEN:
        # Chrome's text is a touch heavier than Qt's at the same weight.
        p.setPen(QPen(brush, EMBOLDEN))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
    p.restore()


FORM_SPAN = {"small": (1, 1), "bar": (2, 1), "big": (2, 2)}
BIG_ZOOM = 1.4


def form_for(cols, rows, count):
    """Which tile form fills the widget for this many tiles (tileFormFor)."""
    cells = cols * rows
    if count > 0 and cells >= 4 and count <= cells / 4:
        return "big"
    if count > 0 and cells >= 2 and count <= cells / 2:
        return "bar"
    return "small"


def tile_layout(size, count):
    """(form, [(x, y, w, h) per tile that fits]) of a widget, in CSS pixels."""
    cols, rows = SIZES.get(size, SIZES["2x4"])
    form = form_for(cols, rows, count)
    sc, sr = FORM_SPAN[form]
    per_row = cols // sc
    w, h = sc * CELL_W + (sc - 1) * GAP, sr * CELL_H + (sr - 1) * GAP
    rects = []
    for i in range(min(count, per_row * (rows // sr))):
        rects.append((PAD + (i % per_row) * sc * (CELL_W + GAP),
                      PAD + (i // per_row) * sr * (CELL_H + GAP), w, h))
    return form, rects


def mini_buttons(form, cw, ch):
    """The climate tile's round - and + in the tile's own units: [(rect, delta sign)]."""
    if form == "bar":
        x, top = cw - 16 - 40, (ch - 90) / 2
        return [(QRectF(x, top, 40, 40), -1), (QRectF(x, top + 50, 40, 40), 1)]
    if form == "big":
        x, y = cw - 14 - 44, ch - 14 - 44
        return [(QRectF(x - 12 - 44, y, 44, 44), -1), (QRectF(x, y, 44, 44), 1)]
    return []


def draw_icon(p, name, color, rect):
    """An icon in a colour that may be translucent (an rgba tuple)."""
    opacity = 1.0
    if isinstance(color, tuple):
        opacity = color[3] if len(color) == 4 else 1.0
        color = "#%02x%02x%02x" % tuple(color[:3])
    p.save()
    p.setOpacity(p.opacity() * opacity)
    svg_renderer(name, color).render(p, rect)
    p.restore()


def draw_centred(p, text, f, color, rect):
    """A short text centred in a box, as a flex box centres a line."""
    fm = QFontMetricsF(f)
    tw = fm.horizontalAdvance(text) / 10 * HSCALE
    p.setPen(Qt.NoPen)
    p.setBrush(parse_color(color))
    p.drawPath(text_path(QPointF(0, 0), f, text, rect.left() + (rect.width() - tw) / 2,
                         rect.top() + (rect.height() - fm.height() / 10) / 2 + fm.ascent() / 10))


def draw_content(p, tile, st, cw, ch, form, theme, tcol, dim):
    """What is on a tile, in the tile's own units (a big tile is these units
    zoomed by 1.4), from its top-left corner."""
    domain = tile["domain"]
    ok = st is not None
    on = ok and domain not in MOMENTARY and is_on(domain, st)
    roomy = form != "small"
    shown = climate_badge(st, on) if domain == "climate" and ok and not tile.get("icon") else None
    reading = shown if roomy else None
    badge = None if roomy else shown
    readonly = domain in READONLY
    value = value_text(domain, st) if ok and not badge and not reading else ""
    readout = readonly and bool(value)
    c1 = tcol["on_text1"] if on else tcol["off_text1"]
    c2 = tcol["on_text2"] if on else tcol["off_text2"]
    label = ((tile.get("label") or default_label(domain, st)) if ok else "無法連線")
    name = tile.get("room") or (st or {}).get("attributes", {}).get("friendly_name") or tile["entity"]
    icolor = icon_color(tile, st, on, theme, tcol) if ok else tcol["off_text1"]
    if dim:
        icolor = (255, 255, 255, 0.95) if on else tcol["off_text1"]

    # -- the icon ------------------------------------------------------
    if form == "bar":
        dx, dy = 23, (ch - 100) / 2
        if reading:
            text = reading["text"].replace("°", "") + " °C"
            f = font(34, QFont.Bold, -0.5)
            fm = QFontMetricsF(f)
            p.setPen(Qt.NoPen)
            p.setBrush(parse_color(c1))
            p.drawPath(text_path(QPointF(0, 0), f, text, dx,
                                 (ch - fm.height() / 10) / 2 + fm.ascent() / 10))
        else:
            if dim:
                disc = (255, 255, 255, 0.20 if on else 0.10)
                glyph = (255, 255, 255, 0.92)
            else:
                disc = parse_color(icolor) if on else QColor(14, 18, 24, 51)
                glyph = "#ffffff" if on else icolor
            p.setPen(Qt.NoPen)
            p.setBrush(parse_color(disc))
            p.drawEllipse(QRectF(dx, dy, 100, 100))
            draw_icon(p, icon_name(tile, st), glyph, QRectF(dx + 26, dy + 26, 48, 48))
    else:
        pad = 18 if form == "big" else 14
        size = 52 if form == "big" else 40
        ix, iy = pad, pad
        if reading:
            f = font(60, QFont.Bold, -0.5)
            fm = QFontMetricsF(f)
            p.setPen(Qt.NoPen)
            p.setBrush(parse_color(c1))
            p.drawPath(text_path(QPointF(0, 0), f, reading["text"].replace("°", "") + " °C", ix,
                                 iy + (60 - fm.height() / 10) / 2 + fm.ascent() / 10))
        elif badge:
            box = QRectF(ix, iy, size, size)
            if dim:
                bg = (255, 255, 255, 0.12) if on else None
                fg = (255, 255, 255, 0.95) if on else tcol["off_text1"]
            else:
                bg, fg = QColor(badge["bg"]), badge["fg"]
            if bg is not None:
                p.setPen(Qt.NoPen)
                p.setBrush(parse_color(bg))
                p.drawEllipse(box)
            draw_centred(p, badge["text"], font(17.5, QFont.Bold), fg, box)
        else:
            draw_icon(p, icon_name(tile, st), icolor, QRectF(ix, iy, size, size))

    # -- the text ------------------------------------------------------
    if form == "bar":
        tx, tw = 139, cw - 23 - 139
        items = []
        if value:
            items.append((value, font(32, QFont.Bold), c1, 35.2, 0))
        items.append((name, font(25, QFont.Medium if readonly else QFont.DemiBold),
                      (c1 if on else tcol["off_text2"]) if readout else c1, 30,
                      1 if readout else 0))
        if not readout:
            items.append((label, font(20, QFont.Medium), c2, 24, 1))
        y = (ch - sum(h + before for _, _, _, h, before in items)) / 2
        for text, f, color, h, before in items:
            y += before
            draw_text_fade(p, text, f, color, QRectF(tx, y, tw, h), False)
            y += h
    else:
        big = form == "big"
        pad = 18 if big else 14
        textw = cw - 2 * pad
        bottom = ch - pad
        if not readout:
            lh = (17.5 if big else 16.5) * 1.2
            draw_text_fade(p, label, font(17.5 if big else 16.5, QFont.Medium), c2,
                           QRectF(pad, bottom - lh, textw, lh), False)
            bottom -= lh + 1
        if readout:
            draw_text_fade(p, name, font(16.5, QFont.Medium), c1 if on else tcol["off_text2"],
                           QRectF(pad, bottom - 19.8, textw, 19.8), False)
            bottom -= 19.8 + 1
            draw_text_fade(p, value, font(27, QFont.Bold), c1,
                           QRectF(pad, bottom - 29.7, textw, 29.7), False)
        else:
            nh = (21 if big else 19.5) * 1.2
            draw_text_fade(p, name, font(21 if big else 19.5, QFont.DemiBold), c1,
                           QRectF(pad, bottom - nh, textw, nh), False)
            if value:
                draw_text_fade(p, value, font(25.5, QFont.Bold), c1,
                               QRectF(pad, 78 if big else 56, textw, 28), False)

    # -- the climate buttons, always there on a long or big tile ----------
    if domain == "climate" and on:
        f = font(26 if form == "bar" else 28, QFont.Bold)
        for rect, sign in mini_buttons(form, cw, ch):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 20))
            p.drawEllipse(rect)
            draw_centred(p, "+" if sign > 0 else "\u2212", f, "#1d1d1f", rect)


def draw_tile(p, tile, st, x, y, w, h, theme, tcol, form="small", dim=False):
    domain = tile["domain"]
    on = st is not None and domain not in MOMENTARY and is_on(domain, st)
    shape = squircle(x, y, w, h, RADIUS_TILE)
    p.setPen(Qt.NoPen)
    p.setBrush(rgba(tcol["tile_on"] if on else tcol["tile_off"]))
    p.drawPath(shape)
    if on:
        inner_shadow(p, shape, rgba(tcol["edge_on"]))
    else:
        inner_shadow(p, shape, rgba(tcol["edge"]))
        inner_shadow(p, shape, rgba(tcol["edge_top"]), dy=1, spread=0)
    zoom = BIG_ZOOM if form == "big" else 1.0
    p.save()
    p.translate(x, y)
    p.scale(zoom, zoom)
    draw_content(p, tile, st, w / zoom, h / zoom, form, theme, tcol, dim)
    p.restore()


def widget_size(size):
    cols, rows = SIZES.get(size, SIZES["2x4"])
    return (cols * CELL_W + (cols - 1) * GAP + 2 * PAD, rows * CELL_H + (rows - 1) * GAP + 2 * PAD)


def draw_widget(p, size, tiles, states, theme, backdrop=None, scale=1.0, dim=False):
    """The whole widget at (0, 0). `backdrop` is the small blurred picture of
    the desktop behind it (a QImage), stretched over the card."""
    tcol = tokens(theme, dim)
    W, H = widget_size(size)
    form, rects = tile_layout(size, len(tiles))
    p.save()
    p.scale(scale, scale)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
    card = squircle(0, 0, W, H, RADIUS_PANEL)
    if backdrop is not None:
        p.save()
        p.setClipPath(card)
        p.drawImage(QRectF(0, 0, W, H), backdrop)
        p.restore()
    p.setPen(Qt.NoPen)
    p.setBrush(rgba(tcol["panel"]))
    p.drawPath(card)
    inner_shadow(p, card, rgba(tcol["edge"]))
    inner_shadow(p, card, rgba(tcol["edge_top"]), dy=1, spread=0)
    for tile, (x, y, w, h) in zip(tiles, rects):
        draw_tile(p, tile, states.get(tile["entity"]), x, y, w, h, theme, tcol, form, dim)
    p.restore()
