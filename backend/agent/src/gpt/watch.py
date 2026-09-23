"""Watch mode: the camera is checked while nobody is talking, so the answer is
ready before the wearer asks.

v1 was passive: the wearer said "done", the voice said "hang on", the backend
called check_step, the vision model took three seconds, the backend answered,
the voice spoke: about nine seconds of waiting for every step. Here a loop runs
the same vision check every few seconds while the agent is not speaking and
keeps the latest verdict per step. check_step (tools.py) answers from that
cache when it is fresh, so the wearer's "done" costs no vision time; and when
two consecutive checks say `built`, the code advances the step and asks the
voice model to tell the wearer, before they ask. Nothing proactive is said on
`not_built`: while a step is being built the brick is not there yet, and the
wearer asks when they want a verdict.

The voice model may decline to speak the announcement (commentary is a request).
Then the step has moved on in the code but the wearer has not heard it:
`pending` records that, and check_step / get_step deliver it on the next turn
instead of judging the new step against an old picture.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from livekit.agents import AgentSession

from gpt.vision import Verdict, VisionCheck
from guide import Build

logger = logging.getLogger("rayneo-agent.watch")


@dataclass
class Watcher:
    session: AgentSession
    build: Build
    vision: VisionCheck
    publish: callable  # async: push the build's position to the glasses
    enabled: bool = True
    interval: float = 4.0  # seconds between the end of one check and the next
    fresh: float = 8.0  # how old a cached verdict may be when a tool uses it
    last: Verdict | None = None
    last_at: float = 0.0
    last_step: int = -1
    pending: tuple[int, str] | None = None  # (step number, what was seen): advanced, not yet told
    _streak: int = 0
    _lock: asyncio.Lock | None = None
    _task: asyncio.Task | None = None

    def __post_init__(self) -> None:
        self._lock = asyncio.Lock()

    def start(self) -> None:
        if self.enabled and self._task is None:
            self._task = asyncio.create_task(self._run(), name="watch")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def fresh_verdict(self) -> Verdict | None:
        if self.last is not None and self.last_step == self.build.step and time.monotonic() - self.last_at < self.fresh:
            return self.last
        return None

    async def check(self, question: str | None = None) -> Verdict:
        """A verdict for the current step: the cached one if fresh, else a new
        check. Serialised with the watch loop, so a tool call that arrives
        during a watch check waits for it and gets that result."""
        assert self._lock is not None
        async with self._lock:
            if question is None and (v := self.fresh_verdict()) is not None:
                logger.info("check: step %d/%d from watch cache, %.1fs old", self.build.step + 1, len(self.build.guide.steps), time.monotonic() - self.last_at)
                return v
            v = await self.vision.check(self.build, question)
            if question is None:
                self._remember(v)
            return v

    def _remember(self, v: Verdict) -> None:
        self.last, self.last_at, self.last_step = v, time.monotonic(), self.build.step

    async def _run(self) -> None:
        assert self._lock is not None
        logger.info("watch: on, interval=%.0fs fresh=%.0fs", self.interval, self.fresh)
        while not self.build.finished:
            await asyncio.sleep(self.interval)
            if self.session.agent_state == "speaking" or self._lock.locked():
                continue
            try:
                async with self._lock:
                    v = await self.vision.check(self.build)
                    self._remember(v)
            except asyncio.TimeoutError:
                continue  # no camera frame; the tools report that when asked
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("watch: check failed")
                await asyncio.sleep(self.interval)
                continue
            self._streak = self._streak + 1 if v.state == "built" else 0
            if self._streak >= 2:
                await self._advance(v)
        logger.info("watch: build finished, stopping")

    async def _advance(self, v: Verdict) -> None:
        build = self.build
        n = build.step + 1
        build.complete_step()
        await self.publish(build)
        self._streak = 0
        self.last = None
        self.pending = (n, v.what_i_see)
        logger.info("watch: step %d built twice in a row, advanced; telling the wearer", n)
        if build.finished:
            text = (
                f"The camera shows step {n} is built: {v.what_i_see} That was the last step. Tell the "
                "wearer it is right and the build is finished, and congratulate them."
            )
        else:
            text = (
                f"The camera shows step {n} is built: {v.what_i_see} Tell the wearer in one sentence "
                f"that it is right, then give them the next step. {build.describe()}"
            )
        handle = self.session.generate_reply(instructions=text)
        await handle
        if handle.exception() is None:
            self.pending = None
        else:
            logger.warning("watch: the voice model declined to announce step %d; the tools will", n)
