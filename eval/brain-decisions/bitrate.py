"""Asks the eyes' questions (gpt/eyes.py, the scene and the step battery) about the codec study's frames at every
bitrate, and scores the answers against the labels a person wrote for those frames, to see what the Decisions API
loses as the video is squeezed.

    backend/agent/.venv/Scripts/python eval/brain-decisions/bitrate.py [--conditions sq1080,hevc-v1000,hevc-v500,hevc-v250,hevc-v100]

Material: the 41 frames of the ladder call of 2026-10-27 (../brain-frame-quality/out/frames.csv) as the codec study
decoded them at each rate (../brain-frame-codec/out/<condition>/fNN.jpg, 1080 px squares), scaled to 512 px as the eyes
send them at detail low; the labels of ../brain-frame-quality/labels.toml, which say per frame where the hands are and
which bricks lie on the plate; and the task as it was recorded (ladder-2026-10-27.toml, the light aqua 1x4 last).

The truth per frame comes from the labels and the study's narrative: the hand is on the plate when the label says on or
over; the steps built right are the bricks on the plate, less the blue rung while it lay at the rails' bottom ends
(f20 to f25) and the white 1x4 that stood in for the light aqua one (f30 to f35); the current step is the next one; the
step's brick is on the plate from the frame it is set down; it sits right except the misplaced blue; it is the step's
colour except the white 1x4.

out/bitrate-<condition>.json has every frame's answers; out/bitrate-summary.md the table.
"""

import argparse
import asyncio
import base64
import io
import json
import os
import statistics as st
import sys
import tomllib
from pathlib import Path

import httpx
from PIL import Image

here = Path(__file__).resolve().parent
root = here.parent.parent
sys.path.insert(0, str(root / "backend" / "agent" / "src"))

from gpt.eyes import scene_questions, step_questions  # noqa: E402
from guide import load_guide  # noqa: E402
from prompts import task_block  # noqa: E402

URL = "https://api.openai.com/v1/decisions"
FRAMES = root / "eval" / "brain-frame-codec" / "out"
LABELS = root / "eval" / "brain-frame-quality" / "labels.toml"
out = here / "out"


def truth_table() -> dict[str, dict]:
    labels = {f["id"]: f for f in tomllib.load(open(LABELS, "rb"))["frame"]}
    truth = {}
    for fid, f in labels.items():
        n = int(fid[1:])
        bricks = f["bricks"]
        held = any(b.get("held") for b in bricks)
        done = len(bricks) - (1 if held else 0)
        if 20 <= n <= 25:
            done = 3  # the blue rung at the rails' bottom ends, being moved from f24
        if 30 <= n <= 35:
            done = 4  # a white 1x4 where the light aqua one goes
        if n == 36:
            done = 4
        step = min(done + 1, 5)
        on_plate = (20 <= n <= 25) or (30 <= n <= 35) or n >= 37 or (held and len(bricks) == step)
        position_right = None if not on_plate else not (20 <= n <= 25)
        colour_right = None if not on_plate else not (30 <= n <= 35)
        truth[fid] = {"hand": f["hands"] in ("on", "over"), "done": done, "step": step, "on_plate": on_plate,
                      "position": position_right, "colour": colour_right}
    return truth


