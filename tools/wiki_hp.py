"""Base HP by level for an enemy, from the Fandom wiki's "Level Scaling" table.

    python tools/wiki_hp.py "Crownless" [level ...]

These are base values. A real fight multiplies them by a factor that depends on the mode and
difficulty, and that factor is not on the wiki. Measured from HP the game logged on 2026-11-15:

    Crownless Lv 90, boss challenge:        1,024,088 logged / 181,198 base = x5.65
    Crownless Lv 100, Tower of Adversity:   5,510,473 logged / 251,470 base = x21.9

So this table alone cannot turn a bar-only boss's percent into damage.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request

_API = "https://wutheringwaves.fandom.com/api.php?"
_AGENT = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}


def level_table(page: str) -> dict[int, int]:
    """{level: base HP} for a wiki page title; empty if the page has no table."""
    query = urllib.parse.urlencode(
        {"action": "parse", "page": page, "prop": "text", "format": "json", "redirects": 1}
    )
    request = urllib.request.Request(_API + query, headers=_AGENT)
    reply = json.loads(urllib.request.urlopen(request, timeout=30).read())
    html = reply.get("parse", {}).get("text", {}).get("*", "")
    start = html.find("Level Scaling")
    if start < 0:
        return {}
    table: dict[int, int] = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html[start:], re.S):
        cells = [
            re.sub(r"<[^>]+>", "", cell).strip().replace(",", "")
            for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
        ]
        if len(cells) >= 2 and cells[0].isdigit() and cells[1].isdigit():
            table[int(cells[0])] = int(cells[1])
    return table


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    table = level_table(sys.argv[1])
    if not table:
        raise SystemExit(f"no Level Scaling table found for {sys.argv[1]!r}")
    levels = [int(a) for a in sys.argv[2:]] or [70, 80, 90, 100, 110, 120]
    print(f"{sys.argv[1]}: levels {min(table)}..{max(table)}")
    for level in levels:
        print(f"  Lv {level}: {table.get(level, 0):,}")


if __name__ == "__main__":
    main()
