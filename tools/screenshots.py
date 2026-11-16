"""Take the README's pictures from the demo meter.

    .venv\\Scripts\\python tools\\screenshots.py

Starts the demo meter (made-up fights, no game needed) on a spare port, with its settings in a
temp folder so no real fight, session, path or name of yours can appear, renders the overlay and
the dashboard's pages with ``render_page.py``, and writes them to ``docs\\images\\``. Run it again
whenever the look changes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "images")
RENDER = os.path.join(ROOT, "tools", "render_page.py")
PORT = 5057  # not 5060 or 5061: browsers refuse those (SIP)

# (file, page, width, height)
SHOTS = [
    ("overlay.png", "?view=overlay", 440, 400),
    ("overlay-classic.png", "?view=overlay&theme=classic", 440, 400),
    ("dashboard-fights.png", "?view=full#fights", 1400, 860),
    ("dashboard-settings.png", "?view=full#settings-rows", 1400, 760),
    ("dashboard-changes.png", "?view=full#changes", 1400, 760),
]
# the same, with the one-line meter switched on
COMPACT = [("overlay-one-line.png", "?view=overlay", 440, 120)]


def _wait_for(url: str, seconds: float = 30.0) -> None:
    end = time.time() + seconds
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=2).read()
            return
        except OSError:
            time.sleep(0.5)
    raise SystemExit(f"The demo meter did not answer at {url}")


def _trim(path: str, margin: int = 6) -> None:
    """Cut the empty page around the meter: everything the colour of the bottom-right corner."""
    from PIL import Image, ImageChops

    image = Image.open(path).convert("RGB")
    ground = Image.new("RGB", image.size, image.getpixel((image.width - 1, image.height - 1)))
    box = ImageChops.difference(image, ground).convert("L").point(lambda v: 255 if v > 12 else 0).getbbox()
    if box:
        x0, y0, x1, y1 = box
        image.crop((max(0, x0 - margin), max(0, y0 - margin), min(image.width, x1 + margin),
                    min(image.height, y1 + margin))).save(path)


def _session(settings: dict, shots: list, warm: float) -> None:
    folder = tempfile.mkdtemp(prefix="waveband-shots-")
    try:
        config = os.path.join(folder, "config.json")
        with open(config, "w", encoding="utf-8") as fh:
            # a made-up game folder, so the settings page shows no real path
            json.dump({"port": PORT, "log_dir": r"C:\Games\Wuthering Waves\Client\Saved\Logs", **settings}, fh)
        env = dict(os.environ, WWMETER_CONFIG=config)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        meter = subprocess.Popen([sys.executable, "-m", "wwmeter", "run", "--demo", "--no-overlay"], cwd=ROOT, env=env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        try:
            base = f"http://127.0.0.1:{PORT}/"
            _wait_for(base)
            time.sleep(warm)  # let the made-up fight build up some figures
            for name, page, width, height in shots:
                subprocess.run([sys.executable, RENDER, base + page, os.path.join(OUT, name), str(width), str(height)],
                               check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
                if name.startswith("overlay"):
                    _trim(os.path.join(OUT, name))
                print("wrote docs/images/" + name)
        finally:
            meter.terminate()
            meter.wait(10)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    _session({}, SHOTS, warm=14.0)
    _session({"compact": True}, COMPACT, warm=10.0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
