"""Check the WebView2 overlay (``wwmeter\\overlay_webview2.py``) on this PC, without the game.

    .venv\\Scripts\\python -m wwmeter run --demo --no-overlay      (in one terminal)
    .venv\\Scripts\\python tools\\webview2_overlay.py               (in another)

Shows ``?view=overlay`` from the running meter in the overlay's window over a solid magenta
one, then reads the screen and the window:

- transparent: the pixels around the meter's card stay exactly magenta, the card is drawn;
- clicks pass through: the window under a point on the card is not the overlay;
- move mode: the overlay takes the mouse, the page gets its dashed outline, scrolling resizes;
- hidden from screenshots: with that on, a grab is all magenta.

It also reports the memory of this process and of the WebView2 processes it started. The
settings are a copy: config.json is not written. Pictures go to ``TMP\\webview2\\``.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from wwmeter import config as config_mod  # noqa: E402
from wwmeter import overlay_webview2 as ov  # noqa: E402
from wwmeter.capture import set_dpi_aware  # noqa: E402

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
GA_ROOT = 2
MAGENTA = (255, 0, 255)


def backdrop(x: int, y: int, width: int, height: int) -> int:
    """A plain magenta window to read the overlay against."""
    instance = ctypes.windll.kernel32.GetModuleHandleW(None)
    proc = ov.WNDPROC(lambda h, m, w, l: ov._user32.DefWindowProcW(h, m, w, l))
    gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
    cls = ov._WNDCLASSEXW(cbSize=ctypes.sizeof(ov._WNDCLASSEXW), lpfnWndProc=proc, hInstance=instance,
                          hbrBackground=gdi32.CreateSolidBrush(0x00FF00FF), lpszClassName="WavebandBackdrop")
    ov._user32.RegisterClassExW(ctypes.byref(cls))
    hwnd = ov._user32.CreateWindowExW(ov.WS_EX_TOPMOST | ov.WS_EX_TOOLWINDOW | ov.WS_EX_NOACTIVATE,
                                      "WavebandBackdrop", "", ov.WS_POPUP, x, y, width, height,
                                      None, None, instance, None)
    backdrop.proc = proc  # keep the callback alive
    user32.ShowWindow(hwnd, ov.SW_SHOWNOACTIVATE)
    return hwnd


def pump(seconds: float, until=lambda: False) -> bool:
    msg = wintypes.MSG()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        if until():
            return True
        time.sleep(0.01)
    return False


def memory_report() -> str:
    """Private bytes of this process and of the msedgewebview2 processes under it."""
    script = (
        "$all = Get-CimInstance Win32_Process; $ids = @(%d); $more = $true; "
        "while ($more) { $more = $false; foreach ($p in $all) { if ($ids -contains $p.ParentProcessId -and "
        "-not ($ids -contains $p.ProcessId)) { $ids += $p.ProcessId; $more = $true } } }; "
        "$all | Where-Object { ($ids -contains $_.ProcessId) -and $_.Name -ne 'powershell.exe' } | ForEach-Object { "
        "'{0} {1} {2}' -f $_.Name, [math]::Round($_.PrivatePageCount/1MB), [math]::Round($_.WorkingSetSize/1MB) }"
    ) % os.getpid()
    out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True).stdout
    rows = [line.split() for line in out.splitlines() if line.strip()]
    lines = [f"  {r[0]:<22} private {r[1]:>5} MB  working set {r[2]:>5} MB" for r in rows]
    private, working = sum(int(r[1]) for r in rows), sum(int(r[2]) for r in rows)
    return "\n".join(lines + [f"  together: {len(rows)} processes, private {private} MB, working set {working} MB"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", help="the overlay page (default: the meter on the configured port)")
    args = parser.parse_args()
    from PIL import ImageGrab

    set_dpi_aware()
    print(f"WebView2 Runtime {ov.runtime_version()}")
    cfg = config_mod.load()
    config_mod.save = lambda *_: None  # a copy to play with: config.json stays as it is
    ov.config_mod.save = config_mod.save
    url = args.url or f"http://127.0.0.1:{cfg.port}/?view=overlay"
    width, height = ov.BASE_SIZE
    x = user32.GetSystemMetrics(0) - width - 40
    y = user32.GetSystemMetrics(1) - height - 80
    cfg.overlay_x, cfg.overlay_y, cfg.overlay_zoom = x, y, 1.0
    cfg.hide_from_capture = False
    shots = os.path.join(ROOT, "TMP", "webview2")
    os.makedirs(shots, exist_ok=True)

    backdrop(x, y, width, height)
    failed: list[str] = []
    window = ov.OverlayWindow(url, cfg, failed.append)
    loaded: list[bool] = []
    original = window._on_loaded
    window._on_loaded = lambda *a: (loaded.append(True), original(*a))
    window._set_visible(True)
    results: list[tuple[str, bool, str]] = []

    def grab(name: str):
        pump(0.6)
        image = ImageGrab.grab(bbox=(x, y, x + width, y + height), all_screens=True).convert("RGB")
        image.save(os.path.join(shots, name))
        return image

    def magenta(image) -> float:
        pixels = list(image.getdata())
        return sum(1 for p in pixels if p == MAGENTA) / len(pixels)

    def page(script: str) -> str | None:
        answer: list[str] = []
        done = window._handler(window._wv.ICoreWebView2ExecuteScriptCompletedHandler,
                               lambda _error, result: answer.append(result))
        window._webview.ExecuteScript(script, done)
        pump(3, lambda: bool(answer))
        return answer[0] if answer else None

    try:
        if not pump(20, lambda: bool(loaded) or bool(failed)) or failed:
            print(f"FAIL: the page never loaded {failed}")
            return 1
        pump(2.5)  # fonts, and the demo fight's numbers
        shown = grab("overlay.png")
        share = magenta(shown)
        results.append(("transparent background", 0.05 < share < 0.98,
                        f"{share:.0%} of the window is exactly the magenta behind it"))
        card = 1 - magenta(shown.crop((10, 10, 200, 120)))
        results.append(("the meter's card is drawn", card > 0.5, f"{card:.0%} of its top left is not magenta"))
        point = wintypes.POINT(x + 60, y + 60)
        hit = user32.GetAncestor(user32.WindowFromPoint(point), GA_ROOT)
        results.append(("clicks pass through", hit != window.hwnd,
                        f"the window under the card is {hit:#x}, the overlay {window.hwnd:#x}"))

        window.set_moving(True)
        pump(0.5)
        hit = user32.GetAncestor(user32.WindowFromPoint(point), GA_ROOT)
        results.append(("move mode takes the mouse", hit == window.hwnd, f"the window under the card is {hit:#x}"))
        outlined = page("document.body.classList.contains('moving')")
        results.append(("move mode outlines the meter", outlined == "true", f"the page says {outlined}"))
        user32.SendMessageW(window.hwnd, ov.WM_MOUSEWHEEL, 120 << 16, 0)
        rect = wintypes.RECT()
        user32.GetWindowRect(window.hwnd, ctypes.byref(rect))
        grown = rect.right - rect.left
        results.append(("scrolling resizes", grown == round(width * 1.05), f"{width} px wide, now {grown}"))
        grab("overlay-moving.png")
        window.nudge_zoom(-0.05)
        window.set_moving(False)
        pump(0.5)
        hit = user32.GetAncestor(user32.WindowFromPoint(point), GA_ROOT)
        outlined = page("document.body.classList.contains('moving')")
        results.append(("locked again", hit != window.hwnd and outlined == "false",
                        f"clicks pass: {hit != window.hwnd}, outline: {outlined}"))

        window.set_hidden_from_capture(True)
        excluded = magenta(grab("overlay-excluded.png"))
        results.append(("hidden from screenshots", excluded > 0.99, f"{excluded:.0%} magenta with it hidden"))
        for name, ok, detail in results:
            print(f"{'ok  ' if ok else 'FAIL'}  {name}: {detail}")
        print("memory (this process and its WebView2 processes):")
        print(memory_report())
        print(f"pictures in {shots}")
        return 0 if all(ok for _, ok, _ in results) else 1
    finally:
        window.close()


if __name__ == "__main__":
    sys.exit(main())
