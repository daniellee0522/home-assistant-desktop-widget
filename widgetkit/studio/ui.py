"""The studio's window: the widget at every size, theme and language you ask for, beside its settings, memory, problems
and an icon browser. It reloads the widget the moment its file is saved, so it works beside any editor."""
import json
import os
import time

from PySide6.QtCore import (QAbstractListModel, QFileSystemWatcher, QModelIndex, QObject, QPointF, QRectF, QSize, Qt, QTimer,
                            Signal)
from PySide6.QtGui import (QAction, QColor, QFont, QGuiApplication, QIcon, QKeySequence, QLinearGradient, QPainter,
                           QPalette, QPixmap)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDateTimeEdit, QDockWidget, QFileDialog, QHBoxLayout,
                               QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem, QMainWindow, QPlainTextEdit,
                               QPushButton, QScrollArea, QTabWidget, QToolBar, QVBoxLayout, QWidget)

from nativeui import render
from ..form import Form
from ..host import KEYS
from ..theme import Theme, smooth
from .session import LANGUAGES, THEMES, Session

CAPTION_H, GAP, MARGIN = 24, 22, 22


class Bridge(QObject):
    """Lets any thread ask for a repaint: the signal is delivered on the GUI thread."""
    changed = Signal()


# ---------------------------------------------------------------------------------------------------- the previews
class PreviewCanvas(QWidget):
    def __init__(self, session):
        super().__init__()
        self.s = session
        self.rects = {}
        self.backdrop = "gradient"
        self.setMouseTracking(True)
        self._pressed = None
        self._frame = QTimer(self)
        self._frame.setSingleShot(True)
        self._frame.timeout.connect(self.update)

    def layout_cells(self):
        """Where each copy goes: a row for each size, wrapping."""
        self.rects.clear()
        x = y = MARGIN
        row_h, last_size = 0, None
        width = max(self.width(), 300)
        for cell in self.s.cells():
            w, h = self.s.size_px(cell)
            w, h = w * self.s.scale, h * self.s.scale
            if last_size is not None and (cell.size != last_size or x + w > width - MARGIN) and x > MARGIN:
                x, y, row_h = MARGIN, y + row_h + GAP + CAPTION_H, 0
            self.rects[cell] = QRectF(x, y + CAPTION_H, w, h)
            x += w + GAP
            row_h = max(row_h, h)
            last_size = cell.size
        self.setMinimumHeight(int(y + row_h + CAPTION_H + 2 * MARGIN))

    def resizeEvent(self, e):
        self.layout_cells()

    def refresh_layout(self):
        self.layout_cells()
        self.update()

    def paintEvent(self, e):
        self.layout_cells()
        p = QPainter(self)
        g = QLinearGradient(0, 0, self.width(), self.height())
        colors = {"gradient": ("#5d7bb5", "#c28fa8"), "dark": ("#16181c", "#23262d"), "light": ("#e9edf3", "#f7f8fa")}[self.backdrop]
        g.setColorAt(0, QColor(colors[0]))
        g.setColorAt(1, QColor(colors[1]))
        p.fillRect(self.rect(), g)
        animating = False
        caption_color = QColor(255, 255, 255, 190) if self.backdrop != "light" else QColor(40, 44, 52, 200)
        for cell, rect in self.rects.items():
            p.save()
            p.setPen(caption_color)
            f = QFont(p.font())
            f.setPointSizeF(9)
            p.setFont(f)
            p.drawText(QRectF(rect.left(), rect.top() - CAPTION_H, rect.width(), CAPTION_H - 4), Qt.AlignLeft | Qt.AlignBottom,
                       "%s · %s · %s" % (cell.size, cell.theme, LANGUAGES.get(cell.lang, cell.lang)))
            p.translate(rect.topLeft())
            p.scale(self.s.scale, self.s.scale)
            self.s.draw_cell(p, cell)
            p.restore()
            animating = animating or self.s.runtime(cell).animating
            if any(i.kind in ("error", "cut") for i in self.s.issues.get(cell, [])):
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#ff453a"))
                p.drawEllipse(QPointF(rect.right() - 8, rect.top() - 12), 5, 5)
        p.end()
        if animating:
            self._frame.start(16)

    def _hit(self, e):
        pos = e.position()
        for cell, rect in self.rects.items():
            if rect.contains(pos):
                return cell, (pos.x() - rect.left()) / self.s.scale, (pos.y() - rect.top()) / self.s.scale
        return None

    def mousePressEvent(self, e):
        hit = self._hit(e)
        if hit and e.button() == Qt.LeftButton:
            self._pressed = hit[0]
            self.s.press(*hit)

    def mouseMoveEvent(self, e):
        if self._pressed is not None:
            rect = self.rects[self._pressed]
            self.s.move(self._pressed, (e.position().x() - rect.left()) / self.s.scale,
                        (e.position().y() - rect.top()) / self.s.scale)
        else:
            hit = self._hit(e)
            self.setCursor(Qt.PointingHandCursor if hit and self.s.runtime(hit[0]).ctx.hits.at(hit[1], hit[2]) is not None
                           else Qt.ArrowCursor)

    def mouseReleaseEvent(self, e):
        if self._pressed is not None:
            rect = self.rects[self._pressed]
            self.s.release(self._pressed, (e.position().x() - rect.left()) / self.s.scale,
                           (e.position().y() - rect.top()) / self.s.scale)
            self._pressed = None


