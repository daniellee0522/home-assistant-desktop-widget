"""Screen reads through DXGI Desktop Duplication, driven by the screen itself.

Windows hands over a new desktop image only when something on an output
was presented, together with the rectangles that changed. A reader asks
for a rectangle and the frame it last received; the answer comes as soon
as that rectangle has changed, or after a timeout if it has not. Nothing is
copied or read back while the desktop under a reader stands still, and an
animated one is followed at the display's own rate.

Each output's duplication keeps a GPU copy of its desktop, patched with
only the rectangles that changed, so any region can be read at once and a
change landing between two reads is never lost. A read that copy can
already answer is served on the reader's thread; the capture thread only
wakes for frames. Duplications are dropped once nobody has read for a
while, and rebuilt after the desktop is lost (mode change, secure desktop,
GPU reset).
"""

import contextlib
import ctypes
import threading
import time
from ctypes import wintypes

_HRESULT = ctypes.c_long
_vp = ctypes.c_void_p

DXGI_ERROR_WAIT_TIMEOUT = -2005270489        # 0x887A0027
DXGI_ERROR_NOT_FOUND = -2005270526           # 0x887A0002

DXGI_FORMAT_B8G8R8A8_UNORM = 87
D3D11_USAGE_DEFAULT = 0
D3D11_USAGE_STAGING = 3
D3D11_CPU_ACCESS_READ = 0x20000
D3D11_MAP_READ = 1
D3D11_SDK_VERSION = 7

ROTATE_IDENTITY, ROTATE_90, ROTATE_180, ROTATE_270 = 1, 2, 3, 4

# How long the thread keeps duplicating after the last read.
_IDLE_RELEASE_SECS = 2.0
# How long the capture thread blocks waiting for a frame before it checks
# for expired reads and idleness. New reads do not wait for it.
_ACQUIRE_MS = 100
# While frames are coming: how long the output that last delivered one is waited on, and for how long after a frame.
_BUSY_WAIT_MS = 8
_BUSY_SECS = 0.5
# Frames of change history kept to answer "changed since frame N".
_HISTORY = 240


class _GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16),
                ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text):
        h = text.replace("-", "")
        return cls(int(h[0:8], 16), int(h[8:12], 16), int(h[12:16], 16),
                   (ctypes.c_ubyte * 8)(*bytes.fromhex(h[16:])))


IID_IDXGIFactory1 = _GUID.parse("770aae78-f26f-4dba-a829-253c83d1b387")
IID_IDXGIOutput1 = _GUID.parse("00cddea8-939b-4b83-a340-a685226666cc")
IID_ID3D11Texture2D = _GUID.parse("6f15aaf2-d208-4e89-9ab4-489535d34f9c")
IID_ID3D10Multithread = _GUID.parse("9b7e4e00-342c-4106-a19f-4f2704f689f0")
IID_IDXGIDevice = _GUID.parse("54ec77fa-1377-44e6-8c32-88fd5f44c84c")
IID_IDXGIResource = _GUID.parse("035f3ab4-482e-4e50-b41f-8a7f8bd8960b")
IID_IDXGIKeyedMutex = _GUID.parse("9d8e1289-d7b3-465f-8126-250e349af85d")
# How long a side waits for the other to let go of the shared desktop copy (ms): each holds it only
# while it issues a copy command.
_MUTEX_WAIT_MS = 20


class _OUTPUT_DESC(ctypes.Structure):
    _fields_ = [("DeviceName", wintypes.WCHAR * 32), ("Desktop", wintypes.RECT),
                ("Attached", wintypes.BOOL), ("Rotation", ctypes.c_uint),
                ("Monitor", _vp)]


class _FRAME_INFO(ctypes.Structure):
    _fields_ = [("LastPresentTime", ctypes.c_int64), ("LastMouseUpdateTime", ctypes.c_int64),
                ("AccumulatedFrames", ctypes.c_uint), ("RectsCoalesced", wintypes.BOOL),
                ("ProtectedContentMaskedOut", wintypes.BOOL),
                ("PointerX", ctypes.c_long), ("PointerY", ctypes.c_long),
                ("PointerVisible", wintypes.BOOL),
                ("TotalMetadataBufferSize", ctypes.c_uint),
                ("PointerShapeBufferSize", ctypes.c_uint)]


class _MOVE_RECT(ctypes.Structure):
    _fields_ = [("SourcePoint", wintypes.POINT), ("Destination", wintypes.RECT)]


