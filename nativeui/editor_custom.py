"""The widget editor's part for widgets written with the widget kit (widgetkit/): the shelf of imported widgets beside
the clock and the calendar (a "+" that imports a .hawidget, each imported widget dragged onto the desktop, a cross to take
one out), the widget's own settings under its preview (every field its author declared, made into the program's own
controls), and what it asks to be allowed.

Each copy on the desktop has settings of its own (`Api.set_custom_value`); what is allowed is answered once per package
(`Api.set_custom_permissions`)."""
import threading
import traceback

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPen

from . import controls, customview, render, style, ui
from .editor_custom_settings import CustomSettingsMixin
from .ui import Button, View



def thumbnail_runtime(definition):
    """A runtime that only draws (nothing is allowed it, nothing is fetched): what a thumbnail is drawn from."""
    from widgetkit.permissions import Grants
    from widgetkit.runtime import WidgetRuntime
    return WidgetRuntime(definition, None, grants=Grants())


# ---------------------------------------------------------------------------------------------- the shelf
class Shelf(View):
    """Items in rows of the shelf's width, their bottoms aligned (as the palette above it is laid out)."""

    def __init__(self, items, w, gap=16, row_gap=14):
        super().__init__(0, 0, w, 0)
        line, line_w, lines = [], 0, []
        for it in items:
            if line and line_w + it.w > w:
                lines.append(line)
                line, line_w = [], 0
            line.append(it)
            line_w += it.w + gap
        if line:
            lines.append(line)
        y = 0
        for ln in lines:
            lh = max(it.h for it in ln)
            x = 0
            for it in ln:
                it.x, it.y = x, y + lh - it.h
                self.add(it)
                x += it.w + gap
            y += lh + row_gap
        self.h = max(0, y - row_gap)


def _thumb_size(size_key):
    """The width and height a widget of `size_key` has in the palette (the sizes' own scale), and the card under it."""
    from .editor_views import PALETTE_SCALE
    cw, ch = render.widget_size(size_key)
    bw = round(cw * PALETTE_SCALE)
    return bw, round(bw * ch / cw), cw


def _caption(p, scene, text, w, y, hovered):
    size, weight, color = style.TEXT["field"]
    f = ui.font(size, weight)
    style.center_text(p, ui.ellipsize(render.tr(text), f, w), f, ui.resolve(scene, "ink1" if hovered else color),
                      QRectF(0, y, w, 14), align="line")


class ImportItem(View):
    """The "+" of the shelf: pressed, it asks for a .hawidget to import."""
    cursor = Qt.PointingHandCursor

    def __init__(self, on_import):
        bw, self.bh, _ = _thumb_size("2x2")
        super().__init__(0, 0, bw, self.bh + 6 + 14)
        self.interactive = True
        self.on_press = lambda e: True
        self.on_click = lambda e: (on_import(), True)[1]
        self.on_enter = self.on_leave = lambda e: self.changed()

    def paint(self, p):
        up = -2 if self.hovered else 0
        rect = QRectF(0.75, up + 0.75, self.w - 1.5, self.bh - 1.5)
        p.setPen(Qt.NoPen)
        p.setBrush(ui.resolve(self.scene, "btn_fill_strong" if self.hovered else "btn_fill"))
        p.drawRoundedRect(rect, 14, 14)
        pen = QPen(ui.resolve(self.scene, "ink1" if self.hovered else "ink2"), 1.5, Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, 14, 14)
        style.center_icon(p, "mdi:plus", ui.resolve(self.scene, "ink1" if self.hovered else "ink2").name(),
                          QRectF(0, up, self.w, self.bh), 28)
        _caption(p, self.scene, "匯入", self.w, self.bh + 6, self.hovered)


