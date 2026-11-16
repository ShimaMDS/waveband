"""An enemy's full HP and its name, from the game's own tables.

The game computes it as ``LifeMax x LifeMaxRatio(level) / 10000``, rounded down. ``LifeMax`` is a
base-property row, the ratio a growth curve. Which row applies depends on where the enemy was
placed: the same boss has one row in the open world, another per Tactical Hologram difficulty,
another in the Tower of Adversity. The log says which placement an enemy is when it spawns::

    [Entity] [实体生命周期:创建实体] 实体详细数据。 [CreatureDataId: 13974] ... [ConfigType: Prefab]
        [EntityType: Monster][PbDataId: 1850002][PrefabId: 405850005] ...

``CreatureDataId`` is the number combat lines call ``EntityId``. ``ConfigType`` says where to look
``PbDataId`` up: in a prefab, in the level (the map the player is in, which the log gives as
``[CreatureController.JoinSceneNotify] Begin [InstanceId: n]``), or among the bare templates.

The same placement says what the enemy is called, as keys into the game's text table: its name,
for a boss the rest of the title on its bar, and now and then the level the bar shows when that is
not the level HP is worked out from. The text is kept for each language the game has, and the one
the player's client is set to is used, so the meter names an enemy the way the game does. The
client's language is read from the settings the game saves beside its logs, and read again when
they change, so switching the game's language switches the names.

``data/enemy_hp.json`` holds those tables boiled down; ``wwmeter update`` (``update.py``)
rebuilds it after a game patch, and a running meter then reads it again (``EnemyData.reload``).
Without the file everything here answers "unknown" and the meter works as it did before.

Some placements multiply the HP by an "extra rate" the client's data does not hold, and some fix
no level, so the tables alone give those no HP. Many bosses have breakable parts, though, whose
own pools the log reports and which are a fixed share of the full HP wherever the boss is placed
(``PartShares``): the share is learned where the HP is known and turns a pool back into the full
HP where it is not.
"""

from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import time
from dataclasses import dataclass

from .config import CONFIG_PATH, ROOT
from .logparse import LogEvent

ENEMY_HP_PATH = os.path.join(ROOT, "data", "enemy_hp.json")
# The shares that come with the meter, and the ones this PC has learned since.
PART_SHARES_PATH = os.path.join(ROOT, "data", "part_shares.json")
LEARNED_PARTS_PATH = os.path.join(os.path.dirname(os.path.abspath(CONFIG_PATH)), "learned_parts.json")
# A part's pool is taken for a share of the HP only when it is a round one, to a tenth of a
# percent: the shares seen are 2%, 15%, 17% and 25%, and a pool first seen after the part had
# been hit would not land on a round figure.
_SHARE_PLACES = 3
_WHOLE_HP = 0.995  # a "part" with this much of the HP is the HP itself
_SPAWN_LIMIT = 4000
# What the text table holds for enemies that were never given a name.
_NO_NAME = ("", "???", "placeholder")
# Where the client keeps its language, as paths from the folder above the log folder ("Saved").
# The game writes the language chosen in its settings to the first at once, as a number. The
# second names it too ("Culture=ko") but is only brought up to date when the game closes.
_CLIENT_STORE = os.path.join("LocalStorage", "LocalStorage.db")
_CLIENT_SETTINGS = os.path.join("Config", "WindowsNoEditor", "GameUserSettings.ini")
# The game's numbers for its languages (its "languagedefine" table, as of 3.8). The built file
# carries the table of the version it was built for; this is for a file built before it did.
LANGUAGE_IDS = {
    0: "zh-Hans", 1: "en", 2: "ja", 3: "ko", 4: "ru", 5: "zh-Hant", 6: "de",
    7: "es", 8: "pt", 9: "id", 10: "fr", 11: "vi", 12: "th",
}
# Codes other programs use for the two Chinese scripts.
_SCRIPTS = {
    "zh": "zh-hans", "zh-cn": "zh-hans", "zh-sg": "zh-hans",
    "zh-tw": "zh-hant", "zh-hk": "zh-hant", "zh-mo": "zh-hant",
}


