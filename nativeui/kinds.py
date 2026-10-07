"""The other kinds of desktop widget, after iOS's own: a clock, a calendar, the weather, a camera, a chart of
sensors and a player. A widget of the tiles kind is render.draw_widget's (scenes and scripts are tiles there).

A widget is made of its kind, dragged from the editor's palette, and keeps it. Its devices (its tiles) say
what it shows: a weather entity, a camera, two sensors or a player; a clock and a calendar need none. Each kind has one size of its own
(KIND_SIZE, as config.KIND_SIZE); the drawing still works in every size.
What comes from elsewhere than the states (the forecast, the camera's picture, the sensors' history) is in
`extras`, fetched by the widget (nativeui/widget.py).
"""
import datetime
import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPainterPathStroker, QPen,
                           QTransform)

from . import render

KINDS = ("tiles", "clock", "calendar", "weather", "camera", "chart", "media")
KIND_LABELS = {"tiles": "配件", "clock": "時鐘", "calendar": "日曆", "weather": "天氣", "camera": "攝影機",
               "chart": "圖表", "media": "播放器"}
KIND_SIZE = {"clock": "2x2", "calendar": "2x2", "weather": "2x4", "camera": "2x4", "chart": "2x4", "media": "2x4"}
KIND_ICONS = {"weather": "mdi:weather-partly-cloudy", "camera": "mdi:cctv", "chart": "mdi:chart-line",
              "media": "mdi:music"}
# what an empty one asks for
KIND_ASK = {"weather": "選擇天氣", "camera": "選擇攝影機", "chart": "選擇感測器", "media": "選擇播放器"}
# which devices each kind takes, and how many (None: any number); a clock and a calendar take none
KIND_DOMAINS = {"weather": ("weather",), "camera": ("camera",), "chart": ("sensor",),
                "media": ("local_media", "media_player")}
KIND_MAX = {"weather": 1, "camera": 1, "chart": 2, "media": 1}
NO_DEVICES = ("clock", "calendar")

CONDITIONS = {
    "sunny": ("weather-sunny", "晴", "Sunny"), "clear-night": ("weather-night", "晴朗", "Clear"),
    "partlycloudy": ("weather-partly-cloudy", "局部多雲", "Partly cloudy"), "cloudy": ("weather-cloudy", "多雲", "Cloudy"),
    "rainy": ("weather-rainy", "雨", "Rain"), "pouring": ("weather-pouring", "大雨", "Heavy rain"),
    "lightning": ("weather-lightning", "雷", "Thunder"), "lightning-rainy": ("weather-lightning-rainy", "雷雨", "Thunderstorm"),
    "snowy": ("weather-snowy", "雪", "Snow"), "snowy-rainy": ("weather-snowy-rainy", "雨夾雪", "Sleet"),
    "fog": ("weather-fog", "霧", "Fog"), "hail": ("weather-hail", "冰雹", "Hail"), "windy": ("weather-windy", "強風", "Windy"),
    "windy-variant": ("weather-windy-variant", "強風", "Windy"), "exceptional": ("alert-circle-outline", "特殊天氣", "Exceptional"),
}
# the sky behind the weather, top to bottom: (day, night)
SKIES = {
    "clear": (("#2f7fd8", "#69aeea"), ("#0a1734", "#22386a")),
    "cloud": (("#5f7a94", "#93a9bd"), ("#252e39", "#45505e")),
    "rain": (("#3f4d5e", "#66778a"), ("#1c232c", "#38424f")),
    "snow": (("#8394a6", "#bcc8d3"), ("#3a4552", "#5d6a78")),
}
CHART_COLORS = ("#0a84ff", "#ff9f0a", "#30d158")


def compatible(kind, tile):
    return kind not in KIND_DOMAINS or tile.get("domain") in KIND_DOMAINS[kind]


def shown(kind, tiles):
    """The devices a widget of this kind shows."""
    if kind in NO_DEVICES:
        return []
    out = [t for t in tiles if compatible(kind, t)]
    return out[:KIND_MAX[kind]] if kind in KIND_MAX else out


def condition(state):
    s = (state or {}).get("state") or ""
    icon, zh, en = CONDITIONS.get(s, ("weather-cloudy", s or "無資料", s or "No data"))
    return "mdi:" + icon, en if render._language == "en" else zh


def _sky(state):
    s = (state or {}).get("state") or ""
    hour = time.localtime().tm_hour
    night = s == "clear-night" or not (6 <= hour < 18)
    kind = ("clear" if s in ("sunny", "clear-night", "windy", "windy-variant", "exceptional") else
            "rain" if s in ("rainy", "pouring", "lightning", "lightning-rainy", "hail") else
            "snow" if s in ("snowy", "snowy-rainy", "fog") else "cloud")
    return SKIES[kind][1 if night else 0]


def _font(px, weight=QFont.Normal):
    return render.font(px, weight)


def _text(p, text, f, color, x, y, align="l", w=0.0):
    """One line with its top at y; returns its width."""
    fm = render.QFontMetricsF(f)
    tw = fm.horizontalAdvance(text) / 10 * render.HSCALE
    if align == "c":
        x += (w - tw) / 2
    elif align == "r":
        x += w - tw
    p.setPen(Qt.NoPen)
    p.setBrush(render.parse_color(color) if not isinstance(color, QColor) else color)
    p.drawPath(render.text_path(QPointF(0, 0), f, text, x, y + fm.ascent() / 10))
    return tw


