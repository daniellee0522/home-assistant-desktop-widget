"""Settings, the widget editor and the entity picker: the page's #settings window, drawn natively.

A nearly solid card (it is read, not glanced at) with three screens in one window. main.py makes it when
asked for and releases it when closed, as it did the page.
"""
import threading
import traceback

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainterPath

from . import render, ui
from .detail import Stack
from .editor import EditorMixin
from .overlay import OverlayScene, create_overlay
from .ui import Button, CheckRow, Label, Rect, ScrollView, Select, Slider, TextField, View

CARD_W, BODY_X, BODY_W = 340, 16, 308
BODY_MAX = 520
SOLID = {"light": (240, 245, 250), "dark": (26, 29, 34)}
DOMAIN_LABELS = {"light": "燈光", "switch": "開關/插座", "input_boolean": "虛擬開關", "climate": "空調", "fan": "風扇",
                 "cover": "窗簾/百葉", "media_player": "媒體播放器", "lock": "門鎖", "vacuum": "掃地機", "scene": "場景",
                 "script": "腳本", "automation": "自動化", "sensor": "感測器", "binary_sensor": "感測器 (開關型)"}


def dim_text(sec):
    return ("%d 秒" % sec) if sec < 60 else ("%s 分鐘" % (round(sec / 6) / 10)).replace(".0 ", " ")


class Hint(Label):
    def __init__(self, text, w, color="ink2", size=11.5):
        super().__init__(text, size, QFont.Normal, color, w=w, wrap=True, lh=1.4)


