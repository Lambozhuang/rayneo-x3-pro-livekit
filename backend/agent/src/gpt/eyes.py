"""The eyes: OpenAI's Decisions API on the newest camera frame, a state machine on its answers, and the lines the
voice gets from it.

The design follows the Decisions API's limits (eval/brain-decisions/): the model behind it, gpt-6-luna, answers typed
questions about a frame in about 0.3 s and reads the coarse state of the desk well, whether a hand is on the plate,
which brick is in the hand, how many steps are built right, whether the current step's brick is on the plate and
whether it sits as the step says, but cannot say which way a misplaced brick should move. So the eyes settle what
happened and say so at once, in a line of facts the voice (GPT-Live) puts into words, and leave the two things that
take words, the content of a correction and the answer to a question about the scene, to one short request to the
brain's model (consult.py), sent while the voice says the first beat: "Hmm, not quite." and then, a second later,
"it's one column too far right".

A reading every QUICK_FAST_S while a hand is on the plate or a brick is in the hand, every `every` seconds (the
BRAIN_QUICK_EVERY setting) when the scene is still, at once when the wearer has spoken (poke), and never twice on the
same frame. A reading is two requests sent together, four questions about the scene (hand, brick in the hand, steps
built right, blur) and three about the current step's brick (on the plate, placed as the step says, where it lies),
since one request with all seven spread the confidences (the step count fell from 0.8 to 0.4 on the same frames,
eval/agent-sim/ 2026-11-04). Every rule acts on two readings in a row at QUICK_SURE confidence or better, so one odd
frame does nothing. The lines:

- the current step's brick in the hand: "Camera: The blue one, in your hand." once per step;
- the current step's brick on the plate as the step says and in the step's colour, hand off, or more steps built
  right than recorded: the progress moves and the voice hears "Progress: ..."; the last step, which ends the task,
  is confirmed by the brain's model first when the consult is on, since the eyes once called a white brick in the
  lime brick's place right (the recording of 2026-10-27, eval/agent-sim/);
- the current step's brick on the plate, hand off, not as the step says, the count unmoved: "Camera: the white one
  is on the plate but not in its place yet." once per attempt (a hand back on it starts a new one), and the brain is
  consulted for the correction; if nothing comes back within CONSULT_WAIT_S the voice is told to say the place once
  more and offer the picture;
- two bricks the model cannot tell apart in the hand, one of them the step's: "Camera: in your hand, the yellow one
  or the lime one, I can't tell which." once per step;
- the picture blurry: "Camera: the picture is blurry right now." at most once a minute;
- the step's brick lying on the desk with nothing in the hand for FIND_AFTER_S after the step was given: "Camera: the
  grey one is right of the plate." once per step.

The wearer's words are classified by the same API on the text alone (what they ask or claim), and routed: a question
about the scene or a disagreement goes to the brain's model with the frame; a request for the picture puts it on the
glasses; with the consult off (BRAIN_CONSULT=off) the eyes alone judge: a misplaced brick gets the place said once more
and the picture offered, a question about the desk the eyes' latest reading in words, and nothing goes to the brain's
model; words sorted as needing no eyes at less than WORDS_SURE confidence go to the brain's model all the same, since
a wasted request is cheap and an unanswered question is not; "I placed it" goes to the brain's model at once as well, and its answer is spoken only when the eyes have not
settled the step by then (PLACED_WAIT_S), so the wearer never waits in silence after it and never hears the verdict
twice; everything else needs no eyes, the voice answers it or lets it pass. The questions are built from the task
file, so another step-wise task needs no change here.
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
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import httpx

from frames import FrameTap, bottom_square
from guide import Build, Guide, publish_build
from runlog import RunLog

logger = logging.getLogger("rayneo-agent.eyes")

URL = "https://api.openai.com/v1/decisions"
QUICK_SURE = 0.7  # a yes-or-no answer counts from this probability; two readings' mean confidence in a choice from SURE_MEAN
SURE_MEAN = 0.6
QUICK_AGREE = 2  # the last this many readings must say the same
QUICK_FAST_S = 0.7  # the pause between readings while a hand is on the plate or a brick is in the hand
QUICK_SIDE = {"low": 512, "high": 1080}  # the photo's side for each detail: the API scales "low" to 512 px anyway
HAND_ON = 0.5  # the probability above which a hand counts as on the plate
RIGHT = 0.6  # "as the step says" at least this is a right placement; WRONG or less a wrong one; between, nothing is said
WRONG = 0.3
BLUR = 0.8
BLUR_EVERY_S = 60.0
FIND_AFTER_S = 12.0  # with nothing in the hand this long after a step was given and the user last spoke, where its brick lies is said
CONSULT_WAIT_S = 4.5  # the correction's words are waited for this long before the voice is told to repeat the place
WORDS_SURE = 0.5  # words classified less surely than this as needing no eyes are sent to the brain's model all the same
WORDS_SETTLE_S = 1.2  # pieces of the wearer's turn that come this close together are classified as one
FINISH_AGAIN_S = 10.0  # the brain's model is asked again whether the build is finished after this long with the count still at the last step
PLACED_WAIT_S = 2.5  # after "I placed it", the eyes get this long to settle the step before the brain's answer is spoken
TIMEOUT_S = 5.0
CUT_IN = "Stop what you are saying at once, mid-sentence, this once: a helper line follows that the user must hear now."


def colour_word(brick: str) -> str:
    """The brick's colour as the user hears it: "dark grey 4x4 round plate" is "dark grey", "lime 1x4" is "lime"."""
    words = [w for w in brick.split() if not re.fullmatch(r"\d+x\d+", w) and w not in ("round", "plate", "brick")]
    return " ".join(words) or brick


