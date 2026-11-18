"""Smoke-test a built Waveband.exe before a release goes out (or the source, with --source).

    python tools/test_exe.py <release folder holding Waveband.exe> [overlay.png]
    python tools/test_exe.py --source [overlay.png]

1. Runs ``selftest`` and prints the report.
2. Runs ``run --demo`` on a spare port, checks the state the meter serves, that the overlay
   window and its web view's processes are up, and saves a picture of the overlay to look at.
   The overlay sits in the bottom right corner of the screen for a few seconds to be grabbed (a
   window drawn through DirectComposition has nothing for PrintWindow), then is closed the way
   the tray menu's Quit closes it: the meter has to exit by itself, with no web view process
   left behind.
3. With an old setting from 0.3.2-beta.1 asking for Qt (gone since), the same again: the
   setting must be ignored and WebView2 draw the meter.

It uses its own config file, so the release folder's settings are not touched, and deletes the
selftest.txt and waveband.log the runs leave behind. Exit code 0 means everything answered;
looking at the pictures is still up to you.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

import win32api
import win32con
import win32gui
import win32process
from PIL import ImageGrab

_PORT = 5057
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOW_CLASS = "WavebandOverlay"  # wwmeter/overlay_webview2.py
HELPER = "msedgewebview2.exe"  # WebView2's processes


def grab_screen(hwnd: int, out: str) -> tuple[int, int]:
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True).save(out)
    return right - left, bottom - top


def descendants(pid: int) -> list[tuple[int, str]]:
    """The processes started by ``pid`` and by those, all the way down: (ID, name)."""
    script = (
        "$all = Get-CimInstance Win32_Process; $ids = @(%d); $more = $true; "
        "while ($more) { $more = $false; foreach ($p in $all) { if ($ids -contains $p.ParentProcessId -and "
        "-not ($ids -contains $p.ProcessId)) { $ids += $p.ProcessId; $more = $true } } }; "
        "$all | Where-Object { ($ids -contains $_.ProcessId) -and $_.ProcessId -ne %d } | ForEach-Object { '{0} {1}' -f $_.ProcessId, $_.Name }"
    ) % (pid, pid)
    out = ""
    # the process query comes back empty now and then right after heavy work (seen after two
    # builds in a row, 2026-11-19): ask again rather than report a meter with no web view
    for _ in range(3):
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True).stdout
        if out.strip():
            break
        time.sleep(1.0)
    rows = [line.split(None, 1) for line in out.splitlines() if line.strip()]
    return [(int(pid_text), name.strip()) for pid_text, name in rows]


def run_demo(command: list[str], label: str, picture: str, extra: dict | None = None) -> int:
    """One demo run, with ``extra`` settings. The number of checks that failed."""
    width, height = 424, 380
    x = win32api.GetSystemMetrics(0) - width - 40
    y = win32api.GetSystemMetrics(1) - height - 80
    handle, settings = tempfile.mkstemp(suffix=".json")
    with os.fdopen(handle, "w") as fh:
        json.dump({"port": _PORT, "only_over_game": False, "overlay_x": x, "overlay_y": y, **(extra or {})}, fh)
    # A WebView2 data folder of its own (Waveband keeps it under LOCALAPPDATA): with the shared
    # one, a Waveband already running here lends its web view processes to this run, and they are
    # not this run's to find or to see closed (seen 2026-11-19)
    local = tempfile.mkdtemp(prefix="wwmeter-test-")
    env = dict(os.environ, WWMETER_CONFIG=settings, LOCALAPPDATA=local)
    failed = 0
    process = subprocess.Popen([*command, "run", "--demo"], env=env)
    try:
        time.sleep(14)
        with urllib.request.urlopen(f"http://127.0.0.1:{_PORT}/state.json", timeout=5) as response:
            state = json.load(response)
        fight = state["encounter"]
        print(f"[{label}] demo state: {fight['title']}, {fight['damage']:,} damage, "
              f"keys {[k['key'] for k in state['ui']['keys']]}")
        windows: list[int] = []
        # from source, the venv's python.exe starts the real one: the window is a child's
        family = {process.pid} | {pid for pid, _ in descendants(process.pid)}

        def visit(hwnd: int, _) -> bool:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid in family and win32gui.GetClassName(hwnd) == WINDOW_CLASS:
                windows.append(hwnd)
            return True

        win32gui.EnumWindows(visit, None)
        if windows:
            size = grab_screen(windows[0], picture)
            print(f"[{label}] overlay window {size[0]}x{size[1]} captured to {picture}")
        else:
            print(f"[{label}] FAIL: no overlay window")
            failed += 1
        helpers = [name for _, name in descendants(process.pid)]
        if HELPER not in helpers:
            print(f"[{label}] FAIL: the web view's process ({HELPER}) is not running: {helpers}")
            failed += 1
        if windows:
            # quit as the tray menu does; the meter has to end by itself and take its web view along
            win32gui.PostMessage(windows[0], win32con.WM_CLOSE, 0, 0)
            try:
                code = process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                print(f"[{label}] FAIL: still running 20 s after Quit")
                failed += 1
            else:
                time.sleep(2.0)
                left = [name for _, name in descendants(process.pid) if name == HELPER]
                print(f"[{label}] quit: exit code {code}, {len(left)} web view processes left")
                failed += code != 0 or bool(left)
    except Exception as exc:  # noqa: BLE001 - any failure here is the finding
        print(f"[{label}] FAIL: {type(exc).__name__}: {exc}")
        failed += 1
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=20)
        os.remove(settings)
        time.sleep(1.0)  # the web view's last files are let go a moment after it ends
        shutil.rmtree(local, ignore_errors=True)
    return failed


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    if argv[1] == "--source":
        release, folder = None, ROOT
        command = [sys.executable, "-m", "wwmeter"]
    else:
        release = folder = os.path.abspath(argv[1])
        command = [os.path.join(release, "Waveband.exe")]
    picture = argv[2] if len(argv) > 2 else os.path.join(tempfile.gettempdir(), "wwmeter-exe-overlay.png")
    handle, settings = tempfile.mkstemp(suffix=".json")
    with os.fdopen(handle, "w") as fh:
        json.dump({"port": _PORT}, fh)
    failed = 0
    code = subprocess.run([*command, "selftest"], env=dict(os.environ, WWMETER_CONFIG=settings),
                          cwd=folder, timeout=180).returncode
    os.remove(settings)
    try:
        with open(os.path.join(folder, "selftest.txt"), encoding="utf-8") as fh:
            print(fh.read())
    except OSError:
        print("selftest wrote no report")
    failed += code != 0

    failed += run_demo(command, "overlay", picture)
    time.sleep(1.0)
    root, ext = os.path.splitext(picture)
    # a settings file from 0.3.2-beta.1 may still ask for Qt: ignored, WebView2 draws the meter
    failed += run_demo(command, "old Qt setting", f"{root}-old-setting{ext}", {"overlay_engine": "qt"})

    if release is not None:
        for leftover in ("selftest.txt", "waveband.log"):
            try:
                os.remove(os.path.join(release, leftover))
            except OSError:
                pass
    print("exe smoke test passed" if not failed else f"{failed} check(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
