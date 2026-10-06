"""Desktop detail and floating menus fit the visible card, independently of its canvas."""
import unittest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage

import test_native_panel as T
from nativeui import controls, detail, ui


class DesktopPopupBounds(unittest.TestCase):
    def make_card(self, zoom=100, work=(0, 0, 300, 400)):
        tile = dict(id="ac", entity="climate.ac", domain="climate", room="冷氣", label="")
        api = T.FakeApi("grid", [tile])
        prefs = api._prefs()
        api._prefs = lambda: dict(prefs, zoom=zoom)
        api._popover_origin = lambda w, h: (max(12, work[2]-w-12), max(12, work[3]-h-12))
        win = detail.create_popover(api)
        card = win.native
        image = QImage(40, 50, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.white)
        card.set_transition_source((work[2]-45, work[3]-55, 40, 50), image, "ac",
                                   source_dpi=1.0, source_work=work)
        card.push_states([("climate.ac", {"state":"cool", "attributes": {
            "temperature":24, "hvac_modes":["off","cool"],
            "fan_modes":["auto","low","medium","high"], "fan_mode":"auto"}})])
        card.open_tile("ac")
        card.progress = 1
        card.show()
        card.enter()
        T.pump(450)
        return win, card

    def test_detail_and_settings_fit_both_dimensions_at_high_zoom(self):
        for zoom in (100, 150, 200):
            win, card = self.make_card(zoom)
            try:
                for settings in (False, True):
                    card.set_edit(settings)
                    T.pump(450)
                    frame = card.transition_frame()
                    self.assertLessEqual(frame.width()*card.scale, 276.01)
                    self.assertLessEqual(frame.height()*card.scale, 376.01)
                    holder = card.page_holder
                    self.assertLessEqual(holder.w, frame.width()+0.01)
                    self.assertLessEqual(holder.h, frame.height()+0.01)
                    self.assertAlmostEqual(card.root.alpha, 1.0)
                    self.assertAlmostEqual(card.detail_radius()/frame.width(), card.t['radius_tile']/detail.CARD_W)
            finally:
                win.dispose()

    def test_long_menu_fits_the_visible_frame_and_survives_new_state(self):
        win, card = self.make_card(150)
        try:
            def find(view):
                return ([view] if isinstance(view, controls.ModeCard) else []) + [v for c in view.children for v in find(c)]
            anchor = find(card.root)[1]
            anchor.show_menu()
            T.pump(40)
            old = card.popup
            before = old.alpha, old.dy, old.zoom
            card.push_states([("climate.ac", {"state":"cool", "attributes": {
                "temperature":24, "hvac_modes":["off","cool"],
                "fan_modes":["auto","low","medium","high"], "fan_mode":"high"}})])
            self.assertEqual((card.popup.alpha,card.popup.dy,card.popup.zoom),before)
            T.pump(350)
            pane = card.popup
            rect = QRectF(pane.x, pane.y, pane.w*pane.scale, pane.h*pane.scale)
            self.assertTrue(card.transition_frame().contains(rect))
            self.assertEqual(pane.current,"high")
            point = rect.center()
            self.assertIsNotNone(card.view_at(point.x(),point.y()))
            image = card.content_image()
            self.assertGreater(image.pixelColor(round(point.x()*card.scale),round(point.y()*card.scale)).alpha(),200)
        finally:
            win.dispose()

    def test_floating_layer_is_not_cut_by_the_cards_rounded_clip(self):
        win, card = self.make_card()
        try:
            frame = card.transition_frame()
            floating = ui.View(0,0,8,8)
            floating.add(ui.Rect(0,0,8,8,"accent_blue",0))
            card.layer.add(floating)
            point = floating.abs_pos()
            self.assertFalse(card.transition_clip().contains(T.ui.QPointF(point[0]+4,point[1]+4)))
            image = card.content_image()
            self.assertGreater(image.pixelColor(round(4*card.scale),round(4*card.scale)).alpha(),200)
        finally:
            win.dispose()
