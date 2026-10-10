# How the code is laid out

Every window is drawn natively with Qt (PySide6); there is no browser engine. The program is a handful of packages,
each with one job, and `main.py` is only the door.

```
main.py              process set-up that must come before Qt loads (DPI awareness, no numpy), then app.lifecycle.run()
app/                 the running program
  lifecycle.py         main(): the widgets, the tray, the Shell (what the tray menu, sleep and display changes do)
  api/                 the Api every window works through, one mixin per concern (below); customs.py: widgets of the widget kit
  widget_windows.py    one desktop widget's window: made, pinned to the bottom, put back where it was left
  capture.py           the three ways of reading the screen, made once
  compose.py           our windows laid over a capture of the screen
  geometry.py          placement and glass rules that need no window (snapping, flipping, liquid parameters)
  startup.py           the "start with Windows" command, the shortcut check, window minimum sizes
  probe.py             HA_WIDGET_OPEN_PANEL: watch the panel's first opening in the running program
core/                the program's data and Home Assistant; imports nothing of ours
  config.py            the settings file: defaults, cleaning, migration from older files, saving
  ha_client.py         REST and WebSocket client
  home.py              the Home view's grouping of devices by room
  alerts.py            what is worth a notification (locks, safety sensors)
  local_media.py       this computer's media player, as if it were a Home Assistant player
  version.py           the running build's version
winsys/              Windows itself: Win32, the desktop's windows, capture, the tray, Qt's shell
  win32.py             the DLLs with argument types, constants, structures, and the small questions everything asks
  windows.py           what is done to our windows: place, size, shape, z-order, capture exclusion, DWM glass
  scan.py              looking at the desktop's other windows (what lies over a widget, who has the user's attention)
  gdi_capture.py       GDI/PrintWindow capture (the compatibility path); capture_worker.py runs it in a process
  dxgi_capture.py      Desktop Duplication (the fast path, GPU)
  capture_pixels.py    "did this picture change by more than noise"
  qtshell.py           Qt's event loop, the GUI-thread marshal, the log, the watchdog, sleep/display notices
  tray.py, hotkey.py   the tray icon, the global shortcut
nativeui/            every window's drawing and behaviour (below)
widgetkit/           the widget kit: widgets that are not the program's own kinds (docs/widgetkit.md). The program runs them through
                     app/api/customs.py (packages, settings, permissions), nativeui/customview.py (the desktop window's part) and
                     nativeui/editor_custom*.py + formrows.py (the editor's shelf, settings and permissions); the kit imports
                     nativeui.render/style and changes nothing in them
.claude/skills/ha-widget-author/   the Claude skill that writes widgets for the kit (docs/ha-widget-author.skill is its zip)
packaging/           installer build, release, README screenshots
tests/               tests/README.md
tools/               pictures and measurements: tools/README.md
```

`core/` depends on nothing of ours. `winsys/` depends on `core/`. `app/` and `nativeui/` depend on both; `app/` makes the
windows that `nativeui/` defines, and `nativeui/` calls back into the `Api`.

## The Api

`app.api.Api` is what a window works through. It is assembled from mixins, each owning the state it uses (set up in
its own `_init_*`) and the methods that use it:

| Mixin | Owns |
| --- | --- |
| `windows.py` | the windows held (widgets, card, panel, Settings): making, releasing, telling them things, sizing them as they ask |
| `prefs.py` | preferences (what every window draws from, how a change is cleaned and broadcast), the connection, the panel's picture, the shortcut |
| `widgets.py` | the widgets: tiles, sizes, places; adding, removing, dragging, snapping |
| `ha.py` | Home Assistant as the windows see it: states in and out to the windows that show them, history, forecasts, services |
| `flyout.py` | the tray panel's coming and going |
| `popover.py` | the detail card over a tile, and the Settings window |
| `glass.py` | which windows are hidden from capture, the system's own glass |
| `backdrop.py` | the picture of the desktop behind a window: read, cleaned of other programs' windows, blurred, answered only when changed |
| `idle.py` | dimming while the desktop is out of sight |

Windows call the Api's public methods, usually from a thread of their own; whatever touches a window is marshalled onto
the GUI thread (`qtshell.ensure_marshal()`). The Api tells a window something with `window.send(name, *args)`
(`nativeui/overlay.py`).

## nativeui

| Module | What it is |
| --- | --- |
| `ui.py`, `style.py`, `controls.py` | the toolkit (views, scenes, scroll boxes, menus), the house style, the detail's controls |
| `render.py`, `kinds.py`, `appearance.py` | drawing a tile and a widget; the other kinds of widget; what a tile is shown as |
| `widget.py` | a desktop widget |
| `panel.py`, `homeview.py`, `homeedit.py`, `homemodel.py` | the tray panel and its Home view (the model has no window) |
| `detail.py` | the card a hold or right-click opens |
| `settings.py`, `editor.py` | Settings, the widget editor, the picker |
| `overlay.py` | what the Api holds for the card, the panel and Settings |
| `glass.py`, `gpu_glass.py`, `liquid.py`, `widget_glass.py`, `widget_capture.py` | the glass behind a window: the worker, the CPU and Direct3D lens, one presentation clock and one capture worker for all GPU widgets |
| `dcomp.py`, `dcomp_liquid.py` | the panel's slide by the desktop compositor and its glass material |
| `actions.py`, `i18n.py`, `fonts.py`, `screens.py`, `animation_clock.py` | what a tap does, the English texts, installed fonts, monitors, animation ticks |

The rules a change to a screen must keep are in `CLAUDE.md`.

## Where a new thing goes

- A new kind of preference: the cleaner in `prefs.py`'s `_PREF_CLEANERS`, the default in `core/config.py`, the control in
  `nativeui/settings.py`, and the text in `nativeui/i18n_en.json`.
- A new Api method a window calls: in the mixin that owns the state it touches. If a window calls it, a test stand-in
  must still match it (`tests/app/test_contract.py` fails if it does not).
- A new Win32 call: its argument types in `winsys/win32.py`, what it does to a window in `winsys/windows.py`.
- A rule about placement or glass that needs no window: `app/geometry.py`, where it can be tested without one.
- A new widget kind or screen: add it to `tools/visual_check.py` and look at the picture.
