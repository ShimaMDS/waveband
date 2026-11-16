"""Fold log events and screen readings into encounters, and describe them for the UI.

Damage comes from three places, best first:

``log``      The game logs the remaining HP of an enemy's weak-point part after every hit
             (``[Part] UpdatePartInfo ... [LifeValue: n]``). For enemies that have one, the drop
             between two lines is the exact damage dealt.
``numbers``  Damage numbers read off the screen (optional reader).
``bar``      The boss HP bar. Only a fraction is known. When the game's tables give the boss's
             full HP (see ``gamedata``) the fraction is turned into damage; otherwise it is
             reported in percent of HP.

Each source keeps its own ledger for the whole fight and the best one that has data is shown, so
nothing is ever counted twice.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections import Counter, deque
from dataclasses import dataclass, field

from .gamedata import EnemyData, PartShares, Spawns
from .logparse import LogEvent, instance_of, strip_instance
from .roster import Roster

UNKNOWN = "?"
OTHER = "~other"  # HP the target lost that the log did not report as hits (damage over time)
SOURCES = ("log", "numbers", "bar")
_WAVE_SECONDS = 180
_HISTORY = 500  # finished fights kept and saved: more than one sitting of the game produces
# What the list of earlier fights needs of each; the full description is sent only for the one
# being looked at.
_HISTORY_ROW = ("id", "title", "duration", "damage", "dps", "unit", "ended_at")
_FIGHT_KEYS = ("id", "title", "duration", "damage", "dps", "unit", "players")
_BOSS_RATE_WINDOW = 10.0
# With a boss bar still on screen a lull is a phase change or a dodge, not the end of the fight.
_BOSS_GRACE = 30.0
# While the game's own combat flag is on, a fight is kept open through a lull this long.
_IN_FIGHT_GRACE = 120.0
# A bar reading has to hold this long before a drop counts: the bar animates in from empty
# whenever the HUD reappears after a cutscene.
_BAR_SETTLE = 0.6
_FIELD_MEMORY = 30.0  # seconds of character switches remembered, to date a bar drop back
_BAR_GAP = 0.35  # no bar for this long (three frames at 10 a second) means the HUD has hidden
_BAR_LAST = 0.45  # the readings this close to the last one say where the bar stood when it hid
_BAR_RESET = 2.0
# What was dealt while the HUD was hidden shows on the bar only once it is back, sliding down
# over this long (recorded: the fall began 0.1 to 0.5 s after the return and ended by 0.6 s).
_BAR_EASE = 0.7
_SKIP_SKILLS = ("闪", "Dodge")  # dodges are not part of a rotation
# Reconciling logged HP with the HP bar. The bar reads within ~0.4% of max HP, so a gap has to be
# larger than that, and has to outlast the settle window, before it is counted.
# Weak points tagged like this report the enemy's whole HP. Seen as 弱点, 背部弱点 and 头部弱点;
# parts tagged with the enemy's own name or a hash have separate, much smaller pools.
_HP_TAG = "怪物.common."
_PHASE_LOW, _PHASE_FULL = 0.10, 0.90
_FIGHT_OVER_WAIT = 1.0  # after the game says combat ended, wait this long for the last lines
_DEAD_BAR = 1.5  # seconds a dead boss's bar may still be on screen
_LATE_DEATH = 10.0  # a death reported this long after a fight closed is still that fight's kill
_BOSS_BLUEPRINT = re.compile(r"^BP_M[BL]\d")  # boss-class enemies: the ones a boss bar is for
_RESTART_QUIET = 3.0  # seconds without damage before a fresh copy of the boss means "restarted"
_POOL_ENEMIES = 400  # enemies whose parts' pools are remembered
_POOL_CHECKS = 30  # bar readings in a row that contradict the logged HP before it is distrusted
_LULL = 1.0  # seconds the fight clock keeps running after the last hit
_NUMBERS_WIN = 1.15  # numbers must beat the logged total by this much to be shown instead
_COMBAT_LINGER = 10.0  # seconds after the last skill during which numbers are still read
_BAR_TOLERANCE = 0.008
# Once the log has been quiet this long, the bar has caught up with every logged hit, so what is
# left between them is a pixel or so of reading. Measured on the recordings (2026-11-17): with
# no damage over time the gap then stays within +0.20% (median -0.04%); with Frazzle it sat at
# +0.80% all along, which was the 0.8% tolerance never being booked.
_LOG_QUIET = 2.0
_BAR_TOLERANCE_QUIET = 0.0035
_BAR_AGREES = 0.01
_BAR_JUMP = 0.03  # a gap growing this fast is the bar switching to another enemy, not damage
# ...unless there is only one boss about. Then it is damage the log did not report, once it has
# lasted this long: longer than a misread of the bar, or a log line arriving after the bar moved.
_JUMP_HOLD = 2.0
# The game writes the killing blow's own HP line just after the death line, at the same moment.
# One that comes later than this is not that blow.
_BLOW_LINE = 0.5
# A hit is in the log at once and on the bar a moment later. After this long the bar shows it.
_LOG_SHOWN = 1.0
# The boss bar belongs to whichever boss-class enemy the log's combat lines named last. A boss
# logs several lines a second while it fights, so one silent for this long is not the one shown.
_BAR_ENEMY_WINDOW = 15.0
_BOSS_GONE = 20.0  # a dead boss's last few lines do not make it the bar's enemy again
_TITLE_LEVEL = re.compile(r"\(Lv (\d{1,3})\)$")


def _plain(name: str) -> str:
    """A name with only its letters and digits, for comparing one read off the screen."""
    return "".join(ch for ch in name.casefold() if ch.isalnum())


def _num(value: float, digits: int) -> float | int:
    return round(value, digits) if digits else round(value)


@dataclass
class PlayerStats:
    damage: float = 0.0
    hits: int = 0
    max_hit: float = 0.0


@dataclass
class Ledger:
    total: float = 0.0
    hits: int = 0
    max_hit: float = 0.0
    players: dict[str, PlayerStats] = field(default_factory=dict)
    wave: dict[int, float] = field(default_factory=dict)  # second since start -> amount

    def add(self, second: int, key: str, value: float, hit: bool = True) -> None:
        self.total += value
        self.wave[second] = self.wave.get(second, 0.0) + value
        stats = self.players.setdefault(key, PlayerStats())
        if not hit:  # an amount with no single hit behind it
            stats.damage += value
            return
        self.hits += 1
        self.max_hit = max(self.max_hit, value)
        stats.damage += value
        stats.hits += 1
        stats.max_hit = max(stats.max_hit, value)


@dataclass
class Encounter:
    id: int
    started: float
    last_activity: float
    title: str = ""
    ended: float | None = None
    ledgers: dict[str, Ledger] = field(default_factory=lambda: {s: Ledger() for s in SOURCES})
    order: list[str] = field(default_factory=list)  # players in order of first appearance
    skills: dict[str, Counter] = field(default_factory=dict)
    targets: Counter = field(default_factory=Counter)  # enemy blueprint -> damage taken
    boss_first: float | None = None
    boss_last: float | None = None
    boss_seen_at: float = 0.0
    boss_samples: deque = field(default_factory=lambda: deque(maxlen=600))
    life: float | None = None  # last logged HP of the main target
    main_entity: int | None = None  # the enemy with the most HP: the one the boss bar shows
    main_actor: str = ""
    main_max: float = 0.0  # its full HP (the log reports full HP before the first hit)
    bar_trusted: bool | None = None  # None until the bar has been compared with logged HP
    other_counted: float = 0.0  # HP lost per the bar that the log never reported
    jump_since: float | None = None  # since when the bar has been far below the log
    life_log: deque = field(default_factory=deque)  # (when, logged HP) of the main target, lately
    full_hp: dict[int, float] = field(default_factory=dict)  # enemy -> full HP, for those damaged
    pool_checks: int = 0
    pool_mismatch: bool = False  # the logged value is a breakable part's own pool, not the HP
    # The bar ledger again, split by which enemy the bar was showing (0: none named yet), so each
    # share can be turned into damage with that enemy's own HP.
    bar_by_enemy: dict[int, Ledger] = field(default_factory=dict)
    bar_enemy: int = 0  # the enemy the bar showed last
    # Who was on field as the fight began (None: not known), and each switch since, as (time,
    # who came on field). The time each character spent on field is counted from these.
    first_on_field: str | None = None
    switches: list[tuple[float, str]] = field(default_factory=list)

    @property
    def source(self) -> str:
        logged, read = self.ledgers["log"].total, self.ledgers["numbers"].total
        if self.pool_mismatch and self.ledgers["bar"].total > 0 and read <= 0:
            return "bar"  # the log was tracking a part, so its total is not the damage dealt
        # The log is exact but only covers enemies that report HP. When the numbers read off the
        # screen add up to clearly more, other enemies were being hit too, and the rough total is
        # the fuller picture. (On a logged enemy alone the reader gets about half, never more.)
        if read > _NUMBERS_WIN * logged and read > 0:
            return "numbers"
        for name in SOURCES:
            if self.ledgers[name].total > 0:
                return name
        return "log"

    def duration(self, now: float) -> float:
        # The clock holds a moment after the last hit. If the fight goes on, the next hit moves it
        # forward and the pause is counted; if it was the last hit, the figures stay put instead
        # of sinking until the fight times out.
        end = self.last_activity if self.ended is not None else min(now, self.last_activity + _LULL)
        return max(1.0, end - self.started)

    def field_times(self, end: float) -> dict[str, float]:
        """Seconds each character was on field between the fight's start and ``end``. They add
        up to ``end`` minus the start: time with nobody known on field is filed under UNKNOWN."""
        times: dict[str, float] = {}
        who, since = self.first_on_field or UNKNOWN, self.started
        for stamp, actor in self.switches:
            stamp = min(max(stamp, since), end)  # a switch after the last hit changes nothing
            if stamp > since:
                times[who] = times.get(who, 0.0) + stamp - since
            who, since = actor, stamp
        if end > since:
            times[who] = times.get(who, 0.0) + end - since
        return times

    def slot(self, key: str) -> int:
        if key not in self.order:
            self.order.append(key)
        return self.order.index(key)


class Tracker:
    """Thread-safe: the log thread, the screen thread and the server all call into it."""

    def __init__(
        self, roster: Roster | None = None, timeout: float = 8.0, use_life: bool = True,
        enemies: EnemyData | None = None, history_path: str | None = None,
        parts: PartShares | None = None,
    ) -> None:
        self._use_life = use_life  # False only to exercise the HP-bar fallback on a recording
        self._history_path = history_path  # finished fights are kept in this file; None: nowhere
        self._view: int | None = None  # the earlier fight being looked at, if any
        self._opened: list[dict] | None = None  # an earlier session opened for reading
        self._opened_label = ""
        self._lock = threading.RLock()
        self._roster = roster or Roster()
        self._spawns = Spawns(enemies)  # which game-data entity each spawned enemy is
        # What share of its HP each of an enemy's parts is, and the parts of each enemy seen:
        # enemy -> (actor, spawned copy, part tag -> its pool when full: the highest value seen).
        self._parts = parts if parts is not None else PartShares(path=None)
        self._pools: dict[int, tuple[str, str, dict[str, float]]] = {}
        self._boss_seen: dict[int, float] = {}  # boss-class enemy -> last combat line naming it
        self._boss_gone: dict[int, float] = {}  # boss-class enemy -> when it died
        self._timeout = timeout
        self._next_id = 1
        self._current: Encounter | None = None
        self._last: Encounter | None = None
        self._history: deque[dict] = deque(maxlen=_HISTORY)  # newest first
        self._load_history()
        self._on_field: str | None = None
        self._field_log: deque[tuple[float, str]] = deque()  # (time, who came on field)
        self._life: dict[int, tuple[str, float]] = {}  # entity -> (part tag, last HP)
        self._life_max: dict[int, float] = {}  # entity -> highest HP seen
        self._instances: dict[str, int] = {}  # blueprint instance number -> entity
        self._first_life: dict[int, float] = {}  # entity -> first value of the part being followed
        self._not_hp: set[int] = set()  # enemies whose weak points turned out to be separate pools
        self._fight_over_at: float | None = None  # when the game said combat ended
        self._in_fight = False  # the game's own combat flag, as last logged
        self._combat_at = 0.0  # last time the player used a skill
        self._combat_since = 0.0  # when the current run of skill use began
        self._enemy_hit_at = 0.0  # last time the log showed an enemy being hit
        self._unmeasured: str = ""  # enemy seen being hit that reports no HP
        self._unmeasured_entity = 0
        self._role_votes: dict[str, Counter] = {}  # blueprint name -> character IDs seen in skills
        self._bar_recent: deque = deque()  # (time, fraction) over the last _BAR_RESET seconds
        self._bar_committed: float | None = None
        self._bar_seen_at = 0.0
        self._bar_back_at = 0.0  # when the bar last came back on screen
        self._bar_flushed = True  # nothing waiting from before the bar was last hidden
        self._bar_dead_until = 0.0  # bar readings are ignored until then: its boss has just died
        self._blow: tuple | None = None  # the kill just credited, until the blow's own line comes
        self.status: dict = {
            "game": False, "focused": False, "log": False, "log_lines": 0,
            "screen": False, "backend": "", "fps": 0.0, "numbers": 0, "note": "",
        }

    # -- inputs -------------------------------------------------------------------------------

    def set_status(self, **values) -> None:
        with self._lock:
            self.status.update(values)

    def on_log(self, event: LogEvent, now: float) -> None:
        with self._lock:
            self.status["log_lines"] += 1
            if event.module == "Battle":
                if "PerformPossess" in event.text and "roleActor" in event.fields:
                    self._set_on_field(strip_instance(event.fields["roleActor"]), now)
                elif event.text.startswith("NotifyInFight"):
                    # the game's own combat flag
                    self._in_fight = event.text.rstrip().endswith("True")
                    self._fight_over_at = None if self._in_fight else now
            elif event.module == "AI":
                if event.text == "RemoveHatredItem" and event.fields.get("reason") == "Dead":
                    self._on_death(event.fields.get("Actor", ""), now)
            elif event.module == "CombatInfo":
                if event.kind == "Monster" and _BOSS_BLUEPRINT.match(event.actor):
                    self._on_boss_line(event, now)
                if event.kind == "Monster" and event.sub == "Part":
                    self._on_pool(event)
                if event.kind == "Player":
                    self._on_player_event(event, now)
                elif event.kind == "Monster" and event.sub == "Part" and self._use_life:
                    self._on_part(event, now)
                elif event.kind == "Monster" and event.sub == "Hit":
                    self._enemy_hit_at = now
                    # A boss with its bar on screen is measured off the bar, logged HP or not.
                    on_bar = bool(_BOSS_BLUEPRINT.match(event.actor)) and now - self._bar_seen_at <= 5.0
                    if event.entity_id not in self._life and not on_bar:
                        self._unmeasured, self._unmeasured_entity = event.actor, event.entity_id
            elif event.module in ("World", "Entity"):
                if "JoinSceneNotify" in event.text:
                    # Another scene: the bosses of the one just left are not about any more.
                    # Entering a hologram again within seconds of leaving it otherwise counts
                    # two bosses, and the bar is not believed over a big gap (_reconcile).
                    self._boss_seen.clear()
                self._spawns.on_event(event)

    def on_context(self, event: LogEvent) -> None:
        """A line from before the meter started: only what says where the player is, which
        enemies are spawned and how big their parts' pools are is taken from it, so a fight
        already loaded can be recognised."""
        with self._lock:
            if event.module in ("World", "Entity"):
                self._spawns.on_event(event)
            elif event.module == "CombatInfo" and event.kind == "Monster" and event.sub == "Part":
                self._on_pool(event)

    def _on_pool(self, event: LogEvent) -> None:
        """Keep the full size of each of an enemy's parts. The first line for a part is written
        before any hit, so on an enemy whose full HP the tables give it says what share of the
        HP that part is; on one whose HP they do not give, a share learned elsewhere turns the
        pool back into the HP."""
        try:
            life = float(event.fields["LifeValue"])
        except (KeyError, ValueError):
            return
        tag = event.fields.get("TagName", "")
        if not tag or life <= 0:
            return
        known = self._pools.get(event.entity_id)
        if known is None or known[:2] != (event.actor, event.instance):
            # another enemy, or a fresh copy of this one, under a number used before
            self._pools.pop(event.entity_id, None)
            known = self._pools[event.entity_id] = (event.actor, event.instance, {})
            while len(self._pools) > _POOL_ENEMIES:
                del self._pools[next(iter(self._pools))]
        pools = known[2]
        if tag not in pools:
            # only a level the placement fixes: one read off the screen could be misread
            hp = self._spawns.data.hp(self._spawns.enemy(event.entity_id))
            if hp:
                self._parts.learn(event.actor, tag, life, hp)
        pools[tag] = max(life, pools.get(tag, 0.0))

    def _pool_hp(self, entity: int) -> int | None:
        """An enemy's full HP worked out from its parts' pools, where a share is known."""
        actor, _, pools = self._pools.get(entity, ("", "", {}))
        return self._parts.full_hp(actor, pools) if pools else None

    def _on_boss_line(self, event: LogEvent, now: float) -> None:
        gone = self._boss_gone.get(event.entity_id)
        if gone is not None:
            if now - gone < _BOSS_GONE:
                return
            del self._boss_gone[event.entity_id]
        self._boss_seen[event.entity_id] = now
        if event.instance:
            self._instances[event.instance] = event.entity_id
        if len(self._boss_seen) + len(self._boss_gone) > 200:
            recent = lambda times: {e: t for e, t in times.items() if now - t < 600.0}  # noqa: E731
            self._boss_seen, self._boss_gone = recent(self._boss_seen), recent(self._boss_gone)

    def _lone_boss(self, enc: Encounter, now: float) -> bool:
        """True when one boss-class enemy has been in the log's combat lines lately and it is
        the one this fight's bar has been showing: a bar that refills is then its next bar."""
        about = [e for e, seen in self._boss_seen.items() if now - seen <= _BAR_ENEMY_WINDOW]
        return len(about) == 1 and enc.bar_enemy in (0, about[0])

    def _set_on_field(self, actor: str, now: float, switched: bool = True) -> None:
        """``switched`` is False when no switch was seen and ``actor`` is taken to be on field
        because it acted: it was then on field before this moment too."""
        self._on_field = actor
        enc = self._current
        if enc is not None:
            if not switched and enc.first_on_field is None and not enc.switches:
                enc.first_on_field = actor
            else:
                enc.switches.append((now, actor))
        log = self._field_log
        log.append((now, actor))
        # keep the last switch before the cut-off too: it says who was on field at the cut-off
        while len(log) > 1 and now - log[1][0] > _FIELD_MEMORY:
            log.popleft()

    def _field_at(self, when: float) -> str | None:
        """Who was on field at a moment in the recent past."""
        found = None
        for stamp, actor in self._field_log:
            if stamp > when:
                break
            found = actor
        if found is None and self._field_log:
            found = self._field_log[0][1]  # before the first switch seen: whoever that was
        return found or self._on_field

    def _bar_enemy(self, now: float) -> int:
        """The boss-class enemy the boss bar is most likely showing, or 0 when none is around."""
        entity, seen = max(self._boss_seen.items(), key=lambda item: item[1], default=(0, 0.0))
        return entity if now - seen <= _BAR_ENEMY_WINDOW else 0

    def _on_player_event(self, event: LogEvent, now: float) -> None:
        if event.sub != "Skill" or "BeginSkill" not in event.text:
            return
        role_id = self._roster.role_id_of(event.fields.get("技能Id", ""))
        if role_id is not None:
            self._role_votes.setdefault(event.actor, Counter())[role_id] += 1
        if self._on_field is None:
            # no switch seen yet: whoever acts is on field
            self._set_on_field(event.actor, now, switched=False)
        name = event.fields.get("技能名", "")
        if not name or any(word in name for word in _SKIP_SKILLS):
            return
        if now - self._combat_at > _COMBAT_LINGER:
            self._combat_since = now
        self._combat_at = now
        enc = self._current
        if enc is not None:
            enc.skills.setdefault(event.actor, Counter())[name] += 1

    def _on_part(self, event: LogEvent, now: float) -> None:
        try:
            life = float(event.fields["LifeValue"])
        except (KeyError, ValueError):
            return
        tag = event.fields.get("TagName", "")
        if not tag.startswith(_HP_TAG):
            return  # a named breakable part (a wing, a shield) with its own pool, not the HP
        if event.entity_id in self._not_hp:
            return
        known = self._life.get(event.entity_id)
        if self._blow is not None and self._blow[1] == event.entity_id and known == (tag, 0.0):
            self._on_late_blow(life, now)
        if known is not None and known[0] != tag:
            # An enemy's weak points normally all report its one HP pool, so a single one is
            # followed. If another starts from a different value, they are separate pools and
            # none of them is the enemy's HP.
            first = self._first_life.get(event.entity_id, life)
            if known[1] == first and abs(life - first) > 0.01 * max(life, first):
                self._not_hp.add(event.entity_id)
                del self._life[event.entity_id]
            return
        self._life[event.entity_id] = (tag, life)
        self._first_life.setdefault(event.entity_id, life)
        if event.instance:
            self._instances[event.instance] = event.entity_id
        self._life_max[event.entity_id] = max(life, self._life_max.get(event.entity_id, 0.0))
        if known is None:
            # First sighting: nothing to compare against yet. If it is a fresh copy of the enemy
            # being fought, the player restarted the fight, so the old attempt is over.
            # A pack has several copies of one enemy, and waves bring more once the first die,
            # so it only counts as a restart when the old copy was left alive and the fight had
            # gone quiet, as it does across the reload.
            enc = self._current
            if enc is not None and enc.main_actor == event.actor and enc.main_entity != event.entity_id:
                old = self._life.get(enc.main_entity)
                if old is not None and old[1] > 0 and now - enc.last_activity >= _RESTART_QUIET:
                    self._close(enc)
            return
        lost = known[1] - life
        if lost <= 0:
            return
        enc = self._add(now, "log", lost)
        enc.targets[event.actor] += lost
        full = self._life_max.get(event.entity_id, life)
        enc.full_hp[event.entity_id] = full
        if enc.main_entity in (None, event.entity_id) or full > enc.main_max:
            if enc.main_entity != event.entity_id:
                enc.bar_trusted, enc.other_counted, enc.jump_since = None, 0.0, None
                enc.life_log.clear()
            enc.main_entity, enc.main_max, enc.life = event.entity_id, full, life
            enc.main_actor = event.actor
            log = enc.life_log
            if not log:
                log.append((float("-inf"), known[1]))
            log.append((now, life))
            # keep the last value from before the cut-off too: it says where the HP stood then
            while len(log) > 1 and now - log[1][0] > 2 * _LOG_SHOWN:
                log.popleft()

    def _on_death(self, actor_with_instance: str, now: float) -> None:
        """An enemy died. Whatever HP it still showed was dealt by the killing blow, which the
        log or the bar can miss when it lands during a cutscene."""
        actor = strip_instance(actor_with_instance)
        entity = self._instances.get(instance_of(actor_with_instance))
        # the bosses about just before this one died, for a next bar the bar had not yet been
        # believed to show
        about = [e for e, seen in self._boss_seen.items() if now - seen <= _BAR_ENEMY_WINDOW]
        if entity is not None and self._boss_seen.pop(entity, None) is not None:
            self._boss_gone[entity] = now  # the boss bar is no longer this enemy's
        enc = self._current
        late = False
        if enc is None:
            # A kill that lands in an ultimate's cutscene: the game drops its combat flag first
            # and reports the death a moment later (1.1 s in the fight this was found in), by
            # which time the fight has been closed. Open it again for the killing blow.
            enc = self._last
            if enc is None or enc.ended is None or not 0 <= now - enc.ended <= _LATE_DEATH:
                return
            if entity is not None and enc.bar_enemy not in (0, entity) and entity != enc.main_entity:
                return  # some other enemy's death, not the one this fight was against
            late = True
            self._current, self._bar_committed = enc, enc.boss_last
        try:
            self._credit_death(enc, actor, entity, now, about)
        finally:
            if late:
                self._current, self._bar_committed = None, None
                enc.ended = enc.last_activity
                self._refile(enc)

    def _refile(self, enc: Encounter) -> None:
        """A fight already in the list has changed: describe it again and save the list."""
        for place, fight in enumerate(self._history):
            if fight["id"] == enc.id:
                self._history[place] = self._describe(enc, enc.ended)
                self._save_history()
                return

    def _credit_death(
        self, enc: Encounter, actor: str, entity: int | None, now: float, about: list[int] | None = None,
    ) -> None:
        if entity is not None and self._use_life and not enc.pool_mismatch:
            tag, life = self._life.get(entity, ("", 0.0))
            if life > 0:
                self._life[entity] = (tag, 0.0)
                # part of what is left may already be booked as 'over time' from the bar
                rest = life - enc.other_counted if entity == enc.main_entity else life
                if rest > 0:
                    ledger, key = enc.ledgers["log"], self._on_field or UNKNOWN
                    stats = ledger.players.get(key)
                    biggest = (ledger.max_hit, stats.max_hit if stats else 0.0)
                    self._add(now, "log", rest)
                    enc.targets[actor] += rest
                    if entity == enc.main_entity and enc.bar_trusted:
                        self._blow = (enc, entity, life, rest, now, key, biggest)
        is_bar_target = actor == enc.main_actor or bool(_BOSS_BLUEPRINT.match(actor))
        if is_bar_target:
            about = about or []
            self._take_unbelieved_bar(enc, len(about) == 1 and enc.bar_enemy in (0, about[0]))
        if is_bar_target and self._bar_committed:
            if enc.ledgers["log"].total <= 0 or enc.pool_mismatch:
                self._add_bar(now, self._bar_committed * 100.0, entity)
            self._bar_committed = 0.0
            enc.boss_last = 0.0
            self._bar_recent.clear()
            self._bar_dead_until = now + _DEAD_BAR  # its bar lingers on screen a moment
        if entity == enc.main_entity and entity is not None:
            enc.life = min(enc.life or 0.0, enc.other_counted)  # the readout shows nothing left

    def _take_unbelieved_bar(self, enc: Encounter, lone: bool) -> bool:
        """The boss's next bar, shown too briefly to have been believed. True when taken.

        A refilled bar is believed once it has stayed up for most of two seconds. Inferno Rider
        at hologram I shows its second bar for under two (recorded at 1080p, 2026-11-16: the
        first bar to 21%, the second full, down to 77%, gone 1.8 s after it appeared, the death
        reported 6.4 s later after the kill's cutscene). With fewer frames than the recording
        had, the live meter never believed it, and the kill counted one bar of two. So when the
        bar leaves the screen, or the boss dies, the readings since the last believed level are
        looked at: a full bar that has not come back down to that level is the next bar, on the
        same terms as while it is on screen (one boss about, or the old bar nearly empty). The
        rest of the old bar was dealt when the new one appeared; the new one's level is then
        the one to count down from."""
        committed, recent = self._bar_committed, self._bar_recent
        if committed is None or not recent:
            return False
        floor = committed + 0.02
        start = len(recent)
        while start > 0 and recent[start - 1][1] > floor:
            start -= 1
        since = list(recent)[start:]
        # a flash or a misread is a reading or two; a bar is several, over a moment
        if len(since) < 3 or since[-1][0] - since[0][0] < 0.4:
            return False
        peak = max(f for _, f in since)
        if peak < _PHASE_FULL or not (committed <= _PHASE_LOW or lone):
            return False
        if committed > 0:
            self._add_bar(since[0][0], committed * 100.0, enc.bar_enemy or None, at=since[0][0])
        self._bar_committed = peak
        return True

    def _on_late_blow(self, life: float, now: float) -> None:
        """The killing blow's own HP line, which the game writes just after the death line.

        Until it came, all the HP the log still showed was credited to the character on field as
        the blow. This line says how big the blow was. The rest was never in the log, and on a
        boss whose bar has agreed with its logged HP that is damage over time (seen 2026-11-16:
        a 229,768 HP Crownless died with 57,081 still logged, after a blow of 4,295)."""
        enc, _entity, before, rest, at, key, (ledger_biggest, player_biggest) = self._blow
        self._blow = None
        blow = before - life
        unlogged = rest - blow
        if now - at > _BLOW_LINE or blow <= 0 or unlogged < 1.0:
            return
        ledger, second = enc.ledgers["log"], int(at - enc.started)
        ledger.add(second, key, -unlogged, hit=False)
        ledger.add(second, OTHER, unlogged, hit=False)
        # the kill was booked as one hit of everything that was left
        ledger.max_hit = max(ledger_biggest, blow)
        ledger.players[key].max_hit = max(player_biggest, blow)
        enc.slot(OTHER)
        enc.other_counted += unlogged
        enc.life = enc.other_counted  # the readout still shows nothing left
        if enc is not self._current:
            self._refile(enc)

    def wants_numbers(self, now: float) -> bool:
        """True while the player is fighting, so the screen reader rests outside combat."""
        with self._lock:
            return now - self._combat_at <= _COMBAT_LINGER

    def on_damage(self, now: float, value: float, actor: str | None = None) -> None:
        """One damage number read off the screen."""
        if value <= 0:
            return
        with self._lock:
            self.status["numbers"] += 1
            self._add(now, "numbers", value, actor)

    def on_boss(self, now: float, fraction: float | None, name: str | None = None) -> None:
        """Boss HP bar reading: 0..1, or None when no bar is on screen."""
        with self._lock:
            if fraction is None or now < self._bar_dead_until:
                # nothing to read, or a dead boss's bar still on screen for a frame or two: read
                # as a bar, it came back as "16.6% left" on a boss that had just been killed
                return
            self._flush_bar(now)
            if now - self._bar_seen_at > _BAR_GAP:
                self._bar_back_at = now
            self._bar_seen_at = now
            self._bar_flushed = False
            recent = self._bar_recent
            recent.append((now, fraction))
            while recent and now - recent[0][0] > _BAR_RESET:
                recent.popleft()

            settled = max(f for t, f in recent if now - t <= _BAR_SETTLE)
            covered = now - recent[0][0] >= _BAR_SETTLE * 0.8
            committed = self._bar_committed
            if committed is None:
                if covered:
                    self._bar_committed = settled
            elif covered and settled < committed - 5e-4:
                # The hits landed when the bar fell, which is at least a settle window ago.
                # Whoever was on field then dealt them, not whoever has come on since.
                began = self._drop_began(now, committed, settled)
                enc = self._add_bar(now, (committed - settled) * 100.0, at=began)
                self._bar_committed = settled
            elif now - recent[0][0] >= _BAR_RESET * 0.8 and min(f for _, f in recent) > committed + 0.02:
                # Refilled: a new target or the boss's next bar, not healing we caused. Every
                # reading in the window is of the new bar (that is what the test above says), so
                # its highest is where the new bar started and its first is when it appeared.
                # Counting from the level two seconds on, as this used to, lost whatever was
                # dealt in those two seconds: 9% and 14% of a bar in two recorded kills.
                peak, rose_at = max(f for _, f in recent), recent[0][0]
                enc = self._current
                if enc is not None and peak >= _PHASE_FULL and (
                    committed <= _PHASE_LOW or self._lone_boss(enc, now)
                ):
                    # The boss's next bar, so the rest of the old one was dealt too. A strong hit
                    # takes the old bar from a third straight to a full new one inside a quarter
                    # of a second (recorded: 37% and 15% left), so with one boss about the rest is
                    # credited whatever its size; otherwise only a sliver, since a bar that jumps
                    # up may be a second boss's.
                    self._add_bar(now, committed * 100.0, enc.bar_enemy or None, at=rose_at)
                self._bar_committed = peak

            enc = self._current
            if enc is None or self._bar_committed is None:
                return
            self._reconcile(enc, now)
            enc.boss_seen_at = now
            if enc.boss_first is None:
                enc.boss_first = self._bar_committed
            enc.boss_last = self._bar_committed
            enc.boss_samples.append((now, self._bar_committed))
            if name and not enc.title:
                enc.title = name

    def _drop_began(self, now: float, before: float, after: float) -> float:
        """When the bar fell from one settled level to the next, going by the readings kept.

        Not simply a settle window ago. A single reading a pixel long (the end of the bar
        flickers by one) holds the settled level up for the whole window, so a drop can be
        booked well after it happened, by when another character may be on field. The fall is
        put where it fits the readings best: before it they are near the old level, after it
        near the new one, and a stray one either side costs only itself.

        A fall in the first moments after the bar comes back was dealt while it was hidden,
        nearly always by an ultimate in its cutscene, and the switch to the next character
        tends to follow the cutscene by a fifth of a second: that fall is dated to the bar's
        return, which is before the switch."""
        recent = self._bar_recent
        cost = best = sum(abs(f - after) for _, f in recent)  # the fall before every reading
        first = 0  # index of the first reading after the fall
        for k, (_, f) in enumerate(recent, 1):
            cost += abs(f - before) - abs(f - after)
            if cost < best - 1e-9 and k < len(recent):
                best, first = cost, k
        fell = recent[first][0]
        if self._bar_back_at <= fell <= self._bar_back_at + _BAR_EASE:
            return self._bar_back_at
        return min(recent[max(first - 1, 0)][0], now - _BAR_SETTLE)

    def _flush_bar(self, now: float) -> None:
        """The bar has gone from the screen (an ultimate's cutscene, usually). Book whatever it
        had lost that was still waiting out the settle window, to whoever was on field while it
        was last seen. Left for the bar's return, a slow run of small hits would be credited to
        the next character: the HUD hides at a switch more often than not."""
        if self._bar_flushed or now - self._bar_seen_at <= _BAR_GAP:
            return
        self._bar_flushed = True
        seen, committed = self._bar_seen_at, self._bar_committed
        enc = self._current
        if enc is not None and self._take_unbelieved_bar(enc, self._lone_boss(enc, now)):
            committed = self._bar_committed
        last = [f for t, f in self._bar_recent if seen - t <= _BAR_LAST]
        if len(last) < 3:  # a slow capture: take the last three readings, if they are recent
            last = [f for t, f in list(self._bar_recent)[-3:] if seen - t <= 2 * _BAR_LAST]
        if committed is None or len(last) < 3:
            return
        # The middle reading: a hit flashes white at the bar's end and reads a few pixels long
        # for a frame, so the highest would hold a real drop back, and the lowest could be a
        # misread.
        level = sorted(last)[len(last) // 2]
        if level < committed - 5e-4:
            self._add_bar(seen, (committed - level) * 100.0, at=seen - _BAR_LAST)
            self._bar_committed = level

    def _settle_other(self, enc: Encounter, now: float) -> None:
        """If the log now accounts for HP that was booked as 'over time' while the bar was ahead
        of it, take that amount back so it is not counted twice.

        The bar is compared with the log as it stood a second ago, not as it stands now: a hit
        is logged at once and shows on the bar a moment later, so at the moment of a hit the bar
        looks a hit too full. Compared then, a burst of hits took back ticks the log never
        reported, and they came back two seconds later; a boss killed inside those seconds lost
        the row (seen 2026-11-16: 453 where about 20,400 was due). The lowest of the bar's
        recent readings is used, so a reading that is a few pixels long for a frame takes
        nothing back."""
        if enc.other_counted <= 0 or enc.life is None or not enc.life_log:
            return
        window = [f for t, f in self._bar_recent if now - t <= _BAR_SETTLE]
        if len(window) < 2:
            return  # the bar has only just come back: one reading is not enough to go by
        then = now - _LOG_SHOWN
        life_then = enc.life_log[0][1]
        for stamp, value in enc.life_log:
            if stamp > then:
                break
            life_then = value
        # the same tolerance as booking uses, or what a quiet spell booked would be taken back at
        # the next hit and booked again after it
        still_missing = (life_then / enc.main_max - min(window) - self._tolerance(enc, now)) * enc.main_max
        still_missing = max(0.0, still_missing)
        if still_missing < enc.other_counted:
            enc.ledgers["log"].add(int(now - enc.started), OTHER, still_missing - enc.other_counted, hit=False)
            enc.other_counted = still_missing

    @staticmethod
    def _tolerance(enc: Encounter, now: float) -> float:
        """How far below the logged HP the bar may sit before the difference counts as damage the
        log did not report. Wide while hits are being logged (a hit is in the log a moment before
        it is on the bar), a pixel or so once the log has been quiet."""
        last_line = enc.life_log[-1][0] if enc.life_log else None
        if last_line is not None and now - last_line >= _LOG_QUIET:
            return _BAR_TOLERANCE_QUIET
        return _BAR_TOLERANCE

    def _reconcile(self, enc: Encounter, now: float) -> None:
        """Count HP the bar shows as lost but the log never reported.

        The log only reports hits. Damage over time (erosion and the like) lowers the bar without
        a log line, so on such teams the log alone comes up short. The bar is only believed once
        it has agreed with the log for this enemy, and only for gaps that persist.
        """
        if enc.main_entity is None or enc.life is None or enc.main_max <= 0 or enc.bar_trusted is False:
            return
        recent = self._bar_recent
        if now - recent[0][0] < _BAR_SETTLE * 0.8:
            return
        self._settle_other(enc, now)
        # the most HP the bar showed lately: a misread shorter than the window cannot lower it
        highest = max(f for t, f in recent if now - t <= _BAR_SETTLE)
        hp_left = enc.life - enc.other_counted
        gap = (hp_left / enc.main_max) - highest
        # Some enemies log a weak point with its own small pool. It empties far faster than the
        # HP bar, or never matched it to begin with; either way it is not the enemy's HP.
        contradicts = gap < -0.05 or (enc.bar_trusted is None and abs(gap) > 0.05)
        enc.pool_checks = enc.pool_checks + 1 if contradicts else 0
        if enc.pool_checks >= _POOL_CHECKS:
            enc.pool_mismatch = True
        if enc.bar_trusted is None:
            if abs(gap) <= _BAR_AGREES:
                enc.bar_trusted = True
            return
        if gap > _BAR_JUMP:
            # With another boss about, the bar has gone over to that one. A lone boss has no
            # other bar to show, so this is damage the log did not report: one damage-over-time
            # tick can be more than 3% of a small boss's bar (seen on 2026-11-16: Frazzle on a
            # 229,768 HP Crownless took 14% of the bar in 21 s without one log line, and the
            # meter stopped believing the bar after the first 1%).
            if not self._lone_boss(enc, now):
                enc.bar_trusted = False
                return
            if enc.jump_since is None:
                enc.jump_since = now
            if now - enc.jump_since < _JUMP_HOLD:
                return
        else:
            enc.jump_since = None
        extra = (gap - self._tolerance(enc, now)) * enc.main_max
        if extra > 1.0:
            enc.other_counted += extra
            enc.last_activity = now
            enc.slot(OTHER)
            enc.ledgers["log"].add(int(now - enc.started), OTHER, extra, hit=False)

    def set_title(self, title: str, replace: bool = False) -> None:
        with self._lock:
            if self._current is not None and title and (replace or not self._current.title):
                self._current.title = title

    def current_id(self) -> int | None:
        with self._lock:
            return self._current.id if self._current is not None else None

    def reload_tables(self, then=None) -> None:
        """Read the enemy tables again, after an update wrote new ones, and call ``then`` (to
        take up the language again) before the tables are used. Enemies already seen are
        looked up afresh, so a boss that had no HP gets one from its next hit on."""
        with self._lock:
            self._spawns.data.reload()
            if then is not None:
                then()
            self._spawns.refresh()

    def set_timeout(self, seconds: float) -> None:
        """Seconds without damage before a fight is closed, from now on."""
        with self._lock:
            self._timeout = float(seconds)

    def tick(self, now: float) -> None:
        """Close the running encounter once it has gone quiet."""
        with self._lock:
            self._spawns.refresh()  # the game's language may have been switched
            self._flush_bar(now)
            enc = self._current
            if enc is None:
                return
            if now - self._bar_seen_at > _BAR_RESET:
                # The HUD hides during ult cutscenes. Drop the stale samples but keep the level
                # the bar was at, so what it lost while hidden is counted when it comes back.
                self._bar_recent.clear()
            # Using skills keeps a fight open: a chain of ult cutscenes can outlast the timeout
            # with no damage line and no bar on screen.
            if self._fight_over_at is not None and now - self._fight_over_at >= _FIGHT_OVER_WAIT:
                self._fight_over_at = None
                self._close(enc)
                return
            quiet = now - max(enc.last_activity, self._combat_at)
            boss_up = now - self._bar_seen_at < 2.0
            limit = _BOSS_GRACE if boss_up else self._timeout
            if self._in_fight:
                # The game itself says the fight is still on. A lull is then a change of phase,
                # a dead character or the player standing back, not the end: closing here split
                # one Inferno Rider run in two and dropped the last 7% of its first bar. The
                # clock holds during a lull anyway. Capped, in case the flag's "off" is missed.
                limit = max(limit, _IN_FIGHT_GRACE)
            if quiet >= limit:
                self._close(enc)

    def reset(self) -> None:
        """Forget the running fight; the next hit starts a new one."""
        with self._lock:
            if self._current is not None:
                self._close(self._current)
            self._last = None
            self._blow = None
            self._view = None
            self._opened, self._opened_label = None, ""

    # -- earlier fights -----------------------------------------------------------------------

    def _load_history(self) -> None:
        if not self._history_path:
            return
        try:
            with open(self._history_path, encoding="utf-8") as fh:
                fights = json.load(fh).get("fights", [])
        except (OSError, ValueError, AttributeError):
            return  # no file yet, or one that cannot be read: start with an empty list
        for fight in fights[:_HISTORY]:
            if isinstance(fight, dict) and all(key in fight for key in _FIGHT_KEYS):
                fight["live"] = False
                self._history.append(fight)
        # numbers go on from the saved ones, so a fight's number names one fight only
        self._next_id = 1 + max((int(f["id"]) for f in self._history), default=0)

    def _save_history(self) -> None:
        if not self._history_path:
            return
        temporary = self._history_path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self._history_path) or ".", exist_ok=True)
            with open(temporary, "w", encoding="utf-8") as fh:
                json.dump({"v": 1, "fights": list(self._history)}, fh, ensure_ascii=False)
            os.replace(temporary, self._history_path)
        except OSError:
            pass  # a list that cannot be saved must not stop the meter

    def _live_shows(self) -> int | None:
        """The finished fight the meter shows when no earlier one is picked, if it shows one."""
        if self._current is None and self._last is not None:
            return self._last.id
        return None

    def open_session(self, fights: list[dict] | None, label: str = "") -> None:
        """Put an earlier session's fights (newest first) on show for reading, or with None go
        back to this session. This session goes on being measured and written meanwhile; an
        opened one is only read."""
        with self._lock:
            if not fights:
                self._opened, self._opened_label, self._view = None, "", None
                return
            self._opened, self._opened_label = list(fights), label
            self._view = fights[0]["id"]

    def _listed(self) -> list[dict]:
        """The fights that can be stepped through: an opened session's, else this session's."""
        return self._opened if self._opened is not None else list(self._history)

    def view_step(self, step: int) -> None:
        """Look at the fight before (-1) or after (+1) the one on show. Stepping past the newest
        goes back to the running fight; measuring goes on whichever is shown."""
        with self._lock:
            ids = [fight["id"] for fight in self._listed()]
            if not ids:
                self._view = None
                return
            if self._opened is not None:
                place = (ids.index(self._view) if self._view in ids else 0) - step
                if place < 0:
                    self.open_session(None)  # past its newest fight: back to this session
                else:
                    self._view = ids[min(place, len(ids) - 1)]
                return
            shown = self._view if self._view in ids else self._live_shows()
            place = ids.index(shown) if shown in ids else -1  # -1: the running fight, or nothing
            place = min(place - step, len(ids) - 1)
            self.view(ids[place] if place >= 0 else None)

    def view(self, fight_id: int | None) -> None:
        """Look at one earlier fight by its number, or (None) go back to the running one."""
        with self._lock:
            known = any(fight["id"] == fight_id for fight in self._listed())
            if self._opened is not None:
                if known:
                    self._view = fight_id
                else:
                    self.open_session(None)
                return
            # picking the fight already on show is the same as picking none
            self._view = fight_id if known and fight_id != self._live_shows() else None

    # -- internals ----------------------------------------------------------------------------

    def _add(self, now: float, source: str, value: float, actor: str | None = None) -> Encounter:
        enc = self._current
        if enc is None:
            self._fight_over_at = None  # a new fight: the old "combat ended" no longer applies
            enc = self._current = Encounter(
                id=self._next_id, started=now, last_activity=now, first_on_field=self._on_field
            )
            self._next_id += 1
        enc.last_activity = now
        key = actor or self._on_field or UNKNOWN
        enc.slot(key)
        enc.ledgers[source].add(int(now - enc.started), key, value)
        return enc

    def _add_bar(
        self, now: float, percent: float, enemy: int | None = None, at: float | None = None
    ) -> Encounter:
        """Book a drop of the boss bar, in percent of HP, against the enemy the bar is showing.
        ``at`` is when the hits behind it landed, if earlier than now: it decides who is credited."""
        actor = (self._field_at(at) if at is not None else self._on_field) or UNKNOWN
        enc = self._add(now, "bar", percent, actor)
        if enemy is None:
            enemy = self._bar_enemy(now)
        if enemy:
            enc.bar_enemy = enemy
        share = enc.bar_by_enemy.setdefault(enemy, Ledger())
        share.add(int(now - enc.started), actor, percent)
        return enc

    def _level(self, enc: Encounter, enemy) -> int | None:
        """An enemy's level: the one its placement fixes, else the one read off the boss bar.
        Never the other way round: in the Tactical Hologram the bar shows a nominal level
        (80 at difficulty 4) while HP is worked out from the placement's own (75)."""
        if enemy is not None and enemy.level:
            return enemy.level
        match = _TITLE_LEVEL.search(enc.title)
        return int(match.group(1)) if match else None

    def _bar_hp(self, enc: Encounter) -> tuple[dict[int, int], str] | None:
        """Full HP of each enemy the boss bar showed during this fight, and where it is from:
        "tables" when the game's tables gave every one, "parts" when any had to be worked out
        from the pool of one of its parts. None unless every one is known: a total that mixes
        damage and percent means nothing."""
        if not enc.bar_by_enemy:
            return None
        found: dict[int, int] = {}
        origin = "tables"
        for entity in enc.bar_by_enemy:
            # drops booked before the log had named a boss belong to the one the bar went on to show
            entity_id = entity or enc.bar_enemy
            enemy = self._spawns.enemy(entity_id)
            hp = self._spawns.data.hp(enemy, self._level(enc, enemy))
            if hp is None:
                hp, origin = self._pool_hp(entity_id), "parts"
            if hp is None:
                return None
            found[entity] = hp
        return found, origin

    @staticmethod
    def _bar_in_damage(enc: Encounter, hp: dict[int, int]) -> Ledger:
        """The bar ledger with each enemy's share of percent turned into damage."""
        out = Ledger()
        for entity, share in enc.bar_by_enemy.items():
            scale = hp[entity] / 100.0
            out.total += share.total * scale
            out.hits += share.hits
            for second, value in share.wave.items():
                out.wave[second] = out.wave.get(second, 0.0) + value * scale
            for key, stats in share.players.items():
                mine = out.players.setdefault(key, PlayerStats())
                mine.damage += stats.damage * scale
                mine.hits += stats.hits
        # max_hit stays 0: one drop of the bar is however many hits landed while it settled
        return out

    def _close(self, enc: Encounter) -> None:
        enc.ended = enc.last_activity
        self._current = None
        # Whatever was hit during this fight was measured in it. Left set, the name of a boss
        # fought off its bar came up as "reports no HP" for the few seconds after the fight in
        # which the last skills were still running (seen as "ML1Qi Shi" after Inferno Rider).
        self._unmeasured = ""
        self._bar_recent.clear()
        self._bar_committed = None
        if enc.ledgers[enc.source].hits < 3:
            return  # a stray hit is not a fight
        self._last = enc
        self._history.appendleft(self._describe(enc, enc.ended))
        self._save_history()

    def _named_enemy(self, enc: Encounter, read: str):
        """The enemy a fight is named after: the first one its boss bar showed, else the one with
        the most HP. With several on the bar, the one whose name was read off the screen."""
        entities = [entity for entity in enc.bar_by_enemy if entity]
        for entity in (enc.bar_enemy, enc.main_entity):
            if entity and entity not in entities:
                entities.append(entity)
        named = [enemy for enemy in map(self._spawns.enemy, entities) if enemy is not None and enemy.name]
        read = _plain(read)
        return next((enemy for enemy in named if read and _plain(enemy.name) == read), named[0] if named else None)

    def _title(self, enc: Encounter) -> str:
        """What a fight is called. The enemy's name comes from the game's tables, in the client's
        language, when they have one; what was read off the screen is the fallback, and the
        enemy's internal name tidied up the last resort. The level is the one the game shows:
        the one its tables give the bar, else the one read off it, else the placement's."""
        match = _TITLE_LEVEL.search(enc.title)
        read = enc.title[: match.start()].strip() if match else enc.title
        level = int(match.group(1)) if match else None
        enemy = self._named_enemy(enc, read)
        if enemy is not None:
            name = enemy.name
            level = enemy.shown_level or level or (enemy.level if enc.bar_by_enemy else None)
        elif read:
            name = read
        elif enc.targets:
            name = self._roster.lookup(enc.targets.most_common(1)[0][0])[0]
        else:
            return f"Fight {enc.id}"
        return f"{name} (Lv {level})" if level else name

    def _boss(self, enc: Encounter, now: float, table_hp: int = 0) -> dict | None:
        # never below zero: what the bar showed lost on top of the log can pass what the log has left
        life = max(0, round(enc.life - enc.other_counted)) if enc.life is not None else 0
        max_hp = round(enc.main_max)
        if enc.boss_last is None or enc.boss_first is None:
            if enc.life is None:
                return None
            return {"hp": None, "rate": 0, "eta": 0, "life": life, "max_hp": max_hp}
        if enc.life is None and table_hp:
            # nothing logged, but the tables give the full HP: what is left is the bar's share
            life, max_hp = round(table_hp * enc.boss_last), table_hp
        rate = 0.0
        recent = [(t, f) for t, f in enc.boss_samples if now - t <= _BOSS_RATE_WINDOW]
        if enc.boss_last <= 0:
            recent = []  # dead: there is no rate of fall, and no time to go
        if len(recent) >= 2 and recent[-1][0] - recent[0][0] >= 1.0:
            rate = max(0.0, (recent[0][1] - recent[-1][1]) / (recent[-1][0] - recent[0][0]))
        return {
            "hp": round(enc.boss_last, 4),
            "rate": round(rate, 5),
            "eta": round(enc.boss_last / rate, 1) if rate > 1e-5 else 0,
            "life": life,
            "max_hp": max_hp,
        }

    def _describe(self, enc: Encounter, now: float) -> dict:
        source = enc.source
        ledger = enc.ledgers[source]
        # A fight read off the boss bar is in percent of HP, unless the tables give that HP.
        bar_hp, hp_from = (self._bar_hp(enc) if source == "bar" else None) or (None, "")
        if bar_hp is not None:
            percent, ledger = ledger.total, self._bar_in_damage(enc, bar_hp)
        unit = "percent" if source == "bar" and bar_hp is None else "damage"
        if source == "log":
            max_hp_total = round(sum(enc.full_hp.values()))
        elif bar_hp is not None and percent > 0:
            max_hp_total = round(ledger.total / percent * 100.0)
        else:
            max_hp_total = 0
        duration = enc.duration(now)
        digits = 2 if unit == "percent" else 0
        players = []
        # Time on field, over the same stretch the fight's length is measured on. A character
        # that was on field and dealt nothing gets a row all the same, so the times add up.
        on_field = enc.field_times(enc.started + duration)
        dealt = dict(ledger.players)
        for key in on_field:
            dealt.setdefault(key, PlayerStats())
        ranked = sorted(dealt.items(), key=lambda item: (item[0] == OTHER, -item[1].damage))
        for key, stats in ranked:
            if key == OTHER and stats.damage < 1.0:
                continue  # booked for a moment, then reported by the log after all
            if key == UNKNOWN:
                name, element = "Unattributed", None
            elif key == OTHER:
                name, element = "Over time", None
            else:
                votes = self._role_votes.get(key)
                name, element = self._roster.lookup(key, votes.most_common(1)[0][0] if votes else None)
            players.append({
                "key": key,
                "other": key == OTHER,
                "slot": enc.slot(key),
                "name": name,
                "element": element,
                "damage": _num(stats.damage, digits),
                "dps": _num(stats.damage / duration, digits),
                "share": round(stats.damage / ledger.total, 4) if ledger.total else 0.0,
                "hits": stats.hits,
                "max_hit": _num(stats.max_hit, digits),
                "on_field": enc.ended is None and key == self._on_field,
                # Seconds on field, and damage per second of them. Damage dealt off field is
                # booked to whoever is on field then, so the second figure flatters a character
                # that stands on field while another's skills are running. None where there is
                # nothing to say: the "over time" row, and under a second on field.
                "field_time": None if key == OTHER else round(on_field.get(key, 0.0), 1),
                "field_dps": (
                    _num(stats.damage / on_field[key], digits) if on_field.get(key, 0.0) >= 1.0 else None
                ),
                "skills": [
                    {"name": name_, "casts": casts}
                    for name_, casts in enc.skills.get(key, Counter()).most_common(8)
                ],
            })
        last_second = int(duration)
        first_second = max(0, last_second - _WAVE_SECONDS + 1)
        return {
            "id": enc.id,
            "live": enc.ended is None,
            "ended_at": round(enc.ended, 1) if enc.ended is not None else None,
            "title": self._title(enc),
            "duration": round(duration, 1),
            "source": source,
            "unit": unit,
            # Full HP of the enemies damaged, from the log or (for a boss-bar fight) the game's
            # tables: lets the display turn damage into percent of HP. 0 when unknown.
            "max_hp_total": max_hp_total,
            # "parts": the tables give this boss no HP here, so it was worked out from the pool
            # of one of its parts, which is a known share of the HP
            "hp_from": "log" if source == "log" else hp_from,
            "damage": _num(ledger.total, digits),
            "dps": _num(ledger.total / duration, digits),
            "hits": ledger.hits,
            "max_hit": _num(ledger.max_hit, digits),
            "wave": [
                _num(ledger.wave.get(s, 0.0), digits) for s in range(first_second, last_second + 1)
            ],
            "boss": self._boss(enc, now, bar_hp.get(enc.bar_enemy) or bar_hp.get(0, 0) if bar_hp else 0),
            "players": players,
        }

    # -- output -------------------------------------------------------------------------------

    def _unmeasured_fight(self, now: float) -> str:
        """Name of the enemy being fought when a fight is under way that gives nothing to
        measure: skills are being used and enemies hit, but none of them reports HP."""
        if self._current is not None:
            return ""
        fighting = now - self._combat_at <= 6.0 and now - self._combat_since >= 3.0
        # hit reactions are logged only now and then, so one during this run of skills is enough
        if fighting and self._enemy_hit_at >= self._combat_since - 1.0 and self._unmeasured:
            enemy = self._spawns.enemy(self._unmeasured_entity)
            if enemy is not None and enemy.name:
                return enemy.name
            return self._roster.lookup(self._unmeasured)[0]
        return ""

    def snapshot(self, now: float) -> dict:
        with self._lock:
            enc = self._current or self._last
            status = dict(self.status)
            status["unmeasured"] = self._unmeasured_fight(now)
            listed = self._listed()
            ids = [fight["id"] for fight in listed]
            view = None
            if self._view in ids:
                place = ids.index(self._view)
                encounter = listed[place]
                # "running": a fight is being measured behind the one on show.
                # "session": the earlier session it belongs to, '' for this one.
                view = {
                    "id": self._view, "place": place + 1, "count": len(ids),
                    "running": self._current is not None, "session": self._opened_label,
                }
            else:
                self._view = None
                self._opened, self._opened_label = None, ""
                listed = list(self._history)
                encounter = self._describe(enc, now) if enc is not None else None
            return {
                "v": 1,
                "now": round(now, 3),
                "status": status,
                "encounter": encounter,
                "view": view,
                # the fights that can be picked: an opened session's, else this session's
                "history": [{key: fight.get(key) for key in _HISTORY_ROW} for fight in listed],
                "fights_this_session": len(self._history),
            }
