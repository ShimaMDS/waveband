r"""Which hotkeys reach a program that isn't run as administrator while the game is in front.

    .venv\Scripts\python tools\key_reach.py [key ...] [--wait SECONDS]

Run it from a terminal that runs as administrator: it taps the keys into the game, and Windows
won't let a program tap keys into a window that runs above it. It starts a listener at normal
privilege (through Explorer, the way a user starts Waveband), which holds each key as a
system-wide hotkey the way Waveband does (RegisterHotKey, MOD_NOREPEAT). Then it waits for the
game to come to the front (click into it), taps each key once, and says which ones arrived.

The default keys are F13 alone, with Shift, with Ctrl and with Alt: no keyboard has F13 and
nothing else holds it, so the test never collides with Waveband's own keys. Give other keys to
test those (``Alt+F8 PageDown``); quit Waveband first if they are its keys.

Found with it on 2026-11-17 (game 3.8, which runs as administrator, Windows 10): keys held with
Ctrl or Alt arrive; bare keys and Shift-only ones never do. Run as administrator, the listener
gets all of them. Hence Waveband's Alt defaults (``wwmeter/hotkeys.py``, ``wwmeter/elevation.py``).
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from wwmeter import elevation, hotkeys  # noqa: E402

_user32 = ctypes.windll.user32
_WM_HOTKEY = 0x0312
_MOD_NOREPEAT = 0x4000
_VK = {hotkeys.MOD_CONTROL: 0x11, hotkeys.MOD_SHIFT: 0x10, hotkeys.MOD_ALT: 0x12, hotkeys.MOD_WIN: 0x5B}
# keys that are extended keys on the main block: their taps carry KEYEVENTF_EXTENDEDKEY
_EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x2D, 0x2E, 0x5B}
DEFAULT_KEYS = ["F13", "Shift+F13", "Ctrl+F13", "Alt+F13"]


def _game_in_front() -> bool:
    from wwmeter.capture import find_game_window

    game = find_game_window()
    return game is not None and _user32.GetForegroundWindow() == game


def listen(out_path: str, seconds: float, keys: list[str]) -> None:
    """The listener: hold the keys, write a line for each one registered and each that arrives."""
    with open(out_path, "w", encoding="utf-8") as out:
        out.write(f"elevated {elevation.this_process()}\n")
        for number, key in enumerate(keys, start=1):
            modifiers, vk = hotkeys.parse(key)
            held = bool(_user32.RegisterHotKey(None, number, modifiers | _MOD_NOREPEAT, vk))
            out.write(f"registered {number} {held}\n")
        out.flush()
        message = wt.MSG()
        end = time.monotonic() + seconds
        while time.monotonic() < end and not os.path.exists(out_path + ".stop"):
            while _user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                if message.message == _WM_HOTKEY:
                    out.write(f"arrived {message.wParam}\n")
                    out.flush()
            time.sleep(0.005)
    for number in range(1, len(keys) + 1):
        _user32.UnregisterHotKey(None, number)


def _tap(key: str) -> None:
    modifiers, vk = hotkeys.parse(key)
    held = [code for flag, code in _VK.items() if modifiers & flag]
    for code in held + [vk]:
        _user32.keybd_event(code, 0, 1 if code in _EXTENDED else 0, 0)
        time.sleep(0.03)
    for code in reversed(held + [vk]):
        _user32.keybd_event(code, 0, (1 if code in _EXTENDED else 0) | 2, 0)
        time.sleep(0.03)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("keys", nargs="*", default=DEFAULT_KEYS)
    parser.add_argument("--wait", type=float, default=300.0, help="seconds to wait for the game")
    parser.add_argument("--listen", nargs=2, metavar=("OUT", "SECONDS"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    keys = [hotkeys.spell(key) for key in args.keys]
    if any(not key for key in keys):
        print("A key can't be understood:", " ".join(args.keys))
        return 2
    if args.listen:
        listen(args.listen[0], float(args.listen[1]), keys)
        return 0
    if not elevation.this_process():
        print("Run this from a terminal that runs as administrator: the game does, and a program "
              "below it can't tap keys into it.")
        return 2

    folder = os.path.join(ROOT, "TMP", "key_reach")
    os.makedirs(folder, exist_ok=True)
    out_path = os.path.join(folder, "listener.txt")
    for stale in (out_path, out_path + ".stop"):
        if os.path.exists(stale):
            os.remove(stale)
    python = sys.executable.replace("python.exe", "pythonw.exe")
    batch = os.path.join(folder, "listener.bat")
    with open(batch, "w", encoding="ascii") as fh:
        fh.write(f'@echo off\r\nstart "" "{python}" "{os.path.abspath(__file__)}" --listen "{out_path}" '
                 f'{args.wait + 60:.0f} {" ".join(keys)}\r\n')
    subprocess.run(["explorer.exe", batch], check=False)  # Explorer starts it at normal privilege
    for _ in range(100):
        if os.path.exists(out_path) and open(out_path, encoding="utf-8").read().count("registered") == len(keys):
            break
        time.sleep(0.1)
    else:
        print("The listener didn't start.")
        return 1

    print("Click into the game; the keys are tapped once it has been in front for 2 s.")
    end = time.monotonic() + args.wait
    while not _game_in_front():
        if time.monotonic() > end:
            print("The game never came to the front.")
            open(out_path + ".stop", "w").close()
            return 1
        time.sleep(0.3)
    time.sleep(2.0)
    from wwmeter.capture import find_game_window

    game_elevated = elevation.window(find_game_window())
    for key in keys:
        if not _game_in_front():
            print("The game left the front; stopped.")
            break
        _tap(key)
        time.sleep(0.6)
    time.sleep(1.0)
    open(out_path + ".stop", "w").close()
    time.sleep(0.5)

    lines = open(out_path, encoding="utf-8").read().split("\n")
    listener_elevated = lines[0].split()[-1] == "True"
    registered = {int(line.split()[1]): line.split()[2] == "True" for line in lines if line.startswith("registered")}
    arrived = {int(line.split()[1]) for line in lines if line.startswith("arrived")}
    print(f"game runs as administrator: {game_elevated}; listener does: {listener_elevated}")
    for number, key in enumerate(keys, start=1):
        if not registered.get(number):
            verdict = "held by another program: not tested"
        else:
            verdict = "arrived" if number in arrived else "did NOT arrive"
        print(f"  {key:16s} {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
