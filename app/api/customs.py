"""Widgets people write with the widget kit (widgetkit/) and import as .hawidget files: the packages installed, what a
copy on the desktop is set to, and what the user allowed each of them. A copy's settings live in the config beside
its place (`widget["custom"]`); the packages, the permission answers and each copy's memory live in the kit's own
folder beside the config (widget_library/, widgetkit.library.Library; not the kit's own source folder)."""

import copy
import os
import tempfile
import threading

from core import config as cfgmod
from widgetkit import package
from widgetkit import permissions as perms
from widgetkit.definition import text_of
from widgetkit.library import Library, LibraryError
from winsys import qtshell


class CustomsMixin:
    def _init_customs(self):
        self._library = None
        self._library_lock = threading.RLock()

    # -- the library -------------------------------------------------------------------------------------------------
    def _lib(self):
        with self._library_lock:
            if self._library is None:
                self._library = Library(os.path.join(os.path.dirname(os.path.abspath(cfgmod.CONFIG_FILE)), "widget_library"))
            return self._library

    def _lang(self):
        return "zh" if str(self._cfg.get("language", "zh-TW")).startswith("zh") else "en"

    def _custom_of(self, widget_id):
        """The widget's `custom` entry ({"widget", "config"}), or None when it is not one."""
        w = self._widget_cfg(widget_id)
        return w.get("custom") if w is not None and w.get("kind") == "custom" else None

    def _custom_def(self, widget_id):
        """The WidgetDef a desktop copy runs, or None (the package is gone, or its code no longer loads)."""
        entry = self._custom_of(widget_id)
        if not entry:
            return None
        try:
            return self._lib().widget(entry["widget"])
        except (LibraryError, package.PackageError):
            return None

    def custom_prefs(self, widget):
        """What a desktop window needs to know of a copy, as plain data (see `_prefs`): which package, its settings, and
        which permissions are allowed (so that it asks its sources again when they change)."""
        entry = widget.get("custom") or {}
        table = self._lib().grants.table.get(entry.get("widget"), {})
        return {"widget": entry.get("widget", ""), "config": copy.deepcopy(entry.get("config", {})),
                "granted": sorted(table.get("granted", []))}

    # -- packages ------------------------------------------------------------------------------------------------------
    def import_custom_widget(self, path):
        """Install a .hawidget, a folder with a manifest, or one .py file that defines WIDGET. Its code is loaded once to check it works; a package that
        does not load is taken out again. -> {"ok", "id", "name", "notes"} or {"ok": False, "error"}."""
        lib, settings_file = self._lib(), cfgmod.CONFIG_FILE
        try:
            if str(path).lower().endswith(".py"):               # one Python file that defines WIDGET: wrapped as a package
                path = package.wrap_file(str(path), tempfile.mkdtemp(prefix="widget-file-"))
            manifest = lib.install(str(path))
            try:
                lib.widget(manifest["id"])
            except package.PackageError:
                lib.uninstall(manifest["id"])
                raise
        except (package.PackageError, LibraryError, OSError) as e:
            return {"ok": False, "error": str(e)}
        finally:
            if cfgmod.CONFIG_FILE != settings_file:        # code that ran while loading moved the settings file: put it back
                cfgmod.CONFIG_FILE = settings_file
        if any((w.get("custom") or {}).get("widget") == manifest["id"] for w in self._cfg.get("widgets", [])):
            self._push_prefs()                      # a newer version of one already placed: its copies take it up
        return {"ok": True, "id": manifest["id"], "name": text_of(manifest["name"], self._lang()),
                "notes": list(lib.notes)}

    def custom_widgets(self):
        """The packages installed, for the editor's palette."""
        lib, out = self._lib(), []
        for pkg_id, entry in lib.installed.items():
            m = entry["manifest"]
            try:
                size = lib.widget(pkg_id).size
            except (LibraryError, package.PackageError):
                size = "2x2"
            copies = sum(1 for w in self._cfg.get("widgets", []) if (w.get("custom") or {}).get("widget") == pkg_id)
            out.append({"id": pkg_id, "name": text_of(m["name"], self._lang()), "version": str(m.get("version", "")),
                        "author": str(m.get("author", "")), "size": size, "copies": copies})
        return out

    def custom_definition(self, pkg_id):
        """A package's WidgetDef (the editor draws its thumbnail from it), or None when it will not load."""
        try:
            return self._lib().widget(pkg_id)
        except (LibraryError, package.PackageError):
            return None

    def uninstall_custom_widget(self, pkg_id):
        """The package, its permission answers and every copy of it on the desktop. A desktop never ends up with no widget:
        the last one that held it becomes an empty widget of tiles in the same place."""
        for w in [w for w in self._cfg.get("widgets", []) if (w.get("custom") or {}).get("widget") == pkg_id]:
            if len(self._cfg.get("widgets", [])) > 1:
                self.remove_widget(w["id"])
            else:
                self._unwrap(w)
        self._lib().uninstall(pkg_id)
        self._push_prefs()
        return True

    def _unwrap(self, widget):
        widget.update(kind="tiles", tiles=[])
        widget.pop("custom", None)
        self._forget_custom_state(widget["id"])
        cfgmod.save_config(self._cfg)

    def _forget_custom_state(self, widget_id):
        try:
            os.remove(self._lib().state_path(widget_id))
        except OSError:
            pass

    # -- a copy on the desktop -------------------------------------------------------------------------------------------
    def custom_info(self, widget_id):
        """Everything the editor shows of a copy: its fields with their values, its sizes and its permissions."""
        entry, wd = self._custom_of(widget_id), self._custom_def(widget_id)
        if not entry:
            return {"ok": False, "error": "not a widget of the kit"}
        if wd is None:
            return {"ok": False, "error": "its package is missing or does not load", "package": entry["widget"]}
        lang = self._lang()
        decided = self._lib().grants.table.get(wd.id, {})
        return {"ok": True, "package": wd.id, "name": text_of(wd.name, lang), "version": wd.version,
                "size": self._widget_cfg(widget_id)["size"], "sizes": list(wd.supported_sizes()),
                "config": wd.settings(entry["config"]), "fields": [self._field_info(f, lang) for f in wd.config],
                "permissions": [{"perm": p, "text": perms.describe(p, lang), "risky": perms.is_risky(p),
                                 "icon": perms.icon_of(p),
                                 "state": "granted" if p in decided.get("granted", []) else
                                          "denied" if p in decided.get("denied", []) else "pending"}
                                for p in wd.permissions]}

    @staticmethod
    def _field_info(f, lang):
        return {"key": f.key, "type": f.type, "label": text_of(f.label, lang) or f.key, "help": text_of(f.help, lang),
                "options": [{"value": o, "text": f.shown(o, lang)} for o in f.options], "min": f.minimum, "max": f.maximum,
                "step": f.step}

    def set_custom_value(self, widget_id, key, value):
        """One setting of a copy (cleaned the way its field takes it); only that copy changes."""
        entry, wd = self._custom_of(widget_id), self._custom_def(widget_id)
        field = next((f for f in wd.config if f.key == key), None) if wd else None
        if not entry or field is None:
            return False
        entry["config"][key] = field.clean(value)
        cfgmod.save_config(self._cfg)
        self._push_prefs()
        return True

    def set_custom_permissions(self, widget_id, allowed):
        """The user's answer to what a widget asked for: `allowed` are permitted, the rest of what it declared are not."""
        wd = self._custom_def(widget_id)
        if wd is None:
            return False
        allowed = set(allowed or ())
        self._lib().grants.decide(wd, allowed, set(wd.permissions) - allowed)
        self._push_prefs()
        return True

    def choose_and_import_custom_widget(self):
        """The file dialog, then `import_custom_widget` of what was chosen; None when nothing was."""
        zh = self._lang() == "zh"
        path = qtshell.choose_widget_file("選擇要匯入的 Widget 檔案" if zh else "Choose a widget file to import")
        return self.import_custom_widget(path) if path else None

    def choose_images(self, limit=10):
        """The file dialog for pictures (a setting of the kind "images"): the paths chosen, at most `limit`."""
        zh = self._lang() == "zh"
        return qtshell.choose_image_files("選擇圖片" if zh else "Choose pictures")[:max(0, int(limit))]

    def custom_preview_runtime(self, widget_id, **kw):
        """A runtime for the editor's preview of a copy: its settings and what it was allowed, its memory as it is now, and
        no way to change that memory (what the preview does is not kept)."""
        rt = self.custom_runtime(widget_id, **kw)
        if rt is not None:
            rt.state_path = None
        return rt

    def custom_runtime(self, widget_id, **kw):
        """A runtime for a copy (the desktop window's, on the GUI thread), or None. `kw` go to WidgetRuntime."""
        entry, wd = self._custom_of(widget_id), self._custom_def(widget_id)
        if not entry or wd is None:
            return None
        from widgetkit.runtime import WidgetRuntime
        lib = self._lib()
        return WidgetRuntime(wd, entry["config"], grants=lib.grants, state_path=lib.state_path(widget_id),
                             lang=self._lang(), **kw)
