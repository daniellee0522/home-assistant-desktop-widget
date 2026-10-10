# widgetkit API (what a widget can use)

Imports a widget normally needs:

```python
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor
from widgetkit import charts, controls, media, rows, faces
from widgetkit.definition import (Field, WidgetDef, open_url, open_app, launch, copy, request, pick_file, media as media_action,
                                  record_start, record_stop)
from widgetkit.sources import JsonSource, RssSource, ImageSource, SystemSource, SystemMediaSource, StaticSource
from widgetkit.theme import text, paragraph, fit_text
```

## WidgetDef

`WidgetDef(id, name, size, config, sources, draw, ...)`; every other argument is optional.

| Argument | Meaning |
| --- | --- |
| `id` | `dev.name.widget`: letters, digits, `.` `_` `-`; the same as in `manifest.json`. |
| `name` | words, or `{"en": "...", "zh": "..."}`. |
| `size`, `sizes` | the size it is added at (`"1x1"`, `"2x2"`, `"2x4"`, `"4x4"`) and a tuple of the others it can be. |
| `config` | list of `Field`. |
| `sources` | list of sources (fetched off the GUI thread). |
| `draw(p, th, W, H, ctx)` | paints the widget; see below. |
| `on_tap(id, ctx)`, `on_submit(id, text, ctx)`, `on_drop(id, paths, ctx)`, `on_drag(id, move, ctx)`, `on_scroll(id, dy, ctx)`, `on_context(id, ctx)` | handlers; each may return an `Action` or a list. `on_context` is the right click (a widget that has one keeps the right click). |
| `permissions` | tuple of permission strings (below). |
| `tick` | seconds between redraws of something that moves; `None` = still. `standby_tick`: the same in standby (`None` = once a minute for a widget that ticks, `0` = never). |
| `background` | `"solid"` (default: the program paints an opaque face under the widget awake; clear glass in standby) or `"glass"` (no face of its own). |
| `state` | dict: the memory before it has any. |

Size room: `1x1` 160x161, `2x2` 333x334, `2x4` 678x334, `4x4` 678x680 (units of the drawing). `draw` gets the exact `W`, `H`.

## Field (a setting; the settings window is made from these)

`Field(key, type, default, label="", options=(), minimum=None, maximum=None, step=1, help="", choices={})`

| `type` | The person sees | The value |
| --- | --- | --- |
| `"text"` | a line of text | str |
| `"secret"` | a masked line (never exported) | str |
| `"number"` | a number (`minimum`, `maximum`, `step`) | int or float |
| `"bool"` | an on/off switch | bool |
| `"choice"` | a pop-up of `options` (`choices={"a": {"en": "A", "zh": "甲"}}` gives each its words) | one of `options` |
| `"list"` | a list of strings with add and remove | list[str] |
| `"feeds"` | name + address pairs | list of `{"name", "url"}` |
| `"launchers"` | icon + label + address buttons | list of `{"icon", "label", "url"}` |
| `"images"` | picture files chosen in a dialog, at most `maximum` (default 10) | list[str] of paths |

`key` is a name (`goal`, `api_key`); label and help may be `{"en", "zh"}`. In `draw` read `ctx.config["key"]`; the value is
already cleaned (a number is within its limits) and the default is used for what was never set.

## Context (`ctx`)

| | |
| --- | --- |
| `ctx.config`, `ctx.data`, `ctx.errors` | the settings; `ctx.data["source name"]` = what the source fetched (None / absent until it has); `ctx.errors` = sources that failed |
| `ctx.state`, `ctx.set_state(**values)` | the widget's memory, kept between runs (JSON values). Read anywhere; change only in handlers. |
| `ctx.now` | the time (seconds since epoch) of this drawing: use it, never `time.time()`, so a drawing is repeatable |
| `ctx.size`, `ctx.size_name()` | `(W, H)`; `"1x1"`, `"2x2"`, `"2x4"`, `"4x4"` |
| `ctx.lang` | `"en"` or `"zh-TW"` |
| `ctx.standby` | the program is in standby: draw quietly |
| `ctx.hits.add(rect, id)` | register a pressable place; `ctx.pressed`, `ctx.hover` say which id is held / under the pointer; `ctx.pointer` = last (x, y) |
| `ctx.spring(key, target, response=0.35, damping=1.0)` | a number that eases to `target`; redrawn each frame until it rests |
| `ctx.redraw_in(seconds)` | draw again after that long (the soonest ask wins) |
| `ctx.text_input(id)` / `ctx.set_input(id, text)` / `ctx.inputs` | a text box: `controls.search_bar(..., **ctx.text_input("ask"))`; Enter calls `on_submit` |
| `ctx.drop_target(id, rect, accepts=("image",))` | a place files may be dropped; True while files are over it |

## Text roles (use these, never sizes)

`text(p, th, role, "words", x, y, w=None, align="l"|"c"|"r", color=None)` draws one line with its top at `y`, cut with … at `w`.
`paragraph(p, th, role, "words", QRectF, align="l", max_lines=None)` wraps. `fit_text(p, th, "12:30", QRectF)` makes one line as large as fits.

Roles (px): `hero` 52 light, `display` 40, `title` 19.5 bold, `headline` 19 bold, `value` 16, `body` 15, `secondary` 14 (ink2), `label` 13,
`caption` 12 (ink2), `eyebrow` 12.5 (ink2), `meta` 13.5, `hint` 11.5, `tiny` 10.5; the kit adds `clock_day`, `calendar_month`,
`calendar_head`, `calendar_day`, `quote`, `news_source`, `news_title`, `launcher_label`, `player_title`, `player_artist`, `player_app`.
`ink1` is for what is read, `ink2` for what is said about it.

