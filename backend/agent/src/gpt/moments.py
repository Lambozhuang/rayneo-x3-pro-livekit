"""The second line of the GPT path: the Decisions API reads every frame and says which moment of the build it shows.

    FrameTap --the newest frame, bottom square at MOMENTS_SIDE--> POST /v1/decisions (gpt-6-luna), one request after
        the other, five questions: the plate in view, a hand on the plate, a brick held, which brick, the current
        step's brick on the plate with no hand on it
        --> one commentary to GPT-Live when the step's brick, or another, is held ("Camera: yes, that's the one.")
        --> Brain.look_now(frame) the moment the step's brick lies on the plate with no hand on it

The brain (brain.py) keeps judging the plate: what is placed right or wrong, the progress, the answers about the desk.
This line never judges a placement and never changes the record; it answers the one moment a frame settles fast, the
brick in the hand, and tells the brain when to look. Measured in eval/decisions-frames/ on 2026-11-05: the three state
questions were read right on every frame at 720 px, whether a placement is right not at all; a request takes 0.4 to
0.7 s. The first home run (2026-11-06 00:03) showed the model reads a brick's hue and not its size: a dark red 2x6 and a
tan 1x6 passed as the step's red 2x4 and tan 2x6 at 0.9 and above, by the choice over the build's bricks and by the
yes-or-no alike, so the brick line is a yes-or-no the user accepts as roughly right, said once per pick-up and only with
the hand away from the plate; the same run had a placed red brick read as held while the hand was on the plate, and the
step's brick read as on the plate twice while the plate was empty, so the brain's look is called on the hand leaving the
plate, not on the plate's state alone. The structure is docs/design/2026-11-05-two-lines.md.
"""

import asyncio
import base64
import io
import logging
import os
import time
from collections import deque

import httpx
from livekit.agents import AgentSession

from frames import FrameTap, bottom_square
from gpt.brain import Brain
from gpt.prompts import CUT_IN, spoken
from guide import Build, Guide
from prompts import DIRECTIONS
from runlog import RunLog

logger = logging.getLogger("rayneo-agent.moments")

URL = "https://api.openai.com/v1/decisions"
# The coarse colours a held brick is sorted into, as the sign that the brick in the hand has changed: the model reads a
# brick's hue reliably and its size not at all (eval/decisions-frames), so a change of hue is a change of brick while a
# change of size is invisible. Coarse, so that a dark red brick does not flicker between two names from frame to frame.
COLOURS = ["red", "orange", "yellow", "green", "blue", "purple", "pink", "tan or brown", "white", "grey", "black", "none"]
AGREE = 3  # frames in a row that have to agree before the brick line is said a second time: one frame's reading drifts (below)
# Colours that are not a brick in the hand: "none" came with "held" at 0.83 to 0.91 on empty hands twice in the home run of
# 2026-11-06 14:19, and orange is the brick separator, the only orange thing in the kit, which read as a brick held
# four times over two runs although the question and the task text call it a tool. No line is said about either.
NO_BRICK = {"none", "orange"}


def developer_text(guide: Guide, step: int) -> str:
    """What the model is told about the build and the step: the scene, the direction words, the build's bricks, the
    steps placed before and the current step (`step` as Build counts it, from 0). The same text for every frame of
    a step. eval/decisions-frames/probe.py sends the same text."""
    steps = guide.steps
    placed = "\n".join(f"{i}. {s.brick}: {s.place}" for i, s in enumerate(steps[:step], 1)) or "none"
    cur = steps[step]
    return (
        "You see one photo taken just now by the camera of a pair of AR glasses on the user, who is building a small LEGO "
        f"model, \"{guide.title}\", on a {guide.plate}x{guide.plate} baseplate on a desk; loose bricks lie around the "
        f"plate. {DIRECTIONS} An orange brick separator, a tool, lies among the bricks; it is not a brick.\n\n"
        f"The bricks of this build: {', '.join(s.brick for s in steps)}.\n\n"
        f"Placed in the steps before:\n{placed}\n\n"
        f"The current step, step {step + 1}: {cur.brick}, {cur.place}.\n\n"
        "\"The current step's brick\" in the questions means that brick."
    )


def questions() -> list[dict]:
    """Five yes-or-no questions and the held brick's coarse colour, the same for every frame. Whether a placement is
    right is not asked: the model answered 0.84 to 1.00 on misplaced bricks (eval/decisions-frames), so the plate is
    the brain's. The colour decides nothing by itself; it only tells one held brick from the next."""
    def p(name: str, text: str) -> dict:
        return {"name": name, "type": "predicate", "instructions": text}

    return [
        p("plate", "The baseplate is in the picture and the picture is sharp enough to see its studs."),
        p("hand", "A hand is on the baseplate or on a brick that is on the baseplate."),
        p("held", "The user holds a LEGO brick in the air, not resting on the desk or on the baseplate; the orange "
                  "brick separator is a tool, not a brick."),
        p("is_step", "The brick the user holds is the current step's brick: the same colour and the same size."),
        p("on", "The current step's brick is on the baseplate with no hand on it."),
        {"name": "colour", "type": "choice", "instructions": "What colour is the brick the user holds? \"none\" when no brick is held.",
         "choices": [{"value": c} for c in COLOURS]},
    ]


