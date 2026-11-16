"""Pictures of every theme, for looking them over: ``assets\\themes\\``.

    .venv\\Scripts\\python tools\\theme_previews.py

For each theme the meter (``<theme>-meter.png``) and the dashboard's Settings page
(``<theme>-dashboard.png``), drawn twice as sharp as the screen shows them, and
``themes-overview.png``: all of them in a grid, two themes to a row, each meter beside its
dashboard, as large as stays under 20 MB. (``themes-overview-vertical.png`` is the first,
one-long-column layout, kept as it was; this script leaves it alone.)

Taken from the demo meter with its settings in a temp folder, as ``screenshots.py`` does, so
nothing real appears.
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
ZOOM = 2.0  # the pictures' sharpness: device pixels per CSS pixel
LIMIT = 19.5 * 1024 * 1024  # the grid stays under 20 MB
GROUND = (12, 14, 18)
LABEL = (236, 238, 242)


def _font(size: int):
    from PIL import ImageFont

    path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "bahnschrift.ttf")
    return ImageFont.truetype(path, size) if os.path.isfile(path) else ImageFont.load_default()


def _label(name: str) -> str:
    return theme_label(name) + ("  (default)" if name == "wuwa" else "")


def _pictures(themes: list[str]):
    from PIL import Image

    return [(name, Image.open(os.path.join(OUT, f"{name}-meter.png")).convert("RGB"),
             Image.open(os.path.join(OUT, f"{name}-dashboard.png")).convert("RGB")) for name in themes]


def _sheet(pictures, columns: int, scale: float, board_scale: float):
    """Each theme as a cell: its name over its meter and its dashboard side by side. ``scale``
    sizes the whole sheet; the dashboard is drawn ``board_scale`` times the meter's scale."""
    from PIL import Image, ImageDraw

    def sized(image, factor):
        return image.resize((max(1, round(image.width * factor)), max(1, round(image.height * factor))), Image.LANCZOS)

    cells = [(name, sized(meter, scale), sized(board, scale * board_scale)) for name, meter, board in pictures]
    unit = ZOOM * scale  # pixels per CSS pixel on the sheet
    margin, gap, label_h = round(24 * unit), round(20 * unit), round(40 * unit)
    meter_w = max(m.width for _, m, _ in cells)
    cell_w = meter_w + gap + max(b.width for _, _, b in cells)
    cell_h = label_h + max(max(m.height, b.height) for _, m, b in cells)
    rows = -(-len(cells) // columns)
    sheet = Image.new("RGB", (margin * 2 + columns * cell_w + (columns - 1) * margin * 2,
                              margin * 2 + rows * cell_h + (rows - 1) * gap * 2), GROUND)
    draw = ImageDraw.Draw(sheet)
    font = _font(round(26 * unit))
    for index, (name, meter, board) in enumerate(cells):
        x = margin + (index % columns) * (cell_w + margin * 2)
        y = margin + (index // columns) * (cell_h + gap * 2)
        draw.text((x, y + round(4 * unit)), _label(name), font=font, fill=LABEL)
        sheet.paste(meter, (x, y + label_h))
        sheet.paste(board, (x + meter_w + gap, y + label_h))
    return sheet


def overviews(themes: list[str]) -> None:
    pictures = _pictures(themes)
    # the grid: as sharp as the pictures are, shrunk only as far as the size limit needs
    path = os.path.join(OUT, "themes-overview.png")
    scale = 1.0
    while True:
        _sheet(pictures, 2, scale, 0.6).save(path, optimize=True)
        if os.path.getsize(path) <= LIMIT or scale < 0.3:
            break
        scale *= 0.9


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    themes = available_themes()
    screenshots.OUT = OUT
    shots = []
    for name in themes:
        shots.append((f"overlay-{name}.png", f"?view=overlay&theme={name}", 440, 400))
        shots.append((f"{name}-dashboard.png", f"?view=full&theme={name}#settings-rows", 1400, 760))
    screenshots._session({}, shots, warm=12.0, zoom=ZOOM)
    for name in themes:  # the meter pictures were trimmed to the meter on the way
        os.replace(os.path.join(OUT, f"overlay-{name}.png"), os.path.join(OUT, f"{name}-meter.png"))
    overviews(themes)
    print("wrote assets/themes/:", ", ".join(sorted(os.listdir(OUT))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
