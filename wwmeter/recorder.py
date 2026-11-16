"""Record a fight: game frames plus the decoded log, timestamped on one clock.

The recordings are what the screen readers are tuned and regression-tested against.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time

import cv2

from .capture import GameCapture
from .config import ROOT, Config
from .logtail import LogTail


class _FrameWriter(threading.Thread):
    def __init__(self, quality: int) -> None:
        super().__init__(daemon=True)
        self.jobs: queue.Queue = queue.Queue(maxsize=64)
        self._quality = quality
        self.dropped = 0

    def run(self) -> None:
        while True:
            job = self.jobs.get()
            if job is None:
                return
            path, frame = job
            cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, self._quality])

    def submit(self, path: str, frame) -> None:
        try:
            self.jobs.put_nowait((path, frame))
        except queue.Full:
            self.dropped += 1


def record(
    cfg: Config,
    seconds: float = 360.0,
    fps: float = 12.0,
    idle_fps: float = 0.5,
    quality: int = 88,
    out_dir: str | None = None,
    max_wait: float = 2400.0,
) -> str:
    """Record until ``seconds`` of game-focused time have been captured. Returns the folder.

    Frames are written at ``fps`` while the game is the foreground window and at ``idle_fps``
    otherwise, so time spent reading instructions does not eat the budget. ``max_wait`` bounds
    the total wall-clock time in case the game never gets focus.
    """
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = out_dir or os.path.join(ROOT, "recordings", stamp)
    frames_dir = os.path.join(out_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    capture = GameCapture(cfg.capture_backend)
    tail = LogTail(cfg.log_path)
    writers = [_FrameWriter(quality) for _ in range(3)]
    for writer in writers:
        writer.start()

    focused_time = 0.0
    frames = 0
    last_frame_at = 0.0
    last_status = time.monotonic()
    last_tick = time.monotonic()
    started = time.time()
    print(f"recording to {out_dir}", flush=True)
    print(f"capture backend: {capture.backend}; log: {cfg.log_path}", flush=True)

    with (
        open(os.path.join(out_dir, "log.txt"), "w", encoding="utf-8") as log_out,
        open(os.path.join(out_dir, "frames.csv"), "w", encoding="utf-8") as index_out,
    ):
        index_out.write("file,epoch,focused\n")
        try:
            deadline = time.monotonic() + max_wait
            while focused_time < seconds and time.monotonic() < deadline:
                now_mono = time.monotonic()
                elapsed, last_tick = now_mono - last_tick, now_mono
                focused = capture.game_focused()
                if focused:
                    focused_time += elapsed

                now = time.time()
                for line in tail.poll():
                    log_out.write(f"{now:.3f}\t{line}\n")

                interval = 1.0 / (fps if focused else idle_fps)
                if now_mono - last_frame_at >= interval:
                    frame = capture.grab()
                    if frame is not None:
                        last_frame_at = now_mono
                        name = f"{frames:06d}.jpg"
                        writers[frames % len(writers)].submit(os.path.join(frames_dir, name), frame)
                        index_out.write(f"{name},{time.time():.3f},{int(focused)}\n")
                        frames += 1

                if now_mono - last_status >= 15.0:
                    last_status = now_mono
                    log_out.flush()
                    index_out.flush()
                    print(
                        f"  {focused_time:5.0f}/{seconds:.0f}s of game time recorded, {frames} frames"
                        + ("" if capture.game_running() else "  (game window not found)"),
                        flush=True,
                    )
                time.sleep(0.004)
        except KeyboardInterrupt:
            print("stopped early", flush=True)
        finally:
            for writer in writers:
                writer.jobs.put(None)
            for writer in writers:
                writer.join(timeout=30)
            tail.close()
            capture.close()

    meta = {
        "started": started,
        "ended": time.time(),
        "focused_seconds": round(focused_time, 1),
        "frames": frames,
        "dropped": sum(w.dropped for w in writers),
        "fps": fps,
        "backend": capture.backend,
    }
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    print(f"done: {frames} frames, {meta['dropped']} dropped, {focused_time:.0f}s -> {out_dir}", flush=True)
    return out_dir
