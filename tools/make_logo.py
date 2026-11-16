"""Draw Waveband's logo: the mark, the wordmark, and the icons the program and dashboard use.

    .venv\\Scripts\\python tools\\make_logo.py

Writes ``assets\\logo\\`` (SVGs, large PNGs and a sheet of them all, for the README and anywhere
else the project is shown), ``assets\\waveband.ico`` (the program's icon, used by
``build_release.py``), ``ui\\waveband.png`` (the tray icon and the dashboard's favicon) and
``ui\\waveband-mark.svg`` (the mark in the dashboard's top bar). Those come from the design in
use, concept C, Resonance Halo.

It also draws the other concepts, for asking people which they like: each in
``assets\\logo\\concepts\\<letter>-<name>\\`` with its own sheet, and all five side by side in
``assets\\logo\\concepts\\overview.png``.

Everything is drawn here from straight lines, arcs and polygons: no font file and nothing taken
from the game. The designs borrow the game's manner only: dark grounds, a metal accent and an
off-white, thin geometric strokes, chamfered corners, diamonds as markers, rings and sigils. Each
mark is a picture of what the meter does: a band of waveform bars, a wave, a pulse, a spike.
"""

from __future__ import annotations

import math
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
LOGO = os.path.join(ASSETS, "logo")
CONCEPTS = os.path.join(LOGO, "concepts")
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


@dataclass(frozen=True)
class Design:
    key: str  # the concept's letter
    title: str
    ground: str  # the dark behind everything
    edge: str  # a thin line on the ground
    accent: str  # the metal
    pale: str  # the off-white
    fade_end: str  # where the wordmark's fill fades to, at its foot
    mark: Callable[["Design", bool], str]  # the mark on a 512 canvas; True: the 16-48 px one
    stroke: float = 10.0  # the wordmark's stroke, on a cap height of 100
    spacing: float = 26.0  # between its letters
    skew: float = 0.0  # its slant, in degrees
    cut: bool = False  # a band cut through its letters
    tagline: str = "PASSIVE DAMAGE METER"

    @property
    def slug(self) -> str:
        return f"{self.key.lower()}-{self.title.lower().replace(' ', '-')}"


def _arc(cx: float, cy: float, r: float, start: float, end: float) -> str:
    """An SVG arc path from ``start`` to ``end`` degrees (0 = right, clockwise, y down)."""
    x0, y0 = cx + r * math.cos(math.radians(start)), cy + r * math.sin(math.radians(start))
    x1, y1 = cx + r * math.cos(math.radians(end)), cy + r * math.sin(math.radians(end))
    large = 1 if (end - start) % 360 > 180 else 0
    return f"M{x0:.2f},{y0:.2f} A{r},{r} 0 {large} 1 {x1:.2f},{y1:.2f}"


def _diamond(cx: float, cy: float, half: float, fill: str) -> str:
    return (f'<path d="M{cx},{cy - half} L{cx + half * 0.72},{cy} L{cx},{cy + half} '
            f'L{cx - half * 0.72},{cy} Z" fill="{fill}"/>')


def _stroke(d: str, colour: str, width: float, extra: str = "") -> str:
    return (f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="{width}" '
            f'stroke-linejoin="miter" stroke-miterlimit="8"{extra}/>')


# --- the marks ----------------------------------------------------------------------------------

# The waveform, centre outwards: a damage graph, so not symmetrical.
_BARS = (36, 84, 58, 150, 228, 312, 196, 262, 118, 70, 42)


