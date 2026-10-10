"""Doing what a widget's handlers asked for, and only what it may.

`Executor.perform(action, widget, ctx)` checks the permission the action needs (permissions.Grants), then does it;
the answer of anything slow (a web request, a recording) arrives later in `ctx.state`. Everything that touches the
computer is a service handed in (`Services`), so a test or another platform can stand in for it.

Web addresses are opened only if they are http, https or mailto. Programs are started without a shell, only the exact
path the user allowed, with the arguments the widget gave. A web request may only go to a host the widget was allowed;
`GatedTransport` applies the same rule to every address a *source* reads.
"""
import json as jsonlib
import os
import subprocess
import threading
import webbrowser
from dataclasses import dataclass

from . import permissions as perms
from .sources import Transport, do_request

WEB_SCHEMES = ("http://", "https://", "mailto:")
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD")
# Headers that are the connection's own business, or that would send a request somewhere its permission does not say.
FORBIDDEN_HEADERS = {"host", "content-length", "transfer-encoding", "connection", "upgrade", "te", "trailer", "expect",
                     "proxy-authorization", "proxy-connection", "x-forwarded-host", "forwarded"}
MAX_BODY, MAX_TIMEOUT, MAX_INFLIGHT, MAX_CLIPBOARD, MAX_RECORD_S = 1_000_000, 60.0, 4, 1_000_000, 600
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
AUDIO_EXT = (".wav", ".mp3", ".m4a", ".ogg", ".flac")


def _start_program(path, args):
    subprocess.Popen([path] + list(args), shell=False, close_fds=True)


def _copy_to_clipboard(text):
    from PySide6.QtGui import QGuiApplication
    QGuiApplication.clipboard().setText(text)


def _choose(kind):
    from PySide6.QtWidgets import QFileDialog
    pattern = "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp)" if kind == "image" else "All files (*)"
    path, _ = QFileDialog.getOpenFileName(None, "Choose a file", "", pattern)
    return path or ""


def _spawn(fn):
    threading.Thread(target=fn, daemon=True).start()


def _direct(fn):
    return fn()


BLOCKED_SCHEMES = {"file", "javascript", "vbscript", "data", "ms-msdt", "search-ms", "search", "ms-officecmd", "shell",
                   "ms-cxh", "ms-cxh-full", "ms-appinstaller", "ms-gamingoverlay", "cmd", "powershell", "mshta"}


