"""Replays every look of a recorded call with the brain's exact input, asking for one JSON object instead of tool calls.

    uv run python replay.py <record dir> [look id ...]

Look ids are `w<n>` for a routine look and `n<n>` for a hand-over, as the record numbers them. Each reply lands in
out/<id>.json with the parsed object, the raw text, the timing and the token counts; a look whose reply exists is
not sent again.

What is identical to the live call: the model, the system prompt (brain.txt), the three text parts after the photo
(the call so far, the progress line, the words), the photo as it was sent, and the thinking setting (between_tools
for a routine look, adaptive at effort low for a hand-over). What differs: no tools; instead `output_config.format`
with SCHEMA, whose fields are the three tools' arguments plus the reply text, and one paragraph appended to the
system prompt that says so.

The key is ANTHROPIC_API_KEY from backend/.env.
"""

import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

from anthropic import AsyncAnthropic

MODEL = "claude-sonnet-5-5"
PARALLEL = 16

here = Path(__file__).resolve().parent
out = here / "out"


def load_key() -> None:
    env = here.parent.parent / "backend" / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip()
            return
    sys.exit(f"no ANTHROPIC_API_KEY in {env}")


def schema(tools: list) -> dict:
    """One object with a field per tool, carrying the tool's own description and argument schema, plus the reply."""
    by = {t["name"]: t for t in tools}
    props = {
        "reply": {"type": "string", "description": "What you would have written as your reply: for a request, the "
                  "answer; for a routine look, the one word nothing when there is nothing to note, else your reasons."},
    }
    for name in ("set_progress", "note", "say"):
        if name not in by:
            continue
        desc, params = by[name]["description"], by[name]["input_schema"]
        if name == "set_progress":
            props[name] = {"anyOf": [params, {"type": "null"}], "description": desc + " Null when you would not call it."}
        else:
            props[name] = {"type": "array", "items": params, "description": desc + " Empty when you would not call it."}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


APPENDIX = """

Output format for this run: instead of calling tools, answer with one JSON object. Its fields are the tools, each with the arguments you would have given it: set_progress (or null when you would not call it), note and say as lists (empty when you would not call them), and reply, the text you would have written. Calling a tool means filling its field; calling no tool means leaving it null or empty."""


def looks(rec: Path) -> list[dict]:
    """Every look of the record as {id, kind, sent, back}, in call order."""
    ev = [json.loads(l) for l in open(rec / "events.jsonl", encoding="utf-8")]
    sent = {}
    for e in ev:
        if e["kind"] in ("watch_sent", "look_sent"):
            k = "w" if e["kind"] == "watch_sent" else "n"
            sent[f"{k}{e[k]}"] = {"id": f"{k}{e[k]}", "kind": "watch" if k == "w" else "look", "sent": e, "back": None}
        elif e["kind"] in ("watch_back", "look_back"):
            k = "w" if e["kind"] == "watch_back" else "n"
            sent[f"{k}{e[k]}"]["back"] = e
    return [l for l in sent.values() if l["back"] is not None and l["sent"].get("photo")]


async def main() -> None:
    rec = Path(sys.argv[1])
    only = set(sys.argv[2:])
    load_key()
    instructions = (rec / "brain.txt").read_text(encoding="utf-8") + APPENDIX
    tools = json.load(open(rec / "brain-tools.json", encoding="utf-8"))
    formats = {k: {"type": "json_schema", "schema": schema(tools[k])} for k in ("delegation", "watch")}
    client = AsyncAnthropic()
    gate = asyncio.Semaphore(PARALLEL)
    out.mkdir(exist_ok=True)

    async def one(look: dict) -> None:
        target = out / f"{look['id']}.json"
        if target.exists():
            return
        s = look["sent"]
        photo = (rec / s["photo"]).read_bytes()
        texts = [f"The photo above was taken just now.\n<call>\n{s['said']}\n</call>", s["notice"], s["words"]]
        if look["kind"] == "watch":
            kw = {"thinking": {"type": "between_tools"}}
            fmt = formats["watch"]
        else:
            kw = {"thinking": {"type": "adaptive"}, "output_config": {"effort": "low"}}
            fmt = formats["delegation"]
        kw.setdefault("output_config", {})["format"] = fmt
        t0 = time.perf_counter()
        async with gate:
            async with client.messages.stream(
                model=MODEL, max_tokens=4096, **kw,
                system=[{"type": "text", "text": instructions, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                 "data": base64.b64encode(photo).decode()}}] + [
                    {"type": "text", "text": t} for t in texts]}],
            ) as stream:
                resp = await stream.get_final_message()
        text = " ".join(b.text for b in resp.content if b.type == "text").strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        u = resp.usage
        details = getattr(u, "output_tokens_details", None)
        r = {"id": look["id"], "kind": look["kind"], "parsed": parsed, "text": text,
             "model_ms": round((time.perf_counter() - t0) * 1000),
             "in": u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0),
             "out": u.output_tokens, "cached": u.cache_read_input_tokens or 0,
             "thinking": getattr(details, "thinking_tokens", None) if details is not None else None,
             "stop": resp.stop_reason, "model": MODEL}
        target.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{look['id']} {r['model_ms']} ms, out {r['out']}, {'ok' if parsed is not None else 'NOT JSON'}")

    todo = [l for l in looks(rec) if not only or l["id"] in only]
    await asyncio.gather(*(one(l) for l in todo))
    print(f"{len(list(out.glob('*.json')))} replies in {out.relative_to(here)}")


if __name__ == "__main__":
    asyncio.run(main())
