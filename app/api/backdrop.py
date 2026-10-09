"""The picture of the desktop behind a window (its glass): read from the screen, cleaned of other programs' windows,
blurred, and answered only when it changed."""

import ctypes
import time
import zlib

from PIL import Image, ImageFilter

from app.capture import BACKDROP_NOISE, compat_capture, desktop_capture, DUPLICATION_WAIT_SECS, screen_duplication
from app.compose import compose_popover_backdrop, composite_rgba_window, grab_widget_rgba, patch_covered
from app.geometry import is_widget_kind, liquid_params, popover_needs_compat
from winsys.capture_pixels import within_noise, within_noise_bgrx
from winsys.scan import nothing_visible_of, window_snapshot, windows_below, windows_over
from winsys.win32 import get_hwnd, rects_overlap, user32, visible_rect


class _Answer(Exception):
    """The answer to a backdrop request, known before the picture is made (raised out of a step)."""

    def __init__(self, reply):
        super().__init__()
        self.reply = reply


class _BackdropJob:
    """One request for a window's backdrop, as it is worked through: what was asked, and what each step found."""

    def __init__(self, kind, window, hwnd, last_hash, wait_secs, defer_pixels, gpu, capture_epoch):
        self.kind, self.window, self.hwnd, self.last_hash = kind, window, hwnd, last_hash
        self.wait_secs, self.defer_pixels, self.gpu = wait_secs, defer_pixels, gpu
        self.capture_epoch = capture_epoch
        self.started = time.perf_counter()
        self.rect = (0, 0, 0, 0)         # (x, y, w, h) the backdrop covers, physical pixels
        self.raw = None                  # its pixels, BGRA
        self.paced = False               # the screen set the pace: ask again straight away
        self.over = ()                   # windows to draw over the wallpaper (compatibility capture)
        self.can_read_screen = self.compose_widget = self.look_over = False
        self.snapshot, self.ours, self.covers = None, (), []


def reduce_backdrop(raw, w, h, liquid, scale, pre_blur):
    """The capture (BGRA, w x h) as the small RGB picture the glass is made from."""
    small = Image.frombuffer("RGBA", (w, h), raw, "raw", "RGBA", 0, 1)
    if liquid:
        if scale == 1:
            # Decode the original capture directly; serialising the full RGBA view first copies every pixel
            # unnecessarily.
            small = Image.frombytes("RGB", (w, h), raw, "raw", "BGRX")
        else:
            small = (small.reduce(2) if not (w % 2 or h % 2) else
                     small.resize((max(1, round(w / 2)), max(1, round(h / 2))), Image.BOX))
            small = Image.frombytes("RGB", small.size, small.tobytes(), "raw", "BGRX")
        if pre_blur:
            small = small.filter(ImageFilter.GaussianBlur(radius=pre_blur))
        if scale > 2:
            small = small.resize((max(1, round(w / scale)), max(1, round(h / scale))), Image.HAMMING)
        return small
    if w % scale or h % scale:
        # Not a whole number of cells: stretch the picture over the window exactly rather than past its edge.
        small = small.resize((max(1, round(w / scale)), max(1, round(h / scale))), Image.BOX)
    else:
        small = small.reduce(scale)
    return Image.frombytes("RGB", small.size, small.tobytes(), "raw", "BGRX")


