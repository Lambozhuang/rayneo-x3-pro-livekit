"""Route D: judge a build step with plain CV, no model (PIL + numpy).

  python eval/cv_judge.py overlay [--frames frames_1080p15] [--questions truck/rest.json]
  python eval/cv_judge.py run     [--frames frames_1080p15] [--questions truck/rest.json]
      -> truck/results/cv/<questions>_cv[_1080p15].jsonl (same shape as vlm_judge) + sheets/cv/<stem>.jpg with, per
         question, the crop with the grid, the observed class map and the expected map (new cells of the step outlined).
      -> truck/run1/sheets/cv/grid[_1080p15].jpg : for each question frame, the plate crop with the fitted 16x16 grid
         and, beside it, the raw colour sampled at every cell. Look at this before trusting anything downstream.

Pipeline: saturated-green mask -> plate silhouette (closing + nearby blobs, as plate_bbox) -> convex hull -> four
corners (extremes along the diagonals, refined by fitting a line to the hull points of each side and intersecting)
-> homography grid (0..16, 0..16) -> image -> per-cell median colour from a small patch around the cell centre.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as cm  # noqa: E402

RESULTS = cm.RESULTS / "cv"
SHEETS = cm.SHEETS / "cv"

N = 16  # studs per side


def green_mask(img: Image.Image, s: int) -> np.ndarray:
    small = img.copy()
    small.thumbnail((img.width // s, img.height // s))
    a = np.asarray(small.convert("RGB")).astype(np.float32) / 255
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(-1), a.min(-1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    return (g > 2.0 * r) & (g > 1.5 * b) & (sat > 0.35) & (mx > 0.25)  # plate g/r > 3; lime ~1.3, blue g < b


def silhouette(img: Image.Image, s: int = 4):
    """Plate pixels at 1/s scale: closed green mask, largest blob plus nearby blobs (same rule as plate_bbox)."""
    mask = green_mask(img, s)
    k = 2 * (9 * 8 // s // 2) + 1  # ~2 studs, odd
    closed = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(k))
                        .filter(ImageFilter.MinFilter(k))) > 0
    comps = cm.components(closed)
    if not comps or len(comps[0]) < 400 * (8 / s) ** 2:
        return None
    main = comps[0]
    cy, cx = main.mean(0)
    size = max(np.ptp(main[:, 0]), np.ptp(main[:, 1]))
    keep = [main] + [c for c in comps[1:] if len(c) >= len(main) / 5 and np.hypot(*(c.mean(0) - (cy, cx))) < size]
    pts = np.concatenate(keep)  # (y, x)
    return pts[:, ::-1].astype(np.float64) * s + s / 2  # (x, y) full-res


def hull(pts: np.ndarray) -> np.ndarray:
    """Convex hull (monotone chain) of (x, y) points, counter-clockwise in image coords."""
    p = np.unique(pts, axis=0)
    p = p[np.lexsort((p[:, 1], p[:, 0]))]
    if len(p) < 3:
        return p

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for q in p:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    for q in p[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    return np.array(lower[:-1] + upper[:-1])


def fit_line(pts: np.ndarray):
    """Total least squares line through points: returns (point, direction)."""
    c = pts.mean(0)
    u, s, vt = np.linalg.svd(pts - c)
    return c, vt[0]


def intersect(l1, l2):
    (p1, d1), (p2, d2) = l1, l2
    a = np.array([d1, -d2]).T
    t = np.linalg.solve(a, p2 - p1)
    return p1 + t[0] * d1


def segments(h: np.ndarray, tol_deg: float = 4.0):
    """Hull edges merged while nearly collinear -> list of (length, angle_deg, point indices)."""
    n = len(h)
    edges = [(i, (i + 1) % n) for i in range(n)]
    ang = [np.degrees(np.arctan2(*(h[b] - h[a])[::-1])) for a, b in edges]
    segs = []
    cur = [0]
    for i in range(1, n):
        d = abs((ang[i] - ang[cur[-1]] + 180) % 360 - 180)
        if d < tol_deg:
            cur.append(i)
        else:
            segs.append(cur)
            cur = [i]
    segs.append(cur)
    if len(segs) > 1 and abs((ang[segs[0][0]] - ang[segs[-1][-1]] + 180) % 360 - 180) < tol_deg:
        segs[0] = segs.pop() + segs[0]
    out = []
    for sg in segs:
        idx = sorted({edges[i][0] for i in sg} | {edges[i][1] for i in sg})
        pts = h[idx]
        a, b = h[edges[sg[0]][0]], h[edges[sg[-1]][1]]
        d = b - a
        out.append((float(np.hypot(*d)), float(np.degrees(np.arctan2(d[1], d[0]))), pts))
    return out


def corners(sil: np.ndarray, border=None):
    """Four plate corners TL, TR, BR, BL. The hull of the silhouette is split into straight segments; the longest
    roughly horizontal segment above / below the centre and the longest roughly vertical one left / right of it are
    the four sides (a hand cutting a corner, or the frame border, leaves the true sides the longest). Each side is a
    total-least-squares line through its hull points; corners are the intersections."""
    h = hull(sil)
    cx, cy = h.mean(0)
    sides = {}
    cut = set()  # sides with any hull run along the frame border: the edge is at least partly out of view
    for length, ang, pts in segments(h):
        on_border = border is not None and (((pts[:, 0] < 3) | (pts[:, 0] > border[0] - 4)).all()
                                            or ((pts[:, 1] < 3) | (pts[:, 1] > border[1] - 4)).all())
        a = abs((ang + 90) % 180 - 90)  # 0 = horizontal, 90 = vertical
        mx, my = pts.mean(0)
        if a < 35:
            key = "top" if my < cy else "bottom"
        elif a > 55:
            key = "left" if mx < cx else "right"
        else:
            continue
        if on_border:
            if length > 0.15 * max(np.ptp(h[:, 0]), np.ptp(h[:, 1])):
                cut.add(key)
            length *= 0.5  # lies on the frame border: only wins when nothing better exists
        if key not in sides or sides[key][0] < length:
            sides[key] = (length, pts, on_border)
    if len(sides) < 4:
        return None, h, []
    L = {k: fit_line(v[1]) if len(v[1]) >= 2 else None for k, v in sides.items()}
    if any(v is None for v in L.values()):
        return None, h, []
    out = [intersect(L["top"], L["left"]), intersect(L["top"], L["right"]),
           intersect(L["bottom"], L["right"]), intersect(L["bottom"], L["left"])]
    return np.array(out), h, sorted(cut)


def focal(H: np.ndarray, size) -> float | None:
    """Focal length (px) from the homography of a square seen in full, assuming square pixels and the principal
    point at the image centre: the two plane axes must be orthogonal in camera space."""
    w, h = size
    h1, h2 = H[:, 0].copy(), H[:, 1].copy()
    for v in (h1, h2):
        v[0] -= w / 2 * v[2]
        v[1] -= h / 2 * v[2]
    f2 = -(h1[0] * h2[0] + h1[1] * h2[1]) / (h1[2] * h2[2])
    return float(np.sqrt(f2)) if f2 > 0 else None


def far_corners(A, B, A2, B2, f: float, size):
    """The plate is square: given its two corners A, B on one fully visible side, one more point on each adjacent
    side (A2 on the side through A, B2 on the side through B) and the focal length, return the two corners of the
    opposite side (the one next to B first, then the one next to A). Used when that side is cut off by the frame."""
    w, h = size
    K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]])
    Ki = np.linalg.inv(K)
    A, B, A2, B2 = (np.r_[np.asarray(p, dtype=float), 1.0] for p in (A, B, A2, B2))
    vv = np.cross(np.cross(A, A2), np.cross(B, B2))  # vanishing point of the two adjacent sides
    dv = Ki @ vv
    dv /= np.linalg.norm(dv)
    a, b = Ki @ A, Ki @ (B - A)  # vanishing point of side AB: the point on it orthogonal to dv
    sgn = -(a @ dv) / (b @ dv)
    du = Ki @ (A + sgn * (B - A))
    du /= np.linalg.norm(du)
    n = np.cross(du, dv)
    XA = Ki @ A
    XB = (n @ XA) / (n @ (Ki @ B)) * (Ki @ B)
    L = np.linalg.norm(XB - XA)
    step = L * dv
    if np.dot(((K @ (XA + step))[:2] / (XA + step)[2]) - A[:2], A2[:2] - A[:2]) < 0:
        step = -step  # go toward the cut side, not away from it
    out = []
    for X in (XB + step, XA + step):
        x = K @ X
        out.append(x[:2] / x[2])
    return out


def homography(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """H with dst ~ H @ src (4 point DLT). src = grid corners, dst = image corners."""
    rows = []
    for (u, v), (x, y) in zip(src, dst):
        rows.append([u, v, 1, 0, 0, 0, -x * u, -x * v, -x])
        rows.append([0, 0, 0, u, v, 1, -y * u, -y * v, -y])
    _, _, vt = np.linalg.svd(np.array(rows, dtype=np.float64))
    return vt[-1].reshape(3, 3)


def project(H: np.ndarray, uv: np.ndarray) -> np.ndarray:
    p = np.c_[uv, np.ones(len(uv))] @ H.T
    return p[:, :2] / p[:, 2:3]


GRID_CORNERS = np.array([[0, 0], [N, 0], [N, N], [0, N]], dtype=np.float64)


class Plate:
    """Plate geometry of one frame. With f (focal length, px) a side cut off by the frame border is rebuilt from
    the other three and the square shape; without f the border itself stands in for the edge."""

    def __init__(self, img: Image.Image, f: float | None = None):
        self.img = img
        self.arr = np.asarray(img.convert("RGB"))
        sil = silhouette(img)
        self.ok = sil is not None
        if not self.ok:
            return
        self.corners, self.hull, self.cut = corners(sil, img.size)
        if self.corners is None:
            self.ok = False
            return
        if f and len(self.cut) == 1:
            c = self.corners
            i = ["top", "right", "bottom", "left"].index(self.cut[0])  # side i runs from corner i to corner i+1
            A, B = c[(i + 2) % 4], c[(i + 3) % 4]  # the opposite side, fully visible
            nb, na = far_corners(A, B, c[(i + 1) % 4], c[i], f, img.size)
            c[i], c[(i + 1) % 4] = nb, na  # nb is next to B = c[i+3], i.e. corner i; na next to A = c[i+2], i.e. corner i+1
        self.H = homography(GRID_CORNERS, self.corners)

    def sample(self, u: float, v: float, rad: float = 0.15, n: int = 5) -> np.ndarray:
        """Median RGB of an n x n patch of grid points within +-rad cell of (u, v)."""
        g = np.linspace(-rad, rad, n)
        uv = np.array([(u + du, v + dv) for du in g for dv in g])
        xy = project(self.H, uv).round().astype(int)
        h, w = self.arr.shape[:2]
        xy[:, 0] = xy[:, 0].clip(0, w - 1)
        xy[:, 1] = xy[:, 1].clip(0, h - 1)
        return np.median(self.arr[xy[:, 1], xy[:, 0]], axis=0)

    def cell_colours(self, dv: float = 0.0) -> np.ndarray:
        """(N, N, 3) raw median colour per cell [row, col]; dv shifts the sample point along rows (toward the camera > 0).
        Also fills self.seen: whether the sample point lies inside the image."""
        out = np.zeros((N, N, 3))
        self.seen = np.ones((N, N), dtype=bool)
        h, w = self.arr.shape[:2]
        for r in range(N):
            for c in range(N):
                x, y = project(self.H, np.array([[c + 0.5, r + 0.5 + dv]]))[0]
                self.seen[r, c] = 0 <= x < w and 0 <= y < h
                out[r, c] = self.sample(c + 0.5, r + 0.5 + dv)
        return out

    def draw(self, pad: float = 0.08) -> Image.Image:
        """Crop around the plate with the fitted grid and corners drawn on it."""
        xs, ys = self.corners[:, 0], self.corners[:, 1]
        w, h = xs.max() - xs.min(), ys.max() - ys.min()
        x0, y0 = int(max(0, xs.min() - w * pad)), int(max(0, ys.min() - h * pad))
        x1, y1 = int(min(self.img.width, xs.max() + w * pad)), int(min(self.img.height, ys.max() + h * pad))
        crop = self.img.crop((x0, y0, x1, y1)).convert("RGB")
        d = ImageDraw.Draw(crop)
        for i in range(N + 1):
            a = project(self.H, np.array([[i, 0], [i, N]], dtype=float)) - (x0, y0)
            b = project(self.H, np.array([[0, i], [N, i]], dtype=float)) - (x0, y0)
            col = (255, 255, 0) if i % 4 else (255, 80, 255)
            d.line([tuple(a[0]), tuple(a[1])], fill=col, width=1)
            d.line([tuple(b[0]), tuple(b[1])], fill=col, width=1)
        for p in self.corners:
            x, y = p - (x0, y0)
            d.ellipse([x - 5, y - 5, x + 5, y + 5], outline=(255, 0, 0), width=2)
        return crop


PALETTE = {"plate": (40, 140, 60), "red": (200, 30, 20), "purple": (120, 30, 150), "lime": (170, 210, 40),
           "white": (240, 240, 240), "blue": (20, 80, 200), "tan": (215, 190, 140), "yellow": (250, 200, 0),
           "other": (0, 0, 0), "unseen": (128, 128, 128), "dark": (60, 60, 60)}
CLASSES = ["plate", "red", "purple", "lime", "white", "blue", "tan", "yellow"]
DV = -0.45      # sample point: this far from the cell centre, i.e. just inside the cell's far edge (see expected_map)
DARK = 75       # max channel below this: shadow, colour unreliable, counts for nothing (bricks' top faces are > 90)
BRIGHT_W = 0.0  # brightness is left out: near faces are dark, top faces bright, same brick
OTHER_D = 0.13  # farther than this (chromaticity) from every colour centre -> "other" (hand, shadow, table); white-tan are 0.085 apart
CALIB = ("run1_part2_p2", "003.jpg")  # the finished model: colour centres are taken from this frame per frame source


def features(rgb: np.ndarray) -> np.ndarray:
    """Chromaticity (r, g, b)/(r+g+b) plus a damped brightness, for any (..., 3) array."""
    rgb = np.asarray(rgb, dtype=np.float64)
    s = np.maximum(rgb.sum(-1, keepdims=True), 1)
    return np.concatenate([rgb / s, BRIGHT_W * rgb.max(-1, keepdims=True) / 255], -1)


def cells_of(step) -> list[tuple[int, int]]:
    x0, y0, x1, y1 = step["cells"]
    return [(r - 1, c - 1) for r in range(y0, y1 + 1) for c in range(x0, x1 + 1)]


def is_disc(step) -> bool:
    return "disc" in step["name"].lower()


def expected_map(steps, n: int):
    """Class label per cell after step n, plus a care mask. Measured on the recorded run: the camera looks down from
    the row-16 side at ~45-60 deg, so a brick's top face (9.6 mm) appears shifted 0.3-0.8 rows away from the camera and
    its near face is a dim, greenish sliver. Sampling each cell just inside its far edge (DV = -0.45, patch +-0.15)
    therefore lands on the top face of the brick in that cell for any shift in that range, and on the plate otherwise,
    so the expected map is simply the layout. Discs are round: their four corner cells are don't-care."""
    E = np.full((N, N), "plate", dtype=object)
    care = np.ones((N, N), dtype=bool)
    for st in steps[:n]:
        cells = cells_of(st)
        rs = [r for r, _ in cells]
        cs = [c for _, c in cells]
        r0, r1, c0, c1 = min(rs), max(rs), min(cs), max(cs)
        for r, c in cells:
            if is_disc(st) and r in (r0, r1) and c in (c0, c1):
                care[r, c] = False
            else:
                E[r, c] = st["color"]
    return E, care


