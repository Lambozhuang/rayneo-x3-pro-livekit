"""Asks the model to describe the plate in every frame of one condition, and keeps each reply.

    uv run python probe.py <pictures> <thinking> [frame id ...] [--model=<id>] [--base-url=<url>]

`pictures` is a directory under out/ with one JPEG per frame, as pick_frames.py and encode.py write them (sq768,
v2000-720, ...). `thinking` is `none` (no thinking, as the routine look runs) or an effort (`low`, as the hand-over
runs). Frame ids restrict the run; by default every frame in out/frames.csv is asked. Replies land in
out/replies/<pictures>-<thinking>/<id>.json, one per frame, with the parsed object, the raw text, the token counts
and the timing; a frame whose reply exists is not asked again, so a stopped run can be continued.

`--model` asks another model the same question, to compare it with the brain's: a `claude-*` id goes to Anthropic as
below; any other id goes to an OpenAI-compatible chat completion, at OpenAI with OPENAI_API_KEY from backend/.env, or at
`--base-url` (an LM Studio server, say, one call at a time) with no key, the same prompt as the system message, the
photo as a data URL, the reply as a strict JSON schema, `thinking` as the reasoning effort. Its replies land in
out/replies/<pictures>-<thinking>-<model's last path part>/ so the brain's own stay where they are.

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
from openai import AsyncOpenAI

MODEL = "claude-sonnet-5-5"  # the brain's model, asked unless --model says another
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


def load_key(name: str) -> None:
    env = here.parent.parent / "backend" / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            os.environ[name] = line.split("=", 1)[1].strip()
            return
    sys.exit(f"no {name} in {env}")


class Probe:
    def __init__(self, model: str, thinking: str) -> None:
        self.model = model
        load_key("ANTHROPIC_API_KEY")
        self._client = AsyncAnthropic()
        # Sonnet 5.5 rejects {"type": "disabled"} and names between_tools as its way of not thinking; with no tools
        # in the call that is simply no thinking
        self._kw = {"thinking": {"type": "between_tools"}} if thinking == "none" else {
            "thinking": {"type": "adaptive"}, "output_config": {"effort": thinking}}
        self._kw.setdefault("output_config", {})["format"] = {"type": "json_schema", "schema": SCHEMA}

    async def ask(self, photo: bytes) -> dict:
        t0, ttft = time.perf_counter(), None
        async with self._client.messages.stream(
            model=self.model, max_tokens=8192, **self._kw,
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


class OpenAIProbe:
    """The same question through an OpenAI-compatible chat completion: OpenAI's own models, or a local server."""

    def __init__(self, model: str, thinking: str, base_url: str | None) -> None:
        self.model = model
        if base_url:
            self._client = AsyncOpenAI(base_url=base_url, api_key="none")
        else:
            load_key("OPENAI_API_KEY")
            self._client = AsyncOpenAI()
        self._effort = thinking  # "none" asks for no reasoning; an effort asks for that much

    async def ask(self, photo: bytes) -> dict:
        t0, ttft, chunks, usage, stop = time.perf_counter(), None, [], None, None
        async with await self._client.chat.completions.create(
            model=self.model, stream=True, stream_options={"include_usage": True}, max_completion_tokens=8192,
            reasoning_effort=self._effort,
            response_format={"type": "json_schema", "json_schema": {"name": "plate", "schema": SCHEMA, "strict": True}},
            messages=[{"role": "system", "content": PROMPT},
                      {"role": "user", "content": [
                          {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(photo).decode()}},
                          {"type": "text", "text": ASK}]}],
        ) as stream:
            async for ev in stream:
                if ev.usage:
                    usage = ev.usage
                if ev.choices:
                    if ev.choices[0].finish_reason:
                        stop = ev.choices[0].finish_reason
                    if ev.choices[0].delta and ev.choices[0].delta.content:
                        if ttft is None:
                            ttft = time.perf_counter() - t0
                        chunks.append(ev.choices[0].delta.content)
        text = "".join(chunks).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        details = getattr(usage, "completion_tokens_details", None) if usage else None
        prompt = getattr(usage, "prompt_tokens_details", None) if usage else None
        return {
            "parsed": parsed, "text": text,
            "model_ms": round((time.perf_counter() - t0) * 1000),
            "ttft_ms": round(ttft * 1000) if ttft else None,
            "in": usage.prompt_tokens if usage else None, "out": usage.completion_tokens if usage else None,
            "cached": (getattr(prompt, "cached_tokens", 0) or 0) if prompt else 0,
            "thinking": getattr(details, "reasoning_tokens", None) if details else None,
            "stop": stop, "thinking_mode": {"reasoning_effort": self._effort},
        }


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--"))
    pictures, thinking, ids = args[0], args[1], args[2:]
    model, base_url = opts.get("model", MODEL), opts.get("base-url")
    frames = [r["id"] for r in csv.DictReader(open(out / "frames.csv"))]
    if ids:
        frames = [f for f in frames if f in ids]
    cond = f"{pictures}-{thinking}" + ("" if model == MODEL else f"-{model.rsplit('/', 1)[-1]}")
    dest = out / "replies" / cond
    dest.mkdir(parents=True, exist_ok=True)
    probe = Probe(model, thinking) if model.startswith("claude-") else OpenAIProbe(model, thinking, base_url)
    gate = asyncio.Semaphore(1 if base_url else PARALLEL)  # a local server answers one call at a time

    async def one(fid: str) -> None:
        target = dest / f"{fid}.json"
        if target.exists():
            return
        photo = (out / pictures / f"{fid}.jpg").read_bytes()
        async with gate:
            r = await probe.ask(photo)
        r.update({"id": fid, "pictures": pictures, "photo_kb": len(photo) // 1024, "model": model})
        target.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{fid} {r['model_ms']} ms, ttft {r['ttft_ms']} ms, in {r['in']} out {r['out']}"
              + (f" thinking {r['thinking']}" if r["thinking"] else "") + ("" if r["parsed"] is not None else " NOT JSON"))

    await asyncio.gather(*(one(f) for f in frames))
    print(f"{len(list(dest.glob('*.json')))} replies in {dest.relative_to(here)}")


if __name__ == "__main__":
    asyncio.run(main())
