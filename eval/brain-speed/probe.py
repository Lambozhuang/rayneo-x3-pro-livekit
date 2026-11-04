"""Replays the first looks of a recorded call through the brain's code under several speed variants and times each.

    backend/agent/.venv/Scripts/python eval/brain-speed/probe.py <record dir> [--looks 30] [--tier priority]
        [--variants terra-1080-http,terra-768-http,terra-1080-ws,luna-1080-http,luna-768-http]

A variant is <model>-<side>-<transport>: the model is terra (gpt-6.1-terra) or luna (gpt-6-luna), the side is the
pixel size the record's photo is scaled to before it is sent, and the transport is http (one request per look, as
the agent does today) or ws (one persistent WebSocket to the Responses API, a response.create event per look). Each
variant runs the same looks in the record's order as one conversation of its own, the brain's code unchanged
(gpt/brain.py, its OpenAIWsModel for ws), so the request has the shape a call has: instructions, every look so far,
the newest photo.

Per look it keeps the model's time, the tokens (in, cached, out), the reply and the tool calls beside the record's.
out/<variant>.json has every look, out/summary.md the table. The key comes from backend/.env.
"""

import argparse
import asyncio
import importlib.util
import io
import json
import statistics as st
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

here = Path(__file__).resolve().parent
root = here.parent.parent
sys.path.insert(0, str(root / "backend" / "agent" / "src"))

