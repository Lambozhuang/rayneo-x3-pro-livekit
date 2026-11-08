"""Game B of the user study, "place the brick": one anchor brick fixed on the plate, one movable brick, six rounds.

    glasses --video--> FrameTap --> gpt/moments.py: every frame, "the movable brick is on the plate with no hand on it"
                                        --two frames in a row--> PlaceGame.look_now(frame): one judgement of that frame
                                        --the reading drops after a "right"--> PlaceGame.lifted(): the next round's picture
    PlaceGame --one request: this round's target and the photo, nothing of the rounds before--> the brain's model
              <--verdict: right / off / cannot_tell--
              --> GPT-Live: the verdict's line as a commentary, which the voice says in its own words
              --> the glasses: the next round's picture (Build.picture) and the hint line (Build.hint)
              --> the record: judge_sent, verdict, step, picture, round; the frame judged saved as judge<n>-r<round>.jpg

Each round the glasses show where the movable brick goes against the anchor, and the hint line says where to put it
first, one row or one column off the target. The participant puts it there and takes the hand away, hears that it is
off, moves it onto the target, hand away, hears that it is right, lifts it, and the next picture comes; with the sixth
round's "right" the voice says the game is over, and the call ends by itself (gpt/agent.py, Build.over). The
judge gets the round's target and the one frame, with no memory of the rounds before, so it cannot learn that the
first placement of a round is always off. The study's game-spec.md (outside the repo) fixes what affects the
measurement; the truth of a placement is labelled afterwards from the saved frame, not taken from the instruction.

The class stands where Brain stands: for gpt/agent.py it has start_watching, stop_watching, voice_now, on_delegation
and instructions, for gpt/moments.py look_now and lifted, so the call is wired the same way as a build's.
"""

import asyncio
import io
import json
import logging
import time

from livekit.agents import AgentSession

from frames import bottom_square
from gpt.brain import Look, handed_back
from gpt.prompts import CUT_IN, PLACE_DONE, PLACE_PHRASES, VERDICT, place_judge
from guide import Build, publish_build, send_picture
from runlog import RunLog

logger = logging.getLogger("rayneo-agent.place")

REARM_S = 2.0  # after a "cannot tell" or a failed request, how long before the same placement is judged again

# The glasses' hint line through a round (Build.hint, the line above the dots): where to put the brick first, one row or
# one column off the target as the round's file says (Step.offset), then onto it, then up. The wording is Lambo's
# (2026-11-08).
HINT_OFF = "Round {n} of {total}. Put the {brick} {offset}. Hand away."
HINT_ONTO = "Now put it on the target. Hand away."
HINT_LIFT = "Lift the brick."


def _jpeg(frame, side: int) -> bytes:
    buf = io.BytesIO()
    bottom_square(frame, side).save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _brick_word(brick: str) -> str:
    """A brick's name for the hint line, its colour and the word brick: "red 2x4" is "red brick"."""
    return brick.rsplit(" ", 1)[0] + " brick"


