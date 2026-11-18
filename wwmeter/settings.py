"""The settings as the settings page sees them: what it shows, the checks on what it sends back,
and all of them as one line of text to carry to another PC.

Nothing here touches Qt or the running meter. ``apply`` changes a Config and says which fields
changed; whoever called it saves the file and makes the running meter take them up.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import zlib
from dataclasses import asdict

from . import hotkeys
from .config import ROOT, Config
from .selfupdate import effective_channel

ELEMENTS = ("glacio", "fusion", "electro", "aero", "spectro", "havoc")
THEME_LABELS = {"wuwa": "WuWa", "classic": "Classic"}
# The game's languages, each in its own words.
LANGUAGE_LABELS = {
    "en": "English", "zh-Hans": "简体中文", "zh-Hant": "繁體中文", "ja": "日本語", "ko": "한국어",
    "de": "Deutsch", "es": "Español", "fr": "Français", "pt": "Português", "th": "ไทย",
    "ru": "Русский", "id": "Bahasa Indonesia", "vi": "Tiếng Việt",
}
ZOOM = (0.6, 2.5)  # the meter's size, as the overlay window allows it
# The figures a character's row can show: name, what the settings page calls it, and anything
# the page should say beside it.
FIGURES = (
    ("dps", "Damage per second", ""),
    ("damage", "Total damage", ""),
    ("share", "Share of the fight's damage", ""),
    ("field_time", "Time on field", ""),
    ("field_dps", "Damage per second on field",
     "Damage dealt from off field is counted for whoever is on field at that moment. So this "
     "figure flatters a character that stands on field while another's skills are running."),
)
USUAL_FIGURES = ("dps", "share")

# What the one line of text leaves out: where things are on this PC. The log folder's path can
# hold the Windows user name, and the port is how this PC's browser reaches the meter. The
# version last run is no setting: it is this PC's own record of which notes it has been shown.
# What draws the overlay is chosen for this PC's WebView2, which another PC's may not share.
NOT_EXPORTED = ("log_dir", "port", "seen_version", "overlay_engine")
_LINE_PREFIX = "wwmeter1:"
_LINE_LIMIT = 40_000  # characters of a pasted line; a real one is under a thousand
_JSON_LIMIT = 200_000  # bytes it may unpack to
_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
_LOGS_UNDER = (
    ("Client", "Saved", "Logs"),  # the "Wuthering Waves Game" folder
    ("Wuthering Waves Game", "Client", "Saved", "Logs"),  # the launcher's folder
    ("Saved", "Logs"),
    ("Logs",),
)


def available_themes() -> list[str]:
    folder = os.path.join(ROOT, "ui", "themes")
    try:
        names = sorted(os.path.splitext(f)[0] for f in os.listdir(folder) if f.endswith(".css"))
    except OSError:
        return []
    # WuWa first, then the element themes in the game's order, then any others (Classic)
    order = {name: place for place, name in enumerate(("wuwa", *ELEMENTS))}
    return sorted(names, key=lambda n: (order.get(n, len(order)), n))


def theme_label(name: str) -> str:
    return THEME_LABELS.get(name, name.capitalize())


# ---- the game's log folder ------------------------------------------------------------------

def log_folder(text: str) -> str | None:
    """The log folder meant by what was typed or pasted: the folder itself, the Client.log in
    it, or the game's folder above it. None when there is no such folder."""
    path = str(text or "").strip().strip('"').strip()
    if not path or "\x00" in path:
        return None
    path = os.path.abspath(os.path.expandvars(path))
    if os.path.isfile(path):
        path = os.path.dirname(path)
    if not os.path.isdir(path):
        return None
    if os.path.isfile(os.path.join(path, "Client.log")):
        return path
    for parts in _LOGS_UNDER:
        below = os.path.join(path, *parts)
        if os.path.isdir(below):
            return below
    return path


# ---- checks, one per setting ----------------------------------------------------------------

class Refused(ValueError):
    """A value the meter will not take, with the reason in words for the user."""


def _flag(value) -> bool:
    if not isinstance(value, bool):
        raise Refused("has to be on or off")
    return value


