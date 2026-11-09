"""Game A of the user study, "pick the brick": a tray of six 2x4 bricks of six hues, the agent names a colour, the user
holds that brick up, the Decisions line says whether it is the one, four times; then the user asks which bricks they
picked and the voice answers from the conversation.

    PickGame --"Pick up the red brick."--> GPT-Live says it                       (record: name)
    glasses --video--> FrameTap --> PickGame._frames: every frame to the Decisions API, three questions:
        a brick is held in the air, the held brick is the named colour, which colour it is
        --first frame held--> record: pick_held
        --two frames held and the named colour at MOMENTS_YES_AT or above, or at MOMENTS_NOT_AT or below-->
            Build.act_now("yes" | "not") to the glasses (the dots flash green or red)        (record: pick_verdict)
            "That's the red one." | "That's not the red one." to GPT-Live, which says it
        --the hand empty for AGREE frames--> the next colour
    the hint line says what to do while the picks run (HINT_PICK, Build.hint); after the last pick it says to ask which
    bricks were picked; the user's next turn finishes the build, the voice answers from what it said, and the call ends
    as a finished build's does (gpt/agent.py)

The agent paces the trial and the brain does not run: there is nothing to judge but the brick in the hand, which the
Decisions line reads in under a second, so the delay the block adds shows in the time from the pick-up to the flash and
to the voice. A brick held for HELD_MAX_S without a verdict is "none": the voice says it cannot tell and asks for it to be
put back, and the game moves on. The trial files are guides/a-1 to a-6 (game = "pick", a step per pick with the brick's
colour, numbers 201 to 206), four picks each from the six colours, no two trials the same four or the same order; the
spec is the study's game-spec.md, outside the repo (2026-11-08, built 2026-11-09, four picks and six colours from the
user's first runs the same night).

The class stands where the brain stands for gpt/agent.py (start_watching, stop_watching, voice_now, on_delegation,
instructions) and hears the wearer's turns (wearer_said) for the question at the end.
"""

import asyncio
import base64
import io
import logging
import os
import time

import httpx
from livekit.agents import AgentSession

from frames import FrameTap, bottom_square
from gpt.config import Settings
from gpt.moments import AGREE, COLOURS, URL, NO_BRICK
from gpt.prompts import CUT_IN
from guide import Build, publish_build
from runlog import RunLog

logger = logging.getLogger("rayneo-agent.pick")

# The tray's six colours, one 2x4 brick each (the study's game-spec.md; green went on 2026-11-09, the kit's green being
# a teal that misleads); a trial names four of them.
TRAY = ("red", "blue", "purple", "pink", "white", "light grey")
# The hint line: one text through the picks, then the question (Lambo's wording, 2026-11-09).
HINT_PICK = "Listen for the colour, pick that brick up and hold it up. Put it back once the agent has confirmed it."
HINT_ASK = "Now ask the agent which bricks you picked."
HELD_MAX_S = 5.0  # a brick held this long without a verdict is "none"
PAUSE_S = 1.0  # between the hand reading empty and the next colour named
START_WAIT_S = 6.0  # the most the first colour waits for the greeting to be said

# The lines the voice gets; it says them in its own words (the user's decision of 2026-11-08: no fixed phrases).
NAME = "Pick up the {colour} brick."
YES = "That's the {colour} one."
NOT = "That's not the {colour} one."
NONE = "I can't tell which one that is; put it back."
LAST = "That was the last one."


def _colour(brick: str) -> str:
    """The colour words of a brick's name: "light grey 2x4" is "light grey"."""
    return brick.rsplit(" ", 1)[0]


def _jpeg(frame, side: int) -> bytes:
    buf = io.BytesIO()
    bottom_square(frame, side).save(buf, "JPEG", quality=85)
    return buf.getvalue()


def developer_text(colours: list[str], named: str) -> str:
    """What the Decisions model is told: the tray, its colours and the colour asked for now."""
    return (
        "You see one photo taken just now by the camera of a pair of AR glasses on the user, who plays a game at a desk: a "
        f"tray holds LEGO 2x4 bricks, one of each of these colours: {', '.join(colours)}. The user picks one brick up and "
        f"holds it in the air; there is no baseplate. The colour asked for now: {named}."
    )


def questions(named: str) -> list[dict]:
    def p(name: str, text: str) -> dict:
        return {"name": name, "type": "predicate", "instructions": text}

    return [
        p("held", "The user holds a LEGO brick in the air, not resting on the tray or the desk."),
        p("named", f"The brick the user holds is {named}."),
        {"name": "colour", "type": "choice", "instructions": "What colour is the brick the user holds? \"none\" when no brick is held.",
         "choices": [{"value": c} for c in COLOURS]},
    ]


