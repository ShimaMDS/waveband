"""Settings, stored as config.json next to the program."""

from __future__ import annotations

import functools
import json
import os
import re
import string
import sys
import threading
from dataclasses import asdict, dataclass, field

from .hotkeys import DEFAULTS as _HOTKEY_DEFAULTS
from .hotkeys import REVISION as _HOTKEYS_REVISION
from .hotkeys import off_old_defaults, with_new_actions


def _root() -> str:
    """The folder that holds ui\\, data\\ and config.json: the project folder when run from
    source, the folder of Waveband.exe when run as the packaged program."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


ROOT = _root()
# What the meter is called where a user sees it. The package, its settings line and its temp
# folders keep the internal name, wwmeter.
NAME = "Waveband"
# Where a run without a console (run.bat, the packaged program) and an update write what they say.
LOG_PATH = os.path.join(ROOT, "waveband.log")
CONFIG_PATH = os.environ.get("WWMETER_CONFIG") or os.path.join(ROOT, "config.json")
# Finished fights, kept across restarts. Beside config.json, so a second set of settings (the
# WWMETER_CONFIG variable) keeps its own list.
HISTORY_PATH = os.path.join(os.path.dirname(os.path.abspath(CONFIG_PATH)), "history.json")
_LOG_SUFFIX = os.path.join("Wuthering Waves Game", "Client", "Saved", "Logs")
# Where the launcher folder ("Wuthering Waves", holding "Wuthering Waves Game") usually is,
# under each drive: the game's own launcher, Steam libraries, and the Epic launcher.
_USUAL_FOLDERS = (
    "Wuthering Waves",
    r"Games\Wuthering Waves",
    r"Program Files\Wuthering Waves",
    r"SteamLibrary\steamapps\common\Wuthering Waves",
    r"Steam\steamapps\common\Wuthering Waves",
    r"Program Files (x86)\Steam\steamapps\common\Wuthering Waves",
    r"Program Files\Epic Games\WutheringWavesj3oFh",
    r"Epic Games\WutheringWavesj3oFh",
)


def _steam_libraries() -> list[str]:
    """Steam's library folders, from its own list. Empty when Steam is not installed."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            steam = winreg.QueryValueEx(key, "SteamPath")[0]
        with open(os.path.join(steam, "steamapps", "libraryfolders.vdf"), encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, ImportError):
        return []
    return [path.replace("\\\\", "\\") for path in re.findall(r'"path"\s+"([^"]+)"', text)]


@functools.lru_cache(maxsize=1)
def _guess_log_dir() -> str:
    """The game's log folder. Looks next to this program (it is often unpacked into the launcher
    folder), in Steam's libraries and in the usual install folders on every drive; when the game
    is installed in more than one place, the one whose log was written last wins."""
    beside = os.path.join(os.path.dirname(ROOT), _LOG_SUFFIX)
    candidates = [beside]
    candidates += [
        os.path.join(library, "steamapps", "common", "Wuthering Waves", _LOG_SUFFIX)
        for library in _steam_libraries()
    ]
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if os.path.isdir(drive):
            candidates += [os.path.join(drive, folder, _LOG_SUFFIX) for folder in _USUAL_FOLDERS]

    def written(path: str) -> float:
        try:
            return os.path.getmtime(os.path.join(path, "Client.log"))
        except OSError:
            return 0.0

    found = [path for path in dict.fromkeys(candidates) if os.path.isdir(path)]
    return max(found, key=written) if found else beside


def find_log_dir() -> str:
    """Look for the game's log folder afresh (the game may have been installed since the meter
    started). The folder may not exist: it is then where the meter would look first."""
    _guess_log_dir.cache_clear()
    return _guess_log_dir()


