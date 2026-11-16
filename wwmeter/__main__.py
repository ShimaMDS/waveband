"""Command line entry point: ``python -m wwmeter <command>``."""

from __future__ import annotations

import argparse
import sys

from . import config


def _decode(path: str, out: str | None, keep_noise: bool) -> int:
    import os

    from . import logcodec
    from .logtail import is_noise

    out = out or os.path.join(
        config.ROOT, os.path.splitext(os.path.basename(path))[0] + ".decoded.txt"
    )
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        print(f"can't read {path}: {exc}")
        return 1
    lines = data.translate(logcodec.detect_table(data[:16])).splitlines()
    kept = [line for line in lines if line.strip() and (keep_noise or not is_noise(line))]
    with open(out, "wb") as fh:
        fh.write(b"\r\n".join(kept) + b"\r\n")
    print(f"{len(kept):,} of {len(lines):,} lines written to {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    if sys.stdout is None or sys.stderr is None:
        # no console (pythonw from run.bat, or the packaged .exe): keep a log file instead
        import os

        stream = open(config.LOG_PATH, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = stream
    else:
        # Skill and enemy names are Chinese. Sent to a file or a pipe, Windows encodes output
        # in the system code page, which has no such characters: print "?" instead of failing.
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(errors="replace")

    from . import __version__

    parser = argparse.ArgumentParser(
        prog=config.NAME, description=f"{config.NAME}: a passive damage meter for Wuthering Waves."
    )
    parser.add_argument("--version", action="version", version=f"{config.NAME} {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("selftest", help="check what the meter depends on and write selftest.txt")

    run = sub.add_parser("run", help="start the meter and its overlay (default)")
    run.add_argument("--demo", action="store_true", help="show a made-up fight instead of the game")
    run.add_argument("--no-overlay", action="store_true", help="serve the dashboard only")

    rec = sub.add_parser("record", help="record frames + log of a fight for calibration")
    rec.add_argument("--seconds", type=float, default=360.0, help="game-focused seconds to record")
    rec.add_argument("--fps", type=float, default=12.0)
    rec.add_argument("--max-wait", type=float, default=2400.0, help="give up after this many seconds")

    rep = sub.add_parser("replay", help="run a recording through the meter and print the result")
    rep.add_argument("folder")
    rep.add_argument("--no-frames", action="store_true", help="log only, skip the screen readers")
    rep.add_argument("--frame-step", type=int, default=1, help="use every Nth frame")
    rep.add_argument("--no-life", action="store_true", help="ignore logged HP (tests the HP-bar fallback)")

    dec = sub.add_parser("decode", help="write a readable copy of a Client.log")
    dec.add_argument("file", nargs="?", help="log to decode (default: the live Client.log)")
    dec.add_argument("--out", help="output file (default: <name>.decoded.txt in this folder)")
    dec.add_argument("--all", action="store_true", help="keep the rendering warnings too")

    upd = sub.add_parser(
        "update", help="fetch the game's tables for the installed version and rebuild the boss HP file",
        description="After a game patch: download the game's config tables for the installed "
        "version (about 260 MB, deleted afterwards) and rebuild data\\enemy_hp.json from them.",
    )
    upd.add_argument("--branch", help="game version to fetch, e.g. 3.8 (default: the installed game's)")
    upd.add_argument(
        "--languages", help="'all', or codes with commas between, e.g. en,ja (default: English, "
        "the game's language and the one in the settings; the others keep the names they had)",
    )
    upd.add_argument("--force", action="store_true", help="rebuild even when the file is up to date")
    upd.add_argument("--keep-downloads", action="store_true", help="leave the downloaded tables in the cache folder")
    upd.add_argument("--cache", help="folder to download into (kept afterwards)")
    upd.add_argument("--out", help="file to write (default: data\\enemy_hp.json)")
    upd.add_argument("--status-file", help=argparse.SUPPRESS)  # where a running meter reads the progress

    args = parser.parse_args(argv)
    cfg = config.load()

    if args.command == "update":
        from .update import main as run_update

        return run_update(cfg, args)

    if args.command == "decode":
        return _decode(args.file or cfg.log_path, args.out, args.all)

    if args.command == "replay":
        from .replay import print_report, replay

        print_report(replay(cfg, args.folder, not args.no_frames, args.frame_step, not args.no_life))
        return 0

    if args.command == "record":
        from .recorder import record

        record(cfg, seconds=args.seconds, fps=args.fps, max_wait=args.max_wait)
        return 0

    if args.command == "selftest":
        from .selftest import run as run_selftest

        return run_selftest(cfg)

    from .app import run as run_app

    return run_app(
        cfg,
        demo=getattr(args, "demo", False),
        overlay=not getattr(args, "no_overlay", False),
    )


if __name__ == "__main__":
    sys.exit(main())
