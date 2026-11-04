"""The quick look: a small, fast vision model that answers fixed questions about the newest camera frame about once
a second, so that the two moments a human instructor answers in half a second, "this one?" and "done", get an
answer within a second or two instead of waiting for the brain's next full look.

OpenAI's Decisions API (BRAIN_QUICK_MODEL, gpt-6-luna) takes the photo and returns typed answers only, a
probability for a yes-or-no question and a choice with its confidence for a pick from a list, in about 0.4 s
(eval/brain-decisions/). It writes no words and calls no tools, so it cannot phrase a correction or answer a
question; it reads the state: is a hand on the plate, which brick is in the hand, how many steps are built right,
is the picture blurry. The brain (brain.py) does everything else, and gets each reading in its next message.

Two rules act on the readings, both needing QUICK_AGREE readings in a row at QUICK_SURE confidence, so that one
odd frame does nothing:
- the brick in the hand is the current step's: the user is told so, once per step ("The blue one, in your hand."),
  and the voice gives the place if it has not yet;
- more steps are built right than recorded, and no hand is on the plate: the progress moves and the user hears it,
  as when the brain records it.
A hand leaving the plate without the progress moving wakes the brain for a look at once (the placement may be
wrong, which takes words), as the user's words do (agent.py). Everything the quick look says or records is written
into the brain's next message, so the brain knows what the user has heard.

The questions are built from the task file, so another task needs no change here: the choices for the brick in the
hand are the steps' bricks, "another brick" and "none"; for the count, 0 to the number of steps.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import re
import time
from collections import deque
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx

from frames import FrameTap, bottom_square
from guide import Build, Guide
from runlog import RunLog

logger = logging.getLogger("rayneo-agent.quick")

URL = "https://api.openai.com/v1/decisions"
QUICK_SURE = 0.7  # a reading counts when the model is at least this sure of it
QUICK_AGREE = 2  # and the last this many readings say the same
QUICK_SIDE = {"low": 512, "high": 1080}  # the photo's side for each detail: the API scales "low" to 512 px anyway
HAND_ON = 0.5  # the probability above which a hand counts as on the plate
TIMEOUT_S = 5.0


def colour_word(brick: str) -> str:
    """The brick's colour as the user hears it: "dark grey 4x4 round plate" is "dark grey", "lime 1x4" is "lime"."""
    words = [w for w in brick.split() if not re.fullmatch(r"\d+x\d+", w) and w not in ("round", "plate", "brick")]
    return " ".join(words) or brick


def questions(guide: Guide) -> list[dict]:
    """The four questions, from the task's steps."""
    n = len(guide.steps)
    bricks = [{"value": f"step {i}", "description": f"the {s.brick} of step {i}"} for i, s in enumerate(guide.steps, 1)]
    counts = [{"value": str(k), "description": ("nothing is built right yet" if k == 0 else
                                                 "every step is built right" if k == n else
                                                 f"steps 1 to {k} are built right, step {k + 1} is not placed or not right")}
              for k in range(n + 1)]
    return [
        {"type": "predicate", "name": "hand",
         "instructions": "Is a hand touching the baseplate, touching a brick on it, or covering part of it?"},
        {"type": "choice", "name": "in_hand",
         "instructions": "Which brick is the user holding in a hand right now, above the desk or the plate, not resting on the plate?",
         "choices": bricks + [{"value": "another brick", "description": "a brick that is none of the steps' bricks"},
                              {"value": "none", "description": "no brick is held in a hand"}]},
        {"type": "choice", "name": "done",
         "instructions": "Counting from step 1 in order, how many steps are built right on the baseplate, each brick in its "
                         "place and orientation as the steps say? A brick still under a hand does not count.",
         "choices": counts},
        {"type": "predicate", "name": "blurry",
         "instructions": "Is the photo blurry, smeared or blocky from compression, so that the studs on the bricks cannot be made out?"},
    ]


@dataclass
class Reading:
    """One answer set: when it came, what it said and how sure, and what it cost."""
    at: float
    hand: float
    in_hand: str
    in_hand_sure: float
    done: int
    done_sure: float
    blurry: float
    ms: int
    tokens: int

    def line(self, guide: Guide) -> str:
        """The reading as one line of the brain's message."""
        if self.in_hand.startswith("step "):
            held = f"the {guide.steps[int(self.in_hand[5:]) - 1].brick} of {self.in_hand}"
        else:
            held = self.in_hand
        return (f"Quick look, {time.monotonic() - self.at:.0f} s ago: hand on the plate {'yes' if self.hand >= HAND_ON else 'no'}; "
                f"in the hand: {held} ({self.in_hand_sure:.0%} sure); steps built right: {self.done} ({self.done_sure:.0%} sure); "
                f"picture {'blurry' if self.blurry >= 0.5 else 'clear'}.")


