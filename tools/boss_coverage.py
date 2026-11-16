"""Count how many boss placements the game's tables give an HP for, by mode.

A placement with an "extra rate" gets no HP (the rate table is not in the client's data), so the
meter shows that boss in percent. This counts them, from the raw tables that
``build_enemy_hp.py`` leaves in its cache folder:

    python tools/boss_coverage.py [--cache <folder>] [--list "open world"]

Bosses are picked out by the game's own internal names (BOSS, 领主 "lord"), and the mode by
keywords in the placement's name (道馆 hologram, 爬塔 tower, 复刷 respawning, 任务 quest), so
the figures are approximate. ``--list`` prints the placements of one mode that get no HP.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.build_enemy_hp import components, installed_version  # noqa: E402

_BOSS = re.compile(r"BOSS|Boss|boss|领主")
_MODES = (
    ("Tactical Hologram", "道馆"),
    ("Tower of Adversity", "爬塔"),
    ("events, boss rush, roguelike", "BossRush|肉鸽|活动|挑战|深塔|[Rr]ogue"),
    ("quest and story", "任务|主线|支线|剧情|教学"),
    ("open world (respawning)", "复刷"),
)


def mode_of(name: str) -> str:
    for label, pattern in _MODES:
        if re.search(pattern, name):
            return label
    return "no mode in the name"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cache", help="folder with the downloaded tables (default: build_enemy_hp's)")
    parser.add_argument("--list", metavar="MODE", help="print the placements of this mode that get no HP")
    args = parser.parse_args(argv)
    version = installed_version()
    branch = ".".join(version.split(".")[:2]) if version else ""
    cache = args.cache or os.path.join(tempfile.gettempdir(), "wwmeter-gamedata", branch)
    if not os.path.isfile(os.path.join(cache, "templateconfig.json")):
        print(f"No tables in {cache}. Run tools\\build_enemy_hp.py first (it downloads them).")
        return 1

    def load(name: str):
        with open(os.path.join(cache, name), encoding="utf-8") as fh:
            return json.load(fh)

    templates: dict[str, tuple[str, dict]] = {}
    for entry in load("templateconfig.json"):
        parts = components(entry)
        kind = ((parts.get("BaseInfoComponent") or {}).get("Category") or {}).get("MainType")
        if kind == "Monster" or (kind is None and "MonsterComponent" in parts):
            templates[entry["BlueprintType"]] = (entry["Name"], parts.get("AttributeComponent") or {})

    counts: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    without: dict[str, set[str]] = collections.defaultdict(set)

    def add(name: str, blueprint: str, entry: dict) -> None:
        if blueprint not in templates:
            return
        if not (_BOSS.search(name) or _BOSS.search(templates[blueprint][0])):
            return
        own = components(entry).get("AttributeComponent") or {}
        base = templates[blueprint][1]
        extra = own["MonsterPropExtraRateId"] if "MonsterPropExtraRateId" in own else base.get("MonsterPropExtraRateId")
        mode = mode_of(name)
        counts[mode]["no HP" if extra else "HP"] += 1
        if extra:
            without[mode].add(name)

    n = 1
    while os.path.isfile(os.path.join(cache, f"levelentityconfig_{n}.json")):
        for entry in load(f"levelentityconfig_{n}.json"):
            add(entry.get("Name") or "", entry.get("BlueprintType", ""), entry)
        n += 1
    for prefab in load("prefabconfig.json"):
        members = prefab.get("Entities") or []
        for member in json.loads(members) if isinstance(members, str) else members:
            data = member.get("EntityData") or {}
            add(data.get("Name") or "", data.get("BlueprintType", ""), data)

    total = collections.Counter()
    print(f"Boss placements in {cache}:")
    for mode, count in sorted(counts.items(), key=lambda item: -sum(item[1].values())):
        placed = sum(count.values())
        print(f"  {mode:<30} {placed:>5}   {count['HP'] / placed:5.0%} get an HP, {count['no HP']} do not")
        total.update(count)
    placed = sum(total.values())
    if placed:
        print(f"  {'all':<30} {placed:>5}   {total['HP'] / placed:5.0%} get an HP, {total['no HP']} do not")
    if args.list:
        for mode, names in without.items():
            if args.list.lower() in mode.lower():
                print(f"\n{mode}, no HP ({len(names)} distinct names):")
                for name in sorted(names):
                    print("  " + name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
