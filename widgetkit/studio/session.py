"""The studio without a window: one widget file being developed, its settings, memory and clock, a runtime for each
language and size on show, what it asked to do (as a log, not done), and what looks wrong in it. The window
(studio/ui.py) is a view of this; tests drive it directly.
"""
import json
import os
import time
from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPen

from nativeui import render
from .. import pseudo as pseudo_mod
from .. import theme as theme_mod
from ..actions import Services
from ..permissions import Grants
from ..runtime import WidgetRuntime
from ..sources import Transport
from ..theme import Theme, smooth
from . import loader

LANGUAGES = {"en": "English", "zh-TW": "繁體中文", "pseudo": "Pseudo (+40% long)", "pseudo-zh": "Pseudo 中文 (+40% long)"}
LANG_CTX = {"pseudo": "en", "pseudo-zh": "zh-TW"}      # what ctx.lang is in a false language: the real one it is made from
SLOW_DRAW_S = 0.05                           # a drawing slower than this is reported (a frame is 0.016)
THEMES = ("dark", "light")
TINY = 32                                    # a control drawn smaller than this (px) is flagged: it is hard to press


@dataclass(frozen=True)
class Cell:
    lang: str
    size: str
    theme: str

    @property
    def caption(self):
        return "%s · %s · %s" % (self.size, self.theme, self.lang)


@dataclass
class Issue:
    kind: str                                # "error", "cut", "tiny", "load"
    text: str
    cell: object = None


class FixtureTransport:
    """Answers web requests from a file {"address piece": answer}, so a widget can be developed with no network."""

    def __init__(self, table):
        self.table = table

    def get(self, url, timeout=10):
        for piece, answer in self.table.items():
            if piece in url:
                return answer.encode() if isinstance(answer, str) else json.dumps(answer).encode()
        raise OSError("no fixture for " + url)


