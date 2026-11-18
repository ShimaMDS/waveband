"""``wwmeter update``: bring data\\enemy_hp.json up to date with the installed game.

The game computes a monster's HP as ``LifeMax x LifeMaxRatio(level) / 10000``. ``LifeMax`` comes
from the base-property row the spawned entity points at, the ratio from a growth curve. Which row
an entity points at depends on where it was placed (a level, a prefab, or a bare template), and
the log names exactly that when the entity spawns. This boils the game's config tables down to
those few lookups.

The same entries say what the enemy is called: a text key for its name, and for a boss a second
one for the rest of the title on its bar ("Inferno Rider" + ": Blazing Guardian") and sometimes a
third for the level the bar shows when that is not the level its HP is worked out from. The text
behind the keys is in the game's text table, one per language. The playable characters' names
come from that table too, and their elements from the game's role table.

The tables are the game's own, as published per version by a community dump of the client's
config files (https://github.com/Arikatsu/WutheringWaves_Data, one branch per game version).
Only JSON is fetched; nothing is run and no game file is touched. The request names the game's
version and nothing else. About 205 MB of tables are downloaded, and 32 to 87 MB more for each
language's text table; the result is about 1.3 MB and the downloads are deleted afterwards.

An update fetches the text of English, of the language the game is set to and of the one the
settings name. The other languages keep the names the file already had for them (an enemy new
with the patch shows in English there). ``--languages all`` fetches every language.

    Waveband.exe update                 # or Settings, The game, "Update boss HP tables"
    python -m wwmeter update --languages all --keep-downloads

A meter that is running does this as a program of its own (``Updater``), so the tables being
rebuilt, some hundreds of MB while they are, never sit in the meter's memory.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable

from .config import LOG_PATH, ROOT
from .gamedata import ENEMY_HP_PATH, client_language, pick_language
from .roster import ELEMENTS

REPO = "Arikatsu/WutheringWaves_Data"
RAW = f"https://raw.githubusercontent.com/{REPO}"
TABLES = {
    "baseproperty.json": "BinData/property/baseproperty.json",
    "monsterpropertygrowth.json": "BinData/property/monsterpropertygrowth.json",
    "templateconfig.json": "BinData/template/templateconfig.json",
    "prefabconfig.json": "BinData/prefab/prefabconfig.json",
    "instancedungeon.json": "BinData/instance_dungeon/instancedungeon.json",
}
# The level-entity table is split into numbered files; they are fetched until one is missing.
LEVEL_ENTITIES = "BinData/level_entity/levelentityconfig_{n}.json"
# The text table, one per language. English is always taken: it stands in where another has a gap.
TEXT = "Textmaps/{language}/multi_text/MultiText.json"
LANGUAGES = ("en", "zh-Hans", "zh-Hant", "ja", "ko", "de", "es", "fr", "id", "pt", "ru", "th", "vi")
# The bestiary. A few enemy types have an empty name of their own and are named only here.
BESTIARY = "BinData/monster_Info/monsterinfo.json"
# The game's numbers for its languages: its own settings name the chosen one by number.
LANGUAGE_IDS = "BinData/menu/languagedefine.json"
# The playable characters, for their elements (the game numbers them 1 to 6, in ELEMENTS' order).
ROLES = "BinData/role/roleinfo.json"
_PLAYABLE_ROLE = 1  # RoleType of a character a player can own; the rest are stand-ins and echoes
# What the text table holds for enemies that were never given a name.
NO_NAME = ("", "???", "placeholder")
# Where the launcher records the installed version, from the log folder (...\Client\Saved\Logs).
_LAUNCHER_RECORD = os.path.join("..", "..", "..", "launcherDownloadConfig.json")
_TIMEOUT = 60.0  # seconds without a byte before a download is given up
# What this leaves in its cache folder, and so what it may delete there.
_OURS = re.compile(
    r"^(?:README\.md|levelentityconfig_\d+\.json|multitext_[\w-]+\.json|monsterinfo\.json|"
    r"languagedefine\.json|roleinfo\.json|" + "|".join(map(re.escape, TABLES)) + r")(?:\.part)?$"
)
# New tables with fewer than this share of the enemy types the old ones had are not trusted.
_SHRUNK = 0.5

Say = Callable[[str], None]


class Failed(Exception):
    """The update could not be done. The message is for the user; nothing was changed."""


def installed_version(log_dir: str) -> str | None:
    """Game version from the launcher's own record, e.g. '3.8.0'. None when it is not there."""
    path = os.path.normpath(os.path.join(log_dir, _LAUNCHER_RECORD))
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read(1 << 20)
    except (OSError, UnicodeDecodeError):
        return None
    match = re.search(r'"version"\s*:\s*"(\d+\.\d+\.\d+)"', text)
    return match.group(1) if match else None


