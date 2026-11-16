"""What changed in each version (CHANGELOG.md), and which part of it is news on this PC.

The meter keeps the version it last ran as in the settings (``seen_version``). When a start
finds an older one there, the versions in between are news: said in a line on the meter and
marked on the dashboard, for that run only.
"""

from __future__ import annotations

import os
import re

from .config import ROOT

PATH = os.path.join(ROOT, "CHANGELOG.md")
# The one version that went out before the meter kept track of what it last ran as. A settings
# file that names no version was written by it.
FIRST_OUT = "0.1.0"

_HEADING = re.compile(r"^##\s+(\d+(?:\.\d+)*)\s*(?:\((.*)\))?\s*$")
_NUMBERS = re.compile(r"\d+(?:\.\d+)*")


def parse(text: str) -> list[dict]:
    """The versions of a changelog, in the order written: ``{"version", "when", "notes"}``.

    A version starts at a ``## 0.2.0 (when)`` heading. Its notes are the ``- `` items under it,
    each with its indented continuation lines joined on; anything else is passed over.
    """
    versions: list[dict] = []
    note: list[str] | None = None  # the lines of the item being read

    def close() -> None:
        nonlocal note
        if note and versions:
            versions[-1]["notes"].append(" ".join(note))
        note = None

    for line in text.splitlines():
        heading = _HEADING.match(line)
        if heading:
            close()
            versions.append({"version": heading.group(1), "when": heading.group(2) or "", "notes": []})
        elif line.startswith("- "):
            close()
            note = [line[2:].strip()]
        elif note is not None and line[:1] in (" ", "\t") and line.strip():
            note.append(line.strip())
        else:
            close()
    close()
    return versions


def read(path: str = PATH) -> list[dict]:
    """The changelog beside the program. Empty when the file is not there."""
    try:
        with open(path, encoding="utf-8") as fh:
            return parse(fh.read())
    except (OSError, ValueError):
        return []


def key(version) -> tuple[int, ...]:
    """A version as numbers to compare. Only the numbers at the front count, so a build on the
    way to 0.2.0 (``0.2.0.dev0``) is 0.2.0 here: it already has that version's notes."""
    found = _NUMBERS.match(version) if isinstance(version, str) else None
    parts = [int(n) for n in found.group().split(".")] if found else []
    while parts and parts[-1] == 0:  # 0.2 and 0.2.0 are the same version
        parts.pop()
    return tuple(parts)


def last_run(seen, had_settings: bool) -> str | None:
    """The version that ran here before this start. None when nothing says one did: a first
    start, or a meter that never had a setting changed and so never wrote a settings file."""
    if isinstance(seen, str) and key(seen):
        return seen
    return FIRST_OUT if had_settings else None


def news(versions: list[dict], before: str | None, current: str) -> list[dict]:
    """The versions that came after ``before``, up to the one running."""
    if before is None:
        return []
    return [v for v in versions if key(before) < key(v["version"]) <= key(current)]