def mark_ring(d: Design, small: bool) -> str:
    """A: an open ring with the meter's waveform bars running through it."""
    cx = cy = 256
    parts = []
    ring_r, ring_w, gap = (190, 30, 24) if small else (186, 12, 21)
    for start, end in ((180 + gap, 360 - gap), (gap, 180 - gap)):
        parts.append(f'<path d="{_arc(cx, cy, ring_r, start, end)}" fill="none" stroke="{d.accent}" '
                     f'stroke-width="{ring_w}" stroke-linecap="butt"/>')
    if small:
        heights, step, width = (120, 230, 300, 200, 130), 70, 34
    else:
        heights, step, width = _BARS, 34, 14
        # the band's axis, running out through the ring's openings
        parts.append(f'<line x1="34" y1="{cy}" x2="478" y2="{cy}" stroke="{d.accent}" '
                     'stroke-width="3" stroke-opacity="0.55"/>')
    middle = len(heights) // 2
    for k, h in enumerate(heights):
        x = cx + (k - middle) * step - width / 2
        colour = d.accent if abs(k - middle) <= (0 if small else 1) else d.pale
        parts.append(f'<rect x="{x:.1f}" y="{cy - h / 2:.1f}" width="{width}" height="{h}" fill="{colour}"/>')
    if not small:
        parts.append(_diamond(cx, cy - ring_r, 15, d.accent))
        parts.append(_diamond(cx, cy + ring_r, 15, d.accent))
    return "\n  ".join(parts)


def _sine(x0: float, x1: float, cy: float, amplitude: float, periods: float, steps: int = 96) -> str:
    points = []
    for i in range(steps + 1):
        t = i / steps
        x = x0 + (x1 - x0) * t
        # the swing grows to the middle and dies away at the ends, like a struck note
        envelope = math.sin(math.pi * t)
        y = cy - amplitude * envelope * math.sin(2 * math.pi * periods * t)
        points.append(f"{x:.1f},{y:.1f}")
    return "M" + " L".join(points)


def mark_diamond(d: Design, small: bool) -> str:
    """B: a tall diamond frame with a sine wave passing through it, out beyond its sides."""
    parts = []
    if small:
        parts.append(_stroke("M256,34 L436,256 L256,478 L76,256 Z", d.accent, 30))
        parts.append(_stroke(_sine(40, 472, 256, 120, 1.5, 48), d.pale, 34, ' stroke-linecap="butt"'))
        return "\n  ".join(parts)
    parts.append(_stroke("M256,40 L430,256 L256,472 L82,256 Z", d.accent, 10))
    parts.append(_stroke("M256,118 L367,256 L256,394 L145,256 Z", d.accent, 3, ' stroke-opacity="0.6"'))
    parts.append(_stroke(_sine(28, 484, 256, 118, 2.5), d.pale, 13, ' stroke-linecap="butt"'))
    for x in (28, 484):
        parts.append(_diamond(x, 256, 13, d.accent))
    parts.append(_diamond(256, 40, 16, d.pale))
    parts.append(_diamond(256, 472, 16, d.pale))
    return "\n  ".join(parts)


def _spark(cx: float, cy: float, long: float, short: float, fill: str) -> str:
    """A four-pointed star with concave sides."""
    k = short * 0.28
    return (f'<path d="M{cx},{cy - long} Q{cx + k},{cy - k} {cx + short},{cy} Q{cx + k},{cy + k} {cx},{cy + long} '
            f'Q{cx - k},{cy + k} {cx - short},{cy} Q{cx - k},{cy - k} {cx},{cy - long} Z" fill="{fill}"/>')


def mark_halo(d: Design, small: bool) -> str:
    """C: ripples spreading from a spark, the way a struck note spreads."""
    cx = cy = 256
    parts = []
    if small:
        # for 16 to 48 pixels (taskbar, Explorer, tray): two heavy arcs and a spark that fills the
        # ring, so it stays a star and not a dot
        for a0, a1 in ((212, 328), (32, 148)):
            parts.append(f'<path d="{_arc(cx, cy, 206, a0, a1)}" fill="none" stroke="{d.accent}" stroke-width="40"/>')
        parts.append(_spark(cx, cy, 168, 84, d.pale))
        parts.append(_spark(cx, cy, 66, 30, d.accent))
        return "\n  ".join(parts)
    rings = ((206, 9, 200, 340, d.accent, 1.0), (206, 9, 20, 160, d.accent, 1.0),
             (166, 5, 235, 395, d.pale, 0.85), (166, 5, 55, 125, d.pale, 0.85),
             (128, 3, 150, 300, d.accent, 0.7), (128, 3, 330, 480, d.accent, 0.7))
    for r, w, a0, a1, colour, opacity in rings:
        parts.append(f'<path d="{_arc(cx, cy, r, a0, a1)}" fill="none" stroke="{colour}" '
                     f'stroke-width="{w}" stroke-opacity="{opacity}"/>')
    parts.append(_spark(cx, cy, 108, 44, d.pale))
    parts.append(_spark(cx, cy, 52, 22, d.accent))
    for angle in (270, 90):
        x, y = cx + 206 * math.cos(math.radians(angle)), cy + 206 * math.sin(math.radians(angle))
        parts.append(_diamond(x, y, 14, d.accent))
    return "\n  ".join(parts)


