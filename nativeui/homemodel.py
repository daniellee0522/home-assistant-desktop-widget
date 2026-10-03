"""The Home-style panel's rules, with no window: which devices are shown, in which room and order, what
the capsules say, and where tiles stand on a room's grid."""
import math

HOME_COLS = 4
HOME_PREFIX = "home:"
OTHER_ROOM = "\u0000other"             # uncategorised: the devices with no room, or whose room was deleted

CATEGORIES = [
    {"id": "env", "title": "環境", "icon": "thermometer", "tint": "cyan"},
    {"id": "light", "title": "燈光", "icon": "light", "tint": "yellow", "domains": ["light"]},
    {"id": "security", "title": "保全系統", "icon": "lock", "tint": "teal", "domains": ["lock", "camera"]},
    {"id": "media", "title": "媒體音訊", "icon": "media", "tint": "green", "domains": ["media_player"]},
]


# ---------------------------------------------------------------------------------- the grid

def home_layout(items, pin=None):
    """Places a room's tiles on its grid, four cells wide. Tiles that have a place keep it; tiles with no
    place yet take the first free one, in their order. `pin` is a tile held at a place (the one being
    moved or resized), which the others make way for: those it lands on are shoved on along `pin['dir']`
    (the way its movement pushes them: dragged left, they go right) and push what is in their way in
    turn; where that runs out of room they go down. Then what has nothing above it moves up.
    Returns {id: {x, y, w, h}}.

    items: [{id, w, h, order, x?, y?}]"""
    def placed(i):
        return isinstance(i.get("x"), int) and isinstance(i.get("y"), int)

    def clamp_x(x, w):
        return max(0, min(x, HOME_COLS - w))

    def overlap(a, b):
        return a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]

    rest = [i for i in items if not pin or i["id"] != pin["id"]]
    rects = []

    def taken(x, y, w, h):
        return any(overlap({"x": x, "y": y, "w": w, "h": h}, r) for r in rects)

    for it in sorted([i for i in rest if placed(i)], key=lambda i: (i["y"], i["x"])):
        rects.append({"id": it["id"], "x": clamp_x(it["x"], it["w"]), "y": max(0, it["y"]), "w": it["w"],
                      "h": it["h"], "order": it.get("order", 0)})
    for it in sorted([i for i in rest if not placed(i)], key=lambda i: i.get("order", 0)):
        done = False
        y = 0
        while not done:
            for x in range(0, HOME_COLS - it["w"] + 1):
                if not taken(x, y, it["w"], it["h"]):
                    rects.append({"id": it["id"], "x": x, "y": y, "w": it["w"], "h": it["h"], "order": it.get("order", 0)})
                    done = True
                    break
            y += 1

    pin_rect = None
    if pin:
        pin_rect = {"id": pin["id"], "x": clamp_x(pin["x"], pin["w"]), "y": max(0, pin["y"]), "w": pin["w"], "h": pin["h"]}
        d = pin.get("dir") or {"x": 0, "y": 1}
        settled = {pin["id"]}
        queue = [pin_rect]
        guard = 0
        while queue and guard < 300:
            guard += 1
            by = queue.pop(0)
            hit = [o for o in rects if o["id"] not in settled and overlap(o, by)]
            if d["x"]:
                hit.sort(key=lambda o: o["x"] * d["x"])
            else:
                hit.sort(key=lambda o: o["y"] * d["y"])
            for o in hit:
                if d["x"]:
                    nx = by["x"] + by["w"] if d["x"] > 0 else by["x"] - o["w"]
                    if nx < 0 or nx + o["w"] > HOME_COLS:
                        o["y"] = by["y"] + by["h"]                  # no room that way
                    else:
                        o["x"] = nx
                else:
                    ny = by["y"] + by["h"] if d["y"] > 0 else by["y"] - o["h"]
                    o["y"] = by["y"] + by["h"] if ny < 0 else ny
                settled.add(o["id"])
                queue.append(o)

    # Overlaps that are left (two shoved onto one place) go down in turn, and anything with room
    # above it moves up. The held tile stays where it is.
    final = [pin_rect] if pin_rect else []

    def free(x, y, w, h):
        return x >= 0 and y >= 0 and x + w <= HOME_COLS and not any(overlap({"x": x, "y": y, "w": w, "h": h}, r) for r in final)

    for o in sorted(rects, key=lambda o: (o["y"], o["x"], o["order"])):
        y = o["y"]
        while y > 0 and free(o["x"], y - 1, o["w"], o["h"]):
            y -= 1
        while not free(o["x"], y, o["w"], o["h"]):
            y += 1
        final.append({"id": o["id"], "x": o["x"], "y": y, "w": o["w"], "h": o["h"]})
    return {r["id"]: r for r in final}


