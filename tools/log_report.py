"""What the game's log says about recent fights: the first thing to run when the meter and a fight
disagree, when someone says "I fought X, check the logs", or after a game patch.

    python tools/log_report.py [minutes]        (default 10)

Prints, for the last N minutes of the retained logs:
  - every enemy type seen, how many copies, hit events, and each weak-point tag with its values
  - for each enemy, the placement its spawn line named and the full HP the game's tables give
    for it, and each logged part as a share of that HP
  - the timeline of the game's combat flag, enemy deaths, character deaths and scene loads
  - which characters used skills, and the on-field switches

An enemy is measurable from the log when it has a `怪物.common.` tag whose value falls as it is
hit; its first value should equal the table HP. Tags named after the enemy are breakable parts
with their own pools, and come out as round shares of the table HP when that HP is right (Inferno
Rider 15% and 25%, Impermanence Heron 2%, Nameless Explorer 17%). No tags: bar or nothing.
"""

from __future__ import annotations

import collections
import glob
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wwmeter import config  # noqa: E402
from wwmeter.gamedata import Spawns  # noqa: E402
from wwmeter.logparse import parse_line  # noqa: E402
from wwmeter.logtail import read_file  # noqa: E402

_VARIANT = re.compile(r"Md?\d+$")
_INSTANCE = re.compile(r"_C_\d+$")


def _placement_text(spawns: Spawns, spawn: tuple | None) -> str:
    if spawn is None:
        return "spawn line not in the retained logs"
    config_type, pb_data, prefab, instance = spawn
    where = f"{config_type} {pb_data}" + (f" in prefab {prefab}" if prefab else "") + f", instance {instance}"
    enemy = spawns.data.find(*spawn)
    if enemy is None:
        return f"{where}: not in the tables"
    shown = f", bar shows Lv {enemy.shown_level}" if enemy.shown_level else ""
    where += f': "{enemy.name}"{shown}' if enemy.name else ": no name in the tables"
    hp = spawns.data.hp(enemy)
    if hp is not None:
        return f"{where}; Lv {enemy.level}, table HP {hp:,}"
    if not enemy.life_max:
        return f"{where}; no HP row in the tables"
    if not enemy.exact:
        return (
            f"{where}; has an extra rate, so the tables give no HP (percent, or damage from a"
            " part's pool when that part's share of the HP is known)"
        )
    return f"{where}; level not fixed (read off the screen); base {enemy.life_max:,}, curve {enemy.curve}"


def main() -> None:
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    cfg = config.load()
    now = time.time()
    files = sorted(glob.glob(os.path.join(cfg.log_dir, "*.log")), key=os.path.getmtime)
    files = [f for f in files if now - os.path.getmtime(f) < minutes * 60 + 1800]

    spawns = Spawns()
    copies: dict[str, set[int]] = collections.defaultdict(set)
    placements: dict[str, dict[tuple | None, int]] = collections.defaultdict(dict)
    hits: collections.Counter = collections.Counter()
    seen: dict[str, list[float]] = {}
    tags: dict[tuple[str, str], list[float]] = collections.defaultdict(list)
    timeline: list[tuple[float, str]] = []
    skills: collections.Counter = collections.Counter()

    for path in files:
        for line in read_file(path):
            event = parse_line(line)
            if event is None:
                continue
            if event.module in ("World", "Entity"):
                spawns.on_event(event)  # an enemy can spawn well before the stretch looked at
            if now - event.ts > minutes * 60:
                continue
            ago = now - event.ts
            if event.kind == "Monster" and event.actor.startswith("BP_M"):
                name = _VARIANT.sub("", event.actor)
                if event.entity_id not in copies[name]:
                    spawn = spawns.placement(event.entity_id)
                    placements[name][spawn] = placements[name].get(spawn, 0) + 1
                copies[name].add(event.entity_id)
                seen.setdefault(name, [ago, ago])[1] = ago
                if event.sub == "Hit":
                    hits[name] += 1
                if event.sub == "Part" and "LifeValue" in event.fields:
                    tags[(name, event.fields.get("TagName", "?"))].append(float(event.fields["LifeValue"]))
            elif event.kind == "Player" and event.sub == "Skill" and "BeginSkill" in event.text:
                skills[event.actor] += 1
            if event.module == "Battle" and event.text.startswith("NotifyInFight"):
                timeline.append((ago, "combat flag: " + event.text.split(":")[-1].strip()))
            elif event.module == "Battle" and "PerformPossess" in event.text:
                timeline.append((ago, "on field: " + _INSTANCE.sub("", event.fields.get("roleActor", "?"))))
            elif event.module == "Battle" and "DeathComponent]执行角色死亡" in event.text:
                timeline.append((ago, "death logic, PbDataId " + event.fields.get("PbDataId", "?")))
            elif event.module == "AI" and event.fields.get("reason") == "Dead":
                timeline.append((ago, "enemy dead: " + _INSTANCE.sub("", event.fields.get("Actor", "?"))))
            elif event.module == "World" and "JoinSceneNotify" in event.text:
                timeline.append((ago, "joined instance " + event.fields.get("InstanceId", "?")))
            elif event.module == "GameMode" and "加载场景:加载完成" in event.text:
                timeline.append((ago, "scene loaded"))

    tables = f"boss HP tables for game {spawns.data.version}" if spawns.data else "no boss HP tables (data\\enemy_hp.json)"
    print(f"last {minutes:g} minutes, {len(files)} log file(s), {tables}\n")
    print("enemies (type, copies, first..last seen s ago, hit events):")
    for name in sorted(seen, key=lambda n: -seen[n][0]):
        print(f"  {name:28s} x{len(copies[name]):<2d} {seen[name][0]:5.0f}..{seen[name][1]:5.0f}  hits={hits[name]}")
        table_hp = set()
        for spawn, count in placements[name].items():
            print(f"      placement x{count}: {_placement_text(spawns, spawn)}")
            table_hp.add(spawns.data.hp(spawns.data.find(*spawn)) if spawn else None)
        hp = table_hp.pop() if len(table_hp) == 1 else None  # only when every copy has the same HP
        for (owner, tag), values in tags.items():
            if owner == name:
                verdict = "HP" if tag.startswith("怪物.common.") else "part pool"
                share = f", first value is {values[0] / hp:.2%} of the table HP" if hp else ""
                print(f"      {tag:30s} {values[0]:>12,.0f} -> {values[-1]:>12,.0f}  updates={len(values)}  ({verdict}?{share})")
    print("\nskills begun:", dict(skills.most_common()))
    print("\ntimeline (s ago):")
    for ago, text in timeline:
        print(f"  {ago:7.1f}  {text}")


if __name__ == "__main__":
    main()
