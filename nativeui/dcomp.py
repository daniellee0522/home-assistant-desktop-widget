"""A picture slid by the compositor (DirectComposition), the way the system's own flyouts are moved.

The panel used to be drawn again at each step of its coming and going, so every frame was a new bitmap through
Qt's layered window, handed over when the program got to it and taken up by the desktop at its own next
composition: some refreshes got two pictures, some none, and it looked like steps. Here the picture goes to the
graphics card once; what moves is a number the desktop evaluates itself at each refresh, from a curve the program
describes once (a few cubic pieces). Liquid glass optionally refreshes only its GPU material;
the card's movement never depends on those refresh callbacks.

One helper window (no redirection bitmap, so its pixels are the surfaces') lies over the panel's place for the
length of the slide, directly above the panel in the stacking order (not topmost: the panel is, while it is open, so
that the program clicked to close it does not cover the slide). The panel itself is shown or hidden at either end,
with the same pixels. The helper is two layers: the glass, which stays where it is and shows through a clip that rises
with the card, and the card, which moves. GUI thread only.

The panel supplies disjoint one-pixel corner columns from its own outline. Their parent follows the card while
their shared desktop texture follows the inverse curve, so the exact rounded mask moves but the glass does not.

What this costs: the card is translucent over the glass, and the desktop blends two translucent layers by its own rule,
not the encoded-value blend Qt makes for the panel's own picture. Measured through Desktop Duplication, that rule is
neither that blend nor linear light (white at half over black shows as 150 where Qt's is 128 and linear light's is
186), and it does not follow one curve, so a card remade to come out the same was tried and was no nearer. The panel
is therefore a little different in brightness over the slide than before and after it. Handing the desktop one opaque
picture (glass and card blended here) has no such difference, but then the glass moves with the card.

Nothing here is imported for its side effects, and anything that fails (no hardware device, an old Windows) makes
`slider()` return None: the caller keeps drawing the panel itself.

The interface method numbers are those of the Windows SDK's headers (d3d11.h, dxgi.h, dcomp.h, dcompanimation.h),
counted with IUnknown's three first, except that MSVC lays overloads of one name out in the reverse of their order in
the header (SetOffsetY: the animation's is 5, the number's 6). Methods that return nothing are called with `_void`:
what they leave in the return register is not an HRESULT.
"""
import ctypes
import os
import traceback
import uuid
import time
from functools import lru_cache
from ctypes import POINTER, WINFUNCTYPE, byref, c_char_p, c_double, c_float, c_long, c_uint, c_void_p, wintypes

_IID_DXGI_DEVICE = "54ec77fa-1377-44e6-8c32-88fd5f44c84c"
_IID_TEXTURE2D = "6f15aaf2-d208-4e89-9ab4-489535d34f9c"
_IID_DCOMP_DEVICE = "C37EA93A-E7AA-450D-B16F-9746CB0407F3"

_FORMAT_B8G8R8A8_UNORM = 87
_ALPHA_PREMULTIPLIED = 1
_CREATE_BGRA_SUPPORT = 0x20
_SDK_VERSION = 7

_WS_POPUP = 0x80000000
_EX_TRANSPARENT, _EX_TOOLWINDOW, _EX_NOREDIRECTIONBITMAP, _EX_NOACTIVATE = 0x20, 0x80, 0x00200000, 0x08000000
_SWP_NOACTIVATE, _SWP_SHOWWINDOW, _SWP_NOMOVE, _SWP_NOSIZE, _SWP_NOZORDER = 0x10, 0x40, 0x2, 0x1, 0x4
_WDA_EXCLUDEFROMCAPTURE = 0x11
_GW_HWNDPREV = 3
_HWND_TOP = 0


class _GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_uint32), ("d2", ctypes.c_uint16), ("d3", ctypes.c_uint16), ("d4", ctypes.c_ubyte * 8)]


