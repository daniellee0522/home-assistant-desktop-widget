"""Drawing a desktop widget with QPainter: its card and tiles, and what the other windows share
(the colours, the icons, the text, what a tile shows for each kind of device).

Everything here is in CSS pixels (the widget is 678 x 334 for 2x4) and is scaled to the screen
by one factor (the zoom times the monitor's DPI).
"""
import json
import math
import mmap
import os
import re
import sys

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPolygonF, QTransform)
from PySide6.QtSvg import QSvgRenderer

from . import appearance, i18n

HERE = os.path.dirname(os.path.abspath(__file__))
# Frozen, this package's data files live under PyInstaller's _MEIPASS.
DATA = os.path.join(sys._MEIPASS, "nativeui") if hasattr(sys, "_MEIPASS") else HERE

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


# data-glass-style="liquid": clearer glass, tiles 62 px round, and the tint of the
# card, the tiles and their rims are lighter (the rims are literals in the stylesheet).
LIQUID = {
    "light": {"panel": (226, 239, 248, 0.18), "tile_off": (39, 55, 73, 0.3),
              "tile_on": (245, 251, 255, 0.44)},
    "dark": {"panel": (26, 29, 34, 0.7), "tile_off": (18, 26, 37, 0.54),
             "tile_on": (232, 242, 250, 0.68)},
}
LIQUID_RIMS = {"edge": (255, 255, 255, 0.2), "edge_top": (255, 255, 255, 0.48),
               "edge_on": (255, 255, 255, 0.35), "edge_on_top": (255, 255, 255, 0.7),
               "card_edge": (255, 255, 255, 0.24), "card_edge_top": (255, 255, 255, 0.42)}
LIQUID_DARK_DIM = {"panel": (26, 29, 34, 0.52), "tile_on": (53, 63, 76, 0.52),
                   "on_text1": (255, 255, 255, 0.9), "on_text2": (226, 235, 242, 0.72),
                   "tile_off": (18, 26, 37, 0.4)}
# data-glass-style="windows": a frosted pane in the Windows manner; tiles 32 px round, a
# thin light rim and no top highlight.
WINDOWS = {"light": {"panel": (231, 237, 244, 0.72), "tile_off": (58, 68, 81, 0.66)},
           "dark": {"panel": (33, 38, 46, 0.76), "tile_off": (58, 68, 81, 0.66)}}
WINDOWS_RIMS = {"edge": (255, 255, 255, 0.2), "edge_top": None, "edge_on": (255, 255, 255, 0.2),
                "edge_on_top": None, "card_edge": (255, 255, 255, 0.42), "card_edge_top": None}
RADII = {"classic": 70, "liquid": 62, "windows": 32}


def tokens(theme, dim=False, style="classic"):
    t = dict(THEMES[theme])
    t["card_edge"], t["card_edge_top"], t["edge_on_top"] = t["edge"], t["edge_top"], None
    t["style"] = style
    t["radius_tile"] = RADII.get(style, 70)
    t["radius_panel"] = t["radius_tile"] + PAD
    if style == "liquid":
        t.update(LIQUID[theme])
        t.update(LIQUID_RIMS)
    elif style == "windows":
        t.update(WINDOWS[theme])
        t.update(WINDOWS_RIMS)
    if dim:
        # The rims of the liquid and Windows tiles are literals: the dimmed tokens do not
        # reach them (the Windows card's rim is a token).
        keep = ("edge", "edge_on") if style != "classic" else ()
        t.update({k: v for k, v in DIM.items() if k not in keep})
        if style != "liquid":
            t["card_edge"] = DIM["edge"]
        if style == "liquid" and theme == "dark":
            t.update(LIQUID_DARK_DIM)
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


_language = "zh-TW"


def set_language(language):
    global _language
    _language = language


def tr(text):
    return i18n.translate(text, _language)


def rgba(c, alpha=None):
    r, g, b, a = (c if len(c) == 4 else (*c, 1))
    return QColor(r, g, b, round(255 * (a if alpha is None else alpha)))


