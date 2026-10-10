"""The widgets a person has: the packages installed, and the copies of them placed (each with its own settings and its
own memory), kept in one folder the program owns.

    lib = Library(root)
    lib.register_builtin(WIDGET)                       # something that ships with the program
    manifest = lib.install("ask.hawidget")             # unpacks it; runs none of its code
    inst = lib.add("dev.alice.ask", {"endpoint": "..."})        # a copy; its id names its state
    rt = lib.runtime_for(inst["id"], services=...)      # loads the code now, builds the runtime with the user's
                                                        # settings, their permission answers and this copy's state
    lib.set_config(inst["id"], new_settings)            # saved; the runtime is told
    lib.remove(inst["id"])                               # the copy and its state go
    lib.uninstall("dev.alice.ask")                       # the package, its copies and the answers about it go

    root/packages/<hash>/   unpacked packages        root/instances.json    the copies
    root/grants.json        permission answers       root/state/<id>.json   each copy's memory

The program's own windows keep where each copy sits on the desktop in the same `instances.json` entry (extra keys are
kept as they are).
"""
import json
import os
import shutil
import uuid

from . import package
from .permissions import Grants
from .runtime import WidgetRuntime


class LibraryError(Exception):
    pass


class Library:
    def __init__(self, root):
        self.root = str(root)
        os.makedirs(self.root, exist_ok=True)
        self._file = os.path.join(self.root, "library.json")
        self.grants = Grants(os.path.join(self.root, "grants.json"))
        self.builtin = {}                    # widget id -> WidgetDef (not from a package)
        self._loaded = {}                    # widget id -> WidgetDef (imported from its package)
        data = self._read()
        self.installed = {i: e for i, e in (data.get("installed") or {}).items()
                          if isinstance(e, dict) and isinstance(e.get("manifest"), dict) and isinstance(e.get("path"), str)}
        self.instances = [i for i in (data.get("instances") or []) if isinstance(i, dict) and isinstance(i.get("id"), str)
                          and isinstance(i.get("widget"), str) and isinstance(i.get("config", {}), dict)]
        self.notes = []                                   # things a person should be told about the last install

    # ------------------------------------------------------------------ files
    def _read(self):
        try:
            with open(self._file, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save(self):
        tmp = self._file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"installed": self.installed, "instances": self.instances}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._file)

    def state_path(self, instance_id):
        return os.path.join(self.root, "state", instance_id + ".json")

    # ------------------------------------------------------------------ what is available
    def register_builtin(self, widget):
        self.builtin[widget.id] = widget

    def available(self):
        """[(widget id, name, version, builtin?)] for everything that can be added."""
        out = [(w.id, w.name, w.version, True) for w in self.builtin.values()]
        out += [(i, e["manifest"]["name"], e["manifest"]["version"], False) for i, e in self.installed.items()]
        return out

    def install(self, path):
        """Unpack a package into the library (replacing an older version of the same widget). Nothing is run."""
        manifest = package.read_manifest(path)
        if manifest["id"] in self.builtin:
            raise LibraryError("%s is built in" % manifest["id"])
        root = os.path.join(self.root, "packages")
        if os.path.isdir(path):
            dest = os.path.join(root, "%s-%s" % (manifest["id"], manifest["version"]))
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(path, dest, ignore=shutil.ignore_patterns(*package.JUNK, "*.pyc"))
        else:
            os.makedirs(root, exist_ok=True)
            dest = package.unpack(path, root)
        old = self.installed.get(manifest["id"])
        self.notes = []
        if old and old["manifest"].get("author") != manifest.get("author"):
            # The same id from someone else is not an update of the same widget: what was allowed to the old one is not
            # allowed to this one, and the person is asked again.
            self.grants.table.pop(manifest["id"], None)
            self.grants.save()
            self.notes.append("%s now comes from %r (it was %r): its permissions will be asked again"
                              % (manifest["id"], manifest.get("author"), old["manifest"].get("author")))
        self.installed[manifest["id"]] = {"manifest": manifest, "path": dest}
        self._loaded.pop(manifest["id"], None)
        self.save()
        if old and old["path"] != dest:
            shutil.rmtree(old["path"], ignore_errors=True)
        return manifest

    def widget(self, widget_id):
        """The WidgetDef for an id: built in, or the installed package's code imported now."""
        if widget_id in self.builtin:
            return self.builtin[widget_id]
        if widget_id not in self._loaded:
            entry = self.installed.get(widget_id)
            if not entry:
                raise LibraryError("no such widget: %s" % widget_id)
            self._loaded[widget_id] = package.load(entry["path"]).widget
        return self._loaded[widget_id]

    def pending_permissions(self, widget_id):
        """What the user has not yet answered for this widget, from its manifest (no code is run to find out)."""
        if widget_id in self.builtin:
            w = self.builtin[widget_id]
            return self.grants.pending(w)
        manifest = self.installed[widget_id]["manifest"]
        stand_in = type("W", (), {"id": widget_id, "permissions": tuple(manifest.get("permissions", []))})
        return self.grants.pending(stand_in)

    # ------------------------------------------------------------------ copies
    def add(self, widget_id, config=None, **extra):
        if widget_id not in self.builtin and widget_id not in self.installed:
            raise LibraryError("no such widget: %s" % widget_id)
        inst = {"id": uuid.uuid4().hex[:8], "widget": widget_id, "config": dict(config or {})}
        inst.update(extra)
        self.instances.append(inst)
        self.save()
        return inst

    def instance(self, instance_id):
        for i in self.instances:
            if i["id"] == instance_id:
                return i
        raise LibraryError("no such copy: %s" % instance_id)

    def set_config(self, instance_id, config, runtime=None):
        self.instance(instance_id)["config"] = dict(config)
        self.save()
        if runtime:
            runtime.set_config(config)

    def remove(self, instance_id):
        self.instances.remove(self.instance(instance_id))
        self.save()
        try:
            os.remove(self.state_path(instance_id))
        except OSError:
            pass

    def uninstall(self, widget_id):
        for inst in [i for i in self.instances if i["widget"] == widget_id]:
            self.remove(inst["id"])
        entry = self.installed.pop(widget_id, None)
        self._loaded.pop(widget_id, None)
        self.builtin.pop(widget_id, None)
        if entry:
            shutil.rmtree(entry["path"], ignore_errors=True)
        self.grants.table.pop(widget_id, None)
        self.grants.save()
        self.save()

    def size_of(self, instance_id):
        """The size a copy is placed at: the one saved with it if its widget supports that, else the widget's own."""
        inst = self.instance(instance_id)
        widget = self.widget(inst["widget"])
        return inst["size"] if inst.get("size") in widget.supported_sizes() else widget.size

    def runtime_for(self, instance_id, **kw):
        """A runtime for one copy: its widget, settings, permission answers and own state. `kw` go to WidgetRuntime."""
        inst = self.instance(instance_id)
        return WidgetRuntime(self.widget(inst["widget"]), inst["config"], grants=self.grants,
                             state_path=self.state_path(instance_id), **kw)
