"""Pictures: a QImage (or a path) drawn into a rect, and the cards and collages made of them."""
import os
import threading

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QImageReader, QLinearGradient, QPainter, QPainterPath

from nativeui import render

from .theme import text


_cache = {}
MAX_PIXELS = 100_000_000                 # a picture larger than this is refused (it would take a gigabyte to decode)
SHOW_SIDE = 4096                         # one larger than this is read at a smaller size: no widget is this big


def _read(reader):
    """The picture a QImageReader has, read at a size a widget can use, turned upright by its camera's note; an empty
    one when it is absurdly large or cannot be read."""
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid():
        if size.width() * size.height() > MAX_PIXELS:
            return QImage()
        if max(size.width(), size.height()) > SHOW_SIDE:
            reader.setScaledSize(size.scaled(SHOW_SIDE, SHOW_SIDE, Qt.KeepAspectRatio))
    return reader.read()


def _from_bytes(data):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    ba = QByteArray(data)
    buf = QBuffer(ba)
    buf.open(QIODevice.ReadOnly)
    return _read(QImageReader(buf))


def load(source):
    """A QImage from a path, downloaded bytes or a QImage; an empty one when it cannot be read. Pictures made from a
    path or bytes are kept (a path again when its file changes), so drawing every frame does not decode again."""
    if isinstance(source, QImage):
        return source
    if isinstance(source, (bytes, bytearray)):
        key = ("b", len(source), hash(bytes(source[:64])), hash(bytes(source[-64:])))
        make = lambda: _from_bytes(bytes(source))
    else:
        path = str(source)
        try:
            stamp = os.stat(path).st_mtime_ns
        except OSError:
            return QImage()
        key = ("p", path, stamp)
        make = lambda: _read(QImageReader(path))
    img = _cache.get(key)
    if img is None:
        if len(_cache) >= 48:
            _cache.pop(next(iter(_cache)))
        img = _cache[key] = make()
    return img


# ---- animated pictures (a GIF, an animated WebP)
ANIM_SIDE = 900                          # frames are kept at no more than this many px on a side
ANIM_FRAMES, ANIM_BYTES = 400, 160_000_000
MIN_DELAY = 40                           # ms: a frame is never shown for less (a GIF that asks for 0 gets a tenth of a second)
_anims = {}


class Animation:
    """The frames of an animated picture, decoded on a thread of their own (the first frame is there at once, so the widget
    shows something while the rest comes). `at(ms)` is the frame to show `ms` after it started, and how long until the
    one after; the picture loops. A long or huge animation keeps only the frames that fit (ANIM_FRAMES, ANIM_BYTES)."""

    def __init__(self, path):
        self.path, self.frames, self.done = path, [], False
        threading.Thread(target=self._decode, daemon=True).start()

    def _decode(self):
        try:
            reader = QImageReader(self.path)
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid() and max(size.width(), size.height()) > ANIM_SIDE:
                reader.setScaledSize(size.scaled(ANIM_SIDE, ANIM_SIDE, Qt.KeepAspectRatio))
            spent = 0
            while len(self.frames) < ANIM_FRAMES and spent < ANIM_BYTES:
                img = reader.read()
                if img.isNull():
                    break
                delay = reader.nextImageDelay()                  # (Qt tells a frame's delay once the frame is read)
                spent += img.sizeInBytes()
                self.frames.append((img, max(MIN_DELAY, delay if delay > 0 else 100)))
        finally:
            self.done = True

    @property
    def ready(self):
        return self.done and len(self.frames) > 1

    def at(self, ms):
        frames = list(self.frames)
        if not frames:
            return QImage(), 100
        if not self.done:                                    # still decoding: the first frame, and ask again soon
            return frames[0][0], 100
        total = sum(d for _, d in frames)
        t = ms % total
        for img, delay in frames:
            if t < delay:
                return img, max(MIN_DELAY, int(delay - t))
            t -= delay
        return frames[0]


def animation(source):
    """An `Animation` when `source` (a path) is a picture that moves, else None. Kept, so asking every frame costs nothing."""
    if isinstance(source, QImage) or isinstance(source, (bytes, bytearray)):
        return None
    path = str(source)
    try:
        key = ("a", path, os.stat(path).st_mtime_ns)
    except OSError:
        return None
    if key not in _anims:
        if len(_anims) >= 6:
            _anims.pop(next(iter(_anims)))
        reader = QImageReader(path)
        _anims[key] = Animation(path) if reader.supportsAnimation() and reader.imageCount() != 1 else None
    found = _anims[key]
    return found if found is not None and not (found.done and len(found.frames) < 2) else None


# ---- standby: a picture as white, more or less clear
_mono_cache = {}
STANDBY_INK = QColor(255, 255, 255)        # the one colour of a picture in standby (the program's design: white, never another)


