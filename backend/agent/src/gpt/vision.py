"""The vision check: one camera frame, one step, one verdict.

GPT-Live hears; it does not see, and neither does the backend model it
delegates to. So the camera is judged here, by a separate stateless Responses
call: the frame taken when the check was asked for, the steps built so far, the
step to check, two rendered reference views of the finished model with that
step's brick highlighted, and an optional question from the wearer. The answer
is JSON with a fixed schema, and the code, not a model, moves the build on when
the state is `built` (tools.py). Nothing accumulates: every check starts from
nothing, so an old frame can never colour a new verdict.

What the 2026-09-22/23 frames taught the prompt (tmp/poc/vision_eval.py):
- Three states only. `in_progress` became the model's way out on frames of a
  finished assembly held in the hands ("not pressed in yet", which it could not
  see); now it has to say built or what is wrong.
- Orientation is judged between bricks, never against the camera. The wearer
  turns the assembly in their hands, and a house built with the yellow on the
  far row is still the house; "front = nearer the camera" only produced false
  fails and one false pass.
- Observations before the verdict: listing what is attached where, brick by
  brick, is cheaper than reasoning effort and steadier. Effort `low` and
  `medium` made both models more suspicious, not more right.
- Resolution is not the bottleneck: `original` and `high` cost the same
  tokens, and crops of the bricks at native resolution judged no better.
  `detail` stays configurable (OPENAI_CHECK_DETAIL) all the same.
- gpt-6-luna passes a reversed or turned roof it cannot see; gpt-6-sol never
  passed a wrong build in any run but fails or doubts more good ones.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import time
from dataclasses import dataclass, field

from livekit.agents.utils import images
from openai import AsyncOpenAI

from frames import FrameTap
from gpt.config import FRAME_ENCODE_OPTIONS
from guide import Build, Guide

logger = logging.getLogger("rayneo-agent.vision")

CHECK_TIMEOUT = 15.0

PROMPT = """You are checking one step of a small LEGO build from a photo taken by the
builder's glasses camera. The builder faces the bricks; "front" and "nearer to
you" mean the side nearer the camera, "back" the side further away. The bricks
may lie on the table or be held up in the builder's hands to show you: both are
normal. The assembly may be turned any way relative to the camera, so never
judge front and back off the camera: judge each brick by its relation to the
bricks placed before it, as the steps describe them (behind, beside, flush
with, overhanging), and take the earlier steps as correctly built unless the
photo clearly shows otherwise. The very first brick is right in any orientation.

Steps already built (they should be visible, done as described):
{done}

The step to check, what the photo must show:
{step}

Look only at the LEGO bricks relevant to this build (ignore any loose pile of
other bricks). The camera shifts colours: a brick may look lighter or a
different shade than named, so identify bricks by size and shape first and
treat colour names approximately. Count studs where it matters, and check which
way a brick faces against the reference. Report:
- observations: three to six short facts, one per line, each about one relevant
  brick: which brick it is (colour, studs), what it is attached to, which row or
  side of the base it sits on, and which way it faces (for a slope: on which
  side its studs are, and which way the slope runs down), read against the
  reference. State what you actually see, not what the step says.
- what_i_see: one sentence summarising the observations;
- state: "built" only if every observation matches what the step must show;
  "not_built" if the brick is missing, wrong, misplaced or misoriented, not
  attached where the step attaches it, or an earlier step is visibly wrong;
  "unsure" only if the bricks are hidden, out of frame or too small to tell;