def _protocol_registered(scheme):
    """Is there an app registered for `scheme:` addresses on this computer?"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, scheme) as k:
            winreg.QueryValueEx(k, "URL Protocol")
        return True
    except OSError:
        return False


def _open_app(uri):
    os.startfile(uri)


def _media_control(command, seconds):
    from . import sysmedia
    return sysmedia.control(command, seconds)


def _make_recorder(path, seconds, on_level, on_done):
    from .devices import Recorder
    return Recorder(path, seconds, on_level, on_done)


@dataclass
class Services:
    """What the computer does for the executor. Each is a plain function; replace any of them."""
    transport: object = None
    opener: object = webbrowser.open
    starter: object = _start_program
    clipboard: object = _copy_to_clipboard
    chooser: object = _choose                 # chooser(kind) -> path or ""
    recorder_factory: object = _make_recorder  # (path, seconds, on_level, on_done) -> object with start() / stop()
    app_opener: object = _open_app            # app_opener(uri)
    protocols: object = _protocol_registered  # protocols(scheme) -> is an app registered for it
    media_control: object = _media_control    # media_control(command, seconds) -> bool
    spawn: object = _spawn                    # run a function off the GUI thread
    gui: object = _direct                     # run a function on the GUI thread

    def __post_init__(self):
        if self.transport is None:
            self.transport = Transport()


class GatedTransport:
    """A transport that reads only the hosts the widget was allowed (for its sources)."""

    def __init__(self, inner, check):
        self.inner, self.check = inner, check

    def get(self, url, timeout=10):
        self.check(url)
        return self.inner.get(url, timeout)

    def request(self, method, url, body=None, headers=None, timeout=20):
        self.check(url)
        return do_request(self.inner, method, url, body, headers, timeout)


def _wav_seconds(path):
    try:
        import wave
        with wave.open(path) as w:
            return round(w.getnframes() / w.getframerate(), 1)
    except Exception:
        return 0.0


def accepts_file(path, accepts):
    low = str(path).lower()
    if os.path.isdir(path):
        return False
    return ("any" in accepts or ("image" in accepts and low.endswith(IMAGE_EXT))
            or ("audio" in accepts and low.endswith(AUDIO_EXT)))


def clean_headers(headers):
    """The headers a widget asked for, as plain text pairs, without those it may not set."""
    out = {}
    for k, v in (headers or {}).items():
        k, v = str(k).strip(), str(v)
        if not k or "\r" in k + v or "\n" in k + v or ":" in k:
            raise ValueError("not a valid header: %r" % (k,))
        if k.lower() in FORBIDDEN_HEADERS:
            raise ValueError("a widget may not set the %s header" % k)
        out[k] = v
    return out


class Executor:
    def __init__(self, widget, grants, services=None):
        self.widget, self.grants, self.sv = widget, grants, services or Services()
        self._recorders = {}
        self.closed = False
        self._inflight = 0
        self._lock = threading.Lock()

    def gate(self):
        """The check a source's transport uses."""
        return lambda url: self.grants.require(self.widget, perms.need_network(url))

    def perform(self, action, ctx):
        """Do `action`. Raises PermissionDenied / ValueError when it may not or cannot be done."""
        handler = getattr(self, "_do_" + action.kind, None)
        if handler is None:
            raise ValueError("unknown action %r" % action.kind)
        return handler(action, ctx)

    def close(self):
        self.closed = True                           # an answer that arrives after this is dropped
        for rec in list(self._recorders.values()):
            try:
                rec.stop()
            except Exception:
                pass
        self._recorders.clear()

    # ------------------------------------------------------------------ the actions
    def _do_open_url(self, a, ctx):
        if not a.target.lower().startswith(WEB_SCHEMES):
            raise ValueError("only web addresses are opened: %r" % a.target)
        return bool(self.sv.opener(a.target))

    def _do_open_app(self, a, ctx):
        scheme = a.target.partition(":")[0].lower()
        if not scheme or not all(c.isalnum() or c in "-+." for c in scheme):
            raise ValueError("not an app address: %r" % a.target)
        if scheme in BLOCKED_SCHEMES or scheme in ("http", "https", "mailto"):
            raise ValueError("%s: is not opened as an app" % scheme)
        self.grants.require(self.widget, perms.need_app(a.target))
        if not self.sv.protocols(scheme):
            raise ValueError("no app is installed for %s:" % scheme)
        self.sv.app_opener(a.target)
        return True

    def _do_media(self, a, ctx):
        self.grants.require(self.widget, "media")
        if a.target not in ("play_pause", "next", "previous", "seek"):
            raise ValueError("unknown media command %r" % a.target)
        return bool(self.sv.media_control(a.target, a.options.get("seconds")))

    def _do_copy(self, a, ctx):
        self.grants.require(self.widget, "clipboard")
        if len(a.target) > MAX_CLIPBOARD:
            raise ValueError("too much text for the clipboard (%d characters at most)" % MAX_CLIPBOARD)
        self.sv.clipboard(a.target)
        return True

    def _do_launch(self, a, ctx):
        self.grants.require(self.widget, perms.need_launch(a.target))
        if not os.path.isfile(os.path.expandvars(a.target)):
            raise ValueError("no such program: %r" % a.target)
        args = [str(x) for x in a.options.get("args", [])]
        if len(args) > 32 or any(len(x) > 4096 for x in args):
            raise ValueError("too many or too long arguments")
        self.sv.starter(os.path.expandvars(a.target), args)
        return True

    def _do_pick_file(self, a, ctx):
        path = self.sv.chooser(a.options.get("kind", "image"))
        if path:
            ctx.set_state(**{a.options["into"]: path})
        return bool(path)

    def _do_request(self, a, ctx):
        url, o = a.target, a.options
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("only http and https addresses are requested: %r" % url)
        self.grants.require(self.widget, perms.need_network(url))
        method = str(o["method"]).upper()
        if method not in METHODS:
            raise ValueError("a request is one of %s, not %r" % (", ".join(METHODS), o["method"]))
        into, headers, body = o["into"], clean_headers(o.get("headers")), o.get("body")
        if o.get("json") is not None:
            body = jsonlib.dumps(o["json"]).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        if body is not None and len(body) > MAX_BODY:
            raise ValueError("a request body may be %d bytes at most" % MAX_BODY)
        try:
            timeout = max(1.0, min(MAX_TIMEOUT, float(o["timeout"])))
        except (TypeError, ValueError):
            timeout = 20.0
        with self._lock:
            if self._inflight >= MAX_INFLIGHT:
                raise ValueError("too many requests at once (%d): wait for one to finish" % MAX_INFLIGHT)
            self._inflight += 1
        ctx.set_state(**{into + "_busy": True})

        def work():
            try:
                status, data, _ = do_request(self.sv.transport, method, url, body, headers, timeout)
                text = data.decode("utf-8", "replace")
                try:
                    parsed = jsonlib.loads(text)
                except ValueError:
                    parsed = text
                result = {"ok": 200 <= status < 300, "status": status, "data": parsed}
            except Exception as e:
                result = {"ok": False, "status": 0, "data": None, "error": str(e) or type(e).__name__}
            with self._lock:
                self._inflight -= 1
            if not self.closed:
                self.sv.gui(lambda: None if self.closed else ctx.set_state(**{into: result, into + "_busy": False}))

        self.sv.spawn(work)
        return True

    def _do_record_start(self, a, ctx):
        self.grants.require(self.widget, "microphone")
        into = a.options["into"]
        if into in self._recorders:
            return False

        def level(v):
            ctx.set_state(**{into + "_level": v})

        def done(path):
            self._recorders.pop(into, None)
            ctx.set_state(**{into: path, into + "_recording": False, into + "_seconds": _wav_seconds(path)})

        try:
            seconds = max(1, min(MAX_RECORD_S, float(a.options.get("seconds", 60))))
        except (TypeError, ValueError):
            seconds = 60
        rec = self.sv.recorder_factory(None, seconds, level, done)
        ctx.set_state(**{into + "_recording": True, into + "_error": None, into + "_level": 0.0})
        self._recorders[into] = rec
        try:
            rec.start()
        except Exception as e:
            self._recorders.pop(into, None)
            ctx.set_state(**{into + "_error": str(e), into + "_recording": False})
            return False
        return True

    def _do_record_stop(self, a, ctx):
        rec = self._recorders.get(a.options["into"])
        if rec is None:
            return False
        rec.stop()                                  # its on_done keeps the file's path in the state
        return True
