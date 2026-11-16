import unittest

from wwmeter.summary import fight_summary


def player(name: str, damage: float, share: float, dps: float) -> dict:
    return {"name": name, "damage": damage, "share": share, "dps": dps}


# the second of the three hologram fights of 2026-11-15, as the meter kept it
KILL = {
    "title": "Fallacy of No Return: Tethys System (Lv 70)", "live": False, "duration": 66.3,
    "source": "bar", "unit": "damage", "hp_from": "tables", "max_hp_total": 682_649,
    "damage": 682_649, "dps": 10_293,
    "players": [
        player("Hiyuki", 602_165, 0.8821, 9_080),
        player("Lynae", 54_522, 0.0799, 822),
        player("Shorekeeper", 25_963, 0.038, 391),
    ],
}


class FightSummaryTest(unittest.TestCase):
    def test_a_fight_in_damage(self):
        self.assertEqual(
            fight_summary(KILL, "0.1.0").splitlines(),
            [
                "### Fallacy of No Return: Tethys System (Lv 70)",
                "**10,293 DPS** · 682,649 damage · 1:06 · 100% of its 682,649 HP",
                "1. **Hiyuki** · 9,080 DPS · 602,165 (88.2%)",
                "2. **Lynae** · 822 DPS · 54,522 (8.0%)",
                "3. **Shorekeeper** · 391 DPS · 25,963 (3.8%)",
                "-# Measured from the boss HP bar and the boss's HP from the game's data."
                " Split by who was on field. Waveband 0.1.0",
            ],
        )

    def test_a_fight_only_known_in_percent_of_hp(self):
        fight = dict(
            KILL, unit="percent", hp_from="", max_hp_total=0, damage=45.2, dps=0.68,
            players=[player("Hiyuki", 40.1, 0.887, 0.6), player("Lynae", 5.1, 0.113, 0.08)],
        )
        lines = fight_summary(fight).splitlines()
        self.assertEqual(lines[1], "**0.68% of HP/s** · 45.2% of its HP · 1:06")
        self.assertEqual(lines[2], "1. **Hiyuki** · 0.60% of HP/s · 40.1% (88.7%)")
        self.assertEqual(lines[3], "2. **Lynae** · 0.08% of HP/s · 5.10% (11.3%)")
        self.assertIn("its HP isn't known, so this is percent of HP", lines[4])
        self.assertNotIn("damage", lines[1])

    def test_a_whole_bar_in_percent_says_each_part_once(self):
        fight = dict(
            KILL, unit="percent", hp_from="", max_hp_total=0, damage=100.0, dps=0.86,
            players=[player("Hiyuki", 93.5, 0.935, 0.81), player("Lynae", 6.5, 0.065, 0.05)],
        )
        lines = fight_summary(fight).splitlines()
        self.assertEqual(lines[2], "1. **Hiyuki** · 0.81% of HP/s · 93.5%")

    def test_exact_damage_from_the_log_says_so(self):
        fight = dict(KILL, source="log", hp_from="log", players=[player("Carlotta", 682_649, 1.0, 10_293)])
        lines = fight_summary(fight).splitlines()
        self.assertEqual(lines[-1], "-# Measured from enemy HP in the game log (exact).")  # one row: no split

    def test_a_running_fight_is_marked(self):
        self.assertIn("(still running)", fight_summary(dict(KILL, live=True)).splitlines()[0])

    def test_a_fight_with_nothing_but_a_total(self):
        bare = {"title": "", "duration": 5, "damage": 1_200, "dps": 240}
        self.assertEqual(fight_summary(bare), "### Fight\n**240 DPS** · 1,200 damage · 0:05")

    def test_names_cannot_turn_into_formatting(self):
        fight = dict(KILL, title="665_Monster_004 *test*", players=[player("Rover_Havoc", 10, 1.0, 1)])
        lines = fight_summary(fight).splitlines()
        self.assertEqual(lines[0], r"### 665\_Monster\_004 \*test\*")
        self.assertEqual(lines[2], r"1. **Rover\_Havoc** · 1 DPS · 10 (100.0%)")


class DerivedHpTest(unittest.TestCase):
    def test_hp_worked_out_from_a_part_is_said_so(self):
        text = fight_summary(dict(KILL, hp_from="parts"))
        self.assertIn("the boss's HP worked out from one of its parts", text)
        self.assertNotIn("from the game's data", text)


if __name__ == "__main__":
    unittest.main()
