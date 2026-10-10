"""The settings window of a widget, made from its `Field`s: the user changes choices, the developer writes none of it.

    form = Form(WIDGET, saved_values, on_change=lambda values, key: save_and_refresh(values))
    height = form.draw(p, th, QRectF(0, 0, 520, 900))      # draws it and records what is where
    form.click(x, y)            # a press: toggles, steps, opens a menu, removes a chip, focuses a field
    form.type("NVDA")           # characters the host received while a field has focus
    form.press("Enter")         # "Enter", "Backspace", "Escape"

The form owns what is being typed and which menu is open; `form.values` is always valid (cleaned by its Field).
A host rebuilding the screen keeps the same Form, so a typed draft and an open menu survive it (CLAUDE.md).
Choices open as a floating menu, never inline; anything removable shows the program's one remove badge.
"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPen

from nativeui import style, ui

from . import controls
from .definition import text_of
from .theme import line_height, paragraph, role_font, text

ROW = 48
GAP = 14
CHIP_H = 36
MENU_ROW = 42
MENU_ROWS = 8
FEED_H = 56


class Form:
    def __init__(self, widget, user=None, on_change=None, lang="en"):
        self.widget, self.lang = widget, lang
        self.values = widget.settings(user)
        self.on_change = on_change
        self.focus = None               # the text / list / feeds field being typed in
        self.draft = {}                 # what is typed in each, not yet kept
        self.menu = None                # the choice whose menu is open
        self.menu_scroll = 0.0          # how far a long menu is scrolled (px)
        self._menu_box, self._menu_max = None, 0
        self.hits = controls.HitMap()
        self._anchor = None

    # ------------------------------------------------------------------ what the user does
    def field(self, key):
        return next(f for f in self.widget.config if f.key == key)

    def _set(self, key, value):
        value = self.field(key).clean(value)
        if value != self.values[key]:
            self.values[key] = value
            if self.on_change:
                self.on_change(dict(self.values), key)

    def click(self, x, y):
        hit = self.hits.at(x, y)
        if self.menu and not (hit and hit[0] == "pick"):          # a press outside an open menu only closes it
            self.menu = None
            return
        self._blur(keep=hit and hit[0] in ("text", "add") and hit[1])
        if not hit:
            return
        kind, key = hit[0], hit[1]
        if kind in ("text", "add"):
            self.focus = key
            self.draft.setdefault(key, str(self.values[key]) if kind == "text" else "")
        elif kind == "toggle":
            self._set(key, not self.values[key])
        elif kind == "step":
            f = self.field(key)
            self._set(key, self.values[key] + hit[2] * f.step)
        elif kind == "menu":
            self.menu = key
            f = self.field(key)                                       # a long menu opens with the choice in view
            idx = list(f.options).index(self.values[key]) if self.values[key] in f.options else 0
            self.menu_scroll = max(0.0, (idx - MENU_ROWS // 2) * MENU_ROW)
        elif kind == "pick":
            self._set(key, hit[2])
            self.menu = None
        elif kind == "remove":
            items = list(self.values[key])
            del items[hit[2]]
            self._set(key, items)

    def type(self, chars):
        if self.focus:
            self.draft[self.focus] = self.draft.get(self.focus, "") + chars

    def press(self, name):
        if not self.focus:
            return
        key = self.focus
        if name == "Backspace":
            self.draft[key] = self.draft.get(key, "")[:-1]
        elif name == "Enter":
            self._commit(key)
            if self.field(key).type == "text":
                self.focus = None
        elif name == "Escape":
            self.draft.pop(key, None)
            self.focus = None

    def _commit(self, key):
        f, d = self.field(key), self.draft.get(key, "").strip()
        if f.type in ("text", "secret"):
            if d:
                self._set(key, d)
            self.draft.pop(key, None)
        elif d:
            if f.type == "feeds":
                name, sep, url = d.partition("=")
                d = {"name": name.strip(), "url": url.strip()} if sep and url.strip() else d
            elif f.type == "launchers":
                icon, sep, url = d.partition("=")
                d = {"icon": icon.strip() or "mdi:link", "url": url.strip()} if sep and url.strip() else {"icon": "mdi:link", "url": d}
            self._set(key, list(self.values[key]) + [d])
            self.draft[key] = ""

    def _blur(self, keep=None):
        """Leaving a field keeps what was typed in it."""
        if self.focus and self.focus != keep:
            self._commit(self.focus)
            self.draft.pop(self.focus, None)
            self.focus = None

    # ------------------------------------------------------------------ drawing
    def draw(self, p, th, rect):
        """Draw every field in order inside `rect`; returns the height used (to scroll by)."""
        self.hits.clear()
        self._anchor = None
        y = rect.top()
        for f in self.widget.config:
            y += getattr(self, "_row_" + {"text": "stacked", "secret": "stacked", "list": "list", "images": "list",
                                                "feeds": "feeds", "launchers": "feeds"}.get(f.type, "inline"))(
                p, th, f, rect.left(), y, rect.width()) + GAP
        if self.menu and self._anchor:
            self._draw_menu(p, th, self.field(self.menu), self._anchor)
        return y - rect.top()

    def _label(self, p, th, f, x, y, w, role="label"):
        text(p, th, role, text_of(f.label, self.lang) or f.key, x, y, w)
        return line_height(role)

    def _help(self, p, th, f, x, y, w):
        if not f.help:
            return 0
        return 4 + paragraph(p, th, "hint", text_of(f.help, self.lang), QRectF(x, y + 4, w, 60))

    def _row_inline(self, p, th, f, x, y, w):
        """Label left, its control right: a switch, a number, a choice."""
        mid = y + ROW / 2
        text(p, th, "body", text_of(f.label, self.lang) or f.key, x, mid - line_height("body") / 2, w - 150)
        blue, v = th.accent("blue"), self.values[f.key]
        if f.type == "bool":
            controls.toggle(p, th, QRectF(x + w - 52, mid - 16, 52, 32), v, th.accent("green"))
            self.hits.add(QRectF(x + w - 52, mid - 16, 52, 32), ("toggle", f.key))
        elif f.type == "number":
            box = QRectF(x + w - 96, mid - 17, 96, 34)
            controls.stepper(p, th, box, blue)
            self.hits.add(QRectF(box.left(), box.top(), 48, 34), ("step", f.key, -1))
            self.hits.add(QRectF(box.center().x(), box.top(), 48, 34), ("step", f.key, 1))
            text(p, th, "value", "%g" % v, x + w - 96 - 70, mid - line_height("value") / 2, 60, "r")
        elif f.type == "choice":
            pill = QRectF(x + w - 150, mid - 18, 150, 36)
            self._pill(p, th, pill, f.shown(v, self.lang), open_=self.menu == f.key)
            self.hits.add(pill, ("menu", f.key))
            if self.menu == f.key:
                self._anchor = pill
        return ROW + self._help(p, th, f, x, y + ROW, w)

    def _pill(self, p, th, rect, label, open_=False):
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(th.faint(th.accent("blue"), 0.28 if open_ else 0.16))
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.restore()
        fg = th.legible(th.accent("blue"))
        text(p, th, "body", label, rect.left() + 16, rect.center().y() - line_height("body") / 2, rect.width() - 52,
             color=fg)
        controls.icon(p, "mdi:unfold-more-horizontal", fg, QRectF(rect.right() - 34, rect.top(), 24, rect.height()), 18)

    def _row_stacked(self, p, th, f, x, y, w):
        y0 = y
        y += self._label(p, th, f, x, y, w) + 8
        focus = self.focus == f.key
        value = self.draft.get(f.key, "") if focus else str(self.values[f.key])
        if f.type == "secret":                       # a key is never drawn: only that there is one
            value = "\u2022" * len(value)
        box = QRectF(x, y, w, controls_height())
        controls.field(p, th, box, value, "", "focus" if focus else "")
        self.hits.add(box, ("text", f.key))
        y += box.height()
        return y - y0 + self._help(p, th, f, x, y, w)

    def _row_list(self, p, th, f, x, y, w):
        y0 = y
        y += self._label(p, th, f, x, y, w) + 8
        font = role_font("body")
        cx, cy = x, y
        for i, item in enumerate(self.values[f.key]):
            shown = str(item).partition("=")[2] or str(item).partition("=")[0]
            cw = min(w, ui.text_width(shown, font) + 14 + 12 + 26)
            if cx > x and cx + cw > x + w:
                cx, cy = x, cy + CHIP_H + 8
            self._chip(p, th, QRectF(cx, cy, cw, CHIP_H), shown, f.key, i)
            cx += cw + 8
        y = cy + CHIP_H + 10
        return y - y0 + self._adder(p, th, f, x, y, w)

    def _chip(self, p, th, rect, label, key, i):
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(th.faint(None, 0.16))
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.restore()
        text(p, th, "body", label, rect.left() + 14, rect.center().y() - line_height("body") / 2, rect.width() - 14 - 30)
        badge = QRectF(rect.right() - 26, rect.center().y() - 10, 20, 20)
        style.remove_badge(p, badge, shadow=False)
        self.hits.add(badge, ("remove", key, i))

    def _adder(self, p, th, f, x, y, w):
        focus = self.focus == f.key
        hint = {"feeds": "name=https://…  or  https://…", "launchers": "mdi:camera=https://…  or  https://…"}.get(f.type, "Add")
        box = QRectF(x, y, w, controls_height())
        controls.field(p, th, box, self.draft.get(f.key, "") if focus else "", hint, "focus" if focus else "",
                       icon_name="mdi:plus")
        self.hits.add(box, ("add", f.key))
        return box.height() + self._help(p, th, f, x, y + box.height(), w)

    def _row_feeds(self, p, th, f, x, y, w):
        y0 = y
        y += self._label(p, th, f, x, y, w) + 8
        for i, feed in enumerate(self.values[f.key]):
            rect = QRectF(x, y, w, FEED_H)
            p.save()
            p.setPen(Qt.NoPen)
            p.setBrush(th.faint(None, 0.12))
            p.drawRoundedRect(rect, 16, 16)
            p.restore()
            text(p, th, "body", feed.get("name") or feed.get("label") or feed.get("icon") or feed["url"], x + 16, y + 7, w - 70)
            text(p, th, "caption", feed["url"], x + 16, y + 30, w - 70)
            badge = QRectF(rect.right() - 36, rect.center().y() - 10, 20, 20)
            style.remove_badge(p, badge, shadow=False)
            self.hits.add(badge, ("remove", f.key, i))
            y += FEED_H + 8
        return y - y0 + self._adder(p, th, f, x, y, w)

    def _draw_menu(self, p, th, f, anchor):
        """The floating menu of a choice: at most MENU_ROWS rows show; a longer list scrolls (wheel) and fades at an
        end with more beyond it."""
        opts = list(f.options)
        font = role_font("menu")
        w = max(ui.text_width(f.shown(o, self.lang), font) for o in opts) + 76
        total, shown = len(opts) * MENU_ROW, min(len(opts), MENU_ROWS) * MENU_ROW
        self._menu_max = total - shown
        self.menu_scroll = max(0.0, min(self._menu_max, self.menu_scroll))
        box = QRectF(anchor.right() - w, anchor.bottom() + 6, w, shown + 12)
        self._menu_box = box
        style.shadow(p, box, 16, style.SHADOW)
        solid = QColor(44, 46, 52) if th.name == "dark" else QColor(255, 255, 255)
        p.save()
        p.setBrush(solid)
        p.setPen(QPen(th.faint(None, 0.2), 1))
        p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 16, 16)
        view = box.adjusted(6, 6, -6, -6)
        p.setClipRect(view)
        for i, o in enumerate(opts):
            row = QRectF(view.left(), view.top() + i * MENU_ROW - self.menu_scroll, view.width(), MENU_ROW)
            if row.bottom() <= view.top() or row.top() >= view.bottom():
                continue
            if o == self.values[f.key]:
                p.setPen(Qt.NoPen)
                p.setBrush(th.faint(th.accent("blue"), 0.16))
                p.drawRoundedRect(row, 10, 10)
                controls.icon(p, "mdi:check", th.legible(th.accent("blue")), QRectF(row.left() + 6, row.top(), 28, MENU_ROW), 18)
            text(p, th, "menu", f.shown(o, self.lang), row.left() + 38, row.center().y() - line_height("menu") / 2,
                 row.width() - 44)
            self.hits.add(row.intersected(view), ("pick", f.key, o))
        for at_top in (True, False):                                   # fade where there is more beyond
            if (self.menu_scroll > 0) if at_top else (self.menu_scroll < self._menu_max):
                g = QLinearGradient(0, view.top() if at_top else view.bottom(), 0,
                                    view.top() + style.SCROLL_FADE if at_top else view.bottom() - style.SCROLL_FADE)
                clear = QColor(solid)
                clear.setAlpha(0)
                g.setColorAt(0, solid)
                g.setColorAt(1, clear)
                p.fillRect(QRectF(view.left(), view.top() if at_top else view.bottom() - style.SCROLL_FADE, view.width(),
                                  style.SCROLL_FADE), g)
        p.restore()

    def wheel(self, x, y, dy):
        """The mouse wheel: scrolls an open menu that is under the pointer. True if it did."""
        if self.menu and self._menu_box is not None and self._menu_box.contains(x, y) and self._menu_max > 0:
            self.menu_scroll = max(0.0, min(self._menu_max, self.menu_scroll + dy))
            return True
        return False


def controls_height():
    from .theme import FIELD_H
    return FIELD_H
