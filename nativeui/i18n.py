"""The English text of the interface (i18n_en.json: Traditional Chinese text -> English).

The interface is written in Traditional Chinese; with the language set to English every whole
text that has an entry is swapped. Names the user gave their devices are left alone.
"""
import json
import os
import re
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


# Sentences with a number in them cannot each be in the table: (Traditional Chinese pattern, English).
_COUNTED = [(re.compile(p), e) for p, e in (
    (r"過去 (\d+) 小時", r"Last \1 hours"), (r"(\d+) 個開著", r"\1 on"), (r"(\d+) 個未鎖上", r"\1 unlocked"),
    (r"(\d+) 個播放中", r"\1 playing"), (r"(\d+) 台攝影機", r"\1 cameras"),
    (r"(\d+) 個配件　顯示", r"\1 devices  shown"))]


def translate(text, language):
    """`text` in the interface language ('zh-TW' leaves it as it is)."""
    if language != "en" or not text:
        return text
    found = _load().get(text.strip())
    if found is not None:
        return found
    for pattern, english in _COUNTED:
        if pattern.fullmatch(text.strip()):
            return pattern.sub(english, text.strip())
    return text
