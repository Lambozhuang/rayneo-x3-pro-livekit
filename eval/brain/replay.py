"""Replay a recorded lab run through the brain, in order, with the timeline building up as in a call.

The run's agent.log and its frame dump (FRAME_DUMP_DIR) give: what the wearer said and when, every frame the old
loop judged and when it was taken (log time minus the judge call's latency), and when the old loop saw each step
done or wrong. The asks are the wearer's real words, plus a synthetic "Is it right?" at each moment the old loop
saw a step done or wrong (the new system has no watcher: the wearer has to ask). Each ask gets the first judged
frame taken after it (within FRESH s), else the last one before it. One brain for the whole run: its replies and
confirmations stay in its timeline and its confirmations move the step. The voice's lines are left out (they came
from the old system).

    python eval/brain/replay.py plan <run dir>                       the ask list, no API call
    python eval/brain/replay.py run <run dir> <provider> <model env var> <effort> <out.json>
(run from backend/agent with uv, like run.py)
"""
import asyncio, datetime as dt, json, os, re, sys, time, types
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CALLER = os.getcwd()  # paths on the command line are the caller's
os.chdir(ROOT)
sys.path.insert(0, "backend/agent/src")

FRESH = 6.0  # s after the ask within which a frame counts as taken after it
SYNTH = "Is it right?"


def ts(d):
    return dt.datetime.fromisoformat(d["timestamp"]).timestamp()


def load(run):
    frames = sorted(f for f in os.listdir(f"{run}/frames") if re.match(r"\d+-s\d+-", f))
    judged, said, events, t0 = [], [], [], None
    for line in open(f"{run}/agent.log", encoding="utf-8", errors="replace"):
        if not line.startswith("{"):
            continue
        d = json.loads(line)
        m = d.get("message", "")
        if not d.get("room"):
            continue
        t = ts(d)
        if m.startswith("step 1/") and "start" in m and t0 is None:
            t0 = t
        if m.startswith("judge: step"):
            ms = float(re.search(r" (\d+) ms ", m).group(1))
            judged.append(t - ms / 1000)
        elif m.startswith("user:"):
            said.append((t, m[5:].strip()))
        elif re.match(r"step \d+/\d+ done", m):
            events.append((t, "done", int(m.split()[1].split("/")[0])))
        elif re.match(r"step \d+ wrong", m):
            events.append((t, "wrong", int(m.split()[1])))
    assert len(frames) == len(judged), (len(frames), len(judged))
    shots = list(zip(judged, frames))  # (time taken, file), in verdict order
    shots.sort()
    asks = [(t, w, "said") for t, w in said]
    for t, kind, n in events:
        if not any(0 <= t - ta <= 4 for ta, _, _ in asks):  # a real ask just before covers it
            asks.append((t, SYNTH, f"synthetic (old loop: step {n} {kind})"))
    asks.sort()
    plan = []
    for t, words, why in asks:
        after = [s for s in shots if t <= s[0] <= t + FRESH]
        shot, gap = (after[0], after[0][0] - t) if after else (max((s for s in shots if s[0] < t), default=None), None)
        if shot is None:
            continue
        plan.append(dict(t=round(t - t0, 1), words=words, why=why, frame=shot[1],
                         frame_t=round(shot[0] - t0, 1), gap=None if gap is None else round(gap, 1)))
    return plan, [(round(t - t0, 1), k, n) for t, k, n in events]


def show(plan, events):
    print(f"{len(plan)} asks; old loop events: {len(events)}")
    for p in plan:
        g = f"+{p['gap']}s" if p["gap"] is not None else "BEFORE"
        print(f"{p['t']:6.1f}s  {p['words'][:44]:44}  {p['why'][:34]:34}  frame {p['frame']}  ({g})")


async def run(run_dir, plan, provider, model_var, effort, out_path):
    from dotenv import load_dotenv
    load_dotenv("backend/.env")
    from PIL import Image
    from livekit import rtc
    import gpt.brain as B
    from guide import Build, load_guide
    guide = load_guide("guides/truck")
    inner = B.make_model(provider, os.environ[model_var], effort, "high")
    last = {}

    class Recorded:  # the model, with each call's usage kept for the result file
        async def ask(self, *a):
            out = await inner.ask(*a)
            last.update(usage=out[2], calls=out[1])
            return out
    model = Recorded()
    sent = []
    duplex = types.SimpleNamespace(append_commentary=lambda t, delegation_id=None: sent.append(("commentary", t)),
                                   append_thinking=lambda t, delegation_id=None: sent.append(("thinking", t)))
    sess = types.SimpleNamespace(current_agent=types.SimpleNamespace(duplex_session=duplex), agent_state="listening")

    async def pub(b):
        pass
    B.publish_build = pub

    class Tap:
        dumping = False
        frame = None
        async def next_frame(self, t): return self.frame
    tap = Tap()
    build = Build(guide=guide, run=f"replay-{provider}")
    brain = B.Brain(sess, build, tap, model, 1080, "English", timeout=60)
    clock = {"t": 0.0}

    def note(who, text):  # the replay's clock, not the wall clock
        text = " ".join(text.split())
        if text:
            t = int(clock["t"])
            brain._timeline.append(f"{t // 60:02d}:{t % 60:02d} {who}: {text}")
    brain.note = note
    rows = []
    for n, p in enumerate(plan, 1):
        clock["t"] = p["t"]
        img = Image.open(f"{run_dir}/frames/{p['frame']}").convert("RGB")
        tap.frame = rtc.VideoFrame(img.width, img.height, rtc.VideoBufferType.RGB24, img.tobytes())
        note("wearer", p["words"])
        before = build.step + 1
        sent.clear()
        t0 = time.perf_counter()
        await brain._answer(f"d{n}", p["words"], n)
        secs = time.perf_counter() - t0
        rows.append(dict(p, step_before=before, step_after=build.step + 1, secs=round(secs, 2), usage=last.get("usage"),
                         calls=last.get("calls"),
                         commentary=[t for k, t in sent if k == "commentary"], timeline_lines=len(brain._timeline)))
        print(f"{p['t']:6.1f}s step {before}->{build.step + 1} {secs:4.1f}s | {p['words'][:30]:30} | "
              f"{(rows[-1]['commentary'] or [''])[0][:120]}", flush=True)
    json.dump(dict(provider=provider, model=os.environ[model_var], effort=effort, run=run_dir, rows=rows),
              open(out_path, "w"), indent=1)


if __name__ == "__main__":
    cmd, run_dir = sys.argv[1], os.path.relpath(os.path.join(CALLER, sys.argv[2]), ROOT)
    plan, events = load(run_dir)
    if cmd == "plan":
        show(plan, events)
    else:
        provider, model_var, effort, out = sys.argv[3:7]
        asyncio.run(run(run_dir, plan, provider, model_var, effort, os.path.join(CALLER, out)))
