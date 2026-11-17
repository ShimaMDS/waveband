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

import numpy as np
from PIL import Image

from wwmeter import hud
from wwmeter.replay import read_frame

try:
    import cv2  # only to check the meter's own colour conversion against OpenCV's
except ImportError:
    cv2 = None

DATA = os.path.join(os.path.dirname(__file__), "data")


def frame(label: str, height: int = 1440) -> np.ndarray:
    strip = read_frame(os.path.join(DATA, f"bar_{label}.png" if height == 1440 else f"bar{height}_{label}.png"))
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
        small = np.asarray(Image.fromarray(frame("mid")).resize((1920, 1080), Image.BOX))
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

    def test_the_top_strip_alone_reads_as_the_whole_frame(self):
        # the meter copies only the strip off the screen and says how tall the game is
        for label, height in (("full", 1440), ("mid", 1440), ("shattered", 1440), ("full", 1080),
                              ("mid", 1080), ("cutscene", 1440), ("overworld", 1440)):
            whole = frame(label, height)
            rows = round(height * hud.strip_share())
            self.assertEqual(hud.read_boss_bar(whole[:rows], height=height), hud.read_boss_bar(whole),
                             f"{label} {height}")

    def test_the_strip_holds_everything_read(self):
        self.assertEqual(round(1440 * hud.strip_share()), 130)
        self.assertEqual(round(1080 * hud.strip_share()), 98)  # what the 1080p test strips hold
        self.assertAlmostEqual(hud.strip_share([0.3, 0.5, 0.7, 0.52]), 0.54)  # a bar placed by hand
        self.assertEqual(hud.strip_share([0.1, 0.9, 0.9, 0.99]), 1.0)

    def test_the_title_is_cut_from_the_same_place_in_a_strip(self):
        seen = []

        def ocr(crop):
            seen.append(crop.copy())
            return "", 0.0

        whole = frame("mid")
        hud.read_boss_title(whole, ocr)
        hud.read_boss_title(whole[:130], ocr, height=1440)
        self.assertEqual(seen[0].shape, seen[1].shape)
        self.assertTrue(np.array_equal(seen[0], seen[1]))

    def test_ultrawide_is_anchored_to_the_centre(self):
        wide = np.zeros((1440, 3440, 3), np.uint8)
        wide[:, 440:3000] = frame("late")
        bar = hud.read_boss_bar(wide)
        self.assertIsNotNone(bar)
        self.assertAlmostEqual(bar.fraction, 0.7333, delta=0.003)


class ColourTest(unittest.TestCase):
    @unittest.skipIf(cv2 is None, "OpenCV is not installed (requirements-dev.txt)")
    def test_hsv_is_opencvs_on_every_colour(self):
        # the bar's thresholds were fitted on OpenCV's HSV; the meter now converts on its own
        g, b = np.meshgrid(np.arange(256, dtype=np.uint8), np.arange(256, dtype=np.uint8), indexing="ij")
        for r in range(256):
            image = np.stack([b, g, np.full_like(b, r)], axis=-1)
            np.testing.assert_array_equal(hud.bgr_to_hsv(image), cv2.cvtColor(image, cv2.COLOR_BGR2HSV), f"r={r}")

    def test_known_colours(self):
        pixels = np.array([[[0, 0, 255], [0, 255, 0], [255, 0, 0], [0, 0, 0], [255, 255, 255], [40, 140, 255]]], np.uint8)
        self.assertEqual(hud.bgr_to_hsv(pixels).tolist(),
                         [[[0, 255, 255], [60, 255, 255], [120, 255, 255], [0, 0, 0], [0, 0, 255], [14, 215, 255]]])


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


class TitleReadingTest(unittest.TestCase):
    """Real crops above the boss bar (Crownless in the hologram), read by the meter's own reader:
    at 2560x1440, where the crop is the network's height already, and at 1920x1080, where it is
    scaled up to it."""

    @classmethod
    def setUpClass(cls):
        from wwmeter.ocr import TextReader

        cls.reader = TextReader()

    def read(self, name: str) -> str:
        text, score = self.reader(read_frame(os.path.join(DATA, name)))
        return hud.parse_title(text, name_readable=score >= 0.6)

    def test_1440p(self):
        self.assertEqual(self.read("title_1440.png"), "Crownless: Newborn Desires (Lv 65)")

    def test_1080p(self):
        self.assertEqual(self.read("title1080.png"), "Crownless: Newborn Desires (Lv 60)")

    def test_nothing_to_read(self):
        self.assertEqual(self.reader(np.zeros((48, 600, 3), np.uint8)), ("", 0.0))
        self.assertEqual(self.reader(np.zeros((0, 0, 3), np.uint8)), ("", 0.0))


if __name__ == "__main__":
    unittest.main()