# ---------------------------------------------------------------- shapes

def squircle(x, y, w, h, r, steps=16):
    """The fourth-power superellipse corner every rounded shape uses
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
        with open(os.path.join(DATA, "icon_paths.json"), encoding="utf-8") as f:
            _icons = json.load(f)
    return _icons


def mdi_path(name):
    """One icon's path from the 2.7 MB file, without reading it all in."""
    global _mdi_file
    if _mdi_file is None:
        with open(os.path.join(DATA, "mdi_paths.json"), "rb") as f:     # the map keeps its own handle
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
        if name.startswith("path:"):                # a path of the 24 px grid given as it is
            body = '<path d="%s"/>' % name[5:]
        else:
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
READONLY = ("sensor", "binary_sensor", "weather", "camera")


def is_readonly(domain):
    """Sensors and every kind of device the widget has no control for."""
    return domain in READONLY or domain not in DEFAULT_ICON


def has_detail_on_hold(domain):
    """Tapped it acts; held it opens the detail card (a lock and the momentary kinds do not)."""
    return domain in ("light", "switch", "input_boolean", "climate", "fan", "cover", "media_player", "vacuum")
DEFAULT_ICON = {"light": "light", "switch": "mdi:toggle-switch-variant", "input_boolean": "mdi:toggle-switch-variant",
                "climate": "mdi:air-conditioner", "fan": "fan", "cover": "mdi:blinds",
                "media_player": "media", "lock": "lock", "vacuum": "mdi:robot-vacuum",
                "scene": "mdi:palette", "script": "script", "automation": "mdi:robot",
                "sensor": "sensor", "binary_sensor": "sensor", "weather": "mdi:weather-partly-cloudy",
                "camera": "mdi:cctv"}


def is_open(tile, st):
    """Whether the tile's thing is open: an unlocked lock (or a switch shown as one), an open cover."""
    fam = appearance.family(tile)
    if fam == "lock":
        return is_unlocked(st) if tile["domain"] == "lock" else bool(st) and st.get("state") == "on"
    return fam == "cover" and bool(st) and st.get("state") in ("open", "opening")


def icon_name(tile, st):
    """The tile's icon (appearance.py): its own, or Home Assistant's, or its family's; in its open shape
    when it is open."""
    icon = tile.get("icon")
    if not icon:
        attrs = (st or {}).get("attributes") or {}
        ha = attrs.get("icon")
        if isinstance(ha, str) and ha.startswith("mdi:") and mdi_path(ha[4:]):
            icon = ha
        elif tile["domain"] == "sensor":
            unit = attrs.get("unit_of_measurement") or ""
            if attrs.get("device_class") == "temperature" or unit.startswith("°"):
                icon = "thermometer"
            elif attrs.get("device_class") == "humidity" or unit == "%":
                icon = "humidity"
        icon = icon or appearance.own_icon(tile)
    return appearance.open_shape(icon) if is_open(tile, st) else icon


def light_color(st, theme):
    attrs = (st or {}).get("attributes") or {}
    if isinstance(attrs.get("rgb_color"), list) and attrs.get("color_mode") in ("hs", "rgb", "rgbw", "rgbww", "xy"):
        return "rgb(%d,%d,%d)" % tuple(attrs["rgb_color"][:3])
    return ACCENT["yellow"] if theme == "dark" else LIGHT_THEME_BULB


def icon_color(tile, st, on, theme, tcol):
    """The icon's colour, by what the tile is shown as (appearance.family): its family's colour when on."""
    fam = appearance.family(tile)
    off = tcol["off_text1"]
    if fam == "scene":
        return ACCENT["blue"]
    if not on or fam not in appearance.COLORS:
        return off
    if fam == "light":
        return light_color(st if tile["domain"] == "light" else None, theme)
    return ACCENT[appearance.COLORS[fam]]


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
        if not unit and attrs.get("device_class") == "temperature":
            unit = "°"                        # a temperature that does not say °C or °F
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