def _hexagon(cx: float, cy: float, r: float) -> str:
    points = [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a))) for a in range(-90, 270, 60)]
    return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in points) + " Z"


def mark_crest(d: Design, small: bool) -> str:
    """D: a hexagonal crest with a damage spike across it, like a heartbeat on a monitor."""
    cx = cy = 256
    spike = "M70,286 L170,286 L204,236 L238,340 L282,120 L318,300 L342,262 L442,262"
    if small:
        return "\n  ".join([_stroke(_hexagon(cx, cy, 222), d.accent, 32),
                            _stroke("M60,290 L180,290 L250,120 L312,330 L452,260", d.pale, 36)])
    parts = [_stroke(_hexagon(cx, cy, 214), d.accent, 12),
             _stroke(_hexagon(cx, cy, 184), d.accent, 3, ' stroke-opacity="0.55"'),
             _stroke(spike, d.pale, 14),
             _diamond(282, 92, 16, d.accent)]
    return "\n  ".join(parts)


def mark_monogram(d: Design, small: bool) -> str:
    """E: waveform bars whose tops trace a W, in a chamfered frame."""
    parts = []
    base = 392
    if small:
        heights, step, width = (290, 130, 230, 130, 290), 84, 50
    else:
        heights, step, width = (300, 230, 150, 210, 270, 210, 150, 230, 300), 42, 22
        parts.append(_stroke("M120,56 H392 L456,120 V392 L392,456 H120 L56,392 V120 Z", d.accent, 6))
        parts.append(f'<line x1="96" y1="{base + 22}" x2="416" y2="{base + 22}" stroke="{d.accent}" stroke-width="3"/>')
    middle = len(heights) // 2
    for k, h in enumerate(heights):
        x = 256 + (k - middle) * step - width / 2
        colour = d.accent if k in (0, len(heights) - 1, middle) else d.pale
        parts.append(f'<rect x="{x:.1f}" y="{base - h:.1f}" width="{width}" height="{h}" fill="{colour}"/>')
    if small:
        parts.insert(0, _stroke("M110,40 H402 L472,110 V402 L402,472 H110 L40,402 V110 Z", d.accent, 26))
    return "\n  ".join(parts)


DESIGNS = (
    Design("A", "Gold Ring", "#0b0f17", "#2a3242", "#d9b566", "#f1ece0", "#d8c493", mark_ring),
    Design("B", "Tacet Diamond", "#08111f", "#1f3247", "#6fd3cf", "#e8f1f4", "#9fd9db", mark_diamond,
           stroke=9.0, spacing=28.0, skew=-10.0),
    Design("C", "Resonance Halo", "#120d18", "#33283f", "#f0b45a", "#fbf3e4", "#f3cf8f", mark_halo,
           stroke=11.0, cut=True),
    Design("D", "Havoc Crest", "#0d0a0c", "#3a2228", "#c73a4c", "#f2e9e6", "#e2a3a8", mark_crest,
           stroke=15.0, spacing=22.0),
    Design("E", "Aero Monogram", "#0c1416", "#23383a", "#63d6a8", "#eef6f1", "#a8e6cb", mark_monogram,
           stroke=7.0, spacing=36.0),
)
# The design in use, picked by the owner on 2026-11-16 from the five: the others read as a music
# program, this one as part of the game's world.
CURRENT = DESIGNS[2]


# --- the wordmark -------------------------------------------------------------------------------

