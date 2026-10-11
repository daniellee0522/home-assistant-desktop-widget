"""A secret kept in the settings file, sealed for this Windows user with DPAPI (the same protection the system gives a
saved Wi-Fi password): the file can be copied, backed up or read by another program without the token being in it, but
only this user on this computer can open it again. Imports nothing of ours.

    sealed = seal("token")            # "dpapi:..." (None where DPAPI is not available)
    unseal(sealed)                    # "token"; None when it cannot be opened (another user, another computer, damaged)
"""
import base64
import ctypes
import sys
from ctypes import wintypes

PREFIX = "dpapi:"
_ENTROPY = b"ha-widgets/settings"          # not a secret: it only keeps another program's sealed text from opening here by chance


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data):
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _crypt(function, data):
    """`function` (CryptProtectData or CryptUnprotectData) applied to bytes; None when it fails."""
    if sys.platform != "win32":
        return None
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    kernel32.LocalFree.argtypes, kernel32.LocalFree.restype = [ctypes.c_void_p], ctypes.c_void_p
    source, keep = _blob(data)
    entropy, keep_entropy = _blob(_ENTROPY)
    out = _Blob()
    call = getattr(crypt32, function)
    call.restype = wintypes.BOOL
    ok = call(ctypes.byref(source), None, ctypes.byref(entropy), None, None, 0, ctypes.byref(out))
    if not ok:
        return None
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def sealed(text):
    """Is `text` something `seal` made?"""
    return isinstance(text, str) and text.startswith(PREFIX)


def seal(text):
    """`text` sealed for this user as "dpapi:<base64>", or None where that cannot be done (the caller then keeps it as it is)."""
    if not text:
        return text
    raw = _crypt("CryptProtectData", text.encode("utf-8"))
    return None if raw is None else PREFIX + base64.b64encode(raw).decode("ascii")


def unseal(value):
    """The text inside `value` (made by `seal`), or None when it cannot be opened."""
    if not sealed(value):
        return None
    try:
        raw = _crypt("CryptUnprotectData", base64.b64decode(value[len(PREFIX):], validate=True))
        return None if raw is None else raw.decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