STATE_WORDS = {"locked": "已上鎖", "locking": "上鎖中", "unlocked": "未上鎖", "unlocking": "解鎖中",
               "open": "已開啟", "opening": "開啟中", "jammed": "卡住了", "closed": "關閉", "closing": "關閉中",
               "unavailable": "無法連線", "unknown": "狀態不明"}
HVAC_WORDS = {"off": "關閉", "cool": "冷氣", "heat": "暖氣", "heat_cool": "自動", "auto": "自動", "dry": "除濕",
              "fan_only": "送風"}
VACUUM_WORDS = {"cleaning": "清掃中", "docked": "已回充", "returning": "回充中", "paused": "已暫停", "idle": "待命",
                "error": "錯誤"}


def state_text(tile, st):
    """The words under a tile's name: what it is doing now (an on/off thing in its family's words: a switch
    shown as a lock is unlocked or locked). Sensors show their reading instead (draw_content)."""
    domain = tile["domain"]
    s = st.get("state", "") if st else ""
    attrs = (st or {}).get("attributes") or {}
    if s in ("unavailable", "unknown"):
        return STATE_WORDS[s]
    if domain in MOMENTARY:
        return {"scene": "場景", "script": "腳本", "automation": "自動化"}[domain]
    if domain == "media_player":
        return media_label(st or {})
    if domain == "climate":
        return HVAC_WORDS.get(s, s)
    if domain == "lock":
        return STATE_WORDS.get(s, "未上鎖")
    if domain == "cover":
        pos = attrs.get("current_position")
        return "%d%%" % pos if s == "open" and isinstance(pos, (int, float)) and 0 < pos < 100 else STATE_WORDS.get(s, s)
    if domain == "vacuum":
        return VACUUM_WORDS.get(s, s)
    if domain == "binary_sensor":
        return "偵測到" if s == "on" else "正常"
    if domain not in ("switch", "input_boolean", "light", "fan"):
        return s
    on_words, off_words = appearance.words(tile)
    if s != "on":
        return off_words
    if domain == "light" and attrs.get("brightness") is not None:
        return "%d%%" % round(attrs["brightness"] / 255 * 100)
    if domain == "fan" and attrs.get("percentage"):
        return "%d%%" % attrs["percentage"]
    return on_words


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


_text_paths = {}


def text_path(origin, f, text, x, y):
    """The text as an outline at (x, y) on its baseline, from a font ten times
    the size and scaled back (and narrowed by HSCALE: Chrome sets this font a
    little tighter than Qt does)."""
    key = (f.key(), text, origin.x(), origin.y())
    path = _text_paths.get(key)
    if path is None:
        path = QPainterPath()
        path.addText(origin, f, text)             # the costly part (shaping and outlining): kept
        if len(_text_paths) > 4000:
            _text_paths.clear()
        _text_paths[key] = path
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
    base = QPointF(0, 0)
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


