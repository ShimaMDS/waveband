"""The strips in tests/data are the top 130 rows of real 2560x1440 frames from one boss fight.

The expected fractions are the boss's HP at that moment as written in the game log, divided by
its maximum (5,511,481), so these tests check the screen reader against the game's own numbers.

``bar1080_*`` are the top 98 rows of real frames from the game in a 1920x1080 window
(`recordings/20261116-105636`): a full bar at a moment the log also had the boss at full HP, and
Inferno Rider's bar with its fill ending at x=1062 and the white trail of a hit beyond it. That
fight logs no HP, so the second figure is the one the fill's end gives on the scaled bar (its
fill runs from x=680 to 1250, just where the 1440p measure scales to). The corner where the
player's performance overlay was is blanked in all the strips.
"""

import os
import unittest

import cv2
import numpy as np

from wwmeter import hud

DATA = os.path.join(os.path.dirname(__file__), "data")


def frame(label: str, height: int = 1440) -> np.ndarray:
    strip = cv2.imread(os.path.join(DATA, f"bar_{label}.png" if height == 1440 else f"bar{height}_{label}.png"))
    full = np.zeros((height, strip.shape[1], 3), np.uint8)
    full[: strip.shape[0]] = strip
    return full


class BossBarTest(unittest.TestCase):
    def check(self, label: str, logged: float):
        bar = hud.read_boss_bar(frame(label))
        self.assertIsNotNone(bar, label)
        self.assertAlmostEqual(bar.fraction, logged, delta=0.003, msg=label)
        self.assertGreaterEqual(bar.confidence, 0.8, label)

    def test_fraction_matches_logged_hp(self):
        self.check("full", 0.9989)
        self.check("mid", 0.8133)
        self.check("late", 0.7333)

    def test_shattered_bar_during_stagger(self):
        self.check("shattered", 0.9325)

    def test_no_bar_during_a_cutscene_or_in_the_overworld(self):
        self.assertIsNone(hud.read_boss_bar(frame("cutscene")))
        self.assertIsNone(hud.read_boss_bar(frame("overworld")))

    def test_blank_and_tiny_frames(self):
        self.assertIsNone(hud.read_boss_bar(np.zeros((1440, 2560, 3), np.uint8)))
        self.assertIsNone(hud.read_boss_bar(np.zeros((90, 160, 3), np.uint8)))

    def test_scales_with_resolution(self):
        small = cv2.resize(frame("mid"), (1920, 1080), interpolation=cv2.INTER_AREA)
        bar = hud.read_boss_bar(small)
        self.assertIsNotNone(bar)
        self.assertAlmostEqual(bar.fraction, 0.8133, delta=0.005)

    def test_a_real_1080p_frame(self):
        full = hud.read_boss_bar(frame("full", 1080))
        self.assertIsNotNone(full)
        self.assertGreaterEqual(full.fraction, 0.997)
        self.assertEqual(hud.bar_rect(1920, 1080)[::2], (680, 1250))

    def test_a_hits_white_trail_at_1080p_is_not_counted_as_hp(self):
        bar = hud.read_boss_bar(frame("mid", 1080))
        self.assertIsNotNone(bar)
        self.assertAlmostEqual(bar.fraction, 0.6839, delta=0.003)  # not the trail's end, near 0.83
        self.assertGreaterEqual(bar.confidence, 0.8)

    def test_ultrawide_is_anchored_to_the_centre(self):
        wide = np.zeros((1440, 3440, 3), np.uint8)
        wide[:, 440:3000] = frame("late")
        bar = hud.read_boss_bar(wide)
        self.assertIsNotNone(bar)
        self.assertAlmostEqual(bar.fraction, 0.7333, delta=0.003)


class TitleTest(unittest.TestCase):
    def test_parse_title(self):
        self.assertEqual(
            hud.parse_title("Lv. 10o Crownless: Newborn Desires 、/"),
            "Crownless: Newborn Desires (Lv 100)",
        )
        self.assertEqual(
            hud.parse_title("Lv.100 Crownless:NewbornDesires"), "Crownless: Newborn Desires (Lv 100)"
        )
        self.assertEqual(hud.parse_title("Lv. 9O 无冠者"), "无冠者 (Lv 90)")
        self.assertEqual(hud.parse_title("Tempest Mephis"), "Tempest Mephis")
        self.assertEqual(hud.parse_title(" ./"), "")

    def test_a_level_in_front_of_a_name_that_could_not_be_read_is_kept(self):
        # a client in a script the reader does not know: the name comes from the game's tables
        self.assertEqual(hud.parse_title("Lv. 90 ?#@", name_readable=False), "(Lv 90)")
        self.assertEqual(hud.parse_title("Lv.100", name_readable=False), "(Lv 100)")
        self.assertEqual(hud.parse_title("Lv. 70 ."), "(Lv 70)")
        # but only a level read cleanly: there is no name to vouch for the reading
        self.assertEqual(hud.parse_title("Lv. 9O ?#@", name_readable=False), "")
        self.assertEqual(hud.parse_title("Ly 90 ?#@", name_readable=False), "")
        self.assertEqual(hud.parse_title("?#@ 90", name_readable=False), "")


if __name__ == "__main__":
    unittest.main()