# ---------------------------------------------------------------------------------- the model

def range_text(values, digits, unit):
    if not values:
        return ""
    lo, hi = min(values), max(values)

    def f(n):
        return ("%." + str(digits) + "f") % n
    return (f(lo) if f(lo) == f(hi) else f(lo) + "–" + f(hi)) + unit


def is_unlocked(state):
    s = (state or {}).get("state")
    return bool(s) and s not in ("locked", "locking", "unavailable", "unknown")


class HomeModel:
    """The panel's data (from Api.get_home), the panel's settings (cfg['panel']) and the states."""

    def __init__(self):
        self.entities, self.sensors, self.rooms = [], [], []
        self.panel = {"mode": "home", "tiles": None, "home_tiles": []}
        self.states = {}
        self.room = ""                      # the room being looked at; '' = all
        self.editing = False                # the rooms are being edited
        self.cat_editing = False            # the open capsule is being edited
        self.sheet = False                  # the add sheet is open
        self.category = None                # the capsule that is open
        self.adding_room = False

    def reset(self):
        """Back to the start when the panel closes."""
        self.category = None
        self.editing = self.cat_editing = self.sheet = self.adding_room = False
        self.room = ""

    # -- settings ---------------------------------------------------------------------------------
    def hidden_rooms(self):
        """The rooms off the main screen. Uncategorised is one unless it was chosen (show_other)."""
        out = set(self.panel.get("hidden_rooms") or [])
        if not self.panel.get("show_other"):
            out.add(OTHER_ROOM)
        return out

    def hidden_chips(self):
        return set(self.panel.get("hidden_chips") or [])

    def record(self, entity_id):
        rid = HOME_PREFIX + entity_id
        for t in self.panel.get("home_tiles") or []:
            if t.get("id") == rid:
                return t
        return None

    def tile_from_id(self, tile_id):
        entity = tile_id[len(HOME_PREFIX):]
        found = self.entity_by_id(entity)
        st = self.states.get(entity)
        return {"id": tile_id, "entity": entity, "domain": found["domain"] if found else entity.split(".")[0],
                "room": (found and found.get("name")) or ((st or {}).get("attributes") or {}).get("friendly_name") or entity,
                "label": "", "icon": "", "on_mode": "cool", "temp_step": 1}

    def ensure_record(self, entity_id):
        if not isinstance(self.panel.get("home_tiles"), list):
            self.panel["home_tiles"] = []
        rec = self.record(entity_id)
        if rec is None:
            rec = self.tile_from_id(HOME_PREFIX + entity_id)
            self.panel["home_tiles"].append(rec)
        return rec

    def tile_for(self, entity):
        return self.record(entity["entity_id"]) or self.tile_from_id(HOME_PREFIX + entity["entity_id"])

    def entity_by_id(self, entity_id):
        for e in self.entities:
            if e["entity_id"] == entity_id:
                return e
        for e in self.sensors:
            if e["entity_id"] == entity_id:
                return e
        return None

    @staticmethod
    def span(rec):
        w = 2 if rec and rec.get("w") == 2 else 1
        h = 2 if rec and rec.get("h") == 2 and w == 2 else 1
        return w, h

    @staticmethod
    def cat_span(rec):
        """A capsule screen's own size for a tile; the rooms' sizes (w, h) do not reach it."""
        w = 2 if rec and rec.get("cat_w") == 2 else 1
        h = 2 if rec and rec.get("cat_h") == 2 and w == 2 else 1
        return w, h

    @staticmethod
    def form(span):
        return "big" if span[1] == 2 else "bar" if span[0] == 2 else "small"

    # -- what is shown ----------------------------------------------------------------------------------
    @staticmethod
    def room_key(area):
        return area or OTHER_ROOM

    @staticmethod
    def room_label(key):
        return "未分類" if key == OTHER_ROOM else key

    def visible(self, e):
        rec = self.record(e["entity_id"])
        key = self.room_key(e.get("area"))
        return not (rec and rec.get("hidden")) and (self.room == key or key not in self.hidden_rooms())

    def ordered(self, entities):
        index = {e["entity_id"]: i for i, e in enumerate(entities)}

        def key(e):
            rec = self.record(e["entity_id"])
            return rec["order"] if rec and isinstance(rec.get("order"), (int, float)) else 1000 + index[e["entity_id"]]
        return sorted(entities, key=key)

    def room_names(self):
        base = sorted(self.rooms, key=lambda s: s.lower() if False else s)
        for r in self.panel.get("custom_rooms") or []:
            if r not in base:
                base.append(r)
        chosen = [r for r in (self.panel.get("room_order") or []) if r in base]
        names = chosen + [r for r in base if r not in chosen]
        if any(not e.get("area") for e in self.entities):
            names.append(OTHER_ROOM)
        return names

    def room_sort_key(self, key):
        names = self.room_names()
        if key == OTHER_ROOM:
            return 1e9
        return 1e6 if key not in names else names.index(key)

    def groups(self):
        """[(room, devices)] for what the main screen shows. While editing, a room with nothing in it is
        shown too, as somewhere to drop a device, and one that is off the main screen is there to be put back."""
        groups = {}
        stubs = set()
        for e in self.entities:
            if not self.visible(e):
                continue
            key = self.room_key(e.get("area"))
            if self.room and self.room != key:
                continue
            groups.setdefault(key, [])
            groups[key].append(e)
        if self.editing:
            hidden = self.hidden_rooms()
            for key in self.room_names():
                if self.room and self.room != key:
                    continue
                groups.setdefault(key, [])
                if key in hidden and not self.room:
                    stubs.add(key)
        out = []
        for key in sorted(groups, key=self.room_sort_key):
            out.append((key, self.ordered(groups[key]), key in stubs))
        return out

    def items(self, entities):
        """A room's devices as layout items."""
        out = []
        for index, e in enumerate(self.ordered(entities)):
            rec = self.record(e["entity_id"])
            w, h = self.span(rec)
            out.append({"id": e["entity_id"], "w": w, "h": h, "order": index,
                        "x": rec.get("x") if rec and isinstance(rec.get("x"), int) else None,
                        "y": rec.get("y") if rec and isinstance(rec.get("y"), int) else None})
        return out

    def save_layout(self, layout):
        for r in layout.values():
            rec = self.ensure_record(r["id"])
            rec["x"], rec["y"], rec["w"], rec["h"] = r["x"], r["y"], r["w"], r["h"]

    def room_layout(self, room, skip=None, pin=None):
        entities = [x for x in self.entities if self.visible(x) and self.room_key(x.get("area")) == room
                    and x["entity_id"] != skip]
        return home_layout(self.items(entities), pin)

    # -- readings, capsules -----------------------------------------------------------------------------------
    def readings(self, sensors):
        out = {"temperature": [], "humidity": []}
        for s in sensors:
            st = self.states.get(s["entity_id"])
            try:
                v = float(st["state"]) if st else math.nan
            except (TypeError, ValueError):
                v = math.nan
            if not math.isnan(v):
                out[s["kind"]].append(v)
        return out

    def readings_text(self, sensors):
        r = self.readings(sensors)
        return " · ".join(t for t in (range_text(r["temperature"], 1, "°"), range_text(r["humidity"], 0, "%")) if t)

    def sensor_visible(self, s):
        rec = self.record(s["entity_id"])
        return not (rec and rec.get("hidden"))

    def sensors_in(self, key=None):
        return [s for s in self.sensors if self.sensor_visible(s) and (key is None or self.room_key(s.get("area")) == key)]

    def category_all(self, cat):
        return self.sensors if cat["id"] == "env" else [e for e in self.entities if e["domain"] in cat["domains"]]

    def category_chosen(self, e):
        r = self.record(e["entity_id"])
        return not (r and r.get("cat_hidden"))

    def category_members(self, cat):
        def in_room(e):
            return not self.room or self.room_key(e.get("area")) == self.room
        return [e for e in self.category_all(cat) if self.category_chosen(e) and in_room(e)]

    def category_pill(self, cat, members):
        def count(test):
            return sum(1 for e in members if self.states.get(e["entity_id"]) and test(self.states[e["entity_id"]]))
        if cat["id"] == "env":
            return {"sub": self.readings_text(members) or "無資料", "tint": cat["tint"]}
        if cat["id"] == "light":
            n = count(lambda s: s.get("state") == "on")
            return {"sub": ("%d 個開著" % n) if n else "全部關閉", "tint": cat["tint"]}
        if cat["id"] == "security":
            locks = [e for e in members if e["domain"] == "lock"]
            open_ = sum(1 for e in locks if is_unlocked(self.states.get(e["entity_id"])))
            if open_:
                return {"sub": "%d 個未鎖上" % open_, "tint": "teal", "icon": "lock-open"}
            return {"sub": "全部已鎖上" if locks else "%d 台攝影機" % len(members), "tint": cat["tint"]}
        playing = count(lambda s: s.get("state") == "playing")
        return {"sub": ("%d 個播放中" % playing) if playing else "閒置", "tint": cat["tint"]}

    def visible_categories(self):
        """[(cat, members, pill)] of the capsules that are shown."""
        out = []
        for cat in CATEGORIES:
            members = self.category_members(cat)
            if not members and not (self.category == cat["id"] and self.cat_editing):
                continue
            out.append((cat, members, self.category_pill(cat, members)))
        return out
