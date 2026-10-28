"""Draws every guide's step pictures, the files the agent sends to the glasses when the wearer asks to see a step
(brain.py `show`): guides/<task>/step-<n>.png for each step n, 432 px square, from the `color` and `cells` of the task
file. Run after changing a task file: `python render_pictures.py` in backend/agent. load_guide refuses a guide whose
pictures are missing, so a forgotten run shows up when the agent starts, not in a call.

A picture is the build seen from above at step n, as tasks/sheet.html draws it: the plate as a grid of studs, the bricks
of steps 1 to n in their colours, the brick of step n with a white edge, the bricks still to come left out. The plate is
dark grey, not green: the glasses' display is additive, so a bright plate would be a lamp in the wearer's eye and the
bricks are what has to read. Drawn at four times the size and scaled down, since PIL draws without antialiasing.
"""

import glob
import sys
from math import hypot
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent / "src"))
from guide import Guide, load_guide  # noqa: E402

SIDE = 432  # px; the glasses show the picture in a 216 px square, so this is two pixels per pixel shown
PLATE = (0x1C, 0x1C, 0x1C)
STUD = (0x33, 0x33, 0x33)
EDGE = (0xFF, 0xFF, 0xFF)
OVERSAMPLE = 4


def render(guide: Guide, step: int, side: int = SIDE) -> Image.Image:
    """The build at `step`, numbered as the wearer counts (1 to the count): the bricks of steps 1 to `step`, the
    last of them outlined."""
    px = side * OVERSAMPLE
    img = Image.new("RGB", (px, px), PLATE)
    d = ImageDraw.Draw(img)
    cell = px / guide.plate
    for r in range(guide.plate):
        for c in range(guide.plate):
            _disc(d, (c + 0.5) * cell, (r + 0.5) * cell, cell * 0.18, STUD)
    for i, b in enumerate(guide.steps[:step], 1):
        col0, row0, col1, row1 = b.cells
        x0, y0 = (col0 - 1) * cell, (row0 - 1) * cell
        w, h = (col1 - col0 + 1) * cell, (row1 - row0 + 1) * cell
        colour = tuple(int(b.color[k:k + 2], 16) for k in (1, 3, 5))
        cx, cy, radius = x0 + w / 2, y0 + h / 2, min(w, h) / 2
        if b.round:
            d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=colour)
        else:
            d.rectangle([x0, y0, x0 + w, y0 + h], fill=colour)
        stud = tuple(round(v * 0.8) for v in colour)  # the sheet's 20 % black over the brick
        for r in range(row0, row1 + 1):
            for c in range(col0, col1 + 1):
                sx, sy = (c - 0.5) * cell, (r - 0.5) * cell
                if b.round and hypot(sx - cx, sy - cy) > radius - cell * 0.1:
                    continue  # on a round plate the corner studs are outside the disc
                _disc(d, sx, sy, cell * 0.22, stud)
        if i == step:
            width = round(px * 2 / 216)  # 2 dp of the glasses' 216 dp square
            if b.round:
                d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=EDGE, width=width)
            else:
                d.rectangle([x0, y0, x0 + w, y0 + h], outline=EDGE, width=width)
    return img.resize((side, side), Image.LANCZOS)


def _disc(d: ImageDraw.ImageDraw, x: float, y: float, r: float, colour: tuple) -> None:
    d.ellipse([x - r, y - r, x + r, y + r], fill=colour)


if __name__ == "__main__":
    count = 0
    for p in sorted(glob.glob(str(Path(__file__).parent / "guides/*"))):
        guide = load_guide(p, pictures=False)
        for n in range(1, len(guide.steps) + 1):
            render(guide, n).save(guide.picture(n), "PNG", optimize=True)
            count += 1
    print(f"{count} pictures written under {Path(__file__).parent / 'guides'}")