class Classifier:
    def __init__(self, centres: dict, f: float | None = None):
        self.names = list(centres)
        self.c = np.array([centres[k] for k in self.names])
        self.f = f

    def __call__(self, rgb: np.ndarray) -> str:
        r, g, b = (float(x) for x in rgb)
        if g > 1.4 * r and g > 1.25 * b and b > 0.3 * g:
            return "plate"  # any shade of the plate's green incl. shadow (lime: g/r ~1.3 and almost no blue; blue: b > g)
        if max(r, g, b) < DARK:
            return "dark"
        lime = g > r > 1.5 * b  # yellow-green with little blue; plate shadows keep b/g ~0.5 and fail this
        f = features(rgb)
        d = np.linalg.norm(self.c - f, axis=1)
        i = int(d.argmin())
        if self.names[i] == "lime" and not lime:
            return "other"
        if lime and "lime" in self.names and d[self.names.index("lime")] < 2 * OTHER_D:
            return "lime"
        return self.names[i] if d[i] < OTHER_D else "other"

    @classmethod
    def calibrate(cls, steps, frames_dir: Path):
        """Colour centres = per-class median feature over the cells of the finished model (CALIB frame)."""
        img = Image.open(frames_dir / CALIB[0] / CALIB[1]).convert("RGB")
        pl = Plate(img)
        E, care = expected_map(steps, len(steps))
        cols = pl.cell_colours(DV)
        groups = {k: [] for k in CLASSES}
        for r in range(N):
            for c in range(N):
                if care[r, c] and pl.seen[r, c]:
                    groups[E[r, c]].append(features(cols[r, c]))
        centres = {k: np.median(np.array(v), axis=0) for k, v in groups.items() if v}
        return cls(centres, focal(pl.H, img.size))


