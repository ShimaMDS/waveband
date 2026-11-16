import os
import tempfile
import unittest

from enemy_fixture import enemy_data

from wwmeter.logparse import LogEvent
from wwmeter.roster import Roster, tidy
from wwmeter.tracker import Tracker

BOSS = "BP_MB1Wuguanzhe00601"


def switch(actor: str, ts: float) -> LogEvent:
    return LogEvent(
        ts=ts, tick=0, module="Battle", sub="", entity_id=0, kind="", actor="",
        text="RoleTeam PerformPossess", fields={"roleActor": f"{actor}_C_2147326125", "valid": ": True"},
    )


def skill(actor: str, name: str, ts: float) -> LogEvent:
    return LogEvent(
        ts=ts, tick=0, module="CombatInfo", sub="Skill", entity_id=1, kind="Player", actor=actor,
        text="BaseSkillComponent.BeginSkillAsync", fields={"技能名": name},
    )


def life(value: float, ts: float, entity: int = 13974, actor: str = BOSS, tag: str = "怪物.common.弱点") -> LogEvent:
    return LogEvent(
        ts=ts, tick=0, module="CombatInfo", sub="Part", entity_id=entity, kind="Monster", actor=actor,
        text="UpdatePartInfo", fields={"TagName": tag, "Activated": "True", "LifeValue": str(value)},
        instance=str(2147000000 + entity),
    )


def in_fight(flag: bool, ts: float) -> LogEvent:
    return LogEvent(ts=ts, tick=0, module="Battle", sub="", entity_id=0, kind="", actor="",
                    text=f"NotifyInFight: {flag}", fields={})


def died(ts: float, entity: int = 13974, actor: str = BOSS) -> LogEvent:
    return LogEvent(
        ts=ts, tick=0, module="AI", sub="", entity_id=0, kind="", actor="", text="RemoveHatredItem",
        fields={"Actor": f"{actor}_C_{2147000000 + entity}", "entityId": "0", "reason": "Dead"},
    )