class QuickEye:
    def __init__(self, tap: FrameTap, build: Build, task_text: str, model: str, detail: str, every: float,
                 record: RunLog, on_progress: Callable[[int, str], Awaitable[None]],
                 on_say: Callable[[str], Awaitable[None]], on_poke: Callable[[str], None]) -> None:
        self._tap, self._build, self._task = tap, build, task_text
        self._model, self._detail, self._every = model, detail, every
        self._record = record
        self._on_progress, self._on_say, self._on_poke = on_progress, on_say, on_poke
        self._questions = questions(build.guide)
        self._http = httpx.AsyncClient(timeout=TIMEOUT_S, headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"})
        self._readings: deque[Reading] = deque(maxlen=QUICK_AGREE)
        self.latest: Reading | None = None
        self._announced = 0  # the step whose brick in the hand has been announced
        self._task_handle: asyncio.Task | None = None
        self._n = 0

    def start(self) -> None:
        self._task_handle = asyncio.create_task(self._loop(), name="quick_look")

    def cancel(self) -> None:
        """No more looks; the call is over."""
        if self._task_handle is not None:
            self._task_handle.cancel()

    async def stop(self) -> None:
        self.cancel()
        await self._http.aclose()

    async def _loop(self) -> None:
        while True:
            started = time.monotonic()
            if self._tap.latest is not None:
                try:
                    await self._once()
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    logger.warning("quick: #%d failed (%s: %s)", self._n, type(e).__name__, str(e)[:200])
                    self._record.event("quick_failed", n=self._n, error=f"{type(e).__name__}: {e}"[:300])
            await asyncio.sleep(max(0.0, self._every - (time.monotonic() - started)))

    async def _once(self) -> None:
        self._n += 1
        frame = self._tap.latest
        photo = await asyncio.to_thread(self._jpeg, frame)
        body = {"model": self._model,
                "input": [{"type": "message", "role": "user", "content": [
                    {"type": "input_text", "text": f"{self._task}\n\nThe photo is what the user's glasses see right now, the desk from above."},
                    {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(photo).decode(),
                     "detail": self._detail}]}],
                "questions": self._questions}
        t0 = time.perf_counter()
        r = await self._http.post(URL, json=body)
        ms = round((time.perf_counter() - t0) * 1000)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        a = {x["name"]: x for x in data.get("answers", [])}
        if any(a.get(k, {}).get("type") == "refusal" for k in ("hand", "in_hand", "done", "blurry")):
            raise RuntimeError("the model refused a question")
        reading = Reading(at=time.monotonic(), hand=a["hand"]["probability"],
                          in_hand=a["in_hand"]["choice"], in_hand_sure=a["in_hand"].get("confidence", 0.0),
                          done=int(a["done"]["choice"]), done_sure=a["done"].get("confidence", 0.0),
                          blurry=a["blurry"]["probability"], ms=ms,
                          tokens=(data.get("usage") or {}).get("input_tokens", 0))
        before = self._readings[-1] if self._readings else None
        self._readings.append(reading)
        self.latest = reading
        self._record.event("quick", n=self._n, ms=ms, tokens=reading.tokens, hand=round(reading.hand, 2),
                           in_hand=reading.in_hand, in_hand_sure=round(reading.in_hand_sure, 2), done=reading.done,
                           done_sure=round(reading.done_sure, 2), blurry=round(reading.blurry, 2), step=self._build.step + 1)
        logger.info("quick: #%d %d ms hand %.2f in_hand %s (%.2f) done %d (%.2f) blurry %.2f", self._n, ms, reading.hand,
                    reading.in_hand, reading.in_hand_sure, reading.done, reading.done_sure, reading.blurry)
        await self._act(before, reading)

    def _jpeg(self, frame) -> bytes:
        buf = io.BytesIO()
        bottom_square(frame, QUICK_SIDE.get(self._detail, 1080)).save(buf, "JPEG", quality=85)
        return buf.getvalue()

    def _agree(self, key: str, value) -> bool:
        """Whether the last QUICK_AGREE readings all say `value` for `key`, each at least QUICK_SURE sure."""
        if len(self._readings) < QUICK_AGREE:
            return False
        return all(getattr(r, key) == value and getattr(r, f"{key}_sure") >= QUICK_SURE for r in self._readings)

    async def _act(self, before: Reading | None, now: Reading) -> None:
        build = self._build
        step = build.step + 1  # the step the user is on, as they count
        # the current step's brick in the hand: told once per step
        if step <= len(build.guide.steps) and self._announced != step and self._agree("in_hand", f"step {step}"):
            self._announced = step
            await self._on_say(f"The {colour_word(build.guide.steps[step - 1].brick)} one, in your hand.")
            return
        # more steps built right than recorded, hand off the plate: the progress moves
        if now.done > build.step and now.hand < HAND_ON and self._agree("done", now.done):
            await self._on_progress(now.done, f"the quick look counts {now.done} steps built right, {now.done_sure:.0%} sure")
            return
        # the hand left the plate and the count did not move: the brain looks now, the placement may be wrong
        if before is not None and before.hand >= HAND_ON and now.hand < HAND_ON and now.done <= build.step:
            self._on_poke("the hand left the plate")
