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