def observe(pl: "Plate", clf: Classifier) -> np.ndarray:
    cols = pl.cell_colours(DV)
    O = np.full((N, N), "unseen", dtype=object)
    for r in range(N):
        for c in range(N):
            if pl.seen[r, c]:
                O[r, c] = clf(cols[r, c])
    return O


HIT_OK = 0.7     # share of the step's cells (not counting dark ones) showing its colour -> placed
OTHER_BAD = 0.5  # share of the step's cells showing a colour that belongs to nothing expected -> wrong colour
STRAY_BAD = 2    # cells of the step's colour near its place but outside every expected place -> wrong place
NEAR = 3         # "near": within this many cells of the step's bounding box (a misplaced brick lands close by)
UNSEEN_MAX = 0.5  # more of the step's cells than this unreadable -> cannot_see


def judge(steps, n: int, O: np.ndarray) -> tuple[str, str, dict]:
    """Four-way answer for step n from the observed class map."""
    st = steps[n - 1]
    k = st["color"]
    E_prev, _ = expected_map(steps, n - 1)
    E_now, care = expected_map(steps, n)
    D = [(r, c) for r in range(N) for c in range(N) if care[r, c] and E_now[r, c] != E_prev[r, c]]
    blind = sum(1 for r, c in D if O[r, c] in ("unseen", "other", "dark"))  # out of frame, hand/shadow, too dark
    if not D or blind / len(D) > UNSEEN_MAX:
        return "cannot_see", "the place of this step is out of view or covered", {"blind": blind, "cells": len(D)}
    hit = sum(1 for r, c in D if O[r, c] == k) / max(1, len(D) - blind)
    others = sorted({str(O[r, c]) for r, c in D if O[r, c] in CLASSES and O[r, c] not in (k, "plate", E_prev[r, c])})
    other = sum(1 for r, c in D if O[r, c] in others) / len(D)
    allowed = np.zeros((N, N), dtype=bool)
    for r in range(N):
        for c in range(N):
            if E_now[r, c] == k or not care[r, c]:
                allowed[max(0, r - 1):r + 2, c] = True
    r0, r1 = min(r for r, _ in D) - NEAR, max(r for r, _ in D) + NEAR
    c0, c1 = min(c for _, c in D) - NEAR, max(c for _, c in D) + NEAR
    near = [(r, c) for r in range(max(0, r0), min(N, r1 + 1)) for c in range(max(0, c0), min(N, c1 + 1)) if O[r, c] == k]
    stray = [(r, c) for r, c in near if not allowed[r, c]]
    info = {"hit": round(hit, 2), "other": round(other, 2), "stray": len(stray), "blind": blind, "cells": len(D)}
    if hit >= HIT_OK and len(stray) < STRAY_BAD and other < OTHER_BAD:
        return "correct", f"{int(hit * 100)}% of its cells show {k}", info
    if other >= OTHER_BAD:
        return "wrong", f"{'/'.join(others)} where the {k} brick should be", info
    if len(stray) >= STRAY_BAD:
        fresh = [(r, c) for r, c in near if E_prev[r, c] != k]  # this colour nearby that was not there before this step
        dr = np.mean([r for r, _ in fresh]) - np.mean([r for r, _ in D])
        dc = np.mean([c for _, c in fresh]) - np.mean([c for _, c in D])
        side = (f"{abs(dc):.0f} studs to the {'right' if dc > 0 else 'left'}" if abs(dc) >= abs(dr)
                else f"{abs(dr):.0f} rows {'toward' if dr > 0 else 'away from'} the camera")
        return "wrong", f"the {k} brick sits about {side} of where it should be", info
    return "not_placed", f"only {int(hit * 100)}% of its cells show {k}", info