class Session:
    def __init__(self, path, transport=None, clock=time.time):
        self.path = os.path.abspath(path)
        self.entry = loader.entry_of(self.path) if os.path.exists(self.path) else self.path
        self.sidecar = os.path.join(os.path.dirname(self.entry), ".studio-" + os.path.basename(self.entry) + ".json")
        self.widget, self.load_error = None, None
        self.config, self.state = {}, {}
        self.langs, self.themes, self.sizes = ["en", "zh-TW"], list(THEMES), None
        self.scale = 1.0
        self.overlays = {"hits": False, "safe": False}
        self.fake_now = None                 # a time to pretend it is; None: now
        self.real_actions = False            # do what the widget asks (open pages, record...) rather than only log it
        self.threaded = False                # fetch data off the GUI thread (the window sets this; tests do not)
        self.standby = False                 # show every copy as it is when the program is in standby (dimmed, drawn rarely)
        self._clock = clock
        self.log = []                        # what the widget asked to do: [(time, text)]
        self.issues = {}                     # cell -> [Issue]
        self.runtimes = {}
        self.on_change = lambda: None
        self.gui = lambda fn: fn()
        self.spawn = lambda fn: fn()
        self._transport = transport
        self.fixtures = self.entry + ".fixtures.json"
        self.grants = Grants()
        self._restore()
        self.reload()

    # ------------------------------------------------------------------ the file
    def reload(self):
        """Import the widget again. A mistake leaves the last good widget showing, with the message in `load_error`."""
        widget, error = loader.load(self.path)
        self.load_error = error
        if widget is None:
            return False
        self.widget = widget
        keys = {f.key for f in widget.config}
        self.config = {k: v for k, v in self.config.items() if k in keys}
        self.grants.decide(widget, allow=widget.permissions)
        self.sizes = [s for s in (self.sizes or []) if s in widget.supported_sizes()] or list(widget.supported_sizes())
        for rt in self.runtimes.values():                       # let go of what the old copies held (recorders, readers)
            rt.close()
        self.runtimes.clear()
        self.issues.clear()
        self.on_change()
        return True

    # ------------------------------------------------------------------ what is shown
    def cells(self):
        if not self.widget:
            return []
        return [Cell(l, s, t) for s in self.sizes for l in self.langs for t in self.themes]

    def size_px(self, cell):
        return tuple(render.widget_size(cell.size))

    def clock(self):
        return self.fake_now if self.fake_now is not None else self._clock()

    def transport(self):
        if self._transport is not None:
            return self._transport
        if os.path.exists(self.fixtures):
            with open(self.fixtures, encoding="utf-8") as f:
                return FixtureTransport(json.load(f))
        return Transport()

    def services(self):
        sv = Services(transport=self.transport(), spawn=self.spawn, gui=self.gui)
        real = Services()

        def doing(text, then=None):
            def go(*a, **k):
                self.log.append((self.clock(), text(*a, **k)))
                self.on_change()
                return then(*a, **k) if (then and self.real_actions) else True
            return go
        sv.opener = doing(lambda u: "open page %s" % u, real.opener)
        sv.starter = doing(lambda p, a: "run %s %s" % (p, " ".join(a)), real.starter)
        sv.clipboard = doing(lambda t: "copy %r" % t, real.clipboard)
        sv.app_opener = doing(lambda u: "open app %s" % u, real.app_opener)
        sv.media_control = doing(lambda c, s: "media %s%s" % (c, "" if s is None else " to %.1f s" % s), real.media_control)
        sv.chooser = lambda kind: (self.log.append((self.clock(), "choose a file (%s)" % kind)), self.on_change(), "")[2]
        sv.protocols = lambda scheme: True
        sv.recorder_factory = lambda path, seconds, on_level, on_done: (
            real.recorder_factory if self.real_actions else _NoRecorder)(path, seconds, on_level, on_done)
        return sv

    def runtime(self, cell):
        key = (cell.lang, cell.size)
        rt = self.runtimes.get(key)
        if rt is None:
            rt = WidgetRuntime(self.widget, self.config, services=self.services(), grants=self.grants,
                               invalidate=self.on_change, clock=self.clock, lang=LANG_CTX.get(cell.lang, cell.lang))
            rt.ctx.state = self.state                      # one memory for every copy on show: they are the same widget
            rt.size_px = self.size_px(cell)
            rt.set_standby(self.standby)
            self.runtimes[key] = rt
            rt.refresh_async() if self.threaded else rt.refresh()
        return rt

    def _share_data(self):
        """Fetch once, show everywhere: a copy that has no data yet takes it from one that has."""
        have = next((rt for rt in self.runtimes.values() if rt.ctx.data), None)
        if have:
            for rt in self.runtimes.values():
                if not rt.ctx.data:
                    rt.ctx.data, rt.ctx.errors = have.ctx.data, have.ctx.errors

    def refresh(self):
        """Fetch the widget's data again (live, or from its fixtures file)."""
        first = None
        for rt in self.runtimes.values():
            rt.store.invalidate()
            if first is None:
                rt.refresh()
                first = rt
            else:
                rt.ctx.data, rt.ctx.errors = first.ctx.data, first.ctx.errors
        self.on_change()

    def set_standby(self, on):
        """Show the widget as it is in standby, or awake again."""
        self.standby = bool(on)
        for rt in self.runtimes.values():
            rt.set_standby(on)
        self.on_change()

    def tick_seconds(self):
        """Seconds between redraws the widget asks for now (awake, or in standby); None for none."""
        if not self.widget:
            return None
        return self.widget.standby_interval() if self.standby else self.widget.tick

    # ------------------------------------------------------------------ settings and memory
    def set_config(self, config):
        self.config = dict(config)
        for rt in self.runtimes.values():
            rt.set_config(self.config)
        self.refresh()
        self.save()

    def state_json(self):
        return json.dumps(self.state, ensure_ascii=False, indent=2, default=str)

    def apply_state_json(self, text):
        """Replace the widget's memory with what the developer typed. None if it took, else why not."""
        try:
            new = json.loads(text or "{}")
        except ValueError as e:
            return str(e)
        if not isinstance(new, dict):
            return "the state must be a JSON object {...}"
        self.state.clear()
        self.state.update(new)
        self.on_change()
        self.save()
        return None

    def reset_state(self):
        self.state.clear()
        self.state.update(self.widget.state if self.widget else {})
        self.on_change()
        self.save()

    # ------------------------------------------------------------------ drawing and what is found wrong
    def draw_cell(self, p, cell, overlays=True):
        """Draw one copy at its own size (0, 0) and note what looks wrong."""
        rt = self.runtime(cell)
        self._share_data()
        th = Theme(cell.theme, dim=self.standby)
        W, H = self.size_px(cell)
        found, pieces = [], []
        cut = lambda kind, role, wanted, shown, width: found.append(Issue(
            "cut", "text cut (%s): %r became %r in %.0f px" % (role, wanted, shown, width), cell))
        drawn = lambda role, s, rect: pieces.append((role, s, rect))
        theme_mod.listeners.append(cut)
        theme_mod.drawn_listeners.append(drawn)
        theme_mod.pseudo = pseudo_mod.MODES.get(cell.lang)             # a false language changes every word drawn
        p.save()
        smooth(p)
        started = time.perf_counter()
        try:
            render.draw_card_bg(p, W, H, th.tokens, "classic", cell.theme)
            rt.draw(p, th, W, H)
        finally:
            theme_mod.pseudo = None
            theme_mod.listeners.remove(cut)
            theme_mod.drawn_listeners.remove(drawn)
        elapsed = time.perf_counter() - started
        if elapsed > SLOW_DRAW_S:
            found.append(Issue("slow", "drawing took %d ms: a frame is 16 ms (a widget that moves must draw in less)"
                               % (elapsed * 1000), cell))
        found += self._layout_issues(cell, pieces, W, H)
        if rt.error:
            found.append(Issue("error", rt.error.strip().splitlines()[-1], cell))
        for rect, id in rt.ctx.hits.drawn:
            if (rect.width() < TINY or rect.height() < TINY) and rect.width() < W * 0.9:
                found.append(Issue("tiny", "%r is drawn %.0f x %.0f px: small to press (pressable area is made 44 px)"
                                   % (id, rect.width(), rect.height()), cell))
        self.issues[cell] = found
        if overlays:
            self._overlays(p, rt, W, H)
        p.restore()

    @staticmethod
    def _layout_issues(cell, pieces, W, H):
        """What the pieces of text drawn say about the layout: any outside the widget, and any on top of another."""
        found = []
        for role, s, r in pieces:
            if r.left() < -0.5 or r.top() < -0.5 or r.right() > W + 0.5 or r.bottom() > H + 0.5:
                found.append(Issue("overflow", "text %r (%s) runs outside the widget" % (s, role), cell))
        for i, (ra, a, A) in enumerate(pieces):
            for rb, b, B in pieces[i + 1:]:
                inner = A.adjusted(0, 2, 0, -2).intersected(B.adjusted(0, 2, 0, -2))   # line boxes touch; text does not
                if inner.width() > 3 and inner.height() > 3 and len(found) < 40:
                    found.append(Issue("overlap", "text %r (%s) and %r (%s) are on top of each other" % (a, ra, b, rb), cell))
        return found

    def _overlays(self, p, rt, W, H):
        if self.overlays["safe"]:
            p.setPen(QPen(QColor(255, 80, 200, 200), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(22, 22, W - 44, H - 44))
        if self.overlays["hits"]:
            for rect, id in rt.ctx.hits.drawn:
                small = rect.width() < TINY or rect.height() < TINY
                p.setPen(QPen(QColor(255, 159, 10) if small else QColor(48, 209, 88), 1.5))
                p.setBrush(QColor(48, 209, 88, 30) if not small else QColor(255, 159, 10, 40))
                p.drawRect(rect)

    def check_backgrounds(self):
        """Does what each widget declares about its background (WidgetDef.background) match what it draws? Draws every size
        in each theme once and looks at how much of the card is opaque. In standby there is nothing to check: it is glass."""
        from PySide6.QtGui import QImage, QPainter
        self.bg_issues = []
        if not self.widget or self.standby:
            return self.bg_issues
        for size in self.sizes:
            for theme in self.themes:
                cell = Cell(self.langs[0], size, theme)
                W, H = self.size_px(cell)
                img = QImage(round(W), round(H), QImage.Format_ARGB32_Premultiplied)
                img.fill(0)
                q = QPainter(img)
                self.draw_cell(q, cell, overlays=False)
                q.end()
                spots = [img.pixelColor(round(W * fx), round(H * fy)).alpha() for fx in (0.12, 0.3, 0.5, 0.7, 0.88)
                         for fy in (0.12, 0.3, 0.5, 0.7, 0.88)]
                opaque = all(a >= 254 for a in spots)
                if self.widget.background == "solid" and not opaque:
                    self.bg_issues.append(Issue("background", "declares background=\"solid\" but the card is not opaque all over "
                                                "(%d of %d sample points show the glass)" % (sum(a < 254 for a in spots), len(spots)), cell))
                elif self.widget.background == "glass" and opaque:
                    self.bg_issues.append(Issue("hint", "covers the whole card with an opaque face: declare background=\"solid\" and the "
                                                "program need not capture the desktop behind it", cell))
        return self.bg_issues

    def all_issues(self):
        out = [Issue("load", self.load_error)] if self.load_error else []
        for found in self.issues.values():
            out.extend(found)
        out.extend(getattr(self, "bg_issues", []))
        for rt in self.runtimes.values():
            if rt.handler_error:
                out.append(Issue("error", "when pressed: " + rt.handler_error.strip().splitlines()[-1]))
            out.extend(Issue("warning", w) for w in sorted(rt.warnings))
        seen, unique = set(), []
        for i in out:                                      # the same cut in two themes is one thing to fix
            key = (i.kind, i.text, i.cell.size if i.cell else None, i.cell.lang if i.cell else None)
            if key not in seen:
                seen.add(key)
                unique.append(i)
        return unique

    # ------------------------------------------------------------------ the pointer, per copy
    def press(self, cell, x, y):
        self.runtime(cell).press(x, y)

    def release(self, cell, x, y):
        self.runtime(cell).release(x, y)

    def move(self, cell, x, y):
        self.runtime(cell).move(x, y)

    # ------------------------------------------------------------------ keeping choices between runs
    def save(self):
        try:
            with open(self.sidecar, "w", encoding="utf-8") as f:
                json.dump({"config": self.config, "state": self.state, "langs": self.langs, "themes": self.themes,
                           "sizes": self.sizes, "scale": self.scale}, f, ensure_ascii=False, indent=2, default=str)
        except OSError:
            pass

    def _restore(self):
        try:
            with open(self.sidecar, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return
        self.config = d.get("config", {})
        self.state.update(d.get("state", {}))
        self.langs = [l for l in d.get("langs", self.langs) if l in LANGUAGES] or self.langs
        self.themes = [t for t in d.get("themes", self.themes) if t in THEMES] or self.themes
        self.sizes = d.get("sizes")
        self.scale = d.get("scale", 1.0)


class _NoRecorder:
    """In the studio the microphone is not opened unless 'do it for real' is on."""

    def __init__(self, path, seconds, on_level, on_done):
        self.on_level, self.on_done, self.path = on_level, on_done, path

    def start(self):
        self.on_level(0.4)

    def stop(self):
        self.on_level(0.0)
        self.on_done(None)
