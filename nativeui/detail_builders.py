"""What each kind of device shows in its detail (after Home Assistant's more-info dialogs): one builder for each, put on a Stack."""
import threading
import time

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen

from . import appearance, controls, kinds, render, style, ui
from .ui import Button, Slider, View


BODY_X, BODY_W = 14, 292


HISTORY_HOURS = 24

HVAC_LABELS = {"off": "關閉", "cool": "冷氣", "heat": "暖氣", "heat_cool": "自動", "auto": "自動",
               "dry": "除濕", "fan_only": "送風"}


def trim_number(n):
    return str(round(n * 10) / 10).rstrip("0").rstrip(".") if round(n * 10) / 10 != int(round(n * 10) / 10) else str(int(round(n * 10) / 10))


class Chart(View):
    """The last day of a sensor: its line, the area under it, and a dot at the end."""

    def __init__(self, w, h=64):
        super().__init__(0, 0, w, h)
        self.points = None
        self.message = "載入中…"

    def paint(self, p):
        if not self.points:
            f = ui.font(12)
            tw = ui.text_width(render.tr(self.message), f)
            fm = ui.QFontMetricsF(f)
            p.setPen(Qt.NoPen)
            p.setBrush(ui.resolve(self.scene, "ink2"))
            p.drawPath(render.text_path(QPointF(0, 0), f, render.tr(self.message), (self.w - tw) / 2,
                                        (self.h - fm.height() / 10) / 2 + fm.ascent() / 10))
            return
        pts = self.points
        t0, t1 = pts[0][0], pts[-1][0] or pts[0][0] + 1
        span = max(1, t1 - t0)
        lo, hi = min(v for _, v in pts), max(v for _, v in pts)
        if hi - lo < 0.5:
            mid = (hi + lo) / 2
            lo, hi = mid - 0.5, mid + 0.5
        pad = 3
        xy = [((t - t0) / span * self.w, pad + (1 - (v - lo) / (hi - lo)) * (self.h - 2 * pad)) for t, v in pts]
        line = QPainterPath()
        line.moveTo(*xy[0])
        for x, y in xy[1:]:
            line.lineTo(x, y)
        area = QPainterPath(line)
        area.lineTo(self.w, self.h)
        area.lineTo(0, self.h)
        area.closeSubpath()
        blue = ui.resolve(self.scene, "accent_blue")
        p.setPen(Qt.NoPen)
        fillc = QColor(blue)
        fillc.setAlphaF(0.16)
        p.setBrush(fillc)
        p.drawPath(area)
        p.setPen(QPen(blue, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPath(line)
        p.setPen(QPen(QColor(255, 255, 255), 1.2))
        p.setBrush(blue)
        p.drawEllipse(QPointF(*xy[-1]), 2.5, 2.5)


STATE_TEXT = {
    "lock": {"locked": "已上鎖", "unlocked": "已解鎖", "jammed": "卡住了", "locking": "上鎖中", "unlocking": "解鎖中",
             "open": "已開啟", "opening": "開啟中"},
    "cover": {"open": "開啟", "closed": "關閉", "opening": "開啟中", "closing": "關閉中"},
    "vacuum": {"cleaning": "清掃中", "docked": "已回充", "returning": "回充中", "paused": "已暫停", "idle": "待命",
               "error": "錯誤"},
}
TALL_W, TALL_H = 120, 220
TALL_MIN = 150                       # the shortest a tall control is made to fit the tray panel


def _attrs(state):
    return (state or {}).get("attributes") or {}


def centered(stack, view, mt=0, mb=0):
    """A view in the middle of the body's width."""
    row = View(0, 0, BODY_W, view.h)
    view.x, view.y = (BODY_W - view.w) / 2, 0
    row.add(view)
    return stack.place(row, mt, mb)


def mode_bar(card, items):
    return controls.ModeBar(items, size=36 if getattr(card, "panel_layout", False) else 44 if getattr(card, "panel_fit", False) else 52)


def big_value(stack, text, state, mt=6):
    """The state, large, and how long ago it changed; the label is returned to follow a slider."""
    label = style.label("display", text, w=BODY_W, align="c")
    stack.place(label, mt, 2)
    since = controls.ago((state or {}).get("last_changed"))
    if since:
        stack.place(style.label("meta", since, w=BODY_W, align="c"), 0, 14)
    return label


def cards(card, stack, items):
    """Mode cards two to a row; pressed, one opens its choices in a menu over the screen.
    items: [(icon, title, current label, [(value, label)], on_pick)]."""
    if not items:
        return
    gap = 10
    w = (BODY_W - gap) / 2 if len(items) > 1 else min(BODY_W, 190)
    for i in range(0, len(items), 2):
        row_h = 50 if getattr(card, "panel_layout", False) else 54 if getattr(card, "panel_fit", False) else 62
        row = View(0, 0, BODY_W, row_h)
        pair = items[i:i + 2]
        left = (BODY_W - (len(pair) * w + (len(pair) - 1) * gap)) / 2
        for j, (icon, title, value, options, pick) in enumerate(pair):
            current = next((v for v, lab in options if lab == value), None)
            mc = controls.ModeCard(w, icon, title, value, options, pick, current,
                                   compact=getattr(card, "panel_fit", False))
            mc.h = row_h
            mc.x = left + j * (w + gap)
            row.add(mc)
        stack.place(row, 6 if getattr(card, "panel_layout", False) else 8, 8)


def build_onoff(card, stack, tile, state):
    """A thing switched on and off, shown as its family (appearance.py): its words, its colour, its icon; as a
    lock, the lock's own screen."""
    if appearance.family(tile) == "lock":
        return build_lock(card, stack, tile, state)
    on = bool(state) and state.get("state") == "on"
    on_words, off_words = appearance.words(tile)
    big_value(stack, on_words if on else off_words, state)
    color = "accent_" + appearance.COLORS.get(appearance.family(tile), "blue")
    if appearance.family(tile) == "light":
        color = render.light_color(state if tile["domain"] == "light" else None, "dark")
    centered(stack, controls.TallSwitch(TALL_W, card.tall, on, color, render.icon_name(tile, state),
                                        lambda: (card.optimistic(tile["entity"], {"state": "off" if on else "on"}),
                                                 card.call(tile["domain"], "toggle", tile["entity"]))), 4, 16)


def light_effects(card, stack, entity, attrs):
    """A light's effects, as one card that opens a menu of them. Shown on or off: the card is fitted to what it
    holds when opened, and one that came with the light switching on would fall outside it."""
    effects = attrs.get("effect_list") or []
    if effects:
        cards(card, stack, [("mdi:auto-fix", "特效", attrs.get("effect") or "無",
                             [(e, e) for e in effects],
                             lambda v: card.call("light", "turn_on", entity, {"effect": v}))])


def build_light(card, stack, tile, state):
    attrs = _attrs(state)
    on = bool(state) and state.get("state") == "on"
    entity = tile["entity"]
    modes = attrs.get("supported_color_modes") or []
    if modes and all(m == "onoff" for m in modes):      # a light that only goes on and off: its switch, not a slider
        build_onoff(card, stack, tile, state)
        light_effects(card, stack, entity, attrs)
        return
    pct =round(attrs["brightness"] / 255 * 100) if attrs.get("brightness") is not None else (100 if on else 0)
    modes = attrs.get("supported_color_modes") or []
    rgb = attrs.get("rgb_color") if isinstance(attrs.get("rgb_color"), list) else None
    color = "rgb(%d,%d,%d)" % tuple(rgb[:3]) if rgb else "accent_yellow"
    temps = "color_temp" in modes
    try:
        lo_k, hi_k = float(attrs["min_color_temp_kelvin"]), float(attrs["max_color_temp_kelvin"])
    except (KeyError, TypeError, ValueError):
        lo_k = hi_k = 0.0
    temps = temps and lo_k > 0 and hi_k > lo_k
    view = card.light_view if (card.light_view != "temp" or (temps and on)) else "brightness"
    label = big_value(stack, ("%d%%" % pct) if on else "關閉", state)
    if view == "temp":
        cur = attrs.get("color_temp_kelvin")
        val = cur if isinstance(cur, (int, float)) and lo_k <= cur <= hi_k else round((lo_k + hi_k) / 2)
        warm, cool = kelvin_css(lo_k), kelvin_css(hi_k)
        slider = controls.TallSlider(TALL_W, card.tall, val, lo_k, hi_k, color, step=50,
                                     gradient=[(0, warm), (1, cool)],
                                     on_input=lambda v: setattr(label, "text", "%dK" % v),
                                     on_commit=lambda v: card.call("light", "turn_on", entity, {"color_temp_kelvin": int(v)}))
    else:
        def commit(v):
            if v <= 0:
                card.optimistic(entity, {"state": "off"})
                card.call("light", "turn_off", entity)
            else:
                card.call("light", "turn_on", entity, {"brightness_pct": int(v)})
        slider = controls.TallSlider(TALL_W, card.tall, pct if on else 0, 0, 100, color,
                                     on_input=lambda v: setattr(label, "text", ("%d%%" % v) if v else render.tr("關閉")),
                                     on_commit=commit)
    centered(stack, slider, 4, 14)
    bar = [("mdi:power", False, lambda: (card.optimistic(entity, {"state": "off" if on else "on"}),
                                        card.call("light", "toggle", entity))),
           ("mdi:brightness6", view == "brightness", lambda: card.set_light_view("brightness"))]
    if temps and on:
        bar.append(("mdi:thermometer", view == "temp", lambda: card.set_light_view("temp")))
    centered(stack, mode_bar(card, bar), 4, 8 if getattr(card, "panel_layout", False) else 14)
    swatches = []
    if temps:
        for k in (2700, 3500, 4500, 6000):
            k = max(lo_k, min(hi_k, k))
            swatches.append((kelvin_css(k), ("k", int(k))))
    if any(m in modes for m in ("hs", "rgb", "rgbw", "rgbww", "xy")):
        swatches.append(("rainbow", ("pick", None)))

    def pick(value):
        kind, v = value
        if kind == "k":
            card.call("light", "turn_on", entity, {"color_temp_kelvin": v})
        else:
            controls.open_colors(sw, tuple(rgb[:3]) if rgb else None,
                                 lambda c: card.call("light", "turn_on", entity, {"rgb_color": list(c)}))
    if swatches:
        sw = controls.Swatches(BODY_W, swatches, pick, size=32 if getattr(card, "panel_layout", False) else 46)
        sw.key, sw.open = "colors", False
        stack.place(sw, 4, 8 if getattr(card, "panel_layout", False) else 14)
    light_effects(card, stack, entity, attrs)


def kelvin_css(k):
    return "rgb(%d,%d,%d)" % controls.kelvin_rgb(k)


def build_fan(card, stack, tile, state):
    attrs = _attrs(state)
    on = bool(state) and state.get("state") == "on"
    entity = tile["entity"]
    if attrs.get("percentage") is None:
        return build_onoff(card, stack, tile, state)
    pct = attrs["percentage"] if on else 0
    label = big_value(stack, ("%d%%" % pct) if on else "關閉", state)

    def commit(v):
        if v <= 0:
            card.optimistic(entity, {"state": "off"})
            card.call("fan", "turn_off", entity)
        else:
            card.call("fan", "set_percentage", entity, {"percentage": int(v)})
    step = attrs.get("percentage_step") or 1
    centered(stack, controls.TallSlider(TALL_W, card.tall, pct, 0, 100, "accent_blue", step=step,
                                        on_input=lambda v: setattr(label, "text", ("%d%%" % v) if v else render.tr("關閉")),
                                        on_commit=commit), 4, 14)
    centered(stack, mode_bar(card, [("mdi:power", on, lambda: (card.optimistic(entity, {"state": "off" if on else "on"}),
                                                                 card.call("fan", "toggle", entity)))]), 4, 14)
    presets = attrs.get("preset_modes") or []
    if presets:
        cards(card, stack, [("mdi:fan", "預設模式", attrs.get("preset_mode") or "無",
                             [(p, p) for p in presets],
                             lambda v: card.call("fan", "set_preset_mode", entity, {"preset_mode": v}))])


def build_lock(card, stack, tile, state):
    """A lock, and anything shown as one (a switch given a lock's icon): the same screen. The tall switch is
    up and green when locked; its words are the tile's (render.state_text)."""
    s = (state or {}).get("state")
    entity = tile["entity"]
    if tile["domain"] == "lock":
        locked = s == "locked"
        act = lambda: (card.optimistic(entity, {"state": "unlocked" if locked else "locked"}),
                       card.call("lock", "unlock" if locked else "lock", entity))
    else:                                   # a switch shown as a lock: on is unlocked (appearance.WORDS)
        locked = s != "on"
        act = lambda: (card.optimistic(entity, {"state": "on" if locked else "off"}),
                       card.call(tile["domain"], "toggle", entity))
    big_value(stack, render.state_text(tile, state) if state else "無法連線", state)
    centered(stack, controls.TallSwitch(TALL_W, card.tall, locked, "accent_green", render.icon_name(tile, state),
                                        act), 4, 16)


def build_climate(card, stack, tile, state):
    attrs = _attrs(state)
    entity = tile["entity"]
    mode = (state or {}).get("state") or "off"
    target, current = attrs.get("temperature"), attrs.get("current_temperature")
    humidity = attrs.get("current_humidity")
    # the room: temperature and humidity, side by side
    readings = [(lab, val) for lab, val in (("目前溫度", None if current is None else "%s°" % trim_number(current)),
                                            ("目前濕度", None if humidity is None else "%s%%" % trim_number(humidity)))
                if val is not None]
    if readings:
        row = View(0, 0, BODY_W, 44)
        w = BODY_W / len(readings)
        for i, (lab, val) in enumerate(readings):
            row.add(style.label("label", lab, x=i * w, y=0, w=w, align="c"))
            row.add(style.label("headline", val, x=i * w, y=18, w=w, align="c"))
        stack.place(row, 2, 8)
    step = float(attrs.get("target_temp_step") or tile.get("temp_step") or 1)
    lo, hi = float(attrs.get("min_temp") or 7), float(attrs.get("max_temp") or 35)

    def commit(v):
        card.optimistic(entity, {"attributes": dict(attrs, temperature=v)})
        card.call("climate", "set_temperature", entity, {"temperature": v})
    dial = controls.Dial(min(BODY_W, card.tall + (44 if getattr(card, "panel_layout", False) else 16)), target, lo, hi, step, current, HVAC_LABELS.get(mode, mode),
                         None if mode == "off" else render.HVAC_COLORS.get(mode, "accent_cyan"), on_commit=commit)
    centered(stack, dial, 0, 0)

    def stepper(delta):
        if target is not None:
            commit(max(lo, min(hi, round((target + delta) * 10) / 10)))
    button_size = 36 if getattr(card, "panel_layout", False) else 44 if getattr(card, "panel_fit", False) else 52
    row = View(0, 0, BODY_W, button_size)
    for i, (sign, delta) in enumerate((("mdi:minus", -step), ("mdi:plus", step))):
        b = Button(x=BODY_W / 2 + (-12 - button_size if i == 0 else 12), y=0, w=button_size, h=button_size, icon=sign, icon_size=22,
                   fill=None, ring="ink2", hover_fill="btn_fill", on_click=lambda e, d=delta: stepper(d))
        row.add(b)
    stack.place(row, 0, 8 if getattr(card, "panel_layout", False) else 14)
    items = [("mdi:power" if mode == "off" else "mdi:thermostat", "模式", HVAC_LABELS.get(mode, mode),
              [(m, HVAC_LABELS.get(m, m)) for m in (attrs.get("hvac_modes") or ["off", "cool", "heat", "auto"])],
              lambda m: (card.optimistic(entity, {"state": m}),
                         card.call("climate", "set_hvac_mode", entity, {"hvac_mode": m})))]
    if attrs.get("fan_modes"):
        items.append(("mdi:fan", "風速模式", FAN_LABELS.get(attrs.get("fan_mode"), attrs.get("fan_mode") or "無"),
                      [(m, FAN_LABELS.get(m, m)) for m in attrs["fan_modes"]],
                      lambda m: card.call("climate", "set_fan_mode", entity, {"fan_mode": m})))
    if attrs.get("preset_modes"):
        items.append(("mdi:tune-variant", "預設模式", attrs.get("preset_mode") or "無",
                      [(m, m) for m in attrs["preset_modes"]],
                      lambda m: card.call("climate", "set_preset_mode", entity, {"preset_mode": m})))
    cards(card, stack, items)


FAN_LABELS = {"auto": "自動", "low": "低", "medium": "中", "high": "高", "middle": "中", "silent": "靜音",
              "quiet": "靜音", "turbo": "強力", "strong": "強"}


def build_cover(card, stack, tile, state):
    attrs = _attrs(state)
    entity = tile["entity"]
    s = (state or {}).get("state") or ""
    pos = attrs.get("current_position")
    label = big_value(stack, ("%d%%" % pos) if pos is not None else STATE_TEXT["cover"].get(s, s or "無法連線"), state)
    if pos is not None:
        centered(stack, controls.TallSlider(TALL_W, card.tall, pos, 0, 100, "accent_blue",
                                            on_input=lambda v: setattr(label, "text", "%d%%" % v),
                                            on_commit=lambda v: card.call("cover", "set_cover_position", entity,
                                                                         {"position": int(v)})), 4, 14)
    centered(stack, mode_bar(card, [
        ("mdi:arrow-up", s == "open", lambda: card.call("cover", "open_cover", entity)),
        ("mdi:stop", False, lambda: card.call("cover", "stop_cover", entity)),
        ("mdi:arrow-down", s == "closed", lambda: card.call("cover", "close_cover", entity))]), 4, 14)


def build_media(card, stack, tile, state):
    attrs = _attrs(state)
    entity = tile["entity"]
    s = (state or {}).get("state") or ""
    playing = s == "playing"
    art = attrs.get("entity_picture")
    side = card.tall - 24
    centered(stack, controls.Picture(side, side, art, card.api.get_picture, card.run_on_ui_thread), 4, 16)
    title = attrs.get("media_title") or STATE_TEXT.get("media", {}).get(s) or s
    stack.place(style.label("headline", title, w=BODY_W, overflow="fade"), 0, 2)
    artist = attrs.get("media_artist") or attrs.get("app_name") or ""
    if artist:
        stack.place(style.label("secondary", artist, w=BODY_W, overflow="fade"), 0, 10)
    if attrs.get("media_duration"):
        def seek(s):
            card.optimistic(entity, {"attributes": dict(attrs, media_position=s,
                                                        media_position_updated_at=controls.now_iso())})
            card.call("media_player", "media_seek", entity, {"seek_position": round(s, 1)})
        can_seek = int(attrs.get("supported_features") or 0) & 2      # MediaPlayerEntityFeature.SEEK
        stack.place(controls.Progress(BODY_W, attrs.get("media_position"), attrs.get("media_position_updated_at"),
                                      attrs.get("media_duration"), playing, on_seek=seek if can_seek else None), 6, 6)
    row = View(0, 0, BODY_W, 64)
    buttons = []
    if "shuffle" in attrs:
        buttons.append((40, "mdi:shuffle-variant" if attrs.get("shuffle") else "mdi:shuffle-disabled",
                        lambda: card.call("media_player", "shuffle_set", entity, {"shuffle": not attrs.get("shuffle")})))
    buttons.append((44, "mdi:skip-previous", lambda: card.call("media_player", "media_previous_track", entity)))
    buttons.append((64, "mdi:pause" if playing else "mdi:play",
                    lambda: (card.optimistic(entity, kinds.play_pause_patch(state)),
                             card.call("media_player", "media_play_pause", entity))))
    buttons.append((44, "mdi:skip-next", lambda: card.call("media_player", "media_next_track", entity)))
    if "repeat" in attrs:
        nxt = {"off": "all", "all": "one", "one": "off"}.get(attrs.get("repeat"), "off")
        buttons.append((40, {"one": "mdi:repeat-once", "all": "mdi:repeat"}.get(attrs.get("repeat"), "mdi:repeat-off"),
                        lambda: card.call("media_player", "repeat_set", entity, {"repeat": nxt})))
    gap = 12
    x = (BODY_W - (sum(b[0] for b in buttons) + gap * (len(buttons) - 1))) / 2
    can = kinds.media_controls(state)
    needs = {"mdi:skip-previous": "previous", "mdi:skip-next": "next", "mdi:pause": "play_pause",
             "mdi:play": "play_pause"}
    for size, icon, click in buttons:
        big = size == 64
        b = Button(x=x, y=(64 - size) / 2, w=size, h=size, icon=icon, icon_size=28 if big else 22,
                   fill="accent_blue" if big else None, hover_fill="accent_blue" if big else "btn_fill",
                   color="white" if big else "ink1", on_click=lambda e, c=click: c())
        if icon in needs and needs[icon] not in can:     # nothing playing, or the player cannot: inert
            b.alpha, b.interactive = 0.35, False
        row.add(b)
        x += size + gap
    stack.place(row, 8, 8)
    if attrs.get("volume_level") is not None:
        vol = View(0, 0, BODY_W, 30)
        muted = attrs.get("is_volume_muted")
        vol.add(Button(x=0, y=0, w=30, h=30, icon="mdi:volume-off" if muted else "mdi:volume-high", icon_size=18, fill=None,
                       hover_fill="btn_fill",
                       on_click=lambda e: card.call("media_player", "volume_mute", entity, {"is_volume_muted": not muted})))
        vol.add(Slider(40, 4, BODY_W - 40, round(attrs["volume_level"] * 100), 0, 100, 1,
                       on_commit=lambda v: card.call("media_player", "volume_set", entity, {"volume_level": v / 100})))
        stack.place(vol, 6, 10)
    items = []
    if attrs.get("source_list"):
        items.append(("mdi:import", "來源", attrs.get("source") or "無", [(x, x) for x in attrs["source_list"]],
                      lambda v: card.call("media_player", "select_source", entity, {"source": v})))
    off = s in ("off", "standby", "")
    items.append(("mdi:power", "電源", "關閉" if off else "開啟", [("on", "開啟"), ("off", "關閉")],
                  lambda v: card.call("media_player", "turn_on" if v == "on" else "turn_off", entity)))
    cards(card, stack, items)


def build_vacuum(card, stack, tile, state):
    s = state.get("state") if state else ""
    cleaning = s == "cleaning"
    big_value(stack, STATE_TEXT["vacuum"].get(s, s or "無法連線"), state)
    centered(stack, mode_bar(card, [
        ("mdi:pause" if cleaning else "mdi:play", cleaning,
         lambda: card.call("vacuum", "pause" if cleaning else "start", tile["entity"])),
        ("mdi:home-import-outline", s == "returning", lambda: card.call("vacuum", "return_to_base", tile["entity"]))]),
        8, 14)


def build_readout(card, stack, tile, state):
    """Devices with no controls: the reading, large, and its history when it is a number."""
    text = (render.value_text(tile["domain"], state) or state["state"]) if state else "無法連線"
    stack.place(style.label("display", text, w=BODY_W - 8, align="c", wrap=True, any_break=True), 22, 0)
    since = controls.ago((state or {}).get("last_changed"))
    stack.place(style.label("meta", since or tile["entity"], w=BODY_W - 8, align="c", wrap=True,
                      any_break=True), 6, 8)
    try:
        numeric = bool(state) and float(state["state"]) == float(state["state"])
    except (TypeError, ValueError):
        numeric = False
    if numeric:
        block = View(0, 0, BODY_W, 16 + 4 + 64)
        block.add(style.label("caption", "過去 %d 小時" % HISTORY_HOURS, w=BODY_W))
        rng = style.label("caption", "", w=BODY_W, align="r")
        block.add(rng)
        chart = Chart(BODY_W)
        chart.y = 20
        block.add(chart)
        stack.place(block, 10, 0)
        card.history_token += 1
        token = card.history_token

        def load():
            try:
                res = card.api.get_history(tile["entity"], HISTORY_HOURS)
            except Exception:
                res = None

            def apply():
                if token != card.history_token:
                    return
                if not res or not res.get("ok") or len(res.get("points") or []) < 2:
                    chart.message = "沒有紀錄"
                else:
                    chart.points = res["points"]
                    vs = [v for _, v in res["points"]]
                    rng.text = "%s – %s" % (trim_number(min(vs)), trim_number(max(vs)))
                chart.changed()
            card.run_on_ui_thread(apply)
        threading.Thread(target=load, daemon=True).start()


def build_weather(card, stack, tile, state):
    """Now, large, and the coming days, each with its low and high (fetched once, then kept on the card)."""
    from . import kinds
    attrs = _attrs(state)
    icon, text = kinds.condition(state)
    centered(stack, ui.IconView(icon, "ink1", size=52), 4, 0)
    stack.place(style.label("hero", "%s°" % trim_number(attrs["temperature"]) if attrs.get("temperature") is not None
                            else "--", w=BODY_W, align="c"), 0, 0)
    stack.place(style.label("headline", text, w=BODY_W, align="c"), 2, 4)
    extra = " · ".join(x for x in (("%s %s%%" % (render.tr("濕度"), trim_number(attrs["humidity"])))
                                   if attrs.get("humidity") is not None else "",
                                   controls.ago((state or {}).get("last_changed"))) if x)
    if extra:
        stack.place(style.label("meta", extra, w=BODY_W, align="c"), 0, 14)
    kept = getattr(card, "forecast", None)
    if not kept or kept[0] != tile["entity"]:
        stack.place(style.label("meta", "載入中…", w=BODY_W, align="c"), 6, 8)
        entity = tile["entity"]

        def load():
            try:
                days = card.api.get_forecast(entity)
            except Exception:
                days = []

            def apply():
                card.forecast = (entity, days)
                if card.tile and card.tile["entity"] == entity:
                    card.rebuilt()
            card.run_on_ui_thread(apply)
        threading.Thread(target=load, daemon=True).start()
        return
    days = kept[1][:7]
    if not days:
        stack.place(style.label("meta", "沒有預報", w=BODY_W, align="c"), 6, 8)
    for i, d in enumerate(days):
        r = View(0, 0, BODY_W, 40)
        r.add(style.label("body", kinds._day(d.get("datetime"), i), x=4, y=10, w=80))
        r.add(ui.IconView("mdi:" + kinds.CONDITIONS.get(d.get("condition"), ("weather-cloudy",))[0], "ink1",
                          x=96, y=7, size=26))
        lo = d.get("templow")
        r.add(style.label("body", ("%s°" % trim_number(lo)) if lo is not None else "", color="ink2", x=BODY_W - 120,
                    y=10, w=50, align="r"))
        r.add(style.label("body", "%s°" % trim_number(d.get("temperature")) if d.get("temperature") is not None else "--",
                                 x=BODY_W - 60, y=10, w=56, align="r"))
        stack.place(r, 0, 2)


def build_camera(card, stack, tile, state):
    """The camera's view, large; a new one each time the card is built."""
    attrs = _attrs(state)
    url = attrs.get("entity_picture") or "/api/camera_proxy/" + tile["entity"]
    url += ("&" if "?" in url else "?") + "_=%d" % (time.time() // 5)
    stack.place(controls.Picture(BODY_W, round(BODY_W * 9 / 16), url, card.api.get_picture, card.run_on_ui_thread,
                                 icon="mdi:cctv", keep=False), 4, 10)
    since = controls.ago((state or {}).get("last_changed"))
    stack.place(style.label("meta", " · ".join(x for x in ((state or {}).get("state") or "", since) if x),
                      w=BODY_W, align="c"), 0, 10)


DETAIL = {"light": build_light, "fan": build_fan, "switch": build_onoff, "input_boolean": build_onoff,
          "lock": build_lock, "climate": build_climate, "cover": build_cover, "media_player": build_media,
          "vacuum": build_vacuum, "weather": build_weather, "camera": build_camera}