def _fit(text, f, width):
    fm = render.QFontMetricsF(f)
    if fm.horizontalAdvance(text) / 10 * render.HSCALE <= width:
        return text
    while text and fm.horizontalAdvance(text + "…") / 10 * render.HSCALE > width:
        text = text[:-1]
    return text + "…"


def _deg(v):
    try:
        return "%d°" % round(float(v))
    except (TypeError, ValueError):
        return "--"


def _day(iso, i):
    if i == 0:
        return "Today" if render._language == "en" else "今天"
    try:
        d = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone()
    except (TypeError, ValueError):
        return ""
    return (("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun") if render._language == "en" else
            ("週一", "週二", "週三", "週四", "週五", "週六", "週日"))[d.weekday()]


# ---------------------------------------------------------------------------------- the weather

def draw_weather(p, W, H, cols, rows, tile, state, forecast, card, sky=True):
    """sky: the condition's own sky behind it (not while dimmed: then it is clear glass, as the tiles are)."""
    if sky:
        top, bottom = _sky(state)
        g = QLinearGradient(0, 0, 0, H)
        g.setColorAt(0, QColor(top))
        g.setColorAt(1, QColor(bottom))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawPath(card)
    white, soft = QColor(255, 255, 255), QColor(255, 255, 255, 205)
    attrs = (state or {}).get("attributes") or {}
    name = tile.get("room") or attrs.get("friendly_name") or tile["entity"]
    icon, text = condition(state)
    temp = _deg(attrs.get("temperature"))
    today = (forecast or [{}])[0] if forecast else {}
    hl = ""
    if today.get("temperature") is not None:
        hl = ("H:%s L:%s" if render._language == "en" else "高 %s 低 %s") % (_deg(today.get("temperature")),
                                                                          _deg(today.get("templow")))
    pad = 22
    if cols == 1:                                         # an icon and the temperature
        render.draw_icon(p, icon, "#ffffff", QRectF(pad, pad, 48, 48))
        _text(p, temp, _font(46, QFont.Light), white, pad, H - pad - 56)
        return
    _text(p, _fit(name, _font(19, QFont.DemiBold), W / 2 - pad), _font(19, QFont.DemiBold), white, pad, pad)
    _text(p, temp, _font(64, QFont.Light), white, pad, pad + 24)
    if cols == 2:                                         # iOS's small one
        render.draw_icon(p, icon, "#ffffff", QRectF(pad, H - pad - 64, 26, 26))
        _text(p, _fit(text, _font(17, QFont.DemiBold), W - 2 * pad), _font(17, QFont.DemiBold), white, pad, H - pad - 34)
        if hl:
            _text(p, hl, _font(16, QFont.Medium), soft, pad, H - pad - 14)
        return
    # wider: the condition on the right, the coming days below
    render.draw_icon(p, icon, "#ffffff", QRectF(W - pad - 34, pad, 34, 34))
    _text(p, text, _font(17, QFont.DemiBold), white, W - pad - 260, pad + 44, "r", 260)
    if hl:
        _text(p, hl, _font(16, QFont.Medium), soft, W - pad - 260, pad + 68, "r", 260)
    days = (forecast or [])[:6 if rows == 2 else 7]
    if not days:
        return
    if rows == 2:
        y0 = H - pad - 112
        p.setBrush(QColor(255, 255, 255, 60))
        p.drawRect(QRectF(pad, y0 - 14, W - 2 * pad, 1))
        cw = (W - 2 * pad) / len(days)
        for i, d in enumerate(days):
            x = pad + i * cw
            _text(p, _day(d.get("datetime"), i), _font(15, QFont.DemiBold), soft, x, y0, "c", cw)
            render.draw_icon(p, "mdi:" + CONDITIONS.get(d.get("condition"), ("weather-cloudy",))[0], "#ffffff",
                             QRectF(x + cw / 2 - 16, y0 + 28, 32, 32))
            _text(p, _deg(d.get("temperature")), _font(17, QFont.DemiBold), white, x, y0 + 72, "c", cw)
        return
    # the large one: a row for each day, its low and high on a shared scale
    lows = [d.get("templow") if d.get("templow") is not None else d.get("temperature") for d in days]
    highs = [d.get("temperature") for d in days]
    try:
        lo, hi = min(float(v) for v in lows if v is not None), max(float(v) for v in highs if v is not None)
    except ValueError:
        lo, hi = 0.0, 1.0
    y = pad + 150
    p.setBrush(QColor(255, 255, 255, 60))
    p.drawRect(QRectF(pad, y - 12, W - 2 * pad, 1))
    rh = (H - y - pad) / len(days)
    bar_x, bar_w = pad + 260, W - 2 * pad - 260 - 160
    for i, d in enumerate(days):
        cy = y + i * rh
        _text(p, _day(d.get("datetime"), i), _font(18, QFont.DemiBold), white, pad, cy + rh / 2 - 12)
        render.draw_icon(p, "mdi:" + CONDITIONS.get(d.get("condition"), ("weather-cloudy",))[0], "#ffffff",
                         QRectF(pad + 120, cy + rh / 2 - 15, 30, 30))
        lo_v, hi_v = lows[i], highs[i]
        _text(p, _deg(lo_v), _font(18, QFont.Medium), soft, bar_x - 70, cy + rh / 2 - 12, "r", 56)
        _text(p, _deg(hi_v), _font(18, QFont.DemiBold), white, bar_x + bar_w + 14, cy + rh / 2 - 12)
        p.setBrush(QColor(255, 255, 255, 50))
        p.drawRoundedRect(QRectF(bar_x, cy + rh / 2 - 3, bar_w, 6), 3, 3)
        try:
            a = (float(lo_v) - lo) / max(1e-6, hi - lo)
            b = (float(hi_v) - lo) / max(1e-6, hi - lo)
        except (TypeError, ValueError):
            continue
        rg = QLinearGradient(bar_x, 0, bar_x + bar_w, 0)
        rg.setColorAt(0, QColor("#7fd3ff"))
        rg.setColorAt(1, QColor("#ffb340"))
        p.setBrush(rg)
        p.drawRoundedRect(QRectF(bar_x + a * bar_w, cy + rh / 2 - 3, max(6, (b - a) * bar_w), 6), 3, 3)


