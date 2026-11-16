"""Hotkey names as written in config.json ("F8", "Ctrl+Alt+M") to what Windows wants.

The defaults are function keys the game leaves alone, two of them with Shift. The game's own key
table (3.8) binds F1 to F4 to menus and uses F1 to F6 to switch tabs inside menus; F12 is avoided
because Windows reserves it for debuggers and Steam takes screenshots with it.
"""

from __future__ import annotations

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x1, 0x2, 0x4, 0x8

# action -> key. The order is the order of the tray menu.
DEFAULTS = {
    "older": "F7",          # look at the fight before the one on show
    "newer": "Shift+F7",    # and back towards the running one
    "toggle": "F8",   # show or hide the overlay
    "compact": "Shift+F8",  # one-line meter
    "unit": "F9",     # damage or percent of HP
    "reset": "F10",   # start a new fight
    "move": "F11",    # move or resize the overlay
    # Hiding the overlay from screenshots and streams has no key unless one is set: pressed by
    # accident it makes the overlay vanish from every screenshot with nothing on screen to say why.
    "capture": "",
    "hints": "",      # show or hide the line of keys on the meter (tray menu by default)
    "rest": "",       # hide the meter between fights, or stop hiding it (tray menu by default)
    "copy": "",       # put the summary of the fight on show on the clipboard (tray menu by default)
}
# What each key is called in the line of keys along the top of the meter. The line has room for
# about five, so the two Shift keys are left to the tray menu, which lists every key.
_HINT_LABELS = {
    "older": "earlier", "toggle": "hide", "unit": "dmg / %", "reset": "new fight", "move": "move",
    "capture": "screenshots", "hints": "keys", "rest": "auto-hide", "copy": "copy",
}

# What each action does, as the settings page says it.
LABELS = {
    "older": "Show the fight before this one",
    "newer": "Show the fight after this one",
    "toggle": "Show or hide the meter",
    "compact": "One-line meter, or the full one",
    "unit": "Damage, or percent of the enemy's HP",
    "reset": "Start a new fight",
    "move": "Move or resize the meter",
    "capture": "Hide the meter from screenshots and streams",
    "hints": "Show the keys on the meter",
    "rest": "Hide the meter between fights",
    "copy": "Copy the fight's summary",
}

_MODIFIERS = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN,
}
_MODIFIER_NAMES = ((MOD_CONTROL, "Ctrl"), (MOD_ALT, "Alt"), (MOD_SHIFT, "Shift"), (MOD_WIN, "Win"))
_NAMED = {
    "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "pause": 0x13, "scrolllock": 0x91, "numlock": 0x90, "tab": 0x09, "space": 0x20,
}
_NAMED_SPELLING = {
    "insert": "Insert", "delete": "Delete", "home": "Home", "end": "End", "pageup": "PageUp",
    "pagedown": "PageDown", "pause": "Pause", "scrolllock": "ScrollLock", "numlock": "NumLock",
    "tab": "Tab", "space": "Space",
}


def parse(text: str) -> tuple[int, int] | None:
    """(modifier flags, virtual-key code) for a name like 'F8' or 'Ctrl+Alt+M'.

    None when the name is empty (the action has no hotkey) or cannot be understood.
    """
    parts = [part.strip().lower() for part in str(text or "").split("+")]
    if not parts or not all(parts):
        return None
    modifiers = 0
    for part in parts[:-1]:
        if part not in _MODIFIERS:
            return None
        modifiers |= _MODIFIERS[part]
    key = parts[-1]
    if key[0] == "f" and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return modifiers, 0x70 + int(key[1:]) - 1
    if len(key) == 1 and (key.isascii() and key.isalnum()):
        return modifiers, ord(key.upper())
    if key in _NAMED:
        return modifiers, _NAMED[key]
    return None


def spell(text: str) -> str | None:
    """A key name written one way: 'alt + control + m' is 'Ctrl+Alt+M'. '' for no key, None
    for a name that cannot be understood."""
    if not str(text or "").strip():
        return ""
    parsed = parse(text)
    if parsed is None:
        return None
    key = str(text).split("+")[-1].strip().lower()
    names = [name for flag, name in _MODIFIER_NAMES if parsed[0] & flag]
    return "+".join(names + [_NAMED_SPELLING.get(key, key.upper())])


def bindings(configured: dict | None) -> dict[str, str]:
    """The key for every action: the defaults, with whatever config.json overrides.

    An action set to an empty string has no hotkey. Unknown actions are ignored. A key that
    cannot be understood, or one already given to an earlier action, is dropped.
    """
    chosen = dict(DEFAULTS)
    if isinstance(configured, dict):
        for action, key in configured.items():
            if action in chosen and isinstance(key, str):
                chosen[action] = key.strip()
    taken: set[tuple[int, int]] = set()
    for action, key in chosen.items():
        parsed = parse(key)
        if parsed is None or parsed in taken:
            chosen[action] = ""
        else:
            taken.add(parsed)
    return chosen


def with_new_actions(configured: dict) -> dict[str, str]:
    """A hotkey table from config.json, with the actions added since it was written.

    A new action gets its default key, unless the file already gives that key to something:
    then it gets none, so a key the user chose is never taken away by an update.
    """
    used = {parse(key) for key in configured.values() if isinstance(key, str)} - {None}
    merged = {}
    for action, key in DEFAULTS.items():
        if action in configured:
            merged[action] = configured[action]
        else:
            merged[action] = "" if parse(key) in used else key
    return merged


def in_use(keys: list[str]) -> list[str]:
    """Those of ``keys`` that some program already holds as a system-wide hotkey right now.

    Found by asking Windows for each key and giving it straight back. The meter's own keys
    count as held while it is running with the game in front.
    """
    import ctypes

    user32 = ctypes.windll.user32
    held = []
    for number, name in enumerate(keys):
        parsed = parse(name)
        if parsed is None:
            continue
        probe = 0xB000 + number  # an ID no hotkey of the meter's uses
        if user32.RegisterHotKey(None, probe, parsed[0], parsed[1]):
            user32.UnregisterHotKey(None, probe)
        else:
            held.append(name)
    return held


def hints(configured: dict | None) -> list[dict[str, str]]:
    """The keys in use and a word for what each does, for the line along the top of the meter."""
    return [
        {"key": key, "label": _HINT_LABELS[action]}
        for action, key in bindings(configured).items()
        if key and action in _HINT_LABELS
    ]
