"""One question to the brain's model, with the newest frame: the words the eyes (eyes.py) cannot produce.

The eyes read the state of the desk through the Decisions API and say what happened; two things take a model that
writes: what is wrong with a misplaced brick and how to fix it, and the answer to the wearer's question about what is
in front of them. For those the eyes call `Consult.ask` once, with the frame, the task, the step, the eyes' latest
reading, the last lines said and what is asked, and get back one sentence for the voice, or nothing when the model
has nothing to add. The model may also move the progress (set_progress), when it finds the placement right after all
or a step undone. No conversation is kept between consults: the eyes hold the state, each request stands alone, and
the model's reasoning is off (BRAIN_EFFORT none) so the sentence comes in about 1.3 s over the WebSocket.

The model is the brain's (BRAIN_MODEL, gpt-6.1-terra, BRAIN_SERVICE_TIER, BRAIN_TRANSPORT), through brain.py's
clients, which also serve the watch-loop brain of the earlier design that eval/brain-thread-replay/ and
eval/brain-speed/ replay.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time
from typing import Awaitable, Callable

from frames import FrameTap, bottom_square
from gpt.brain import SAY, SET_PROGRESS, Look
from gpt.prompts import consult_instructions
from guide import Build
from runlog import RunLog

logger = logging.getLogger("rayneo-agent.consult")

TOOLS = [SET_PROGRESS, SAY]
WHO = {"user": "User", "assistant": "Assistant"}
LINES_BACK = 8  # how many of the last lines said go into a consult


class Consult:
    def __init__(self, session, build: Build, tap: FrameTap, model, effort: str, side: int, language: str,
                 record: RunLog, progress: Callable[[int, str, str], Awaitable[None]]) -> None:
        self._session, self._build, self._tap = session, build, tap
        self._model, self._effort, self._side = model, effort, side
        self._record = record
        self._progress = progress  # eyes.progress: moves the build and tells the voice
        self._instructions = consult_instructions(build.guide, language)
        self._n = 0

    @property
    def instructions(self) -> str:
        return self._instructions

    def _lines(self) -> str:
        items = [i for i in self._session.history.items
                 if i.type == "message" and i.role in ("user", "assistant") and (i.text_content or "").strip()]
        return "\n".join(f"{WHO[i.role]}: {' '.join(i.text_content.split())}" for i in items[-LINES_BACK:]) or "No one has spoken yet."

    async def ask(self, reason: str, reading, question: str) -> str | None:
        """One request on the newest frame. Returns the line for the voice ("Camera: ...") or None."""
        self._n += 1
        n = self._n
        build = self._build
        frame = self._tap.latest
        if frame is None:
            return None
        t0 = time.perf_counter()
        photo = await asyncio.to_thread(self._jpeg, frame)
        step = min(build.step + 1, len(build.guide.steps))
        text = (f"The user is on step {step} ({build.guide.steps[step - 1].brick}); {build.step} of {len(build.guide.steps)} steps are "
                f"recorded as built right.\n" + (reading.line(build.guide) + "\n" if reading else "")
                + f"The last lines said:\n{self._lines()}\n\n{question}")
        look = Look(text=text, photo=photo)
        saved = self._record.photo(photo, f"consult{n}-s{step}")
        self._record.event("consult_sent", n=n, reason=reason, step=step, photo=saved, text=text)
        try:
            reply, calls, _, u = await self._model.ask(self._instructions, [look], TOOLS, self._effort, build.run)
        except BaseException as e:
            self._record.event("consult_failed", n=n, reason=reason, error=f"{type(e).__name__}: {e}"[:300])
            raise
        ms = round((time.perf_counter() - t0) * 1000)
        self._record.event("consult_back", n=n, ms=ms, reply=reply, calls=[[c, a] for _, c, a in calls], usage=u)
        logger.info("consult: #%d %s in %d ms: %s %s", n, reason, ms, reply, json.dumps([[c, a] for _, c, a in calls]))
        line = None
        for _, name, args in calls:
            if name == "say" and str(args.get("text") or "").strip():
                line = f"Camera: {' '.join(str(args['text']).split())}"
            elif name == "set_progress" and isinstance(args.get("done"), int):
                done = args["done"]
                if 0 <= done <= len(build.guide.steps) and done != build.step:
                    if done > build.step:
                        await self._progress(done, args.get("seen") or reply, "consult")
                    else:
                        build.set_step(done)
                        self._record.event("step", done=None, reopened=build.step + 1, now=build.step + 1,
                                           seen=args.get("seen"), basis="consult")
                        from guide import publish_build
                        await publish_build(build)
                        total = len(build.guide.steps)
                        line = (line or "") + f" Progress: {build.step} of {total} steps done; the user is on step {build.step + 1} ({build.guide.steps[build.step].brick})."
        return line.strip() if line else None

    def _jpeg(self, frame) -> bytes:
        buf = io.BytesIO()
        bottom_square(frame, self._side).save(buf, "JPEG", quality=85)
        return buf.getvalue()