def _guid(text):
    return _GUID.from_buffer_copy(uuid.UUID(text).bytes_le)


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _Timing(ctypes.Structure):
    # DWM_TIMING_INFO is packed to one byte by dwmapi.h.
    _pack_ = 1
    _fields_ = [("size", c_uint), ("rate", c_uint * 2), ("period", ctypes.c_ulonglong),
                ("compose_rate", c_uint * 2), ("vblank", ctypes.c_ulonglong),
                ("refresh", ctypes.c_ulonglong), ("dx_refresh", c_uint),
                ("compose", ctypes.c_ulonglong), ("frame", ctypes.c_ulonglong), ("dx_present", c_uint),
                ("refresh_frame", ctypes.c_ulonglong), ("submitted", ctypes.c_ulonglong),
                ("dx_submitted", c_uint), ("confirmed", ctypes.c_ulonglong), ("dx_confirmed", c_uint),
                ("refresh_confirmed", ctypes.c_ulonglong), ("dx_refresh_confirmed", c_uint),
                ("late", ctypes.c_ulonglong), ("outstanding", c_uint),
                ("frame_statistics", ctypes.c_ulonglong * 21)]


def next_frame_time():
    """Next desktop refresh in the same QPC seconds used by its animation clock."""
    try:
        _libraries()
        info = _Timing()
        info.size = ctypes.sizeof(info)
        if _dwm.DwmGetCompositionTimingInfo(None, byref(info)) < 0 or not info.period:
            return None
        now, frequency = ctypes.c_longlong(), ctypes.c_longlong()
        _kernel.QueryPerformanceCounter(byref(now))
        _kernel.QueryPerformanceFrequency(byref(frequency))
        steps = max(1, (now.value - info.vblank) // info.period + 1)
        return (info.vblank + steps * info.period) / frequency.value
    except (OSError, AttributeError):
        return None


class _Box(ctypes.Structure):
    _fields_ = [("left", c_uint), ("top", c_uint), ("front", c_uint), ("right", c_uint), ("bottom", c_uint),
                ("back", c_uint)]


@lru_cache(maxsize=256)
def _function(entry, result_type, argtypes):
    # Cache the native function, never an interface instance. COM objects can
    # be released/recreated without leaving a stale object pointer here.
    return WINFUNCTYPE(result_type, c_void_p, *argtypes)(entry)


def _call(obj, index, argtypes, *args):
    """Call method `index` of the COM object whose pointer is `obj`; the HRESULT is checked."""
    table = ctypes.cast(c_void_p(obj), POINTER(c_void_p)).contents.value
    entry = ctypes.cast(table + index * ctypes.sizeof(c_void_p), POINTER(c_void_p)).contents.value
    result = _function(entry, c_long, tuple(argtypes))(obj, *args)
    if result < 0:
        raise OSError("COM method %d failed: 0x%08X" % (index, result & 0xFFFFFFFF))
    return result


def _void(obj, index, argtypes, *args):
    """A call of a method that returns nothing (Direct3D's setters and draws): what it leaves in the return register
    is not an HRESULT and is not looked at."""
    table = ctypes.cast(c_void_p(obj), POINTER(c_void_p)).contents.value
    entry = ctypes.cast(table + index * ctypes.sizeof(c_void_p), POINTER(c_void_p)).contents.value
    _function(entry, None, tuple(argtypes))(obj, *args)


def _new(obj, index, argtypes, *args):
    """A call whose last argument is where a new interface pointer goes; that pointer."""
    out = c_void_p()
    _call(obj, index, argtypes + (POINTER(c_void_p),), *args, byref(out))
    return out.value


def _release(obj):
    if obj:
        try:
            _call(obj, 2, ())
        except OSError:
            pass


_user32 = _kernel = _dwm = None


def _libraries():
    global _user32, _kernel, _dwm
    if _user32 is not None:
        return
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _dwm = ctypes.WinDLL("dwmapi")
    _user32.DefWindowProcW.argtypes = [c_void_p, c_uint, wintypes.WPARAM, wintypes.LPARAM]
    _user32.DefWindowProcW.restype = ctypes.c_ssize_t
    _user32.CreateWindowExW.argtypes = [c_uint, wintypes.LPCWSTR, wintypes.LPCWSTR, c_uint, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, c_void_p, c_void_p, c_void_p,
                                       c_void_p]
    _user32.CreateWindowExW.restype = c_void_p
    _user32.SetWindowPos.restype = ctypes.c_int
    _user32.SetWindowPos.argtypes = [c_void_p, c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    c_uint]
    _user32.ShowWindow.argtypes = [c_void_p, ctypes.c_int]
    _user32.GetWindowRect.argtypes = [c_void_p, c_void_p]
    _user32.SetWindowDisplayAffinity.argtypes = [c_void_p, c_uint]
    _user32.DestroyWindow.argtypes = [c_void_p]
    _user32.GetWindow.argtypes = [c_void_p, c_uint]
    _user32.GetWindowLongW.argtypes = [c_void_p, ctypes.c_int]
    _user32.GetWindow.restype = c_void_p
    _kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    _kernel.GetModuleHandleW.restype = c_void_p


_WNDPROC = WINFUNCTYPE(ctypes.c_ssize_t, c_void_p, c_uint, wintypes.WPARAM, wintypes.LPARAM)


class _WndClass(ctypes.Structure):
    _fields_ = [("size", c_uint), ("style", c_uint), ("proc", _WNDPROC), ("class_extra", ctypes.c_int),
                ("window_extra", ctypes.c_int), ("instance", c_void_p), ("icon", c_void_p), ("cursor", c_void_p),
                ("background", c_void_p), ("menu", wintypes.LPCWSTR), ("name", wintypes.LPCWSTR),
                ("small_icon", c_void_p)]


def plain_window(hwnd):
    """Turn off DWM's own show animation, rounding and border for a window, as main._apply_window_shape does for
    the panel: every outline and motion here is ours. Showing a window restores the defaults, so before each show."""
    _libraries()
    for attribute, value in ((3, 1), (33, 1), (34, 0xFFFFFFFE)):    # transitions off, do not round, no border colour
        number = c_uint(value)
        try:
            _dwm.DwmSetWindowAttribute(c_void_p(hwnd), attribute, byref(number), ctypes.sizeof(number))
        except Exception:
            pass


_procedure = []


def _window_procedure():
    """The helper window's procedure, made once: the window class keeps pointing at it for as long as the program
    lives, so a second Slider (the first closed) must not find it freed."""
    if not _procedure:
        def dispatch(h, m, w, l):
            # A visual-only HWND must never consume panel or desktop clicks.
            if m == 0x0084:  # WM_NCHITTEST
                return -1   # HTTRANSPARENT
            if m == 0x0021:  # WM_MOUSEACTIVATE
                return 3    # MA_NOACTIVATE
            return _user32.DefWindowProcW(h, m, w, l)
        _procedure.append(_WNDPROC(dispatch))
    return _procedure[0]


def window_rect(hwnd):
    """(x, y, width, height) of a window in physical pixels, or None."""
    try:
        _libraries()
        rect = (ctypes.c_long * 4)()
        if _user32.GetWindowRect(c_void_p(hwnd), byref(rect)):
            return rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]
    except Exception:
        pass
    return None


