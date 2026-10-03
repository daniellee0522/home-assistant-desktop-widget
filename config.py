"""Config load/save for the HA desktop widget."""

import json
import os
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _config_path():
    """Where the settings live.

    Beside the source when running from a checkout, which keeps a
    development copy self-contained. Installed, that folder belongs to the
    program and may not even be writable, so the settings go where
    Windows keeps per-user application data.
    """
    if getattr(sys, "frozen", False):
        base = os.path.join(
            os.environ.get("APPDATA") or os.path.expanduser("~"), "HA Widgets",
        )
        try:
            os.makedirs(base, exist_ok=True)
        except Exception:
            base = BASE_DIR
        return os.path.join(base, "ha_widgets_config.json")
    return os.path.join(BASE_DIR, "ha_widgets_config.json")


CONFIG_FILE = _config_path()

# Domains we know how to render/control. Anything else configured manually
# still works as a read-only tile (falls back to the generic renderer).
SUPPORTED_DOMAINS = [
    "light", "switch", "climate", "fan", "cover", "media_player",
    "lock", "vacuum", "camera", "scene", "script", "automation",
    "sensor", "binary_sensor", "input_boolean",
]

DEFAULT_CONFIG = {
    "ha_url": "http://homeassistant.local:8123",
    "ha_token": "",
    "theme": "auto",          # light | dark | auto
    "language": "zh-TW",      # zh-TW | en
    "glass_style": "classic",  # classic | liquid | windows
    "columns": 4,
    "window_x": 200,
    "window_y": 200,
    "poll_fallback_sec": 30,  # safety-net poll in case the websocket drops
    "lock_position": False,
    "start_on_boot": False,
    "zoom": 100,              # percent; scales the whole widget via CSS zoom
    # Who draws the frosted glass:
    #   "fast"    - screen capture through Desktop Duplication, refreshed
    #               when the screen behind changes; the widget is hidden
    #               from screenshots and recordings so it does not read
    #               itself back
    #   "compat"  - slower wallpaper rendering; the widget stays visible
    #   "system"  - DWM glass; only offered with HA_WIDGET_SYSTEM_GLASS set
    "glass_mode": "fast",
    # How often a widget's glass looks at the desktop behind it:
    #   "live"  - whenever the picture there changes (video wallpapers move it)
    #   "still" - now and then, and when the widget moves or changes
    "glass_sampling": "live",
    # How blurred the liquid glass is, 0 (the clearest) to 100 (close to the classic frost).
    "liquid_blur": 0,
    # The tray panel's own theme; "follow" uses the widget's.
    "panel_theme": "follow",
    # Dim the widget once the desktop has been covered for dim_after_sec
    # (immediately for a full-screen app) until the desktop returns or the
    # widget is clicked.
    "dim_when_idle": True,
    "dim_after_sec": 120,
    # The shortcut that opens and closes the tray panel from anywhere ("" for none; see hotkey.py).
    "hotkey": "ctrl+alt+h",
    # Notifications when a safety sensor or a lock on a tile changes (see alerts.py).
    "alert_sensors": False,
    "alert_locks": False,
    "fixed_size": False,      # skip auto-fit-to-content; use fixed_width/height
    "fixed_width": 400,
    "fixed_height": 300,
    "tiles": [],              # legacy mirror of the first widget's tiles
    # The desktop widgets: [{id, size, x, y, tiles}]. See WIDGET_SIZES.
    "widgets": [],
    # The tray panel. tiles=None shows every widget's tiles. In "home" mode
    # every device is shown by room; home_tiles are the customised ones
    # (name, icon) and room_overrides maps an entity to a room name that
    # replaces its Home Assistant area.
    "panel": {"mode": "grid", "tiles": None, "home_tiles": [], "room_overrides": {},
              "hidden_rooms": [], "hidden_chips": [], "custom_rooms": [], "room_order": [],
              "bg_image": "", "bg_blur": 28},
}

