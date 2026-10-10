"""What the user is shown when they add a widget that asks for permissions: each one in plain words with its own
switch, and two buttons. A floating card (no modal dialog: CLAUDE.md), drawn with the kit and recorded in a HitMap, so
the program's windows or a test can press it the same way.

    card = ConsentCard(widget, grants)
    card.draw(painter, th, QRectF(0, 0, 520, 0))        # returns the card's height; draws from the rect's top-left
    card.click(x, y)                                      # "add" / "cancel" when decided, else None
"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor

from nativeui import style

from . import controls, permissions as perms
from .definition import text_of
from .theme import line_height, paragraph, text

PAD = 24
ROW = 64


class ConsentCard:
    def __init__(self, widget, grants, lang="en", author=""):
        self.widget, self.grants, self.lang, self.author = widget, grants, lang, author
        asking = grants.pending(widget) or list(widget.permissions)
        # Safe things start on; the ones that reach outside the program (running programs, the microphone, any
        # website) start off, so allowing them is a choice and never a habit.
        self.choice = {p: not perms.is_risky(p) for p in asking}
        self.hits = controls.HitMap()
        self.decision = None

    def needs_asking(self):
        return bool(self.grants.pending(self.widget))

    def draw(self, p, th, rect):
        self.hits.clear()
        x, w = rect.left() + PAD, rect.width() - 2 * PAD
        n = len(self.choice)
        h = PAD + 30 + 22 + n * ROW + 20 + 52 + 36 + PAD
        card = QRectF(rect.left(), rect.top(), rect.width(), h)
        style.shadow(p, card, 24, style.SHADOW)
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(44, 46, 52) if th.name == "dark" else QColor(255, 255, 255))
        p.drawRoundedRect(card, 24, 24)
        p.restore()
        y = rect.top() + PAD
        text(p, th, "title", text_of(self.widget.name, self.lang), x, y, w)
        y += line_height("title") + 2
        text(p, th, "secondary", "wants to:" if not self.lang.startswith("zh") else "想要:", x, y, w)
        y += line_height("secondary") + 14
        for perm, on in self.choice.items():
            self._row(p, th, perm, on, QRectF(x, y, w, ROW))
            y += ROW
        y += 8
        paragraph(p, th, "hint", "Only add widgets from people you trust: a widget is a program." if not self.lang.startswith("zh")
                  else "只加入你信任的人寫的 widget:它是一段程式。", QRectF(x, y, w, 40))
        y += 36
        half = (w - 12) / 2
        controls.button(p, th, QRectF(x, y, half, 48), "Don't allow" if not self.lang.startswith("zh") else "取消",
                        th.accent("blue"), "tinted", hits=self.hits, id="cancel")
        controls.button(p, th, QRectF(x + half + 12, y, half, 48), "Add widget" if not self.lang.startswith("zh") else "加入",
                        th.accent("blue"), "filled", hits=self.hits, id="add")
        return h

    def _row(self, p, th, perm, on, rect):
        risky = perms.is_risky(perm)
        controls.icon_badge(p, perms.icon_of(perm), th.accent("red" if risky else "blue"),
                            QRectF(rect.left(), rect.center().y() - 20, 40, 40))
        text(p, th, "body", perms.describe(perm, self.lang), rect.left() + 54, rect.center().y() - line_height("body") / 2
             - (9 if risky else 0), rect.width() - 54 - 70)
        if risky:
            text(p, th, "caption", "Can affect things outside this widget" if not self.lang.startswith("zh") else "可能影響這個 widget 以外的東西",
                 rect.left() + 54, rect.center().y() + 4, rect.width() - 54 - 70, color=th.accent("red"))
        sw = QRectF(rect.right() - 52, rect.center().y() - 16, 52, 32)
        controls.toggle(p, th, sw, on, th.accent("green"), hits=self.hits, id=("perm", perm))

    def click(self, x, y):
        hit = self.hits.at(x, y)
        if isinstance(hit, tuple) and hit[0] == "perm":
            self.choice[hit[1]] = not self.choice[hit[1]]
        elif hit == "add":
            yes = [p for p, on in self.choice.items() if on]
            before = self.grants.table.get(self.widget.id, {})
            self.grants.decide(self.widget,
                               allow=yes + [p for p in before.get("granted", []) if p not in self.choice],
                               deny=[p for p, on in self.choice.items() if not on]
                               + [p for p in before.get("denied", []) if p not in self.choice])
            self.decision = "add"
        elif hit == "cancel":
            self.decision = "cancel"
        return self.decision
