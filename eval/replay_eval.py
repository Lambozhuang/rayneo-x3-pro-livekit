"""Replay the recorded run through gate -> judge -> state machine and compare the state timeline with the truth.

  python eval/replay_eval.py run [--confirm 2] [--frames frames_1080p15]
  python eval/replay_eval.py report

Frames are taken in order at 1 fps. For each frame the gate (eval/gate_eval.py) decides whether to ask; if so the
judge (gpt-6-sol, no reasoning, terse2 relational prompt, server-side crop; same code as judge_eval.py) is asked
about the state machine's current step N. The state machine:
  correct  CONFIRM times in a row -> step N done, N += 1, fact "step N placed"
  wrong    CONFIRM times in a row -> fact "step N wrong: <first failed check>", said once per wrong spell
  not_placed / cannot_see         -> counters reset, nothing said
Judge answers are cached per (frames folder, clip, frame, step) in truck/results/replay_cache.jsonl, so a rerun with
another --confirm costs no calls. Output: truck/results/replay_<frames>_c<confirm>.json with the timeline and the
comparison against events.json (detection delay per step, alarm time per error window, false alarms).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import judge_eval as je  # noqa: E402
from gate_eval import HAND_TOTAL, skin_stats, tight_box  # noqa: E402
from gate_eval import BORDER, MIN_SIDE, ASPECT  # noqa: E402

CACHE = je.RESULTS / "replay_cache.jsonl"


def gate(img: Image.Image) -> tuple[bool, str]:
    box = tight_box(img)
    if not box:
        return False, "no plate"
    x0, y0, x1, y1 = box
    w, h = img.size
    bw, bh = x1 - x0, y1 - y0
    if not (x0 > w * BORDER and y0 > h * BORDER and x1 < w * (1 - BORDER) and y1 < h * (1 - BORDER)):
        return False, "plate cut"
    if min(bw, bh) < w * MIN_SIDE or not (ASPECT[0] <= bw / bh <= ASPECT[1]):
        return False, "plate partial"
    if skin_stats(img.crop(box))["skin"] >= HAND_TOTAL:
        return False, "hand"
    return True, "ok"


class Judge:
    def __init__(self, frames: str):
        je.load_env()
        self.frames = frames
        self.steps, _ = je.load()
        self.model = je.OpenAIJudge()
        self.tag = self.model.tag + "_terse2"
        self.cache = {}
        if CACHE.exists():
            for line in CACHE.read_text(encoding="utf-8").splitlines():
                d = json.loads(line)
                self.cache[(d["frames"], d["clip"], d["frame"], d["step"], d["model"])] = d
        self.calls = 0

    def ask(self, clip: str, frame: str, step: int) -> dict:
        key = (self.frames, clip, frame, step, self.tag)
        if key in self.cache:
            return self.cache[key]
        photo = je.prep_photo(je.FRAMES / clip / frame, "C")
        if photo is None:
            rec = {"answer": "cannot_see", "checks": "", "reason": "no plate in green mask", "latency": 0.0, "raw": ""}
        else:
            t0 = time.perf_counter()
            text, usage = self.model.ask(None, je.to_jpeg(photo), je.step_text_rel(self.steps, step), je.SYSTEM_REL_TERSE2)
            answer, reason = je.parse_answer(text)
            checks = ""
            try:
                checks = str(json.loads(text[text.index("{"):text.rindex("}") + 1]).get("checks", ""))
            except (ValueError, AttributeError):
                pass
            rec = {"answer": answer, "checks": checks, "reason": reason, "latency": round(time.perf_counter() - t0, 2),
                   "ttft": usage.pop("ttft", None), "usage": usage, "raw": text}
            self.calls += 1
        rec.update(frames=self.frames, clip=clip, frame=frame, step=step, model=self.tag)
        with CACHE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        self.cache[key] = rec
        return rec


def failed_check(steps, step: int, checks: str) -> str:
    s = next(s for s in steps if s["step"] == step)
    for i, ch in enumerate(checks):
        if ch == "n" and i < len(s["checks"]):
            return s["checks"][i]
    return "placement differs"


def cmd_run(args):
    if args.frames:
        je.FRAMES = je.RUN / args.frames
    judge = Judge(args.frames or "frames")
    steps = judge.steps
    n, last = 1, len(steps)
    streak_ok = streak_bad = 0
    said_wrong = False
    timeline = []  # one entry per frame
    facts = []
    for i, (clip, t) in enumerate(je.frame_list()):
        frame = f"{t + 1:03d}.jpg"
        img = Image.open(je.FRAMES / clip / frame).convert("RGB")
        ok, why = gate(img)
        entry = {"i": i, "clip": clip, "t": t, "step": n, "gate": why}
        if ok and n <= last:
            v = judge.ask(clip, frame, n)
            entry.update(answer=v["answer"], latency=v.get("latency"), reason=v["reason"])
            if v["answer"] == "correct":
                streak_ok, streak_bad = streak_ok + 1, 0
                if streak_ok >= args.confirm:
                    facts.append({"i": i, "clip": clip, "t": t, "kind": "done", "step": n, "text": f"step {n} placed"})
                    n += 1
                    streak_ok = streak_bad = 0
                    said_wrong = False
            elif v["answer"] == "wrong":
                streak_bad, streak_ok = streak_bad + 1, 0
                if streak_bad >= args.confirm and not said_wrong:
                    facts.append({"i": i, "clip": clip, "t": t, "kind": "wrong", "step": n,
                                  "text": f"step {n} wrong: {failed_check(steps, n, v['checks'])}"})
                    said_wrong = True
            else:
                streak_ok = streak_bad = 0
                if v["answer"] == "not_placed":
                    said_wrong = False
        timeline.append(entry)
        print(f"{i:3d} {clip[5:]}/{frame[:3]} N={n:2d} {why:<13} {entry.get('answer', ''):<10} {entry.get('reason', '')[:60]}")
    out = je.RESULTS / f"replay_{args.frames or 'frames'}_c{args.confirm}.json"
    out.write_text(json.dumps({"confirm": args.confirm, "frames": args.frames or "frames", "model": judge.tag,
                               "calls": judge.calls, "facts": facts, "timeline": timeline}, indent=1), encoding="utf-8")
    print(f"{judge.calls} new calls; facts {len(facts)}; -> {out.name}")
    report(out)


def report(path: Path):
    r = json.loads(path.read_text(encoding="utf-8"))
    _, events = je.load()
    idx = {(c, t): i for i, (c, t) in enumerate(je.frame_list())}
    facts = r["facts"]
    print(f"\n== {path.name}: confirm {r['confirm']}, {len(r['facts'])} facts, {sum(1 for e in r['timeline'] if 'answer' in e)} judge answers over {len(r['timeline'])} frames")
    print(f"{'step':>4} {'truth done':>11} {'detected':>9} {'delay s':>8}   error window -> alarm")
    for s in events["steps"]:
        n = s["step"]
        truth = idx[tuple(s["done"])]
        det = next((f for f in facts if f["kind"] == "done" and f["step"] == n), None)
        d = f"{det['i'] - truth:+d}" if det else "never"
        w = s.get("wrong")
        alarm = ""
        if w:
            a, b = idx[tuple(w["from"])], idx[tuple(w["to"])]
            al = [f for f in facts if f["kind"] == "wrong" and f["step"] == n]
            alarm = f"[{a}-{b}] -> " + (", ".join(f"{f['i']}" + ("" if a <= f["i"] <= b + 2 else "(late)" if f["i"] > b + 2 else "(early)") for f in al) if al else "missed")
        print(f"{n:>4} {truth:>11} {det['i'] if det else '-':>9} {d:>8}   {alarm}")
    wrong_steps = {s["step"] for s in events["steps"] if s.get("wrong")}
    false_alarms = [f for f in facts if f["kind"] == "wrong" and f["step"] not in wrong_steps]
    print("false alarms:", [(f["clip"][5:], f["t"], f["step"], f["text"]) for f in false_alarms])
    for f in facts:
        print(f"  {f['i']:3d} {f['clip'][5:]}/{f['t'] + 1:03d}  {f['text']}")


def cmd_report(args):
    for p in sorted(je.RESULTS.glob("replay_*_c*.json")):
        report(p)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--confirm", type=int, default=2)
    p.add_argument("--frames")
    p.set_defaults(fn=cmd_run)
    sub.add_parser("report").set_defaults(fn=cmd_report)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