# Widget sizes, named rows x columns: "2x4" is two rows of four tiles. Every
# side is a whole number of tile cells, so sizes stay proportional.
WIDGET_SIZES = {"1x1": (1, 1), "2x2": (2, 2), "2x4": (4, 2), "4x4": (4, 4)}
DEFAULT_WIDGET_SIZE = "2x4"


def widget_grid(size):
    """(columns, rows) of tile cells for a widget size."""
    return WIDGET_SIZES.get(size) or WIDGET_SIZES[DEFAULT_WIDGET_SIZE]


def new_widget_id():
    return os.urandom(3).hex()


def size_for_count(n):
    """The smallest widget size that holds n tiles (4x4 scrolls beyond)."""
    if n <= 1:
        return "1x1"
    if n <= 4:
        return "2x2"
    if n <= 8:
        return "2x4"
    return "4x4"


def domain_of(entity_id):
    return entity_id.split(".", 1)[0] if entity_id and "." in entity_id else ""


def tile_layout(t):
    """What the Home panel keeps about a device's place: its shape in tile
    cells, whether it was removed, and its order in its room."""
    out = {}
    if "w" in t:
        out["w"] = 2 if t.get("w") == 2 else 1
    if "h" in t:
        out["h"] = 2 if t.get("h") == 2 else 1
    # The shape inside a capsule is its own; the room's shape does not reach it.
    if t.get("cat_w") == 2:
        out["cat_w"] = 2
    if t.get("cat_h") == 2:
        out["cat_h"] = 2
    for axis in ("x", "y"):
        value = t.get(axis)
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 200:
            out[axis] = value
    if t.get("hidden"):
        out["hidden"] = True
    # Left out of its capsule (the lights, the locks...), not out of its room.
    if t.get("cat_hidden"):
        out["cat_hidden"] = True
    if isinstance(t.get("order"), (int, float)) and not isinstance(t.get("order"), bool):
        out["order"] = float(t["order"])
    return out


def _migrate_tile(t):
    """Upgrade tiles saved by the old Tkinter version of this app."""
    entity = t.get("entity", "")
    domain = t.get("domain") or domain_of(entity) or t.get("type", "sensor")
    return {
        "id": t.get("id") or entity or os.urandom(4).hex(),
        "entity": entity,
        "domain": domain,
        "room": t.get("room", ""),
        "label": t.get("label", ""),
        "icon": t.get("icon", ""),
        "on_mode": t.get("on_mode", "cool"),
        "temp_step": t.get("temp_step", 1),
        **tile_layout(t),
    }


def _clean_widget(w, fallback_xy=(200, 200)):
    size = w.get("size")
    try:
        x = int(w.get("x", fallback_xy[0]))
        y = int(w.get("y", fallback_xy[1]))
    except (TypeError, ValueError):
        x, y = fallback_xy
    return {
        "id": str(w.get("id") or new_widget_id()),
        "size": size if size in WIDGET_SIZES else DEFAULT_WIDGET_SIZE,
        "x": x,
        "y": y,
        "tiles": [_migrate_tile(t) for t in (w.get("tiles") or [])],
    }


def sync_legacy(cfg):
    """Mirror the first widget into the old top-level keys, so a downgrade
    to a single-widget build still finds its tiles and position."""
    widgets = cfg.get("widgets") or []
    if widgets:
        cfg["tiles"] = widgets[0]["tiles"]
        cfg["window_x"] = widgets[0]["x"]
        cfg["window_y"] = widgets[0]["y"]


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            cfg.update({k: v for k, v in loaded.items()
                        if k not in ("tiles", "widgets", "panel")})
            cfg["tiles"] = [_migrate_tile(t) for t in loaded.get("tiles", [])]
            _migrate(cfg, loaded)
        except Exception as exc:
            _log("settings could not be read in full: %r" % (exc,))
    _ensure_widgets(cfg)
    return cfg


