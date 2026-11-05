"""The second line of the GPT path: the Decisions API reads every frame and says which moment of the build it shows.

    FrameTap --the newest frame, bottom square at MOMENTS_SIDE--> POST /v1/decisions (gpt-6-luna), one request after
        the other, five questions: the plate in view, a hand on the plate, a brick held, which brick, the current
        step's brick on the plate with no hand on it
        --> one commentary to GPT-Live when the step's brick, or another, is held ("Camera: yes, that's the one.")
        --> Brain.look_now(frame) the moment the step's brick lies on the plate and the hand has gone

The brain (brain.py) keeps judging the plate: what is placed right or wrong, the progress, the answers about the desk.
This line never judges a placement and never changes the record; it answers the one moment a frame settles fast, the
brick in the hand, and tells the brain when to look. Measured in eval/decisions-frames/ on 2026-11-05: the three state
questions were read right on every frame at 720 px, the brick held was named right on 12 of 12, whether a placement
is right not at all; a request takes 0.4 to 0.7 s. The structure is docs/design/2026-11-05-two-lines.md.
"""

import asyncio
import base64
import io
import logging
import os
import re
import time

import httpx
from livekit.agents import AgentSession

from frames import FrameTap, bottom_square
from gpt.brain import Brain
from guide import Build, Guide
from runlog import RunLog

logger = logging.getLogger("rayneo-agent.moments")

URL = "https://api.openai.com/v1/decisions"
OTHER, NONE = "another brick", "none"  # the choice's two answers besides the build's bricks


def developer_text(guide: Guide, step: int) -> str:
    """What the model is told about the build and the step: the scene, the direction words, the build's bricks, the
    steps placed before and the current step (`step` as Build counts it, from 0). The same text for every frame of
    a step. eval/decisions-frames/probe.py sends the same text."""
    steps = guide.steps
    placed = "\n".join(f"{i}. {s.brick}: {s.place}" for i, s in enumerate(steps[:step], 1)) or "none"
    cur = steps[step]
    return (
        "You see one photo taken just now by the camera of a pair of AR glasses on a person building a small LEGO "
        f"model, \"{guide.title}\", on a {guide.plate}x{guide.plate} baseplate on a desk; loose bricks lie around the "
        "plate. Directions on the plate are as the builder sees it: up is the far edge, down the near edge; vertical "
        "means a brick's long side runs up and down, horizontal that it runs left and right. A brick's size counts "
        "its studs: a 1x6 is one stud wide and six long.\n\n"
        f"The bricks of this build: {', '.join(s.brick for s in steps)}.\n\n"
        f"Placed in the steps before:\n{placed}\n\n"
        f"The current step, step {step + 1}: {cur.brick}, {cur.place}.\n\n"
        "\"The current step's brick\" in the questions means that brick."
    )


def questions(bricks: list[str]) -> list[dict]:
    """The five questions, the same for every frame: four yes-or-no and which brick is held, a choice over the
    build's bricks. Whether a placement is right is not asked: the model answered 0.84 to 1.00 on misplaced bricks
    (eval/decisions-frames), so the plate is the brain's."""
    def p(name: str, text: str) -> dict:
        return {"name": name, "type": "predicate", "instructions": text}

    return [
        p("plate", "The baseplate is in the picture and the picture is sharp enough to see its studs."),
        p("hand", "A hand is on the baseplate or on a brick that is on the baseplate."),
        p("held", "The builder holds a brick in the air, not resting on the desk or on the baseplate."),
        {"name": "which", "type": "choice", "instructions": "Which brick does the builder hold?",
         "choices": [{"value": b} for b in bricks + [OTHER, NONE]]},
        p("on", "The current step's brick is on the baseplate with no hand on it."),
    ]


def spoken(brick: str) -> str:
    """A brick's name as the voice should say it: "white 1x6" is "white one by six"."""
    words = {"1": "one", "2": "two", "3": "three", "4": "four", "6": "six", "8": "eight"}
    return re.sub(r"(\d)x(\d)", lambda m: f"{words.get(m[1], m[1])} by {words.get(m[2], m[2])}", brick)


def _jpeg(frame, side: int) -> bytes:
    buf = io.BytesIO()
    bottom_square(frame, side).save(buf, "JPEG", quality=85)
    return buf.getvalue()


