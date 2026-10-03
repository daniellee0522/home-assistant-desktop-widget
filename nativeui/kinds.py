"""The other kinds of desktop widget, after iOS's own: the weather, a camera, a chart of sensors and a
row of shortcuts (scenes, scripts, automations). A widget of the tiles kind is render.draw_widget's.

A widget is made of its kind, dragged from the editor's palette, and keeps it. Its devices (its tiles) say
what it shows: a weather entity, a camera, two sensors, or the shortcuts. Each kind has one size of its own
(KIND_SIZE, as config.KIND_SIZE); the drawing still works in every size.
What comes from elsewhere than the states (the forecast, the camera's picture, the sensors' history) is in
`extras`, fetched by the widget (nativeui/widget.py).
"""
import datetime
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen

from . import render

KINDS = ("tiles", "weather", "camera", "chart", "shortcuts")
KIND_LABELS = {"tiles": "配件", "weather": "天氣", "camera": "攝影機", "chart": "圖表", "shortcuts": "捷徑"}
KIND_SIZE = {"weather": "2x4", "camera": "2x4", "chart": "2x4", "shortcuts": "2x4"}
KIND_ICONS = {"weather": "mdi:weather-partly-cloudy", "camera": "mdi:cctv", "chart": "mdi:chart-line",
              "shortcuts": "mdi:gesture-tap-button"}
# what an empty one asks for
KIND_ASK = {"weather": "選擇天氣", "camera": "選擇攝影機", "chart": "選擇感測器", "shortcuts": "加入場景或腳本"}
# which devices each kind takes, and how many (None: any number)
KIND_DOMAINS = {"weather": ("weather",), "camera": ("camera",), "chart": ("sensor",),
                "shortcuts": ("scene", "script", "automation")}
KIND_MAX = {"weather": 1, "camera": 1, "chart": 2}

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
SHORTCUT_COLORS = ("#ff9f0a", "#30d158", "#0a84ff", "#bf5af2", "#ff375f", "#64d2ff", "#5e5ce6", "#ffd60a")
CHART_COLORS = ("#0a84ff", "#ff9f0a", "#30d158")


def compatible(kind, tile):
    return kind not in KIND_DOMAINS or tile.get("domain") in KIND_DOMAINS[kind]


def shown(kind, tiles):
    """The devices a widget of this kind shows."""
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

def draw_weather(p, W, H, cols, rows, tile, state, forecast, card):
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

def draw_camera(p, W, H, tile, state, picture, taken, card):
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


# ---------------------------------------------------------------------------------- shortcuts

def draw_shortcuts(p, tiles, rects, states, ui, first=0):
    """The shortcuts as coloured buttons; each one's colour is its place's (first: the place of tiles[0])."""
    flash = (ui or {}).get("flash") or {}
    for i, (tile, (x, y, w, h)) in enumerate(zip(tiles, rects)):
        p.save()
        if (ui or {}).get("pressed") == i:
            p.translate(x + w / 2, y + h / 2)
            p.scale(0.95, 0.95)
            p.translate(-(x + w / 2), -(y + h / 2))
        c = QColor(SHORTCUT_COLORS[(i + first) % len(SHORTCUT_COLORS)])
        shape = render.squircle(x, y, w, h, 40)
        g = QLinearGradient(0, y, 0, y + h)
        g.setColorAt(0, c.lighter(112))
        g.setColorAt(1, c)
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawPath(shape)
        k = flash.get(i, 0.0)
        if k > 0:
            p.setBrush(QColor(255, 255, 255, round(110 * k)))
            p.drawPath(shape)
        st = states.get(tile["entity"])
        render.draw_icon(p, render.icon_name(tile, st), "#ffffff", QRectF(x + 18, y + 18, 34, 34))
        name = tile.get("room") or ((st or {}).get("attributes") or {}).get("friendly_name") or tile["entity"]
        f = _font(18, QFont.Bold)
        lines = render.wrap_text(name, f, w - 36)[:2]
        for j, line in enumerate(lines):
            _text(p, line, f, QColor(255, 255, 255), x + 18, y + h - 18 - (len(lines) - j) * 23)
        p.restore()


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
    if kind == "shortcuts":
        names = (("scene.home", "回家", "mdi:home"), ("scene.away", "出門", "mdi:exit-run"),
                 ("scene.night", "晚安", "mdi:weather-night"), ("script.movie", "電影", "mdi:movie-open"))
        return ([dict(t(e, e.split(".")[0], render.tr(n)), icon=i) for e, n, i in names], {}, {})
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
    if kind in ("chart", "shortcuts") or not mine:
        render.draw_card_bg(p, W, H, tcol, style, theme)
    if not mine:
        button = draw_kind_empty(p, W, H, kind, tcol, dim) if message else None
    elif kind == "weather":
        draw_weather(p, W, H, cols, rows, mine[0], states.get(mine[0]["entity"]), extras.get("forecast"), card)
    elif kind == "camera":
        draw_camera(p, W, H, mine[0], states.get(mine[0]["entity"]), extras.get("picture"),
                    extras.get("picture_at"), card)
    elif kind == "chart":
        draw_chart(p, W, H, cols, rows, mine, states, extras.get("history"), tcol)
    elif kind == "shortcuts":
        _, rects = render.tile_layout(size, len(mine), "small")
        p.save()
        p.setClipRect(QRectF(render.PAD, render.PAD, W - 2 * render.PAD, H - 2 * render.PAD))
        p.translate(0, -(ui or {}).get("scroll", 0))
        draw_shortcuts(p, mine, rects, states, ui)
        p.restore()
    if dim and kind in ("weather", "camera") and mine:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 120))
        p.drawPath(card)
    if kind in ("weather", "camera") and mine:
        render.inner_shadow(p, card, QColor(255, 255, 255, 40))
    p.restore()
    return button
