"""Pictures of this program's own windows laid over a capture of the screen (a widget under the detail card, the
windows under the panel), and a clean picture patched in where another program's window lies over a widget."""

from winsys.win32 import get_hwnd, window_rect


def grab_widget_rgba(window):
    """Capture the Qt widget with its transparent corner alpha intact."""
    if not window:
        return None

    def grab():
        from PySide6.QtGui import QImage
        snapshot = getattr(window.native,"backdrop_image",None)
        image = (snapshot() if snapshot else window.native.grab().toImage()).convertToFormat(QImage.Format_RGBA8888)
        if image.isNull():
            return None
        r = window_rect(get_hwnd(window))
        if not r:
            return None
        from PIL import Image
        rgba = Image.frombytes('RGBA', (image.width(), image.height()),
                               image.bits().tobytes(), 'raw', 'RGBA',
                               image.bytesPerLine(), 1)
        size = (r[2] - r[0], r[3] - r[1])
        if rgba.size != size:
            rgba = rgba.resize(size, Image.Resampling.BILINEAR)
        return rgba, r

    try:
        return window.run_on_ui_thread(grab)
    except Exception:
        return None


def composite_rgba_window(base_bgra, size, layer, offset):
    """Place a translucent window over a BGRA backdrop without black corners."""
    from PIL import Image
    # GDI's fourth byte is often zero even for an opaque desktop bitmap.
    # Treat the backdrop as opaque before applying the Qt window's alpha.
    base = Image.frombytes('RGBA', size, base_bgra, 'raw', 'BGRA').convert('RGB').convert('RGBA')
    left, top = max(0, offset[0]), max(0, offset[1])
    right = min(size[0], offset[0] + layer.width)
    bottom = min(size[1], offset[1] + layer.height)
    if right > left and bottom > top:
        clipped = layer.crop((left - offset[0], top - offset[1],
                              right - offset[0], bottom - offset[1]))
        base.alpha_composite(clipped, (left, top))
    return base.tobytes('raw', 'BGRA')


def compose_popover_backdrop(screen_bgra, popover_rect, main_frame, widget):
    """Restore pixels hidden by capture affinity, then blend the Qt widget."""
    from PIL import Image
    x, y, w, h = popover_rect
    mx, my, mw, mh, main_bgra = main_frame
    if callable(main_bgra):              # a widget drawn on the GPU hands over its picture only now
        main_bgra = main_bgra()
        if not main_bgra or len(main_bgra) != mw * mh * 4:
            return None
    image, rect = widget
    if (abs(mx - rect[0]) > 3 or abs(my - rect[1]) > 3 or
            abs(mw - (rect[2] - rect[0])) > 3 or
            abs(mh - (rect[3] - rect[1])) > 3):
        return None
    left, top = max(x, mx), max(y, my)
    right, bottom = min(x + w, mx + mw), min(y + h, my + mh)
    if right <= left or bottom <= top:
        return screen_bgra
    base = Image.frombytes('RGBA', (w, h), screen_bgra, 'raw', 'BGRA').convert('RGB')
    main = Image.frombytes('RGBA', (mw, mh), main_bgra, 'raw', 'BGRA').convert('RGB')
    base.paste(main.crop((left - mx, top - my, right - mx, bottom - my)),
               (left - x, top - y))
    return composite_rgba_window(base.convert('RGBA').tobytes('raw', 'BGRA'),
                                  (w, h), image, (rect[0] - x, rect[1] - y))


def patch_covered(raw, rect, covers, clean):
    """`raw` (BGRA of `rect`, (x, y, w, h)) with the parts under `covers` taken from `clean`, a picture of
    the same place with nothing over it."""
    from PIL import Image
    x, y, w, h = rect
    img = Image.frombytes("RGBA", (w, h), raw)
    base = Image.frombuffer("RGBA", (w, h), clean, "raw", "RGBA", 0, 1)
    for l, t, r, b in covers:
        box = (max(0, l - x), max(0, t - y), min(w, r - x), min(h, b - y))
        if box[2] > box[0] and box[3] > box[1]:
            img.paste(base.crop(box), box[:2])
    return img.tobytes()
