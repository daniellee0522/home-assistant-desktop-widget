"""The English text of the desktop widget, from the page's own dictionary (web/i18n.js).

The widget's texts are written in Traditional Chinese; with the language set to English the page
swaps every whole text it has an entry for. Names the user gave their devices are left alone.
"""
import os
import re
import sys

_table = None
_PAIR = re.compile(r"'((?:\\.|[^'\\])*)'\s*:\s*'((?:\\.|[^'\\])*)'")


def _unescape(text):
    return re.sub(r"\\(.)", r"\1", text)


def _load():
    global _table
    if _table is None:
        _table = {}
        base = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "web")
        try:
            with open(os.path.join(base, "i18n.js"), encoding="utf-8") as f:
                source = f.read()
            block = source[source.index("const EN_TEXT = {"):]
            block = block[:block.index("\n};")]
            for key, value in _PAIR.findall(block):
                _table[_unescape(key)] = _unescape(value)
        except (OSError, ValueError):
            pass
    return _table


def translate(text, language):
    """`text` in the interface language ('zh-TW' leaves it as it is)."""
    if language != "en" or not text:
        return text
    return _load().get(text.strip(), text)
