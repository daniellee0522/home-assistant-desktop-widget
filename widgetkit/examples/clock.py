"""The program's clock, remade with the kit, and with a time zone the person can choose: the time large on a solid
face, the day above it, a ring of 60 ticks whose bright tick is the second hand, easing from one second to the next."""
import datetime
import math
from zoneinfo import ZoneInfo

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPainterPathStroker, QPen, QTransform

from nativeui import fonts, render, ui
from widgetkit import faces
from widgetkit.definition import Field, WidgetDef
from widgetkit.theme import text

# (zone, English, Chinese): what the settings menu offers. Any other zone can be typed in "Another zone".
ZONES = [("local", "This computer", "這台電腦"), ("Asia/Taipei", "Taipei", "台北"), ("Asia/Tokyo", "Tokyo", "東京"),
         ("Asia/Seoul", "Seoul", "首爾"), ("Asia/Shanghai", "Shanghai", "上海"), ("Asia/Hong_Kong", "Hong Kong", "香港"),
         ("Asia/Singapore", "Singapore", "新加坡"), ("Asia/Bangkok", "Bangkok", "曼谷"),
         ("Asia/Kolkata", "India", "印度"), ("Asia/Dubai", "Dubai", "杜拜"), ("Europe/Moscow", "Moscow", "莫斯科"),
         ("Europe/Istanbul", "Istanbul", "伊斯坦堡"), ("Europe/London", "London", "倫敦"), ("Europe/Paris", "Paris", "巴黎"),
         ("Europe/Berlin", "Berlin", "柏林"), ("Europe/Madrid", "Madrid", "馬德里"), ("Africa/Cairo", "Cairo", "開羅"),
         ("Africa/Johannesburg", "Johannesburg", "約翰尼斯堡"), ("America/Sao_Paulo", "São Paulo", "聖保羅"),
         ("America/New_York", "New York", "紐約"), ("America/Chicago", "Chicago", "芝加哥"),
         ("America/Denver", "Denver", "丹佛"), ("America/Los_Angeles", "Los Angeles", "洛杉磯"),
         ("America/Anchorage", "Anchorage", "安克拉治"), ("Pacific/Honolulu", "Honolulu", "檀香山"),
         ("Australia/Sydney", "Sydney", "雪梨"), ("Pacific/Auckland", "Auckland", "奧克蘭"), ("UTC", "UTC", "世界協調時間")]
NAMES = {z: {"en": en, "zh": zh} for z, en, zh in ZONES}

_outlines = {}


def zone_of(cfg):
    """The tzinfo to show: a typed zone if there is a valid one, else the chosen one; None for this computer's own."""
    for key in (cfg["custom_zone"].strip(), cfg["zone"]):
        if key and key != "local":
            try:
                return ZoneInfo(key)
            except Exception:
                continue
    return None


def city_of(cfg, lang):
    if cfg["label"].strip():
        return cfg["label"].strip()
    if cfg["custom_zone"].strip() and zone_of(cfg) is not None:
        return cfg["custom_zone"].strip().split("/")[-1].replace("_", " ")
    names = NAMES.get(cfg["zone"], {})
    return names.get(lang.split("-")[0], names.get("en", "")) if cfg["zone"] != "local" else ""


def now_in(epoch, tz):
    return datetime.datetime.fromtimestamp(epoch, tz) if tz else datetime.datetime.fromtimestamp(epoch).astimezone()


def tick_alpha(ago):
    """How bright a tick is: the hand's is full, and the ones it has passed fade over the last minute."""
    return 1.0 - 0.88 * ago / 59 if ago <= 59 else 0.12 + 0.88 * (ago - 59)


def _outline(W, H, radius, inset):
    key = (W, H, radius, inset)
    if key not in _outlines:
        poly = render.squircle(inset, inset, W - 2 * inset, H - 2 * inset, max(1.0, radius - inset), steps=48).toFillPolygon()
        _outlines[key] = [(poly.at(i).x(), poly.at(i).y()) for i in range(poly.size())]
    return _outlines[key]