class LogDamageTest(unittest.TestCase):
    def setUp(self):
        self.t = Tracker(Roster(characters="does-not-exist.json", names="does-not-exist.json"), timeout=8.0)

    def feed(self, *events):
        for event in events:
            self.t.on_log(event, event.ts)

    def test_idle_snapshot(self):
        snap = self.t.snapshot(100.0)
        self.assertIsNone(snap["encounter"])
        self.assertEqual(snap["history"], [])

    def test_hp_drops_are_damage_credited_to_whoever_is_on_field(self):
        self.feed(
            switch("BP_Alpha", 99.0),
            life(10_000, 100.0),  # first sighting: nothing to compare with
            life(9_000, 100.5),
            life(6_000, 101.0),
            switch("BP_Beta", 101.5),
            life(0, 102.5),
        )
        enc = self.t.snapshot(102.5)["encounter"]
        self.assertTrue(enc["live"])
        self.assertEqual((enc["source"], enc["unit"]), ("log", "damage"))
        self.assertEqual((enc["damage"], enc["hits"], enc["max_hit"]), (10_000, 3, 6_000))
        self.assertEqual(enc["dps"], 5000)  # 10,000 over the 2 s from the first drop to the last
        by_name = {p["name"]: p for p in enc["players"]}
        self.assertEqual(by_name["Alpha"]["damage"], 4_000)
        self.assertEqual(by_name["Beta"]["damage"], 6_000)
        self.assertEqual(by_name["Beta"]["share"], 0.6)
        self.assertTrue(by_name["Beta"]["on_field"])
        self.assertFalse(by_name["Alpha"]["on_field"])
        self.assertEqual(enc["title"], "Wuguanzhe")
        self.assertEqual(enc["boss"]["life"], 0)

    def test_hp_going_up_is_not_damage(self):
        self.feed(life(5_000, 100.0), life(4_000, 101.0), life(9_000, 102.0), life(8_500, 103.0))
        self.assertEqual(self.t.snapshot(104.0)["encounter"]["damage"], 1_500)

    def test_each_enemy_is_tracked_separately(self):
        self.feed(
            life(5_000, 100.0, entity=1, actor="BP_ME1WolfMd00601"),
            life(900, 100.1, entity=2, actor="BP_MO1RatMd00201"),
            life(4_000, 101.0, entity=1, actor="BP_ME1WolfMd00601"),
            life(600, 101.1, entity=2, actor="BP_MO1RatMd00201"),
        )
        enc = self.t.snapshot(102.0)["encounter"]
        self.assertEqual(enc["damage"], 1_300)
        self.assertEqual(enc["title"], "Wolf")  # the enemy that took the most

    def test_only_one_part_per_enemy_is_followed(self):
        self.feed(
            life(5_000, 100.0, tag="怪物.common.弱点"),
            life(5_000, 100.0, tag="怪物.common.背部弱点"),
            life(4_000, 101.0, tag="怪物.common.弱点"),
            life(4_000, 101.0, tag="怪物.common.背部弱点"),
        )
        self.assertEqual(self.t.snapshot(102.0)["encounter"]["damage"], 1_000)

    def test_time_on_field_adds_up_to_the_fights_length(self):
        self.feed(
            switch("BP_Alpha", 99.0),
            life(10_000, 100.0),
            life(9_000, 100.5),  # the fight starts here
            life(6_000, 101.0),
            switch("BP_Beta", 101.5),
            life(0, 102.5),
        )
        enc = self.t.snapshot(102.5)["encounter"]
        by_name = {p["name"]: p for p in enc["players"]}
        self.assertEqual((by_name["Alpha"]["field_time"], by_name["Beta"]["field_time"]), (1.0, 1.0))
        self.assertEqual(sum(p["field_time"] for p in enc["players"]), enc["duration"])
        # damage per second of that time: Alpha's 4,000 and Beta's 6,000 in a second each
        self.assertEqual((by_name["Alpha"]["field_dps"], by_name["Beta"]["field_dps"]), (4_000, 6_000))

    def test_time_on_field_of_a_finished_fight_ends_with_its_last_hit(self):
        self.feed(
            switch("BP_Alpha", 99.0), life(900, 100.0), life(800, 100.5), life(700, 101.5),
            switch("BP_Beta", 102.0), life(600, 103.0), life(500, 104.5),
            switch("BP_Alpha", 107.0),  # after the last hit: no part of the fight
        )
        self.t.tick(120.0)
        fight = self.t.snapshot(120.0)["encounter"]
        self.assertFalse(fight["live"])
        times = {p["name"]: p["field_time"] for p in fight["players"]}
        self.assertEqual(times, {"Alpha": 1.5, "Beta": 2.5})
        self.assertEqual(sum(times.values()), fight["duration"])

    def test_a_character_on_field_that_dealt_nothing_has_a_row(self):
        self.feed(
            switch("BP_Alpha", 99.0), life(900, 100.0), life(800, 100.5),
            switch("BP_Beta", 101.0), switch("BP_Alpha", 103.0), life(700, 104.5),
        )
        enc = self.t.snapshot(104.5)["encounter"]
        rows = [(p["name"], p["damage"], p["field_time"], p["field_dps"]) for p in enc["players"]]
        self.assertEqual(rows, [("Alpha", 200, 2.0, 100), ("Beta", 0, 2.0, 0)])

    def test_a_character_first_seen_acting_was_on_field_from_the_start(self):
        # nobody is known on field until Solo uses a skill: Solo was there all along
        self.feed(life(500, 100.0), life(400, 101.0), skill("BP_Solo", "slash", 101.5), life(300, 103.0))
        enc = self.t.snapshot(103.0)["encounter"]
        times = {p["name"]: p["field_time"] for p in enc["players"]}
        self.assertEqual(times, {"Unattributed": 0.0, "Solo": 2.0})

    def test_with_nobody_known_on_field_the_time_is_unattributed(self):
        self.feed(life(500, 100.0), life(400, 101.0), life(300, 103.0))
        player = self.t.snapshot(103.0)["encounter"]["players"][0]
        self.assertEqual((player["name"], player["field_time"]), ("Unattributed", 2.0))

    def test_under_a_second_on_field_gives_no_rate_for_it(self):
        self.feed(
            switch("BP_Alpha", 99.0), life(900, 100.0), life(800, 100.5),
            switch("BP_Beta", 102.0), life(700, 102.5),
        )
        by_name = {p["name"]: p for p in self.t.snapshot(102.5)["encounter"]["players"]}
        self.assertEqual((by_name["Beta"]["field_time"], by_name["Beta"]["field_dps"]), (0.5, None))

    def test_without_a_switch_event_the_acting_character_is_assumed_on_field(self):
        self.feed(skill("BP_Solo", "slash", 99.0), life(500, 100.0), life(400, 101.0))
        enc = self.t.snapshot(102.0)["encounter"]
        self.assertEqual(enc["players"][0]["name"], "Solo")

    def test_damage_with_nobody_known_on_field_is_unattributed(self):
        self.feed(life(500, 100.0), life(400, 101.0))
        self.assertEqual(self.t.snapshot(102.0)["encounter"]["players"][0]["name"], "Unattributed")

    def test_skills_are_counted_per_character_and_dodges_left_out(self):
        self.feed(
            switch("BP_Alpha", 99.0), life(900, 100.0), life(800, 100.5),
            skill("BP_Alpha", "E技能", 101.0), skill("BP_Alpha", "E技能", 102.0),
            skill("BP_Alpha", "前闪", 102.5), life(700, 103.0),
        )
        player = self.t.snapshot(104.0)["encounter"]["players"][0]
        self.assertEqual(player["skills"], [{"name": "E技能", "casts": 2}])

    def test_wave_has_one_sample_per_second(self):
        self.feed(life(1_000, 99.0), life(900, 100.0), life(700, 100.9), life(650, 103.1))
        self.assertEqual(self.t.snapshot(103.5)["encounter"]["wave"], [300, 0, 0, 50])

    def test_fight_closes_after_the_timeout_and_duration_stops_at_the_last_hit(self):
        self.feed(*[life(10_000 - 1_000 * i, 99.0 + i) for i in range(6)])  # drops at 100..104
        self.t.tick(108.0)  # 4 s quiet
        self.assertTrue(self.t.snapshot(108.0)["encounter"]["live"])
        self.t.tick(112.5)  # 8.5 s quiet
        snap = self.t.snapshot(200.0)
        self.assertFalse(snap["encounter"]["live"])
        self.assertEqual(snap["encounter"]["duration"], 4.0)
        self.assertEqual(snap["encounter"]["dps"], 1250)
        self.assertEqual([h["damage"] for h in snap["history"]], [5_000])

    def test_a_stray_hit_is_not_kept_as_a_fight(self):
        self.feed(life(1_000, 99.0), life(900, 100.0))
        self.t.tick(120.0)
        snap = self.t.snapshot(121.0)
        self.assertIsNone(snap["encounter"])
        self.assertEqual(snap["history"], [])

    def test_next_hit_after_a_closed_fight_starts_a_new_one(self):
        self.feed(*[life(10_000 - 1_000 * i, 99.0 + i) for i in range(4)])
        self.t.tick(120.0)
        self.feed(life(6_923, 130.0))
        snap = self.t.snapshot(130.5)
        self.assertTrue(snap["encounter"]["live"])
        self.assertEqual(snap["encounter"]["damage"], 77)
        self.assertNotEqual(snap["encounter"]["id"], snap["history"][0]["id"])

    def test_restarting_the_fight_closes_the_old_attempt(self):
        self.feed(switch("BP_Alpha", 99.0), life(10_000, 99.5))
        self.feed(*[life(10_000 - 1_000 * i, 100.0 + i) for i in range(1, 5)])
        # same boss, new copy at full HP after the reload, old one left alive: a restart
        self.feed(life(10_000, 109.0, entity=20001), life(9_500, 110.0, entity=20001))
        snap = self.t.snapshot(110.5)
        self.assertEqual([h["damage"] for h in snap["history"]], [4_000])
        self.assertTrue(snap["encounter"]["live"])
        self.assertEqual(snap["encounter"]["damage"], 500)
        self.assertEqual(snap["encounter"]["boss"]["max_hp"], 10_000)

    def test_a_different_enemy_joining_does_not_end_the_fight(self):
        self.feed(life(10_000, 99.5), life(9_000, 100.0), life(8_000, 101.0))
        self.feed(life(500, 101.5, entity=5, actor="BP_MO1RatMd00201"), life(300, 102.0, entity=5, actor="BP_MO1RatMd00201"))
        snap = self.t.snapshot(102.5)
        self.assertEqual(snap["history"], [])
        self.assertEqual(snap["encounter"]["damage"], 2_200)

    def test_numbers_are_shown_when_they_add_up_to_more_than_the_log(self):
        # an elite that logs HP, fought alongside enemies that do not
        self.feed(switch("BP_Alpha", 99.0), life(10_000, 99.5), life(9_000, 100.0), life(8_000, 101.0))
        for i in range(10):
            self.t.on_damage(100.0 + i / 5, 700)
        enc = self.t.snapshot(102.5)["encounter"]
        self.assertEqual((enc["source"], enc["damage"]), ("numbers", 7_000))
        self.assertEqual(enc["players"][0]["name"], "Alpha")

    def test_log_is_kept_when_numbers_read_less_or_about_the_same(self):
        self.feed(switch("BP_Alpha", 99.0), life(10_000, 99.5), life(9_000, 100.0), life(8_000, 101.0))
        for value in (900, 600, 700):  # 2,200 read against 2,000 logged: within the margin
            self.t.on_damage(100.5, value)
        enc = self.t.snapshot(102.0)["encounter"]
        self.assertEqual((enc["source"], enc["damage"]), ("log", 2_000))

    def test_numbers_are_only_wanted_while_fighting(self):
        self.assertFalse(self.t.wants_numbers(100.0))
        self.feed(skill("BP_Alpha", "E技能", 100.0))
        self.assertTrue(self.t.wants_numbers(105.0))
        self.assertFalse(self.t.wants_numbers(115.0))

    def test_figures_hold_after_the_last_hit_instead_of_sinking(self):
        self.feed(life(10_000, 99.0), *[life(10_000 - 1_000 * i, 99.0 + i) for i in range(1, 6)])
        # last hit at 104.0, first at 100.0: 5,000 damage
        during = self.t.snapshot(104.0)["encounter"]
        just_after = self.t.snapshot(104.6)["encounter"]
        later = self.t.snapshot(109.0)["encounter"]  # still live: the timeout has not passed
        self.assertTrue(later["live"])
        self.assertEqual(during["dps"], 1250)
        self.assertLess(just_after["dps"], during["dps"])  # the clock runs on for a second
        self.assertEqual((later["duration"], later["dps"]), (5.0, 1000))
        self.assertEqual(self.t.snapshot(111.9)["encounter"]["dps"], 1000)  # and then holds
        # the fight goes on: the pause counts
        self.feed(life(4_000, 110.0))
        resumed = self.t.snapshot(110.0)["encounter"]
        self.assertEqual((resumed["duration"], resumed["damage"]), (10.0, 6_000))

    def test_a_fight_with_enemies_that_report_no_hp_is_named_as_such(self):
        hit = LogEvent(
            ts=101.0, tick=0, module="CombatInfo", sub="Hit", entity_id=77, kind="Monster",
            actor="BP_ME1AnMaoziRenMd00601", text="受击", fields={"BeHitAnim": "重右"},
        )
        self.assertEqual(self.t.snapshot(100.0)["status"]["unmeasured"], "")
        for i in range(6):
            self.feed(skill("BP_Alpha", "E技能", 100.0 + i))
        self.t.on_log(hit, 103.0)
        self.assertEqual(self.t.snapshot(105.5)["status"]["unmeasured"], "An Maozi Ren")
        self.assertIsNone(self.t.snapshot(105.5)["encounter"])
        self.assertEqual(self.t.snapshot(120.0)["status"]["unmeasured"], "")  # fight over

    def test_a_boss_fought_off_its_bar_is_not_named_as_unmeasured_once_the_fight_is_over(self):
        # Seen live on 2026-11-15: for a few seconds after an Inferno Rider fight the meter read
        # "ML1Qi Shi ... doesn't report its HP", then went back to the fight's result.
        def boss_hit(ts: float) -> LogEvent:
            return LogEvent(
                ts=ts, tick=0, module="CombatInfo", sub="Hit", entity_id=15036, kind="Monster",
                actor="BP_ML1QiShiMd00001", text="受击", fields={"BeHitAnim": "重右"},
            )

        for start, fraction in ((100.0, 1.00), (102.0, 0.80), (104.0, 0.60), (106.0, 0.40)):
            now = start
            while now < start + 2.0 - 1e-9:  # the bar on screen, ten readings a second
                self.t.on_boss(now, fraction)
                now += 0.1
            self.feed(skill("BP_Alpha", "E技能", start + 1.0))
        self.t.on_boss(108.0, 0.40)
        self.feed(boss_hit(108.0))  # the boss flinches, bar up: it is being measured
        self.feed(boss_hit(111.5))  # and again inside a cutscene, with the HUD hidden
        self.feed(in_fight(False, 112.0))
        self.t.tick(113.1)  # the fight is closed
        for ts in (113.5, 114.5, 115.5):  # the last skills are still running
            self.feed(skill("BP_Alpha", "E技能", ts))
        snap = self.t.snapshot(116.0)
        self.assertFalse(snap["encounter"]["live"])
        self.assertEqual(snap["status"]["unmeasured"], "")

    def test_a_measured_fight_is_not_called_unmeasured(self):
        self.feed(life(10_000, 99.5))
        for i in range(6):
            self.feed(skill("BP_Alpha", "E技能", 100.0 + i), life(9_000 - 500 * i, 100.2 + i))
        self.assertEqual(self.t.snapshot(105.5)["status"]["unmeasured"], "")

    def test_a_pack_of_one_enemy_type_is_one_fight(self):
        wolf = "BP_ME1BinlangMd00601"
        self.feed(life(5_000, 99.5, entity=1, actor=wolf), life(4_000, 100.0, entity=1, actor=wolf))
        self.feed(life(5_000, 100.5, entity=2, actor=wolf), life(4_500, 101.0, entity=2, actor=wolf))
        self.feed(life(0, 104.0, entity=1, actor=wolf))
        # second wave arrives after the first wolf died and a few quiet seconds
        self.feed(life(5_000, 109.0, entity=3, actor=wolf), life(4_000, 110.0, entity=3, actor=wolf))
        snap = self.t.snapshot(110.5)
        self.assertEqual(snap["history"], [])
        self.assertEqual(snap["encounter"]["damage"], 6_500)

    def test_using_skills_keeps_a_fight_open_through_long_cutscenes(self):
        self.feed(life(10_000, 99.0), *[life(10_000 - 1_000 * i, 99.0 + i) for i in range(1, 6)])
        for i in range(12):  # twelve seconds of ults with no damage line: last hit was at 104
            self.feed(skill("BP_Alpha", "大招", 105.0 + i))
            self.t.tick(105.0 + i)
        self.assertTrue(self.t.snapshot(116.0)["encounter"]["live"])
        self.t.tick(125.5)
        self.assertFalse(self.t.snapshot(125.5)["encounter"]["live"])

    def test_dodging_does_not_keep_a_fight_open(self):
        self.feed(life(10_000, 99.0), *[life(10_000 - 1_000 * i, 99.0 + i) for i in range(1, 6)])
        for i in range(12):
            self.feed(skill("BP_Alpha", "前闪", 105.0 + i))
            self.t.tick(105.0 + i)
        self.assertFalse(self.t.snapshot(116.0)["encounter"]["live"])

    def test_the_game_saying_combat_ended_closes_the_fight_at_once(self):
        self.feed(life(10_000, 99.0), *[life(10_000 - 1_000 * i, 99.0 + i) for i in range(1, 6)])
        self.feed(in_fight(False, 104.2))
        self.t.tick(104.5)
        self.assertTrue(self.t.snapshot(104.5)["encounter"]["live"])  # a moment for the last lines
        self.t.tick(105.3)
        snap = self.t.snapshot(105.3)
        self.assertFalse(snap["encounter"]["live"])
        self.assertEqual((snap["encounter"]["duration"], snap["encounter"]["damage"]), (4.0, 5_000))

    def test_combat_starting_again_cancels_the_pending_close(self):
        self.feed(life(10_000, 99.0), *[life(10_000 - 1_000 * i, 99.0 + i) for i in range(1, 6)])
        self.feed(in_fight(False, 104.2), in_fight(True, 104.6))
        self.t.tick(106.0)
        self.assertTrue(self.t.snapshot(106.0)["encounter"]["live"])

    def test_a_kill_credits_the_hp_the_log_never_saw_drop(self):
        # the killing blow landed in a cutscene: the last logged HP is 4,000, then the boss dies
        self.feed(switch("BP_Alpha", 98.0), life(10_000, 99.0), life(7_000, 100.0), life(4_000, 101.0))
        self.feed(in_fight(False, 103.0), died(103.0))
        self.t.tick(104.5)
        enc = self.t.snapshot(104.5)["encounter"]
        self.assertFalse(enc["live"])
        self.assertEqual(enc["damage"], 10_000)
        self.assertEqual(enc["boss"]["life"], 0)

    def test_the_killing_blow_s_line_after_the_death_is_not_counted_again(self):
        # the game writes the death first and the blow's HP line just after it
        self.feed(switch("BP_Alpha", 98.0), life(10_000, 99.0), life(7_000, 100.0), life(4_000, 101.0))
        self.feed(died(103.0), life(1_000, 103.0))
        enc = self.t.snapshot(103.1)["encounter"]
        self.assertEqual(enc["damage"], 10_000)
        self.assertEqual([p["name"] for p in enc["players"]], ["Alpha"])  # no bar to say otherwise

    def test_a_death_of_some_other_enemy_credits_nothing(self):
        self.feed(life(10_000, 99.0), life(7_000, 100.0), life(4_000, 101.0))
        self.feed(died(102.0, entity=555, actor="BP_MO1RatMd00201"))
        self.assertEqual(self.t.snapshot(102.5)["encounter"]["damage"], 6_000)

    def test_a_named_part_is_not_the_enemys_hp(self):
        wing = "怪物.ML1WuChangluMd00601.翅膀"
        self.feed(life(49_895, 99.0, tag=wing), life(30_000, 100.0, tag=wing), life(0, 101.0, tag=wing))
        self.assertIsNone(self.t.snapshot(101.5)["encounter"])

    def test_full_hp_of_the_enemies_fought_is_reported_for_percent_display(self):
        wolf = "BP_ME1BinlangMd00601"
        self.feed(life(5_000, 99.5, entity=1, actor=wolf), life(4_000, 100.0, entity=1, actor=wolf))
        self.feed(life(3_000, 100.5, entity=2, actor=wolf), life(2_500, 101.0, entity=2, actor=wolf))
        self.feed(life(9_999, 101.5, entity=3, actor=wolf))  # seen but never damaged: not counted
        enc = self.t.snapshot(102.0)["encounter"]
        self.assertEqual((enc["damage"], enc["max_hp_total"]), (1_500, 8_000))

    def test_weak_points_with_different_values_are_not_the_enemys_hp(self):
        rider = "BP_ML1QiShiMd00601"
        self.feed(
            life(198_060, 99.0, entity=9, actor=rider, tag="怪物.common.弱点"),
            life(330_100, 99.0, entity=9, actor=rider, tag="怪物.common.背部弱点"),
            life(150_000, 100.0, entity=9, actor=rider, tag="怪物.common.弱点"),
            life(100_000, 101.0, entity=9, actor=rider, tag="怪物.common.弱点"),
        )
        self.assertIsNone(self.t.snapshot(101.5)["encounter"])

    def test_weak_points_with_the_same_value_are_one_hp_pool(self):
        elite = "BP_ME1AntankeMd00601"
        self.feed(
            life(135_067, 99.0, entity=9, actor=elite, tag="怪物.common.弱点"),
            life(135_067, 99.0, entity=9, actor=elite, tag="怪物.common.背部弱点"),
            life(130_000, 100.0, entity=9, actor=elite, tag="怪物.common.弱点"),
            life(130_000, 100.0, entity=9, actor=elite, tag="怪物.common.背部弱点"),
        )
        self.assertEqual(self.t.snapshot(100.5)["encounter"]["damage"], 5_067)

    def test_reset(self):
        self.feed(*[life(10_000 - 1_000 * i, 99.0 + i) for i in range(4)])
        self.t.reset()
        self.assertIsNone(self.t.snapshot(103.0)["encounter"])