class _TEX2D_DESC(ctypes.Structure):
    _fields_ = [("Width", ctypes.c_uint), ("Height", ctypes.c_uint),
                ("MipLevels", ctypes.c_uint), ("ArraySize", ctypes.c_uint),
                ("Format", ctypes.c_uint), ("SampleCount", ctypes.c_uint),
                ("SampleQuality", ctypes.c_uint), ("Usage", ctypes.c_uint),
                ("BindFlags", ctypes.c_uint), ("CPUAccessFlags", ctypes.c_uint),
                ("MiscFlags", ctypes.c_uint)]


class _BOX(ctypes.Structure):
    _fields_ = [("left", ctypes.c_uint), ("top", ctypes.c_uint), ("front", ctypes.c_uint),
                ("right", ctypes.c_uint), ("bottom", ctypes.c_uint), ("back", ctypes.c_uint)]


class _MAPPED(ctypes.Structure):
    _fields_ = [("pData", _vp), ("RowPitch", ctypes.c_uint), ("DepthPitch", ctypes.c_uint)]


class _ADAPTER_DESC(ctypes.Structure):
    _fields_ = [("Description", ctypes.c_wchar * 128), ("VendorId", ctypes.c_uint),
                ("DeviceId", ctypes.c_uint), ("SubSysId", ctypes.c_uint),
                ("Revision", ctypes.c_uint), ("DedicatedVideoMemory", ctypes.c_size_t),
                ("DedicatedSystemMemory", ctypes.c_size_t), ("SharedSystemMemory", ctypes.c_size_t),
                ("LuidLow", ctypes.c_uint), ("LuidHigh", ctypes.c_int)]


def _address(pointer):
    return int(getattr(pointer, "value", pointer) or 0)


def _adapter_luid(adapter):
    """(low, high) of an IDXGIAdapter, the identity two devices share when on one GPU."""
    desc = _ADAPTER_DESC()
    _call(adapter, 8, ctypes.byref(desc), argtypes=(_vp,), what="GetDesc")
    return desc.LuidLow, desc.LuidHigh


def _device_luid(dxgi_device):
    adapter = _vp()
    _call(dxgi_device, 7, ctypes.byref(adapter), argtypes=(_vp,), what="GetAdapter")
    try:
        return _adapter_luid(adapter)
    finally:
        _release(adapter)


class DxgiError(OSError):
    def __init__(self, what, hr):
        super().__init__("%s failed: 0x%08X" % (what, hr & 0xFFFFFFFF))
        self.hr = hr


# ---------------------------------------------------------------------
# COM through vtables
# ---------------------------------------------------------------------
# IDXGIFactory1::EnumAdapters1 12; IDXGIAdapter::EnumOutputs 7;
# IDXGIOutput::GetDesc 7; IDXGIOutput1::DuplicateOutput 22;
# IDXGIOutputDuplication: AcquireNextFrame 8, GetFrameDirtyRects 9,
# GetFrameMoveRects 10, ReleaseFrame 14; ID3D11Device::CreateTexture2D 5;
# ID3D11DeviceContext: Map 14, Unmap 15, CopySubresourceRegion 46;
# ID3D10Multithread::SetMultithreadProtected 5.

_prototypes = {}
_COPY_REGION_ARGS = (_vp, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
                     ctypes.c_uint, _vp, ctypes.c_uint, _vp)


def _call(obj, index, *args, restype=_HRESULT, argtypes=None, what=None):
    """Call vtable slot `index` of COM object `obj` (a c_void_p)."""
    argtypes = tuple(argtypes or ())
    key = (restype, argtypes)
    proto = _prototypes.get(key)
    if proto is None:
        proto = _prototypes[key] = ctypes.WINFUNCTYPE(restype, _vp, *argtypes)
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(_vp))).contents
    result = proto(vtable[index])(obj, *args)
    if restype is _HRESULT and what and result < 0:
        raise DxgiError(what, result)
    return result


def _release(obj):
    if obj:
        _call(obj, 2, restype=ctypes.c_ulong)


def _query(obj, iid, what):
    out = _vp()
    _call(obj, 0, ctypes.byref(iid), ctypes.byref(out),
          argtypes=(_vp, _vp), what=what)
    return out


