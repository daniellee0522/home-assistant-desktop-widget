"""Settings made of grouped rows, as iOS draws them: a rounded card (a Group) holding rows separated by hairlines. A row is
a label with its control at the right (a switch, the choice made with a menu, a field), a list entry with the remove badge, or
the row that adds one. The widget editor makes a widget-kit widget's settings and permissions from these."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont

from . import controls, render, style, ui
from .ui import Button, IconView, TextField, View

ROW_H = 48
INSET = 16                         # the card's side padding, and where a hairline starts
FIELD_H = 30


class Group(View):
    """A card of rows, one under the other. `add(row)` places it; `finish()` once the last is in (no hairline under it)."""

    def __init__(self, w):
        super().__init__(0, 0, w, 0)
        self.rows = []

    def add_row(self, row):
        row.x, row.y = 0, self.h
        self.rows.append(row)
        self.add(row)
        self.h += row.h
        return row

    def finish(self):
        if self.rows:
            self.rows[-1].last = True
        return self

    def paint(self, p):
        p.setPen(Qt.NoPen)
        p.setBrush(ui.resolve(self.scene, "btn_fill"))
        p.drawRoundedRect(QRectF(0, 0, self.w, self.h), 16, 16)


class Row(View):
    """What every row has: its width and height, and the hairline under it (unless it is the last of its group)."""

    def __init__(self, w, h=ROW_H):
        super().__init__(0, 0, w, h)
        self.last = False

    def paint(self, p):
        if not self.last:
            p.setPen(Qt.NoPen)
            p.setBrush(ui.resolve(self.scene, "input_border"))
            p.drawRect(QRectF(INSET, self.h - 0.5, self.w - INSET, 0.5))


def _centred(label, h, x=INSET, w=0):
    label.x, label.y = x, (h - label.h) / 2
    return label


class ToggleRow(Row):
    """A label (its second line under it, in red when it warns), an optional icon in a disc, and a switch."""

    def __init__(self, w, label, on, on_change, icon=None, sub="", warn=False):
        super().__init__(w, 56 if sub else ROW_H)
        self.text = label
        x = INSET
        if icon:
            disc = View(INSET, (self.h - 32) / 2, 32, 32)
            disc.paint = lambda p, name=icon, red=warn: self._disc(p, name, red)
            self.add(disc)
            x = INSET + 32 + 12
        room = w - x - INSET - controls.Switch.W - 12
        title = style.label("row", label, x=x, w=room, overflow="ellipsis")
        if sub:
            note = style.label("tiny", sub, x=x, w=room, overflow="ellipsis", color="accent_red" if warn else "ink2")
            gap = 2
            top = (self.h - title.h - gap - note.h) / 2
            title.y, note.y = top, top + title.h + gap
            self.add(note)
        else:
            title.y = (self.h - title.h) / 2
        self.add(title)
        self.switch = controls.Switch(on, on_change)
        self.switch.x, self.switch.y = w - INSET - self.switch.w, (self.h - self.switch.h) / 2
        self.add(self.switch)
        self.interactive = True
        self.on_press = lambda e: True
        self.on_click = lambda e: self.switch._click(e) or True

    def _disc(self, p, name, red):
        color = ui.resolve(self.scene, "accent_red" if red else "accent_blue")
        wash = QColor(color)
        wash.setAlphaF(0.18)
        p.setPen(Qt.NoPen)
        p.setBrush(wash)
        p.drawEllipse(QRectF(0, 0, 32, 32))
        style.center_icon(p, name, color.name(), QRectF(0, 0, 32, 32), 18)


class ChoiceRow(Row):
    """A label and what is chosen now with a pair of chevrons, as iOS shows a pop-up: pressed, the choices open in a menu
    under it. `key`, `options` and `current` are what a menu left open over a screen built again is re-anchored by."""
    cursor = Qt.PointingHandCursor

    def __init__(self, w, label, options, current, on_pick, key):
        super().__init__(w)
        self.text = label
        shown = next((text for value, text in options if value == current), str(current))
        self.options, self.current, self.on_pick, self.key, self.open = options, current, on_pick, key, False
        size, weight, _ = style.TEXT["row_value"]
        value_w = min(w * 0.55, ui.text_width(render.tr(shown), ui.font(size, weight)) + 16 + 22)
        room = w - 2 * INSET - value_w - 12
        self.add(_centred(style.label("row", label, w=room, overflow="ellipsis"), self.h))
        self.pill = View(w - INSET - value_w, 0, value_w, self.h)
        self.pill.key, self.pill.options, self.pill.current, self.pill.open = key, options, current, False
        self.pill.paint = lambda p, text=shown, vw=value_w: self._pill(p, text, vw)
        self.add(self.pill)
        self.interactive = True
        self.on_press = lambda e: True
        self.on_click = lambda e: (controls.open_menu(self.pill, self.options, self.current, self.on_pick), True)[1]

    def _pill(self, p, text, w):
        size, weight, color = style.TEXT["row_value"]
        f = ui.font(size, weight)
        shown = ui.ellipsize(render.tr(text), f, w - 22)
        style.center_text(p, shown, f, ui.resolve(self.scene, color), QRectF(0, 0, w - 20, self.h), align="line")
        render.draw_icon(p, "mdi:unfold-more-horizontal", ui.resolve(self.scene, "ink2").name(),
                         QRectF(w - 20, (self.h - 18) / 2, 18, 18))


class FieldRow(Row):
    """A label and a line of text (or a number, or a secret) to edit, at the right of it."""

    def __init__(self, w, label, text, on_done, password=False, align=Qt.AlignRight, max_length=400):
        super().__init__(w)
        size, weight, _ = style.TEXT["row"]
        label_w = ui.text_width(render.tr(label), ui.font(size, weight))
        field_w = max(110, min(w * 0.6, w - 2 * INSET - label_w - 12))
        self.add(_centred(style.label("row", label, w=w - 2 * INSET - field_w - 12, overflow="ellipsis"), self.h))
        self.field = TextField(w - INSET - field_w, (self.h - FIELD_H) / 2, field_w, FIELD_H, text, "", 13, on_done,
                               max_length, radius=FIELD_H / 2, password=password, align=align)
        self.add(self.field)


class NoteRow(Row):
    """A line of small print under a row: what a setting means."""

    def __init__(self, w, text):
        super().__init__(w, 0)
        note = style.label("hint", text, x=INSET, y=8, w=w - 2 * INSET, wrap=True, lh=1.4)
        self.add(note)
        self.h = note.h + 14
        self.hairline = False

    def paint(self, p):
        pass


class HeaderRow(Row):
    """The first row of a list: its label, how many there are, and (if given) a button that adds."""

    def __init__(self, w, label, count="", button=None):
        super().__init__(w)
        right = w - INSET
        if button is not None:
            button.x, button.y = right - button.w, (self.h - button.h) / 2
            self.add(button)
            right = button.x - 12
        if count:
            note = style.label("row_value", count)
            note.x, note.y = right - note.w, (self.h - note.h) / 2
            self.add(note)
            right = note.x - 8
        self.add(_centred(style.label("row", label, w=max(40, right - INSET), overflow="ellipsis"), self.h))


class EntryRow(Row):
    """One entry of a list: an optional icon, one line or two, and the remove badge."""

    def __init__(self, w, line1, line2="", icon=None, on_remove=None):
        super().__init__(w)
        x = INSET
        if icon:
            self.add(IconView(icon, "ink2", INSET, (self.h - 22) / 2, 22))
            x = INSET + 22 + 12
        room = w - x - INSET - 24 - 12
        title = style.label("item", line1, x=x, w=room, overflow="ellipsis")
        if line2:
            sub = style.label("tiny", line2, x=x, w=room, overflow="ellipsis")
            top = (self.h - title.h - 2 - sub.h) / 2
            title.y, sub.y = top, top + title.h + 2
            self.add(sub)
        else:
            title.y = (self.h - title.h) / 2
        self.add(title)
        self.badge = View(w - INSET - 24, (self.h - 24) / 2, 24, 24)
        self.badge.interactive = on_remove is not None
        self.badge.cursor = Qt.PointingHandCursor
        self.badge.on_press = lambda e: True
        self.badge.on_click = lambda e: (on_remove(), True)[1]
        self.badge.paint = lambda p: style.remove_badge(p, QRectF(0, 0, 24, 24), shadow=False)
        self.add(self.badge)


class AddRow(Row):
    """The row that makes one more entry: fields (each with its placeholder) and a blue button. Enter in a field adds too."""

    def __init__(self, w, placeholders, on_add, button="新增", drafts=None, on_draft=None, lead=None):
        super().__init__(w)
        add = Button(button, size=12, weight=QFont.DemiBold, h=28, pad=12, fill="accent_blue", hover_fill="accent_blue",
                     color="white")
        add.x, add.y = w - INSET - add.w, (self.h - 28) / 2
        left = INSET
        if lead is not None:                         # a small control before the fields (a launcher's icon)
            lead.x, lead.y = left, (self.h - lead.h) / 2
            self.add(lead)
            left += lead.w + 8
        span = add.x - 8 - left
        widths = [span] if len(placeholders) == 1 else [round(span * 0.36), span - round(span * 0.36) - 8]
        self.fields, x = [], left
        for i, (holder, fw) in enumerate(zip(placeholders, widths)):
            fld = TextField(x, (self.h - FIELD_H) / 2, fw, FIELD_H, (drafts or {}).get(holder, ""), holder, 12.5, None, 400,
                            radius=FIELD_H / 2,
                            on_change=(lambda t, h=holder: on_draft(h, t)) if on_draft else None)
            self.add(fld)
            self.fields.append(fld)
            x += fw + 8
        done = []

        def commit(e=None):
            texts = [f.value().strip() for f in self.fields]
            if done or not all(texts):               # (a field says it is done again as the screen is built over)
                return True
            done.append(True)
            on_add(texts)
            return True
        add.on_click = commit
        for f in self.fields:
            f.on_done = lambda text: commit()
        self.add(add)
        self.button = add