def _number(low: float, high: float, whole: bool = False):
    def check(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
            raise Refused("has to be a number")
        if not low <= value <= high:
            raise Refused(f"has to be between {low:g} and {high:g}")
        return int(round(value)) if whole else float(value)

    return check


def _one_of(*allowed: str):
    def check(value):
        if value not in allowed:
            raise Refused("has to be one of: " + ", ".join(allowed))
        return value

    return check


def _or_none(check):
    return lambda value: None if value is None else check(value)


def _capture_tools(value) -> list[str]:
    if not isinstance(value, list) or len(value) > 60:
        raise Refused("has to be a list of program names")
    for name in value:
        if not isinstance(name, str) or not 0 < len(name) <= 120:
            raise Refused("has to be a list of program names")
    return list(value)


def _boss_bar(value) -> list[float]:
    ok = (
        isinstance(value, list) and len(value) == 4
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1 for v in value)
        and value[0] < value[2] and value[1] < value[3]
    )
    if not ok:
        raise Refused("has to be four fractions of the game window: left, top, right, bottom")
    return [float(v) for v in value]


def _row_figures(value) -> list[str]:
    known = [name for name, _, _ in FIGURES]
    ok = (
        isinstance(value, list) and all(isinstance(name, str) for name in value)
        and len(set(value)) == len(value) and all(name in known for name in value)
    )
    if not ok:
        raise Refused("has to be a list of these, each once at most: " + ", ".join(known))
    if not value:
        raise Refused("a row has to show one figure at least")
    return list(value)


def row_figures(value) -> list[str]:
    """The row's figures as the meter uses them: the usual ones when the file holds nonsense."""
    try:
        return _row_figures(value)
    except Refused:
        return list(USUAL_FIGURES)


