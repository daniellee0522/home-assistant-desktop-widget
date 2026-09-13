"""System tray icon for the HA desktop widget."""

import pystray
from PIL import Image, ImageDraw


def _make_image():
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 4, size - 4, size - 4], radius=16, fill=(80, 150, 255, 255))
    # simple house glyph
    d.polygon([(32, 14), (14, 30), (50, 30)], fill=(255, 255, 255, 255))
    d.rectangle([20, 30, 44, 50], fill=(255, 255, 255, 255))
    d.rectangle([28, 38, 36, 50], fill=(80, 150, 255, 255))
    return img


def build_tray_icon(on_toggle_visibility, on_open_settings, on_toggle_theme, on_refresh, on_quit):
    menu = pystray.Menu(
        pystray.MenuItem("Show / Hide widget", on_toggle_visibility, default=True),
        pystray.MenuItem("Settings...", on_open_settings),
        pystray.MenuItem("Switch theme", on_toggle_theme),
        pystray.MenuItem("Refresh now", on_refresh),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", on_quit),
    )
    icon = pystray.Icon("ha_widgets", _make_image(), "HA Widgets", menu)
    return icon
