"""The running build's identity, independent of which shortcut launched it."""
import json
from pathlib import Path
import re
import sys


def running_version():
    try:
        if getattr(sys, "frozen", False):
            value = json.loads((Path(sys.executable).parent / "build-info.json").read_text(encoding="utf-8"))["version"]
        else:
            value = (Path(__file__).resolve().parent / "VERSION").read_text(encoding="utf-8-sig").strip()
        return value if isinstance(value, str) and re.fullmatch(r"\d+\.\d+\.\d+", value) else "dev"
    except (OSError, ValueError, KeyError):
        return "dev"
