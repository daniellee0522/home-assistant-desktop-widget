# widgetkit: making widgets that are not the program's own

`widgetkit/` is a separate package. It reads the program's look (`nativeui.render`, `nativeui.style`) and changes
nothing in it. The program runs what it makes (see "In the program" below). A widget is one Python file (or a `.hawidget` package) that says
what it shows, where its data comes from, what a person can change, and what happens when it is pressed, typed in,
dragged or dropped on. The kit draws, hosts and protects; the developer does not touch Qt windows.

```
python -m unittest discover -s widgetkit/tests -t .     # the kit's own tests (real windows, a real microphone if present)
python tools/widgetkit_examples.py                      # pictures of every example in use  -> visual/
python -m widgetkit.studio widgetkit/examples/price.py                           # look at a widget while writing it
```

## Checking a widget, and having an AI write one

```
python -m widgetkit.check my-widget --out preview.png --pack my-widget.hawidget
```

Loads the widget (a `.py` file or a package folder), draws every size in light and dark in English, Traditional Chinese and a longer
made-up language, writes one picture, lists what is wrong (`ERROR` load / error; `WARN` cut, overlap, overflow, tiny, slow, a
`background` declaration that does not match the drawing) and, only when there is no error, writes the `.hawidget` with `--pack`.
`--config`, `--state`, `--standby`, `--sizes`, `--langs`, `--themes` choose what is drawn. Exit code 1 on an error. A Traditional Chinese
guide for users and authors is `docs/widgetkit.zh-TW.md`.

The Claude skill **`ha-widget-author`** (`.claude/skills/ha-widget-author/`, and `docs/ha-widget-author.skill` to install it elsewhere;
`python tools/pack_skill.py` rebuilds that file) lets an AI write a widget from a description or a screenshot: it decides size, data,
permissions and settings, writes `main.py` and `manifest.json` from one of three checked recipes (`assets/`), runs the check, looks at
the preview and fixes what it sees, and packs the result. Its API sheet and design notes are in `references/`.

## The shortest widget

```python
from widgetkit.definition import Field, WidgetDef
from widgetkit.sources import JsonSource
from widgetkit.theme import text

PRICE = JsonSource("p", "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                   {"price": "chart.result.0.meta.regularMarketPrice"}, every=60)

def draw(p, th, W, H, ctx):                          # paint with the painter; register controls in ctx
    text(p, th, "display", "%.2f" % ctx.data["p"]["price"], 24, 24)

WIDGET = WidgetDef(id="dev.me.price", name="Price", size="2x2",
                   config=[Field("symbol", "text", "AAPL", "Symbol")],      # becomes the settings window
                   sources=[PRICE], draw=draw, permissions=("network:query1.finance.yahoo.com",))
```

Examples to copy from, in `widgetkit/examples/`: `price` and `watchlist` (web data, settings), `ask` (text input,
Enter sends it to a service, the reply shown), `album` (a photo: drop, choose, or from the web), `timer` (state and a
ticking redraw), `worldclock` (drawn straight with the painter), `battery` (this computer), `map` (drag, zoom, tiles
from the web), `recorder` (the microphone), `launcher` (a search bar and shortcuts), and the program's own three remade
with the kit: `clock` (a time zone the person picks, from a menu of 27 or any typed name; the second ring eases with
`ctx.spring`), `calendar` (a press opens the Windows Calendar app) and `player` (what this computer is playing: cover,
seek by tap or drag, previous / play-pause / next). `python tools/widgetkit_remakes.py` draws each beside the original.

## Widget Studio: seeing what you are making

```
python -m widgetkit.studio path/to/widget.py          # a file, or a package folder
```

