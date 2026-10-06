"""The gate: which camera frames are worth judging.

The judge (judge_cv.py) reads the plate cell by cell, so it needs the whole
plate in view, no hand over it, and nothing moving. Three local signals, no
model, a few milliseconds per frame:

  plate   the green plate is found and its box keeps clear of the frame border,
          is big enough and roughly square: the whole plate at working distance
  skin    share of skin-coloured pixels inside the plate box (YCbCr window):
          a hand on or over the plate. Only a gross share counts; finer rules
          (blob size, border contact, shape) confused hands with the tan,
          purple and red bricks on the recorded run
  still   mean grey difference between this frame's plate crop and the last
          one's, both resized to 96x96 (tolerates head movement, not hands):
          the frame is judged only after the plate has been still for
          `still_s` seconds

Thresholds were set on the recorded run (eval/gate_eval.py, which imports this
file): 70/70 rest frames pass, 55/75 frames with a hand are stopped; the still
rule is for the live 15 fps stream and was not measurable at 1 fps.

The constants are the CV judge's: it reads cells, so the plate must be close
and still. A VLM only needs the plate in the picture and not blurred, so the
agent gives it a loose gate (gpt/config.py: smaller `min_side`, higher
`motion_max`, shorter `still_s`). On the glasses, with the wearer sitting up
(plate ~300 px of 1080), the CV thresholds passed nothing for minutes: the
plate hovered at MIN_SIDE and head sway kept the motion above MOTION_MAX.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

from judge_cv import close, components, green_mask, hull

BORDER = 0.01       # tight plate box must stay this far (fraction of frame size) from every frame edge
MIN_SIDE = 0.23     # tight box sides at least this fraction of the frame width: a whole plate at working distance
ASPECT = (0.55, 1.45)  # tight box width/height for a whole plate seen from the builder's seat (steep view in portrait: ~0.6)
HAND_TOTAL = 0.15   # skin share inside the plate outline from which a hand is assumed (tan brick + red shadow stay < 6 %)
MOTION_MAX = 12.0   # mean |grey diff| (0-255) between plate-aligned crops of consecutive frames above which it moved


def plate_pixels(img: Image.Image, s: int = 8):
    """(y, x) points of the baseplate at 1/s scale: the plate-green mask (judge_cv.green_mask), closed so rows of
    bricks do not cut the plate in two; the largest blob plus any blob at least a fifth of its size within one
    plate-width (hands split the plate). None when there is no plate-sized blob."""
    k = 9  # closing kernel (px at 1/8 scale; ~2 studs)
    comps = components(close(green_mask(img, s), k))
    if not comps or len(comps[0]) < 400 * (8 / s) ** 2:  # < ~160x160 px of plate at full resolution
        return None
    main = comps[0]
    cy, cx = main.mean(0)
    size = max(np.ptp(main[:, 0]), np.ptp(main[:, 1]))
    keep = [main] + [c for c in comps[1:] if len(c) >= len(main) / 5 and np.hypot(*(c.mean(0) - (cy, cx))) < size]
    return np.concatenate(keep)


def plate_outline(img: Image.Image, s: int = 8) -> Image.Image | None:
    """Full-size 1-bit mask of the plate's convex hull: where a hand would have to be to cover the plate. The
    table around a tilted plate falls inside its bounding box but outside this outline."""
    pts = plate_pixels(img, s)
    if pts is None:
        return None
    h = hull(pts[:, ::-1].astype(np.float64) * s + s / 2)
    m = Image.new("1", img.size, 0)
    ImageDraw.Draw(m).polygon([tuple(p) for p in h], fill=1)
    return m


def plate_bbox(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Bounding box of the baseplate with a 10 % margin (plate_pixels)."""
    s = 8
    pts = plate_pixels(img, s)
    if pts is None:
        return None
    y0, x0 = pts.min(0)
    y1, x1 = pts.max(0) + 1
    w, h = (x1 - x0) * s, (y1 - y0) * s
    mg = 0.10
    return (int(max(0, x0 * s - w * mg)), int(max(0, y0 * s - h * mg)),
            int(min(img.width, x1 * s + w * mg)), int(min(img.height, y1 * s + h * mg)))


