"""Collect labelled damage-number crops from recordings, for building the digit templates.

    python tools/collect_number_samples.py out.pkl <recording> <first> <last> <step> [more quads...]

A general OCR engine (RapidOCR) finds and reads the numbers; it is too slow and too error-prone
to use live, but its confident readings make good labels. Each sample is
(BGR crop with padding, digits as text, source frame). Healing numbers keep their leading "+".

The samples the shipped templates were built from are in data/number_samples.pkl:
    recordings/20261115-091128  frames 1400-3600 step 7   (glacio, spectro, heals)
    recordings/20261115-100536  frames 150-420  step 1    (fusion, spectro)
"""

from __future__ import annotations

import csv
import os
import pickle
import re
import sys

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR

_ROI = (0.25, 0.09, 0.86, 0.86)  # same play area the live reader searches
_TIMER = (0.40, 0.105, 0.60, 0.175)


def main() -> None:
    out = sys.argv[1]
    jobs = [sys.argv[i : i + 4] for i in range(2, len(sys.argv), 4)]
    ocr = RapidOCR()
    samples = []
    for folder, first, last, step in jobs:
        with open(os.path.join(folder, "frames.csv"), encoding="utf-8") as fh:
            rows = [r for r in csv.DictReader(fh) if r["focused"] == "1"]
        rows = [r for r in rows if int(first) <= int(r["file"][:6]) <= int(last)][:: int(step)]
        for row in rows:
            frame = cv2.imread(os.path.join(folder, "frames", row["file"]))
            height, width = frame.shape[:2]
            x0, y0 = round(_ROI[0] * width), round(_ROI[1] * height)
            x1, y1 = round(_ROI[2] * width), round(_ROI[3] * height)
            roi = frame[y0:y1, x0:x1].copy()
            roi[round(_TIMER[1] * height) - y0 : round(_TIMER[3] * height) - y0,
                round(_TIMER[0] * width) - x0 : round(_TIMER[2] * width) - x0] = 0
            small = cv2.resize(roi, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
            result, _ = ocr(small, use_cls=False)
            for box, text, score in result or []:
                text = text.strip().replace(",", "").replace(" ", "")
                if float(score) < 0.7 or not re.fullmatch(r"\+?\d{1,6}", text):
                    continue
                points = np.asarray(box, dtype=np.float32) * 2
                bx0, by0 = points[:, 0].min(), points[:, 1].min()
                bx1, by1 = points[:, 0].max(), points[:, 1].max()
                pad = 0.25 * (by1 - by0)
                crop = roi[int(max(0, by0 - pad)) : int(min(roi.shape[0], by1 + pad)),
                           int(max(0, bx0 - pad)) : int(min(roi.shape[1], bx1 + pad))]
                samples.append((crop.copy(), text, f"{os.path.basename(os.path.normpath(folder))}/{row['file']}"))
        print(f"{folder}: {len(rows)} frames, {len(samples)} samples so far", flush=True)
    with open(out, "wb") as fh:
        pickle.dump(samples, fh)
    print(f"{len(samples)} samples -> {out}")


if __name__ == "__main__":
    main()
