"""Where a widget's numbers and words come from. A widget lists its sources; each one is told the user's settings
(which symbols, which feeds), fetches, and hands back plain data. The widget's drawing never touches the network.

    JsonSource   a JSON address, once or for each item of a list setting, and which values to take from the answer
    RssSource    news feeds (RSS or Atom), merged newest first
    ImageSource  pictures from the web (one address, or several: the tiles of a map)
    SystemSource this computer: battery, memory, disk, cpu (needs the "system" permission)
    StaticSource a value written in the widget

Every address a source reads is checked against the widget's "network:<host>" permissions by the runtime.

A source that fails keeps the last good answer (`Store`), and says so, so a widget can show old numbers rather than
nothing.
"""
import json
import string
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime


class _Plain(string.Formatter):
    """str.format without the parts that reach into objects: {name} and {name:spec} only, never {name.attr} or {name[0]}
    (a template may come from what a person typed into a setting)."""

    def get_field(self, field_name, args, kwargs):
        if "." in field_name or "[" in field_name:
            raise ValueError("a template may only name a value, not reach into it: {%s}" % field_name)
        return super().get_field(field_name, args, kwargs)


def fill(template, **values):
    """`template` with its {names} filled from `values`."""
    return _Plain().vformat(template, (), values)


def scalars(cfg):
    """The settings a template may use: text and numbers."""
    return {k: v for k, v in cfg.items() if isinstance(v, (str, int, float)) and not isinstance(v, bool)}


def get_path(obj, path, default=None):
    """`path` ("chart.result.0.meta.price") followed through dicts and lists."""
    for part in path.split("."):
        try:
            obj = obj[int(part)] if isinstance(obj, list) else obj[part]
        except (KeyError, IndexError, ValueError, TypeError):
            return default
    return obj


class Transport:
    """How an address is read. The program's own: HTTP(S) with a timeout and a size limit. Tests give their own
    (anything with get(url, timeout) and, for requests, request(method, url, body, headers, timeout))."""

    MAX_BYTES = 8_000_000

    def get(self, url, timeout=10):
        return self.request("GET", url, timeout=timeout)[1]

    def request(self, method, url, body=None, headers=None, timeout=20):
        """(status, bytes, headers). A non-2xx answer is returned, not raised, so a service's error text can be shown.
        A redirect to another host is refused: the permission the widget has is for the host it asked for."""
        head = {"User-Agent": "widgetkit/1 (desktop widget host; contact: local user)"}
        head.update(headers or {})
        req = urllib.request.Request(url, data=body, method=method, headers=head)
        try:
            with _OPENER.open(req, timeout=timeout) as r:
                data = r.read(self.MAX_BYTES + 1)
                status, got = r.status, dict(r.headers)
        except urllib.error.HTTPError as e:
            data, status, got = e.read(self.MAX_BYTES + 1), e.code, dict(e.headers)
        if len(data) > self.MAX_BYTES:
            raise ValueError("answer larger than %d bytes" % self.MAX_BYTES)
        return status, data, got


class _SameHost(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).hostname != urllib.parse.urlparse(req.full_url).hostname:
            raise urllib.error.URLError("redirect to another host refused: %s" % newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SameHost)


def do_request(transport, method, url, body=None, headers=None, timeout=20):
    """transport.request if it has one, else its get (a stand-in that only answers addresses)."""
    if hasattr(transport, "request"):
        return transport.request(method, url, body=body, headers=headers, timeout=timeout)
    return 200, transport.get(url, timeout), {}


class Source:
    name = ""
    every = 60                      # seconds between fetches
    permission = None               # a permission the runtime must find allowed before it fetches ("system")
    standby_every = None            # seconds between fetches in standby: None = five times `every` (a minute at least),
                                    # 0 = none until the widget wakes (set in the source's constructor)

    def interval(self, standby=False):
        """Seconds until this source is due again: `every`, or the longer standby time while the program is in standby."""
        if not standby:
            return self.every
        if self.standby_every is None:
            return max(self.every * 5, 60.0)
        return self.standby_every if self.standby_every > 0 else float("inf")

    def close(self):
        """The widget is going away: let go of anything held."""

    def key(self, inputs):
        """What this source's answer depends on besides time: fetched again at once when it changes (a map's tiles
        follow where the user dragged it). `inputs` are the settings plus {"state": the widget's state}."""
        return None

    def fetch(self, cfg, transport):
        raise NotImplementedError