WHERE = [("in a hand", "in a hand"), ("on the baseplate", "on the plate"),
         ("left of the plate, on the desk", "left of the plate"), ("right of the plate, on the desk", "right of the plate"),
         ("beyond the plate, on the desk at the far side", "beyond the plate, at the far side"),
         ("before the plate, on the desk at the near side", "in front of the plate, on the near side"),
         ("not visible", "not visible")]


def scene_questions(guide: Guide) -> list[dict]:
    """The four questions about the scene, the same for every frame, from the task's steps."""
    n = len(guide.steps)
    bricks = [{"value": f"step {i}", "description": f"the {s.brick} of step {i}"} for i, s in enumerate(guide.steps, 1)]
    counts = [{"value": str(c), "description": ("nothing is built right yet" if c == 0 else
                                                 "every step is built right" if c == n else
                                                 f"steps 1 to {c} are built right, step {c + 1} is not placed or not right")}
              for c in range(n + 1)]
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


def step_questions(guide: Guide, k: int) -> list[dict]:
    """The four questions about the brick of step k (1-based)."""
    step = guide.steps[min(k, len(guide.steps)) - 1]
    return [
        {"type": "predicate", "name": "colour",
         "instructions": f"Is the brick lying at step {k}'s place on the baseplate {colour_word(step.brick)}, the colour step {k} "
                         "names, and not a brick of another colour?"},
        {"type": "predicate", "name": "on_plate",
         "instructions": f"Is the {step.brick} of step {k} resting on the baseplate, pressed on, with no hand on it?"},
        {"type": "predicate", "name": "right",
         "instructions": f"Step {k} says the {step.brick} goes {step.place}. Is the {step.brick} on the baseplate exactly there, "
                         "in that orientation, touching what it should touch, in the right row and column?"},
        {"type": "choice", "name": "where",
         "instructions": f"Where is the {step.brick} of step {k} right now?",
         "choices": [{"value": v} for v, _ in WHERE]},
    ]


WORDS = [
    ("scene", "asks whether something in front of them is right, what a brick or the plate looks like, or anything else that takes looking at the desk"),
    ("disagrees", "says a brick, a colour or a step is not as the assistant said, or that something was wrong"),
    ("picture", "asks to see the picture of the step, or says yes to the assistant's offer of it"),
    ("placed", "says they have placed the brick or finished the step"),
    ("have", "says they have the brick or picked it up"),
    ("steps", "asks about the steps themselves, which step they are on, where a brick goes, what comes next"),
    ("other", "acknowledges, agrees, or says something that needs no answer about the desk"),
]


