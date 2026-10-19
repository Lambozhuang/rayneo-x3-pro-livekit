"""The brain: it looks at the camera by itself every few seconds, and answers what GPT-Live hands over.

GPT-Live cannot see. The brain is one vision model, behind OpenAI's Responses API
or Anthropic's Messages API (BRAIN_PROVIDER), that looks in two ways:

- A watch look runs whenever no delegation does, one after the other, at most one
  every BRAIN_WATCH_EVERY seconds, on the newest camera frame scaled to
  BRAIN_WATCH_SIDE, without thinking. Nobody asked: the brain writes down what may
  matter later (note, which also goes to GPT-Live as silent thinking unless it is
  about what the photo does not let it tell), has GPT-Live say something now (say,
  commentary on no delegation, sent once the next look calls say too), moves the
  build (set_progress), or does nothing, which leaves no trace in its context.
- A delegation: when the wearer says something that needs eyes ("is this right?",
  "where does it go?", "what is this?"), GPT-Live delegates; the plugin emits
  `delegation_created` with an id and, sometimes, the wearer's words not yet in the
  history. The brain answers from the newest frame scaled to BRAIN_SIDE, at
  BRAIN_EFFORT, and the reply goes to GPT-Live as commentary on that id
  ("Camera: ..."), which says it in its own words. A watch look still running is
  cancelled, and the watch goes on once the answer is out.

Both send one request built the same way:

    tools         set_progress(done); a watch look also note(text) and say(text)
    instructions  rules for both + the whole task file          fixed, so the prompt cache hits
    one message   the frame's bottom square, the call so far, the progress recorded, and
                  the wearer's latest words (a delegation) or "routine look" (a watch)

The call so far is one line per entry with its time into the call: the wearer's
and the voice's lines from the chat history, and what the brain wrote earlier
(its notes, what it had the voice say, its answers to delegations). Photos are
never kept: what an earlier look saw survives only as what the brain wrote of it.
Nothing goes back to the model: tool calls are executed here. Only a set_progress
call moves the build, forward or back (published to the glasses, told to GPT-Live
in the same commentary); no call, nothing moves.

The newest delegation wins: a call still running when the next arrives is
cancelled. A delegation that fails or takes longer than BRAIN_TIMEOUT answers "the helper could
not answer, say it again"; with no camera frame yet the model is asked without a photo.
A watch look that fails is logged and the next one follows; with no frame yet none is made.
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

from livekit.agents import AgentSession

from frames import FrameTap, bottom_square
from gpt.prompts import WATCH_ASK, brain_instructions
from guide import Build, publish_build
from livekit.agents import get_job_context
from runlog import RunLog

logger = logging.getLogger("rayneo-agent.brain")

LOOKING_ATTRIBUTE = "rayneo.brain.looking"  # "1" while a delegation runs; the glasses show "Thinking" (Phase.kt)


# (name, description, JSON schema of the arguments); the same for both providers
SET_PROGRESS = (
    "set_progress",
    "Records how far the build is: the number of steps, counted from step 1, that the photo shows built right, from 0 "
    "to the number of the last step. It can go up by more than one, or down when an earlier step turns out wrong. The "
    "step list on the glasses and the voice follow it, so your reply should say the same, and progress recorded "
    "higher than the plate shows leaves the wearer building on a mistake. Call it only when the photo lets you tell "
    "and the number differs from the progress given in the input; leave it out when part of the build is hidden or "
    "too small to judge, and when the wearer only says they are done without the photo showing it.",
    {"type": "object", "properties": {"done": {"type": "integer",
                                               "description": "how many steps, from step 1, are built right"}},
     "required": ["done"], "additionalProperties": False})
NOTE = (
    "note",
    "Writes down what the photo shows that may matter later and the call so far does not say yet. It goes into the "
    "call so far, so later looks and requests read it, and, unless to_voice is false, silently to the voice, which "
    "uses it when the wearer asks and does not read it out.",
    {"type": "object", "properties": {
        "text": {"type": "string", "description": "one short sentence of plain facts"},
        "to_voice": {"type": "boolean",
                     "description": "false when the note is about what the photo does not let you tell yet (a hand "
                                    "covers it, it is blurred, it is out of the picture): such a note stays in the "
                                    "call so far for your later looks, and the voice, which cannot look again, is "
                                    "not told something it might pass on as a doubt"}},
     "required": ["text", "to_voice"], "additionalProperties": False})
SAY = (
    "say",
    "Has the voice tell the wearer something now, unasked, in its own words. It also goes into the call so far.",
    {"type": "object", "properties": {"text": {"type": "string",
                                               "description": "one or two short sentences of plain facts"}},
     "required": ["text"], "additionalProperties": False})
ASK_TOOLS = [SET_PROGRESS]
WATCH_TOOLS = [SET_PROGRESS, NOTE, SAY]

# who wrote a line in the call so far, as the brain reads it
WHO = {"user": "wearer", "assistant": "voice", "noted": "you noted", "said": "you had the voice say",
       "answered": "you answered the voice"}


def _jpeg(frame, side: int) -> bytes:
    """The bottom square of the frame (frames.bottom_square) as a JPEG."""
    buf = io.BytesIO()
    bottom_square(frame, side).save(buf, "JPEG", quality=85)
    return buf.getvalue()


class OpenAIModel:
    """Responses API; the prompt cache is automatic (prompt_cache_key keeps one call's requests together)."""

    def __init__(self, model: str, detail: str) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI()
        self._model, self._detail = model, detail

    async def ask(self, instructions: str, texts: list[str], photo: bytes | None, tools: list, effort: str,
                  key: str) -> tuple[str, list, dict]:
        kw = {"reasoning": {"effort": effort}} if effort else {}
        resp = await self._client.responses.create(
            model=self._model, instructions=instructions,
            input=[{"role": "user", "content": ([
                {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(photo).decode(),
                 "detail": self._detail}] if photo else []) + [{"type": "input_text", "text": t} for t in texts]}],
            tools=[{"type": "function", "name": n, "description": d, "parameters": p, "strict": True} for n, d, p in tools],
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
            "stop": resp.status, "ttft_ms": None,  # not streamed
        }


class AnthropicModel:
    """Messages API; the instructions carry an explicit cache breakpoint (nothing is cached otherwise).
    Effort none = thinking disabled; any other value = adaptive thinking at that effort."""

    def __init__(self, model: str) -> None:
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic()
        self._model = model
        # "no thinking": disabled on most models; Sonnet 5.5 rejects that and takes between_tools (no up-front
        # thinking), which the API's error names; switched once, on the first such error
        self._off = {"type": "disabled"}

    async def ask(self, instructions: str, texts: list[str], photo: bytes | None, tools: list, effort: str,
                  key: str) -> tuple[str, list, dict]:
        from anthropic import BadRequestError

        try:
            return await self._ask(instructions, texts, photo, tools, effort)
        except BadRequestError as e:
            if self._off["type"] != "disabled" or "between_tools" not in str(e):
                raise
            logger.info("brain: %s takes no disabled thinking, using between_tools", self._model)
            self._off = {"type": "between_tools"}
            return await self._ask(instructions, texts, photo, tools, effort)

    async def _ask(self, instructions: str, texts: list[str], photo: bytes | None, tools: list,
                   effort: str) -> tuple[str, list, dict]:
        kw: dict = {"thinking": self._off}
        if effort and effort != "none":
            kw = {"thinking": {"type": "adaptive"}, "output_config": {"effort": effort}}
        # the photo first (Anthropic: images before text work best), then each part of the input in a block of its
        # own (Anthropic's Haiku 5.5 guide). Streamed only to time the first output (ttft: the way there, the
        # API's queue and its reading of the input, apart from the writing); the reply is used once complete.
        t0, ttft = time.perf_counter(), None
        async with self._client.messages.stream(
            model=self._model, max_tokens=4096, **kw,
            tools=[{"name": n, "description": d, "input_schema": p, "strict": True} for n, d, p in tools],
            system=[{"type": "text", "text": instructions, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": ([
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": base64.b64encode(photo).decode()}}] if photo else []) + [
                {"type": "text", "text": t} for t in texts]}],
        ) as stream:
            async for event in stream:
                if ttft is None and event.type == "content_block_start":
                    ttft = time.perf_counter() - t0
            resp = await stream.get_final_message()
        u = resp.usage
        text_out = " ".join(b.text for b in resp.content if b.type == "text").strip()
        calls = [(b.name, b.input or {}) for b in resp.content if b.type == "tool_use"]
        details = getattr(u, "output_tokens_details", None)
        return text_out, calls, {
            "in": u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0),
            "out": u.output_tokens, "cached": u.cache_read_input_tokens or 0,
            "written": u.cache_creation_input_tokens or 0,
            "thinking": getattr(details, "thinking_tokens", None) if details is not None else None,
            "stop": resp.stop_reason, "ttft_ms": round(ttft * 1000) if ttft is not None else None,
        }


