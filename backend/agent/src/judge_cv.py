"""The CV judge: one camera frame in, a four-way verdict on one step out. No model.

The task is a flat layout on a green 16x16 baseplate (guides/truck/task.toml:
every step has a colour and a footprint in plate cells). Judging a step is then
geometry plus colour, which this file does with PIL and numpy in ~0.1 s:

1. plate: saturated-green mask -> closed silhouette -> convex hull -> the hull
   edges merged into straight segments -> the longest roughly horizontal
   segment above / below the centre and the longest roughly vertical one left /
   right are the four sides -> least-squares lines -> corners. Bricks sit inside
   the plate and a hand over a corner leaves the true sides the longest.
2. a side cut off by the frame border (the near edge, often): with the focal
   length known, the two missing corners follow from the other three sides and
   the plate being square. The focal length is a camera constant; the judge
   fits it from frames that show the whole plate (principal point at the image
   centre, square pixels): the f for which rebuilding each side of those
   plates from the other three lands on the measured corners. Four such frames
   give it within 1 % on the recorded run (a per-frame closed form was off by
   up to 2x), so a session calibrates itself in its first seconds; JUDGE_FOCAL_PX
   can pin it instead.
3. grid: four corners -> homography -> each cell's sample point in the image.
4. colour per cell, sampled just inside the cell's far edge (DV): the camera
   looks down from the near side at 45-60 deg, so a brick's top face appears
   shifted 0.3-0.8 rows away from the camera and its near face is a dim sliver;
   the far-edge point lands on the top face of the brick in that cell for any
   shift in that range and on the plate otherwise, so the expected map is the
   layout itself.
5. class per cell: rules for plate green, too dark and lime; otherwise nearest
   colour centre in chromaticity (r, g, b)/(r+g+b), brightness left out (the
   same brick is bright on top and dark on the side); far from every centre is
   "other" (hand, table). The centres live in the task file ([colours]) and
   were measured on the recorded run; `calibrate()` recomputes them from a
   frame of the finished model.
6. verdict for step n: D = the cells the step adds. Too many of them
   unreadable -> cannot_see. Enough of them in the step's colour and nothing
   else amiss -> correct. Another brick colour on them -> wrong ("<colour>
   where the <k> brick should be"). The step's colour near D but off every
   place it belongs -> wrong ("about N studs to the right"). Otherwise
   not_placed. Thresholds were tuned on the 29 rest questions of eval/truck.

Evaluated offline in eval/cv_judge.py and eval/replay_eval.py, which import
this file; the numbers in eval/RESULTS.md are from this code.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ANSWERS = ("correct", "wrong", "not_placed", "cannot_see")

DV = -0.45       # sample point: this far from the cell centre along rows, i.e. just inside the cell's far edge
DARK = 75        # max channel below this: shadow, colour unreliable, counts for nothing (bricks' top faces are > 90)
OTHER_D = 0.13   # farther than this (chromaticity) from every colour centre -> "other"; white and tan are 0.085 apart
HIT_OK = 0.7     # share of the step's cells (not counting unreadable ones) showing its colour -> placed
OTHER_BAD = 0.5  # share of the step's cells showing a colour that belongs to nothing expected -> wrong colour
STRAY_BAD = 2    # cells of the step's colour near its place but outside every expected place -> wrong place
NEAR = 3         # "near": within this many cells of the step's bounding box (a misplaced brick lands close by)
UNSEEN_MAX = 0.5  # more of the step's cells than this unreadable -> cannot_see
FOCAL_MIN = 4      # full-plate frames needed before the focal length is fitted
FOCAL_MEMORY = 20  # full-plate frames kept for the fit; the fit is redone at every FOCAL_MIN new ones until full


# ------------------------------------------------------------------ plate geometry

def green_mask(img: Image.Image, s: int) -> np.ndarray:
    """Plate green at 1/s scale: g/r > 3 on the plate, ~1.3 on lime bricks, and blue has b > g."""
    small = img.copy()
    small.thumbnail((img.width // s, img.height // s))
    a = np.asarray(small.convert("RGB")).astype(np.float32) / 255
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(-1), a.min(-1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    return (g > 2.0 * r) & (g > 1.5 * b) & (sat > 0.35) & (mx > 0.25)


def components(mask: np.ndarray) -> list[np.ndarray]:
    """4-connected True regions of a small boolean mask as (y, x) index arrays, largest first (plain BFS; no scipy/cv2)."""
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


def close(mask: np.ndarray, k: int) -> np.ndarray:
    """Morphological closing with a k x k square (k odd)."""
    return np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(k))
                      .filter(ImageFilter.MinFilter(k))) > 0


def silhouette(img: Image.Image, s: int = 4) -> np.ndarray | None:
    """Plate pixels as (x, y) full-resolution points: closed green mask, largest blob plus nearby blobs of at least a
    fifth of its size (hands split the plate; screens and lime bricks also pass the colour test but are small or far)."""
    mask = green_mask(img, s)
    k = 2 * (9 * 8 // s // 2) + 1  # ~2 studs, odd
    comps = components(close(mask, k))
    if not comps or len(comps[0]) < 400 * (8 / s) ** 2:
        return None
    main = comps[0]
    cy, cx = main.mean(0)
    size = max(np.ptp(main[:, 0]), np.ptp(main[:, 1]))
    keep = [main] + [c for c in comps[1:] if len(c) >= len(main) / 5 and np.hypot(*(c.mean(0) - (cy, cx))) < size]
    pts = np.concatenate(keep)  # (y, x)
    return pts[:, ::-1].astype(np.float64) * s + s / 2


def hull(pts: np.ndarray) -> np.ndarray:
    """Convex hull (monotone chain) of (x, y) points."""
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
    """Total least squares line through points: (point, direction)."""
    c = pts.mean(0)
    _, _, vt = np.linalg.svd(pts - c)
    return c, vt[0]


def intersect(l1, l2):
    (p1, d1), (p2, d2) = l1, l2
    t = np.linalg.solve(np.array([d1, -d2]).T, p2 - p1)
    return p1 + t[0] * d1


def segments(h: np.ndarray, tol_deg: float = 4.0):
    """Hull edges merged while nearly collinear -> list of (length, angle_deg, hull points)."""
    n = len(h)
    edges = [(i, (i + 1) % n) for i in range(n)]
    ang = [np.degrees(np.arctan2(*(h[b] - h[a])[::-1])) for a, b in edges]
    segs, cur = [], [0]
    for i in range(1, n):
        if abs((ang[i] - ang[cur[-1]] + 180) % 360 - 180) < tol_deg:
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
        a, b = h[edges[sg[0]][0]], h[edges[sg[-1]][1]]
        d = b - a
        out.append((float(np.hypot(*d)), float(np.degrees(np.arctan2(d[1], d[0]))), h[idx]))
    return out


def corners(sil: np.ndarray, size):
    """Four plate corners TL, TR, BR, BL, the hull, and which sides lie along the frame border (cut off)."""
    h = hull(sil)
    cx, cy = h.mean(0)
    sides, cut = {}, set()
    for length, ang, pts in segments(h):
        on_border = (((pts[:, 0] < 3) | (pts[:, 0] > size[0] - 4)).all()
                     or ((pts[:, 1] < 3) | (pts[:, 1] > size[1] - 4)).all())
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
            sides[key] = (length, pts)
    if len(sides) < 4 or any(len(v[1]) < 2 for v in sides.values()):
        return None, h, []
    L = {k: fit_line(v[1]) for k, v in sides.items()}
    out = [intersect(L["top"], L["left"]), intersect(L["top"], L["right"]),
           intersect(L["bottom"], L["right"]), intersect(L["bottom"], L["left"])]
    return np.array(out), h, sorted(cut)


def focal(H: np.ndarray, size) -> float | None:
    """Focal length (px) from the homography of a square seen in full: the two plane axes are orthogonal in camera
    space; principal point at the image centre, square pixels."""
    w, h = size
    h1, h2 = H[:, 0].copy(), H[:, 1].copy()
    for v in (h1, h2):
        v[0] -= w / 2 * v[2]
        v[1] -= h / 2 * v[2]
    f2 = -(h1[0] * h2[0] + h1[1] * h2[1]) / (h1[2] * h2[2])
    return float(np.sqrt(f2)) if f2 > 0 else None


def fit_focal(corners_list, size, n: int = 16) -> tuple[float, float]:
    """Focal length (px) from plates seen in full: the f for which far_corners rebuilds every side of every plate from
    the other three closest to the measured corners. Returns (f, median corner error in cells). Coarse log-spaced
    search over 0.3-4x the frame size, then a fine one around the best."""

    def err(f: float) -> float:
        e = []
        for c in corners_list:
            cell = np.mean([np.linalg.norm(c[(i + 1) % 4] - c[i]) for i in range(4)]) / n
            for i in range(4):
                try:
                    nb, na = far_corners(c[(i + 2) % 4], c[(i + 3) % 4], c[(i + 1) % 4], c[i], f, size)
                except (np.linalg.LinAlgError, ZeroDivisionError, FloatingPointError):
                    return np.inf
                d = (np.linalg.norm(nb - c[i]) + np.linalg.norm(na - c[(i + 1) % 4])) / 2 / cell
                if not np.isfinite(d):
                    return np.inf
                e.append(d)
        return float(np.median(e))

    with np.errstate(all="ignore"):
        coarse = np.geomspace(0.3 * max(size), 4 * max(size), 80)
        best = coarse[int(np.argmin([err(f) for f in coarse]))]
        fine = np.linspace(best / 1.15, best * 1.15, 61)
        errs = [err(f) for f in fine]
    i = int(np.argmin(errs))
    return float(fine[i]), float(errs[i])


def far_corners(A, B, A2, B2, f: float, size):
    """The plate is square: from its two corners A, B on one fully visible side, one more point on each adjacent side
    (A2 on the side through A, B2 through B) and the focal length, the two corners of the opposite side (the one
    next to B first, then the one next to A)."""
    w, h = size
    K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]])
    Ki = np.linalg.inv(K)
    A, B, A2, B2 = (np.r_[np.asarray(p, dtype=float), 1.0] for p in (A, B, A2, B2))
    dv = Ki @ np.cross(np.cross(A, A2), np.cross(B, B2))  # direction of the two adjacent sides
    dv /= np.linalg.norm(dv)
    a, b = Ki @ A, Ki @ (B - A)
    du = Ki @ (A + (-(a @ dv) / (b @ dv)) * (B - A))  # direction of side AB: its point orthogonal to dv
    du /= np.linalg.norm(du)
    n = np.cross(du, dv)
    XA = Ki @ A
    XB = (n @ XA) / (n @ (Ki @ B)) * (Ki @ B)
    step = np.linalg.norm(XB - XA) * dv
    if np.dot(((K @ (XA + step))[:2] / (XA + step)[2]) - A[:2], A2[:2] - A[:2]) < 0:
        step = -step  # toward the cut side
    out = []
    for X in (XB + step, XA + step):
        x = K @ X
        out.append(x[:2] / x[2])
    return out


def homography(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """H with dst ~ H @ src (four-point DLT)."""
    rows = []
    for (u, v), (x, y) in zip(src, dst):
        rows.append([u, v, 1, 0, 0, 0, -x * u, -x * v, -x])
        rows.append([0, 0, 0, u, v, 1, -y * u, -y * v, -y])
    _, _, vt = np.linalg.svd(np.array(rows, dtype=np.float64))
    return vt[-1].reshape(3, 3)


def project(H: np.ndarray, uv: np.ndarray) -> np.ndarray:
    p = np.c_[uv, np.ones(len(uv))] @ H.T
    return p[:, :2] / p[:, 2:3]


class Plate:
    """Plate geometry of one frame: corners, cut sides, homography from grid (0..n)^2 to image pixels.
    With f (focal length, px) one side cut off by the frame border is rebuilt from the other three."""

    def __init__(self, img: Image.Image, f: float | None = None, n: int = 16) -> None:
        self.img = img
        self.n = n
        self.arr = np.asarray(img.convert("RGB"))
        self.ok = False
        self.cut: list[str] = []
        sil = silhouette(img)
        if sil is None:
            return
        self.corners, self.hull, self.cut = corners(sil, img.size)
        if self.corners is None:
            return
        if f and len(self.cut) == 1:
            c = self.corners
            i = ["top", "right", "bottom", "left"].index(self.cut[0])  # side i runs from corner i to corner i+1
            A, B = c[(i + 2) % 4], c[(i + 3) % 4]  # the opposite side, fully visible
            nb, na = far_corners(A, B, c[(i + 1) % 4], c[i], f, img.size)
            c[i], c[(i + 1) % 4] = nb, na
        grid = np.array([[0, 0], [n, 0], [n, n], [0, n]], dtype=np.float64)
        self.H = homography(grid, self.corners)
        self.ok = True

    def sample(self, u: float, v: float, rad: float = 0.15, k: int = 5) -> np.ndarray:
        """Median RGB of a k x k patch of grid points within +-rad cell of (u, v)."""
        g = np.linspace(-rad, rad, k)
        uv = np.array([(u + du, v + dv) for du in g for dv in g])
        xy = project(self.H, uv).round().astype(int)
        h, w = self.arr.shape[:2]
        xy[:, 0] = xy[:, 0].clip(0, w - 1)
        xy[:, 1] = xy[:, 1].clip(0, h - 1)
        return np.median(self.arr[xy[:, 1], xy[:, 0]], axis=0)

    def cell_colours(self, dv: float = DV) -> tuple[np.ndarray, np.ndarray]:
        """(n, n, 3) raw median colour per cell [row, col] sampled dv rows from the centre, and an (n, n) mask of
        the sample points that lie inside the image."""
        n = self.n
        out = np.zeros((n, n, 3))
        seen = np.ones((n, n), dtype=bool)
        h, w = self.arr.shape[:2]
        for r in range(n):
            for c in range(n):
                x, y = project(self.H, np.array([[c + 0.5, r + 0.5 + dv]]))[0]
                seen[r, c] = 0 <= x < w and 0 <= y < h
                out[r, c] = self.sample(c + 0.5, r + 0.5 + dv)
        return out, seen

    def draw(self, pad: float = 0.08) -> Image.Image:
        """Crop around the plate with the fitted grid and corners drawn on it, for frame dumps and eval sheets."""
        n = self.n
        xs, ys = self.corners[:, 0], self.corners[:, 1]
        w, h = xs.max() - xs.min(), ys.max() - ys.min()
        x0, y0 = int(max(0, xs.min() - w * pad)), int(max(0, ys.min() - h * pad))
        x1, y1 = int(min(self.img.width, xs.max() + w * pad)), int(min(self.img.height, ys.max() + h * pad))
        crop = self.img.crop((x0, y0, x1, y1)).convert("RGB")
        d = ImageDraw.Draw(crop)
        for i in range(n + 1):
            a = project(self.H, np.array([[i, 0], [i, n]], dtype=float)) - (x0, y0)
            b = project(self.H, np.array([[0, i], [n, i]], dtype=float)) - (x0, y0)
            col = (255, 255, 0) if i % 4 else (255, 80, 255)
            d.line([tuple(a[0]), tuple(a[1])], fill=col, width=1)
            d.line([tuple(b[0]), tuple(b[1])], fill=col, width=1)
        for p in self.corners:
            x, y = p - (x0, y0)
            d.ellipse([x - 5, y - 5, x + 5, y + 5], outline=(255, 0, 0), width=2)
        return crop


# ------------------------------------------------------------------ layout and colour

@dataclass(frozen=True)
class Brick:
    color: str
    cells: tuple[int, int, int, int]  # col0, row0, col1, row1, 1-based inclusive
    disc: bool = False  # round: the four corner cells of the footprint are don't-care


class Layout:
    """The task as the judge sees it: one brick per step, on an n x n plate."""

    def __init__(self, bricks: list[Brick], n: int = 16) -> None:
        self.bricks = bricks
        self.n = n
        self.colours = sorted({b.color for b in bricks})
        self._maps: dict[int, tuple[np.ndarray, np.ndarray]] = {}

    @classmethod
    def from_guide(cls, guide) -> Layout:
        """From guide.Guide: every step needs `color` and `cells`."""
        bricks = []
        for i, s in enumerate(guide.steps, 1):
            if not s.color or s.cells is None:
                raise ValueError(f"{guide.name}: step {i} has no color/cells; the CV judge needs a flat layout")
            bricks.append(Brick(s.color, tuple(s.cells), "disc" in (s.part + " " + s.name).lower()))
        return cls(bricks, guide.plate)

    @classmethod
    def from_dicts(cls, steps, n: int = 16) -> Layout:
        """From the eval's step dicts (task.toml steps with color/cells/name)."""
        return cls([Brick(s["color"], tuple(s["cells"]), "disc" in s["name"].lower()) for s in steps], n)

    @staticmethod
    def cells_of(b: Brick) -> list[tuple[int, int]]:
        x0, y0, x1, y1 = b.cells
        return [(r - 1, c - 1) for r in range(y0, y1 + 1) for c in range(x0, x1 + 1)]

    def expected(self, k: int) -> tuple[np.ndarray, np.ndarray]:
        """Class label per cell after k steps (0 = empty plate) and a care mask (False on disc corners)."""
        if k not in self._maps:
            n = self.n
            E = np.full((n, n), "plate", dtype=object)
            care = np.ones((n, n), dtype=bool)
            for b in self.bricks[:k]:
                cells = self.cells_of(b)
                rs, cs = [r for r, _ in cells], [c for _, c in cells]
                r0, r1, c0, c1 = min(rs), max(rs), min(cs), max(cs)
                for r, c in cells:
                    if b.disc and r in (r0, r1) and c in (c0, c1):
                        care[r, c] = False
                    else:
                        E[r, c] = b.color
            self._maps[k] = (E, care)
        return self._maps[k]

    def new_cells(self, k: int) -> list[tuple[int, int]]:
        """The cells step k (1-based) adds."""
        E_prev, _ = self.expected(k - 1)
        E_now, care = self.expected(k)
        n = self.n
        return [(r, c) for r in range(n) for c in range(n) if care[r, c] and E_now[r, c] != E_prev[r, c]]


