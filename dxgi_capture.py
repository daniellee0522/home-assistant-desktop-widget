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

    def __init__(self, device, context, output1, desc):
        self.context = context
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
        for attr in ("staging", "copy", "dup"):
            _release(getattr(self, attr))
            setattr(self, attr, None)

    def _texture(self, w, h, staging):
        desc = _TEX2D_DESC(w, h, 1, 1, DXGI_FORMAT_B8G8R8A8_UNORM, 1, 0,
                           D3D11_USAGE_STAGING if staging else D3D11_USAGE_DEFAULT,
                           0, D3D11_CPU_ACCESS_READ if staging else 0, 0)
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
            _release(self.copy)
            self.copy = None
            self.copy = self._texture(tw, th, staging=False)
            self.copy_size = (tw, th)
            self.valid = None
        whole = (0, 0, tw, th)
        boxes = [whole] if self.valid is None else [
            hit for hit in (_intersect(r, whole) for r in changed) if hit]
        for l, t, r, b in boxes:
            _call(self.context, 46, self.copy, 0, l, t, 0, frame, 0,
                  ctypes.byref(_BOX(l, t, 0, r, b, 1)),
                  restype=None, argtypes=_COPY_REGION_ARGS)
        self.valid = whole

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

# ---------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------

class _Read:
    def __init__(self, rect, after, timeout):
        self.rect = rect
        self.after = after
        self.deadline = time.monotonic() + timeout
        self.done = threading.Event()
        self.result = None


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
        self._log = None
        # Counts the desktop frames received, so that anyone watching
        # several rectangles can wait for "the screen changed" once.

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

    def grab(self, x, y, w, h, after=None, timeout=1.0):
        if w <= 0 or h <= 0 or not self.available():
            return None
        read = _Read((x, y, x + w, y + h), after, timeout)
        with self._lock:
            self._interest[read.rect] = time.monotonic()
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
                output1 = _query(output, IID_IDXGIOutput1, "QueryInterface(Output1)")
                try:
                    outputs.append(_Output(device, context, output1, desc))
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
        """Wait for the screen on every output somebody is reading, while a read waits. With none waiting no
        frame is taken: duplication keeps what changed until the next one is (its dirty rectangles add up),
        so nothing is missed, and an animated desktop is not copied at the monitor's rate (60-144 a second)
        for windows that look a few times a second."""
        with self._lock:
            rects = list(self._interest)
            waiting = bool(self._reads)
        if not waiting:
            self._wake.wait(_ACQUIRE_MS / 1000.0)
            self._wake.clear()
            return
        active = [out for out in self._outputs
                  if any(out.texture_rect(rect)[1] for rect in rects)]
        if not active:
            self._wake.wait(_ACQUIRE_MS / 1000.0)
            self._wake.clear()
            return
        # Shared between the outputs, so none waits on another for long.
        wait_ms = max(8, _ACQUIRE_MS // len(active))
        for out in active:
            out.acquire(wait_ms, self._gpu)

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