def tile_layout(size, count, form=None):
    """(form, [(x, y, w, h) per tile that fits]) of a widget, in CSS pixels. `form` fixes the form."""
    cols, rows = SIZES.get(size, SIZES["2x4"])
    form = form or form_for(cols, rows, count)
    sc, sr = FORM_SPAN[form]
    per_row = cols // sc
    w, h = sc * CELL_W + (sc - 1) * GAP, sr * CELL_H + (sr - 1) * GAP
    rects = []
    for i in range(count):
        rects.append((PAD + (i % per_row) * sc * (CELL_W + GAP),
                      PAD + (i // per_row) * sr * (CELL_H + GAP), w, h))
    return form, rects


def scroll_range(size, count):
    """How far a widget with more tiles than fit can scroll (CSS px)."""
    form, rects = tile_layout(size, count)
    if not rects:
        return 0
    _, H = widget_size(size)
    bottom = max(y + h for _, y, _, h in rects)
    return max(0, bottom - (H - PAD))


def mini_buttons(form, cw, ch):
    """The climate tile's round - and + in the tile's own units: [(rect, delta sign)]."""
    if form == "small":
        # In the corner, shown while the pointer is over the tile.
        return [(QRectF(cw - 10 - 30 - 6 - 30, 10, 30, 30), -1), (QRectF(cw - 10 - 30, 10, 30, 30), 1)]
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


def draw_content(p, tile, st, cw, ch, form, theme, tcol, dim, hover=False):
    """What is on a tile, in the tile's own units (a big tile is these units
    zoomed by 1.4), from its top-left corner."""
    domain = tile["domain"]
    ok = st is not None
    on = ok and domain not in MOMENTARY and is_on(domain, st)
    roomy = form != "small"
    shown = climate_badge(st, on) if domain == "climate" and ok and not tile.get("icon") else None
    reading = shown if roomy else None
    badge = None if roomy else shown
    readonly = is_readonly(domain)
    value = tr(value_text(domain, st)) if ok and not badge and not reading else ""
    readout = readonly and bool(value)
    c1 = tcol["on_text1"] if on else tcol["off_text1"]
    c2 = tcol["on_text2"] if on else tcol["off_text2"]
    label = tr(state_text(tile, st) if ok else "無法連線")
    name = tile.get("room") or (st or {}).get("attributes", {}).get("friendly_name") or tile["entity"]
    icolor = icon_color(tile, st, on, theme, tcol) if ok else tcol["off_text1"]
    if dim:
        icolor = (255, 255, 255, 0.95) if on else tcol["off_text1"]

    # -- the icon ------------------------------------------------------
    if form == "bar":
        dx, dy = 23, (ch - 100) / 2
        if reading:
            text = reading["text"]               # "24°": a thermostat does not say whether it is °C or °F
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
            p.drawPath(text_path(QPointF(0, 0), f, reading["text"], ix,
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

    if not ok:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ACCENT["red"]))
        p.drawEllipse(QRectF(cw - 12 - 7, ch - 12 - 7, 7, 7))

    # -- the climate buttons: always on a long or big tile, on hover on a small one ----
    if domain == "climate" and on and (roomy or hover):
        f = font({"bar": 26, "big": 28}.get(form, 20), QFont.Bold)
        for rect, sign in mini_buttons(form, cw, ch):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 20))
            p.drawEllipse(rect)
            draw_centred(p, "+" if sign > 0 else "\u2212", f, "#1d1d1f", rect)


def draw_tile(p, tile, st, x, y, w, h, theme, tcol, form="small", dim=False,
              hover=False, pressed=False, flash=0.0):
    domain = tile["domain"]
    on = st is not None and domain not in MOMENTARY and is_on(domain, st)
    shape = squircle(x, y, w, h, tcol["radius_tile"])
    p.setPen(Qt.NoPen)
    p.setBrush(rgba(tcol["tile_on"] if on else tcol["tile_off"]))
    p.drawPath(shape)
    if on:
        inner_shadow(p, shape, rgba(tcol["edge_on"]))
        if tcol["edge_on_top"]:
            inner_shadow(p, shape, rgba(tcol["edge_on_top"]), dy=1, spread=0)
    else:
        inner_shadow(p, shape, rgba(tcol["edge"]))
        if tcol["edge_top"]:
            inner_shadow(p, shape, rgba(tcol["edge_top"]), dy=1, spread=0)
    if flash > 0:
        # tile-flash: an inner glow that swells and fades over 0.6 s (flash is 1 -> 0 of it).
        t = 1 - flash
        glow = t / 0.3 if t < 0.3 else (1 - t) / 0.7
        inner_shadow(p, shape, QColor(255, 255, 255, round(255 * 0.35 * max(0.0, glow))), spread=6)
    zoom = BIG_ZOOM if form == "big" else 1.0
    p.save()
    p.translate(x, y)
    p.scale(zoom, zoom)
    draw_content(p, tile, st, w / zoom, h / zoom, form, theme, tcol, dim, hover)
    p.restore()


def widget_size(size):
    cols, rows = SIZES.get(size, SIZES["2x4"])
    return (cols * CELL_W + (cols - 1) * GAP + 2 * PAD, rows * CELL_H + (rows - 1) * GAP + 2 * PAD)


def _fade_gradient(h, stops):
    g = QLinearGradient(0, 0, 0, h)
    for at, c in stops:
        g.setColorAt(at, QColor(*c))
    return g


def draw_liquid_rim(p, W, H, radius, dark):
    """The light that runs along the rim of the liquid card (its ::before and
    ::after) and the wash over the pane."""
    ring = squircle(0, 0, W, H, radius).subtracted(squircle(2, 2, W - 4, H - 4, radius - 2))
    p.save()
    p.setOpacity(0.72 if dark else 1.0)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(_fade_gradient(H, [
        (0, (255, 255, 255, 209)), (0.10, (235, 249, 255, 102)), (0.28, (235, 249, 255, 0)),
        (0.72, (166, 222, 255, 0)), (0.90, (166, 222, 255, 71)), (1, (222, 247, 255, 158))])))
    p.drawPath(ring)
    p.setOpacity(0.75 if dark else 1.0)
    p.setBrush(QBrush(_fade_gradient(H, [
        (0, (255, 255, 255, 36)), (0.12, (245, 252, 255, 17)), (0.28, (245, 252, 255, 0)),
        (0.72, (188, 231, 255, 0)), (0.88, (188, 231, 255, 13)), (1, (166, 222, 255, 28))])))
    p.drawPath(squircle(0, 0, W, H, radius))
    p.restore()


