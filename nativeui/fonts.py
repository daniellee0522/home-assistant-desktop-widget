"""Fonts installed on this computer, for the clock's digits (chosen per clock in the widget editor).

Qt's FreeType engine, which the app uses, sees only the fonts in Windows' own folder, not those installed
for one user; so a font is taken from its file, which the registry names, when it is first used.
"""
import os
import re
import winreg

from PySide6.QtGui import QFont, QFontDatabase

# What a clock uses when none is chosen, where it is installed.
DEFAULT_NAME = "SF Pro Freeze"
# Icon and symbol fonts (no digits to show), and slanted faces (not for a clock's digits).
_SKIP = re.compile(r"symbol|wingdings|webdings|marlett|mdl2|icons?\b|emoji|holomdl|bookshelf|italic|oblique", re.I)
_KEYS = ((winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"),
         (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"))
_installed = None
_loaded = {}


def installed():
    """[{"file", "name"}] of the fonts installed, by name: the registry's own names ("SF Compact Rounded
    Medium"), without "(TrueType)"."""
    global _installed
    if _installed is None:
        found = {}
        windir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        for root, key in _KEYS:
            try:
                k = winreg.OpenKey(root, key)
            except OSError:
                continue
            with k:
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    i += 1
                    path = value if os.path.isabs(str(value)) else os.path.join(windir, str(value))
                    if not str(path).lower().endswith((".ttf", ".otf", ".ttc")):
                        continue
                    name = re.sub(r"\s*\((TrueType|OpenType)\);?\s*$", "", name).strip()
                    if (name and "\ufffd" not in name and not _SKIP.search(name)
                            and os.path.exists(path)):
                        found.setdefault(name, path)
        _installed = [{"file": f, "name": n} for n, f in sorted(found.items(), key=lambda kv: kv[0].lower())]
    return _installed


def default():
    """The font a clock uses when none is chosen, if installed."""
    return next((f for f in installed() if f["name"].startswith(DEFAULT_NAME)), None)


def load(choice):
    """(family, style) of a font {"file", "name"}, read from its file once; None if it can't be (gone,
    unreadable, or without digits)."""
    if not choice or not choice.get("file"):
        return None
    key = choice["file"], choice.get("name", "")
    if key not in _loaded:
        _loaded[key] = None
        fid = QFontDatabase.addApplicationFont(choice["file"])
        families = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        name = choice.get("name", "")
        # A collection (.ttc) holds several families: the one the name starts with.
        family = max(families, key=lambda f: len(f) if name.lower().startswith(f.lower()) else -1, default=None)
        if family:
            styles = QFontDatabase.styles(family)
            rest = name[len(family):].strip().lower() if name.lower().startswith(family.lower()) else ""
            style = next((s for s in styles if s.lower() == rest), None) or \
                next((s for s in styles if s.lower() in ("regular", "normal", "book")), None) or \
                (styles[0] if styles else "")
            f = QFontDatabase.font(family, style, 12)
            if _has_digits(f):
                _loaded[key] = (family, style)
    return _loaded[key]


def _has_digits(f):
    from PySide6.QtGui import QFontMetricsF
    m = QFontMetricsF(f)
    return all(m.inFont(c) for c in "0123456789")


def qfont(face, px):
    """The font (family, style) at `px`, drawn ten times bigger as render.font is (render.text_path)."""
    f = QFontDatabase.font(face[0], face[1], 12)
    f.setPixelSize(max(10, round(px * 10)))
    f.setStyleStrategy(QFont.PreferAntialias | QFont.NoSubpixelAntialias)
    f.setHintingPreference(QFont.PreferNoHinting)
    return f
