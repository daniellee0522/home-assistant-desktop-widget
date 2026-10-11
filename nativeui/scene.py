"""The scene of the natively drawn windows (ui.py's views): one QWidget that paints a tree of views scaled to the screen,
routes the mouse to them, animates them (Tweens), and holds the glass behind them and the floating pane over them."""
import math
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QCursor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter
from PySide6.QtWidgets import QWidget

from . import render
from .glass import GlassMixin
from .animation_clock import FrameTimer
from .ui import (
    CachedView, Ev, Label, Rect, View,
    draw_device_image, font, on_pixels, text_width, ui_tokens)


def _bezier(x1, y1, x2, y2, t):
    """CSS cubic-bezier(x1, y1, x2, y2) at time t."""
    def at(a, b, u):
        return 3 * a * u * (1 - u) ** 2 + 3 * b * u * u * (1 - u) + u ** 3
    lo, hi = 0.0, 1.0
    for _ in range(24):
        mid = (lo + hi) / 2
        if at(x1, x2, mid) < t:
            lo = mid
        else:
            hi = mid
    return at(y1, y2, (lo + hi) / 2)


def _ease(name, t):
    if isinstance(name, tuple):
        return _bezier(*name, t)
    if name == "linear":
        return t
    if name == "in":
        return t * t * t
    if name == "inout":
        return t * t * (3 - 2 * t)
    if name == "back":                      # a pop: a little overshoot
        c1 = 1.70158
        t -= 1
        return 1 + t * t * ((c1 + 1) * t + c1)
    return 1 - (1 - t) ** 3                 # "out" (and "ease")


class Tweens:
    def __init__(self, scene):
        self.scene = scene
        self.running = []
        self.timer = FrameTimer(scene)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)
        self._paused_at = None

    def pause(self):
        if self._paused_at is None:
            self._paused_at = time.monotonic()
        self.timer.stop()
        self.scene.set_animation_active(False)

    def resume(self):
        if self._paused_at is None:
            return
        elapsed = time.monotonic() - self._paused_at
        for tween in self.running:
            tween["t0"] += elapsed
        self._paused_at = None
        if self.running:
            self.scene.set_animation_active(True)
            self.timer.start()

    def animate(self, view, props, ms, ease, done, delay=0):
        # Retarget a spring from its displayed value and velocity.
        velocity = {}
        for t in self.running:
            if t["view"] is view:
                for k in props:
                    if ease == "spring" and t["ease"] == "spring":
                        velocity[k] = t.get("velocity", {}).get(k, 0.0)
                    t["props"].pop(k, None)
        self.running = [t for t in self.running if t["props"]]
        start = {k: getattr(view, k) for k in props}
        if ms <= 0:
            for k, v in props.items():
                setattr(view, k, v)
            self.scene.request_paint()
            if not self.running:
                self.timer.stop()
                self.scene.set_animation_active(False)
            if done:
                done()
            return
        if not self.running and self._paused_at is None:
            self.scene.set_animation_active(True)
            self.scene.prepare_animation()
        now = self._paused_at if self._paused_at is not None else time.monotonic()
        self.running.append({"view": view, "props": dict(props), "start": start, "ms": ms, "ease": ease,
                             "t0": now + delay / 1000, "done": done,
                             "initial_velocity": velocity, "velocity": dict(velocity)})
        screen = self.scene.screen() if hasattr(self.scene, "screen") else None
        rate = screen.refreshRate() if screen is not None else 60
        interval = max(4, min(16, int(1000 / max(60, rate))))
        if self.timer.interval() != interval:
            self.timer.setInterval(interval)
        if self._paused_at is None and not self.timer.isActive():
            self.scene.set_animation_active(True)
            self.timer.start()

    def cancel(self, view):
        self.running = [t for t in self.running if t["view"] is not view]
        if not self.running:
            self.timer.stop()
            self.scene.set_animation_active(False)

    def replace_view(self, old, new):
        """A rebuilt view inherits the current presentation and the original timeline."""
        for tween in self.running:
            if tween["view"] is old:
                for name in tween["props"]:
                    setattr(new, name, getattr(old, name))
                tween["view"] = new

    def tick(self):
        if self._paused_at is not None:
            return
        now = time.monotonic()
        finished = []
        for t in self.running:
            if now < t["t0"]:
                continue
            if t["ease"] == "spring":
                elapsed = now - t["t0"]
                omega = 10 / (t["ms"] / 1000)
                decay = math.exp(-omega * elapsed)
                settled = True
                for name, goal in t["props"].items():
                    offset = t["start"][name] - goal
                    velocity = t["initial_velocity"].get(name, 0.0)
                    c = velocity + omega * offset
                    displacement = (offset + c * elapsed) * decay
                    current_velocity = (velocity - omega * c * elapsed) * decay
                    t["velocity"][name] = current_velocity
                    setattr(t["view"], name, goal + displacement)
                    amplitude = max(1, abs(offset))
                    settled &= abs(displacement) < 0.001 * amplitude and abs(current_velocity) < 0.03 * amplitude
                if settled:
                    for name, goal in t["props"].items():
                        setattr(t["view"], name, goal)
                    finished.append(t)
            else:
                k = min(1.0, (now - t["t0"]) * 1000 / t["ms"])
                e = _ease(t["ease"], k)
                for name, goal in t["props"].items():
                    setattr(t["view"], name, t["start"][name] + (goal - t["start"][name]) * e)
                if k >= 1.0:
                    for name, goal in t["props"].items():
                        setattr(t["view"], name, goal)
                    finished.append(t)
        for t in finished:
            if t in self.running:
                self.running.remove(t)
            if t["done"]:
                t["done"]()
        for t in self.running + finished:
            invalidate = getattr(t["view"],"invalidate_cached_ancestors",None)
            if invalidate:
                invalidate(include_self=False)
        if not self.running:
            self.timer.stop()
            self.scene.set_animation_active(False)
        # only the window's own fade and scale moved: what is drawn in it did not
        self.scene.request_paint(content=any(t["view"] is not self.scene or "progress" in t["props"] for t in self.running + finished),
                                 invalidate=False)


