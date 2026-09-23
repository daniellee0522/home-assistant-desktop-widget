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
    "lock", "vacuum", "scene", "script", "automation",
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
    #   "fast"    - screen capture; the widget is hidden from screenshots
    #               and recordings so it does not read itself back
    #   "compat"  - slower wallpaper rendering; the widget stays visible
    #   "system"  - DWM glass; only offered with HA_WIDGET_SYSTEM_GLASS set
    "glass_mode": "fast",
    # Ceiling on how often the backdrop is re-captured, in frames per
    # second. Still wallpaper backs off on its own (see app.js).
    "sample_fps": 16,
    # The tray panel's own theme; "follow" uses the widget's.
    "panel_theme": "follow",
    # Dim the widget once the desktop has been covered for dim_after_sec
    # (immediately for a full-screen app) until the desktop returns or the
    # widget is clicked.
    "dim_when_idle": True,
    "dim_after_sec": 120,
    "fixed_size": False,      # skip auto-fit-to-content; use fixed_width/height
    "fixed_width": 400,
    "fixed_height": 300,
    "tiles": [],
}


def domain_of(entity_id):
    return entity_id.split(".", 1)[0] if entity_id and "." in entity_id else ""


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
    }


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            cfg.update({k: v for k, v in loaded.items() if k != "tiles"})
            cfg["tiles"] = [_migrate_tile(t) for t in loaded.get("tiles", [])]
            _migrate(cfg, loaded)
        except Exception:
            pass
    return cfg


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
    for key in ("system_glass", "fast_glass", "opacity"):
        cfg.pop(key, None)
    return cfg


def save_config(cfg):
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
