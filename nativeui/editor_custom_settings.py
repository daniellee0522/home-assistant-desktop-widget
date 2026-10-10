"""A widget-kit widget's settings and permissions in the widget editor, made of the program's grouped rows
(nativeui/formrows.py): every field its author declared becomes the row an iOS settings page would have (a switch, a choice
opened as a menu, a field at the right of its label), the lists become cards with their entries and an add row, and what it
asks to be allowed is a card of switches."""
import os
import threading
import traceback

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from . import controls, style
from .formrows import AddRow, ChoiceRow, EntryRow, FieldRow, Group, HeaderRow, NoteRow, ToggleRow
from .ui import Button

GAP = 14                           # between two cards
ICONS = [("mdi:link", "連結"), ("mdi:web", "網站"), ("mdi:camera", "相機"), ("mdi:email", "郵件"),
         ("mdi:calendar", "行事曆"), ("mdi:folder", "資料夾"), ("mdi:music", "音樂"), ("mdi:cog", "設定"),
         ("mdi:home", "家"), ("mdi:play", "播放")]
LISTS = ("list", "feeds", "launchers", "images")


class CustomSettingsMixin:
    def editor_custom(self, body, y, widget):
        """Under the preview: the copy's own settings, and what it asks to be allowed. Returns the y below them."""
        from .editor import RIGHT_W, RIGHT_X
        info = self.custom_now
        if not info or not info.get("ok"):
            msg = style.label("hint", "這個 Widget 的套件已不見了，或程式無法載入；可以刪除它，或重新匯入。",
                              x=RIGHT_X, y=y + 5, w=RIGHT_W, wrap=True, lh=1.4)
            body.add(msg)
            return y + 5 + msg.h
        wid = widget["id"]
        if info["fields"]:
            body.add(style.label("group", "設定", x=RIGHT_X, y=y + 5, spacing=0.36))
            y += 5 + 14.4 + 8
            y = self.custom_groups(body, y, wid, info)
        if info["permissions"]:
            y = self.custom_permissions(body, y + GAP, wid, info["permissions"])
        return y + 4

    def custom_sizes(self, body, tx, ty, widget):
        """The sizes the widget says it can be, as the chips tiles have (or its one size in words); returns the x after them."""
        from .editor import Chip
        info = self.custom_now or {}
        sizes = info.get("sizes") or [widget["size"]]
        if len(sizes) < 2:
            note = style.label("field", "%s Widget · %s" % (self.custom_name(widget), widget["size"]), x=tx, y=ty + 6)
            body.add(note)
            return tx + note.w + 14
        for size in sizes:
            c = Chip(size, widget["size"] == size, lambda e, s=size: self.set_size(s))
            c.x, c.y = tx, ty
            body.add(c)
            tx += c.w + 6
        return tx + 6

    def set_custom(self, wid, key, value):
        """One setting of this copy; the screen is built again with it."""
        try:
            self.facade.api.set_custom_value(wid, key, value)
        except Exception:
            traceback.print_exc()
        self.build(keep=True)

    # -- the groups -------------------------------------------------------------------------------------------------------------
    def custom_groups(self, body, y, wid, info):
        """The fields in the order they were declared: those that are one row each share a card, as in a settings page; a
        list has a card of its own. Returns the y under the last."""
        from .editor import RIGHT_W, RIGHT_X
        card = None
        for f in info["fields"]:
            value = info["config"][f["key"]]
            if f["type"] in LISTS:
                card, y = self.close_group(body, card, y)
                group = self.custom_list_group(wid, f, value)
                group.x, group.y = RIGHT_X, y
                body.add(group)
                y += group.h
                if f["help"]:
                    y = self.group_note(body, y + 6, f["help"])
                y += GAP
                continue
            if card is None:
                card = Group(RIGHT_W)
            card.add_row(self.custom_row(wid, f, value))
            if f["help"]:
                card.add_row(NoteRow(RIGHT_W, f["help"]))
        card, y = self.close_group(body, card, y)
        return y - GAP

    def close_group(self, body, card, y):
        from .editor import RIGHT_X
        if card is None:
            return None, y
        card.finish()
        card.x, card.y = RIGHT_X, y
        body.add(card)
        return None, y + card.h + GAP

    def group_note(self, body, y, text):
        """Small print under a card (what the list is for); returns the y under it."""
        from .editor import RIGHT_W, RIGHT_X
        note = style.label("hint", text, x=RIGHT_X + 16, y=y, w=RIGHT_W - 32, wrap=True, lh=1.4)
        body.add(note)
        return y + note.h

    def custom_row(self, wid, f, value):
        """The one row of a setting that is a switch, a choice, a number or a line of text."""
        from .editor import RIGHT_W
        key, kind, label = f["key"], f["type"], f["label"]
        if kind == "bool":
            return ToggleRow(RIGHT_W, label, bool(value), lambda on, k=key: self.set_custom(wid, k, on))
        if kind == "choice":
            return ChoiceRow(RIGHT_W, label, [(o["value"], o["text"]) for o in f["options"]], value,
                             lambda v, k=key: self.set_custom(wid, k, v), "%s:%s" % (wid, key))
        shown = "" if value is None else str(value)

        def done(text, k=key):
            if text == shown:
                return                                   # (leaving the field again must not save again)
            if kind == "number":
                try:
                    float(text)
                except ValueError:
                    self.build(keep=True)                # not a number: what it was is shown again
                    return
            self.set_custom(wid, k, text)
        return FieldRow(RIGHT_W, label, shown, done, password=(kind == "secret"),
                        align=Qt.AlignRight if kind == "number" else Qt.AlignLeft)

    # -- lists --------------------------------------------------------------------------------------------------------------------
    def custom_list_group(self, wid, f, value):
        """A list of strings, feeds, launcher buttons or pictures: a header, an entry for each with the remove badge, and (but
        for pictures, whose button is in the header) a row to add one."""
        from .editor import RIGHT_W
        key, kind = f["key"], f["type"]
        entries = list(value or [])
        room = int(f["max"] or 10) if kind == "images" else 0
        group = Group(RIGHT_W)
        count = "%d/%d" % (len(entries), room) if room else (str(len(entries)) if entries else "")
        button = None
        if kind == "images":
            button = Button("新增圖片", size=12, weight=QFont.DemiBold, h=28, pad=12, fill="accent_blue",
                            hover_fill="accent_blue", color="white",
                            on_click=lambda e: self.add_images(wid, key, entries, room))
            if len(entries) >= room:
                button.alpha, button.interactive = 0.4, False
        group.add_row(HeaderRow(RIGHT_W, f["label"], count, button))
        for i, entry in enumerate(entries):
            line1, line2, icon = self.entry_lines(kind, entry)
            group.add_row(EntryRow(RIGHT_W, line1, line2, icon,
                                   lambda i=i: self.set_custom(wid, key, entries[:i] + entries[i + 1:])))
        if kind != "images":
            group.add_row(self.custom_add_row(wid, f, entries))
        return group.finish()

    @staticmethod
    def entry_lines(kind, entry):
        if kind == "list":
            return str(entry), "", None
        if kind == "images":
            return os.path.basename(entry) or entry, os.path.dirname(entry), "mdi:image-outline"
        if kind == "feeds":
            return entry.get("name") or entry.get("url", ""), entry.get("url", "") if entry.get("name") else "", "mdi:rss"
        return entry.get("label") or entry.get("url", ""), entry.get("url", ""), entry.get("icon") or "mdi:link"

    def custom_add_row(self, wid, f, entries):
        from .editor import RIGHT_W
        key, kind = f["key"], f["type"]
        holders = {"list": ["值"], "feeds": ["名稱", "網址"], "launchers": ["名稱", "網址"]}[kind]
        draft = {h: self.draft.get((wid, key, h), "") for h in holders}
        lead = None
        icon = self.draft.get((wid, key, "icon"), "mdi:link")
        if kind == "launchers":
            lead = Button(icon=icon, icon_size=18, w=32, h=32)
            lead.key, lead.options, lead.current = "icon:%s:%s" % (wid, key), list(ICONS), icon
            lead.on_click = lambda e, b=lead: controls.open_menu(b, b.options, b.current, lambda v: self.pick_icon(wid, key, v))

        def add(texts):
            for h in holders:
                self.draft.pop((wid, key, h), None)
            if kind == "list":
                new = texts[0]
            elif kind == "feeds":
                new = {"name": texts[0], "url": texts[1]}
            else:
                new = {"label": texts[0], "url": texts[1], "icon": icon}
            self.set_custom(wid, key, entries + [new])
        return AddRow(RIGHT_W, holders, add, drafts=draft, on_draft=lambda h, t: self.draft.__setitem__((wid, key, h), t),
                      lead=lead)

    def pick_icon(self, wid, key, icon):
        self.draft[(wid, key, "icon")] = icon
        self.build(keep=True)

    def add_images(self, wid, key, files, room):
        """The file dialog for pictures (off the GUI thread: it waits for the person), then what was chosen is added."""
        api = self.facade.api

        def go():
            try:
                chosen = api.choose_images(room - len(files))
            except Exception:
                traceback.print_exc()
                chosen = []
            if chosen:
                self.facade.run_on_ui_thread(lambda: self.set_custom(wid, key, files + [c for c in chosen if c not in files]))
        threading.Thread(target=go, daemon=True).start()

    # -- what it asks to be allowed --------------------------------------------------------------------------------------------------
    def custom_permissions(self, body, y, wid, perms):
        """A card of switches, one for each permission. Before the user has answered, the switches are only a choice (the safe
        ones start on, the ones that reach outside the widget start off) and a button applies it; after, a switch is the answer."""
        from .editor import RIGHT_W, RIGHT_X
        pending = any(p["state"] == "pending" for p in perms)
        choice = self.perm_choice.setdefault(wid, {})
        for p in perms:
            choice.setdefault(p["perm"], p["state"] == "granted" if p["state"] != "pending" else not p["risky"])
        body.add(style.label("group", "權限", x=RIGHT_X, y=y + 5, spacing=0.36))
        y += 5 + 14.4 + 8
        if pending:
            note = style.label("hint", "這個 Widget 想使用下列功能。選好要允許的項目，按「允許所選」才會生效。",
                               x=RIGHT_X, y=y, w=RIGHT_W, wrap=True, lh=1.4)
            body.add(note)
            y += note.h + 8
        group = Group(RIGHT_W)
        for p in perms:
            group.add_row(ToggleRow(RIGHT_W, p["text"], choice[p["perm"]],
                                    lambda on, perm=p["perm"]: self.choose_permission(wid, perm, on, pending),
                                    icon=p["icon"], sub="可能影響這個 Widget 以外的東西" if p["risky"] else "", warn=p["risky"]))
        group.finish()
        group.x, group.y = RIGHT_X, y
        body.add(group)
        y += group.h
        if pending:
            ok = Button("允許所選", size=12, weight=QFont.DemiBold, h=28, pad=12, fill="accent_blue",
                        hover_fill="accent_blue", color="white", on_click=lambda e: self.apply_permissions(wid))
            ok.x, ok.y = RIGHT_X, y + 10
            body.add(ok)
            y += 10 + 28
        return y

    def choose_permission(self, wid, perm, on, pending):
        self.perm_choice.setdefault(wid, {})[perm] = on
        if not pending:
            self.apply_permissions(wid)

    def apply_permissions(self, wid):
        allowed = [p for p, on in self.perm_choice.get(wid, {}).items() if on]
        try:
            self.facade.api.set_custom_permissions(wid, allowed)
        except Exception:
            traceback.print_exc()
        self.perm_choice.pop(wid, None)
        self.close_custom_runtimes()                     # the preview asks its sources again with what is allowed now
        self.build(keep=True)