def chroma(rgb) -> np.ndarray:
    """Chromaticity (r, g, b)/(r+g+b) of any (..., 3) array."""
    rgb = np.asarray(rgb, dtype=np.float64)
    return rgb / np.maximum(rgb.sum(-1, keepdims=True), 1)


class Colours:
    """Cell colour -> class name: plate, dark, other, or one of the brick colours (nearest chromaticity centre)."""

    def __init__(self, centres: dict[str, tuple[float, float, float]]) -> None:
        self.names = list(centres)
        self.c = np.array([centres[k][:3] for k in self.names], dtype=np.float64)

    def __call__(self, rgb) -> str:
        r, g, b = (float(x) for x in rgb)
        if g > 1.4 * r and g > 1.25 * b and b > 0.3 * g:
            return "plate"  # any shade of the plate's green incl. shadow (lime: g/r ~1.3, little blue; blue: b > g)
        if max(r, g, b) < DARK:
            return "dark"
        lime = g > r > 1.5 * b  # yellow-green with little blue; plate shadows keep b/g ~0.5 and fail this
        d = np.linalg.norm(self.c - chroma(rgb), axis=1)
        i = int(d.argmin())
        if self.names[i] == "lime" and not lime:
            return "other"
        if lime and "lime" in self.names and d[self.names.index("lime")] < 2 * OTHER_D:
            return "lime"
        return self.names[i] if d[i] < OTHER_D else "other"

    def as_dict(self) -> dict[str, list[float]]:
        return {k: [round(float(x), 3) for x in v] for k, v in zip(self.names, self.c)}


