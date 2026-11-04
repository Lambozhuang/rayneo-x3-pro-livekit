"""Asks the Decisions API (gpt-6-luna, typed answers) the brain's yes-or-no questions about a recorded call's photos
and times it, to see whether it can serve as a fast first look.

    backend/agent/.venv/Scripts/python eval/brain-decisions/probe.py <record dir> [--looks 40] [--detail high]

For each watch look of the record the photo goes to POST /v1/decisions with the task's steps and the lines said
since the look before as text, and four questions: whether a hand is on the plate, which brick is in the hand, how
many steps are built right, and whether the picture is blurry. Each answer comes back as a probability or a
choice with a confidence. out/<record>.json has every look's answers, latency and tokens beside what the recorded
brain said; out/summary.md the latency figures and the agreement with the record's progress. The key comes from
backend/.env.
"""

import argparse
import asyncio
import base64
import importlib.util
import json
import os
import statistics as st
import sys
import time
from pathlib import Path

import httpx

here = Path(__file__).resolve().parent
root = here.parent.parent
sys.path.insert(0, str(root / "backend" / "agent" / "src"))

spec = importlib.util.spec_from_file_location("replay", root / "eval" / "brain-thread-replay" / "replay.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)

from guide import load_guide  # noqa: E402
from prompts import task_block  # noqa: E402

out = here / "out"
URL = "https://api.openai.com/v1/decisions"


def questions(guide) -> list[dict]:
    bricks = [{"value": f"step {i}", "description": f"the {s.brick} of step {i}"} for i, s in enumerate(guide.steps, 1)]
    counts = [{"value": str(n), "description": (f"steps 1 to {n} are built right, step {n + 1} is not placed or not right"
                                                 if 0 < n < len(guide.steps) else
                                                 "nothing is built right yet" if n == 0 else "every step is built right")}
              for n in range(len(guide.steps) + 1)]
    return [
        {"type": "predicate", "name": "hand_on_plate",
         "instructions": "Is a hand touching the baseplate, touching a brick on it, or covering part of it?"},
        {"type": "choice", "name": "in_hand",
         "instructions": "Which brick is the user holding in a hand right now, above the desk or the plate, not resting on the plate?",
         "choices": bricks + [{"value": "another brick", "description": "a brick that is none of the steps' bricks"},
                              {"value": "none", "description": "no brick is held in a hand"}]},
        {"type": "choice", "name": "steps_done",
         "instructions": "Counting from step 1 in order, how many steps are built right on the baseplate, each brick in its "
                         "place and orientation as the steps say? A brick still under a hand does not count.",
         "choices": counts},
        {"type": "predicate", "name": "blurry",
         "instructions": "Is the photo blurry, smeared or blocky from compression, so that the studs on the bricks cannot be made out?"},
    ]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("record")
    ap.add_argument("--looks", type=int, default=40)
    ap.add_argument("--detail", default="high")
    ap.add_argument("--model", default="gpt-6-luna")
    args = ap.parse_args()
    rec = Path(args.record)
    call = json.loads(open(rec / "events.jsonl", encoding="utf-8").readline())
    replay.load_key("openai")
    guide = load_guide(root / "backend" / "agent" / "guides" / call["guide"] / "task.toml")
    task = task_block(guide)
    todo = [l for l in replay.looks(rec) if l["kind"] == "watch"][: args.looks]
    qs = questions(guide)
    out.mkdir(exist_ok=True)
    rows = []
    headers = {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60) as http:
        for look in todo:
            s = look["sent"]
            photo = (rec / s["photo"]).read_bytes()
            text = (f"{task}\n\nThe photo is what the user's glasses see right now, the desk from above. Lines said since "
                    f"the photo before:\n{s['lines']}")
            body = {"model": args.model,
                    "input": [{"type": "message", "role": "user", "content": [
                        {"type": "input_text", "text": text},
                        {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(photo).decode(),
                         "detail": args.detail}]}],
                    "questions": qs}
            t0 = time.perf_counter()
            r = await http.post(URL, headers=headers, json=body)
            ms = round((time.perf_counter() - t0) * 1000)
            if r.status_code != 200:
                print(f"{look['id']:<5} HTTP {r.status_code}: {r.text[:300]}")
                rows.append({"id": look["id"], "error": r.text[:500], "ms": ms})
                if r.status_code == 400 and "detail" in r.text:
                    print("the detail field is refused; rerun without --detail")
                    return
                continue
            data = r.json()
            answers = {}
            for a in data.get("answers", []):
                if a["type"] == "predicate":
                    answers[a["name"]] = round(a["probability"], 2)
                elif a["type"] == "choice":
                    answers[a["name"]] = (a["choice"], round(a.get("confidence", 0), 2))
                else:
                    answers[a["name"]] = a["type"]
            u = data.get("usage", {})
            rec_progress = look["back"].get("progress")
            rows.append({"id": look["id"], "ms": ms, "answers": answers, "usage": u, "step_at_look": s["step"],
                         "record_reply": look["back"]["reply"], "record_calls": look["back"]["calls"],
                         "record_progress": rec_progress})
            print(f"{look['id']:<5} {ms:5d} ms  in {u.get('input_tokens', 0):5d}  hand {answers.get('hand_on_plate')}  "
                  f"in_hand {answers.get('in_hand')}  done {answers.get('steps_done')}  blurry {answers.get('blurry')}  "
                  f"| step {s['step']}, record: {look['back']['reply'][:60]}")
    (out / f"{rec.name}-{args.detail}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = [x for x in rows if "answers" in x]
    if not ok:
        return
    ms = sorted(x["ms"] for x in ok)
    # the record's progress at each look is the step the user was on minus one; where the record moved at that look,
    # the count after the move
    agree = 0
    for x in ok:
        truth = x["record_progress"] if x["record_progress"] is not None else x["step_at_look"] - 1
        agree += str(truth) == x["answers"]["steps_done"][0]
    table = (f"# {rec.name}, {len(ok)} looks, {args.model}, detail {args.detail}\n\n"
             f"| latency median | p90 | max | input tokens median | steps_done agrees with the record |\n|---|---|---|---|---|\n"
             f"| {st.median(ms):.0f} ms | {ms[int(.9 * len(ms)) - 1]} ms | {ms[-1]} ms | "
             f"{st.median([x['usage'].get('input_tokens', 0) for x in ok]):.0f} | {agree}/{len(ok)} |\n")
    (out / f"summary-{args.detail}.md").write_text(table, encoding="utf-8")
    print("\n" + table)


if __name__ == "__main__":
    asyncio.run(main())