@dataclass
class Reading:
    """One answer set: when it came, what it said and how sure, and what it cost."""
    at: float
    step: int  # the step the questions were about
    hand: float
    in_hand: str
    in_hand_sure: float
    in_hand_p: dict[str, float]
    done: int
    done_sure: float
    on_plate: float
    right: float
    colour: float  # the brick at the step's place is the step's colour
    where: str
    where_sure: float
    blurry: float
    ms: int
    tokens: int

    def line(self, guide: Guide) -> str:
        """The reading as one line for the brain's model."""
        held = f"the {guide.steps[int(self.in_hand[5:]) - 1].brick}" if self.in_hand.startswith("step ") else self.in_hand
        return (f"The quick look, {time.monotonic() - self.at:.0f} s ago: hand on the plate {'yes' if self.hand >= HAND_ON else 'no'}; "
                f"in the hand {held} ({self.in_hand_sure:.0%} sure); steps built right {self.done} ({self.done_sure:.0%} sure); "
                f"the step's brick on the plate {self.on_plate:.0%}, placed as the step says {self.right:.0%}, its colour {self.colour:.0%}; "
                f"picture {'blurry' if self.blurry >= 0.5 else 'clear'}.")


class Eyes:
    def __init__(self, session, build: Build, tap: FrameTap, task_text: str, model: str, detail: str, every: float,
                 record: RunLog, consult: Callable[[str, Reading | None, str | None], Awaitable[str | None]] | None,
                 show: Callable[[int], Awaitable[str]]) -> None:
        self._session, self._build, self._tap, self._task = session, build, tap, task_text
        self._model, self._detail, self._every = model, detail, every
        self._record = record
        self._consult, self._show = consult, show  # the brain's model for words (consult.py), or None with the consult off, and the picture
        self._http = httpx.AsyncClient(timeout=TIMEOUT_S, headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"})
        self._readings: deque[Reading] = deque(maxlen=QUICK_AGREE)
        self.latest: Reading | None = None
        self._wake = asyncio.Event()
        self._task_handle: asyncio.Task | None = None
        self._n = 0
        self._read_count = -1  # the camera's frame count at the last reading: a frame is read once
        self._user_spoke_at: float | None = None  # when the wearer last said something
        # what has been said for the step the user is on, reset when the progress moves
        self._step_told = self._build.step
        self._said_in_hand = self._said_doubt = self._said_where = False
        self._wrong_said_at: float | None = None  # the attempt the "not in its place" line was said for
        self._hand_was_on = False
        self._finish_asked_at: float | None = None  # when the brain's model was last asked whether the build is finished
        self._step_given_at = time.monotonic()
        self._blur_said_at: float | None = None
        self._last_line: str | None = None
        self._last_line_at: float | None = None
        self._consulting: asyncio.Task | None = None
        self._verdict_at: float | None = None  # when the step was last settled, by the progress or a "not in its place" line
        self._pieces: list[str] = []  # the wearer's turn as it comes through, classified once it has settled
        self._settling: asyncio.Task | None = None

    # ------------------------------------------------------------------ the loop

    def start(self) -> None:
        self._task_handle = asyncio.create_task(self._loop(), name="eyes")

    def cancel(self) -> None:
        if self._task_handle is not None:
            self._task_handle.cancel()
        if self._consulting is not None:
            self._consulting.cancel()

    async def stop(self) -> None:
        self.cancel()
        await self._http.aclose()

    def poke(self, reason: str) -> None:
        """A reading now: the wearer has spoken."""
        self._record.event("poke", reason=reason)
        self._wake.set()

    async def _loop(self) -> None:
        while True:
            started = time.monotonic()
            self._wake.clear()
            if self._tap.latest is not None:
                try:
                    await self._once()
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    logger.warning("eyes: reading #%d failed (%s: %s)", self._n, type(e).__name__, str(e)[:200])
                    self._record.event("quick_failed", n=self._n, error=f"{type(e).__name__}: {e}"[:300])
            busy = self.latest is not None and (self.latest.hand >= HAND_ON or self.latest.in_hand not in ("none", "another brick"))
            rest = (QUICK_FAST_S if busy else self._every) - (time.monotonic() - started)
            if rest > 0:
                try:
                    await asyncio.wait_for(self._wake.wait(), rest)
                except asyncio.TimeoutError:
                    pass

    async def _once(self) -> None:
        if self._tap.count == self._read_count:
            return  # no new frame since the last reading
        self._read_count = self._tap.count
        self._n += 1
        step = min(self._build.step + 1, len(self._build.guide.steps))  # after the last step the questions stay on it
        photo = await asyncio.to_thread(self._jpeg, self._tap.latest)
        text = f"{self._task}\n\nThe photo is what the user's glasses see right now, the desk from above."
        (a, ms1, t1), (b, ms2, t2) = await asyncio.gather(
            self._ask_decisions(text, photo, scene_questions(self._build.guide)),  # no word of the step: it pulled the count down
            self._ask_decisions(f"{text} The user is on step {step}.", photo, step_questions(self._build.guide, step)))
        a.update(b)
        ms, tokens = max(ms1, ms2), t1 + t2
        in_hand = a["in_hand"]
        reading = Reading(at=time.monotonic(), step=step, hand=a["hand"]["probability"],
                          in_hand=in_hand["choice"], in_hand_sure=in_hand.get("confidence", 0.0),
                          in_hand_p={p["value"]: p["probability"] for p in in_hand.get("probabilities", [])},
                          done=int(a["done"]["choice"]), done_sure=a["done"].get("confidence", 0.0),
                          on_plate=a["on_plate"]["probability"], right=a["right"]["probability"],
                          colour=a["colour"]["probability"],
                          where=a["where"]["choice"], where_sure=a["where"].get("confidence", 0.0),
                          blurry=a["blurry"]["probability"], ms=ms, tokens=tokens)
        before = self._readings[-1] if self._readings else None
        if before is not None and before.step != step:
            self._readings.clear()  # the questions changed with the step: the old answers do not agree with anything
            before = None
        self._readings.append(reading)
        self.latest = reading
        self._record.event("quick", n=self._n, ms=ms, tokens=tokens, step=step, hand=round(reading.hand, 2),
                           in_hand=reading.in_hand, in_hand_sure=round(reading.in_hand_sure, 2), done=reading.done,
                           done_sure=round(reading.done_sure, 2), on_plate=round(reading.on_plate, 2),
                           right=round(reading.right, 2), colour=round(reading.colour, 2), where=reading.where,
                           blurry=round(reading.blurry, 2))
        logger.info("eyes: #%d %d ms step %d hand %.2f in_hand %s (%.2f) done %d (%.2f) on %.2f right %.2f colour %.2f where %s blurry %.2f",
                    self._n, ms, step, reading.hand, reading.in_hand, reading.in_hand_sure, reading.done, reading.done_sure,
                    reading.on_plate, reading.right, reading.colour, reading.where, reading.blurry)
        await self._act(before, reading)

    async def _ask_decisions(self, text: str, photo: bytes | None, qs: list[dict]) -> tuple[dict, int, int]:
        """One Decisions request; returns the answers by name, the time and the tokens."""
        content: list = [{"type": "input_text", "text": text}]
        if photo is not None:
            content.append({"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(photo).decode(),
                            "detail": self._detail})
        body = {"model": self._model, "input": [{"type": "message", "role": "user", "content": content}], "questions": qs}
        t0 = time.perf_counter()
        r = await self._http.post(URL, json=body)
        ms = round((time.perf_counter() - t0) * 1000)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        answers = {x["name"]: x for x in data.get("answers", [])}
        if any(x.get("type") == "refusal" for x in answers.values()):
            raise RuntimeError("the model refused a question")
        return answers, ms, (data.get("usage") or {}).get("input_tokens", 0)

    def _jpeg(self, frame) -> bytes:
        buf = io.BytesIO()
        bottom_square(frame, QUICK_SIDE.get(self._detail, 1080)).save(buf, "JPEG", quality=85)
        return buf.getvalue()

    # ------------------------------------------------------------------ the rules

    def _agree(self, test: Callable[[Reading], bool]) -> bool:
        """Whether the last QUICK_AGREE readings all pass `test`."""
        return len(self._readings) >= QUICK_AGREE and all(test(r) for r in self._readings)

    def _agree_on(self, value_of: Callable[[Reading], object], value, sure_of: Callable[[Reading], float],
                  mean: float = SURE_MEAN) -> bool:
        """Whether the last QUICK_AGREE readings all give `value`, with their mean confidence at least `mean`: the
        confidence swings between near-identical frames, the value much less."""
        if len(self._readings) < QUICK_AGREE or any(value_of(r) != value for r in self._readings):
            return False
        return sum(sure_of(r) for r in self._readings) / len(self._readings) >= mean

    async def _act(self, before: Reading | None, now: Reading) -> None:
        build = self._build
        step = now.step
        if self._build.finished:
            return  # the task is over: the glasses hang up once the voice has said so
        if step != self._step_told:
            self._step_told = step
            self._said_in_hand = self._said_doubt = self._said_where = False
            self._wrong_said_at = None
            self._step_given_at = time.monotonic()
        brick = build.guide.steps[min(step, len(build.guide.steps)) - 1].brick
        colour = colour_word(brick)
        hand_on = now.hand >= HAND_ON
        if self._hand_was_on and not hand_on:
            self._wrong_said_at = None  # the hand was on the plate and left: a new attempt
            self._finish_asked_at = None
        self._hand_was_on = hand_on
        last = len(build.guide.steps)

        if step > len(build.guide.steps):
            return  # finished
        # the step's brick on the plate as the step says, hand off: the step is done; or more steps counted built right
        if now.done > build.step and not hand_on and self._agree_on(lambda r: r.done, now.done, lambda r: r.done_sure, 0.5):
            if now.done == last and not await self._finish():
                return
            await self.progress(now.done, f"the quick look counts {now.done} steps built right, {now.done_sure:.0%} sure", "quick look")
            return
        if not hand_on and self._agree(lambda r: r.on_plate >= QUICK_SURE and r.right >= RIGHT and r.colour >= RIGHT):
            if step == last and not await self._finish():
                return
            await self.progress(step, f"the quick look sees the {brick} on the plate as the step says, {now.right:.0%} sure, "
                                      f"its colour {now.colour:.0%}", "quick look")
            return
        # the current step's brick in the hand: told once per step
        if not self._said_in_hand and self._agree_on(lambda r: r.in_hand, f"step {step}", lambda r: r.in_hand_sure):
            self._said_in_hand = True
            self.speak([f"Camera: The {colour} one, in your hand."], "quick")
            return
        # two bricks the model cannot tell apart, one of them the step's: asked as a question, once per step
        if not self._said_in_hand and not self._said_doubt and self._agree(lambda r: r.in_hand.startswith("step ") and r.in_hand_sure < SURE_MEAN):
            top = sorted(now.in_hand_p.items(), key=lambda kv: -kv[1])[:2]
            if len(top) == 2 and top[1][1] >= 0.25 and any(v == f"step {step}" for v, _ in top) and all(v.startswith("step ") for v, _ in top):
                self._said_doubt = True
                names = [colour_word(build.guide.steps[int(v[5:]) - 1].brick) for v, _ in top]
                self.speak([f"Camera: in your hand, the {names[0]} one or the {names[1]} one, I can't tell which from here."], "quick")
                return
        # the step's brick on the plate, hand off, not as the step says, the count unmoved: not in its place yet
        # the step's brick on the plate, sitting right, but not the step's colour to the eyes: the brain's model is asked
        # quietly, since the eyes misread white under a dark exposure and a wrong "not quite" costs more than a second
        if self._wrong_said_at is None and not hand_on and self._agree(lambda r: r.on_plate >= QUICK_SURE and r.right >= RIGHT and r.colour <= WRONG):
            self._wrong_said_at = time.monotonic()
            if self._consult is not None:
                self._consult_now("colour", f"The brick at step {step}'s place sits right, but to the quick look it is not {colour} "
                                            f"({now.colour:.0%} that it is). Is it the {brick}? If it is, call set_progress with {step}; "
                                            "if it is another colour, say which and that the step wants the {colour} one.", fallback=False)
            return
        if self._wrong_said_at is None and not hand_on and self._agree(lambda r: r.on_plate >= QUICK_SURE and r.right <= WRONG):
            self._wrong_said_at = self._verdict_at = time.monotonic()
            if self._consult is None:  # the eyes alone: one line, the place said again and the picture offered
                self.speak([f"Camera: the {colour} one is on the plate but not in its place yet; say once more where it goes, "
                            "and offer the picture."], "eyes", urgent=True)
                return
            self.speak([f"Camera: the {colour} one is on the plate but not in its place yet."], "quick", urgent=True)
            doubt = (f"The brick at that place may not be {colour} at all ({now.colour:.0%} that it is): check the colour first, since "
                     f"a brick of another colour is not the step's brick, whatever its place. " if now.colour <= WRONG else "")
            self._consult_now("placement", f"The {brick} of step {step} is on the plate but not as the step says. {doubt}Say what is "
                                           "wrong and what would make it right, in one sentence.", fallback=True)
            return
        # the picture blurry
        if (self._blur_said_at is None or time.monotonic() - self._blur_said_at > BLUR_EVERY_S) and self._agree(lambda r: r.blurry >= BLUR):
            self._blur_said_at = time.monotonic()
            self.speak(["Camera: the picture I'm getting is blurry right now."], "quick")
            return
        # nothing in the hand for a while after the step was given, the brick in sight on the desk: where it lies
        since = min(time.monotonic() - self._step_given_at,
                    time.monotonic() - self._user_spoke_at if self._user_spoke_at else 0.0)
        if (not self._said_where and not self._said_in_hand and self._user_spoke_at is not None and since >= FIND_AFTER_S
                and self._agree(lambda r: r.in_hand == "none" and r.where_sure >= QUICK_SURE
                                and r.where not in ("in a hand", "on the baseplate", "not visible"))):
            self._said_where = True
            spoken = dict(WHERE)[now.where]
            self.speak([f"Camera: the {colour} one is {spoken}."], "quick")

    async def _finish(self) -> bool:
        """Whether the eyes may call the build finished by themselves: yes with the consult off; with it on, the
        brain's model is asked once per attempt and moves the progress itself when it agrees, since finishing ends
        the task on the glasses."""
        if self._consult is None:
            return True
        if self._finish_asked_at is None or time.monotonic() - self._finish_asked_at >= FINISH_AGAIN_S:
            self._finish_asked_at = time.monotonic()
            n = len(self._build.guide.steps)
            self._consult_now("finish", f"The quick look counts all {n} steps built. Is the build finished as the steps say, every "
                                        f"brick its step's colour in its place? If it is, call set_progress with {n}; if not, say "
                                        "in one sentence what is still off.", fallback=False)
        return False

    # ------------------------------------------------------------------ the wearer's words

    async def words(self, text: str) -> None:
        """The wearer's words as they come through: a reading now, and the words classified once no more have come
        for WORDS_SETTLE_S, since the transcript hands a turn over in pieces."""
        self.poke("the wearer's words")
        self._user_spoke_at = time.monotonic()
        self._pieces.append(text.strip())
        if self._settling is None or self._settling.done():
            self._settling = asyncio.create_task(self._settle_words(), name="words")

    async def _settle_words(self) -> None:
        n = -1
        while n != len(self._pieces):  # wait until no new piece came during a whole pause
            n = len(self._pieces)
            await asyncio.sleep(WORDS_SETTLE_S)
        text, self._pieces = " ".join(self._pieces), []
        await self._route(text)

    async def _route(self, text: str) -> None:
        """The wearer's turn, classified by the same API on the text and the lines before it, and routed: a question
        about the scene or a disagreement goes to the brain's model with the frame, a request for the picture puts it
        up, the rest needs no eyes."""
        try:
            items = [i for i in self._session.history.items
                     if i.type == "message" and i.role in ("user", "assistant") and (i.text_content or "").strip()]
            before = "\n".join(f"{'User' if i.role == 'user' else 'Assistant'}: {' '.join(i.text_content.split())}" for i in items[-3:-1])
            context = f"The last lines before it:\n{before}\n" if before else ""
            if self._last_line and self._last_line_at and time.monotonic() - self._last_line_at < 30:
                context += f"The helper's last line to the assistant: {self._last_line}\n"
            a, ms, _ = await self._ask_decisions(f"{self._task}\n\n{context}The user, building this, just said to the assistant: \"{text}\"", None, [
                {"type": "choice", "name": "kind", "instructions": "What are these words, as the assistant should take them?",
                 "choices": [{"value": v, "description": d} for v, d in WORDS]}])
        except Exception as e:  # noqa: BLE001
            logger.warning("eyes: words not classified (%s)", str(e)[:100])
            self._record.event("words", text=text, words_kind="unclassified")
            return
        kind, sure = a["kind"]["choice"], a["kind"].get("confidence", 0.0)
        self._record.event("words", text=text, words_kind=kind, sure=round(sure, 2), ms=ms)
        logger.info("eyes: words %r -> %s (%.2f)", text, kind, sure)
        if kind in ("scene", "disagrees") or (sure < WORDS_SURE and kind in ("steps", "other") and self._consult is not None):
            # an unclear classification goes to the brain's model too: a wasted request is cheap, an unanswered question is not
            self._consult_now("words", f'The user just said: "{text}". Answer them in one sentence from what the photo shows, '
                                       "starting with the answer; if you cannot see what they ask about, say what is in the way; if the words need "
                                       "no answer about the desk, an acknowledgement or small talk, call no tool.",
                              fallback=False)
        elif kind == "picture":
            line = await self._show(min(self._build.step + 1, len(self._build.guide.steps)))
            self.speak([line], "eyes")
        elif kind == "placed":
            self._placed(time.monotonic())

    def _placed(self, said_at: float) -> None:
        """The wearer says they placed it: the brain's model is asked at once, speculatively, and its verdict is spoken
        only if the eyes have not settled the step by the time it comes (the progress or a "not in its place" line
        since the words, less a second for the transcript's lag)."""
        if self._verdict_at is not None and self._verdict_at >= said_at - 1.0:
            return  # settled just before the words came through
        step = self._build.step + 1
        if step > len(self._build.guide.steps):
            return
        brick = self._build.guide.steps[step - 1].brick
        self._consult_now("placed", f"The user says they have placed the {brick} of step {step}. Is it on the plate as the step says? "
                                    "If it is, say so and call set_progress; if not, say what is wrong and what would make it right; "
                                    "if you cannot see it, say what is in the way.", fallback=True, unless_settled_since=said_at - 1.0)

    # ------------------------------------------------------------------ speaking and consulting

    def speak(self, lines: list[str], source: str, urgent: bool = False) -> None:
        """Hands lines to the voice as one commentary and records it. An urgent line that comes while the voice is
        speaking is preceded by an appended instruction to stop, which makes GPT-Live break off within two seconds
        and say the line, where a commentary alone waits for the sentence in progress (eval/voice-script,
        interrupt-*.json, 2026-11-05); used for a step done and a brick placed wrong, the two moments a person
        interrupts themselves for."""
        line = " ".join(lines)
        speaking = self._session.agent_state == "speaking"
        duplex = self._session.current_agent.duplex_session
        if urgent and speaking:
            self._record.event("cut_in", text=line, source=source)
            duplex.append_instructions(CUT_IN)
        self._record.event("commentary", text=line, source=source, voice_speaking=speaking)
        duplex.append_commentary(line)
        self._last_line, self._last_line_at = lines[-1], time.monotonic()

    async def progress(self, done: int, seen: str, basis: str) -> None:
        """The build moves up to `done`; the voice hears it."""
        build = self._build
        if done <= build.step:
            return
        self._verdict_at = time.monotonic()
        picture = build.picture
        build.set_step(done)
        self._record.event("step", done=build.step, now=None if build.finished else build.step + 1, seen=seen, basis=basis)
        if build.finished:
            self._record.event("build", finished=True, took_s=round(time.monotonic() - build.started, 1))
        await publish_build(build)
        total = len(build.guide.steps)
        where = (f"all {total} steps done, the build is finished" if build.finished else
                 f"{build.step} of {total} steps done; the user is on step {build.step + 1} ({build.guide.steps[build.step].brick})")
        self.speak([f"Progress: {where}."], basis.replace(" ", "_"), urgent=True)
        if picture:
            logger.info("picture: taken off the glasses with the progress")

    def _consult_now(self, reason: str, ask: str, fallback: bool, unless_settled_since: float | None = None) -> None:
        """One request to the brain's model, in the background; the voice gets its sentence when it comes, or the
        fallback line when nothing comes within CONSULT_WAIT_S. With `unless_settled_since`, the sentence is dropped
        when the eyes have settled the step since that moment."""
        if self._consult is None:
            self._record.event("consult_off", reason=reason)
            self.speak([self._eyes_only(reason)], "eyes")
            return
        if self._consulting is not None and not self._consulting.done():
            self._consulting.cancel()
        self._consulting = asyncio.create_task(self._consult_task(reason, ask, fallback, unless_settled_since), name="consult")

    def _eyes_only(self, reason: str) -> str:
        """What the eyes can say by themselves where the brain's model would have been asked: for a misplaced brick,
        that the place is to be said once more with the picture offered; for the wearer's words, the latest reading
        on the step's brick in words."""
        step = min(self._build.step + 1, len(self._build.guide.steps))
        colour = colour_word(self._build.guide.steps[step - 1].brick)
        r = self.latest
        if r is None:
            return f"Camera: I can't see the plate yet."
        if r.on_plate >= QUICK_SURE and r.right >= RIGHT:
            return f"Camera: the {colour} one looks in its place to me."
        if r.on_plate >= QUICK_SURE and r.right <= WRONG:
            if self._wrong_said_at is not None:
                return f"Camera: the {colour} one still does not look in its place to me."
            return f"Camera: the {colour} one is on the plate but does not look in its place yet; say once more where it goes, and offer the picture."
        if r.hand >= HAND_ON:
            return "Camera: a hand is over the plate, so I can't tell yet."
        return f"Camera: I can't tell from here whether the {colour} one is in its place yet."

    async def _consult_task(self, reason: str, ask: str, fallback: bool, unless_settled_since: float | None) -> None:
        step = self._build.step + 1
        brick = self._build.guide.steps[min(step, len(self._build.guide.steps)) - 1].brick
        try:
            line = await asyncio.wait_for(self._consult(reason, self.latest, ask), CONSULT_WAIT_S)
            if unless_settled_since is not None and self._verdict_at is not None and self._verdict_at >= unless_settled_since:
                self._record.event("consult_dropped", reason=reason, text=line)
                return  # the eyes settled it meanwhile; the user has heard
        except asyncio.TimeoutError:
            self._record.event("consult_late", reason=reason, waited_s=CONSULT_WAIT_S)
            line = None
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("eyes: consult failed (%s: %s)", type(e).__name__, str(e)[:200])
            self._record.event("consult_failed", reason=reason, error=f"{type(e).__name__}: {e}"[:300])
            line = None
        if line:
            self.speak([line], "consult")
        elif fallback:
            self.speak([f"Camera: I can't make out what is off with the {colour_word(brick)} one; say once more where it goes, and offer the picture."], "fallback")

    def handed_back(self) -> str:
        """What closes a hand-over GPT-Live makes although its prompt tells it not to: the last line while fresh,
        otherwise the three words a person says."""
        if self._last_line and self._last_line_at and time.monotonic() - self._last_line_at <= 6.0:
            fact = self._last_line.split(": ", 1)[1] if ": " in self._last_line else self._last_line
            return f"Camera: nothing new since the last look; still: {fact}"
        return "Camera: let me look."