class StaticSource(Source):
    def __init__(self, name, value):
        self.name, self.value = name, value

    def fetch(self, cfg, transport):
        return self.value


class JsonSource(Source):
    def __init__(self, name, url, fields, each=None, every=60, standby_every=None):
        """url: "https://host/{item}?lang={lang}" - {item} is the current item of the list setting `each`, and
        any other {key} is that setting. fields: {"price": "chart.result.0.meta.regularMarketPrice"}."""
        self.name, self.url, self.fields, self.each, self.every = name, url, fields, each, every
        self.standby_every = standby_every

    def _one(self, cfg, transport, item=None):
        key, _, label = str(item).partition("=")
        values = scalars(cfg)
        values["item"] = urllib.parse.quote(key.strip(), safe="")
        url = fill(self.url, **values)
        body = json.loads(transport.get(url))
        out = {k: get_path(body, path) for k, path in self.fields.items()}
        out["item"], out["label"] = key.strip(), label.strip() or None
        return out

    def fetch(self, cfg, transport):
        if self.each is None:
            return self._one(cfg, transport)
        items = cfg.get(self.each, [])
        if not isinstance(items, (list, tuple)):
            raise ValueError("%s: the setting %r must be a list" % (self.name, self.each))
        out = []
        for item in items:
            try:
                out.append(self._one(cfg, transport, item))
            except PermissionError:
                raise                                                # refused is not "this one failed"
            except Exception:
                out.append({"item": str(item).partition("=")[0].strip(), "label": str(item).partition("=")[2].strip() or None,
                            "error": True})           # one bad symbol does not blank the rest
        return out


