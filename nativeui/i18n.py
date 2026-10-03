"""The English text of the interface (i18n_en.json: Traditional Chinese text -> English).

The interface is written in Traditional Chinese; with the language set to English every whole
text that has an entry is swapped. Names the user gave their devices are left alone.
"""
import json
import os
import sys

_table = None


def _load():
    global _table
    if _table is None:
        base = os.path.join(sys._MEIPASS, "nativeui") if hasattr(sys, "_MEIPASS") else os.path.dirname(
            os.path.abspath(__file__))
        try:
            with open(os.path.join(base, "i18n_en.json"), encoding="utf-8") as f:
                _table = json.load(f)
        except (OSError, ValueError):
            _table = {}
    return _table


def translate(text, language):
    """`text` in the interface language ('zh-TW' leaves it as it is)."""
    if language != "en" or not text:
        return text
    return _load().get(text.strip(), text)