# ---------------------------------------------------------------------------------- a camera

def draw_camera(p, W, H, tile, state, picture, taken, card, dim=False):
    """dim: clear glass with the camera's icon and name, as the tiles are while dimmed (no picture is taken
    then either)."""
    if dim:
        render.draw_icon(p, "mdi:cctv", "#ffffff", QRectF(22, 22, 44, 44))
        name = tile.get("room") or ((state or {}).get("attributes") or {}).get("friendly_name") or tile["entity"]
        f = _font(20, QFont.DemiBold)
        _text(p, _fit(name, f, W - 44), f, QColor(255, 255, 255, 230), 22, H - 22 - 26)
        return
    p.save()
    p.setClipPath(card)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(22, 24, 28))
    p.drawRect(QRectF(0, 0, W, H))
    if picture is not None and not picture.isNull():
        k = max(W / picture.width(), H / picture.height())
        w, h = picture.width() * k, picture.height() * k
        p.drawImage(QRectF((W - w) / 2, (H - h) / 2, w, h), picture)
    else:
        render.draw_icon(p, "mdi:cctv", "#8e8e93", QRectF(W / 2 - 30, H / 2 - 30, 60, 60))
    scrim = QLinearGradient(0, H * 0.55, 0, H)
    scrim.setColorAt(0, QColor(0, 0, 0, 0))
    scrim.setColorAt(1, QColor(0, 0, 0, 150))
    p.setBrush(scrim)
    p.drawRect(QRectF(0, H * 0.55, W, H * 0.45))
    p.restore()
    attrs = (state or {}).get("attributes") or {}
    name = tile.get("room") or attrs.get("friendly_name") or tile["entity"]
    f = _font(20, QFont.DemiBold)
    _text(p, _fit(name, f, W - 44), f, QColor(255, 255, 255), 22, H - 22 - 26)
    if taken and W > 200:
        t = time.strftime("%H:%M", time.localtime(taken))
        fs = _font(15, QFont.DemiBold)
        tw = render.QFontMetricsF(fs).horizontalAdvance(t) / 10 * render.HSCALE
        p.setBrush(QColor(0, 0, 0, 110))
        p.drawRoundedRect(QRectF(W - 22 - tw - 34, 20, tw + 34, 28), 14, 14)
        p.setBrush(QColor("#ff453a"))
        p.drawEllipse(QPointF(W - 22 - tw - 18, 34), 4.5, 4.5)
        _text(p, t, fs, QColor(255, 255, 255), W - 22 - tw - 8, 24)


# ---------------------------------------------------------------------------------- a chart of sensors

