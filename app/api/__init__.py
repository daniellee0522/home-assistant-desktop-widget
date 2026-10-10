"""What every window works through: the config, Home Assistant, the windows' places and glass.

`Api` is assembled from mixins, one per concern (the windows it holds, preferences, the widgets, Home Assistant,
the tray panel, the card and Settings, glass, the backdrop, dimming). Each mixin sets up its own state in an
`_init_*` method and owns the methods that use it. The public methods are what the windows (nativeui/) call,
usually from a thread of their own; anything that touches a window is marshalled onto the GUI thread. Anything
prefixed with `_` is the program's own.
"""

import os

from .backdrop import BackdropMixin
from .customs import CustomsMixin
from .flyout import FlyoutMixin
from .glass import GlassMixin
from .ha import HomeAssistantMixin
from .idle import IdleMixin
from .popover import PopoverMixin
from .prefs import PrefsMixin
from .widgets import WidgetsMixin
from .windows import WindowsMixin


class Api(WindowsMixin, PrefsMixin, WidgetsMixin, CustomsMixin, HomeAssistantMixin, FlyoutMixin, PopoverMixin, GlassMixin,
          BackdropMixin, IdleMixin):
    """`cfg`: the settings (read from the settings file when None); `client`: a Home Assistant client to use
    instead of making one; `start`: configure and start the client (a test gives False)."""

    def __init__(self, cfg=None, client=None, start=True):
        self._init_prefs(cfg)
        self._init_windows()
        self._init_widgets()
        self._init_customs()
        self._init_glass()
        self._init_flyout()
        self._init_popover()
        self._init_idle()
        self._init_ha(client, start)

    def quit_app(self):
        self._quit()

    def _quit(self):
        from app.capture import compat_capture
        try:
            self._client.stop()
        except Exception:
            pass
        try:
            if self._tray_icon:
                self._tray_icon.stop()
        except Exception:
            pass
        for window in list(self._widgets.values()):
            try:
                window.destroy()
            except Exception:
                pass
        compat_capture.close()
        os._exit(0)
