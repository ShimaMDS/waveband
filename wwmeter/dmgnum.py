"""Read floating damage numbers off the screen with templates of the game's own digit font.

Used for enemies that neither log their HP nor show a boss bar. A damage number is drawn in one
bright colour per element with a dark outline. In a mask of that colour, blobs of one height that
sit side by side form a row; the row is scaled to a fixed height and the ten digit shapes are
slid along it.

A row is only accepted when digits account for all of it. Numbers that overlap each other or the
scenery are dropped rather than guessed, so busy moments read low, never wildly high.

A number stays on screen for several frames, so each one is followed from frame to frame and
counted once.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import cv2
import numpy as np

from .config import ROOT

TEMPLATES_PATH = os.path.join(ROOT, "data", "digits.npz")

# Play area searched for numbers, as fractions of the frame (x0, y0, x1, y1). The edges hold HUD
# text and bars in the same colours: quest tracker, party list, skill icons, HP readout.
_ROI = (0.25, 0.09, 0.86, 0.86)
_TIMER = (0.40, 0.105, 0.60, 0.175)  # the challenge timer sits inside the play area

# Fill colour of the numbers per element, as OpenCV hue ranges. Fusion, spectro and glacio are
# measured from recordings; aero, electro and havoc are placed by eye and still unconfirmed.
# Green is healing and is never read.
BANDS: dict[str, tuple[tuple[int, int], ...]] = {
    "fusion": ((5, 19),),  # orange; pure red is left out, it is not a damage-dealt colour
    "spectro": ((20, 36),),
    "aero": ((76, 89),),
    "glacio": ((90, 112),),
    "electro": ((125, 155),),
    "havoc": ((156, 171),),
}
_MIN_SAT, _MIN_VAL = 60, 185

GLYPH_W, GLYPH_H = 20, 32  # every blob is scaled to this before matching
_MIN_HEIGHT = 0.016  # smallest digit height, as a fraction of frame height (23 px at 1440p)
_MAX_HEIGHT = 0.14
_MATCH = 0.58  # lowest correlation for a digit shape
_MATCH_ALONE = 0.80  # a one-digit number has nothing to line up with, so it must match well
_TRACK_GAP = 1.5  # seconds a number may go unseen and still be the same one
_MAX_DIGITS = 7


@dataclass(slots=True)
class Reading:
    value: int
    element: str
    x: float  # centre, in frame pixels
    y: float
    height: float
    score: float


@dataclass(slots=True)
class _Blob:
    x: int
    y: int
    w: int
    h: int
    digit: int  # the blob's label in the mask's label image
    score: float


@dataclass(slots=True)
class _Track:
    value: int
    element: str
    x: float
    y: float
    height: float
    last_seen: float
    sightings: int = 1
    counted: bool = False


class Templates:
    def __init__(self, path: str = TEMPLATES_PATH) -> None:
        data = np.load(path)
        self.aspects = data["aspects"].astype(np.float32)
        self.glyphs: list[np.ndarray] = []  # each digit at its natural width, GLYPH_H tall
        for digit in range(10):
            width = max(6, int(round(float(self.aspects[digit]) * GLYPH_H)))
            glyph = cv2.resize(data["templates"][digit], (width, GLYPH_H), interpolation=cv2.INTER_AREA)
            self.glyphs.append(glyph.astype(np.float32))


def band_mask(hsv: np.ndarray, element: str) -> np.ndarray:
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    mask = np.zeros(h.shape, bool)
    for low, high in BANDS[element]:
        mask |= (h >= low) & (h <= high)
    return mask & (s >= _MIN_SAT) & (v >= _MIN_VAL)


def find_blobs(mask: np.ndarray, min_h: float, max_h: float) -> tuple[np.ndarray, list[_Blob]]:
    """(label image, digit-height blobs) of a colour mask. A blob may be several fused digits."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    blobs: list[_Blob] = []
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        if not min_h <= h <= max_h or w < 0.15 * h or w > _MAX_DIGITS * h or area < 0.2 * w * h:
            continue
        blobs.append(_Blob(x, y, w, h, index, 0.0))
    return labels, blobs


def rows_of(blobs: list[_Blob]) -> list[list[_Blob]]:
    """Blobs that sit side by side at one height: the pieces of one number."""
    rows: list[list[_Blob]] = []
    for blob in sorted(blobs, key=lambda b: b.x):
        for row in rows:
            last = row[-1]
            tall, short = max(last.h, blob.h), min(last.h, blob.h)
            same_row = abs((last.y + last.h / 2) - (blob.y + blob.h / 2)) <= 0.3 * tall
            gap = blob.x - (last.x + last.w)
            if short >= 0.75 * tall and same_row and -0.35 * tall <= gap <= 0.55 * tall:
                row.append(blob)
                break
        else:
            rows.append([blob])
    return rows