class SettingsScene(EditorMixin, OverlayScene):
    def __init__(self, facade, api):
        super().__init__(facade, api, "settings")
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)      # it has fields to type in
        self.prefs = api._prefs()
        self.cfg = api.bootstrap().get("config", {})
        self.connected = bool(api.bootstrap().get("connected"))
        self.states = {}
        self.page = "settings"
        self.return_page = "settings"
        self.widget_id = ""
        self.zoom_css = 1.0
        self.system_glass = False
        self.lensed = False
        self.sampling = "still"
        self.fields_text = {}
        self.test_result = None
        self.scroll_keep = {}
        self.configure()
        self.retheme()
        self.editor_init()
        self.build()
        threading.Thread(target=self._load_states, daemon=True).start()

    # -- preferences -----------------------------------------------------------------------------------------
    def configure(self):
        self.theme_raw = self.prefs.get("theme", "auto")
        self.style = self.prefs.get("glass_style", "classic")
        if self.style not in ("classic", "liquid", "windows"):
            self.style = "classic"
        self.language = self.prefs.get("language", "zh-TW")

    def apply_prefs(self, prefs):
        before = (self.theme_raw, self.style, self.language, repr(self.prefs.get("panel")),
                  repr(self.prefs.get("widgets")), self.prefs.get("glass_mode"))
        self.prefs = prefs
        self.configure()
        after = (self.theme_raw, self.style, self.language, repr(prefs.get("panel")), repr(prefs.get("widgets")),
                 prefs.get("glass_mode"))
        if before != after:
            self.retheme()
            if self.page != "settings" or before[:3] != after[:3] or before[3] != after[3] or before[5] != after[5]:
                self.build(keep=True)

    def themed(self):
        self.build(keep=True)

    def set_connected(self, on):
        self.connected = bool(on)
        if self.page == "settings":
            self.build(keep=True)

    def _load_states(self):
        pass

    def push_states(self, items):
        for entity, state in items:
            self.states[entity] = state
        if self.page == "editor":
            self.editor_states_changed()

    def card_radius(self):
        return 48

    def paint_card(self, p):
        w, h = self.css_w, self.css_h
        card = render.squircle(0, 0, w, h, 48)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(*SOLID[self.theme]))
        p.drawPath(card)
        render.inner_shadow(p, card, render.rgba(self.t["card_edge"]))
        if self.t["card_edge_top"]:
            render.inner_shadow(p, card, render.rgba(self.t["card_edge_top"]), dy=1, spread=0)

    def t_(self, text):
        return render.tr(text)

    # -- main.py's calls ----------------------------------------------------------------------------------------
    def enter_settings(self):
        self.go("settings")

    def enter_editor(self, widget_id):
        self.open_editor(widget_id or "")

    def shown_up(self):
        self.cache_hwnd()

    def arm(self):
        self.facade.api.backdrop_armed()

    def escape(self):
        if self.page == "picker":
            self.go(self.return_page)
        elif self.page == "editor":
            self.close_editor()
        else:
            self.close_settings()

    def close_settings(self):
        """Saves the connection fields and has main.py close (and release) the window."""
        if self.page == "settings" and hasattr(self, "url_field"):
            self.fields_text["url"], self.fields_text["token"] = self.url_field.value(), self.token_field.value()
        url = self.fields_text.get("url")
        token = self.fields_text.get("token")
        url = url.strip() if url is not None else None
        token = token.strip() if token is not None else None
        api = self.facade.api

        def go():
            try:
                if url is not None and (url != self.cfg.get("ha_url", "") or token != self.cfg.get("ha_token", "")):
                    api.save_ha_config(url, token)
                api.close_settings_window()
            except Exception:
                traceback.print_exc()
        threading.Thread(target=go, daemon=True).start()

    def save_pref(self, changes):
        self.prefs.update(changes)
        self.cfg.update(changes)

        def go():
            try:
                self.facade.api.save_prefs(changes)
            except Exception:
                traceback.print_exc()
        threading.Thread(target=go, daemon=True).start()

    def save_panel(self, panel):
        self.prefs["panel"] = panel

        def go():
            try:
                self.facade.api.save_panel(panel)
            except Exception:
                traceback.print_exc()
        threading.Thread(target=go, daemon=True).start()

    # -- screens -----------------------------------------------------------------------------------------------------
    def go(self, page):
        self.page = page
        self.build()

    def keep_scroll(self):
        sv = getattr(self, "body_scroll", None)
        if sv is not None:
            self.scroll_keep[self.page] = sv.offset

    def build(self, keep=False):
        self.keep_scroll()
        if hasattr(self, "url_field"):
            self.fields_text["url"] = self.url_field.value()
            self.fields_text["token"] = self.token_field.value()
        self.close_popup()
        self.root.clear()
        for f in list(self.fields):
            self.fields.remove(f)
        self.body_scroll = None
        if self.page == "editor":
            top = self.header("Widget 編輯器", "拖曳新增、擺放，並編排配件", back=self.close_editor)
            body, max_h, width = self.build_editor_body(), 640, 800
        elif self.page == "picker":
            top = self.header("新增配件", "選擇一個實體", back=lambda e: self.go(self.return_page), dot=True)
            body, max_h, width = self.build_picker_body(), BODY_MAX, CARD_W
        else:
            top = self.header("設定", self.t_("已連線 (即時同步)") if self.connected else self.t_("未連線"), dot=True)
            body, max_h, width = self.build_settings_body(), BODY_MAX, CARD_W
        shown_h = min(body.h, max_h)
        sv = ScrollView(0, top, width, shown_h)
        sv.add(body)
        sv.content.w, sv.content.h = width, body.h
        self.root.add(sv)
        self.body_scroll = sv
        sv.scroll_to(self.scroll_keep.get(self.page, 0.0))
        self.card_w = width
        self.set_css_size(width, top + shown_h)
        self.request_size()
        for f in self.fields:
            f.place()
        self.request_paint()

    def mousePressEvent(self, e):
        gx, gy = self._css(e)
        if self.popup is None and isinstance(self.view_at(gx, gy), ui.ScrollView):
            self.pressed_nothing(gx, gy, e)            # the page's own background, between its controls
            return
        super().mousePressEvent(e)

    def pressed_nothing(self, gx, gy, e):
        """The window has no title bar of its own: it is carried by whatever is not a control."""
        if e.button() == Qt.LeftButton:
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemMove()

    def request_size(self):
        self.update_metrics()
        self.seq = getattr(self, "seq", 0) + 1
        seq, pw, ph = self.seq, self.pw, self.ph
        threading.Thread(target=lambda: self.facade.api.resize_settings_window(pw, ph, seq), daemon=True).start()

    def header(self, title, sub, back=None, dot=False):
        width = 800 if self.page == "editor" else CARD_W
        x = 16
        if back is not None:
            b = Button("‹", x=14, y=14, w=30, h=30, size=22, weight=QFont.Bold, on_click=back)
            self.root.add(b)
            x = 14 + 30 + 8
        self.root.add(Label(title, 15, QFont.Bold, "ink1", x=x, y=14, w=width - x - 60, overflow="ellipsis"))
        sx = x
        if dot:
            ok = self.connected
            self.root.add(Rect(x, 14 + 18 + 3.5, 8, 8, "accent_green" if ok else "accent_red", "full"))
            sx = x + 13
        self.root.add(Label(sub, 11.5, QFont.Normal, "ink2", x=sx, y=14 + 18))
        if back is None or self.page == "editor":
            self.root.add(Button("✕", x=width - 14 - 30, y=14, w=30, h=30, size=15,
                                 on_click=lambda e: self.close_settings()))
        return 14 + 18 + 13.8 + 10

    # -- the settings screen -------------------------------------------------------------------------------------------
    def section_title(self, stack, text, mt=0):
        stack.place(Label(text, 12, QFont.Bold, "ink2", w=BODY_W, spacing=0.36), mt, 8)

    def labelled(self, stack, label, view, mb=10):
        block = View(0, 0, BODY_W, 16 + 4 + view.h)
        block.add(Label(label, 12, QFont.Normal, "ink2", w=BODY_W))
        view.y = 20
        block.add(view)
        stack.place(block, 0, mb)

    def build_settings_body(self):
        body = View(0, 0, CARD_W, 0)
        stack = Stack(body, BODY_X, 4, BODY_W)
        prefs = self.prefs
        panel = prefs.get("panel") or {}

        # the connection
        self.section_title(stack, "Home Assistant 連線")
        self.url_field = TextField(0, 0, BODY_W, 36, self.fields_text.get("url", self.cfg.get("ha_url", "")),
                                   "http://homeassistant.local:8123", 13, None, 200)
        self.labelled(stack, "網址", self.url_field)
        self.token_field = TextField(0, 0, BODY_W, 36, self.fields_text.get("token", self.cfg.get("ha_token", "")),
                                     "貼上你的 token", 13, None, 500, password=True)
        self.labelled(stack, "長效存取權杖 (Long-Lived Access Token)", self.token_field)
        row = View(0, 0, BODY_W, 33)
        test = Button("測試連線", size=12.5, weight=QFont.DemiBold, h=33, pad=16, on_click=lambda e: self.test_connection())
        row.add(test)
        self.test_label = Label("", 11.5, QFont.Normal, "ink2", x=test.w + 10, y=(33 - 14) / 2)
        if self.test_result:
            text, color = self.test_result
            self.test_label.text, self.test_label.color = text, color
        row.add(self.test_label)
        stack.place(row, 0, 14)

        # looks
        self.section_title(stack, "外觀")
        stack.place(self.select_block("語言", [("zh-TW", "繁體中文"), ("en", "English")], prefs.get("language", "zh-TW"),
                                      lambda v: self.save_pref({"language": v})), 0, 10)
        half = (BODY_W - 10) / 2
        grid = View(0, 0, BODY_W, 0)
        cells = [("主題", [("auto", "跟隨系統"), ("light", "淺色"), ("dark", "深色")], prefs.get("theme", "auto"),
                  lambda v: self.save_pref({"theme": v})),
                 ("玻璃外觀", [("classic", "經典毛玻璃"), ("liquid", "液態玻璃"), ("windows", "Windows 玻璃")],
                  prefs.get("glass_style", "classic"), self.set_glass_style),
                 ("面板樣式", [("grid", "配件方塊"), ("home", "Home 風格 (依房間)")], panel.get("mode", "grid"),
                  lambda v: self.save_panel(dict(self.prefs.get("panel") or {}, mode=v))),
                 ("工作列面板", [("follow", "同上"), ("auto", "跟隨系統"), ("light", "淺色"), ("dark", "深色")],
                  prefs.get("panel_theme", "follow"), lambda v: self.save_pref({"panel_theme": v}))]
        for i, (label, options, value, change) in enumerate(cells):
            cell = self.select_block(label, options, value, change, w=half)
            cell.x, cell.y = (i % 2) * (half + 10), (i // 2) * (cell.h + 10)
            grid.add(cell)
        grid.h = 2 * (16 + 4 + 36) + 10
        stack.place(grid, 0, 10)
        if self.style == "liquid":
            self.slider_row(stack, "液態玻璃模糊度", prefs.get("liquid_blur", 0), 0, 100, 5, "%",
                            lambda v: self.save_pref({"liquid_blur": int(v)}),
                            "0 最透明，折射最清楚；越往右越模糊，最右接近經典毛玻璃。")
        modes = [("system", "系統繪製 (最省資源，即時)"), ("fast", "畫面擷取 (widget 不出現在截圖／錄影)"),
                 ("compat", "相容模式 (較耗資源，會出現在截圖)")]
        if not prefs.get("system_glass_ok"):
            modes = modes[1:]
        mode = prefs.get("glass_mode", "fast")
        if mode == "system" and not prefs.get("system_glass_ok"):
            mode = "fast"
        self.select_hint(stack, "毛玻璃來源", modes, mode, lambda v: self.save_pref({"glass_mode": v}),
                         "毛玻璃是把視窗底下的桌面擷取下來再模糊畫上去的。擷取模式為了讀得夠快，會把 widget 從畫面擷取中排除，代價是截圖和錄影裡看不到它；相容模式不排除，但改用比較慢的方式取得桌布。")
        # the panel's own picture
        block = View(0, 0, BODY_W, 0)
        block.add(Label("面板背景圖片", 12, QFont.Normal, "ink2", w=BODY_W))
        y = 20
        has = bool(panel.get("bg_image"))
        choose = Button("更換圖片" if has else "選擇圖片", size=12, weight=QFont.DemiBold, h=28, pad=12, x=0, y=y,
                        fill="accent_blue", hover_fill="accent_blue", color="white", on_click=lambda e: self.choose_bg())
        block.add(choose)
        if has:
            block.add(Button("移除", size=12, weight=QFont.DemiBold, h=28, pad=12, x=choose.w + 10, y=y,
                             on_click=lambda e: self.clear_bg()))
        y += 28 + 8
        if has:
            blur_lbl = Label("%s" % self.t_("圖片模糊程度"), 12, QFont.Normal, "ink2", w=BODY_W)
            blur_lbl.y = y
            block.add(blur_lbl)
            y += 18 + 6
            block.add(Slider(0, y - 5, BODY_W, 28 if panel.get("bg_blur") is None else panel["bg_blur"], 0, 80, 2,
                             on_commit=lambda v: self.save_panel(dict(self.prefs.get("panel") or {}, bg_blur=int(v)))))
            y += 12 + 6
        hint = Hint("在系統匣面板的玻璃位置顯示你選的圖片（先套用一層模糊），取代桌面的毛玻璃。", BODY_W)
        hint.y = y
        block.add(hint)
        block.h = y + hint.h
        stack.place(block, 14, 14)
        self.select_hint(stack, "毛玻璃更新", [("live", "動態 (桌布變動時即時更新)"), ("still", "靜態 (只在移動 widget 時更新，最省資源)")],
                         prefs.get("glass_sampling", "live"), lambda v: self.save_pref({"glass_sampling": v}),
                         "使用動態桌布 (如 Wallpaper Engine) 時，動態會隨每個畫面重新取樣。桌布暫停或靜止時兩者都不耗資源；想在動態桌布播放時也省資源，選靜態。")
        self.slider_row(stack, "縮放比例", prefs.get("zoom", 100), 50, 200, 5, "%", lambda v: self.save_pref({"zoom": int(v)}))

        # behaviour
        self.section_title(stack, "行為", 14)
        lock = CheckRow("鎖定位置 (無法拖曳移動)", bool(prefs.get("lock_position")), BODY_W,
                        lambda on: self.save_pref({"lock_position": on}))
        stack.place(lock, 0, 8)
        dim_on = prefs.get("dim_when_idle", True) is not False
        dim = CheckRow("離開桌面時淡化 (全螢幕時立刻淡化，回到桌面或點一下恢復)", dim_on, BODY_W,
                       lambda on: (self.save_pref({"dim_when_idle": on}), self.build(keep=True)))
        stack.place(dim, 0, 8)
        if dim_on:
            sec = prefs.get("dim_after_sec", 120)
            self.slider_row(stack, "離開桌面多久後淡化", sec, 10, 600, 10, "", lambda v: self.save_pref({"dim_after_sec": int(v)}),
                            fmt=dim_text)
        boot = CheckRow("開機時自動啟動", bool(self.cfg.get("start_on_boot")), BODY_W, self.set_boot)
        stack.place(boot, 0, 8)

        # the widgets
        self.section_title(stack, "桌面 Widget", 6)
        stack.place(Button("開啟 Widget 編輯器", size=12.5, weight=QFont.DemiBold, h=33, pad=16, fill="accent_blue",
                           hover_fill="accent_blue", color="white", on_click=lambda e: self.open_editor("")), 0, 5)
        stack.place(Hint("用拖曳新增、擺放 Widget，並編排每個 Widget 顯示的配件。也可以在桌面上對 Widget 按右鍵。", BODY_W), 0, 14)
        foot = View(0, 0, BODY_W, 33)
        done = Button("完成", size=12.5, weight=QFont.DemiBold, h=33, pad=16, fill="accent_blue", hover_fill="accent_blue",
                      color="white", on_click=lambda e: self.close_settings())
        quit_ = Button("結束程式", size=12.5, weight=QFont.DemiBold, h=33, pad=16, color="accent_red",
                       on_click=lambda e: threading.Thread(target=self.facade.api.quit_app, daemon=True).start())
        done.x = BODY_W - done.w
        quit_.x = done.x - 10 - quit_.w
        foot.add(quit_, done)
        stack.place(foot, 8, 0)
        body.h = stack.end() + 16
        return body

    def select_block(self, label, options, value, change, w=BODY_W):
        block = View(0, 0, w, 16 + 4 + 36)
        block.add(Label(label, 12, QFont.Normal, "ink2", w=w))
        block.add(Select(0, 20, w, options, value, change))
        return block

    def select_hint(self, stack, label, options, value, change, hint):
        block = View(0, 0, BODY_W, 0)
        block.add(Label(label, 12, QFont.Normal, "ink2", w=BODY_W))
        block.add(Select(0, 20, BODY_W, options, value, change))
        h = Hint(hint, BODY_W)
        h.y = 20 + 36 + 5
        block.add(h)
        block.h = h.y + h.h
        stack.place(block, 14, 14)

    def slider_row(self, stack, label, value, lo, hi, step, unit, on_commit, hint=None, fmt=None):
        block = View(0, 0, BODY_W, 0)
        fmt = fmt or (lambda v: "%s%s" % (int(v) if float(v).is_integer() else v, unit))
        val = Label(fmt(value), 12, QFont.Normal, "ink2", w=BODY_W, align="r")
        block.add(Label(label, 12, QFont.Normal, "ink2", w=BODY_W), val)
        block.add(Slider(0, 18 + 6 - 5, BODY_W, value, lo, hi, step, on_input=lambda v: setattr(val, "text", fmt(v)),
                         on_commit=on_commit))
        block.h = 18 + 6 + 12
        if hint:
            h = Hint(hint, BODY_W)
            h.y = block.h + 5
            block.add(h)
            block.h = h.y + h.h
        stack.place(block, 14, 14)

    def set_glass_style(self, value):
        self.save_pref({"glass_style": value})
        self.style = value
        self.retheme()
        self.build(keep=True)

    def set_boot(self, on):
        def go():
            try:
                r = self.facade.api.set_start_on_boot(on)
            except Exception as exc:
                r = {"ok": False, "error": str(exc)}
            ok = bool(r and r.get("ok"))
            self.cfg["start_on_boot"] = on if ok else not on

            def after():
                if not ok:
                    self.toast("設定開機啟動失敗: %s" % ((r or {}).get("error") or "未知錯誤"))
                    self.build(keep=True)
            self.facade.run_on_ui_thread(after)
        threading.Thread(target=go, daemon=True).start()

    def choose_bg(self):
        def go():
            try:
                self.facade.api.choose_panel_background()
            except Exception:
                traceback.print_exc()
        threading.Thread(target=go, daemon=True).start()

    def clear_bg(self):
        def go():
            try:
                self.facade.api.clear_panel_background()
            except Exception:
                traceback.print_exc()
        threading.Thread(target=go, daemon=True).start()

    def test_connection(self):
        url, token = self.url_field.value().strip(), self.token_field.value().strip()
        self.test_label.text, self.test_label.color = "測試中...", "ink2"

        def go():
            try:
                r = self.facade.api.test_connection(url, token)
                if r.get("ok"):
                    self.facade.api.save_ha_config(url, token)
                    self.cfg["ha_url"], self.cfg["ha_token"] = url, token
                    res = ("連線成功", "accent_green")
                else:
                    res = ("失敗: %s" % r.get("detail"), "accent_red")
            except Exception as exc:
                res = ("失敗: %s" % exc, "accent_red")

            def show():
                self.test_result = res
                self.test_label.text, self.test_label.color = res
            self.facade.run_on_ui_thread(show)
        threading.Thread(target=go, daemon=True).start()

    # -- the picker --------------------------------------------------------------------------------------------------------
    def open_picker(self):
        self.return_page = "editor" if self.page == "editor" else "settings"
        self.picker_query = ""
        self.entities = None
        self.go("picker")

        def go():
            try:
                ents = self.facade.api.get_entities()
            except Exception:
                ents = []
            self.facade.run_on_ui_thread(lambda: self.picker_loaded(ents))
        threading.Thread(target=go, daemon=True).start()

    def picker_loaded(self, ents):
        self.entities = ents
        if self.page == "picker":
            self.build()

    def build_picker_body(self):
        body = View(0, 0, CARD_W, 0)
        stack = Stack(body, BODY_X, 4, BODY_W)
        search = TextField(0, 0, BODY_W, 36, getattr(self, "picker_query", ""), "搜尋實體 / 名稱...", 13, None, 100,
                           on_change=self.picker_search)
        stack.place(search, 0, 8)
        self.picker_field = search
        list_view = View(0, 0, BODY_W, 0)
        self.picker_list = list_view
        self.fill_picker(list_view)
        stack.place(list_view, 0, 0)
        body.h = stack.end() + 16
        self._picker_stack = stack
        self._picker_body = body
        return body

    def picker_search(self, text):
        self.picker_query = text
        self.fill_picker(self.picker_list)
        self._picker_body.h = self._picker_stack.y + self.picker_list.h + 16
        if self.body_scroll is not None:
            self.body_scroll.content.h = self._picker_body.h
            self.body_scroll.scroll_to(0)
        self.request_paint()

    def fill_picker(self, host):
        host.clear()
        y = 0
        if self.entities is None:
            host.add(Label("載入中...", 11.5, QFont.Normal, "ink2", w=BODY_W))
            host.h = 16
            return
        q = (getattr(self, "picker_query", "") or "").lower()
        used = {t["entity"] for t in self.current_tiles()}
        groups = {}
        for e in self.entities:
            if e["entity_id"] in used:
                continue
            if q and q not in (e["entity_id"] + " " + (e.get("name") or "")).lower():
                continue
            groups.setdefault(e["domain"], []).append(e)
        any_ = False
        for domain in DOMAIN_LABELS:
            items = groups.get(domain)
            if not items:
                continue
            any_ = True
            host.add(Label(DOMAIN_LABELS[domain], 11, QFont.Bold, "ink2", x=2, y=y + 10, spacing=0.3))
            y += 10 + 13 + 4
            for e in items:
                host.add(PickerRow(e, y, BODY_W, self.add_entity))
                y += 44 + 4
        if not any_:
            host.add(Label("沒有符合的實體", 11.5, QFont.Normal, "ink2", w=BODY_W))
            y = 16
        host.h = y


class PickerRow(View):
    cursor = Qt.PointingHandCursor

    def __init__(self, entity, y, w, on_pick):
        super().__init__(0, y, w, 44)
        self.interactive = True
        self.e = entity
        self.on_press = lambda e: True
        self.on_click = lambda ev: on_pick(entity)

    def paint(self, p):
        if self.hovered:
            p.setPen(Qt.NoPen)
            p.setBrush(ui.resolve(self.scene, "btn_fill"))
            p.drawRoundedRect(QRectF(0, 0, self.w, self.h), 22, 22)
        render.draw_icon(p, render.DEFAULT_ICON.get(self.e["domain"], "sensor"), self.scene.t["ink2"], QRectF(8 + 0, 11, 22, 22)) \
            if False else None
        c = ui.resolve(self.scene, "ink2")
        render.draw_icon(p, render.DEFAULT_ICON.get(self.e["domain"], "sensor"), (c.red(), c.green(), c.blue(), c.alphaF()),
                         QRectF(8, 11, 22, 22))
        f1, f2 = ui.font(13), ui.font(10.5)
        m1, m2 = ui.QFontMetricsF(f1), ui.QFontMetricsF(f2)
        p.setPen(Qt.NoPen)
        p.setBrush(ui.resolve(self.scene, "ink1"))
        p.drawPath(render.text_path(QPointF(0, 0), f1, ui.ellipsize(self.e.get("name") or self.e["entity_id"], f1, self.w - 56),
                                    40, 6 + (16 - m1.height() / 10) / 2 + m1.ascent() / 10))
        p.setBrush(ui.resolve(self.scene, "ink2"))
        p.drawPath(render.text_path(QPointF(0, 0), f2, ui.ellipsize(self.e["entity_id"], f2, self.w - 56), 40,
                                    24 + (14 - m2.height() / 10) / 2 + m2.ascent() / 10))


def create_settings(api):
    return create_overlay(api, "HA Widgets Settings", lambda facade: SettingsScene(facade, api), 200, 200)