# ---------------------------------------------------------------------------------------------------- settings
class FormView(QWidget):
    """The widget's settings window, drawn by the kit's own Form, in a Qt widget that feeds it the mouse and keyboard."""

    def __init__(self, session):
        super().__init__()
        self.s, self.form, self.lang = session, None, "en"
        self.setAttribute(Qt.WA_InputMethodEnabled, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumWidth(380)
        self.rebuild()

    def rebuild(self):
        if self.s.widget is None:
            self.form = None
        else:
            self.form = Form(self.s.widget, self.s.config, on_change=self._changed, lang=self.lang)
            self.s.config = dict(self.form.values)
        self.update()

    def _changed(self, values, key):
        self.s.set_config(values)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(28, 28, 30))
        if self.form:
            smooth(p)
            h = self.form.draw(p, Theme("dark"), QRectF(16, 12, self.width() - 32, 4000))
            self.setMinimumHeight(int(h + 40))
        p.end()

    def mousePressEvent(self, e):
        if self.form:
            self.form.click(e.position().x(), e.position().y())
            self.setFocus()
            self._input_mode()
            self.update()

    def _input_mode(self):
        self.setAttribute(Qt.WA_InputMethodEnabled, True)

    def wheelEvent(self, e):
        if self.form and self.form.wheel(e.position().x(), e.position().y(), -e.angleDelta().y() / 120 * 40):
            self.update()
            e.accept()
        else:
            e.ignore()

    def keyPressEvent(self, e):
        if not (self.form and self.form.focus):
            return super().keyPressEvent(e)
        if e.matches(QKeySequence.Paste):
            self.form.type(QGuiApplication.clipboard().text().replace("\n", " "))
        elif e.key() in KEYS:
            self.form.press(KEYS[e.key()])
        elif e.text() and not (e.modifiers() & (Qt.ControlModifier | Qt.AltModifier)):
            self.form.type(e.text())
        self.update()

    def inputMethodEvent(self, e):
        if self.form and e.commitString():
            self.form.type(e.commitString())
            self.update()

    def inputMethodQuery(self, q):
        if q == Qt.ImEnabled:
            return bool(self.form and self.form.focus)
        return super().inputMethodQuery(q)


# ---------------------------------------------------------------------------------------------------- icons
class IconModel(QAbstractListModel):
    """Every icon the kit can draw, rendered when the list first needs it."""

    def __init__(self):
        super().__init__()
        path = os.path.join(os.path.dirname(render.__file__), "mdi_paths.json")
        with open(path, encoding="utf-8") as f:
            self.all = sorted(json.load(f))
        self.names = list(self.all)
        self._cache = {}

    def filter(self, text):
        self.beginResetModel()
        words = text.lower().split()
        self.names = [n for n in self.all if all(w in n for w in words)]
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self.names)

    def data(self, index, role):
        name = self.names[index.row()]
        if role == Qt.DisplayRole:
            return name
        if role == Qt.ToolTipRole:
            return "mdi:" + name
        if role == Qt.DecorationRole:
            icon = self._cache.get(name)
            if icon is None:
                pm = QPixmap(96, 96)
                pm.fill(Qt.transparent)
                q = QPainter(pm)
                q.setRenderHint(QPainter.Antialiasing)
                render.draw_icon(q, "mdi:" + name, "#f5f5f7", QRectF(12, 12, 72, 72))
                q.end()
                icon = self._cache[name] = QIcon(pm)
            return icon
        return None