class BackdropMixin:
    def get_desktop_backdrop(self, window_kind="main", last_hash=None, want_w=0, want_h=0,
                             at_x=None, at_y=None, wait_secs=None, defer_pixels=False, gpu=False):
        """The desktop behind a window, blurred, as a small raw-pixel picture
        (RGB bytes in "blur_raw", "blur_w" x "blur_h").

        `last_hash` is the window's previous frame; an identical capture is
        answered with {"unchanged": True} and costs no encoding.
        `want_w`/`want_h` are the device-pixel size the window draws at,
        used when it differs from the window by more than rounding (fixed
        size, zoom). `at_x`/`at_y` capture where a dragged window is going
        rather than where it still is.
        """
        if window_kind == "settings":
            # A solid panel: no backdrop to take, and no capture to pay for.
            return {"skip": True, "retry_ms": 60000}
        if window_kind == "flyout" and self._panel_bg_path():
            # The panel has a picture of its own behind it.
            return {"skip": True, "retry_ms": 60000}
        window = self._window_for(window_kind)
        hwnd = get_hwnd(window) if window else None
        if not hwnd:
            return None
        # Nothing to paint for a window that is hidden or fully covered -
        # which is most of the time, and most of the program's idle cost. A
        # window being armed is the exception (see _arm_backdrop).
        if window_kind != self._arming_kind:
            skipped = self._hidden_answer(window_kind, hwnd)
            if skipped:
                return skipped
        if self._system_glass_on(window_kind):
            return {"skip": True, "retry_ms": 1000, "system_glass": True}
        if is_widget_kind(window_kind) and time.monotonic() < self._capture_transition_until:
            return {"skip": True, "retry_ms": 80}
        job = _BackdropJob(window_kind, window, hwnd, last_hash, wait_secs, defer_pixels, gpu,
                           self._capture_epoch)
        try:
            job.rect = self._capture_rect(hwnd, want_w, want_h, at_x, at_y)
            self._plan_backdrop(job)
            if job.can_read_screen or job.compose_widget:
                self._duplicate_screen(job)
            self._complete_backdrop(job)
            return (lambda: self._backdrop_pixels(job)) if defer_pixels else self._backdrop_pixels(job)
        except _Answer as answer:
            return answer.reply
        except Exception:
            return None

    def _plan_backdrop(self, job):
        """What this request may read and which windows need laying over it (sets the job's `over`,
        `can_read_screen`, `compose_widget`, `look_over`, `snapshot`, `ours` and `covers`)."""
        kind, hwnd = job.kind, job.hwnd
        x, y, w, h = job.rect
        area = (x, y, x + w, y + h)
        # Our own windows beneath an overlay, to draw into its backdrop.
        job.over = ()
        if kind in ("popover", "settings"):
            below = []
            for other in (*self._widget_kinds(), "flyout"):
                win = self._window_for(other)
                below_hwnd = get_hwnd(win) if win else None
                below_rect = visible_rect(win) if below_hwnd else None
                if below_rect and rects_overlap(below_rect, area):
                    below.append(below_hwnd)
            job.over = tuple(below)
        # A window may read the screen only while it is excluded from capture, or it reads itself back in.
        # Toggling the exclusion around each read does not work: DWM applies it on its next composition.
        job.can_read_screen = kind in self._excluded_kinds
        # A liquid-mode popover over the (still excluded) widget composes the widget itself; see
        # _apply_capture_exclusion.
        job.compose_widget = popover_needs_compat(kind, self._cfg.get("glass_style"), self._excluded_kinds,
                                                  job.over, self._popover_owner)
        if job.compose_widget:
            job.can_read_screen = False
        if kind == "flyout" and not job.can_read_screen:
            # Compatibility mode cannot read a screen containing itself; render the windows beneath the panel
            # over the wallpaper.
            from nativeui import dcomp
            helper = dcomp._state["slider"]
            job.over = tuple(o for o in windows_below(hwnd, area) if helper is None or o != helper.hwnd)
        # Other programs' windows over a widget show in a picture of the screen; looked for on both sides of the
        # wait for a frame, as one moving could be anywhere between the two.
        job.look_over = is_widget_kind(kind) and job.can_read_screen and not job.compose_widget
        shared = self._shared_windows if job.look_over else None
        job.snapshot = shared[0] if shared else None
        job.ours = (shared[1] if shared else self._own_hwnds()) if job.look_over else ()
        job.covers = windows_over(hwnd, area, job.ours, job.snapshot) if job.look_over else []

    def _unchanged_reply(self, job):
        if job.capture_epoch != self._capture_epoch:
            return {"skip": True, "retry_ms": 80}
        return {"unchanged": True, "hash": job.last_hash, "paced": True, "system_glass": False}

    def _duplicate_screen(self, job):
        """Read the screen under the window through Desktop Duplication (GDI only if it is unavailable): the
        pixels go to `job.raw`, and when the answer is already known (unchanged, or a copy on the GPU) it is
        raised as an _Answer."""
        kind = job.kind
        x, y, w, h = job.rect
        # Answered when the screen under the window changes, at the display's own rate.
        seen = self._duplication_after.get(kind)
        after = seen[1] if seen and seen[0] == job.rect and job.last_hash is not None else None
        if job.compose_widget:
            # The widget drawn into this frame changes on its own, so the screen under it cannot set the pace.
            after = None
        direct = (self._gpu_direct_frame(job.window, kind, job.rect, job.last_hash)
                  if job.look_over and not job.covers and job.defer_pixels and kind != "popover" else None)
        if direct is None and job.gpu and kind == "flyout" and job.can_read_screen and not job.compose_widget:
            direct = self._flyout_direct(job.rect)
            direct = None if direct is None else (direct, 1)
        if direct is not None:
            # The picture never leaves the GPU: only whether it changed is asked here. A widget's batch has
            # waited for the screen already; the panel waits here, and is answered the moment the screen
            # changes instead of polling it.
            got = screen_duplication.grab(x, y, w, h, after, 0 if job.defer_pixels else 0.1, pixels=False)
            if got is not None:
                self._duplication_after[kind] = (job.rect, got[0])
                if got[1] is None:
                    raise _Answer(self._unchanged_reply(job))
                if is_widget_kind(kind):
                    # A popover over this widget composes the picture only when it opens.
                    self._widget_frames[kind] = (
                        x, y, w, h, lambda: (screen_duplication.grab(x, y, w, h, None, 0.2) or (None, None))[1])
                raise _Answer(dict(gpu=(x, y, w, h), copy=screen_duplication.copy_region, pre_blur=direct[0],
                                   divide=direct[1], w=w, h=h, system_glass=False, paced=True, hash=hash(got[0]) & 0x7FFFFFFF,
                                   ms=(time.perf_counter() - job.started) * 1000))
        got = screen_duplication.grab(x, y, w, h, after,
                                      DUPLICATION_WAIT_SECS if job.wait_secs is None else job.wait_secs)
        if got is not None:
            job.paced = not job.compose_widget
            self._duplication_after[kind] = (job.rect, got[0])
            if got[1] is None:
                raise _Answer(self._unchanged_reply(job))
            job.raw = got[1]
            return
        if kind == "flyout" and seen is not None and screen_duplication.available():
            # A live source may temporarily rebuild or have no frame. GDI treats excluded layered windows
            # differently, so swapping to it for one update flashes the material. Keep the last valid picture
            # and retry the same source. Its frame counter can restart after a rebuild: request a fresh frame
            # next time.
            self._duplication_after[kind] = (job.rect, None)
            raise _Answer({"skip": True, "retry_ms": 16, "paced": True})
        self._duplication_after.pop(kind, None)
        job.raw = desktop_capture.grab_screen(x, y, w, h)

    def _complete_backdrop(self, job):
        """From the screen's pixels to the picture the window stands on: our windows laid over it where they
        belong, other programs' windows taken out of it. Leaves it in `job.raw`."""
        kind = job.kind
        x, y, w, h = job.rect
        owner_window = self._window_for(self._popover_owner) or self._window
        raw, widget = job.raw, None
        if raw and job.compose_widget:
            widget = grab_widget_rgba(owner_window)
            frame = self._widget_frames.get(self._popover_owner)
            raw = compose_popover_backdrop(raw, job.rect, frame, widget) if frame and widget else None
        if raw is None:
            # The fast path is off, unusable here, or failed.
            main_hwnd = get_hwnd(owner_window)
            raw = compat_capture.grab(x, y, w, h, tuple(o for o in job.over if o != main_hwnd)
                                      if job.compose_widget else job.over)
            if raw and job.compose_widget:
                widget = widget or grab_widget_rgba(owner_window)
                if widget:
                    image, rect = widget
                    raw = composite_rgba_window(raw, (w, h), image, (rect[0] - x, rect[1] - y))
                else:
                    raw = compat_capture.grab(x, y, w, h, job.over)
        if not raw:
            raise _Answer(None)
        if kind == "flyout" and job.can_read_screen:
            # Widgets stay excluded while the panel opens. Compose their native/GPU snapshots into the panel
            # only, without restarting the widgets' capture or compositor.
            for other in self._widget_kinds() or ["main"]:
                if other in self._excluded_kinds:
                    under = self._widget_under(other, (x, y, x + w, y + h))
                    if under:
                        image, rect = under
                        raw = composite_rgba_window(raw, (w, h), image, (rect[0] - x, rect[1] - y))
        if job.capture_epoch != self._capture_epoch:
            raise _Answer({"skip": True, "retry_ms": 80})
        if job.look_over:
            raw = self._without_windows_over(kind, job.hwnd, job.rect, raw, job.covers, job.ours, job.snapshot)
            if raw is None:
                # Never publish an occluding app as the widget's glass when the clean wallpaper source is
                # temporarily unavailable.
                raise _Answer({"skip": True, "retry_ms": 80})
        if is_widget_kind(kind) and job.can_read_screen:
            self._widget_frames[kind] = (x, y, w, h, raw)
        job.raw = raw

    def _backdrop_pixels(self, job):
        """The picture sent to the window: the capture reduced and blurred as its glass style wants, or
        {"unchanged": True} when it differs from the one on screen by less than the eye can tell."""
        kind, last_hash = job.kind, job.last_hash
        w, h = job.rect[2:]
        liquid = self._cfg.get("glass_style") == "liquid" and kind != "popover"
        # Clear liquid keeps the original desktop resolution. Frosted liquid progressively reduces the source,
        # with an anti-aliasing prefilter; the window's full-resolution lens applies the frost.
        level = max(0, min(100, int(self._cfg.get("liquid_blur", 0)))) / 100.0
        scale, pre_blur, post_blur = liquid_params(level) if liquid else (8, 0, 2)
        if liquid and scale == 1 and getattr(getattr(job.window, "native", None), "_gpu_shared_capture", False):
            return self._direct_backdrop_pixels(job, pre_blur)
        small = reduce_backdrop(job.raw, w, h, liquid, scale, pre_blur)
        sent = self._backdrop_sent.get(kind)
        if (last_hash is not None and sent and sent[0] == int(last_hash)
                and within_noise(sent[1], small, BACKDROP_NOISE)):
            return {"unchanged": True, "hash": int(last_hash), "ms": (time.perf_counter() - job.started) * 1000.0,
                    "paced": job.paced, "system_glass": False}
        blur_raw = small.tobytes()
        digest = zlib.crc32(blur_raw) & 0xFFFFFFFF
        self._backdrop_sent[kind] = (digest, small)
        # Blurring the source avoids the dark wedges a canvas blur leaves in rounded corners by sampling past
        # its edges.
        if post_blur:
            small = small.filter(ImageFilter.GaussianBlur(radius=post_blur))
            blur_raw = small.tobytes()
        if job.capture_epoch != self._capture_epoch:
            return {"skip": True, "retry_ms": 80}
        # Raw pixels, not an image file: a JPEG this small, stretched back up to the window, shows its 8x8
        # blocks as mottling, and a file needs decoding (and leaves memory behind) for a few KB of data.
        return {
            "system_glass": False,
            "blur_raw": blur_raw,
            "pixel_format": "RGB",
            "blur_w": small.size[0],
            "blur_h": small.size[1],
            "w": w,
            "h": h,
            "hash": digest,
            # The capture's own cost; the window paces itself from this.
            "ms": (time.perf_counter() - job.started) * 1000.0,
            # The screen set the pace; ask again straight away.
            "paced": job.paced,
        }

    def _direct_backdrop_pixels(self, job, pre_blur):
        """Clear liquid glass of a window that blurs on its GPU: the capture goes as it is (BGRX)."""
        kind, last_hash, raw = job.kind, job.last_hash, job.raw
        w, h = job.rect[2:]
        sent = self._backdrop_direct.get(kind)
        if (last_hash is not None and sent and sent[0] == int(last_hash) and sent[1] == (w, h)
                and within_noise_bgrx(sent[2], raw, (w, h), BACKDROP_NOISE, pre_blur)):
            return {"unchanged": True, "hash": int(last_hash), "paced": job.paced}
        digest = zlib.crc32(raw) & 0xFFFFFFFF
        if job.capture_epoch != self._capture_epoch:
            return {"skip": True, "retry_ms": 80}
        self._backdrop_direct[kind] = (digest, (w, h), raw)
        return dict(blur_raw=raw, pixel_format="BGRX", pre_blur=pre_blur, blur_w=w, blur_h=h, w=w, h=h,
                    hash=digest, paced=job.paced, system_glass=False,
                    ms=(time.perf_counter() - job.started) * 1000)

    def _flyout_direct(self, rect):
        """0.0 when the panel's material may take the desktop straight from the GPU: it runs on the compositor
        (liquid glass), no widget lies under the panel (those are drawn into its picture on the processor),
        and the screen's duplication can copy that rectangle to the compositor's device."""
        from nativeui import dcomp
        helper = dcomp._state["slider"]
        if (helper is None or helper.material is None or not helper.shown
                or time.monotonic() < helper.direct_after or self._cfg.get("glass_style") != "liquid"):
            return None
        x, y, w, h = rect
        area = (x, y, x + w, y + h)
        for kind in self._widget_kinds() or ["main"]:
            if kind in self._excluded_kinds:
                window = self._window_for(kind)
                shown = visible_rect(window) if window else None
                if shown and rects_overlap(shown, area):
                    return None
        return 0.0 if screen_duplication.gpu_source(rect, helper.device) else None

    def _widget_under(self, kind, area):
        """A widget's picture (as grab_widget_rgba) for the panel's backdrop, only if it is under `area`.
        Taking it reads a GPU widget back on the GUI thread, so a picture of a widget that has not drawn
        since, or less than 60 ms old, is used again, and widgets the panel does not cover cost nothing."""
        window = self._window_for(kind)
        rect = visible_rect(window) if window else None
        if not rect or not rects_overlap(rect, area):
            return None
        snaps = self._widget_snaps
        receiver = getattr(getattr(window, "native", None), "_gpu_receiver", None)
        frames = getattr(receiver, "frames", None)
        now = time.monotonic()
        kept = snaps.get(kind)
        if (kept and kept[3] == rect and kept[2] is not None
                and ((frames is not None and kept[1] == frames) or now - kept[0] < 0.06)):
            return kept[2]
        widget = grab_widget_rgba(window)
        snaps[kind] = (now, frames, widget, rect)
        return widget

    def _gpu_direct_frame(self, window, kind, rect, last_hash):
        """(the picture's pre-blur, how much smaller its frost is blurred) when this widget may take the desktop
        straight from the GPU, else None. Any glass of a widget with its own compositor, on the screen whose
        duplication shares that compositor's device: the classic glass is made from the whole desktop picture
        there, and the liquid glass shrinks its frost itself (the processor used to, before sending it)."""
        native = getattr(window, "native", None)
        receiver = getattr(native, "_gpu_receiver", None)
        if (receiver is None or receiver.compositor is None or not native._gpu_shared_capture
                or time.monotonic() < getattr(native, "_gpu_direct_after", 0)):
            return None
        if self._cfg.get("glass_style") == "liquid":
            level = max(0, min(100, int(self._cfg.get("liquid_blur", 0)))) / 100.0
            divide, pre_blur, _ = liquid_params(level)
        else:
            divide, pre_blur = 1, 0
        if not screen_duplication.gpu_source(rect, receiver.compositor.device):
            return None
        return pre_blur, divide

    def _without_windows_over(self, kind, hwnd, rect, raw, covers, ours, snapshot=None):
        """A widget's picture of the screen with other programs' windows over it replaced by the desktop:
        from its last clean picture, or the wallpaper when it has none yet. The picture becomes the clean one."""
        x, y, w, h = rect
        covers = covers + windows_over(hwnd, (x, y, x + w, y + h), ours, snapshot)
        if covers:
            kept = self._clean_backdrops.get(kind)
            clean = kept[1] if kept and kept[0] == rect else compat_capture.grab(x, y, w, h)
            if not clean or len(clean) != len(raw):
                return None                       # keep the last glass; retry a clean capture
            raw = patch_covered(raw, rect, covers, clean)
        self._clean_backdrops[kind] = (rect, raw)
        return raw

    @staticmethod
    def _capture_rect(hwnd, want_w=0, want_h=0, at_x=None, at_y=None):
        """(x, y, w, h) of what a window's backdrop covers, physical pixels."""
        r = (ctypes.c_long * 4)()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        x, y, w, h = r[0], r[1], r[2] - r[0], r[3] - r[1]
        if at_x is not None and at_y is not None:
            try:
                x, y = int(at_x), int(at_y)
            except Exception:
                pass
        if want_w and want_h:
            want_w, want_h = max(1, int(want_w)), max(1, int(want_h))
            # Within a few pixels the window's own arithmetic is just
            # rounding, and the window's real size is the accurate one.
            if abs(want_w - w) > 3 or abs(want_h - h) > 3:
                w, h = want_w, want_h
        return x, y, w, h

    def _hidden_answer(self, kind, hwnd):
        """{"skip": ...} when the window is hidden or entirely covered. For a
        widget the answer is reused for a moment: looking costs a couple of
        dozen hit tests, and a watcher asks every frame."""
        widget = is_widget_kind(kind)
        now = time.monotonic()
        if widget:
            cached = self._hidden_cache.get(kind)
            if cached and now < cached[0]:
                return cached[1]
        answer = None
        if not user32.IsWindowVisible(hwnd):
            answer = {"skip": True, "retry_ms": 1000}
        elif nothing_visible_of(hwnd, self._own_hwnds()):
            # Covered: looked at again soon, for the glass to be back within a moment of the cover going.
            answer = {"skip": True, "retry_ms": 100}
        if widget:
            self._hidden_cache[kind] = (now + (0.08 if answer and answer["retry_ms"] < 400 else 0.25), answer)
        return answer

    def gpu_widget_glass_allowed(self, kind):
        # Compatibility capture must remain visible in recordings. Only the
        # explicitly excluded liquid widgets use an excluded GPU visual.
        return is_widget_kind(kind) and kind in self._excluded_kinds

    def widget_glass_frames(self, requests, after=None, defer=False):
        """Wait once, then sample all GPU widgets from one immutable desktop frame.

        Zero-wait per-window reads while holding the duplication's GPU lock
        cannot block waiting for a future frame. Existing occlusion filtering,
        hashes, capture exclusion and compatibility fallback still apply.
        """
        rects = []
        for kind, last_hash, w, h in requests:
            window = self._window_for(kind)
            hwnd = get_hwnd(window) if window else None
            if hwnd:
                x, y, w, h = self._capture_rect(hwnd, w, h)
                rects.append((x, y, x + w, y + h))
        if not rects:
            return None, [None] * len(requests)
        x, y = min(r[0] for r in rects), min(r[1] for r in rects)
        right, bottom = max(r[2] for r in rects), max(r[3] for r in rects)
        source_after = after[1] if after and after[0] == tuple(rects) else None
        if any(digest is None for _, digest, _, _ in requests):
            source_after = None
        got = screen_duplication.grab(x, y, right-x, bottom-y, source_after, .5,
                                       pixels=False, interest_rects=rects)
        if got is None:
            return None, [self.get_desktop_backdrop(kind, digest, w, h, None, None, 0)
                          for kind, digest, w, h in requests]
        with screen_duplication._gpu:
            # A frame may arrive between wakeup and this lock. The cursor
            # describes the exact kept copy all the following reads observe.
            frame = tuple((out.name, out.seq) for out in screen_duplication._outputs
                          if any(out.texture_rect(rect)[1] for rect in rects))
            shots = []
            # The desktop's windows are looked at once for every widget of this frame.
            try:
                self._shared_windows = (window_snapshot(), self._own_hwnds())
            except Exception:
                self._shared_windows = None
            try:
                for kind, digest, w, h in requests:
                    shots.append(self.get_desktop_backdrop(kind, digest, w, h, None, None, 0, True))
            finally:
                self._shared_windows = None
        if defer:
            # The caller finishes these while this thread waits for the next
            # desktop frame, so a slow filter pass never delays the capture.
            return (tuple(rects), frame), shots
        # Read all source rectangles under one GPU lock, then release it before
        # CPU filters run. Native Pillow filters release the GIL, so independent
        # widgets can prepare the same desktop frame concurrently.
        from concurrent.futures import ThreadPoolExecutor
        pool = self._backdrop_pool
        if pool is None:
            pool = self._backdrop_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='glass-pixels')
        def finish(shot):
            try:
                return shot() if callable(shot) else shot
            except Exception:
                return None
        if int(self._cfg.get('liquid_blur', 0)) > 0 and len(shots) > 1:
            shots = list(pool.map(finish, shots))
        else:
            finished = []
            for shot in shots:
                finished.append(finish(shot))
                if len(shots) > 1:
                    time.sleep(0)  # let the GUI submit the preceding frame
            shots = finished
        return (tuple(rects), frame), shots

    widget_glass_clock_paced = True

    widget_glass_deferred = True

    flyout_gpu_backdrop = True        # get_desktop_backdrop("flyout", ..., gpu=True) may answer with a GPU copy
