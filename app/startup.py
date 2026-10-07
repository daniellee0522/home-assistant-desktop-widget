"""Small things about how the program is started and what size its windows start at."""

import os
import sys

from winsys import hotkey as hotkeymod


# The smallest size any window is set to.
MIN_WINDOW_W = 80
MIN_WINDOW_H = 60


def valid_hotkey(text):
    """A shortcut as hotkey.py writes it, "" for none; anything else is refused (ValueError)."""
    value = hotkeymod.normalise(text)
    if value is None:
        raise ValueError("not a shortcut: %r" % (text,))
    return value


def startup_command():
    """The command line for the "start with Windows" Run key."""
    if getattr(sys, "frozen", False):
        return '"%s"' % sys.executable
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    return '"%s" "%s"' % (pythonw, os.path.abspath(__file__))


def widget_initial_size(size, zoom):
    """Only the size until the window's first measurement; close is better.
    Every side is a whole number of tile cells."""
    from nativeui import render as native_render
    w, h = native_render.widget_size(size)
    try:
        factor = max(50, min(200, int(zoom))) / 100.0
    except Exception:
        factor = 1.0
    return max(MIN_WINDOW_W, int(w * factor)), max(MIN_WINDOW_H, int(h * factor))
