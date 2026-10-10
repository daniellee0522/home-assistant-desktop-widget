"""A widget while it runs: its data, state, input focus and handlers, with no window of its own.

The host (widgetkit/host.py, or the program's widget window) feeds it what happens and draws what it says:

    rt = WidgetRuntime(WIDGET, user_config, grants=Grants(path), state_path=path, invalidate=window.update)
    rt.refresh_async()                        # sources, off the GUI thread; invalidate() when they have answered
    rt.draw(painter, theme, W, H)             # every time the window paints
    rt.press(x, y) / rt.release(x, y)         # the pointer; a release on what was pressed is a tap
    rt.text("ab") / rt.key("Enter")           # the keyboard, while rt.wants_keyboard
    rt.set_preedit("ㄋㄧ")                     # an input method's composing text
    rt.drag_move(x, y, paths) / rt.drop(x, y, paths)

Handlers' Actions are performed through actions.Executor, which asks permissions.Grants. A widget that raises is
caught: it shows an error card, and the rest of the program carries on.
"""
import copy
import json
import os
import threading
import time
import traceback
import unicodedata

from PySide6.QtCore import QRectF

from nativeui import render
from . import faces, permissions as perms
from .actions import Executor, GatedTransport, Services, accepts_file
from .definition import Action, Context, Move
from .sources import Store
from .theme import paragraph, text as draw_text

MAX_INPUT = 2000
DRAG_START = 6                    # px a pressed pointer must move before it is a drag and no longer a tap


