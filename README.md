# HA Widgets

Home Assistant controls on your Windows desktop. Built with Qt, with a
frosted-glass background and transparent rounded corners.

## Themes

These screenshots use demo devices and show the actual Qt interface in each
appearance. The captured desktop and system glass effects vary with your wallpaper.

| Appearance | Light | Dark |
| --- | --- | --- |
| Classic frost | ![Classic light theme](docs/theme-classic-light.png) | ![Classic dark theme](docs/theme-classic-dark.png) |
| Liquid glass | ![Liquid light theme](docs/theme-liquid-light.png) | ![Liquid dark theme](docs/theme-liquid-dark.png) |
| Windows glass | ![Windows light theme](docs/theme-windows-light.png) | ![Windows dark theme](docs/theme-windows-dark.png) |

## Features

- **Desktop controls:** keep your devices on the desktop, drag to reposition, and lock in place.
- **Live updates:** device states update through Home Assistant's WebSocket API.
- **Quick access:** click the tray icon to open a panel beside the taskbar.
- **Device details:** right-click or hold a tile for additional controls and sensor history.
- **Personalization:** light and dark themes, classic, liquid, and Windows glass appearances, adjustable size, zoom, and opacity.
- **Languages:** switch between Traditional Chinese and English in Settings.

In a device's detail view, open the edit panel to choose an icon or enter a
Material Design Icons name such as `mdi:air-conditioner`. Home Assistant's
`mdi:` entity icon is used automatically when no icon is selected. Icons are
bundled for offline use and keep each device type's on/off color.

The liquid appearance ports the rounded-rectangle distance and edge
displacement from [KMPLiquidGlass's Skia Lens.kt](https://github.com/Kashif-E/KMPLiquidGlass/blob/master/backdrop/src/skiaMain/kotlin/com/kashif_e/backdrop/effects/Lens.kt).
The backdrop is captured from the desktop and sampled in Canvas; the
Kotlin shader itself cannot run inside this Qt WebView.
Liquid mode schedules each new backdrop sample on the display's next
animation frame after the previous capture finishes. Actual sampling can
fall below the refresh rate when capture, transfer, or rendering takes
longer than one frame.

| Tray panel | Device controls | Sensor history |
| --- | --- | --- |
| ![Tray panel](docs/tray-panel.png) | ![Device controls](docs/detail-switch.png) | ![Sensor history](docs/detail-history.png) |

![English settings with language and appearance controls](docs/settings-english.png)

To regenerate the theme images from demo data: `python packaging/render_readme.py`.

## Run

For a packaged release, run `HA-Widgets-Setup-<version>.exe`. Run the newer
installer to upgrade; your settings are preserved.

To run from source: Windows 10/11 and Python 3.12.

```powershell
pip install -r requirements.txt
python main.py
```

Open Settings, enter your Home Assistant URL and a
[long-lived access token](https://www.home-assistant.io/docs/authentication/#your-account-profile),
then choose your devices.

Fast glass hides the widget from screenshots and recordings. Choose compatibility
mode to include it; background capture depends on the applications behind it.

## License

[MIT](LICENSE)

Bundled Material Design Icons path data: [Apache 2.0](web/mdi-LICENSE).
