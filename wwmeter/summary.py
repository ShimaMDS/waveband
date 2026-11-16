"""A fight as a few lines of plain text, for pasting into a chat."""

from __future__ import annotations

_SOURCES = {
    "log": "enemy HP in the game log (exact)",
    "numbers": "damage numbers read off the screen (rough: about half is read)",
    "bar": "the boss HP bar",
}


def _clock(seconds: float) -> str:
    whole = max(0, int(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


def _amount(value: float, unit: str) -> str:
    if unit == "percent":
        return f"{value:.1f}%" if value >= 10 else f"{value:.2f}%"
    return f"{round(value):,}"


def fight_summary(fight: dict, version: str = "") -> str:
    """``fight`` is an encounter as the tracker describes it (the "encounter" of a snapshot)."""
    unit = fight.get("unit", "damage")
    percent = unit == "percent"
    total, rate = _amount(fight["damage"], unit), _amount(fight["dps"], unit)
    title = fight.get("title") or "Fight"
    if fight.get("live"):
        title += " (still running)"
    if percent:
        head = f"{title} | {_clock(fight['duration'])} | {total} of its HP | {rate} of HP/s"
    else:
        head = f"{title} | {_clock(fight['duration'])} | {total} damage | {rate} DPS"
        full = fight.get("max_hp_total") or 0
        if full:
            head += f" | {fight['damage'] / full:.0%} of {full:,} HP"
    lines = [head]
    players = fight.get("players", [])
    width = max((len(p["name"]) for p in players), default=0)
    for player in players:
        each = _amount(player["damage"], unit)
        per_second = _amount(player["dps"], unit)
        lines.append(
            f"{player['name']:<{width}}  {each} ({player['share']:.1%})  "
            + (f"{per_second} of HP/s" if percent else f"{per_second} DPS")
        )
    source = _SOURCES.get(fight.get("source", ""), "")
    if fight.get("source") == "bar":
        source += {
            "tables": " and the boss's HP from the game's data",
            "parts": " and the boss's HP worked out from one of its parts",
        }.get(fight.get("hp_from", ""), "; its HP isn't known, so this is percent of HP")
    notes = [f"Measured from {source}."] if source else []
    if len(players) > 1:
        notes.append("Split by who was on field.")
    lines.append(" ".join(notes + ([f"Waveband {version}"] if version else [])))
    return "\n".join(line for line in lines if line)