## Colours (`th`)

`th.ink1`, `th.ink2` (text), `th.accent("blue"|"green"|"red"|"teal"|"cyan"|"yellow")`, `th.faint(color, alpha)` (a track),
`th.legible(color)` (an accent for thin marks/words), `th.on_accent` (what is drawn on an accent fill), `th.name` (`"light"`/`"dark"`),
`th.dim` (standby), `th.tokens["radius_panel"]` (the card's corner radius). Standby turns ink and accents white by itself.

## Controls (`widgetkit.controls`): each draws and registers its hit area

`button(p, th, rect, label, color, kind="filled"|"tinted"|"plain", icon_name=None, state="", hits=None, id=None)` ·
`icon_button(p, th, rect, "mdi:name", color, filled=False, state="", hits=None, id=None)` · `search_bar(p, th, rect, label, icon, ..., hits, id)` ·
`toggle(p, th, rect, on, color, hits, id)` · `segmented(p, th, rect, labels, selected, color, hits, id)` · `slider(p, th, rect, value, color, hits, id)` ·
`field(...)` · `stepper(p, th, rect, color, hits, id)` · `checkbox(...)` · `drop_zone(p, th, rect, active, label)` · `icon(p, "mdi:name", color, rect, size)` ·
`icon_badge(p, "mdi:name", color, rect)`. Pass `state="pressed" if ctx.pressed == "id" else ""` so a press shows. Icons are Material Design
Icons (`mdi:` + name, 7,447 of them; browse them in `python -m widgetkit.studio`, Icons tab).

## Charts (`widgetkit.charts`): values 0..1 unless said

`ring(p, th, rect, value, color, width=None)` (returns the room inside) · `rings(p, th, rect, values, colors)` · `gauge(...)` · `bar(p, th, rect, value, color)` ·
`segments(...)` · `columns(p, th, rect, values, color, labels=None)` · `line(p, th, rect, [series], [colors], fill=True, grid=3)` ·
`sparkline(p, th, rect, values, color)` · `donut(p, th, rect, parts)`. Rows: `rows.quote_row`, `rows.news_item`.

## Pictures (`widgetkit.media`)

`media.picture(p, path_or_QImage_or_bytes, rect, fit="cover"|"contain"|"fill", radius=0, mono=False)` · `media.caption_card(p, th, source, rect, title, subtitle)` ·
`media.collage(p, sources, rect)` · `media.animation(path)` → an `Animation` for a GIF / animated WebP (else None): `anim.at(ms)` → `(QImage, ms_to_next)`; draw it and
`ctx.redraw_in(wait / 1000)` · `media.monochrome(img, mode="luminance"|"alpha", contrast=1.0, invert=False)` · `media.dominant_color(img)`. In standby a picture is
white and clear where it is dark (`mono=th.dim`); never another colour.

## Sources (data, fetched when due, kept when a fetch fails)

- `JsonSource(name, url, fields, each=None, every=60, standby_every=None)`: `url` may contain `{setting_key}` and, with `each="list_setting"`, `{item}`;
  `fields={"price": "chart.result.0.meta.regularMarketPrice"}` (dotted path, numbers index lists). Result: `ctx.data[name]` = a dict (or a list of dicts with `each`).
- `RssSource(name, feeds="feeds", limit="max_news", every=300)`: `feeds` / `limit` are the *keys of settings* (a `"feeds"` field and a number field); result: a list of `{"source", "title", "time"}`, newest first.
- `ImageSource(name, url="{image_url}", every=1800)`: a real picture (the bytes) in `ctx.data[name]`.
- `SystemSource(name, what, every=30, path="C:/", path_key=None)` with `what` one of `"battery"` (`{percent, charging, plugged, minutes_left}`), `"memory"` / `"disk"` (`{percent, used, total}`; disk of `path` or the setting named `path_key`), `"cpu"` (`{percent}`); needs `system`.
- `SystemMediaSource(name="media")`: what this computer is playing: `{state, title, artist, app, duration, position, position_at, can, art}`; control it with the `media_action` (needs `media`).
- `StaticSource(name, value)`.
Needs `network:<host>` for every host a source reads.

## Actions (returned by handlers; done only if declared **and** allowed)

`open_url(url)` (http/https/mailto; no permission) · `pick_file(into, kind="image")` (system file chooser → `state[into]`) ·
`request(url, method="GET", json=None, headers=None, into="reply")` (`network:<host>`; answer in `state[into]` = `{ok, status, data}`, `state[into + "_busy"]`) ·
`open_app("outlookcal:")` (`app:<scheme>`) · `media_action("play_pause"|"next"|"previous"|"seek", seconds)` (`media`) · `copy(text)` (`clipboard`) ·
`launch(path, *args)` (`launch:<path>`) · `record_start(into)` / `record_stop(into)` (`microphone`).

## Permissions (strings)

`network:api.example.com`, `network:*.example.com`, `network:*` (any site: risky), `launch:C:/path/app.exe`, `clipboard`, `microphone`, `system`, `app:<scheme>`, `media`.
Declare exactly what the widget uses, in `WidgetDef.permissions` **and** `manifest.json`. The user is asked when they add it.

## Manifest

```json
{"id": "dev.me.tally", "name": {"en": "Tally", "zh": "計數器"}, "version": "1.0", "kit": 1, "entry": "main.py",
 "author": "me", "permissions": []}
```

A `.hawidget` is a zip with `manifest.json` and `main.py` (and any assets) at its root. The code may not ask for more permissions than the manifest lists.
