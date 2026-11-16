"""Turn decoded log lines into structured events.

A script log line looks like::

    [2026.11.15-08.56.03:712][400][GameThread]Sharphereal: Display: [C#][33679][Info][CombatInfo][WCL][486698] [Skill][EntityId:13188:Monster:BP_ME1JiancuxiongMd00001_C_2147374192] BaseSkillComponent.BeginSkillAsync [技能Id: 1004][技能名: 狂暴·冲锋]

Everything after the entity tag is free text followed by ``[key: value]`` pairs. The parser keeps
both: the text names the event, the pairs carry its data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

_LINE = re.compile(
    r"^\[(?P<ts>\d{4}\.\d\d\.\d\d-\d\d\.\d\d\.\d\d:\d{3})\]\[\s*\d+\]\[[^\]]*\]"
    r"Sharphereal: \w+: \[C#\]\[\d+\]\[(?P<level>\w+)\]\[(?P<module>\w+)\]\[\w+\]\[(?P<tick>\d+)\] ?"
    r"(?P<body>.*)$"
)
_ENTITY = re.compile(
    r"^\[(?P<sub>\w+)\]\[EntityId:(?P<id>\d+):(?P<kind>\w+):(?P<actor>[^\]]+)\] ?(?P<rest>.*)$"
)
_SUB = re.compile(r"^\[(?P<sub>\w+)\] ?(?P<rest>.*)$")
_PAIR = re.compile(r"\[([^\[\]:]+): ?([^\[\]]*)\]")
_ACTOR_SUFFIX = re.compile(r"_C_\d+$")
_TS_FORMAT = "%Y.%m.%d-%H.%M.%S:%f"


@dataclass(slots=True)
class LogEvent:
    ts: float  # seconds since epoch, as written by the game (local wall clock)
    tick: int
    module: str  # CombatInfo, AI, Battle, ...
    sub: str  # Skill, Buff, Hit, Part, FightState, ... ('' when the line has none)
    entity_id: int  # 0 when the line is not about an entity
    kind: str  # Monster, Player, ...
    actor: str  # blueprint name without the instance suffix, e.g. BP_ME1BinlangMd00601
    text: str  # message with the [key: value] pairs removed
    fields: dict[str, str] = field(default_factory=dict)
    instance: str = ""  # the number after _C_ in the blueprint name: one spawned copy

    def num(self, key: str, default: float = 0.0) -> float:
        try:
            return float(self.fields[key])
        except (KeyError, ValueError):
            return default


def parse_timestamp(stamp: str) -> float:
    # "2026.11.15-08.56.03:712" -> the %f directive wants microseconds, so pad the millis
    return datetime.strptime(stamp + "000", _TS_FORMAT).timestamp()


def strip_instance(actor: str) -> str:
    return _ACTOR_SUFFIX.sub("", actor)


def instance_of(actor: str) -> str:
    match = _ACTOR_SUFFIX.search(actor)
    return match.group(0)[3:] if match else ""


def parse_line(line: str) -> LogEvent | None:
    """Parse one script log line; engine lines and anything unrecognised give None."""
    m = _LINE.match(line)
    if m is None:
        return None
    body = m.group("body")
    sub, entity_id, kind, actor, instance = "", 0, "", "", ""
    em = _ENTITY.match(body)
    if em is not None:
        sub, entity_id, kind = em.group("sub"), int(em.group("id")), em.group("kind")
        instance = instance_of(em.group("actor"))
        actor, body = strip_instance(em.group("actor")), em.group("rest")
    elif m.group("module") == "CombatInfo":
        sm = _SUB.match(body)
        if sm is not None:
            sub, body = sm.group("sub"), sm.group("rest")
    fields = {key.strip(): value.strip() for key, value in _PAIR.findall(body)}
    text = _PAIR.sub("", body).strip() if fields else body.strip()
    return LogEvent(
        ts=parse_timestamp(m.group("ts")),
        tick=int(m.group("tick")),
        module=m.group("module"),
        sub=sub,
        entity_id=entity_id,
        kind=kind,
        actor=actor,
        text=text,
        fields=fields,
        instance=instance,
    )