def cubic_pieces(start, end, seconds, curve, pieces=16):
    """A cubic Bezier easing `curve` (x1, y1, x2, y2) from value `start` to `end` over `seconds`, as the cubic
    polynomials DirectComposition takes: [(begin, constant, linear, quadratic, cubic)], each in time from its own begin.
    Each piece is the cubic through its two ends with the curve's own slopes there."""
    x1, y1, x2, y2 = curve

    def point(s, a, b):
        return 3 * (1 - s) ** 2 * s * a + 3 * (1 - s) * s * s * b + s ** 3

    def slope(s, a, b):
        return 3 * (1 - s) ** 2 * a + 6 * (1 - s) * s * (b - a) + 3 * s * s * (1 - b)

    def at(fraction):
        low, high = 0.0, 1.0
        for _ in range(40):
            mid = (low + high) / 2
            if point(mid, x1, x2) < fraction:
                low = mid
            else:
                high = mid
        s = (low + high) / 2
        dx = slope(s, x1, x2)
        eased = point(s, y1, y2)
        return eased, (slope(s, y1, y2) / dx if dx > 1e-9 else 0.0)

    span = end - start
    result = []
    for i in range(pieces):
        f0, f1 = i / pieces, (i + 1) / pieces
        e0, d0 = at(f0)
        e1, d1 = at(f1)
        h = (f1 - f0) * seconds
        y0, y1_ = start + span * e0, start + span * e1
        m0, m1 = span * d0 / seconds, span * d1 / seconds
        c = 3 * (y1_ - y0) / h ** 2 - (2 * m0 + m1) / h
        d = -2 * (y1_ - y0) / h ** 3 + (m0 + m1) / h ** 2
        result.append((f0 * seconds, y0, m0, c, d))
    return result


