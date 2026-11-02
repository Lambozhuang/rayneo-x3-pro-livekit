"""The control experiment: one request sent twice, then the next look's request right after, cached tokens of each.

    backend/agent/.venv/Scripts/python eval/brain-thread-replay/cache_control.py <record dir> <look id> <next look id>
"""
import asyncio
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "eval" / "brain-thread-replay"))
import replay  # noqa: E402
from gpt.brain import TOOLS, Look, OpenAIModel, brain_instructions  # noqa: E402
from guide import load_guide  # noqa: E402

rec = Path(sys.argv[1])
first, second = sys.argv[2], sys.argv[3]
call = json.loads(open(rec / "events.jsonl", encoding="utf-8").readline())
s = call["settings"]
replay.load_key("openai")
guide = load_guide(root / "backend" / "agent" / "guides" / call["guide"] / "task.toml")
instructions = brain_instructions(guide, call["language"])
model = OpenAIModel(s["brain_model"], s["brain_detail"])
by_id = {l["id"]: l for l in replay.looks(rec)}
a, b = by_id[first], by_id[second]
# the first message carries every line said before the first look, as the brain's first look of a call does
lines = []
for look in replay.looks(rec):
    if look["id"] == first:
        break
    lines += [f"{'User' if role == 'user' else 'Assistant'}: {text}" for _, role, text in replay.chat_lines(look["sent"])]
look1 = Look(text="\n".join(lines) or "No one spoke.", photo=(rec / a["sent"]["photo"]).read_bytes())
key = rec.name + "-control"


async def send(looks, label):
    text, calls, output, u = await model.ask(instructions, looks, TOOLS, s["brain_effort"], key)
    print(f"{label:<44} in {u['in']:>5}  cached {u['cached']:>5}  out {u['out']:>4}")
    return calls, output


async def main():
    print("first message tokens: about", len(look1.text) // 4, "(", len(look1.text), "chars )")
    await send([look1], "request 1")
    calls, output = await send([look1], "request 1 again, identical")
    look1.photo, look1.output, look1.calls = None, output, calls
    for call_id, name, args in calls:
        look1.results[call_id] = "Unchanged: 3 of 5 steps were already recorded as done." if name == "set_progress" else "The assistant knows it."
    look2 = Look(text="\n".join(f"{'User' if r == 'user' else 'Assistant'}: {t}" for _, r, t in replay.chat_lines(b["sent"])) or "No one spoke.",
                 photo=(rec / b["sent"]["photo"]).read_bytes())
    await send([look1, look2], "request 2: photo 1 gone, look 2 and its photo added")

asyncio.run(main())
