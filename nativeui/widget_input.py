"""Hit-testing and the keyboard, wheel and drag-and-drop handling of a desktop widget's surface (widget.py); its mouse\npress, move and release stay in the surface itself."""

from PySide6.QtCore import QPointF


from . import kinds, render
from .widget_common import WHEEL_STEP

class SurfaceInput:
    """Hit-testing and the keyboard, wheel and drag-and-drop handling of a desktop widget's surface (widget.py); its mouse\npress, move and release stay in the surface itself"""

    # ---- the pointer -----------------------------------------------------------
    def _point(self, e):
        """The pointer in CSS px of the widget (the scroll undone for the tiles) and physical px."""
        pos = e.position()
        px, py = pos.x() * self.devicePixelRatioF(), pos.y() * self.devicePixelRatioF()
        return px / self.scale, py / self.scale, px, py

    def _tile_at(self, x, y):
        y += self.scroll
        for i, (tx, ty, tw, th) in enumerate(self.rects):
            if tx <= x < tx + tw and ty <= y < ty + th and \
                    render.squircle(tx, ty, tw, th, self.tcol["radius_tile"]).contains(QPointF(x, y)):
                return i
        return -1

    def _hit_mini(self, i, x, y):
        """+1 / -1 for a press on a climate button of tile i, 0 otherwise."""
        tile = self.tiles[i]
        st = self.states.get(tile["entity"])
        if tile["domain"] != "climate" or not st or st.get("state") == "off":
            return 0
        tx, ty, tw, th = self.rects[i]
        zoom = render.BIG_ZOOM if self.form == "big" else 1.0
        local = QPointF((x - tx) / zoom, (y + self.scroll - ty) / zoom)
        if self.form == "small" and self.hover != i:
            return 0
        for rect, sign in render.mini_buttons(self.form, tw / zoom, th / zoom):
            if rect.contains(local):
                return sign
        return 0

    def _button_at(self, x, y):
        r = self.empty_button
        return bool(r and not self.tiles and r.contains(QPointF(x, y)))

    def _seek_to(self, x):
        """Where the song would be with the bar let go at x (shown at once)."""
        bar = next((r for r, a in self.kind_buttons if a == "seek"), None)
        st = self.states.get(self.tiles[0]["entity"]) if self.tiles else None
        if bar is None or not st:
            return None
        _, dur = kinds.media_position(st)
        self.extras["seek_to"] = max(0.0, min(1.0, (x - bar.x()) / max(1.0, bar.width()))) * dur
        self._redraw_tiles()
        return self.extras["seek_to"]

    def _action_at(self, x, y):
        """A player's button under (x, y): its action, or None."""
        for rect, action in self.kind_buttons:
            if rect.adjusted(-6, -6, 6, 6).contains(QPointF(x, y)):
                return action
        return None

    def _held(self):
        if self._press and self._press.get("tile", -1) >= 0 and not self._press.get("moved"):
            self._press["fired"] = True
            self.pressed = -1
            self._invalidate_overlay()
            self.facade.popover(self.tiles[self._press["tile"]])

    def _qt_leaveEvent(self, e):
        if self.wkind == "custom":
            self.kit.leave()
            return
        self._hold.stop()
        if self.hover >= 0:
            self.hover = -1
            self._invalidate_overlay()
        if self.pressed >= 0:
            self.pressed = -1
            self._invalidate_overlay()

    def _qt_wheelEvent(self, e):
        if self.wkind == "custom":
            if self.kit.wheel(e):
                e.accept()
            return
        if self.scroll_max <= 0:
            return
        step = -e.angleDelta().y() / 120.0 * WHEEL_STEP
        new = max(0.0, min(self.scroll + step, self.scroll_max))
        if new != self.scroll:
            self.scroll = new
            self._invalidate_overlay()
            if self._liquid_glass():
                # The liquid glass blurs behind each tile (glass_tiles), which have just moved.
                self.invalidate_glass()

    # ---- the keyboard, the input method and files, for a widget of the kit ------------------------------
    def _qt_keyPressEvent(self, e):
        if not (self.wkind == "custom" and self.kit.key_press(e)):
            super().keyPressEvent(e)

    def _qt_inputMethodEvent(self, e):
        if self.wkind == "custom":
            self.kit.input_method(e)

    def _qt_inputMethodQuery(self, query):
        got = self.kit.input_query(query) if self.wkind == "custom" else None
        return super().inputMethodQuery(query) if got is None else got

    def _qt_focusOutEvent(self, e):
        if self.wkind == "custom" and not self.hasFocus():
            self.kit.focus_out()
        super().focusOutEvent(e)

    def _qt_dragEnterEvent(self, e):
        if self.wkind == "custom" and e.mimeData().hasUrls():
            e.acceptProposedAction()

    def _qt_dragMoveEvent(self, e):
        if self.wkind == "custom" and self.kit.drag_move(e):
            e.acceptProposedAction()
        else:
            e.ignore()

    def _qt_dragLeaveEvent(self, e):
        self.kit.drag_leave()

    def _qt_dropEvent(self, e):
        if self.wkind == "custom" and self.kit.drop(e):
            e.acceptProposedAction()
