"""Grab frames of the game window.

Only window enumeration and bitmap copies are used. The game process is never opened, read or
sent input.
"""

from __future__ import annotations

import ctypes
import time

import numpy as np
import win32api
import win32con
import win32gui
import win32ui

GAME_WINDOW_CLASS = "UnrealWindow"
GAME_TITLE_PREFIX = "Wuthering Waves"

_user32 = ctypes.windll.user32
_PW_CLIENTONLY = 1
_PW_RENDERFULLCONTENT = 2


def set_dpi_aware() -> None:
    """Make window coordinates real pixels. Safe to call more than once."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except OSError:
        pass  # already set for this process


def find_game_window() -> int | None:
    found: list[int] = []

    def visit(hwnd: int, _: object) -> bool:
        if (
            win32gui.IsWindowVisible(hwnd)
            and win32gui.GetClassName(hwnd) == GAME_WINDOW_CLASS
            and win32gui.GetWindowText(hwnd).startswith(GAME_TITLE_PREFIX)
        ):
            found.append(hwnd)
        return True

    win32gui.EnumWindows(visit, None)
    return found[0] if found else None


def client_rect_on_screen(hwnd: int) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) of the window's client area in virtual-screen pixels."""
    _, _, width, height = win32gui.GetClientRect(hwnd)
    left, top = win32gui.ClientToScreen(hwnd, (0, 0))
    return left, top, left + width, top + height


class _PrintWindowBackend:
    """Asks DWM for the window's content. Works while occluded, but costs ~50 ms at 1440p."""

    name = "printwindow"

    def grab(self, hwnd: int, rect: tuple[int, int, int, int]) -> np.ndarray | None:
        width, height = rect[2] - rect[0], rect[3] - rect[1]
        if width <= 0 or height <= 0:
            return None
        hdc = win32gui.GetWindowDC(hwnd)
        src = win32ui.CreateDCFromHandle(hdc)
        mem = src.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        try:
            bmp.CreateCompatibleBitmap(src, width, height)
            mem.SelectObject(bmp)
            if not _user32.PrintWindow(hwnd, mem.GetSafeHdc(), _PW_CLIENTONLY | _PW_RENDERFULLCONTENT):
                return None
            raw = bmp.GetBitmapBits(True)
            return np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)[:, :, :3].copy()
        finally:
            win32gui.DeleteObject(bmp.GetHandle())
            mem.DeleteDC()
            src.DeleteDC()
            win32gui.ReleaseDC(hwnd, hdc)

    def close(self) -> None:
        pass


def _bgra_to_bgr(image: np.ndarray) -> np.ndarray:
    """The frame as BGR: a plain copy of the BGRA rows (about 3.5 ms at 2560x1440), seen without
    its alpha channel. Not a contiguous BGR array: packing the three channels together in NumPy
    takes 20 ms a frame, and the readers only look at strips of the frame anyway."""
    return np.array(image)[..., :3]


def _convert_without_opencv(camera) -> None:
    """Have bettercam turn its BGRA frames into BGR without OpenCV.

    Asked for BGR, bettercam converts each frame with ``cv2.cvtColor`` (OpenCV, which the meter
    no longer ships); asked for BGRA, it hands back a view of the GPU staging surface, which it
    unmaps before returning, so the pixels would be read after they are gone. Its converter is
    replaced instead: it runs while the frame is still mapped, and copies it out (bettercam
    1.0.0's NumpyProcessor.process_cvtcolor)."""
    backend = getattr(getattr(camera, "_processor", None), "backend", None)
    if backend is None or not hasattr(backend, "process_cvtcolor"):
        raise RuntimeError("this bettercam has no colour converter to replace; capture needs OpenCV")
    backend.process_cvtcolor = _bgra_to_bgr


class _DuplicationBackend:
    """DXGI desktop duplication of the monitor the game is on. Fast, but sees whatever is on top."""

    name = "duplication"

    def __init__(self) -> None:
        import bettercam  # imported lazily: optional dependency

        self._bettercam = bettercam
        self._camera = None
        self._monitor = None
        self._origin = (0, 0)

    def _camera_for(self, hwnd: int):
        monitor = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
        handle = int(monitor)
        if self._camera is not None and handle == self._monitor:
            return self._camera
        self.close()
        factory = getattr(self._bettercam, "__factory")
        for device_idx, outputs in enumerate(factory.outputs):
            for output_idx, output in enumerate(outputs):
                if int(output.hmonitor) == handle:
                    self._camera = self._bettercam.create(
                        device_idx=device_idx, output_idx=output_idx, output_color="BGR"
                    )
                    _convert_without_opencv(self._camera)
                    left, top, _, _ = win32api.GetMonitorInfo(monitor)["Monitor"]
                    self._monitor, self._origin = handle, (left, top)
                    return self._camera
        return None

    def grab(self, hwnd: int, rect: tuple[int, int, int, int]) -> np.ndarray | None:
        camera = self._camera_for(hwnd)
        if camera is None:
            return None
        ox, oy = self._origin
        region = (
            max(0, rect[0] - ox),
            max(0, rect[1] - oy),
            min(camera.width, rect[2] - ox),
            min(camera.height, rect[3] - oy),
        )
        if region[2] <= region[0] or region[3] <= region[1]:
            return None
        # None when the screen has not changed; otherwise BGR, a view of the meter's own copy
        return camera.grab(region=region)

    def close(self) -> None:
        if self._camera is not None:
            try:
                self._camera.release()
            except Exception:  # noqa: BLE001 - teardown of a COM wrapper; nothing useful to do
                pass
            self._camera = None
            self._monitor = None


class GameCapture:
    """Frames of the game's client area as BGR arrays."""

    def __init__(self, backend: str = "auto") -> None:
        set_dpi_aware()
        self.hwnd: int | None = None
        self._last_lookup = 0.0
        self._backend = self._make_backend(backend)

    @staticmethod
    def _make_backend(name: str):
        if name in ("auto", "duplication"):
            try:
                return _DuplicationBackend()
            except Exception:  # noqa: BLE001 - bettercam missing or no usable adapter
                if name == "duplication":
                    raise
        return _PrintWindowBackend()

    @property
    def backend(self) -> str:
        return self._backend.name

    def _ensure_window(self) -> int | None:
        if self.hwnd is not None and win32gui.IsWindow(self.hwnd):
            return self.hwnd
        now = time.monotonic()
        if now - self._last_lookup < 1.0:
            return None
        self._last_lookup = now
        self.hwnd = find_game_window()
        return self.hwnd

    def game_running(self) -> bool:
        return self._ensure_window() is not None

    def game_focused(self) -> bool:
        hwnd = self._ensure_window()
        return hwnd is not None and win32gui.GetForegroundWindow() == hwnd

    def rect(self) -> tuple[int, int, int, int] | None:
        hwnd = self._ensure_window()
        if hwnd is None or win32gui.IsIconic(hwnd):
            return None
        return client_rect_on_screen(hwnd)

    def grab(self) -> np.ndarray | None:
        """Newest frame, or None when the game is missing, minimized or nothing changed."""
        rect = self.rect()
        if rect is None:
            return None
        return self._backend.grab(self.hwnd, rect)

    def close(self) -> None:
        self._backend.close()