# The letters, drawn as strokes on a cap height of 100 (y down). Chamfered corners where a round
# one would be, a diamond where A's crossbar would be.
_LETTERS = {
    "W": (96, ["M0,0 L24,100 L48,30 L72,100 L96,0"], [(48, 74)]),
    "A": (70, ["M0,100 L35,0 L70,100"], [(35, 66)]),
    "V": (70, ["M0,0 L35,100 L70,0"], []),
    "E": (56, ["M56,0 H0 V100 H56", "M0,50 H40"], []),
    "B": (60, ["M0,0 H44 L56,12 V38 L46,50 L60,62 V88 L48,100 H0 Z", "M0,50 H46"], []),
    "N": (64, ["M0,100 V0 L64,100 V0"], []),
    "D": (64, ["M0,0 H40 L64,24 V76 L40,100 H0 Z"], []),
}


def _fade(d: Design) -> str:
    """The wordmark's fill: off-white at the top fading toward the accent, as on a metal plate."""
    return ('<defs><linearGradient id="fade" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="100">'
            f'<stop offset="0" stop-color="{d.pale}"/><stop offset="1" stop-color="{d.fade_end}"/>'
            '</linearGradient></defs>')


def wordmark_body(d: Design, x: float, y: float, cap: float) -> tuple[str, float]:
    """WAVEBAND at (x, y) with a cap height of ``cap``. Returns the drawing and its width."""
    s = cap / 100.0
    parts, pen = [], 0.0
    for letter in "WAVEBAND":
        width, paths, diamonds = _LETTERS[letter]
        group = [f'<path d="{p}" fill="none" stroke="url(#fade)" stroke-width="{d.stroke}" '
                 'stroke-linejoin="miter" stroke-miterlimit="8" stroke-linecap="square"/>' for p in paths]
        group += [_diamond(dx, dy, 9, d.accent) for dx, dy in diamonds if letter == "A"]
        slant = f" skewX({d.skew:g})" if d.skew else ""
        parts.append(f'<g transform="translate({x + pen * s:.2f},{y:.2f}) scale({s:g}){slant}">{"".join(group)}</g>')
        pen += width + d.spacing
    total = (pen - d.spacing) * s
    if d.cut:
        # the band: a clean gap of the ground's colour sliced through every letter
        top, gap = y + cap * 0.6, cap * 0.06
        parts.append(f'<rect x="{x - 8:.1f}" y="{top:.1f}" width="{total + 16:.1f}" height="{gap:.1f}" fill="{d.ground}"/>')
    return "\n  ".join(parts), total


# A small capital alphabet for the tagline, from strokes like the wordmark's.
_SMALL = {
    "P": (52, ["M0,100 V0 H40 L52,12 V38 L40,50 H0"]),
    "A": (60, ["M0,100 L30,0 L60,100", "M12,62 H48"]),
    "S": (52, ["M52,0 H10 L0,10 V40 L10,50 H42 L52,60 V90 L42,100 H0"]),
    "I": (8, ["M4,0 V100"]),
    "V": (60, ["M0,0 L30,100 L60,0"]),
    "E": (48, ["M48,0 H0 V100 H48", "M0,50 H36"]),
    "D": (54, ["M0,0 H34 L54,20 V80 L34,100 H0 Z"]),
    "M": (70, ["M0,100 V0 L35,60 L70,0 V100"]),
    "G": (54, ["M54,10 L44,0 H10 L0,10 V90 L10,100 H44 L54,90 V56 H30"]),
    "T": (52, ["M0,0 H52", "M26,0 V100"]),
    "R": (54, ["M0,100 V0 H42 L54,12 V38 L42,50 H0", "M30,50 L54,100"]),
    " ": (30, []),
}


def _tagline(d: Design, x: float, y: float, cap: float) -> tuple[str, float]:
    s = cap / 100.0
    parts, pen, spacing = [], 0.0, 46.0
    for letter in d.tagline:
        width, paths = _SMALL[letter]
        if paths:
            group = "".join(f'<path d="{p}" fill="none" stroke="{d.accent}" stroke-width="11" '
                            'stroke-linejoin="miter" stroke-linecap="square"/>' for p in paths)
            parts.append(f'<g transform="translate({x + pen * s:.2f},{y:.2f}) scale({s:g})">{group}</g>')
        pen += width + spacing
    return "".join(parts), (pen - spacing) * s


# --- the files ----------------------------------------------------------------------------------

def _svg(width: float, height: float, body: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:g} {height:g}" '
            f'width="{width:g}" height="{height:g}">\n  {body}\n</svg>\n')


