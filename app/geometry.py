"""Rules of placement and glass that need no window: where a dragged widget snaps, where a box goes beside its
anchor, how the liquid glass's picture is made, which windows can lie above which."""


# Which of this app's windows can end up on top of which.
# Settings is not listed above the widgets: it paints no glass of its own, so
# nothing needs to see the widgets through it, and a widget under it must keep
# its fast capture path.
WINDOWS_ABOVE = {
    "main": ("flyout", "popover"),
    "flyout": ("popover", "settings"),
    "popover": (),
    "settings": (),
}


def snap_rect(rect, others, areas, threshold, gap):
    """Where to put a widget being dragged to `rect` (left, top, right,
    bottom, physical pixels): magnetised to the edges of the other widgets
    (side by side one gap apart, or flush-aligned) and to the screen edges,
    then pushed clear of anything it still overlaps. Returns (x, y)."""
    left, top, right, bottom = rect
    w, h = right - left, bottom - top
    xs, ys = [], []
    for ol, ot, orr, ob in others:
        beside = top < ob + threshold and bottom > ot - threshold
        stacked = left < orr + threshold and right > ol - threshold
        if beside:
            xs += [orr + gap, ol - gap - w]
        if beside or stacked:
            xs += [ol, orr - w]
            ys += [ot, ob - h]
        if stacked:
            ys += [ob + gap, ot - gap - h]
    for al, at, ar, ab in areas:
        xs += [al + gap, ar - gap - w]
        ys += [at + gap, ab - gap - h]

    def nearest(current, candidates):
        best = min(candidates, key=lambda c: abs(c - current), default=None)
        return best if best is not None and abs(best - current) <= threshold else current

    x, y = nearest(left, xs), nearest(top, ys)
    # Never on top of another widget: step out the shortest way.
    for _ in range(4):
        moved = False
        for ol, ot, orr, ob in others:
            if x < orr and x + w > ol and y < ob and y + h > ot:
                options = [(abs(x - (orr + gap)), (orr + gap, y)),
                           (abs(x + w - (ol - gap)), (ol - gap - w, y)),
                           (abs(y - (ob + gap)), (x, ob + gap)),
                           (abs(y + h - (ot - gap)), (x, ot - gap - h))]
                x, y = min(options, key=lambda o: o[0])[1]
                moved = True
        if not moved:
            break
    # Stepping out of another widget must not take it off the screens: it stays inside the work area its
    # middle is in (or the nearest one), even if that means overlapping.
    if areas:
        cx, cy = x + w / 2, y + h / 2

        def distance(a):
            al, at, ar, ab = a
            return max(al - cx, 0, cx - ar) + max(at - cy, 0, cy - ab)
        al, at, ar, ab = min(areas, key=distance)
        x = max(al, min(x, ar - w))
        y = max(at, min(y, ab - h))
    return int(x), int(y)


def place_against(start, extent, span_start, span_extent, limit_lo, limit_hi):
    """Where to put an `extent`-long box that wants to start at `start`.

    Aligned to the near edge of its anchor, or to the far edge if that would
    run past `limit_hi` (the way a menu flips at the bottom of the screen),
    and finally clamped into view.
    """
    if start + extent <= limit_hi:
        pos = start
    else:
        pos = span_start + span_extent - extent
    return max(limit_lo, min(pos, limit_hi - extent))


def liquid_params(level):
    """How the liquid glass's picture is made for a blur level, 0 (the clearest:
    full window detail) to 1 (a one-third-resolution frosted source):
    (the picture's scale as 1/n, the blur before it is shrunk, the blur after)."""
    level = max(0.0, min(1.0, level))
    return 1 if level <= 0.45 else 2 if level <= 0.85 else 3, 0.3 * level, 0


def is_widget_kind(kind):
    return kind == "main" or (isinstance(kind, str) and kind.startswith("w:"))


def popover_needs_compat(kind, style, excluded, below, owner="main"):
    return (kind == "popover"
            and (owner or "main") in excluded and bool(below))