# ------------------------------------------------------------------ the judge

@dataclass(frozen=True)
class Verdict:
    answer: str  # one of ANSWERS
    reason: str  # one plain sentence the voice can relay ("the blue brick sits about 2 studs to the right of ...")
    info: dict = field(default_factory=dict)  # hit / other / stray / blind / cells, for the log
    seconds: float = 0.0


@dataclass
class Observation:
    """One frame read: the plate geometry and the class of every cell ("unseen" where the sample point is off-image)."""
    plate: Plate
    classes: np.ndarray | None  # (n, n) of str, None when no plate was found

    @property
    def ok(self) -> bool:
        return self.classes is not None


class CVJudge:
    def __init__(self, layout: Layout, centres: dict, f: float | None = None) -> None:
        self.layout = layout
        self.colours = Colours(centres)
        self.f = f  # focal length in px; None until fitted from full-plate frames (or pinned by the caller)
        self.f_error: float | None = None  # median corner error of the fit, in cells
        self._pinned = f is not None
        self._full: list[np.ndarray] = []  # corners of full-plate frames, for the fit

    def observe(self, img: Image.Image) -> Observation:
        """Find the plate, read every cell. Frames that show the whole plate also feed the focal-length fit."""
        pl = Plate(img, self.f, self.layout.n)
        if not pl.ok:
            return Observation(pl, None)
        if not pl.cut and not self._pinned and len(self._full) < FOCAL_MEMORY:
            self._full.append(pl.corners.copy())
            if len(self._full) % FOCAL_MIN == 0:
                self.f, self.f_error = fit_focal(self._full, img.size, self.layout.n)
        cols, seen = pl.cell_colours(DV)
        n = self.layout.n
        O = np.full((n, n), "unseen", dtype=object)
        for r in range(n):
            for c in range(n):
                if seen[r, c]:
                    O[r, c] = self.colours(cols[r, c])
        return Observation(pl, O)

    def decide(self, obs: Observation, step: int) -> Verdict:
        """Verdict on step `step` (1-based) from an observation."""
        if not obs.ok:
            return Verdict("cannot_see", "the plate is not in view", {})
        L, O, n = self.layout, obs.classes, self.layout.n
        k = L.bricks[step - 1].color
        E_prev, _ = L.expected(step - 1)
        E_now, care = L.expected(step)
        D = L.new_cells(step)
        blind = sum(1 for r, c in D if O[r, c] in ("unseen", "other", "dark"))  # off-image, hand/shadow, too dark
        if not D or blind / len(D) > UNSEEN_MAX:
            return Verdict("cannot_see", "the place of this step is out of view or covered", {"blind": blind, "cells": len(D)})
        hit = sum(1 for r, c in D if O[r, c] == k) / max(1, len(D) - blind)
        others = sorted({str(O[r, c]) for r, c in D if O[r, c] in L.colours and O[r, c] not in (k, "plate", E_prev[r, c])})
        other = sum(1 for r, c in D if O[r, c] in others) / len(D)
        allowed = np.zeros((n, n), dtype=bool)
        for r in range(n):
            for c in range(n):
                if E_now[r, c] == k or not care[r, c]:
                    allowed[max(0, r - 1):r + 2, c] = True  # one row of slack for the top-face shift
        r0, r1 = min(r for r, _ in D) - NEAR, max(r for r, _ in D) + NEAR
        c0, c1 = min(c for _, c in D) - NEAR, max(c for _, c in D) + NEAR
        near = [(r, c) for r in range(max(0, r0), min(n, r1 + 1)) for c in range(max(0, c0), min(n, c1 + 1)) if O[r, c] == k]
        stray = [(r, c) for r, c in near if not allowed[r, c]]
        info = {"hit": round(hit, 2), "other": round(other, 2), "stray": len(stray), "blind": blind, "cells": len(D)}
        if hit >= HIT_OK and len(stray) < STRAY_BAD and other < OTHER_BAD:
            return Verdict("correct", f"{int(hit * 100)}% of its cells show {k}", info)
        if other >= OTHER_BAD:
            return Verdict("wrong", f"{'/'.join(others)} where the {k} brick should be", info)
        if len(stray) >= STRAY_BAD:
            fresh = [(r, c) for r, c in near if E_prev[r, c] != k]  # this colour nearby that was not there before
            dr = np.mean([r for r, _ in fresh]) - np.mean([r for r, _ in D])
            dc = np.mean([c for _, c in fresh]) - np.mean([c for _, c in D])
            side = (f"{abs(dc):.0f} studs to the {'right' if dc > 0 else 'left'}" if abs(dc) >= abs(dr)
                    else f"{abs(dr):.0f} rows {'toward' if dr > 0 else 'away from'} the camera")
            return Verdict("wrong", f"the {k} brick sits about {side} of where it should be", info)
        return Verdict("not_placed", f"only {int(hit * 100)}% of its cells show {k}", info)

    def judge(self, img: Image.Image, step: int) -> Verdict:
        """One frame, one step: observe + decide, timed."""
        t0 = time.perf_counter()
        v = self.decide(self.observe(img), step)
        return Verdict(v.answer, v.reason, v.info, time.perf_counter() - t0)

    def calibrate(self, img: Image.Image, steps_done: int | None = None) -> dict[str, list[float]]:
        """Colour centres from a frame showing the build after `steps_done` steps (default: finished): the median
        chromaticity over the cells of each colour. Writes nothing; the result goes into the task file by hand."""
        obs_plate = Plate(img, self.f, self.layout.n)
        if not obs_plate.ok:
            raise ValueError("no plate in the calibration frame")
        k = len(self.layout.bricks) if steps_done is None else steps_done
        E, care = self.layout.expected(k)
        cols, seen = obs_plate.cell_colours(DV)
        groups: dict[str, list] = {}
        for r in range(self.layout.n):
            for c in range(self.layout.n):
                if care[r, c] and seen[r, c]:
                    groups.setdefault(str(E[r, c]), []).append(chroma(cols[r, c]))
        centres = {name: np.median(np.array(v), axis=0) for name, v in groups.items()}
        return {k: [round(float(x), 3) for x in v] for k, v in centres.items()}