def mark_svg(d: Design) -> str:
    return _svg(512, 512, d.mark(d, False))


def icon_svg(d: Design, small: bool = False) -> str:
    """The mark on its ground: a dark rounded square with a thin edge."""
    ground = (f'<rect x="8" y="8" width="496" height="496" rx="{84 if small else 96}" fill="{d.ground}"/>'
              + ("" if small else f'<rect x="20" y="20" width="472" height="472" rx="86" fill="none" '
                 f'stroke="{d.edge}" stroke-width="3"/>'))
    scale = 0.86 if small else 0.8
    shift = 256 * (1 - scale)
    return _svg(512, 512, f'{ground}\n  <g transform="translate({shift:g},{shift:g}) scale({scale:g})">\n  '
                          f'{d.mark(d, small)}\n  </g>')


def wordmark_svg(d: Design) -> str:
    words, words_w = wordmark_body(d, 24, 24, 80)
    # a cut is the ground's colour, so a design with one keeps its ground behind the letters
    ground = f'<rect x="0" y="0" width="{words_w + 48:.1f}" height="128" fill="{d.ground}"/>' if d.cut else ""
    return _svg(words_w + 48, 128, _fade(d) + ground + words)


def lockup_svg(d: Design) -> str:
    """Mark and wordmark side by side, with a rule and a line saying what it is."""
    height, mark_size = 300, 240
    words, words_w = wordmark_body(d, 320, 92, 80)
    tagline, tag_w = _tagline(d, 320, 238, 16)
    width = 320 + max(words_w, tag_w) + 44
    rule_y = 214
    body = [_fade(d), f'<rect x="0" y="0" width="{width:.1f}" height="{height}" fill="{d.ground}"/>',
            f'<g transform="translate(30,30) scale({mark_size / 512:g})">{d.mark(d, False)}</g>',
            words,
            f'<line x1="320" y1="{rule_y}" x2="{320 + words_w:.1f}" y2="{rule_y}" stroke="{d.accent}" stroke-width="2"/>',
            _diamond(320 + words_w / 2, rule_y, 9, d.accent),
            tagline]
    return _svg(width, height, "\n  ".join(body))


def _width_of(svg: str) -> float:
    return float(svg.split('width="')[1].split('"')[0])


def _render(svg: str, path: str, width: int, height: int) -> None:
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    QGuiApplication.instance() or QGuiApplication(sys.argv[:1] + ["-platform", "offscreen"])
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
    painter.end()
    image.save(path)


def _image(svg: str, width: int, height: int, folder: str):
    from PIL import Image

    tmp = os.path.join(folder, f".render-{width}x{height}.png")
    _render(svg, tmp, width, height)
    try:
        return Image.open(tmp).convert("RGBA").copy()
    finally:
        os.remove(tmp)


