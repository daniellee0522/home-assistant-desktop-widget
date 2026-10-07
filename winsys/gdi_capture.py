"""Screen and wallpaper capture into reusable GDI bitmaps (the compatibility path of the glass).
Run in a worker process of its own (capture_worker.py), since PrintWindow can block on an unresponsive window."""

import ctypes
import threading

from winsys.win32 import (
    BITMAPINFOHEADER, BLACKNESS, covers, ENUM_WINDOWS_PROC, gdi32, PW_RENDERFULLCONTENT, SM_CXVIRTUALSCREEN,
    SM_CYVIRTUALSCREEN, SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SRCCOPY, user32, window_rect)


class DesktopCapture:
    """Screen and wallpaper capture into reusable GDI bitmaps.

    grab_screen reads the composed screen (fast; the caller's windows must
    be excluded from capture). grab renders the wallpaper with
    PrintWindow(PW_RENDERFULLCONTENT) instead, which also catches animated
    wallpaper drawn into the desktop window.

    PrintWindow always draws at the destination's origin and ignores DC
    transforms, so a whole surface is rendered and the wanted rectangle
    blitted out of it. Progman spans the entire virtual desktop, so
    _pick_surface looks for the smallest descendant that covers the target
    and renders the same picture, falling back to Progman itself.
    """

    # Mean absolute difference per byte below which a candidate surface
    # agrees with Progman. Animated wallpaper moves between the two renders;
    # a wrong region scores several times this.
    _AGREE_THRESHOLD = 28

    def __init__(self):
        self._lock = threading.Lock()
        self._dc = None
        self._bmp = None
        self._size = (0, 0)
        self._out_dc = None
        self._out_bmp = None
        self._out_size = (0, 0)
        # Separate scratch for windows drawn over the desktop, so it never
        # forces the monitor-sized surface bitmap to be reallocated.
        self._ov_dc = None
        self._ov_bmp = None
        self._ov_size = (0, 0)
        # (hwnd, x, y, w, h) of the surface we render
        self._surface = None
        self._original_bitmaps = {}

    # -- scratch surfaces ------------------------------------------------

    def _ensure(self, attr_dc, attr_bmp, attr_size, w, h):
        if getattr(self, attr_dc) and getattr(self, attr_size) == (w, h):
            return True
        self._release(attr_dc, attr_bmp)
        setattr(self, attr_size, (0, 0))
        screen_dc = user32.GetDC(None)
        if not screen_dc:
            return False
        try:
            dc = gdi32.CreateCompatibleDC(screen_dc)
            bmp = gdi32.CreateCompatibleBitmap(screen_dc, w, h)
            if not dc or not bmp:
                if bmp:
                    gdi32.DeleteObject(bmp)
                if dc:
                    gdi32.DeleteDC(dc)
                return False
            original = gdi32.SelectObject(dc, bmp)
            if not original or original == ctypes.c_void_p(-1).value:
                gdi32.DeleteObject(bmp)
                gdi32.DeleteDC(dc)
                return False
            self._original_bitmaps[attr_dc] = original
            setattr(self, attr_dc, dc)
            setattr(self, attr_bmp, bmp)
            setattr(self, attr_size, (w, h))
            return True
        finally:
            user32.ReleaseDC(None, screen_dc)

    def _release(self, attr_dc, attr_bmp):
        dc, bmp = getattr(self, attr_dc), getattr(self, attr_bmp)
        original = self._original_bitmaps.pop(attr_dc, None)
        if dc and original:
            gdi32.SelectObject(dc, original)
        if bmp:
            gdi32.DeleteObject(bmp)
        if dc:
            gdi32.DeleteDC(dc)
        setattr(self, attr_dc, None)
        setattr(self, attr_bmp, None)

    # -- choosing which surface to render --------------------------------

    def _candidates(self, x, y, w, h):
        """Visible descendants of Progman that fully cover the rect,
        smallest first, with Progman itself last as the fallback."""
        progman = user32.FindWindowW("Progman", None)
        if not progman:
            return []
        found = []

        def visit(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return 1
            r = window_rect(hwnd)
            if r and covers(r, x, y, w, h):
                found.append((hwnd, r[0], r[1], r[2] - r[0], r[3] - r[1]))
            return 1

        try:
            user32.EnumChildWindows(progman, ENUM_WINDOWS_PROC(visit), None)
        except Exception:
            found = []
        found.sort(key=lambda c: c[3] * c[4])
        r = window_rect(progman) or (0, 0, 0, 0)
        found.append((progman, r[0], r[1], r[2] - r[0], r[3] - r[1]))
        return found

    def _render(self, surface, x, y, w, h):
        """Render `surface` and return the requested rect as BGRA, or None."""
        hwnd, sx, sy, sw, sh = surface
        if not self._ensure("_dc", "_bmp", "_size", sw, sh):
            return None
        if not user32.PrintWindow(hwnd, self._dc, PW_RENDERFULLCONTENT):
            return None
        if not self._ensure("_out_dc", "_out_bmp", "_out_size", w, h):
            return None
        if not gdi32.PatBlt(self._out_dc, 0, 0, w, h, BLACKNESS):
            return None
        if not gdi32.BitBlt(self._out_dc, 0, 0, w, h,
                             self._dc, x - sx, y - sy, SRCCOPY):
            return None
        return self._read_out(w, h)

    @staticmethod
    def _disagreement(a, b):
        # Sampled: this only has to tell "the same view, a moment apart"
        # from "somewhere else entirely".
        step = max(4, (len(a) // 4096) * 4)
        n = total = 0
        for i in range(0, min(len(a), len(b)), step):
            total += abs(a[i] - b[i])
            n += 1
        return (total / n) if n else 999

    def _pick_surface(self, x, y, w, h):
        # Cached until it stops covering the target (the widget moved to
        # another monitor); re-picking renders every candidate.
        if self._surface:
            hwnd = self._surface[0]
            r = window_rect(hwnd) if user32.IsWindowVisible(hwnd) else None
            if r and covers(r, x, y, w, h):
                return (hwnd, r[0], r[1], r[2] - r[0], r[3] - r[1])
            self._surface = None
        cands = self._candidates(x, y, w, h)
        if not cands:
            return None
        reference = self._render(cands[-1], x, y, w, h)      # Progman
        chosen = cands[-1]
        if reference:
            for cand in cands[:-1]:
                shot = self._render(cand, x, y, w, h)
                if shot and self._disagreement(shot, reference) <= self._AGREE_THRESHOLD:
                    chosen = cand
                    break
        self._surface = chosen
        return chosen

    def reset(self):
        """Throw away every cached DC, bitmap and surface choice.

        They belong to the display configuration they were made for, which
        routinely changes across a suspend. The next capture rebuilds them.
        """
        with self._lock:
            for dc, bmp in (("_dc", "_bmp"), ("_out_dc", "_out_bmp"), ("_ov_dc", "_ov_bmp")):
                self._release(dc, bmp)
            self._size = self._out_size = self._ov_size = (0, 0)
            self._surface = None

    # -- the capture itself ----------------------------------------------

    def grab_screen(self, x, y, w, h):
        """BGRA for a screen rectangle, read straight off the composed
        desktop (~9ms against ~45ms for PrintWindow). The caller's windows
        must be excluded from capture (see set_capture_exclusion)."""
        if w <= 0 or h <= 0:
            return None
        # Only the on-screen part can be read, and it has to land at its
        # own offset: BitBlt would slide it against the corner instead.
        vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        sx, sy = max(x, vx), max(y, vy)
        ex = min(x + w, vx + user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
        ey = min(y + h, vy + user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
        if ex <= sx or ey <= sy:
            return None
        with self._lock:
            if not self._ensure("_out_dc", "_out_bmp", "_out_size", w, h):
                return None
            # Clear off-screen pixels left from a previous frame.
            if not gdi32.PatBlt(self._out_dc, 0, 0, w, h, BLACKNESS):
                return None
            screen_dc = user32.GetDC(None)
            if not screen_dc:
                return None
            try:
                if not gdi32.BitBlt(self._out_dc, sx - x, sy - y, ex - sx, ey - sy,
                                     screen_dc, sx, sy, SRCCOPY):
                    return None
            finally:
                user32.ReleaseDC(None, screen_dc)
            return self._read_out(w, h)

    def _read_out(self, w, h):
        hdr = BITMAPINFOHEADER(
            ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0,
        )
        buf = ctypes.create_string_buffer(w * h * 4)
        original = self._original_bitmaps["_out_dc"]
        selected = gdi32.SelectObject(self._out_dc, original)
        if not selected or selected == ctypes.c_void_p(-1).value:
            return None
        try:
            rows = gdi32.GetDIBits(self._out_dc, self._out_bmp, 0, h,
                                    buf, ctypes.byref(hdr), 0)
            return buf.raw if rows == h else None
        finally:
            gdi32.SelectObject(self._out_dc, self._out_bmp)

    def _paint_windows(self, hwnds, x, y):
        """Render `hwnds` into the output bitmap at their screen positions."""
        for hwnd in hwnds:
            r = window_rect(hwnd) if hwnd else None
            if not r:
                continue
            ow, oh = r[2] - r[0], r[3] - r[1]
            if ow <= 0 or oh <= 0:
                continue
            if not self._ensure("_ov_dc", "_ov_bmp", "_ov_size", ow, oh):
                continue
            if not user32.PrintWindow(hwnd, self._ov_dc, PW_RENDERFULLCONTENT):
                continue
            gdi32.BitBlt(
                self._out_dc, r[0] - x, r[1] - y, ow, oh, self._ov_dc, 0, 0, SRCCOPY)

    def grab(self, x, y, w, h, over=()):
        """BGRA for the wallpaper under (x, y, w, h), or None.

        `over` lists windows between the desktop and the caller, drawn in
        that order - e.g. the widget beneath a detail popover.
        """
        if w <= 0 or h <= 0:
            return None
        with self._lock:
            surface = self._pick_surface(x, y, w, h)
            if not surface:
                return None
            raw = self._render(surface, x, y, w, h)
            if raw is None:
                # The surface has gone (monitor change, wallpaper tool
                # restarted). Re-pick once rather than fail.
                self._surface = None
                surface = self._pick_surface(x, y, w, h)
                if not surface:
                    return None
                raw = self._render(surface, x, y, w, h)
            if raw is None or not over:
                return raw
            self._paint_windows(over, x, y)
            return self._read_out(w, h) or raw