def decimals(value, usual: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 2 else usual


def _hotkeys(value, current: dict) -> dict[str, str]:
    """The key table with ``value`` laid over it. A key is written one way ("Ctrl+Alt+M")."""
    if not isinstance(value, dict):
        raise Refused("The keys have to be a table of action and key")
    # the table as the meter uses it: every action, and no key given twice
    merged = hotkeys.bindings(hotkeys.with_new_actions(current if isinstance(current, dict) else {}))
    wanted: dict[str, str] = {}
    for action, key in value.items():
        if action not in hotkeys.DEFAULTS:
            continue  # an action of a newer version of the meter
        spelt = hotkeys.spell(key) if isinstance(key, str) else None
        if spelt is None:
            raise Refused(f"{key!r} is not a key the meter can use")
        wanted[action] = spelt
    merged.update(wanted)
    for action, key in wanted.items():
        parsed = hotkeys.parse(key)
        if parsed is None:
            continue
        for other, held in merged.items():
            if other != action and hotkeys.parse(held) == parsed:
                raise Refused(f'{key} is already the key for "{hotkeys.LABELS[other]}"')
    return merged


def _colours(value, current: dict) -> dict[str, str]:
    """The colours with ``value`` laid over them. "" gives an element back the theme's colour."""
    if not isinstance(value, dict):
        raise Refused("has to be a table of element and colour")
    merged = {k: v for k, v in (current if isinstance(current, dict) else {}).items() if k in ELEMENTS}
    for element, colour in value.items():
        if element not in ELEMENTS:
            continue
        if colour in ("", None):
            merged.pop(element, None)
        elif isinstance(colour, str) and _COLOUR.match(colour):
            merged[element] = colour.lower()
        else:
            raise Refused(f"{colour!r} is not a colour (written like #41aefb)")
    return merged


def _checks(themes: list[str], languages: list[str]) -> dict:
    return {
        "capture_backend": _one_of("auto", "duplication", "printwindow"),
        "capture_fps": _number(1, 60, whole=True),
        "overlay_x": _or_none(_number(-100_000, 100_000, whole=True)),
        "overlay_y": _or_none(_number(-100_000, 100_000, whole=True)),
        "overlay_zoom": lambda value: round(_number(*ZOOM)(value), 2),
        "only_over_game": _flag,
        "hide_from_capture": _flag,
        "overlay_engine": _one_of("webview2", "qt"),
        "capture_tools": _capture_tools,
        "display_unit": _one_of("damage", "percent"),
        "theme": _one_of(*themes),
        "read_numbers": _flag,
        "encounter_timeout": _number(2, 120),
        "boss_bar": _or_none(_boss_bar),
        "show_keys": _flag,
        "compact": _flag,
        "hide_between_fights": _flag,
        "language": _one_of("", *languages),
        "row_figures": _row_figures,
        "figure_decimals": _number(0, 2, whole=True),
        "share_decimals": _number(0, 2, whole=True),
        "check_updates": _flag,
        "auto_update": _flag,
        "update_channel": _one_of("", "stable", "beta"),  # "": not chosen, follows the version
    }


NAMES = {  # a setting, as a message about it calls it
    "capture_backend": "The way the screen is captured",
    "capture_fps": "Screen captures per second",
    "overlay_x": "The meter's place on screen",
    "overlay_y": "The meter's place on screen",
    "overlay_zoom": "The meter's size",
    "only_over_game": "Showing only over the game",
    "hide_from_capture": "Hiding from screenshots",
    "overlay_engine": "What draws the meter",
    "capture_tools": "The list of screenshot programs",
    "display_unit": "Damage or percent",
    "theme": "The theme",
    "read_numbers": "Reading damage numbers",
    "encounter_timeout": "Seconds before a fight is closed",
    "boss_bar": "The boss bar's place",
    "show_keys": "Showing the keybinds",
    "compact": "The one-line meter",
    "hide_between_fights": "Hiding between fights",
    "language": "The language of names",
    "row_figures": "The figures on a row",
    "figure_decimals": "Decimals of a figure",
    "share_decimals": "Decimals of a share",
    "check_updates": "Looking for updates",
    "auto_update": "Installing updates without asking",
    "update_channel": "The update channel",
    "hotkeys": "Keybinds",
    "colours": "Colours",
    "log_dir": "The log folder",
}


def apply(cfg: Config, changes, themes: list[str], languages: list[str]) -> tuple[set[str], list[str]]:
    """Lay ``changes`` (setting -> value) over ``cfg``. Gives the settings that changed, and a
    sentence for each one refused; a refused setting is left as it was and the rest are taken."""
    changed: set[str] = set()
    refused: list[str] = []
    if not isinstance(changes, dict):
        return changed, ["That is not a set of settings."]
    checks = _checks(themes, languages)
    for name, value in changes.items():
        try:
            if name == "hotkeys":
                value = _hotkeys(value, cfg.hotkeys)
            elif name == "colours":
                value = _colours(value, cfg.colours)
            elif name == "log_dir":
                found = log_folder(value) if isinstance(value, str) else None
                if found is None:
                    raise Refused("there is no such folder")
                value = found
            elif name in checks:
                value = checks[name](value)
            else:
                continue  # not a setting of this version, or one that stays on its own PC
        except Refused as why:
            reason = str(why)
            refused.append(f"{reason}." if name == "hotkeys" else f"{NAMES.get(name, name)}: {reason}.")
            continue
        if getattr(cfg, name) != value:
            setattr(cfg, name, value)
            changed.add(name)
    return changed, refused


# ---- one line of text -----------------------------------------------------------------------

def export(cfg: Config) -> str:
    """Every setting but those of ``NOT_EXPORTED``, as one line to paste somewhere else."""
    kept = {key: value for key, value in asdict(cfg).items() if key not in NOT_EXPORTED}
    packed = zlib.compress(json.dumps(kept, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9)
    return _LINE_PREFIX + base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")


def read_line(line) -> dict:
    """The settings in a line made by ``export``. Refused when it is not one."""
    text = "".join(str(line or "").split())
    if not text.startswith(_LINE_PREFIX):
        raise Refused(f"That is not a line of meter settings. One starts with {_LINE_PREFIX}")
    if len(text) > _LINE_LIMIT:
        raise Refused("That line is too long to be meter settings.")
    body = text[len(_LINE_PREFIX):]
    try:
        packed = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        unpacker = zlib.decompressobj()
        raw = unpacker.decompress(packed, _JSON_LIMIT)
        if unpacker.unconsumed_tail or not unpacker.eof:
            raise ValueError("too long, or cut short")
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, binascii.Error, zlib.error) as exc:
        raise Refused("That line is damaged: part of it may be missing. Copy it again, whole.") from exc
    if not isinstance(data, dict):
        raise Refused("That line is damaged: part of it may be missing. Copy it again, whole.")
    return {key: value for key, value in data.items() if key not in NOT_EXPORTED}


def take_line(cfg: Config, line, themes: list[str], languages: list[str]) -> tuple[set[str], list[str]]:
    """Take up the settings of an exported line: all of them, so a setting the line has at its
    default goes back to the default here too."""
    incoming = read_line(line)
    if isinstance(incoming.get("hotkeys"), dict):
        # The line's table as the meter it came from used it: a key written twice there went to
        # the first action only. An action the line leaves out keeps the key it has here.
        table: dict[str, str] = {}
        seen: set[tuple[int, int]] = set()
        for action, key in incoming["hotkeys"].items():
            if action not in hotkeys.DEFAULTS or not isinstance(key, str):
                continue
            parsed = hotkeys.parse(key)
            if parsed is None or parsed in seen:
                key = ""
            else:
                seen.add(parsed)
            table[action] = key
        revision = incoming.get("hotkeys_revision")
        if not isinstance(revision, int) or revision < hotkeys.REVISION:
            table = hotkeys.off_old_defaults(table)  # a line from 0.3.0 or before: F8 is Alt+F8 now
        incoming["hotkeys"] = table
    if isinstance(incoming.get("colours"), dict):
        # the line's colours whole: an element it does not colour goes back to the theme's
        incoming["colours"] = {element: incoming["colours"].get(element, "") for element in ELEMENTS}
    return apply(cfg, incoming, themes, languages)


# ---- what the page shows --------------------------------------------------------------------

def describe(
    cfg: Config, themes: list[str], languages: list[str], game_language: str = "",
    keys_need_ctrl_or_alt: bool = False,
) -> dict:
    """What the settings page shows. ``keys_need_ctrl_or_alt``: the game runs as administrator
    and Waveband does not, so a key without Ctrl or Alt won't reach Waveband (``elevation``)."""
    keys = hotkeys.bindings(cfg.hotkeys)
    colours = cfg.colours if isinstance(cfg.colours, dict) else {}
    return {
        "hotkeys": [
            {"action": action, "label": hotkeys.LABELS[action], "key": hotkeys.spell(keys[action]) or "",
             "default": default,
             "blocked": keys_need_ctrl_or_alt and hotkeys.needs_ctrl_or_alt(keys[action])}
            for action, default in hotkeys.DEFAULTS.items()
        ],
        "keys_need_ctrl_or_alt": keys_need_ctrl_or_alt,
        "elements": list(ELEMENTS),
        "colours": {e: colours[e] for e in ELEMENTS if _COLOUR.match(str(colours.get(e, "")))},
        "theme": cfg.theme,
        "themes": [{"name": name, "label": theme_label(name)} for name in themes],
        "display_unit": cfg.display_unit,
        "compact": bool(cfg.compact),
        "show_keys": bool(cfg.show_keys),
        "hide_between_fights": bool(cfg.hide_between_fights),
        "hide_from_capture": bool(cfg.hide_from_capture),
        "overlay_engine": cfg.overlay_engine if cfg.overlay_engine in ("webview2", "qt") else "webview2",
        "only_over_game": bool(cfg.only_over_game),
        "check_updates": bool(cfg.check_updates),
        "auto_update": bool(cfg.auto_update),
        # the channel in use, so the page shows Beta on a beta of Waveband until one is chosen
        "update_channel": effective_channel(cfg.update_channel),
        "overlay_zoom": cfg.overlay_zoom,
        "zoom_range": list(ZOOM),
        "row_figures": row_figures(cfg.row_figures),
        "figures": [{"name": name, "label": label, "note": note} for name, label, note in FIGURES],
        "figure_decimals": decimals(cfg.figure_decimals, 2),
        "share_decimals": decimals(cfg.share_decimals, 0),
        "language": cfg.language if cfg.language in languages else "",
        "languages": [{"code": code, "label": LANGUAGE_LABELS.get(code, code)} for code in languages],
        "game_language": LANGUAGE_LABELS.get(game_language, game_language),
        "log_dir": cfg.log_dir,
        "log_found": os.path.isfile(cfg.log_path),
        "line": export(cfg),
    }
