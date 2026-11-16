"""Run a recording back through the same code the live meter uses, as fast as it will go."""

from __future__ import annotations

import csv
import os

from .config import Config
from .engine import ScreenReader
from .gamedata import PartShares, enemy_data
from .logparse import parse_line
from .roster import Roster
from .tracker import Tracker


def read_frame(path: str):
    """A recorded frame as a BGR array, the way the capture hands frames over; None if unreadable."""
    import numpy as np
    from PIL import Image

    try:
        with Image.open(path) as image:
            return np.ascontiguousarray(np.asarray(image.convert("RGB"))[..., ::-1])
    except (OSError, ValueError):
        return None


def _events(folder: str, use_frames: bool, frame_step: int):
    """(time, kind, payload) for every log line and frame, in time order."""
    items: list[tuple[float, int, str, str]] = []
    with open(os.path.join(folder, "log.txt"), encoding="utf-8") as fh:
        for line in fh:
            stamp, _, text = line.rstrip("\n").partition("\t")
            try:
                items.append((float(stamp), 0, "log", text))
            except ValueError:
                continue  # continuation of a multi-line message
    if use_frames:
        with open(os.path.join(folder, "frames.csv"), encoding="utf-8") as fh:
            for index, row in enumerate(csv.DictReader(fh)):
                if row["focused"] == "1" and index % frame_step == 0:
                    items.append((float(row["epoch"]), 1, "frame", row["file"]))
    items.sort()
    for stamp, _, kind, payload in items:
        yield stamp, kind, payload


def replay(
    cfg: Config, folder: str, use_frames: bool = True, frame_step: int = 1, use_life: bool = True
) -> list[dict]:
    """Returns one description per fight found in the recording, oldest first."""
    tables = enemy_data(cfg)
    tracker = Tracker(
        Roster(game_name=tables.character_name, game_element=tables.element), timeout=cfg.encounter_timeout, use_life=use_life,
        enemies=tables, parts=PartShares(),  # learns within the replay, keeps nothing
    )
    reader = ScreenReader(cfg, tracker)
    fights: dict[int, dict] = {}
    now = 0.0
    for now, kind, payload in _events(folder, use_frames, frame_step):
        if kind == "log":
            event = parse_line(payload)
            if event is not None:
                tracker.on_log(event, now)
        else:
            frame = read_frame(os.path.join(folder, "frames", payload))
            if frame is not None:
                reader.process(frame, now)
        tracker.tick(now)
        encounter = tracker.snapshot(now)["encounter"]
        if encounter is not None:
            fights[encounter["id"]] = encounter
    tracker.tick(now + 3600.0)  # close whatever was still running
    encounter = tracker.snapshot(now)["encounter"]
    if encounter is not None:
        fights[encounter["id"]] = encounter
    kept = {item["id"] for item in tracker.snapshot(now)["history"]}
    return [fights[key] for key in sorted(fights) if key in kept]


def print_report(fights: list[dict]) -> None:
    if not fights:
        print("no fights found")
        return
    for fight in fights:
        unit = "% of HP" if fight["unit"] == "percent" else "damage"
        if fight["source"] == "bar" and fight["unit"] == "damage":
            unit += (
                " (HP bar x HP worked out from one of the boss's parts)"
                if fight.get("hp_from") == "parts" else " (HP bar x HP from the game's tables)"
            )
        biggest = f", biggest {fight['max_hit']:,}" if fight["max_hit"] else ""
        print(
            f"#{fight['id']} {fight['title']}: {fight['duration']:.1f}s, "
            f"{fight['damage']:,} {unit}, {fight['dps']:,}/s, source={fight['source']}, "
            f"{fight['hits']} updates{biggest}"
        )
        for player in fight["players"]:
            skills = ", ".join(f"{s['name']}×{s['casts']}" for s in player["skills"][:4])
            on_field = player.get("field_time")
            field = "" if on_field is None else f"  on field {on_field:6.1f}s"
            print(
                f"    {player['name']:<14} {player['damage']:>12,}  {player['share']:6.1%}  "
                f"{player['dps']:>9,}/s{field}  {skills}"
            )
        # the times on field are counted over the same stretch as the fight's length
        on_field = sum(player.get("field_time") or 0.0 for player in fight["players"])
        print(f"    on field in all {on_field:.1f}s of the fight's {fight['duration']:.1f}s")
        boss = fight["boss"]
        if boss:
            hp = "?" if boss["hp"] is None else f"{boss['hp']:.1%}"
            print(f"    target HP {hp}, HP left {boss['life']:,} of {boss['max_hp']:,}")