def wrap_text(text, f, width):
    """`text` broken into lines no wider than `width`: at spaces, or anywhere between CJK characters."""
    fm = QFontMetricsF(f)
    lines, cur = [], ""
    for token in re.findall(r"\s+|[A-Za-z0-9_.,'\-]+|.", text):
        trial = cur + token
        if cur and fm.horizontalAdvance(trial.rstrip()) / 10 * HSCALE > width:
            lines.append(cur.rstrip())
            cur = token.lstrip()
        else:
            cur = trial
    if cur.strip():
        lines.append(cur.rstrip())
    return lines or [""]


def draw_empty(p, W, H, small, theme, raw_theme, dim):
    """An empty widget's message, and the rectangle of its button (None when there is none)."""
    tcol = tokens(theme, dim)
    title_c = tokens("light")["on_text1"] if raw_theme == "light" else tcol["off_text1"]
    sub_c = tcol["on_text2"] if raw_theme == "light" else tcol["off_text2"]
    if dim:
        title_c, sub_c = tcol["off_text1"], tcol["off_text2"]
    width = W - 40
    k = 1.0
    while True:                                   # smaller until the message and its button sit inside the card
        icon = (60 if small else 80) * k
        blocks = [([chr(0x2302)], font(icon, QFont.Normal), ACCENT["blue"], icon)]
        tf = font((26 if small else 40) * k, QFont.Bold)
        blocks.append((wrap_text(tr("尚未設定任何配件"), tf, width), tf, title_c, (26 if small else 40) * k * 1.2))
        if not small:
            sf = font(26 * k, QFont.Normal)
            blocks.append((wrap_text(tr("按這裡加入配件"), sf, width), sf, sub_c, 26 * k * 1.25))
        btn_h = 26 * k * 1.33 + 28 * k
        gap = 8 * k
        total = sum(len(lines) * h for lines, _, _, h in blocks) + gap * (len(blocks) - 1)             + (0 if small else 2 * gap + btn_h)
        if total <= H - 40 or k < 0.45:
            break
        k *= 0.94
    y = (H - total) / 2
    for lines, f, color, h in blocks:
        for line in lines:
            draw_centred(p, line, f, color, QRectF(20, y, width, h))
            y += h
        y += gap
    if small:
        return None
    f = font(26 * k, QFont.DemiBold)
    tw = QFontMetricsF(f).horizontalAdvance(tr("編輯 Widget")) / 10 * HSCALE
    rect = QRectF((W - tw - 72 * k) / 2, y + gap, tw + 72 * k, btn_h)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(ACCENT["blue"]))
    p.drawPath(squircle_pill(rect))
    draw_centred(p, tr("編輯 Widget"), f, "#ffffff", rect)
    return rect