def decode(strip_mask: np.ndarray, templates: Templates) -> tuple[str, float] | None:
    """Digits spelled by a tightly cropped row mask, with the weakest match score. None unless
    digits account for the whole row."""
    height, width = strip_mask.shape
    if height < 6 or width < 3:
        return None
    strip_w = max(4, int(round(width * GLYPH_H / height)))
    strip = cv2.resize(strip_mask.astype(np.uint8) * 255, (strip_w, GLYPH_H), interpolation=cv2.INTER_AREA)
    strip = cv2.copyMakeBorder(strip, 2, 2, 3, 3, cv2.BORDER_CONSTANT, value=0).astype(np.float32) / 255.0

    candidates: list[tuple[float, int, int, int]] = []  # score, left, width, digit
    for digit, glyph in enumerate(templates.glyphs):
        if glyph.shape[1] > strip.shape[1]:
            continue
        profile = cv2.matchTemplate(strip, glyph, cv2.TM_CCOEFF_NORMED).max(axis=0)
        for x in np.flatnonzero(profile >= _MATCH):
            before = profile[x - 1] if x > 0 else -1.0
            after = profile[x + 1] if x + 1 < profile.size else -1.0
            if profile[x] >= before and profile[x] >= after:
                candidates.append((float(profile[x]), int(x), glyph.shape[1], digit))
    candidates.sort(reverse=True)

    chosen: list[tuple[int, int, int, float]] = []  # left, width, digit, score
    for score, left, glyph_w, digit in candidates:
        if all(
            min(left + glyph_w, o_left + o_w) - max(left, o_left) <= 0.3 * min(glyph_w, o_w)
            for o_left, o_w, _, _ in chosen
        ):
            chosen.append((left, glyph_w, digit, score))
    if not chosen or len(chosen) > _MAX_DIGITS:
        return None
    chosen.sort()
    covered = sum(w for _, w, _, _ in chosen)
    if not 0.8 * strip_w <= covered <= 1.2 * strip_w:
        return None  # something in the row is not a digit: overlap or scenery, so no guess
    text = "".join(str(digit) for _, _, digit, _ in chosen)
    weakest = min(score for _, _, _, score in chosen)
    if text.startswith("0") or (len(text) == 1 and weakest < _MATCH_ALONE):
        return None
    return text, weakest


class NumberReader:
    """Feed it frames; it returns each new damage number once."""

    def __init__(self, templates: Templates | None = None, min_sightings: int = 1) -> None:
        self._templates = templates or Templates()
        self._min_sightings = min_sightings
        self._tracks: list[_Track] = []

    def read(self, frame: np.ndarray) -> list[Reading]:
        """Every damage number legible in this frame."""
        height, width = frame.shape[:2]
        x0, y0 = round(_ROI[0] * width), round(_ROI[1] * height)
        x1, y1 = round(_ROI[2] * width), round(_ROI[3] * height)
        hsv = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
        timer = (
            slice(max(0, round(_TIMER[1] * height) - y0), max(0, round(_TIMER[3] * height) - y0)),
            slice(max(0, round(_TIMER[0] * width) - x0), max(0, round(_TIMER[2] * width) - x0)),
        )
        min_h, max_h = _MIN_HEIGHT * height, _MAX_HEIGHT * height

        readings: list[Reading] = []
        for element in BANDS:
            mask = band_mask(hsv, element)
            mask[timer] = False
            labels, blobs = find_blobs(mask, min_h, max_h)
            for row in rows_of(blobs):
                left, right = row[0].x, row[-1].x + row[-1].w
                top = min(b.y for b in row)
                bottom = max(b.y + b.h for b in row)
                if right - left > _MAX_DIGITS * (bottom - top):
                    continue
                members = np.isin(labels[top:bottom, left:right], [b.digit for b in row])
                result = decode(members, self._templates)
                if result is None:
                    continue
                text, score = result
                readings.append(Reading(
                    int(text), element, x0 + (left + right) / 2, y0 + (top + bottom) / 2,
                    float(bottom - top), score,
                ))
        return readings

    def update(self, frame: np.ndarray, now: float) -> list[Reading]:
        """Numbers that became certain with this frame. Each on-screen number is returned once."""
        return self.track(self.read(frame), now)

    def track(self, readings: list[Reading], now: float) -> list[Reading]:
        self._tracks = [t for t in self._tracks if now - t.last_seen <= _TRACK_GAP]
        fresh: list[Reading] = []
        used: set[int] = set()
        for reading in readings:
            match = None
            for index, track in enumerate(self._tracks):
                if index in used or track.value != reading.value or track.element != reading.element:
                    continue
                reach = 2.5 * max(track.height, reading.height)
                if abs(track.x - reading.x) <= reach and abs(track.y - reading.y) <= reach:
                    match = index
                    break
            if match is None:
                self._tracks.append(_Track(
                    reading.value, reading.element, reading.x, reading.y, reading.height, now,
                ))
                track = self._tracks[-1]
                used.add(len(self._tracks) - 1)
            else:
                track = self._tracks[match]
                used.add(match)
                track.x, track.y, track.height, track.last_seen = reading.x, reading.y, reading.height, now
                track.sightings += 1
            if not track.counted and track.sightings >= self._min_sightings:
                track.counted = True
                fresh.append(reading)
        return fresh
