"""The eyes: one camera frame in, where the build stands out.

GPT-Live hears; it does not see. So a vision model looks at the camera for it,
in a separate stateless Responses call per frame: all the steps of the guide,
the frame, and two rendered views of what the build should look like at the
step the wearer is expected to be on. It answers with how many steps are
visibly complete and what, if anything, is wrong with the next one. watch.py
runs this in a loop and hands the result to GPT-Live as context; nothing here
decides anything.

Learned the hard way (2026-09-22 to 24): tell the model what to look for in
terms of the bricks placed before, never of the camera (the wearer turns the
assembly in their hands); make it list observations before it concludes; and
make sure the reference render actually shows the brick in question (a finished
model greyed out hid steps 1-3 under the roof, and every conclusion drawn from
those tests was void).
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import time
from dataclasses import dataclass

from openai import AsyncOpenAI

from guide import Guide

logger = logging.getLogger("rayneo-agent.vision")

CHECK_TIMEOUT = 15.0

PROMPT = """You are watching a small LEGO build through the builder's glasses camera and
reporting how far it has got. The bricks may lie on the table or be held up in
the builder's hands: both are normal. The assembly may be turned any way
relative to the camera, so never judge by "front" or "back" of the picture:
judge each brick by its relation to the bricks placed before it, as the steps
describe (along which row, beside, flush with, overhanging).

The steps, in order, each saying what the photo must show when it is done:
{steps}

{context}Look only at the bricks of this build; ignore any loose pile of other bricks,
and anything on screens. The camera shifts colours: identify bricks by size and
shape first and treat colour names approximately. Count studs where it
matters. Report:
- observations: three to six short facts, one per line, each about one brick
  of the build: which brick (colour, studs), what it is attached to, along
  which row or side, which way it faces (for a slope: where its studs are and
  which way it runs down). Say what you actually see, not what a step says.
- steps_done: the largest n such that steps 1 to n are all complete exactly
  as described (0 if the first brick is not in place). A brick placed wrongly
  does not count, and neither do the steps after it.
- what_i_see: one sentence: where the build stands.
- problem: if a brick for the next step is placed but wrongly (wrong row,
  sticking out, turned, wrong brick), one short sentence to the builder saying
  what to do with which brick, in plain words. Empty if nothing is placed
  wrongly, if the next brick is simply not there yet, or if the build is
  finished.
- visible: false if the build is out of frame or too small to judge (then
  keep steps_done as your best guess and leave problem empty)."""

CONTEXT = """What you knew a moment ago, from the previous frames (the two before this one
are attached first, smaller): {previous}{said}Keep that count unless this frame
clearly shows the build has changed; a hand in the way, a brick lifted up, or
a poor angle is not a change. If the build is hidden or out of frame, keep the
count and set visible to false.