def _spark(p, rect, points, color):
    if not points or len(points) < 2:
        return
    t0, t1 = points[0][0], points[-1][0]
    vs = [v for _, v in points]
    lo, hi = min(vs), max(vs)
    if hi - lo < 1e-6:
        lo, hi = lo - 0.5, hi + 0.5
    xy = [(rect.left() + (t - t0) / max(1, t1 - t0) * rect.width(),
           rect.top() + (1 - (v - lo) / (hi - lo)) * rect.height()) for t, v in points]
    line = QPainterPath()
    line.moveTo(*xy[0])
    for x, y in xy[1:]:
        line.lineTo(x, y)
    area = QPainterPath(line)
    area.lineTo(rect.right(), rect.bottom())
    area.lineTo(rect.left(), rect.bottom())
    area.closeSubpath()
    c = QColor(color)
    g = QLinearGradient(0, rect.top(), 0, rect.bottom())
    c1, c2 = QColor(c), QColor(c)
    c1.setAlphaF(0.35)
    c2.setAlphaF(0.0)
    g.setColorAt(0, c1)
    g.setColorAt(1, c2)
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawPath(area)
    p.setPen(QPen(c, 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawPath(line)
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawEllipse(QPointF(*xy[-1]), 5, 5)


def _reading(st):
    if not st:
        return "--", ""
    attrs = st.get("attributes") or {}
    unit = attrs.get("unit_of_measurement") or ("°" if attrs.get("device_class") == "temperature" else "")
    s = st.get("state")
    try:
        v = float(s)
        s = ("%.1f" % v).rstrip("0").rstrip(".") if abs(v) < 1000 else "%d" % round(v)
    except (TypeError, ValueError):
        pass
    return s, unit


def draw_chart(p, W, H, cols, rows, tiles, states, history, tcol):
    ink1, ink2 = render.parse_color(tcol["off_text1"]), render.parse_color(tcol["off_text2"])
    pad = 22
    n = 1 if rows == 1 or cols <= 2 else min(len(tiles), 2 if rows == 2 else 3)
    tiles = tiles[:n]
    rh = (H - 2 * pad) / n
    for i, tile in enumerate(tiles):
        st = states.get(tile["entity"])
        attrs = (st or {}).get("attributes") or {}
        name = tile.get("room") or attrs.get("friendly_name") or tile["entity"]
        value, unit = _reading(st)
        color = CHART_COLORS[i % len(CHART_COLORS)]
        y = pad + i * rh
        if i:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(ink2.red(), ink2.green(), ink2.blue(), 50))
            p.drawRect(QRectF(pad, y - 1, W - 2 * pad, 1))
        if cols == 1:
            _text(p, _fit(name, _font(15, QFont.DemiBold), W - 2 * pad), _font(15, QFont.DemiBold), ink2, pad, y)
            vw = _text(p, value, _font(40, QFont.DemiBold), ink1, pad, y + 26)
            _text(p, unit, _font(17, QFont.DemiBold), ink2, pad + vw + 3, y + 46)
            continue
        side = cols > 2 and n > 1                      # in rows: the reading left, its line right
        tw = (W - 2 * pad) * (0.38 if side else 1.0)
        _text(p, _fit(name, _font(17, QFont.DemiBold), tw), _font(17, QFont.DemiBold), color, pad, y + 2)
        vw = _text(p, value, _font(44, QFont.DemiBold), ink1, pad, y + 26)
        _text(p, unit, _font(19, QFont.DemiBold), ink2, pad + vw + 4, y + 50)
        if side:
            rect = QRectF(pad + tw + 18, y + 12, W - 2 * pad - tw - 18, rh - 30)
        else:
            rect = QRectF(pad, y + 92, W - 2 * pad, rh - 92 - 10)
        if rect.height() > 20:
            _spark(p, rect, (history or {}).get(tile["entity"]), color)


# ---------------------------------------------------------------------------------- a clock, a calendar

def _face(p, W, H, card, theme, dim, tcol, style):
    """The face of a clock or a calendar, as iOS's: solid white (or black in the dark), or clear glass while
    dimmed. Returns (ink, ink2) for what is drawn on it."""
    if dim:
        render.draw_card_bg(p, W, H, tcol, style, theme)
        return QColor(255, 255, 255, 235), QColor(255, 255, 255, 150)
    dark = theme == "dark"
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(28, 28, 30) if dark else QColor(255, 255, 255))      # solid: no desktop shows through
    p.drawPath(card)
    render.inner_shadow(p, card, QColor(255, 255, 255, 30) if dark else QColor(0, 0, 0, 18))
    return (QColor(245, 245, 247), QColor(245, 245, 247, 140)) if dark else (QColor(17, 17, 19), QColor(17, 17, 19, 120))


_rings = {}


def _ring(W, H, radius, inset):
    """The card's own outline drawn `inset` inside it (its corners as round as the card's), as points."""
    key = (W, H, radius, inset)
    if key not in _rings:
        path = render.squircle(inset, inset, W - 2 * inset, H - 2 * inset, max(1.0, radius - inset), steps=48)
        poly = path.toFillPolygon()
        _rings[key] = [(poly.at(i).x(), poly.at(i).y()) for i in range(poly.size())]
    return _rings[key]


def _ticks(W, H, radius):
    """The 60 minute ticks: (outer end, inner end) along the card's outline, worked out once per size."""
    key = ("ticks", W, H, radius)
    if key not in _rings:
        outer, inner = _ring(W, H, radius, 18), _ring(W, H, radius, 18 + 17)
        angles = [-math.pi / 2 + i / 60 * 2 * math.pi for i in range(60)]
        _rings[key] = [(_on_ring(outer, W / 2, H / 2, a), _on_ring(inner, W / 2, H / 2, a)) for a in angles]
    return _rings[key]


def _on_ring(points, cx, cy, angle):
    """Where a ray from (cx, cy) at `angle` leaves the outline."""
    dx, dy = math.cos(angle), math.sin(angle)
    best = None
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        ex, ey = x2 - x1, y2 - y1
        den = dx * ey - dy * ex
        if abs(den) < 1e-9:
            continue
        t = ((x1 - cx) * ey - (y1 - cy) * ex) / den
        u = ((x1 - cx) * dy - (y1 - cy) * dx) / den
        if t > 0 and 0 <= u <= 1 and (best is None or t > best):
            best = t
    best = best or 0.0
    return cx + dx * best, cy + dy * best


# The clock's digits are drawn in a font installed on this computer, chosen per clock in the widget editor
# (nativeui/fonts.py); SF Pro Freeze (narrow, as iOS's clock has them) when none is chosen and it is installed,
# else the app's own face. Whatever the font, its strokes are brought up to the same weight by an outline with
# round joins (which also rounds their ends): CLOCK_STEM, a stroke's width as a share of the digits' height.
CLOCK_STEM = 0.14
_stems = {}


def clock_face(choice=None):
    """(family, style) of a clock's digits for its chosen font {"file", "name"} (or None for the default);
    None for the app's own face."""
    from . import fonts
    return fonts.load(choice) or fonts.load(fonts.default())


def clock_font(px, face=None):
    if face is None:
        return render.font(px, QFont.Black)
    from . import fonts
    return fonts.qfont(face, px)


