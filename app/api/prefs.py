"""Preferences and the Home Assistant connection settings: what every window draws from, how a change is
validated, saved and broadcast, the panel's picture, the shortcut and the notifications."""

import os
import threading
import time

from app.startup import startup_command, valid_hotkey
from core import alerts, config as cfgmod
from core.ha_client import HAClient
from winsys import hotkey as hotkeymod, qtshell
from winsys.windows import SYSTEM_GLASS_SUPPORTED


class PrefsMixin:
    def _init_prefs(self, cfg):
        self._cfg = cfgmod.load_config() if cfg is None else cfg
        self._tray_icon = None
        # Notifications about locks and safety sensors (off unless chosen), and the shortcut that opens the
        # panel (registered once the tray is up).
        self._alerts = alerts.Alerts(self._notify)
        self._hotkey = None
        self._hotkey_ok = True

    def _prefs(self):
        """The preferences every window draws from."""
        return {
            "theme": self._cfg.get("theme", "auto"),
            "language": self._cfg.get("language", "zh-TW"),
            "glass_style": self._cfg.get("glass_style", "classic"),
            "lock_position": bool(self._cfg.get("lock_position", False)),
            "zoom": self._cfg.get("zoom", 100),
            "glass_mode": self._cfg.get("glass_mode", "fast"),
            "glass_sampling": self._cfg.get("glass_sampling", "live"),
            "glass_rate": str(self._cfg.get("glass_rate", "30")),
            "liquid_blur": int(self._cfg.get("liquid_blur", 0)),
            "system_glass_ok": bool(SYSTEM_GLASS_SUPPORTED),
            "system_glass_active": self._system_glass_status(),
            "panel_theme": self._cfg.get("panel_theme", "follow"),
            "dim_when_idle": bool(self._cfg.get("dim_when_idle", True)),
            "dim_after_sec": int(self._cfg.get("dim_after_sec", 120)),
            "hotkey": self._cfg.get("hotkey", ""),
            "hotkey_ok": bool(self._hotkey_ok),
            "alert_sensors": bool(self._cfg.get("alert_sensors", False)),
            "alert_locks": bool(self._cfg.get("alert_locks", False)),
            # Positions stay on this side; the windows only need what to draw.
            "widgets": [{"id": w["id"], "size": w["size"], "tiles": w["tiles"], "kind": w.get("kind", "tiles"),
                         "font": w.get("font"),
                         "custom": self.custom_prefs(w) if w.get("kind") == "custom" else None}
                        for w in self._cfg.get("widgets", [])],
            "panel": self._cfg.get("panel") or {"mode": "grid", "tiles": None,
                                                 "home_tiles": [], "room_overrides": {}},
        }

    def bootstrap(self):
        # No network I/O here, so the grid renders immediately even when
        # Home Assistant is slow or unreachable; states follow separately
        # (fetch_initial_states) and then over the websocket.
        config = self._prefs()
        config.update({
            "ha_url": self._cfg.get("ha_url", ""),
            "ha_token": self._cfg.get("ha_token", ""),
            "start_on_boot": bool(self._cfg.get("start_on_boot", False)),
            # A widget made while the others are dimmed starts dimmed too.
            "dimmed": bool(self._dimmed),
        })
        return {"config": config, "connected": self._connected}

    # How each preference is validated. Windows send only the keys they
    # changed, so one window's stale copy never overwrites another's edit.
    _PREF_CLEANERS = {
        "theme": lambda v: v if v in ("auto", "light", "dark") else "auto",
        "glass_style": lambda v: v if v in ("classic", "liquid", "windows") else "classic",
        "language": lambda v: v if v in ("zh-TW", "en") else "zh-TW",
        # "follow" uses the widget's theme for the tray panel.
        "panel_theme": lambda v: v if v in ("follow", "auto", "light", "dark") else "follow",
        "lock_position": bool,
        "zoom": lambda v: max(50, min(200, int(v))),
        "glass_mode": lambda v: v if v in ("system", "fast", "compat") else "fast",
        "glass_sampling": lambda v: v if v in ("live", "still") else "live",
        "glass_rate": lambda v: str(v) if str(v) in ("30", "20", "15") else "30",
        "liquid_blur": lambda v: max(0, min(100, int(v))),
        "dim_when_idle": bool,
        "dim_after_sec": lambda v: max(10, min(3600, int(v))),
        "hotkey": lambda v: valid_hotkey(v),
        "alert_sensors": bool,
        "alert_locks": bool,
    }

    def save_prefs(self, changes):
        """Merge `changes` into the config, clean, save and broadcast."""
        if not isinstance(changes, dict):
            return False
        touched = set()
        for key, value in changes.items():
            clean = self._PREF_CLEANERS.get(key)
            if clean is None or value is None:
                continue
            try:
                self._cfg[key] = clean(value)
            except Exception:
                continue
            touched.add(key)
        if "glass_mode" in touched or "glass_style" in touched:
            self._apply_capture_exclusion()
            self._apply_system_glass()
        if "dim_when_idle" in touched and not self._cfg["dim_when_idle"] and self._dimmed:
            self._dimmed = False
            self._push_dim()
        if "hotkey" in touched:
            self._apply_hotkey()
        cfgmod.save_config(self._cfg)
        self._push_prefs()
        return True

    def set_start_on_boot(self, enabled):
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE,
            )
            try:
                if enabled:
                    winreg.SetValueEx(key, "HAWidgets", 0,
                                      winreg.REG_SZ, startup_command())
                else:
                    try:
                        winreg.DeleteValue(key, "HAWidgets")
                    except FileNotFoundError:
                        pass
            finally:
                winreg.CloseKey(key)
            self._cfg["start_on_boot"] = bool(enabled)
            cfgmod.save_config(self._cfg)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _push_prefs(self):
        """Send the current preferences to every window. Any of them can
        change something; each compares before acting, so the window that
        made the change is not disturbed."""
        if not self._all_tiles() and self._flyout_open:
            self.hide_flyout()
        self._broadcast("apply_prefs", self._prefs())

    def _new_client(self):
        """A Home Assistant client to try a connection with (apart from the one the program keeps)."""
        return HAClient()

    def test_connection(self, url, token):
        tmp = self._new_client()
        tmp.configure(url, token)
        ok, detail = tmp.test_connection()
        return {"ok": ok, "detail": detail}

    def save_ha_config(self, url, token):
        self._cfg["ha_url"] = (url or "").rstrip("/")
        self._cfg["ha_token"] = token or ""
        cfgmod.save_config(self._cfg)
        self._client.configure(
            self._cfg["ha_url"], self._cfg["ha_token"], self._cfg.get(
                "poll_fallback_sec", 30),
        )
        return True

    _BG_MAX_SIDE = 1600

    def _panel_bg_path(self):
        """The chosen picture's file, or None."""
        tag = (self._cfg.get("panel") or {}).get("bg_image") or ""
        if not tag:
            return None
        path = os.path.join(os.path.dirname(cfgmod.CONFIG_FILE), "panel_bg.jpg")
        return path if os.path.exists(path) else None

    def choose_panel_background(self):
        """Ask for a picture, keep a reduced copy in the settings folder and
        use it behind the panel (blurred; see nativeui/panel.py make_bg)."""
        source = qtshell.choose_image_file("選擇面板背景圖片")
        if not source:
            return False
        try:
            from PIL import Image
            with Image.open(source) as image:
                image = image.convert("RGB")
                # A phone-sized picture is plenty behind a blur.
                image.thumbnail((self._BG_MAX_SIDE, self._BG_MAX_SIDE))
                folder = os.path.dirname(cfgmod.CONFIG_FILE)
                os.makedirs(folder, exist_ok=True)
                image.save(os.path.join(folder, "panel_bg.jpg"), "JPEG", quality=88)
        except Exception:
            return False
        self._set_panel_bg(str(int(time.time())) + ".jpg")
        return True

    def clear_panel_background(self):
        path = self._panel_bg_path()
        self._set_panel_bg("")
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
        return True

    def _set_panel_bg(self, tag):
        panel = dict(self._cfg.get("panel") or {})
        panel["bg_image"] = tag
        self._cfg["panel"] = cfgmod.clean_panel(panel, self._clean_tiles)
        self._tiles_changed()

    def _apply_hotkey(self):
        """Register the shortcut in the config (or none), and tell Settings whether it took."""
        if self._hotkey is None:
            self._hotkey = hotkeymod.GlobalHotkey(self._hotkey_pressed)
        wanted = self._cfg.get("hotkey", "")
        ok = self._hotkey.set(wanted)
        if not ok:
            qtshell.log("Shortcut %r could not be registered (another program may have it)" % wanted)
        if ok != self._hotkey_ok:
            self._hotkey_ok = ok
            self._push_prefs()

    def _hotkey_pressed(self):
        threading.Thread(target=self.toggle_flyout, args=(True,), daemon=True).start()

    def _notify(self, title, message):
        icon = self._tray_icon
        if icon is None:
            return
        threading.Thread(target=lambda: icon.notify(message, title), daemon=True).start()
