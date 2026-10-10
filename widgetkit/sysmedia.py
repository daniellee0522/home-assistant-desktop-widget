"""What this computer is playing, and control of it, shared by every widget that shows it: one reader (the program's own
core.local_media, Windows' media sessions through WinRT), counted by how many widgets hold it.

`snapshot()` is what a SystemMediaSource gives; `control(command, seconds)` is what the `media` action does. A test (or
another platform) replaces the reader with `install(factory)`.
"""
import datetime
import threading
import time

_lock = threading.Lock()
_reader = None
_holders = 0
_latest = {"state": "off"}
_factory = None


def install(factory):
    """Use another reader: factory(on_state) -> object with set_active(bool), control(service, data), get_art(path)."""
    global _factory, _reader
    _factory, _reader = factory, None


def reset():
    """Forget the reader and what it said (for tests; the reader, if any, is stopped)."""
    global _factory, _reader, _holders, _latest
    if _reader is not None:
        try:
            _reader.set_active(False)
        except Exception:
            pass
    _factory = _reader = None
    _holders = 0
    _latest = {"state": "off"}


def _make():
    if _factory:
        return _factory(_on_state)
    from core.local_media import LocalMedia
    return LocalMedia(_on_state)


def _on_state(entity, state):
    global _latest
    _latest = _convert(state, _reader)


def _convert(state, reader):
    attrs = (state or {}).get("attributes") or {}
    features = int(attrs.get("supported_features") or 0)
    can = []
    for flag, name in ((16, "previous"), (16384 | 1, "play_pause"), (32, "next"), (2, "seek")):
        if features & flag:
            can.append(name)
    updated = attrs.get("media_position_updated_at")
    try:
        at = datetime.datetime.fromisoformat(str(updated).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        at = time.time()
    art = None
    if attrs.get("entity_picture") and reader is not None:
        art = reader.get_art(attrs["entity_picture"])
    return {"state": (state or {}).get("state", "off"), "title": attrs.get("media_title", ""),
            "artist": attrs.get("media_artist", ""), "app": attrs.get("app_name", ""),
            "duration": attrs.get("media_duration") or 0.0, "position": attrs.get("media_position") or 0.0,
            "position_at": at, "can": can, "art": art}


def acquire():
    global _reader, _holders
    with _lock:
        if _reader is None:
            _reader = _make()
        _holders += 1
        _reader.set_active(True)


def release():
    global _holders
    with _lock:
        _holders = max(0, _holders - 1)
        if _reader is not None and _holders == 0:
            _reader.set_active(False)


def snapshot():
    return dict(_latest)


def control(command, seconds=None):
    """"play_pause", "next", "previous", or "seek" (to `seconds`). False if there is nothing to control."""
    with _lock:
        reader = _reader or _make()
    service = {"play_pause": "media_play_pause", "next": "media_next_track", "previous": "media_previous_track",
               "seek": "media_seek"}[command]
    return bool(reader.control(service, {"seek_position": seconds} if command == "seek" else None))