def _stem(face):
    """How wide a stroke of this face is, against its zero's height: across the middle of a "0"."""
    key = face
    if key not in _stems:
        path = render.text_path(QPointF(0, 0), clock_font(118, face), "0", 0, 0).simplified()
        br = path.boundingRect()
        k = 200 / max(1.0, br.height())
        img = QImage(int(br.width() * k) + 4, 204, QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        q = QPainter(img)
        q.translate(2, 2)
        q.scale(k, k)
        q.translate(-br.left(), -br.top())
        q.setPen(Qt.NoPen)
        q.setBrush(QColor(0, 0, 0))
        q.drawPath(path)
        q.end()
        runs, run = [], 0
        for x in range(img.width()):
            if img.pixelColor(x, 102).alpha() > 127:
                run += 1
            elif run:
                runs.append(run)
                run = 0
        if run:
            runs.append(run)
        _stems[key] = (sum(runs[:1] + runs[-1:]) / 2 / 200) if runs else CLOCK_STEM
    return _stems[key]


_digit_paths = {}


def clock_digits(W, H, hhmm, choice=None):
    """The time as one outline, in the card's coordinates: the hours and the minutes drawn from the font, as
    tall as a third of the card and as wide as the ring leaves, its strokes CLOCK_STEM wide; and between them a
    colon of two round dots (a font's own often sits off the middle), placed as iOS places them: one a quarter
    down, one three quarters."""
    face = clock_face(choice)
    key = (W, H, hhmm, face)
    if key in _digit_paths:
        return _digit_paths[key]
    f = clock_font(118, face)
    hh, mm = hhmm.split(":")
    parts = [render.text_path(QPointF(0, 0), f, t, 0, 0).simplified() for t in (hh, mm)]
    boxes = [q.boundingRect() for q in parts]
    top = min(b.top() for b in boxes)
    src_h = max(1.0, max(b.bottom() for b in boxes) - top)
    src_w = sum(b.width() for b in boxes)
    want_w = W - 2 * 54                             # across: inside the ring
    # The digits' height, outline included: a third of the card, less for a font too wide to fit narrowed
    # by a fifth at most (it is narrowed no further, or it looks squeezed).
    h = min(H * 0.34, want_w / (0.25 + 0.8 * src_w / src_h + 0.3))
    stem = _stem(face) if face else CLOCK_STEM
    gap = max(0.25, 1.05 * max(CLOCK_STEM, stem) + 0.1) * h      # the colon's room: its dot, and air

    def fit(e):
        k = (h - e) / src_h                         # down the page
        kx = k * max(0.8, min(1.3, (want_w - gap - 2 * e) / max(1.0, src_w * k)))
        return k, kx
    e = 0.0
    for _ in range(3):                              # the outline that makes a stroke CLOCK_STEM wide
        k, kx = fit(e)
        e = max(0.0, min(0.14 * h, CLOCK_STEM * h - stem * (h - e) * kx / k))
    k, kx = fit(e)
    total = src_w * kx + gap + 2 * e
    x0, y0 = (W - total) / 2 + e / 2, H / 2 + 8 - (h - e) / 2
    out = QPainterPath()
    x = x0
    for q, b in zip(parts, boxes):
        t = QTransform()
        t.translate(x, y0)
        t.scale(kx, k)
        t.translate(-b.left(), -top)
        out.addPath(t.map(q))
        x += b.width() * kx + gap + e
    if e > 0.05:
        stroker = QPainterPathStroker()
        stroker.setWidth(e)
        stroker.setJoinStyle(Qt.RoundJoin)
        stroker.setCapStyle(Qt.RoundCap)
        out = out + stroker.createStroke(out)
    cx = x0 + boxes[0].width() * kx + e / 2 + gap / 2
    d = 1.05 * max(CLOCK_STEM * h, stem * (h - e) * kx / k + e)      # a dot, about as wide as a stroke
    y_top = H / 2 + 8 - h / 2
    for frac in (0.25, 0.74):
        out.addEllipse(QPointF(cx, y_top + h * frac), d / 2, d / 2)
    out = out.simplified()
    if len(_digit_paths) > 8:
        _digit_paths.clear()
    _digit_paths[key] = out
    return out


def tick_alpha(ago):
    """How dark a tick is (0..1) when the hand is `ago` ticks (0..60, fractions too) past it: the hand's own
    tick the darkest, the coming one the lightest, fading between them round the ring. Over the last tick
    the coming one darkens into the hand's."""
    if ago <= 59:
        return 1.0 - 0.88 * ago / 59
    return 0.12 + 0.88 * (ago - 59)


# The ring of a dimmed clock: every tick this faint, none the hand's, so that nothing on it moves.
STANDBY_TICK_ALPHA = 0.3


def draw_clock_ticks(p, W, H, ink, hand, radius=84):
    """The 60 ticks round the card with the hand at `hand` (see clock_hand); with no hand (standby) all of
    them equally faint."""
    for i, ((x1, y1), (x2, y2)) in enumerate(_ticks(W, H, radius)):
        c = QColor(ink)
        c.setAlphaF(ink.alphaF() * (STANDBY_TICK_ALPHA if hand is None else tick_alpha((hand - i) % 60)))
        p.setPen(QPen(c, 3.2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


# The hand moves to each second's tick in this long at its start, eased, and rests there for the rest of it:
# smooth where it moves, and nothing to draw while it rests.
HAND_MOVE_S = 0.6


def clock_hand(now, smooth=True):
    """Where the hand is, in ticks: on this second's tick, or on its way there from the last one."""
    if not smooth:
        return float(now.second)
    t = min(1.0, (now.microsecond / 1e6) / HAND_MOVE_S)
    return now.second - 1 + t * t * (3 - 2 * t)


def draw_clock(p, W, H, ink, ink2, now, radius=84, ticks=True, font=None, still=False):
    """The time, large, narrow and tall, inside a ring of 60 ticks that follow the seconds; the day above it.
    Without `ticks` the ring is left out: a widget on the desktop draws it itself, many times a second, over
    the rest drawn once a minute. `still` (standby): the ring has no hand."""
    if ticks:
        draw_clock_ticks(p, W, H, ink, None if still else clock_hand(now), radius)
    day = (now.strftime("%a %m/%d") if render._language == "en" else
           "週%s %d/%d" % ("一二三四五六日"[now.weekday()], now.month, now.day))
    _text(p, day, _font(19, QFont.DemiBold), ink2, 0, 58, "c", W)
    p.setPen(Qt.NoPen)
    p.setBrush(ink)
    p.drawPath(clock_digits(W, H, now.strftime("%H:%M"), font))


def clock_ink(theme, dim):
    """The ink a clock's ticks are drawn in (as _face gives it)."""
    if dim:
        return QColor(255, 255, 255, 235)
    return QColor(245, 245, 247) if theme == "dark" else QColor(17, 17, 19)


def draw_calendar(p, W, H, ink, ink2, today, accent):
    """The month: its name, then one even grid (style.grid) of the days of the week and the weeks, every row
    the same height and every number centred in its cell by the same rule; today in a filled circle round
    the middle of its cell."""
    from . import style
    pad = 26
    month = today.strftime("%B") if render._language == "en" else "%d月" % today.month
    _text(p, month, _font(22, QFont.Bold), accent, pad + 4, pad - 2)
    names = "SMTWTFS" if render._language == "en" else "日一二三四五六"
    first = today.replace(day=1)
    lead = (first.weekday() + 1) % 7                  # Sunday first
    days = (first.replace(month=first.month % 12 + 1, year=first.year + first.month // 12) - first).days
    weeks = (lead + days + 6) // 7
    cells = style.grid(QRectF(pad, pad + 34, W - 2 * pad, H - 2 * pad - 34 + 6), 7, 1 + weeks)
    head = _font(15, QFont.DemiBold)
    for c, n in enumerate(names):
        style.center_text(p, n, head, ink2, cells[0][c])
    df = _font(17, QFont.DemiBold)
    r_today = min(cells[1][0].width(), cells[1][0].height()) * 0.46
    for d in range(1, days + 1):
        r, c = divmod(lead + d - 1, 7)
        cell = cells[1 + r][c]
        if d == today.day:
            p.setPen(Qt.NoPen)
            p.setBrush(ink)
            p.drawEllipse(cell.center(), r_today, r_today)
            col = QColor(255, 255, 255) if ink.lightness() < 128 else QColor(17, 17, 19)
            style.center_text(p, str(d), df, col, cell, align="ink")
        else:
            style.center_text(p, str(d), df, ink2 if c in (0, 6) else ink, cell)


# ---------------------------------------------------------------------------------- a player

def _when(iso):
    try:
        return datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return time.time()


def media_position(state):
    """Where the song is now (seconds), and its length."""
    attrs = (state or {}).get("attributes") or {}
    dur = attrs.get("media_duration") or 0
    pos = attrs.get("media_position") or 0
    if (state or {}).get("state") == "playing":
        pos += time.time() - _when(attrs.get("media_position_updated_at"))
    return max(0.0, min(dur or pos, pos)), dur


_cover_colors = {}


def cover_color(art):
    """The card's colour from its cover, as Apple Music takes it: the hue that most of the cover's coloured
    part has (not the average of all of it, which turns muddy), made deep enough for white words; a grey
    cover gives a grey card. No cover: Music's own red."""
    if art is None or art.isNull():
        return QColor("#e8344e")
    key = art.cacheKey()
    if key in _cover_colors:
        return _cover_colors[key]
    small = art.scaled(24, 24, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    bins, grey, weight = [0.0] * 24, 0.0, 0.0
    sums = [[0.0, 0.0, 0.0] for _ in range(24)]
    for y in range(small.height()):
        for x in range(small.width()):
            h, s, v, _ = small.pixelColor(x, y).getHsvF()
            weight += 1
            if s < 0.18 or v < 0.12 or h < 0:
                grey += v
                continue
            b = int(h * 24) % 24
            w = s * v                                      # the vivid count for more
            bins[b] += w
            sums[b][0] += h * w
            sums[b][1] += s * w
            sums[b][2] += v * w
    best = max(range(24), key=lambda b: bins[b])
    if bins[best] < 0.06 * weight:                         # hardly any colour: a grey card
        level = grey / max(1.0, weight)
        color = QColor.fromHsvF(0.0, 0.0, min(0.42, max(0.22, level * 0.6)))
    else:
        w = bins[best]
        h, s, v = (sums[best][0] / w, sums[best][1] / w, sums[best][2] / w)
        color = QColor.fromHsvF(h, min(0.9, max(0.45, s)), min(0.62, max(0.38, v * 0.8)))
    if len(_cover_colors) > 32:
        _cover_colors.clear()
    _cover_colors[key] = color
    return color


# Home Assistant's media player features (MediaPlayerEntityFeature); this computer's player gives the same
PAUSE, SEEK, PREVIOUS, NEXT, PLAY = 1, 2, 16, 32, 16384
ACTIVE = ("playing", "paused", "buffering")


def media_controls(state):
    """Which of previous / play_pause / next work now: none with nothing playing, and only what the player
    says it can (a player that says nothing is taken to do all)."""
    s = (state or {}).get("state")
    if s not in ACTIVE:
        return set()
    features = int(((state or {}).get("attributes") or {}).get("supported_features") or 0)
    if not features:
        return {"previous", "play_pause", "next"}
    out = set()
    if features & PREVIOUS:
        out.add("previous")
    if features & NEXT:
        out.add("next")
    if features & (PLAY | PAUSE):
        out.add("play_pause")
    return out


def play_pause_patch(state):
    """What a player is at once when play/pause is pressed (before Home Assistant says so): playing or
    paused, and its place taken now, so the bar neither jumps on (the time since it was last told counted
    as played) nor back."""
    pos, _ = media_position(state)
    playing = (state or {}).get("state") == "playing"
    return {"state": "paused" if playing else "playing",
            "attributes": dict((state or {}).get("attributes") or {}, media_position=pos,
                               media_position_updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat())}


def draw_media(p, W, H, tile, state, art, card, tcol, dim, style, theme, seek_to=None):
    """Now playing, as iOS's Music widget: the cover on the left, the song, its artist and where it is on the
    right, and previous / play-pause / next. The card takes the cover's colour. Returns the buttons as
    [(rect, action)] (action: "previous", "play_pause", "next", "source": where it plays, and "seek": the bar,
    where the player can seek; seek_to is where it is being dragged to, in seconds)."""
    attrs = (state or {}).get("attributes") or {}
    s = (state or {}).get("state") or ""
    playing = s == "playing"
    white, soft = QColor(255, 255, 255), QColor(255, 255, 255, 190)
    if dim:
        render.draw_card_bg(p, W, H, tcol, style, theme)
    else:
        base = cover_color(art)
        g = QLinearGradient(0, 0, 0, H)
        g.setColorAt(0, base.lighter(118))
        g.setColorAt(1, base.darker(118))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawPath(card)
    pad = 24
    side = H - 2 * pad
    box = QRectF(pad, pad, side, side)
    clip = render.squircle(box.x(), box.y(), side, side, 26)
    p.save()
    p.setClipPath(clip)
    if art is not None and not art.isNull():
        k = max(side / art.width(), side / art.height())
        p.drawImage(QRectF(box.x() + (side - art.width() * k) / 2, box.y() + (side - art.height() * k) / 2,
                           art.width() * k, art.height() * k), art)
    else:
        p.fillRect(box, QColor(255, 255, 255, 46))
        render.draw_icon(p, "mdi:music", "#ffffff", QRectF(box.center().x() - 34, box.center().y() - 34, 68, 68))
    p.restore()
    x = pad + side + 26
    tw = W - x - pad
    render.draw_icon(p, "mdi:music", (255, 255, 255, 0.75), QRectF(W - pad - 26, pad, 26, 26))
    # where it plays, with a chevron: pressed, the player to show is chosen
    name = tile.get("room") or attrs.get("friendly_name") or tile["entity"]
    nf = _font(16, QFont.DemiBold)
    name = _fit(name, nf, tw - 36 - 24)
    nw = _text(p, name, nf, soft, x, pad + 2)
    render.draw_icon(p, "mdi:chevron-down", (255, 255, 255, 0.75), QRectF(x + nw + 2, pad + 1, 20, 20))
    source = QRectF(x - 8, pad - 8, nw + 40, 36)
    title = attrs.get("media_title") or (render.tr("未在播放") if s in ("off", "idle", "standby", "") else s)
    tf = _font(27, QFont.Bold)
    _text(p, _fit(title, tf, tw), tf, white, x, pad + 40)
    artist = attrs.get("media_artist") or attrs.get("app_name") or ""
    if artist:
        _text(p, _fit(artist, _font(20, QFont.Medium), tw), _font(20, QFont.Medium), soft, x, pad + 78)
    pos, dur = media_position(state)
    buttons = [(source, "source")]
    if dur and dim:                                  # dimmed: the bar, faint, and not where the song is
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 46))
        p.drawRoundedRect(QRectF(x, pad + 124, tw, 6), 3, 3)
    elif dur:
        if seek_to is not None:
            pos = max(0.0, min(dur, seek_to))
        y = pad + 124
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 70))
        p.drawRoundedRect(QRectF(x, y, tw, 6), 3, 3)
        p.setBrush(white)
        p.drawRoundedRect(QRectF(x, y, max(6.0, tw * pos / dur), 6), 3, 3)
        if int(attrs.get("supported_features") or 0) & SEEK and s in ACTIVE:
            r = 11 if seek_to is not None else 8
            p.drawEllipse(QPointF(x + tw * pos / dur, y + 3), r, r)
            buttons.append((QRectF(x, y - 16, tw, 38), "seek"))
    # the buttons, along the bottom
    big, small = 76, 58
    cy = H - pad - big / 2
    cx = x + tw / 2
    can = media_controls(state)
    for action, icon, size, dx in (("previous", "mdi:skip-previous", small, -(big / 2 + 22 + small / 2)),
                                   ("play_pause", "mdi:pause" if playing else "mdi:play", big, 0),
                                   ("next", "mdi:skip-next", small, big / 2 + 22 + small / 2)):
        r = QRectF(cx + dx - size / 2, cy - size / 2, size, size)
        on = action in can
        p.save()
        if not on:                                     # nothing playing, or the player cannot: faint, inert
            p.setOpacity(p.opacity() * (0.65 if dim else 0.35))
        if action == "play_pause":
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 235))
            p.drawEllipse(r)
            render.draw_icon(p, icon, "#1d1d1f", r.adjusted(18, 18, -18, -18))
        else:
            render.draw_icon(p, icon, "#ffffff", r.adjusted(10, 10, -10, -10))
        p.restore()
        if on:
            buttons.append((r, action))
    return buttons