def _stored_language(saved: str) -> int | None:
    """The number of the text language in the game's own settings store, or None when it holds
    none or cannot be read. The store is an SQLite file the running game has open: it is opened
    read-only and without taking any lock, so the game is never kept waiting on it."""
    path = os.path.join(saved, _CLIENT_STORE)
    if not os.path.isfile(path):
        return None
    try:
        db = sqlite3.connect(pathlib.Path(path).as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            row = db.execute("select value from LocalStorage where key = 'TextLanguage'").fetchone()
        finally:
            db.close()
        return int(str(row[0]).strip().strip('"')) if row else None
    except (sqlite3.Error, ValueError, OSError):
        return None


def client_language(log_dir: str, ids: dict[int, str] | None = None) -> str:
    """The language the game client is set to ("en", "ja", "zh-Hans", ...), from the settings
    the game keeps beside its logs. "" when they are not there or do not say."""
    saved = os.path.dirname(os.path.abspath(log_dir))
    stored = (ids or LANGUAGE_IDS).get(_stored_language(saved))
    if stored:
        return stored
    path = os.path.join(saved, _CLIENT_SETTINGS)
    try:
        with open(path, "rb") as fh:
            raw = fh.read(1 << 20)
    except OSError:
        return ""
    encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8"
    for line in raw.decode(encoding, errors="replace").splitlines():
        key, _, value = line.partition("=")
        if key.strip().lower() == "culture" and value.strip():
            return value.strip()
    return ""


class ClientLanguage:
    """The game client's language, for asking often: the files are looked at every few seconds
    at most and read again only when one of them has changed."""

    def __init__(self, log_dir: str, ids: dict[int, str] | None = None, every: float = 3.0) -> None:
        self._log_dir = log_dir
        self._ids = ids
        self._every = every
        self._checked = float("-inf")
        self._seen: tuple | None = None
        self._language = ""

    def _state(self) -> tuple:
        saved = os.path.dirname(os.path.abspath(self._log_dir))
        state = []
        for name in (_CLIENT_STORE, _CLIENT_STORE + "-journal", _CLIENT_SETTINGS):
            try:
                found = os.stat(os.path.join(saved, name))
                state.append((found.st_mtime_ns, found.st_size))
            except OSError:
                state.append(None)
        return tuple(state)

    def current(self) -> str:
        now = time.monotonic()
        if now - self._checked >= self._every:
            self._checked = now
            state = self._state()
            if state != self._seen:
                self._seen = state
                self._language = client_language(self._log_dir, self._ids)
        return self._language


def pick_language(available, wanted: str) -> str:
    """The language among ``available`` that ``wanted`` means: itself whatever its case, the
    script for a regional Chinese code, the plain language for a regional one ("pt-BR": "pt"),
    and English when it is not there at all."""
    codes = {code.lower(): code for code in available}
    wanted = wanted.strip().lower().replace("_", "-")
    for code in (wanted, _SCRIPTS.get(wanted, ""), wanted.split("-")[0], "en"):
        if code in codes:
            return codes[code]
    return ""


@dataclass(frozen=True, slots=True)
class Enemy:
    blueprint: str  # the game data's name for the enemy type, e.g. Monster104
    life_max: int
    curve: str  # growth curve ID
    level: int | None  # set by the placement or the instance; None when only the screen says
    # False when the placement names an extra rate. The tables that define those are not in the
    # client, so HP worked out for such an enemy could be off and is not offered.
    exact: bool
    # What the game calls it, in the language asked for: for a boss the whole title of its bar
    # ("Inferno Rider: Blazing Guardian"). "" when the tables give it no name.
    name: str = ""
    # The level its bar shows, where the game sets one that is not the level above.
    shown_level: int | None = None
    shown_text: str = ""  # that level as the tables write it: "90", or "?" for one kept hidden


class EnemyData:
    def __init__(self, path: str = ENEMY_HP_PATH, language: str = "en") -> None:
        self._path = path
        self.language: str = ""  # the one names are given in
        self.names_version = 0  # goes up each time the names may have changed
        self._client: ClientLanguage | None = None
        self._read()
        self.set_language(language)

    def _read(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        self.version: str = str(data.get("game_version") or "")  # the game the tables are for
        self.built: str = str(data.get("built") or "")  # the day they were boiled down
        self._names: list[str] = data.get("blueprint_names", [])
        self._blueprints: list[list] = data.get("blueprints", [])
        self._template_ids: dict[str, str] = data.get("template_ids", {})
        self._level: dict[str, dict[str, list]] = data.get("level", {})
        self._prefab: dict[str, dict[str, list]] = data.get("prefab", {})
        self._life: dict[str, int] = data.get("life", {})
        self._curves: dict[str, list[int]] = data.get("curves", {})
        self._instances: dict[str, list[int]] = data.get("instances", {})
        self._texts: dict[str, list[str]] = data.get("text", {})
        # language -> character ID -> what the game calls that playable character
        self._characters: dict[str, dict[str, str]] = data.get("characters", {})
        # character ID -> element; empty in a file built before the tables carried them
        elements = data.get("elements")
        self._elements: dict[str, str] = elements if isinstance(elements, dict) else {}
        self.languages: list[str] = list(self._texts)
        try:
            self.language_ids = {int(key): str(code) for key, code in data.get("language_ids", {}).items()}
        except ValueError:
            self.language_ids = {}
        self.language_ids = self.language_ids or dict(LANGUAGE_IDS)
        self._text: list[str] = self._texts.get(self.language, [])
        self._english: list[str] = self._texts.get("en", [])
        self._character: dict[str, str] = self._characters.get(self.language, {})
        self._index = {name: index for index, name in enumerate(self._names)}
        self._maps_of: dict[str, list[str]] | None = None  # level entity -> maps it is placed in

    def reload(self) -> None:
        """Read the file again, after an update wrote a new one. The language asked for stays,
        and everything found before is to be looked up afresh (``names_version`` goes up)."""
        wanted = self.language
        self._read()
        self.language = ""
        self.set_language(wanted)
        self.names_version += 1

    def __bool__(self) -> bool:
        return bool(self._life and self._curves)

    def set_language(self, wanted: str) -> bool:
        """Give names in ``wanted`` from now on (or what stands in for it). True when that is a
        change. Enemies found before keep the name they were found with."""
        language = pick_language(self._texts, wanted)
        changed = language != self.language
        self.language = language
        self._text = self._texts.get(language, [])
        self._character = self._characters.get(language, {})
        if changed:
            self.names_version += 1
        return changed

    def follow(self, client: ClientLanguage) -> None:
        """Keep to the game client's language, whatever it is changed to."""
        self._client = client
        self.refresh()

    def fix_language(self, wanted: str) -> None:
        """Give names in ``wanted`` whatever the game client is set to."""
        self._client = None
        self.set_language(wanted)

    def refresh(self) -> bool:
        """Look whether the client's language has changed. True when the names' language did."""
        if self._client is None:
            return False
        return self.set_language(self._client.current())

    def character_name(self, role_id: int | None) -> str:
        """What the game calls the playable character with this ID, in the language names are
        given in, in English where that language has none, '' when the tables do not know it.
        Asked afresh each time it is shown, so it follows a change of language at once."""
        key = str(role_id)
        return self._character.get(key) or self._characters.get("en", {}).get(key, "")

    def element(self, role_id: int | None) -> str:
        """The element of the playable character with this ID, '' when the tables do not say."""
        return self._elements.get(str(role_id), "")

    def find(self, config_type: str, pb_data_id: int, prefab_id: int, instance_id: int | None) -> Enemy | None:
        """The enemy a spawn line describes, or None when the tables do not have it."""
        if not self:
            return None
        key = str(pb_data_id)
        instance = self._instances.get(str(instance_id)) if instance_id is not None else None
        record = None
        if config_type == "Prefab":
            record = self._prefab.get(str(prefab_id), {}).get(key)
        elif config_type == "Template":
            name = self._template_ids.get(key)
            record = [self._index[name]] if name in self._index else None
        elif config_type == "Level":
            if instance is not None:
                record = self._level.get(str(instance[0]), {}).get(key)
            if record is None:
                record = self._only_placement(key)
        if record is None:
            return None
        return self._enemy(record, instance)

    def placements(self):
        """Every enemy the tables place in a map, as (map, entity ID, Enemy, whether an
        instance of that map fixes the level of what is in it). For the tools that check the
        tables; a level the placement does not fix is left as None."""
        fixed = {str(instance[0]) for instance in self._instances.values() if instance[1] > 0}
        for map_id, members in self._level.items():
            for entity, record in members.items():
                yield map_id, int(entity), self._enemy(record, None), map_id in fixed

    def _enemy(self, record: list, instance: list[int] | None) -> Enemy:
        own = list(record) + [None] * (8 - len(record))
        base = list(self._blueprints[own[0]]) + [None] * 6
        # an enemy with no HP row is still returned: it has a name, and hp() answers None for it
        life_max = self._life.get(str(own[1] if own[1] is not None else base[0])) or 0
        level = own[2]
        if level is None and instance is not None and instance[1] > 0:
            level = instance[1]
        extra = own[4] if own[4] is not None else base[2]
        curve = own[3] if own[3] is not None else base[1]
        return Enemy(
            blueprint=self._names[own[0]],
            life_max=int(life_max),
            curve=str(curve or 0),
            level=int(level) if level else None,
            exact=not extra,
            name=self._name(*(mine if mine is not None else theirs for mine, theirs in zip(own[5:7], base[3:5]))),
            shown_level=self._shown_level(own[7] if own[7] is not None else base[5]),
            shown_text=self._words(own[7] if own[7] is not None else base[5], english=True),
        )

    def _words(self, ref: int | None, english: bool = False) -> str:
        """The text behind a place in the list of text keys, in English where the language asked
        for has nothing for it."""
        if ref is None:
            return ""
        for table in (self._english,) if english else (self._text, self._english):
            if 0 <= ref < len(table) and table[ref]:
                return table[ref]
        return ""

    def _name(self, name: int | None, rest: int | None) -> str:
        """An enemy's name and, for a boss, the rest of the title on its bar. The rest carries
        its own separator (": Blazing Guardian"), and now and then the whole title."""
        first, second = self._words(name), self._words(rest)
        if first.lower() in _NO_NAME:
            return ""
        return second if second.startswith(first) else first + second

    def _shown_level(self, ref: int | None) -> int | None:
        words = self._words(ref, english=True)  # other languages write the digits their own way
        return int(words) if words.isascii() and words.isdigit() else None

    def _only_placement(self, key: str) -> list | None:
        """A level entity's record when the map is unknown: entity IDs repeat across maps, so
        this only answers when every map that has the ID agrees on what it is."""
        if self._maps_of is None:
            self._maps_of = {}
            for map_id, members in self._level.items():
                for entity in members:
                    self._maps_of.setdefault(entity, []).append(map_id)
        records = [self._level[map_id][key] for map_id in self._maps_of.get(key, [])]
        if records and all(record == records[0] for record in records):
            return records[0]
        return None

    def hp(self, enemy: Enemy | None, level: int | None = None) -> int | None:
        """Full HP at ``level`` (default: the level its placement fixes), or None if unknown."""
        if enemy is None or not enemy.exact or not enemy.life_max:
            return None
        level = level or enemy.level
        curve = self._curves.get(enemy.curve)
        if not level or curve is None or not 1 <= level <= len(curve):
            return None
        return enemy.life_max * curve[level - 1] // 10000


class PartShares:
    """What share of an enemy's full HP each of its breakable parts' own pools is.

    Keyed by the enemy's actor name (``BP_ML1QiShiMd00001``) and the part's tag as the log
    writes them, because the parts belong to the actor whichever placement spawned it: Inferno
    Rider's two were 15% and 25% of its HP in seven placements at seven levels. A share is
    learned from a placement whose HP the tables give, and used on one where they do not. A
    part seen with two different shares is marked as varying (None) and never used.
    """

    def __init__(self, path: str | None = PART_SHARES_PATH, learned_path: str | None = None) -> None:
        self._learned_path = learned_path  # what is learned is kept in this file; None: nowhere
        self._shares: dict[str, dict[str, float | None]] = {}
        self._learned: dict[str, dict[str, float | None]] = {}
        for source, mine in ((path, False), (learned_path, True)):
            for actor, tags in self._read(source).items():
                self._shares.setdefault(actor, {}).update(tags)
                if mine:
                    self._learned.setdefault(actor, {}).update(tags)

    @staticmethod
    def _read(path: str | None) -> dict[str, dict[str, float | None]]:
        if not path:
            return {}
        try:
            with open(path, encoding="utf-8") as fh:
                shares = json.load(fh)["shares"]
        except (OSError, ValueError, KeyError, TypeError):
            return {}
        found: dict[str, dict[str, float | None]] = {}
        if not isinstance(shares, dict):
            return found
        for actor, tags in shares.items():
            if not isinstance(tags, dict):
                continue
            for tag, share in tags.items():
                if share is None:
                    found.setdefault(str(actor), {})[str(tag)] = None
                elif isinstance(share, (int, float)) and not isinstance(share, bool) and 0 < share < _WHOLE_HP:
                    found.setdefault(str(actor), {})[str(tag)] = float(share)
        return found

    def share(self, actor: str, tag: str) -> float | None:
        return self._shares.get(actor, {}).get(tag)

    def learn(self, actor: str, tag: str, pool: float, hp: float) -> bool:
        """Take note of a part's full pool on an enemy whose full HP is known. True when that
        changed what is known."""
        if not actor or not tag or pool <= 0 or hp <= 0:
            return False
        share = pool / hp
        if share >= _WHOLE_HP:
            return False  # this tag reports the enemy's HP itself
        found: float | None = round(share, _SHARE_PLACES)
        if not found or abs(share - found) * hp > 1.0:
            return False  # not a round share: most likely a pool that had already been hit
        known = self._shares.get(actor, {})
        if tag in known:
            if known[tag] is None or abs(known[tag] - found) < 1e-9:
                return False
            found = None  # two different shares for one part: it cannot be relied on
        self._shares.setdefault(actor, {})[tag] = found
        self._learned.setdefault(actor, {})[tag] = found
        self._save()
        return True

    def full_hp(self, actor: str, pools: dict[str, float]) -> int | None:
        """An enemy's full HP from the full pools of its parts, or None when no share is known
        for any of them. A pool first seen after the part was hit reads low, so with several
        parts the highest answer is the one to believe."""
        answers = [
            pool / share for tag, pool in pools.items()
            if pool > 0 and (share := self.share(actor, tag))
        ]
        return round(max(answers)) if answers else None

    def _save(self) -> None:
        if not self._learned_path:
            return
        temporary = self._learned_path + ".tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as fh:
                json.dump({"shares": self._learned}, fh, ensure_ascii=False, indent=1, sort_keys=True)
            os.replace(temporary, self._learned_path)
        except OSError:
            pass  # still known for as long as the meter runs


def game_language(cfg, ids: dict[int, str] | None = None) -> str:
    """The language the settings ask for names in: the one named there, else the game client's."""
    return str(cfg.language or "").strip() or client_language(cfg.log_dir, ids)


def enemy_data(cfg) -> EnemyData:
    """The tables, with names in the language the settings ask for: the one named there, else
    the game client's for as long as the meter runs."""
    data = EnemyData(language=str(cfg.language or "").strip() or "en")
    apply_language(data, cfg)
    return data


def apply_language(data: EnemyData, cfg) -> None:
    """Take up the settings' choice of language for names: the one named there, else the game
    client's for as long as the meter runs. Also for a choice changed while the meter runs."""
    fixed = str(cfg.language or "").strip()
    if fixed:
        data.fix_language(fixed)
    else:
        data.follow(ClientLanguage(cfg.log_dir, data.language_ids))


class Spawns:
    """Remembers which placement each spawned enemy is, from the log's entity lines."""

    def __init__(self, data: EnemyData | None = None) -> None:
        self.data = data if data is not None else EnemyData()
        self.instance: int | None = None  # the instance (map) the player is in
        self._seen: dict[int, tuple[str, int, int, int | None]] = {}
        self._resolved: dict[int, Enemy | None] = {}
        self._names_version = self.data.names_version

    def on_event(self, event: LogEvent) -> None:
        fields = event.fields
        if event.module == "World":
            if "JoinSceneNotify" in event.text and fields.get("InstanceId", "").isdigit():
                self.instance = int(fields["InstanceId"])
            return
        if event.module != "Entity" or fields.get("EntityType") != "Monster":
            return
        try:
            entity = int(fields["CreatureDataId"])
            spawn = (fields["ConfigType"], int(fields["PbDataId"]), int(fields.get("PrefabId") or 0), self.instance)
        except (KeyError, ValueError):
            return
        self._seen.pop(entity, None)  # re-insert so the oldest entries are the ones dropped
        self._seen[entity] = spawn
        self._resolved.pop(entity, None)
        while len(self._seen) > _SPAWN_LIMIT:
            oldest = next(iter(self._seen))
            del self._seen[oldest]
            self._resolved.pop(oldest, None)

    def refresh(self) -> bool:
        """Take up a change of language, the game's or the settings': enemies are named afresh.
        True when it changed."""
        self.data.refresh()
        if self.data.names_version == self._names_version:
            return False
        self._names_version = self.data.names_version
        self._resolved.clear()
        return True

    def placement(self, entity_id: int) -> tuple[str, int, int, int | None] | None:
        """(ConfigType, PbDataId, PrefabId, instance) from the enemy's spawn line, if one was seen."""
        return self._seen.get(entity_id)

    def enemy(self, entity_id: int) -> Enemy | None:
        if entity_id not in self._resolved:
            spawn = self._seen.get(entity_id)
            self._resolved[entity_id] = self.data.find(*spawn) if spawn is not None else None
        return self._resolved[entity_id]
