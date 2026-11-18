"""Live readers: one thread follows the log, one watches the screen. Both feed the tracker."""

from __future__ import annotations

import os
import threading
from collections import Counter
import time

import numpy as np

from . import hud
from .capture import GameCapture
from .config import Config
from .logparse import parse_line
from .logtail import LogTail, scan_file
from .tracker import Tracker

# Lines that say which map the player is in and which enemies are spawned. The meter needs them
# to look an enemy's HP up, and they were written before the fight, often before the meter started.
_CONTEXT = ("JoinSceneNotify", "实体详细数据", "UpdatePartInfo")
_CONTEXT_MAX_AGE = 3 * 3600.0
_BAR_CONFIDENCE = 0.8
_TITLE_RETRY = 4.0
_TITLE_READS = 5


class ScreenReader:
    """What is done with each frame. Shared by the live engine and by replays of recordings."""

    def __init__(self, cfg: Config, tracker: Tracker) -> None:
        self._cfg = cfg
        self._tracker = tracker
        self._title_tried_at = 0.0
        self._title_fight: int | None = None
        self._title_reads: Counter = Counter()
        self._ocr = None
        self._ocr_failed = False
        self._numbers = None
        self._numbers_failed = False
        self._height: int | None = None  # the game's full height, for a frame that is a strip

    def strip(self) -> float | None:
        """How much of the game's height, from the top, a frame needs: the strip with the boss's
        name and bar, or (None) the whole frame while damage numbers are read off it."""
        if self._cfg.read_numbers and not self._numbers_failed:
            return None
        return hud.strip_share(self._cfg.boss_bar)

    def process(self, frame: np.ndarray, now: float, height: int | None = None) -> None:
        """``frame`` may be the top strip only (``strip``); ``height`` is then the game's full
        height."""
        whole = height is None or frame.shape[0] >= height
        if (whole and self._cfg.read_numbers and not self._numbers_failed
                and self._tracker.wants_numbers(now)):
            self._read_numbers(frame, now)
        self._height = height
        bar = hud.read_boss_bar(frame, self._cfg.boss_bar, height)
        if bar is None or bar.confidence < _BAR_CONFIDENCE:
            self._tracker.on_boss(now, None)
            return
        self._tracker.on_boss(now, bar.fraction)
        fight = self._tracker.current_id()
        if fight != self._title_fight:
            self._title_fight, self._title_reads = fight, Counter()
        # One reading can pick up stray marks beside the name, so read it a few times over the
        # fight and keep whichever spelling comes up most.
        wanted = fight is not None and sum(self._title_reads.values()) < _TITLE_READS
        if wanted and now - self._title_tried_at >= _TITLE_RETRY:
            self._title_tried_at = now
            title = self._read_title(frame)
            if title:
                self._title_reads[title] += 1
                self._tracker.set_title(self._title_reads.most_common(1)[0][0], replace=True)

    def _read_numbers(self, frame: np.ndarray, now: float) -> None:
        try:
            if self._numbers is None:
                from .dmgnum import NumberReader

                self._numbers = NumberReader()
            for reading in self._numbers.update(frame, now):
                self._tracker.on_damage(now, reading.value)
        except Exception as exc:  # noqa: BLE001 - optional reader; say why and carry on without it
            self._numbers_failed = True
            self._tracker.set_status(note=f"Number reading is off: {exc}")

    def _read_title(self, frame: np.ndarray) -> str:
        if self._ocr_failed:
            return ""
        try:
            if self._ocr is None:
                from .ocr import TextReader

                self._ocr = TextReader()
            return hud.read_boss_title(frame, self._ocr, self._height)
        except Exception:  # noqa: BLE001 - the title is a nicety; never let OCR break the meter
            self._ocr_failed = True
            return ""


