"""What a developer writes to make a widget: a definition with its settings, sources, drawing and handlers.

    WIDGET = WidgetDef(
        id="dev.alice.ask", name="Ask", size="2x4",
        config=[Field("endpoint", "text", "https://api.example.com/ask", "Service"),
                Field("api_key", "secret", "", "Key")],
        sources=[],
        draw=draw,                      # draw(p, th, W, H, ctx): paint, and register controls in ctx
        on_tap=on_tap,                  # on_tap(id, ctx)        -> Action(s)
        on_submit=on_submit,            # on_submit(id, text, ctx) after Enter in an input -> Action(s)
        on_drop=on_drop,                # on_drop(id, paths, ctx) when files are dropped on a target
        on_drag=on_drag,                # on_drag(id, move, ctx) while a pointer drags what it pressed (pan, scrub)
        on_scroll=on_scroll,            # on_scroll(id, dy, ctx) for the mouse wheel over the widget (dy > 0: down)
        permissions=("network:api.example.com",))

A handler changes the widget by `ctx.set_state(...)` / `ctx.set_input(...)` and by returning Actions; it never does
the thing itself. The program performs an Action only if the widget declared it in `permissions` and the user
allowed it (widgetkit.permissions). A user's choices are only `config` (a small shareable JSON file); `state` is the
widget's own memory (a timer's start, a chosen photo, the last answer) and is kept between runs.
"""
import json
import re
import threading
from dataclasses import dataclass, field

KIT_VERSION = 1


def text_of(value, lang="en"):
    """Words for a person: a plain string, or {"en": ..., "zh": ...} (the language's own, else "en", else any)."""
    if isinstance(value, dict):
        short = lang.split("-")[0]
        return value.get(lang) or value.get(short) or value.get("en") or next(iter(value.values()), "")
    return value


FIELD_TYPES = ("text", "secret", "number", "bool", "choice", "list", "feeds", "launchers", "images")
MAX_IMAGES = 10               # how many pictures an "images" field takes unless it says another number (`maximum`)
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


@dataclass
class Field:
    key: str
    type: str                       # "text", "secret", "number", "list", "feeds", "launchers", "images", "choice", "bool"
    default: object
    label: object = ""              # words, or {"en": ..., "zh": ...}
    options: tuple = ()             # for "choice"
    minimum: float = None
    maximum: float = None
    step: float = 1
    help: object = ""               # one line under the field in the settings window (words, or per language)
    choices: dict = field(default_factory=dict)   # for "choice": option -> the words shown (default: the option)

    def __post_init__(self):
        """A field that cannot work is refused when it is written, with the reason, not found out in a settings window."""
        if not isinstance(self.key, str) or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", self.key):
            raise ValueError("a field's key is a name like goal or api_key, not %r" % (self.key,))
        if self.type not in FIELD_TYPES:
            raise ValueError("%s: type %r is not one of %s" % (self.key, self.type, ", ".join(FIELD_TYPES)))
        if self.type == "choice":
            if not self.options:
                raise ValueError("%s: a choice needs options" % self.key)
            if self.default not in self.options:
                raise ValueError("%s: its default %r is not one of its options" % (self.key, self.default))
        if self.type == "number":
            if not isinstance(self.default, (int, float)) or isinstance(self.default, bool):
                raise ValueError("%s: a number's default is a number" % self.key)
            if None not in (self.minimum, self.maximum) and self.minimum > self.maximum:
                raise ValueError("%s: minimum is above maximum" % self.key)
        if self.type in ("list", "feeds", "launchers", "images") and not isinstance(self.default, (list, tuple)):
            raise ValueError("%s: the default of a %s is a list" % (self.key, self.type))

    def shown(self, option, lang="en"):
        return text_of(self.choices.get(option, str(option)), lang)

    def clean(self, value):
        """`value` as this field takes it, or its default when it will not do."""
        try:
            if self.type in ("text", "secret"):
                return str(value)
            if self.type == "number":
                v = float(value)
                if self.minimum is not None:
                    v = max(self.minimum, v)
                if self.maximum is not None:
                    v = min(self.maximum, v)
                return int(v) if v == int(v) else v
            if self.type == "bool":
                return bool(value)
            if self.type == "choice":
                return value if value in self.options else self.default
            if self.type in ("list", "feeds", "launchers", "images") and not isinstance(value, (list, tuple)):
                return self.default
            if self.type == "images":                     # picture files the user chose, as many as it takes at most
                room = int(self.maximum) if self.maximum else MAX_IMAGES
                return [str(v).strip() for v in value if str(v).strip()][:room]
            if self.type == "list":
                return [str(v).strip() for v in value if str(v).strip()]
            if self.type == "launchers":                  # buttons: [{"icon": "mdi:camera", "url": "https://..."}]
                return [{"icon": str(v.get("icon") or "mdi:link"), "url": str(v["url"]), "label": str(v.get("label") or "")}
                        for v in value if isinstance(v, dict) and v.get("url")]
            if self.type == "feeds":
                return [v if isinstance(v, dict) and v.get("url") else {"name": str(v), "url": str(v)}
                        for v in value if v]
        except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
            pass
        return self.default


