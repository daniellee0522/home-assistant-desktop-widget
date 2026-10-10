---
name: ha-widget-author
description: Write a custom desktop widget for HA Widgets (the Windows app) from a description or a picture, as a ready-to-import .hawidget. Use whenever the user wants a new widget for HA Widgets or asks to "make / design / build / 做 / 設計 / 寫一個 widget" (a clock, countdown, stocks, weather, photo frame, counter, shortcuts, battery, timer, chart...), shows a screenshot or mock-up of a widget to copy, or wants to change an existing widget of the widget kit (widgetkit). Not for Home Assistant device tiles.
---

# Writing a widget for HA Widgets

A widget is one Python file (plus a small `manifest.json`) written against the **widget kit** (`widgetkit`). The kit draws the
card's glass, the dimmed look, the settings window and the permission questions; the widget only says **what it shows, where
its data comes from, what a person can change, and what happens when it is pressed**. A person imports the finished
`.hawidget` in *Settings → Widget editor → "+" under Imported widgets*, drags it onto the desktop, and changes its settings
there. Several copies of one widget each keep their own settings.

Read these when you need them (do not load all at the start):
- `references/kit-api.md`: every part of the kit with its exact arguments (WidgetDef, Field, Context, handlers, text roles,
  colours, controls, charts, pictures, sources, actions, permissions, the manifest).
- `references/design.md`: the house style, the four sizes, standby, and how to turn a picture or a description into a layout.
- `assets/*.py`: three complete, checked widgets to copy from: `countdown.py` (settings, a ring, no data), `tally.py` (state,
  taps, a spring, a layout per size), `temperature.py` (a number from the web with its permission). Bigger ones, if the
  repository is at hand: `widgetkit/examples/*.py` (price, watchlist, ask, album, timer, worldclock, battery, map, recorder,
  launcher, clock, calendar, player, water) and `widgetkit/packages/photoframe/` (pictures, a right click, a slideshow).

## Workflow

1. **Understand the widget.** From the words or the picture, decide: what it shows; which **size(s)** (`1x1` small square,
   `2x2` square, `2x4` wide, `4x4` large; the first is the default, `sizes=` lists the others it can be); what data it needs
   (nothing / this computer / a web address / the user's own files) and so which **permissions**; what the user should be able
   to change (these become `Field`s: the settings window is made for you); whether pressing, typing, dragging or a right click
   does anything. Ask the user only for what you cannot decide (a data source's address, an API key's name). Do not ask about
   colours or fonts: the program's own are used.
2. **Write the files** in a new folder, e.g. `my-widget/`:
   - `main.py` defining `WIDGET = WidgetDef(...)` (start from the closest file in `assets/`);
   - `manifest.json`: `{"id": "dev.<name>.<widget>", "name": {"en": "...", "zh": "..."}, "version": "1.0", "kit": 1,
     "entry": "main.py", "author": "<name>", "permissions": [...same as WidgetDef.permissions...]}`.
   The `id` is the same in both. A single `.py` also works (the program wraps it); write the manifest when you want to ship a
   package.
3. **Check it** (needs the repository or `pip`-less access to `widgetkit`):

   ```
   python -m widgetkit.check my-widget --out preview.png --pack my-widget.hawidget
   ```

   It loads the widget, draws every size in light and dark in English, Traditional Chinese and a longer made-up language, writes
   one picture, lists what is wrong (`ERROR` must be fixed; `WARN cut` means text that does not fit, `overlap` text on text,
   `overflow` outside the card, `tiny` a control too small to press, `slow` a drawing over 50 ms, `hint`/`background` a declaration
   that does not match the drawing), and with `--pack` writes the package only when there is no error. Useful switches:
   `--config '{"goal": 6}'` and `--state '{"count": 5}'` to see it filled, `--standby` for the dimmed look, `--sizes 2x4`.
4. **Look at the picture** (open `preview.png`): is it what was asked for, in both themes, at every size, with long words? Fix
   and check again until there are no errors and no avoidable warnings. Say what you saw, not that "it should work".
5. **Hand over**: give the path of the `.hawidget`, what the settings are, and what it asks to be allowed (each permission in
   plain words). Remind them that a widget is a program, so only widgets from people they trust should be imported.

When `widgetkit` is not at hand (only the installed app): still write `main.py` and `manifest.json`, zip them (the two files at
the root of the zip, extension `.hawidget`), and tell the user to import it; the program shows an error on import when the code
does not load. Say clearly that it was not run.

## From a picture or a description

A screenshot of a widget (an iOS widget, a mock-up, another app) is a **layout and a content to copy, not pixels**:
- Name the regions (a big number, a label, a ring, a list of rows, a picture) and which are **data** and which are fixed words.
- Re-express every region with the kit: text with a **text role** (`display`, `headline`, `body`, `caption`...), colours with the
  theme (`th.ink1`, `th.ink2`, `th.accent("green")`), shapes with `charts` and `controls`, pictures with `media`, icons as
  `mdi:` names. Never copy a colour or a font size from the picture; take the nearest role and accent.
- Keep **proportion, not pixels**: lay out from `W` and `H` (and `ctx.size_name()`), never from numbers like 333.
- If the picture shows a background (photo, gradient, glass), the program supplies the card; a widget draws on it. A full
  picture is `media.picture(p, path, QRectF(0, 0, W, H), "cover", th.tokens["radius_panel"])`.
- Say what you could not match and why (a font, a blur, an animation the kit does not have).

## Rules that make a widget right (details in `references/design.md`)

- Text only through `theme.text` / `theme.paragraph` with a **role**; colours only from `th`; never your own sizes or QColors
  for ink. This is what makes standby and light/dark work by themselves: in standby `th.ink1/ink2/accent` become white.
- Do not draw glass, blur or shadows of the card: the program does. Awake the card is a **solid face** (white / near black)
  drawn for you; say `background="glass"` only if the widget has no face of its own (a transparent overlay).
- Everything a person can press is registered with `ctx.hits.add(rect, id)` (or a kit control with `hits=ctx.hits, id=...`) and
  handled in `on_tap(id, ctx)`. Handlers **change state and return Actions**; they never do the thing themselves.
- Never block in `draw` or a handler (no `time.sleep`, no network, no file reads of unknown size): data comes from `sources`,
  things to do come back as `Action`s. Never change state in `draw`; draw from `ctx.state`, `ctx.config`, `ctx.data`, `ctx.now`.
- Redraw rules: `tick=` (seconds) for what moves, `ctx.redraw_in(s)` for the next frame or picture, `ctx.spring(...)` to ease. A
  still widget has none. In standby the program draws rarely whatever is asked (`ctx.standby`, `standby_tick`).
- Declare the least permission that works (`network:api.example.com`, never `network:*` unless the user picks the address).
  Secrets are `Field(..., "secret", ...)`.
- Words for people go in `{"en": ..., "zh": ...}`. Draw something sensible for **no data yet** and **no data at all**.
- Keep the file readable: one `draw`, small helpers, constants at the top, a comment where the idea is not obvious.