# ---------------------------------------------------------------------------------- empty, and the samples

def draw_kind_empty(p, W, H, kind, tcol, dim):
    """An empty widget of a kind: its icon and what to choose. The whole card is its button (returned)."""
    ink1, ink2 = render.parse_color(tcol["off_text1"]), render.parse_color(tcol["off_text2"])
    blue = QColor(render.ACCENT["blue"])
    r = 34
    cy = H / 2 - 22
    p.setPen(Qt.NoPen)
    tint = QColor(blue)
    tint.setAlphaF(0.16)
    p.setBrush(tint)
    p.drawEllipse(QPointF(W / 2, cy), r, r)
    render.draw_icon(p, KIND_ICONS.get(kind, "mdi:plus"), blue.name(), QRectF(W / 2 - 20, cy - 20, 40, 40))
    f = _font(20, QFont.DemiBold)
    _text(p, render.tr(KIND_ASK.get(kind, "")), f, ink1, 0, cy + r + 14, "c", W)
    _text(p, render.tr("按這裡設定"), _font(15), ink2, 0, cy + r + 42, "c", W)
    return QRectF(0, 0, W, H)


def sample(kind):
    """(tiles, states, extras) that show a kind in the editor's palette."""
    t = lambda e, d, name: {"id": e, "entity": e, "domain": d, "room": name, "label": "", "icon": ""}
    if kind == "media":
        return ([t("media_player.study", "media_player", render.tr("書房"))],
                {"media_player.study": {"state": "playing", "attributes": {
                    "media_title": "Tiny Giant", "media_artist": "HOYO-MiX", "media_duration": 177,
                    "media_position": 60, "media_position_updated_at": "2000-01-01T00:00:00+00:00"}}}, {})
    if kind == "weather":
        days = [{"datetime": "2026-01-0%dT04:00:00+00:00" % (i + 1), "condition": c, "temperature": hi}
                for i, (c, hi) in enumerate((("sunny", 27), ("partlycloudy", 26), ("rainy", 23), ("cloudy", 24),
                                             ("sunny", 28), ("sunny", 29)))]
        days[0]["templow"] = 19
        return ([t("weather.home", "weather", render.tr("家"))],
                {"weather.home": {"state": "sunny", "attributes": {"temperature": 25}}}, {"forecast": days})
    if kind == "camera":
        return [t("camera.door", "camera", render.tr("門口"))], {}, {}
    if kind == "chart":
        hist = {"sensor.t": [[i, 22 + 2 * __import__("math").sin(i / 5)] for i in range(40)],
                "sensor.h": [[i, 55 + 6 * __import__("math").cos(i / 7)] for i in range(40)]}
        return ([t("sensor.t", "sensor", render.tr("溫度")), t("sensor.h", "sensor", render.tr("濕度"))],
                {"sensor.t": {"state": "23.4", "attributes": {"unit_of_measurement": "°C"}},
                 "sensor.h": {"state": "58", "attributes": {"unit_of_measurement": "%"}}}, {"history": hist})
    return [], {}, {}


