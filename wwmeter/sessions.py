"""One file of finished fights per launch of the meter, in ``sessions\\`` beside config.json.

A session is everything fought between starting the meter and closing it. The meter starts
each launch with an empty list and writes that launch's fights to a file of its own, so the list
never grows from one day into the next. An earlier session is read back only when asked for.
"""

from __future__ import annotations

import json
import os
import re
import time

from .config import HISTORY_PATH

SESSIONS_DIR = os.path.join(os.path.dirname(HISTORY_PATH), "sessions")
# 2026-11-15_16-30-05.json: the moment the meter was started, local time
_NAME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})\.json$")
_FIGHT_KEYS = ("id", "title", "duration", "damage", "dps", "unit", "players")


def new_path(started: float, folder: str = SESSIONS_DIR) -> str:
    """Where a session started at ``started`` keeps its fights. Nothing is created until the
    first fight ends, so a launch without a fight leaves no file."""
    return os.path.join(folder, time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(started)) + ".json")


def _started(name: str) -> float | None:
    match = _NAME.match(name)
    if match is None:
        return None
    try:
        return time.mktime(time.strptime(name[:-5], "%Y-%m-%d_%H-%M-%S"))
    except (ValueError, OverflowError):
        return None


def read(name: str, folder: str = SESSIONS_DIR) -> list[dict]:
    """The fights of one session, newest first. ``name`` is a file name as ``listing`` gives
    it; anything else (a path, a name of another shape) reads as no fights."""
    if _NAME.match(name) is None:
        return []
    try:
        with open(os.path.join(folder, name), encoding="utf-8") as fh:
            fights = json.load(fh).get("fights", [])
    except (OSError, ValueError, AttributeError):
        return []
    kept = [f for f in fights if isinstance(f, dict) and all(key in f for key in _FIGHT_KEYS)]
    for fight in kept:
        fight["live"] = False
    return kept


def label(name: str) -> str:
    """'15 Nov 16:30' for a session's file name."""
    started = _started(name)
    if started is None:
        return name
    moment = time.localtime(started)
    return f"{moment.tm_mday} {time.strftime('%b %H:%M', moment)}"


def listing(limit: int = 30, skip: str = "", folder: str = SESSIONS_DIR) -> list[dict]:
    """The latest sessions that hold a fight, newest first: file name, a label, how many fights
    and what the last one was. ``skip`` leaves out the running session's own file."""
    try:
        names = sorted((n for n in os.listdir(folder) if _started(n) is not None), reverse=True)
    except OSError:
        return []
    found = []
    for name in names:
        if name == os.path.basename(skip):
            continue
        fights = read(name, folder)
        if not fights:
            continue
        found.append({
            "file": name, "label": label(name), "fights": len(fights), "last": fights[0]["title"],
        })
        if len(found) >= limit:
            break
    return found


def adopt_old_list(path: str = HISTORY_PATH, folder: str = SESSIONS_DIR) -> str:
    """Turn the single list an earlier version kept (history.json) into a session of its own,
    dated by its first fight, and remove the old file. Returns the new file's name, or ''."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        fights = [f for f in data.get("fights", []) if isinstance(f, dict)]
    except (OSError, ValueError, AttributeError):
        return ""
    if not fights:
        return ""
    began = [f["ended_at"] - f.get("duration", 0) for f in fights if f.get("ended_at")]
    target = new_path(min(began) if began else os.path.getmtime(path), folder)
    try:
        os.makedirs(folder, exist_ok=True)
        if os.path.exists(target):
            return ""  # already adopted once; leave both files alone
        with open(target, "w", encoding="utf-8") as fh:
            json.dump({"v": 1, "fights": fights}, fh, ensure_ascii=False)
        os.remove(path)
    except OSError:
        return ""
    return os.path.basename(target)
