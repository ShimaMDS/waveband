"""The damage-number reader, checked on numbers drawn from its own digit shapes.

These tests show the matching and bookkeeping are sound on clean input. How it does on real
frames is measured by tools/grade_number_reader.py, and it is far from perfect there.
"""

import unittest

import numpy as np

try:
    import cv2
except ImportError:  # the number reader is off, and OpenCV is only in requirements-dev.txt
    raise unittest.SkipTest("OpenCV is not installed (requirements-dev.txt)")

from wwmeter import dmgnum  # noqa: E402

TEMPLATES = dmgnum.Templates()
ORANGE = (40, 140, 255)  # BGR, inside the fusion band
CYAN = (255, 215, 110)  # BGR, inside the glacio band


def glyph_mask(digit: int, height: int) -> np.ndarray:
    glyph = TEMPLATES.glyphs[digit]
    width = max(3, round(glyph.shape[1] * height / glyph.shape[0]))
    return cv2.resize(glyph, (width, height), interpolation=cv2.INTER_AREA) > 0.5


def row_mask(text: str, height: int = 48, gap: int = 4) -> np.ndarray:
    parts = [glyph_mask(int(c), height) for c in text]
    width = sum(p.shape[1] for p in parts) + gap * (len(parts) - 1)
    mask = np.zeros((height, width), bool)
    x = 0
    for part in parts:
        mask[:, x : x + part.shape[1]] = part
        x += part.shape[1] + gap
    return mask


def paint(frame: np.ndarray, text: str, x: int, y: int, colour, height: int = 48) -> None:
    mask = row_mask(text, height)
    frame[y : y + mask.shape[0], x : x + mask.shape[1]][mask] = colour


class DecodeTest(unittest.TestCase):
    def test_reads_rows_of_separate_digits(self):
        for text in ("7", "42", "1903", "58428", "1234567"):
            decoded = dmgnum.decode(row_mask(text), TEMPLATES)
            self.assertIsNotNone(decoded, text)
            self.assertEqual(decoded[0], text)

    def test_reads_digits_that_touch(self):
        decoded = dmgnum.decode(row_mask("2057", gap=0), TEMPLATES)
        self.assertEqual(decoded[0], "2057")

    def test_size_does_not_matter(self):
        for height in (24, 60, 110):
            self.assertEqual(dmgnum.decode(row_mask("3916", height), TEMPLATES)[0], "3916")

    def test_a_row_with_something_that_is_not_a_digit_is_refused(self):
        mask = row_mask("3916")
        junk = np.ones((mask.shape[0], 40), bool)
        self.assertIsNone(dmgnum.decode(np.hstack([mask, junk]), TEMPLATES))
        self.assertIsNone(dmgnum.decode(np.ones((40, 90), bool), TEMPLATES))

    def test_leading_zero_is_refused(self):
        self.assertIsNone(dmgnum.decode(row_mask("0412"), TEMPLATES))


class ReadTest(unittest.TestCase):
    def setUp(self):
        self.frame = np.full((1440, 2560, 3), 40, np.uint8)
        self.reader = dmgnum.NumberReader(TEMPLATES)

    def test_reads_numbers_by_colour_and_place(self):
        paint(self.frame, "1903", 1100, 500, ORANGE)
        paint(self.frame, "58428", 1400, 800, CYAN, height=70)
        readings = sorted(self.reader.read(self.frame), key=lambda r: r.value)
        self.assertEqual([(r.value, r.element) for r in readings], [(1903, "fusion"), (58428, "glacio")])
        self.assertAlmostEqual(readings[1].y, 835, delta=3)

    def test_hud_edges_and_the_timer_are_not_read(self):
        paint(self.frame, "4455", 80, 600, ORANGE)  # quest tracker side
        paint(self.frame, "3878", 1150, 1300, ORANGE)  # HP readout
        paint(self.frame, "0447", 1140, 165, ORANGE)  # challenge timer
        self.assertEqual(self.reader.read(self.frame), [])

    def test_healing_green_is_not_read(self):
        paint(self.frame, "1064", 1100, 500, (90, 230, 90))
        self.assertEqual(self.reader.read(self.frame), [])

    def test_a_number_is_counted_once_while_it_floats_upward(self):
        counted = []
        for step in range(8):
            frame = np.full((1440, 2560, 3), 40, np.uint8)
            paint(frame, "1903", 1100, 700 - 12 * step, ORANGE)
            counted += [r.value for r in self.reader.update(frame, 10.0 + step / 10)]
        self.assertEqual(counted, [1903])

    def test_the_same_value_elsewhere_or_later_is_a_new_number(self):
        paint(self.frame, "116", 1000, 500, ORANGE)
        paint(self.frame, "116", 1700, 900, ORANGE)
        first = [r.value for r in self.reader.update(self.frame, 10.0)]
        again = [r.value for r in self.reader.update(self.frame, 10.1)]
        later = [r.value for r in self.reader.update(self.frame, 14.0)]
        self.assertEqual((first, again, later), ([116, 116], [], [116, 116]))


if __name__ == "__main__":
    unittest.main()
