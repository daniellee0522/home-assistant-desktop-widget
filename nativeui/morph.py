"""The tile-to-card morph, after the Home app on the Mac: the tile itself grows into the card.

The frame (the card's background and glass) moves from the tile's rectangle to the card's, and the tile's own picture
and the card cross-fade in the first half. The card's central control comes out of the tile's icon (paint_hero, below).
Everything else on the card (the words, the small buttons, the mode menus) stands at its own place from the start, as
the Mac's does (a picture of small words and buttons scaled at every frame shimmers), and comes into sight as the card
reaches it: seen through the frame with a soft edge (paint_revealed), and faded in on an eased curve. Closing is the same path backwards, quicker, as the Mac's is. The tray panel's
detail (panel_detail.py) and a desktop widget's card (detail.py) both use these rules.
"""

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QTransform

OPEN_MS = 340
CLOSE_MS = 280
TILE_FADE = 0.45            # the tile's picture is gone by this far along
CARD_FADE = 0.55            # the card is all there by this far along
LANDED = 0.03               # a closing card is back in its tile this near the end (the spring settles long after)
FEATHER = 40.0              # px past the frame's edge over which what is on the card fades out of sight
FEATHER_STEPS = 12
MASK_SHRINK = 4


def progress(t):
    return max(0.0, min(1.0, t))


def frame(source, target, t):
    """The rectangle the morph shows at t (0 the tile, 1 the card)."""
    t = progress(t)
    return QRectF(source.x() + (target.x() - source.x()) * t,
                  source.y() + (target.y() - source.y()) * t,
                  source.width() + (target.width() - source.width()) * t,
                  source.height() + (target.height() - source.height()) * t)


def tile_alpha(t):
    return max(0.0, 1.0 - progress(t) / TILE_FADE)


def card_alpha(t):
    return min(1.0, progress(t) / CARD_FADE)


def content_alpha(t):
    """What is on the card (but its control) fades in on an eased curve, over the card's own fade."""
    u = min(1.0, progress(t) / CARD_FADE)
    return u * u * (3 - 2 * u)


