"""
HA Desktop Widgets (Qt edition)
===============================

A borderless desktop widget that mirrors Home Assistant accessories as a
tile grid, with realtime updates over Home Assistant's WebSocket API. It
lives at the bottom of the z-order like a desktop gadget and never takes
focus away from other applications.

Every window is drawn natively (nativeui/), with no browser page, and shares one Api instance (app/api/):

  * widgets  - the widgets on the desktop (nativeui.widget)
  * popover  - an accessory's detail card, opened by right-click or hold (nativeui.detail)
  * settings - connection, appearance and the widget editor (nativeui.settings)
  * flyout   - the tray panel, opened by clicking the tray icon (nativeui.panel)

The card, the panel and Settings are made when first wanted and released after a while unused.
The Api tells a window something with `window.send(name, *args)` (see nativeui/overlay.py), and
the windows call the Api's public methods.

Settings are saved to ha_widgets_config.json beside this script, or under
%APPDATA%/HA Widgets for an installed build (see core/config.py). Closing the
widget hides it; use the tray menu's Quit to exit.

This file only prepares the process (what has to happen before Qt or Pillow load); the program is app/lifecycle.py.

Run:  python main.py
"""

import ctypes
import os
import sys

# Pillow imports numpy when it finds it, only to name a type: about 10 MB of memory for nothing.
sys.modules.setdefault("numpy", None)
sys.modules.setdefault("numpy.typing", None)

if sys.platform == "win32":
    # Must happen before Qt creates anything. Per-monitor-v2 awareness keeps
    # every Win32 coordinate in physical pixels on mixed-DPI setups.
    try:
        _set_ctx = ctypes.WinDLL("user32").SetProcessDpiAwarenessContext
        _set_ctx.argtypes = [ctypes.c_void_p]
        _set_ctx.restype = ctypes.c_int
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if not _set_ctx(ctypes.c_void_p(-4)):
            raise OSError("SetProcessDpiAwarenessContext failed")
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        except Exception:
            pass

# Glyphs from the font files rather than DirectWrite, which copies a whole CJK font
# (about 40 MB) into the process the first time one is used.
os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=freetype")

if __name__ == "__main__":
    from app.lifecycle import run
    run()
