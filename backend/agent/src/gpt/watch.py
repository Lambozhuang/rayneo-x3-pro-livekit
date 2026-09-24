"""The loop that looks and tells.

Frame in, vision verdict out, verdict into GPT-Live's context, next frame. No
tools, no requests, no waiting: the voice model always has a note a few
seconds old on how far the build has got, and it decides on its own whether to
speak. The process does three things: takes the next camera frame, asks the
vision model (vision.py), and hands the answer over:

- nothing goes in per frame. Every frame's verdict as thinking made the voice
  narrate the camera ("I'm still seeing just the yellow") from notes a few
  seconds stale, then contradict itself when the confirmed change arrived.
  What the voice needs is the confirmed state, and it has it: if no note has
  said the step is done, it is not done;
- a step newly complete, or a brick newly placed wrongly, goes in as
  *commentary*: something to say now, in the model's own words. A step
  forward needs `confirm` consecutive frames agreeing; a step back needs twice
  that and is never announced (the model can see it in the thinking); a
  wrongly placed brick is announced once per visit to a step, however the
  vision model words it from frame to frame. Commentary waits while the voice
  is speaking, and only the newest one is kept: two verdicts a few seconds
  apart must not become two overlapping corrections.

The step index the glasses show (Build) follows the vision model's count of
completed steps; the code keeps no opinion of its own.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from collections import deque

from livekit.agents import AgentSession
from livekit.agents.utils import images

from frames import FrameTap
from gpt.config import FRAME_ENCODE_OPTIONS
from gpt.vision import Eyes, Sight
from guide import Build

logger = logging.getLogger("rayneo-agent.watch")


class Watch:
    def __init__(
        self, session: AgentSession, build: Build, eyes: Eyes, tap: FrameTap, publish,
        gap: float = 0.0, confirm: int = 2,
    ) -> None:
        self._session = session
        self._build = build
        self._eyes = eyes
        self._tap = tap
        self._publish = publish
        self._gap = gap
        self._confirm = max(1, confirm)
        self._task: asyncio.Task | None = None
        self.last: Sight | None = None
        self._earlier: deque[bytes] = deque(maxlen=2)  # the last frames, small, for continuity
        self._said: deque[tuple[float, str]] = deque(maxlen=3)  # (when, what) the wearer said
        self._last_note = ""
        self._agree = 0  # consecutive frames with the same (steps_done, problem or not)
        self._unseen = 0  # consecutive frames without the build in view
        self._told_problem_at: int | None = None  # steps_done at which a problem was already announced
        self._pending_say: str | None = None  # commentary held back while the voice speaks
        self._announced_step: int | None = None  # a step advance the voice already told (via check_now)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="watch")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def check_now(self) -> str:
        """What the camera sees right now, for the voice when the wearer asks.
        Takes a fresh frame at once and asks the vision model in parallel with
        whatever the loop has in flight, so the answer costs one look, not the
        rest of the current one plus another."""
        build = self._build
        total = len(build.guide.steps)
        try:
            s = await self._look_once()
        except asyncio.TimeoutError:
            return "The camera gave no frame; tell the wearer to hold the bricks in view and ask again."
        except Exception:
            logger.exception("check_now: vision call failed")
            return "The camera check failed; tell the wearer to ask again in a moment."
        if s.steps_done > build.step:
            # the voice will confirm from this answer; the loop must not announce it again
            self._announced_step = s.steps_done
        await self._digest(s)
        if not s.visible:
            return "The camera cannot see the build right now; ask the wearer to bring the bricks into view."
        text = f"Camera now: {s.steps_done} of {total} steps done. {s.what_i_see}"
        if s.problem:
            text += f" Something is off: {s.problem}"
        elif s.steps_done < total:
            text += f" Step {s.steps_done + 1} is not done yet."
        return text

    async def _look_once(self) -> Sight:
        """One fresh frame through the vision model, logged; raises on no frame."""
        frame = await self._tap.next_frame(3.0)
        jpeg = await asyncio.to_thread(images.encode, frame, FRAME_ENCODE_OPTIONS)
        expected = self._build.step + 1
        said = [t for at, t in self._said if time.monotonic() - at < 20]
        s = await self._eyes.look(jpeg, expected, self.last, said, list(self._earlier))
        self._tap.dump(jpeg, f"s{expected}")
        self._earlier.append(await asyncio.to_thread(_thumbnail, jpeg))
        total = len(self._build.guide.steps)
        logger.info(
            "camera: done=%d/%d visible=%s %.1fs in=%d out=%d see=%s%s",
            s.steps_done, total, s.visible, s.seconds, *s.tokens, s.what_i_see,
            f" problem={s.problem}" if s.problem else "",
        )
        for o in s.observations:
            logger.info("camera:   - %s", o)
        return s

    def note_user(self, text: str) -> None:
        """What the wearer said, for the vision model's next look."""
        if text.strip():
            self._said.append((time.monotonic(), text.strip()))

    async def _run(self) -> None:
        logger.info("watch: on, gap=%.1fs confirm=%d", self._gap, self._confirm)
        while True:
            if self._gap:
                await asyncio.sleep(self._gap)
            try:
                s = await self._look_once()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("watch: vision call failed")
                await asyncio.sleep(2)
                continue
            await self._digest(s)

    async def _digest(self, s: Sight) -> None:
        build = self._build
        total = len(build.guide.steps)
        prev = self.last
        self.last = s
        if not s.visible:
            self._unseen += 1
            if self._unseen == 3:
                self._think("Camera: the build has been out of view for a while.")
            self._agree = 0
            return
        if self._unseen >= 3:
            self._think("Camera: the build is in view again.")
        self._unseen = 0
        same = prev is not None and prev.visible and prev.steps_done == s.steps_done and bool(prev.problem) == bool(s.problem)
        self._agree = self._agree + 1 if same else 1
        # forward on `confirm` frames; backward only on twice as many: a hand,
        # an angle or a lifted brick must not undo a step
        needed = self._confirm if s.steps_done >= build.step else 2 * self._confirm
        confirmed = self._agree >= needed

        if confirmed and s.steps_done != build.step:
            went_up = s.steps_done > build.step
            build.set_step(s.steps_done)
            await self._publish(build)
            self._told_problem_at = None
            if went_up:
                if self._announced_step == s.steps_done:
                    self._announced_step = None
                    return  # the voice already told the wearer, from check_now
                if build.finished:
                    self._say(f"Camera: the last step is done: {s.what_i_see} Tell the wearer the build is finished and congratulate them.")
                else:
                    nxt = build.guide.steps[build.step]
                    self._say(
                        f"Camera: step {s.steps_done} is done: {s.what_i_see} Tell the wearer it is right, "
                        f"then give step {build.step + 1}: {nxt.say}"
                    )
                return
            # a step back: the model may use it when asked, we do not announce it
            self._think(f"Camera: the build is back at {s.steps_done} of {total} steps done. {s.what_i_see}")
            return
        if confirmed and s.problem and self._told_problem_at != s.steps_done:
            self._told_problem_at = s.steps_done
            self._say(f"Camera, on step {s.steps_done + 1}: {s.problem} Tell the wearer in one short sentence.")

    def _think(self, text: str) -> None:
        if text == self._last_note:  # the model has this already
            return
        self._last_note = text
        try:
            self._session.current_agent.duplex_session.append_thinking(text)
        except Exception:
            logger.exception("watch: append_thinking failed")

    def _say(self, text: str) -> None:
        """Commentary, once the voice is quiet. A newer one replaces a held one."""
        if self._session.agent_state == "speaking":
            if self._pending_say is None:
                asyncio.create_task(self._say_when_quiet(), name="say_when_quiet")
            self._pending_say = text
            return
        self._say_now(text)

    async def _say_when_quiet(self) -> None:
        t0 = time.monotonic()
        while self._session.agent_state == "speaking" and time.monotonic() - t0 < 20:
            await asyncio.sleep(0.1)
        text, self._pending_say = self._pending_say, None
        if text:
            self._say_now(text)

    def _say_now(self, text: str) -> None:
        logger.info("watch: commentary: %s", text)
        handle = self._session.generate_reply(instructions=text)

        def _done(h) -> None:
            if h.exception() is not None:
                logger.warning("watch: the voice model declined the commentary")

        handle.add_done_callback(_done)


def _thumbnail(jpeg: bytes) -> bytes:
    from PIL import Image

    im = Image.open(io.BytesIO(jpeg))
    im.thumbnail((512, 512))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=70)
    return buf.getvalue()