@dataclass
class Action:
    """What a handler asks the program to do. `kind` and `options` are plain data; `widgetkit.runtime` performs it
    when the widget declared the permission it needs and the user allowed it."""
    kind: str
    target: str = ""
    options: dict = field(default_factory=dict)


def open_url(url):
    """Open a web address (http, https, mailto) in the browser. No permission needed."""
    return Action("open_url", url)


def launch(path, *args):
    """Run a program with arguments (no shell). Needs "launch:<program>"."""
    return Action("launch", path, {"args": [str(a) for a in args]})


def copy(text):
    """Put text on the clipboard. Needs "clipboard"."""
    return Action("copy", text)


def open_app(uri):
    """Open a Windows app by its address ("outlookcal:" is the Calendar, "ms-clock:" the Clock). The app must be
    installed. Needs "app:<scheme>" (e.g. "app:outlookcal")."""
    return Action("open_app", uri)


def media(command, seconds=None):
    """Control what this computer is playing: "play_pause", "next", "previous", or "seek" to `seconds`.
    Needs "media"."""
    return Action("media", command, {"seconds": seconds})


def request(url, method="GET", json=None, body=None, headers=None, into="reply", timeout=20):
    """Ask a web service and keep the answer in state[into] = {"ok", "status", "data"} (data is parsed JSON, or text);
    state[into + "_busy"] is True while it is out. Needs "network:<host>"."""
    return Action("request", url, {"method": method, "json": json, "body": body, "headers": headers or {},
                                   "into": into, "timeout": timeout})


def pick_file(into, kind="image"):
    """Open the system's file chooser; the chosen path goes to state[into]. kind: "image" or "any"."""
    return Action("pick_file", "", {"into": into, "kind": kind})


def record_start(into="clip", seconds=60):
    """Start recording the microphone; stop with record_stop. state[into + "_level"] is the live level 0..1 and
    state[into] the saved sound's path once stopped. Needs "microphone"."""
    return Action("record_start", "", {"into": into, "seconds": seconds})


def record_stop(into="clip"):
    return Action("record_stop", "", {"into": into})


@dataclass
class Move:
    """One step of a drag that began on a control with an id. `dx`, `dy`: since the last step; `x`, `y`: the pointer;
    `phase`: "start" (it moved past the little distance that tells a drag from a tap), "move", "end"."""
    phase: str
    x: float
    y: float
    dx: float = 0.0
    dy: float = 0.0
    total_dx: float = 0.0
    total_dy: float = 0.0


