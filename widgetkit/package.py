"""Widgets as files people can share: a `.hawidget` is a zip of a folder with a manifest and the widget's code.

    my-widget/
        manifest.json    {"id": "dev.alice.ask", "name": "Ask", "version": "1.0", "kit": 1,
                          "entry": "main.py", "permissions": ["network:api.example.com"], "author": "Alice"}
        main.py          defines WIDGET (a WidgetDef)
        assets/...       pictures, fonts, anything the code reads

    export("my-widget", "ask.hawidget")          # checks the manifest, leaves out junk, refuses what is too big
    manifest = read_manifest("ask.hawidget")     # what it is and what it asks, WITHOUT running any of its code
    pkg = load("ask.hawidget")                   # unpacks, imports main.py, checks it matches its manifest
    pkg.widget                                   # the WidgetDef

Importing runs the widget's top-level code, so look at `read_manifest` (and show the ConsentCard) first and load only
what the user chose to add. The manifest is what the user is shown; a widget whose code asks for more than its
manifest says is refused. Archives with paths that climb out of their folder, or that are too large, are refused.
"""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass

from . import permissions as perms
from .definition import ID_RE, KIT_VERSION, WidgetDef

MAX_FILES, MAX_BYTES = 500, 50_000_000
JUNK = ("__pycache__", ".git", ".DS_Store", "Thumbs.db")
REQUIRED = ("id", "name", "version", "kit", "entry")
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,40}$")
ENTRY_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]{0,100}\.py$")
MAX_ARCHIVE_BYTES = 60_000_000


class PackageError(Exception):
    pass


@dataclass
class Package:
    widget: WidgetDef
    manifest: dict
    root: str


def _check_manifest(m):
    """The manifest, or why it is not one. Its id and version become file names, and its entry a path: all three are
    checked to be only what such a thing can safely be."""
    if not isinstance(m, dict):
        raise PackageError("manifest.json must be an object {...}")
    missing = [k for k in REQUIRED if k not in m]
    if missing:
        raise PackageError("manifest.json lacks: " + ", ".join(missing))
    if not isinstance(m["id"], str) or not ID_RE.match(m["id"]):
        raise PackageError("id must be a name like dev.alice.ask (letters, digits . _ -), not %r" % (m["id"],))
    if not isinstance(m["version"], str) or not VERSION_RE.match(m["version"]):
        raise PackageError("version must be text like 1.0 or 2.1.3, not %r" % (m["version"],))
    if not isinstance(m["name"], (str, dict)) or len(str(m["name"])) > 200:
        raise PackageError("name must be short text")
    if "author" in m and (not isinstance(m["author"], str) or len(m["author"]) > 100):
        raise PackageError("author must be short text")
    if not isinstance(m["kit"], int) or isinstance(m["kit"], bool) or m["kit"] > KIT_VERSION:
        raise PackageError("this widget needs a newer widget kit (%s; this is %s)" % (m["kit"], KIT_VERSION))
    entry = m["entry"]
    if not isinstance(entry, str) or not ENTRY_RE.match(entry) or ".." in entry.split("/") or "//" in entry:
        raise PackageError("entry must be a .py file inside the package (like main.py), not %r" % (entry,))
    if not isinstance(m.get("permissions", []), list):
        raise PackageError("permissions must be a list")
    try:
        perms.validate(m.get("permissions", []))
    except ValueError as e:
        raise PackageError(str(e))
    return m


def read_manifest(path):
    """The manifest of a folder or a .hawidget, checked, with no code run."""
    try:
        if os.path.isdir(path):
            with open(os.path.join(path, "manifest.json"), encoding="utf-8") as f:
                return _check_manifest(json.load(f))
        with zipfile.ZipFile(path) as z:
            return _check_manifest(json.loads(z.read("manifest.json").decode("utf-8")))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as e:
        if isinstance(e, PackageError):
            raise
        raise PackageError("not a widget package: %s" % e)


