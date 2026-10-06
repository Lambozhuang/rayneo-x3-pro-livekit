"""Rest-state gate on the recorded run: which frames are worth a judge call.

  python eval/gate_eval.py signals        per-frame signals -> truck/results/gate/gate_signals.jsonl + contact sheet with the decision
  python eval/gate_eval.py score          compare the decision with truck/gate_labels.json (hand-labelled ask / skip)

Three local signals, no model (PIL + numpy):
  plate   the green plate is found and its box keeps clear of the frame border (whole plate in view)
  skin    share of skin-coloured pixels inside the plate box (YCbCr window); a hand on or over the plate
  motion  mean absolute grey difference against the previous frame inside the plate box (1 fps here)
Decision: ask = whole plate in view and no gross skin share. Motion is recorded but not used at 1 fps (it mostly
measures head movement here; the live gate at 15 fps can require a still second). Finer skin rules (blob size,
touching the border, blob shape) were tried and dropped: the tan 1x6, purple edges and red shadows fall in the
skin window, and the judge answers hand frames sensibly on its own, so a leak costs one call, not a wrong verdict.
Thresholds live at the top so the agent's gate can use the same numbers.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as cm  # noqa: E402
from common import SHEETS, TRUCK, components, frame_list  # noqa: E402
from gate import ASPECT, BORDER, HAND_TOTAL, MIN_SIDE, MOTION_MAX, plate_outline, skin_share, tight_box  # noqa: E402,F401  (the agent's gate)

RESULTS = cm.RESULTS / "gate"
from PIL import ImageFilter  # noqa: E402

HAND_BLOB = 0.05    # largest skin blob this large (share of the plate box) = a hand; the tan 1x6 is ~2.5 %, red bricks are cut by the Cr bound
HAND_EDGE_BLOB = 0.03  # a smaller blob still counts when it touches the box border (a hand reaching in)
THIN = 3.0          # a skin blob whose bounding box is this elongated is a brick (the tan 1x6), not a hand


def skin_stats(crop: Image.Image) -> dict:
    """Skin-coloured pixels inside the plate box: total share, largest blob share, whether that blob touches the border."""
    small = crop.copy()
    small.thumbnail((crop.width // 4, crop.height // 4))
    a = np.asarray(small.convert("YCbCr")).astype(np.int16)
    y, cb, cr = a[..., 0], a[..., 1], a[..., 2]
    skin = (cr >= 135) & (cr <= 152) & (cb >= 100) & (cb <= 140) & (y > 60)  # measured: hands Cr 135-148, red bricks 150-170
    closed = np.asarray(Image.fromarray(skin.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))) > 0
    total = float(skin.mean())
    comps = components(closed)
    if not comps:
        return {"skin": round(total, 4), "blob": 0.0, "edge": False}
    h, w = closed.shape
    # the largest blob that is not brick-shaped: thin rectangles are the tan 1x6, hands are blobby
    for big in comps:
        bh, bw = np.ptp(big[:, 0]) + 1, np.ptp(big[:, 1]) + 1
        if max(bh, bw) / max(1, min(bh, bw)) < THIN:
            break
    else:
        return {"skin": round(total, 4), "blob": 0.0, "edge": False, "thin": True}
    edge = bool((big[:, 0] == 0).any() or (big[:, 1] == 0).any() or (big[:, 0] == h - 1).any() or (big[:, 1] == w - 1).any())
    return {"skin": round(total, 4), "blob": round(len(big) / closed.size, 4), "edge": edge, "thin": False}


def motion(prev: Image.Image | None, prev_box, cur: Image.Image, box) -> float | None:
    """Grey difference between the two plate crops, each resized to 96x96: tolerates head movement, not hands."""
    if prev is None or prev_box is None:
        return None
    a = np.asarray(prev.crop(prev_box).convert("L").resize((96, 96))).astype(np.int16)
    b = np.asarray(cur.crop(box).convert("L").resize((96, 96))).astype(np.int16)
    return float(np.abs(a - b).mean())


def signals():
    out = []
    prev_img, prev_box, prev_clip = None, None, None
    for clip, t in frame_list():
        img = Image.open(cm.FRAMES / clip / f"{t + 1:03d}.jpg").convert("RGB")
        if clip != prev_clip:
            prev_img, prev_box = None, None
        box = tight_box(img)
        rec = {"clip": clip, "t": t, "frame": f"{t + 1:03d}.jpg", "plate": False, "skin": None, "blob": None, "edge": None, "motion": None}
        if box:
            x0, y0, x1, y1 = box
            w, h = img.size
            rec["box"] = list(box)
            bw, bh = x1 - x0, y1 - y0
            rec["plate"] = bool(x0 > w * BORDER and y0 > h * BORDER and x1 < w * (1 - BORDER) and y1 < h * (1 - BORDER)
                                and min(bw, bh) >= w * MIN_SIDE and ASPECT[0] <= bw / bh <= ASPECT[1])
            rec.update(skin_stats(img.crop(box)))
            outline = plate_outline(img)  # the agent's rule: skin inside the plate outline, not its bounding box
            rec["skin"] = round(skin_share(img.crop(box), outline.crop(box) if outline is not None else None), 4)
            m = motion(prev_img, prev_box, img, box)
            rec["motion"] = None if m is None else round(m, 2)
        # Only gross skin counts: finer skin rules confuse hands with the tan, purple and red bricks, and the judge
        # answers hand frames sensibly on its own (not_placed / cannot_see), so leaks cost a call, not a mistake.
        hand = rec["skin"] is not None and rec["skin"] >= HAND_TOTAL
        rec["hand"] = bool(hand)
        rec["ask"] = bool(rec["plate"] and not hand)  # motion is reported, not yet used: at 1 fps it mostly measures head movement
        out.append(rec)
        prev_img, prev_box, prev_clip = img, box, clip
    return out


def sheet(recs, labels=None):
    tiles = []
    for r in recs:
        img = Image.open(cm.FRAMES / r["clip"] / r["frame"]).convert("RGB")
        if r.get("box"):  # the box grown by half its size, so hands around the plate stay visible
            x0, y0, x1, y1 = r["box"]
            gx, gy = (x1 - x0) // 2, (y1 - y0) // 2
            tile = img.crop((max(0, x0 - gx), max(0, y0 - gy), min(img.width, x1 + gx), min(img.height, y1 + gy)))
        else:
            tile = img
        tile.thumbnail((150, 150))
        bg = Image.new("RGB", (154, 184), "white")
        bg.paste(tile, (2, 32))
        d = ImageDraw.Draw(bg)
        colour = (0, 160, 0) if r["ask"] else (200, 0, 0)
        d.rectangle([0, 0, 153, 183], outline=colour, width=3)
        d.text((4, 3), f"{r['clip'][5:]}/{r['frame'][:3]}", fill="black")
        s = "" if r["skin"] is None else f"s{r['skin'] * 100:.0f} b{r['blob'] * 100:.0f}{'e' if r['edge'] else ''}"
        m = "" if r["motion"] is None else f" m{r['motion']:.0f}"
        p = "" if r["plate"] else " cut"
        d.text((4, 16), f"{s}{m}{p}", fill="black")
        if labels is not None:
            lab = labels.get(f"{r['clip']}/{r['frame'][:3]}")
            if lab is not None and lab != r["ask"]:
                d.text((100, 3), "MISS" if lab else "LEAK", fill=(200, 0, 0))
        tiles.append(bg)
    cols = 12
    rows = (len(tiles) + cols - 1) // cols
    img = Image.new("RGB", (cols * 154, rows * 184), "white")
    for i, t in enumerate(tiles):
        img.paste(t, ((i % cols) * 154, (i // cols) * 184))
    return img


def cmd_signals(args):
    recs = signals()
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "gate_signals.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    labels = None
    lp = TRUCK / "gate_labels.json"
    if lp.exists():
        labels = json.loads(lp.read_text(encoding="utf-8"))
    sheet(recs, labels).save(SHEETS / "gate_sheet.jpg", quality=80)
    print(len(recs), "frames;", sum(r["ask"] for r in recs), "ask;", sum(not r["plate"] for r in recs), "no/cut plate")
    print("sheet ->", SHEETS / "gate_sheet.jpg")


def cmd_score(args):
    recs = [json.loads(l) for l in (RESULTS / "gate_signals.jsonl").read_text(encoding="utf-8").splitlines()]
    labels = json.loads((TRUCK / "gate_labels.json").read_text(encoding="utf-8"))
    tp = fp = fn = tn = 0
    leaks, misses = [], []
    for r in recs:
        key = f"{r['clip']}/{r['frame'][:3]}"
        if labels.get(key) is None:
            continue
        want, got = labels[key], r["ask"]
        if want and got:
            tp += 1
        elif want and not got:
            fn += 1
            misses.append(key)
        elif not want and got:
            fp += 1
            leaks.append(key)
        else:
            tn += 1
    print(f"labelled {tp + fp + fn + tn}: ask-and-asked {tp}, skip-and-skipped {tn}")
    print(f"missed rest frames (would not ask): {fn} {misses}")
    print(f"leaked bad frames (would ask): {fp} {leaks}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("signals").set_defaults(fn=cmd_signals)
    sub.add_parser("score").set_defaults(fn=cmd_score)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
