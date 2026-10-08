"""What is actually on the plate in each case's photo, as bricks (colour, [col0,row0,col1,row1], disc), for the
'perfect view' test: the photo replaced by a top-down drawing of that state. Correct and not-placed cases are the
task's own cells; the four wrong placements are read off the photos by eye (eval/brain/wrong_closeup.jpg)."""
import sys
sys.path.insert(0, "backend/agent/src")
from PIL import Image, ImageDraw
from guide import load_guide

STEPS = load_guide("guides/truck").steps
COLORS = {"red": (200, 30, 20), "purple": (120, 30, 150), "lime": (170, 210, 40), "white": (240, 240, 240),
          "blue": (20, 80, 200), "tan": (230, 200, 150), "yellow": (250, 200, 30)}


def done(n):
    return [(s.color, s.cells, "disc" in s.name.lower()) for s in STEPS[:n]]


STATE = {
    "A": done(1),
    "B": done(1) + [("purple", (5, 6, 8, 7), False)],          # purple lying horizontally right of the red slope
    "C": done(2),
    "D": done(2),
    "E": done(2) + [("lime", (7, 5, 7, 8), False)],             # lime strip right of purple, level with it, not sticking up
    "F": done(3),
    "G": done(3) + [("tan", (7, 6, 12, 6), False)],             # tan 1x6 where the white one goes
    "H": done(4),
    "I": done(7),
    "J": done(9) + [("red", (12, 9, 15, 12), True)],           # right disc too far right, under the white 1x4 end
    "K": done(10),
    "L": done(13),
    "N": done(13),
    "O": done(10),
}

CELL, M = 32, 6


def draw(case):
    img = Image.new("RGB", (2 * M + 16 * CELL, 2 * M + 16 * CELL), (30, 120, 60))
    d = ImageDraw.Draw(img)
    for i in range(16):
        for j in range(16):
            cx, cy = M + i * CELL + CELL // 2, M + j * CELL + CELL // 2
            d.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=(25, 100, 50))
    for color, (c0, r0, c1, r1), disc in STATE[case]:
        box = [M + (c0 - 1) * CELL, M + (r0 - 1) * CELL, M + c1 * CELL - 1, M + r1 * CELL - 1]
        (d.ellipse if disc else d.rectangle)(box, fill=COLORS[color], outline="black")
    return img