def export(folder, out):
    """Pack `folder` into `out` (a .hawidget)."""
    m = read_manifest(folder)
    if not os.path.isfile(os.path.join(folder, m["entry"])):
        raise PackageError("entry %r is not in the folder" % m["entry"])
    total = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        count = 0
        for here, dirs, files in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if d not in JUNK)
            for name in sorted(files):
                if name in JUNK or name.endswith(".pyc") or name.startswith(".studio-") or name.endswith(".fixtures.json"):
                    continue                              # not for sharing: caches, the studio's notes, test answers
                full = os.path.join(here, name)
                if os.path.islink(full):                  # a link could carry a file from outside the folder into the package
                    continue
                total += os.path.getsize(full)
                count += 1
                if total > MAX_BYTES or count > MAX_FILES:
                    raise PackageError("too large to share (limit: %d files, %d MB)" % (MAX_FILES, MAX_BYTES // 1_000_000))
                z.write(full, os.path.relpath(full, folder).replace("\\", "/"))
    return out


def unpack(path, cache):
    """Unpack a .hawidget under `cache` (once per distinct file); returns the folder. Runs none of its code."""
    try:
        size = os.path.getsize(path)
    except OSError as e:
        raise PackageError("not a widget package: %s" % e)
    if size > MAX_ARCHIVE_BYTES:
        raise PackageError("package is too large (%d MB at most)" % (MAX_ARCHIVE_BYTES // 1_000_000))
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    digest = h.hexdigest()[:16]
    root = os.path.join(cache, digest)
    if os.path.isdir(root):
        return root
    tmp = root + ".part"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_BYTES:
                raise PackageError("package is too large")
            base = os.path.realpath(tmp)
            for info in infos:
                if "\\" in info.filename or ":" in info.filename or info.filename.startswith("/"):
                    raise PackageError("package has a file name that is not plain: %r" % info.filename)
                target = os.path.realpath(os.path.join(tmp, info.filename))
                if not (target == base or target.startswith(base + os.sep)):
                    raise PackageError("package has a path outside itself: %r" % info.filename)
            z.extractall(tmp)
        os.replace(tmp, root)
    except zipfile.BadZipFile as e:
        raise PackageError("not a widget package: %s" % e)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return root


def wrap_file(py_path, folder):
    """A single Python file that defines WIDGET, as a package folder under `folder` (its manifest worked out from the widget,
    its code copied as main.py); returns the folder. The file's code is run once to read its WIDGET, as `load` would."""
    if not os.path.isfile(py_path) or os.path.getsize(py_path) > 2_000_000:
        raise PackageError("not a widget file: %s" % py_path)
    name = "hawidget_file_" + hashlib.sha1(os.path.abspath(py_path).encode()).hexdigest()[:10]
    spec = importlib.util.spec_from_file_location(name, py_path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except (Exception, SystemExit) as e:
        raise PackageError("the widget's code failed to load: %s: %s" % (type(e).__name__, e))
    widget = getattr(mod, "WIDGET", None)
    if not isinstance(widget, WidgetDef):
        raise PackageError("%s does not define WIDGET" % os.path.basename(py_path))
    if getattr(widget.draw, "__module__", name) != name:
        # its WIDGET comes from some other module (a test file that loads one, a file that imports another widget): that is
        # not this file's widget, and running such a file can do a great deal else
        raise PackageError("%s does not define its own widget: its draw function comes from %s"
                           % (os.path.basename(py_path), widget.draw.__module__))
    shutil.copyfile(py_path, os.path.join(folder, "main.py"))
    with open(os.path.join(folder, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"id": widget.id, "name": widget.name, "version": str(widget.version), "kit": KIT_VERSION,
                   "entry": "main.py", "author": "", "permissions": list(widget.permissions)}, f, ensure_ascii=False)
    return folder


def load(path, cache=None):
    """Unpack (if a .hawidget) and import the widget. Raises PackageError for anything that does not check out."""
    manifest = read_manifest(path)
    root = path if os.path.isdir(path) else unpack(path, cache or os.path.join(tempfile.gettempdir(), "hawidget-cache"))
    entry = os.path.join(root, manifest["entry"])
    name = "hawidget_" + hashlib.sha1((manifest["id"] + root).encode()).hexdigest()[:10]
    spec = importlib.util.spec_from_file_location(name, entry)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, root)
    try:
        spec.loader.exec_module(mod)
    except (Exception, SystemExit) as e:                       # a widget that calls exit() must not take the program with it
        raise PackageError("the widget's code failed to load: %s: %s" % (type(e).__name__, e))
    finally:
        if sys.path and sys.path[0] == root:
            sys.path.pop(0)
    widget = getattr(mod, "WIDGET", None)
    if not isinstance(widget, WidgetDef):
        raise PackageError("%s does not define WIDGET" % manifest["entry"])
    if widget.id != manifest["id"]:
        raise PackageError("code says %r, manifest says %r" % (widget.id, manifest["id"]))
    extra = [p for p in widget.permissions if p not in manifest.get("permissions", [])]
    if extra:
        raise PackageError("the code asks for permissions its manifest does not list: " + ", ".join(extra))
    widget.version = str(manifest["version"])
    return Package(widget, manifest, root)
