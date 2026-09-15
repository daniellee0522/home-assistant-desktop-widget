"""System tray icon for the HA desktop widget.

The icon is deliberately a monochrome glyph rather than a little coloured
logo: that is what the Windows 11 notification area looks like, and an app
icon with its own background chip sits in that row like a sticker. It is
drawn from Segoe Fluent Icons - the font Windows itself uses for these -
and it follows the taskbar between light and dark.
"""

import threading

import pystray
from PIL import Image, ImageDraw, ImageFont

# Segoe Fluent Icons (Windows 11), then Segoe MDL2 Assets (Windows 10).
# Same codepoint for "Home" in both.
_ICON_FONTS = (
    r"C:\Windows\Fonts\SegoeIcons.ttf",
    r"C:\Windows\Fonts\segmdl2.ttf",
)
_HOME_GLYPH = "\ue80f"

# The tray is drawn at 16pt; this is that at 200%, which downscales
# cleanly to whatever the display actually asks for.
_SIZE = 32


def _taskbar_is_light():
    """True when the taskbar is the light one, so the glyph must be dark.

    Windows keeps the taskbar's own light/dark setting separate from the
    one apps follow (AppsUseLightTheme), and it is the taskbar's that
    decides what colour is legible here.
    """
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        try:
            value, _ = winreg.QueryValueEx(key, "SystemUsesLightTheme")
            return bool(value)
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False        # dark taskbar is the Windows 11 default


def _glyph_font(px):
    for path in _ICON_FONTS:
        try:
            return ImageFont.truetype(path, px)
        except Exception:
            continue
    return None


def _make_image(light_taskbar=None):
    if light_taskbar is None:
        light_taskbar = _taskbar_is_light()
    # Not pure black/white: the system glyphs are a shade off it, which
    # keeps them from looking heavier than the text beside them.
    fill = (26, 26, 26, 255) if light_taskbar else (242, 242, 242, 255)
    img = Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = _glyph_font(int(_SIZE * 0.82))
    if font is not None:
        # Centred on the glyph's own ink rather than its advance box: the
        # icon fonts carry a lot of side bearing and centring on the box
        # leaves it visibly high and to the left.
        box = d.textbbox((0, 0), _HOME_GLYPH, font=font)
        d.text(
            ((_SIZE - (box[2] - box[0])) / 2 - box[0],
             (_SIZE - (box[3] - box[1])) / 2 - box[1]),
            _HOME_GLYPH, font=font, fill=fill,
        )
        return img
    # No icon font: draw the same house, stroked rather than filled, to
    # stay in the same visual family.
    s = _SIZE / 32.0
    d.line([(4 * s, 15 * s), (16 * s, 5 * s), (28 * s, 15 * s)], fill=fill, width=max(1, int(2 * s)))
    d.line([(7 * s, 14 * s), (7 * s, 27 * s), (25 * s, 27 * s), (25 * s, 14 * s)],
           fill=fill, width=max(1, int(2 * s)))
    return img


def _follow_taskbar_theme(icon):
    """Repaint the glyph when the taskbar flips light/dark.

    A registry read every few seconds, rather than a window subclass to
    catch WM_SETTINGCHANGE: pystray owns the only window here and does not
    hand out its handle, and this costs microseconds.
    """
    state = {"light": _taskbar_is_light()}

    def loop():
        while True:
            try:
                now = _taskbar_is_light()
                if now != state["light"]:
                    state["light"] = now
                    icon.icon = _make_image(now)
            except Exception:
                pass
            threading.Event().wait(5.0)

    threading.Thread(target=loop, daemon=True).start()


def build_tray_icon(on_activate, on_toggle_visibility, on_open_settings,
                    on_toggle_theme, on_refresh, on_quit):
    menu = pystray.Menu(
        # Invisible, and the default: this is what a left click runs (see
        # Api.toggle_flyout), which is not the same thing as any of the
        # entries below it.
        pystray.MenuItem("", on_activate, default=True, visible=False),
        pystray.MenuItem("Show / Hide on desktop", on_toggle_visibility),
        pystray.MenuItem("Settings...", on_open_settings),
        pystray.MenuItem("Switch theme", on_toggle_theme),
        pystray.MenuItem("Refresh now", on_refresh),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", on_quit),
    )
    icon = pystray.Icon("ha_widgets", _make_image(), "HA Widgets", menu)
    _follow_taskbar_theme(icon)
    return icon
