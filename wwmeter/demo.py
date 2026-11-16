"""A made-up fight fed through the real tracker, for trying the overlay without the game."""

from __future__ import annotations

import math
import random
import threading
import time

from .logparse import LogEvent
from .tracker import Tracker

_TEAM = (
    ("BP_DemoVanguard", "破阵", 1.00),
    ("BP_DemoSupport", "回响", 0.35),
    ("BP_DemoBurst", "终曲", 0.70),
)
_BOSS_HP = 6_500_000.0


class DemoFeed(threading.Thread):
    def __init__(self, tracker: Tracker, speed: float = 1.0) -> None:
        super().__init__(name="demo-feed", daemon=True)
        self._tracker = tracker
        self._speed = speed
        self._stop_flag = threading.Event()

    def stop(self) -> None:
        self._stop_flag.set()

    def _skill(self, actor: str, skill: str, now: float) -> None:
        self._tracker.on_log(
            LogEvent(
                ts=now, tick=0, module="Battle", sub="", entity_id=0, kind="", actor="",
                text="RoleTeam PerformPossess", fields={"roleActor": actor + "_C_1"},
            ),
            now,
        )
        self._tracker.on_log(
            LogEvent(
                ts=now, tick=0, module="CombatInfo", sub="Skill", entity_id=1, kind="Player",
                actor=actor, text="BaseSkillComponent.BeginSkillAsync", fields={"技能名": skill},
            ),
            now,
        )

    def _life(self, entity: int, hp: float, now: float) -> None:
        self._tracker.on_log(
            LogEvent(
                ts=now, tick=0, module="CombatInfo", sub="Part", entity_id=entity, kind="Monster",
                actor="BP_MB1DemoTarget00601", text="UpdatePartInfo",
                fields={"TagName": "怪物.common.弱点", "Activated": "True", "LifeValue": str(round(hp))},
            ),
            now,
        )

    def run(self) -> None:
        rng = random.Random(7)
        tracker = self._tracker
        tracker.set_status(
            game=True, focused=True, log=True, screen=True, backend="demo", fps=20.0,
            note="Demo data. Not a real fight.",
        )
        entity = 0
        while not self._stop_flag.is_set():
            hp = _BOSS_HP
            entity += 1
            started = time.time()
            self._life(entity, hp, started)
            turn = 0
            next_swap = 0.0
            while hp > 0 and not self._stop_flag.is_set():
                now = time.time()
                elapsed = (now - started) * self._speed
                if elapsed >= next_swap:
                    actor, skill, _ = _TEAM[turn % len(_TEAM)]
                    self._skill(actor, skill, now)
                    turn += 1
                    next_swap = elapsed + rng.uniform(3.0, 7.0)
                _, _, weight = _TEAM[(turn - 1) % len(_TEAM)]
                # bursts every ~12 s on top of a steady trickle
                burst = 1.0 + 2.5 * max(0.0, math.sin(elapsed * 2 * math.pi / 12.0)) ** 4
                if rng.random() < 0.55:
                    value = rng.uniform(2_000, 9_000) * weight * burst
                    if rng.random() < 0.25:
                        value *= 2.1
                    hp -= value
                    self._life(entity, max(0.0, hp), now)
                tracker.on_boss(now, max(0.0, hp / _BOSS_HP), "Demo target")
                tracker.tick(now)
                time.sleep(0.08)
            # between fights
            pause_until = time.time() + 12.0
            while time.time() < pause_until and not self._stop_flag.is_set():
                tracker.on_boss(time.time(), None)
                tracker.tick(time.time())
                time.sleep(0.2)