"""

REFERENCE_NOTE = (
    "Reference: how the build should look once step {n} is done, rendered from two angles; "
    "only the bricks placed up to that step are shown. The photo will not match the exact angle."
)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "observations": {"type": "array", "items": {"type": "string"}},
        "steps_done": {"type": "integer"},
        "what_i_see": {"type": "string"},
        "problem": {"type": "string"},
        "visible": {"type": "boolean"},
    },
    "required": ["observations", "steps_done", "what_i_see", "problem", "visible"],
}


@dataclass(frozen=True)
class Sight:
    steps_done: int
    what_i_see: str
    problem: str
    visible: bool
    observations: tuple[str, ...]
    seconds: float
    tokens: tuple[int, int] = (0, 0)  # in, out


def _data_url(data: bytes, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(data).decode()


def render_references(guide: Guide) -> dict[int, list[tuple[str, bytes]]]:
    """Two PNG views per step (1-based key): the build as it should look once
    that step is done, later bricks absent. Runs in a worker thread: the GL
    context belongs to the thread that made it."""
    import numpy as np
    from PIL import Image

    from render import VIEWS, _Renderer

    assert guide.model is not None
    r = _Renderer(guide.model, 480, 360)
    out: dict[int, list[tuple[str, bytes]]] = {}
    try:
        for i, step in enumerate(guide.steps):
            node = next((n for n in r.nodes if n.startswith(step.node or "")), None)
            upto = {n for k in range(i + 1) for n in r.nodes if n.startswith(guide.steps[k].node or "")}
            views = []
            for view in ("front-left", "top"):
                yaw, pitch = VIEWS[view]
                rgba = np.frombuffer(r.frame(np.radians(yaw), np.radians(pitch), node, only=upto), "u1").reshape(360, 480, 4)
                buf = io.BytesIO()
                Image.fromarray(rgba[..., :3]).save(buf, "PNG")
                views.append((view, buf.getvalue()))
            out[i + 1] = views
    finally:
        r.release()
    return out


class Eyes:
    def __init__(self, client: AsyncOpenAI, model: str, effort: str, guide: Guide, detail: str = "high") -> None:
        self._client = client
        self._model = model
        self._effort = effort
        self._guide = guide
        self._detail = detail
        self._refs: dict[int, list[tuple[str, bytes]]] = {}
        self._steps_text = "\n".join(f"  {i}. {s.check}" for i, s in enumerate(guide.steps, 1))

    async def prepare(self) -> None:
        if self._guide.model is None:
            return
        try:
            self._refs = await asyncio.to_thread(render_references, self._guide)
            logger.info("vision: reference views rendered for %d steps", len(self._refs))
        except Exception:
            logger.exception("vision: could not render reference views; looking without them")

    async def look(
        self, jpeg: bytes, expected_step: int, previous: Sight | None = None,
        said: list[str] = (), earlier: list[bytes] = (),
    ) -> Sight:
        """Judge one frame. `expected_step` (1-based) picks the reference
        render: the step the wearer is thought to be working on. `previous` is
        the last verdict, `said` the wearer's recent words, `earlier` the last
        frames before this one (small): the memory this stateless call gets."""
        t0 = time.perf_counter()
        n = max(1, min(expected_step, len(self._guide.steps)))
        context = ""
        if previous is not None:
            prev = f"{previous.steps_done} of {len(self._guide.steps)} steps done; {previous.what_i_see}"
            if previous.problem:
                prev += f" Problem then: {previous.problem}"
            quotes = " ".join(f'The builder just said: "{q}".' for q in said)
            context = CONTEXT.format(previous=prev, said=(" " + quotes + " ") if quotes else " ")
        content: list[dict] = [{"type": "input_text", "text": PROMPT.format(steps=self._steps_text, context=context)}]
        for k, small in enumerate(earlier):
            content.append({"type": "input_text", "text": f"[earlier frame {k + 1}, for continuity]"})
            content.append({"type": "input_image", "image_url": _data_url(small, "image/jpeg"), "detail": "low"})
        if refs := self._refs.get(n):
            content.append({"type": "input_text", "text": REFERENCE_NOTE.format(n=n)})
            for view, png in refs:
                content.append({"type": "input_text", "text": f"[{view} view]"})
                content.append({"type": "input_image", "image_url": _data_url(png, "image/png"), "detail": "low"})
        content.append({"type": "input_text", "text": "The photo:"})
        content.append({"type": "input_image", "image_url": _data_url(jpeg, "image/jpeg"), "detail": self._detail})
        resp = await self._client.responses.create(
            model=self._model,
            input=[{"role": "user", "content": content}],
            reasoning={"effort": self._effort},
            text={"format": {"type": "json_schema", "name": "sight", "strict": True, "schema": SCHEMA}},
            timeout=CHECK_TIMEOUT,
        )
        d, _ = json.JSONDecoder().raw_decode(resp.output_text)  # the model has appended stray text once
        u = resp.usage
        return Sight(
            steps_done=max(0, min(int(d["steps_done"]), len(self._guide.steps))),
            what_i_see=d["what_i_see"], problem=d["problem"], visible=bool(d["visible"]),
            observations=tuple(d.get("observations", ())), seconds=time.perf_counter() - t0,
            tokens=(u.input_tokens if u else 0, u.output_tokens if u else 0),
        )