@dataclass
class Context:
    config: dict
    data: dict = field(default_factory=dict)
    errors: dict = field(default_factory=dict)
    now: float = 0.0
    pressed: object = None          # the id under a held pointer (fed by the host; draw it pressed)
    hover: object = None            # the id under the pointer
    hits: object = None             # where draw put its controls: a controls.HitMap
    state: dict = field(default_factory=dict)       # the widget's own memory, kept between runs
    inputs: dict = field(default_factory=dict)      # what is typed in each input, by id
    focus: object = None            # the input that has the keyboard
    caret: int = 0
    preedit: str = ""               # text still being composed by an input method
    drag_over: object = None        # the drop target under files being dragged
    drops: list = field(default_factory=list)       # [(rect, id, accepts)] registered by the last draw
    on_change: object = None        # set by the runtime: called when a handler changed something to draw
    size: tuple = (0, 0)            # W, H the widget is being drawn at
    lang: str = "en"                # the language of the program ("en", "zh-TW"): for words the widget draws
    standby: bool = False           # the program is in standby: draw quietly (nothing that moves, nothing that needs
                                    # reading from afar) and expect to be drawn rarely
    pointer: tuple = (0.0, 0.0)     # where the pointer last pressed, released, or moved to: (x, y) in widget px

    def __post_init__(self):
        if self.hits is None:
            from .controls import HitMap
            self.hits = HitMap()
        self._input_ids = set()
        self._lock = threading.RLock()
        self._springs = {}
        self._dt = 0.0
        self._animating = False
        self._redraw_in = None

    def spring(self, key, target, response=0.35, damping=1.0):
        """A number that eases to `target` and keeps moving from where it is if the target changes (an interruptible
        spring, see widgetkit.motion). Ask for it while drawing; the widget is redrawn every frame until it rests."""
        from .motion import Spring
        s = self._springs.get(key)
        if s is None:
            s = self._springs[key] = Spring(target, response, damping)
        s.target = float(target)
        s.response, s.damping = response, damping
        if self._dt > 0:
            s.step(self._dt)
        if not s.at_rest:
            self._animating = True
        return s.value

    def redraw_in(self, seconds):
        """Ask to be drawn again after `seconds` (the soonest of the asks of one drawing counts): a slideshow's next picture,
        the next frame of an animated one. For something that moves all the time use `tick`; for something that eases use
        `spring`. In standby the program draws no sooner than its standby pace, whatever is asked."""
        seconds = max(0.0, float(seconds))
        self._redraw_in = seconds if self._redraw_in is None else min(self._redraw_in, seconds)

    # --- for draw
    def text_input(self, id):
        """Register an input and return what to draw it with: controls.search_bar(..., **ctx.text_input("ask"))."""
        self._input_ids.add(id)
        focused = self.focus == id
        return {"value": self.inputs.get(id, ""), "focused": focused, "caret": self.caret if focused else 0,
                "preedit": self.preedit if focused else ""}

    def drop_target(self, id, rect, accepts=("image",)):
        """Register a place files may be dropped; True while files are being dragged over it."""
        self.drops.append((rect, id, tuple(accepts)))
        return self.drag_over == id

    def is_input(self, id):
        return id in self._input_ids

    # --- for handlers
    def set_state(self, **values):
        with self._lock:
            self.state.update(values)
        self._changed()

    def snapshot_state(self):
        """A copy of the state that is safe to take from another thread while a handler is changing it."""
        with self._lock:
            return dict(self.state)

    def set_input(self, id, text):
        self.inputs[id] = text
        if self.focus == id:
            self.caret = len(text)
        self._changed()

    def size_name(self):
        """Which of the program's sizes this is ("1x1", "2x2", "2x4", "4x4"): the one whose shape is nearest to the size
        being drawn. For choosing a layout; the exact room is `ctx.size`."""
        from nativeui import render
        w, h = self.size
        return min(render.SIZES, key=lambda n: abs(render.widget_size(n)[0] - w) + abs(render.widget_size(n)[1] - h))

    def _changed(self):
        if self.on_change:
            self.on_change()


