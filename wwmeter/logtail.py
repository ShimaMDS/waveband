"""Follow Client.log as the game writes and rotates it."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pywintypes
import win32con
import win32file

from . import logcodec

# Lines the renderer spams by the thousand per second; dropped before any parsing.
NOISE = (
    b"Niagara Parameter Not Assigned",
    b"Capture scene color",
    b"SparseVolumeTexture",
)

_SHARE_ALL = win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE
_CHUNK = 4 * 1024 * 1024


def is_noise(line: bytes) -> bool:
    return any(marker in line for marker in NOISE)


class LogTail:
    """Yields decoded, noise-filtered lines appended to a log file.

    The file is opened with every share flag, including delete: the game rotates the log by
    renaming it, and a handle without delete sharing would make that rename fail.
    """

    def __init__(self, path: str, from_start: bool = False) -> None:
        self.path = path
        self._handle = None
        self._ino = None
        self._pos = 0
        self._partial = b""
        self._table = logcodec.DECODE
        self._from_start = from_start
        self.bytes_read = 0

    def close(self) -> None:
        if self._handle is not None:
            self._handle.Close()
            self._handle = None

    def _open(self, from_start: bool) -> bool:
        try:
            handle = win32file.CreateFile(
                self.path, win32con.GENERIC_READ, _SHARE_ALL, None, win32con.OPEN_EXISTING, 0, None
            )
            ino = os.stat(self.path).st_ino
        except (pywintypes.error, OSError):
            return False
        _, head = win32file.ReadFile(handle, 16)
        self._table = logcodec.detect_table(bytes(head))
        if from_start:
            pos = 0
        else:
            pos = win32file.GetFileSize(handle)
        win32file.SetFilePointer(handle, pos, win32con.FILE_BEGIN)
        self._handle, self._ino, self._pos, self._partial = handle, ino, pos, b""
        return True

    def _rotated(self) -> bool:
        try:
            st = os.stat(self.path)
        except OSError:
            return False  # mid-rename; the new file is not there yet
        return st.st_ino != self._ino or st.st_size < self._pos

    def poll(self) -> list[str]:
        """Return the complete lines written since the last call."""
        if self._handle is None:
            if not self._open(self._from_start):
                return []
            self._from_start = True  # anything opened later is a fresh file: read all of it
        out: list[str] = []
        while True:
            try:
                _, chunk = win32file.ReadFile(self._handle, _CHUNK)
            except pywintypes.error:
                chunk = b""
            if not chunk:
                if self._rotated():
                    self.close()
                    if self._open(True):
                        continue
                break
            self._pos += len(chunk)
            self.bytes_read += len(chunk)
            data = self._partial + bytes(chunk).translate(self._table)
            lines = data.split(b"\n")
            self._partial = lines.pop()
            for raw in lines:
                if raw and not is_noise(raw):
                    out.append(raw.rstrip(b"\r").decode("utf-8", errors="replace").lstrip("﻿"))
            if len(chunk) < _CHUNK:
                # drained for now; a rotation is picked up on the next poll
                if not self._rotated():
                    break
        return out


def scan_file(path: str, markers: tuple[str, ...]) -> list[str]:
    """Decoded lines of a log file that contain any of ``markers``, oldest first.

    For catching up on a log that is already being written: the file is opened with the same
    share flags as the tail, so reading the live Client.log cannot block the game's rotation.
    """
    try:
        handle = win32file.CreateFile(
            path, win32con.GENERIC_READ, _SHARE_ALL, None, win32con.OPEN_EXISTING, 0, None
        )
    except pywintypes.error:
        return []
    chunks = []
    try:
        while True:
            _, chunk = win32file.ReadFile(handle, _CHUNK)
            if not chunk:
                break
            chunks.append(bytes(chunk))
    except pywintypes.error:
        pass
    finally:
        handle.Close()
    data = b"".join(chunks)
    wanted = tuple(marker.encode("utf-8") for marker in markers)
    out = []
    for raw in data.translate(logcodec.detect_table(data[:16])).split(b"\n"):
        if any(marker in raw for marker in wanted):
            out.append(raw.rstrip(b"\r").decode("utf-8", errors="replace").lstrip("﻿"))
    return out


def read_file(path: str) -> Iterator[str]:
    """Decode a whole log file (live or backup) and yield its non-noise lines."""
    with open(path, "rb") as fh:
        data = fh.read()
    table = logcodec.detect_table(data[:16])
    for raw in data.translate(table).split(b"\n"):
        if raw and not is_noise(raw):
            yield raw.rstrip(b"\r").decode("utf-8", errors="replace").lstrip("﻿")
