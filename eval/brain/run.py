"""Run the test cases (cases.py) through the brain's own code (gpt/brain.py as it is in the repo: instructions,
tools, the frame's bottom square at BRAIN_SIDE), one stateless look per case.
Usage: run.py <provider> <model env var> <side> <repeats> <out.json> [effort] [repo|drawing|plate]
Earlier variants (JSON output, wording v2, reference drawing) survive only as their result files."""
import asyncio, json, os, sys, time, types
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CALLER = os.getcwd()  # the out path on the command line is the caller's
os.chdir(ROOT)
sys.path.insert(0, "backend/agent/src"); sys.path.insert(0, "eval/brain")
from dotenv import load_dotenv
load_dotenv("backend/.env")
from PIL import Image
from livekit import rtc
import gpt.brain as B
from guide import Build, load_guide
from cases import CASES

provider, model_var, side, repeats, out_path = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
effort = sys.argv[6] if len(sys.argv) > 6 else "none"
image = sys.argv[7] if len(sys.argv) > 7 else "repo"
model_id = os.environ[model_var]
guide = load_guide("guides/truck")
CUR = {"case": None}

if image in ("drawing", "plate"):
    # 'perfect view' tests: the photo replaced by a top-down drawing of what is on the plate (states.py), or by the
    # plate cut out of the full frame (10 % margin) and scaled up; both at side x side like the real input
    import io
    import states
    from gate import plate_bbox

    def _jpeg_alt(frame, side):
        if image == "drawing":
            img = states.draw(CUR["case"]).resize((side, side), Image.LANCZOS)
        else:
            img = B.to_image(frame); x0, y0, x1, y1 = plate_bbox(img); mx, my = (x1 - x0) // 10, (y1 - y0) // 10
            img = img.crop((max(0, x0 - mx), max(0, y0 - my), min(img.width, x1 + mx), min(img.height, y1 + my)))
            k = side / max(img.size); img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
        buf = io.BytesIO(); img.save(buf, "JPEG", quality=90); return buf.getvalue()
    B._jpeg = _jpeg_alt
    CASES = [c for c in CASES if c[0] != "M"]


class Timed:
    def __init__(s, m): s.m, s.last = m, None
    async def ask(s, *a):
        t0 = time.perf_counter(); out = await s.m.ask(*a)
        s.last = (time.perf_counter() - t0, out[2]); return out


class Tap:
    dumping = False
    def __init__(s): s.frame = None
    async def next_frame(s, t): return s.frame


async def main():
    model = Timed(B.make_model(provider, model_id, effort, "high"))
    tap = Tap()
    sess = types.SimpleNamespace(current_agent=None, agent_state="listening")
    rows = []
    for r in range(repeats):
        for cid, fr, step, words, after, truth in CASES:
            img = Image.open(f"eval/brain/frames/{fr}.jpg").convert("RGB")
            tap.frame = rtc.VideoFrame(img.width, img.height, rtc.VideoBufferType.RGB24, img.tobytes())
            CUR["case"] = cid
            build = Build(guide=guide, run=f"haiku-test-{provider}")
            build.step = step - 1
            brain = B.Brain(sess, build, tap, model, side, "English")
            brain.note("voice", guide.steps[step - 1].say if step <= len(guide.steps) else "That was the last step.")
            try:
                out = await brain._ask(words, 1)
                secs, u = model.last
                got = step + 1 if out["done"] else step
                rows.append(dict(case=cid, rep=r, secs=round(secs, 2), u=u, out=dict(text=out["text"], calls=out["calls"],
                                 step=got), ok_step=got == after))
            except Exception as e:
                rows.append(dict(case=cid, rep=r, error=f"{type(e).__name__}: {e}"[:300]))
            print(cid, r, rows[-1].get("secs"), rows[-1].get("ok_step"), rows[-1].get("error", ""), flush=True)
    json.dump(dict(provider=provider, model=model_id, side=side, effort=effort, image=image, rows=rows),
              open(os.path.join(CALLER, out_path), "w"), indent=1)

asyncio.run(main())
