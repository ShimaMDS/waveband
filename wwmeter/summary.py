"""A fight as a few lines of text for pasting into a chat, written in Discord's markdown.

    ### Fallacy of No Return: Tethys System (Lv 70)
    **10,293 DPS** · 682,649 damage · 1:06 · 100% of its 682,649 HP
    1. **Hiyuki** · 9,080 DPS · 602,165 (88.2%)
    2. **Lynae** · 822 DPS · 54,522 (8.0%)
    -# Measured from the boss HP bar and the boss's HP from the game's data. Split by who ...

Discord shows the first line as a small heading, the second with the figure in bold, the
characters as a numbered list and the last line as small grey text. It has no tables, and its
letters are of different widths, so columns padded with spaces (as up to 0.3.0) came out ragged;
the "·" separated lines read the same in any font, on a phone too. Pasted somewhere without
markdown, the marks are few and the text still reads.
"""

from __future__ import annotations

import re

_SOURCES = {
    "log": "enemy HP in the game log (exact)",
    "numbers": "damage numbers read off the screen (rough: about half is read)",
    "bar": "the boss HP bar",
}
# Characters Discord's markdown would take as formatting inside a name: escaped with a backslash.
_MARKDOWN = re.compile(r"([\\*_~`|>#\[\]])")
_DOT = " · "


def _plain(text: str) -> str:
    return _MARKDOWN.sub(r"\\\1", text)


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
    title = _plain(fight.get("title") or "Fight")
    if fight.get("live"):
        title += " (still running)"
    clock = _clock(fight["duration"])
    if percent:
        head = [f"**{rate} of HP/s**", f"{total} of its HP", clock]
    else:
        head = [f"**{rate} DPS**", f"{total} damage", clock]
        full = fight.get("max_hp_total") or 0
        if full:
            head.append(f"{fight['damage'] / full:.0%} of its {full:,} HP")
    lines = [f"### {title}", _DOT.join(head)]
    # In percent of HP, a character's part of the HP and their share of the team's damage are
    # the same number when the fight took the whole bar: "93.5% (93.5%)". Said once then.
    whole_bar = percent and abs(fight["damage"] - 100.0) < 0.05
    for place, player in enumerate(fight.get("players", []), start=1):
        per_second = _amount(player["dps"], unit) + (" of HP/s" if percent else " DPS")
        each = _amount(player["damage"], unit)
        if not whole_bar:
            each += f" ({player['share']:.1%})"
        lines.append(f"{place}. **{_plain(player['name'])}**{_DOT}{per_second}{_DOT}{each}")
    source = _SOURCES.get(fight.get("source", ""), "")
    if fight.get("source") == "bar":
        source += {
            "tables": " and the boss's HP from the game's data",
            "parts": " and the boss's HP worked out from one of its parts",
        }.get(fight.get("hp_from", ""), "; its HP isn't known, so this is percent of HP")
    notes = [f"Measured from {source}."] if source else []
    if len(fight.get("players", [])) > 1:
        notes.append("Split by who was on field.")
    if version:
        notes.append(f"Waveband {version}")
    if notes:
        lines.append("-# " + " ".join(notes))
    return "\n".join(lines)