def tight_box(img: Image.Image) -> tuple[int, int, int, int] | None:
    """plate_bbox without its margin."""
    b = plate_bbox(img)
    if not b:
        return None
    x0, y0, x1, y1 = b
    w, h = x1 - x0, y1 - y0
    return (int(x0 + w / 12), int(y0 + h / 12), int(x1 - w / 12), int(y1 - h / 12))


def whole_plate(box, size, min_side: float = MIN_SIDE) -> bool:
    x0, y0, x1, y1 = box
    w, h = size
    bw, bh = x1 - x0, y1 - y0
    return (x0 > w * BORDER and y0 > h * BORDER and x1 < w * (1 - BORDER) and y1 < h * (1 - BORDER)
            and min(bw, bh) >= w * min_side and ASPECT[0] <= bw / bh <= ASPECT[1])


def skin_share(crop: Image.Image, within: Image.Image | None = None) -> float:
    """Share of skin-coloured pixels (YCbCr window; measured: hands Cr 135-148, red bricks 150-170), over the
    whole crop or over the pixels where `within` (a 1-bit mask of the same size) is set."""
    small = crop.copy()
    small.thumbnail((max(1, crop.width // 4), max(1, crop.height // 4)))
    a = np.asarray(small.convert("YCbCr")).astype(np.int16)
    y, cb, cr = a[..., 0], a[..., 1], a[..., 2]
    skin = (cr >= 135) & (cr <= 152) & (cb >= 100) & (cb <= 140) & (y > 60)
    if within is None:
        return float(skin.mean())
    w = np.asarray(within.resize(small.size)) > 0
    return float(skin[w].mean()) if w.any() else 0.0


def plate_grey(img: Image.Image, box) -> np.ndarray:
    return np.asarray(img.crop(box).convert("L").resize((96, 96))).astype(np.int16)


@dataclass
class Decision:
    ask: bool
    why: str  # ok | no plate | plate cut | plate partial | hand | moving
    box: tuple[int, int, int, int] | None = None
    skin: float = 0.0
    motion: float | None = None


class Gate:
    """Per-frame decision with the still rule across frames. `still_s` = 0 disables it (offline replay at 1 fps);
    `motion_max` None disables the motion rule; `min_side` is the smallest plate accepted (fraction of frame width)."""

    def __init__(self, still_s: float = 1.0, motion_max: float | None = MOTION_MAX, min_side: float = MIN_SIDE) -> None:
        self.still_s = still_s
        self.motion_max = motion_max
        self.min_side = min_side
        self._prev: np.ndarray | None = None
        self._still_since: float | None = None

    def __call__(self, img: Image.Image, now: float | None = None) -> Decision:
        now = time.monotonic() if now is None else now
        box = tight_box(img)
        if not box:
            self._prev = None
            self._still_since = None
            return Decision(False, "no plate")
        grey = plate_grey(img, box)
        motion = None if self._prev is None else float(np.abs(grey - self._prev).mean())
        self._prev = grey
        if not whole_plate(box, img.size, self.min_side):
            x0, y0, x1, y1 = box
            w, h = img.size
            cut = not (x0 > w * BORDER and y0 > h * BORDER and x1 < w * (1 - BORDER) and y1 < h * (1 - BORDER))
            self._still_since = None
            return Decision(False, "plate cut" if cut else "plate partial", box, motion=motion)
        outline = plate_outline(img)
        skin = skin_share(img.crop(box), outline.crop(box) if outline is not None else None)
        if skin >= HAND_TOTAL:
            self._still_since = None
            return Decision(False, "hand", box, skin, motion)
        if self.motion_max is not None and motion is not None and motion > self.motion_max:
            self._still_since = None
            return Decision(False, "moving", box, skin, motion)
        if self._still_since is None:
            self._still_since = now
        if now - self._still_since < self.still_s:
            return Decision(False, "settling", box, skin, motion)
        return Decision(True, "ok", box, skin, motion)