class IconBrowser(QWidget):
    copied = Signal(str)

    def __init__(self):
        super().__init__()
        self.model = IconModel()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search %d icons: water, cup, clock..." % len(self.model.all))
        self.search.textChanged.connect(self.model.filter)
        self.view = QListView()
        self.view.setViewMode(QListView.IconMode)
        self.view.setResizeMode(QListView.Adjust)
        self.view.setUniformItemSizes(True)
        self.view.setIconSize(QSize(40, 40))
        self.view.setGridSize(QSize(96, 80))
        self.view.setWordWrap(True)
        self.view.setModel(self.model)
        self.view.doubleClicked.connect(self._copy)
        self.view.clicked.connect(lambda i: self.line.setText("mdi:%s      (double-click to copy)" % self.model.names[i.row()]))
        self.line = QLabel("Double-click an icon to copy its name")
        self.line.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay = QVBoxLayout(self)
        lay.addWidget(self.search)
        lay.addWidget(self.view)
        lay.addWidget(self.line)

    def _copy(self, index):
        name = "mdi:" + self.model.names[index.row()]
        QGuiApplication.clipboard().setText(name)
        self.line.setText("Copied  %s   →   controls.icon(p, \"%s\", th.ink1, rect, 24)" % (name, name))
        self.copied.emit(name)


