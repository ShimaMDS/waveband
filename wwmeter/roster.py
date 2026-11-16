"""Display names and elements for the game's internal names.

Characters are identified by the game's numeric ID, which every skill ID in the log starts with
(skill 1107051 belongs to character 1107). ``data/characters.json`` maps those IDs to a name,
element and weapon. The game's own text tables (``gamedata.EnemyData.character_name``) have the
name in each of the game's languages, and that one is shown when the tables are passed in; the
name in ``characters.json`` is what is left when they are not, or do not know the character.
``data/names.json`` holds hand-written names for anything else, keyed by internal name (enemies,
mostly). Whatever is in none of them is shown under a tidied internal name, so the meter keeps
working when a new character ships before the tables are updated. A character the game's
tables know and ``characters.json`` does not gets its name and its element from the tables, so
one that ships with a patch has both as soon as the tables are updated.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable

from .config import ROOT

CHARACTERS_PATH = os.path.join(ROOT, "data", "characters.json")
NAMES_PATH = os.path.join(ROOT, "data", "names.json")
ELEMENTS = ("glacio", "fusion", "electro", "aero", "spectro", "havoc")

_PREFIX = re.compile(r"^BP_")
_VARIANT = re.compile(r"(Md|_)\d+.*$")
_WORDS = re.compile(r"(?<=[a-z])(?=[A-Z])")


def tidy(actor: str) -> str:
    """BP_ME1JiancuxiongMd00001 -> 'Jiancuxiong'; BP_Feixue -> 'Feixue'."""
    name = _PREFIX.sub("", actor)
    name = _VARIANT.sub("", name)
    name = re.sub(r"^(ME|MO|MB|SM)\d+", "", name) or name
    name = re.sub(r"[\d_]+$", "", name) or name
    return _WORDS.sub(" ", name).strip() or actor


def _key(name: str) -> str:
    return tidy(name).replace(" ", "").lower()


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


# The IDs the game gives playable characters. Its table of names also has rows for other things
# that can be played for a while (echoes, story stand-ins) under other numbers.
_PLAYABLE = range(1000, 2000)


class Roster:
    def __init__(
        self, characters: str = CHARACTERS_PATH, names: str = NAMES_PATH,
        game_name: Callable[[int], str] | None = None,
        game_element: Callable[[int], str] | None = None,
    ) -> None:
        """``game_name`` gives the game's own name for a character ID, in whatever language is
        wanted at the moment it is asked, or '' when it has none. ``game_element`` gives its
        element the same way, for a character ``characters`` does not have."""
        self._game_name = game_name
        self._game_element = game_element
        self._by_id: dict[int, dict] = {}
        self._by_name: dict[str, dict] = {}
        for role_id, entry in _load(characters).get("characters", {}).items():
            if not isinstance(entry, dict):
                continue
            try:
                self._by_id[int(role_id)] = entry
            except ValueError:
                continue
            if entry.get("codename"):
                self._by_name.setdefault(_key(entry["codename"]), entry)
        for name, entry in _load(names).items():
            if isinstance(entry, dict):
                self._by_name[_key(name)] = entry  # hand-written names win over codenames

    def role_id_of(self, skill_id: str) -> int | None:
        """The character a skill ID belongs to, if it is a character's skill at all."""
        if len(skill_id) < 7 or not skill_id.isdigit():
            return None
        role_id = int(skill_id[:4])
        if role_id in self._by_id:
            return role_id
        # a character newer than characters.json, which the game's tables already name
        if role_id in _PLAYABLE and self._game_name is not None and self._game_name(role_id):
            return role_id
        return None

    def lookup(self, actor: str, role_id: int | None = None) -> tuple[str, str | None]:
        """(display name, element or None) for a blueprint name, or better, a character ID."""
        entry = self._by_id.get(role_id) if role_id is not None else None
        named = self._game_name(role_id) if role_id is not None and self._game_name is not None else ""
        if entry is None and not named:
            entry = self._by_name.get(_key(actor))
        if entry is None:
            element = self._game_element(role_id) if named and self._game_element is not None else None
            return named or tidy(actor), element if element in ELEMENTS else None
        element = entry.get("element")
        return named or entry.get("name") or tidy(actor), element if element in ELEMENTS else None
