"""Replays a recorded call's looks through the brain as it is now, one conversation of its own, against the real model.

    backend/agent/.venv/Scripts/python eval/brain-thread-replay/replay.py <record dir> [first look id] [last look id]

The brain's code is run as it is (backend/agent/src/gpt/brain.py), not copied: the record's photos and the lines
the user and the assistant said are fed to it look by look, in the record's order, and every request goes to the
model named in the record's settings at the record's effort. What is identical to the live call: the photos (the
bottom square as it was sent), the lines said and when they became known, the delegations and the words that came
with them, the tools. What differs: the model is the one of today's code with today's prompt and conversation,
not the one that ran; nothing goes to a voice or to glasses (the appends and the picture bytes are written to the
output instead); and there is no clock, so a reply's time is the model's own.

Look ids are `w<n>` for a routine look and `n<n>` for a hand-over, as the record numbers them. With a first look
given, the replay starts there: the conversation's first message then carries every line said up to that look, as
the brain's first look of a call does, and the record's progress at that point is set before it. With a last look
given, the replay stops after it.

Each look lands in out/<id>.json: the message sent (its text; the photo is the record's file), the reply, the tool
calls and their results, what would have gone to the voice, the time the look took, the progress before and after.
out/transcript.md is the whole replay readable in order, out/summary.txt puts the replayed progress beside the
record's, and the brain's own record of the replay (out/<time>-<room>/events.jsonl, as runlog.py writes it in a
call) has every request's tokens, cached tokens and model time, which is where the conversation's growth is read.

The key is OPENAI_API_KEY (or ANTHROPIC_API_KEY) from backend/.env.
"""

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace

here = Path(__file__).resolve().parent
root = here.parent.parent
sys.path.insert(0, str(root / "backend" / "agent" / "src"))

from gpt import brain  # noqa: E402
from gpt.brain import TOOLS, Brain, make_model  # noqa: E402
from guide import Build, load_guide  # noqa: E402
from runlog import RunLog  # noqa: E402

out = here / "out"

LINE = re.compile(r"^\[(\d+):(\d\d)\] (wearer|voice): (.*)$")  # records before 2026-10-29: the whole call so far
LABEL = {"User: ": "user", "Assistant: ": "assistant"}  # records from 2026-10-29: the lines since the look before


def load_key(provider: str) -> None:
    name = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
    env = root / "backend" / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith(name + "="):
            os.environ[name] = line.split("=", 1)[1].strip()
            return
    sys.exit(f"no {name} in {env}")


def looks(rec: Path) -> list[dict]:
    """Every answered look of the record with its photo, as {id, kind, n, sent, back}, in call order."""
    ev = [json.loads(line) for line in open(rec / "events.jsonl", encoding="utf-8")]
    found: dict[str, dict] = {}
    for e in ev:
        if e["kind"] in ("watch_sent", "look_sent"):
            k = "w" if e["kind"] == "watch_sent" else "n"
            found[f"{k}{e[k]}"] = {"id": f"{k}{e[k]}", "kind": "watch" if k == "w" else "look", "n": e[k], "sent": e,
                                   "back": None}
        elif e["kind"] in ("watch_back", "look_back"):
            k = "w" if e["kind"] == "watch_back" else "n"
            found[f"{k}{e[k]}"]["back"] = e
    return [v for v in found.values() if v["back"] is not None and v["sent"].get("photo")]


def chat_lines(sent: dict) -> list[tuple[str, str, str]]:
    """The user's and the assistant's lines a look's record carries, as (key, role, text). A record before
    2026-10-29 has the whole call so far with a time on every line, the brain's own lines among them, which are
    left out since the replayed brain writes its own; the time is the key, so a line already added is known. A
    record from 2026-10-29 has the lines said since the look before, labelled, each new, and the key is the look's
    own id with the line's number."""
    lines = []
    if "said" in sent:
        for raw in sent["said"].splitlines():
            m = LINE.match(raw)
            if m:
                lines.append((f"{m[1]}:{m[2]}", "user" if m[3] == "wearer" else "assistant", m[4]))
        return lines
    k = "w" if "w" in sent else "n"
    for i, raw in enumerate(sent["lines"].splitlines()):
        for label, role in LABEL.items():
            if raw.startswith(label):
                lines.append((f"{k}{sent[k]}.{i}", role, raw[len(label):]))
    return lines


class History:
    """A chat history as the brain reads it from the session: items with type, role, id and text, appended as the
    record's lines become known."""

    def __init__(self) -> None:
        self.items: list = []
        self._known: set[tuple[str, str, str]] = set()

    def add(self, lines: list[tuple[str, str, str]]) -> None:
        for line in lines:
            if line in self._known:
                continue
            self._known.add(line)
            self.items.append(SimpleNamespace(type="message", role=line[1], id=f"i{len(self.items)}", text_content=line[2]))


class Voice:
    """Stands in for GPT-Live: keeps what the brain appends."""

    def __init__(self) -> None:
        self.agent_state = "listening"
        self.appended: list[tuple[str, str]] = []
        self.current_agent = SimpleNamespace(duplex_session=self)
        self.history = History()

    def append_thinking(self, text: str) -> None:
        self.appended.append(("thinking", text))

    def append_commentary(self, text: str, delegation_id: str | None = None) -> None:
        self.appended.append(("commentary", text))