class ApprovePane(View):
    """What an imported widget is and what it asks for, and the two answers, in a floating pane over the shelf (not a
    dialog: it would take the editor's focus). A widget is a program, so its code is not run until this is answered."""
    W, PAD = 300, 16
    WARNING = ("Widget 是一段程式：信任後它會在本程式內執行，能讀取你電腦上的檔案與 Home Assistant 權杖。"
               "上面的權限只限制工具組提供的動作，並不是沙箱。只信任你認識的來源。")
    reanchors = True                               # (kept over its tile when the screen is built again)

    def __init__(self, pkg, on_use, on_refuse):
        super().__init__(0, 0, self.W, 0)
        self.interactive = True
        self.on_press = lambda e: True
        self.on_click = lambda e: True
        self.key = "package:" + pkg["id"]
        self.anchor = self.on_closed = None
        pad, w = self.PAD, self.W - 2 * self.PAD
        y = pad
        title = style.label("header", pkg["name"], x=pad, y=y, w=w, overflow="ellipsis")
        self.add(title)
        y += title.h + 4
        colon = ": " if render._language == "en" else "："
        who = style.label("header_sub", render.tr("作者") + colon + pkg["author"] if pkg.get("author") else "作者不明",
                          x=pad, y=y, w=w, overflow="ellipsis")
        self.add(who)
        y += who.h + 14
        group = style.label("group", "它要求的權限", x=pad, y=y, spacing=0.36)
        self.add(group)
        y += group.h + 6
        asked = pkg.get("permissions")
        lines = (["執行後才會知道它要求哪些權限。"] if asked is None
                 else ["•  " + t for t in asked] or ["它沒有要求任何權限。"])
        for text in lines:
            row = style.label("row", text, x=pad, y=y, w=w, wrap=True, lh=1.35)
            self.add(row)
            y += row.h + 4
        y += 8
        warn = style.label("hint", self.WARNING, x=pad, y=y, w=w, wrap=True, lh=1.4, color="accent_red")
        self.add(warn)
        y += warn.h + 14
        half = (w - 8) / 2
        self.add(Button("不使用並移除", x=pad, y=y, w=half, h=32, size=12, weight=QFont.DemiBold,
                        on_click=lambda e: self._answer(on_refuse, pkg)))
        self.add(Button("信任並使用", x=pad + half + 8, y=y, w=half, h=32, size=12, weight=QFont.DemiBold,
                        fill="accent_blue", hover_fill="accent_blue", color="white",
                        on_click=lambda e: self._answer(on_use, pkg)))
        self.h = y + 32 + pad

    def _answer(self, then, pkg):
        self.scene.close_popup()
        then(pkg)
        return True

    def paint(self, p):
        style.popup_pane(p, self.scene, self.w, self.h)


class PackageItem(View):
    """An imported widget in the shelf, drawn as it looks (nothing fetched), its name under it. Pressed, a copy follows the
    pointer onto the desktop; the cross of a hovered one asks to take it out. One not yet approved is a closed tile: pressed,
    it opens the pane that asks whether to trust it (its code has not been run)."""
    cursor = Qt.OpenHandCursor

    def __init__(self, editor, pkg, on_drag, on_remove, on_review=None):
        self.editor, self.pkg, self.start_drag, self.ask_remove = editor, pkg, on_drag, on_remove
        self.review = on_review
        bw, self.bh, self.cw = _thumb_size(pkg["size"])
        super().__init__(0, 0, bw, self.bh + 6 + 14)
        self.interactive = True
        self.key = "package:" + pkg["id"]            # (a menu open over it stays when the screen is built again)
        self.options, self.current = [("remove", "移除（含桌面上的複本）"), ("keep", "取消")], None
        self.on_press = self._press
        self.on_enter = self.on_leave = lambda e: self.changed()
        self.pic = None

    def badge(self):
        return QRectF(self.w - 20, -8, 24, 24)

    def _press(self, e):
        if self.hovered and self.badge().adjusted(-4, -4, 4, 4).contains(e.x, e.y):
            controls.open_menu(self, self.options, None, lambda v: self.ask_remove(self.pkg) if v == "remove" else None)
        elif not self.pkg.get("approved", True):
            if self.review:
                self.review(self.pkg, self)
        else:
            self.start_drag(self.pkg)
        return True

    def paint_waiting(self, p, up):
        sc = self.scene
        rect = QRectF(0.75, up + 0.75, self.w - 1.5, self.bh - 1.5)
        p.setPen(Qt.NoPen)
        p.setBrush(ui.resolve(sc, "btn_fill_strong" if self.hovered else "btn_fill"))
        p.drawRoundedRect(rect, 14, 14)
        color = ui.resolve(sc, "ink1" if self.hovered else "ink2")
        style.center_icon(p, "mdi:lock-outline", color.name(), QRectF(0, up, self.w, self.bh - 22), 28)
        size, weight, _ = style.TEXT["tiny"]
        style.center_text(p, render.tr("待審核"), ui.font(size, weight), color,
                          QRectF(0, up + self.bh - 28, self.w, 16), align="line")
        _caption(p, sc, self.pkg["name"], self.w, self.bh + 6, self.hovered)

    def paint(self, p):
        up = -2 if self.hovered else 0
        sc = self.scene
        if not self.pkg.get("approved", True):
            return self.paint_waiting(p, up)
        key = (sc.theme, sc.style, render._language, p.transform().m11())
        if self.pic is None or self.pic[0] != key:
            rt = self.editor.thumbnail(self.pkg["id"])
            k = self.bw_scale()

            def draw(q):
                q.scale(k, k)
                customview.paint(q, rt, self.pkg["size"], sc.theme, sc.style)
            from .editor_views import device_image
            self.pic = (key, device_image(p, self.w, self.bh, draw))
        from .editor_views import put_image
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 34 if self.hovered else 20))
        p.drawPath(render.squircle(0, up + 2, self.w, self.bh, 14))
        p.setBrush(ui.resolve(sc, "btn_fill_strong"))
        p.drawPath(render.squircle(0, up, self.w, self.bh, 14))
        put_image(p, self.pic[1], 0, up)
        _caption(p, sc, self.pkg["name"], self.w, self.bh + 6, self.hovered)
        if self.hovered:
            style.remove_badge(p, self.badge())

    def bw_scale(self):
        return self.w / self.cw


