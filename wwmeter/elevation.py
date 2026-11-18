"""Whether a process runs as administrator (elevated), Waveband's own and the game's.

It matters for the keybinds. While a window that runs as administrator is in front, Windows gives
a program that does not only the keys held with Ctrl or Alt: F8 or Shift+F8 alone never reach it,
so nobody can read what is typed into such a window. Wuthering Waves runs as administrator, so
Waveband's keys need Ctrl or Alt, unless Waveband runs as administrator too.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_TOKEN_QUERY = 0x8
_TOKEN_ELEVATION = 20  # TOKEN_INFORMATION_CLASS.TokenElevation
_ERROR_ACCESS_DENIED = 5

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_kernel32.OpenProcess.restype = wt.HANDLE
_kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_kernel32.GetCurrentProcess.restype = wt.HANDLE
_kernel32.CloseHandle.argtypes = [wt.HANDLE]
_advapi32.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
_advapi32.GetTokenInformation.argtypes = [
    wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD),
]


def _token_elevated(process: int) -> bool | None:
    """True or False from the process's token; None when the token can't be read."""
    token = wt.HANDLE()
    if not _advapi32.OpenProcessToken(process, _TOKEN_QUERY, ctypes.byref(token)):
        return None
    try:
        elevated = wt.DWORD()
        size = wt.DWORD()
        if not _advapi32.GetTokenInformation(
            token, _TOKEN_ELEVATION, ctypes.byref(elevated), ctypes.sizeof(elevated), ctypes.byref(size)
        ):
            return None
        return bool(elevated.value)
    finally:
        _kernel32.CloseHandle(token)


def this_process() -> bool:
    """Whether Waveband itself runs as administrator."""
    return bool(_token_elevated(_kernel32.GetCurrentProcess()))


def process(pid: int) -> bool | None:
    """Whether the process ``pid`` runs as administrator. None when it can't be told (gone)."""
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        elevated = _token_elevated(handle)
        if elevated is None and ctypes.get_last_error() == _ERROR_ACCESS_DENIED:
            # A program of the same user that won't show its token to this one runs above it:
            # as administrator.
            return True
        return elevated
    finally:
        _kernel32.CloseHandle(handle)


def window(hwnd: int) -> bool | None:
    """Whether the process that owns a window runs as administrator."""
    pid = wt.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(wt.HWND(hwnd), ctypes.byref(pid))
    return process(pid.value) if pid.value else None
