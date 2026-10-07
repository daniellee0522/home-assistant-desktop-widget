"""A global keyboard shortcut (RegisterHotKey), on a thread of its own with its own message loop.

Shortcuts are written as text, "ctrl+alt+h": modifiers (ctrl, alt, shift, win) and one key (a letter,
a digit, f1-f24, or one of the names in _NAMED). "" is no shortcut.
"""
import ctypes
import threading
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
_user32.RegisterHotKey.restype = wintypes.BOOL
_user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
_user32.GetMessageW.restype = wintypes.BOOL
_user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.PostThreadMessageW.restype = wintypes.BOOL
_user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
                                 wintypes.UINT]
_kernel32 = ctypes.WinDLL("kernel32")

WM_HOTKEY = 0x0312
WM_APP_SET = 0x8001           # re-register: the new shortcut is in self._wanted
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
_MODS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN}
_NAMED = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "home": 0x24, "end": 0x23, "insert": 0x2D,
          "delete": 0x2E, "pageup": 0x21, "pagedown": 0x22, "up": 0x26, "down": 0x28, "left": 0x25,
          "right": 0x27, "pause": 0x13}
_ORDER = ("ctrl", "alt", "shift", "win")
DEFAULT = "ctrl+alt+h"
_ID = 1


def parse(text):
    """(modifiers, virtual key) for a shortcut, or None if it is not one (a key with at least one
    modifier other than Shift alone, so a plain key or Shift+letter is never taken from every app)."""
    parts = [p.strip().lower() for p in (text or "").split("+") if p.strip()]
    if len(parts) < 2:
        return None
    mods = 0
    for p in parts[:-1]:
        if p not in _MODS:
            return None
        mods |= _MODS[p]
    key = parts[-1]
    if len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif key in _NAMED:
        vk = _NAMED[key]
    elif key[0] == "f" and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    else:
        return None
    if mods in (0, MOD_SHIFT):
        return None
    return mods, vk


def normalise(text):
    """The shortcut in its one written form ("ctrl+alt+h"), "" for none, or None if it is not one."""
    if not text:
        return ""
    if parse(text) is None:
        return None
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    mods = sorted({"control": "ctrl"}.get(p, p) for p in parts[:-1])
    return "+".join([m for m in _ORDER if m in mods] + [parts[-1]])


def label(text):
    """How a shortcut is shown: "Ctrl + Alt + H"."""
    if not text:
        return ""

    def one(part):
        if len(part) == 1 or (part[0] == "f" and part[1:].isdigit()):
            return part.upper()                      # H, 5, F5
        return part.capitalize()                     # Ctrl, Alt, Space

    return " + ".join(one(p) for p in text.split("+"))


class GlobalHotkey:
    """One shortcut for the whole system: `on_press` is called (on the hotkey thread) when it is pressed."""

    def __init__(self, on_press):
        self.on_press = on_press
        self._wanted = ""
        self._ok = False
        self._answered = threading.Event()
        self._tid = 0
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="hotkey")
        self._thread.start()
        self._ready.wait(2.0)

    def set(self, text):
        """Take this shortcut instead of the last ("" for none). True when it is registered (or none is
        wanted); False when the system refused it, usually because another program has it."""
        self._wanted = normalise(text) or ""
        self._answered.clear()
        if not self._tid or not _user32.PostThreadMessageW(self._tid, WM_APP_SET, 0, 0):
            return False
        self._answered.wait(2.0)
        return self._ok

    def _loop(self):
        msg = wintypes.MSG()
        # A thread has a message queue once it has asked for a message; then it can be posted to.
        _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        self._tid = _kernel32.GetCurrentThreadId()
        self._ready.set()
        registered = False
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_APP_SET:
                if registered:
                    _user32.UnregisterHotKey(None, _ID)
                    registered = False
                parsed = parse(self._wanted)
                if parsed:
                    registered = bool(_user32.RegisterHotKey(None, _ID, parsed[0] | MOD_NOREPEAT, parsed[1]))
                self._ok = registered or not self._wanted
                self._answered.set()
            elif msg.message == WM_HOTKEY and msg.wParam == _ID:
                try:
                    self.on_press()
                except Exception:
                    pass