def _key(source):
    if isinstance(source, QImage):
        return ("i", source.cacheKey())
    if isinstance(source, (bytes, bytearray)):
        return ("b", len(source), hash(bytes(source[:64])), hash(bytes(source[-64:])))
    try:
        return ("p", str(source), os.stat(str(source)).st_mtime_ns)
    except OSError:
        return ("p", str(source), 0)


def monochrome(source, mode="luminance", contrast=1.0, invert=False):
    """`source` as a white picture that is clear where the original is dark or clear, for standby, when the widget lies on
    the program's clear glass and colour would fight it. The colour is always white (the program's design); what varies
    is how much of it is there:

      mode="luminance"  brightness decides: bright parts are white, dark parts clear (a photograph, a cover)
      mode="alpha"      the picture's own transparency decides, colours ignored (a logo, an icon with a clear background)

    `contrast` (1.0 = as it is; above 1 pushes mid-greys apart, below 1 flattens them) and `invert` (dark becomes white)
    shape the luminance. Returns a new QImage the size of the original; an empty one for an empty source. Kept, so asking
    every frame costs nothing after the first."""
    if mode not in ("luminance", "alpha"):
        raise ValueError("mode is \"luminance\" or \"alpha\", not %r" % (mode,))
    key = (_key(source), mode, round(float(contrast), 3), bool(invert))
    out = _mono_cache.get(key)
    if out is not None:
        return out
    src = load(source)
    if src.isNull():
        return QImage()
    src = src.convertToFormat(QImage.Format_ARGB32)
    w, h = src.width(), src.height()
    own = src.convertToFormat(QImage.Format_Alpha8)                       # the picture's own transparency, 8 bits
    if mode == "alpha":
        shape = own
    else:
        gray = src.convertToFormat(QImage.Format_Grayscale8)
        idx = QImage(bytes(gray.constBits()), w, h, gray.bytesPerLine(), QImage.Format_Indexed8)
        table = []
        for v in range(256):
            x = v / 255.0
            x = (x - 0.5) * float(contrast) + 0.5
            x = 1.0 - x if invert else x
            g = round(255 * max(0.0, min(1.0, x)))
            table.append((255 << 24) | (g << 16) | (g << 8) | g)
        idx.setColorTable(table)                                            # the curve: a table of 256 greys
        lum = idx.convertToFormat(QImage.Format_Grayscale8)
        shape = QImage(bytes(lum.constBits()), w, h, lum.bytesPerLine(), QImage.Format_Alpha8).copy()
    result = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    result.fill(STANDBY_INK)
    result.setAlphaChannel(shape)
    if mode == "luminance":                                                 # where the picture itself is clear, so is this
        keep = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        keep.fill(STANDBY_INK)
        keep.setAlphaChannel(own)
        q = QPainter(result)
        q.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        q.drawImage(0, 0, keep)
        q.end()
    if len(_mono_cache) >= 24:
        _mono_cache.pop(next(iter(_mono_cache)))
    _mono_cache[key] = result
    return result


def _source_rect(img, rect, fit):
    iw, ih = img.width(), img.height()
    if fit == "fill":
        return QRectF(0, 0, iw, ih), QRectF(rect)
    k = (max if fit == "cover" else min)(rect.width() / iw, rect.height() / ih)
    w, h = iw * k, ih * k
    target = QRectF(rect.center().x() - w / 2, rect.center().y() - h / 2, w, h)
    return QRectF(0, 0, iw, ih), target


def picture(p, source, rect, fit="cover", radius=0.0, squircle=True, mono=False, mono_mode="luminance", contrast=1.0,
            invert=False):
    """`source` in `rect`. fit: "cover" (fills, cuts the overflow), "contain" (all of it), "fill" (stretched).
    Corners round by `radius` as the program's shapes do. `mono=True` draws it as in standby: white, clear where it is dark
    (see `monochrome`); pass `mono=th.dim` and the picture follows the program into standby by itself."""
    img = monochrome(source, mono_mode, contrast, invert) if mono else load(source)
    p.save()
    if radius:
        clip = (render.squircle(rect.x(), rect.y(), rect.width(), rect.height(), radius) if squircle
                else QPainterPath())
        if not squircle:
            clip.addRoundedRect(rect, radius, radius)
        p.setClipPath(clip, Qt.IntersectClip)
    else:
        p.setClipRect(rect, Qt.IntersectClip)
    if img.isNull():
        p.fillRect(rect, QColor(128, 136, 150, 90))
    else:
        src, dst = _source_rect(img, rect, fit)
        p.drawImage(dst, img, src)
    p.restore()


_hues = {}


