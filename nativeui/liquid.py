"""The liquid glass lens, without a GPU and without numpy.

The lens refracts the blurred picture of the desktop around the card's edge. Where each pixel of that ring
samples the picture from depends only on the card's shape, never on the
picture, so it is worked out once here and kept as a mesh of small quads; for
every new picture Pillow's C code warps the ring through the mesh. The rest of
the lens (the white line along the rim, the fading opacity) is two more
masks, also made once.

The widget's own tiles blur what is behind them (12 px);
that is done here too, on a quarter-size copy: the picture is smooth already.

All coordinates are device pixels.
"""
import math

from PIL import Image, ImageFilter

WHITE_LINE = 0.16
LENS_OPACITY = 1.0
EXPONENT = 4.0                         # the corners are fourth-power superellipses


def _smoothstep(a, b, x):
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def picture(rgb):
    """The lens's picture from the sharp capture (RGB, window size), as main.py makes it for
    the liquid glass: much more detail than the 1/8 one of the classic glass, or the
    refraction is blurred away. A light blur at half size removes what the quarter-size grid
    cannot represent (fine patterns beat against it into stripes)."""
    w, h = rgb.size
    half = rgb.reduce(2) if not (w % 2 or h % 2) else rgb.resize((max(1, round(w / 2)), max(1, round(h / 2))), Image.BOX)
    return half.filter(ImageFilter.GaussianBlur(0.6))


def _strip_mesh(mesh):
    """Join straight-edge quads with identical sampling into long strips.

    Pillow dispatches each quad through Python on every frame. Along a straight
    edge the field varies only across the edge, so dividing its length into
    two-pixel pieces buys no detail. Keep the curved corners unchanged.
    """
    rest, groups = [], {}
    for box, quad in mesh:
        x0, y0, x1, y1 = box
        a, b, c, d, e, f, g, h = quad
        if a == c == x0 and e == g == x1 and b == h and d == f:
            key = ('h', y0, y1, b, d)
            groups.setdefault(key, []).append((box, quad))
        elif b == h == y0 and d == f == y1 and a == c and e == g:
            key = ('v', x0, x1, a, e)
            groups.setdefault(key, []).append((box, quad))
        else:
            rest.append((box, quad))
    for key, pieces in groups.items():
        horizontal = key[0] == 'h'
        axis = 0 if horizontal else 1
        pieces.sort(key=lambda item: item[0][axis])
        box, quad = pieces[0]
        for next_box, next_quad in pieces[1:]:
            if box[axis + 2] == next_box[axis]:
                box = (box[0], box[1], next_box[2], next_box[3])
                quad = ((quad[0], quad[1], quad[2], quad[3],
                         next_quad[4], next_quad[5], next_quad[6], next_quad[7])
                        if horizontal else
                        (quad[0], quad[1], next_quad[2], next_quad[3],
                         next_quad[4], next_quad[5], quad[6], quad[7]))
            else:
                rest.append((box, quad))
                box, quad = next_box, next_quad
        rest.append((box, quad))
    return rest


