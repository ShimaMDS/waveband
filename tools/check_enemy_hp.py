"""Check data\\enemy_hp.json against the game's own log.

Some enemies log their full HP (the first ``LifeValue`` of a ``怪物.common.`` weak point). For each
of those found in the local logs, this prints the HP the tables give next to the HP the game
logged; they should be equal. Bosses whose logged parts are separate pools are listed with the HP
the tables give and each pool as a share of it, which comes out as a round percentage when the
HP is right.

Run it after rebuilding the file for a new patch:

    .venv\\Scripts\\python tools\\check_enemy_hp.py
"""

from __future__ import annotations

import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wwmeter import config  # noqa: E402
from wwmeter.gamedata import Spawns  # noqa: E402
from wwmeter.logparse import parse_line  # noqa: E402
from wwmeter.logtail import read_file  # noqa: E402

_WANTED = ("JoinSceneNotify", "实体详细数据", "UpdatePartInfo")
_BOSS = re.compile(r"^BP_M[BL]\d")
_HP_TAG = "怪物.common."


def main() -> int:
    cfg = config.load()
    files = sorted(glob.glob(os.path.join(cfg.log_dir, "Client*.log")), key=os.path.getmtime)
    spawns = Spawns()
    data = spawns.data
    if not data:
        print("data\\enemy_hp.json is missing or empty. Run tools\\build_enemy_hp.py first.")
        return 1
    print(f"Tables for game {data.version}; {len(files)} log files in {cfg.log_dir}")

    # One entry per spawned enemy: its spawn line and the first value of each part it logged.
    spawned: dict[int, tuple] = {}  # creature ID -> spawn, as of the latest spawn line
    firsts: dict[tuple, dict[str, float]] = {}  # (actor, spawn, serial) -> tag -> first value
    serial: dict[int, int] = {}
    for path in files:
        for line in read_file(path):
            if not any(word in line for word in _WANTED):
                continue
            event = parse_line(line)
            if event is None:
                continue
            if event.module == "World":
                spawns.on_event(event)
            elif event.module == "Entity":
                if event.fields.get("EntityType") != "Monster" or "ConfigType" not in event.fields:
                    continue
                creature = int(event.fields["CreatureDataId"])
                spawned[creature] = (
                    event.fields["ConfigType"], int(event.fields["PbDataId"]),
                    int(event.fields.get("PrefabId") or 0), spawns.instance,
                )
                serial[creature] = serial.get(creature, 0) + 1
            elif event.kind == "Monster" and event.sub == "Part" and "LifeValue" in event.fields:
                spawn = spawned.get(event.entity_id)
                if spawn is None:
                    continue  # spawned before the oldest log kept
                key = (event.actor, spawn, (event.entity_id, serial[event.entity_id]))
                tag = event.fields.get("TagName", "")
                firsts.setdefault(key, {}).setdefault(tag, float(event.fields["LifeValue"]))

    whole: dict[tuple, int] = {}  # (actor, spawn, level, table HP, logged HP) -> times seen
    pools: dict[tuple, dict[str, float]] = {}  # (actor, spawn) -> tag -> first value
    for (actor, spawn, _), tags in firsts.items():
        enemy = data.find(*spawn)
        common = {value for tag, value in tags.items() if tag.startswith(_HP_TAG)}
        if len(common) == 1:  # weak points that share one value report the enemy's whole HP
            key = (actor, spawn, enemy.level if enemy else None, data.hp(enemy), round(common.pop()))
            whole[key] = whole.get(key, 0) + 1
        elif _BOSS.match(actor):
            pools.setdefault((actor, spawn), {}).update(tags)

    print("\nEnemies that logged their full HP:")
    good = bad = unknown = 0
    for (actor, spawn, level, table_hp, logged_hp), times in whole.items():
        if table_hp is None:
            verdict, unknown = "no table HP (level or placement unknown)", unknown + 1
        elif table_hp == logged_hp:
            verdict, good = "match", good + 1
        else:
            verdict, bad = "DIFFERS", bad + 1
        shown = f"{table_hp:,}" if table_hp is not None else "?"
        where = f"{spawn[0]} {spawn[1]}" + (f" in prefab {spawn[2]}" if spawn[2] else "")
        enemy = data.find(*spawn)
        name = f'  "{enemy.name}"' if enemy is not None and enemy.name else "  no name in the tables"
        print(f"  {actor:<32} Lv {level or '?':<4} tables {shown:>12}  log {logged_hp:>12,}  "
              f"{verdict}  x{times}  {where}{name}")
    print(f"  {good} match, {bad} differ, {unknown} without a table value")

    print("\nBosses that log part pools only, each pool as a share of the table HP:")
    for (actor, spawn), tags in pools.items():
        enemy = data.find(*spawn)
        hp = data.hp(enemy)
        if hp is None:
            print(f"  {actor:<32} no table HP  {spawn}")
            continue
        shares = ", ".join(f"{tag.rsplit('.', 1)[-1]} {value / hp:.2%}" for tag, value in tags.items())
        print(f"  {actor:<32} Lv {enemy.level:<4} tables {hp:>12,}  {shares}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