def _on_outline(points, cx, cy, angle):
    """Where a ray from (cx, cy) at `angle` leaves the outline."""
    dx, dy = math.cos(angle), math.sin(angle)
    best = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        ex, ey = x2 - x1, y2 - y1
        den = dx * ey - dy * ex
        if abs(den) < 1e-9:
            continue
        t = ((x1 - cx) * ey - (y1 - cy) * ex) / den
        u = ((x1 - cx) * dy - (y1 - cy) * dx) / den
        if t > 0 and 0 <= u <= 1 and t > best:
            best = t
    return QPointF(cx + dx * best, cy + dy * best)


def tick_ends(W, H, radius):
    key = ("ticks", W, H, radius)
    if key not in _outlines:
        outer, inner = _outline(W, H, radius, 18), _outline(W, H, radius, 35)
        angles = [-math.pi / 2 + i / 60 * 2 * math.pi for i in range(60)]
        _outlines[key] = [(_on_outline(outer, W / 2, H / 2, a), _on_outline(inner, W / 2, H / 2, a)) for a in angles]
    return _outlines[key]


def digit_font():
    """The program's clock digits (narrow and tall, as iOS's), when its font is installed; else the plain bold."""
    face = fonts.load(None) or fonts.load(fonts.default())
    return (lambda px: fonts.qfont(face, px)) if face else (lambda px: ui.font(px, QFont.Black))


STANDBY_TICK_ALPHA = 0.3
STEM = 0.14                                   # a stroke's width as a share of the digits' height
_stems, _paths = {}, {}


def _stem(font):
    """How wide one stroke of this font is against its zero's height, measured across the middle of a "0"."""
    from PySide6.QtGui import QImage
    key = font(100).key()
    if key not in _stems:
        path = render.text_path(QPointF(0, 0), font(118), "0", 0, 0).simplified()
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
        _stems[key] = (sum(runs[:1] + runs[-1:]) / 2 / 200) if runs else STEM
    return _stems[key]


def digits_path(W, H, hh, mm, font):
    """The time as one outline in the card's coordinates, laid out as the program's own clock does: a third of the card
    tall, as wide as the ring leaves, strokes brought up to one weight by a round outline (only as much as the font
    lacks), and a colon of two round dots a quarter and three quarters down."""
    key = (W, H, hh, mm, font(100).key())
    if key in _paths:
        return _paths[key]
    parts = [render.text_path(QPointF(0, 0), font(118), t, 0, 0).simplified() for t in (hh, mm)]
    boxes = [q.boundingRect() for q in parts]
    top = min(b.top() for b in boxes)
    src_h = max(1.0, max(b.bottom() for b in boxes) - top)
    src_w = sum(b.width() for b in boxes)
    want_w = W - 2 * 54
    h = min(H * 0.34, want_w / (0.25 + 0.8 * src_w / src_h + 0.3))
    stem = _stem(font)
    gap = max(0.25, 1.05 * max(STEM, stem) + 0.1) * h

    def fit(e):
        k = (h - e) / src_h
        return k, k * max(0.8, min(1.3, (want_w - gap - 2 * e) / max(1.0, src_w * k)))
    e = 0.0
    for _ in range(3):
        k, kx = fit(e)
        e = max(0.0, min(0.14 * h, STEM * h - stem * (h - e) * kx / k))
    k, kx = fit(e)
    total = src_w * kx + gap + 2 * e
    x0, y0 = (W - total) / 2 + e / 2, H / 2 + 8 - (h - e) / 2
    out, x = QPainterPath(), x0
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
    d = 1.05 * max(STEM * h, stem * (h - e) * kx / k + e)
    for frac in (0.25, 0.74):
        out.addEllipse(QPointF(cx, H / 2 + 8 - h / 2 + h * frac), d / 2, d / 2)
    out = out.simplified()
    if len(_paths) > 12:
        _paths.clear()
    _paths[key] = out
    return out


