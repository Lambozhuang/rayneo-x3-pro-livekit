"""Judge routes B and C on a recorded run: one narrow question per frame and step.

  python eval/judge_eval.py labels                       write the per-frame label table + a sample sheet, no API calls
  python eval/judge_eval.py run --route B --provider openai --questions truck/rest.json      30 rest-state questions (step 1 of the plan)
  python eval/judge_eval.py run --route B --provider openai [--subset truck/subset_small.json] [--limit N]   derived per-frame labels
  python eval/judge_eval.py summarize truck/results/B_<model>_<detail>.jsonl

Models come from backend/.env: OPENAI_CHECK_MODEL (+ OPENAI_CHECK_DETAIL, OPENAI_CHECK_EFFORT) for
--provider openai, GEMINI_CHECK_MODEL for --provider gemini. Nothing is hardcoded here.

Route B sends the whole frame (long side SIDE px). Route C crops the baseplate with a green mask
(margin 10 %, native resolution, never upscaled) and sends the crop; frames where the mask finds no
plate are answered cannot_see without a call. Both routes send the same reference diagram first:
the target state after step N with the step-N brick outlined, drawn from layout.json.

Per frame t the truth gives the active step N (first step not done yet). Two questions are asked:
step N (expected not_placed / wrong / correct) and step N-1 (expected correct). Frames between a
wrong window and the step's done time are 'moving' and only reported, not scored; frames inside a
distraction window are reported separately.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
TRUCK = ROOT / "truck"
RUN = TRUCK / "run1"
FRAMES = RUN / "frames"
RESULTS = TRUCK / "results"
SHEETS = RUN / "sheets"
CLIP_ORDER = ["run1_part1", "run1_part2_p1", "run1_part2_p2"]
SIDE = 1024
CELL = 24
ANSWERS = ("correct", "wrong", "not_placed", "cannot_see")
COLORS = {"red": (200, 30, 20), "purple": (120, 30, 150), "lime": (170, 210, 40), "white": (240, 240, 240),
          "blue": (20, 80, 200), "tan": (230, 200, 150), "yellow": (250, 200, 30)}

SYSTEM = """You check one LEGO building step. The builder places flat bricks on a fixed green 16x16 LEGO baseplate; the plate is never rotated.
The first image is a top-down diagram of how the plate should look after step N. The brick added in step N is outlined in yellow; all other bricks in the diagram were placed in earlier steps and are already on the plate. Columns 1-16 run left to right and rows 1-16 top to bottom; the diagram's top edge is the plate edge farthest from the builder, which is the upper edge of the plate in the photo.
The second image is a photo from the builder's glasses. Judge only the step-N brick:
- correct: a brick of exactly that colour and footprint sits on exactly those cells.
- wrong: a brick for this step is on the plate but its colour, size, position or orientation differs from the diagram.
- not_placed: no new brick is on or near those cells yet (it may be in the builder's hand or off the plate).
- cannot_see: the plate or that region is hidden, blurred or out of frame, so you cannot tell.
Reply with JSON only: {"answer": "correct|wrong|not_placed|cannot_see", "reason": "<one sentence>"}."""


SYSTEM_REL = """You check one step of a LEGO build from a photo taken by the builder's glasses. The builder places flat bricks on a fixed green 16x16 baseplate that is never rotated. You get a plain-language description of what was already on the plate and of the brick this step adds, with a few facts about where it sits relative to the other bricks and the plate edges. No diagram, no coordinates.
Work in this order and report all of it:
1. seen: describe only what you actually see for this step's brick: is a brick of that kind on the plate, its colour, whether it lies flat or stands upright, what it touches, how its ends line up with its neighbours. If there is no such brick, say so. Do not repeat the description you were given; look.
2. checks: answer each listed fact with yes, no, or unsure, from the photo.
3. answer: correct if the brick is there and every fact is yes; wrong if the brick is there but any fact is no (wrong colour, wrong place, wrong orientation); not_placed if no such brick is on the plate yet (it may be in the builder's hand); cannot_see if the plate or that area is hidden, blurred or out of frame.
Reply with JSON only: {"seen": "...", "checks": [{"fact": "...", "result": "yes|no|unsure"}, ...], "answer": "correct|wrong|not_placed|cannot_see", "reason": "<one sentence>"}."""


def load():
    layout = json.loads((TRUCK / "layout.json").read_text(encoding="utf-8"))
    events = json.loads((TRUCK / "events.json").read_text(encoding="utf-8"))
    steps = layout["steps"] if isinstance(layout, dict) else layout
    return steps, events


def tkey(clip: str, sec: float) -> tuple[int, float]:
    return CLIP_ORDER.index(clip), sec


# ---------------------------------------------------------------- labels

def frame_list() -> list[tuple[str, int]]:
    out = []
    for clip in CLIP_ORDER:
        for p in sorted((FRAMES / clip).glob("*.jpg")):
            out.append((clip, int(p.stem) - 1))
    return out


def label_frames(events) -> list[dict]:
    steps = {s["step"]: s for s in events["steps"]}
    rows = []
    for clip, t in frame_list():
        k = tkey(clip, t)
        active = next((s for s in sorted(steps) if k < tkey(*steps[s]["done"])), None)
        n = active if active is not None else max(steps)
        distraction = any(c == clip and a <= t <= b for c, a, b in events["distractions"])
        qs = []
        s = steps[n]
        done = tkey(*s["done"])
        w = s.get("wrong")
        if k >= done:
            exp = "correct"
        elif w and tkey(*w["from"]) <= k <= tkey(*w["to"]):
            exp = "wrong"
        elif w and tkey(*w["to"]) < k < done:
            exp = "moving"
        else:
            exp = "not_placed"
        qs.append({"step": n, "expected": exp})
        if n > 1 and k > tkey(*steps[n - 1]["done"]):
            qs.append({"step": n - 1, "expected": "correct"})
        for q in qs:
            rows.append({"clip": clip, "t": t, "frame": f"{t + 1:03d}.jpg", "distraction": distraction, **q})
    return rows


# ---------------------------------------------------------------- images

def render_ref(steps, n: int) -> Image.Image:
    m = CELL
    img = Image.new("RGB", (m + 16 * CELL, m + 16 * CELL), (30, 120, 60))
    d = ImageDraw.Draw(img)
    for i in range(16):
        for j in range(16):
            cx, cy = m + i * CELL + CELL // 2, m + j * CELL + CELL // 2
            d.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(25, 100, 50))
    font = ImageFont.load_default()
    for i in range(16):
        d.text((m + i * CELL + 7, 6), str(i + 1), fill="white", font=font)
        d.text((6, m + i * CELL + 7), str(i + 1), fill="white", font=font)
    for s in steps:
        if s["step"] > n:
            continue
        c0, r0, c1, r1 = s["cells"]
        box = [m + (c0 - 1) * CELL, m + (r0 - 1) * CELL, m + c1 * CELL - 1, m + r1 * CELL - 1]
        fill = COLORS[s["color"]]
        if "disc" in s["name"]:
            d.ellipse(box, fill=fill, outline="black")
        else:
            d.rectangle(box, fill=fill, outline="black")
        if s["step"] == n:
            d.rectangle([box[0] - 3, box[1] - 3, box[2] + 3, box[3] + 3], outline=(255, 230, 0), width=3)
    return img


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


def prep_photo(path: Path, route: str) -> Image.Image | None:
    img = Image.open(path).convert("RGB")
    if route == "B":
        img.thumbnail((SIDE, SIDE))
        return img
    box = plate_bbox(img)
    if box is None:
        return None
    crop = img.crop(box)
    crop.thumbnail((SIDE, SIDE))
    return crop


def to_jpeg(img: Image.Image, q: int = 90) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=q)
    return buf.getvalue()


def to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def step_text(steps, n: int) -> str:
    s = next(s for s in steps if s["step"] == n)
    c0, r0, c1, r1 = s["cells"]
    desc = s["name"] if s["name"].startswith(s["color"]) else f"{s['color']} {s['name']}"
    return f"Step {n}: {desc}, columns {c0}-{c1}, rows {r0}-{r1}. Is the step-{n} brick placed correctly?"


def step_text_rel(steps, n: int) -> str:
    s = next(s for s in steps if s["step"] == n)
    before = [x for x in steps if x["step"] < n]
    lines = []
    if before:
        lines.append("Already on the plate from earlier steps: " + "; ".join(x["name"] for x in before) + ".")
    else:
        lines.append("The plate is empty before this step.")
    lines.append(f"Step {n} adds {s['where']}.")
    lines.append("Facts to check:")
    lines += [f"{i}. {c}" for i, c in enumerate(s["checks"], 1)]
    return chr(10).join(lines)


# ---------------------------------------------------------------- providers

def load_env():
    env = ROOT.parent / "backend" / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


class OpenAIJudge:
    def __init__(self):
        from openai import OpenAI
        self.client = OpenAI()
        self.model = os.environ.get("OPENAI_CHECK_MODEL") or sys.exit("OPENAI_CHECK_MODEL not set in backend/.env")
        self.detail = os.environ.get("OPENAI_CHECK_DETAIL", "high")  # same default as backend vision.py
        self.effort = os.environ.get("OPENAI_CHECK_EFFORT")
        self.tag = f"{self.model}_{self.detail}"

    def ask(self, ref: bytes | None, photo: bytes, text: str, system: str) -> tuple[str, dict]:
        content = [{"type": "input_text", "text": text}]
        if ref:
            content.append({"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(ref).decode(), "detail": "low"})
        content.append({"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(photo).decode(), "detail": self.detail})
        kw = {}
        if self.effort:
            kw["reasoning"] = {"effort": self.effort}
        r = self.client.responses.create(model=self.model, instructions=system,
                                         input=[{"role": "user", "content": content}], **kw)
        u = r.usage
        return r.output_text, {"in": u.input_tokens, "out": u.output_tokens}


class GeminiJudge:
    def __init__(self):
        from google import genai
        from google.genai import types
        self.types = types
        self.client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        self.model = os.environ.get("GEMINI_CHECK_MODEL") or sys.exit("GEMINI_CHECK_MODEL not set in backend/.env")
        self.tag = self.model

    def ask(self, ref: bytes | None, photo: bytes, text: str, system: str) -> tuple[str, dict]:
        t = self.types
        parts = [text] + ([t.Part.from_bytes(data=ref, mime_type="image/png")] if ref else []) + [t.Part.from_bytes(data=photo, mime_type="image/jpeg")]
        r = self.client.models.generate_content(
            model=self.model,
            contents=parts,
            config=t.GenerateContentConfig(system_instruction=system, response_mime_type="application/json"),
        )
        u = r.usage_metadata
        return r.text, {"in": u.prompt_token_count, "out": u.candidates_token_count}


class DryJudge:
    """No API: writes the exact request material and a placeholder answer, to check the pipeline."""
    tag = "dry"

    def ask(self, ref, photo, text, system) -> tuple[str, dict]:
        return '{"answer": "cannot_see", "reason": "dry run"}', {}


def parse_answer(text: str) -> tuple[str, str]:
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        obj = json.loads(text[start:end])
        a = str(obj.get("answer", "")).strip().lower()
        return (a if a in ANSWERS else "invalid"), str(obj.get("reason", ""))
    except (ValueError, AttributeError):
        return "invalid", (text or "")[:200]


# ---------------------------------------------------------------- commands

def cmd_labels(args):
    steps, events = load()
    rows = label_frames(events)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "labels.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print(len(rows), "questions over", len(frame_list()), "frames")
    print(dict(Counter(r["expected"] for r in rows)))
    print("in distraction windows:", sum(r["distraction"] for r in rows))
    miss = [f"{c}/{t + 1:03d}" for c, t in frame_list() if plate_bbox(Image.open(FRAMES / c / f"{t + 1:03d}.jpg")) is None]
    print("route C: no plate found in", len(miss), "frames", miss)
    # per-frame table, compact
    by_frame = defaultdict(list)
    for r in rows:
        by_frame[(r["clip"], r["frame"])].append(f"s{r['step']}={r['expected']}" )
    with (RESULTS / "labels.txt").open("w", encoding="utf-8") as f:
        for (clip, frame), qs in by_frame.items():
            dis = "  [distraction]" if any(r["distraction"] for r in rows if (r["clip"], r["frame"]) == (clip, frame)) else ""
            f.write(f"{clip} {frame}  " + "  ".join(qs) + dis + "\n")
    print("table ->", RESULTS / "labels.txt")
    # sample sheet: what the model will see (ref + route C crop) for a few frames of each class
    picks = []
    for want in ("wrong", "correct", "not_placed", "moving"):
        cand = [r for r in rows if r["expected"] == want and not r["distraction"]]
        picks += cand[:: max(1, len(cand) // 3)][:3]
    picks += [r for r in rows if r["distraction"]][:2]
    tiles = []
    for r in picks:
        ref = render_ref(steps, r["step"])
        photo = prep_photo(FRAMES / r["clip"] / r["frame"], "C") or Image.new("RGB", (300, 300), "grey")
        photo.thumbnail((360, 360))
        ref.thumbnail((360, 360))
        tile = Image.new("RGB", (ref.width + photo.width + 20, max(ref.height, photo.height) + 24), "white")
        tile.paste(ref, (0, 24))
        tile.paste(photo, (ref.width + 20, 24))
        ImageDraw.Draw(tile).text((4, 4), f"{r['clip']} {r['frame']}  step {r['step']}  expected {r['expected']}"
                                  + ("  [distraction]" if r["distraction"] else ""), fill="black")
        tiles.append(tile)
    w = max(x.width for x in tiles)
    sheet = Image.new("RGB", (w, sum(x.height for x in tiles)), "white")
    y = 0
    for x in tiles:
        sheet.paste(x, (0, y))
        y += x.height
    sheet.save(SHEETS / "labels_sample.jpg", quality=85)
    print("sample sheet ->", SHEETS / "labels_sample.jpg")


def cmd_run(args):
    steps, events = load()
    load_env()
    if args.questions:  # hand-picked rest-state questions with their own expected answers
        rows = [dict(q, t=int(q["frame"][:3]) - 1, distraction=False) for q in json.loads(Path(args.questions).read_text(encoding="utf-8"))]
    else:
        rows = label_frames(events)
    if args.subset:
        keep = {(s["clip"], s["frame"], s["step"]) for s in json.loads(Path(args.subset).read_text(encoding="utf-8"))}
        rows = [r for r in rows if (r["clip"], r["frame"], r["step"]) in keep]
    judge = {"openai": OpenAIJudge, "gemini": GeminiJudge, "dry": DryJudge}[args.provider]()
    rel = args.prompt == "relational"
    system = SYSTEM_REL if rel else SYSTEM
    judge.tag += "_rel" if rel else ""
    RESULTS.mkdir(exist_ok=True)
    name = f"{Path(args.questions).stem}_" if args.questions else ""
    out = RESULTS / f"{name}{args.route}_{judge.tag}.jsonl"
    calls = RESULTS / f"{name}{args.route}_{judge.tag}"  # exactly what was sent, per question: ref png + photo jpeg (gitignored)
    calls.mkdir(exist_ok=True)
    header = [f"provider={args.provider} model={judge.tag} route={args.route} side={SIDE} prompt={args.prompt}"]
    if args.provider == "openai":
        header.append(f"detail photo={judge.detail} ref=low effort={judge.effort}")
    (calls / "prompt.txt").write_text("\n".join(header) + "\n\n--- system ---\n" + system
                                      + "\n\n--- user text, per question (one example) ---\n" + (step_text_rel(steps, 6) if rel else step_text(steps, 1)) + "\n", encoding="utf-8")
    done = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            done.add((d["clip"], d["frame"], d["step"]))
    todo = [r for r in rows if (r["clip"], r["frame"], r["step"]) not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} calls to {judge.tag}, route {args.route} -> {out.name} ({len(done)} already done)")
    refs = {}
    with out.open("a", encoding="utf-8") as f:
        for i, r in enumerate(todo, 1):
            n = r["step"]
            if n not in refs:
                refs[n] = None if rel else to_png(render_ref(steps, n))
            photo = prep_photo(FRAMES / r["clip"] / r["frame"], args.route)
            rec = dict(r, route=args.route, model=judge.tag, question=(step_text_rel if rel else step_text)(steps, n))
            if photo is None:
                rec.update(answer="cannot_see", reason="no plate in green mask", raw="", latency=0, usage={})
            else:
                stem = f"{r['clip']}_{r['frame'][:3]}_s{n:02d}"
                jpeg = to_jpeg(photo)
                if refs[n]:
                    (calls / f"{stem}_ref.png").write_bytes(refs[n])
                (calls / f"{stem}_photo.jpg").write_bytes(jpeg)
                t0 = time.perf_counter()
                try:
                    text, usage = judge.ask(refs[n], jpeg, rec["question"], system)
                except Exception as e:  # quota, network: keep what we have, resume later
                    print(f"\n{r['clip']}/{r['frame']} step {n}: {type(e).__name__}: {str(e)[:300]}")
                    break
                rec["latency"] = round(time.perf_counter() - t0, 2)
                rec["raw"] = text
                rec["answer"], rec["reason"] = parse_answer(text)
                rec["usage"] = usage
                rec["photo_size"] = list(photo.size)
            f.write(json.dumps(rec) + "\n")
            f.flush()
            ok = "ok " if rec["answer"] == r["expected"] else "XX "
            print(f"{i:3d} {r['clip']}/{r['frame']} s{n:02d} exp={r['expected']:<10} got={rec['answer']:<10} {ok}{rec.get('latency', 0):5.1f}s  {rec['reason'][:90]}")


def cmd_summarize(args):
    recs = [json.loads(l) for l in Path(args.file).read_text(encoding="utf-8").splitlines()]
    scored = [r for r in recs if r["expected"] != "moving" and not r["distraction"]]
    conf = defaultdict(Counter)
    for r in scored:
        conf[r["expected"]][r["answer"]] += 1
    cols = ANSWERS + ("invalid",)
    print(f"{len(recs)} answers, {len(scored)} scored (moving and distraction frames excluded)")
    print(f"{'expected':<12}" + "".join(f"{a:>12}" for a in cols) + "   acc")
    for e in ("not_placed", "wrong", "correct"):
        c = conf[e]
        n = sum(c.values())
        if n:
            print(f"{e:<12}" + "".join(f"{c[a]:>12}" for a in cols) + f"   {c[e] / n:5.1%}")
    _, events = load()
    for s in events["steps"]:
        w = s.get("wrong")
        if not w:
            continue
        hits = [r for r in recs if r["step"] == s["step"] and r["expected"] == "wrong"]
        got = sum(r["answer"] == "wrong" for r in hits)
        print(f"error step {s['step']:2d} ({w['kind']}): {got}/{len(hits)} frames said wrong")
    fa = [r for r in scored if r["expected"] == "correct" and r["answer"] == "wrong"]
    print("false 'wrong' on correct bricks:", len(fa), [f"{r['clip']}/{r['frame']} s{r['step']}" for r in fa][:12])
    mv = [r for r in recs if r["expected"] == "moving"]
    print("moving frames:", len(mv), dict(Counter(r["answer"] for r in mv)))
    dis = [r for r in recs if r["distraction"]]
    print("distraction frames:", len(dis), dict(Counter(r["answer"] for r in dis)))
    lat = sorted(r["latency"] for r in recs if r.get("latency"))
    if lat:
        print(f"latency median {lat[len(lat) // 2]:.2f}s  p90 {lat[int(len(lat) * 0.9)]:.2f}s")
    calls = [r for r in recs if r.get("usage")]
    print(f"tokens in {sum(r['usage'].get('in', 0) for r in calls)} out {sum(r['usage'].get('out', 0) for r in calls)} over {len(calls)} calls")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("labels").set_defaults(fn=cmd_labels)
    p = sub.add_parser("run")
    p.add_argument("--route", choices=["B", "C"], required=True)
    p.add_argument("--provider", choices=["openai", "gemini", "dry"], required=True)
    p.add_argument("--questions", help="question file such as truck/rest.json instead of the derived per-frame labels")
    p.add_argument("--prompt", choices=["grid", "relational"], default="grid",
                   help="grid: numbered diagram + columns/rows; relational: plain-language neighbours and alignment, describe first, no diagram")
    p.add_argument("--subset")
    p.add_argument("--limit", type=int)
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("summarize")
    p.add_argument("file")
    p.set_defaults(fn=cmd_summarize)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