# ---------------------------------------------------------------------------------------------------- the window
class Studio(QMainWindow):
    def __init__(self, path):
        super().__init__()
        self.setWindowTitle("Widget Studio")
        self.resize(1500, 950)
        self.s = Session(path)
        self.bridge = Bridge()
        self.bridge.changed.connect(self._repaint)
        self._wire(self.s)
        self.canvas = PreviewCanvas(self.s)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.canvas)
        self.setCentralWidget(scroll)
        self._build_toolbar()
        self._build_dock()
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._file_changed)
        self.watcher.directoryChanged.connect(self._file_changed)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self.reload)
        self._tick = QTimer(self)
        self._tick.timeout.connect(self.canvas.update)
        self._watch()
        self._after_reload()

    def _wire(self, session):
        """Let the session ask this window to repaint from any thread, and fetch data off the GUI thread."""
        import threading
        session.on_change = self.bridge.changed.emit
        session.gui = lambda fn: QTimer.singleShot(0, self, fn)
        session.spawn = lambda fn: threading.Thread(target=fn, daemon=True).start()
        session.threaded = True

    # ---- toolbar
    def _toggle(self, bar, text, on, slot, tip=""):
        a = QAction(text, self)
        a.setCheckable(True)
        a.setChecked(on)
        a.setToolTip(tip)
        a.toggled.connect(slot)
        bar.addAction(a)
        return a

    def _build_toolbar(self):
        bar = QToolBar("main")
        bar.setMovable(False)
        bar.setStyleSheet("QToolButton:checked { background: #0a84ff; color: white; border-radius: 4px; }"
                          "QToolButton { padding: 3px 7px; }")
        self.addToolBar(bar)
        a = QAction("Open…", self)
        a.triggered.connect(self.open_file)
        bar.addAction(a)
        a = QAction("Reload", self)
        a.setShortcut(QKeySequence("F5"))
        a.triggered.connect(self.reload)
        bar.addAction(a)
        a = QAction("Refresh data", self)
        a.setToolTip("Fetch the widget's data again (live, or from its .fixtures.json)")
        a.triggered.connect(self.s.refresh)
        bar.addAction(a)
        bar.addSeparator()
        bar.addWidget(QLabel(" Language "))
        self.lang_actions = {l: self._toggle(bar, name, l in self.s.langs, lambda on, l=l: self._pick("langs", l, on))
                             for l, name in LANGUAGES.items()}
        bar.addSeparator()
        bar.addWidget(QLabel(" Theme "))
        self.theme_actions = {t: self._toggle(bar, t, t in self.s.themes, lambda on, t=t: self._pick("themes", t, on))
                              for t in THEMES}
        bar.addSeparator()
        bar.addWidget(QLabel(" Size "))
        self.size_holder = bar
        self.size_mark = bar.addSeparator()
        self._size_widgets = []
        bar.addWidget(QLabel(" Zoom "))
        self.zoom = QComboBox()
        for z in (0.5, 0.75, 1.0, 1.5, 2.0):
            self.zoom.addItem("%d%%" % (z * 100), z)
        self.zoom.setCurrentIndex(max(0, self.zoom.findData(self.s.scale)))
        self.zoom.currentIndexChanged.connect(self._zoom)
        bar.addWidget(self.zoom)
        bar.addWidget(QLabel(" Behind "))
        self.backdrop = QComboBox()
        self.backdrop.addItems(["gradient", "dark", "light"])
        self.backdrop.currentTextChanged.connect(self._backdrop)
        bar.addWidget(self.backdrop)
        bar.addSeparator()
        self.hits_action = self._toggle(bar, "Hit areas", False, lambda on: self._overlay("hits", on),
                                        "Show where each control can be pressed (orange: drawn too small)")
        self.safe_action = self._toggle(bar, "Safe area", False, lambda on: self._overlay("safe", on),
                                        "Show the 22 px margin")
        self.standby_action = self._toggle(bar, "Standby", False, self._standby,
                                           "Show the widget as it is when the program is in standby: dimmed, drawn rarely")
        bar.addSeparator()
        self.fake = QCheckBox("Pretend it is")
        self.fake.toggled.connect(self._fake_time)
        self.when = QDateTimeEdit()
        self.when.setCalendarPopup(True)
        self.when.setDisplayFormat("yyyy-MM-dd HH:mm")
        from PySide6.QtCore import QDateTime
        self.when.setDateTime(QDateTime.currentDateTime())
        self.when.dateTimeChanged.connect(self._fake_time)
        bar.addWidget(self.fake)
        bar.addWidget(self.when)

    def _rebuild_size_buttons(self):
        for a in self._size_widgets:
            self.size_holder.removeAction(a)
        self._size_widgets.clear()
        if not self.s.widget:
            return
        for size in self.s.widget.supported_sizes():
            a = QAction(size, self)
            a.setCheckable(True)
            a.setChecked(size in self.s.sizes)
            a.toggled.connect(lambda on, size=size: self._pick("sizes", size, on))
            self.size_holder.insertAction(self.size_mark, a)
            self._size_widgets.append(a)

    def _pick(self, what, value, on):
        items = getattr(self.s, what)
        if on and value not in items:
            items.append(value)
        elif not on and value in items and len(items) > 1:
            items.remove(value)
        order = {"langs": list(LANGUAGES), "themes": list(THEMES), "sizes": list(self.s.widget.supported_sizes()) if self.s.widget else []}[what]
        items.sort(key=order.index)
        self.s.save()
        self.canvas.refresh_layout()

    def _zoom(self):
        self.s.scale = self.zoom.currentData()
        self.s.save()
        self.canvas.refresh_layout()

    def _backdrop(self, name):
        self.canvas.backdrop = name
        self.canvas.update()

    def _standby(self, on):
        self.s.set_standby(on)
        self._apply_tick()
        self.canvas.update()
        self.status.showMessage(("Standby: dimmed, and redrawn every %s s" % ("%g" % self.s.tick_seconds())
                                 if self.s.tick_seconds() else "Standby: dimmed, and not redrawn by itself") if on else "Awake", 4000)

    def _apply_tick(self):
        """Redraw by itself as often as the widget asks for in the state it is in (awake, or standby)."""
        self._tick.stop()
        seconds = self.s.tick_seconds()
        if seconds:
            self._tick.start(max(1, int(seconds * 1000)))

    def _overlay(self, name, on):
        self.s.overlays[name] = on
        self.canvas.update()

    def _fake_time(self, *_):
        self.s.fake_now = self.when.dateTime().toSecsSinceEpoch() if self.fake.isChecked() else None
        self.canvas.update()

    # ---- the side panel
    def _build_dock(self):
        self.tabs = QTabWidget()
        self.form_view = FormView(self.s)
        fscroll = QScrollArea()
        fscroll.setWidgetResizable(True)
        fscroll.setWidget(self.form_view)
        settings = QWidget()
        lay = QVBoxLayout(settings)
        lay.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("Settings shown in"))
        self.form_lang = QComboBox()
        for l, name in LANGUAGES.items():
            self.form_lang.addItem(name, l)
        self.form_lang.currentIndexChanged.connect(self._form_lang)
        row.addWidget(self.form_lang)
        row.addStretch()
        lay.addLayout(row)
        lay.addWidget(fscroll)
        self.tabs.addTab(settings, "Settings")

        state = QWidget()
        sl = QVBoxLayout(state)
        self.state_edit = QPlainTextEdit()
        self.state_edit.setFont(QFont("Consolas", 10))
        self.state_error = QLabel("")
        self.state_error.setStyleSheet("color:#ff453a")
        self.state_edit.textChanged.connect(self._state_typed)
        reset = QPushButton("Reset to the widget's own starting state")
        reset.clicked.connect(self._reset_state)
        sl.addWidget(QLabel("The widget's memory (ctx.state), as JSON. Edit it to see the widget in any situation."))
        sl.addWidget(self.state_edit)
        sl.addWidget(self.state_error)
        sl.addWidget(reset)
        self.tabs.addTab(state, "State")
        self._state_timer = QTimer(self)
        self._state_timer.setSingleShot(True)
        self._state_timer.timeout.connect(self._apply_state)

        self.problems = QListWidget()
        self.load_box = QPlainTextEdit()
        self.load_box.setReadOnly(True)
        self.load_box.setFont(QFont("Consolas", 9))
        self.load_box.setStyleSheet("color:#ff6b61")
        pw = QWidget()
        pl = QVBoxLayout(pw)
        pl.addWidget(self.load_box, 1)
        pl.addWidget(self.problems, 2)
        self.tabs.addTab(pw, "Problems")

        self.actions_list = QListWidget()
        self.real = QCheckBox("Do what the widget asks for real (open pages, record, run programs)")
        self.real.toggled.connect(lambda on: setattr(self.s, "real_actions", on))
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda: (self.s.log.clear(), self._repaint()))
        aw = QWidget()
        al = QVBoxLayout(aw)
        al.addWidget(QLabel("What the widget asked to do (not done unless the box below is ticked):"))
        al.addWidget(self.actions_list)
        al.addWidget(self.real)
        al.addWidget(clear)
        self.tabs.addTab(aw, "Actions")

        self.icons = IconBrowser()
        self.tabs.addTab(self.icons, "Icons")
        dock = QDockWidget("", self)
        dock.setTitleBarWidget(QWidget())
        dock.setWidget(self.tabs)
        dock.setMinimumWidth(430)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.status = self.statusBar()

    def _form_lang(self):
        self.form_view.lang = self.form_lang.currentData()
        self.form_view.rebuild()

    def _state_typed(self):
        if not self._setting_state:
            self._state_timer.start(400)

    _setting_state = False

    def _apply_state(self):
        err = self.s.apply_state_json(self.state_edit.toPlainText())
        self.state_error.setText(err or "")

    def _reset_state(self):
        self.s.reset_state()
        self._show_state()

    def _show_state(self):
        if self.state_edit.hasFocus():
            return
        self._setting_state = True
        text = self.s.state_json()
        if text != self.state_edit.toPlainText():
            self.state_edit.setPlainText(text)
        self._setting_state = False

    # ---- file
    def _watch(self):
        for p in self.watcher.files() + self.watcher.directories():
            self.watcher.removePath(p)
        if os.path.exists(self.s.entry):
            self.watcher.addPath(self.s.entry)
            self.watcher.addPath(os.path.dirname(self.s.entry))

    def _file_changed(self, _):
        self._debounce.start(200)                     # editors save in several steps: wait for them to finish

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open a widget", os.path.dirname(self.s.entry), "Python (*.py)")
        if path:
            for rt in self.s.runtimes.values():
                rt.close()
            self.s = Session(path)
            self._wire(self.s)
            self.canvas.s = self.form_view.s = self.s
            self._watch()
            self._after_reload()

    def reload(self):
        ok = self.s.reload()
        self._watch()
        self._after_reload()
        self.status.showMessage(("Reloaded %s" if ok else "Could not load %s — showing the last good version")
                                % time.strftime("%H:%M:%S"), 5000)

    def _after_reload(self):
        self._rebuild_size_buttons()
        self.form_view.rebuild()
        self.canvas.refresh_layout()
        w = self.s.widget
        self.setWindowTitle("Widget Studio — %s" % (os.path.basename(self.s.entry)))
        self._apply_tick()
        self._show_state()
        self.s.check_backgrounds()
        self._repaint()

    def _repaint(self):
        self.canvas.update()
        self._show_state()
        self.load_box.setPlainText(self.s.load_error or "")
        self.problems.clear()
        for i in self.s.all_issues():
            item = QListWidgetItem(("● " if i.kind in ("load", "error") else "▲ ") + i.text +
                                   ("   [%s]" % i.cell.caption if i.cell else ""))
            item.setForeground(QColor("#ff6b61") if i.kind in ("load", "error") else QColor("#ffb340"))
            self.problems.addItem(item)
        n = self.problems.count()
        if not n and self.s.widget:
            item = QListWidgetItem("✓ Nothing looks wrong in the %d copies on show" % len(self.s.cells()))
            item.setForeground(QColor("#32d74b"))
            self.problems.addItem(item)
        self.tabs.setTabText(2, "Problems (%d)" % n if n else "Problems")
        self.actions_list.clear()
        for when, text in self.s.log[-200:]:
            self.actions_list.addItem("%s   %s" % (time.strftime("%H:%M:%S", time.localtime(when)), text))
        self.actions_list.scrollToBottom()


