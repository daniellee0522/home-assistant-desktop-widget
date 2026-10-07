"""What this computer is playing, as a player widget shows it: Windows' media sessions (Spotify, a browser,
any player that shows in the volume flyout), read and controlled through WinRT
(GlobalSystemMediaTransportControlsSessionManager).

It answers as a Home Assistant media player would, under ENTITY: {"state": "playing" | "paused" | "idle",
"attributes": {...}}, so the widget draws it as any other player. Its cover is given by get_art() for the
"local:" picture path the state names. Read on a thread of its own, once a second while a widget shows it
(every few seconds while the widgets are dimmed), and told on_state only when something changed.
"""
import asyncio
import datetime
import threading
import time
import traceback

ENTITY = "local_media.this_pc"
NAME = "本機"
TRANSITION_GRACE_S = 0.3
TRANSITION_POLL_S = 0.05

try:
    from winrt.windows.media.control import \
        GlobalSystemMediaTransportControlsSessionManager as _Manager  # noqa: N814
    from winrt.windows.media.control import \
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as _Status  # noqa: N814
    from winrt.windows.storage.streams import Buffer, InputStreamOptions
    AVAILABLE = True
except Exception:                                   # not Windows 10+, or the packages are missing
    AVAILABLE = False

_STATES = {}
if AVAILABLE:
    _STATES = {_Status.PLAYING: "playing", _Status.PAUSED: "paused", _Status.STOPPED: "idle",
               _Status.CHANGING: "playing", _Status.OPENED: "idle", _Status.CLOSED: "off"}


def _seconds(span):
    try:
        return span.total_seconds()
    except AttributeError:                          # a raw TimeSpan: 100 ns ticks
        return getattr(span, "duration", 0) / 1e7


def app_name(aumid):
    """The playing app's name from its id: "Spotify.exe" -> Spotify, "AppleInc.AppleMusicWin_8wekyb3d8bbwe!App"
    -> AppleMusicWin."""
    part = (aumid or "").split("!")[0]
    if part.lower().endswith(".exe"):
        return part[:-4].split("\\")[-1]
    return part.split("_")[0].split(".")[-1]


def _iso(when):
    try:
        return when.astimezone(datetime.timezone.utc).isoformat()
    except Exception:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()


