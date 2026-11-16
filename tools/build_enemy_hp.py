"""Build data\\enemy_hp.json with names in every language, and keep the downloaded tables.

The work is done by ``wwmeter update`` (``wwmeter\\update.py``, which says where the tables come
from and what is boiled down from them); a tester's meter runs the same thing from its tray menu.
This is the developer's way in. It differs in three things: every language's text table is
fetched (13 of them, about 900 MB with the tables), the file is rebuilt even when it is already
for this version, and the downloads stay in the cache folder, where ``boss_coverage.py`` and the
other tools read them.

    .venv\\Scripts\\python tools\\build_enemy_hp.py            # version read from the launcher
    .venv\\Scripts\\python tools\\build_enemy_hp.py --branch 3.8
    .venv\\Scripts\\python tools\\build_enemy_hp.py --languages en,ja   # fetch fewer languages
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wwmeter import config, update  # noqa: E402
from wwmeter.update import components  # noqa: E402,F401 - boss_coverage.py takes it from here


def installed_version() -> str | None:
    """Game version from the launcher's own record, e.g. '3.8.0'."""
    return update.installed_version(config.load().log_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--branch", help="game version as major.minor, e.g. 3.8 (default: the installed one)")
    parser.add_argument("--cache", help="folder for the downloaded tables (default: under the temp folder)")
    parser.add_argument("--out", default=update.ENEMY_HP_PATH)
    parser.add_argument(
        "--languages", default="all",
        help="languages to fetch names in, comma-separated (default: all; English is always "
        "fetched, and a language not fetched keeps the names the file had for it)",
    )
    args = parser.parse_args(argv)
    cfg = config.load()
    try:
        print(update.run(
            cfg.log_dir, branch=args.branch or "", languages=args.languages, out=args.out,
            cache=args.cache or "", keep=True, force=True,
        ))
    except update.Failed as why:
        print(why)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