A window that shows the widget as the program will draw it (it is the kit's own drawing), at every size it declares, in
light and dark, in every language you tick, side by side; it reloads the moment the file is saved, in any editor
(`widgetkit/studio/vscode/` has a VS Code task and key). Beside the pictures:

* **Settings**: the widget's settings window as a person will see it (made from its `Field`s), live; change a setting
  and every picture follows. Shown in either language.
* **State**: the widget's memory as JSON; type `{"count": 8}` and see a full ring. Plus *Pretend it is* a date and time
  for clocks and calendars.
* **Problems**: what looks wrong: an error when importing or drawing (with the file and line), text that had to be cut
  (which text, in which size and language), a control drawn too small to press. A mistake in the file keeps the last good
  pictures on screen with the message beside them.
* **Actions**: what the widget asked to do when you pressed it (open a page, copy, run, record), logged and **not done**
  unless you tick the box. Permissions the widget declared are allowed while you develop.
* **Icons**: all 7,447 icons the kit can draw, searchable; double-click copies `mdi:name`.
* **False languages** (*Pseudo (+40% long)*, *Pseudo 中文*): every word the kit draws is made 40 % longer, in accented letters
  between brackets (`[Ŵàţéŕ ţǿďàý~~~~]`), so a layout that only breaks in a longer language breaks here, where you can see it.
  Text that no longer fits is reported as *cut*; text on top of other text as *overlap*; text outside the widget as
  *overflow*; a drawing slower than 50 ms as *slow*; a handler that failed as *error*. The same checks run on every language
  you tick.
* Overlays: *Hit areas* (where each control can be pressed; orange if drawn smaller than 32 px) and *Safe area*.
* Clicking a picture presses the real widget (taps, drags, typing in its inputs), so you can use it, not only look.
* Data: from the web, or, with a `widget.py.fixtures.json` beside the file (`{"address piece": answer}`), from that.
  *Refresh data* fetches again. Your choices are kept in `.studio-widget.py.json` beside the file.

`--shot out.png --sizes 2x4 --langs zh-TW --themes dark --state @state.json --tab icons --search cup` draws a picture
of the window and exits (for documentation).

## Glass, background and standby

The program's glass is a shared theme, not something a widget does: a widget draws on the program's transparent card and any
transparent widget gets the glass (the desktop, blurred, behind the card's tint) automatically; in standby the program dims
it (`Theme(dim=True)`) and the widget is told (`ctx.standby`) to draw quietly. A widget never captures or blurs anything.

* `background="solid"` (the default): awake, the program paints an opaque face under the widget (`faces.solid`: white, or near
  black in the dark) and need not capture the desktop for it (`runtime.needs_glass()`), as it does for anything opaque that
  covers a widget. A widget that wants its own face (the player's cover colour) calls `faces.tinted` over it. In standby the
  face is not painted: it is clear glass again, and the glass is needed.
* `background="glass"`: it draws on the card with no face of its own, awake too, and the program provides the glass behind it.
* **Ink follows standby by itself.** `th.ink1` / `th.ink2` (what `text` and the kit's controls use) are the theme's ink awake and
  white in standby; `th.accent(...)` and `th.legible(...)` are white in standby (the program's standby look has one colour, so do
  not tell two things apart by colour alone); `th.on_accent` is what is drawn on a fill of an accent (white awake, dark in
  standby, where the fill is white). Colours a widget picks for itself (a hand-made QColor) are its own: use `th`.
* The studio checks the declaration against the drawing: *glass* that covers the whole card with an opaque face (so it could
  say *solid*) is listed under Problems; a *solid* widget has its face painted for it.
* **Pictures in standby** are white and clear where they are dark, never another colour (the program's design). `media.picture(p, img, rect, mono=th.dim)` does it
  (`th.dim` is true in standby, so the picture follows the program by itself); `media.monochrome(img, mode, contrast, invert)` returns the
  converted QImage. `mode="luminance"` (default) lets brightness decide, for photographs and covers; `mode="alpha"` lets the picture's own
  transparency decide, for logos and icons. `contrast` and `invert` shape the luminance. `python tools/widgetkit_mono.py` draws it.
* `tick` is how often it is redrawn awake (seconds), `standby_tick` in standby (default once a minute for a widget that ticks;
  `0` never). A source's `standby_every` is the same for data (default five times `every`, a minute at least; `0` none). A
  window that is hidden or minimised runs none of these timers.

## Sizes

A widget is placed at one of the program's four sizes (`render.SIZES`): `1x1` (160 x 161), `2x2` (333 x 334), `2x4`
(678 x 334), `4x4` (678 x 680). It declares `size` (the one it is added at) and `sizes` (the others a person may resize it
to; `WidgetDef.supported_sizes()` lists them). `draw(p, th, W, H, ctx)` is given the room it has, and chooses its layout:
`ctx.size_name()` says which size that is, `ctx.size` is the exact room. A window or a library copy asked to be a size
the widget did not declare is refused (`WidgetWindow(rt, size="3x3")` raises; `Library.size_of` falls back to its own).
Sources see the size too (`inputs["size"]`), so a map fetches the tiles that cover the room it has.
`widgetkit/examples/water.py` is a complete small widget with a layout for each of the four; read it first.
`python tools/widgetkit_tutorial.py` draws it at every size.

## What a developer writes

`WidgetDef(id, name, size, config, sources, draw, ...)`

| Part | What it is |
| --- | --- |
| `config` | `Field`s: `text`, `secret`, `number`, `bool`, `choice`, `list`, `feeds`, `launchers`. The settings window is made from them (`Form`); a person's choices are a small JSON file they can share. `secret` is typed masked and never exported. Labels, help, choices and the widget's name may be `{"en": ..., "zh": ...}`. |
| `sources` | Where data comes from, fetched off the GUI thread when due and kept when a fetch fails: `JsonSource` (an address and which values), `RssSource`, `ImageSource` (one picture, or many such as map tiles; real pictures only), `SystemSource` (battery, memory, disk, cpu), `SystemMediaSource` (what is playing, and its cover), `StaticSource`. Each placed copy of a widget gets its own copies of its sources. Their input is the settings plus `state` and `size`, so a map's tiles follow where it was dragged. |
| `draw(p, th, W, H, ctx)` | Paint with any QPainter calls. Use the kit's parts (`charts`, `controls`, `media`, `rows`, `theme.text` with the program's text roles) so it matches the program and its two themes; or draw directly (see `worldclock`). |
| `on_tap(id, ctx)` | A press and release on a control registered with that `id`. |
| `on_submit(id, text, ctx)` | Enter in an input (`controls.search_bar(..., **ctx.text_input("ask"))`). The box is emptied first; `ctx.set_input(id, ...)` puts something back. |
| `on_drop(id, paths, ctx)` | Files dropped on `ctx.drop_target(id, rect, accepts=("image",))`; only matching files arrive. |
| `on_drag(id, move, ctx)` | A pointer dragging what it pressed (`Move`: `phase`, `dx`, `dy`, ...). A drag is not a tap. |
| `on_scroll(id, dy, ctx)` | The mouse wheel. |
| `on_context(id, ctx)` | A right click. A widget that has one keeps the right click (the program then does not open its editor on it). |
| `tick` | Seconds between redraws of something that moves (a clock, a timer). |
| `ctx.spring(key, target)` | A number that eases to a target, interruptible; the widget is redrawn each frame until it rests. Reduced motion jumps instead. |
| `ctx.lang`, `ctx.pointer`, `ctx.size` | the program's language; where the pointer last pressed, released or moved (a tap on a bar needs the x); the size it is drawn at. |
| `ctx.state` / `ctx.set_state(...)` | The widget's memory, kept between runs (JSON values). |
| `sizes` | Other sizes it can be; `draw` gets `W`, `H` and lays itself out. |

A handler changes the widget with `ctx.set_state` / `ctx.set_input` and returns `Action`s. It never does the thing.

## Actions and permissions

| Action | Does | Needs |
| --- | --- | --- |
| `open_url(url)` | opens http, https or mailto in the browser | nothing |
| `pick_file(into, kind)` | the system file chooser; path to `state[into]` | nothing (the user chooses) |
| `request(url, method, json, headers, into)` | a web request off the GUI thread; answer in `state[into]` = `{ok, status, data}`, `state[into+"_busy"]` while out | `network:<host>` |
| `open_app(uri)` | opens a Windows app by its address scheme (`outlookcal:` Calendar, `ms-clock:` Clock) if one is installed; file, script and web schemes are refused | `app:<scheme>` |
| `media(command, seconds)` | `play_pause`, `next`, `previous`, `seek` on what this computer is playing | `media` |
| `copy(text)` | clipboard | `clipboard` |
| `launch(path, *args)` | runs that exact program, no shell | `launch:<path>` |
| `record_start(into)` / `record_stop(into)` | microphone to a WAV; live `state[into+"_level"]`; `state[into]` is the path | `microphone` |
| (sources) | every address a source reads | `network:<host>`; `SystemSource` needs `system` |

A widget declares permissions (`WidgetDef.permissions`, and its manifest). The user answers them on the **ConsentCard**
when adding it (risky ones start switched off); an action is performed only if it was declared **and** allowed
(`permissions.Grants`). A redirect to another host is refused, so `network:a.com` cannot be turned into `b.com`.

**What this is not:** a sandbox. Widget code is Python in the program, so it can do anything Python can; permissions
bound what the kit's actions do for it and tell the user honestly what it asks. Add only widgets from people you trust.
A widget that raises shows an error card; it does not take the program down.

## Packages and the library

`package.export(folder, "x.hawidget")` / `package.read_manifest(path)` (no code run) / `package.load(path)`.
`manifest.json`: `id`, `name`, `version`, `kit`, `entry`, `permissions`. The code may not ask for more than its
manifest shows; archives that climb out of their folder or are too big are refused.
`Library(root)` keeps installed packages, the copies placed (each with its own settings and memory), permission
answers, and updates (copies kept) and removal (memory removed).

## Running one

`WidgetRuntime(widget, user_config, grants=, state_path=, invalidate=)` is a widget with no window: feed it
`press/release/move`, `text/key/set_preedit`, `drag_move/drop`, `wheel`, `draw(p, th, W, H)`.
`host.WidgetWindow(runtime)` is a window that does that with real events (pointer, keyboard, an input method for
Chinese, drag and drop, wheel, timers, refreshing its sources as they come due). A desktop widget normally refuses
focus; while an input has the caret the window borrows it and gives it back (`set_noactivate`).

## Pictures that move, and drawing again later

* `media.animation(path)` is an `Animation` for a GIF or an animated WebP (None for a still picture): `anim.at(ms)` is the
  frame to show `ms` after the start and how long until the next. Frames are decoded on a thread of their own (the first
  is there at once), kept at 900 px a side and at most 400 frames / 160 MB. APNG is not read (Qt has no reader for it).
* `ctx.redraw_in(seconds)` asks to be drawn again after that long (a slideshow's next picture, an animation's next frame);
  the soonest ask of a drawing counts. In standby the program draws no sooner than the standby pace, whatever is asked.
* A setting of the kind `"images"` is a list of picture files the user chooses with a file dialog, `maximum` of them (10 by
  default).
* `widgetkit/packages/photoframe/` is a complete widget made of these (ten pictures, a right click for the next, a timer for
  moving on by itself, standby as clear white or as it is); `photoframe.hawidget` beside it is what a person imports.

## In the program

A person adds a widget of the kit from the widget editor (Settings → Widget 編輯器):

* On the left, under the clock, calendar and the rest, **匯入的 Widget** has a **+** that opens a file dialog for a
  `.hawidget` (`Api.import_custom_widget`: the manifest is checked, the code is loaded once to see it works, and a package
  that does not load is taken out again). Each imported widget is shown there as it looks and is dragged onto the desktop
  like a clock; its cross (on hover) asks, in a menu, to take it out with every copy of it.
* On the right, a copy is a chip under **我的 Widget**, with a preview. Under the preview are the sizes it says it can be,
  then **its own settings** made from its `Field`s (a text or number in a field, a bool as a tick, a choice as a card with a
  menu, a list, feeds and launcher buttons as rows with the remove badge and an add row), then **權限**. Every copy has its
  own settings; what the user allows is answered once per package, and until it is answered the ticks are only a choice
  that **允許所選** applies.
* On the desktop the copy is a widget window of kind `custom` (`nativeui/customview.py` inside `nativeui/widget.py`): the
  same glass, dimming and place as the others; the kit's runtime draws it, takes the pointer, wheel, keyboard (the window
  borrows focus while an input has the caret), files dropped on it, and its `tick`/`standby_tick`. Right-click opens the
  editor on it.
* The config keeps `{"kind": "custom", "custom": {"widget": <package id>, "config": {...}}}` beside the widget's place; the
  packages, permission answers and each copy's memory are in a `widget_library/` folder beside the config file
  (`app/api/customs.py`, `widgetkit.library.Library`; the folder is `widget_library/`).

## What it does not do yet (honestly)

* **Only the glass is the program's, not yet measured for these widgets**: a widget of the kit stands on the same glass as
  every other (it says `background`), but the program's occlusion and standby rules have been tried on the examples only.
* **No sandbox** (above). A stronger boundary means another language or process.
* **Secrets are stored in plain text** in the user's settings file (not exported with shared settings). A credential
  store would be better.
* **No camera, location, notifications, calendar or contacts.** The microphone is the pattern for a device: an action,
  a permission, a consent line.
* **Media**: the player reads and controls whatever Windows reports (Spotify, a browser...); choosing *which* player, and
  Home Assistant players, are not in the kit. The clock's narrow digits need the font the program chooses.
* **The caret is placed at the end on a click** (not where the click landed) and does not blink.
* **No long-press** handler, and no multi-line text input.
* **No scrolling container**: a widget keeps its own offset (`on_scroll` + state) and clips itself.
* **Audio playback and video** are not provided.
* **`.hawidget` has no signing**; the user's trust is the only check.
* **Settings window text is the developer's** (`{"en", "zh"}`); the kit's own words (buttons, hints) are English with a
  Chinese line on the permission card only.

## Rules for a widget that looks right (the program's own, from `CLAUDE.md`)

Text comes from roles (`theme.text(p, th, "body", ...)`), never a size or colour of your own; words over a picture
stand on a backing; a removable thing shows the one remove badge; pressed things shrink a little; small things are
pressed within 44 px; and a screen that is drawn again keeps what is typed and what is open (the runtime does).
