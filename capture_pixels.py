"""Exact desktop noise detection with a cheap changed-frame fast path."""
from PIL import ImageChops
from PIL import Image, ImageFilter
import math


def within_noise_bgrx(previous, current, size, threshold, pre_blur=0):
    if len(previous) != len(current):
        return False
    if previous == current:
        return True
    w, h = size
    if len(current) != w * h * 4:
        return False
    limit = threshold
    radius = 0
    if pre_blur:
        from nativeui.gpu_glass import box_parameters
        radius, center, far = box_parameters(pre_blur)
        # Bound each of six rounded box passes. If a raw pixel differs by
        # more than both pictures' possible filter change, the filtered pixel
        # must still exceed the noise threshold. Otherwise compare exactly.
        delta = 6 * math.ceil(255 * (1 - center / 16777216) + .5)
        limit += 2 * delta
    xs = (0, w // 2, w - 1)
    ys = (0, h // 2, h - 1)
    for y in ys:
        for x in xs:
            start = (y * w + x) * 4
            if any(abs(previous[start + c] - current[start + c]) > limit for c in range(3)):
                return False
    # The whole-picture difference runs in native code over the shared bytes;
    # the unused fourth byte is dropped by the RGB conversion.
    diff = ImageChops.difference(Image.frombuffer('RGBA', size, previous, 'raw', 'RGBA', 0, 1),
                                 Image.frombuffer('RGBA', size, current, 'raw', 'RGBA', 0, 1)
                                 ).convert('RGB')
    if max(hi for _, hi in diff.getextrema()) > limit:
        return False
    if not pre_blur:
        return True
    # Only the neighbourhood of changed pixels can differ once filtered, so
    # the exact comparison filters that crop instead of both whole pictures.
    changed = diff.getbbox()
    if changed is None:
        return True
    pad = 3 * (radius + 1) + 2
    box = (max(0, changed[0] - pad), max(0, changed[1] - pad),
           min(w, changed[2] + pad), min(h, changed[3] + pad))
    old = Image.frombytes('RGB', size, previous, 'raw', 'BGRX').crop(box)
    new = Image.frombytes('RGB', size, current, 'raw', 'BGRX').crop(box)
    old = old.filter(ImageFilter.GaussianBlur(pre_blur))
    new = new.filter(ImageFilter.GaussianBlur(pre_blur))
    return within_noise(old, new, threshold)


def within_noise(previous, current, threshold):
    if previous.size != current.size:
        return False
    w, h = current.size
    old, new = previous.load(), current.load()
    # A single differing pixel proves the frame changed. Sampling only decides
    # whether to skip the expensive comparison, never whether to freeze glass.
    for y in (0, h // 2, h - 1):
        for x in (0, w // 2, w - 1):
            if any(abs(a - b) > threshold for a, b in zip(old[x, y], new[x, y])):
                return False
    return max(hi for _, hi in ImageChops.difference(previous, current).getextrema()) <= threshold
