r"""Load the meter's parts one after another and say how much memory each adds to the process.

    .venv\Scripts\python tools\memory_steps.py [overlay page address]

"private" is the memory Windows has promised the process (Task Manager's "Commit size"), "WS"
the working set, what it holds in RAM now. Each line is one part loaded on top of the ones before:
NumPy, the meter's modules, the boss HP tables, screen capture (bettercam and the graphics driver,
then a camera and a few grabs if the game is running), the title reader (ONNX Runtime) and one
read, then Qt, its web engine and an overlay page shown for 6 seconds. The page is the running
meter's (http://127.0.0.1:5055/?view=overlay by default): start the meter or a demo first.

Measured 2026-11-17 on a 16-thread CPU, game running: NumPy +13 WS; modules +16; tables +10;
bettercam +28; camera +30; title reader +39 (17 of it is given back when it is let go); the web
page +175, and its renderer process another 75-105 on top. Before 0.3.1 NumPy also took 482 MB of
commit for OpenBLAS's per-thread buffers (`OPENBLAS_NUM_THREADS`, set in ``wwmeter/__init__.py``).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wwmeter  # noqa: E402,F401 - first, as in the meter: it limits OpenBLAS to one thread

PAGE =sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5055/?view=overlay"


class _Counters(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]


_kernel32 = ctypes.WinDLL("kernel32")
_psapi = ctypes.WinDLL("psapi")
_kernel32.GetCurrentProcess.restype = wt.HANDLE
_psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(_Counters), wt.DWORD]


def memory() -> tuple[float, float]:
    """(private, working set) of this process, in MB."""
    counters = _Counters()
    counters.cb = ctypes.sizeof(counters)
    _psapi.GetProcessMemoryInfo(_kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return counters.PrivateUsage / 2**20, counters.WorkingSetSize / 2**20


_last = memory()


def step(name: str) -> None:
    global _last
    now = memory()
    print(f"{name:46s} {now[0]:7.0f} {now[0] - _last[0]:+6.0f} {now[1]:7.0f} {now[1] - _last[1]:+6.0f}", flush=True)
    _last = now


def main() -> int:
    print(f"{'part loaded':46s} {'private':>7s} {'':>6s} {'WS':>7s} {'':>6s}   (MB)")
    step("Python")
    import numpy as np

    step("NumPy")
    from wwmeter import app, config  # noqa: F401 - imported for what it loads

    step("the meter's modules")
    cfg = config.load()
    from wwmeter.gamedata import enemy_data

    enemy_data(cfg)
    step("boss HP tables")
    from wwmeter.capture import GameCapture

    capture = GameCapture(cfg.capture_backend)
    step(f"screen capture ({capture.backend})")
    frame = None
    for _ in range(3):
        frame = capture.grab()
        time.sleep(0.2)
    step("camera and grabs" + ("" if frame is not None else " (no game frame)"))
    from wwmeter import hud
    from wwmeter.ocr import TextReader

    reader = TextReader()
    step("title reader (ONNX Runtime)")
    hud.read_boss_title(np.zeros((1440, 2560, 3), np.uint8), reader)
    step("one title read")
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication

    application = QApplication([])
    step("Qt and its web engine")
    view = QWebEngineView()
    view.resize(424, 380)
    view.setUrl(QUrl(PAGE))
    view.show()
    QTimer.singleShot(6000, application.quit)
    application.exec()
    step("overlay page shown for 6 s")
    capture.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
