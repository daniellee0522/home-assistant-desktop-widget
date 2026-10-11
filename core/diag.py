"""Saying that something which may fail did, without stopping anything: `note("what was being done")` inside an `except`.

Many things here are allowed to fail (a window already gone, a connection that dropped, a callback of ours that raised); the
program goes on, and before this the only trace of a bug in one of them was nothing at all. A note is one line (what, the
kind of error and where it was raised) sent to whatever `set_sink` was given (the program's log). The same fault is noted
once a minute, and the notes of a run are capped, so a failure that repeats every frame does not fill the log or cost time.
Imports nothing of ours; never raises.
"""
import sys
import time
import traceback

_sink = [None]
_seen = {}
_count = [0]
REPEAT_S = 60.0
MAX_NOTES = 500


def set_sink(fn):
    """Where notes go (a function taking one line of text); None for nowhere."""
    _sink[0] = fn


def note(what, exc=None):
    """Note the exception being handled (or `exc`), as happening while `what`."""
    try:
        sink = _sink[0]
        exc = exc or sys.exc_info()[1]
        if sink is None or exc is None or _count[0] >= MAX_NOTES:
            return
        frames = traceback.extract_tb(exc.__traceback__)
        where = "%s:%d" % (frames[-1].filename.replace("\\", "/").rsplit("/", 1)[-1], frames[-1].lineno) if frames else "?"
        key = (what, type(exc).__name__, where)
        now = time.monotonic()
        if now - _seen.get(key, -REPEAT_S) < REPEAT_S:
            return
        _seen[key] = now
        _count[0] += 1
        sink("%s failed: %s: %s (%s)" % (what, type(exc).__name__, str(exc)[:200], where))
    except Exception:
        pass
