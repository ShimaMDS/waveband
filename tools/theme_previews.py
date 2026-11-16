"""Pictures of every theme, for looking them over: ``assets\\themes\\``.

    .venv\\Scripts\\python tools\\theme_previews.py

For each theme the meter (``<theme>-meter.png``) and the dashboard's Settings page
(``<theme>-dashboard.png``), and ``themes-overview.png`` with all of them, each meter beside its
dashboard. Taken from the demo meter with its settings in a temp folder, as ``screenshots.py``
does, so nothing real appears.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import screenshots  # noqa: E402

from wwmeter.settings import available_themes, theme_label  # noqa: E402

OUT = os.path.join(ROOT, "assets", "themes")


def overview(themes: list[str]) -> None:
    from PIL import Image, ImageDraw, ImageFont

    font_path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "bahnschrift.ttf")
    title_font = ImageFont.truetype(font_path, 26) if os.path.isfile(font_path) else ImageFont.load_default()
    rows = []
    for name in themes:
        meter = Image.open(os.path.join(OUT, f"{name}-meter.png")).convert("RGB")
        board = Image.open(os.path.join(OUT, f"{name}-dashboard.png")).convert("RGB")
        board = board.resize((round(board.width * 0.5), round(board.height * 0.5)), Image.LANCZOS)
        rows.append((name, meter, board))
    margin, gap, label_h = 24, 20, 40
    width = margin * 2 + max(m.width for _, m, _ in rows) + gap + max(b.width for _, _, b in rows)
    height = margin + sum(label_h + max(m.height, b.height) + gap for _, m, b in rows) + margin - gap
    sheet = Image.new("RGB", (width, height), (12, 14, 18))
    draw = ImageDraw.Draw(sheet)
    y = margin
    meter_w = max(m.width for _, m, _ in rows)
    for name, meter, board in rows:
        label = theme_label(name) + ("  (default)" if name == "wuwa" else "")
        draw.text((margin, y + 4), label, font=title_font, fill=(236, 238, 242))
        y += label_h
        sheet.paste(meter, (margin, y))
        sheet.paste(board, (margin + meter_w + gap, y))
        y += max(meter.height, board.height) + gap
    sheet.save(os.path.join(OUT, "themes-overview.png"))


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    themes = available_themes()
    screenshots.OUT = OUT
    shots = []
    for name in themes:
        shots.append((f"overlay-{name}.png", f"?view=overlay&theme={name}", 440, 400))
        shots.append((f"{name}-dashboard.png", f"?view=full&theme={name}#settings-rows", 1400, 760))
    screenshots._session({}, shots, warm=12.0)
    for name in themes:  # the meter pictures were trimmed to the meter on the way
        os.replace(os.path.join(OUT, f"overlay-{name}.png"), os.path.join(OUT, f"{name}-meter.png"))
    overview(themes)
    print("wrote assets/themes/:", ", ".join(sorted(os.listdir(OUT))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
