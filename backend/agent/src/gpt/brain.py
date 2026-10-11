"""The brain: what GPT-Live hands over (client delegation) is answered here, from the camera.

GPT-Live cannot see. When the wearer says something that needs eyes ("is this
right?", "where does it go?", "what is this?"), it delegates; the plugin emits
`delegation_created` with an id and, sometimes, the wearer's words not yet in the
history. The brain then takes the newest camera frame (the glasses send ~15 a second),
and makes one stateless vision call, to OpenAI's Responses API or Anthropic's
Messages API (BRAIN_PROVIDER), built like LiveKit's client-delegation example:

    tool          confirm_step_correct(step)
    instructions  rules + the whole task file                 fixed, so the prompt cache hits
    turns         the call's chat history: the wearer as user, the voice as assistant
    last turn     the frame's bottom square, the current step, the wearer's latest words

and gets back a reply in plain facts, maybe with the tool call. Nothing goes
back to the model: the call is executed here and the reply goes to GPT-Live as
commentary on that delegation id ("Camera: ..."), which says it in its own
words. Only a confirm_step_correct call moves the build (published to the glasses,
told to GPT-Live in the same commentary and as one silent thinking line); no
call, nothing moves, whether the step is not done, unsure or not asked about.
There is no hang-up tool: a model misjudging a goodbye cut calls off, and the
wearer ends the call on the glasses (double tap). Only the newest photo goes;
what an earlier look saw survives only as what the voice said of it, and the
brain's own earlier replies are not sent back to it.

The newest delegation wins: a call still running when the next arrives is
cancelled. A call that fails or takes longer than BRAIN_TIMEOUT answers "the helper could
not answer, say it again"; with no camera frame yet the model is asked without a photo.
Every step of a look goes into the call's record (runlog.py): the photo and the whole
input as sent, the reply, the timings.
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
from runlog import RunLog

logger = logging.getLogger("rayneo-agent.brain")


# (name, description, JSON schema of the arguments); the same for both providers
TOOLS = [
    ("confirm_step_correct",
     "Confirms that the current step is built correctly. Use it when the photo clearly shows the current step's brick "
     "in place and every one of that step's facts holds. When you call it, the build moves on: the step list on the "
     "glasses advances and the voice tells the wearer the step is right, so your reply should say the same, and a "
     "step confirmed when it is not right leaves the wearer building on a mistake. Leave it "
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

    async def ask(self, instructions: str, turns: list[tuple[str, str]], notice: str, words: str, photo: bytes | None,
                  key: str) -> tuple[str, list, dict]:
        kw = {"reasoning": {"effort": self._effort}} if self._effort else {}
        resp = await self._client.responses.create(
            model=self._model, instructions=instructions,
            input=[{"role": r, "content": t} for r, t in turns] + [{"role": "user", "content": ([
                {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(photo).decode(),
                 "detail": self._detail}] if photo else []) + [
                {"type": "input_text", "text": notice}, {"type": "input_text", "text": words},
            ]}],
            tools=[{"type": "function", "name": n, "description": d, "parameters": p, "strict": True} for n, d, p in TOOLS],
            prompt_cache_key=key, **kw,
        )
        calls = [(o.name, json.loads(o.arguments or "{}")) for o in resp.output if o.type == "function_call"]
        u = resp.usage
        out_details = getattr(u, "output_tokens_details", None) if u else None
        return resp.output_text, calls, {
            "in": u.input_tokens if u else 0, "out": u.output_tokens if u else 0,
            "cached": u.input_tokens_details.cached_tokens if u and u.input_tokens_details else 0,
            "written": 0,  # OpenAI caches by itself and reports no writes
            "thinking": getattr(out_details, "reasoning_tokens", None) if out_details is not None else None,
            "stop": resp.status,
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

    async def ask(self, instructions: str, turns: list[tuple[str, str]], notice: str, words: str, photo: bytes | None,
                  key: str) -> tuple[str, list, dict]:
        from anthropic import BadRequestError

        try:
            return await self._ask(instructions, turns, notice, words, photo)
        except BadRequestError as e:
            if self._off["type"] != "disabled" or "between_tools" not in str(e):
                raise
            logger.info("brain: %s takes no disabled thinking, using between_tools", self._model)
            self._off = {"type": "between_tools"}
            return await self._ask(instructions, turns, notice, words, photo)

    async def _ask(self, instructions: str, turns: list[tuple[str, str]], notice: str, words: str,
                   photo: bytes | None) -> tuple[str, list, dict]:
        kw: dict = {"thinking": self._off}
        if self._effort and self._effort != "none":
            kw = {"thinking": {"type": "adaptive"}, "output_config": {"effort": self._effort}}
        # the notice and the wearer's words in blocks of their own (Anthropic's Haiku 5.5 guide)
        resp = await self._client.messages.create(
            model=self._model, max_tokens=4096, **kw,
            tools=[{"name": n, "description": d, "input_schema": p, "strict": True} for n, d, p in TOOLS],
            system=[{"type": "text", "text": instructions, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": r, "content": t} for r, t in turns] + [{"role": "user", "content": ([
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": base64.b64encode(photo).decode()}}] if photo else []) + [
                {"type": "text", "text": notice}, {"type": "text", "text": words},
            ]}],
        )
        u = resp.usage
        text_out = " ".join(b.text for b in resp.content if b.type == "text").strip()
        calls = [(b.name, b.input or {}) for b in resp.content if b.type == "tool_use"]
        details = getattr(u, "output_tokens_details", None)
        return text_out, calls, {
            "in": u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0),
            "out": u.output_tokens, "cached": u.cache_read_input_tokens or 0,
            "written": u.cache_creation_input_tokens or 0,
            "thinking": getattr(details, "thinking_tokens", None) if details is not None else None,
            "stop": resp.stop_reason,
        }


def conversation(history, words: str) -> tuple[list[tuple[str, str]], str]:
    """The call so far as the model's turns, and the wearer's latest words. As in LiveKit's client-delegation example
    the chat history goes over as it is, the wearer's lines as user turns and the voice's as assistant turns; for
    Anthropic the turns alternate (lines of one side in a row are joined) and start with the wearer (the voice's
    greeting is dropped). The wearer's last lines move out to the ask, so the photo can go before them."""
    turns: list[list[str]] = []
    for item in history.items:
        if item.type != "message" or item.role not in ("user", "assistant"):
            continue
        text = " ".join((item.text_content or "").split())
        if not text:
            continue
        if turns and turns[-1][0] == item.role:
            turns[-1][1] += "\n" + text
        else:
            turns.append([item.role, text])
    while turns and turns[0][0] == "assistant":
        turns.pop(0)
    last = turns.pop()[1] if turns and turns[-1][0] == "user" else ""
    return [(r, t) for r, t in turns], "\n".join(w for w in (last, words) if w)