def draw_digits(p, ink, W, H, hh, mm, font):
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(ink)
    p.drawPath(digits_path(W, H, hh, mm, font))
    p.restore()


def day_line(now, lang):
    if lang.startswith("zh"):
        return "週%s %d/%d" % ("一二三四五六日"[now.weekday()], now.month, now.day)
    return now.strftime("%a %m/%d")


def offset_line(now, lang):
    """How far this time is from this computer's: '+1h', '-3.5h', and 'Tomorrow' / 'Yesterday' when the date differs."""
    here = datetime.datetime.fromtimestamp(now.timestamp()).astimezone()
    hours = (now.utcoffset() - here.utcoffset()).total_seconds() / 3600
    zh = lang.startswith("zh")
    parts = []
    if abs(hours) > 1e-6:
        parts.append(("%+g" % hours) + ("小時" if zh else "h"))
    days = (now.date() - here.date()).days
    if days:
        parts.append(({1: "明天", -1: "昨天"} if zh else {1: "Tomorrow", -1: "Yesterday"}).get(days, "%+dd" % days))
    return " · ".join(parts)


def draw(p, th, W, H, ctx):
    cfg = ctx.config
    tz = zone_of(cfg)
    now = now_in(ctx.now, tz)
    ink, ink2 = faces.solid(p, th, W, H)
    if cfg["ring"]:
        # Awake: the bright tick eases to each second. Standby: nothing moves, every tick equally faint, and the whole
        # clock is drawn once a minute (standby_tick) instead of once a second.
        hand = None if ctx.standby else ctx.spring("second", int(ctx.now), response=0.2) % 60
        for i, (a, b) in enumerate(tick_ends(W, H, th.tokens["radius_panel"])):
            c = QColor(ink)
            c.setAlphaF(ink.alphaF() * (STANDBY_TICK_ALPHA if hand is None else tick_alpha((hand - i) % 60)))
            p.setPen(QPen(c, 3.2, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(a, b)
    text(p, th, "clock_day", day_line(now, ctx.lang), 0, 58, W, "c", ink2)
    if cfg["hours"] == "12":
        digits, ampm = now.strftime("%I:%M").lstrip("0"), now.strftime("%p")
    else:
        digits, ampm = now.strftime("%H:%M"), ""
    hh, mm = digits.split(":")
    draw_digits(p, ink, W, H, hh, mm, digit_font())
    sub = " · ".join(s for s in (ampm, city_of(cfg, ctx.lang), offset_line(now, ctx.lang) if tz else "") if s)
    if sub:
        text(p, th, "secondary", sub, 40, 248, W - 80, "c", ink2)


WIDGET = WidgetDef(
    id="example.clock", name={"en": "Clock", "zh": "時鐘"}, size="2x2",
    config=[Field("zone", "choice", "local", {"en": "Time zone", "zh": "時區"}, options=tuple(z for z, _, _ in ZONES),
                  choices=NAMES),
            Field("custom_zone", "text", "", {"en": "Another zone", "zh": "其他時區"},
                  help={"en": "Any name such as Asia/Kolkata; used instead of the list above.",
                        "zh": "任何時區名稱,例如 Asia/Kolkata;填了就取代上面的選擇。"}),
            Field("label", "text", "", {"en": "Name shown", "zh": "顯示的名稱"}),
            Field("hours", "choice", "24", {"en": "Hours", "zh": "時制"}, options=("24", "12"),
                  choices={"24": {"en": "24-hour", "zh": "24 小時"}, "12": {"en": "12-hour", "zh": "12 小時"}}),
            Field("ring", "bool", True, {"en": "Seconds ring", "zh": "秒針環"})],
    sources=[], draw=draw, tick=1, standby_tick=60, background="solid")