def class_map_image(M: np.ndarray, care=None, size: int = 12, mark=None) -> Image.Image:
    img = Image.new("RGB", (N * size, N * size))
    d = ImageDraw.Draw(img)
    for r in range(N):
        for c in range(N):
            box = [c * size, r * size, (c + 1) * size - 1, (r + 1) * size - 1]
            d.rectangle(box, fill=PALETTE[M[r, c]])
            if care is not None and not care[r, c]:
                d.line([box[0], box[1], box[2], box[3]], fill=(90, 90, 90))
            if mark is not None and (r, c) in mark:
                d.rectangle(box, outline=(255, 0, 255))
    return img


def colour_map_image(cells: np.ndarray, size: int = 12) -> Image.Image:
    img = Image.new("RGB", (N * size, N * size))
    d = ImageDraw.Draw(img)
    for r in range(N):
        for c in range(N):
            d.rectangle([c * size, r * size, (c + 1) * size - 1, (r + 1) * size - 1], fill=tuple(int(x) for x in cells[r, c]))
    return img


def cmd_run(args):
    """Answer every question in --questions with the CV judge; results in the same jsonl shape as judge_eval."""
    import time
    cm.set_frames(args.frames)
    steps, _ = cm.load()
    clf = Classifier.calibrate(steps, cm.FRAMES)
    qs = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    stem = f"{Path(args.questions).stem}_cv{cm.frames_tag()}"
    out_dir = RESULTS / stem
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "prompt.txt").write_text(
        f"route=D prompt=cv frames={args.frames or 'frames'} dv={DV} hit_ok={HIT_OK} other_bad={OTHER_BAD} stray_bad={STRAY_BAD}\n"
        f"No model. Plate corners from the green silhouette, homography to the 16x16 grid, per-cell median colour at the\n"
        f"cell centre shifted {DV} toward the camera, nearest colour centre (centres from {CALIB[0]}/{CALIB[1]}), compared\n"
        f"with the expected map of step N (brick top faces shifted one row away from the camera).\n"
        f"centres: {json.dumps({k: [round(float(x), 3) for x in v] for k, v in zip(clf.names, clf.c)})} focal_px={clf.f:.0f}\n", encoding="utf-8")
    recs, tiles = [], []
    plates = {}
    for i, q in enumerate(qs, 1):
        key = (q["clip"], q["frame"])
        t0 = time.perf_counter()
        if key not in plates:
            img = Image.open(cm.FRAMES / q["clip"] / q["frame"]).convert("RGB")
            pl = Plate(img, clf.f)
            plates[key] = (pl, observe(pl, clf) if pl.ok else None)
        pl, O = plates[key]
        if O is None:
            answer, reason, info = "cannot_see", "no plate found", {}
        else:
            answer, reason, info = judge(steps, q["step"], O)
        lat = time.perf_counter() - t0
        rec = {"clip": q["clip"], "frame": q["frame"], "step": q["step"], "expected": q["expected"], "answer": answer,
               "reason": reason, "latency": round(lat, 3), "raw": json.dumps(info), "question": f"step {q['step']}"}
        recs.append(rec)
        mark = "" if answer == q["expected"] else "  <-- expected " + q["expected"]
        print(f"Q{i:<3} {q['clip'][5:]}/{q['frame'][:3]} s{q['step']:<3} {answer:<10} {reason}{mark}")
        # tile: crop with grid | observed | expected (new cells outlined)
        E_now, care = expected_map(steps, q["step"])
        E_prev, _ = expected_map(steps, q["step"] - 1)
        D = {(r, c) for r in range(N) for c in range(N) if care[r, c] and E_now[r, c] != E_prev[r, c]}
        tile = Image.new("RGB", (240 + 2 * 192 + 24, 270), "white")
        d = ImageDraw.Draw(tile)
        d.text((4, 4), f"Q{i} {q['clip'][5:]}/{q['frame'][:3]} step {q['step']}: {answer} (expected {q['expected']}) {reason}"[:95],
               fill=(0, 120, 0) if answer == q["expected"] else (200, 0, 0))
        if pl.ok:
            crop = pl.draw()
            crop.thumbnail((240, 240))
            tile.paste(crop, (0, 24))
            tile.paste(class_map_image(O, care), (252, 24))
        tile.paste(class_map_image(E_now, care, mark=D), (252 + 204, 24))
        tiles.append(tile)
    (RESULTS / f"{stem}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    cols = 2
    rows = (len(tiles) + cols - 1) // cols
    tw, th = tiles[0].size
    sheet = Image.new("RGB", (cols * tw, rows * th), "white")
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * tw, (i // cols) * th))
    SHEETS.mkdir(parents=True, exist_ok=True)
    sheet_path = SHEETS / f"{stem}.jpg"
    sheet.save(sheet_path, quality=85)
    ok = sum(r["answer"] == r["expected"] for r in recs)
    print(f"{ok}/{len(recs)} ; median latency {sorted(r['latency'] for r in recs)[len(recs) // 2]:.3f} s ; sheet -> {sheet_path}")


def cmd_overlay(args):
    """Grid fit check: crop with the grid | raw sampled colour per cell, for every distinct question frame."""
    cm.set_frames(args.frames)
    qs = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    seen = set()
    tiles = []
    for i, q in enumerate(qs, 1):
        key = (q["clip"], q["frame"])
        if key in seen:
            continue
        seen.add(key)
        img = Image.open(cm.FRAMES / q["clip"] / q["frame"]).convert("RGB")
        pl = Plate(img)
        label = f"Q{i} {q['clip'][5:]}/{q['frame'][:3]}"
        if not pl.ok:
            t = Image.new("RGB", (300 + 200, 320), "white")
            ImageDraw.Draw(t).text((4, 4), label + "  no plate", fill="red")
            tiles.append(t)
            continue
        crop = pl.draw()
        crop.thumbnail((300, 300))
        cmap = colour_map_image(pl.cell_colours(DV))
        t = Image.new("RGB", (300 + cmap.width + 8, 320), "white")
        t.paste(crop, (0, 20))
        t.paste(cmap, (308, 20))
        ImageDraw.Draw(t).text((4, 4), label, fill="black")
        tiles.append(t)
        print(label, "corners", pl.corners.round().astype(int).tolist())
    cols = 3
    rows = (len(tiles) + cols - 1) // cols
    tw, th = tiles[0].size
    sheet = Image.new("RGB", (cols * tw, rows * th), "white")
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * tw, (i // cols) * th))
    SHEETS.mkdir(parents=True, exist_ok=True)
    out = SHEETS / f"grid{cm.frames_tag()}.jpg"
    sheet.save(out, quality=85)
    print("sheet ->", out)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("overlay")
    p.add_argument("--frames")
    p.add_argument("--questions", default=str(cm.TRUCK / "rest.json"))
    p.set_defaults(fn=cmd_overlay)
    p = sub.add_parser("run")
    p.add_argument("--frames")
    p.add_argument("--questions", default=str(cm.TRUCK / "rest.json"))
    p.set_defaults(fn=cmd_run)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