class Writer:
    async def write(self, data: bytes) -> None:
        pass

    async def aclose(self) -> None:
        pass


class Participant:
    async def stream_bytes(self, name, total_size, mime_type, topic):
        return Writer()

    async def set_attributes(self, attributes) -> None:
        pass


async def main() -> None:
    rec = Path(sys.argv[1])
    first = sys.argv[2] if len(sys.argv) > 2 else None
    last = sys.argv[3] if len(sys.argv) > 3 else None
    call = json.loads(open(rec / "events.jsonl", encoding="utf-8").readline())
    settings = call["settings"]
    load_key(settings["brain_provider"])
    guide = load_guide(root / "backend" / "agent" / "guides" / call["guide"] / "task.toml")
    model = make_model(settings["brain_provider"], settings["brain_model"], settings["brain_detail"])

    # nothing leaves this process: no room, no glasses, no voice
    async def no_publish(build) -> None:
        pass
    brain.publish_build = no_publish
    brain.get_job_context = lambda: SimpleNamespace(room=SimpleNamespace(local_participant=Participant()))
    brain._jpeg = lambda frame, side: frame.jpeg

    voice = Voice()
    tap = SimpleNamespace(latest=None, count=0, latest_at=time.monotonic())
    build = Build(guide=guide, run=rec.name)
    out.mkdir(exist_ok=True)
    # the brain's own record of the replay (out/<time>-<room>/events.jsonl): every request's tokens and timing
    b = Brain(voice, build, tap, model, settings["brain_effort"], settings["brain_side"], settings["brain_watch_side"],
              settings["brain_watch_every"], call["language"], record=RunLog(str(out), rec.name))

    todo = looks(rec)
    ids = [l["id"] for l in todo]
    start = ids.index(first) if first else 0
    stop = ids.index(last) + 1 if last else len(todo)
    transcript = []
    summary = [f"{'look':<6}{'record':>8}{'replay':>8}  reply"]
    before = todo[start]["sent"]
    if start:
        # the record's progress at the first replayed look, and every line said before it
        build.set_step(before["step"] - 1)
        for earlier in todo[:start]:
            voice.history.add(chat_lines(earlier["sent"]))
    print(f"replaying {len(todo[start:stop])} looks of {rec.name} with {settings['brain_model']} at effort "
          f"{settings['brain_effort']}, from {ids[start]} to {ids[stop - 1]}")
    for look in todo[start:stop]:
        s = look["sent"]
        voice.history.add(chat_lines(s))  # a delegation's words come as its pending transcript below
        photo = (rec / s["photo"]).read_bytes()
        tap.latest = SimpleNamespace(jpeg=photo, width=1080, height=1080)
        tap.count += 1
        tap.latest_at = time.monotonic()
        voice.appended = []
        step_before = build.step
        t0 = time.perf_counter()
        if look["kind"] == "watch":
            text, calls, kept = await b._look_once("watch", look["n"], settings["brain_watch_side"], None, TOOLS)
            speak = await b._carry_out(kept, calls, "watch", look["n"])  # a tell appends to the stand-in voice
            if speak:
                voice.append_commentary(" ".join(speak))
        else:
            text, calls, kept = await b._look_once("look", look["n"], settings["brain_side"], s.get("words") or "",
                                                   TOOLS)
            parts = [f"Camera: {text}"] if text else []
            parts += await b._carry_out(kept, calls, "look", look["n"])
            voice.append_commentary(" ".join(parts) or "Camera: nothing to add.", "d")
        ms = round((time.perf_counter() - t0) * 1000)
        record_progress = look["back"].get("progress")
        replay_progress = next((a.get("done") for _, c, a in calls if c == "set_progress"), None)
        r = {"id": look["id"], "kind": look["kind"], "message": kept.text, "photo": s["photo"], "reply": text,
             "calls": [[c, a] for _, c, a in calls], "results": list(kept.results.values()),
             "to_voice": voice.appended, "ms": ms, "looks": len(b._looks),
             "step_before": step_before, "step_after": build.step,
             "record": {"reply": look["back"]["reply"], "calls": look["back"]["calls"], "progress": record_progress}}
        (out / f"{look['id']}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        transcript.append(f"## {look['id']} ({look['kind']}, {ms} ms, look {len(b._looks)} of the conversation)\n\n"
                          f"user:\n{kept.text}\n\nassistant: {text}\n"
                          + "".join(f"  call {c}({json.dumps(a)}) -> {kept.results.get(i, '?')}\n" for i, c, a in calls)
                          + "".join(f"  {k}: {v}\n" for k, v in voice.appended) + "\n")
        summary.append(f"{look['id']:<6}{str(record_progress or '-'):>8}{str(replay_progress if replay_progress is not None else '-'):>8}"
                       f"  {text[:90]}")
        print(summary[-1], f"| {ms} ms")
        (out / "transcript.md").write_text("\n".join(transcript), encoding="utf-8")
        (out / "summary.txt").write_text("\n".join(summary), encoding="utf-8")
    print(f"written to {out.relative_to(root)}")


if __name__ == "__main__":
    asyncio.run(main())
