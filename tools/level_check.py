"""List the placements whose level needs a second look, from ``data\\enemy_hp.json``.

    python tools/level_check.py [--data <enemy_hp.json>]

Run it after rebuilding the tables for a new game version. It prints three lists:

1. Placements whose bar shows one level while HP uses another. In 3.8 that is Crownless:
   Newborn Desires in the hologram and nothing else. The meter uses the placement's level,
   which is right; a new name here is a boss to fight once and compare with the table.
2. Placements whose bar shows something that is not a number ("?", "???").
3. The odd one out: a placement that fixes no level where the same enemy is placed on that
   map at three or more levels (a boss with a row of difficulties), and no instance fixes
   it either. For these the meter has only the level it reads off the screen. In 3.8: the
   difficulty VI hologram of Sigillum, Denia and Myriad Snare, whose level (100) is on the
   enemy's template instead.
"""

from __future__ import annotations

import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wwmeter.gamedata import ENEMY_HP_PATH, EnemyData  # noqa: E402


def check(data: EnemyData) -> tuple[list[tuple], list[tuple], list[tuple]]:
    """(shown differently, shown as no number, no level of its own), each a list of rows."""
    differs, unreadable, unfixed = [], [], []
    by_type: dict[tuple[str, str], list[tuple]] = collections.defaultdict(list)
    for map_id, entity, enemy, fixed in data.placements():
        by_type[map_id, enemy.blueprint].append((entity, enemy, fixed))
        if enemy.shown_level is not None and enemy.level is not None and enemy.shown_level != enemy.level:
            differs.append((int(map_id), entity, enemy.name or enemy.blueprint, enemy.shown_level,
                            enemy.level, data.hp(enemy)))
        elif enemy.shown_text and enemy.shown_level is None:
            unreadable.append((int(map_id), entity, enemy.name or enemy.blueprint, enemy.shown_text))
    for (map_id, _), placed in by_type.items():
        levels = sorted({enemy.level for _, enemy, _ in placed if enemy.level})
        without = [(entity, enemy) for entity, enemy, fixed in placed if enemy.level is None and not fixed]
        if len(levels) < 3 or len(without) >= len(placed) - len(without):
            continue
        for entity, enemy in without:
            unfixed.append((int(map_id), entity, enemy.name or enemy.blueprint, levels))
    return sorted(differs), sorted(unreadable), sorted(unfixed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data", default=ENEMY_HP_PATH, help="the built tables (default: data\\enemy_hp.json)")
    args = parser.parse_args(argv)
    data = EnemyData(args.data)
    if not data:
        print(f"No tables in {args.data}. Run tools\\build_enemy_hp.py first.")
        return 1
    differs, unreadable, unfixed = check(data)
    print(f"Game version {data.version}.")
    print(f"\n1. The bar shows one level, HP uses another ({len(differs)}):")
    for map_id, entity, name, shown, level, hp in differs:
        print(f"   map {map_id:>5}  {entity:>10}  {name:<34} shows {shown:>3}, HP at {level:>3}"
              + (f" = {hp:,}" if hp else ""))
    print(f"\n2. The bar shows no number ({len(unreadable)}):")
    for map_id, entity, name, text in unreadable:
        print(f"   map {map_id:>5}  {entity:>10}  {name:<34} shows {text!r}")
    print(f"\n3. No level of its own, on a map that has the same enemy at several ({len(unfixed)}):")
    for map_id, entity, name, levels in unfixed:
        print(f"   map {map_id:>5}  {entity:>10}  {name:<34} the others: {', '.join(map(str, levels))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