def _create_device(d3d11, adapter):
    """A D3D11 device on `adapter` whose immediate context may be used from
    more than one thread (the capture thread and a reader's)."""
    device, context = _vp(), _vp()
    level = ctypes.c_uint()
    d3d11.D3D11CreateDevice.argtypes = [
        _vp, ctypes.c_uint, _vp, ctypes.c_uint, _vp, ctypes.c_uint,
        ctypes.c_uint, _vp, _vp, _vp]
    hr = d3d11.D3D11CreateDevice(
        adapter, 0, None, 0, None, 0, D3D11_SDK_VERSION,
        ctypes.byref(device), ctypes.byref(level), ctypes.byref(context))
    if hr < 0:
        raise DxgiError("D3D11CreateDevice", hr)
    try:
        guard = _query(context, IID_ID3D10Multithread, "QueryInterface(Multithread)")
        try:
            _call(guard, 5, 1, restype=wintypes.BOOL, argtypes=(wintypes.BOOL,))
        finally:
            _release(guard)
    except Exception:
        _release(context)
        _release(device)
        raise
    return device, context


# ---------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------

def _intersect(a, b):
    l, t, r, bt = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return (l, t, r, bt) if l < r and t < bt else None


def desktop_to_texture(rect, rotation, out_w, out_h):
    """A rectangle relative to an output's desktop area, in the output's
    unrotated desktop image. out_w/out_h are the desktop area's size."""
    l, t, r, b = rect
    if rotation == ROTATE_90:
        return (t, out_w - r, b, out_w - l)
    if rotation == ROTATE_180:
        return (out_w - r, out_h - b, out_w - l, out_h - t)
    if rotation == ROTATE_270:
        return (out_h - b, l, out_h - t, r)
    return rect


# PIL transposition taking an image read in texture orientation back to the
# desktop's; None for an unrotated output.
def _untransposer(rotation):
    from PIL import Image
    return {ROTATE_90: Image.Transpose.ROTATE_270,
            ROTATE_180: Image.Transpose.ROTATE_180,
            ROTATE_270: Image.Transpose.ROTATE_90}.get(rotation)


# ---------------------------------------------------------------------
# One output
# ---------------------------------------------------------------------

