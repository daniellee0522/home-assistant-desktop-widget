"""What a widget may do beyond showing things, who decides, and what is remembered.

A widget declares the permissions it needs (`WidgetDef.permissions`, and the package's manifest). The user is shown
them when they add the widget (`consent.ConsentCard`) and each can be allowed or refused. An Action is performed
only if its permission was declared AND allowed; otherwise it raises `PermissionDenied` and nothing happens.

    network:api.example.com     talk to that host ("*.example.com" matches its subdomains)
    launch:C:/Windows/notepad.exe   run exactly that program
    clipboard                   put text on the clipboard
    microphone                  record sound
    system                      read this computer's battery, memory, disk and CPU use
    app:outlookcal              open a Windows app by its address scheme (outlookcal: the Calendar, ms-clock: Clock)
    media                       see what this computer is playing, and pause, skip and seek it

Opening a web address in the browser, choosing a file with the system's chooser, and files the user drops on the
widget need no permission: the user does each of them in the act.

What this does not do: widget code is Python running in the program, so it can do anything Python can. These
permissions bound what the *kit's actions* will do for a widget, and tell the user honestly what it asks; they are
not a sandbox. Add only widgets from people you trust.
"""
import ipaddress
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

PERMISSION_KINDS = {"network": True, "launch": True, "clipboard": False, "microphone": False, "system": False,
                   "app": True, "media": False}
RISKY = ("launch", "microphone")


class PermissionDenied(PermissionError):
    """A permission was not declared or not allowed. A PermissionError, so no source swallows it as a plain failure."""


HOST_RE = re.compile(r"^(\*|(\*\.)?[a-z0-9]([a-z0-9.-]*[a-z0-9])?|[0-9a-f:.]+)$")
SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*$")


def parse(perm):
    """(kind, argument or None); ValueError for something the kit does not know or that is spelt oddly (a host is a
    name, "*.name" or "*": no other wildcards)."""
    if not isinstance(perm, str):
        raise ValueError("a permission is text, not %r" % (perm,))
    kind, sep, arg = perm.partition(":")
    if kind not in PERMISSION_KINDS or PERMISSION_KINDS[kind] != bool(sep and arg):
        raise ValueError("unknown permission %r" % (perm,))
    if kind == "network" and not HOST_RE.match(arg.lower()):
        raise ValueError("not a host name: %r (use name.com, *.name.com or *)" % arg)
    if kind == "app" and not SCHEME_RE.match(arg.lower()):
        raise ValueError("not an address scheme: %r" % arg)
    return kind, (arg if sep else None)


def validate(perms):
    for p in perms:
        parse(p)
    return tuple(perms)


def norm_path(path):
    return os.path.normcase(os.path.normpath(os.path.expandvars(str(path)))).replace("\\", "/")


def is_private_host(host):
    """A host that is on this computer or this network, not out on the internet: an IP literal in a private, loopback,
    link-local or reserved range, `localhost`, and the names networks keep to themselves."""
    h = host.lower().strip("[]").rstrip(".")
    try:
        ip = ipaddress.ip_address(h)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    except ValueError:
        pass
    return h == "localhost" or h.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa", ".corp"))


def need_network(url):
    """The permission needed to read `url`: only http and https addresses, and always a named host."""
    parts = urlparse(url)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("only http and https addresses are read: %r" % (url,))
    if not parts.hostname:
        raise ValueError("no host in %r" % (url,))
    return "network:" + parts.hostname.lower().rstrip(".")


def host_matches(pattern, host):
    """`pattern` (name, *.name or *) against a host. "*" is the internet: it does not reach this computer or this
    network (name those hosts exactly to allow them)."""
    pattern, host = pattern.lower(), host.lower()
    if pattern == "*":
        return not is_private_host(host)
    if pattern.startswith("*."):
        return host.endswith(pattern[1:])
    return pattern == host


def need_app(uri):
    return "app:" + str(uri).partition(":")[0].lower()


def need_launch(path):
    return "launch:" + norm_path(path)


def covers(declared, needed):
    """Does a declared permission cover a needed one?"""
    dk, da = parse(declared)
    nk, na = parse(needed)
    if dk != nk:
        return False
    if da is None:
        return True
    if dk == "launch":
        return norm_path(da) == norm_path(na)
    if dk == "network":
        return host_matches(da, na)
    return da.lower() == na.lower()


def describe(perm, lang="en"):
    kind, arg = parse(perm)
    zh = lang.startswith("zh")
    apps = {"outlookcal": ("行事曆", "Calendar"), "outlookmail": ("郵件", "Mail"), "ms-clock": ("時鐘", "Clock"),
            "ms-settings": ("設定", "Settings")}
    any_site = arg == "*"
    return {"network": ("連線到任何網站" if any_site else "連線到 %s" % arg,
                        "Connect to any website" if any_site else "Connect to %s" % arg),
            "launch": ("執行程式 %s" % arg, "Run the program %s" % arg),
            "clipboard": ("寫入剪貼簿", "Put text on the clipboard"),
            "microphone": ("使用麥克風錄音", "Record from the microphone"),
            "system": ("讀取電池、記憶體、磁碟與 CPU 狀態", "Read battery, memory, disk and CPU use"),
            "app": ("開啟「%s」應用程式" % apps.get(arg, (arg, arg))[0], "Open the %s app" % apps.get(arg, (arg, arg))[1]),
            "media": ("查看並控制這台電腦正在播放的內容", "See and control what this computer is playing")}[kind][0 if zh else 1]


def icon_of(perm):
    return {"network": "mdi:web", "launch": "mdi:application-outline", "clipboard": "mdi:content-copy",
            "microphone": "mdi:microphone", "system": "mdi:chip", "app": "mdi:application-outline",
            "media": "mdi:play-box-outline"}[parse(perm)[0]]


def is_risky(perm):
    kind, arg = parse(perm)
    return kind in RISKY or (kind == "network" and arg == "*")


class Grants:
    """The user's decisions, per widget, kept in a small JSON file (or only in memory when `path` is None).

    A widget whose declared permissions change is asked again about the ones that are new."""

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.table = {}
        if self.path and self.path.exists():
            try:
                self.table = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.table = {}

    def _entry(self, widget_id):
        return self.table.setdefault(widget_id, {"granted": [], "denied": []})

    def decided(self, widget):
        e = self.table.get(widget.id, {})
        return set(e.get("granted", [])) | set(e.get("denied", []))

    def pending(self, widget):
        """Declared permissions the user has not answered yet."""
        return [p for p in widget.permissions if p not in self.decided(widget)]

    def decide(self, widget, allow, deny=()):
        e = self._entry(widget.id)
        e["granted"] = sorted(set(allow) & set(widget.permissions))
        e["denied"] = sorted(set(deny) & set(widget.permissions))
        self.save()

    def revoke(self, widget):
        self.table.pop(widget.id, None)
        self.save()

    def allowed(self, widget, needed):
        """Is `needed` covered by a permission the widget declared and the user allowed?"""
        granted = self.table.get(widget.id, {}).get("granted", [])
        return any(p in widget.permissions and covers(p, needed) for p in granted)

    def require(self, widget, needed):
        """Raise PermissionDenied unless `needed` is declared by the widget and allowed by the user."""
        if not self.allowed(widget, needed):
            declared = any(covers(p, needed) for p in widget.permissions)
            raise PermissionDenied("%s: %s %s" % (widget.id, needed, "was not allowed" if declared else "was not declared"))

    def save(self):
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.table, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