# ---------------------------------------------------------------------------------------
# the window
# ---------------------------------------------------------------------------------------

class Scene(GlassMixin, QWidget):
    """A frameless translucent window holding a tree of views, with glass behind its card."""

    def __init__(self, api, kind):
        super().__init__()
        from winsys import qtshell
        qtshell.ensure_marshal()                # (calls from other threads come to this, the GUI thread)
        self.api, self.kind = api, kind
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.root = CachedView()
        self.root.scene = self
        self.layer = View()               # above the root: menus and the toast
        self.layer.scene = self
        self.popup = None
        self.fields = []
        self.animation_active = False
        self._deferred_animation_glass = False
        self.tweens = Tweens(self)
        self.capture = None
        self.hover_view = None
        self.press_view = None
        self.theme_raw, self.theme, self.style = "auto", "light", "classic"
        self.language, self.liquid_level, self.sampling = "zh-TW", 0, "live"
        self.system_glass = False
        self.zoom_css = 1.0              # this window's own zoom (the card scale)
        self.dpi, self.scale = 1.0, 1.0
        self.pw = self.ph = 1
        self.css_w = self.css_h = 1.0
        self.t = ui_tokens("light")
        self.fade_alpha = 1.0            # the whole window's opacity (entrances and exits)
        self.anim_alpha, self.anim_zoom, self.anim_origin = 1.0, 1.0, (1.0, 1.0)   # the glass and card as one
        self.anim_dy = 0.0
        self.init_glass()
        self._hwnd = 0
        self._paint_pending = False
        self._content, self._content_dirty, self._content_at = None, True, 0.0
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda *_: self._system_theme_changed())

    # -- theme and size ----------------------------------------------------------------------
    def hideEvent(self, event):
        self.tweens.pause()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.tweens.resume()

    def resolve_theme(self):
        theme = self.theme_raw
        if theme == "auto":
            theme = "dark" if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
        return theme

    def _system_theme_changed(self):
        if self.theme_raw == "auto" and self.resolve_theme() != self.theme:
            self.retheme()

    def retheme(self):
        self.theme = self.resolve_theme()
        self.t = ui_tokens(self.theme, self.style)
        render.set_language(self.language)
        for f in self.fields:
            f.restyle()
        self.themed()
        self.request_paint()

    def themed(self):
        """The theme or style changed: rebuild what is made from them."""

    def set_css_size(self, w, h):
        """The card's size in CSS px; the window follows in physical pixels."""
        self.css_w, self.css_h = w, h
        self.root.w, self.root.h = w, h
        self.update_metrics()

    def update_metrics(self):
        hwnd = self.cache_hwnd()
        self.dpi = getattr(self, "metric_dpi", None) or (((_dpi(hwnd) / 96.0) if hwnd else
                                                       (self.devicePixelRatioF() or 1.0)) or 1.0)
        self.scale = self.zoom_css * self.dpi
        self.pw, self.ph = max(1, round(self.css_w * self.scale)), max(1, round(self.css_h * self.scale))
        self.fit_glass()
        for f in self.fields:
            f.restyle()
            f.place()
        self.request_paint()

    def cache_hwnd(self):
        try:
            self._hwnd = int(self.winId())
        except Exception:
            self._hwnd = 0
        return self._hwnd

    _cache_hwnd = cache_hwnd

    # -- glass: the card is the window ----------------------------------------------------------
    def glass_card(self):
        return self.css_w, self.css_h, self.card_radius()

    def card_radius(self):
        return self.t["radius_panel"]

    # -- painting ---------------------------------------------------------------------------------
    def request_paint(self, content=True, invalidate=True):
        """`content`: what is drawn changed (not only the window's own fade or scale)."""
        if content:
            self._content_dirty = True
            if invalidate:
                self.root.invalidate_cached_tree()
                self.layer.invalidate_cached_tree()
        if not self._paint_pending:
            self._paint_pending = True
            QTimer.singleShot(0, self._paint_now)

    def _paint_now(self):
        self._paint_pending = False
        for f in self.fields:
            f.place()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        if self.fade_alpha * self.anim_alpha < 1:
            p.setOpacity(self.fade_alpha * self.anim_alpha)
        p.translate(0, self.anim_dy * self.scale / self.devicePixelRatioF())
        if self.anim_zoom != 1.0:
            ox, oy = self.anim_origin[0] * self.width(), self.anim_origin[1] * self.height()
            p.translate(ox, oy)
            p.scale(self.anim_zoom, self.anim_zoom)
            p.translate(-ox, -oy)
        # The pictures are made in the window's physical pixels and put on exactly those, whatever Qt
        # believes the window's scale to be: just moved to a monitor of another DPI, Qt may not know yet,
        # and a picture placed by its own ratio was drawn shifted and too large or small (and the pointer,
        # which Qt maps by its ratio, missed what it pointed at).
        q = self.devicePixelRatioF() or 1.0
        clip = self.transition_clip()
        p.save()
        if clip is not None:
            transform = p.transform()
            p.scale(self.scale / q, self.scale / q)
            p.setClipPath(clip)
            p.setTransform(transform)
        if self.glass is not None and not self.system_glass:
            p.save()
            p.setOpacity(p.opacity() * self.transition_glass_opacity())
            p.drawImage(QRectF(0, 0, self.glass.width() / q, self.glass.height() / q), self.glass)
            p.restore()
        p.restore()
        # What is on the card is drawn once into a picture and that picture is what is painted: the glass
        # behind it changes up to sixty times a second while the views do not, and drawing them again for
        # each new glass costs a few ms where the picture costs a tenth of one. Coming in or going away
        # also only scales and fades that picture.
        img = self.content_image()
        p.drawImage(QRectF(0, 0, img.width() / q, img.height() / q), img)
        p.end()

    def transition_glass_opacity(self):
        return 1.0

    def transition_clip(self):
        return None

    def popup_bounds(self):
        return QRectF(0, 0, self.css_w, self.css_h)

    def glass_changed(self):
        # A view changed without asking to be drawn again shows at the latest within a quarter second,
        # as it did when every new glass drew the views again.
        if time.monotonic() - self._content_at > 0.25:
            self._content_dirty = True
            self.root.invalidate_cached_tree()
            self.layer.invalidate_cached_tree()
        super().glass_changed()

    def set_animation_active(self, active):
        if self.animation_active == active:
            return
        self.animation_active = active
        if not active:
            if self._deferred_animation_glass:
                self._deferred_animation_glass = False
                self._on_glass()
            self.sample_now.set()

    def prepare_animation(self):
        # Build static artwork before starting the timeline, including panes at
        # zero opacity. The first visible frame then only composites pixels.
        def prepare(view):
            for child in view.children:
                prepare(child)
            if isinstance(view, CachedView) and view.visible and view.w > 0 and view.h > 0:
                view.prepare_cache()
        prepare(self.root)
        prepare(self.layer)

    def _on_glass(self):
        if self.animation_active:
            self.glass_queued.clear()
            self._deferred_animation_glass = True
            return
        super()._on_glass()

    def content_image(self):
        img = self._content
        if img is None or self._content_dirty or img.width() != self.pw or img.height() != self.ph:
            img = QImage(self.pw, self.ph, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            q = QPainter(img)
            q.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
            q.scale(self.scale, self.scale)
            try:
                q.save()
                clip = self.transition_clip()
                if clip is not None:
                    q.setClipPath(clip)
                self.paint_card(q)
                self.root.paint_tree(q)
                q.restore()
                self.layer.paint_tree(q)
            finally:
                q.end()                         # (a painter left open on a picture brings Qt down when it is freed)
            img.setDevicePixelRatio(self.dpi)
            self._content, self._content_dirty, self._content_at = img, False, time.monotonic()
        return img

    def paint_card(self, p):
        """The card's own tint and rims, under everything."""

    def paint_blurred(self, view, p):
        """A view drawn through a blur: the subtree goes to a picture, the picture is blurred."""
        from PIL import Image, ImageFilter
        dev = p.transform().m11()               # device px to one of the parent's
        # what is blurred by r px loses nothing made at 1/(r/2) of the resolution, and costs that squared less
        s = dev / max(1.0, min(4.0, view.blur * dev / 2.5))
        pad = math.ceil(view.blur * 2)
        ox, oy, fx, fy = on_pixels(p, view.x + view.dx - pad, view.y + view.dy - pad)
        fx, fy = fx * s / dev, fy * s / dev
        w, h = math.ceil((view.w + 2 * pad) * s) + 1, math.ceil((view.h + 2 * pad) * s) + 1
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        q = QPainter(img)
        q.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        q.translate(fx, fy)
        q.scale(s, s)
        q.translate(pad - view.x - view.dx, pad - view.y - view.dy)
        saved = view.blur
        view.blur = 0
        view.paint_tree(q)
        view.blur = saved
        q.end()
        pil = Image.frombuffer("RGBA", (w, h), bytes(img.constBits()), "raw", "BGRA", img.bytesPerLine(), 1)
        pil = pil.filter(ImageFilter.GaussianBlur(view.blur * s))
        out = QImage(pil.tobytes("raw", "BGRA"), w, h, QImage.Format_ARGB32_Premultiplied).copy()
        if abs(s - dev) < 1e-3:
            draw_device_image(p, out, ox, oy)
        else:
            p.save()
            p.resetTransform()
            p.drawImage(QRectF(ox, oy, w * dev / s, h * dev / s), out)
            p.restore()

    def paint_faded(self, view, p):
        """A scrolling row whose ends fade out (the capsule rows). Made at the device's resolution and put on
        its pixels: made at the window's own (logical) size and stretched, its words were blurred."""
        s = p.transform().m11()
        ox, oy, fx, fy = on_pixels(p, view.x + view.dx, view.y + view.dy)
        w, h = math.ceil(view.w * s) + 1, math.ceil(view.h * s) + 1
        key = (w, h, s, fx, fy, view.offset, view.extent(), view.fade_px(),
               view.zoom, view.zoom_origin, view.scale, view.blur)
        cached = view._fade_cache
        if cached is not None and cached[0] == key:
            p.save()
            p.setOpacity(p.opacity() * view.alpha)
            p.resetTransform()
            p.drawImage(ox, oy, cached[1])
            p.restore()
            return
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        q = QPainter(img)
        q.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        q.translate(fx, fy)
        q.scale(s, s)
        q.translate(-view.x - view.dx, -view.y - view.dy)
        saved, fade, alpha = view.fade, view.fade_px(), view.alpha
        view.fade, view.alpha = 0, 1.0
        try:
            view.paint_tree(q)
        finally:
            view.fade, view.alpha = saved, alpha
        q.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        edge = min(0.45, fade / max(1.0, view.w if view.horizontal else view.h))
        left = view.offset > 0.5
        right = view.offset < view.max_offset() - 0.5
        q.resetTransform()
        grad = QLinearGradient(0, 0, w if view.horizontal else 0, 0 if view.horizontal else h)
        grad.setColorAt(0, QColor(0, 0, 0, 0 if left else 255))
        grad.setColorAt(edge, QColor(0, 0, 0, 255))
        grad.setColorAt(1 - edge, QColor(0, 0, 0, 255))
        grad.setColorAt(1, QColor(0, 0, 0, 0 if right else 255))
        q.fillRect(0, 0, w, h, QBrush(grad))
        q.end()
        view._fade_cache = (key, img)
        p.save()
        p.setOpacity(p.opacity() * view.alpha)
        p.resetTransform()
        p.drawImage(ox, oy, img)
        p.restore()

    # -- the pointer ----------------------------------------------------------------------------------
    def _css(self, e):
        pos = e.position()
        k = self.devicePixelRatioF() / self.scale
        return pos.x() * k, pos.y() * k - self.anim_dy

    def view_at(self, gx, gy):
        return self.layer.hit(gx, gy) or self.root.hit(gx, gy)

    def _ev(self, view, gx, gy, e):
        lx, ly = view.to_local(gx, gy) if view else (gx, gy)
        return Ev(lx, ly, gx, gy, e.button() if hasattr(e, "button") else Qt.NoButton,
                  e.buttons() if hasattr(e, "buttons") else Qt.NoButton)

    def _bubble(self, view, handler, ev_fn):
        """Offer an event to a view, then its parents, until one handles it."""
        while view is not None:
            fn = getattr(view, handler)
            if fn is not None:
                r = ev_fn(view, fn)
                if r is not False:
                    return view
            view = view.parent
        return None

    def open_popup(self, view):
        self.close_popup()
        self.popup = view
        self.layer.add(view)
        self.request_paint()

    def close_popup(self):
        if self.popup is not None:
            popup, self.popup = self.popup, None
            self.tweens.cancel(popup)
            self.layer.remove(popup)
            if getattr(popup, "on_closed", None):
                popup.on_closed()
            self.request_paint()

    def toast(self, text):
        """A short message at the bottom of the window."""
        f = font(12)
        w = text_width(render.tr(text), f) + 28
        v = Rect((self.css_w - w) / 2, self.css_h - 14 - 30, w, 30, (20, 22, 26, 0.88), "full")
        v.add(Label(text, 12, QFont.Normal, "white", x=14, y=(30 - 12 * 1.2) / 2))
        v.alpha = 0.0
        self.layer.add(v)
        v.animate(250, "out", alpha=1.0)

        def away():
            v.animate(250, "out", alpha=0.0, done=lambda: self.layer.remove(v))
        QTimer.singleShot(2200, away)

    def mousePressEvent(self, e):
        gx, gy = self._css(e)
        target = self.view_at(gx, gy)
        if self.popup is not None:
            inside = target is not None and (target is self.popup or self.popup in set(self._chain(target)))
            if not inside:
                self.close_popup()
                return
        self.press_view = target
        self.press_at = (gx, gy)
        self.press_button = e.button()
        if target is None:
            self.pressed_nothing(gx, gy, e)
            return
        for v in self._chain(target):
            v.pressed = True
        self.request_paint()
        handled = self._bubble(target, "on_press", lambda v, fn: fn(self._ev(v, gx, gy, e)))
        if handled is not None and self.capture is None and handled is not target:
            self.press_view = handled

    def pressed_nothing(self, gx, gy, e):
        """A press that landed on nothing."""

    def _chain(self, view):
        while view is not None:
            yield view
            view = view.parent

    def mouseMoveEvent(self, e):
        gx, gy = self._css(e)
        if e.buttons() and (self.capture or self.press_view):
            owner = self.capture or self.press_view
            if owner.on_move is not None:
                owner.on_move(self._ev(owner, gx, gy, e))
            return
        target = self.view_at(gx, gy)
        if target is not self.hover_view:
            old = self.hover_view
            self.hover_view = target
            for v in self._chain(old):
                if v not in set(self._chain(target)):
                    v.hovered = False
                    if v.on_leave:
                        v.on_leave(Ev(0, 0, gx, gy))
            for v in self._chain(target):
                if not v.hovered:
                    v.hovered = True
                    if v.on_enter:
                        v.on_enter(Ev(0, 0, gx, gy))
            cursor = None
            for v in self._chain(target):
                if v.cursor is not None:
                    cursor = v.cursor
                    break
            self.setCursor(QCursor(cursor) if cursor is not None else QCursor(Qt.ArrowCursor))
            self.request_paint()
        self.hovered_over(target, gx, gy, e)

    def hovered_over(self, target, gx, gy, e):
        """The pointer moved with no button down."""
        v = target
        while v is not None:
            if getattr(v, "hovered_move", None):
                lx, ly = v.to_local(gx, gy)
                v.hovered_move(lx, ly)
                break
            v = v.parent

    def leaveEvent(self, e):
        for v in self._chain(self.hover_view):
            v.hovered = False
            if v.on_leave:
                v.on_leave(Ev(0, 0, 0, 0))
        self.hover_view = None

    def mouseReleaseEvent(self, e):
        gx, gy = self._css(e)
        owner = self.capture or self.press_view
        self.capture = None
        target = self.view_at(gx, gy)
        if owner is not None:
            for v in self._chain(owner):
                v.pressed = False
            if owner.on_release is not None:
                owner.on_release(self._ev(owner, gx, gy, e))
            inside = target is not None and (target is owner or owner in set(self._chain(target)))
            if inside and e.button() in (Qt.LeftButton, Qt.RightButton):
                self._bubble(owner, "on_click", lambda v, fn: fn(self._ev(v, gx, gy, e)))
        self.press_view = None
        self.released(gx, gy, e)
        self.request_paint()

    def released(self, gx, gy, e):
        """A button was let go (after the views had it)."""

    def mouseDoubleClickEvent(self, e):
        gx, gy = self._css(e)
        target = self.view_at(gx, gy)
        self._bubble(target, "on_dblclick", lambda v, fn: fn(self._ev(v, gx, gy, e)))

    def wheelEvent(self, e):
        gx, gy = self._css(e)
        target = self.view_at(gx, gy)
        delta = e.angleDelta().y() or e.angleDelta().x()
        self._bubble(target, "on_wheel", lambda v, fn: fn(self._ev(v, gx, gy, e), delta))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.escape()
        else:
            super().keyPressEvent(e)

    def escape(self):
        """Escape was pressed."""


def _dpi(hwnd):
    import ctypes
    try:
        return ctypes.WinDLL("user32").GetDpiForWindow(ctypes.c_void_p(hwnd))
    except Exception:
        return 96
