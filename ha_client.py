"""Minimal Home Assistant client: REST for commands/snapshots, WebSocket for
realtime state push. Runs its own background threads; all callbacks land on
those threads, so callers must hop back to the UI thread themselves.
"""

import json
import threading
import time
import urllib.request
import urllib.error

import websocket  # websocket-client


class HAClient:
    def __init__(self, on_event=None, on_status=None):
        self.url = ""
        self.token = ""
        self.on_event = on_event      # callback(entity_id, new_state_dict)
        self.on_status = on_status    # callback(connected: bool, detail: str)
        self.poll_interval = 30

        self._entity_ids = []
        self._ws = None
        self._stop = threading.Event()
        self._ws_thread = None
        self._poll_thread = None
        self._lock = threading.Lock()

    # ---- configuration ----

    def configure(self, url, token, poll_interval=None):
        with self._lock:
            self.url = (url or "").rstrip("/")
            self.token = token or ""
            if poll_interval:
                self.poll_interval = max(5, int(poll_interval))
        self._kick()

    def set_entities(self, entity_ids):
        self._entity_ids = list(dict.fromkeys(entity_ids))

    def _kick(self):
        """Force the ws loop to drop its current connection and reconnect
        immediately with the new url/token (e.g. after Settings is saved)."""
        try:
            if self._ws:
                self._ws.close()
        except Exception:
            pass

    # ---- lifecycle ----

    def start(self):
        self._stop.clear()
        self._ws_thread = threading.Thread(target=self._ws_loop, daemon=True)
        self._ws_thread.start()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def stop(self):
        self._stop.set()
        try:
            if self._ws:
                self._ws.close()
        except Exception:
            pass

    # ---- REST ----

    def _request(self, path, method="GET", body=None, timeout=8):
        if not self.url:
            raise RuntimeError("not configured")
        req = urllib.request.Request(
            self.url + path,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
            },
            method=method,
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8")) if raw else None

    def test_connection(self):
        try:
            self._request("/api/")
            return True, "ok"
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return False, "invalid token"
            return False, "HTTP %d" % e.code
        except Exception as e:
            return False, str(e)

    def get_states(self, timeout=15):
        return self._request("/api/states", timeout=timeout) or []

    def get_state(self, entity_id, timeout=8):
        return self._request("/api/states/%s" % entity_id, timeout=timeout)

    def call_service(self, domain, service, entity_id=None, extra=None, timeout=8):
        data = dict(extra or {})
        if entity_id:
            data["entity_id"] = entity_id
        return self._request("/api/services/%s/%s" % (domain, service), "POST", data, timeout=timeout)

    # ---- websocket (realtime push) ----

    def _ws_url(self):
        url = self.url
        if url.startswith("https://"):
            return "wss://" + url[len("https://"):] + "/api/websocket"
        if url.startswith("http://"):
            return "ws://" + url[len("http://"):] + "/api/websocket"
        return "ws://" + url + "/api/websocket"

    def _set_status(self, connected, detail=""):
        if self.on_status:
            try:
                self.on_status(connected, detail)
            except Exception:
                pass

    def _ws_loop(self):
        backoff = 2
        while not self._stop.is_set():
            if not self.url or not self.token:
                time.sleep(1)
                continue
            try:
                ws = websocket.create_connection(self._ws_url(), timeout=10)
                self._ws = ws
                try:
                    hello = json.loads(ws.recv())
                    if hello.get("type") != "auth_required":
                        raise RuntimeError("unexpected handshake: %r" % hello)
                    ws.send(json.dumps({"type": "auth", "access_token": self.token}))
                    auth_resp = json.loads(ws.recv())
                    if auth_resp.get("type") != "auth_ok":
                        self._set_status(False, "invalid token")
                        time.sleep(15)
                        continue
                    ws.send(json.dumps({
                        "id": 1, "type": "subscribe_events", "event_type": "state_changed",
                    }))
                    ws.recv()  # result ack for id 1
                    self._set_status(True, "connected")
                    backoff = 2

                    while not self._stop.is_set():
                        raw = ws.recv()
                        if raw is None or raw == "":
                            break
                        msg = json.loads(raw)
                        if msg.get("type") != "event":
                            continue
                        event = msg.get("event") or {}
                        if event.get("event_type") != "state_changed":
                            continue
                        data = event.get("data") or {}
                        new_state = data.get("new_state")
                        entity_id = data.get("entity_id")
                        if entity_id and new_state and self.on_event:
                            self.on_event(entity_id, new_state)
                finally:
                    try:
                        ws.close()
                    except Exception:
                        pass
                    self._ws = None
            except Exception as e:
                self._set_status(False, str(e))

            if self._stop.is_set():
                return
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)

    # ---- fallback poll (safety net if the websocket is stuck/unreachable) ----

    def _poll_loop(self):
        while not self._stop.is_set():
            for _ in range(max(5, self.poll_interval)):
                if self._stop.is_set():
                    return
                time.sleep(1)
            if not self.url or not self.token:
                continue
            for eid in list(self._entity_ids):
                if self._stop.is_set():
                    return
                try:
                    state = self.get_state(eid)
                    if state and self.on_event:
                        self.on_event(eid, state)
                except Exception:
                    pass
