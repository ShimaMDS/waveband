"""``wwmeter selftest``: check each thing the meter depends on and write what was found.

For when the meter does not work on someone's PC: the report (selftest.txt next to the program)
says which part is missing, and holds nothing personal beyond the game's install path.
"""

from __future__ import annotations

import os
import sys
import time

from . import __version__, config, hotkeys


def _checks(cfg: config.Config):
    """Yield (name, function returning a one-line finding); a raised exception is a failure."""

    def program():
        kind = "packaged .exe" if getattr(sys, "frozen", False) else "from source"
        return f"{config.NAME} {__version__}, {kind}, Python {sys.version.split()[0]}, in {config.ROOT}"

    def files():
        from .gamedata import client_language, enemy_data
        from .roster import Roster
        from .update import installed_version, out_of_date

        themes = sorted(os.listdir(os.path.join(config.ROOT, "ui", "themes")))
        tables = enemy_data(cfg)
        if not tables:
            raise RuntimeError("data\\enemy_hp.json is missing: bar-only bosses will show percent")
        known = len(Roster()._by_id)  # noqa: SLF001 - a diagnostic
        client = client_language(cfg.log_dir, tables.language_ids) or "not found"
        names = (
            f"enemy and character names in '{tables.language}' (game client: {client}; language "
            f"setting: {cfg.language or 'follow the client'}; Carlotta is "
            f"'{tables.character_name(1107) or 'not in the tables'}')"
            if tables.language else "no enemy names in the tables: read off the screen instead"
        )
        game = installed_version(cfg.log_dir) or "not found"
        behind = " (out of date: Settings, The game, Update boss HP tables)" if out_of_date(game, tables.version) else ""
        return (
            f"themes {themes}; {known} characters; boss HP tables for game {tables.version}, "
            f"built {tables.built or '?'} (installed game: {game}){behind}; {names}"
        )

    def game_log():
        from .logtail import scan_file

        path = cfg.log_path
        if not os.path.isfile(path):
            raise RuntimeError(f"no Client.log in {cfg.log_dir}. Paste the game's folder into the "
                               "meter's Settings (tray menu), or set log_dir in config.json to "
                               r"...\Wuthering Waves Game\Client\Saved\Logs")
        age = time.time() - os.path.getmtime(path)
        lines = scan_file(path, ("Sharphereal",))
        if not lines:
            raise RuntimeError(f"{path} has no readable game lines: the log's scrambling may have changed")
        return f"{path}: {len(lines):,} readable game lines, last written {age / 60:.0f} min ago"

    def game_window():
        from .capture import client_rect_on_screen, find_game_window

        hwnd = find_game_window()
        if hwnd is None:
            return "game is not running (start it and run this again to test screen reading)"
        left, top, right, bottom = client_rect_on_screen(hwnd)
        return f"game window found, {right - left}x{bottom - top} at ({left}, {top})"

    def screen():
        from . import hud
        from .capture import GameCapture

        capture = GameCapture(cfg.capture_backend)
        try:
            if not capture.game_running():
                return "skipped: game is not running"
            if not capture.game_focused():
                return f"backend {capture.backend}; skipped the grab: the game is not the focused window"
            frame = None
            for _ in range(20):
                frame = capture.grab()
                if frame is not None:
                    break
                time.sleep(0.1)
            if frame is None:
                raise RuntimeError(f"backend {capture.backend} returned no frame")
            bar = hud.read_boss_bar(frame, cfg.boss_bar)
            seen = f"boss bar at {bar.fraction:.1%}" if bar else "no boss bar on screen"
            return f"backend {capture.backend}, frame {frame.shape[1]}x{frame.shape[0]}, {seen}"
        finally:
            capture.close()

    def text_reading():
        import numpy as np
        from PIL import Image, ImageDraw, ImageFont

        from . import hud
        from .ocr import TextReader

        image = Image.new("RGB", (640, 48), (24, 24, 24))
        try:
            font = ImageFont.truetype("arial.ttf", 30)
        except OSError:
            font = ImageFont.load_default(30)
        ImageDraw.Draw(image).text((12, 7), "Lv. 90 Crownless", font=font, fill=(240, 240, 240))
        text, _ = TextReader()(np.asarray(image)[..., ::-1].copy())
        title = hud.parse_title(text)
        if "90" not in title or "rownless" not in title:
            raise RuntimeError(f"read {text!r} from a test image that says 'Lv. 90 Crownless'")
        return f"read {title!r} from a test image"

    def overlay_parts():
        from . import overlay_webview2

        try:
            return f"drawn by WebView2 Runtime {overlay_webview2.runtime_version()}"
        except overlay_webview2.Unavailable as why:
            raise RuntimeError(f"{why}. The meter is drawn by Microsoft Edge WebView2: install the "
                               "WebView2 Runtime from https://developer.microsoft.com/microsoft-edge/webview2/") from why

    def keys():
        chosen = hotkeys.bindings(cfg.hotkeys)
        listed = ", ".join(f"{action}: {key or 'none'}" for action, key in chosen.items())
        held = hotkeys.in_use([key for key in chosen.values() if key])
        if not held:
            return listed + ". None is held by another program right now"
        # not a failure by itself: the meter's own keys read as held while it runs in front
        return (
            f"{listed}. HELD BY A PROGRAM RIGHT NOW: {', '.join(held)}. If the meter is not "
            "running, another program has taken them and they will do nothing in the meter: "
            "give those actions other keys in the meter's Settings (tray menu)"
        )

    yield "program", program
    yield "files", files
    yield "game log", game_log
    yield "game window", game_window
    yield "screen reading", screen
    yield "text reading", text_reading
    yield "overlay window", overlay_parts
    yield "hotkeys", keys


def run(cfg: config.Config) -> int:
    lines = [f"{config.NAME} self-test, {time.strftime('%Y-%m-%d %H:%M')}"]
    failed = 0
    for name, check in _checks(cfg):
        try:
            lines.append(f"ok    {name}: {check()}")
        except Exception as exc:  # noqa: BLE001 - every failure is a finding
            failed += 1
            lines.append(f"FAIL  {name}: {type(exc).__name__}: {exc}")
    lines.append("All checks passed." if not failed else f"{failed} check(s) failed.")
    report = "\n".join(lines) + "\n"
    path = os.path.join(config.ROOT, "selftest.txt")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(report)
    except OSError:
        path = ""
    print(report + (f"Written to {path}" if path else ""))
    return 1 if failed else 0