def write_design(d: Design, folder: str, title: str) -> dict:
    """The design's SVGs and PNGs in ``folder``, and its sheet. Returns its icons by size."""
    os.makedirs(folder, exist_ok=True)
    files = {
        "waveband-mark.svg": mark_svg(d),
        "waveband-icon.svg": icon_svg(d),
        "waveband-icon-small.svg": icon_svg(d, small=True),
        "waveband-wordmark.svg": wordmark_svg(d),
        "waveband-lockup.svg": lockup_svg(d),
    }
    for name, svg in files.items():
        with open(os.path.join(folder, name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(svg)
    _render(files["waveband-icon.svg"], os.path.join(folder, "waveband-icon-512.png"), 512, 512)
    _render(files["waveband-mark.svg"], os.path.join(folder, "waveband-mark-512.png"), 512, 512)
    lockup = files["waveband-lockup.svg"]
    _render(lockup, os.path.join(folder, "waveband-lockup.png"), round(_width_of(lockup) * 2), 600)
    # icons: the detailed mark from 64 pixels up, the plain one below
    icons = {size: _image(icon_svg(d, small=size < 64), size, size, folder) for size in ICON_SIZES}
    small_icon = _image(files["waveband-icon-small.svg"], 320, 320, folder)
    word = files["waveband-wordmark.svg"]
    wordmark = _image(word, round(_width_of(word) * 2), 256, folder)
    sheet(d, folder, title, icons, small_icon, wordmark)
    return icons


def main() -> int:
    from PIL import Image

    # the design in use: its files where the README and the build look for them
    icons = write_design(CURRENT, LOGO, "logo and icons")
    images = [icons[s] for s in ICON_SIZES]
    images[-1].save(os.path.join(ASSETS, "waveband.ico"), sizes=[(s, s) for s in ICON_SIZES],
                    append_images=images[:-1])
    # Windows shows the tray icon at 16 to 24 pixels, so it is the bold small one, not the detailed
    # 64: shrunk that far, fine rings turn to mush
    _image(icon_svg(CURRENT, small=True), 64, 64, LOGO).save(os.path.join(ROOT, "ui", "waveband.png"))
    # the mark for the dashboard's top bar
    with open(os.path.join(ROOT, "ui", "waveband-mark.svg"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_svg(512, 512, CURRENT.mark(CURRENT, True)))  # shown at 26 px: the bold one
    installer_images(CURRENT)
    # every concept, the one in use among them, for showing people side by side
    for d in DESIGNS:
        write_design(d, os.path.join(CONCEPTS, d.slug), f"concept {d.key}  ·  {d.title}")
    overview()
    print("wrote assets\\logo, assets\\waveband.ico, ui\\waveband.png and",
          ", ".join(f"concepts\\{d.slug}" for d in DESIGNS), "+ concepts\\overview.png")
    return 0


INSTALLER = os.path.join(ASSETS, "installer")
# Windows' display scales the installer's pictures are drawn for, in percent.
_SCALES = (100, 125, 150, 175, 200, 250)


def installer_images(d: Design) -> None:
    """The installer's pictures, as the BMPs Inno Setup takes, one per display scale: the tall
    panel on its first and last pages (164 x 314 at 100%) and the small one at the top right of
    the others (55 x 55). ``tools\\installer\\waveband.iss`` lists them."""
    from PIL import Image

    os.makedirs(INSTALLER, exist_ok=True)
    words, words_w = wordmark_body(d, 0, 0, 80)
    cap = 80 * 132 / words_w
    words, words_w = wordmark_body(d, 16, 218, cap)
    tag, tag_w = _tagline(d, (164 - 120) / 2, 262, 120 / 1300 * 100 * 0.62)
    panel = _svg(164, 314, "\n  ".join([
        _fade(d),
        f'<rect x="0" y="0" width="164" height="314" fill="{d.ground}"/>',
        # a ring larger than the panel, behind everything, as on a title screen
        f'<circle cx="82" cy="104" r="150" fill="none" stroke="{d.edge}" stroke-width="1"/>',
        f'<circle cx="82" cy="104" r="118" fill="none" stroke="{d.edge}" stroke-width="1"/>',
        f'<g transform="translate(17,39) scale({130 / 512:g})">{d.mark(d, False)}</g>',
        words,
        f'<line x1="16" y1="{218 + cap + 14:.1f}" x2="{16 + words_w:.1f}" y2="{218 + cap + 14:.1f}" '
        f'stroke="{d.accent}" stroke-width="1"/>',
        _diamond(16 + words_w / 2, 218 + cap + 14, 4, d.accent),
        tag,
    ]))
    for scale in _SCALES:
        w, h = round(164 * scale / 100), round(314 * scale / 100)
        _image(panel, w, h, INSTALLER).convert("RGB").save(os.path.join(INSTALLER, f"wizard-{scale}.bmp"))
        s = round(55 * scale / 100)
        small = _image(icon_svg(d, small=True), s, s, INSTALLER)
        ground = Image.new("RGB", (s, s), (255, 255, 255))  # the page header behind it is white
        ground.paste(small, (0, 0), small)
        ground.save(os.path.join(INSTALLER, f"wizard-small-{scale}.bmp"))


# --- the sheets ---------------------------------------------------------------------------------

def _font(size: int):
    from PIL import ImageFont

    for name in ("bahnschrift.ttf", "segoeui.ttf"):
        path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    return tuple(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))


def _darker(hex_colour: str, by: float) -> tuple[int, int, int]:
    return tuple(max(0, round(c * by)) for c in _rgb(hex_colour))


def _lighter(hex_colour: str, by: int) -> tuple[int, int, int]:
    return tuple(min(255, c + by) for c in _rgb(hex_colour))


def sheet(d: Design, folder: str, title: str, icons: dict, small_icon, wordmark) -> None:
    """``waveband-logo-sheet.png`` in ``folder``: every file of the design on one page, each in a
    tile captioned with its name and size, for looking the set over at a glance."""
    from PIL import Image, ImageDraw

    width, margin, gutter, caption = 1600, 28, 16, 34
    page_bg, panel, edge, caption_bg = _darker(d.ground, 0.6), _lighter(d.ground, 6), _rgb(d.edge), _rgb(d.ground)
    checker = _lighter(d.ground, 14)
    pale, accent, muted = _rgb(d.pale), _rgb(d.accent), (120, 130, 146)
    small_font, name_font = _font(15), _font(16)

    lockup = Image.open(os.path.join(folder, "waveband-lockup.png")).convert("RGBA")
    mark_img = Image.open(os.path.join(folder, "waveband-mark-512.png")).convert("RGBA")
    icon_img = Image.open(os.path.join(folder, "waveband-icon-512.png")).convert("RGBA")

    inner = width - 2 * margin
    third = (inner - 2 * gutter) // 3
    eighth = (inner - 7 * gutter) // 8
    # (picture, file name, size as written, tile width, preview height, checker behind it)
    rows = [
        [(lockup, "waveband-lockup  .svg  .png", f"{lockup.width}x{lockup.height}", inner, 360, False)],
        [(mark_img, "waveband-mark  .svg  .png", "512x512", third, 400, True),
         (icon_img, "waveband-icon  .svg  .png", "512x512", third, 400, True),
         (small_icon, "waveband-icon-small  .svg  (16 to 48 px)", "512x512", third, 400, True)],
        [(wordmark, "waveband-wordmark  .svg", f"{wordmark.width // 2}x{wordmark.height // 2}", inner, 200, False)],
        [(icons[s], "icon", f"{s}x{s}", eighth, 230, True) for s in ICON_SIZES]
        + [(_image(icon_svg(d, small=True), 64, 64, folder), "tray, favicon", "64x64", eighth, 230, True)],
    ]
    header = 92
    height = header + sum(row[0][4] + caption + gutter for row in rows) + margin - gutter + 20
    page = Image.new("RGB", (width, height), page_bg)
    draw = ImageDraw.Draw(page)

    # the title bar: name, which design this is, a rule with a diamond
    draw.text((margin, 26), "WAVEBAND", font=_font(30), fill=pale)
    draw.text((margin + 190, 36), title, font=_font(18), fill=accent)
    right = "drawn by tools/make_logo.py  ·  no font file, nothing from the game"
    draw.text((width - margin - draw.textlength(right, font=small_font), 38), right, font=small_font, fill=pale)
    rule_y = 76
    draw.line([(margin, rule_y), (width - margin, rule_y)], fill=accent, width=2)
    mid = width // 2
    draw.polygon([(mid, rule_y - 7), (mid + 5, rule_y), (mid, rule_y + 7), (mid - 5, rule_y)], fill=accent)

    y = header + 20
    for row in rows:
        x = margin
        for picture, name, size, tile_w, preview_h, with_checker in row:
            chamfer = 16
            box = [(x, y), (x + tile_w - chamfer, y), (x + tile_w, y + chamfer), (x + tile_w, y + preview_h + caption),
                   (x, y + preview_h + caption)]
            draw.polygon(box, fill=panel, outline=edge)
            if with_checker:
                step = 12
                for cy in range(y + 1, y + preview_h, step):
                    for cx in range(x + 1, x + tile_w - 1, step):
                        if ((cx - x) // step + (cy - y) // step) % 2 and not (cx > x + tile_w - chamfer - step and cy < y + chamfer + step):
                            draw.rectangle([cx, cy, min(cx + step - 1, x + tile_w - 2), min(cy + step - 1, y + preview_h - 1)],
                                           fill=checker)
            # the picture: actual size when it fits, else scaled to fit
            room_w, room_h = tile_w - 40, preview_h - 36
            scale = min(1.0, room_w / picture.width, room_h / picture.height)
            shown = picture if scale == 1.0 else picture.resize(
                (round(picture.width * scale), round(picture.height * scale)), Image.LANCZOS)
            page.paste(shown, (x + (tile_w - shown.width) // 2, y + (preview_h - shown.height) // 2), shown)
            if tile_w < inner:
                note = f"shown at {round(scale * 100)}%" if scale < 1.0 else "actual size"
                draw.text((x + 10, y + preview_h - 24), note, font=_font(12), fill=muted)
            # caption strip: name on the left, size on the right
            cap_y = y + preview_h
            draw.rectangle([x + 1, cap_y, x + tile_w - 1, cap_y + caption - 1], fill=caption_bg)
            draw.line([(x + 1, cap_y), (x + tile_w - 1, cap_y)], fill=accent, width=1)
            label_font = name_font if tile_w > 300 else _font(13)
            text = name
            room = tile_w - 30 - draw.textlength(size, font=label_font)
            while draw.textlength(text, font=label_font) > room and len(text) > 4:
                text = text[:-2].rstrip() + "…"
            draw.text((x + 10, cap_y + 8), text, font=label_font, fill=pale)
            draw.text((x + tile_w - 10 - draw.textlength(size, font=label_font), cap_y + 8), size,
                      font=label_font, fill=accent)
            x += tile_w + gutter
        y += row[0][4] + caption + gutter
    page.save(os.path.join(folder, "waveband-logo-sheet.png"))


def overview() -> None:
    """``concepts\\overview.png``: the five side by side, each as its icon at 128, 48 and 24 px
    and its lockup, labelled with its letter and name, for asking which people like."""
    from PIL import Image, ImageDraw

    width, margin, row_h, header = 1600, 28, 230, 92
    page = Image.new("RGB", (width, header + len(DESIGNS) * (row_h + 14) + margin), (8, 10, 14))
    draw = ImageDraw.Draw(page)
    pale, gold = _rgb("#f1ece0"), _rgb("#d9b566")
    draw.text((margin, 26), "WAVEBAND", font=_font(30), fill=pale)
    draw.text((margin + 190, 36), "five logo concepts", font=_font(18), fill=gold)
    right = "which one would you pick?  ·  inspired by the game's look, nothing taken from it"
    draw.text((width - margin - draw.textlength(right, font=_font(15)), 38), right, font=_font(15), fill=pale)
    draw.line([(margin, 76), (width - margin, 76)], fill=gold, width=2)
    y = header + 6
    for d in DESIGNS:
        folder = os.path.join(CONCEPTS, d.slug)
        ground, accent = _rgb(d.ground), _rgb(d.accent)
        draw.rectangle([margin, y, width - margin, y + row_h], fill=ground, outline=_rgb(d.edge))
        draw.rectangle([margin, y, margin + 6, y + row_h], fill=accent)
        draw.text((margin + 24, y + 16), d.key, font=_font(40), fill=accent)
        draw.text((margin + 24, y + 66), d.title, font=_font(16), fill=_rgb(d.pale))
        icon = Image.open(os.path.join(folder, "waveband-icon-512.png")).convert("RGBA")
        x = margin + 190
        for size in (128, 48, 24):
            shown = icon if size >= 64 else _image(icon_svg(d, small=True), size, size, folder)
            shown = shown.resize((size, size), Image.LANCZOS) if shown.width != size else shown
            page.paste(shown, (x, y + (row_h - size) // 2), shown)
            x += size + 22
        lockup = Image.open(os.path.join(folder, "waveband-lockup.png")).convert("RGBA")
        scale = (row_h - 20) / lockup.height
        lockup = lockup.resize((round(lockup.width * scale), row_h - 20), Image.LANCZOS)
        room = width - margin - 10 - x
        if lockup.width > room:
            lockup = lockup.resize((room, round(lockup.height * room / lockup.width)), Image.LANCZOS)
        page.paste(lockup, (x + 10, y + (row_h - lockup.height) // 2), lockup)
        y += row_h + 14
    page.save(os.path.join(CONCEPTS, "overview.png"))


if __name__ == "__main__":
    sys.exit(main())