def call_so_far(history, written: list[tuple[float, str, str]], record: RunLog, words: str | None = None
                ) -> tuple[str, str]:
    """The call so far as one line per entry, in time order, each with its time into the call: the wearer's and the
    voice's lines from the chat history (stamped when the line closed, so they trail the speech) and what the brain
    wrote (`written`: wall time, who, text). With words (a delegation), the wearer's lines after the voice's last
    move out and join them, so the request's own words go last."""
    chat = []
    for item in history.items:
        if item.type != "message" or item.role not in ("user", "assistant"):
            continue
        text = " ".join((item.text_content or "").split())
        if text:
            chat.append((item.created_at, item.role, text))
    last = []
    if words is not None:
        while chat and chat[-1][1] == "user":
            last.insert(0, chat.pop()[2])
    entries = sorted(chat + written, key=lambda e: e[0])
    lines = []
    for at, who, text in entries:
        s = max(0, round(record.t(at)))
        lines.append(f"[{s // 60}:{s % 60:02d}] {WHO[who]}: {text}")
    said = "\n".join(lines) or "(nothing yet)"
    if words is None:
        return said, ""
    last_words = "\n".join(last)
    # the words that came with the delegation may have reached the history by now: then they go once
    if last_words and words and (words in last_words or last_words in words):
        return said, max(last_words, words, key=len)
    return said, "\n".join(w for w in (last_words, words) if w)