class RssSource(Source):
    def __init__(self, name, feeds="feeds", limit="max_news", every=300, standby_every=None):
        """feeds: the list setting of {"name", "url"} (or just urls); limit: the number setting."""
        self.name, self.feeds, self.limit, self.every = name, feeds, limit, every
        self.standby_every = standby_every

    @staticmethod
    def _items(xml, label):
        head = xml[:4096].upper() if isinstance(xml, (bytes, bytearray)) else xml[:4096].upper().encode("utf-8", "ignore")
        if b"<!DOCTYPE" in head or b"<!ENTITY" in head:                  # no DTDs: they are how feeds blow up a parser
            raise ValueError("a feed may not carry a DTD")
        root = ET.fromstring(xml)
        out = []
        for it in list(root.iter("item")) + list(root.iter("{http://www.w3.org/2005/Atom}entry")):
            title = (it.findtext("title") or it.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
            when = it.findtext("pubDate") or it.findtext("{http://www.w3.org/2005/Atom}updated") or ""
            try:
                ts = parsedate_to_datetime(when).timestamp()
            except (TypeError, ValueError):
                ts = 0
            if title:
                out.append({"source": label, "title": title, "time": ts})
        return out

    def fetch(self, cfg, transport):
        items = []
        for feed in cfg.get(self.feeds, []):
            feed = feed if isinstance(feed, dict) else {"name": feed, "url": feed}
            try:
                items += self._items(transport.get(feed["url"]), feed.get("name") or feed["url"])
            except PermissionError:
                raise
            except Exception:
                continue
        items.sort(key=lambda i: -i["time"])
        return items[:int(cfg.get(self.limit, 5))]


def is_image(data):
    """Do these bytes begin as a PNG, JPEG, GIF, BMP or WebP picture (the header, not just a letter or two)?"""
    return (data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff")
            or data.startswith((b"GIF87a", b"GIF89a")) or (data.startswith(b"BM") and data[6:10] == b"\0\0\0\0")
            or (data.startswith(b"RIFF") and data[8:12] == b"WEBP"))


IMAGE_CACHE_BYTES = 64_000_000                       # what an ImageSource keeps of what it fetched, all told


class ImageSource(Source):
    def __init__(self, name, url=None, urls=None, every=3600, keep=96, standby_every=None):
        """One picture: `url` ("https://host/{key}.jpg" over the settings) gives its bytes. Several: `urls` is a
        function of the inputs (the settings, and {"state": ...}) returning addresses (the tiles of a map); the answer
        is {address: bytes} for those that came. Pictures already fetched are kept (`keep` of them), so only what is
        new is asked for. Only real pictures are taken: the first bytes must be a PNG, JPEG, GIF, BMP or WebP."""
        self.name, self.url, self.urls, self.every, self.keep = name, url, urls, every, keep
        self.standby_every = standby_every
        self._have = {}

    def key(self, inputs):
        return tuple(self.urls(inputs)) if self.urls else None

    def _one(self, url, transport):
        status, data, _ = do_request(transport, "GET", url, timeout=15)
        if status >= 300 or not is_image(data):
            raise ValueError("not a picture (status %s)" % status)
        return data

    def fetch(self, cfg, transport):
        if self.urls:
            wanted = list(self.urls(cfg))
            for url in wanted:
                if url not in self._have:
                    try:
                        self._have[url] = self._one(url, transport)
                    except PermissionError:
                        raise
                    except Exception:
                        pass
            self._trim(wanted)
            return {u: self._have[u] for u in wanted if u in self._have}
        url = fill(self.url, **scalars(cfg))
        return self._one(url, transport) if url.strip() else None


    def _trim(self, wanted):
        """Let go of what is no longer wanted, oldest first, while there are too many pictures or too many bytes."""
        def over():
            return len(self._have) > self.keep or sum(len(v) for v in self._have.values()) > IMAGE_CACHE_BYTES
        for url in [u for u in self._have if u not in wanted]:
            if not over():
                break
            del self._have[url]
        for url in list(self._have):                       # still over: what is wanted is too much to keep
            if not over():
                break
            del self._have[url]


class SystemSource(Source):
    permission = "system"

    def __init__(self, name, what, every=30, path="C:/", path_key=None, standby_every=None):
        """what: "battery" -> {percent, charging, plugged, minutes_left}; "memory" -> {percent, used, total};
        "disk" -> {percent, used, total} of `path` (or of the setting named `path_key`); "cpu" -> {percent} since the
        last fetch."""
        if what not in ("battery", "memory", "disk", "cpu"):
            raise ValueError("SystemSource reads battery, memory, disk or cpu, not %r" % (what,))
        self.name, self.what, self.every, self.path, self.path_key = name, what, every, path, path_key
        self.standby_every = standby_every
        self._last_cpu = None

    def fetch(self, cfg, transport):
        if self.what == "disk":
            path = cfg.get(self.path_key) if self.path_key else None
            return self._disk(path if isinstance(path, str) and path else self.path)
        return getattr(self, "_" + self.what)()

    def _battery(self):
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [("ac", ctypes.c_ubyte), ("flag", ctypes.c_ubyte), ("percent", ctypes.c_ubyte),
                        ("saver", ctypes.c_ubyte), ("life", ctypes.c_ulong), ("full", ctypes.c_ulong)]
        st = Status()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st)) or st.percent == 255:
            return {"percent": None, "charging": False, "plugged": bool(st.ac == 1), "minutes_left": None}
        return {"percent": st.percent, "charging": bool(st.flag & 8), "plugged": st.ac == 1,
                "minutes_left": None if st.life == 0xFFFFFFFF else st.life // 60}

    def _memory(self):
        import ctypes

        class Mem(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("pt", ctypes.c_ulonglong), ("pa", ctypes.c_ulonglong),
                        ("vt", ctypes.c_ulonglong), ("va", ctypes.c_ulonglong), ("ve", ctypes.c_ulonglong)]
        m = Mem()
        m.length = ctypes.sizeof(m)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return {"percent": m.load, "used": m.total - m.avail, "total": m.total}

    def _disk(self, path):
        import shutil
        u = shutil.disk_usage(path)
        return {"percent": round(u.used / u.total * 100), "used": u.used, "total": u.total}

    def _cpu_times(self):
        import ctypes
        t = [ctypes.c_ulonglong() for _ in range(3)]
        ctypes.windll.kernel32.GetSystemTimes(*[ctypes.byref(x) for x in t])
        idle, kernel, user = (x.value for x in t)
        return idle, kernel + user

    def _cpu(self):
        idle, total = self._cpu_times()
        last, self._last_cpu = self._last_cpu, (idle, total)
        if not last or total == last[1]:
            return {"percent": None}
        return {"percent": round(100 * (1 - (idle - last[0]) / (total - last[1])))}


class SystemMediaSource(Source):
    permission = "media"

    def __init__(self, name="media", every=1.0, standby_every=0):
        """What this computer is playing (Spotify, a browser, anything in the volume flyout):
        {state: "playing" | "paused" | "idle" | "off", title, artist, app, duration, position, position_at (epoch seconds
        when `position` was true), can: ["previous", "play_pause", "next", "seek"], art: picture bytes or None}.
        Control it with the `media` action."""
        self.name, self.every, self._held = name, every, False
        self.standby_every = standby_every                    # a player nobody can see is not read (0: not until it wakes)

    def fetch(self, cfg, transport):
        from . import sysmedia
        if not self._held:
            sysmedia.acquire()
            self._held = True
        return sysmedia.snapshot()

    def close(self):
        if self._held:
            from . import sysmedia
            sysmedia.release()
            self._held = False


class Store:
    """Answers kept between fetches: a source is asked again only when it is due, and a failure keeps the last answer.

    `allow(permission) -> bool` decides sources that need one (the runtime's, from what the user allowed)."""

    def __init__(self, transport=None, clock=time.time, allow=None):
        self.transport, self.clock, self.allow = transport or Transport(), clock, allow
        self.data, self.errors, self._at, self._keys = {}, {}, {}, {}
        self.sources_seen = []

    def refresh(self, sources, cfg, standby=False):
        """Fetch what is due (in standby, what is due by each source's longer standby time). Returns (data by source
        name, errors by source name)."""
        now = self.clock()
        for s in sources:
            if s not in self.sources_seen:
                self.sources_seen.append(s)
            try:
                key = s.key(cfg)
            except Exception as e:                                   # a widget's own function: its mistake is a message
                self.errors[s.name] = "%s: %s" % (type(e).__name__, e)
                continue
            elapsed = now - self._at.get(s.name, -1e18)
            # Due again when the interval has passed, or the clock went back (a person set it earlier): never "wait
            # until it catches up".
            if s.name in self._at and 0 <= elapsed < s.interval(standby) and key == self._keys.get(s.name):
                continue
            self._keys[s.name] = key
            try:
                if s.permission and self.allow and not self.allow(s.permission):
                    raise PermissionError("%s needs the %r permission" % (s.name, s.permission))
                self.data[s.name] = self._keep_old(self.data.get(s.name), s.fetch(cfg, self.transport))
                self.errors.pop(s.name, None)
            except Exception as e:                                   # keep what we had
                self.errors[s.name] = str(e) or type(e).__name__
            self._at[s.name] = now
        return self.data, self.errors

    @staticmethod
    def _keep_old(old, new):
        """An item that failed this time keeps its last good values, marked "stale", rather than going blank."""
        if not (isinstance(old, list) and isinstance(new, list)):
            return new
        before = {o.get("item"): o for o in old if not o.get("error")}
        return [dict(before[n["item"]], stale=True) if n.get("error") and n.get("item") in before else n for n in new]

    def close(self):
        for s in self.sources_seen:
            s.close()

    def invalidate(self):
        """The settings changed: everything is due."""
        self._at.clear()
