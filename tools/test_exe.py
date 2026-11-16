"""Smoke-test a built Waveband.exe before a release goes out.

    python tools/test_exe.py <release folder holding Waveband.exe> [overlay.png]

1. Runs ``Waveband.exe selftest`` and prints the report.
2. Runs ``Waveband.exe run --demo`` on a spare port with the overlay parked far off-screen (so it
   does not cover anything), checks the state it serves, checks the web view's helper process is
   up, and captures the overlay window to a PNG to look at.

It uses its own config file, so the release folder's settings are not touched, and deletes the
selftest.txt and waveband.log the two runs leave behind. Exit code 0 means everything answered;
looking at the PNG is still up to you.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

import win32gui
import win32process
import win32ui
from PIL import Image

_PORT = 5057


def capture_window(hwnd: int, out: str) -> tuple[int, int]:
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width, height = right - left, bottom - top
    window_dc = win32gui.GetWindowDC(hwnd)
    source = win32ui.CreateDCFromHandle(window_dc)
    memory = source.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(source, width, height)
    memory.SelectObject(bitmap)
    ctypes.windll.user32.PrintWindow(hwnd, memory.GetSafeHdc(), 2)  # 2: render the full content
    info = bitmap.GetInfo()
    image = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bitmap.GetBitmapBits(True), "raw", "BGRX", 0, 1)
    image.save(out)
    return width, height


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    release = os.path.abspath(argv[1])
    exe = os.path.join(release, "Waveband.exe")
    picture = argv[2] if len(argv) > 2 else os.path.join(tempfile.gettempdir(), "wwmeter-exe-overlay.png")
    handle, settings = tempfile.mkstemp(suffix=".json")
    with os.fdopen(handle, "w") as fh:
        json.dump({"port": _PORT, "only_over_game": False, "overlay_x": 200, "overlay_y": 6000}, fh)
    env = dict(os.environ, WWMETER_CONFIG=settings)
    failed = 0

    code = subprocess.run([exe, "selftest"], env=env, timeout=180).returncode
    try:
        with open(os.path.join(release, "selftest.txt"), encoding="utf-8") as fh:
            print(fh.read())
    except OSError:
        print("selftest wrote no report")
    failed += code != 0

    process = subprocess.Popen([exe, "run", "--demo"], env=env)
    try:
        time.sleep(14)
        with urllib.request.urlopen(f"http://127.0.0.1:{_PORT}/state.json", timeout=5) as response:
            state = json.load(response)
        fight = state["encounter"]
        print(f"demo state: {fight['title']}, {fight['damage']:,} damage, keys {[k['key'] for k in state['ui']['keys']]}")
        windows: list[int] = []

        def visit(hwnd: int, _) -> bool:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid == process.pid and "QWindowTool" in win32gui.GetClassName(hwnd):
                windows.append(hwnd)
            return True

        win32gui.EnumWindows(visit, None)
        if windows:
            size = capture_window(windows[0], picture)
            print(f"overlay window {size[0]}x{size[1]} captured to {picture}")
        else:
            print("FAIL: no overlay window")
            failed += 1
        helpers = subprocess.run(
            ["wmic", "process", "where", f"ParentProcessId={process.pid}", "get", "Name"],
            capture_output=True, text=True, check=False,
        ).stdout
        if "QtWebEngineProcess" not in helpers:
            print("FAIL: the web view's helper process is not running")
            failed += 1
    except Exception as exc:  # noqa: BLE001 - any failure here is the finding
        print(f"FAIL: {type(exc).__name__}: {exc}")
        failed += 1
    finally:
        process.kill()
        process.wait(timeout=20)
    time.sleep(1.0)
    for leftover in ("selftest.txt", "waveband.log"):
        try:
            os.remove(os.path.join(release, leftover))
        except OSError:
            pass
    os.remove(settings)
    print("exe smoke test passed" if not failed else f"{failed} check(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