class Moments:
    """Reads every frame with the Decisions API and acts on two moments. `sure` is the probability a yes needs and
    that the brick's name needs; `hold_s` is how long after a line the same line is not said again, so one pick-up
    gets one line and not one a frame."""

    YES = "Camera: yes, that's the one."
    NOT = "Camera: not that one; the step wants the {brick}."

    def __init__(self, session: AgentSession, build: Build, tap: FrameTap, brain: Brain, record: RunLog, side: int,
                 sure: float, hold_s: float, model: str, detail: str, timeout: float = 5.0) -> None:
        self._session, self._build, self._tap, self._brain, self._record = session, build, tap, brain, record
        self._side, self._sure, self._hold_s = side, sure, hold_s
        self._model, self._detail, self._timeout = model, detail, timeout
        self._key = os.environ["OPENAI_API_KEY"]
        self._task: asyncio.Task | None = None
        self._hold: dict[str, float] = {}  # a line's kind -> the time (monotonic) until which it is not said again
        self._on_before = False  # the frame before showed the step's brick on the plate with no hand on it
        self._on_step = -1  # the step _on_before is about
        self.count = 0  # requests made, for the record

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="moments")

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def _loop(self) -> None:
        """One request after the other on the newest frame, over one kept connection; a failed one is logged and
        the next goes out half a second later."""
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self._timeout, headers=headers) as http:
            while True:
                frame, seq, at = self._tap.latest, self._tap.count, self._tap.latest_at
                if frame is None or self._build.finished:
                    await asyncio.sleep(0.25)
                    continue
                self.count += 1
                try:
                    await self._one(http, self.count, self._build.step, frame, seq, at)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning("moments: #%d failed (%s: %s)", self.count, type(e).__name__, str(e)[:200])
                    self._record.event("moment_failed", n=self.count, error=f"{type(e).__name__}: {e}"[:300])
                    await asyncio.sleep(0.5)

    async def _one(self, http: httpx.AsyncClient, n: int, step: int, frame, seq: int, at: float) -> None:
        guide = self._build.guide
        t0 = time.perf_counter()
        photo = await asyncio.to_thread(_jpeg, frame, self._side)
        body = {"model": self._model,
                "input": [{"role": "developer", "content": developer_text(guide, step)},
                          {"role": "user", "content": [{"type": "input_image", "detail": self._detail,
                                                        "image_url": "data:image/jpeg;base64," + base64.b64encode(photo).decode()}]}],
                "questions": questions([s.brick for s in guide.steps])}
        t_sent = time.perf_counter()
        r = await http.post(URL, json=body)
        ms = round((time.perf_counter() - t_sent) * 1000)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        a = {x.get("name"): x for x in data.get("answers", [])}
        if any(x.get("type") == "refusal" for x in a.values()):
            raise RuntimeError("a question was refused")
        plate, hand, held, on = (a[k]["probability"] for k in ("plate", "hand", "held", "on"))
        which = a["which"]["choice"]
        which_p = next((x["probability"] for x in a["which"]["probabilities"] if x["value"] == which), 0.0)
        tokens = (data.get("usage") or {}).get("input_tokens")
        self._record.event("moment", n=n, step=step + 1, frame=seq, frame_age_ms=round((time.monotonic() - at) * 1000),
                           prep_ms=round((t_sent - t0) * 1000), ms=ms, tokens=tokens, plate=round(plate, 2),
                           hand=round(hand, 2), held=round(held, 2), which=which, which_p=round(which_p, 2), on=round(on, 2))
        logger.info("moments: #%d step %d frame %d, %d ms: plate %.2f hand %.2f held %.2f which %s (%.2f) on %.2f",
                    n, step + 1, seq, ms, plate, hand, held, which, which_p, on)
        if step != self._build.step:
            return  # the brain moved the progress while the request was out: these answers are about the step before
        if plate < 0.5:
            return
        self._brick_line(step, held, which, which_p)
        self._placement(step, frame, seq, at, hand, on)

    def _brick_line(self, step: int, held: float, which: str, which_p: float) -> None:
        """A brick held and named with enough probability gets one line, "yes" for the step's brick and "not that
        one" for any other; the same kind of line then holds for hold_s seconds."""
        if held < self._sure or which_p < self._sure or which == NONE:
            return
        wanted = self._build.guide.steps[step].brick
        kind = "yes" if which == wanted else "not"
        now = time.monotonic()
        if now < self._hold.get(kind, 0.0):
            return
        self._hold[kind] = now + self._hold_s
        line = self.YES if kind == "yes" else self.NOT.format(brick=spoken(wanted))
        speaking = self._session.agent_state == "speaking"
        logger.info("moments: say %r (held %.2f, %s at %.2f)", line, held, which, which_p)
        self._record.event("moment_say", n=self.count, step=step + 1, text=line, which=which, which_p=round(which_p, 2),
                           voice_speaking=speaking)
        self._session.current_agent.duplex_session.append_commentary(line)

    def _placement(self, step: int, frame, seq: int, at: float, hand: float, on: float) -> None:
        """The step's brick on the plate with no hand on it, where the frame before did not show that: the brain
        looks now, at this frame. Armed again when the state drops or the step changes."""
        if step != self._on_step:
            self._on_step, self._on_before = step, False
        on_now = on >= self._sure and hand < 0.5
        if on_now and not self._on_before:
            logger.info("moments: the step's brick is on the plate and the hand gone (on %.2f, hand %.2f): the brain "
                        "looks now at frame %d", on, hand, seq)
            self._record.event("look_now", n=self.count, step=step + 1, frame=seq, on=round(on, 2), hand=round(hand, 2))
            self._brain.look_now(frame, seq, at)
        self._on_before = on_now
