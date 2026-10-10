"""The program's player, remade with the kit: what this computer is playing, with its cover, a bar to seek by (tap or drag),
and previous / play-pause / next. The card takes its colour from the cover."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor

from nativeui import render
from widgetkit import controls, faces, media
from widgetkit.definition import WidgetDef, media as media_action
from widgetkit.sources import SystemMediaSource
from widgetkit.theme import text

PAD = 24
WHITE, SOFT = QColor(255, 255, 255), QColor(255, 255, 255, 190)
ACTIVE = ("playing", "paused")
OPTIMISTIC_S = 3.0


def layout(W, H):
    """Where things go, shared by drawing and by the handlers that need a position on the bar."""
    side = H - 2 * PAD
    x = PAD + side + 26
    tw = W - x - PAD
    return {"cover": QRectF(PAD, PAD, side, side), "x": x, "w": tw, "bar_y": PAD + 124}


def current(ctx):
    """What is playing, with a play/pause just pressed shown at once (before Windows says so)."""
    d = dict(ctx.data.get("media") or {"state": "off", "can": []})
    opt = ctx.state.get("_optimistic")
    if opt and ctx.now < opt["until"] and d["state"] != opt["state"]:
        d.update(state=opt["state"], position=opt["position"], position_at=ctx.now)
    return d


def position(d, now):
    dur = d.get("duration") or 0.0
    pos = d.get("position") or 0.0
    if d["state"] == "playing":
        pos += now - d.get("position_at", now)
    return max(0.0, min(dur or pos, pos)), dur


def draw(p, th, W, H, ctx):
    d = current(ctx)
    art = d.get("art")
    faces.tinted(p, th, W, H, media.dominant_color(art))
    L = layout(W, H)
    box = L["cover"]
    p.save()
    p.setClipPath(render.squircle(box.x(), box.y(), box.width(), box.height(), 26))
    if art:
        media.picture(p, art, box, "cover", mono=th.dim)                      # standby: the cover as white on clear glass
    else:
        p.fillRect(box, QColor(255, 255, 255, 46))
        controls.icon(p, "mdi:music", WHITE, box, 68)
    p.restore()
    x, tw = L["x"], L["w"]
    controls.icon(p, "mdi:music", QColor(255, 255, 255, 190), QRectF(W - PAD - 26, PAD, 26, 26), 24)
    zh = ctx.lang.startswith("zh")
    idle = d["state"] not in ACTIVE
    text(p, th, "player_app", d.get("app") or ("本機" if zh else "This computer"), x, PAD + 2, tw - 36, color=SOFT)
    title = d.get("title") or (("未在播放" if zh else "Not playing") if idle else d["state"])
    text(p, th, "player_title", title, x, PAD + 40, tw)
    if d.get("artist"):
        text(p, th, "player_artist", d["artist"], x, PAD + 78, tw, color=SOFT)
    pos, dur = position(d, ctx.now)
    seeking = ctx.state.get("_seek_to")
    if dur:
        if seeking is not None:
            pos = max(0.0, min(dur, seeking))
        y = L["bar_y"]
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 70))
        p.drawRoundedRect(QRectF(x, y, tw, 6), 3, 3)
        p.setBrush(WHITE)
        p.drawRoundedRect(QRectF(x, y, max(6.0, tw * pos / dur), 6), 3, 3)
        if "seek" in d["can"] and not idle:
            r = 11 if seeking is not None else 8
            p.drawEllipse(QPointF(x + tw * pos / dur, y + 3), r, r)
            ctx.hits.add(QRectF(x, y - 16, tw, 38), "seek")
    big, small = 76, 58
    cy, cx = H - PAD - big / 2, x + tw / 2
    playing = d["state"] == "playing"
    for id, icon, size, dx in (("previous", "mdi:skip-previous", small, -(big / 2 + 22 + small / 2)),
                               ("play_pause", "mdi:pause" if playing else "mdi:play", big, 0),
                               ("next", "mdi:skip-next", small, big / 2 + 22 + small / 2)):
        r = QRectF(cx + dx - size / 2, cy - size / 2, size, size)
        on = id in d["can"] and not idle
        p.save()
        if not on:                                                         # nothing playing, or it cannot: faint, inert
            p.setOpacity(p.opacity() * 0.35)
        if ctx.pressed == id and on:
            c = r.center()
            p.translate(c)
            p.scale(0.94, 0.94)
            p.translate(-c.x(), -c.y())
        if id == "play_pause":
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 235))
            p.drawEllipse(r)
            controls.icon(p, icon, QColor("#1d1d1f"), r, size - 36)
        else:
            controls.icon(p, icon, WHITE, r, size - 20)
        p.restore()
        if on:
            ctx.hits.add(r, id)


def fraction(ctx, x):
    L = layout(*ctx.size)
    return max(0.0, min(1.0, (x - L["x"]) / L["w"]))


def on_tap(id, ctx):
    d = current(ctx)
    if id in ("previous", "next"):
        return media_action(id)
    if id == "play_pause":
        pos, _ = position(d, ctx.now)
        ctx.set_state(_optimistic={"state": "paused" if d["state"] == "playing" else "playing", "position": pos,
                                   "until": ctx.now + OPTIMISTIC_S})
        return media_action("play_pause")
    if id == "seek":                                                       # a tap on the bar: go there
        return media_action("seek", fraction(ctx, ctx.pointer[0]) * (d.get("duration") or 0.0))


def on_drag(id, move, ctx):
    if id != "seek":
        return None
    dur = current(ctx).get("duration") or 0.0
    target = fraction(ctx, move.x) * dur
    if move.phase == "end":
        ctx.set_state(_seek_to=None, _optimistic={"state": current(ctx)["state"], "position": target,
                                                   "until": ctx.now + OPTIMISTIC_S})
        return media_action("seek", target)
    ctx.set_state(_seek_to=target)                                         # the knob follows the pointer while dragging


WIDGET = WidgetDef(
    id="example.player", name={"en": "Player", "zh": "播放器"}, size="2x4", config=[],
    sources=[SystemMediaSource("media", every=1.0)], draw=draw, on_tap=on_tap, on_drag=on_drag,
    permissions=("media",), tick=0.5, background="solid")