def dominant_color(source):
    """A card colour from a cover, as Apple Music takes it: the hue most of the picture's coloured part has (not the
    average of everything, which turns muddy), made deep enough for white words; a grey cover gives a grey card; no
    cover gives Music's red."""
    img = load(source) if source is not None else QImage()
    if img.isNull():
        return QColor("#e8344e")
    key = img.cacheKey()
    if key in _hues:
        return _hues[key]
    small = img.scaled(24, 24, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    bins, grey, weight = [0.0] * 24, 0.0, 0.0
    sums = [[0.0, 0.0, 0.0] for _ in range(24)]
    for y in range(small.height()):
        for x in range(small.width()):
            h, s, v, _ = small.pixelColor(x, y).getHsvF()
            weight += 1
            if s < 0.18 or v < 0.12 or h < 0:
                grey += v
                continue
            b = int(h * 24) % 24
            w = s * v
            bins[b] += w
            sums[b][0] += h * w
            sums[b][1] += s * w
            sums[b][2] += v * w
    best = max(range(24), key=lambda b: bins[b])
    if bins[best] < 0.06 * weight:
        color = QColor.fromHsvF(0.0, 0.0, min(0.42, max(0.22, grey / max(1.0, weight) * 0.6)))
    else:
        w = bins[best]
        h, s, v = (sums[best][0] / w, sums[best][1] / w, sums[best][2] / w)
        color = QColor.fromHsvF(h, min(0.9, max(0.45, s)), min(0.62, max(0.38, v * 0.8)))
    if len(_hues) > 32:
        _hues.clear()
    _hues[key] = color
    return color


def shade(p, rect, strength=0.55, from_bottom=True):
    """A dark fade over the lower part of a picture, to stand words on."""
    g = QLinearGradient(0, rect.bottom() if from_bottom else rect.top(), 0, rect.center().y())
    g.setColorAt(0, QColor(0, 0, 0, round(255 * strength)))
    g.setColorAt(1, QColor(0, 0, 0, 0))
    p.fillRect(rect, g)


def caption_card(p, th, source, rect, title, subtitle="", radius=34, mono=False):
    """A picture with its title over a shade at the foot (an album cover, a memory). `mono=th.dim` for standby."""
    picture(p, source, rect, "cover", radius, mono=mono)
    p.save()
    p.setClipPath(render.squircle(rect.x(), rect.y(), rect.width(), rect.height(), radius))
    shade(p, rect)
    p.restore()
    white = QColor(255, 255, 255)
    text(p, th, "headline", title, rect.left() + 18, rect.bottom() - (52 if subtitle else 34), rect.width() - 36,
         color=white)
    if subtitle:
        text(p, th, "caption", subtitle, rect.left() + 18, rect.bottom() - 26, rect.width() - 36,
             color=QColor(255, 255, 255, 215))


def collage(p, sources, rect, gap=6, radius=18):
    """One large picture and up to two beside it."""
    big = QRectF(rect.left(), rect.top(), rect.width() * 0.58 - gap / 2, rect.height())
    side_w = rect.width() - big.width() - gap
    picture(p, sources[0], big, "cover", radius)
    rest = sources[1:3]
    h = (rect.height() - gap * (len(rest) - 1)) / max(1, len(rest))
    for i, s in enumerate(rest):
        picture(p, s, QRectF(big.right() + gap, rect.top() + i * (h + gap), side_w, h), "cover", radius)


def sample_image(kind=0, w=480, h=360):
    """A made-up photograph (a sky, a hill, a sun) so that the kit can be seen with no files."""
    palettes = [("#ff9a76", "#ffd29d", "#5b4b8a"), ("#4facfe", "#b8e1ff", "#1f6f54"),
                ("#2b1b4b", "#8a4f9e", "#0d1b2a"), ("#ffd86f", "#fc6262", "#35523a")]
    top, bottom, ground = palettes[kind % len(palettes)]
    from PySide6.QtGui import QPainter
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    q = QPainter(img)
    q.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, 0, h)
    g.setColorAt(0, QColor(top))
    g.setColorAt(1, QColor(bottom))
    q.fillRect(0, 0, w, h, g)
    q.setPen(Qt.NoPen)
    q.setBrush(QColor(255, 255, 255, 235))
    q.drawEllipse(w * (0.25 + 0.15 * kind % 3 / 3), h * 0.22, h * 0.2, h * 0.2)
    hill = QPainterPath()
    hill.moveTo(0, h * 0.78)
    hill.cubicTo(w * 0.3, h * 0.55, w * 0.6, h * 0.95, w, h * 0.65)
    hill.lineTo(w, h)
    hill.lineTo(0, h)
    hill.closeSubpath()
    q.setBrush(QColor(ground))
    q.drawPath(hill)
    q.end()
    return img