class WidgetRuntime:
    def __init__(self, widget, user=None, *, services=None, grants=None, state_path=None, invalidate=None,
                 clock=time.time, on_denied=None, on_focus=None, lang="en"):
        self.widget, self.clock = widget, clock
        self.grants = grants or perms.Grants()
        self.sv = services or Services()
        self.invalidate = invalidate or (lambda: None)
        self.on_denied, self.on_focus = on_denied, on_focus
        self.state_path = state_path
        self.cfg = widget.settings(user)
        self.executor = Executor(widget, self.grants, self.sv)
        # A widget defined once may be placed many times: each copy gets sources of its own (their caches, and what
        # they hold, are not shared).
        self.sources = [copy.deepcopy(s) for s in widget.sources]
        self.store = Store(GatedTransport(self.sv.transport, self.executor.gate()), clock,
                           allow=lambda perm: self.grants.allowed(widget, perm))
        state = copy.deepcopy(widget.state)                  # its own copy: nested values are not shared between copies
        state.update(self._load_state())
        self.ctx = Context(self.cfg, state=state, on_change=self._state_changed, lang=lang)
        self.size_px = tuple(render.widget_size(widget.size))
        self.animating = False             # something eased this frame and has not come to rest: draw again soon
        self.redraw_in = None              # seconds until the widget asked to be drawn again (ctx.redraw_in), or None
        self._frame_at = None
        self._down = None                  # (x, y) where the pointer was pressed
        self._last = None                  # (x, y) of the last drag step; None until it is a drag
        self.error = None                  # why its last drawing failed, if it did
        self.handler_error = None          # why its last tap, drag, drop or Enter failed (kept until the next one runs)
        self.warnings = set()              # things a widget does that it should not (changing state while drawing)
        self.denied = []                   # permissions asked for and refused, in order
        self._closed = self._drawing = False
        self.standby = False
        self._dirty = False
        self._lock = threading.RLock()
        self._refreshing = self._again = False

    # ------------------------------------------------------------------ data
    def set_config(self, user):
        self.cfg = self.widget.settings(user)
        self.ctx.config = self.cfg
        self.store.invalidate()
        self._changed()

    def inputs(self):
        """What sources see: the settings, and the widget's own state under "state"."""
        return dict(self.cfg, state=self.ctx.snapshot_state(), size=self.size_px)

    def set_standby(self, on):
        """The program went into standby (the desktop is out of sight, or dimmed), or came out of it. In standby a widget
        is drawn quietly (`ctx.standby`) and rarely, and its sources are asked for less; coming out of it, what has
        gone stale is fetched at once."""
        on = bool(on)
        if on == self.standby:
            return
        self.standby = self.ctx.standby = on
        self._changed()
        if not on:
            self.refresh_async()

    def needs_glass(self):
        """Whether the window hosting this must show the desktop's glass behind it right now (see WidgetDef.background)."""
        return self.widget.needs_glass(self.standby)

    def refresh(self):
        data, errors = self.store.refresh(self.sources, self.inputs(), self.standby)
        self.ctx.data, self.ctx.errors = dict(data), dict(errors)

    def refresh_async(self):
        """Fetch what is due or whose inputs changed, off the GUI thread. A call while one is running asks for another
        pass when it ends, so a drag that moved on is never left showing the place it left."""
        if not self.sources or self._closed:
            return
        with self._lock:
            if self._refreshing:
                self._again = True
                return
            self._refreshing = True

        def work():
            try:
                while True:
                    self.refresh()
                    self.sv.gui(self._changed)
                    with self._lock:
                        if not self._again:
                            self._refreshing = False
                            return
                        self._again = False
            except Exception:
                with self._lock:
                    self._refreshing = False
                traceback.print_exc()
        self.sv.spawn(work)

    # ------------------------------------------------------------------ drawing
    def draw(self, p, th, W, H):
        ctx = self.ctx
        ctx.now = self.clock()
        ctx._dt = min(0.1, ctx.now - self._frame_at) if self._frame_at else 0.0
        self._frame_at = ctx.now
        ctx.hits.clear()
        ctx.drops.clear()
        ctx._input_ids = set()
        ctx._animating = False
        ctx._redraw_in = None
        ctx.size = (W, H)
        if self.size_px != (W, H):
            self.size_px = (W, H)                    # sources that depend on size (a map's tiles) are asked again
        self._drawing = True
        try:
            if self.widget.background == "solid" and not th.dim:
                faces.solid(p, th, W, H)               # the face every widget stands on unless it asked for glass
            self.widget.draw(p, th, W, H, ctx)
            self.error = None
        except Exception:
            self.error = traceback.format_exc(limit=3)
            ctx.hits.clear()
            self._error_card(p, th, W, H)
        finally:
            self._drawing = False
        self.animating = ctx._animating
        self.redraw_in = self._paced(ctx._redraw_in)
        if ctx.focus is not None and not ctx.is_input(ctx.focus):
            self._focus(None)                        # the input it was in is no longer drawn

    def _paced(self, seconds):
        """When it asked to be drawn again, kept to the pace of standby while the program is in it (never, if the widget says it
        wants no drawing in standby)."""
        if seconds is None or not self.standby:
            return seconds
        if self.widget.standby_tick == 0:
            return None
        return max(seconds, self.widget.standby_interval() or 30.0)

    def _error_card(self, p, th, W, H):
        draw_text(p, th, "headline", "This widget stopped", 24, 24, W - 48)
        last = self.error.strip().splitlines()[-1]
        paragraph(p, th, "secondary", last, QRectF(24, 60, W - 48, H - 84), max_lines=6)

    # ------------------------------------------------------------------ pointer
    def press(self, x, y):
        ctx = self.ctx
        hit = ctx.hits.at(x, y)
        ctx.pressed = hit
        ctx.pointer = (x, y)
        self._down, self._last = (x, y), None
        if hit is not None and ctx.is_input(hit):
            self._focus(hit)
            ctx.caret = len(ctx.inputs.get(hit, ""))
        elif ctx.focus is not None:
            self._focus(None)
        self._changed()
        return hit

    def release(self, x, y):
        ctx = self.ctx
        hit, pressed = ctx.hits.at(x, y), ctx.pressed
        ctx.pressed = None
        ctx.pointer = (x, y)
        self._changed()
        if self._last is not None:                                  # it was a drag: not a tap
            self._drag("end", x, y, pressed)
            self._down = self._last = None
            return
        self._down = None
        if pressed is not None and hit == pressed and not ctx.is_input(hit) and self.widget.on_tap:
            self._run(lambda: self.widget.on_tap(hit, ctx))

    def _drag(self, phase, x, y, id):
        self.ctx.pointer = (x, y)
        if not self.widget.on_drag or id is None:
            return
        lx, ly = self._last if phase != "start" else self._down
        mv = Move(phase, x, y, x - lx, y - ly, x - self._down[0], y - self._down[1])
        self._run(lambda: self.widget.on_drag(id, mv, self.ctx))

    def move(self, x, y):
        ctx = self.ctx
        if ctx.pressed is not None and self._down is not None and self.widget.on_drag \
                and not ctx.is_input(ctx.pressed):
            if self._last is None and (abs(x - self._down[0]) > DRAG_START or abs(y - self._down[1]) > DRAG_START):
                self._drag("start", x, y, ctx.pressed)
                self._last = (x, y)
            elif self._last is not None:
                self._drag("move", x, y, ctx.pressed)
                self._last = (x, y)
        hit = self.ctx.hits.at(x, y)
        if hit != self.ctx.hover:
            self.ctx.hover = hit
            self._changed()

    def leave(self):
        self.ctx.hover = self.ctx.pressed = None
        self._changed()

    def context(self, x, y):
        """A right click at (x, y). True when the widget takes it (it has an `on_context`); False leaves it to the program."""
        if not self.widget.on_context:
            return False
        hit = self.ctx.hits.at(x, y)
        self._run(lambda: self.widget.on_context(hit, self.ctx))
        return True

    def wheel(self, x, y, dy):
        """The mouse wheel at (x, y), `dy` px (> 0: down). True if the widget has something to scroll."""
        if not self.widget.on_scroll:
            return False
        hit = self.ctx.hits.at(x, y)
        self._run(lambda: self.widget.on_scroll(hit, dy, self.ctx))
        return True

    # ------------------------------------------------------------------ keyboard
    @property
    def wants_keyboard(self):
        return self.ctx.focus is not None

    def _focus(self, id):
        had = self.ctx.focus is not None
        self.ctx.focus = id
        self.ctx.preedit = ""
        if (id is not None) != had and self.on_focus:
            self.on_focus(id is not None)

    def blur(self):
        self._focus(None)
        self._changed()

    def text(self, chars):
        """Characters typed or pasted into the focused input (one line: line breaks become spaces)."""
        ctx, id = self.ctx, self.ctx.focus
        if id is None:
            return False
        chars = chars.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
        cur = ctx.inputs.get(id, "")
        room = MAX_INPUT - len(cur)
        # Control characters go; a tab or a line separator is a space. (Not isprintable(): that would also take the joiners
        # and variation marks that hold an emoji together.)
        chars = "".join((" " if c == "\t" or unicodedata.category(c) in ("Zl", "Zp") else c)
                        for c in chars if c == "\t" or unicodedata.category(c) != "Cc")[:max(0, room)]
        ctx.inputs[id] = cur[:ctx.caret] + chars + cur[ctx.caret:]
        ctx.caret += len(chars)
        ctx.preedit = ""
        self._changed()
        return True

    def set_preedit(self, s):
        if self.ctx.focus is not None:
            self.ctx.preedit = s
            self._changed()

    def key(self, name):
        ctx, id = self.ctx, self.ctx.focus
        if id is None:
            return False
        cur, c = ctx.inputs.get(id, ""), ctx.caret
        if name == "Backspace" and c:
            ctx.inputs[id], ctx.caret = cur[:c - 1] + cur[c:], c - 1
        elif name == "Delete":
            ctx.inputs[id] = cur[:c] + cur[c + 1:]
        elif name == "Left":
            ctx.caret = max(0, c - 1)
        elif name == "Right":
            ctx.caret = min(len(cur), c + 1)
        elif name == "Home":
            ctx.caret = 0
        elif name == "End":
            ctx.caret = len(cur)
        elif name == "Escape":
            self._focus(None)
        elif name == "Enter":
            self._submit(id)
        self._changed()
        return True

    def _submit(self, id):
        """Enter: what is typed goes to on_submit and the input is emptied (the handler may put something back with
        ctx.set_input). Nothing typed: nothing is sent."""
        ctx = self.ctx
        value = ctx.inputs.get(id, "")
        if not value.strip():
            return
        ctx.inputs[id], ctx.caret = "", 0
        if self.widget.on_submit:
            self._run(lambda: self.widget.on_submit(id, value, ctx))

    # ------------------------------------------------------------------ files dragged or dropped
    def _target(self, x, y, paths):
        for rect, id, accepts in reversed(self.ctx.drops):
            if rect.contains(x, y) and any(accepts_file(p, accepts) for p in paths):
                return id, accepts
        return None, ()

    def drag_move(self, x, y, paths):
        """Files are being dragged over (x, y): True when a target there will take them."""
        id, _ = self._target(x, y, paths)
        if id != self.ctx.drag_over:
            self.ctx.drag_over = id
            self._changed()
        return id is not None

    def drag_leave(self):
        if self.ctx.drag_over is not None:
            self.ctx.drag_over = None
            self._changed()

    def drop(self, x, y, paths):
        id, accepts = self._target(x, y, paths)
        self.ctx.drag_over = None
        self._changed()
        if id is None or not self.widget.on_drop:
            return False
        files = [p for p in paths if accepts_file(p, accepts)]
        self._run(lambda: self.widget.on_drop(id, files, self.ctx))
        return True

    # ------------------------------------------------------------------ handlers and actions
    def _run(self, handler):
        self.ctx.now = self.clock()
        self.handler_error = None
        try:
            result = handler()
            for action in (result if isinstance(result, (list, tuple)) else [result]):
                if isinstance(action, Action):
                    self._perform(action)
        except Exception:
            self.handler_error = traceback.format_exc(limit=3)
            traceback.print_exc()
        self.flush()
        self._changed()
        self.refresh_async()                       # what a handler changed may be what a source reads

    def _perform(self, action):
        try:
            self.executor.perform(action, self.ctx)
        except perms.PermissionDenied as e:
            needed = str(e)
            self.denied.append(needed)
            if self.on_denied:
                self.on_denied(self.widget, needed)
        except ValueError as e:                    # an action the widget got wrong: shown, not fatal
            self.ctx.state["_last_error"] = self.handler_error = str(e)
        except Exception as e:                     # the computer said no (a program that will not start...)
            self.ctx.state["_last_error"] = self.handler_error = "%s: %s" % (type(e).__name__, e)

    # ------------------------------------------------------------------ state kept between runs
    def _load_state(self):
        if self.state_path and os.path.exists(self.state_path):
            try:
                with open(self.state_path, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, ValueError):
                pass
        return {}

    def flush(self):
        """Write the state if it changed (only the parts that are JSON)."""
        if not self.state_path or not self._dirty:
            return
        keep = {}
        for k, v in self.ctx.snapshot_state().items():
            if k.startswith("_") or k.endswith("_busy") or k.endswith("_level") or k.endswith("_recording"):
                continue
            try:
                json.dumps(v)
                keep[k] = v
            except (TypeError, ValueError):
                pass
        os.makedirs(os.path.dirname(os.path.abspath(self.state_path)), exist_ok=True)
        tmp = self.state_path + ".tmp"
        with self._lock:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(keep, f, ensure_ascii=False)
            os.replace(tmp, self.state_path)
        self._dirty = False

    def _changed(self):
        """Something to draw differently (a hover, a caret)."""
        if not self._closed:
            self.invalidate()

    def _state_changed(self):
        """A handler or an action changed the widget's state: draw it, and keep it."""
        self._dirty = True
        if self._drawing:
            # Changing state while drawing would ask for another drawing, for ever. Keep the change, do not ask.
            self.warnings.add("the widget changed its state while drawing: change state in a handler, not in draw")
            return
        self._changed()

    def close(self):
        self._closed = True
        self.executor.close()
        self.store.close()
        self.flush()