# ---------------------------------------------------------------------------------- the widget

def draw_widget(p, kind, size, tiles, states, theme, scale=1.0, dim=False, style="classic", ui=None,
                raw_theme=None, extras=None, message=True):
    """A widget of a kind other than the tiles at (0, 0), as render.draw_widget draws those."""
    extras = extras or {}
    tcol = render.tokens(theme, dim, style)
    W, H = render.widget_size(size)
    cols, rows = render.SIZES.get(size, (4, 2))
    mine = shown(kind, tiles)
    p.save()
    p.scale(scale, scale)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
    card = render.squircle(0, 0, W, H, tcol["radius_panel"])
    button = None
    if kind in NO_DEVICES:
        ink, ink2 = _face(p, W, H, card, theme, dim, tcol, style)
        now = extras.get("now") or datetime.datetime.now()      # (a picture of it may give its own time)
        if kind == "clock":
            draw_clock(p, W, H, ink, ink2, now, tcol["radius_panel"], not extras.get("live_ticks"),
                       extras.get("font"), dim)
        else:
            draw_calendar(p, W, H, ink, ink2, now.date(), QColor(255, 255, 255) if dim else QColor("#ff3b30"))
        p.restore()
        return None
    if (kind == "chart" or not mine or dim) and kind != "media":   # dimmed, clear glass, as the tiles are
        render.draw_card_bg(p, W, H, tcol, style, theme)
    if not mine:
        button = draw_kind_empty(p, W, H, kind, tcol, dim) if message else None
    elif kind == "weather":
        draw_weather(p, W, H, cols, rows, mine[0], states.get(mine[0]["entity"]), extras.get("forecast"), card,
                     sky=not dim)
    elif kind == "camera":
        draw_camera(p, W, H, mine[0], states.get(mine[0]["entity"]), extras.get("picture"),
                    extras.get("picture_at"), card, dim)
    elif kind == "chart":
        draw_chart(p, W, H, cols, rows, mine, states, extras.get("history"), tcol)
    elif kind == "media":
        button = draw_media(p, W, H, mine[0], states.get(mine[0]["entity"]), extras.get("art"), card, tcol, dim,
                            style, theme, extras.get("seek_to"))
    if kind in ("weather", "camera", "media") and mine and not dim:
        render.inner_shadow(p, card, QColor(255, 255, 255, 40))
    p.restore()
    return button
