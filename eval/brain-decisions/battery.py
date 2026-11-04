"""Asks the Decisions API the whole battery an eyes-only design would need, on a recorded call's photos: beside the
state questions of probe.py, the current step's placement in detail (on the plate, orientation, which way off and by
how much, as the step says) and where the step's brick lies, and times it.

    backend/agent/.venv/Scripts/python eval/brain-decisions/battery.py <record dir> [--first w100] [--last w144]
        [--step 4] [--detail low]

The current step is the record's (the step the user was on at each look) unless --step fixes it, as for the gate
record of 2026-10-28 where the white 1x6 of step 4 lay one column too far right from w100 to w144 and the brain's
progress went back and forth. out/battery-<record>-<detail>.json has every look's answers; the console prints a
line a look.
"""

import argparse
import asyncio
import base64
import importlib.util
import json
import os
import re
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

from guide import Guide, load_guide  # noqa: E402
from prompts import task_block  # noqa: E402

out = here / "out"
URL = "https://api.openai.com/v1/decisions"


def battery(guide: Guide, k: int) -> list[dict]:
    """The questions for step k (1-based): the state questions and the step's placement."""
    n = len(guide.steps)
    step = guide.steps[min(k, n) - 1]  # after the last step the questions stay on it
    bricks = [{"value": f"step {i}", "description": f"the {s.brick} of step {i}"} for i, s in enumerate(guide.steps, 1)]
    counts = [{"value": str(c), "description": ("nothing is built right yet" if c == 0 else
                                                 "every step is built right" if c == n else
                                                 f"steps 1 to {c} are built right, step {c + 1} is not placed or not right")}
              for c in range(n + 1)]
    qs = [
        {"type": "predicate", "name": "hand",
         "instructions": "Is a hand touching the baseplate, touching a brick on it, or covering part of it?"},
        {"type": "choice", "name": "in_hand",
         "instructions": "Which brick is the user holding in a hand right now, above the desk or the plate, not resting on the plate?",
         "choices": bricks + [{"value": "another brick", "description": "a brick that is none of the steps' bricks"},
                              {"value": "none", "description": "no brick is held in a hand"}]},
        {"type": "choice", "name": "done",
         "instructions": "Counting from step 1 in order, how many steps are built right on the baseplate, each brick in its "
                         "place and orientation as the steps say? A brick still under a hand does not count.",
         "choices": counts},
        {"type": "predicate", "name": "blurry",
         "instructions": "Is the photo blurry, smeared or blocky from compression, so that the studs on the bricks cannot be made out?"},
        {"type": "choice", "name": "where",
         "instructions": f"Where is the {step.brick} of step {k} right now?",
         "choices": [{"value": "in a hand"}, {"value": "on the baseplate"}, {"value": "left of the plate, on the desk"},
                     {"value": "right of the plate, on the desk"}, {"value": "beyond the plate, on the desk at the far side"},
                     {"value": "before the plate, on the desk at the near side"}, {"value": "not visible"}]},
        {"type": "predicate", "name": "on_plate",
         "instructions": f"Is the {step.brick} of step {k} resting on the baseplate, pressed on, with no hand on it?"},
        {"type": "predicate", "name": "as_said",
         "instructions": f"Step {k} says the {step.brick} goes {step.place}. Is the {step.brick} on the baseplate exactly there, "
                         "in that orientation, touching what it should touch, in the right row and column?"},
        {"type": "choice", "name": "off",
         "instructions": f"Compared with where step {k} puts it ({step.place}), where does the {step.brick} on the baseplate sit? "
                         "Up is toward the far edge of the plate, down toward the near edge, left and right as the user sees them. "
                         "If it is not on the baseplate, answer not on the plate.",
         "choices": [{"value": "in the right place"}, {"value": "too far left"}, {"value": "too far right"},
                     {"value": "too far up"}, {"value": "too far down"}, {"value": "turned the wrong way"},
                     {"value": "not on the plate"}, {"value": "can't tell"}]},
        {"type": "choice", "name": "by",
         "instructions": f"If the {step.brick} of step {k} is on the baseplate but off its place, by how many studs is it off?",
         "choices": [{"value": "in the right place"}, {"value": "one stud"}, {"value": "two studs"},
                     {"value": "three or more"}, {"value": "not on the plate or can't tell"}]},
    ]
    m = re.search(r"\b(horizontal|vertical)\b", step.place)
    if m:
        qs.append({"type": "predicate", "name": "orientation",
                   "instructions": f"Is the {step.brick} on the baseplate lying {m.group(1)}, as step {k} says "
                                   "(vertical: its long side runs up and down the plate; horizontal: left and right)?"})
    return qs


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("record")
    ap.add_argument("--first", default=None)
    ap.add_argument("--last", default=None)
    ap.add_argument("--step", type=int, default=None, help="the current step for every look, instead of the record's")
    ap.add_argument("--detail", default="low")
    ap.add_argument("--model", default="gpt-6-luna")
    ap.add_argument("--reference", action="store_true",
                    help="give the step's rendered picture (step-<k>.png, the plate from above, the brick outlined) as a reference image")
    args = ap.parse_args()
    rec = Path(args.record)
    if not rec.is_absolute():
        rec = root / rec
    call = json.loads(open(rec / "events.jsonl", encoding="utf-8").readline())
    replay.load_key("openai")
    guide = load_guide(root / "backend" / "agent" / "guides" / call["guide"] / "task.toml")
    task = task_block(guide)
    todo = [l for l in replay.looks(rec)]
    ids = [l["id"] for l in todo]
    start = ids.index(args.first) if args.first else 0
    stop = ids.index(args.last) + 1 if args.last else len(todo)
    todo = todo[start:stop]
    out.mkdir(exist_ok=True)
    rows = []
    headers = {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60) as http:
        for look in todo:
            s = look["sent"]
            k = args.step or s["step"]
            photo = (rec / s["photo"]).read_bytes()
            text = f"{task}\n\nThe photo is what the user's glasses see right now, the desk from above. The user is on step {k}."
            content = [{"type": "input_text", "text": text},
                       {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(photo).decode(),
                        "detail": args.detail}]
            if args.reference:
                png = guide.picture(min(k, len(guide.steps))).read_bytes()
                content += [{"type": "input_text",
                             "text": f"The second picture is the reference for step {k}: the baseplate from straight above, the bricks "
                                     f"of steps 1 to {k} in their right places, the step {k} brick outlined. Compare the photo with it."},
                            {"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(png).decode(),
                             "detail": args.detail}]
            body = {"model": args.model, "input": [{"type": "message", "role": "user", "content": content}],
                    "questions": battery(guide, k)}
            t0 = time.perf_counter()
            r = await http.post(URL, headers=headers, json=body)
            ms = round((time.perf_counter() - t0) * 1000)
            if r.status_code != 200:
                print(f"{look['id']:<5} HTTP {r.status_code}: {r.text[:300]}")
                rows.append({"id": look["id"], "error": r.text[:500], "ms": ms})
                continue
            data = r.json()
            a = {}
            for x in data.get("answers", []):
                if x["type"] == "predicate":
                    a[x["name"]] = round(x["probability"], 2)
                elif x["type"] == "choice":
                    a[x["name"]] = (x["choice"], round(x.get("confidence", 0), 2))
                else:
                    a[x["name"]] = x["type"]
            u = data.get("usage", {})
            rows.append({"id": look["id"], "step": k, "ms": ms, "answers": a, "usage": u,
                         "record_reply": look["back"]["reply"], "record_calls": look["back"]["calls"]})
            print(f"{look['id']:<5} k{k} {ms:4d} ms  hand {a['hand']:<4} in_hand {a['in_hand'][0]:<13}{a['in_hand'][1]:<5} done {a['done'][0]} {a['done'][1]:<5} "
                  f"where {a['where'][0][:18]:<18} on {a['on_plate']:<4} as_said {a['as_said']:<4} off {a['off'][0]:<18}{a['off'][1]:<5} "
                  f"by {a['by'][0]:<10} ori {a.get('orientation', '-')}  | {look['back']['reply'][:50]}")
    (out / f"battery-{rec.name}-{args.detail}{'-ref' if args.reference else ''}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = [x for x in rows if "answers" in x]
    if ok:
        ms = sorted(x["ms"] for x in ok)
        print(f"\n{len(ok)} looks, {len(ok[0]['answers'])} questions: latency median {st.median(ms):.0f} ms, p90 {ms[int(.9 * len(ms)) - 1]}, "
              f"max {ms[-1]}; input tokens median {st.median([x['usage'].get('input_tokens', 0) for x in ok]):.0f}")


if __name__ == "__main__":
    asyncio.run(main())
