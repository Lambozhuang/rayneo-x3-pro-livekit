"""The brain: what GPT-Live hands over (client delegation) is answered here, from the camera.

GPT-Live cannot see. When the wearer says something that needs eyes ("is this
right?", "where does it go?", "what is this?"), it delegates; the plugin emits
`delegation_created` with an id and the wearer's words so far. The brain then
takes the next camera frame (taken after the ask), and makes one stateless
vision call, to OpenAI's Responses API or Anthropic's Messages API
(BRAIN_PROVIDER):

    tool          confirm_step_correct(step)
    instructions  rules + the whole task file                 fixed, so the prompt cache hits
    input         the timeline of the call (the wearer's words, what the brain answered and did)
                  + the current step + the wearer's words + the frame's bottom square

and gets back a reply in plain facts, maybe with the tool call. Nothing goes
back to the model: the call is executed here and the reply goes to GPT-Live as
commentary on that delegation id ("Camera: ..."), which says it in its own
words. Only a confirm_step_correct call moves the build (published to the glasses,
told to GPT-Live in the same commentary and as one silent thinking line); no
call, nothing moves, whether the step is not done, unsure or not asked about.
There is no hang-up tool: a model misjudging a goodbye cut calls off, and the
wearer ends the call on the glasses (double tap). The timeline only grows at
the end, and no image is kept in it: what a look saw survives as its reply.

The newest delegation wins: a call still running when the next arrives is
cancelled. A call that fails or takes longer than BRAIN_TIMEOUT answers "I could
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

from frames import FrameTap, to_image
from gpt.prompts import brain_instructions
from guide import Build

logger = logging.getLogger("rayneo-agent.brain")

FRAME_WAIT = 1.0

# (name, description, JSON schema of the arguments); the same for both providers
TOOLS = [
    ("confirm_step_correct",
     "Confirms that the current step is built correctly. Use it when the photo clearly shows the current step's brick "
     "in place and every one of that step's facts holds. When you call it, the build moves on: the step list on the "
     "glasses advances and the voice tells the wearer the step is right, so your reply should say the same. Leave it "
     "out when any fact fails, when part of the step is hidden or too small to judge, when the wearer only says they "
     "are done without the photo showing it, and when the question is not about the current step. step is the number "
     "of the current step given in the input.",
     {"type": "object", "properties": {"step": {"type": "integer", "description": "the current step's number"}},
      "required": ["step"], "additionalProperties": False}),
]


async def publish_build(build: Build) -> None:
    """The run's position to the glasses, as participant attributes (Build.attributes)."""
    await get_job_context().room.local_participant.set_attributes(build.attributes())