class EarlierFightsTest(unittest.TestCase):
    """Finished fights are kept, in full and across a restart, and can be put back on show."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = os.path.join(folder.name, "history.json")
        self.t = self.tracker()

    def tracker(self) -> Tracker:
        roster = Roster(characters="does-not-exist.json", names="does-not-exist.json")
        return Tracker(roster, timeout=8.0, history_path=self.path)

    def fight(self, tracker: Tracker, start: float, entity: int, hit: int = 1_000) -> None:
        """Four hits of ``hit`` on a fresh enemy, then long enough for the fight to close."""
        tracker.on_log(switch("BP_Alpha", start), start)
        for i in range(5):
            tracker.on_log(life(10_000 - hit * i, start + i, entity=entity), start + i)
        tracker.tick(start + 20.0)

    def test_a_finished_fight_is_kept_in_full(self):
        self.fight(self.t, 100.0, entity=1)
        self.t.view_step(-1)  # nothing older than the one already on show
        snap = self.t.snapshot(130.0)
        self.assertIsNone(snap["view"])
        self.assertEqual(snap["history"][0]["damage"], 4_000)
        self.assertEqual(snap["history"][0]["ended_at"], 104.0)

    def test_the_file_holds_the_fights_in_full_and_can_be_read_back(self):
        self.fight(self.t, 100.0, entity=1)
        self.fight(self.t, 200.0, entity=2, hit=500)
        again = self.tracker()  # a second tracker given the same file
        snap = again.snapshot(1_000.0)
        self.assertIsNone(snap["encounter"])  # nothing on show until asked
        self.assertEqual([h["damage"] for h in snap["history"]], [2_000, 4_000])
        again.view_step(-1)
        shown = again.snapshot(1_000.0)
        self.assertEqual(shown["encounter"]["damage"], 2_000)
        self.assertEqual(shown["encounter"]["players"][0]["name"], "Alpha")
        self.assertFalse(shown["encounter"]["live"])
        # a fight after the restart does not reuse a kept fight's number
        self.fight(again, 2_000.0, entity=3)
        numbers = [h["id"] for h in again.snapshot(2_100.0)["history"]]
        self.assertEqual(len(set(numbers)), 3)

    def test_stepping_back_and_forward_through_fights(self):
        for n, start in enumerate((100.0, 200.0, 300.0), start=1):
            self.fight(self.t, start, entity=n, hit=n * 100)
        newest, middle, oldest = (h["id"] for h in self.t.snapshot(400.0)["history"])
        self.assertEqual(self.t.snapshot(400.0)["encounter"]["id"], newest)
        self.t.view_step(-1)
        snap = self.t.snapshot(400.0)
        self.assertEqual(snap["encounter"]["id"], middle)
        self.assertEqual(
            snap["view"], {"id": middle, "place": 2, "count": 3, "running": False, "session": ""}
        )
        self.t.view_step(-1)
        self.t.view_step(-1)  # already at the oldest: stays there
        self.assertEqual(self.t.snapshot(400.0)["encounter"]["id"], oldest)
        self.t.view_step(1)
        self.assertEqual(self.t.snapshot(400.0)["encounter"]["id"], middle)
        self.t.view_step(1)
        snap = self.t.snapshot(400.0)
        self.assertEqual((snap["encounter"]["id"], snap["view"]), (newest, None))

    def test_a_fight_goes_on_being_measured_behind_an_earlier_one(self):
        self.fight(self.t, 100.0, entity=1)
        self.fight(self.t, 200.0, entity=2, hit=500)
        self.t.view_step(-1)
        old = self.t.snapshot(250.0)["encounter"]["id"]
        for i in range(4):  # a new fight starts while the old one is on show
            self.t.on_log(life(10_000 - 700 * i, 300.0 + i, entity=3), 300.0 + i)
        snap = self.t.snapshot(303.5)
        self.assertEqual(snap["encounter"]["id"], old)  # still the one asked for
        self.assertTrue(snap["view"]["running"])
        self.t.view_step(1)
        self.t.view_step(1)
        snap = self.t.snapshot(303.5)
        self.assertIsNone(snap["view"])
        self.assertTrue(snap["encounter"]["live"])
        self.assertEqual(snap["encounter"]["damage"], 2_100)

    def test_a_new_fight_key_goes_back_to_the_running_fight(self):
        self.fight(self.t, 100.0, entity=1)
        self.fight(self.t, 200.0, entity=2)
        self.t.view_step(-1)
        self.t.reset()
        snap = self.t.snapshot(250.0)
        self.assertEqual((snap["view"], snap["encounter"]), (None, None))
        self.assertEqual(len(snap["history"]), 2)  # the list itself is kept

    def test_one_fight_can_be_picked_by_number(self):
        self.fight(self.t, 100.0, entity=1)
        self.fight(self.t, 200.0, entity=2)
        oldest = self.t.snapshot(250.0)["history"][-1]["id"]
        self.t.view(oldest)
        self.assertEqual(self.t.snapshot(250.0)["encounter"]["id"], oldest)
        self.t.view(999)  # no such fight
        self.assertIsNone(self.t.snapshot(250.0)["view"])

    # -- an earlier session opened for reading ---------------------------------------------

    def earlier_session(self) -> list[dict]:
        """Two fights of another launch, as its file holds them: newest first."""
        other = Tracker(Roster(characters="does-not-exist.json", names="does-not-exist.json"))
        self.fight(other, 10.0, entity=7, hit=300)
        self.fight(other, 50.0, entity=8, hit=900)
        return [dict(f) for f in other._history]

    def test_an_opened_session_is_read_in_place_of_this_sessions_list(self):
        self.fight(self.t, 100.0, entity=1)
        self.t.open_session(self.earlier_session(), "14 Nov 20:05")
        snap = self.t.snapshot(200.0)
        self.assertEqual([h["damage"] for h in snap["history"]], [3_600, 1_200])
        self.assertEqual(snap["encounter"]["damage"], 3_600)  # its newest fight to begin with
        self.assertEqual(snap["view"]["session"], "14 Nov 20:05")
        self.assertEqual((snap["view"]["place"], snap["view"]["count"]), (1, 2))
        self.assertEqual(snap["fights_this_session"], 1)
        self.t.view_step(-1)
        self.t.view_step(-1)  # stays at its oldest
        self.assertEqual(self.t.snapshot(200.0)["encounter"]["damage"], 1_200)

    def test_stepping_past_an_opened_sessions_newest_fight_returns_to_this_session(self):
        self.fight(self.t, 100.0, entity=1)
        self.t.open_session(self.earlier_session(), "14 Nov 20:05")
        self.t.view_step(1)
        snap = self.t.snapshot(200.0)
        self.assertIsNone(snap["view"])
        self.assertEqual([h["damage"] for h in snap["history"]], [4_000])  # this session's own
        self.assertEqual(snap["encounter"]["damage"], 4_000)

    def test_fights_fought_while_a_session_is_open_go_to_this_session_only(self):
        earlier = self.earlier_session()
        self.t.open_session(earlier, "14 Nov 20:05")
        self.fight(self.t, 300.0, entity=3, hit=700)
        snap = self.t.snapshot(400.0)
        self.assertEqual(snap["view"]["session"], "14 Nov 20:05")  # still the one being read
        self.assertEqual(len(snap["history"]), 2)
        self.assertEqual(snap["fights_this_session"], 1)
        self.assertEqual(len(self.tracker().snapshot(500.0)["history"]), 1)  # and one in the file
        self.t.open_session(None)
        self.assertEqual([h["damage"] for h in self.t.snapshot(400.0)["history"]], [2_800])

    def test_new_fight_and_a_missing_session_both_go_back_to_this_session(self):
        self.t.open_session(self.earlier_session(), "14 Nov 20:05")
        self.t.reset()
        self.assertIsNone(self.t.snapshot(200.0)["view"])
        self.t.open_session([], "")  # a file that could not be read
        self.assertIsNone(self.t.snapshot(200.0)["view"])

    def test_a_file_that_cannot_be_read_is_ignored(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        tracker = self.tracker()
        self.assertEqual(tracker.snapshot(100.0)["history"], [])
        self.fight(tracker, 100.0, entity=1)  # and is replaced by the next fight
        self.assertEqual(len(self.tracker().snapshot(200.0)["history"]), 1)

    def test_nothing_is_written_without_a_path(self):
        tracker = Tracker(Roster(characters="does-not-exist.json", names="does-not-exist.json"))
        self.fight(tracker, 100.0, entity=1)
        self.assertEqual(len(tracker.snapshot(200.0)["history"]), 1)
        self.assertFalse(os.path.exists(self.path))


class BossBarTest(unittest.TestCase):
    def setUp(self):
        self.t = Tracker(Roster(characters="does-not-exist.json", names="does-not-exist.json"), timeout=8.0)

    def bar(self, start: float, end: float, fraction: float, step: float = 0.1):
        now = start
        while now < end - 1e-9:
            self.t.on_boss(now, fraction)
            self.t.tick(now)
            now += step

    def test_bar_alone_reports_percent_of_hp(self):
        self.t.on_log(switch("BP_Alpha", 99.0), 99.0)
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.90)
        self.bar(104.0, 106.0, 0.75)
        self.bar(106.0, 108.0, 0.70)
        enc = self.t.snapshot(108.0)["encounter"]
        self.assertEqual((enc["source"], enc["unit"]), ("bar", "percent"))
        self.assertAlmostEqual(enc["damage"], 30.0, places=1)
        self.assertEqual(enc["players"][0]["name"], "Alpha")
        self.assertAlmostEqual(enc["boss"]["hp"], 0.70, places=3)

    def test_a_brief_misread_is_ignored(self):
        self.bar(100.0, 102.0, 0.90)
        self.bar(102.0, 102.3, 0.04)  # bar animating back in after a cutscene
        self.bar(102.3, 104.0, 0.90)
        self.assertIsNone(self.t.snapshot(104.0)["encounter"])

    def shares(self, now: float) -> dict[str, float]:
        # who was credited with what; a character on field that has dealt nothing has a row too
        enc = self.t.snapshot(now)["encounter"]
        return {p["name"]: round(p["damage"], 1) for p in enc["players"] if p["damage"]}

    def test_a_drop_goes_to_whoever_was_on_field_when_it_happened(self):
        # The bar is believed only once it has held for the settle window. A switch inside
        # that window must not hand the drop to the character who has just come on.
        self.t.on_log(switch("BP_Alpha", 99.0), 99.0)
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 102.3, 0.90)
        self.t.on_log(switch("BP_Beta", 102.3), 102.3)
        self.bar(102.3, 104.0, 0.90)
        self.assertEqual(self.shares(104.0), {"Alpha": 10.0})

    def test_a_drop_after_the_switch_goes_to_the_new_character(self):
        self.t.on_log(switch("BP_Alpha", 99.0), 99.0)
        self.bar(100.0, 102.0, 1.00)
        self.t.on_log(switch("BP_Beta", 102.0), 102.0)
        self.bar(102.0, 103.0, 1.00)
        self.bar(103.0, 105.0, 0.90)
        self.assertEqual(self.shares(105.0), {"Beta": 10.0})

    def test_a_drop_still_settling_when_the_bar_hides_is_not_left_for_the_next_character(self):
        # Alpha's last hits land just before an ultimate's cutscene hides the HUD, Beta comes
        # on during it, and the bar returns lower still.
        self.t.on_log(switch("BP_Alpha", 99.0), 99.0)
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 102.5, 0.95)
        self.t.on_log(switch("BP_Beta", 102.6), 102.6)
        for tenth in range(26, 50):
            self.t.tick(100.0 + tenth / 10)  # no bar on screen
        self.bar(105.0, 107.0, 0.90)
        self.assertEqual(self.shares(107.0), {"Alpha": 5.0, "Beta": 5.0})

    def test_one_long_reading_before_the_bar_hides_does_not_hold_a_drop_back(self):
        # a hit flashes white at the end of the bar, which reads a little long for a frame
        self.t.on_log(switch("BP_Alpha", 99.0), 99.0)
        self.bar(100.0, 102.0, 1.00)
        for now, fraction in ((102.0, 0.95), (102.1, 0.95), (102.2, 1.00), (102.3, 0.95), (102.4, 0.95)):
            self.t.on_boss(now, fraction)
        self.t.on_log(switch("BP_Beta", 102.6), 102.6)
        for tenth in range(26, 50):
            self.t.tick(100.0 + tenth / 10)
        self.bar(105.0, 107.0, 0.95)
        self.assertEqual(self.shares(107.0), {"Alpha": 5.0})

    def after_a_cutscene(self, fell_at: float) -> dict[str, float]:
        # Alpha's ultimate hides the HUD from 102 to 105, Beta is switched to a fifth of a
        # second after it is back, and the bar falls at the given moment.
        self.t.on_log(switch("BP_Alpha", 99.0), 99.0)
        self.bar(100.0, 102.0, 1.00)
        for tenth in range(20, 50):
            self.t.tick(100.0 + tenth / 10)  # no bar on screen
        self.bar(105.0, 105.2, 1.00)
        self.t.on_log(switch("BP_Beta", 105.2), 105.2)
        self.bar(105.2, fell_at, 1.00)
        self.bar(fell_at, fell_at + 2.0, 0.80)
        return self.shares(fell_at + 2.0)

    def test_what_the_bar_shows_just_after_a_cutscene_was_dealt_during_it(self):
        # Recorded: the bar comes back at its old level and only then slides down by what the
        # ultimate dealt, by when the next character is already on field.
        self.assertEqual(self.after_a_cutscene(105.5), {"Alpha": 20.0})

    def test_a_drop_a_second_after_the_cutscene_is_the_new_characters(self):
        self.assertEqual(self.after_a_cutscene(106.0), {"Beta": 20.0})

    def test_one_long_reading_after_a_drop_does_not_date_it_later(self):
        # The end of the bar flickers by a pixel. One reading back at the old level holds the
        # settled level up for a whole settle window; the drop still happened before it.
        self.t.on_log(switch("BP_Alpha", 99.0), 99.0)
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 102.2, 0.99)
        self.t.on_log(switch("BP_Beta", 102.25), 102.25)
        self.bar(102.3, 102.4, 0.99)
        self.bar(102.4, 102.5, 1.00)
        self.bar(102.5, 104.5, 0.99)
        self.assertEqual(self.shares(104.5), {"Alpha": 1.0})

    def test_a_drop_seen_in_the_first_frame_after_a_switch_is_the_old_characters(self):
        # the bar shows a hit a frame late at best, and nobody lands one the instant they come on
        self.t.on_log(switch("BP_Alpha", 99.0), 99.0)
        self.bar(100.0, 102.0, 1.00)
        self.t.on_log(switch("BP_Beta", 102.03), 102.03)
        self.bar(102.1, 104.0, 0.90)
        self.assertEqual(self.shares(104.0), {"Alpha": 10.0})

    def test_a_refilled_bar_is_a_new_target_not_negative_damage(self):
        self.bar(100.0, 102.0, 0.50)
        self.bar(102.0, 104.0, 0.40)
        self.bar(104.0, 108.0, 1.00)
        self.bar(108.0, 110.0, 0.95)
        enc = self.t.snapshot(110.0)["encounter"]
        self.assertAlmostEqual(enc["damage"], 15.0, places=1)

    def test_logged_hp_wins_over_the_bar_and_is_not_added_to_it(self):
        self.bar(100.0, 102.0, 1.00)
        self.t.on_log(life(10_000, 102.0), 102.0)
        self.t.on_log(life(8_000, 102.5), 102.5)
        self.bar(102.5, 105.0, 0.80)
        enc = self.t.snapshot(105.0)["encounter"]
        self.assertEqual((enc["source"], enc["damage"]), ("log", 2_000))
        self.assertAlmostEqual(enc["boss"]["hp"], 0.80, places=3)

    def test_boss_bar_keeps_a_quiet_fight_open_longer(self):
        for i in range(5):
            self.t.on_log(life(10_000 - 1_000 * i, 100.0 + i), 100.0 + i)
        self.bar(104.0, 125.0, 0.9, step=0.5)  # 21 s with the bar up and nobody hitting
        self.assertTrue(self.t.snapshot(125.0)["encounter"]["live"])
        self.bar(125.0, 140.0, 0.9, step=0.5)
        self.assertFalse(self.t.snapshot(140.0)["encounter"]["live"])

    def test_max_hp_estimate_from_logged_hp_and_bar(self):
        for i in range(12):
            now = 100.0 + i
            self.bar(now, now + 1.0, 1.0 - 0.01 * i)
            self.t.on_log(life(5_000_000 * (1.0 - 0.01 * i), now + 0.95), now + 0.95)
        boss = self.t.snapshot(112.0)["encounter"]["boss"]
        self.assertAlmostEqual(boss["max_hp"], 5_000_000, delta=5_000_000 * 0.02)


def joined(instance: int, ts: float) -> LogEvent:
    return LogEvent(ts=ts, tick=0, module="World", sub="", entity_id=0, kind="", actor="",
                    text="[CreatureController.JoinSceneNotify] Begin", fields={"InstanceId": str(instance)})


def spawned(entity: int, config_type: str, pb_data: int, ts: float, prefab: int = 0) -> LogEvent:
    return LogEvent(
        ts=ts, tick=0, module="Entity", sub="", entity_id=0, kind="", actor="", text="实体详细数据。",
        fields={"CreatureDataId": str(entity), "ConfigType": config_type, "EntityType": "Monster",
                "PbDataId": str(pb_data), "PrefabId": str(prefab)},
    )


def boss_line(ts: float, entity: int = 13974, actor: str = BOSS) -> LogEvent:
    """Any combat line about a boss: they come several a second while it fights."""
    return LogEvent(ts=ts, tick=0, module="CombatInfo", sub="Ai", entity_id=entity, kind="Monster",
                    actor=actor, text="行为树:设置Cd", fields={"id": "1"}, instance=str(2147000000 + entity))


class BossBarDamageTest(unittest.TestCase):
    """A boss that logs no HP, fought off its HP bar, with its full HP known from the game's
    tables. The fixture's figures are real: 1,024,088 is the hologram Crownless at level 80."""

    HP = 1_024_088

    def setUp(self):
        self.t = Tracker(
            Roster(characters="does-not-exist.json", names="does-not-exist.json"), timeout=8.0,
            enemies=enemy_data(),
        )

    def feed(self, *events):
        for event in events:
            self.t.on_log(event, event.ts)

    def bar(self, start: float, end: float, fraction: float, step: float = 0.1):
        now = start
        while now < end - 1e-9:
            self.t.on_boss(now, fraction)
            self.t.tick(now)
            now += step

    def hologram_fight(self):
        self.feed(joined(3927, 90.0), spawned(13974, "Level", 7, 91.0), switch("BP_Alpha", 99.0), boss_line(99.5))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.90)
        self.bar(104.0, 106.0, 0.75)
        self.bar(106.0, 108.0, 0.70)

    def test_the_bar_times_the_tables_hp_is_damage(self):
        self.hologram_fight()
        enc = self.t.snapshot(108.0)["encounter"]
        self.assertEqual((enc["source"], enc["unit"], enc["hp_from"]), ("bar", "damage", "tables"))
        self.assertAlmostEqual(enc["damage"], 0.30 * self.HP, delta=600)
        self.assertAlmostEqual(enc["players"][0]["damage"], 0.30 * self.HP, delta=600)
        self.assertEqual(enc["players"][0]["name"], "Alpha")
        self.assertEqual(enc["max_hp_total"], self.HP)  # lets the display go back to percent
        self.assertEqual(enc["max_hit"], 0)  # a drop of the bar is not one hit
        self.assertEqual(sum(enc["wave"]), enc["damage"])
        self.assertEqual(enc["boss"]["max_hp"], self.HP)
        self.assertAlmostEqual(enc["boss"]["life"], 0.70 * self.HP, delta=600)

    def test_the_finished_fight_is_listed_in_damage(self):
        self.hologram_fight()
        self.t.tick(200.0)
        entry = self.t.snapshot(200.0)["history"][0]
        self.assertEqual(entry["unit"], "damage")
        self.assertAlmostEqual(entry["damage"], 0.30 * self.HP, delta=600)

    def test_a_boss_whose_spawn_was_never_seen_stays_in_percent(self):
        self.feed(switch("BP_Alpha", 99.0), boss_line(99.5))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.90)
        enc = self.t.snapshot(104.0)["encounter"]
        self.assertEqual((enc["unit"], enc["hp_from"], enc["max_hp_total"]), ("percent", "", 0))
        self.assertAlmostEqual(enc["damage"], 10.0, places=1)

    def test_a_boss_with_an_extra_rate_stays_in_percent(self):
        self.feed(joined(20019, 90.0), spawned(13974, "Prefab", 2, 91.0, prefab=401), boss_line(99.5))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.90)
        self.assertEqual(self.t.snapshot(104.0)["encounter"]["unit"], "percent")

    WING = "怪物.boss.翅膀"  # a part with a pool of its own, a fifth of the boss's HP

    def learn_the_wing(self):
        # in the hologram, whose HP the tables give, the wing starts at 20% of it
        self.feed(joined(3927, 80.0), spawned(13974, "Level", 7, 81.0), life(204_817.6, 82.0, tag=self.WING))

    def extra_rate_fight(self, feed=None):
        (feed or self.feed)(
            joined(20019, 90.0), spawned(14000, "Prefab", 2, 91.0, prefab=401),
            life(500_000.0, 92.0, entity=14000, tag=self.WING),
        )
        self.feed(life(350_000.0, 99.0, entity=14000, tag=self.WING), boss_line(99.5, entity=14000))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.90)
        return self.t.snapshot(104.0)["encounter"]

    def test_a_boss_with_an_extra_rate_gets_its_hp_from_a_part_whose_share_is_known(self):
        self.learn_the_wing()
        enc = self.extra_rate_fight()
        self.assertEqual((enc["source"], enc["unit"], enc["hp_from"]), ("bar", "damage", "parts"))
        self.assertEqual(enc["max_hp_total"], 2_500_000)  # the wing's 500,000 is a fifth of it
        self.assertEqual(enc["boss"]["max_hp"], 2_500_000)
        self.assertAlmostEqual(enc["damage"], 0.10 * 2_500_000, delta=1_500)

    def test_a_part_whose_share_is_not_known_gives_no_hp(self):
        enc = self.extra_rate_fight()
        self.assertEqual((enc["unit"], enc["hp_from"]), ("percent", ""))

    def test_parts_logged_before_the_meter_started_count(self):
        def earlier(*events):
            for event in events:
                self.t.on_context(event)

        earlier(joined(3927, 80.0), spawned(13974, "Level", 7, 81.0), life(204_817.6, 82.0, tag=self.WING))
        enc = self.extra_rate_fight(feed=earlier)
        self.assertEqual((enc["unit"], enc["hp_from"], enc["max_hp_total"]), ("damage", "parts", 2_500_000))
        self.assertEqual(self.t.snapshot(104.0)["history"], [])  # and no fight was made of them

    def test_a_fresh_copy_of_the_boss_starts_its_parts_afresh(self):
        self.learn_the_wing()
        self.feed(joined(20019, 90.0), spawned(14000, "Prefab", 2, 91.0, prefab=401),
                  life(500_000.0, 92.0, entity=14000, tag=self.WING))
        # the same number given to a new copy, at a lower level
        again = life(300_000.0, 95.0, entity=14000, tag=self.WING)
        again.instance = "2147999999"
        self.feed(spawned(14000, "Prefab", 2, 94.0, prefab=401), again, boss_line(99.5, entity=14000))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.90)
        self.assertEqual(self.t.snapshot(104.0)["encounter"]["max_hp_total"], 1_500_000)

    def test_a_part_gives_the_hp_of_a_boss_whose_level_is_not_fixed(self):
        self.learn_the_wing()
        self.feed(joined(8, 90.0), spawned(14000, "Template", 9001, 91.0),
                  life(36_239.6, 92.0, entity=14000, tag=self.WING), boss_line(99.5, entity=14000))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.90)
        enc = self.t.snapshot(104.0)["encounter"]  # no level has been read off the screen
        self.assertEqual((enc["unit"], enc["hp_from"], enc["max_hp_total"]), ("damage", "parts", 181_198))
        self.t.set_title("Crownless (Lv 90)", replace=True)  # once read, the tables' HP is used
        self.assertEqual(self.t.snapshot(104.0)["encounter"]["hp_from"], "tables")

    def test_the_level_read_off_the_screen_is_used_when_the_placement_fixes_none(self):
        # an open-world boss: its level depends on the player's world level
        self.feed(joined(8, 90.0), spawned(13974, "Template", 9001, 91.0), boss_line(99.5))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.90)
        self.assertEqual(self.t.snapshot(104.0)["encounter"]["unit"], "percent")  # level not read yet
        self.t.set_title("Crownless (Lv 90)", replace=True)
        enc = self.t.snapshot(104.0)["encounter"]
        self.assertEqual(enc["unit"], "damage")
        self.assertAlmostEqual(enc["damage"], 0.10 * 181_198, delta=120)

    def test_the_level_the_placement_fixes_wins_over_the_one_read(self):
        self.hologram_fight()
        # the hologram's bar shows the difficulty's nominal level; HP uses the placement's 80
        self.t.set_title("Crownless (Lv 90)", replace=True)
        self.assertAlmostEqual(self.t.snapshot(108.0)["encounter"]["damage"], 0.30 * self.HP, delta=600)

    def test_the_fight_is_named_from_the_tables_with_the_level_the_bar_shows(self):
        self.hologram_fight()
        # nothing read off the screen: the name and the bar's level are both in the tables
        self.assertEqual(self.t.snapshot(108.0)["encounter"]["title"], "Crownless: Newborn Desires (Lv 90)")
        # and a misreading of the screen does not change either
        self.t.set_title("Crownlesss Newbom Desires (Lv 80)", replace=True)
        self.assertEqual(self.t.snapshot(108.0)["encounter"]["title"], "Crownless: Newborn Desires (Lv 90)")

    def test_the_level_of_a_boss_whose_placement_fixes_none_is_the_one_read(self):
        self.feed(joined(8, 90.0), spawned(13974, "Template", 9001, 91.0), boss_line(99.5))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.90)
        self.assertEqual(self.t.snapshot(104.0)["encounter"]["title"], "Crownless: Newborn Desires")
        self.t.set_title("(Lv 90)", replace=True)  # all a reader can make of another script
        self.assertEqual(self.t.snapshot(104.0)["encounter"]["title"], "Crownless: Newborn Desires (Lv 90)")

    def test_the_level_a_placement_fixes_is_shown_when_nothing_else_gives_one(self):
        self.feed(joined(20019, 90.0), spawned(13974, "Prefab", 1, 91.0, prefab=400), boss_line(99.5))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.90)
        self.assertEqual(self.t.snapshot(104.0)["encounter"]["title"], "Crownless: Newborn Desires (Lv 100)")

    def test_names_follow_the_language_the_tables_were_opened_in(self):
        self.t = Tracker(
            Roster(characters="does-not-exist.json", names="does-not-exist.json"), enemies=enemy_data("ja")
        )
        self.hologram_fight()
        self.assertEqual(self.t.snapshot(108.0)["encounter"]["title"], "無冠者・芽生える欲望 (Lv 90)")

    def test_switching_the_games_language_renames_the_fight_under_way(self):
        class Client:  # stands in for the game's settings
            language = "en"

            def current(self):
                return self.language

        client = Client()
        data = enemy_data()
        data.follow(client)
        self.t = Tracker(Roster(characters="does-not-exist.json", names="does-not-exist.json"), enemies=data)
        self.hologram_fight()
        self.assertEqual(self.t.snapshot(108.0)["encounter"]["title"], "Crownless: Newborn Desires (Lv 90)")
        client.language = "ja"
        self.t.tick(108.5)
        self.assertEqual(self.t.snapshot(109.0)["encounter"]["title"], "無冠者・芽生える欲望 (Lv 90)")

    def test_an_enemy_the_tables_do_not_name_keeps_the_title_read_off_the_screen(self):
        self.feed(joined(20019, 90.0), spawned(13974, "Prefab", 2, 91.0, prefab=401), boss_line(99.5))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.90)
        self.t.set_title("Tempest Mephis (Lv 70)", replace=True)
        self.assertEqual(self.t.snapshot(104.0)["encounter"]["title"], "Tempest Mephis (Lv 70)")

    def test_with_two_bosses_on_the_bar_the_fight_is_named_after_the_one_read_off_the_screen(self):
        other = "BP_ML1QiShiMd00001"
        self.feed(joined(20019, 90.0), spawned(10, "Prefab", 4, 91.0, prefab=403),
                  spawned(11, "Prefab", 1, 93.0, prefab=400), boss_line(99.5, entity=10))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.90)
        self.feed(boss_line(104.0, entity=11, actor=other))
        self.bar(104.0, 108.0, 1.00)
        self.bar(108.0, 110.0, 0.80)
        self.assertEqual(self.t.snapshot(110.0)["encounter"]["title"], "Cadanto (Lv 100)")  # the first
        self.t.set_title("Crownless:Newborn Desires (Lv 100)", replace=True)
        self.assertEqual(self.t.snapshot(110.0)["encounter"]["title"], "Crownless: Newborn Desires (Lv 100)")

    def test_an_enemy_that_reports_no_hp_is_named_from_the_tables(self):
        hit = LogEvent(
            ts=103.0, tick=0, module="CombatInfo", sub="Hit", entity_id=77, kind="Monster",
            actor="BP_ME1AnMaoziRenMd00601", text="受击", fields={"BeHitAnim": "重右"},
        )
        self.feed(joined(20019, 90.0), spawned(77, "Prefab", 4, 91.0, prefab=403))
        for i in range(6):
            self.feed(skill("BP_Alpha", "E技能", 100.0 + i))
        self.t.on_log(hit, 103.0)
        self.assertEqual(self.t.snapshot(105.5)["status"]["unmeasured"], "Cadanto")

    def test_each_boss_the_bar_shows_is_counted_with_its_own_hp(self):
        other = "BP_ML1QiShiMd00001"
        self.feed(joined(3927, 90.0), spawned(10, "Level", 7, 91.0), joined(20019, 92.0),
                  spawned(11, "Prefab", 1, 93.0, prefab=400), boss_line(99.5, entity=10))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.90)  # 10% of the first boss
        self.feed(boss_line(104.0, entity=11, actor=other))
        self.bar(104.0, 108.0, 1.00)  # the bar now shows the second one
        self.bar(108.0, 110.0, 0.95)  # 5% of it
        enc = self.t.snapshot(110.0)["encounter"]
        self.assertAlmostEqual(enc["damage"], 0.10 * self.HP + 0.05 * 5_510_473, delta=4000)
        self.assertEqual(enc["boss"]["max_hp"], 5_510_473)

    def test_a_kill_credits_what_the_bar_still_showed_to_the_boss_that_died(self):
        self.feed(joined(3927, 90.0), spawned(13974, "Level", 7, 91.0), boss_line(99.5))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.50)
        self.bar(104.0, 106.0, 0.06)
        self.feed(died(106.0))
        enc = self.t.snapshot(106.5)["encounter"]
        self.assertAlmostEqual(enc["damage"], self.HP, delta=600)
        self.assertEqual(enc["boss"]["life"], 0)
        # A dead boss has no rate of fall and no time to go. Half a second after the kill the
        # bar's last readings are still fresh, and the rate drawn from them read as "-x%/s"
        # beside "Target HP 0.0%".
        self.assertEqual((enc["boss"]["hp"], enc["boss"]["rate"], enc["boss"]["eta"]), (0.0, 0.0, 0))

    def killed_in_a_cutscene(self, death_after: float) -> None:
        """A boss taken to 6% with the bar up, then killed inside an ultimate's cutscene: the
        game ends combat first and reports the death ``death_after`` seconds later."""
        self.feed(joined(3927, 90.0), spawned(13974, "Level", 7, 91.0), boss_line(99.5))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.70)
        self.bar(104.0, 106.0, 0.40)
        self.bar(106.0, 108.0, 0.06)
        self.feed(in_fight(False, 108.0))
        for tenth in range(1, 15):
            self.t.tick(108.0 + tenth / 10)  # no bar on screen; the fight is closed after 1 s
        self.feed(died(108.0 + death_after))

    # -- a boss with a second bar ---------------------------------------------------------------
    # Recorded on 2026-11-15 (recordings\20261115-180315): four Inferno Rider kills in the
    # hologram that read 153%, 171%, 185% and 199% of one bar's HP, where each is two bars.

    def readings(self, *values: tuple[float, float], step: float = 0.1) -> None:
        """Bar readings at the given times, with a boss line every half second or so."""
        for now, fraction in values:
            self.t.on_boss(now, fraction)
            self.t.tick(now)

    def test_a_bar_that_jumps_from_a_third_to_full_is_the_next_bar_and_the_rest_is_counted(self):
        # A strong hit takes the first bar from 37% straight to a full second bar: the bar is
        # never seen near empty, and by the time the new bar is believed it has fallen to 91%.
        self.feed(joined(3927, 90.0), spawned(13974, "Level", 7, 91.0), boss_line(99.5))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.70)
        self.bar(104.0, 106.0, 0.37)
        self.feed(boss_line(105.9))
        self.readings((106.0, 0.96), (106.1, 1.00), (106.2, 0.96))  # filling, full, hit at once
        self.bar(106.3, 108.5, 0.91)
        self.feed(boss_line(108.0))
        enc = self.t.snapshot(108.5)["encounter"]
        # 63% seen falling, the 37% the jump hid, and 9% of the new bar
        self.assertAlmostEqual(enc["damage"], 1.09 * self.HP, delta=1_500)
        self.assertAlmostEqual(enc["boss"]["hp"], 0.91, places=2)

    def test_a_kill_on_a_next_bar_not_yet_believed_counts_both_bars(self):
        # Inferno Rider at hologram I, recorded at 1080p: the second bar was up for 1.8 s before
        # the kill, and at four readings a second it was never believed. The kill counted one bar.
        self.feed(joined(3927, 90.0), spawned(13974, "Level", 7, 91.0), boss_line(99.5))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.60)
        self.bar(104.0, 106.0, 0.21)
        self.feed(boss_line(105.9))
        self.readings((106.0, 0.998), (106.25, 0.95), (106.5, 0.90), (106.75, 0.85), (107.0, 0.77))
        self.feed(died(107.2))
        enc = self.t.snapshot(108.0)["encounter"]
        self.assertAlmostEqual(enc["damage"], 2 * self.HP, delta=3_000)

    def test_a_next_bar_seen_briefly_before_the_kills_cutscene_counts_both_bars(self):
        # The same fight as it really went: the bar left the screen 1.8 s after the second one
        # appeared, and the death was reported 6.4 s later, once the kill's cutscene was over.
        self.feed(joined(3927, 90.0), spawned(13974, "Level", 7, 91.0), boss_line(99.5))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.60)
        self.bar(104.0, 106.0, 0.21)
        self.feed(boss_line(105.9))
        self.readings((106.0, 0.998), (106.25, 0.95), (106.5, 0.90), (106.75, 0.85), (107.0, 0.77))
        for k in range(1, 26):
            self.t.tick(107.0 + k * 0.25)  # no bar on screen
        self.feed(died(113.4))
        enc = self.t.snapshot(114.0)["encounter"]
        self.assertAlmostEqual(enc["damage"], 2 * self.HP, delta=3_000)

    def test_a_brief_jump_up_and_hiding_is_not_a_next_bar(self):
        # Two readings of a full bar before the HUD hides: too little to be a bar.
        self.feed(joined(3927, 90.0), spawned(13974, "Level", 7, 91.0), boss_line(99.5))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.50)
        self.readings((104.0, 0.95), (104.1, 0.95))
        for k in range(1, 12):
            self.t.tick(104.1 + k * 0.25)
        self.bar(107.0, 109.0, 0.50)
        enc = self.t.snapshot(109.0)["encounter"]
        self.assertAlmostEqual(enc["damage"], 0.5 * self.HP, delta=1_500)

    def test_a_kill_with_no_new_bar_in_sight_counts_one_bar(self):
        self.feed(joined(3927, 90.0), spawned(13974, "Level", 7, 91.0), boss_line(99.5))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.60)
        self.bar(104.0, 106.0, 0.21)
        self.readings((106.0, 0.22), (106.25, 0.21))  # a pixel of flicker is not a new bar
        self.feed(died(106.4))
        enc = self.t.snapshot(107.0)["encounter"]
        self.assertAlmostEqual(enc["damage"], self.HP, delta=1_500)

    def test_with_a_second_boss_about_a_jump_up_is_not_taken_for_the_next_bar(self):
        # Two bosses in one fight: the bar going from 37% to full is the other boss's bar.
        self.feed(joined(3927, 90.0), spawned(13974, "Level", 7, 91.0), spawned(13975, "Level", 7, 91.0))
        self.feed(boss_line(99.5), boss_line(99.6, entity=13975))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.70)
        self.bar(104.0, 106.0, 0.37)
        self.feed(boss_line(105.8), boss_line(105.9, entity=13975))
        self.bar(106.0, 108.5, 1.00)
        self.bar(108.5, 110.0, 0.90)
        enc = self.t.snapshot(110.0)["encounter"]
        self.assertAlmostEqual(enc["damage"], 0.73 * self.HP, delta=1_500)  # 63% and 10%, no more

    def test_a_dead_bosss_bar_still_on_screen_is_not_read_as_hp_left(self):
        # The bar stays up for a frame or two after the kill. Read, it put "16.6% left" on a
        # boss that had just been credited as killed.
        self.feed(joined(3927, 90.0), spawned(13974, "Level", 7, 91.0), boss_line(99.5))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.60)
        self.bar(104.0, 106.0, 0.30)
        self.bar(106.0, 108.0, 0.17)
        self.feed(died(108.0))
        self.readings((108.05, 0.17), (108.15, 0.17))
        enc = self.t.snapshot(108.5)["encounter"]
        self.assertAlmostEqual(enc["damage"], self.HP, delta=600)
        self.assertEqual((enc["boss"]["hp"], enc["boss"]["life"]), (0.0, 0))

    def test_a_long_lull_with_the_games_combat_flag_on_does_not_split_the_fight(self):
        # Seen live on 2026-11-15: the first bar taken to 7%, then 41 s without a hit (a dead
        # character, the change of phase) with the game still in combat, then the second bar.
        # It came out as two fights, 92.8% and 20.5%, with the 7% between them counted nowhere.
        self.feed(joined(3927, 90.0), spawned(13974, "Level", 7, 91.0), boss_line(99.5))
        self.feed(in_fight(True, 99.8))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.60)
        self.bar(104.0, 106.0, 0.30)
        self.bar(106.0, 108.0, 0.07)
        for tenth in range(0, 400, 5):
            self.t.tick(108.0 + tenth / 10)  # 40 s: no bar, no skills, the flag still on
        self.assertTrue(self.t.snapshot(148.0)["encounter"]["live"])
        self.bar(148.0, 151.0, 1.00)  # the second bar
        self.bar(151.0, 154.0, 0.80)
        self.feed(in_fight(False, 154.0))
        self.t.tick(155.5)
        snap = self.t.snapshot(156.0)
        self.assertEqual(len(snap["history"]), 1)
        self.assertAlmostEqual(snap["encounter"]["damage"], 1.20 * self.HP, delta=1_500)

    def test_without_the_flag_a_long_lull_still_ends_the_fight(self):
        self.feed(joined(3927, 90.0), spawned(13974, "Level", 7, 91.0), boss_line(99.5))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.60)
        self.bar(104.0, 106.0, 0.30)
        self.bar(106.0, 108.0, 0.07)
        for tenth in range(0, 400, 5):
            self.t.tick(108.0 + tenth / 10)
        self.assertFalse(self.t.snapshot(148.0)["encounter"]["live"])

    def test_a_flag_left_on_does_not_hold_a_fight_open_for_ever(self):
        self.feed(joined(3927, 90.0), spawned(13974, "Level", 7, 91.0), boss_line(99.5))
        self.feed(in_fight(True, 99.8))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.60)
        self.bar(104.0, 106.0, 0.30)
        self.bar(106.0, 108.0, 0.07)
        self.t.tick(200.0)
        self.assertTrue(self.t.snapshot(200.0)["encounter"]["live"])
        self.t.tick(230.0)  # two minutes without anything
        self.assertFalse(self.t.snapshot(230.0)["encounter"]["live"])

    def test_a_kill_reported_just_after_the_fight_closed_still_counts(self):
        # Seen live on 2026-11-15: the death came 1.1 s after the combat flag and the fight was
        # left at 94.45% of the boss's HP, with 5.8% of the bar still showing.
        self.killed_in_a_cutscene(death_after=1.5)
        snap = self.t.snapshot(112.0)
        enc = snap["encounter"]
        self.assertFalse(enc["live"])
        self.assertAlmostEqual(enc["damage"], self.HP, delta=600)
        self.assertEqual((enc["boss"]["hp"], enc["boss"]["life"]), (0.0, 0))
        self.assertEqual(len(snap["history"]), 1)  # the same fight, not a second one
        self.assertEqual(snap["history"][0]["damage"], enc["damage"])
        # from the first drop counted (102.5) to the kill (109.5), not to the last bar reading
        self.assertAlmostEqual(enc["duration"], 7.0, places=1)

    def test_a_death_long_after_the_fight_closed_changes_nothing(self):
        self.killed_in_a_cutscene(death_after=30.0)
        enc = self.t.snapshot(140.0)["encounter"]
        self.assertAlmostEqual(enc["damage"], 0.94 * self.HP, delta=600)
        self.assertAlmostEqual(enc["boss"]["hp"], 0.06, places=3)

    def test_a_dead_boss_is_not_the_bars_enemy_for_the_next_fight(self):
        self.feed(joined(3927, 90.0), spawned(13974, "Level", 7, 91.0), boss_line(99.5))
        self.bar(100.0, 102.0, 1.00)
        self.bar(102.0, 104.0, 0.06)
        self.feed(died(104.0), boss_line(104.2))  # its last lines trail the death
        self.t.reset()
        self.bar(105.0, 107.0, 1.00)  # the next boss, not yet named in the log
        self.bar(107.0, 109.0, 0.80)
        self.assertEqual(self.t.snapshot(109.0)["encounter"]["unit"], "percent")

    def test_logged_hp_is_still_preferred_and_untouched(self):
        self.feed(joined(3927, 90.0), spawned(13974, "Level", 7, 91.0))
        self.bar(100.0, 102.0, 1.00)
        self.feed(life(self.HP, 102.0), life(self.HP - 2_000, 102.5))
        self.bar(102.5, 105.0, 0.98)
        enc = self.t.snapshot(105.0)["encounter"]
        self.assertEqual((enc["source"], enc["damage"], enc["hp_from"]), ("log", 2_000, "log"))


