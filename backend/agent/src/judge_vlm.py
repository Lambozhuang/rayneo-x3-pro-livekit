"""The VLM judge: the same question as judge_cv.py, answered by a vision model. Fallback, not the default.

One stateless Responses call per frame: the plate cropped out of the frame
(green mask, 10 % margin, longest side 1024 px), and a plain-language text
about the current step from the task file: what is already on the plate (the
step names), what this step adds (`where`) and three or four facts a photo
must show (`checks`). The model describes what it sees at that place, answers
each fact y/n/?, and gives the four-way answer. ~2 s with gpt-6-sol and no
reasoning; 29/29 on the full-resolution rest frames of the recorded run, 28/29
at 1080p (eval/RESULTS.md, "VLM 路线"). Learned there: coordinates and
diagrams fail (the model echoes them), relational facts work, and fragile
wording ("level with", "directly above") causes false wrongs.

Selected with JUDGE=vlm; the model and its settings come from OPENAI_CHECK_*.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import time

from openai import AsyncOpenAI
from PIL import Image

from gate import plate_bbox
from guide import Guide
from judge_cv import ANSWERS, Verdict

logger = logging.getLogger("rayneo-agent.judge")

TIMEOUT = 6.0  # a stalled call is dropped; normal is ~2 s
SIDE = 1024    # longest side of the crop sent

SYSTEM = """You check one step of a LEGO build from a photo taken by the builder's glasses. The builder places flat bricks on a fixed green {n}x{n} baseplate that is never rotated. You get a plain-language description of what was already on the plate and of the brick this step adds, with a few facts about where it sits relative to the other bricks and the plate edges. No diagram, no coordinates.
Work in this order and report all of it:
1. seen: describe only what you actually see at the place where this step's brick belongs: what colours are there, how many rows of studs, what touches what, how ends line up. Do not repeat the description you were given; look.
2. checks: answer each listed fact with yes, no, or unsure, from the photo.
3. answer: correct if the brick is there and every fact is yes; wrong if the brick is there but any fact is no (wrong colour, wrong place, wrong orientation); not_placed if no such brick is on the plate yet (it may be in the builder's hand); cannot_see if the plate or that area is hidden, blurred or out of frame.
Be brief: seen is one sentence; no other prose.
Reply with JSON only: {{"seen": "...", "checks": "<one letter per fact, in order: y, n or ?>", "answer": "correct|wrong|not_placed|cannot_see", "reason": "<at most ten words>"}}"""


def step_text(guide: Guide, step: int) -> str:
    """The user text for step `step` (1-based)."""
    s = guide.steps[step - 1]
    before = guide.steps[:step - 1]
    lines = ["Already on the plate from earlier steps: " + "; ".join(x.name for x in before) + "."
             if before else "The plate is empty before this step."]
    lines.append(f"Step {step} adds {s.where}.")
    lines.append("Facts to check:")
    lines += [f"{i}. {c}" for i, c in enumerate(s.checks, 1)]
    return "\n".join(lines)


def crop_plate(img: Image.Image) -> bytes | None:
    box = plate_bbox(img)
    if box is None:
        return None
    crop = img.crop(box)
    crop.thumbnail((SIDE, SIDE))
    buf = io.BytesIO()
    crop.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def parse(text: str, checks: tuple[str, ...]) -> tuple[str, str]:
    """(answer, reason): the last JSON object in the reply; a wrong answer's reason is the first failed fact."""
    try:
        obj = json.loads(text[text.rindex("{"):text.rindex("}") + 1])
    except (ValueError, AttributeError):
        return "cannot_see", "unreadable answer from the vision model"
    answer = str(obj.get("answer", "")).strip().lower()
    if answer not in ANSWERS:
        return "cannot_see", "unreadable answer from the vision model"
    reason = str(obj.get("reason", ""))
    if answer == "wrong":
        letters = str(obj.get("checks", ""))
        for i, ch in enumerate(letters):
            if ch == "n" and i < len(checks):
                reason = checks[i]
                break
    return answer, reason


class VLMJudge:
    def __init__(self, client: AsyncOpenAI, guide: Guide, model: str, effort: str = "none", detail: str = "high") -> None:
        self._client = client
        self._guide = guide
        self._model = model
        self._effort = effort
        self._detail = detail
        self._system = SYSTEM.format(n=guide.plate)
        self.f = None  # no geometry to calibrate; here so the watch can log judges alike

    async def ajudge(self, img: Image.Image, step: int) -> Verdict:
        t0 = time.perf_counter()
        photo = crop_plate(img)
        if photo is None:
            return Verdict("cannot_see", "the plate is not in view", {}, time.perf_counter() - t0)
        content = [{"type": "input_text", "text": step_text(self._guide, step)},
                   {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(photo).decode(),
                    "detail": self._detail}]
        kw = {"reasoning": {"effort": self._effort}} if self._effort else {}
        resp = await self._client.responses.create(
            model=self._model, instructions=self._system, input=[{"role": "user", "content": content}],
            timeout=TIMEOUT, **kw,
        )
        answer, reason = parse(resp.output_text, self._guide.steps[step - 1].checks)
        u = resp.usage
        info = {"in": u.input_tokens if u else 0, "out": u.output_tokens if u else 0, "raw": resp.output_text[:300]}
        return Verdict(answer, reason, info, time.perf_counter() - t0)
