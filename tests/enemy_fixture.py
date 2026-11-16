"""A small stand-in for data/enemy_hp.json, with the real figures the formula was checked on."""

import json
import os
import tempfile

from wwmeter.gamedata import EnemyData

_CURVE = [10000] * 120
_CURVE[79] = 1563733  # level 80 on the game's curve 0
_CURVE[89] = 2626059  # level 90
_CURVE[99] = 3644493  # level 100
_STEEP = [20000] * 120

TABLES = {
    "game_version": "test",
    "blueprint_names": ["MonsterA", "MonsterB", "MonsterC"],
    # per enemy type: [HP row, growth curve, extra rate, name, rest of the boss title, level the
    # bar shows]; the last three are places in text_keys
    "blueprints": [[100, None, None, 0, 1], [200, 3001, 77, 2], [100, None, None, 6, 7]],
    "template_ids": {"9001": "MonsterA", "9002": "MonsterC"},
    # map -> entity -> [type index, HP row, level, growth curve, extra rate, name, rest of the
    # boss title, level the bar shows]
    "level": {
        "50": {"7": [0, 101, 80, None, None, None, None, 4]},
        "51": {"7": [0, 102, 90]},
        "52": {"8": [0]},
        "53": {"8": [0]},
    },
    "prefab": {
        "400": {"1": [0, 103]},
        "401": {"2": [1]},
        "402": {"3": [1, None, None, None, 0]},
        "403": {"4": [0, 103, None, None, None, 3, 5]},  # its own name, and no second part
        "404": {"5": [0, 999]},  # an HP row the tables do not have
    },
    "life": {"100": 690, "101": 6549, "102": 9892, "103": 15120, "200": 4680},
    "curves": {"0": _CURVE, "3001": _STEEP},
    # instance -> [map, level of the enemies in it (0: not fixed)]
    "instances": {"3927": [50, 0], "3925": [51, 0], "20019": [90, 100], "8": [52, 0]},
    "text_keys": ["Entity_a", "Sub_a", "Entity_b", "Entity_c", "Level_90", "Sub_none", "Entity_d", "Sub_d"],
    "text": {
        "en": ["Crownless", ": Newborn Desires", "???", "Cadanto", "90", "", "The False Sovereign",
               "The False Sovereign: Dark Serpent"],
        "ja": ["無冠者", "・芽生える欲望", "???", "", "９０", "", "", ""],
    },
    # language -> character ID -> the game's name for that playable character
    "characters": {
        "en": {"1107": "Carlotta", "1408": "Rover: Aero", "1999": "Newcomer", "5001": "Cruisewing"},
        "ja": {"1107": "カルロッタ"},
    },
}


def enemy_data(language: str = "en", tables: dict | None = None) -> EnemyData:
    handle, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(TABLES if tables is None else tables, fh)
        return EnemyData(path, language)
    finally:
        os.remove(path)