def run(path, shot=None, tab=None, search=None, langs=None, themes=None, sizes=None, zoom=None, overlays=(), fake=None,
        width=None, height=None, state=None, config=None, standby=False):
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(37, 38, 42))
    pal.setColor(QPalette.WindowText, QColor(235, 235, 240))
    pal.setColor(QPalette.Base, QColor(28, 29, 32))
    pal.setColor(QPalette.AlternateBase, QColor(37, 38, 42))
    pal.setColor(QPalette.Text, QColor(235, 235, 240))
    pal.setColor(QPalette.Button, QColor(52, 54, 60))
    pal.setColor(QPalette.ButtonText, QColor(235, 235, 240))
    pal.setColor(QPalette.Highlight, QColor(10, 132, 255))
    app.setPalette(pal)
    win = Studio(path)
    read = lambda v: open(v[1:], encoding="utf-8").read() if v.startswith("@") else v          # --state @file.json
    state, config = (read(state) if state else None), (read(config) if config else None)
    if config:
        win.s.set_config(json.loads(config))
        win.form_view.rebuild()
    if state:
        win.s.apply_state_json(state)
        win._show_state()
    if width:
        win.resize(width, height or win.height())
    if langs:
        for l, a in win.lang_actions.items():
            a.setChecked(l in langs)
    if themes:
        for t, a in win.theme_actions.items():
            a.setChecked(t in themes)
    if sizes:
        for a in win._size_widgets:
            a.setChecked(a.text() in sizes)
    if zoom:
        win.zoom.setCurrentIndex(max(0, win.zoom.findData(zoom)))
    for name in overlays:
        {"hits": win.hits_action, "safe": win.safe_action}[name].setChecked(True)
    if standby:
        win.standby_action.setChecked(True)
    if fake is not None:
        win.when.setDateTime(fake)
        win.fake.setChecked(True)
    if tab:
        win.tabs.setCurrentIndex({"settings": 0, "state": 1, "problems": 2, "actions": 3, "icons": 4}[tab])
    if search:
        win.icons.search.setText(search)
    win.show()
    if shot:
        end = time.monotonic() + 1.0
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)
        win.grab().save(shot)
        win.close()
        return win
    return app.exec()
