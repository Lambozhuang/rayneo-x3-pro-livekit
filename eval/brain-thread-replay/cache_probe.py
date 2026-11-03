"""Sends six consecutive looks of a record through the brain, one way at a time, and prints OpenAI's cached tokens
per look, to see when the Responses API's prompt cache takes the conversation and when it does not.

    backend/agent/.venv/Scripts/python eval/brain-thread-replay/cache_probe.py <record dir> <variant>

Variants: asis (the code as it is, the photo taken out of a look once answered), photos (every photo kept),
trailing (the photo as a user item of its own after the look's text), noimage (no photo at all), lowdetail (the
photo at detail low), store (store=True), noreasoning (the reasoning items not passed back). The README has the
result of 2026-11-02.
"""
import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "eval" / "brain-thread-replay"))
import replay  # noqa: E402
from gpt import brain  # noqa: E402
from gpt.brain import TOOLS, Brain, OpenAIModel  # noqa: E402
from guide import Build, load_guide  # noqa: E402
import json  # noqa: E402

rec = Path(sys.argv[1])
variant = sys.argv[2]
call = json.loads(open(rec / "events.jsonl", encoding="utf-8").readline())
s = call["settings"]
replay.load_key("openai")
guide = load_guide(root / "backend" / "agent" / "guides" / call["guide"] / "task.toml")
model = OpenAIModel(s["brain_model"], s["brain_detail"])

if variant == "photos":
    original = OpenAIModel._render

    def keep_photos(self, looks):
        for look in looks:
            if look.photo is None and getattr(look, "kept_photo", None) is not None:
                look.photo = look.kept_photo
        items = original(self, looks)
        for look in looks[:-1]:
            look.kept_photo, look.photo = look.photo, None
        return items
    OpenAIModel._render = keep_photos
elif variant == "trailing":
    def trailing(self, looks):
        items = []
        for look in looks:
            items.append({"role": "user", "content": [{"type": "input_text", "text": look.text}]})
            items.extend(look.output)
            for call_id, _, _ in look.calls:
                items.append({"type": "function_call_output", "call_id": call_id,
                              "output": look.results.get(call_id, brain.NOT_DONE)})
        if looks[-1].photo is not None:
            items.append({"role": "user", "content": [
                {"type": "input_image", "image_url": brain._data_url(looks[-1].photo), "detail": self._detail}]})
        return items
    OpenAIModel._render = trailing
elif variant == "noimage":
    original_render = OpenAIModel._render

    def no_image(self, looks):
        for look in looks:
            look.photo = None
        return original_render(self, looks)
    OpenAIModel._render = no_image
elif variant == "lowdetail":
    model._detail = "low"
elif variant == "store":
    import openai
    real_create = model._client.responses.create

    async def create_store(**kw):
        kw["store"] = True
        kw.pop("include", None)
        return await real_create(**kw)
    model._client.responses.create = create_store
elif variant == "noreasoning":
    original_ask = OpenAIModel.ask

    async def ask_no_reasoning(self, instructions, looks, tools, effort, key):
        text, calls, output, u = await original_ask(self, instructions, looks, tools, effort, key)
        return text, calls, [o for o in output if o.type != "reasoning"], u
    OpenAIModel.ask = ask_no_reasoning


async def no_publish(build):
    pass
brain.publish_build = no_publish
brain.get_job_context = lambda: SimpleNamespace(room=SimpleNamespace(local_participant=replay.Participant()))
brain._jpeg = lambda frame, side: frame.jpeg

voice = replay.Voice()
tap = SimpleNamespace(latest=None, count=0, latest_at=time.monotonic())
b = Brain(voice, Build(guide=guide, run=rec.name + "-" + variant), tap, model, s["brain_effort"],
          s["brain_watch_side"], s["brain_watch_every"], call["language"])
usages = []
orig_ask = model.ask


async def spy(instructions, looks, tools, effort, key):
    r = await orig_ask(instructions, looks, tools, effort, key)
    usages.append(r[3])
    return r
model.ask = spy


async def main():
    for look in replay.looks(rec)[:6]:
        sent = look["sent"]
        voice.history.add(replay.chat_lines(sent))
        photo = (rec / sent["photo"]).read_bytes()
        tap.latest = SimpleNamespace(jpeg=photo, width=1080, height=1080)
        tap.count += 1
        tap.latest_at = time.monotonic()
        text, calls, kept = await b._look_once("watch", look["n"], s["brain_watch_side"], None, TOOLS)
        if variant == "photos":
            kept.kept_photo = photo
        await b._carry_out(kept, calls, "watch", look["n"])
        u = usages[-1]
        print(f"{variant:12} look {len(b._looks)}  in {u['in']:>6}  cached {u['cached']:>6}  out {u['out']:>4}")

asyncio.run(main())
