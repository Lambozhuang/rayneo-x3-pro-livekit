"""Route D on the recorded run: the agent's own CV judge (backend/agent/src/judge_cv.py) over the rest questions.

  python eval/cv_judge.py overlay   [--frames frames_1080p15] [--questions truck/rest.json]
  python eval/cv_judge.py run       [--frames frames_1080p15] [--questions truck/rest.json]
  python eval/cv_judge.py calibrate <frame.jpg> [--steps 13]
      overlay   -> truck/run1/sheets/cv/grid[_1080p15].jpg: every question frame with the fitted grid and the raw colour
                   sampled at each cell. Look at this before trusting anything downstream.
      run       -> truck/results/cv/<questions>_cv[_1080p15].jsonl (same shape as vlm_judge) + sheets/cv/<stem>.jpg with,
                   per question, the crop with the grid | the observed class map | the expected map (new cells outlined).
      calibrate -> colour centres from one frame of the build after --steps steps, to paste into task.toml [colours].

The method, thresholds and colour centres are the agent's (judge_cv.py, guides/truck/task.toml); this file only
feeds frames in and draws. `run` fits the focal length on the full-plate question frames up front (a session has it after
its first seconds); the replay (replay_eval.py) lets the judge fit it online, as in production.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as cm  # noqa: E402
import judge_cv as jc  # noqa: E402  (backend/agent/src, on the path via common)

RESULTS = cm.RESULTS / "cv"
SHEETS = cm.SHEETS / "cv"

PALETTE = {"plate": (40, 140, 60), "red": (200, 30, 20), "purple": (120, 30, 150), "lime": (170, 210, 40),
           "white": (240, 240, 240), "blue": (20, 80, 200), "tan": (215, 190, 140), "yellow": (250, 200, 0),
           "other": (0, 0, 0), "unseen": (128, 128, 128), "dark": (60, 60, 60)}


def make_judge(steps, calibrate_from=None) -> jc.CVJudge:
    """The agent's judge on the eval's task dicts, colour centres from the task file. `calibrate_from` = frame paths
    whose full-plate views fit the focal length up front (as a session has after its first seconds); None = online."""
    layout = jc.Layout.from_dicts(steps, cm.task()["plate"])
    judge = jc.CVJudge(layout, cm.task()["colours"])
    if calibrate_from:
        for p in calibrate_from:
            img = Image.open(p).convert("RGB")
            pl = jc.Plate(img, None, layout.n)
            if pl.ok and not pl.cut:
                judge._full.append(pl.corners.copy())
        judge.f, judge.f_error = jc.fit_focal(judge._full, img.size, layout.n)
        judge._pinned = True
    return judge


def class_map_image(M, care=None, size: int = 12, mark=None) -> Image.Image:
    n = M.shape[0]
    img = Image.new("RGB", (n * size, n * size))
    d = ImageDraw.Draw(img)
    for r in range(n):
        for c in range(n):
            box = [c * size, r * size, (c + 1) * size - 1, (r + 1) * size - 1]
            d.rectangle(box, fill=PALETTE[M[r, c]])
            if care is not None and not care[r, c]:
                d.line([box[0], box[1], box[2], box[3]], fill=(90, 90, 90))
            if mark is not None and (r, c) in mark:
                d.rectangle(box, outline=(255, 0, 255))
    return img


def colour_map_image(cells, size: int = 12) -> Image.Image:
    n = cells.shape[0]
    img = Image.new("RGB", (n * size, n * size))
    d = ImageDraw.Draw(img)
    for r in range(n):
        for c in range(n):
            d.rectangle([c * size, r * size, (c + 1) * size - 1, (r + 1) * size - 1], fill=tuple(int(x) for x in cells[r, c]))
    return img


def sheet_of(tiles, cols: int) -> Image.Image:
    rows = (len(tiles) + cols - 1) // cols
    tw, th = tiles[0].size
    sheet = Image.new("RGB", (cols * tw, rows * th), "white")
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * tw, (i // cols) * th))
    return sheet


def cmd_run(args):
    cm.set_frames(args.frames)
    steps, _ = cm.load()
    qs = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    judge = make_judge(steps, [cm.FRAMES / q["clip"] / q["frame"] for q in qs])
    L = judge.layout
    stem = f"{Path(args.questions).stem}_cv{cm.frames_tag()}"
    out_dir = RESULTS / stem
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "prompt.txt").write_text(
        f"route=D prompt=cv frames={args.frames or 'frames'} dv={jc.DV} hit_ok={jc.HIT_OK} other_bad={jc.OTHER_BAD} stray_bad={jc.STRAY_BAD}\n"
        f"No model: backend/agent/src/judge_cv.py (the agent's judge). Plate corners from the green silhouette, a side cut by the\n"
        f"frame rebuilt from the focal length, homography to the {L.n}x{L.n} grid, per-cell median colour {jc.DV} rows from the cell\n"
        f"centre (just inside the far edge), nearest colour centre from guides/truck/task.toml [colours], compared with the layout.\n"
        f"centres: {json.dumps(judge.colours.as_dict())} focal_px={judge.f:.0f} (fit on {len(judge._full)} full-plate question frames, "
        f"corner error {judge.f_error:.2f} cells)\n", encoding="utf-8")
    recs, tiles, obs = [], [], {}
    for i, q in enumerate(qs, 1):
        key = (q["clip"], q["frame"])
        t0 = time.perf_counter()
        if key not in obs:
            obs[key] = judge.observe(Image.open(cm.FRAMES / q["clip"] / q["frame"]).convert("RGB"))
        v = judge.decide(obs[key], q["step"])
        lat = time.perf_counter() - t0
        recs.append({"clip": q["clip"], "frame": q["frame"], "step": q["step"], "expected": q["expected"], "answer": v.answer,
                     "reason": v.reason, "latency": round(lat, 3), "raw": json.dumps(v.info), "question": f"step {q['step']}"})
        mark = "" if v.answer == q["expected"] else "  <-- expected " + q["expected"]
        print(f"Q{i:<3} {q['clip'][5:]}/{q['frame'][:3]} s{q['step']:<3} {v.answer:<10} {v.reason}{mark}")
        E_now, care = L.expected(q["step"])
        D = set(L.new_cells(q["step"]))
        tile = Image.new("RGB", (240 + 2 * 192 + 24, 270), "white")
        d = ImageDraw.Draw(tile)
        d.text((4, 4), f"Q{i} {q['clip'][5:]}/{q['frame'][:3]} step {q['step']}: {v.answer} (expected {q['expected']}) {v.reason}"[:95],
               fill=(0, 120, 0) if v.answer == q["expected"] else (200, 0, 0))
        o = obs[key]
        if o.ok:
            crop = o.plate.draw()
            crop.thumbnail((240, 240))
            tile.paste(crop, (0, 24))
            tile.paste(class_map_image(o.classes, care), (252, 24))
        tile.paste(class_map_image(E_now, care, mark=D), (252 + 204, 24))
        tiles.append(tile)
    (RESULTS / f"{stem}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    SHEETS.mkdir(parents=True, exist_ok=True)
    sheet_path = SHEETS / f"{stem}.jpg"
    sheet_of(tiles, 2).save(sheet_path, quality=85)
    ok = sum(r["answer"] == r["expected"] for r in recs)
    print(f"{ok}/{len(recs)} ; median latency {sorted(r['latency'] for r in recs)[len(recs) // 2]:.3f} s ; sheet -> {sheet_path}")


def cmd_overlay(args):
    cm.set_frames(args.frames)
    n = cm.task()["plate"]
    qs = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    seen, tiles = set(), []
    for i, q in enumerate(qs, 1):
        key = (q["clip"], q["frame"])
        if key in seen:
            continue
        seen.add(key)
        pl = jc.Plate(Image.open(cm.FRAMES / q["clip"] / q["frame"]).convert("RGB"), None, n)
        label = f"Q{i} {q['clip'][5:]}/{q['frame'][:3]}"
        if not pl.ok:
            t = Image.new("RGB", (500, 320), "white")
            ImageDraw.Draw(t).text((4, 4), label + "  no plate", fill="red")
            tiles.append(t)
            continue
        crop = pl.draw()
        crop.thumbnail((300, 300))
        cmap = colour_map_image(pl.cell_colours()[0])
        t = Image.new("RGB", (300 + cmap.width + 8, 320), "white")
        t.paste(crop, (0, 20))
        t.paste(cmap, (308, 20))
        ImageDraw.Draw(t).text((4, 4), label, fill="black")
        tiles.append(t)
        print(label, "corners", pl.corners.round().astype(int).tolist(), "cut", pl.cut)
    SHEETS.mkdir(parents=True, exist_ok=True)
    out = SHEETS / f"grid{cm.frames_tag()}.jpg"
    sheet_of(tiles, 3).save(out, quality=85)
    print("sheet ->", out)


def cmd_calibrate(args):
    steps, _ = cm.load()
    judge = jc.CVJudge(jc.Layout.from_dicts(steps, cm.task()["plate"]), cm.task()["colours"])
    centres = judge.calibrate(Image.open(args.frame).convert("RGB"), args.steps)
    print("[colours]")
    for k, v in centres.items():
        print(f"{k} = {list(v)}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("overlay", cmd_overlay), ("run", cmd_run)):
        p = sub.add_parser(name)
        p.add_argument("--frames")
        p.add_argument("--questions", default=str(cm.TRUCK / "rest.json"))
        p.set_defaults(fn=fn)
    p = sub.add_parser("calibrate")
    p.add_argument("frame")
    p.add_argument("--steps", type=int, default=None, help="steps done in the frame (default: all)")
    p.set_defaults(fn=cmd_calibrate)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
