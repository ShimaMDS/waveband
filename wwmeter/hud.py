"""Read the game's HUD from a frame: the boss HP bar and which party slot is on field.

All positions are measured on a 2560x1440 frame and scaled by frame height, anchored to the
horizontal centre (the HUD is centred and scales with height, so this also holds for ultrawide).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import cv2
import numpy as np

_REF_HEIGHT = 1440.0
# Boss HP bar: fill runs from x=906 to x=1666 (centre 1280), rows 77..86 inside a 14 px bar.
_BAR_LEFT, _BAR_RIGHT = 906 - 1280, 1666 - 1280
_BAR_TOP, _BAR_BOTTOM = 77, 87
# Zero HP sits left of the visible fill's start (the bar has a pointed cap), by this share of the
# fill width. Fitted against HP values from the log: see tests/test_hud.py.
_BAR_PAD = 0.0379
# Rows just outside the bar, used to tell the thin bar from orange scenery behind the HUD.
_GUARD_ABOVE, _GUARD_BELOW = (64, 70), (93, 99)


@dataclass(slots=True)
class BossBar:
    fraction: float  # 0..1 of the bar that is filled
    confidence: float  # 0..1, how bar-like the pixels are


def _scale(frame_height: int) -> float:
    return frame_height / _REF_HEIGHT


def bar_rect(width: int, height: int, override: list[float] | None = None) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) of the boss bar's fill area in this frame."""
    if override:
        x0, y0, x1, y1 = override
        return round(x0 * width), round(y0 * height), round(x1 * width), round(y1 * height)
    s = _scale(height)
    cx = width / 2
    return (
        round(cx + _BAR_LEFT * s),
        round(_BAR_TOP * s),
        round(cx + _BAR_RIGHT * s),
        round(_BAR_BOTTOM * s),
    )


def _classify(bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(fill, empty) masks: the bar's orange-to-red fill, and the dark empty track."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    fill = ((h <= 24) | (h >= 172)) & (s >= 140) & (v >= 190)
    empty = v < 140
    return fill, empty


def read_boss_bar(frame: np.ndarray, override: list[float] | None = None) -> BossBar | None:
    """Filled fraction of the boss HP bar, or None when no bar is on screen."""
    height, width = frame.shape[:2]
    x0, y0, x1, y1 = bar_rect(width, height, override)
    if x1 - x0 < 50 or y1 <= y0 or x0 < 0 or x1 > width:
        return None
    fill, empty = _classify(frame[y0:y1, x0:x1])
    filled = fill.mean(axis=0) >= 0.4
    dark = empty.mean(axis=0) >= 0.6
    n = filled.size

    # The fill is one run from the left edge. While the boss is staggered the bar is drawn
    # "shattered", with white shards across it, so columns that are neither fill nor empty track
    # are ignored and the end is where fill stops outnumbering empty track.
    score = np.cumsum(filled.astype(np.int32) - dark.astype(np.int32))
    end = int(np.argmax(score)) + 1
    cap = max(3, n // 100)
    if score[end - 1] < cap or filled[: 3 * cap].mean() < 0.5:
        return None

    # Guard rows: the bar is thin, scenery is not.
    s = _scale(height)
    spill = 0.0
    if not override:
        for top, bottom in (_GUARD_ABOVE, _GUARD_BELOW):
            band = frame[round(top * s) : round(bottom * s), x0 : x0 + end]
            if band.size:
                spill = max(spill, float(_classify(band)[0].mean()))
    if spill > 0.5:
        return None
    pad = _BAR_PAD * n
    clean = 1.0 - float(dark[:end].mean())
    return BossBar(fraction=(end + pad) / (n + pad), confidence=round(clean * (1.0 - spill), 3))


# ---- boss name -------------------------------------------------------------------------------

_TITLE_TOP, _TITLE_BOTTOM, _TITLE_PAD = 18, 66, 56
_LEVEL = re.compile(r"^\s*[Ll][VvYy]\.?\s*([0-9oOlI]{1,3})\s*")
_LEVEL_ALONE = re.compile(r"^\s*[Ll][Vv]\.\s?([1-9][0-9]{0,2})(?![0-9oOlI])")
_TRAILING_JUNK = re.compile(r"[\s\W_]+$", re.UNICODE)
_DIGIT_FIXES = str.maketrans("oOlI", "0011")


def parse_title(text: str, name_readable: bool = True) -> str:
    """'Lv. 10o Crownless: Newborn Desires 、/' -> 'Crownless: Newborn Desires (Lv 100)'.

    With a name that could not be read (``name_readable`` False, or nothing left of it) but a
    level in front, the level alone comes back as '(Lv 100)': the name can come from the game's
    tables, the level of an open-world boss only from the screen. That is what a client in a
    script the reader does not know gives."""
    level = ""
    match = _LEVEL.match(text)
    well_formed = _LEVEL_ALONE.match(text)
    if match:
        level = match.group(1).translate(_DIGIT_FIXES)
        text = text[match.end():]
    name = _TRAILING_JUNK.sub("", text).strip()
    name = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[:,])(?=\S)", " ", name)
    if len(name) < 2 or not name_readable:
        # only a level read cleanly counts on its own: there is no name to vouch for the reading
        return f"(Lv {well_formed.group(1)})" if well_formed else ""
    return f"{name} (Lv {level})" if level else name


def read_boss_title(frame: np.ndarray, ocr) -> str:
    """OCR the name above the boss bar. ``ocr`` is a RapidOCR engine."""
    height, width = frame.shape[:2]
    x0, _, x1, _ = bar_rect(width, height)
    s = _scale(height)
    pad = round(_TITLE_PAD * s)
    crop = frame[round(_TITLE_TOP * s) : round(_TITLE_BOTTOM * s), max(0, x0 - pad) : x1 + pad]
    if crop.size == 0:
        return ""
    result, _ = ocr(crop, use_det=False, use_cls=False)
    if not result:
        return ""
    text, score = result[0][-2], float(result[0][-1])
    return parse_title(text, name_readable=score >= 0.6)
