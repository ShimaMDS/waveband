"""Grade the damage-number reader against exact damage from the log.

    python tools/grade_number_reader.py <recording> <first_frame> <last_frame>

Needs a recording of a fight whose enemy logs its HP, so the true damage in each second is known.
The frames are read once, then replayed at several frame rates and confirmation rules.
"""

from __future__ import annotations

import csv
import os
import statistics
import sys
import time

import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wwmeter.dmgnum import NumberReader  # noqa: E402
from wwmeter.logparse import parse_line  # noqa: E402


def main() -> None:
    folder, first, last = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    with open(os.path.join(folder, "frames.csv"), encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if first <= int(r["file"][:6]) <= last]
    t_start, t_end = float(rows[0]["epoch"]), float(rows[-1]["epoch"])
    recorded_fps = len(rows) / (t_end - t_start)

    truth: dict[int, float] = {}
    previous = None
    with open(os.path.join(folder, "log.txt"), encoding="utf-8") as fh:
        for line in fh:
            stamp, _, text = line.rstrip("\n").partition("\t")
            try:
                at = float(stamp)
            except ValueError:
                continue
            event = parse_line(text)
            if event and event.sub == "Part" and "LifeValue" in event.fields:
                life = float(event.fields["LifeValue"])
                if previous is not None and previous > life and t_start <= at <= t_end:
                    truth[int(at - t_start)] = truth.get(int(at - t_start), 0) + (previous - life)
                previous = life
    true_total = sum(truth.values())

    reader = NumberReader()
    per_frame = []
    started = time.time()
    for row in rows:
        frame = cv2.imread(os.path.join(folder, "frames", row["file"]))
        per_frame.append((float(row["epoch"]), reader.read(frame)))
    cost = (time.time() - started) / len(rows) * 1000
    print(f"{t_end - t_start:.0f} s, {len(rows)} frames at {recorded_fps:.0f}/s, "
          f"{cost:.0f} ms per frame incl. loading, true damage {true_total:,.0f}")

    for step in (1, 2):
        for need in (1, 2, 3):
            tracker = NumberReader(templates=reader._templates, min_sightings=need)
            got: dict[int, float] = {}
            values = []
            by_element: dict[str, int] = {}
            for at, readings in per_frame[::step]:
                for reading in tracker.track(readings, at):
                    got[int(at - t_start)] = got.get(int(at - t_start), 0) + reading.value
                    values.append(reading.value)
                    by_element[reading.element] = by_element.get(reading.element, 0) + reading.value
            total = sum(values)
            ratios = []
            for window in range(0, int(t_end - t_start), 5):
                want = sum(truth.get(s, 0) for s in range(window, window + 5))
                have = sum(got.get(s, 0) for s in range(window, window + 5))
                if want > 20000:
                    ratios.append(have / want)
            spread = (f"per 5 s: median {statistics.median(ratios):.2f}, "
                      f"range {min(ratios):.2f}-{max(ratios):.2f}") if ratios else ""
            print(f"  {recorded_fps / step:4.0f} frames/s, seen {need}x: {len(values):4d} numbers, "
                  f"{total:>9,} = {total / true_total:6.1%} of true, biggest {max(values, default=0):,}; "
                  f"{spread}; {by_element}")


if __name__ == "__main__":
    main()
