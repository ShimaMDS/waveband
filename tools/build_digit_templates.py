"""Rebuild data/digits.npz, the digit shapes the damage-number reader matches against.

    python tools/build_digit_templates.py samples.pkl [--bootstrap]

``samples.pkl`` is a list of (BGR crop of one damage number, its digits as text, source). The
crops come from recordings (``python -m wwmeter record``) labelled by a general OCR engine.

Each crop's fill is masked by colour and split into blobs. With ``--bootstrap`` (no templates
yet) a crop is used when it has exactly one digit-sized blob per digit of its label. Otherwise a
crop is used when the current templates read it the same as its label, which admits many more
samples, including crops with stray scenery in them. The blobs filed under each digit are
averaged into the new templates.
"""

from __future__ import annotations

import collections
import os
import pickle
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from wwmeter import dmgnum  # noqa: E402


def read_crop(crop: np.ndarray, templates, bootstrap: bool, label: str):
    """Blobs spelling ``label`` in this crop as [(mask, blob)], or None."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    min_h = 0.35 * crop.shape[0]
    for element in dmgnum.BANDS:
        mask = dmgnum.band_mask(hsv, element)
        if bootstrap:
            count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
            parts = sorted(
                (int(stats[i][0]), i) for i in range(1, count)
                if stats[i][3] >= min_h and stats[i][4] >= 0.2 * stats[i][2] * stats[i][3]
            )
            heights = [stats[i][3] for _, i in parts]
            if len(parts) == len(label) and max(heights) <= 1.35 * min(heights):
                out = []
                for _, i in parts:
                    x, y, w, h, _ = stats[i]
                    out.append(labels[y : y + h, x : x + w] == i)
                return out
            continue
        labels, blobs = dmgnum.find_blobs(mask, min_h, crop.shape[0])
        singles = [b for b in blobs if b.w <= 1.1 * b.h]
        for row in dmgnum.rows_of(singles):
            if len(row) != len(label):
                continue
            left, right = row[0].x, row[-1].x + row[-1].w
            top, bottom = min(b.y for b in row), max(b.y + b.h for b in row)
            members = np.isin(labels[top:bottom, left:right], [b.digit for b in row])
            decoded = dmgnum.decode(members, templates)
            if decoded is not None and decoded[0] == label:
                return [labels[b.y : b.y + b.h, b.x : b.x + b.w] == b.digit for b in row]
    return None


def main() -> None:
    samples = pickle.load(open(sys.argv[1], "rb"))
    bootstrap = "--bootstrap" in sys.argv
    templates = None if bootstrap else dmgnum.Templates()
    glyphs: dict[str, list[tuple[np.ndarray, float]]] = collections.defaultdict(list)
    used = total = 0
    for crop, text, _ in samples:
        if text.startswith("+"):
            continue
        total += 1
        parts = read_crop(crop, templates, bootstrap, text)
        if parts is None:
            continue
        used += 1
        for part, digit in zip(parts, text):
            glyph = cv2.resize(
                part.astype(np.uint8) * 255, (dmgnum.GLYPH_W, dmgnum.GLYPH_H), interpolation=cv2.INTER_AREA
            )
            glyphs[digit].append((glyph, part.shape[1] / part.shape[0]))

    shapes = np.zeros((10, dmgnum.GLYPH_H, dmgnum.GLYPH_W), np.float32)
    aspects = np.zeros(10, np.float32)
    for digit in "0123456789":
        got = glyphs.get(digit, [])
        if not got:
            raise SystemExit(f"no samples for digit {digit}")
        shapes[int(digit)] = np.mean([g for g, _ in got], axis=0) / 255.0
        aspects[int(digit)] = float(np.median([a for _, a in got]))
    out = os.path.join(ROOT, "data", "digits.npz")
    np.savez_compressed(out, templates=shapes, aspects=aspects)
    print(f"{used} of {total} crops used; glyphs per digit:", {d: len(glyphs[d]) for d in "0123456789"})
    print("aspects:", [round(float(a), 2) for a in aspects], "->", out)


if __name__ == "__main__":
    main()