class LocalMedia:
    def __init__(self, on_state):
        self.on_state = on_state
        self.active = False                         # a widget shows it
        self.slow = False                           # the widgets are dimmed
        self.art, self._art_key, self._art_n = None, None, 0
        self._last = None
        self._transition_until = None
        self._manager = None
        self._loop = None
        self._wake_event = None
        self._watched = None                        # the session whose changes wake the reading
        self._props_dirty = True                    # its song (and cover) changed since last read
        if AVAILABLE:
            threading.Thread(target=self._run, daemon=True, name="local-media").start()

    # -- reading -----------------------------------------------------------------------------------------
    def _run(self):
        # The loop runs for good: reads come round on it, and controls asked from other threads join it.
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self):
        self._wake_event = asyncio.Event()
        while True:
            self._wake_event.clear()
            if self.active:
                try:
                    await self._read()
                except Exception:
                    traceback.print_exc()
            try:
                # (the session's own events wake it at once; this is the fallback)
                timeout = 5.0 if (self.slow or not self.active) else 2.0
                if self.active and self._transition_until is not None:
                    timeout = min(timeout, TRANSITION_POLL_S)
                await asyncio.wait_for(self._wake_event.wait(), timeout)
            except asyncio.TimeoutError:
                pass

    def _wake(self):
        if self._loop is not None and self._wake_event is not None:
            self._loop.call_soon_threadsafe(self._wake_event.set)

    async def _session(self):
        if self._manager is None:
            self._manager = await _Manager.request_async()
            # another app's session becoming the current one is read at once
            self._manager.add_current_session_changed(lambda *a: self._changed_now(True))
        session = self._manager.get_current_session()
        if session is not None and (self._watched is None or
                                    session.source_app_user_model_id != self._watched.source_app_user_model_id):
            # its song, its playing or pausing, a jump: read at once, not at the next round
            session.add_media_properties_changed(lambda *a: self._changed_now(True))
            session.add_playback_info_changed(lambda *a: self._changed_now(False))
            session.add_timeline_properties_changed(lambda *a: self._changed_now(False))
            self._watched = session
            self._props_dirty = True
        return session

    def _changed_now(self, song):
        if song:
            self._props_dirty = True
        self._wake()

    async def _read(self):
        session = await self._session()
        if session is None:
            state = {"state": "off", "attributes": {"friendly_name": NAME}}
            if self._hold_transition(state):
                return
            self.art, self._art_key = None, None
        else:
            props = await session.try_get_media_properties_async()
            info = session.get_playback_info()
            line = session.get_timeline_properties()
            status = _STATES.get(info.playback_status, "idle")
            attrs = {"friendly_name": NAME, "media_title": props.title or "",
                     # (Apple Music gives "artist — album"; the artist is what is shown)
                     "media_artist": (props.artist or "").split(" — ")[0],
                     "app_name": app_name(session.source_app_user_model_id),
                     # what it can be asked, as Home Assistant's features: pause 1, seek 2, previous 16,
                     # next 32, play 16384
                     "supported_features": ((1 | 16384 if info.controls.is_play_pause_toggle_enabled else 0)
                                            | (2 if info.controls.is_playback_position_enabled else 0)
                                            | (16 if info.controls.is_previous_enabled else 0)
                                            | (32 if info.controls.is_next_enabled else 0))}
            duration = _seconds(line.end_time) - _seconds(line.start_time)
            if duration > 0:
                attrs["media_duration"] = round(duration, 1)
                attrs["media_position"] = round(_seconds(line.position) - _seconds(line.start_time), 1)
                attrs["media_position_updated_at"] = _iso(line.last_updated_time)
            state = {"state": status, "attributes": attrs}
            if self._hold_transition(state):
                return
            # The cover is read again whenever the song's details change, and kept only if it differs: an
            # app gives the new title first and its cover a moment later.
            if self._props_dirty or (props.title, props.artist) != self._art_key:
                self._props_dirty = False
                self._art_key = (props.title, props.artist)
                art = await self._thumbnail(props.thumbnail)
                if art != self.art:
                    self.art = art
                    self._art_n += 1
            if self.art:
                attrs["entity_picture"] = "local:art/%d" % self._art_n
            state = {"state": status, "attributes": attrs}
        if self._changed(state):
            self._last = state
            self.on_state(ENTITY, state)

    def _hold_transition(self, state):
        """Keep the last track through a bounded gap while Windows replaces a media session.

        A real pause with metadata is immediate; only missing metadata or an inactive session
        gets a grace period. Retry during that period without discarding the last cover.
        """
        incomplete = (state["state"] in ("off", "idle") or
                      not state["attributes"].get("media_title"))
        last = self._last
        if (not incomplete or last is None or last["state"] not in ("playing", "paused") or
                not last["attributes"].get("media_title")):
            self._transition_until = None
            return False
        now = time.monotonic()
        if self._transition_until is None:
            self._transition_until = now + TRANSITION_GRACE_S
        if now < self._transition_until:
            return True
        self._transition_until = None
        return False

    async def _thumbnail(self, ref):
        if ref is None:
            return None
        try:
            stream = await ref.open_read_async()
            size = int(stream.size)
            if not size:
                return None
            buf = Buffer(size)
            got = await stream.read_async(buf, size, InputStreamOptions.READ_AHEAD)
            return bytes(memoryview(got))[:got.length]
        except Exception:
            traceback.print_exc()
            return None

    def _changed(self, state):
        """Anything but the song's place moving on as it should."""
        last = self._last
        if last is None or last["state"] != state["state"]:
            return True
        a, b = dict(last["attributes"]), dict(state["attributes"])
        pa, pb = a.pop("media_position", None), b.pop("media_position", None)
        ta, tb = a.pop("media_position_updated_at", None), b.pop("media_position_updated_at", None)
        if a != b:
            return True
        if pa is None or pb is None:
            return pa != pb
        try:
            elapsed = (datetime.datetime.fromisoformat(tb) - datetime.datetime.fromisoformat(ta)).total_seconds()
        except (TypeError, ValueError):
            elapsed = 0.0
        expected = pa + (elapsed if state["state"] == "playing" else 0.0)
        return abs(pb - expected) > 2.0

    # -- control -------------------------------------------------------------------------------------------
    def control(self, service, data=None):
        """A Home Assistant media_player service, done on this computer's current session."""
        if not (AVAILABLE and self._loop):
            return False

        async def go():
            session = await self._session()
            if session is None:
                return
            if service == "media_play_pause":
                await session.try_toggle_play_pause_async()
            elif service == "media_next_track":
                await session.try_skip_next_async()
            elif service == "media_previous_track":
                await session.try_skip_previous_async()
            elif service == "media_seek":
                await session.try_change_playback_position_async(int(float((data or {}).get("seek_position", 0)) * 1e7))
        try:
            asyncio.run_coroutine_threadsafe(go(), self._loop).result(3)
        except Exception:
            traceback.print_exc()
            return False
        time.sleep(0.15)
        self._wake()                               # read again soon: the session changed
        return True

    def set_active(self, active, slow=False):
        changed = active and not self.active
        self.active, self.slow = active, slow
        if changed:
            self._last = None                      # a widget that just started showing it is told all
            self._transition_until = None
            self._wake()

    def get_art(self, path):
        return self.art if path.startswith("local:art/") else None
