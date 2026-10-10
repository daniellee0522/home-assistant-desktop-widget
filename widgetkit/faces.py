"""The surface a widget is drawn on when it is not the program's glass: a solid face like iOS's clock and calendar
(white, or near black in the dark), and a face coloured from a cover (a player)."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient

from nativeui import render


def card_path(th, W, H):
    return render.squircle(0, 0, W, H, th.tokens["radius_panel"])


def solid(p, th, W, H):
    """A solid face with the card's shape and a faint inner edge. Returns (ink, ink2) for what is drawn on it."""
    if th.dim:                                    # standby: clear glass with white ink, as the program's own clock and calendar
        render.draw_card_bg(p, W, H, th.tokens, th.surface, th.name)
        return QColor(255, 255, 255, 235), QColor(255, 255, 255, 150)
    dark = th.name == "dark"
    card = card_path(th, W, H)
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(28, 28, 30) if dark else QColor(255, 255, 255))
    p.drawPath(card)
    p.restore()
    render.inner_shadow(p, card, QColor(255, 255, 255, 30) if dark else QColor(0, 0, 0, 18))
    return (QColor(245, 245, 247), QColor(245, 245, 247, 140)) if dark else (QColor(17, 17, 19), QColor(17, 17, 19, 120))


def tinted(p, th, W, H, base):
    """A face that fades from a lighter to a deeper shade of `base` (the colour of a cover); in standby, clear glass."""
    if th.dim:
        render.draw_card_bg(p, W, H, th.tokens, th.surface, th.name)
        return
    g = QLinearGradient(0, 0, 0, H)
    g.setColorAt(0, base.lighter(118))
    g.setColorAt(1, base.darker(118))
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawPath(card_path(th, W, H))
    p.restore()
