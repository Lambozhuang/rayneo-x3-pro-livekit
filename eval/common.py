"""Shared by the eval scripts: paths of the recorded run, truth loading, frame list, plate mask, image encoding.

FRAMES is the folder the scripts read frames from; set_frames("frames_1080p15") switches every script to the derived
call-quality frames. Results go under RESULTS/<route>: vlm (routes B/C, vlm_judge.py), cv (route D, cv_judge.py),
gate (gate_eval.py); replays sit next to the judge they used.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent
TRUCK = ROOT / "truck"
RUN = TRUCK / "run1"
FRAMES = RUN / "frames"
RESULTS = TRUCK / "results"  # subfolders vlm / cv / gate
SHEETS = RUN / "sheets"
CLIP_ORDER = ["run1_part1", "run1_part2_p1", "run1_part2_p2"]


def set_frames(name: str | None):
    """Switch the frame source for every script (None = the full-resolution frames)."""
    global FRAMES
    FRAMES = RUN / (name or "frames")


def frames_tag() -> str:
    """'' for the full-resolution frames, '_1080p15' for frames_1080p15, used in result file names."""
    return "" if FRAMES.name == "frames" else "_" + FRAMES.name.replace("frames_", "")


def load():
    layout = json.loads((TRUCK / "layout.json").read_text(encoding="utf-8"))
    events = json.loads((TRUCK / "events.json").read_text(encoding="utf-8"))
    steps = layout["steps"] if isinstance(layout, dict) else layout
    return steps, events


def tkey(clip: str, sec: float) -> tuple[int, float]:
    return CLIP_ORDER.index(clip), sec


def frame_list() -> list[tuple[str, int]]:
    out = []
    for clip in CLIP_ORDER:
        for p in sorted((FRAMES / clip).glob("*.jpg")):
            out.append((clip, int(p.stem) - 1))
    return out


def components(mask: np.ndarray) -> list[np.ndarray]:
    """4-connected True regions of a small boolean mask as (y, x) index arrays, largest first (plain BFS; no scipy/cv2 here)."""
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    comps = []
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        comp = [(y0, x0)]
        seen[y0, x0] = True
        i = 0
        while i < len(comp):
            y, x = comp[i]
            i += 1
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    comp.append((ny, nx))
        comps.append(np.array(comp))
    return sorted(comps, key=len, reverse=True)


def plate_bbox(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Bounding box of the baseplate with a 10 % margin.
    Saturated-green mask at 1/8 scale, closed by a max filter so rows of bricks do not cut the plate in two;
    the largest blob plus any blob at least a fifth of its size whose centre lies within one plate-width of it
    (hands split the plate; screens and lime bricks also pass the colour test but are small or far away)."""
    s, k = 8, 9  # downsample, closing kernel (px at 1/8 scale; ~2 studs)
    small = img.copy()
    small.thumbnail((img.width // s, img.height // s))
    a = np.asarray(small.convert("RGB")).astype(np.float32) / 255
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(-1), a.min(-1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    mask = (g > 1.25 * r) & (g > 1.25 * b) & (sat > 0.35) & (mx > 0.25)
    closed = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(k))
                        .filter(ImageFilter.MinFilter(k))) > 0
    comps = components(closed)
    if not comps or len(comps[0]) < 400:  # < ~160x160 px of plate at full resolution
        return None
    main = comps[0]
    cy, cx = main.mean(0)
    size = max(np.ptp(main[:, 0]), np.ptp(main[:, 1]))
    keep = [main] + [c for c in comps[1:] if len(c) >= len(main) / 5 and np.hypot(*(c.mean(0) - (cy, cx))) < size]
    pts = np.concatenate(keep)
    y0, x0 = pts.min(0)
    y1, x1 = pts.max(0) + 1
    w, h = (x1 - x0) * s, (y1 - y0) * s
    mg = 0.10
    return (int(max(0, x0 * s - w * mg)), int(max(0, y0 * s - h * mg)),
            int(min(img.width, x1 * s + w * mg)), int(min(img.height, y1 * s + h * mg)))


def to_jpeg(img: Image.Image, q: int = 90) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=q)
    return buf.getvalue()


def to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
