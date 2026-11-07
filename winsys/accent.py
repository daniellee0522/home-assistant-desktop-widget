"""The Windows accent colour, as the system's own surfaces take it: its eight shades (Settings >
Personalisation > Colours), lightest first, the accent itself the fourth."""


def accent_palette():
    """[(r, g, b)] * 8 from the lightest shade to the darkest, or None when Windows does not say.

    Explorer keeps the shades it tints the Start menu and the taskbar with (AccentPalette, eight RGBA
    entries); a system without them still has the accent itself (DWM's AccentColor, as 0xAABBGGRR), and
    every shade is that."""
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent") as key:
            raw, _ = winreg.QueryValueEx(key, "AccentPalette")
        if isinstance(raw, (bytes, bytearray)) and len(raw) >= 32:
            return [tuple(raw[i:i + 3]) for i in range(0, 32, 4)]
    except OSError:
        pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as key:
            value, _ = winreg.QueryValueEx(key, "AccentColor")
        rgb = (value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF)
        return [rgb] * 8
    except (OSError, TypeError):
        return None
