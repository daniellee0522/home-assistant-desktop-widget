# HA Widgets: rules for working on this project

Every screen is drawn natively (PySide6, `nativeui/`). These rules hold for every change; check them before
calling UI work done.

## House style (`nativeui/style.py`)

- **Text comes from roles.** Use `style.label(role, text, ...)` (or `style.TEXT[role]` / `style.font(role)` when
  painting). Never pass a size, weight or colour of your own. A new kind of text gets a role in `style.TEXT`
  first. `ink1` is for what is read; `ink2` for what is said about it, never lighter.
- **Words over glass stand on a backing.** Anything drawn over the desktop's glass that isn't a tile (such as
  the panel's detail) has `style.readable_backing` under it. Check it in light and dark themes, over both a
  light and a dark desktop.
- **Scrolling boxes fade.** `ui.ScrollView` fades `style.SCROLL_FADE` px at an end with more beyond it, by
  default. Pass `fade=0` only where per-tile glass is drawn under the content (the tray panel's grid).
- **Floating panes look alike.** Menus and pickers over a screen use `style.popup_pane` (shadow, solid fill,
  rim) and open through `controls.open_menu` / `controls.open_colors`, placed by `controls._place`. Lifted
  things (a dragged tile or row) use `style.LIFT_SHADOW`.
- **No modal dialogs** in the panel or the detail. They take focus and leave the panel waiting. Use a
  floating pane instead.

## Layout (`nativeui/style.py`, checked by `tests/test_layout.py`)

- **Centre by what is drawn, never by a guessed baseline.** Text in a shape or cell goes through
  `style.center_text` / `style.text_path`:
  - `align="ink"` for one mark alone in a shape, such as a number in a circle;
  - `align="cap"` (the default) for words or numbers in a row of cells, so they share one baseline;
  - `align="line"` for a line of words, as in a field or a button.

  Icons go through `style.center_icon`. Don't write `(h - fm.height()/10)/2 + fm.ascent()/10` in new code.
- **Repeated things sit on one grid.** Rows and columns of cells (a calendar, a picker, a palette) come
  from `style.grid`, so every row has the same height and every gap is the same. Never accumulate `y +=`
  with different numbers per row.
- **One remove badge.** Anything removable shows `style.remove_badge` (a cross icon in a red disc or
  capsule). Never draw a cross character; buttons that close use `icon="mdi:close"`.
- **Sizes line up.** Widget sizes come from `render.widget_size` (two of a size and `WIDGET_GAP` make the
  next). Tiles share a size's inside through `render.cell_size`. Never hard-code a widget's pixels.
- **Words don't run under controls.** Where buttons sit on a tile or card, the text width stops before
  them. Take their rectangles from the same function that places them (for example `render.mini_buttons`).
- **Words mean one thing per language.** When a Chinese word has two English meanings (開啟: on or open),
  give each meaning its own words (for example `appearance.WORDS`, or `已關閉` for a closed cover).

## Checking the look

Run `python tools/visual_check.py`. It writes `visual/` (git-ignored), which contains every widget kind
in light, dark and dimmed, the tiles in every size, the editor with a remove badge, each device's
detail, and the Home panel in edit mode. Look at the pictures for anything you changed before calling
it done. Add a new screen or widget kind to the script when you make it.

## What a tile is shown as (`nativeui/appearance.py`)

- A tile's icon decides its family; the family decides the icon's colour, the words under its name, and the
  look of its detail. `render.icon_name` / `icon_color` / `state_text` and the detail builders all read
  `appearance.family(tile)`. Never special-case a domain or an icon elsewhere.
- Switches and input booleans can take any on/off family. Other devices take only other shapes of their own.
  Any other icon only changes the picture. New icons go into `appearance.FAMILIES`, not into scattered
  lists.
- Under a tile's name is its state, never a free label. Sensors show their reading.

## Behaviour that must survive a rebuild

Screens are rebuilt from scratch when a state arrives. A rebuild must keep:

- the scroll position (`DetailContent` keeps `body_scroll.offset`);
- an open menu, re-anchored to the card that replaced its own, still marked open, and showing the current
  choice (`controls.reattach_menu`, called after the new tree is in the scene);
- the size and scale a detail was fitted to while the same device is shown (`tall_fit`, `PanelScene.detail_k`),
  so nothing jumps;
- the glass. Don't change the window's size for a state update. `fit_glass` keeps the old picture until a
  new one comes.

When adding state to a screen (an open menu, a drag in progress, a hover), make sure rebuilding the screen
carries it over. Add a test that pushes a new state while it is active.

## Interaction

- Shape new features after iOS / Home Assistant. Choices open as floating menus, not inline expansions.
  The tray panel's detail never scrolls (`DetailContent.build(fit=True)` and the panel's scale).
- Dragging always previews: what is carried follows the pointer, and the rest make room where they'll be.
- Pickers take several at once where it makes sense, and offer "全選" for a group.
- Controls that show a position (a song's progress, sliders) can be dragged, and their knobs stay inside
  their bounds (not clipped by a scroll box).
- Repaints are not free. A self-ticking view stops when its window is hidden. Something that moves every
  second redraws only what moves over a picture kept for the rest (the clock's ring over its face), and moves
  in a short eased step rather than continuously (`kinds.HAND_MOVE_S`: ~2% of a core against ~7%). Blurs are made at reduced
  resolution (`Scene.paint_blurred`). Measure animations with a script before calling them smooth.

## Checking work

- `python -m unittest discover -s tests` must pass. The tests build real windows. Calls from worker threads
  reach the GUI thread through `qtshell.ensure_marshal()`, which every `Scene` sets up.
- Look at the result: render the screens (scripts in the session scratchpad or `packaging/render_readme.py`)
  and exercise the interaction (press, drag, a state arriving mid-interaction), not only static pictures.
- Strings shown to people are Traditional Chinese in the code, with English in `nativeui/i18n_en.json`.
  Add both.
- Release and local install steps: see the user's memory notes (`packaging/release.ps1`,
  `packaging/build.py --installer`).
