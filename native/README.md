# Tools for the native windows

Every window is drawn natively (`nativeui/`): the widgets (`widget.py`), the detail card (`detail.py`), the
tray panel (`panel.py`, `homeview.py`, `homeedit.py`, rules in `homemodel.py`) and Settings (`settings.py`,
`editor.py`), on a small retained-mode toolkit (`ui.py`). This folder only holds the tools used to check that
the widgets look like the web page did (`web/`, the earlier interface, which is no longer shipped).

- `parity.py [outdir] [filter]` renders the same demo widget with the web page
  (`web/index.html`) and with `nativeui/render.py` over the same picture, for every glass
  style (classic, Windows, liquid), theme, lit or dimmed, tile form (small, bar, big) and size,
  and reports how far apart they are (mean absolute difference, 0-255; pictures in
  `native/out/`). Typical results: 1.6-3.4 for classic and Windows glass, 3-4.5 for liquid; what
  remains is mostly the edges of the glyphs (the page's text shadow is not drawn natively).
- `tune.py` tries font settings against the web pictures.
- `parity_data.py` is the demo tiles and states.

## How the native widget is made

- `nativeui/render.py` draws the card and the tiles with QPainter, from the numbers of
  `web/style.css` and the rules of `web/app.js` (colours, labels, readings, forms, dimming).
  Text is drawn as outlines from a font ten times the size and scaled down, which keeps the
  page's grey anti-aliasing; with Qt's FreeType font engine (set in `main.py`) the CJK font is
  not copied into the process as DirectWrite does (about 40 MB).
- `nativeui/liquid.py` is the liquid glass without a GPU. The ring the lens bends depends only on
  the card's shape, so it is worked out once as a mesh of small quads (1 px at the rim, coarser
  inside) and each new picture of the desktop is warped through it by Pillow's C code. Against a
  numpy port of the shader the ring differs by 0.3/255 on a blurred picture.
- `nativeui/widget.py` is the window: the same interface as the page windows (`hwnd`, `show`,
  `events`, `evaluate_js`...), so `main.py` treats it like one. It takes taps, holds, drags and the
  wheel, asks `Api.get_desktop_backdrop` for the glass on its own thread, and draws only the newest
  picture.

## Measured

With a video wallpaper playing behind one widget (Windows 11, this development machine):

| | memory (USS) | CPU, one core |
| --- | --- | --- |
| web widget (QtWebEngine), v1.6.0 | 233 MB | about 64 % |
| native, glass live (30 looks a second) | 62-65 MB | about 50 % |
| native, glass still | 62-66 MB | 1-2 % |

Opening the settings window, a detail card or the tray panel starts the browser engine
(+75 MB to +290 MB while open); each is released again after a while.
