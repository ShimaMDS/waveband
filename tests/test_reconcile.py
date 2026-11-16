"""Logged HP only moves on hits; the HP bar also moves with damage over time."""

import unittest

from wwmeter.logparse import LogEvent
from wwmeter.roster import Roster
from wwmeter.tracker import Tracker

MAX_HP = 1_000_000


def switch(actor: str, ts: float) -> LogEvent:
    return LogEvent(
        ts=ts, tick=0, module="Battle", sub="", entity_id=0, kind="", actor="",
        text="RoleTeam PerformPossess", fields={"roleActor": f"{actor}_C_1"},
    )


def life(value: float, ts: float, entity: int = 7) -> LogEvent:
    return LogEvent(
        ts=ts, tick=0, module="CombatInfo", sub="Part", entity_id=entity, kind="Monster",
        actor="BP_MB1Boss00601", text="UpdatePartInfo",
        fields={"TagName": "怪物.common.弱点", "Activated": "True", "LifeValue": str(value)},
        instance=str(2147000000 + entity),
    )


def boss_line(ts: float, entity: int = 7, actor: str = "BP_MB1Boss00601") -> LogEvent:
    """Any combat line of a boss: it says that boss is about."""
    return LogEvent(
        ts=ts, tick=0, module="CombatInfo", sub="Buff", entity_id=entity, kind="Monster",
        actor=actor, text="本地添加buff", fields={"buffId": "1"}, instance=str(2147000000 + entity),
    )


