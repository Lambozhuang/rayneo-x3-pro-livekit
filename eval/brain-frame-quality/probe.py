"""Asks the model to describe the plate in every frame of one condition, and keeps each reply.

    uv run python probe.py <pictures> <thinking> [frame id ...]

`pictures` is a directory under out/ with one JPEG per frame, as pick_frames.py and encode.py write them (sq768,
v2000-720, ...). `thinking` is `none` (no thinking, as the routine look runs) or an effort (`low`, as the hand-over
runs). Frame ids restrict the run; by default every frame in out/frames.csv is asked. Replies land in
out/replies/<pictures>-<thinking>/<id>.json, one per frame, with the parsed object, the raw text, the token counts
and the timing; a frame whose reply exists is not asked again, so a stopped run can be continued.

The model and the way it is called are the brain's (backend/agent/src/gpt/brain.py AnthropicModel): the same
model, the photo first and the text after it, the instructions as a cached system prompt, the reply streamed to
time the first output. Sonnet 5.5 rejects thinking "disabled" and takes "between_tools", which is what the brain
runs its routine looks with. The reply is one JSON object in the shape of SCHEMA (`output_config.format`), the same
shape as labels.toml, so score.py compares fields and parses nothing; eval/structured-output-replay/ checked that
this form of answer leaves the model's judgements unchanged. PROMPT is the one fixed probe of the study: no step
list, no word of what is built, so the model has to read the plate rather than recognise it (README).

The key is ANTHROPIC_API_KEY from backend/.env.
"""

import asyncio
import base64
import csv
import json
import os
import sys
import time
from pathlib import Path

from anthropic import AsyncAnthropic

MODEL = "claude-sonnet-5-5"
PARALLEL = 8

PROMPT = """You look through the camera of a pair of AR glasses at a LEGO baseplate on the table in front of the wearer. Describe the bricks on the plate from this one photo, exactly as it shows them, so that someone who cannot see could check a build against it.

Directions are on the plate as the wearer sees it, like a picture lying in front of them: up is toward the far edge, down toward the near edge, left and right are theirs. Every brick lies flat: vertical means its long side runs up and down, horizontal left and right.

Answer with one JSON object. "bricks" has one entry per brick on the plate: its colour; its size as studs wide by studs long, counted in the photo, such as 1x6; whether it lies vertical or horizontal; and its position relative to the bricks it touches: which brick, on which of that brick's sides, which edges are level, and by how many studs it is offset or sticks out, or for a brick touching nothing, the region of the plate (such as upper left) and how many empty rows and columns lie between it and the plate's edges. A brick in a hand or off the plate is not on the plate and gets no entry. If the plate holds no brick, "bricks" is empty.
Write only what the photo shows. When the photo does not let you read a brick's size, its orientation or its position, because a hand covers it or it is too blurred or small, write "can't tell" in that field instead of a guess; a brick wholly under a hand gets no entry.
"hands" says whether a hand is on or over the plate, what it hides, anything you could not make out, and any brick held in a hand or lying off the plate."""

ASK = "Describe the plate."

UNREAD = "can't tell"
SCHEMA = {
    "type": "object",
    "properties": {
        "bricks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "colour": {"type": "string", "description": "the brick's colour, such as white, tan, red, dark grey"},
                    "size": {"type": "string", "description": f"studs wide x studs long, such as 2x4, or \"{UNREAD}\""},
                    "orientation": {"type": "string", "enum": ["vertical", "horizontal", UNREAD]},
                    "position": {"type": "string", "description": f"where it sits, in words, or \"{UNREAD}\""},
                },
                "required": ["colour", "size", "orientation", "position"],
                "additionalProperties": False,
            },
        },
        "hands": {"type": "string"},
    },
    "required": ["bricks", "hands"],
    "additionalProperties": False,
}

here = Path(__file__).resolve().parent
out = here / "out"


def load_key() -> None:
    env = here.parent.parent / "backend" / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip()
            return
    sys.exit(f"no ANTHROPIC_API_KEY in {env}")


class Probe:
    def __init__(self, thinking: str) -> None:
        self._client = AsyncAnthropic()
        # Sonnet 5.5 rejects {"type": "disabled"} and names between_tools as its way of not thinking; with no tools
        # in the call that is simply no thinking
        self._kw = {"thinking": {"type": "between_tools"}} if thinking == "none" else {
            "thinking": {"type": "adaptive"}, "output_config": {"effort": thinking}}
        self._kw.setdefault("output_config", {})["format"] = {"type": "json_schema", "schema": SCHEMA}

    async def ask(self, photo: bytes) -> dict:
        t0, ttft = time.perf_counter(), None
        async with self._client.messages.stream(
            model=MODEL, max_tokens=8192, **self._kw,
            system=[{"type": "text", "text": PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": base64.b64encode(photo).decode()}},
                {"type": "text", "text": ASK}]}],
        ) as stream:
            async for event in stream:
                if ttft is None and event.type == "content_block_start":
                    ttft = time.perf_counter() - t0
            resp = await stream.get_final_message()
        text = " ".join(b.text for b in resp.content if b.type == "text").strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        u = resp.usage
        details = getattr(u, "output_tokens_details", None)
        return {
            "parsed": parsed, "text": text,
            "model_ms": round((time.perf_counter() - t0) * 1000),
            "ttft_ms": round(ttft * 1000) if ttft else None,
            "in": u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0),
            "out": u.output_tokens, "cached": u.cache_read_input_tokens or 0,
            "thinking": getattr(details, "thinking_tokens", None) if details is not None else None,
            "stop": resp.stop_reason, "thinking_mode": self._kw["thinking"],
        }


async def main() -> None:
    pictures, thinking, ids = sys.argv[1], sys.argv[2], sys.argv[3:]
    load_key()
    frames = [r["id"] for r in csv.DictReader(open(out / "frames.csv"))]
    if ids:
        frames = [f for f in frames if f in ids]
    dest = out / "replies" / f"{pictures}-{thinking}"
    dest.mkdir(parents=True, exist_ok=True)
    probe = Probe(thinking)
    gate = asyncio.Semaphore(PARALLEL)

    async def one(fid: str) -> None:
        target = dest / f"{fid}.json"
        if target.exists():
            return
        photo = (out / pictures / f"{fid}.jpg").read_bytes()
        async with gate:
            r = await probe.ask(photo)
        r.update({"id": fid, "pictures": pictures, "photo_kb": len(photo) // 1024, "model": MODEL})
        target.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{fid} {r['model_ms']} ms, ttft {r['ttft_ms']} ms, in {r['in']} out {r['out']}"
              + (f" thinking {r['thinking']}" if r["thinking"] else "") + ("" if r["parsed"] is not None else " NOT JSON"))

    await asyncio.gather(*(one(f) for f in frames))
    print(f"{len(list(dest.glob('*.json')))} replies in {dest.relative_to(here)}")


if __name__ == "__main__":
    asyncio.run(main())
