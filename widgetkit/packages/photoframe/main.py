"""A photo frame: up to ten pictures (still and moving: JPG, PNG, GIF, WebP...) shown full size on the card.

* A right click moves on to the next picture. (The widget keeps the right click, so its editor is opened from the tray.)
* Settings: the pictures; whether it moves on by itself and how often (0 = never); whether in standby the picture turns into
  white, clear line-work (the program's standby look) or stays as it is.
"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor

from widgetkit import controls, media
from widgetkit.definition import Field, WidgetDef
from widgetkit.theme import paragraph

FADE = 0.45                   # seconds a change of picture takes
DOT, DOT_STEP = 3.0, 12.0     # the dots at the foot that say which picture of how many


def position(ctx, n, now):
    """(index, seconds since it came up, previous index or None) of the picture to show at `now`. Pure of the clock: the
    widget keeps where it started (`index`, `since`) and the picture is worked out from the time, so nothing needs changing
    while drawing. A change of the settings that changes the timing starts it again from the picture shown."""
    st, every = ctx.state, float(ctx.config["interval"] or 0)
    if st.get("since") is None or st.get("every") != every or st.get("n") != n:
        shown = int(st.get("index", 0)) % n
        st["index"], st["since"], st["every"], st["n"] = shown, now, every, n      # (not set_state: it is only a start)
    base, since = int(st["index"]) % n, float(st["since"])
    steps = int((now - since) // every) if every > 0 and n > 1 else 0
    idx = (base + steps) % n
    age = (now - since) - steps * every if every > 0 and n > 1 else now - since
    prev = st.get("prev") if steps == 0 else (idx - 1) % n
    return idx, age, (int(prev) % n if prev is not None and n > 1 else None)


def picture(p, th, ctx, path, rect, radius, alpha=1.0):
    """One picture over the whole card: moving ones follow the clock (not in standby), and in standby white and clear if the
    setting says so."""
    p.save()
    p.setOpacity(alpha)
    if th.dim:
        media.picture(p, path, rect, "cover", radius, mono=bool(ctx.config["standby_clear"]))
    else:
        moving = media.animation(path)
        if moving is not None:
            frame, wait = moving.at(ctx.now * 1000)
            media.picture(p, frame, rect, "cover", radius)
            ctx.redraw_in(wait / 1000.0 if moving.done else 0.1)
        else:
            media.picture(p, path, rect, "cover", radius)
    p.restore()


def dots(p, th, W, H, n, at):
    x0 = W / 2 - (n - 1) * DOT_STEP / 2
    p.save()
    for i in range(n):
        c = QRectF(x0 + i * DOT_STEP - DOT, H - 20 - DOT, 2 * DOT, 2 * DOT)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 70))
        p.drawEllipse(c.adjusted(-1, -1, 1, 1))
        p.setBrush(QColor(255, 255, 255, 235 if i == at else 120))
        p.drawEllipse(c)
    p.restore()


def draw(p, th, W, H, ctx):
    files = list(ctx.config["images"])
    card = QRectF(0, 0, W, H)
    if not files:
        zh = ctx.lang.startswith("zh")
        controls.icon(p, "mdi:image-multiple-outline", th.ink2, QRectF(W / 2 - 24, H / 2 - 44, 48, 48))
        paragraph(p, th, "secondary", "在設定裡選擇圖片" if zh else "Choose pictures in settings",
                  QRectF(12, H / 2 + 16, W - 24, 70), "c", max_lines=3)
        return
    now, radius = ctx.now, th.tokens["radius_panel"]
    n = len(files)
    idx, age, prev = position(ctx, n, now)
    fading = not th.dim and prev is not None and age < FADE
    if fading:
        picture(p, th, ctx, files[prev], card, radius)
        picture(p, th, ctx, files[idx], card, radius, age / FADE)
        ctx.redraw_in(0.033)
    else:
        picture(p, th, ctx, files[idx], card, radius)
    every = float(ctx.config["interval"] or 0)
    if every > 0 and n > 1:
        ctx.redraw_in(max(0.05, every - age))
    if n > 1 and not th.dim:
        dots(p, th, W, H, n, idx)


def on_context(id, ctx):
    """Right click: the next picture (and the timer for moving on by itself starts again)."""
    files = ctx.config["images"]
    n = len(files)
    if n < 2:
        return
    idx, _, _ = position(ctx, n, ctx.now)
    ctx.set_state(index=(idx + 1) % n, since=ctx.now, every=float(ctx.config["interval"] or 0), n=n, prev=idx)


WIDGET = WidgetDef(
    id="example.photoframe", name={"en": "Photo frame", "zh": "相框"}, size="2x2", sizes=("1x1", "2x4", "4x4"),
    config=[Field("images", "images", [], {"en": "Pictures", "zh": "圖片"}, maximum=10,
                  help={"en": "Up to 10. Still and moving pictures: JPG, PNG, GIF, WebP and more. Right click the widget to see the next.",
                        "zh": "最多 10 張，支援 JPG、PNG、GIF、WebP 等靜態與動態圖片。在 widget 上按右鍵可切換下一張。"}),
            Field("interval", "number", 30, {"en": "Change picture every (seconds, 0 = never)", "zh": "自動輪播間隔（秒，0 為不輪播）"},
                  minimum=0, maximum=86400, step=5),
            Field("standby_clear", "bool", True, {"en": "Clear white picture in standby", "zh": "待機時變成透明的白色圖片"},
                  help={"en": "In standby the picture becomes white and clear where it is dark, as the program's standby look; "
                              "off keeps it as it is.",
                        "zh": "開啟時，待機畫面會變成白色、暗處透明的單色圖片（程式的待機風格）；關閉則維持原圖。"})],
    sources=[], draw=draw, on_context=on_context)
