"""The brain: what GPT-Live hands over (client delegation) is answered here, from the camera.

GPT-Live cannot see. When the wearer says something that needs eyes ("is this
right?", "where does it go?", "what is this?"), it delegates; the plugin emits
`delegation_created` with an id and the wearer's words so far. The brain then
takes the next camera frame (taken after the ask), and makes one stateless
vision call:

    instructions  rules + the whole task file                 fixed, so the prompt cache hits
    input         the timeline of the call (both speakers, what the brain saw and said)
                  + the current step + the wearer's words + the frame

and gets back JSON {seen, say, step, end_call}. `say` goes back to GPT-Live as
commentary on that delegation id (it says it in its own words); a step change
is published to the glasses and told to GPT-Live as one silent thinking line;
end_call closes the room after the goodbye. The timeline only grows at the
end, and no image is kept in it: what a look saw survives as its `seen` line.

The newest delegation wins: a call still running when the next arrives is
cancelled. A call that fails or takes longer than TIMEOUT answers "I could
not see that, ask again".
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import time

from livekit.agents import AgentSession, get_job_context
from openai import AsyncOpenAI
from PIL import Image

from frames import FrameTap, to_image
from gpt.prompts import brain_instructions
from guide import Build

logger = logging.getLogger("rayneo-agent.brain")

TIMEOUT = 8.0  # the whole answer: frame + model call
FRAME_WAIT = 1.0

SCHEMA = {
    "type": "object",
    "properties": {
        "seen": {"type": "string"},
        "say": {"type": "string"},
        "step": {"type": "integer"},
        "end_call": {"type": "boolean"},
    },
    "required": ["seen", "say", "step", "end_call"],
    "additionalProperties": False,
}


async def publish_build(build: Build) -> None:
    """The run's position to the glasses, as participant attributes (Build.attributes)."""
    await get_job_context().room.local_participant.set_attributes(build.attributes())


def _jpeg(frame, side: int) -> bytes:
    img = to_image(frame)
    img.thumbnail((side, side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


class Brain:
    def __init__(self, session: AgentSession, build: Build, tap: FrameTap, client: AsyncOpenAI,
                 model: str, effort: str, detail: str, side: int, language: str) -> None:
        self._session = session
        self._build = build
        self._tap = tap
        self._client = client
        self._model = model
        self._effort = effort
        self._detail = detail
        self._side = side
        self._instructions = brain_instructions(build.guide, language)
        self._t0 = time.monotonic()
        self._timeline: list[str] = []
        self._task: asyncio.Task | None = None
        self._asks = 0
        self._closing = False

    # ------------------------------------------------------------------ the timeline

    def note(self, who: str, text: str) -> None:
        """One line of the call's timeline: who said or did what, at mm:ss since the call started."""
        text = " ".join(text.split())
        if not text:
            return
        t = int(time.monotonic() - self._t0)
        self._timeline.append(f"{t // 60:02d}:{t % 60:02d} {who}: {text}")

    # ------------------------------------------------------------------ delegations

    def on_delegation(self, d) -> None:
        """GPT-Live handed something over; answer it, dropping any older one still running."""
        self._asks += 1
        logger.info("delegation: %s #%d wearer: %s", d.id, self._asks, d.pending_transcript)
        if self._task is not None and not self._task.done():
            logger.info("brain: newer delegation, the one before is dropped")
            self._task.cancel()
        self._task = asyncio.create_task(self._answer(d.id, d.pending_transcript, self._asks), name="brain")

    async def _answer(self, delegation_id: str, words: str, n: int) -> None:
        try:
            out = await asyncio.wait_for(self._ask(words, n), TIMEOUT)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("brain: #%d failed (%s), asking the wearer to repeat", n, type(e).__name__)
            self._commentary("You could not see that just now. Ask the wearer to hold the plate in view and say it again.",
                             delegation_id)
            return
        build, total = self._build, len(self._build.guide.steps)
        step = max(1, min(int(out["step"]), total + 1))
        self.note("you saw", out["seen"])
        self.note("you said", out["say"])
        if step != build.step + 1:
            build.set_step(step - 1)
            await publish_build(build)
            self.note("step", f"now step {step}" if step <= total else "the build is finished")
            self._think(self._step_line())
        self._commentary(out["say"], delegation_id)
        if out["end_call"] and not self._closing:
            self._closing = True
            logger.info("end_call: run=%s at step %d/%d", build.run, build.step + 1, total)
            asyncio.create_task(_close_after_goodbye(self._session), name="close_after_goodbye")

    async def _ask(self, words: str, n: int) -> dict:
        t0 = time.perf_counter()
        frame = await self._tap.next_frame(FRAME_WAIT)
        photo = await asyncio.to_thread(_jpeg, frame, self._side)
        build = self._build
        total = len(build.guide.steps)
        where = (f"The wearer is on step {build.step + 1} of {total} ({build.guide.steps[build.step].name})."
                 if not build.finished else f"All {total} steps are done.")
        text = ("The call so far (mm:ss since it started):\n" + ("\n".join(self._timeline) or "(nothing yet)")
                + f"\n\n{where}\nThe wearer just said: \"{words}\"\nThe photo was taken just now.")
        kw = {"reasoning": {"effort": self._effort}} if self._effort else {}
        resp = await self._client.responses.create(
            model=self._model, instructions=self._instructions,
            input=[{"role": "user", "content": [
                {"type": "input_text", "text": text},
                {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(photo).decode(),
                 "detail": self._detail},
            ]}],
            text={"format": {"type": "json_schema", "name": "answer", "schema": SCHEMA, "strict": True}},
            prompt_cache_key=build.run, **kw,
        )
        out = json.loads(resp.output_text)
        u = resp.usage
        cached = u.input_tokens_details.cached_tokens if u and u.input_tokens_details else 0
        logger.info("brain: #%d %.0f ms in=%d (cached %d) out=%d step %d->%d end=%s seen: %s | say: %s",
                    n, (time.perf_counter() - t0) * 1000, u.input_tokens if u else 0, cached,
                    u.output_tokens if u else 0, build.step + 1, out["step"], out["end_call"], out["seen"], out["say"])
        if self._tap.dumping:
            self._tap.dump(photo, f"ask{n}-s{build.step + 1}")
        return out

    # ------------------------------------------------------------------ to the voice

    def _step_line(self) -> str:
        build = self._build
        if build.finished:
            return "The helper says: the build is finished, all steps are done."
        s = build.guide.steps[build.step]
        return f"The helper says: the wearer is now on step {build.step + 1} ({s.name})."

    def _think(self, text: str) -> None:
        logger.info("brain: thinking: %s", text)
        self._session.current_agent.duplex_session.append_thinking(text)

    def _commentary(self, text: str, delegation_id: str) -> None:
        logger.info("brain: commentary %s: %s", delegation_id, text)
        self._session.current_agent.duplex_session.append_commentary(text, delegation_id=delegation_id)


async def _close_after_goodbye(session, start_within: float = 8.0, cap: float = 20.0) -> None:
    """Wait for whatever the voice is saying now to end, then for the goodbye to start and end, and close the
    room; the glasses return to their connect screen."""
    t0 = time.monotonic()

    async def until(state_is_speaking: bool, limit: float) -> None:
        while (session.agent_state == "speaking") != state_is_speaking and time.monotonic() - t0 < limit:
            await asyncio.sleep(0.05)

    await until(False, start_within)
    await until(True, start_within)
    await until(False, cap)
    await asyncio.sleep(0.5)  # the tail of the audio reaching the glasses
    logger.info("end_call: closing the room after %.1fs", time.monotonic() - t0)
    await get_job_context().delete_room()