@dataclass
class WidgetDef:
    id: str
    name: object                    # words, or {"en": ..., "zh": ...}
    size: str
    config: list
    sources: list
    draw: object
    version: str = "1.0"
    on_tap: object = None           # on_tap(id, ctx) -> Action / [Action] / None
    on_submit: object = None        # on_submit(id, text, ctx) -> Action / [Action] / None
    on_drop: object = None          # on_drop(id, paths, ctx) -> Action / [Action] / None
    on_drag: object = None          # on_drag(id, move, ctx) -> Action / [Action] / None; move: Move
    on_scroll: object = None        # on_scroll(id, dy, ctx) -> Action / [Action] / None; dy in px, > 0 scrolls down
    on_context: object = None       # on_context(id, ctx) -> Action / [Action] / None; a right click (id: what is under it, or None).
                                    # A widget that has one keeps the right click; the program's own use of it (opening the
                                    # editor) is then left to its menu
    sizes: tuple = ()               # other sizes it can be besides `size`: "1x1", "2x2", "2x4", "4x4"
    permissions: tuple = ()         # "network:host", "launch:program", "clipboard", "microphone"
    tick: float = None              # seconds between redraws of something that moves (a clock, a timer); None: still
    background: str = "solid"       # "solid" (the default): awake, the program paints an opaque face over the whole card under
                                    # the widget (white, or near black in the dark) and need not capture the desktop for it;
                                    # in standby it is clear glass again. "glass": the widget draws on the program's
                                    # transparent card and gets its glass for free, awake too
    standby_tick: float = None      # the same while the program is in standby (the desktop is out of sight or dimmed):
                                    # None = once a minute for a widget that ticks; 0 = not at all; or seconds
    state: dict = field(default_factory=dict)       # the widget's state before it has any of its own

    def __post_init__(self):
        """What cannot work is refused here: an id that is not a name, two fields with one key, a permission the kit does
        not know, and sizes other than the program's four."""
        from nativeui import render
        from . import permissions
        if not isinstance(self.id, str) or not ID_RE.match(self.id):
            raise ValueError("a widget's id is a name like dev.alice.ask (letters, digits . _ -), not %r" % (self.id,))
        keys = [f.key for f in self.config]
        if len(set(keys)) != len(keys):
            raise ValueError("%s: two settings share a key: %s" % (self.id, ", ".join(k for k in keys if keys.count(k) > 1)))
        if not callable(self.draw):
            raise ValueError("%s: draw must be a function draw(p, th, W, H, ctx)" % self.id)
        if self.tick is not None and not (isinstance(self.tick, (int, float)) and self.tick > 0):
            raise ValueError("%s: tick is a number of seconds above zero, or None" % self.id)
        if self.background not in ("glass", "solid"):
            raise ValueError("%s: background is \"glass\" or \"solid\", not %r" % (self.id, self.background))
        if self.standby_tick is not None and not (isinstance(self.standby_tick, (int, float)) and self.standby_tick >= 0):
            raise ValueError("%s: standby_tick is seconds (0 for never), or None" % self.id)
        self.permissions = permissions.validate(tuple(self.permissions))
        for size in self.supported_sizes():
            if size not in render.SIZES:
                raise ValueError("%s: %r is not a widget size; the sizes are %s"
                                 % (self.id, size, ", ".join(render.SIZES)))

    def needs_glass(self, standby=False):
        """Does the program have to give this widget its glass (a capture of the desktop behind it)? Yes unless it paints a
        solid face; and in standby, always: the standby look is clear glass."""
        return self.background != "solid" or bool(standby)

    def standby_interval(self):
        """Seconds between redraws in standby, or None for none: `standby_tick` if the developer set it (0 means none),
        else once a minute for a widget that ticks (never faster than it ticks) and none for one that does not."""
        if self.standby_tick is not None:
            return self.standby_tick or None
        return max(60.0, float(self.tick)) if self.tick else None

    def supported_sizes(self):
        """Every size this widget says it can be: its own `size` first."""
        return (self.size,) + tuple(s for s in self.sizes if s != self.size)

    def settings(self, user=None):
        """The settings in force: the user's, cleaned, over the defaults."""
        user = user or {}
        return {f.key: f.clean(user[f.key]) if f.key in user else f.default for f in self.config}

    def export_config(self, user=None):
        """The user's choices as shareable JSON text. Secrets (a key, a password) are never in it."""
        values = self.settings(user)
        for f in self.config:
            if f.type == "secret":
                values.pop(f.key, None)
        return json.dumps({"widget": self.id, "version": self.version, "config": values}, ensure_ascii=False, indent=2)

    def import_config(self, text):
        """Settings from a shared file; refused if it is for another widget."""
        doc = json.loads(text)
        if doc.get("widget") != self.id:
            raise ValueError("this settings file is for %r, not %r" % (doc.get("widget"), self.id))
        return self.settings(doc.get("config"))

    def tap(self, ctx, x, y):
        """The result of a press at (x, y) of the last drawing recorded in `ctx.hits`, or None."""
        hit = ctx.hits.at(x, y)
        return self.on_tap(hit, ctx) if self.on_tap and hit is not None else None
