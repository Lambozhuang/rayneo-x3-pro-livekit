"""The vision check: one camera frame, one step, one verdict.

GPT-Live hears; it does not see, and neither does the backend model it
delegates to. So the camera is judged here, by a separate stateless Responses
call: the frame taken when the check was asked for, the steps built so far, the
step to check, two rendered reference views of the finished model with that
step's brick highlighted, and an optional question from the wearer. The answer
is JSON with a fixed schema, and the code, not a model, moves the build on when
the state is `built` (tools.py). Nothing accumulates: every check starts from
nothing, so an old frame can never colour a new verdict.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import time
from dataclasses import dataclass

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
may be lying on a table or held in the builder's hands.

Steps already built (they should be visible, done as described):
{done}

The step to check:
{step}

Look only at the LEGO bricks relevant to this build (ignore the loose pile of
other bricks). The camera shifts colours: a brick may look lighter or a
different shade than named, so identify bricks by size and shape first and
treat colour names approximately. Count studs where it matters. Report:
- what_i_see: one sentence, where each relevant brick actually is;
- state: "built" if the step is done exactly as described; "not_built" if the
  brick is missing, wrong, misplaced or misoriented, or an earlier step is
  visibly wrong; "in_progress" only if the brick is clearly still being moved
  and is not attached yet; "unsure" only if the bricks are hidden or too small;
- problem: if not built, one short sentence saying what to change, else "";
- answer: {answer}"""

ANSWER_NONE = 'leave it empty ("").'
ANSWER_QUESTION = """the builder asks: "{question}" Answer that from the photo in one or two
  short spoken sentences, in {language}, still filling in the other fields."""

REFERENCE_NOTE = (
    "Reference: the finished model rendered from two angles, the brick of this step in colour, "
    "the others grey. The photo will not match the exact angle; use it to see where the brick belongs."
)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "what_i_see": {"type": "string"},
        "state": {"type": "string", "enum": ["built", "not_built", "in_progress", "unsure"]},
        "problem": {"type": "string"},
        "answer": {"type": "string"},
    },
    "required": ["what_i_see", "state", "problem", "answer"],
}


@dataclass(frozen=True)
class Verdict:
    state: str  # built | not_built | in_progress | unsure
    what_i_see: str
    problem: str
    answer: str
    seconds: float


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
    def __init__(self, client: AsyncOpenAI, model: str, effort: str, guide: Guide, tap: FrameTap, language: str) -> None:
        self._client = client
        self._model = model
        self._effort = effort
        self._guide = guide
        self._tap = tap
        self._language = language
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
        t0 = time.perf_counter()
        frame = await self._tap.next_frame(3.0)
        jpeg = await asyncio.to_thread(images.encode, frame, FRAME_ENCODE_OPTIONS)
        i = build.step
        self._tap.dump(jpeg, f"s{i + 1}-{'look' if question else 'check'}")

        steps = self._guide.steps
        done = "\n".join(f"  {k + 1}. {s.say}" for k, s in enumerate(steps[:i])) or "  (none yet)"
        answer = ANSWER_QUESTION.format(question=question, language=self._language) if question else ANSWER_NONE
        content: list[dict] = [{"type": "input_text", "text": PROMPT.format(done=done, step=f"  {i + 1}. {steps[i].say}", answer=answer)}]
        if refs := self._refs.get(i):
            content.append({"type": "input_text", "text": REFERENCE_NOTE})
            for view, png in refs:
                content.append({"type": "input_text", "text": f"[{view} view]"})
                content.append({"type": "input_image", "image_url": _data_url(png, "image/png"), "detail": "low"})
        content.append({"type": "input_text", "text": "The photo:"})
        content.append({"type": "input_image", "image_url": _data_url(jpeg, "image/jpeg"), "detail": "high"})

        resp = await self._client.responses.create(
            model=self._model,
            input=[{"role": "user", "content": content}],
            reasoning={"effort": self._effort},
            text={"format": {"type": "json_schema", "name": "verdict", "schema": SCHEMA, "strict": True}},
            timeout=CHECK_TIMEOUT,
        )
        data = json.loads(resp.output_text)
        seconds = time.perf_counter() - t0
        u = resp.usage
        logger.info(
            "check: step %d/%d %s=%s %.1fs in=%d out=%d reasoning=%d see=%s%s",
            i + 1, len(steps), "look" if question else "state", data["state"], seconds,
            u.input_tokens if u else -1, u.output_tokens if u else -1,
            (u.output_tokens_details.reasoning_tokens if u and u.output_tokens_details else 0),
            data["what_i_see"], f" problem={data['problem']}" if data["problem"] else "",
        )
        return Verdict(
            state=data["state"], what_i_see=data["what_i_see"], problem=data["problem"],
            answer=data["answer"], seconds=seconds,
        )