def outline_columns(points, width, height, radius):
    """Disjoint glass columns inside a convex outline, with no circular approximation.

    Only the corners need one-pixel columns; the straight middle is one wide column.
    Taking the inward edge at both ends of each column avoids glass beyond the polygon.
    """
    import math
    radius = min(radius, width / 2, height / 2)
    edges = sorted({0.0, float(width),
                    *(float(x) for x in range(1, math.ceil(radius) + 1) if x < width),
                    *(float(x) for x in range(math.floor(width - radius), math.ceil(width)) if 0 < x < width)})

    def limits(x):
        ys = []
        for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1]):
            if abs(bx - ax) < 1e-9:
                if abs(x - ax) < 1e-7:
                    ys.extend((ay, by))
            elif min(ax, bx) - 1e-7 <= x <= max(ax, bx) + 1e-7:
                ys.append(ay + (by - ay) * (x - ax) / (bx - ax))
        return min(ys), max(ys)

    columns = []
    for left, right in zip(edges, edges[1:]):
        a, b = limits(left), limits(right)
        columns.append((left, right, max(a[0], b[0]), min(a[1], b[1])))
    return columns


class Slider:
    def __init__(self, capture_excluded=True, shared=None):
        _libraries()
        self.capture_excluded = capture_excluded
        self.shared = shared
        self.device = self.context = self.dxgi_device = self.composition = None
        self.hwnd = self.target = self.root = self.glass_visual = self.card_visual = self.clip = None
        self.glass_surface = self.card_surface = None
        self.mask_visuals, self.mask_contents, self.mask_clips, self.mask_columns = [], [], [], []
        self.size = (0, 0)
        self.shown = False
        self.material = None
        self.material_timer = None
        self.handoff_effect = None
        self.handoff_active = False
        self.pending_glass = None
        self.direct_after = 0.0           # the GPU copy of the desktop is not tried before this time
        self._proc = None
        self._make()

    def _make(self):
        if self.shared is not None:
            for name in ('device', 'context', 'dxgi_device', 'composition'):
                pointer = getattr(self.shared, name)
                _call(pointer, 1, ())  # each helper owns an independent COM reference
                setattr(self, name, pointer)
            self.shared = None
            self._make_visuals()
            return
        d3d11, dcomp = ctypes.WinDLL("d3d11"), ctypes.WinDLL("dcomp")
        device, context, level = c_void_p(), c_void_p(), c_uint()
        d3d11.D3D11CreateDevice.argtypes = [c_void_p, c_uint, c_void_p, c_uint, c_void_p, c_uint, c_uint,
                                           POINTER(c_void_p), POINTER(c_uint), POINTER(c_void_p)]
        d3d11.D3D11CreateDevice.restype = c_long
        result = d3d11.D3D11CreateDevice(None, 1, None, _CREATE_BGRA_SUPPORT, None, 0, _SDK_VERSION, byref(device),
                                         byref(level), byref(context))
        if result < 0 or not device.value:
            raise OSError("no Direct3D 11 device: 0x%08X" % (result & 0xFFFFFFFF))
        self.device, self.context = device.value, context.value
        self.dxgi_device = _new(self.device, 0, (POINTER(_GUID),), byref(_guid(_IID_DXGI_DEVICE)))
        composition = c_void_p()
        dcomp.DCompositionCreateDevice.argtypes = [c_void_p, POINTER(_GUID), POINTER(c_void_p)]
        dcomp.DCompositionCreateDevice.restype = c_long
        result = dcomp.DCompositionCreateDevice(self.dxgi_device, byref(_guid(_IID_DCOMP_DEVICE)),
                                                byref(composition))
        if result < 0:
            raise OSError("no DirectComposition device: 0x%08X" % (result & 0xFFFFFFFF))
        self.composition = composition.value
        self._make_visuals()

    def _make_visuals(self):
        self._make_window()
        self.target = _new(self.composition, 6, (c_void_p, ctypes.c_int), self.hwnd, 1)    # CreateTargetForHwnd
        self.root = _new(self.composition, 7, ())                                           # CreateVisual
        self.glass_visual = _new(self.composition, 7, ())
        self.card_visual = _new(self.composition, 7, ())
        _call(self.target, 3, (c_void_p,), self.root)                                       # SetRoot
        # AddVisual(visual, insertAbove, reference): with no reference, "above" puts it at the bottom.
        _call(self.root, 16, (c_void_p, ctypes.c_int, c_void_p), self.glass_visual, 1, None)
        _call(self.root, 16, (c_void_p, ctypes.c_int, c_void_p), self.card_visual, 1, self.glass_visual)
        self.clip = _new(self.composition, 24, ())                                          # CreateRectangleClip
        _call(self.glass_visual, 13, (c_void_p,), self.clip)                                # SetClip(clip)

    def _make_window(self):
        name = "HAWidgetsSlide%d" % os.getpid()
        instance = _kernel.GetModuleHandleW(None)
        cls = _WndClass(ctypes.sizeof(_WndClass), 0, _window_procedure(), 0, 0, instance, None, None, None, None, name, None)
        _user32.RegisterClassExW.argtypes = [POINTER(_WndClass)]
        if not _user32.RegisterClassExW(byref(cls)) and ctypes.get_last_error() != 1410:   # (already registered)
            raise OSError("window class: %d" % ctypes.get_last_error())
        extra = _EX_TRANSPARENT | _EX_TOOLWINDOW | _EX_NOREDIRECTIONBITMAP | _EX_NOACTIVATE
        self.hwnd = _user32.CreateWindowExW(extra, name, "", _WS_POPUP, 0, 0, 1, 1, None, None, instance, None)
        if not self.hwnd:
            raise OSError("window: %d" % ctypes.get_last_error())
        if self.capture_excluded:
            # Like the panel: what reads the screen for a glass behind something must not read this back in.
            _user32.SetWindowDisplayAffinity(self.hwnd, _WDA_EXCLUDEFROMCAPTURE)

    def _make_surfaces(self, width, height):
        for name, visual in (("glass_surface", self.glass_visual), ("card_surface", self.card_visual)):
            _release(getattr(self, name))
            setattr(self, name, None)
            surface = _new(self.composition, 8, (c_uint, c_uint, c_uint, c_uint),       # CreateSurface
                           width, height, _FORMAT_B8G8R8A8_UNORM, _ALPHA_PREMULTIPLIED)
            setattr(self, name, surface)
            _call(visual, 15, (c_void_p,), surface)                                         # SetContent
        self.size = (width, height)

    def _upload(self, surface, image):
        data = image.constBits().tobytes()
        point, texture = _Point(), c_void_p()
        _call(surface, 3, (c_void_p, POINTER(_GUID), POINTER(c_void_p), POINTER(_Point)),     # BeginDraw, all of it
              None, byref(_guid(_IID_TEXTURE2D)), byref(texture), byref(point))
        try:
            # (the surface lies at `point` in a texture the desktop shares among them)
            box = _Box(point.x, point.y, 0, point.x + image.width(), point.y + image.height(), 1)
            _void(self.context, 48, (c_void_p, c_uint, POINTER(_Box), c_char_p, c_uint, c_uint),   # UpdateSubresource
                  texture.value, 0, byref(box), data, image.bytesPerLine(), 0)
        finally:
            _call(surface, 4, ())                                                           # EndDraw
            _release(texture.value)

    def _column_mask(self, columns, offset):
        if len(columns) != len(self.mask_clips):
            for visual, content, clip in zip(self.mask_visuals, self.mask_contents, self.mask_clips):
                _call(self.glass_visual, 17, (c_void_p,), visual)                             # RemoveVisual
                _release(visual)
                _release(content)
                _release(clip)
            self.mask_visuals, self.mask_contents, self.mask_clips = [], [], []
            for _ in columns:
                visual = _new(self.composition, 7, ())
                content = _new(self.composition, 7, ())
                clip = _new(self.composition, 24, ())
                self.mask_visuals.append(visual)
                self.mask_contents.append(content)
                self.mask_clips.append(clip)
                _call(visual, 13, (c_void_p,), clip)
                _call(visual, 16, (c_void_p, ctypes.c_int, c_void_p), content, 1, None)
                _call(self.glass_visual, 16, (c_void_p, ctypes.c_int, c_void_p), visual, 1, None)
        _call(self.glass_visual, 15, (c_void_p,), None)                                       # shared content on children
        _call(self.glass_visual, 13, (c_void_p,), None)                                       # no fixed parent clip
        _call(self.glass_visual, 6, (c_float,), float(offset))
        for content, clip, (left, right, top, bottom) in zip(self.mask_contents, self.mask_clips, columns):
            _call(content, 15, (c_void_p,), self.glass_surface)
            _call(content, 6, (c_float,), float(-offset))
            for index, value in ((4, left), (8, right), (6, top), (10, bottom)):
                _call(clip, index, (c_float,), float(value))
        self.mask_columns = columns

    def show(self, rect, glass, card, offset, radius, above=None, columns=None, liquid=None, wait=True):
        """The two pictures (QImages, premultiplied ARGB, the size of `rect` = (x, y, w, h); `glass` may be None) over
        `rect`, the card held `offset` px down from there and the glass inside its moving outline (`columns`), or a
        rounded rectangle by `radius` px when no outline is supplied. The window goes just above `above`. Returns
        once the desktop has it."""
        x, y, width, height = rect
        self._stop_material()
        if getattr(self, 'handoff_effect', None) is not None:
            # A completed fade remains attached to the reused root. Detach it
            # entirely while sliding; opacity animation state must not survive
            # into the next opening or closing.
            _call(self.root, 10, (c_void_p,), None)
            _call(self.handoff_effect, 4, (c_float,), 1.0)
        if (width, height) != self.size:
            self._make_surfaces(width, height)
        if glass is None:
            glass = type(card)(width, height, card.format())
            glass.fill(0)
        self._upload(self.glass_surface, glass)
        self._upload(self.card_surface, card)
        _call(self.card_visual, 15, (c_void_p,), self.card_surface)
        if liquid is not None:
            from .dcomp_liquid import Material
            try:
                self.material = Material(self, glass, **liquid)
                self.material.draw(offset)
            except Exception:
                self._stop_material()
                _log("Compositor liquid material unavailable:\n" + traceback.format_exc())
        _call(self.card_visual, 6, (c_float,), float(offset))                                # SetOffsetY(value)
        for index, value in ((4, 0.0), (8, float(width)), (6, float(offset)), (10, float(height + offset)),
                             (12, radius), (14, radius), (16, radius), (18, radius),
                             (20, radius), (22, radius), (24, radius), (26, radius)):        # the clip's sides, corners
            _call(self.clip, index, (c_float,), float(value))
        if columns is not None:
            self._column_mask(columns, offset)
        elif getattr(self, "mask_columns", []):
            self._column_mask([], offset)
            _call(self.glass_visual, 15, (c_void_p,), self.glass_surface)
            _call(self.glass_visual, 13, (c_void_p,), self.clip)
            _call(self.glass_visual, 6, (c_float,), 0.0)
        _call(self.composition, 3, ())                                                       # Commit
        behind = _user32.GetWindow(c_void_p(above), _GW_HWNDPREV) if above else None
        flags = _SWP_NOACTIVATE | _SWP_SHOWWINDOW
        if behind == self.hwnd:
            # Hidden, it still lies directly above the panel, where it was put the last time: it is already where it
            # belongs, and a window cannot be put behind itself (the call fails, and the window stays hidden).
            flags |= _SWP_NOZORDER
        plain_window(self.hwnd)
        if above and not behind:
            # Nothing above the panel: just above it, which for a topmost panel is the top of the topmost windows.
            topmost = bool(_user32.GetWindowLongW(c_void_p(above), -20) & 0x8)
            behind = -1 if topmost else _HWND_TOP
        shown = _user32.SetWindowPos(self.hwnd, c_void_p(behind or _HWND_TOP), x, y, width, height, flags)
        if not shown:
            raise OSError("SetWindowPos failed: %d" % ctypes.get_last_error())
        if wait:
            _call(self.composition, 4, ())                                                   # WaitForCommitCompletion
        self.shown = True

    def motion_offset(self):
        """Position of the current compositor curve, without finishing it."""
        elapsed = max(0.0, time.perf_counter() - self.motion_started)
        if elapsed >= self.motion_duration:
            return self.motion_end
        begin, a, b, c, d = next(p for p in reversed(self.motion_curve) if p[0] <= elapsed)
        t = elapsed - begin
        return a + t * (b + t * (c + t * d))

    def slide(self, start, end, seconds, curve):
        """Move the card from `start` to `end` px down, over `seconds`, on the desktop's own clock; the glass's clip
        goes with it."""
        self.motion_started = time.perf_counter()
        self.motion_duration, self.motion_end = seconds, end
        self.motion_curve = cubic_pieces(start, end, seconds, curve)
        animation = _new(self.composition, 25, ())                                           # CreateAnimation
        material = getattr(self, 'material', None)
        begin_time = None
        if material is not None:
            stamp = ctypes.c_longlong()
            _kernel.QueryPerformanceCounter(byref(stamp))
            begin_time = stamp.value
            self.material_start = time.perf_counter()
            frequency = ctypes.c_longlong()
            _kernel.QueryPerformanceFrequency(byref(frequency))
            self.material_qpc_start = begin_time / frequency.value
            self.motion_started = self.material_qpc_start
            self.material_curve = cubic_pieces(start, end, seconds, curve)
            self.material_duration, self.material_end = seconds, end
            _call(animation, 4, (ctypes.c_longlong,), begin_time)
        try:
            for begin, a, b, c, d in cubic_pieces(start, end, seconds, curve):
                _call(animation, 5, (c_double, c_float, c_float, c_float, c_float), begin, a, b, c, d)   # AddCubic
            _call(animation, 8, (c_double, c_float), seconds, float(end))                    # End
            _call(self.card_visual, 5, (c_void_p,), animation)                               # SetOffsetY(animation)
            columns = getattr(self, "mask_columns", [])
            if columns:
                # Move the complete outline with the card, and counter-move its
                # shared desktop texture by exactly the opposite curve. Two curves
                # keep every glass pixel at its original screen position on the GPU.
                _call(self.glass_visual, 5, (c_void_p,), animation)
                inverse = _new(self.composition, 25, ())
                try:
                    if begin_time is not None:
                        _call(inverse, 4, (ctypes.c_longlong,), begin_time)
                    for begin, a, b, c, d in cubic_pieces(start, end, seconds, curve):
                        _call(inverse, 5, (c_double, c_float, c_float, c_float, c_float),
                              begin, -a, -b, -c, -d)
                    _call(inverse, 8, (c_double, c_float), seconds, float(-end))
                    for content in self.mask_contents:
                        _call(content, 5, (c_void_p,), inverse)
                finally:
                    _release(inverse)
                _call(self.composition, 3, ())
                if material is not None:
                    self._start_material()
                return
            _call(self.clip, 5, (c_void_p,), animation)                                      # SetTop(animation)
            # The bottom follows the same curve one card-height below the top. Keeping it
            # beyond the window leaves square glass corners as the card settles or leaves.
            bottom = _new(self.composition, 25, ())
            try:
                for begin, a, b, c, d in cubic_pieces(start, end, seconds, curve):
                    _call(bottom, 5, (c_double, c_float, c_float, c_float, c_float),
                          begin, a + self.size[1], b, c, d)
                _call(bottom, 8, (c_double, c_float), seconds, float(end + self.size[1]))
                _call(self.clip, 9, (c_void_p,), bottom)                                     # SetBottom(animation)
            finally:
                _release(bottom)
            _call(self.composition, 3, ())
        finally:
            _release(animation)

    def _start_material(self):
        from PySide6.QtCore import QObject
        from .animation_clock import FrameTimer
        if self.material_timer is None:
            self.material_owner = QObject()
            self.material_timer = FrameTimer(self.material_owner)
            self.material_timer.vsync = True
            self.material_timer.timeout.connect(self._material_frame)
        self.material_timer.start()

    def _material_frame(self):
        if not self.shown or self.material is None:
            self.material_timer.stop()
            return
        pending = getattr(self, 'pending_glass', None)
        outcome = None
        if pending is not None:
            self.pending_glass = None
            try:
                outcome = self.material.update(pending)
            except Exception:
                # The desktop could not be copied on the GPU: the capture goes through the processor for a while.
                _log("Compositor GPU backdrop unavailable:\n" + traceback.format_exc())
                self.direct_after = time.monotonic() + 5.0
                self.material.gpu_views = None
                outcome = 'failed'
            if outcome is None:
                self.direct_after = time.monotonic() + 1.0
        present = next_frame_time() if hasattr(self, 'material_qpc_start') else None
        elapsed = (present - self.material_qpc_start if present is not None else
                   time.perf_counter() - self.material_start)
        elapsed = max(0.0, elapsed)
        if outcome == 'static' and elapsed >= self.material_duration and not getattr(self, 'handoff_active', False):
            self.material_timer.stop()      # the desktop did not change: what is drawn is still right
            return
        offset = self.material_end
        if elapsed < self.material_duration:
            begin, a, b, c, d = next(piece for piece in reversed(self.material_curve) if piece[0] <= elapsed)
            t = elapsed - begin
            offset = a + t * (b + t * (c + t * d))
        try:
            self.material.draw(offset)
            _call(self.composition, 3, ())
        except Exception:
            _log("Compositor liquid refresh failed:\n" + traceback.format_exc())
            self.material_timer.stop()
        if elapsed >= self.material_duration and not getattr(self, 'handoff_active', False):
            self.material_timer.stop()

    def queue_glass(self, image):
        """Keep only the newest capture; upload and draw it at the next vsync."""
        if self.material is not None and self.shown:
            self.pending_glass = image
            self._start_material()

    def _stop_material(self):
        self.pending_glass = None
        self.handoff_active = False
        if getattr(self, 'material_timer', None) is not None:
            self.material_timer.stop()
        if getattr(self, 'material', None) is not None:
            self.material.close()
            self.material = None

    def fade_out(self, seconds):
        """Blend into the already painted resting window without a one-frame material swap."""
        self.handoff_active = True
        if self.material is not None:
            self.material.draw(0.0)
        if self.handoff_effect is None:
            self.handoff_effect = _new(self.composition, 23, ())
        _call(self.root, 10, (c_void_p,), self.handoff_effect)
        animation = _new(self.composition, 25, ())
        try:
            _call(animation, 5, (c_double, c_float, c_float, c_float, c_float),
                  0.0, 1.0, 0.0, -3.0 / seconds ** 2, 2.0 / seconds ** 3)
            _call(animation, 8, (c_double, c_float), seconds, 0.0)
            _call(self.handoff_effect, 3, (c_void_p,), animation)
            _call(self.composition, 3, ())
            if self.material is not None:
                self._start_material()
        finally:
            _release(animation)

    def settle_glass(self, above):
        """Keep the same live glass under the native foreground, without swapping backdrops."""
        self.handoff_active = False
        _call(self.card_visual, 15, (c_void_p,), None)
        _call(self.glass_visual, 6, (c_float,), 0.0)
        for content in self.mask_contents:
            _call(content, 6, (c_float,), 0.0)
        _call(self.composition, 3, ())
        # Native fields and controls stay above the material and receive input.
        _user32.SetWindowPos(self.hwnd, c_void_p(above), 0, 0, 0, 0,
                            _SWP_NOACTIVATE | _SWP_NOMOVE | _SWP_NOSIZE)

    def visible(self):
        """Whether the helper window is shown on the desktop now."""
        _user32.IsWindowVisible.argtypes = [c_void_p]
        return bool(_user32.IsWindowVisible(c_void_p(self.hwnd)))

    def next_composition(self):
        """Wait for the desktop to compose once."""
        try:
            _dwm.DwmFlush()
        except Exception:
            pass

    def hide(self):
        self._stop_material()
        if self.shown:
            _user32.ShowWindow(self.hwnd, 0)
            self.shown = False

    def close(self):
        self.hide()
        for visual, content, clip in zip(self.mask_visuals, self.mask_contents, self.mask_clips):
            _release(visual)
            _release(content)
            _release(clip)
        self.mask_visuals, self.mask_contents, self.mask_clips, self.mask_columns = [], [], [], []
        for name in ("handoff_effect", "clip", "glass_visual", "card_visual", "root", "target", "glass_surface", "card_surface",
                     "composition", "dxgi_device", "context", "device"):
            _release(getattr(self, name))
            setattr(self, name, None)
        if self.hwnd:
            _user32.DestroyWindow(self.hwnd)
            self.hwnd = None


_state = {"slider": None, "failed": False}


def slider():
    """The program's one Slider, or None where this cannot be had (then the caller draws the motion itself)."""
    if _state["failed"] or os.environ.get("HA_WIDGET_DCOMP") == "0" or os.name != "nt":
        return None
    if _state["slider"] is None:
        try:
            _state["slider"] = Slider()
        except Exception:
            _state["failed"] = True
            _log("DirectComposition slide unavailable:\n" + traceback.format_exc())
            return None
    return _state["slider"]


def disable(reason=""):
    """It failed while in use: not tried again this run."""
    _state["failed"] = True
    if reason:
        _log("DirectComposition slide switched off: " + reason)
    held = _state["slider"]
    _state["slider"] = None
    if held is not None:
        try:
            held.hide()
        except Exception:
            pass


def _log(line):
    try:
        import qtshell
        qtshell.log(line)
    except Exception:
        pass
