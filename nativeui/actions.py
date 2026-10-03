"""What a tap on a tile does , shared by the widgets and the tray panel.

The guess is shown at once (`optimistic`), the service call goes out on its own thread, and the answer
arrives as the state's own push.
"""
import threading
import traceback


class TileActions:
    def __init__(self, api, states, optimistic):
        """states: a callable giving the dict of states; optimistic(entity, patch) shows a guess."""
        self.api, self.states, self.optimistic = api, states, optimistic

    def call(self, domain, service, entity, extra=None):
        def go():
            try:
                self.api.call_service(domain, service, entity, extra or {})
            except Exception:
                traceback.print_exc()
        threading.Thread(target=go, daemon=True).start()

    def quick_action(self, tile, flash=None):
        """Returns True when the tile did something that wants a flash."""
        domain, entity = tile["domain"], tile["entity"]
        st = self.states().get(entity)
        if domain in ("light", "switch", "fan", "input_boolean"):
            if st:
                self.optimistic(entity, {"state": "off" if st.get("state") == "on" else "on"})
            self.call(domain, "toggle", entity)
        elif domain == "climate":
            on = bool(st) and st.get("state") != "off"
            mode = "off" if on else (tile.get("on_mode") or "cool")
            if st:
                self.optimistic(entity, {"state": mode})
            self.call("climate", "set_hvac_mode", entity, {"hvac_mode": mode})
        elif domain == "cover":
            is_open = bool(st) and st.get("state") == "open"
            if st:
                self.optimistic(entity, {"state": "closing" if is_open else "opening"})
            self.call("cover", "close_cover" if is_open else "open_cover", entity)
        elif domain == "media_player":
            self.call("media_player", "media_play_pause", entity)
        elif domain == "lock":
            locked = bool(st) and st.get("state") == "locked"
            if st:
                self.optimistic(entity, {"state": "unlocked" if locked else "locked"})
            self.call("lock", "unlock" if locked else "lock", entity)
        elif domain == "vacuum":
            cleaning = bool(st) and st.get("state") in ("cleaning", "returning")
            self.call("vacuum", "pause" if cleaning else "start", entity)
        elif domain in ("scene", "script"):
            self.call(domain, "turn_on", entity)
            if flash:
                flash()
        elif domain == "automation":
            self.call("automation", "trigger", entity)
            if flash:
                flash()

    def climate_step(self, tile, sign):
        st = self.states().get(tile["entity"]) or {}
        attrs = st.get("attributes") or {}
        if attrs.get("temperature") is None:
            return
        nxt = round((attrs["temperature"] + float(tile.get("temp_step") or 1) * sign) * 10) / 10
        self.optimistic(tile["entity"], {"attributes": dict(attrs, temperature=nxt)})
        self.call("climate", "set_temperature", tile["entity"], {"temperature": nxt})