class Engine:
    def __init__(self, cfg: Config, tracker: Tracker) -> None:
        self._cfg = cfg
        self._tracker = tracker
        self._stop = threading.Event()
        self._threads = [
            threading.Thread(target=self._guard, args=(self._log_loop,), name="log", daemon=True),
            threading.Thread(target=self._guard, args=(self._screen_loop,), name="screen", daemon=True),
        ]

    def start(self) -> None:
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=3)

    def _guard(self, loop) -> None:
        """Keep a reader alive: report the failure on the overlay and try again."""
        while not self._stop.is_set():
            try:
                loop()
                return
            except Exception as exc:  # noqa: BLE001 - surfaced to the user, then retried
                self._tracker.set_status(note=f"{loop.__name__.strip('_')} stopped: {exc}. Retrying.")
                self._stop.wait(3.0)
                self._tracker.set_status(note="")

    def _catch_up(self) -> None:
        """Take the map and spawn lines from the log as it stands (and from the file it was last
        rotated out of), so an enemy that spawned before the meter started is still known."""
        folder = os.path.dirname(self._cfg.log_path)
        try:
            backups = [
                os.path.join(folder, name) for name in os.listdir(folder)
                if name.startswith("Client-backup") and name.endswith(".log")
            ]
            newest = max(backups, key=os.path.getmtime, default=None)
            if newest is not None and time.time() - os.path.getmtime(newest) > _CONTEXT_MAX_AGE:
                newest = None
        except OSError:
            newest = None
        for path in (newest, self._cfg.log_path):
            if path is None:
                continue
            for line in scan_file(path, _CONTEXT):
                event = parse_line(line)
                if event is not None:
                    self._tracker.on_context(event)

    def _log_loop(self) -> None:
        path = self._cfg.log_path
        tail = LogTail(path)
        last_status = 0.0
        readable = unreadable = 0
        try:
            caught_up = False
            while not self._stop.is_set():
                now = time.time()
                if self._cfg.log_path != path:
                    # another log folder was chosen on the settings page: follow that log
                    tail.close()
                    path = self._cfg.log_path
                    tail = LogTail(path)
                    caught_up = False
                    readable = unreadable = 0
                lines = tail.poll()
                if not caught_up:
                    # the tail now sits at the end of the log, so nothing falls between the reads
                    caught_up = True
                    self._catch_up()
                for line in lines:
                    if line.startswith("["):
                        readable += 1
                    else:
                        unreadable += 1
                    event = parse_line(line)
                    if event is not None:
                        self._tracker.on_log(event, now)
                self._tracker.tick(now)
                if now - last_status >= 1.0:
                    last_status = now
                    self._tracker.set_status(log=os.path.isfile(self._cfg.log_path))
                    if readable + unreadable >= 200:
                        garbled = unreadable > 4 * readable
                        self._tracker.set_status(
                            note="Can't make sense of the game's log. Its format may have changed."
                            if garbled else ""
                        )
                        readable = unreadable = 0
                self._stop.wait(0.05)
        finally:
            tail.close()

    def _screen_loop(self) -> None:
        capture = GameCapture(self._cfg.capture_backend)
        reader = ScreenReader(self._cfg, self._tracker)
        # number reading needs to see each number at least once while it is on screen
        rate = max(self._cfg.capture_fps, 12) if self._cfg.read_numbers else self._cfg.capture_fps
        interval = 1.0 / max(1, rate)
        frames = 0
        window_start = time.monotonic()
        last_grab = 0.0
        try:
            while not self._stop.is_set():
                tick = time.monotonic()
                focused = capture.game_focused()
                if focused and tick - last_grab >= interval:
                    frame = capture.grab(reader.strip())
                    if frame is not None:
                        last_grab = tick
                        frames += 1
                        reader.process(frame, time.time(), capture.height)
                if tick - window_start >= 1.0:
                    self._tracker.set_status(
                        game=capture.game_running(),
                        focused=focused,
                        screen=focused and frames > 0 or not focused and capture.game_running(),
                        backend=capture.backend,
                        fps=frames / (tick - window_start),
                    )
                    frames, window_start = 0, tick
                self._stop.wait(0.01 if focused else 0.25)
        finally:
            capture.close()
