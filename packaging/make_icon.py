"""Draw the application icon (the one Windows shows in Start, the taskbar
and the installer) into packaging/app.ico.

Not the same drawing as the tray glyph: the notification area wants a
flat monochrome shape that takes the taskbar's colour, while everywhere
else wants something that reads as a product at 32px against whatever is
behind it. Same house, on its own tile.
"""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SIZES = (16, 24, 32, 48, 64, 128, 256)
BG = (64, 156, 255, 255)
FG = (255, 255, 255, 255)
GLYPH = "\ue80f"
FONTS = (r"C:\Windows\Fonts\SegoeIcons.ttf", r"C:\Windows\Fonts\segmdl2.ttf")


def _font(px):
    for path in FONTS:
        try:
            return ImageFont.truetype(path, px)
        except Exception:
            continue
    return None


def render(size):
    # Drawn at 8x and shrunk: the rounded corners and the glyph's strokes
    # both land on fractions of a pixel at these sizes, and a downscale
    # is the cheapest antialiasing there is.
    s = size * 8
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=BG)
    font = _font(int(s * 0.58))
    if font is not None:
        box = d.textbbox((0, 0), GLYPH, font=font)
        d.text(((s - (box[2] - box[0])) / 2 - box[0],
                (s - (box[3] - box[1])) / 2 - box[1]), GLYPH, font=font, fill=FG)
    else:
        w = s / 32.0
        d.line([(7 * w, 16 * w), (16 * w, 8 * w), (25 * w, 16 * w)], fill=FG, width=int(2.4 * w))
        d.line([(10 * w, 15 * w), (10 * w, 25 * w), (22 * w, 25 * w), (22 * w, 15 * w)],
               fill=FG, width=int(2.4 * w))
    return img.resize((size, size), Image.LANCZOS)


def main():
    frames = [render(n) for n in SIZES]
    out = os.path.join(HERE, "app.ico")
    frames[-1].save(out, format="ICO", sizes=[(n, n) for n in SIZES])
    print("wrote", out)


if __name__ == "__main__":
    main()
