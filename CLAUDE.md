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
- Repaints are not free. A self-ticking view stops when its window is hidden. Blurs are made at reduced
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
