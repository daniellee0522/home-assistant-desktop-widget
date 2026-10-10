"""A window that runs one widget: the pointer, the keyboard, an input method, files dragged onto it, a timer for
what moves. It is the kit's own host (a stand-alone window, for developing and for tests); the program's widget
window does the same few things with the same WidgetRuntime.

Keyboard focus: a desktop widget is normally a window that never takes focus (so it cannot steal it from what the
user is typing in). While one of its inputs has the caret the window asks for focus, and gives it back when the
caret leaves. `noactivate` says whether it is a no-focus window to begin with; `set_noactivate` is the Win32 call
that flips it (winsys.windows.set_noactivate in the program).
"""
import os
import threading

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QPainter
from PySide6.QtWidgets import QWidget

from nativeui import render

from .theme import Theme, smooth

KEYS = {Qt.Key_Backspace: "Backspace", Qt.Key_Delete: "Delete", Qt.Key_Left: "Left", Qt.Key_Right: "Right",
        Qt.Key_Home: "Home", Qt.Key_End: "End", Qt.Key_Return: "Enter", Qt.Key_Enter: "Enter",
        Qt.Key_Escape: "Escape"}


class WidgetWindow(QWidget):
    changed = Signal()                                  # emitted from any thread; repaints on the GUI thread

    def __init__(self, runtime, theme="dark", surface="classic", scale=1.0, noactivate=True, set_noactivate=None,
                 size=None, refresh_every=5.0):
        super().__init__()
        self.rt, self.theme_name, self.surface, self.k = runtime, theme, surface, scale
        self.th = Theme(theme, surface)
        if size and size not in runtime.widget.supported_sizes():
            raise ValueError("%s cannot be %s (it supports %s)" % (runtime.widget.id, size,
                                                                    ", ".join(runtime.widget.supported_sizes())))
        self.W, self.H = render.widget_size(size or runtime.widget.size)
        runtime.size_px = (self.W, self.H)
        self.noactivate = noactivate
        self._set_noactivate = set_noactivate
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_InputMethodEnabled, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.resize(round(self.W * scale), round(self.H * scale))
        runtime.invalidate = self.changed.emit
        runtime.on_focus = self._input_mode
        runtime.sv.gui = self._on_gui
        self.changed.connect(self._schedule)
        self._frame = QTimer(self)
        self._frame.setSingleShot(True)
        self._frame.timeout.connect(self.update)
        self.standby = False
        self._refresh_every = refresh_every
        if runtime.sources:                                 # ask the sources again as they come due
            self._refresh = QTimer(self)
            self._refresh.timeout.connect(runtime.refresh_async)
            QTimer.singleShot(0, runtime.refresh_async)
        if runtime.widget.tick:
            self._tick = QTimer(self)
            self._tick.timeout.connect(self.update)

    # ------------------------------------------------------------------ standby, and not being seen
    def set_standby(self, on):
        """Standby (the desktop out of sight, or dimmed): the widget is dimmed (`Theme(dim=True)`, `ctx.standby`), redraws at
        its `standby_tick` (once a minute unless it says), and its sources are asked less often."""
        self.standby = bool(on)
        self.th = Theme(self.theme_name, self.surface, dim=self.standby)
        self.rt.set_standby(on)
        self._timers()
        self.update()

    def _live(self):
        """Is anyone able to see this window? A window that is hidden or minimised draws nothing and asks for nothing."""
        return self.isVisible() and not self.isMinimized()

    def _timers(self):
        """Run the timers that should be running: its tick (or its standby tick), and the sources' refresh; none at all while
        the window is out of sight."""
        live = self._live()
        if hasattr(self, "_tick"):
            self._tick.stop()
            seconds = self.rt.widget.standby_interval() if self.standby else self.rt.widget.tick
            if live and seconds:
                self._tick.start(max(1, int(seconds * 1000)))
        if hasattr(self, "_refresh"):
            self._refresh.stop()
            if live:
                self._refresh.start(max(1, int(self._refresh_every * (6 if self.standby else 1) * 1000)))
        if not live:
            self._frame.stop()

    def showEvent(self, e):
        super().showEvent(e)
        self._timers()
        if hasattr(self, "_refresh"):
            self.rt.refresh_async()                          # whatever went stale while it was out of sight

    def hideEvent(self, e):
        super().hideEvent(e)
        self._timers()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.WindowStateChange:
            self._timers()

    # ------------------------------------------------------------------ what winsys asks of a window
    def hwnd(self):
        return int(self.winId())

    def run_on_ui_thread(self, fn):
        """Run fn on the GUI thread and wait for it (winsys.windows calls this on the window it works on)."""
        if threading.current_thread() is threading.main_thread():
            return fn()
        done, box = threading.Event(), []
        self._on_gui(lambda: (box.append(fn()), done.set()))
        done.wait(5)
        return box[0] if box else None

    # ------------------------------------------------------------------ the window's own business
    def _on_gui(self, fn):
        """Run fn on the GUI thread: from here it is a queued call through a one-shot timer."""
        QTimer.singleShot(0, self, fn)

    def _input_mode(self, on):
        """An input has the caret (on) or has lost it: take focus, or give it back."""
        if self._set_noactivate:
            self._set_noactivate(self, not on and self.noactivate)
        if on:
            self.activateWindow()
            self.setFocus(Qt.OtherFocusReason)

    def _pos(self, e):
        p = e.position() if hasattr(e, "position") else QPointF(e.pos())
        return p.x() / self.k, p.y() / self.k

    def set_theme(self, theme, surface=None):
        self.theme_name, self.surface = theme, surface or self.surface
        self.th = Theme(self.theme_name, self.surface, dim=self.standby)
        self.update()

    def _schedule(self):
        """Repaint now, or next frame while something is easing (so a spring does not spin the CPU)."""
        if not self._live():
            return                                           # nobody can see it: nothing to draw now, and it is drawn on showing
        if self.rt.animating:
            if not self._frame.isActive():
                self._frame.start(16)
        else:
            self.update()

    # ------------------------------------------------------------------ painting
    def paintEvent(self, e):
        p = QPainter(self)
        p.scale(self.k, self.k)
        smooth(p)
        render.draw_card_bg(p, self.W, self.H, self.th.tokens, self.surface, self.theme_name)
        self.rt.draw(p, self.th, self.W, self.H)
        p.end()
        if self._live():
            if self.rt.animating:
                self._frame.start(16)
            elif self.rt.redraw_in is not None:               # a slideshow's next picture, an animation's next frame
                self._frame.start(max(16, int(self.rt.redraw_in * 1000)))

    def wheelEvent(self, e):
        x, y = self._pos(e)
        if self.rt.wheel(x, y, -e.angleDelta().y() / 120 * 40):
            e.accept()
        else:
            super().wheelEvent(e)

    # ------------------------------------------------------------------ pointer
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.rt.press(*self._pos(e))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.rt.release(*self._pos(e))
        elif e.button() == Qt.RightButton:
            self.rt.context(*self._pos(e))

    def mouseMoveEvent(self, e):
        self.rt.move(*self._pos(e))

    def leaveEvent(self, e):
        self.rt.leave()

    # ------------------------------------------------------------------ keyboard and input method
    def keyPressEvent(self, e):
        if not self.rt.wants_keyboard:
            return super().keyPressEvent(e)
        if e.matches(QKeySequence.Paste):
            self.rt.text(QGuiApplication.clipboard().text())
        elif e.key() in KEYS:
            self.rt.key(KEYS[e.key()])
        elif e.text() and not (e.modifiers() & (Qt.ControlModifier | Qt.AltModifier)):
            self.rt.text(e.text())

    def inputMethodEvent(self, e):
        if e.commitString():
            self.rt.text(e.commitString())
        self.rt.set_preedit(e.preeditString())

    def inputMethodQuery(self, query):
        if query == Qt.ImEnabled:
            return self.rt.wants_keyboard
        if query == Qt.ImCursorRectangle:               # where the input method puts its candidate window
            for rect, id in self.rt.ctx.hits.items:
                if id == self.rt.ctx.focus:
                    return QRectF(rect.left() * self.k, rect.top() * self.k, 2, rect.height() * self.k).toRect()
        return super().inputMethodQuery(query)

    def focusOutEvent(self, e):
        if self.rt.wants_keyboard and not self.hasFocus():
            self.rt.blur()
        super().focusOutEvent(e)

    # ------------------------------------------------------------------ files
    def _paths(self, e):
        return [os.path.normpath(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if self.rt.drag_move(*self._pos(e), self._paths(e)):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        self.rt.drag_leave()

    def dropEvent(self, e):
        if self.rt.drop(*self._pos(e), self._paths(e)):
            e.acceptProposedAction()

    def closeEvent(self, e):
        self.rt.close()
        super().closeEvent(e)