class RosterTest(unittest.TestCase):
    def test_tidy(self):
        self.assertEqual(tidy("BP_Feixue"), "Feixue")
        self.assertEqual(tidy("BP_ME1JiancuxiongMd00001"), "Jiancuxiong")
        self.assertEqual(tidy("BP_MO1LuguiMd00201"), "Lugui")
        self.assertEqual(tidy("BP_ME1WanZhengShiZiMd00101"), "Wan Zheng Shi Zi")
        self.assertEqual(tidy("BP_MB1Wuguanzhe00601"), "Wuguanzhe")
        self.assertEqual(tidy("BP_WindNvzhu_Md20011"), "Wind Nvzhu")

    def test_shipped_table_by_character_id(self):
        roster = Roster()
        self.assertEqual(roster.lookup("BP_Kmola", 1107), ("Carlotta", "glacio"))
        self.assertEqual(roster.lookup("BP_WindNvzhu_Md20011", 1408), ("Rover (Aero)", "aero"))
        self.assertEqual(roster.lookup("BP_Whatever", 1304), ("Jinhsi", "spectro"))  # not electro

    def test_shipped_table_by_internal_name(self):
        roster = Roster()
        self.assertEqual(roster.lookup("BP_Shouanren"), ("Shorekeeper", "spectro"))
        self.assertEqual(roster.lookup("BP_Feixue"), ("Hiyuki", "glacio"))
        self.assertEqual(roster.lookup("BP_MB1Wuguanzhe00601"), ("Crownless", None))
        self.assertEqual(roster.lookup("BP_SomeoneNew"), ("Someone New", None))

    def test_skill_ids_carry_the_character_id(self):
        roster = Roster()
        self.assertEqual(roster.role_id_of("1107051"), 1107)
        self.assertEqual(roster.role_id_of("1505998"), 1505)
        self.assertIsNone(roster.role_id_of("100001"))  # shared dodge
        self.assertIsNone(roster.role_id_of("286133020"))  # event skill, not a character's
        self.assertIsNone(roster.role_id_of(""))


