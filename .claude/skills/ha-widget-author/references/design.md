# Designing a widget that belongs

The program's look is iOS-like: a rounded card, calm type, one accent at a time, big numbers, generous space. A widget made with
the kit's roles and `th` colours has that for free; these notes are for the layout.

## The four sizes

| Name | Room (W x H) | Shape | Good for |
| --- | --- | --- | --- |
| `1x1` | 160 x 161 | small square | one number or icon, a single control |
| `2x2` | 333 x 334 | square | a ring or a number with a label, a short list (3 rows), a picture |
| `2x4` | 678 x 334 | wide | a number with a chart beside it, a row of buttons, a list of 3 to 4 rows, a search bar |
| `4x4` | 678 x 680 | large | a list of 8 rows, a calendar, a chart with a list, news |

Declare `size` (the default) and `sizes` (others). `draw` chooses a layout: `ctx.size_name()` or compare `W` and `H`
(`wide = W > H * 1.5`). Lay out from `W` and `H`, with a margin `PAD` of 22 to 26 and gaps that are multiples of 4 or 8.
Look at `widgetkit/examples/water.py` (a layout for each size) and `assets/tally.py`.

## Layout rules

- **One focus.** The thing the person looks at (a number, a picture) is largest; what explains it is `caption`/`secondary` (ink2).
- **Align to the margin**, not to the middle, unless it is a single mark alone (a ring, a number): then centre it. Centre text in a
  box with `align="c"` and a width, not by guessing x.
- **Rows share a grid**: the same height and gap for every row; compute `y = top + i * row_h`.
- **Press targets** at least 44 x 44 (the kit enlarges a hit area to that); keep controls clear of the card's rounded corners
  (margin 14+) and keep text from running under them (give `text(..., w=...)` the width that stops before a button).
- **Cut long words**, do not wrap into other things: `text(..., w=width)` cuts with …; `paragraph(..., max_lines=n)` wraps and cuts.
  The check tool's longer made-up language (`pseudo`) shows what breaks in a longer language.
- **Empty and error states** are part of the design: "Loading…" before the first answer, "No data" when it failed (`ctx.errors`),
  "Choose pictures in settings" when it has nothing to show. Never a blank card.
- **Numbers** that change are `display` / `hero`; format them (`"{:,.2f}"`, `"%d°"`); units in `caption`.

## Colour

Only through `th`. `th.accent("green"|"red"|"blue"|"teal"|"cyan"|"yellow")` for the one thing that carries meaning (up = green,
down = red, a ring's fill); ink for the rest. Do not paint a background colour: the card is drawn for you (solid face awake).
A widget whose whole card is a picture or its own colour calls `faces.tinted(p, th, W, H, base_colour)` first and then
draws ink in white. In **standby** (`th.dim` / `ctx.standby`) the card is clear glass and every ink and accent is white: so
do not tell two things apart by colour alone (use position, shape or weight), and draw nothing that moves.

## Standby

The program dims every widget when the user is busy elsewhere. A widget does nothing about it except: avoid hard-coded colours,
use `mono=th.dim` for pictures (white, clear where dark), and keep `tick` / `redraw_in` modest (the program draws no sooner than
once a minute in standby unless `standby_tick` says otherwise; `0` = not at all, right for a widget that shows nothing live).

## Turning a picture into a widget

1. Describe the picture back in words: regions, what is data, what is fixed.
2. Map each region: big number → `text(..., "display" or "hero")`; small label → `caption`/`eyebrow` (ink2); ring/progress →
   `charts.ring`/`bar`/`gauge`; chart → `charts.line`/`columns`/`sparkline`; list rows → a loop with `rows.quote_row` or your own
   rows; photo → `media.picture`; icon → `controls.icon(p, "mdi:...", colour, rect)`; buttons → `controls.button`/`icon_button`;
   an input → `controls.search_bar` with `ctx.text_input(id)` and `on_submit`.
3. Decide the size from the picture's aspect (square → `2x2`, about 2:1 → `2x4`, tall/large → `4x4`) and add the others only if the layout
   can follow.
4. Anything that must be set by the user becomes a `Field` (a symbol, a city, a date, a goal, a unit, a picture list).
5. Write it, run `python -m widgetkit.check`, compare the preview with the picture, and list the differences you chose to keep
   (the program's type, glass and colours win over the picture's).

## Things the kit does not do (say so instead of faking it)

No camera, location, notifications, calendar or contacts; no video; no multi-line text input; no custom fonts; no blur or glass
of your own; no long-press; APNG is not read. A widget is Python in the program (no sandbox): permissions bound what the kit's
actions do and tell the user what it asks, nothing more.
