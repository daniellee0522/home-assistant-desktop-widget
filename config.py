"""Config load/save for the HA desktop widget."""

import json
import os
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "ha_widgets_config.json")

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
    "columns": 4,
    "window_x": 200,
    "window_y": 200,
    "poll_fallback_sec": 30,  # safety-net poll in case the websocket drops
    "lock_position": False,
    "start_on_boot": False,
    "zoom": 100,              # percent; scales the whole widget via CSS zoom
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
        except Exception:
            pass
    return cfg


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".ha_widgets_", dir=BASE_DIR)
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