def load_key() -> str:
    for line in (root / "backend" / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENAI_API_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit("no OPENAI_API_KEY in backend/.env")


async def ask(http: httpx.AsyncClient, text: str, photo: bytes, qs: list[dict]) -> tuple[dict, int, int]:
    body = {"model": "gpt-6-luna", "input": [{"type": "message", "role": "user", "content": [
        {"type": "input_text", "text": text},
        {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(photo).decode(), "detail": "low"}]}],
        "questions": qs}
    import time
    t0 = time.perf_counter()
    r = await http.post(URL, json=body)
    ms = round((time.perf_counter() - t0) * 1000)
    r.raise_for_status()
    data = r.json()
    return {a["name"]: a for a in data.get("answers", [])}, ms, (data.get("usage") or {}).get("input_tokens", 0)


def small(path: Path) -> bytes:
    img = Image.open(path).convert("RGB")
    img.thumbnail((512, 512))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


async def run_condition(cond: str, guide, task: str, truth: dict, http: httpx.AsyncClient, sem: asyncio.Semaphore) -> list[dict]:
    rows = []

    async def one(fid: str) -> None:
        async with sem:
            photo = small(FRAMES / cond / f"{fid}.jpg")
            step = truth[fid]["step"]
            text = f"{task}\n\nThe photo is what the user's glasses see right now, the desk from above."
            try:
                (a, ms1, t1), (b, ms2, t2) = await asyncio.gather(
                    ask(http, text, photo, scene_questions(guide)),
                    ask(http, f"{text} The user is on step {step}.", photo, step_questions(guide, step)))
            except Exception as e:  # noqa: BLE001
                rows.append({"id": fid, "error": f"{type(e).__name__}: {str(e)[:120]}"})
                return
            a.update(b)
            if any(x.get("type") == "refusal" for x in a.values()):
                rows.append({"id": fid, "error": "refusal"})
                return
            rows.append({"id": fid, "step": step, "ms": max(ms1, ms2), "tokens": t1 + t2,
                         "hand": round(a["hand"]["probability"], 2), "in_hand": a["in_hand"]["choice"],
                         "in_hand_sure": round(a["in_hand"].get("confidence", 0), 2),
                         "done": int(a["done"]["choice"]), "done_sure": round(a["done"].get("confidence", 0), 2),
                         "blurry": round(a["blurry"]["probability"], 2), "on_plate": round(a["on_plate"]["probability"], 2),
                         "right": round(a["right"]["probability"], 2), "colour": round(a["colour"]["probability"], 2),
                         "where": a["where"]["choice"]})

    await asyncio.gather(*(one(fid) for fid in sorted(truth)))
    rows.sort(key=lambda r: r["id"])
    (out / f"bitrate-{cond}.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return rows


def decided(p: float, want: bool) -> str:
    """right, wrong or unsure, as the eyes' own bars read a probability."""
    if p >= 0.6:
        return "right" if want else "wrong"
    if p <= 0.3:
        return "wrong" if want else "right"
    return "unsure"


def score(cond: str, rows: list[dict], truth: dict, ref: list[dict] | None) -> dict:
    ok = [r for r in rows if "error" not in r]
    hand = sum((r["hand"] >= 0.5) == truth[r["id"]]["hand"] for r in ok)
    done = sum(r["done"] == truth[r["id"]]["done"] for r in ok)
    on = sum((r["on_plate"] >= 0.5) == truth[r["id"]]["on_plate"] for r in ok)
    pos = {"right": 0, "wrong": 0, "unsure": 0}
    col = {"right": 0, "wrong": 0, "unsure": 0}
    for r in ok:
        t = truth[r["id"]]
        if t["position"] is not None:
            pos[decided(r["right"], t["position"])] += 1
            col[decided(r["colour"], t["colour"])] += 1
    agree = None
    if ref is not None:
        refmap = {r["id"]: r for r in ref if "error" not in r}
        both = [r for r in ok if r["id"] in refmap]
        agree = (sum(r["done"] == refmap[r["id"]]["done"] for r in both), sum(r["in_hand"] == refmap[r["id"]]["in_hand"] for r in both), len(both))
    return {"cond": cond, "n": len(ok), "failed": len(rows) - len(ok), "hand": hand, "done": done, "on": on, "pos": pos, "col": col,
            "blurry": sum(r["blurry"] >= 0.5 for r in ok), "ms": st.median([r["ms"] for r in ok]) if ok else 0,
            "tokens": st.median([r["tokens"] for r in ok]) if ok else 0, "agree": agree}


NAMES = {"sq1080": "as recorded", "hevc-v1000": "H.265 1 Mbps", "hevc-v500": "H.265 0.5 Mbps", "hevc-v250": "H.265 0.25 Mbps",
         "hevc-v100": "H.265 0.1 Mbps", "h264-v1000": "H.264 1 Mbps", "h264-v500": "H.264 0.5 Mbps", "h264-v250": "H.264 0.25 Mbps"}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conditions", default="sq1080,hevc-v1000,hevc-v500,hevc-v250,hevc-v100")
    args = ap.parse_args()
    os.environ["OPENAI_API_KEY"] = load_key()
    guide = load_guide(here / "ladder-2026-10-27.toml", pictures=False)
    task = task_block(guide)
    truth = truth_table()
    out.mkdir(exist_ok=True)
    conds = args.conditions.split(",")
    results, ref = [], None
    async with httpx.AsyncClient(timeout=60, headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}) as http:
        sem = asyncio.Semaphore(4)
        for cond in conds:
            rows = await run_condition(cond, guide, task, truth, http, sem)
            if ref is None:
                ref = rows
            s = score(cond, rows, truth, None if cond == conds[0] else ref)
            results.append(s)
            print(f"{cond:<12} n={s['n']} hand {s['hand']}/{s['n']} done {s['done']}/{s['n']} on_plate {s['on']}/{s['n']} "
                  f"position {s['pos']} colour {s['col']} blurry {s['blurry']} ms {s['ms']:.0f} agree {s['agree']}")
    placed = sum(1 for t in truth.values() if t["position"] is not None)
    lines = [f"# The eyes' questions on the codec study's frames (41 frames, {placed} with the step's brick on the plate), gpt-6-luna, detail low",
             "", "| condition | hand on plate | steps built right | step's brick on plate | position right / wrong / unsure | colour right / wrong / unsure | blurry | same count as recorded | same brick in hand | ms |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for s in results:
        a = s["agree"]
        lines.append(f"| {NAMES.get(s['cond'], s['cond'])} | {s['hand']}/{s['n']} | {s['done']}/{s['n']} | {s['on']}/{s['n']} | "
                     f"{s['pos']['right']} / {s['pos']['wrong']} / {s['pos']['unsure']} | {s['col']['right']} / {s['col']['wrong']} / {s['col']['unsure']} | "
                     f"{s['blurry']} | {f'{a[0]}/{a[2]}' if a else '-'} | {f'{a[1]}/{a[2]}' if a else '-'} | {s['ms']:.0f} |")
    (out / "bitrate-summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    asyncio.run(main())