def _ensure_widgets(cfg):
    """At least one widget always exists."""
    if not cfg.get("widgets"):
        cfg["widgets"] = [_clean_widget({
            "id": "w1",
            "size": (size_for_count(len(cfg["tiles"]))
                     if cfg.get("tiles") else DEFAULT_WIDGET_SIZE),
            "x": cfg.get("window_x", 200),
            "y": cfg.get("window_y", 200),
            "tiles": cfg.get("tiles") or [],
        })]
    sync_legacy(cfg)


def _log(text):
    try:
        with open(os.path.join(BASE_DIR, "widget.log"), "a", encoding="utf-8") as f:
            f.write("config: %s\n" % text)
    except Exception:
        pass


def _migrate(cfg, loaded):
    """Carry an older settings file forward.

    Judged on what the file had, since the defaults have already filled
    in the new keys.
    """
    if "glass_mode" not in loaded:
        # Replaces the old fast_glass/system_glass booleans.
        if loaded.get("system_glass"):
            cfg["glass_mode"] = "system"
        else:
            cfg["glass_mode"] = "fast" if loaded.get("fast_glass", True) else "compat"
    # Settings that no longer exist.
    for key in ("system_glass", "fast_glass", "opacity", "sample_fps"):
        cfg.pop(key, None)
    if loaded.get("widgets"):
        cfg["widgets"] = [
            _clean_widget(w, (200 + 40 * i, 200 + 40 * i))
            for i, w in enumerate(loaded["widgets"]) if isinstance(w, dict)]
    panel = loaded.get("panel")
    if isinstance(panel, dict):
        cfg["panel"] = clean_panel(panel, lambda tiles: [_migrate_tile(t) for t in tiles])
    return cfg


def clean_panel(panel, clean_tiles):
    """The tray panel's settings, whatever shape they arrive in."""
    tiles = panel.get("tiles")
    home_tiles = panel.get("home_tiles")
    overrides = panel.get("room_overrides")
    hidden = panel.get("hidden_rooms")
    custom = panel.get("custom_rooms")
    order = panel.get("room_order")
    chips = panel.get("hidden_chips")
    return {
        "mode": panel.get("mode") if panel.get("mode") in ("grid", "home") else "grid",
        "tiles": clean_tiles(tiles) if isinstance(tiles, list) else None,
        "home_tiles": clean_tiles(home_tiles) if isinstance(home_tiles, list) else [],
        "room_overrides": ({str(k): str(v).strip()[:40] for k, v in overrides.items()
                            if isinstance(k, str) and str(v).strip()}
                           if isinstance(overrides, dict) else {}),
        # Rooms left off the Home view's main screen.
        "hidden_rooms": ([str(r) for r in hidden if isinstance(r, str)]
                         if isinstance(hidden, list) else []),
        # Rooms whose button is left off the row of room buttons. What the
        # main screen shows, what a capsule counts and which buttons there are
        # are three separate choices.
        "hidden_chips": ([str(r) for r in chips if isinstance(r, str)]
                         if isinstance(chips, list) else []),
        # Rooms the user made up; they show where devices have been moved
        # into them.
        "custom_rooms": (list(dict.fromkeys(
            str(r).strip()[:40] for r in custom if isinstance(r, str) and str(r).strip()))[:40]
            if isinstance(custom, list) else []),
        # The order the user put the rooms in; rooms not listed follow.
        "room_order": (list(dict.fromkeys(str(r) for r in order if isinstance(r, str)))
                       if isinstance(order, list) else []),
        # A picture behind the panel (a version tag; the file is in the
        # settings folder), blurred by this many pixels.
        "bg_image": str(panel.get("bg_image") or ""),
        "bg_blur": _int_between(panel.get("bg_blur"), 0, 80, 28),
    }


def _int_between(value, low, high, default):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def save_config(cfg):
    sync_legacy(cfg)
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".ha_widgets_", dir=os.path.dirname(CONFIG_FILE))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, CONFIG_FILE)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