- problem: if not built, one short sentence to the builder saying what to do
  with which brick (never empty then), else "". Plain words: no "base",
  "separate", "loose", "assembly".{answer}"""

# The `answer` field exists only when the wearer asked something: an extra field
# that is always empty measurably distracted the model from the verdict.
ANSWER_NONE = ""
ANSWER_QUESTION = """
- answer: the builder asks: "{question}" Answer that from the photo in one or two
  short spoken sentences, in {language}, still filling in the other fields."""

REFERENCE_NOTE = (
    "Reference: the finished model rendered from two angles, the brick of this step in colour, "
    "the others grey. The photo will not match the exact angle; use it to see where the brick belongs."
)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "observations": {"type": "array", "items": {"type": "string"}},
        "what_i_see": {"type": "string"},
        "state": {"type": "string", "enum": ["built", "not_built", "unsure"]},
        "problem": {"type": "string"},
    },
    "required": ["observations", "what_i_see", "state", "problem"],
}
SCHEMA_WITH_ANSWER = {
    **SCHEMA,
    "properties": {**SCHEMA["properties"], "answer": {"type": "string"}},
    "required": [*SCHEMA["required"], "answer"],
}


@dataclass(frozen=True)
class Verdict:
    state: str  # built | not_built | unsure
    what_i_see: str
    problem: str
    answer: str
    seconds: float
    tokens: tuple[int, int, int] = (0, 0, 0)  # in, out, reasoning
    observations: tuple[str, ...] = ()
    jpeg: bytes = field(default=b"", repr=False)  # the frame judged, for GPT_LOOK_IMAGE


def _data_url(data: bytes, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(data).decode()


def _render_references(guide: Guide) -> dict[int, list[tuple[str, bytes]]]:
    """Two PNG views per step, the step's brick highlighted. Runs in a worker
    thread: the GL context belongs to the thread that made it."""
    import numpy as np
    from PIL import Image

    from render import VIEWS, _Renderer

    assert guide.model is not None
    r = _Renderer(guide.model, 480, 360)
    out: dict[int, list[tuple[str, bytes]]] = {}
    try:
        for i, step in enumerate(guide.steps):
            node = next((n for n in r.nodes if n.startswith(step.node or "")), None)
            views = []
            for view in ("front-left", "top"):
                yaw, pitch = VIEWS[view]
                rgba = np.frombuffer(r.frame(np.radians(yaw), np.radians(pitch), node), "u1").reshape(360, 480, 4)
                buf = io.BytesIO()
                Image.fromarray(rgba[..., :3]).save(buf, "PNG")
                views.append((view, buf.getvalue()))
            out[i] = views
    finally:
        r.release()
    return out


class VisionCheck:
    def __init__(
        self, client: AsyncOpenAI, model: str, effort: str, guide: Guide, tap: FrameTap | None,
        language: str, detail: str = "high",
    ) -> None:
        self._client = client
        self._model = model
        self._effort = effort
        self._guide = guide
        self._tap = tap
        self._language = language
        self._detail = detail
        self._refs: dict[int, list[tuple[str, bytes]]] = {}

    async def prepare(self) -> None:
        """Render the reference views once per call, before the first check."""
        if self._guide.model is None:
            return
        try:
            self._refs = await asyncio.to_thread(_render_references, self._guide)
            logger.info("vision: reference views rendered for %d steps", len(self._refs))
        except Exception:
            logger.exception("vision: could not render reference views; checking without them")

    async def check(self, build: Build, question: str | None = None) -> Verdict:
        """Take the next camera frame and judge the current step (and answer
        `question`, if any). Raises asyncio.TimeoutError when no frame comes."""
        assert self._tap is not None
        t0 = time.perf_counter()
        frame = await self._tap.next_frame(3.0)
        jpeg = await asyncio.to_thread(images.encode, frame, FRAME_ENCODE_OPTIONS)
        i = build.step
        self._tap.dump(jpeg, f"s{i + 1}-{'look' if question else 'check'}")
        v = await self.judge(jpeg, i, question)
        v = Verdict(**{**v.__dict__, "seconds": time.perf_counter() - t0, "jpeg": jpeg})
        logger.info(
            "check: step %d/%d %s=%s %.1fs in=%d out=%d reasoning=%d see=%s%s",
            i + 1, len(self._guide.steps), "look" if question else "state", v.state, v.seconds,
            *v.tokens, v.what_i_see, f" problem={v.problem}" if v.problem else "",
        )
        for o in v.observations:
            logger.info("check:   - %s", o)
        return v

    async def judge(self, jpeg: bytes, i: int, question: str | None = None) -> Verdict:
        """Judge step `i` (0-based) from one JPEG. No camera, no log: the eval
        scripts call this on stored frames."""
        t0 = time.perf_counter()
        steps = self._guide.steps
        done = "\n".join(f"  {k + 1}. {s.check}" for k, s in enumerate(steps[:i])) or "  (none yet)"
        answer = ANSWER_QUESTION.format(question=question, language=self._language) if question else ANSWER_NONE
        content: list[dict] = [{"type": "input_text", "text": PROMPT.format(done=done, step=f"  {i + 1}. {steps[i].check}", answer=answer)}]
        if refs := self._refs.get(i):
            content.append({"type": "input_text", "text": REFERENCE_NOTE})
            for view, png in refs:
                content.append({"type": "input_text", "text": f"[{view} view]"})
                content.append({"type": "input_image", "image_url": _data_url(png, "image/png"), "detail": "low"})
        content.append({"type": "input_text", "text": "The photo:"})
        content.append({"type": "input_image", "image_url": _data_url(jpeg, "image/jpeg"), "detail": self._detail})

        resp = await self._client.responses.create(
            model=self._model,
            input=[{"role": "user", "content": content}],
            reasoning={"effort": self._effort},
            text={"format": {"type": "json_schema", "name": "verdict", "strict": True,
                             "schema": SCHEMA_WITH_ANSWER if question else SCHEMA}},
            timeout=CHECK_TIMEOUT,
        )
        data = json.loads(resp.output_text)
        u = resp.usage
        tokens = (
            u.input_tokens if u else 0, u.output_tokens if u else 0,
            u.output_tokens_details.reasoning_tokens if u and u.output_tokens_details else 0,
        )
        return Verdict(
            state=data["state"], what_i_see=data["what_i_see"], problem=data["problem"],
            answer=data.get("answer", ""), seconds=time.perf_counter() - t0, tokens=tokens,
            observations=tuple(data.get("observations", ())),
        )