class PickGame:
    def __init__(self, session: AgentSession, build: Build, tap: FrameTap, record: RunLog, settings: Settings,
                 timeout: float = 5.0) -> None:
        self._session, self._build, self._tap, self._record, self._s = session, build, tap, record, settings
        self._timeout = timeout
        self._key = os.environ["OPENAI_API_KEY"]
        self.voice_now = ""  # fed by gpt/agent.py as for the brain; not read here
        self._task: asyncio.Task | None = None
        self._colours = list(TRAY)
        self._picked: list[str] = []  # the colours confirmed, in order, for closing a hand-over at the end
        self._asking = False  # the sixth verdict is said and the hint is up: the wearer's next turn is the question
        self._asks = 0
        # the pick under way, written by the frame loop and read by the pacing loop
        self._n = 0  # requests made
        self._reading: tuple[float, float, str] | None = None  # (held, named, colour) of the newest frame
        self._recent: list[tuple[float, float, str]] = []  # the last AGREE readings
        self._held_at: float | None = None  # monotonic time the brick was first read as held in this pick
        self._verdict: str | None = None  # "yes", "no" or "none" once this pick is settled

    @property
    def instructions(self) -> str:
        return ("Game A has no brain: GPT-Live names the colours and says the verdicts the Decisions line gives "
                "(gpt/pick.py); the voice persona is voice.txt.")

    # ------------------------------------------------------------------ the surface gpt/agent.py expects

    def start_watching(self) -> None:
        self._task = asyncio.create_task(self._run(), name="pick")

    def stop_watching(self) -> None:
        if self._task is not None:
            self._task.cancel()

    def on_delegation(self, d) -> None:
        """GPT-Live handed the question over although its prompt tells it to answer from the conversation: closed at
        once with the list the game kept, which the voice says as its answer."""
        self._asks += 1
        words = d.pending_transcript.strip()
        logger.info("delegation: %s #%d closed at once, user: %s", d.id, self._asks, words or "(no words came with it)")
        self._record.event("delegation", n=self._asks, id=d.id, words=words)
        text = (f"You picked {', '.join(self._picked)}." if self._picked else "None of the bricks you held up was the one asked for.")
        self._record.event("commentary", n=self._asks, id=d.id, text=text, voice_speaking=self._session.agent_state == "speaking")
        self._session.current_agent.duplex_session.append_commentary(text, delegation_id=d.id)

    def wearer_said(self, text: str) -> None:
        """A turn of the wearer is in the history: after the hint, it is the question, and the build is finished so that
        the call ends once the voice has answered (gpt/agent.py)."""
        if not self._asking or self._build.finished:
            return
        self._asking = False
        self._build.step = len(self._build.guide.steps)
        self._record.event("pick_question", text=text)
        self._record.event("build", finished=True, took_s=round(time.monotonic() - self._build.started, 1))
        logger.info("pick: the question came (%s); the call ends once the voice has answered", text)
        asyncio.create_task(publish_build(self._build), name="pick_publish")

    # ------------------------------------------------------------------ the trial

    async def _run(self) -> None:
        frames = asyncio.create_task(self._frames(), name="pick_frames")
        try:
            await self._wait_quiet(START_WAIT_S)
            build = self._build
            build.hint = HINT_PICK
            for i, step in enumerate(build.guide.steps):
                colour = _colour(step.brick)
                build.step = i
                await publish_build(build)
                self._reading, self._recent, self._held_at, self._verdict = None, [], None, None
                self._record.event("name", n=i + 1, colour=colour)
                self._speak(NAME.format(colour=colour))
                logger.info("pick: %d of %d, %s", i + 1, len(build.guide.steps), colour)
                verdict = await self._settle(colour)
                if verdict == "yes":
                    self._picked.append(colour)
                    build.act_now("yes")
                    line = YES.format(colour=colour)
                elif verdict == "no":
                    build.act_now("not")
                    line = NOT.format(colour=colour)
                else:
                    line = NONE
                if i == len(build.guide.steps) - 1:
                    line += " " + LAST
                    build.hint = HINT_ASK
                    self._asking = True
                await publish_build(build)
                self._speak(line)
                if build.act:
                    build.act_now("")
                    await publish_build(build)
                if i < len(build.guide.steps) - 1:
                    await self._wait_empty()
                    await asyncio.sleep(PAUSE_S)
        finally:
            frames.cancel()

    async def _wait_quiet(self, most: float) -> None:
        """Waits for the voice to finish what it is saying (the greeting), at most `most` seconds."""
        t0 = time.monotonic()
        spoke = False
        while time.monotonic() - t0 < most:
            speaking = self._session.agent_state == "speaking"
            spoke = spoke or speaking
            if spoke and not speaking:
                return
            await asyncio.sleep(0.1)

    async def _settle(self, colour: str) -> str:
        """Waits for this pick's verdict from the frame loop: yes or no on two agreeing frames, none when the brick has
        been held HELD_MAX_S without one."""
        while True:
            if self._verdict is not None:
                return self._verdict
            if self._held_at is not None and time.monotonic() - self._held_at >= HELD_MAX_S:
                self._verdict = "none"
                self._record.event("pick_verdict", n=self._build.step + 1, colour=colour, verdict="none",
                                   read=self._reading[2] if self._reading else None, held_s=HELD_MAX_S)
                logger.info("pick: no verdict after %.0f s held: none", HELD_MAX_S)
                return "none"
            await asyncio.sleep(0.05)

    async def _wait_empty(self) -> None:
        """Waits until the hand has read empty for AGREE frames, the brick put back."""
        empty = 0
        last = None
        while empty < AGREE:
            r = self._reading
            if r is not None and r is not last:
                last = r
                empty = empty + 1 if r[0] < 0.5 else 0
            await asyncio.sleep(0.05)

    def _speak(self, line: str) -> None:
        speaking = self._session.agent_state == "speaking"
        duplex = self._session.current_agent.duplex_session
        if speaking:
            self._record.event("cut_in", text=line)
            duplex.append_instructions(CUT_IN)
        self._record.event("commentary", text=line, voice_speaking=speaking)
        duplex.append_commentary(line)

    # ------------------------------------------------------------------ the frames

    async def _frames(self) -> None:
        """One Decisions request after the other on the newest frame, as gpt/moments.py does, with this game's
        questions about the colour named now; writes the readings for the pacing loop and settles the verdict."""
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self._timeout, headers=headers) as http:
            while True:
                frame, seq, at = self._tap.latest, self._tap.count, self._tap.latest_at
                step = self._build.step
                if frame is None or step >= len(self._build.guide.steps) or self._asking:
                    await asyncio.sleep(0.25)
                    continue
                self._n += 1
                try:
                    await self._one(http, self._n, step, frame, seq, at)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning("pick: frame #%d failed (%s: %s)", self._n, type(e).__name__, str(e)[:200])
                    self._record.event("pick_failed", n=self._n, error=f"{type(e).__name__}: {e}"[:300])
                    await asyncio.sleep(0.5)

    async def _one(self, http: httpx.AsyncClient, n: int, step: int, frame, seq: int, at: float) -> None:
        named = _colour(self._build.guide.steps[step].brick)
        t0 = time.perf_counter()
        photo = await asyncio.to_thread(_jpeg, frame, self._s.moments_side)
        body = {"model": self._s.moments_model,
                "input": [{"role": "developer", "content": developer_text(self._colours, named)},
                          {"role": "user", "content": [{"type": "input_image", "detail": self._s.moments_detail,
                                                        "image_url": "data:image/jpeg;base64," + base64.b64encode(photo).decode()}]}],
                "questions": questions(named)}
        t_sent = time.perf_counter()
        r = await http.post(URL, json=body)
        ms = round((time.perf_counter() - t_sent) * 1000)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        a = {x.get("name"): x for x in data.get("answers", [])}
        if any(x.get("type") == "refusal" for x in a.values()):
            raise RuntimeError("a question was refused")
        held, is_named = a["held"]["probability"], a["named"]["probability"]
        colour = a["colour"]["choice"]
        colour_p = next((x["probability"] for x in a["colour"]["probabilities"] if x["value"] == colour), 0.0)
        self._record.event("pick_frame", n=n, pick=step + 1, named=named, frame=seq, frame_age_ms=round((time.monotonic() - at) * 1000),
                           prep_ms=round((t_sent - t0) * 1000), ms=ms, tokens=(data.get("usage") or {}).get("input_tokens"),
                           held=round(held, 2), is_named=round(is_named, 2), colour=colour, colour_p=round(colour_p, 2))
        logger.info("pick: #%d pick %d (%s) frame %d, %d ms: held %.2f named %.2f colour %s (%.2f)", n, step + 1, named, seq,
                    ms, held, is_named, colour, colour_p)
        if step != self._build.step:
            return  # the pick moved on while the request was out
        reading = (held, is_named, colour)
        self._reading = reading
        self._recent = (self._recent + [reading])[-AGREE:]
        if self._verdict is not None:
            return
        if held >= self._s.moments_sure and self._held_at is None:
            self._held_at = time.monotonic()
            self._record.event("pick_held", n=n, pick=step + 1, frame=seq, held=round(held, 2))
            logger.info("pick: a brick is held (held %.2f)", held)
        two = self._recent[-2:]
        if len(two) < 2 or not all(h >= self._s.moments_sure and c not in NO_BRICK for h, _, c in two):
            return
        if all(p >= self._s.moments_yes_at for _, p, _ in two):
            verdict = "yes"
        elif all(p <= self._s.moments_not_at for _, p, _ in two):
            verdict = "no"
        else:
            return
        self._verdict = verdict
        saved = self._record.photo(photo, f"pick{n}-p{step + 1}")
        self._record.event("pick_verdict", n=n, pick=step + 1, colour=named, verdict=verdict, is_named=round(is_named, 2),
                           read=colour, frame=seq, photo=saved)
        logger.info("pick: %s for %s (named %.2f, read %s, photo %s)", verdict, named, is_named, colour, saved)