class Lens:
    def __init__(self, w, h, radius):
        self.w, self.h = w, h
        self.height = min(46.0, radius * 1.05)          # how far in the lens reaches
        self.amount = min(58.0, self.height * 1.45)     # how far it shifts the sample
        self.radius = min(radius, w / 2, h / 2)
        self._field_cache = {}
        self.mesh = self._build_mesh()
        # QUAD coefficients depend only on shape. Pillow's MESH entry point
        # recomputes them, validates the filter and loads both images for every
        # quad on every frame, under the Python lock shared by all widgets.
        self._compiled_mesh = []
        for box, quad in self.mesh:
            x0, y0, sx, sy, ex, ey, nx, ny = quad
            a, b = 1.0 / (box[2] - box[0]), 1.0 / (box[3] - box[1])
            self._compiled_mesh.append((box, (
                x0, (nx - x0) * a, (sx - x0) * b,
                (ex - sx - nx + x0) * a * b,
                y0, (ny - y0) * a, (sy - y0) * b,
                (ey - sy - ny + y0) * a * b)))
        self.alpha, self.line = self._build_masks()
        self.white = Image.new("RGB", (w, h), (255, 255, 255))
        self._soft = None
        self.tile_masks = {}

    # -- the shader, per point --------------------------------------------
    def _sd(self, x, y):
        """The signed distance to the card's outline (negative inside)."""
        hx, hy = self.w / 2, self.h / 2
        px, py = x - hx, y - hy
        qx, qy = abs(px) - (hx - self.radius), abs(py) - (hy - self.radius)
        ox, oy = max(qx, 0.0), max(qy, 0.0)
        norm = (ox ** EXPONENT + oy ** EXPONENT) ** (1 / EXPONENT)
        return norm - self.radius + min(max(qx, qy), 0.0), px, py

    def _sample_point(self, x, y):
        """Where the pixel at (x, y) takes its colour from."""
        key = (x, y)
        got = self._field_cache.get(key)
        if got is not None:
            return got
        sd, px, py = self._sd(x, y)
        if sd > 0 or -sd >= self.height:
            out = (x, y)
        else:
            t = 1 + sd / self.height
            strength = 1 - math.sqrt(max(0.0, 1 - t * t))
            hx, hy = self.w / 2, self.h / 2
            gr = min(self.radius * 1.5, hx, hy)
            gqx, gqy = abs(px) - (hx - gr), abs(py) - (hy - gr)
            ox, oy = max(gqx, 0.0), max(gqy, 0.0)
            if ox > 0 or oy > 0:
                nx, ny = ox ** (EXPONENT - 1), oy ** (EXPONENT - 1)
                n = math.hypot(nx, ny)
                nx, ny = math.copysign(nx / n, px) if nx else 0.0, math.copysign(ny / n, py) if ny else 0.0
            elif gqx > gqy:
                nx, ny = math.copysign(1.0, px), 0.0
            else:
                nx, ny = 0.0, math.copysign(1.0, py)
            sx = min(max(x - nx * strength * self.amount, 0.5), self.w - 0.5)
            sy = min(max(y - ny * strength * self.amount, 0.5), self.h - 0.5)
            out = (sx, sy)
        self._field_cache[key] = out
        return out

    def _build_mesh(self):
        """[(target box, source quad)] covering the ring. The sampling changes fastest at the
        card's edge, so the quads are 2 px there and grow towards the inside: a mesh of
        equal quads is either coarse at the edge (jagged) or slow (Pillow's cost is per quad)."""
        B, w, h = 8, self.w, self.h
        mesh = []
        for by in range(0, h, B):
            for bx in range(0, w, B):
                bx1, by1 = min(w, bx + B), min(h, by + B)
                depths = [-self._sd(x, y)[0] for x, y in
                          ((bx, by), (bx1, by), (bx, by1), (bx1, by1), ((bx + bx1) / 2, (by + by1) / 2))]
                near = min(depths)
                if near >= self.height + B or max(depths) <= -B:
                    continue                       # deep inside, or outside the card
                c = 2 if near < 6 else 4 if near < 20 else 8
                for y0 in range(by, by1, c):
                    y1 = min(by1, y0 + c)
                    for x0 in range(bx, bx1, c):
                        x1 = min(bx1, x0 + c)
                        mesh.append(((x0, y0, x1, y1), (
                            *self._sample_point(x0, y0), *self._sample_point(x0, y1),
                            *self._sample_point(x1, y1), *self._sample_point(x1, y0))))
        self._field_cache.clear()
        return _strip_mesh(mesh)

    def _build_masks(self):
        """The lens's opacity and the white line along the rim, per pixel."""
        w, h, H = self.w, self.h, self.height
        alpha, line = bytearray(w * h), bytearray(w * h)
        hx, hy = w / 2, h / 2
        for y in range(h):
            row = y * w
            near_y = abs(y + 0.5 - hy) > hy - H - 2
            for x in range(w):
                if not near_y and abs(x + 0.5 - hx) < hx - H - 2:
                    continue
                sd = self._sd(x + 0.5, y + 0.5)[0]
                if sd > 0 or -sd >= H:
                    continue
                inside = -sd
                a = LENS_OPACITY * (1 - _smoothstep(max(0.0, H - 8), H, inside))
                alpha[row + x] = round(255 * a)
                ln = 1 - _smoothstep(0.0, 1.8, abs(inside - 1.4))
                line[row + x] = round(255 * ln * WHITE_LINE)
        return (Image.frombytes("L", (w, h), bytes(alpha)), Image.frombytes("L", (w, h), bytes(line)))

    # -- the picture --------------------------------------------------------
    def _warp(self, sharp):
        """The same Pillow QUAD rasterizer with shape coefficients kept once."""
        sharp.load()
        out = Image.new('RGB', (self.w, self.h))
        out.load()
        transform = getattr(out.im, 'transform', None)
        if transform is None:  # keep working if a future Pillow changes its core API
            return sharp.transform((self.w, self.h), Image.MESH, self.mesh, Image.BILINEAR)
        source = sharp.im
        for box, coefficients in self._compiled_mesh:
            transform(box, source, Image.QUAD, coefficients, Image.BILINEAR, True)
        return out

    def card_mask(self):
        """The card's shape (fourth-power superellipse), anti-aliased."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QImage, QPainter
        from nativeui import render
        img = QImage(self.w, self.h, QImage.Format_Grayscale8)
        img.fill(0)
        q = QPainter(img)
        q.setRenderHint(QPainter.Antialiasing)
        q.setPen(Qt.NoPen)
        q.setBrush(QColor(255, 255, 255))
        q.drawPath(render.squircle(0, 0, self.w, self.h, self.radius))
        q.end()
        return Image.frombuffer("L", (self.w, self.h), bytes(img.constBits()), "raw", "L",
                                img.bytesPerLine(), 1)

    def tile_mask(self, w, h, radius):
        key = (w, h, radius)
        m = self.tile_masks.get(key)
        if m is None:
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QColor, QImage, QPainter
            from nativeui import render
            img = QImage(w, h, QImage.Format_Grayscale8)
            img.fill(0)
            q = QPainter(img)
            q.setRenderHint(QPainter.Antialiasing)
            q.setPen(Qt.NoPen)
            q.setBrush(QColor(255, 255, 255))
            q.drawPath(render.squircle(0, 0, w, h, radius))
            q.end()
            m = self.tile_masks[key] = Image.frombuffer(
                "L", (w, h), bytes(img.constBits()), "raw", "L", img.bytesPerLine(), 1)
        return m

    def frame(self, picture, card_mask, tiles=(), blur=12.0, frost=0.0):
        """The glass for a new picture: `picture` (the small blurred one, RGB)
        stretched over the card, the lens round its edge, and the tiles' own
        blur. Returns an RGBA image the size of the window.

        tiles: [(x, y, w, h, radius)] in device pixels. frost: the blur of the card's glass, in device pixels."""
        sharp = picture.resize((self.w, self.h), Image.BICUBIC)
        base = sharp
        lens = self._warp(sharp)
        lens = Image.composite(self.white, lens, self.line)
        opacity = self.alpha
        # The backdrop is opaque until the card mask is applied. Blend in RGB
        # once rather than allocating two RGBA pictures and alpha-compositing
        # the entire window for every desktop frame.
        out = Image.composite(lens, base, opacity)
        if frost > 0.05:
            out = out.resize(picture.size, Image.BICUBIC).filter(
                ImageFilter.GaussianBlur(frost * picture.width / self.w)).resize(
                    (self.w, self.h), Image.BICUBIC)
        for x, y, w, h, radius in tiles:
            region = out.crop((x, y, x + w, y + h))
            # Blurred at half the size, which costs a quarter as much.
            small = region.reduce(2).filter(ImageFilter.GaussianBlur(blur / 2))
            region = small.resize((w, h), Image.BILINEAR)
            out.paste(region, (x, y), self.tile_mask(w, h, radius))
        out = out.convert("RGBA")
        out.putalpha(card_mask)
        return out