def _jpeg(frame, side: int) -> bytes:
    """The bottom square of the frame (side = the frame's short side), scaled to `side`. The glasses look down at
    the table: the upper part of the portrait frame is wall and the far desk, and dropping it nearly doubles the
    pixels per stud at the same image size (15 -> 27 px on the truck plate). No plate detection, so whatever else
    is in front of the wearer stays in the picture."""
    img = to_image(frame)
    w, h = img.size
    s = min(w, h)
    img = img.crop(((w - s) // 2, h - s, (w - s) // 2 + s, h))
    img.thumbnail((side, side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


class OpenAIModel:
    """Responses API; the prompt cache is automatic (prompt_cache_key keeps one call's requests together)."""

    def __init__(self, model: str, effort: str, detail: str) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI()
        self._model, self._effort, self._detail = model, effort, detail

    async def ask(self, instructions: str, text: str, photo: bytes, key: str) -> tuple[str, list, dict]:
        kw = {"reasoning": {"effort": self._effort}} if self._effort else {}
        resp = await self._client.responses.create(
            model=self._model, instructions=instructions,
            input=[{"role": "user", "content": [
                {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(photo).decode(),
                 "detail": self._detail},
                {"type": "input_text", "text": text},
            ]}],
            tools=[{"type": "function", "name": n, "description": d, "parameters": p, "strict": True} for n, d, p in TOOLS],
            prompt_cache_key=key, **kw,
        )
        calls = [(o.name, json.loads(o.arguments or "{}")) for o in resp.output if o.type == "function_call"]
        u = resp.usage
        return resp.output_text, calls, {
            "in": u.input_tokens if u else 0, "out": u.output_tokens if u else 0,
            "cached": u.input_tokens_details.cached_tokens if u and u.input_tokens_details else 0,
        }


class AnthropicModel:
    """Messages API; the instructions carry an explicit cache breakpoint (nothing is cached otherwise).
    Effort none = thinking disabled; any other value = adaptive thinking at that effort."""

    def __init__(self, model: str, effort: str) -> None:
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic()
        self._model, self._effort = model, effort
        # "no thinking": disabled on most models; Sonnet 5.5 rejects that and takes between_tools (no up-front
        # thinking), which the API's error names; switched once, on the first such error
        self._off = {"type": "disabled"}

    async def ask(self, instructions: str, text: str, photo: bytes, key: str) -> tuple[str, list, dict]:
        from anthropic import BadRequestError

        try:
            return await self._ask(instructions, text, photo)
        except BadRequestError as e:
            if self._off["type"] != "disabled" or "between_tools" not in str(e):
                raise
            logger.info("brain: %s takes no disabled thinking, using between_tools", self._model)
            self._off = {"type": "between_tools"}
            return await self._ask(instructions, text, photo)

    async def _ask(self, instructions: str, text: str, photo: bytes) -> tuple[str, list, dict]:
        kw: dict = {"thinking": self._off}
        if self._effort and self._effort != "none":
            kw = {"thinking": {"type": "adaptive"}, "output_config": {"effort": self._effort}}
        resp = await self._client.messages.create(
            model=self._model, max_tokens=4096, **kw,
            tools=[{"name": n, "description": d, "input_schema": p, "strict": True} for n, d, p in TOOLS],
            system=[{"type": "text", "text": instructions, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": base64.b64encode(photo).decode()}},
                {"type": "text", "text": text},
            ]}],
        )
        u = resp.usage
        text_out = " ".join(b.text for b in resp.content if b.type == "text").strip()
        calls = [(b.name, b.input or {}) for b in resp.content if b.type == "tool_use"]
        return text_out, calls, {
            "in": u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0),
            "out": u.output_tokens, "cached": u.cache_read_input_tokens or 0,
        }


def make_model(provider: str, model: str, effort: str, detail: str):
    """The brain's model client: BRAIN_PROVIDER openai or anthropic."""
    if provider == "anthropic":
        return AnthropicModel(model, effort)
    return OpenAIModel(model, effort, detail)


class Brain:
    def __init__(self, session: AgentSession, build: Build, tap: FrameTap, model, side: int, language: str,
                 timeout: float = 12.0) -> None:
        self._timeout = timeout
        self._session = session
        self._build = build
        self._tap = tap
        self._model = model
        self._side = side
        self._instructions = brain_instructions(build.guide, language)
        self._t0 = time.monotonic()
        self._timeline: list[str] = []
        self._task: asyncio.Task | None = None
        self._asks = 0

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
            out = await asyncio.wait_for(self._ask(words, n), self._timeout)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("brain: #%d failed (%s), asking the wearer to repeat", n, type(e).__name__)
            self._commentary("You could not see that just now. Ask the wearer to hold the plate in view and say it again.",
                             delegation_id)
            return
        build = self._build
        current = build.step + 1
        self.note("you answered", out["text"])
        parts = [f"Camera: {out['text']}"] if out["text"] else []
        if out["done"]:
            self.note("you recorded", f"step {current} done")
            build.set_step(current)  # index of the next step = the number of steps done
            await publish_build(build)
            parts.append(f"Step {current} is recorded as done; that was the last step, the build is finished."
                         if build.finished else f"Step {current} is recorded as done; now give step {current + 1}.")
            self._think(self._step_line())
        self._commentary(" ".join(parts) or "Camera: nothing to add.", delegation_id)

    async def _ask(self, words: str, n: int) -> dict:
        """One look: {text, calls, done}; done = a confirm_step_correct call naming the current step."""
        t0 = time.perf_counter()
        frame = await self._tap.next_frame(FRAME_WAIT)
        photo = await asyncio.to_thread(_jpeg, frame, self._side)
        build = self._build
        total = len(build.guide.steps)
        where = (f"Step {build.step + 1} of {total} ({build.guide.steps[build.step].name})"
                 if not build.finished else f"none: all {total} steps are done")
        timeline = "\n".join(self._timeline) or "(nothing yet)"
        # the photo goes first (Anthropic: images before text work best), then the conversation, then the ask
        text = (f"The photo above was taken just now.\n<conversation>\n{timeline}\n</conversation>\n"
                f"<current_step>{where}</current_step>\n<wearer_said>{words}</wearer_said>")
        reply, calls, u = await self._model.ask(self._instructions, text, photo, build.run)
        done = False
        for name, args in calls:
            if name != "confirm_step_correct":
                continue
            if not build.finished and args.get("step") == build.step + 1:
                done = True
            else:
                logger.warning("brain: #%d confirm_step_correct(%s) ignored, the current step is %d", n, args.get("step"),
                               build.step + 1)
        logger.info("brain: #%d %.0f ms in=%d (cached %d) out=%d step %d calls=%s reply: %s",
                    n, (time.perf_counter() - t0) * 1000, u["in"], u["cached"], u["out"], build.step + 1,
                    [f"{c}({a})" for c, a in calls], reply)
        if self._tap.dumping:
            self._tap.dump(photo, f"ask{n}-s{build.step + 1}{'-done' if done else ''}")
        return {"text": reply, "calls": calls, "done": done}

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