class _Output:
    """One duplicated output and a GPU copy of its desktop."""

    def __init__(self, device, context, output1, desc, luid=None):
        self.context = context
        self.luid = luid           # the adapter this output lives on
        self.mutex = None          # keyed mutex of `copy`, when a renderer on the same adapter may read it
        self.handle = None         # `copy`'s shared handle
        self.opened = {}           # reader device -> (its view of `copy`, its mutex)
        self.device = device
        self.desktop = (desc.Desktop.left, desc.Desktop.top,
                        desc.Desktop.right, desc.Desktop.bottom)
        self.rotation = desc.Rotation
        self.name = desc.DeviceName
        self.dup = _vp()
        _call(output1, 22, device, ctypes.byref(self.dup),
              argtypes=(_vp, _vp), what="DuplicateOutput")
        self.copy = None           # the output's desktop, kept current
        self.copy_size = (0, 0)
        self.staging = None
        self.staging_size = (0, 0)
        self._batch_seq = None
        self._batch = {}
        # Counts the frames this output has taken. It starts from the clock,
        # not zero, so that after a rebuild (the duplication is released when
        # nothing has asked for a while) a caller's older `after` still reads
        # as stale and is answered with the screen, not "unchanged" for ever.
        self.seq = int(time.monotonic() * 1000)
        self.history = []          # (seq, texture-space rects that changed)
        self.valid = None          # texture-space area `copy` holds

    @property
    def size(self):
        return (self.desktop[2] - self.desktop[0], self.desktop[3] - self.desktop[1])

    def _texture_size(self):
        w, h = self.size
        return (h, w) if self.rotation in (ROTATE_90, ROTATE_270) else (w, h)

    def texture_rect(self, rect):
        """A desktop-space rectangle, clipped to this output, as
        (desktop part, the same part in texture space)."""
        part = _intersect(rect, self.desktop)
        if not part:
            return None, None
        local = (part[0] - self.desktop[0], part[1] - self.desktop[1],
                 part[2] - self.desktop[0], part[3] - self.desktop[1])
        w, h = self.size
        return part, desktop_to_texture(local, self.rotation, w, h)

    def close(self):
        self._unshare()
        for attr in ("staging", "copy", "dup"):
            _release(getattr(self, attr))
            setattr(self, attr, None)

    def _texture(self, w, h, staging, shared=False):
        # A shared texture needs a bind flag (shader resource, 8) and a keyed mutex (0x100) to order
        # the two devices' commands on the GPU.
        desc = _TEX2D_DESC(w, h, 1, 1, DXGI_FORMAT_B8G8R8A8_UNORM, 1, 0,
                           D3D11_USAGE_STAGING if staging else D3D11_USAGE_DEFAULT,
                           8 if shared else 0, D3D11_CPU_ACCESS_READ if staging else 0,
                           0x100 if shared else 0)
        tex = _vp()
        _call(self.device, 5, ctypes.byref(desc), None, ctypes.byref(tex),
              argtypes=(_vp, _vp, _vp), what="CreateTexture2D")
        return tex

    def acquire(self, wait_ms, lock):
        """Wait up to wait_ms for the next frame and patch its changes into
        `copy`, holding `lock` for everything but the wait.

        Returns True when a frame arrived. Raises DxgiError when the
        duplication has to be rebuilt.
        """
        info = _FRAME_INFO()
        resource = _vp()
        hr = _call(self.dup, 8, wait_ms, ctypes.byref(info), ctypes.byref(resource),
                   argtypes=(ctypes.c_uint, _vp, _vp))
        if hr == DXGI_ERROR_WAIT_TIMEOUT:
            return False
        if hr < 0:
            raise DxgiError("AcquireNextFrame", hr)
        with lock:
            try:
                # A pointer-only update leaves the desktop image as it was.
                if not info.LastPresentTime or not info.AccumulatedFrames:
                    return True
                changed = self._changed_rects(info)
                tex = _query(resource, IID_ID3D11Texture2D, "QueryInterface(Texture2D)")
                try:
                    self._keep(tex, changed)
                finally:
                    _release(tex)
                self.seq += 1
                self.history.append((self.seq, changed))
                del self.history[:-_HISTORY]
                return True
            finally:
                _release(resource)
                _call(self.dup, 14, what="ReleaseFrame")

    def _changed_rects(self, info):
        """The frame's moved and dirty rectangles, in texture space."""
        whole = [(0, 0) + self._texture_size()]
        size = info.TotalMetadataBufferSize
        if not size:
            return whole
        buf = (ctypes.c_ubyte * size)()
        needed = ctypes.c_uint()
        rects = []
        if _call(self.dup, 10, size, buf, ctypes.byref(needed),
                 argtypes=(ctypes.c_uint, _vp, _vp)) < 0:
            return whole
        for m in (_MOVE_RECT * (needed.value // ctypes.sizeof(_MOVE_RECT))).from_buffer(buf):
            d = m.Destination
            rects.append((d.left, d.top, d.right, d.bottom))
        if _call(self.dup, 9, size, buf, ctypes.byref(needed),
                 argtypes=(ctypes.c_uint, _vp, _vp)) < 0:
            return whole
        for d in (wintypes.RECT * (needed.value // ctypes.sizeof(wintypes.RECT))).from_buffer(buf):
            rects.append((d.left, d.top, d.right, d.bottom))
        return rects

    def _keep(self, frame, changed):
        """Patch the rectangles this frame changed into `copy`."""
        tw, th = self._texture_size()
        if self.copy_size != (tw, th):
            self._unshare()
            _release(self.copy)
            self.copy = None
            try:
                self.copy = self._texture(tw, th, staging=False, shared=True)
                self._share()
            except (DxgiError, OSError):
                self._unshare()
                _release(self.copy)
                self.copy = self._texture(tw, th, staging=False)
            self.copy_size = (tw, th)
            self.valid = None
        whole = (0, 0, tw, th)
        boxes = [whole] if self.valid is None else [
            hit for hit in (_intersect(r, whole) for r in changed) if hit]
        with self._held():
            for l, t, r, b in boxes:
                _call(self.context, 46, self.copy, 0, l, t, 0, frame, 0,
                      ctypes.byref(_BOX(l, t, 0, r, b, 1)),
                      restype=None, argtypes=_COPY_REGION_ARGS)
        self.valid = whole

    def _share(self):
        """Give `copy` a shared handle and a keyed mutex so that a renderer's device can read it."""
        self.mutex = _query(self.copy, IID_IDXGIKeyedMutex, "QueryInterface(KeyedMutex)")
        resource = _query(self.copy, IID_IDXGIResource, "QueryInterface(Resource)")
        try:
            handle = _vp()
            _call(resource, 8, ctypes.byref(handle), argtypes=(_vp,), what="GetSharedHandle")
            self.handle = handle.value
        finally:
            _release(resource)

    def _unshare(self):
        for texture, mutex in self.opened.values():
            _release(mutex)
            _release(texture)
        self.opened = {}
        _release(getattr(self, "mutex", None))
        self.mutex = self.handle = None

    @contextlib.contextmanager
    def _held(self):
        """The keyed mutex of `copy`, held while commands that read or write it are issued."""
        mutex = getattr(self, "mutex", None)
        taken = bool(mutex) and _call(mutex, 8, 0, _MUTEX_WAIT_MS,
                                      argtypes=(ctypes.c_uint64, ctypes.c_uint)) == 0
        try:
            yield
        finally:
            if taken:
                _call(mutex, 9, 0, argtypes=(ctypes.c_uint64,))

    def changed_since(self, tex_rect, after):
        """True if `tex_rect` may have changed after frame `after`."""
        if after is None or after < self.seq - len(self.history):
            return True
        for seq, rects in reversed(self.history):
            if seq <= after:
                break
            if any(_intersect(tex_rect, r) for r in rects):
                return True
        return False

    def read(self, tex_rect):
        """(BGRA bytes, pitch, w, h) of `tex_rect` from the kept copy."""
        if self._batch_seq == self.seq and tex_rect in self._batch:
            return self._batch[tex_rect]
        if not self.copy or not self.valid or _intersect(tex_rect, self.valid) != tex_rect:
            return None
        l, t, r, b = tex_rect
        w, h = r - l, b - t
        if self.staging_size[0] < w or self.staging_size[1] < h:
            _release(self.staging)
            self.staging = None
            sw, sh = max(w, self.staging_size[0]), max(h, self.staging_size[1])
            self.staging = self._texture(sw, sh, staging=True)
            self.staging_size = (sw, sh)
        with self._held():
            _call(self.context, 46, self.staging, 0, 0, 0, 0, self.copy, 0,
                  ctypes.byref(_BOX(l, t, 0, r, b, 1)),
                  restype=None, argtypes=_COPY_REGION_ARGS)
        mapped = _MAPPED()
        _call(self.context, 14, self.staging, 0, D3D11_MAP_READ, 0, ctypes.byref(mapped),
              argtypes=(_vp, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, _vp), what="Map")
        try:
            pitch = mapped.RowPitch
            data = ctypes.string_at(mapped.pData, pitch * (h - 1) + w * 4)
        finally:
            _call(self.context, 15, self.staging, 0, restype=None,
                  argtypes=(_vp, ctypes.c_uint))
        return data, pitch, w, h

    def read_batch(self, rects):
        """One GPU readback for the active windows, with their pixels kept separate.

        Copy each rectangle into a horizontal atlas, then Map once. Several
        independent Maps stall the immediate context once per widget. No
        scaling, sampling or shared refraction is involved here.
        """
        rects = list(dict.fromkeys(rects))
        if self._batch_seq == self.seq:
            return
        self._batch_seq, self._batch = None, {}
        if len(rects) < 2 or not self.copy or not self.valid:
            return
        if any(_intersect(rect, self.valid) != rect for rect in rects):
            return
        width = sum(r - l for l, t, r, b in rects)
        height = max(b - t for l, t, r, b in rects)
        # Stay inside D3D11 texture limits and bound temporary CPU memory.
        if width > 16384 or height > 16384 or width * height > 16_000_000:
            return
        if self.staging_size[0] < width or self.staging_size[1] < height:
            _release(self.staging)
            self.staging = None
            sw, sh = max(width, self.staging_size[0]), max(height, self.staging_size[1])
            self.staging = self._texture(sw, sh, staging=True)
            self.staging_size = (sw, sh)
        placements, offset = [], 0
        with self._held():
            for l, t, r, b in rects:
                _call(self.context, 46, self.staging, 0, offset, 0, 0, self.copy, 0,
                      ctypes.byref(_BOX(l, t, 0, r, b, 1)),
                      restype=None, argtypes=_COPY_REGION_ARGS)
                placements.append((offset, r - l, b - t))
                offset += r - l
        mapped = _MAPPED()
        _call(self.context, 14, self.staging, 0, D3D11_MAP_READ, 0, ctypes.byref(mapped),
              argtypes=(_vp, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, _vp), what="Map")
        try:
            from PIL import Image
            pitch = mapped.RowPitch
            # Cut each window straight out of the mapped memory: one native
            # copy apiece, not a copy of the whole atlas and then a Python
            # slice for every row while other threads wait for the GIL.
            view = (ctypes.c_char * (pitch * height)).from_address(mapped.pData)
            atlas = Image.frombuffer("RGBA", (pitch // 4, height), view, "raw", "RGBA", pitch, 1)
            for rect, (offset, w, h) in zip(rects, placements):
                self._batch[rect] = (atlas.crop((offset, 0, offset + w, h)).tobytes(), w * 4, w, h)
        finally:
            _call(self.context, 15, self.staging, 0, restype=None,
                  argtypes=(_vp, ctypes.c_uint))
        self._batch_seq = self.seq

# ---------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------

class _Read:
    def __init__(self, rect, after, timeout, pixels=True):
        self.rect = rect
        self.after = after
        self.deadline = time.monotonic() + timeout
        self.done = threading.Event()
        self.result = None
        self.pixels = pixels


class DesktopDuplication:
    """Reads screen rectangles through Desktop Duplication.

    grab() returns (frame, BGRA bytes) once the rectangle has changed since
    `after` (a frame returned earlier, or None for "now"), (frame, None) if
    it has not within `timeout`, and None when duplication is unavailable
    (the caller falls back to GDI).
    """

    def __init__(self):
        self._lock = threading.Lock()       # reads and interest
        self._gpu = threading.RLock()       # outputs, devices, D3D calls
        self._wake = threading.Event()
        self._reads = []
        self._interest = {}        # desktop rect -> last time it was read
        self._outputs = []
        self._devices = []
        self._thread = None
        self._broken_until = 0.0
        self._failures = 0
        self._reset = False
        self._frame_at, self._last_out = 0.0, None
        self._log = None
        self._luids = {}           # reader device -> its adapter's identity
        # Counts the desktop frames received, so that anyone watching
        # several rectangles can wait for "the screen changed" once.

    def _reader_luid(self, device):
        key = _address(device)
        if key not in self._luids:
            dxgi_device = _query(device, IID_IDXGIDevice, "QueryInterface(Device)")
            try:
                self._luids[key] = _device_luid(dxgi_device)
            finally:
                _release(dxgi_device)
        return self._luids[key]

    def gpu_source(self, rect, device):
        """(output, texture rectangle) when the desktop rectangle `rect` (x, y, w, h) can be copied on the
        GPU into a texture of `device`: one unrotated output that holds it, on the same adapter, whose
        copy of the desktop is shared."""
        l, t, w, h = rect
        want = (l, t, l + w, t + h)
        if not _address(device):
            return None
        with self._gpu:
            found = None
            for out in self._outputs:
                part, tex = out.texture_rect(want)
                if not part:
                    continue
                if (found is not None or part != want or not out.mutex or not out.handle
                        or _untransposer(out.rotation) is not None
                        or not out.copy or not out.valid or _intersect(tex, out.valid) != tex):
                    return None
                found = (out, tex)
            if found is None:
                return None
            try:
                if found[0].luid != self._reader_luid(device):
                    return None
            except (DxgiError, OSError, ValueError):
                return None
            return found

    def copy_region(self, rect, destination, device, context):
        """Copy desktop `rect` into `destination`, a texture of `device`, entirely on the GPU: the
        renderer's own commands, ordered after the capture's by the copy's keyed mutex. The frame
        cursor, or None."""
        with self._gpu:
            got = self.gpu_source(rect, device)
            if got is None:
                return None
            out, (l, t, r, b) = got
            key = _address(device)
            opened = out.opened.get(key)
            try:
                if opened is None:
                    while len(out.opened) >= 8:          # readers that came and went leave their views behind
                        old = out.opened.pop(next(iter(out.opened)))
                        _release(old[1])
                        _release(old[0])
                    texture = _vp()
                    _call(device, 28, _vp(out.handle), ctypes.byref(IID_ID3D11Texture2D),
                          ctypes.byref(texture), argtypes=(_vp, _vp, _vp), what="OpenSharedResource")
                    mutex = _query(texture, IID_IDXGIKeyedMutex, "QueryInterface(KeyedMutex)")
                    opened = out.opened[key] = (texture, mutex)
                texture, mutex = opened
                if _call(mutex, 8, 0, _MUTEX_WAIT_MS,
                         argtypes=(ctypes.c_uint64, ctypes.c_uint)) != 0:
                    return None
                try:
                    _call(context, 46, destination, 0, 0, 0, 0, texture, 0,
                          ctypes.byref(_BOX(l, t, 0, r, b, 1)),
                          restype=None, argtypes=_COPY_REGION_ARGS)
                finally:
                    _call(mutex, 9, 0, argtypes=(ctypes.c_uint64,))
            except DxgiError:
                return None
            return ((out.name, out.seq),)

    def set_logger(self, fn):
        self._log = fn

    def _note(self, text):
        if self._log:
            try:
                self._log(text)
            except Exception:
                pass

    def available(self):
        return time.monotonic() >= self._broken_until

    def reset(self):
        """Drop every duplication and forgive earlier failures, as after a suspend: the outputs and the
        adapter were made for a display set that may no longer exist, and a duplication of one of those can
        stay valid-looking yet never deliver a frame again. The capture thread rebuilds on the next read."""
        self._reset = True
        self._broken_until = 0.0
        self._failures = 0
        self._luids.clear()
        self._wake.set()

    def grab(self, x, y, w, h, after=None, timeout=1.0, pixels=True, interest_rects=None):
        if w <= 0 or h <= 0 or not self.available():
            return None
        read = _Read((x, y, x + w, y + h), after, timeout, pixels)
        with self._lock:
            for rect in interest_rects if interest_rects is not None else (read.rect,):
                self._interest[rect] = time.monotonic()
            if not self._thread or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, daemon=True, name="dxgi-capture")
                self._thread.start()
        try:
            with self._gpu:
                if self._outputs and self._answer(read, final=False):
                    return read.result
                if timeout <= 0 and read.after is not None and self._outputs:
                    # A look that must not wait: nothing new in this
                    # rectangle since `after`, so say so at once. The caller's
                    # own `after` is handed back, so a change this look could
                    # not read yet is still seen by the next one.
                    return (read.after, None)
        except DxgiError:
            pass                        # the capture thread rebuilds
        with self._lock:
            self._reads.append(read)
        self._wake.set()
        if not read.done.wait(timeout + 1.0):
            with self._lock:
                if read in self._reads:
                    self._reads.remove(read)
            return None
        return read.result

    # -- the capture thread ----------------------------------------------

    def _run(self):
        try:
            while True:
                if self._reset:
                    self._reset = False
                    self._teardown()
                with self._lock:
                    now = time.monotonic()
                    for rect, at in list(self._interest.items()):
                        if now - at > _IDLE_RELEASE_SECS:
                            del self._interest[rect]
                    idle = not self._reads and not self._interest
                if idle:
                    self._teardown()
                    self._wake.clear()
                    self._wake.wait()
                    continue
                if not self._outputs:
                    try:
                        self._build()
                        self._failures = 0
                    except Exception as exc:
                        self._teardown()
                        self._fail("Desktop duplication unavailable: %s" % exc)
                        continue
                try:
                    self._serve()
                    self._pump()
                except DxgiError as exc:
                    # Lost desktop (mode change, secure desktop) or device:
                    # rebuild. Pending reads are answered on the new one.
                    self._note("Desktop duplication reset: %s" % exc)
                    self._teardown()
                    time.sleep(0.25)
        except Exception as exc:
            self._teardown()
            self._fail("Desktop duplication stopped: %r" % exc)

    def _fail(self, text):
        self._note(text)
        self._failures += 1
        self._broken_until = time.monotonic() + min(30.0, 0.5 * 2 ** self._failures)
        with self._lock:
            reads, self._reads = self._reads, []
            self._interest.clear()
        for read in reads:
            read.done.set()          # result None: fall back
        time.sleep(0.25)

    def _build(self):
        dxgi = ctypes.WinDLL("dxgi")
        d3d11 = ctypes.WinDLL("d3d11")
        factory = _vp()
        hr = dxgi.CreateDXGIFactory1(ctypes.byref(IID_IDXGIFactory1), ctypes.byref(factory))
        if hr < 0:
            raise DxgiError("CreateDXGIFactory1", hr)
        outputs, devices = [], []
        try:
            index = 0
            while True:
                adapter = _vp()
                hr = _call(factory, 12, index, ctypes.byref(adapter),
                           argtypes=(ctypes.c_uint, _vp))
                if hr == DXGI_ERROR_NOT_FOUND:
                    break
                if hr < 0:
                    raise DxgiError("EnumAdapters1", hr)
                index += 1
                try:
                    self._build_adapter(d3d11, adapter, outputs, devices)
                finally:
                    _release(adapter)
            if not outputs:
                raise OSError("no duplicable outputs")
        except Exception:
            self._close(outputs, devices)
            raise
        finally:
            _release(factory)
        with self._gpu:
            self._outputs, self._devices = outputs, devices

    @staticmethod
    def _build_adapter(d3d11, adapter, outputs, devices):
        device = context = None
        luid = None
        o = 0
        while True:
            output = _vp()
            hr = _call(adapter, 7, o, ctypes.byref(output), argtypes=(ctypes.c_uint, _vp))
            if hr == DXGI_ERROR_NOT_FOUND:
                return
            if hr < 0:
                raise DxgiError("EnumOutputs", hr)
            o += 1
            try:
                desc = _OUTPUT_DESC()
                _call(output, 7, ctypes.byref(desc), argtypes=(_vp,), what="GetDesc")
                if not desc.Attached:
                    continue
                if device is None:
                    device, context = _create_device(d3d11, adapter)
                    devices.append((device, context))
                    luid = _adapter_luid(adapter)
                output1 = _query(output, IID_IDXGIOutput1, "QueryInterface(Output1)")
                try:
                    outputs.append(_Output(device, context, output1, desc, luid))
                finally:
                    _release(output1)
            finally:
                _release(output)

    @staticmethod
    def _close(outputs, devices):
        for out in outputs:
            try:
                out.close()
            except Exception:
                pass
        for device, context in devices:
            _release(context)
            _release(device)

    def _teardown(self):
        with self._gpu:
            outputs, devices = self._outputs, self._devices
            self._outputs, self._devices = [], []
            self._close(outputs, devices)

    def _pump(self):
        """Wait for the screen on every output somebody is reading. (Every frame is taken while anybody is:
        taking one only when a look waits made the glass lag a frame behind and stutter.)"""
        with self._lock:
            rects = list(self._interest)
        active = [out for out in self._outputs
                  if any(out.texture_rect(rect)[1] for rect in rects)]
        if not active:
            self._wake.wait(_ACQUIRE_MS / 1000.0)
            self._wake.clear()
            return
        # The outputs are waited on one after another, so a still one must not hold up a moving one: while any
        # delivers frames, each is only looked at (the one that moved last waits a little); only when all have
        # been still for a while does each wait long.
        now = time.monotonic()
        busy = now - self._frame_at < _BUSY_SECS
        for out in active:
            if not busy:
                wait_ms = max(8, _ACQUIRE_MS // len(active))
            else:
                wait_ms = _BUSY_WAIT_MS if out is self._last_out or len(active) == 1 else 0
            if out.acquire(wait_ms, self._gpu):
                self._frame_at, self._last_out = time.monotonic(), out

    def _serve(self):
        with self._lock:
            reads = list(self._reads)
        with self._gpu:
            for read in reads:
                if not self._answer(read, final=True):
                    continue
                with self._lock:
                    if read in self._reads:
                        self._reads.remove(read)
                read.done.set()

    def _answer(self, read, final):
        """Fill read.result if it can be answered now. GPU lock held.

        A read whose rectangle has not changed is answered "unchanged" only
        by the capture thread (`final`), once its deadline has passed.
        """
        parts = [(out,) + out.texture_rect(read.rect) for out in self._outputs]
        parts = [p for p in parts if p[1]]
        frame = tuple((out.name, out.seq) for out, _, _ in parts)
        after = dict(read.after or ())
        changed = (read.after is None or not parts
                   or any(out.name not in after
                          or out.changed_since(tex, after[out.name])
                          for out, _, tex in parts))
        if changed:
            if not read.pixels:
                if any(not out.copy or out.valid is None or _intersect(tex, out.valid) != tex
                       for out, _, tex in parts):
                    return False
                read.result = (frame, b'')
                return True
            # The first reader of this desktop frame also brings back the
            # other active windows. Their readers reuse their own exact pixels.
            with self._lock:
                interested = list(self._interest)
            for out, _, _ in parts:
                rectangles = [out.texture_rect(rect)[1] for rect in interested]
                out.read_batch([rect for rect in rectangles if rect])
            data = self._compose(read.rect, parts)
            if data is None:
                return False           # the copy is filled on the next frame
            read.result = (frame, data)
            return True
        if final and time.monotonic() >= read.deadline:
            read.result = (frame, None)
            return True
        return False

    @staticmethod
    def _compose(rect, parts):
        """The rectangle as BGRA bytes; black where no output covers it."""
        from PIL import Image
        x, y = rect[0], rect[1]
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        canvas = None
        for out, part, tex in parts:
            got = out.read(tex)
            if got is None:
                return None
            data, pitch, tw, th = got
            if (canvas is None and part == rect and pitch == tw * 4
                    and _untransposer(out.rotation) is None):
                return data              # already tightly packed BGRA
            img = Image.frombuffer("RGBA", (tw, th), data, "raw", "BGRA", pitch, 1)
            turn = _untransposer(out.rotation)
            if turn is not None:
                img = img.transpose(turn)
            if canvas is None and part == rect:
                return img.tobytes("raw", "BGRA")
            if canvas is None:
                canvas = Image.new("RGBA", (w, h), (0, 0, 0, 255))
            canvas.paste(img, (part[0] - x, part[1] - y))
        if canvas is None:
            return bytes(w * h * 4)
        return canvas.tobytes("raw", "BGRA")