def make_model(provider: str, model: str, effort: str, detail: str):
    """The brain's model client: BRAIN_PROVIDER openai or anthropic."""
    if provider == "anthropic":
        return AnthropicModel(model, effort)
    return OpenAIModel(model, effort, detail)


class Brain:
    def __init__(self, session: AgentSession, build: Build, tap: FrameTap, model, side: int, language: str,
                 timeout: float = 12.0, record: RunLog | None = None) -> None:
        self._timeout = timeout
        self._record = record or RunLog(None, "")
        self._session = session
        self._build = build
        self._tap = tap
        self._model = model
        self._side = side
        self._instructions = brain_instructions(build.guide, language)
        self._task: asyncio.Task | None = None
        self._task_n = 0
        self._asks = 0

    @property
    def instructions(self) -> str:
        return self._instructions

    # ------------------------------------------------------------------ delegations

    def on_delegation(self, d) -> None:
        """GPT-Live handed something over; answer it, dropping any older one still running."""
        self._asks += 1
        words = d.pending_transcript.strip()  # the turn not yet in the history; often empty
        logger.info("delegation: %s #%d wearer: %s", d.id, self._asks, words or "(no words came with it)")
        self._record.event("delegation", n=self._asks, id=d.id, words=words)
        if self._task is not None and not self._task.done():
            logger.info("brain: newer delegation, the one before is dropped")
            self._record.event("look_dropped", n=self._task_n, by=self._asks)
            self._task.cancel()
        self._task_n = self._asks
        self._task = asyncio.create_task(self._answer(d.id, words, self._asks, time.monotonic()), name="brain")

    async def _answer(self, delegation_id: str, words: str, n: int, t_asked: float | None = None) -> None:
        try:
            out = await asyncio.wait_for(self._ask(words, n), self._timeout)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("brain: #%d failed (%s: %s), asking the wearer to repeat", n, type(e).__name__, str(e)[:200])
            self._record.event("look_failed", n=n, error=f"{type(e).__name__}: {e}"[:500])
            self._commentary("The helper could not answer this time. Ask the wearer to say it again.",
                             delegation_id, n, t_asked)
            return
        build = self._build
        current = build.step + 1
        parts = [f"Camera: {out['text']}"] if out["text"] else []
        if out["done"]:
            build.set_step(current)  # index of the next step = the number of steps done
            self._record.event("step", done=current, now=None if build.finished else current + 1)
            await publish_build(build)
            parts.append(f"Step {current} is recorded as done; that was the last step, the build is finished."
                         if build.finished else f"Step {current} is recorded as done; now give step {current + 1}.")
            self._think(self._step_line())
        self._commentary(" ".join(parts) or "Camera: nothing to add.", delegation_id, n, t_asked)

    async def _ask(self, words: str, n: int) -> dict:
        """One look: {text, calls, done}; done = a confirm_step_correct call naming the current step."""
        t0 = time.perf_counter()
        frame, seq = self._tap.latest, self._tap.count  # the newest frame (~15 a second) and its number in this call
        age_ms = (time.monotonic() - self._tap.latest_at) * 1000 if frame is not None else None
        photo = await asyncio.to_thread(_jpeg, frame, self._side) if frame is not None else None
        build = self._build
        total = len(build.guide.steps)
        where = (f"Step {build.step + 1} of {total} ({build.guide.steps[build.step].name}); {build.step} done"
                 if not build.finished else f"none: all {total} steps are done")
        turns, words = conversation(self._session.history, words)
        # the last user turn: the photo first (Anthropic: images before text work best), then where the build is,
        # then the wearer's words
        lead = "The photo above was taken just now." if photo else "No photo came with this request: the camera has sent no picture."
        notice = f"{lead}\n<current_step>{where}</current_step>"
        words = words or "(the wearer's words have not come through yet)"
        t_sent = time.perf_counter()
        saved = self._record.photo(photo, f"ask{n}-s{build.step + 1}") if photo else None
        if frame is not None:
            logger.info("brain: #%d frame %d (%dx%d, %.0f ms old); request sent %.0f ms after the ask: jpeg %d KB, "
                        "%d earlier turns, step %d; wearer: %s", n, seq, frame.width, frame.height, age_ms,
                        (t_sent - t0) * 1000, len(photo) // 1024, len(turns), build.step + 1, words)
        else:
            logger.warning("brain: #%d no camera frame this call; request sent without a photo, step %d; wearer: %s", n,
                           build.step + 1, words)
        self._record.event("look_sent", n=n, step=build.step + 1, frame=seq if frame is not None else None,
                           frame_size=f"{frame.width}x{frame.height}" if frame is not None else None,
                           frame_age_ms=round(age_ms) if age_ms is not None else None,
                           photo=saved, photo_kb=len(photo) // 1024 if photo else None,
                           prep_ms=round((t_sent - t0) * 1000), turns=turns, notice=notice, words=words)
        reply, calls, u = await self._model.ask(self._instructions, turns, notice, words, photo, build.run)
        t_back = time.perf_counter()
        done, ignored = False, None
        for name, args in calls:
            if name != "confirm_step_correct":
                continue
            if not build.finished and args.get("step") == build.step + 1:
                done = True
            else:
                ignored = args.get("step")
                logger.warning("brain: #%d confirm_step_correct(%s) ignored, the current step is %d", n, args.get("step"),
                               build.step + 1)
        logger.info("brain: #%d reply after %.0f ms (model %.0f ms): in=%d (cached %d, written %d) out=%d (thinking %s) "
                    "stop=%s calls=%s frame=%s reply: %s",
                    n, (t_back - t0) * 1000, (t_back - t_sent) * 1000, u["in"], u["cached"], u.get("written", 0),
                    u["out"], u.get("thinking"), u.get("stop"), [f"{c}({a})" for c, a in calls], saved or "-", reply)
        self._record.event("look_back", n=n, model_ms=round((t_back - t_sent) * 1000),
                           total_ms=round((t_back - t0) * 1000), reply=reply, calls=[[c, a] for c, a in calls],
                           done=done, ignored_confirm=ignored, usage=u)
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
        self._record.event("thinking", text=text)
        self._session.current_agent.duplex_session.append_thinking(text)

    def _commentary(self, text: str, delegation_id: str, n: int = 0, t_asked: float | None = None) -> None:
        logger.info("brain: commentary %s: %s", delegation_id, text)
        speaking = self._session.agent_state == "speaking"
        self._record.event("commentary", n=n, id=delegation_id, text=text, voice_speaking=speaking)
        self._session.current_agent.duplex_session.append_commentary(text, delegation_id=delegation_id)
        if t_asked is not None:
            asyncio.create_task(self._time_voice(n, t_asked, time.monotonic(), speaking), name="time_voice")

    async def _time_voice(self, n: int, t_asked: float, t_sent: float, speaking: bool, limit: float = 15.0) -> None:
        """Log when the voice starts saying the answer: ms after the commentary went out and after the delegation
        (~ the wearer's last word). If the voice was still talking when the answer arrived ("let me look"), the
        answer is taken to start with its next speech after a pause, which is approximate."""
        session = self._session
        if speaking:
            while session.agent_state == "speaking":
                if time.monotonic() - t_sent > limit:
                    logger.info("voice: #%d still on its earlier speech %.0fs after the commentary", n, limit)
                    self._record.event("voice_silent", n=n, why=f"still on its earlier speech {limit:.0f} s after")
                    return
                await asyncio.sleep(0.02)
        while session.agent_state != "speaking":
            if time.monotonic() - t_sent > limit:
                logger.info("voice: #%d not speaking %.0fs after the commentary", n, limit)
                self._record.event("voice_silent", n=n, why=f"not speaking {limit:.0f} s after")
                return
            await asyncio.sleep(0.02)
        now = time.monotonic()
        logger.info("voice: #%d started %.0f ms after the commentary, %.0f ms after the delegation%s", n,
                    (now - t_sent) * 1000, (now - t_asked) * 1000,
                    " (it was speaking when the answer arrived)" if speaking else "")
        self._record.event("voice_started", n=n, after_commentary_ms=round((now - t_sent) * 1000),
                           after_delegation_ms=round((now - t_asked) * 1000), was_speaking=speaking)
