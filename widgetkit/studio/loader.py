"""Loading a widget from its file as a developer edits it: every load is fresh (the file, and any module beside it,
is imported again), and a mistake in the code comes back as a message to show, never as a crash of the studio."""
import importlib.util
import itertools
import os
import sys
import traceback

from ..definition import WidgetDef

_counter = itertools.count(1)


def entry_of(path):
    """The Python file for a path that is a file, or a package folder (its manifest names the entry)."""
    path = os.path.abspath(path)
    if os.path.isdir(path):
        import json
        with open(os.path.join(path, "manifest.json"), encoding="utf-8") as f:
            return os.path.join(path, json.load(f).get("entry", "main.py"))
    return path


PROTECTED = ("widgetkit", "nativeui", "core", "app", "winsys", "tests", "tools", "PySide6", "shiboken6", "main")


def _forget(root):
    """Drop modules loaded from beside the widget, so an edit to a helper file is seen too. Only what lies *directly*
    beside it (a helper file, or a helper package), and never the program's or the kit's own modules: a widget kept in
    the project folder must not make the studio forget the project."""
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None)
        top = name.split(".")[0]
        if not f or name == "__main__" or top in PROTECTED:
            continue
        here = os.path.dirname(os.path.abspath(f))
        if here == root or os.path.dirname(here) == root and os.path.basename(f) == "__init__.py":
            del sys.modules[name]


def load(path):
    """(WidgetDef, None) or (None, "what went wrong")."""
    try:
        entry = entry_of(path)
    except (OSError, ValueError) as e:
        return None, "cannot read %s: %s" % (path, e)
    root = os.path.dirname(entry)
    if not os.path.isfile(entry):
        return None, "no such file: %s" % entry
    _forget(root)
    name = "studio_widget_%d" % next(_counter)
    spec = importlib.util.spec_from_file_location(name, entry)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, root)
    try:
        spec.loader.exec_module(mod)
    except SyntaxError as e:
        return None, "SyntaxError in %s, line %s: %s\n%s" % (os.path.basename(e.filename or entry), e.lineno, e.msg,
                                                             (e.text or "").rstrip())
    except BaseException:
        return None, _short(traceback.format_exc(), root)
    finally:
        if root in sys.path:
            sys.path.remove(root)
        sys.modules.pop(name, None)
    widget = getattr(mod, "WIDGET", None)
    if not isinstance(widget, WidgetDef):
        return None, "%s does not define WIDGET (a WidgetDef)" % os.path.basename(entry)
    return widget, None


def _short(tb, root):
    """A traceback with the studio's own frames left out, so the first thing shown is the developer's line."""
    lines = tb.splitlines()
    keep, skip = [], False
    for line in lines:
        if line.startswith("  File "):
            skip = "widgetkit" + os.sep + "studio" in line or "importlib" in line or "<frozen" in line
        if not skip:
            keep.append(line.replace(root + os.sep, ""))
    return "\n".join(keep)
