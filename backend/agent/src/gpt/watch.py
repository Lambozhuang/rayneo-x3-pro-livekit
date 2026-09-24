"""The loop that looks and tells.

Frame in, vision verdict out, verdict into GPT-Live's context, next frame. No
tools, no requests, no waiting: the voice model always has a note a few
seconds old on how far the build has got, and it decides on its own whether to
speak. The process does three things: takes the next camera frame, asks the
vision model (vision.py), and hands the answer over:

- every verdict goes in as *thinking*: silent context the model uses when it
  matters (the wearer asks "done?", it answers from the newest note);
- a step newly complete, or a brick newly placed wrongly, goes in as
  *commentary*: something to say now, in the model's own words. Both need
  `confirm` consecutive frames agreeing, so a hand passing over the bricks
  does not become an announcement.

The step index the glasses show (Build) follows the vision model's count of
completed steps; the code keeps no opinion of its own.
"""

from __future__ import annotations

import asyncio
import logging

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
        self._agree = 0  # consecutive frames with the same (steps_done, problem or not)
        self._told_problem_at: tuple[int, str] | None = None  # (steps_done, problem) already announced

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="watch")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        logger.info("watch: on, gap=%.1fs confirm=%d", self._gap, self._confirm)
        while True:
            if self._gap:
                await asyncio.sleep(self._gap)
            try:
                frame = await self._tap.next_frame(3.0)
            except asyncio.TimeoutError:
                continue
            jpeg = await asyncio.to_thread(images.encode, frame, FRAME_ENCODE_OPTIONS)
            expected = self._build.step + 1
            try:
                s = await self._eyes.look(jpeg, expected)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("watch: vision call failed")
                await asyncio.sleep(2)
                continue
            self._tap.dump(jpeg, f"s{expected}")
            total = len(self._build.guide.steps)
            logger.info(
                "camera: done=%d/%d visible=%s %.1fs in=%d out=%d see=%s%s",
                s.steps_done, total, s.visible, s.seconds, *s.tokens, s.what_i_see,
                f" problem={s.problem}" if s.problem else "",
            )
            for o in s.observations:
                logger.info("camera:   - %s", o)
            await self._digest(s)

    async def _digest(self, s: Sight) -> None:
        build = self._build
        total = len(build.guide.steps)
        prev = self.last
        self.last = s
        if not s.visible:
            if prev is None or prev.visible:
                self._think("Camera: the build is not in view right now.")
            self._agree = 0
            return
        same = prev is not None and prev.visible and prev.steps_done == s.steps_done and bool(prev.problem) == bool(s.problem)
        self._agree = self._agree + 1 if same else 1
        confirmed = self._agree >= self._confirm

        note = f"Camera: {s.steps_done} of {total} steps done. {s.what_i_see}"
        if s.problem:
            note += f" Something is off: {s.problem}"

        if confirmed and s.steps_done != build.step:
            went_up = s.steps_done > build.step
            build.set_step(s.steps_done)
            await self._publish(build)
            self._told_problem_at = None
            if went_up:
                if build.finished:
                    self._say(f"Camera: the last step is done: {s.what_i_see} Tell the wearer the build is finished and congratulate them.")
                else:
                    nxt = build.guide.steps[build.step]
                    self._say(
                        f"Camera: step {s.steps_done} is done: {s.what_i_see} Tell the wearer it is right, "
                        f"then give step {build.step + 1}: {nxt.say}"
                    )
                return
        if confirmed and s.problem and self._told_problem_at != (s.steps_done, s.problem):
            self._told_problem_at = (s.steps_done, s.problem)
            self._say(f"Camera, on step {s.steps_done + 1}: {s.problem} Tell the wearer in one short sentence.")
            return
        self._think(note)

    def _think(self, text: str) -> None:
        try:
            self._session.current_agent.duplex_session.append_thinking(text)
        except Exception:
            logger.exception("watch: append_thinking failed")

    def _say(self, text: str) -> None:
        logger.info("watch: commentary: %s", text)
        handle = self._session.generate_reply(instructions=text)

        def _done(h) -> None:
            if h.exception() is not None:
                logger.warning("watch: the voice model declined the commentary")

        handle.add_done_callback(_done)