spec = importlib.util.spec_from_file_location("replay", root / "eval" / "brain-thread-replay" / "replay.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)

from gpt import brain  # noqa: E402
from gpt.brain import TOOLS, Brain, OpenAIModel, OpenAIWsModel  # noqa: E402
from guide import Build, load_guide  # noqa: E402
from runlog import RunLog  # noqa: E402

out = here / "out"
MODELS = {"terra": "gpt-6.1-terra", "luna": "gpt-6-luna"}


def scaled(photo: bytes, side: int) -> bytes:
    """The record's photo (1080 px) scaled down to `side`, re-encoded as the brain encodes (JPEG quality 85)."""
    img = Image.open(io.BytesIO(photo))
    if max(img.size) <= side:
        return photo
    img.thumbnail((side, side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


class Timed:
    """Wraps a model so every ask's wall time and usage are kept."""

    def __init__(self, model) -> None:
        self.model = model
        self.last: tuple[int, dict] | None = None

    async def ask(self, *a, **kw):
        t0 = time.perf_counter()
        reply, calls, output, u = await self.model.ask(*a, **kw)
        self.last = (round((time.perf_counter() - t0) * 1000), u)
        return reply, calls, output, u


async def run_variant(name: str, rec: Path, todo: list[dict], call: dict, tier: str, effort: str) -> dict:
    kind, side, transport = name.split("-")
    side = int(side)
    model_id = MODELS[kind]
    inner = OpenAIWsModel(model_id, "high", tier) if transport == "ws" else OpenAIModel(model_id, "high", tier)
    model = Timed(inner)
    guide = load_guide(root / "backend" / "agent" / "guides" / call["guide"] / "task.toml")

    async def no_publish(build) -> None:
        pass
    brain.publish_build = no_publish
    brain.get_job_context = lambda: SimpleNamespace(room=SimpleNamespace(local_participant=replay.Participant()))
    brain._jpeg = lambda frame, s: scaled(frame.jpeg, s)

    voice = replay.Voice()
    tap = SimpleNamespace(latest=None, count=0, latest_at=time.monotonic())
    build = Build(guide=guide, run=f"{rec.name}-{name}")
    (out / name).mkdir(parents=True, exist_ok=True)
    b = Brain(voice, build, tap, model, effort, side, 2.0, call["language"], record=RunLog(str(out / name), rec.name))
    rows = []
    print(f"\n== {name}: {model_id} at {side} px over {transport}, tier {tier}, effort {effort}")
    for look in todo:
        s = look["sent"]
        voice.history.add(replay.chat_lines(s))
        photo = (rec / s["photo"]).read_bytes()
        tap.latest = SimpleNamespace(jpeg=photo, width=1080, height=1080)
        tap.count += 1
        tap.latest_at = time.monotonic()
        b._look_w = look["n"]
        voice.appended = []
        try:
            text, calls, kept = await b._look_once("watch", look["n"], side, None, TOOLS)
        except Exception as e:  # noqa: BLE001
            print(f"{look['id']:<5} failed: {type(e).__name__}: {str(e)[:160]}")
            rows.append({"id": look["id"], "error": f"{type(e).__name__}: {e}"[:300]})
            continue
        await b._carry_out(kept, calls, "watch", look["n"])
        ms, u = model.last
        rows.append({"id": look["id"], "ms": ms, "in": u["in"], "cached": u["cached"], "out": u["out"],
                     "thinking": u.get("thinking"), "reply": text, "calls": [[c, a] for _, c, a in calls],
                     "record_ms": look["back"]["model_ms"], "record_calls": look["back"]["calls"]})
        tools_said = ", ".join(f"{c}({a.get('done', a.get('kind', a.get('step', '')))})" for _, c, a in calls) or "-"
        print(f"{look['id']:<5} {ms:5d} ms (record {look['back']['model_ms']:5d})  in {u['in']:5d} cached {u['cached']:5d} "
              f"out {u['out']:3d}  {tools_said}  | {text[:70]}")
    if transport == "ws":
        await inner.close()
    (out / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"name": name, "rows": rows}


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


def summary(results: list[dict], todo: list[dict]) -> str:
    rec_ms = [l["back"]["model_ms"] for l in todo]
    lines = ["| variant | looks | model ms median / p90 / max | uncached tokens median | out tokens median | set_progress calls | says | failed |",
             "|---|---|---|---|---|---|---|---|",
             f"| record (as it ran) | {len(todo)} | {st.median(rec_ms):.0f} / {q(rec_ms, .9)} / {max(rec_ms)} | - | - | "
             f"{sum(1 for l in todo for c in l['back']['calls'] if c[0] == 'set_progress')} | "
             f"{sum(1 for l in todo for c in l['back']['calls'] if c[0] == 'say')} | - |"]
    for r in results:
        ok = [x for x in r["rows"] if "ms" in x]
        if not ok:
            lines.append(f"| {r['name']} | 0 | - | - | - | - | - | {len(r['rows'])} |")
            continue
        ms = [x["ms"] for x in ok]
        unc = [x["in"] - x["cached"] for x in ok]
        lines.append(f"| {r['name']} | {len(ok)} | {st.median(ms):.0f} / {q(ms, .9)} / {max(ms)} | {st.median(unc):.0f} | "
                     f"{st.median([x['out'] for x in ok]):.0f} | {sum(1 for x in ok for c in x['calls'] if c[0] == 'set_progress')} | "
                     f"{sum(1 for x in ok for c in x['calls'] if c[0] == 'say')} | {len(r['rows']) - len(ok)} |")
    return "\n".join(lines)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("record")
    ap.add_argument("--looks", type=int, default=30)
    ap.add_argument("--tier", default="priority")
    ap.add_argument("--effort", default="none")
    ap.add_argument("--variants", default="terra-1080-http,terra-768-http,terra-1080-ws,luna-1080-http,luna-768-http")
    args = ap.parse_args()
    rec = Path(args.record)
    call = json.loads(open(rec / "events.jsonl", encoding="utf-8").readline())
    replay.load_key("openai")
    todo = [l for l in replay.looks(rec) if l["kind"] == "watch"][: args.looks]
    out.mkdir(exist_ok=True)
    results = []
    for name in args.variants.split(","):
        results.append(await run_variant(name, rec, todo, call, args.tier, args.effort))
        table = summary(results, todo)
        (out / "summary.md").write_text(f"# {rec.name}, first {len(todo)} looks, tier {args.tier}, effort {args.effort}\n\n{table}\n", encoding="utf-8")
    print("\n" + table)


if __name__ == "__main__":
    asyncio.run(main())