def make_model(provider: str, model: str, detail: str):
    """The brain's model client: BRAIN_PROVIDER openai or anthropic."""
    if provider == "anthropic":
        return AnthropicModel(model)
    return OpenAIModel(model, detail)


class Brain:
    def __init__(self, session: AgentSession, build: Build, tap: FrameTap, model, effort: str, side: int,
                 watch_side: int, watch_every: float, language: str, timeout: float = 12.0,
                 record: RunLog | None = None) -> None:
        self._timeout = timeout
        self._record = record or RunLog(None, "")
        self._session = session
        self._build = build
        self._tap = tap
        self._model = model
        self._effort = effort
        self._side = side
        self._watch_side = watch_side
        self._watch_every = watch_every
        self._instructions = brain_instructions(build.guide, language)
        self._written: list[tuple[float, str, str]] = []  # what the brain wrote: (wall time, who, text)
        self._task: asyncio.Task | None = None  # the delegation running, if any
        self._task_n = 0
        self._asks = 0
        self._free = asyncio.Event()  # set while no delegation runs: the watch goes on
        self._free.set()
        self._watcher: asyncio.Task | None = None
        self._look: asyncio.Task | None = None  # the watch look running, if any
        self._look_w = 0
        # A watch look's say, and the notes that came with it, waiting for the next look to say something too
        # (_watch_look): {"w", "says", "notes"}, or None.
        self._held: dict | None = None

    @property
    def instructions(self) -> str:
        return self._instructions

    # ------------------------------------------------------------------ watch

    def start_watching(self) -> None:
        self._watcher = asyncio.create_task(self._watch_loop(), name="watch")

    def stop_watching(self) -> None:
        """Stop the watch, the look running included (it is a task of its own)."""
        if self._watcher is not None:
            self._watcher.cancel()
        if self._look is not None:
            self._look.cancel()

    async def _watch_loop(self) -> None:
        """One watch look after the other while no delegation runs, each starting at least watch_every after the
        one before."""
        w = 0
        while True:
            await self._free.wait()
            started = time.monotonic()
            if self._tap.latest is not None:
                w += 1
                self._look_w = w
                self._look = asyncio.create_task(self._watch(w), name="watch_look")
                await asyncio.wait([self._look])  # returns on cancel too, which a delegation does
            await asyncio.sleep(max(0.0, self._watch_every - (time.monotonic() - started)))

    async def _watch(self, w: int) -> None:
        try:
            await asyncio.wait_for(self._watch_look(w), self._timeout)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("watch: #%d failed (%s: %s)", w, type(e).__name__, str(e)[:200])
            self._record.event("watch_failed", w=w, error=f"{type(e).__name__}: {e}"[:500])

    async def _watch_look(self, w: int) -> None:
        """One watch look and what comes of it. A say goes out only when the next look calls say too: GPT-Live
        cannot take back what it was told, so a correction made from one photo, often of a brick still being
        pressed down, would be spoken even once the next look sees it right. Until then the say and the notes of
        its look are held, out of the call so far as well, so the next look judges afresh; they are dropped when
        the next look calls no say, or a delegation comes. Progress is never held."""
        said, _ = call_so_far(self._session.history, self._written, self._record)
        reply, calls, u, progress = await self._look_once("watch", w, self._watch_side, said, WATCH_ASK, WATCH_TOOLS,
                                                          "none")
        now = time.time()
        notes, says = [], []
        for name, args in calls:
            text = " ".join(str(args.get("text") or "").split())
            if name == "note" and text:
                notes.append((text, args.get("to_voice") is not False))
            elif name == "say" and text:
                says.append(text)
        held, self._held = self._held, None
        if says and held is None:
            self._held = {"w": w, "says": says, "notes": notes}
            logger.info("watch: #%d say held until the next look: %s", w, " ".join(says))
            self._record.event("say_held", w=w, text=" ".join(says))
            notes, says = [], []
        elif says:
            logger.info("watch: #%d confirms the say of #%d", w, held["w"])
            self._record.event("say_confirmed", w=held["w"], by=w)
        elif held is not None:
            logger.info("watch: #%d calls no say, the say of #%d is dropped", w, held["w"])
            self._record.event("say_dropped", w=held["w"], by=w)
        speak = []
        for text, to_voice in notes:
            self._written.append((now, "noted", text))
            self._record.event("note", w=w, text=text, to_voice=to_voice)
            if to_voice:
                self._session.current_agent.duplex_session.append_thinking(f"Camera: {text}")
        for text in says:
            self._written.append((now, "said", text))
            self._record.event("say", w=w, text=text)
            speak.append(f"Camera: {text}")
        if progress is not None:
            speak.append(await self._move(progress))
        if speak:
            text = " ".join(speak)
            self._record.event("commentary", w=w, id=None, text=text,
                               voice_speaking=self._session.agent_state == "speaking")
            self._session.current_agent.duplex_session.append_commentary(text)

    # ------------------------------------------------------------------ delegations

    def on_delegation(self, d) -> None:
        """GPT-Live handed something over; answer it, dropping any older one still running and the watch look."""
        self._asks += 1
        words = d.pending_transcript.strip()  # the turn not yet in the history; often empty
        logger.info("delegation: %s #%d wearer: %s", d.id, self._asks, words or "(no words came with it)")
        self._record.event("delegation", n=self._asks, id=d.id, words=words)
        self._free.clear()
        if self._held is not None:
            logger.info("watch: the say of #%d is dropped for delegation #%d", self._held["w"], self._asks)
            self._record.event("say_dropped", w=self._held["w"], by_delegation=self._asks)
            self._held = None
        if self._look is not None and not self._look.done():
            logger.info("watch: #%d dropped for delegation #%d", self._look_w, self._asks)
            self._record.event("watch_dropped", w=self._look_w, by=self._asks)
            self._look.cancel()
        if self._task is not None and not self._task.done():
            logger.info("brain: newer delegation, the one before is dropped")
            self._record.event("look_dropped", n=self._task_n, by=self._asks)
            self._task.cancel()
        self._task_n = self._asks
        self._task = asyncio.create_task(self._answer(d.id, words, self._asks, time.monotonic()), name="brain")
        self._task.add_done_callback(self._delegation_done)
        self._publish_looking(True)

    def _delegation_done(self, task: asyncio.Task) -> None:
        if task is self._task:  # not one a newer delegation replaced
            self._free.set()

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
            self._publish_looking(False)
            return
        if out["text"]:
            self._written.append((time.time(), "answered", " ".join(out["text"].split())))
        parts = [f"Camera: {out['text']}"] if out["text"] else []
        if out["progress"] is not None:
            parts.append(await self._move(out["progress"]))
        self._commentary(" ".join(parts) or "Camera: nothing to add.", delegation_id, n, t_asked)
        self._publish_looking(False)

    def _publish_looking(self, looking: bool) -> None:
        """Tell the glasses whether a delegation is in progress, as the participant attribute LOOKING_ATTRIBUTE ("1"
        or cleared), so they can show "Thinking" while the brain works: the speech model's own state stays
        "listening" through a hand-over. Set on every hand-over and cleared when the answer or the failure goes
        to the voice, not when a look is cancelled, since a cancelled look was replaced by a newer one. Watch
        looks leave it alone: nobody is waiting for them."""
        attributes = {LOOKING_ATTRIBUTE: "1" if looking else ""}
        asyncio.create_task(get_job_context().room.local_participant.set_attributes(attributes), name="looking")

    async def _ask(self, words: str, n: int) -> dict:
        """One look for delegation n: {text, calls, progress}; progress = the steps done by a set_progress call that
        changes it, else None."""
        said, words = call_so_far(self._session.history, self._written, self._record, words)
        words = words or "(the wearer's words have not come through yet)"
        reply, calls, _, progress = await self._look_once("look", n, self._side, said, words, ASK_TOOLS, self._effort)
        return {"text": reply, "calls": calls, "progress": progress}

    # ------------------------------------------------------------------ one look, either kind

    async def _look_once(self, kind: str, n: int, side: int, said: str, last: str, tools: list, effort: str
                         ) -> tuple[str, list, dict, int | None]:
        """Send one request on the newest frame and log and record it as `kind` (look: a delegation, watch: a watch
        look) number n. Returns the reply, the tool calls, the usage, and the steps done if a set_progress call
        changes them, else None; the build itself is moved by the caller."""
        name = "delegation" if kind == "look" else "watch"
        num = "n" if kind == "look" else "w"
        t0 = time.perf_counter()
        frame, seq = self._tap.latest, self._tap.count  # the newest frame (~15 a second) and its number in this call
        age_ms = (time.monotonic() - self._tap.latest_at) * 1000 if frame is not None else None
        photo = await asyncio.to_thread(_jpeg, frame, side) if frame is not None else None
        build = self._build
        total = len(build.guide.steps)
        lead = "The photo above was taken just now." if photo else "No photo came with this request: the camera has sent no picture."
        texts = [f"{lead}\n<call>\n{said}\n</call>", f"<progress>{build.where()}</progress>", last]
        t_sent = time.perf_counter()
        prefix = "ask" if kind == "look" else "watch"
        saved = self._record.photo(photo, f"{prefix}{n}-s{build.step + 1}") if photo else None
        if frame is not None:
            logger.info("brain: %s #%d frame %d (%dx%d, %.0f ms old); request sent %.0f ms after the start: jpeg %d KB "
                        "at %d px, call so far %d lines, step %d; %s", name, n, seq, frame.width, frame.height, age_ms,
                        (t_sent - t0) * 1000, len(photo) // 1024, side, said.count("\n") + 1, build.step + 1, last)
        else:
            logger.warning("brain: %s #%d no camera frame this call; request sent without a photo, step %d; %s", name, n,
                           build.step + 1, last)
        self._record.event(f"{kind}_sent", **{num: n}, step=build.step + 1, frame=seq if frame is not None else None,
                           frame_size=f"{frame.width}x{frame.height}" if frame is not None else None,
                           frame_age_ms=round(age_ms) if age_ms is not None else None, side=side,
                           photo=saved, photo_kb=len(photo) // 1024 if photo else None,
                           prep_ms=round((t_sent - t0) * 1000), said=said, notice=texts[1], words=last)
        reply, calls, u = await self._model.ask(self._instructions, texts, photo, tools, effort, build.run)
        t_back = time.perf_counter()
        logger.info("brain: %s #%d reply after %.0f ms (model %.0f ms, first output %s ms): in=%d (cached %d, "
                    "written %d) out=%d (thinking %s) stop=%s frame=%s reply: %s",
                    name, n, (t_back - t0) * 1000, (t_back - t_sent) * 1000, u.get("ttft_ms"), u["in"], u["cached"],
                    u.get("written", 0),
                    u["out"], u.get("thinking"), u.get("stop"), saved or "-", reply)
        # one line per tool call the brain made, and what came of it
        allowed = {t[0] for t in tools}
        progress, ignored = None, None
        for call, args in calls:
            if call not in allowed:
                logger.warning("brain: %s #%d tool call %s(%s): no such tool, ignored", name, n, call, json.dumps(args))
                continue
            if call != "set_progress":
                logger.info("brain: %s #%d tool call %s(%s)", name, n, call, json.dumps(args))
                continue
            done = args.get("done")
            if not isinstance(done, int) or not 0 <= done <= total:
                ignored = done
                logger.warning("brain: %s #%d tool call set_progress(%s): ignored, not between 0 and %d", name, n,
                               json.dumps(args), total)
            elif done == build.step:
                logger.info("brain: %s #%d tool call set_progress(%s): unchanged, %d done", name, n, json.dumps(args),
                            done)
            else:
                progress = done
                logger.info("brain: %s #%d tool call set_progress(%s): %d done -> %d done", name, n, json.dumps(args),
                            build.step, done)
        if not calls:
            logger.info("brain: %s #%d no tool call", name, n)
        self._record.event(f"{kind}_back", **{num: n}, model_ms=round((t_back - t_sent) * 1000),
                           total_ms=round((t_back - t0) * 1000), reply=reply, calls=[[c, a] for c, a in calls],
                           progress=progress, ignored_progress=ignored, usage=u)
        return reply, calls, u, progress

    async def _move(self, progress: int) -> str:
        """Move the build to `progress` steps done, record and publish it; returns the line that tells the voice."""
        build = self._build
        before = build.step
        build.set_step(progress)  # index of the step the wearer is on = the number of steps done
        if build.step > before:
            self._record.event("step", done=build.step, now=None if build.finished else build.step + 1)
            if build.finished:
                self._record.event("build", finished=True, took_s=round(time.monotonic() - build.started, 1))
        else:
            self._record.event("step", done=None, reopened=build.step + 1, now=build.step + 1)
        await publish_build(build)
        total = len(build.guide.steps)
        return (f"Progress: all {total} steps are done, the build is finished." if build.finished else
                f"Progress: {build.step} of {total} steps done; the wearer is now on step {build.step + 1} "
                f"({build.guide.steps[build.step].brick}).")

    # ------------------------------------------------------------------ to the voice

    def _commentary(self, text: str, delegation_id: str, n: int = 0, t_asked: float | None = None) -> None:
        # the wire line (live: sent commentary.append ...) is logged by agent.py as it goes out
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
