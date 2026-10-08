"""Probe: at the point where the replay stuck at step 5, the wearer pushes back. Rebuilds the brain's timeline
from the replay result up to that ask, adds the wearer's words, and asks again on the same frame, N times."""
import asyncio, json, os, re, sys, types
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")); CALLER = os.getcwd(); os.chdir(ROOT)
sys.path.insert(0, "backend/agent/src")
from dotenv import load_dotenv; load_dotenv("backend/.env")
from PIL import Image
from livekit import rtc
import gpt.brain as B
from guide import Build, load_guide

result, upto, words, reps, out = sys.argv[1], float(sys.argv[2]), sys.argv[3], int(sys.argv[4]), sys.argv[5]
R = json.load(open(os.path.join(CALLER, result)))["rows"]
guide = load_guide("guides/truck")
mmss = lambda t: f"{int(t) // 60:02d}:{int(t) % 60:02d}"
timeline, last = [], None
for r in R:
    if r["t"] > upto:
        break
    timeline.append(f"{mmss(r['t'])} wearer: {r['words']}")
    text = r["commentary"][0]
    text = re.sub(r"^Camera: ", "", text); text = re.sub(r" Step \d+ is recorded as done.*$", "", text)
    timeline.append(f"{mmss(r['t'])} you answered: {text}")
    if r["step_after"] > r["step_before"]:
        timeline.append(f"{mmss(r['t'])} you recorded: step {r['step_before']} done")
    last = r
t = last["t"] + 4
timeline.append(f"{mmss(t)} wearer: {words}")

class Tap:
    dumping = False
    async def next_frame(self, _): return self.frame

async def main():
    model = B.make_model("anthropic", os.environ["BRAIN_MODEL"], "medium", "high")
    img = Image.open(f"tmp/lab/20261007d/frames/{last['frame']}").convert("RGB")
    tap = Tap(); tap.frame = rtc.VideoFrame(img.width, img.height, rtc.VideoBufferType.RGB24, img.tobytes())
    sess = types.SimpleNamespace(current_agent=None, agent_state="listening")
    rows = []
    for i in range(reps):
        build = Build(guide=guide, run="probe"); build.step = last["step_after"] - 1
        brain = B.Brain(sess, build, tap, model, 1080, "English", timeout=60)
        brain._timeline = list(timeline)
        o = await brain._ask(words, 1)
        rows.append(dict(rep=i, done=o["done"], calls=o["calls"], text=o["text"]))
        print(i, "confirmed" if o["done"] else "not confirmed", "|", o["text"])
    json.dump(dict(frame=last["frame"], step=last["step_after"], words=words, timeline=timeline, rows=rows),
              open(os.path.join(CALLER, out), "w"), indent=1)
asyncio.run(main())