class PlaceGame:
    """Plays one trial of the game: six rounds of one placement each, judged when the second line says the brick lies
    on the plate with the hand gone. `side` is the judged photo's side in px, `effort` the model's reasoning effort,
    `timeout` the seconds one judgement may take."""

    def __init__(self, session: AgentSession, build: Build, model, effort: str, side: int, language: str,
                 timeout: float, record: RunLog) -> None:
        self._session, self._build, self._model, self._effort, self._side = session, build, model, effort, side
        self._language, self._timeout, self._record = language, timeout, record
        self.voice_now = ""  # what the voice is saying (gpt/agent.py feeds it, as it does the brain); not read here
        self.moments = None  # the second line, set by gpt/agent.py: it calls look_now and lifted, and is rearmed after a cannot_tell
        self._judge: asyncio.Task | None = None  # the judgement running, if any
        self._n = 0  # judgements asked for in this call
        self._lift_pending = False  # a round was judged right: the next picture waits for the brick to be lifted
        self._last_line: str | None = None  # the last phrase given to the voice, repeated to close a hand-over
        self._asks = 0  # hand-overs GPT-Live made all the same

    @property
    def instructions(self) -> str:
        """The judge's instructions for round 1, for the record (brain.txt); every round gets its own target."""
        return place_judge(self._build.guide, 0, self._language)

    # ------------------------------------------------------------------ the surface gpt/agent.py expects of the brain

    def start_watching(self) -> None:
        """The game begins: the first round's picture and hint go to the glasses."""
        asyncio.create_task(self._next_round(), name="place_round")

    def stop_watching(self) -> None:
        if self._judge is not None:
            self._judge.cancel()

    def on_delegation(self, d) -> None:
        """GPT-Live handed the user's words over although its prompt tells it not to: closed at once with the last
        line again, as the brain does (brain.py on_delegation)."""
        self._asks += 1
        words = d.pending_transcript.strip()
        logger.info("delegation: %s #%d closed at once, user: %s", d.id, self._asks, words or "(no words came with it)")
        self._record.event("delegation", n=self._asks, id=d.id, words=words)
        text = handed_back(self._last_line)
        self._record.event("commentary", n=self._asks, id=d.id, text=text,
                           voice_speaking=self._session.agent_state == "speaking")
        self._session.current_agent.duplex_session.append_commentary(text, delegation_id=d.id)

    # ------------------------------------------------------------------ what the second line calls

    def look_now(self, frame, seq: int, at: float) -> None:
        """The movable brick lies on the plate with no hand on it (gpt/moments.py): judge this frame, unless a
        judgement is running, the round waits for the lift, or the game is over."""
        if self._build.finished or self._lift_pending or (self._judge is not None and not self._judge.done()):
            logger.info("place: frame %d not judged: %s", seq, "the game is over" if self._build.finished else
                        "the round waits for the lift" if self._lift_pending else "a judgement is running")
            return
        self._n += 1
        self._judge = asyncio.create_task(self._judge_frame(self._n, frame, seq, at), name="place_judge")

    def lifted(self) -> None:
        """The reading of the brick on the plate dropped: after a "right" the brick is up and the next round begins."""
        if self._lift_pending and not self._build.finished:
            self._lift_pending = False
            asyncio.create_task(self._next_round(), name="place_round")

    # ------------------------------------------------------------------ rounds

    async def _next_round(self) -> None:
        """The round the build stands on begins: its picture and hint go to the glasses, the picture's name first as an
        attribute and then its bytes (guide.py send_picture)."""
        build = self._build
        n, total = build.step + 1, len(build.guide.steps)
        target = build.guide.steps[n - 1]
        build.hint = HINT_OFF.format(n=n, total=total, brick=_brick_word(target.brick), offset=target.offset)
        build.show(n)
        await publish_build(build)
        sent = await send_picture(build, n)
        self._record.event("picture", step=n, **sent)
        self._record.event("round", n=n, total=total, target=target.place, offset=target.offset, hint=build.hint)
        logger.info("place: round %d of %d, target: %s; first %s", n, total, target.place, target.offset)

    async def _judge_frame(self, n: int, frame, seq: int, at: float) -> None:
        """One judgement: the frame's bottom square and this round's target to the model, its verdict to the voice as
        the phrase, to the glasses as the dots' "looking" while it lasts and as the hint, and to the record with the
        photo. A "right" moves the round; a "cannot tell" or a failed request has the placement judged again."""
        build = self._build
        r = build.step
        target = build.guide.steps[r]
        build.act_now("looking")
        await publish_build(build)
        t0 = time.perf_counter()
        photo = await asyncio.to_thread(_jpeg, frame, self._side)
        saved = self._record.photo(photo, f"judge{n}-r{r + 1}")
        age_ms = round((time.monotonic() - at) * 1000)
        self._record.event("judge_sent", n=n, round=r + 1, frame=seq, frame_age_ms=age_ms, side=self._side, photo=saved,
                           photo_kb=len(photo) // 1024, target=target.place)
        logger.info("place: judge #%d round %d frame %d (%d ms old): jpeg %d KB at %d px, photo %s", n, r + 1, seq,
                    age_ms, len(photo) // 1024, self._side, saved)
        look = Look(text=f"Round {r + 1}. The photo:", photo=photo)
        try:
            reply, calls, _, u = await asyncio.wait_for(
                self._model.ask(place_judge(build.guide, r, self._language), [look], [VERDICT], self._effort,
                                f"{build.run}-r{r + 1}"),
                self._timeout)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("place: judge #%d failed (%s: %s)", n, type(e).__name__, str(e)[:200])
            self._record.event("judge_failed", n=n, round=r + 1, error=f"{type(e).__name__}: {e}"[:500])
            build.act_now("")
            await publish_build(build)
            self._rearm_later()
            return
        ms = round((time.perf_counter() - t0) * 1000)
        call = next((a for _, name, a in calls if name == "verdict"), {})
        verdict, seen = call.get("verdict"), call.get("seen")
        if verdict not in PLACE_PHRASES:
            logger.warning("place: judge #%d gave no verdict (tool calls %s): taken as cannot_tell", n,
                           json.dumps([name for _, name, _ in calls]))
            verdict = "cannot_tell"
        self._record.event("verdict", n=n, round=r + 1, frame=seq, verdict=verdict, seen=seen, ms=ms, reply=reply,
                           photo=saved, usage=u)
        logger.info("place: judge #%d round %d after %d ms: %s (%s); in=%d (cached %d) out=%d", n, r + 1, ms, verdict,
                    seen, u["in"], u["cached"], u["out"])
        build.act_now("")
        if verdict == "right":
            build.set_step(r + 1)  # takes the picture off the glasses; the next one comes when the brick is lifted
            self._record.event("step", done=build.step, now=None if build.finished else build.step + 1)
            if build.finished:
                self._record.event("build", finished=True, took_s=round(time.monotonic() - build.started, 1))
                build.hint = ""
            else:
                self._lift_pending = True
                build.hint = HINT_LIFT
        elif verdict == "off":
            build.hint = HINT_ONTO
        else:
            self._rearm_later()
        await publish_build(build)
        self._speak(PLACE_PHRASES[verdict] + (" " + PLACE_DONE if build.finished else ""), n)

    def _rearm_later(self) -> None:
        """A judgement that settled nothing: the same placement is judged again if the reading still holds REARM_S
        later (gpt/moments.py rearm)."""
        async def rearm() -> None:
            await asyncio.sleep(REARM_S)
            if self.moments is not None:
                self.moments.rearm()

        asyncio.create_task(rearm(), name="place_rearm")

    def _speak(self, line: str, n: int) -> None:
        """The phrase to the voice as a commentary, cutting into a sentence in progress as the brain's lines do."""
        speaking = self._session.agent_state == "speaking"
        duplex = self._session.current_agent.duplex_session
        if speaking:
            self._record.event("cut_in", judge=n, text=line)
            duplex.append_instructions(CUT_IN)
        self._record.event("commentary", judge=n, text=line, voice_speaking=speaking)  # `judge`, not `n`: deploy/report.py counts an `n` as a hand-over
        duplex.append_commentary(line)
        self._last_line = line