class GameNamesTest(unittest.TestCase):
    """Characters named from the game's tables, in the language of the moment."""

    def test_the_games_name_is_shown_with_the_element_from_the_meters_list(self):
        data = enemy_data("ja")
        roster = Roster(game_name=data.character_name)
        self.assertEqual(roster.lookup("BP_Kmola", 1107), ("カルロッタ", "glacio"))
        data.set_language("en")
        self.assertEqual(roster.lookup("BP_Kmola", 1107), ("Carlotta", "glacio"))

    def test_the_games_english_name_replaces_the_lists(self):
        roster = Roster(game_name=enemy_data("en").character_name)
        self.assertEqual(roster.lookup("BP_WindNvzhu_Md20011", 1408), ("Rover: Aero", "aero"))

    def test_a_character_the_tables_lack_keeps_the_lists_name(self):
        roster = Roster(game_name=enemy_data("ja").character_name)
        self.assertEqual(roster.lookup("BP_Whatever", 1304), ("Jinhsi", "spectro"))

    def test_a_character_newer_than_the_list_is_named_by_the_tables(self):
        roster = Roster(game_name=enemy_data("en").character_name)
        self.assertEqual(roster.role_id_of("1999051"), 1999)
        self.assertEqual(roster.lookup("BP_Xinren", 1999), ("Newcomer", None))
        # the tables also name things that are not playable characters: not taken for one
        self.assertIsNone(roster.role_id_of("5001051"))
        self.assertIsNone(Roster().role_id_of("1999051"))

    def test_an_enemy_is_not_named_by_the_tables_of_characters(self):
        roster = Roster(game_name=enemy_data("ja").character_name)
        self.assertEqual(roster.lookup("BP_MB1Wuguanzhe00601"), ("Crownless", None))

    def test_switching_the_games_language_renames_the_characters_of_the_fight_under_way(self):
        data = enemy_data("en")
        t = Tracker(Roster(game_name=data.character_name), timeout=8.0, enemies=data)
        cast = skill("BP_Kmola", "E技能", 99.5)
        cast.fields["技能Id"] = "1107051"
        for event in (switch("BP_Kmola", 99.0), cast, life(9_000, 100.0), life(8_000, 101.0)):
            t.on_log(event, event.ts)
        self.assertEqual(t.snapshot(102.0)["encounter"]["players"][0]["name"], "Carlotta")
        data.set_language("ja")
        player = t.snapshot(102.5)["encounter"]["players"][0]
        self.assertEqual((player["name"], player["element"]), ("カルロッタ", "glacio"))


class CharacterIdTest(unittest.TestCase):
    def test_tracker_names_a_character_from_its_skill_ids(self):
        t = Tracker(Roster(), timeout=8.0)
        cast = skill("BP_Kmola", "E技能", 99.5)
        cast.fields["技能Id"] = "1107051"
        for event in (switch("BP_Kmola", 99.0), cast, life(9_000, 100.0), life(8_000, 101.0)):
            t.on_log(event, event.ts)
        player = t.snapshot(102.0)["encounter"]["players"][0]
        self.assertEqual((player["name"], player["element"]), ("Carlotta", "glacio"))


if __name__ == "__main__":
    unittest.main()