@dataclass
class Config:
    log_dir: str = field(default_factory=_guess_log_dir)
    port: int = 5055
    capture_backend: str = "auto"  # auto | duplication | printwindow
    capture_fps: int = 10
    # Overlay window, in screen pixels. x/y of None means "top-left of the game window + margin".
    overlay_x: int | None = None
    overlay_y: int | None = None
    overlay_zoom: float = 1.0
    # Show the overlay only while the game is the foreground window.
    only_over_game: bool = True
    # True keeps the overlay out of screenshots, streams and recordings. On Windows 10 that makes
    # it a black box in Win+Shift+S, so it is off by default.
    hide_from_capture: bool = False
    # Programs that may take focus without the overlay hiding (so it appears in screenshots).
    capture_tools: list[str] = field(
        default_factory=lambda: [
            "ScreenClippingHost.exe", "SnippingTool.exe", "ScreenSketch.exe", "ShareX.exe",
            "Greenshot.exe", "Lightshot.exe", "GameBar.exe",
        ]
    )
    # What the figures are in: "damage" (per second) or "percent" (of the enemy's HP per second).
    # Damage needs an enemy that logs its HP; percent needs that or a boss bar.
    display_unit: str = "damage"
    # Look of the overlay: the name of a stylesheet in ui/themes ("wuwa" or "classic").
    theme: str = "wuwa"
    # Read damage numbers off the screen for enemies with no logged HP and no boss bar. Rough:
    # graded at about half the true damage, so it is off unless asked for.
    read_numbers: bool = False
    # Seconds without any damage before an encounter is closed.
    encounter_timeout: float = 8.0
    # Boss HP bar rectangle as fractions of the game client area (x0, y0, x1, y1); None = auto.
    boss_bar: list[float] | None = None
    # Hotkeys, active only while the game is the focused window. Actions: older and newer (step
    # through earlier fights), toggle (show or hide), compact (one-line meter), unit (damage or
    # percent), reset (new fight), move (move or resize), capture (show in screenshots), hints
    # (the line of keys on the meter), rest (hide between fights), copy (the fight's summary to
    # the clipboard). Keys are written like "Alt+F8" or "Ctrl+Alt+M"; "" gives an action no hotkey.
    hotkeys: dict[str, str] = field(default_factory=lambda: dict(_HOTKEY_DEFAULTS))
    # Which defaults the keys above were written against: missing (0) in files from 0.3.0 and
    # before, whose bare F7 to F11 are moved to the Alt ones once (hotkeys.off_old_defaults).
    hotkeys_revision: int = _HOTKEYS_REVISION
    # Show the keys and what they do in a line along the top of the meter.
    show_keys: bool = True
    # One-line meter: only the fight clock and the total per second.
    compact: bool = False
    # Take the meter off the screen when no fight is on. A finished fight stays up for a while
    # first, and anything the meter has to say (no log, HP not known) keeps it up.
    hide_between_fights: bool = False
    # The figures on a character's row, left to right. Any of: dps, damage, share, field_time
    # (time on field), field_dps (damage per second of that time).
    row_figures: list[str] = field(default_factory=lambda: ["dps", "share"])
    # Decimals of a figure written short (15.38k, 2.10M), 0 to 2; and of a share (34%), 0 to 2.
    figure_decimals: int = 2
    share_decimals: int = 0
    # Language enemy and character names are shown in. "" follows the game client's own setting;
    # otherwise a code the game has text for: en, zh-Hans, zh-Hant, ja, ko, de, es, fr, pt, th.
    language: str = ""
    # Colours of the user's own for the elements, on top of the theme's: element (glacio, fusion,
    # electro, aero, spectro, havoc) -> "#rrggbb". An element not listed keeps the theme's colour.
    colours: dict[str, str] = field(default_factory=dict)
    # The version of the meter that last ran with these settings: how a newer one knows to say
    # what changed. Kept by the meter itself; "" in a file written by 0.1.0.
    seen_version: str = ""
    # Ask GitHub for a newer Waveband when the meter starts and once a day after, and say so.
    check_updates: bool = True
    # Install a newer version at start without asking first (an installed copy only).
    auto_update: bool = False
    # Which updates to be told about: "stable" (releases only) or "beta" (test versions of the next
    # release too). "" until chosen: then a beta of Waveband follows Beta and any other version
    # Stable, so a tester who installs a beta hears about the next one without changing anything.
    update_channel: str = ""

    @property
    def log_path(self) -> str:
        return os.path.join(self.log_dir, "Client.log")


def load() -> Config:
    cfg = Config()
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return cfg
    for key, value in data.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    revision = data.get("hotkeys_revision")
    if not isinstance(revision, int) or revision < _HOTKEYS_REVISION:
        if isinstance(cfg.hotkeys, dict):
            cfg.hotkeys = off_old_defaults(cfg.hotkeys)
        cfg.hotkeys_revision = _HOTKEYS_REVISION
    if isinstance(cfg.hotkeys, dict):
        # a file written by an earlier version lacks the actions added since: list them, with
        # their default keys, so the next save shows every key that can be changed
        cfg.hotkeys = with_new_actions(cfg.hotkeys)
    return cfg


_saving = threading.Lock()  # the tray menu, the hotkeys and the settings page all save


def save(cfg: Config) -> None:
    """Write the settings. The file is replaced whole, so a crash half-way leaves the old one."""
    with _saving:
        with open(CONFIG_PATH + ".part", "w", encoding="utf-8") as fh:
            json.dump(asdict(cfg), fh, indent=2, ensure_ascii=False)
        os.replace(CONFIG_PATH + ".part", CONFIG_PATH)