def branch_of(version: str | None) -> str:
    """'3.8.0' -> '3.8': the part of a game version the tables are published under."""
    match = re.match(r"\s*(\d+)\.(\d+)", version or "")
    return f"{match.group(1)}.{match.group(2)}" if match else ""


def out_of_date(game: str | None, tables: str | None) -> bool:
    """True when both versions are known and the tables are for another one than the game's."""
    return bool(branch_of(game) and branch_of(tables) and branch_of(game) != branch_of(tables))


def _get(branch: str, path: str):
    request = urllib.request.Request(f"{RAW}/{branch}/{path}", headers={"User-Agent": "curl/8.0"})
    return urllib.request.urlopen(request, timeout=_TIMEOUT)


def fetch(branch: str, path: str, target: str, say: Say | None = None) -> bool:
    """Download one file into the cache unless it is already there. False when the repository
    does not have it."""
    if os.path.isfile(target) and os.path.getsize(target) > 0:
        return True
    name = os.path.basename(target)  # the text tables all have one name in the repository
    try:
        with _get(branch, path) as response, open(target + ".part", "wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            size, told = 0, time.monotonic()
            while True:
                block = response.read(1 << 18)
                if not block:
                    break
                out.write(block)
                size += len(block)
                if say is not None and time.monotonic() - told >= 1.0:
                    told = time.monotonic()
                    of = f" of {total / 1e6:.0f}" if total else ""
                    say(f"Downloading {name}: {size / 1e6:.0f}{of} MB")
    except urllib.error.HTTPError as exc:
        _discard(target + ".part")
        if exc.code == 404:
            return False
        raise Failed(f"GitHub answered {exc.code} for {name}. Try again later.") from exc
    except OSError as exc:  # no connection, a timeout, a full disk
        _discard(target + ".part")
        raise Failed(f"Couldn't download {name}: {getattr(exc, 'reason', None) or exc}") from exc
    os.replace(target + ".part", target)
    if say is not None:
        say(f"Downloaded {name} ({size / 1e6:.1f} MB)")
    return True


def _discard(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def load(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def optional(path: str) -> list:
    """A table the build can do without: empty when it was not in the repository."""
    return load(path) if os.path.isfile(path) else []


def components(entry: dict) -> dict:
    data = entry.get("ComponentsData") or {}
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return {}
    return data if isinstance(data, dict) else {}


def trimmed(record: list) -> list:
    while record and record[-1] is None:
        record.pop()
    return record


def naming(parts: dict) -> tuple:
    """The text keys an entry sets itself: (name, rest of the boss title, level the bar shows)."""
    view = (parts.get("MonsterComponent") or {}).get("BossViewConfig") or {}
    return (
        (parts.get("BaseInfoComponent") or {}).get("TidName") or None,
        view.get("TidBossSubTitle") or None,
        view.get("TidLevelText") or None,
    )


def text_ref(keys: dict[str, int], key: str | None) -> int | None:
    """A text key's place in the list of keys, which is what the records store."""
    return None if key is None else keys.setdefault(key, len(keys))


def bestiary(cache: str) -> dict[str, str]:
    """The name key the game's bestiary has for an enemy type, by the type's name in lower case
    (the two tables do not always agree on its case). Empty when the table was not fetched."""
    names: dict[str, str] = {}
    for row in optional(os.path.join(cache, "monsterinfo.json")):
        if row.get("MonsterEntityID") and row.get("Name"):
            names.setdefault(str(row["MonsterEntityID"]).lower(), row["Name"])
    return names


def text_table(cache: str, language: str) -> dict[str, str]:
    rows = load(os.path.join(cache, f"multitext_{language}.json"))
    return {row["Id"]: str(row.get("Content") or "").strip() for row in rows}


class Types:
    """The enemy types (blueprints) and the list of text keys their names use."""

    def __init__(self) -> None:
        self.records: dict[str, list] = {}
        self.naming: dict[str, tuple] = {}
        self.order: dict[str, int] = {}
        self.keys: dict[str, int] = {}

    def placed(self, blueprint: str, entry: dict) -> list | None:
        """[blueprint index, PropertyId, Level, growth curve, extra rate, name, rest of the boss
        title, level the bar shows], each None unless this placement sets it itself and
        differently (the blueprint's own values are kept separately). The last three are places
        in the list of text keys. A placement that sets a key replaces the blueprint's one and
        leaves its others alone: the open-world bosses set only when their bar shows, and still
        carry their type's title in the game."""
        if blueprint not in self.records:
            return None
        parts = components(entry)
        own = parts.get("AttributeComponent") or {}
        named = [
            text_ref(self.keys, key) if key != inherited else None
            for key, inherited in zip(naming(parts), self.naming[blueprint])
        ]
        return trimmed([
            self.order[blueprint],
            own.get("PropertyId"),
            own.get("Level"),
            own.get("MonsterPropGrowthId"),
            own.get("MonsterPropExtraRateId"),
            *named,
        ])


def build(cache: str, say: Say = print) -> dict:
    templates = load(os.path.join(cache, "templateconfig.json"))
    types = Types()
    blueprints = types.records
    template_ids: dict[str, str] = {}
    english = text_table(cache, "en")
    listed = bestiary(cache)
    borrowed = 0
    for entry in templates:
        parts = components(entry)
        category = (parts.get("BaseInfoComponent") or {}).get("Category") or {}
        # Most enemies are typed "Monster". A few bosses (Dreamless among them) carry no type
        # at all and are told apart by their monster component.
        kind = category.get("MainType")
        if kind != "Monster" and not (kind is None and "MonsterComponent" in parts):
            continue
        attr = parts.get("AttributeComponent") or {}
        name = entry["BlueprintType"]
        # what placements are compared with stays the type's own keys; what the type is called
        # may come from the bestiary instead
        types.naming[name] = own = naming(parts)
        other = listed.get(name.lower())
        if english.get(own[0] or "", "").lower() in NO_NAME and english.get(other or "", "").lower() not in NO_NAME:
            own = (other, *own[1:])
            borrowed += 1
        blueprints[name] = trimmed([
            attr.get("PropertyId"), attr.get("MonsterPropGrowthId") or None,
            attr.get("MonsterPropExtraRateId") or None,
            *(text_ref(types.keys, key) for key in own),
        ])
        template_ids[str(entry["Id"])] = name
    del templates, english
    if borrowed:
        print(f"  {borrowed} enemy types with no name of their own are named from the bestiary")
    names = sorted(blueprints)
    types.order = {name: index for index, name in enumerate(names)}

    level: dict[str, dict[str, list]] = {}
    n = 1
    while os.path.isfile(os.path.join(cache, f"levelentityconfig_{n}.json")):
        say(f"Reading the tables: where enemies are placed, part {n}")
        for entry in load(os.path.join(cache, f"levelentityconfig_{n}.json")):
            record = types.placed(entry.get("BlueprintType", ""), entry)
            if record is not None:
                level.setdefault(str(entry["MapId"]), {})[str(entry["EntityId"])] = record
        n += 1

    prefab: dict[str, dict[str, list]] = {}
    for entry in load(os.path.join(cache, "prefabconfig.json")):
        members = entry.get("Entities") or []
        if isinstance(members, str):
            members = json.loads(members)
        for member in members:
            data = member.get("EntityData") or {}
            record = types.placed(data.get("BlueprintType", ""), data)
            if record is not None:
                prefab.setdefault(str(entry["Id"]), {})[str(data["Id"])] = record

    used = {values[0] for values in blueprints.values() if values and values[0]}
    for group in (level, prefab):
        for members in group.values():
            used.update(record[1] for record in members.values() if len(record) > 1 and record[1])
    life = {
        str(row["Id"]): row["LifeMax"]
        for row in load(os.path.join(cache, "baseproperty.json"))
        if row["Id"] in used
    }

    curves: dict[str, list[int]] = {}
    for row in load(os.path.join(cache, "monsterpropertygrowth.json")):
        curve = curves.setdefault(str(row["CurveId"]), [])
        if row["Level"] != len(curve) + 1:
            raise Failed(f"Growth curve {row['CurveId']} is not listed level by level. Nothing was changed.")
        curve.append(row["LifeMaxRatio"])

    instances = {
        str(row["Id"]): [row["MapConfigId"], row.get("EntityLevel") or 0]
        for row in load(os.path.join(cache, "instancedungeon.json"))
    }
    return {
        "blueprint_names": names,
        "blueprints": [blueprints[name] for name in names],
        "template_ids": template_ids,
        "level": level,
        "prefab": prefab,
        "life": life,
        "curves": curves,
        "instances": instances,
        "text_keys": list(types.keys),
    }


def elements(cache: str) -> dict[str, str]:
    """The element of each playable character, by character ID. Empty when the role table was
    not fetched; ``data\\characters.json`` then stands alone, as it did before."""
    out: dict[str, str] = {}
    for row in optional(os.path.join(cache, "roleinfo.json")):
        number = row.get("ElementId")
        if row.get("RoleType") == _PLAYABLE_ROLE and isinstance(number, int) and 1 <= number <= len(ELEMENTS):
            out[str(row["Id"])] = ELEMENTS[number - 1]
    return out


# The text key of a playable character's name: "RoleInfo_1107_Name" is Carlotta's, and 1107 is
# the ID every one of her skill IDs in the log starts with.
CHARACTER_NAME = re.compile(r"^RoleInfo_(\d+)_Name$")


def texts(
    cache: str, keys: list[str], languages: list[str], say: Say = print
) -> tuple[dict[str, list[str]], dict[str, dict[str, str]]]:
    """Each language's text for the keys, in the keys' order, and each language's names for the
    playable characters, by character ID. A text a language lacks is left empty there, and the
    meter falls back to English for it. A language with hardly any of them (the dump has tables
    for languages the game does not offer yet) is left out altogether."""
    out: dict[str, list[str]] = {}
    characters: dict[str, dict[str, str]] = {}
    for language in languages:
        say(f"Reading the tables: names in '{language}'")
        table = text_table(cache, language)
        words = [table.get(key, "") for key in keys]
        if language != "en":
            wanted = [index for index, word in enumerate(out["en"]) if word]
            missing = sum(1 for index in wanted if not words[index])
            if missing * 2 > len(wanted):
                print(f"  {language}: {missing} of {len(wanted)} names are empty in its text table: left out")
                continue
            if missing:
                print(f"  {language}: {missing} of {len(wanted)} names are empty and will show in English")
        out[language] = words
        characters[language] = {
            match.group(1): word
            for match, word in ((CHARACTER_NAME.match(key), word) for key, word in table.items())
            if match and word and word not in NO_NAME
        }
    return out, characters


def carried(previous: dict, keys: list[str], fetched) -> tuple[dict[str, list[str]], dict[str, dict[str, str]]]:
    """What the file had for the languages this update did not fetch, laid out for the new list
    of keys. A key the old file did not have stays empty, and shows in English."""
    old_keys = previous.get("text_keys")
    old_texts = previous.get("text")
    old_characters = previous.get("characters")
    out: dict[str, list[str]] = {}
    characters: dict[str, dict[str, str]] = {}
    if not isinstance(old_keys, list) or not isinstance(old_texts, dict):
        return out, characters
    for language, words in old_texts.items():
        if language in fetched or not isinstance(words, list):
            continue
        known = dict(zip(old_keys, words))
        out[language] = [known.get(key, "") for key in keys]
        kept = old_characters.get(language) if isinstance(old_characters, dict) else None
        characters[language] = kept if isinstance(kept, dict) else {}
    return out, characters


def _in_order(by_language: dict) -> dict:
    """The languages in the game's own order, whichever of them were fetched this time."""
    place = {code: index for index, code in enumerate(LANGUAGES)}
    return {code: by_language[code] for code in sorted(by_language, key=lambda c: place.get(c, len(place)))}


def wanted_languages(log_dir: str, setting: str = "", asked: str = "") -> list[str]:
    """The languages whose text to fetch. ``asked`` is the command line's word: "all", or codes
    with commas between. Without it: English, the game client's own and the settings' choice."""
    if asked.strip().lower() == "all":
        chosen = list(LANGUAGES)
    elif asked.strip():
        chosen = [code.strip() for code in asked.split(",")]
    else:
        chosen = [client_language(log_dir), setting]
    picked = [pick_language(LANGUAGES, code) for code in chosen if code and code.strip()]
    return list(dict.fromkeys(["en", *(code for code in picked if code)]))


def _stamp(readme: str) -> dict[str, str]:
    return {key: value.strip() for key, value in re.findall(r"> ([\w ]+): ([^<\n]+)", readme)}


def _previous(path: str) -> dict:
    try:
        data = load(path)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def run(
    log_dir: str, *, branch: str = "", languages: str = "", setting: str = "",
    out: str = ENEMY_HP_PATH, cache: str = "", keep: bool = False, force: bool = False,
    say: Say = print,
) -> str:
    """Fetch the tables for the installed game (or ``branch``) and rebuild ``out``. Returns one
    line saying what was done; raises ``Failed`` with one saying why not, having changed
    nothing. ``keep`` leaves the downloads in the cache folder; ``force`` rebuilds even when the
    file is already built from what the repository holds."""
    version = installed_version(log_dir)
    branch = branch or branch_of(version)
    if not branch:
        raise Failed(
            "Can't tell which game version is installed. Check the log folder in the meter's "
            "Settings, or name the version: Waveband.exe update --branch 3.8"
        )
    own_cache = not cache
    cache = cache or os.path.join(tempfile.gettempdir(), "wwmeter-gamedata", branch)
    say(f"Looking for the tables of game {branch}")
    try:
        with _get(branch, "README.md") as response:
            readme = response.read(1 << 16).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise Failed(
                f"The tables for game {branch} are not published yet. Nothing was changed; try "
                "again in a day or two."
            ) from exc
        raise Failed(f"GitHub answered {exc.code}. Nothing was changed; try again later.") from exc
    except OSError as exc:
        raise Failed(
            f"Couldn't reach GitHub ({getattr(exc, 'reason', None) or exc}). Nothing was changed."
        ) from exc
    stamp = _stamp(readme)
    game_version = stamp.get("Game Version") or branch
    resource_version = stamp.get("Resource Version", "")

    previous = _previous(out)
    wanted = wanted_languages(log_dir, setting, languages)
    had = previous.get("text") if isinstance(previous.get("text"), dict) else {}
    if (
        not force and previous.get("game_version") == game_version
        and previous.get("resource_version") == resource_version
        and all(code in had for code in wanted)
    ):
        return f"Boss HP tables are already up to date (game {game_version})."

    os.makedirs(cache, exist_ok=True)
    # Downloads left from an earlier state of the branch are not this one's.
    kept_readme = os.path.join(cache, "README.md")
    try:
        with open(kept_readme, encoding="utf-8") as fh:
            stale = _stamp(fh.read()) != stamp
    except OSError:
        stale = True
    if stale:
        for name in os.listdir(cache):
            if _OURS.match(name):
                _discard(os.path.join(cache, name))
    with open(kept_readme, "w", encoding="utf-8") as fh:
        fh.write(readme)

    for name, path in TABLES.items():
        if not fetch(branch, path, os.path.join(cache, name), say):
            raise Failed(f"The repository has no {path} for game {branch}. Nothing was changed.")
    n = 1
    while fetch(branch, LEVEL_ENTITIES.format(n=n), os.path.join(cache, f"levelentityconfig_{n}.json"), say):
        n += 1
    if n == 1:
        raise Failed(f"The repository has no level-entity table for game {branch}. Nothing was changed.")
    fetched = []
    for language in wanted:
        if fetch(branch, TEXT.format(language=language), os.path.join(cache, f"multitext_{language}.json"), say):
            fetched.append(language)
        elif language == "en":
            raise Failed(f"The repository has no English text table for game {branch}. Nothing was changed.")
        else:
            print(f"  no text table for '{language}' in the repository: left out")
    # optional: without the first a few enemy types go unnamed, the meter knows the second as
    # it was in 3.8, and without the third a new character has no element colour
    for path, name in ((BESTIARY, "monsterinfo.json"), (LANGUAGE_IDS, "languagedefine.json"), (ROLES, "roleinfo.json")):
        fetch(branch, path, os.path.join(cache, name), say)

    say("Reading the tables")
    data = build(cache, say)
    if not (data["blueprints"] and data["level"] and data["life"] and data["curves"]):
        raise Failed("The downloaded tables hold no enemies. Nothing was changed.")
    if len(data["blueprints"]) < _SHRUNK * len(previous.get("blueprint_names") or ()):
        raise Failed(
            f"The downloaded tables hold {len(data['blueprints'])} enemy types where the old ones "
            f"had {len(previous['blueprint_names'])}. Nothing was changed."
        )
    data["language_ids"] = {
        str(row["LanguageType"]): row["LanguageCode"]
        for row in optional(os.path.join(cache, "languagedefine.json"))
        if isinstance(row.get("LanguageType"), int) and row.get("LanguageCode")
    }
    data["elements"] = elements(cache)
    text, characters = texts(cache, data["text_keys"], fetched, say)
    old_text, old_characters = carried(previous, data["text_keys"], text)
    data["text"] = _in_order({**old_text, **text})
    data["characters"] = _in_order({**old_characters, **characters})
    data = {
        "game_version": game_version,
        "resource_version": resource_version,
        "source": f"https://github.com/{REPO}/tree/{branch}",
        "built": time.strftime("%Y-%m-%d"),
        **data,
    }
    try:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out + ".part", "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(out + ".part", out)
    except OSError as exc:
        _discard(out + ".part")
        raise Failed(f"Couldn't write {out}: {exc}") from exc
    if own_cache and not keep:
        for name in os.listdir(cache):
            if _OURS.match(name):
                _discard(os.path.join(cache, name))
        for folder in (cache, os.path.dirname(cache)):
            try:
                os.rmdir(folder)  # only when nothing else is in it
            except OSError:
                break
    placed_count = sum(len(members) for members in data["level"].values())
    prefab_count = sum(len(members) for members in data["prefab"].values())
    print(
        f"Wrote {out} ({os.path.getsize(out) / 1e6:.2f} MB): game {game_version}, "
        f"{len(data['blueprint_names'])} enemy types, {placed_count} placed in levels, "
        f"{prefab_count} in prefabs, {len(data['life'])} HP rows, {len(data['curves'])} growth curves, "
        f"{len(data['text_keys'])} names in {len(data['text'])} languages ({', '.join(data['text'])}; "
        f"fetched now: {', '.join(text)}), {len(data['characters'].get('en', {}))} playable "
        f"characters' names, {len(data['elements'])} with an element."
    )
    note = ""
    if version and branch_of(version) != branch:
        note = f" The installed game is {version}."
    return f"Boss HP tables are now for game {game_version}.{note}"


def main(cfg, args) -> int:
    """The ``update`` command. What is said goes to the console (or waveband.log) and, for a
    meter that started this, into the file it reads the progress from."""

    def say(text: str) -> None:
        if not (args.status_file and text.startswith("Downloading ")):
            print(text, flush=True)  # a meter's log gets each file once, not every second of it
        if args.status_file:
            try:
                with open(args.status_file + ".part", "w", encoding="utf-8") as fh:
                    fh.write(text)
                os.replace(args.status_file + ".part", args.status_file)
            except OSError:
                pass  # the meter is reading it this instant; the next line will get through

    try:
        done = run(
            cfg.log_dir, branch=args.branch or "", languages=args.languages or "",
            setting=str(cfg.language or ""), out=args.out or ENEMY_HP_PATH, cache=args.cache or "",
            keep=args.keep_downloads, force=args.force, say=say,
        )
    except Failed as why:
        say(str(why))
        return 1
    except Exception as exc:  # noqa: BLE001 - a table laid out differently than expected
        say(f"The tables could not be read ({type(exc).__name__}: {exc}). Nothing was changed.")
        return 1
    say(done)
    return 0


class Updater:
    """Runs ``wwmeter update`` beside a running meter and follows what it says."""

    def __init__(self, on_done: Callable[[bool, str], None]) -> None:
        self._on_done = on_done
        self._lock = threading.Lock()
        self._running = False
        self._line = ""

    @property
    def running(self) -> bool:
        return self._running

    @property
    def line(self) -> str:
        """What the update is doing at this moment; '' when none is running."""
        return self._line if self._running else ""

    def start(self) -> bool:
        """Start an update. False when one is already running."""
        with self._lock:
            if self._running:
                return False
            self._running, self._line = True, "Updating boss HP tables"
        threading.Thread(target=self._work, name="update", daemon=True).start()
        return True

    @staticmethod
    def _command(status: str) -> list[str]:
        program = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "wwmeter"]
        return [*program, "update", "--status-file", status]

    def _work(self) -> None:
        status = os.path.join(tempfile.gettempdir(), f"wwmeter-update-{os.getpid()}.txt")
        _discard(status)
        ok, last = False, ""
        try:
            # what the update prints goes where the meter's own output goes, for a tester to send
            log = open(LOG_PATH, "a", encoding="utf-8")
        except OSError:
            log = subprocess.DEVNULL
        try:
            child = subprocess.Popen(
                self._command(status), cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            while True:
                try:
                    code = child.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    code = None
                last = self._read(status) or last
                if last:
                    self._line = last
                if code is not None:
                    break
            ok = code == 0
            if not last:
                last = "Boss HP tables updated." if ok else "The update stopped without saying why. See waveband.log."
        except OSError as exc:
            last = f"Couldn't start the update: {exc}"
        finally:
            if log is not subprocess.DEVNULL:
                log.close()
            _discard(status)
            self._running = False
        self._on_done(ok, last)

    @staticmethod
    def _read(path: str) -> str:
        try:
            with open(path, encoding="utf-8") as fh:
                return fh.read(500).strip()
        except OSError:
            return ""