def squircle_pill(rect):
    path = QPainterPath()
    path.addRoundedRect(rect, rect.height() / 2, rect.height() / 2)
    return path


def draw_card_bg(p, W, H, tcol, style, theme, radius=None, plain=False):
    """The card's tint and rims over its glass. `plain`: the quiet pane of the detail card, which
    has none of the liquid style's light along its rim."""
    radius = radius or tcol["radius_panel"]
    card = squircle(0, 0, W, H, radius)
    p.setPen(Qt.NoPen)
    if plain and style == "liquid":
        p.setBrush(QColor(26, 29, 34, round(255 * 0.72)) if theme == "dark" else QColor(226, 239, 248, round(255 * 0.38)))
        p.drawPath(card)
        inner_shadow(p, card, QColor(255, 255, 255, round(255 * 0.35)))
        return
    p.setBrush(rgba(tcol["panel"]))
    p.drawPath(card)
    inner_shadow(p, card, rgba(tcol["card_edge"]))
    if tcol["card_edge_top"]:
        inner_shadow(p, card, rgba(tcol["card_edge_top"]), dy=1, spread=0)
    if style == "liquid" and not plain:
        draw_liquid_rim(p, W, H, radius, theme == "dark")


def draw_widget(p, size, tiles, states, theme, backdrop=None, scale=1.0, dim=False, style="classic",
                ui=None, raw_theme=None, form=None, message=True):
    """The whole widget at (0, 0). `backdrop` is the small blurred picture of
    the desktop behind it (a QImage), stretched over the card. `ui`: what the pointer is
    doing - {"hover": i, "pressed": i, "flash": {i: 1..0}, "scroll": px}."""
    ui = ui or {}
    tcol = tokens(theme, dim, style)
    W, H = widget_size(size)
    form, rects = tile_layout(size, len(tiles), form)
    p.save()
    p.scale(scale, scale)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
    card = squircle(0, 0, W, H, tcol["radius_panel"])
    if backdrop is not None:
        p.save()
        p.setClipPath(card)
        p.drawImage(QRectF(0, 0, W, H), backdrop)
        p.restore()
    draw_card_bg(p, W, H, tcol, style, theme)
    button = None
    if not tiles:
        # (the editor's preview shows an empty widget as the bare card: its message is for the desktop)
        button = draw_empty(p, W, H, SIZES.get(size, (4, 2)) == (1, 1), theme, raw_theme or theme, dim) if message else None
    else:
        p.save()
        p.setClipRect(QRectF(PAD, PAD, W - 2 * PAD, H - 2 * PAD))
        p.translate(0, -ui.get("scroll", 0))
        for i, (tile, (x, y, w, h)) in enumerate(zip(tiles, rects)):
            if y + h - ui.get("scroll", 0) < 0 or y - ui.get("scroll", 0) > H:
                continue
            pressed = ui.get("pressed") == i
            p.save()
            if pressed:
                k = 0.95 if (has_detail_on_hold(tile["domain"]) or is_readonly(tile["domain"])) else 0.96
                p.translate(x + w / 2, y + h / 2)
                p.scale(k, k)
                p.translate(-(x + w / 2), -(y + h / 2))
            draw_tile(p, tile, states.get(tile["entity"]), x, y, w, h, theme, tcol, form, dim,
                      hover=ui.get("hover") == i, flash=(ui.get("flash") or {}).get(i, 0.0))
            p.restore()
        p.restore()
    p.restore()
    return button