def _jpeg(frame, side: int) -> bytes:
    buf = io.BytesIO()
    bottom_square(frame, side).save(buf, "JPEG", quality=85)
    return buf.getvalue()


class Moments:
    """Reads every frame with the Decisions API and acts on two moments. `sure` is the probability a brick held and
    the step's brick on the plate need; `yes_at` is the probability at or above which the brick held is called the
    step's and `not_at` the one at or below which it is called another, nothing said in between. Both lines go on two
    frames in a row that read so, whatever was said before: one frame misreads at the moment the hand touches a brick
    on the desk, the step's brick reading 0.10 and 0.18 as it was picked up (the home run of 2026-11-06 13:34) and a
    brick still on the desk reading as held and the step's at 0.96 (the run of 14:47). One frame's reading drifts: in the
    run of 01:03 the same tan brick read as the step's at 0.9 and above and then 0.33 a frame later, and its colour as
    tan and then white, which with single-frame rules gave twenty lines in two minutes. So after a "yes" a "not that
    one" takes AGREE frames, after a "not that one" another comes only for a brick of another colour read for AGREE
    frames, the hand empty for AGREE frames arms the line afresh, and two lines are at least `hold_s` seconds apart."""

    YES = "That's the right brick; it goes {place}."  # the place too, so the voice gives it with the confirmation
    NOT = "That's not the right brick; this step needs the {brick}."

    def __init__(self, session: AgentSession, build: Build, tap: FrameTap, brain: Brain, record: RunLog, side: int,
                 sure: float, yes_at: float, not_at: float, hold_s: float, model: str, detail: str,
                 timeout: float = 5.0) -> None:
        self._session, self._build, self._tap, self._brain, self._record = session, build, tap, brain, record
        self._side, self._sure, self._yes_at, self._not_at, self._hold_s = side, sure, yes_at, not_at, hold_s
        self._model, self._detail, self._timeout = model, detail, timeout
        self._key = os.environ["OPENAI_API_KEY"]
        self._task: asyncio.Task | None = None
        self._said_until = 0.0  # the time (monotonic) before which no line is said
        self._announced: str | None = None  # the line said for the brick held now ("yes" or "not"), None when none is
        self._colour: str | None = None  # the coarse colour of the brick the line was said for, once AGREE frames after the line agree on it; another colour then is another brick
        self._recent: deque = deque(maxlen=AGREE)  # (held, is_step, colour) of the last frames with the plate in view
        self._on_before = 0.0  # the frame before's probability of the step's brick on the plate with no hand on it
        self._looked = False  # the brain has been sent to look at this placement; armed again once "on" drops
        self._state_step = -1  # the step the fields above are about
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
                "questions": questions()}
        t_sent = time.perf_counter()
        r = await http.post(URL, json=body)
        ms = round((time.perf_counter() - t_sent) * 1000)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        a = {x.get("name"): x for x in data.get("answers", [])}
        if any(x.get("type") == "refusal" for x in a.values()):
            raise RuntimeError("a question was refused")
        plate, hand, held, is_step, on = (a[k]["probability"] for k in ("plate", "hand", "held", "is_step", "on"))
        colour = a["colour"]["choice"]
        colour_p = next((x["probability"] for x in a["colour"]["probabilities"] if x["value"] == colour), 0.0)
        tokens = (data.get("usage") or {}).get("input_tokens")
        self._record.event("moment", n=n, step=step + 1, frame=seq, frame_age_ms=round((time.monotonic() - at) * 1000),
                           prep_ms=round((t_sent - t0) * 1000), ms=ms, tokens=tokens, plate=round(plate, 2),
                           hand=round(hand, 2), held=round(held, 2), is_step=round(is_step, 2), on=round(on, 2),
                           colour=colour, colour_p=round(colour_p, 2))
        logger.info("moments: #%d step %d frame %d, %d ms: plate %.2f hand %.2f held %.2f is_step %.2f on %.2f colour %s (%.2f)",
                    n, step + 1, seq, ms, plate, hand, held, is_step, on, colour, colour_p)
        if step != self._build.step:
            return  # the brain moved the progress while the request was out: these answers are about the step before
        if step != self._state_step:
            self._state_step, self._announced, self._colour, self._on_before, self._looked = step, None, None, 0.0, False
            self._recent.clear()
        if plate < 0.5:
            self._recent.clear()
            return
        self._recent.append((held, is_step, colour))
        if self._announced is not None and len(self._recent) == AGREE and all(h < 0.5 for h, _, _ in self._recent):
            # the hand has read empty for AGREE frames: the next brick held up gets a line on its first frame. In the
            # home run of 2026-11-06 00:52 the user swapped bricks for 35 s without "held" ever dropping, so this alone
            # is not enough: a brick of another colour or the other verdict for AGREE frames says again too (_brick_line).
            logger.info("moments: the hand has been empty (held %.2f): the brick line is armed again", held)
            self._announced, self._colour = None, None
        self._brick_line(step, held, is_step, colour, photo)
        self._placement(step, frame, seq, at, hand, on, photo)
        self._on_before = on

    def _brick_line(self, step: int, held: float, is_step: float, colour: str, photo: bytes) -> None:
        """"Yes" on two frames in a row that read the brick held as the step's at `yes_at` or above, unless the last
        line was a yes; "not that one" on two frames in a row at `not_at` or below when no line has been said for the
        brick in the hand, on AGREE frames after a yes, and after a not only for a brick of another colour than the one
        the first AGREE frames after that line settled on, since a line's own frame misreads the colour ("none" with a
        brick held at 0.95). Two lines are at least hold_s apart. The line goes as a commentary; while the voice is
        talking a cut-in instruction goes first, so the line is not left behind the sentence in progress (the run of
        2026-11-06 01:03 had three queued lines come out as one breath)."""
        here = self._build.guide.steps[step]
        if colour in NO_BRICK:
            return  # nothing a line can be about: no colour read, or the orange separator in the hand
        recent = list(self._recent)  # the last frames with the plate in view, this one last
        low = [h >= self._sure and p <= self._not_at and c not in NO_BRICK for h, p, c in recent]
        high = [h >= self._sure and p >= self._yes_at and c not in NO_BRICK for h, p, c in recent]
        if len(recent) >= 2 and all(high[-2:]) and self._announced != "yes":
            kind, line = "yes", self.YES.format(place=here.place)
        elif self._announced is None:
            if len(recent) < 2 or not all(low[-2:]):
                return
            kind, line = "not", self.NOT.format(brick=spoken(here.brick))
        elif self._announced == "yes":
            if len(recent) < AGREE or not all(low):
                return
            kind, line = "not", self.NOT.format(brick=spoken(here.brick))
        else:
            if len(recent) < AGREE or not all(low):
                return
            colours = {c for _, _, c in recent}
            if len(colours) != 1:
                return
            c = colours.pop()
            if self._colour is None:
                self._colour = c
                logger.info("moments: the brick the line was said for reads %s", c)
                return
            if c == self._colour:
                return
            kind, line = "not", self.NOT.format(brick=spoken(here.brick))
        now = time.monotonic()
        if now < self._said_until:
            return
        self._said_until, self._announced, self._colour = now + self._hold_s, kind, None
        saved = self._record.photo(photo, f"moment{self.count}-s{step + 1}")
        speaking = self._session.agent_state == "speaking"
        logger.info("moments: say %r (held %.2f, is_step %.2f, colour %s, photo %s)", line, held, is_step, colour, saved)
        self._record.event("moment_say", n=self.count, step=step + 1, text=line, held=round(held, 2),
                           is_step=round(is_step, 2), colour=colour, photo=saved, voice_speaking=speaking)
        duplex = self._session.current_agent.duplex_session
        if speaking:
            duplex.append_instructions(CUT_IN)
        duplex.append_commentary(line)

    def _placement(self, step: int, frame, seq: int, at: float, hand: float, on: float, photo: bytes) -> None:
        """The step's brick lies on the plate with no hand on it, read on two frames in a row: the brain looks now, at
        this frame, once per placement, armed again when the reading drops. The hand elsewhere on the plate does not
        count: in the home run of 2026-11-06 14:47 the user's hand rested on the plate's edge for six seconds after the
        brick was placed, and a rule that waited for the hand to leave the plate waited those six seconds, while this
        question read 0.96 to 0.99 throughout; with the hand on the brick itself it read 0.00 to 0.06 in every run. Its
        false highs were single frames, 0.9 and 0.0 the frame after, which the second frame rules out."""
        if on >= self._sure and self._on_before >= self._sure and not self._looked:
            self._looked = True
            saved = self._record.photo(photo, f"moment{self.count}-s{step + 1}")
            logger.info("moments: the step's brick is on the plate with no hand on it (on %.2f after %.2f, hand %.2f): the "
                        "brain looks now at frame %d, photo %s", on, self._on_before, hand, seq, saved)
            self._record.event("look_now", n=self.count, step=step + 1, frame=seq, on=round(on, 2),
                               on_before=round(self._on_before, 2), hand=round(hand, 2), photo=saved)
            self._brain.look_now(frame, seq, at)
        elif on < 0.5 and self._looked:
            self._looked = False  # the brick is gone or a hand is back on it: the next placement gets a look