# ---------------------------------------------------------------------------------------------- the editor's part
class CustomEditorMixin(CustomSettingsMixin):
    def custom_init(self):
        self.customs = []                  # the packages installed (Api.custom_widgets)
        self.thumbs = {}                   # package id -> a runtime that only draws (the shelf's pictures)
        self.preview_rts = {}              # widget id -> {"pkg", "rt", "cfg"}: what the preview of a copy is drawn from
        self.custom_now = None             # Api.custom_info of the copy being edited
        self.custom_rev = 0                # counted when what a preview shows has changed
        self.perm_choice = {}              # widget id -> {permission: allowed?} while the user is deciding
        self.draft = {}                    # what is typed or chosen in an "add" row, by widget id and field

    # -- what is known of the packages ---------------------------------------------------------------------------------
    def reload_customs(self):
        try:
            self.customs = self.facade.api.custom_widgets()
        except Exception:
            traceback.print_exc()
            self.customs = []
        for rt in self.thumbs.values():
            rt.close()
        self.thumbs.clear()

    def thumbnail(self, pkg_id):
        rt = self.thumbs.get(pkg_id)
        if rt is None:
            wd = self.facade.api.custom_definition(pkg_id)
            rt = self.thumbs[pkg_id] = thumbnail_runtime(wd) if wd is not None else None
        return rt

    def custom_name(self, widget):
        entry = widget.get("custom") or {}
        return next((c["name"] for c in self.customs if c["id"] == entry.get("widget")), "Widget")

    def load_custom_now(self, widget):
        """Read what the editor shows of the copy: its fields, values, sizes and permissions."""
        self.custom_now = None
        if widget and widget.get("kind") == "custom" and not widget.get("panel"):
            try:
                self.custom_now = self.facade.api.custom_info(widget["id"])
            except Exception:
                traceback.print_exc()

    # -- the preview -------------------------------------------------------------------------------------------------------
    def custom_preview(self, widget):
        """The runtime the copy's preview is drawn from (its own, with the copy's settings, never writing its memory)."""
        info = self.custom_now
        if not info or not info.get("ok"):
            return None
        wid, cfg = widget["id"], repr(info["config"])
        cur = self.preview_rts.get(wid)
        if cur is None or cur["pkg"] != info["package"]:
            if cur and cur["rt"] is not None:
                cur["rt"].close()
            rt = self.facade.api.custom_preview_runtime(wid, invalidate=self.custom_changed)
            if rt is not None:
                rt.sv.gui = self.facade.run_on_ui_thread
                rt.refresh_async()
            cur = self.preview_rts[wid] = {"pkg": info["package"], "rt": rt, "cfg": cfg}
        elif cur["cfg"] != cfg and cur["rt"] is not None:
            cur["rt"].set_config(info["config"])
            cur["cfg"] = cfg
            cur["rt"].refresh_async()
        return cur["rt"]

    def custom_changed(self):
        self.custom_rev += 1
        if self.page == "editor" and getattr(self, "preview", None) is not None:
            self.preview.invalidate()

    def close_custom_runtimes(self):
        for cur in self.preview_rts.values():
            if cur["rt"] is not None:
                cur["rt"].close()
        self.preview_rts.clear()

    # -- the shelf: import, drag, take out ---------------------------------------------------------------------------------
    def custom_shelf(self, width):
        items = [ImportItem(self.import_custom)]
        for pkg in self.customs:
            items.append(PackageItem(self, pkg, self.drag_new_custom, self.remove_custom_package, self.review_custom))
        return Shelf(items, width)

    def import_custom(self):
        api = self.facade.api

        def go():
            try:
                result = api.choose_and_import_custom_widget()
            except Exception as e:
                traceback.print_exc()
                result = {"ok": False, "error": str(e)}
            if result is not None:
                self.facade.run_on_ui_thread(lambda: self.custom_imported(result))
        threading.Thread(target=go, daemon=True).start()

    def custom_imported(self, result):
        if not result.get("ok"):
            self.toast(render.tr("無法匯入") + "：" + str(result.get("error", "")))
            return
        self.reload_customs()
        self.build(keep=True)
        if result.get("approved", True):
            self.toast(render.tr("已匯入") + "：" + result["name"])
        else:
            self.toast(render.tr("請確認是否信任") + "：" + result["name"])
            QTimer.singleShot(60, lambda: self.review_waiting(result["id"]))

    # -- an import waits to be trusted ----------------------------------------------------------------------------------------
    def review_waiting(self, pkg_id):
        """Open the pane that asks about a package, over its tile."""
        pkg = next((c for c in self.customs if c["id"] == pkg_id), None)
        item = self.find_package_item(pkg_id)
        if pkg is not None and item is not None:
            self.review_custom(pkg, item)

    def find_package_item(self, pkg_id):
        found = []

        def walk(v):
            if isinstance(v, PackageItem) and v.pkg["id"] == pkg_id:
                found.append(v)
            for c in v.children:
                walk(c)
        walk(self.root)
        return found[0] if found else None

    def review_custom(self, pkg, item):
        controls.open_pane(item, ApprovePane(pkg, self.trust_custom, self.refuse_custom))

    def trust_custom(self, pkg):
        def go():
            try:
                result = self.facade.api.approve_custom_widget(pkg["id"])
            except Exception as e:
                traceback.print_exc()
                result = {"ok": False, "error": str(e)}
            self.facade.run_on_ui_thread(lambda: self.custom_trusted(result))
        threading.Thread(target=go, daemon=True).start()

    def custom_trusted(self, result):
        self.reload_customs()
        self.toast((render.tr("已加入") + "：" + result["name"]) if result.get("ok")
                   else render.tr("無法匯入") + "：" + str(result.get("error", "")))
        self.build(keep=True)

    def refuse_custom(self, pkg):
        def go():
            try:
                self.facade.api.reject_custom_widget(pkg["id"])
            except Exception:
                traceback.print_exc()
            self.facade.run_on_ui_thread(self.custom_removed)
        threading.Thread(target=go, daemon=True).start()

    def drag_new_custom(self, pkg):
        self.drag_new_widget(pkg["size"], "custom", pkg["id"])

    def remove_custom_package(self, pkg):
        def go():
            try:
                self.facade.api.uninstall_custom_widget(pkg["id"])
            except Exception:
                traceback.print_exc()
            self.facade.run_on_ui_thread(self.custom_removed)
        threading.Thread(target=go, daemon=True).start()

    def custom_removed(self):
        self.reload_customs()
        self.close_custom_runtimes()
        self.widget_id = ""
        self.build(keep=True)
        QTimer.singleShot(200, self.refresh_layout)