def paint_revealed(p, shown, radius, bounds, draw):
    """`draw(painter)`, what is on the card in `bounds`, seen in the frame `shown` and fading out over FEATHER past its
    edge: a word or a button comes into sight as the card reaches it, neither cut on a hard line nor floating ahead."""
    from .render import squircle
    world = p.transform()
    seen = bounds.intersected(shown.adjusted(-FEATHER, -FEATHER, FEATHER, FEATHER))    # nothing past it shows
    area = world.mapRect(seen).toAlignedRect().intersected(QRect(0, 0, p.device().width(), p.device().height()))
    if area.isEmpty():
        return
    local = world * QTransform.fromTranslate(-area.x(), -area.y())
    layer = QImage(area.size(), QImage.Format_ARGB32_Premultiplied)
    layer.fill(Qt.transparent)
    q = QPainter(layer)
    q.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
    q.setTransform(local)
    q.setOpacity(p.opacity())
    draw(q)
    # the soft edge is a smooth ramp: made at a quarter of the size and drawn larger
    small = QImage(max(1, area.width() // MASK_SHRINK + 1), max(1, area.height() // MASK_SHRINK + 1),
                   QImage.Format_ARGB32_Premultiplied)
    small.fill(Qt.transparent)
    m = QPainter(small)
    m.setRenderHint(QPainter.Antialiasing)
    m.setTransform(local * QTransform.fromScale(1 / MASK_SHRINK, 1 / MASK_SHRINK))
    m.setCompositionMode(QPainter.CompositionMode_Plus)    # the rings add up: a ramp from the edge outwards
    m.setPen(Qt.NoPen)
    m.setBrush(QColor(0, 0, 0, -(-255 // FEATHER_STEPS)))
    for i in range(FEATHER_STEPS):
        e = FEATHER * (i + 0.5) / FEATHER_STEPS
        m.drawPath(squircle(shown.x() - e, shown.y() - e, shown.width() + 2 * e, shown.height() + 2 * e, radius + e))
    m.end()
    q.resetTransform()
    q.setOpacity(1.0)
    q.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    q.drawImage(QRectF(0, 0, small.width() * MASK_SHRINK, small.height() * MASK_SHRINK), small)
    q.end()
    p.save()
    p.resetTransform()
    p.setOpacity(1.0)
    p.drawImage(area.topLeft(), layer)
    p.restore()


def radius(tile_radius, card_radius, t):
    t = progress(t)
    return tile_radius * (1 - t) + card_radius * t


# -- the tile's icon becomes the card's control --------------------------------------------------------------------
# On the Mac the lamp's icon goes into its slider while the slider shrinks into the tile. A card's central control (a
# view whose class says `hero`: the tall slider, the switch, the dial) is taken out of the card's picture and carried on
# its own from the tile's icon to its place; the tile's icon rides on it and fades into it in the first half.
ICON_FADE = 0.5             # the tile's icon is gone by this far along
HERO_FADE = 0.35            # the control is all there by this far along


def hero_of(view):
    """The card's central control, or None."""
    if getattr(type(view), "hero", False) and (view.visible or getattr(view, "lifted_by_morph", False)):
        return view
    for child in view.children:
        found = hero_of(child)
        if found is not None:
            return found
    return None


def lift(view, lifted):
    """Take the control out of the card's picture while it is carried (and put it back)."""
    if getattr(view, "lifted_by_morph", False) != lifted:
        view.lifted_by_morph = lifted
        view.visible = not lifted
        view.invalidate_cached_ancestors()


def carry(holder, t):
    """Before the card's content is painted: its control is out of it while it is carried, back when it lands."""
    control = hero_of(holder)
    if control is not None:
        lift(control, progress(t) < 1)


def lerp_rect(a, b, t):
    return QRectF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t,
                  a.width() + (b.width() - a.width()) * t, a.height() + (b.height() - a.height()) * t)


def paint_hero(p, holder, t, icon_rect, draw_icon):
    """The card's control (found in `holder`) between the tile's icon (`icon_rect`, t 0) and its own place (t 1), and the
    tile's icon on it (`draw_icon(p, rect)`)."""
    control = hero_of(holder)
    t = progress(t)
    if control is None or t >= 1:
        return
    x, y, k = control.in_scene()
    there = QRectF(x, y, control.w * k, control.h * k)
    rect = lerp_rect(icon_rect, there, t)
    opacity = p.opacity()
    fit = min(rect.width() / control.w, rect.height() / control.h)
    p.save()
    p.setOpacity(opacity * min(1.0, t / HERO_FADE))
    p.translate(rect.center().x() - control.w * fit / 2, rect.center().y() - control.h * fit / 2)
    p.scale(fit, fit)
    saved = control.x, control.y, control.dx, control.dy, control.zoom, control.alpha
    control.x = control.y = control.dx = control.dy = 0.0
    control.zoom, control.alpha, control.visible = 1.0, 1.0, True
    try:
        control.paint_tree(p)
    finally:
        control.x, control.y, control.dx, control.dy, control.zoom, control.alpha = saved
        control.visible = False
    p.restore()
    alpha = max(0.0, 1.0 - t / ICON_FADE)
    if alpha > 0:
        side = min(icon_rect.width() * (1 + t), max(icon_rect.width(), min(rect.width(), rect.height())))
        icon = QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)
        p.save()
        p.setOpacity(opacity * alpha)
        draw_icon(p, icon)
        p.restore()


def without_icon(image, tile, icon_rect):
    """The tile's picture with its icon painted over in the tile's own colour (taken just beside it), so that the icon
    is seen once, on the control, while the picture fades. `tile` and `icon_rect` are where the picture and the icon
    are, in the same units."""
    if image is None or image.isNull() or tile.width() <= 0 or tile.height() <= 0:
        return image
    fx, fy = image.width() / tile.width(), image.height() / tile.height()
    box = QRectF((icon_rect.x() - tile.x()) * fx, (icon_rect.y() - tile.y()) * fy,
                 icon_rect.width() * fx, icon_rect.height() * fy).adjusted(-2, -2, 2, 2)
    wide = icon_rect.width() > tile.width() / 3          # a long tile's disc: its colour is above it
    sx = round(box.center().x() if wide else min(image.width() - 1, box.right() + 3))
    sy = round(max(0, box.top() - 3) if wide else box.top() + 3)
    if not (0 <= sx < image.width() and 0 <= sy < image.height()):
        return image
    clean = image.copy()
    ratio = clean.devicePixelRatio()
    clean.setDevicePixelRatio(1.0)                         # painted in the picture's own pixels, as measured
    painter = QPainter(clean)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setCompositionMode(QPainter.CompositionMode_Source)
    painter.setPen(Qt.NoPen)
    painter.setBrush(image.pixelColor(sx, sy))
    painter.drawRoundedRect(box, box.width() / 4, box.height() / 4)
    painter.end()
    clean.setDevicePixelRatio(ratio)
    return clean