class ReconcileTest(unittest.TestCase):
    def setUp(self):
        self.t = Tracker(Roster(characters="none.json", names="none.json"), timeout=8.0)
        self.t.on_log(switch("BP_Alpha", 99.0), 99.0)
        self.t.on_log(life(MAX_HP, 99.5), 99.5)  # full HP is logged before the first hit

    def run_fight(self, seconds: int, hit_per_second: float, bar_per_second: float, start: float = 100.0):
        """Hits remove ``hit_per_second`` of max HP; the bar falls by ``bar_per_second``."""
        for i in range(seconds * 10):
            now = start + i / 10
            elapsed = (i + 1) / 10
            if i % 10 == 0:
                hp = MAX_HP * (1.0 - hit_per_second * (i // 10 + 1))
                self.t.on_log(life(hp, now), now)
            self.t.on_boss(now, 1.0 - bar_per_second * elapsed)
            self.t.tick(now)

    def players(self, now: float) -> dict:
        return {p["name"]: p for p in self.t.snapshot(now)["encounter"]["players"]}

    def test_bar_and_log_agreeing_adds_nothing(self):
        self.run_fight(30, hit_per_second=0.005, bar_per_second=0.005)
        enc = self.t.snapshot(130.0)["encounter"]
        self.assertEqual([p["name"] for p in enc["players"]], ["Alpha"])
        self.assertEqual(enc["damage"], round(MAX_HP * 0.005 * 30))

    def test_damage_over_time_is_counted_from_the_bar(self):
        # hits take 0.5% a second, the bar falls 0.7% a second: 0.2% a second is not in the log
        self.run_fight(40, hit_per_second=0.005, bar_per_second=0.007)
        enc = self.t.snapshot(140.0)["encounter"]
        players = self.players(140.0)
        self.assertEqual(players["Alpha"]["damage"], round(MAX_HP * 0.005 * 40))
        true_other = MAX_HP * 0.002 * 40
        # short by the tolerance band and the moment the gap has to persist, never over
        self.assertLessEqual(players["Over time"]["damage"], true_other)
        self.assertGreaterEqual(players["Over time"]["damage"], true_other - MAX_HP * 0.016)
        self.assertEqual(enc["players"][-1]["name"], "Over time")  # listed last
        self.assertTrue(enc["players"][-1]["other"])
        self.assertEqual(enc["damage"], players["Alpha"]["damage"] + players["Over time"]["damage"])
        self.assertEqual(enc["max_hit"], round(MAX_HP * 0.005))  # not a hit, so not the biggest hit

    def test_bar_that_never_agreed_with_the_log_is_not_believed(self):
        # as if the bar were read at the wrong place on an untested resolution
        for i in range(300):
            now = 100.0 + i / 10
            if i % 10 == 0:
                self.t.on_log(life(MAX_HP * (1.0 - 0.005 * (i // 10 + 1)), now), now)
            self.t.on_boss(now, 0.60)
            self.t.tick(now)
        self.assertEqual(list(self.players(130.0)), ["Alpha"])

    def test_bar_switching_to_another_enemy_is_not_damage(self):
        self.run_fight(10, hit_per_second=0.005, bar_per_second=0.005)
        for i in range(100):  # the bar now shows a different, half-dead enemy
            now = 110.0 + i / 10
            if i % 10 == 0:
                self.t.on_log(boss_line(now, entity=8, actor="BP_MB1Other00101"), now)
            self.t.on_boss(now, 0.50)
            self.t.tick(now)
        self.assertEqual(list(self.players(120.0)), ["Alpha"])

    def quiet(self, start: float, seconds: float, bar) -> None:
        """No hits: the one boss goes on logging its own lines, and the bar reads ``bar(t)``."""
        for i in range(round(seconds * 10)):
            now = start + i / 10
            if i % 10 == 0:
                self.t.on_log(boss_line(now), now)
            self.t.on_boss(now, bar(now - start))
            self.t.tick(now)

    def test_a_lone_boss_s_big_ticks_are_damage(self):
        # Frazzle on a small boss, as fought on 2026-11-16: ten seconds of hits, then 21 s of
        # dodging while the bar falls 4% every three seconds and the log reports nothing.
        self.run_fight(10, hit_per_second=0.005, bar_per_second=0.005)
        self.quiet(110.0, 21.0, lambda t: 0.95 - 0.04 * (1 + int(t // 3)))
        players = self.players(131.0)
        self.assertEqual(players["Alpha"]["damage"], round(MAX_HP * 0.05))
        self.assertAlmostEqual(players["Over time"]["damage"], MAX_HP * (0.28 - 0.008), delta=MAX_HP * 0.001)
        boss = self.t.snapshot(131.0)["encounter"]["boss"]
        self.assertAlmostEqual(boss["life"], MAX_HP * (0.67 + 0.008), delta=MAX_HP * 0.001)

    def test_the_boss_of_the_scene_just_left_does_not_count_as_a_second_boss(self):
        # As fought on 2026-11-16: the hologram left and entered again at once. The boss of the
        # try before wrote its last line eight seconds before the first hit of this one, and a
        # tick of more than 3% of the bar in the next seven was taken for that boss's bar.
        self.t.on_log(boss_line(95.0, entity=6), 95.0)
        scene = LogEvent(
            ts=95.5, tick=0, module="World", sub="", entity_id=0, kind="", actor="",
            text="[CreatureController.JoinSceneNotify] Begin", fields={"InstanceId": "3927"},
        )
        self.t.on_log(scene, 95.5)
        self.run_fight(4, hit_per_second=0.005, bar_per_second=0.005)
        self.quiet(104.0, 12.0, lambda t: 0.98 - 0.04 * (1 + int(t // 3)))
        self.assertAlmostEqual(
            self.players(116.0)["Over time"]["damage"], MAX_HP * (0.16 - 0.008), delta=MAX_HP * 0.001
        )

    def kill(self, ts: float) -> None:
        dead = LogEvent(
            ts=ts, tick=0, module="AI", sub="", entity_id=0, kind="", actor="", text="RemoveHatredItem",
            fields={"Actor": "BP_MB1Boss00601_C_2147000007", "entityId": "0", "reason": "Dead"},
        )
        self.t.on_log(dead, ts)

    def test_what_the_log_still_showed_at_a_kill_is_over_time_not_the_blow(self):
        # As fought on 2026-11-16: hits down to 50%, ticks take the bar to 30% with no log line,
        # then the boss dies. The game writes the death first and the blow's own HP line after
        # it: a blow of 4%, which leaves 46% that no line ever reported.
        self.run_fight(10, hit_per_second=0.05, bar_per_second=0.05)
        self.quiet(110.0, 6.0, lambda t: 0.30)
        self.kill(116.0)
        self.t.on_log(life(MAX_HP * 0.46, 116.0), 116.0)
        enc = self.t.snapshot(116.1)["encounter"]
        players = self.players(116.1)
        self.assertEqual(enc["damage"], MAX_HP)
        self.assertEqual(players["Alpha"]["damage"], round(MAX_HP * 0.54))
        self.assertEqual(players["Over time"]["damage"], round(MAX_HP * 0.46))
        self.assertEqual(enc["max_hit"], round(MAX_HP * 0.05))  # the kill is not one huge hit
        self.assertEqual(enc["boss"]["life"], 0)

    def test_a_burst_of_hits_before_a_kill_does_not_take_the_ticks_back(self):
        # As fought on 2026-11-16: ticks take 14% of the bar with no log line, then four hits in
        # 0.3 s that the bar shows 0.4 s after the log has them, and a blow bigger than all the
        # HP still logged, so that its line reads nothing left. The meter gave "Over time" 453
        # of the 20,400 it had counted.
        self.run_fight(10, hit_per_second=0.05, bar_per_second=0.05)
        self.quiet(110.0, 6.0, lambda t: 0.36)
        for i in range(8):
            now = 116.0 + i / 10
            if i < 4:
                self.t.on_log(life(MAX_HP * (0.47 - 0.03 * i), now), now)
            self.t.on_boss(now, 0.36 - 0.03 * max(0, i - 3))
            self.t.tick(now)
        self.kill(116.8)
        self.t.on_log(life(0.0, 116.8), 116.8)
        players = self.players(116.9)
        self.assertEqual(self.t.snapshot(116.9)["encounter"]["damage"], MAX_HP)
        self.assertAlmostEqual(players["Over time"]["damage"], MAX_HP * (0.14 - 0.008), delta=MAX_HP * 0.001)
        self.assertAlmostEqual(players["Alpha"]["damage"], MAX_HP * (0.86 + 0.008), delta=MAX_HP * 0.001)

    def test_a_kill_whose_blow_the_log_never_reports_goes_to_who_was_on_field(self):
        # the blow landed in a cutscene: no line follows the death, so what was left is the blow
        self.run_fight(10, hit_per_second=0.05, bar_per_second=0.05)
        self.quiet(110.0, 6.0, lambda t: 0.30)
        self.kill(116.0)
        self.t.on_log(life(MAX_HP * 0.46, 117.0), 117.0)  # too late to be that blow
        players = self.players(117.1)
        self.assertEqual(players["Alpha"]["damage"], round(MAX_HP * (0.50 + 0.30 + 0.008)))
        self.assertEqual(players["Over time"]["damage"], round(MAX_HP * (0.20 - 0.008)))
        self.assertEqual(self.t.snapshot(117.1)["encounter"]["damage"], MAX_HP)

    def test_a_lone_boss_s_bar_misread_for_a_second_is_not_damage(self):
        self.run_fight(10, hit_per_second=0.005, bar_per_second=0.005)
        self.quiet(110.0, 1.5, lambda t: 0.50)
        self.quiet(111.5, 5.0, lambda t: 0.95)
        self.assertEqual(list(self.players(116.5)), ["Alpha"])

    def test_a_big_hit_the_log_reports_late_is_not_counted_twice(self):
        self.run_fight(10, hit_per_second=0.005, bar_per_second=0.005)
        self.quiet(110.0, 0.8, lambda t: 0.65)  # the bar shows the hit first
        self.t.on_log(life(MAX_HP * 0.65, 110.8), 110.8)
        self.quiet(110.8, 5.0, lambda t: 0.65)
        players = self.players(115.8)
        self.assertEqual(list(players), ["Alpha"])
        self.assertEqual(players["Alpha"]["damage"], round(MAX_HP * 0.35))

    def test_a_brief_low_reading_is_not_damage(self):
        self.run_fight(10, hit_per_second=0.005, bar_per_second=0.005)
        for i in range(4):  # a few frames of misreads while the bar is drawn shattered
            self.t.on_boss(110.0 + i / 10, 0.90)
        for i in range(30):  # then the bar is back where the log says it should be
            self.t.on_boss(110.4 + i / 10, 0.95)
        self.assertEqual(list(self.players(113.5)), ["Alpha"])

    def test_bar_level_survives_a_hidden_hud_so_cutscene_damage_is_counted(self):
        tracker = Tracker(Roster(characters="none.json", names="none.json"), timeout=8.0)
        tracker.on_log(switch("BP_Alpha", 99.0), 99.0)
        skill = LogEvent(
            ts=0, tick=0, module="CombatInfo", sub="Skill", entity_id=1, kind="Player",
            actor="BP_Alpha", text="BaseSkillComponent.BeginSkillAsync", fields={"技能名": "大招"},
        )
        for i in range(30):  # bar only: this enemy logs nothing
            now = 100.0 + i / 10
            tracker.on_boss(now, 1.0 - 0.01 * (i // 10))
            tracker.tick(now)
        for i in range(12):  # twelve seconds of ult cutscenes: no HUD, skills in the log
            now = 103.0 + i
            tracker.on_log(skill, now)
            tracker.tick(now)
        for i in range(20):  # the bar is back, 30% lower
            now = 115.0 + i / 10
            tracker.on_boss(now, 0.68)
            tracker.tick(now)
        snap = tracker.snapshot(117.0)
        self.assertEqual(snap["history"], [])  # still the same fight
        self.assertEqual(snap["encounter"]["source"], "bar")
        self.assertAlmostEqual(snap["encounter"]["damage"], 32.0, places=1)

    def test_a_logged_part_pool_that_empties_faster_than_the_bar_is_not_taken_for_hp(self):
        # the weak point has 1,000,000 of its own and is gone in 10 s; the bar barely moves
        for i in range(100):
            now = 100.0 + i / 10
            if i % 10 == 0:
                self.t.on_log(life(MAX_HP * (1.0 - 0.09 * (i // 10 + 1)), now), now)
            self.t.on_boss(now, 1.0 - 0.002 * (i / 10))
            self.t.tick(now)
        enc = self.t.snapshot(110.0)["encounter"]
        self.assertEqual((enc["source"], enc["unit"]), ("bar", "percent"))
        self.assertAlmostEqual(enc["damage"], 2.0, delta=0.4)

    def test_a_kill_seen_only_on_the_bar_counts_the_rest_of_the_bar(self):
        tracker = Tracker(Roster(characters="none.json", names="none.json"), timeout=8.0)
        tracker.on_log(switch("BP_Alpha", 99.0), 99.0)
        for i in range(40):  # bar only, down to 31%
            now = 100.0 + i / 10
            tracker.on_boss(now, max(0.31, 1.0 - 0.02 * i))
            tracker.tick(now)
        dead = LogEvent(
            ts=104.5, tick=0, module="AI", sub="", entity_id=0, kind="", actor="", text="RemoveHatredItem",
            fields={"Actor": "BP_ML1WuMingTanSuoZheMd00401_C_2146928713", "entityId": "0", "reason": "Dead"},
        )
        over = LogEvent(ts=104.5, tick=0, module="Battle", sub="", entity_id=0, kind="", actor="",
                        text="NotifyInFight: False", fields={})
        tracker.on_log(over, 104.5)
        tracker.on_log(dead, 104.5)
        tracker.tick(106.0)
        enc = tracker.snapshot(106.0)["encounter"]
        self.assertFalse(enc["live"])
        self.assertAlmostEqual(enc["damage"], 100.0, delta=0.5)
        self.assertEqual(enc["boss"]["hp"], 0.0)

    def test_a_second_phase_bar_carries_on_the_same_fight(self):
        tracker = Tracker(Roster(characters="none.json", names="none.json"), timeout=8.0)
        tracker.on_log(switch("BP_Alpha", 99.0), 99.0)
        now = 100.0
        for i in range(60):  # phase one: down to 3%, held a second, then gone behind the transition
            tracker.on_boss(now, max(0.03, 1.0 - 0.02 * i))
            tracker.tick(now)
            now += 0.1
        now += 3.0
        for i in range(60):  # phase two: a full bar, then 10% off it
            tracker.on_boss(now, 1.0 if i < 30 else 0.90)
            tracker.tick(now)
            now += 0.1
        snap = tracker.snapshot(now)
        self.assertEqual(snap["history"], [])
        self.assertAlmostEqual(snap["encounter"]["damage"], 110.0, delta=0.5)  # one bar and a tenth

    def test_when_the_log_catches_up_nothing_is_counted_twice(self):
        # the bar empties a second before the log reports the last hits (as at a kill)
        self.run_fight(10, hit_per_second=0.005, bar_per_second=0.005)
        for i in range(15):
            self.t.on_boss(110.0 + i / 10, 0.925)  # bar already 2.5% lower than the log says
        mid = self.players(111.5)
        self.assertGreater(mid["Over time"]["damage"], 0)
        self.t.on_log(life(MAX_HP * 0.925, 111.5), 111.5)  # the log reports those hits
        for i in range(15):  # and the bar falls no further: it had shown them already
            self.t.on_boss(111.6 + i / 10, 0.925)
        enc = self.t.snapshot(113.1)["encounter"]
        self.assertEqual([p["name"] for p in enc["players"]], ["Alpha"])
        self.assertEqual(enc["damage"], round(MAX_HP * 0.075))

    def test_a_kill_never_adds_up_to_more_than_the_enemys_hp(self):
        self.run_fight(10, hit_per_second=0.05, bar_per_second=0.05)  # down to 50%
        for i in range(15):
            self.t.on_boss(110.0 + i / 10, 0.0)  # the bar empties first
        dead = LogEvent(
            ts=111.5, tick=0, module="AI", sub="", entity_id=0, kind="", actor="", text="RemoveHatredItem",
            fields={"Actor": "BP_MB1Boss00601_C_2147000007", "entityId": "0", "reason": "Dead"},
        )
        self.t.on_log(dead, 111.5)
        enc = self.t.snapshot(111.6)["encounter"]
        self.assertEqual(enc["damage"], MAX_HP)

    def test_hp_left_follows_the_bar_once_reconciled(self):
        self.run_fight(40, hit_per_second=0.005, bar_per_second=0.007)
        boss = self.t.snapshot(140.0)["encounter"]["boss"]
        self.assertEqual(boss["max_hp"], MAX_HP)
        self.assertAlmostEqual(boss["life"] / MAX_HP, boss["hp"], delta=0.015)


if __name__ == "__main__":
    unittest.main()
