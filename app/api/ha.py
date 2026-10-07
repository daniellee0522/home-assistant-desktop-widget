"""Home Assistant as the windows see it: states in, pushed to the windows that show them; entities, the
Home view's registry, history, forecasts, pictures and service calls."""

import datetime
import threading
import time

from core import config as cfgmod, home, local_media
from core.ha_client import HAClient
from winsys import qtshell


class HomeAssistantMixin:
    def _init_ha(self, client, start):
        self._connected = False
        self._ui_ready = False
        self._pending = []
        self._pending_lock = threading.Lock()
        self._registry_cache = None
        # The latest state of every entity a tile shows, kept by the websocket's pushes, so a window made later
        # (the panel, the card) starts from it rather than reading every state again.
        self._known_states = {}
        self._known_read_at = -60.0
        self._states_lock = threading.Lock()
        self._home_states = {}
        self._forecasts = {}
        # What this computer plays, for a player widget that shows it (read only while one does).
        self._local_media = (local_media.LocalMedia(lambda e, s: self._on_ha_events([[e, s]]))
                             if local_media.AVAILABLE else None)
        if self._local_media is None:
            qtshell.log("This computer's player is not available (WinRT media sessions could not be loaded)")
        self._client = client or HAClient(on_event=self._on_ha_event, on_status=self._on_ha_status)
        if start:
            self._client.configure(
                self._cfg.get("ha_url", ""), self._cfg.get("ha_token", ""),
                self._cfg.get("poll_fallback_sec", 30),
            )
            self._client.set_entities(self._watched_entities())
            self._client.start()

    def ui_ready(self, kind=None):
        self._ui_ready = True
        with self._pending_lock:
            pending, self._pending = self._pending, []
        if pending:
            self._push_batch(pending)
        return True

    def fetch_initial_states(self):
        entities = self._watched_entities()
        if not (self._cfg.get("ha_token") and entities):
            return {}
        # One read at a time: the widgets all ask at start, and the first answers the rest.
        with self._states_lock:
            known = self._known_states
            # Trusted while the websocket keeps it, or for a moment after it was read (before the
            # websocket is up, as at start).
            fresh = self._connected or time.monotonic() - self._known_read_at < 10.0
            if not (fresh and all(e in known for e in entities)):
                try:
                    by_id = {s.get("entity_id"): s for s in self._client.get_states()}
                    self._known_read_at = time.monotonic()
                except Exception:
                    by_id = {}
                for entity in entities:
                    if entity in by_id:
                        known[entity] = by_id[entity]
            return {e: known[e] for e in entities if e in known}

    def get_entities(self):
        try:
            states = self._client.get_states()
        except Exception:
            return []
        out = []
        for s in states:
            eid = s.get("entity_id", "")
            domain = cfgmod.domain_of(eid)
            if domain not in cfgmod.SUPPORTED_DOMAINS:
                continue
            out.append({
                "entity_id": eid,
                "domain": domain,
                "name": (s.get("attributes") or {}).get("friendly_name") or eid,
                "state": s,
            })
        out.sort(key=lambda e: (e["domain"], e["name"]))
        if self._local_media is not None:
            out.insert(0, {"entity_id": local_media.ENTITY, "domain": "local_media", "name": local_media.NAME,
                           "state": self._known_states.get(local_media.ENTITY) or {"state": "off"}})
        return out

    _REGISTRY_TTL_S = 300

    def _registry(self):
        """Areas, devices and entity registry, cached: they rarely change and
        cost three websocket round trips."""
        cached = self._registry_cache
        if cached and time.monotonic() - cached[0] < self._REGISTRY_TTL_S:
            return cached[1]
        try:
            data = self._client.get_registry()
        except Exception:
            return cached[1] if cached else ([], [], [])
        self._registry_cache = (time.monotonic(), data)
        return data

    def get_home(self):
        """Every device by room, with its current state, for the panel's
        Home view. Also what the panel listens for while it is open."""
        try:
            states = self._client.get_states()
        except Exception:
            return {"rooms": [], "entities": [], "error": True}
        areas, devices, registry = self._registry()
        panel = self._cfg.get("panel") or {}
        entities, sensors, rooms = home.build_home(
            states, areas, devices, registry, panel.get("room_overrides") or {},
            set(panel.get("deleted_rooms") or ()))
        self._home_states = {e["entity_id"]: e["state"] for e in (*entities, *sensors)}
        self._sync_client_entities()
        return {"rooms": rooms, "entities": entities, "sensors": sensors}

    def _home_mode(self):
        return (self._cfg.get("panel") or {}).get("mode") == "home"

    def _sync_client_entities(self):
        """What the websocket client reports: the tiles' devices, and while
        the Home panel is open, every device it shows."""
        ids = self._watched_entities()
        if self._flyout_open and self._home_mode():
            ids = ids + list(self._home_states)
        self._client.set_entities(ids)
        self._sync_local_media()
        # A device just added says nothing until it changes (a room's temperature, for hours): its state
        # now is read once and given to the windows.
        unknown = [e for e in self._watched_entities()
                   if e not in self._known_states and not e.startswith("local_media.")]
        if unknown and self._cfg.get("ha_token"):
            threading.Thread(target=self._read_new_states, args=(unknown,), daemon=True).start()

    def _sync_local_media(self):
        """This computer's player is read while a widget shows it, slowly while the widgets are dimmed."""
        if self._local_media is not None:
            self._local_media.set_active(local_media.ENTITY in self._watched_entities(), slow=bool(self._dimmed))

    def get_media_sources(self):
        """What a player widget can show: this computer, then Home Assistant's players. [{entity_id, name}]."""
        out = [{"entity_id": local_media.ENTITY, "name": local_media.NAME}] if self._local_media else []
        try:
            states = self._client.get_states() if self._cfg.get("ha_token") else []
        except Exception:
            states = []
        for s in sorted(states, key=lambda s: s.get("entity_id", "")):
            eid = s.get("entity_id", "")
            if cfgmod.domain_of(eid) == "media_player":
                out.append({"entity_id": eid, "name": (s.get("attributes") or {}).get("friendly_name") or eid})
        return out

    def _read_new_states(self, entities):
        try:
            by_id = {s.get("entity_id"): s for s in self._client.get_states()}
        except Exception:
            return
        items = [[e, by_id[e]] for e in entities if e in by_id]
        if items:
            self._on_ha_events(items)

    def get_history(self, entity_id, hours=24):
        """Recent numeric values for a sensor as [[epoch seconds, value]].

        Non-numeric samples are dropped so an `unavailable` stretch leaves a
        gap instead of a dive to zero.
        """
        try:
            raw = self._client.get_history(entity_id, hours=hours)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        points = []
        for row in raw or []:
            try:
                value = float(row.get("state"))
            except (TypeError, ValueError):
                continue
            stamp = row.get("last_changed") or row.get("last_updated") or ""
            try:
                text = stamp.replace("Z", "+00:00")
                when = datetime.datetime.fromisoformat(text).timestamp()
            except Exception:
                continue
            points.append([when, value])
        points.sort(key=lambda p: p[0])
        # The chart is a couple of hundred pixels wide; thin the series.
        limit = 240
        if len(points) > limit:
            step = len(points) / float(limit)
            points = [points[min(len(points) - 1, int(i * step))]
                      for i in range(limit)]
        return {"ok": True, "points": points, "hours": hours}

    _FORECAST_TTL_S = 1200

    def get_forecast(self, entity_id):
        """A weather entity's coming days (kept for 20 minutes), or []."""
        cache = self._forecasts
        got = cache.get(entity_id)
        if got and time.monotonic() - got[0] < self._FORECAST_TTL_S:
            return got[1]
        try:
            days = self._client.get_forecast(entity_id)
        except Exception:
            return got[1] if got else []
        cache[entity_id] = (time.monotonic(), days)
        return days

    def get_picture(self, path):
        """The bytes of a picture from Home Assistant (a song's cover, a camera's view), or None."""
        if not path:
            return None
        if path.startswith("local:"):
            return self._local_media.get_art(path) if self._local_media else None
        try:
            return self._client.get_bytes(path)
        except Exception:
            return None

    def call_service(self, domain, service, entity_id, extra):
        if entity_id.startswith("local_media."):          # this computer's player
            ok = bool(self._local_media and self._local_media.control(service, extra))
            return {"ok": ok}
        try:
            self._client.call_service(domain, service, entity_id, extra or {})
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _push_batch(self, items):
        # Hidden windows keep their states too, ready for their next opening.
        self._broadcast("push_states", items)

    def _on_ha_event(self, entity_id, new_state):
        self._on_ha_events([[entity_id, new_state]])

    def _on_ha_events(self, items):
        """New states, [[entity_id, state], ...], to the windows that show them, in one push each."""
        sensors, locks = self._cfg.get("alert_sensors"), self._cfg.get("alert_locks")
        watched = set(self._watched_entities())
        for entity_id, new_state in items:
            if (sensors or locks) and entity_id in watched:
                try:
                    self._alerts.check(entity_id, self._known_states.get(entity_id), new_state,
                                       bool(sensors), bool(locks), self._cfg.get("language", "zh-TW"))
                except Exception:
                    pass
            self._known_states[entity_id] = new_state
        if not self._ui_ready or not (self._widgets or self._window):
            with self._pending_lock:
                self._pending.extend(items)
                if len(self._pending) > 500:
                    self._pending = self._pending[-500:]
            return
        on_tiles, home_only = [], []
        for entity_id, new_state in items:
            if entity_id in self._home_states:
                self._home_states[entity_id] = new_state
            (on_tiles if entity_id in watched else home_only).append([entity_id, new_state])
        if home_only:
            # Only the Home panel (and a card opened from it) shows these.
            self._broadcast("push_states", home_only,
                            windows=(self._flyout_window, self._popover_window))
        if on_tiles:
            self._push_batch(on_tiles)

    def _on_ha_status(self, connected, detail=""):
        reconnected = connected and not self._connected
        self._connected = connected
        if self._ui_ready:
            self._broadcast("set_connected", bool(connected))
        if reconnected:
            self._refresh_now()

    def _refresh_now(self):
        def go():
            wanted = set(self._watched_entities())
            try:
                if not self._cfg.get("ha_token"):
                    raise RuntimeError("not configured")
                states = {s["entity_id"]: s for s in self._client.get_states()}
            except Exception as exc:
                states = {}
                self._on_ha_status(False, str(exc))
            # One push for all of them: per entity, every window would redraw once for each.
            self._on_ha_events([[entity, states.get(entity) or {
                "entity_id": entity, "state": "unavailable", "attributes": {},
            }] for entity in wanted])
        threading.Thread(target=go, daemon=True).start()
