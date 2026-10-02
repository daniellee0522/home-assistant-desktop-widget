# Native widget prototype

Can a desktop widget be drawn natively, without a browser page, and look the
same? This branch (`native-widget-proto`) tries it for one case: a 2x4 widget
with the classic frosted glass, light and dark.

- `render.py` draws the card and tiles with QPainter from the same numbers as
  `web/style.css` and the same rules as `web/app.js` (icon colours, labels,
  readings, on/off).
- `widget_native.py` is a live widget: it reads the settings file, shows the
  first widget at its saved place, takes its tiles from Home Assistant, makes
  the glass from the captured, blurred desktop behind it, and toggles on click.
  `python native/widget_native.py` (Esc quits).
- `parity.py` renders the same demo widget with the web page and with
  `render.py` over the same picture and reports how far apart they are
  (`python native/parity.py`, pictures in `native/out/`).
- `tune.py` tries font settings against the web pictures.

## What was measured

One widget, a video wallpaper playing behind it, glass following the screen:

| | memory (private, task manager "Memory") | CPU, one core |
| --- | --- | --- |
| web widget (QtWebEngine), v1.6.0 | 233 MB | about 64% |
| native widget, glass live | 59 MB | about 20% |
| native widget, no glass capture | 33 MB | 0.4% |

Picture parity (`parity.py`, 8 demo tiles, mean absolute difference over the
widget, 0-255): 3.3 for both themes; flat colours differ by under 1.3, the
rest is text and icon edges.

## What made the difference

- The browser: an empty page alone is 107 MB; Python and Qt without it 18 MB.
- Text: Qt's DirectWrite engine copies a whole CJK font (about 40 MB) into
  the process the first time one is used. With Qt's FreeType engine
  (`QT_QPA_PLATFORM=windows:fontengine=freetype`) it costs nothing, and
  loading `SegUIVar.ttf` as an application font gives the weight and optical
  size axes back. Text is drawn as outlines (grey anti-aliasing, as the page's).
- The card (tint and tiles) is painted once per change into a pixmap; a frame
  of glass is the small picture stretched, cut to the card's shape, and that
  pixmap on top.

## Not done

Liquid glass (the lens is a shader), Windows glass, the dimmed look, the bar
and large tile forms, the other sizes, long press and right-click detail,
dragging with snapping, the tray panel, the Home panel, settings.

## Second round: dimming, tile forms, liquid glass

Added to the prototype (all measured against the web page with `python native/parity.py [outdir] [filter]`,
32 scenes: classic and liquid, light and dark, lit and dimmed, small/bar/big tiles, 2x4 and 4x4):

- **Dimming** (`idle.py`): the same rule as `_watch_for_idle`, eased 700 ms in and 260 ms out by
  cross-fading two cached pictures of the tiles (lit and dimmed colours); mouse move or press wakes it.
- **Tile forms** (`render.tile_layout`): 1x1, 2x2, 2x4, 4x4; bar (2x1) and big (2x2, zoom 1.4) chosen
  from the tile count as `tileFormFor` does; the climate reading (`24 °C`) and round − / + buttons.
- **Liquid glass** (`liquid.py`): the shader's sampling ring depends only on the card's shape, so it is
  worked out once as a mesh of 4 px quads and each new desktop picture is warped through it by Pillow's
  C code (no GPU, no numpy). Against a numpy port of the shader the ring differs by 0.3/255 on average.
  The tiles' `backdrop-filter: blur(12px)` is a blur of a quarter-size copy.
- **Sampling**: `glass_sampling: still` takes the desktop once and again only when the widget is dropped
  or its tiles change; a widget covered by other windows does not sample at all.

Measured here (preview, animated wallpaper behind it): USS 62-67 MB; CPU 1.3-1.9 % of a core on
`still`, about 18 % on `live` with a wallpaper that moves (the cost is Desktop Duplication itself).

Not done: Windows glass, the right-click / long-press detail card, the tray panel and settings (they stay
web pages, opened on demand), drag snapping, several widgets in one process, and the chromatic split at the
lens rim (it changes the result by less than 0.01/255 on a blurred picture).
