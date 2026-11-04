"""The brain: the vision model that helps GPT-Live, which talks with the user and cannot see.

The brain is one vision model, behind OpenAI's Responses API or Anthropic's
Messages API (BRAIN_PROVIDER), that keeps one conversation of its own for the
whole call and looks by itself: one watch look after the other, at most one every
BRAIN_WATCH_EVERY seconds, on the newest camera frame scaled to BRAIN_WATCH_SIDE,
at BRAIN_EFFORT. Nobody asks it anything: each look's message carries the lines
the user and the assistant said since the look before, so the brain reads the
user's questions and claims ("I placed it", "is this right?") there, and what it
writes stays in its own conversation. GPT-Live hears of a look only through the
tools: tell gives it a fact silently (thinking, context for what it says next),
say has it tell the user something now (commentary), set_progress moves the
build and show puts a step's picture on the glasses, each told to GPT-Live as
commentary. On 2026-11-02 every look's text went to GPT-Live as thinking, 45
lines in 107 s, and GPT-Live read them out, the doubts ("I still can't count")
above all; the brain now chooses what the assistant needs, as OpenAI's guidance
has it: an update when something useful changes.

Until the pilot of 2026-11-03 GPT-Live also handed the user's words over
(client delegation) and the brain answered each hand-over with a look of its own
at BRAIN_SIDE, cancelling the watch meanwhile. The pilot's participant felt those
answers come sometimes fast, sometimes slow (2.7 to 5.7 s from the hand-over to
the spoken answer, the same spread the watch has), so the look is gone: GPT-Live's
prompt tells it never to hand over but to answer from what the brain has told it,
and since the GPT-Live session cannot be started without a delegation target, a
hand-over it makes all the same is closed at once with a commentary that says
so (on_delegation), without a request to the vision model. The record counts them.

The brain's conversation (Look, one per request) is a chat with tools as a model
is used anywhere: a user message per look, with the lines the user and the
assistant said since the look before ("User: ...", "Assistant: ...") and the
photo; the model's reply, text and tool calls, in the provider's own items; and
one result per tool call, what carrying it out did. Nothing is dropped or
rewritten, except that the photo is taken out of a look once the model has
answered on it: images are too large to keep (about 1500 tokens each, a look
every two seconds), and what the model wrote of the photo is what it keeps of
it. So the model reads its own earlier observations and actions, and the
progress it knows is the one its last set_progress result told it. For the
prompt cache every request is the one before plus one look, the photo of the
look before taken out.

The picture of a step on the glasses (show) follows the user's words: they asked
for it, or took the assistant up on an offer the brain made (say), as a helper
standing beside them would offer before pointing at the instructions; the
prompt says so, the code does not hold the tool back. The picture is a file
beside the task (render_pictures.py), named in an attribute and then sent to the
glasses as a byte stream; the glasses show that it is on its way, then the
picture itself. It goes away when the progress moves (Build.set_step) or when
the brain is asked to take it away (show 0).

Every request is built the same way:

    tools         set_progress(done), tell(text), say(text), show(step), the same every time
    instructions  the rules + the whole task file                   fixed, so the prompt cache hits
    conversation  every look so far, the newest with its photo

A watch look that fails or takes longer than BRAIN_TIMEOUT is logged and the next
one follows; with no camera frame yet none is made. A look that gets no answer
(failed, timed out) is not kept, and the lines it carried come again with the
next look. Every step of a look goes into the call's record (runlog.py): the
photo and the message as sent, the reply, the timings. `_look_once` and
`_message` still take the handed-over words of a look of the old kind, which
eval/brain-thread-replay replays from the records of 2026-10-29 to 11-03.
"""

from __future__ import annotations

import asyncio
import base64
import difflib
import io
import json
import logging
import time
from dataclasses import dataclass, field

from livekit.agents import AgentSession

from frames import FrameTap, bottom_square
from gpt.prompts import HANDED, NO_ONE_SPOKE, NO_PHOTO, NO_WORDS_YET, brain_instructions
from guide import PICTURE_TOPIC, Build, publish_build
from livekit.agents import get_job_context
from runlog import RunLog

logger = logging.getLogger("rayneo-agent.brain")



def handed_back(last: str | None) -> str:
    """What closes a hand-over GPT-Live makes although its prompt tells it not to: a commentary on the hand-over's id
    that repeats the brain's last line, so the voice answers from it when it covers the question and otherwise says
    it is checking; the next watch look answers the words anyway (the brain's rule 5). The first wording, "answer
    from what the helper has already told you", made the voice give the next step as if the one before were checked;
    the second, "still looking at it", made it say so even when it knew the answer (eval/voice-script, 2026-11-03)."""
    if not last:
        return "Camera: nothing seen yet; the helper says when it has."
    fact = last.split(": ", 1)[1] if last.startswith(("Camera: ", "Progress: ", "Picture: ")) else last
    return f"Camera: nothing new since the last look; still: {fact}"


# (name, description, JSON schema of the arguments); the same for both providers
SET_PROGRESS = (
    "set_progress",
    "Records how far the build is: the number of steps, counted from step 1, that the photo shows built right, from 0 "
    "to the number of the last step. It can go up by more than one, or down when an earlier step turns out wrong. The "
    "step list on the glasses and the assistant follow it, so what you write should say the same, and progress "
    "recorded higher than the plate shows leaves the user building on a mistake. Call it only when the photo lets "
    "you tell and the number differs from the progress recorded, which the result of your last call told you; leave "
    "it out when part of the build is hidden or too small to judge, and when the user only says they are done "
    "without the photo showing it. seen and basis go into the call's record and are never spoken: seen is one "
    "sentence of what the photo shows that the number rests on, basis says how far the photo itself carries it.",
    {"type": "object", "properties": {"done": {"type": "integer",
                                               "description": "how many steps, from step 1, are built right"},
                                      "seen": {"type": "string",
                                               "description": "one sentence: the brick or bricks the number rests on and where they sit"},
                                      "basis": {"type": "string", "enum": ["studs read", "colour and place", "step and words"],
                                                "description": "studs read: you counted the brick's studs in this photo; colour and place: "
                                                               "you saw its colour and position but not its studs; step and words: the "
                                                               "step list and what the user said carry it more than the photo"}},
     "required": ["done", "seen", "basis"], "additionalProperties": False})
TELL = (
    "tell",
    "Gives the assistant a fact silently, for a later answer; it does not speak it on its own, but it tends to work it "
    "into what it says, so tell rarely: where bricks lie on the desk when the user will look for them, a picture on "
    "the glasses. Not hands, not a brick being set down, not what the user is doing: write those for yourself. One "
    "tell every twenty seconds reaches the assistant; the rest is held. What you write outside this tool stays with "
    "you.",
    {"type": "object", "properties": {"text": {"type": "string",
                                               "description": "one short sentence of plain facts"}},
     "required": ["text"], "additionalProperties": False})
SAY = (
    "say",
    "Has the assistant tell the user something now, without their asking, in its own words. kind says what it is: "
    "news, something the user acts on now (the brick in their hand named, a placement wrong, an offer of a picture, "
    "an answer to them), which is spoken at once; or waiting, nothing can be told yet (studs unclear, hands in the "
    "way, the picture poor) with what would help, which is spoken at most once every fifteen seconds, so say it and "
    "the extras are held.",
    {"type": "object", "properties": {"text": {"type": "string",
                                               "description": "one or two short sentences of plain facts"},
                                      "kind": {"type": "string", "enum": ["news", "waiting"],
                                               "description": "news: the user acts on it now; waiting: nothing can be told yet"}},
     "required": ["text", "kind"], "additionalProperties": False})
SHOW = (
    "show",
    "Puts the picture of one step on the user's glasses, in the square that otherwise shows what the camera sees: "
    "the plate from above with the bricks of the steps up to that one, the step's own brick outlined. Call it when "
    "the user asks to see a picture or accepts the assistant's offer of one, with the step they are on or the step "
    "their question is about; call it with 0 when they say they do not need it any more. The picture stays until "
    "the progress moves or you take it away. Write what to look at in it, since the assistant points the user to "
    "the picture in your words.",
    {"type": "object", "properties": {"step": {"type": "integer",
                                               "description": "the step's number as the user counts them, from "
                                                              "1; 0 takes the picture away"}},
     "required": ["step"], "additionalProperties": False})
TOOLS = [SET_PROGRESS, TELL, SAY, SHOW]  # the same for every look, so the cached prefix holds

# how a line of the chat history is labelled in a look's message
WHO = {"user": "User", "assistant": "Assistant"}

SAY_REPEAT_S = 8.0  # a say that says what the last say said, this soon after it, is held: the voice has it already
SAY_REPEAT_RATIO = 0.6  # how alike two says must read (difflib ratio) to count as the same
WAIT_SAY_EVERY_S = 15.0  # a waiting say (nothing can be told yet) goes out at most this often; the model asks at every look
TELL_EVERY_S = 20.0  # a tell goes to the voice at most this often: GPT-Live reads thinking aloud, and 34 tells in a call made a monologue
GATE_WAIT_MAX_S = 15.0  # how long a line to the voice waits for both sides to fall silent before it goes anyway
WAITING_STALE_S = 10.0  # a waiting line older than this when the voice is free is dropped: the moment has passed

# the result of a tool call the look did not get to carry out (the call ended while it was being done)
NOT_DONE = "Not carried out: a request from the assistant came first."


@dataclass
class Look:
    """One look, as a turn of the brain's conversation: its message, the model's reply and the tools' results.

    `text` is what the message says besides the photo: the lines said since the look before, and whether the
    assistant handed the user's words over. `photo` is the frame's bottom square as a JPEG until the model has
    answered on it, then None. `output` is the model's reply in the provider's own items, passed back as they
    came, and `calls` the tool calls in it as (call id, name, arguments). `results` is what carrying each call
    out did, by call id, written as each is done; a call still without one when the next look is sent gets
    NOT_DONE."""
    text: str
    photo: bytes | None
    output: list = field(default_factory=list)
    calls: list[tuple[str, str, dict]] = field(default_factory=list)
    results: dict[str, str] = field(default_factory=dict)


def _jpeg(frame, side: int) -> bytes:
    """The bottom square of the frame (frames.bottom_square) as a JPEG."""
    buf = io.BytesIO()
    bottom_square(frame, side).save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _data_url(photo: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(photo).decode()


class OpenAIModel:
    """Responses API, the conversation managed here: every request carries all the looks as input items
    (`store=False`), the model's output items passed back as they came, its reasoning included as encrypted
    content so a later request can read it.

    The prompt cache is driven by explicit breakpoints (gpt-5.6 and later): the API writes a cache entry only at a
    breakpoint, one implicit at the end of the request unless told otherwise, and a later request is matched only
    against entries, not against any prefix it happens to share. Found out on 2026-11-02: with the photo at the end
    of every request and gone from the next, no entry ever matched and only the instructions and tools were
    cached, 1992 tokens of a request grown to 8700. So every look's text block carries an explicit breakpoint and
    the request runs in explicit mode: the API writes entries at the latest four looks' texts and none at the
    photo, which is never seen again; the next request matches the entry at the look before and pays for the
    look's answer, the new lines and the new photo only. The photo goes last, as a user item of its own, so that
    nothing of it precedes the breakpoint."""

    def __init__(self, model: str, detail: str) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI()
        self._model, self._detail = model, detail

    def _render(self, looks: list[Look]) -> list:
        items: list = []
        for look in looks:
            items.append({"role": "user", "content": [{"type": "input_text", "text": look.text,
                                                       "prompt_cache_breakpoint": {"mode": "explicit"}}]})
            items.extend(look.output)
            for call_id, _, _ in look.calls:
                items.append({"type": "function_call_output", "call_id": call_id,
                              "output": look.results.get(call_id, NOT_DONE)})
            if look.photo is not None:  # only the newest look still has one
                items.append({"role": "user", "content": [
                    {"type": "input_image", "image_url": _data_url(look.photo), "detail": self._detail}]})
        return items

    async def ask(self, instructions: str, looks: list[Look], tools: list, effort: str, key: str
                  ) -> tuple[str, list[tuple[str, str, dict]], list, dict]:
        """Answers the newest look. Returns the reply text, the tool calls, the output items to keep, the usage."""
        kw = {"reasoning": {"effort": effort}} if effort else {}
        resp = await self._client.responses.create(
            model=self._model, instructions=instructions, input=self._render(looks),
            tools=[{"type": "function", "name": n, "description": d, "parameters": p, "strict": True} for n, d, p in tools],
            store=False, include=["reasoning.encrypted_content"], prompt_cache_key=key,
            prompt_cache_options={"mode": "explicit"}, **kw,
        )
        if not resp.output:
            raise RuntimeError("the model returned no output")
        calls = [(o.call_id, o.name, json.loads(o.arguments or "{}")) for o in resp.output if o.type == "function_call"]
        u = resp.usage
        out_details = getattr(u, "output_tokens_details", None) if u else None
        return resp.output_text, calls, list(resp.output), {
            "in": u.input_tokens if u else 0, "out": u.output_tokens if u else 0,
            "cached": u.input_tokens_details.cached_tokens if u and u.input_tokens_details else 0,
            "written": 0,  # OpenAI caches by itself and reports no writes
            "thinking": getattr(out_details, "reasoning_tokens", None) if out_details is not None else None,
            "stop": resp.status, "ttft_ms": None,  # not streamed
        }


class AnthropicModel:
    """Messages API, the conversation managed here: every request carries all the looks as messages, a user
    message per look (the results of the look before first, then the text, then the photo) and the model's content
    blocks passed back as they came, thinking blocks included. Cache breakpoints are explicit here too: one on the
    instructions and one on the newest look's text, before the photo, so the next request finds the entry written
    at this look's text (the API looks back twenty blocks from a breakpoint) and pays for what follows it only.
    Effort none = thinking disabled; any other value = adaptive thinking at that effort."""

    def __init__(self, model: str) -> None:
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic()
        self._model = model
        # "no thinking": disabled on most models; Sonnet 5.5 rejects that and takes between_tools (no up-front
        # thinking), which the API's error names; switched once, on the first such error
        self._off = {"type": "disabled"}

    @staticmethod
    def _render(looks: list[Look]) -> list:
        messages: list = []
        results: list = []  # the tool results of the look before, which open the next user message
        for look in looks:
            content: list = list(results)
            content.append({"type": "text", "text": look.text}
                           | ({"cache_control": {"type": "ephemeral"}} if look is looks[-1] else {}))
            if look.photo is not None:  # only the newest look still has one
                content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                            "data": base64.b64encode(look.photo).decode()}})
            messages.append({"role": "user", "content": content})
            if look.output:
                messages.append({"role": "assistant", "content": look.output})
            results = [{"type": "tool_result", "tool_use_id": call_id, "content": look.results.get(call_id, NOT_DONE)}
                       for call_id, _, _ in look.calls]
        return messages

    async def ask(self, instructions: str, looks: list[Look], tools: list, effort: str, key: str
                  ) -> tuple[str, list[tuple[str, str, dict]], list, dict]:
        from anthropic import BadRequestError

        try:
            return await self._ask(instructions, looks, tools, effort)
        except BadRequestError as e:
            if self._off["type"] != "disabled" or "between_tools" not in str(e):
                raise
            logger.info("brain: %s takes no disabled thinking, using between_tools", self._model)
            self._off = {"type": "between_tools"}
            return await self._ask(instructions, looks, tools, effort)

    async def _ask(self, instructions: str, looks: list[Look], tools: list, effort: str
                   ) -> tuple[str, list[tuple[str, str, dict]], list, dict]:
        kw: dict = {"thinking": self._off}
        if effort and effort != "none":
            kw = {"thinking": {"type": "adaptive"}, "output_config": {"effort": effort}}
        # Streamed only to time the first output (ttft: the way there, the API's queue and its reading of the
        # input, apart from the writing); the reply is used once complete.
        t0, ttft = time.perf_counter(), None
        async with self._client.messages.stream(
            model=self._model, max_tokens=4096, **kw,
            tools=[{"name": n, "description": d, "input_schema": p, "strict": True} for n, d, p in tools],
            system=[{"type": "text", "text": instructions, "cache_control": {"type": "ephemeral"}}],
            messages=self._render(looks),
        ) as stream:
            async for event in stream:
                if ttft is None and event.type == "content_block_start":
                    ttft = time.perf_counter() - t0
            resp = await stream.get_final_message()
        u = resp.usage
        text_out = " ".join(b.text for b in resp.content if b.type == "text").strip()
        calls = [(b.id, b.name, b.input or {}) for b in resp.content if b.type == "tool_use"]
        # an empty text block is refused when passed back, so it is not kept
        output = [b.model_dump(exclude_none=True) for b in resp.content if not (b.type == "text" and not b.text.strip())]
        if not output:
            raise RuntimeError("the model returned no output")
        details = getattr(u, "output_tokens_details", None)
        return text_out, calls, output, {
            "in": u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0),
            "out": u.output_tokens, "cached": u.cache_read_input_tokens or 0,
            "written": u.cache_creation_input_tokens or 0,
            "thinking": getattr(details, "thinking_tokens", None) if details is not None else None,
            "stop": resp.stop_reason, "ttft_ms": round(ttft * 1000) if ttft is not None else None,
        }


def make_model(provider: str, model: str, detail: str):
    """The brain's model client: BRAIN_PROVIDER openai or anthropic."""
    if provider == "anthropic":
        return AnthropicModel(model)
    return OpenAIModel(model, detail)


class Brain:
    def __init__(self, session: AgentSession, build: Build, tap: FrameTap, model, effort: str,
                 watch_side: int, watch_every: float, language: str, timeout: float = 12.0,
                 record: RunLog | None = None) -> None:
        self._timeout = timeout
        self._record = record or RunLog(None, "")
        self._notes: list[str] = []  # lines for the model's next message, such as a pending step that stood
        self._pending_progress: tuple[int, int, dict] | None = None  # (steps done, the look that recorded it, seen and basis), until the next look
        self._line_class: dict[str, tuple[str, bool]] = {}  # a line _carry_out made -> (class, waiting)
        self._pending_lines: dict[str, tuple[float, str, bool]] = {}  # class -> (when, line, waiting), the newest, awaiting the voice
        self._gate: asyncio.Task | None = None
        self._session = session
        self._build = build
        self._tap = tap
        self._model = model
        self._effort = effort
        self._watch_side = watch_side
        self._watch_every = watch_every
        self._instructions = brain_instructions(build.guide, language)
        self._looks: list[Look] = []  # the conversation: every look the model answered, in order
        self._seen: set[str] = set()  # ids of the chat history items already in a kept look
        self._pending: str | None = None  # handed-over words put in a look before the history had them (replays only)
        self._turn = asyncio.Lock()  # one look is built, sent and kept at a time
        self._asks = 0  # hand-overs GPT-Live made all the same, each closed at once
        self._last_line: str | None = None  # the last line given to the voice, repeated to close a hand-over
        self._last_say: tuple[float, str] | None = None  # when and what the brain last had the voice say
        self._last_tell: float | None = None  # when the brain last gave the voice a silent fact
        self._watcher: asyncio.Task | None = None
        self._look: asyncio.Task | None = None  # the watch look running, if any
        self._look_w = 0

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
        """One watch look after the other, each starting at least watch_every after the one before."""
        w = 0
        while True:
            started = time.monotonic()
            if self._tap.latest is not None:
                w += 1
                self._look_w = w
                self._look = asyncio.create_task(self._watch(w), name="watch_look")
                await asyncio.wait([self._look])  # returns on cancel too, which stop_watching does
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
        """One watch look and what comes of it: the reply stays in the brain's conversation; a tell goes to GPT-Live
        as thinking, a say and a progress moved as one commentary."""
        text, calls, look = await self._look_once("watch", w, self._watch_side, None, TOOLS)
        speak = await self._carry_out(look, calls, "watch", w)
        for line in speak:
            cls, waiting = self._line_class.pop(line, ("say", False))
            self._to_voice(line, cls, waiting, w)
        await self._settle_progress(w, calls)

    # ------------------------------------------------------------------ hand-overs

    def on_delegation(self, d) -> None:
        """GPT-Live handed the user's words over although its prompt tells it not to: close the hand-over at once
        with the last line again (handed_back), so it answers from what it has been told, and count it. No request is made and the watch
        is not touched; the words it came with go into the record, since the next watch look reads them from the
        history anyway."""
        self._asks += 1
        words = d.pending_transcript.strip()  # the turn not yet in the history; often empty
        logger.info("delegation: %s #%d closed at once, user: %s", d.id, self._asks, words or "(no words came with it)")
        self._record.event("delegation", n=self._asks, id=d.id, words=words)
        text = handed_back(self._last_line)
        self._record.event("commentary", n=self._asks, id=d.id, text=text,
                           voice_speaking=self._session.agent_state == "speaking")
        self._session.current_agent.duplex_session.append_commentary(text, delegation_id=d.id)

    # ------------------------------------------------------------------ one look

    def _message(self, words: str | None) -> tuple[str, list[str], str | None]:
        """The text of the next look's message, the ids of the chat history items it takes, and the delegation's
        words it put in before the history had them, if any; both kept once the look is. The text is the lines the
        user and the assistant said since the look before, in the history's order, each labelled; for a handed-over
        look (`words` given, maybe empty; replays only) the words that came with it when the history does not have
        them yet, and HANDED last. With nothing new, NO_ONE_SPOKE. The history's own line for words put in earlier is taken as
        seen when it comes, so the user is not read as saying it twice."""
        lines, ids, pending = self._notes, [], self._pending
        self._notes = []
        for item in self._session.history.items:
            if item.type != "message" or item.role not in ("user", "assistant") or item.id in self._seen:
                continue
            text = " ".join((item.text_content or "").split())
            if not text:
                continue  # a turn still being transcribed: taken once it has words
            ids.append(item.id)
            if item.role == "user" and pending and (pending in text or text in pending):
                pending = None
                continue
            lines.append(f"{WHO[item.role]}: {text}")
        if words is None:
            return "\n".join(lines) or NO_ONE_SPOKE, ids, pending
        users = [line[len("User: "):] for line in lines if line.startswith("User: ")]
        if words and not any(words in u or u in words for u in users):
            lines.append(f"User: {words}")
            pending = words
        elif not words and not users:
            lines.append(NO_WORDS_YET)
        lines.append(HANDED)
        return "\n".join(lines), ids, pending

    async def _look_once(self, kind: str, n: int, side: int, words: str | None, tools: list
                         ) -> tuple[str, list[tuple[str, str, dict]], Look]:
        """Send one request on the newest frame and log and record it as `kind` number n: "watch", the only kind
        the call makes, or "look" with the handed-over `words`, the kind the replays of old records make
        (eval/brain-thread-replay). Returns the reply, the tool calls, and the Look, kept in the conversation with
        its output; the calls are carried out by the caller (_carry_out), which writes their results into the
        Look. A look the model does not answer (cancelled, failed) is taken out again."""
        async with self._turn:
            name = "delegation" if kind == "look" else "watch"
            num = "n" if kind == "look" else "w"
            t0 = time.perf_counter()
            frame, seq = self._tap.latest, self._tap.count  # the newest frame (~15 a second) and its number in this call
            age_ms = (time.monotonic() - self._tap.latest_at) * 1000 if frame is not None else None
            photo = await asyncio.to_thread(_jpeg, frame, side) if frame is not None else None
            text, ids, pending = self._message(words)
            if photo is None:
                text = f"{NO_PHOTO}\n{text}"
            look = Look(text=text, photo=photo)
            self._looks.append(look)
            build = self._build
            total = len(build.guide.steps)
            t_sent = time.perf_counter()
            prefix = "ask" if kind == "look" else "watch"
            saved = self._record.photo(photo, f"{prefix}{n}-s{build.step + 1}") if photo else None
            if frame is not None:
                logger.info("brain: %s #%d frame %d (%dx%d, %.0f ms old); request sent %.0f ms after the start: jpeg "
                            "%d KB at %d px, look %d of the conversation, %d new lines, step %d", name, n, seq,
                            frame.width, frame.height, age_ms, (t_sent - t0) * 1000, len(photo) // 1024, side,
                            len(self._looks), len(ids), build.step + 1)
            else:
                logger.warning("brain: %s #%d no camera frame this call; request sent without a photo, step %d", name,
                               n, build.step + 1)
            self._record.event(f"{kind}_sent", **{num: n}, step=build.step + 1, frame=seq if frame is not None else None,
                               frame_size=f"{frame.width}x{frame.height}" if frame is not None else None,
                               frame_age_ms=round(age_ms) if age_ms is not None else None, side=side,
                               photo=saved, photo_kb=len(photo) // 1024 if photo else None,
                               prep_ms=round((t_sent - t0) * 1000), lines=text, looks=len(self._looks), words=words)
            try:
                reply, calls, output, u = await self._model.ask(self._instructions, self._looks, tools, self._effort,
                                                                build.run)
            except BaseException:
                self._looks.remove(look)  # no answer: not kept, and its lines come again with the next look
                raise
            look.photo, look.output, look.calls = None, output, calls
            self._seen.update(ids)
            self._pending = pending
            t_back = time.perf_counter()
            logger.info("brain: %s #%d reply after %.0f ms (model %.0f ms, first output %s ms): in=%d (cached %d, "
                        "written %d) out=%d (thinking %s) stop=%s frame=%s reply: %s",
                        name, n, (t_back - t0) * 1000, (t_back - t_sent) * 1000, u.get("ttft_ms"), u["in"], u["cached"],
                        u.get("written", 0), u["out"], u.get("thinking"), u.get("stop"), saved or "-", reply)
            # what the set_progress call, if any, will do, for the record; _carry_out does it
            progress, ignored = None, None
            for _, call, args in calls:
                if call != "set_progress":
                    logger.info("brain: %s #%d tool call %s(%s)", name, n, call, json.dumps(args))
                    continue
                done = args.get("done")
                if not isinstance(done, int) or not 0 <= done <= total:
                    ignored = done
                    logger.warning("brain: %s #%d tool call set_progress(%s): ignored, not between 0 and %d", name, n,
                                   json.dumps(args), total)
                elif done == build.step:
                    logger.info("brain: %s #%d tool call set_progress(%s): unchanged, %d done", name, n,
                                json.dumps(args), done)
                else:
                    progress = done
                    logger.info("brain: %s #%d tool call set_progress(%s): %d done -> %d done", name, n,
                                json.dumps(args), build.step, done)
            if not calls:
                logger.info("brain: %s #%d no tool call", name, n)
            self._record.event(f"{kind}_back", **{num: n}, model_ms=round((t_back - t_sent) * 1000),
                               total_ms=round((t_back - t0) * 1000), reply=reply, calls=[[c, a] for _, c, a in calls],
                               progress=progress, ignored_progress=ignored, usage=u)
            return reply, calls, look

    async def _carry_out(self, look: Look, calls: list[tuple[str, str, dict]], kind: str, n: int) -> list[str]:
        """Carry out the look's tool calls, write each result into the look, and return the lines GPT-Live is to
        say now as commentary. set_progress goes before show, since a move takes any picture away."""
        speak = []
        for call_id, name, args in sorted(calls, key=lambda c: c[1] == "show"):
            if name == "set_progress":
                result, line = await self._move(args.get("done"), args)
            elif name == "show":
                result, line = await self._show(args.get("step"), kind, n)
            elif name == "say":
                said = " ".join(str(args.get("text") or "").split())
                waiting = args.get("kind") == "waiting"
                since = time.monotonic() - self._last_say[0] if self._last_say else None
                if not said:
                    result, line = "Ignored: nothing to say.", None
                elif waiting and since is not None and since < WAIT_SAY_EVERY_S:
                    # The model asks for a better view at every look while a state lasts (the replay of 2026-11-04 under
                    # 0.25 Mbps: "turn the studs toward me" five times in 25 s); one such line every ten seconds keeps the
                    # helper present without nagging, and the model is told so its own record stays honest.
                    self._record.event("say_held", **{"w" if kind == "watch" else "n": n}, text=said, say_kind="waiting", since_s=round(since, 1))
                    result, line = f"Held: a line went out {since:.0f} s ago; a waiting line is spoken every {WAIT_SAY_EVERY_S:.0f} s at most.", None
                elif self._repeats(said):
                    self._record.event("say_held", **{"w" if kind == "watch" else "n": n}, text=said, say_kind="repeat", since_s=round(since, 1))
                    result, line = "Held: this says what your last say said, seconds ago; the assistant has it.", None
                else:
                    self._last_say = (time.monotonic(), said)
                    self._record.event("say", **{"w" if kind == "watch" else "n": n}, text=said, say_kind="waiting" if waiting else "news")
                    result, line = "The assistant says it.", f"Camera: {said}"
            elif name == "tell":
                told = " ".join(str(args.get("text") or "").split())
                since = time.monotonic() - self._last_tell if self._last_tell is not None else None
                if not told:
                    result, line = "Ignored: nothing to tell.", None
                elif since is not None and since < TELL_EVERY_S:
                    # GPT-Live reads thinking aloud: the run of 2026-11-04 12:30 had 34 tells and a voice that spoke 91 %
                    # of the time, every hand movement included. One silent fact every TELL_EVERY_S is what gets through.
                    self._record.event("tell_held", **{"w" if kind == "watch" else "n": n}, text=told, since_s=round(since, 1))
                    result, line = f"Held: a fact went to the assistant {since:.0f} s ago; one every {TELL_EVERY_S:.0f} s at most. Keep this for yourself.", None
                else:
                    self._last_tell = time.monotonic()
                    self._record.event("tell", **{"w" if kind == "watch" else "n": n}, text=told)
                    self._session.current_agent.duplex_session.append_thinking(f"Camera: {told}")
                    self._last_line = f"Camera: {told}"
                    result, line = "The assistant knows it.", None
            else:
                result, line = f"No such tool here: {name}.", None
            look.results[call_id] = result
            if line:
                speak.append(line)
                self._last_line = line
                self._line_class[line] = ("say", bool(args.get("kind") == "waiting")) if name == "say" else ("state", False)
        return speak

    def _to_voice(self, line: str, cls: str, waiting: bool, w: int) -> None:
        """Hands a line to the voice once neither side is speaking. While one is, the newest line of each class waits,
        `state` (Progress, Picture) and `say` (Camera), and a newer one of the same class replaces it, so the voice
        never reads a queue of stale lines, which the second pilot heard three at a time ("That's step two. Now take
        the dark red... Two of five steps done. You're on step three..."), and does not start over the wearer, which it
        did four to eight times a run. A waiting line that has waited WAITING_STALE_S is dropped: the moment has passed.
        After GATE_WAIT_MAX_S the lines go anyway."""
        if cls in self._pending_lines:
            self._record.event("line_replaced", w=w, text=self._pending_lines[cls][1], by=line)
        self._pending_lines[cls] = (time.monotonic(), line, waiting)
        if self._gate is None or self._gate.done():
            self._gate = asyncio.create_task(self._release_lines(), name="to_voice")

    async def _release_lines(self) -> None:
        t0 = time.monotonic()
        while self._pending_lines:
            busy = self._session.agent_state == "speaking" or getattr(self._session, "user_state", None) == "speaking"
            if not busy or time.monotonic() - t0 >= GATE_WAIT_MAX_S:
                parts = []
                for cls in ("state", "say"):
                    if cls not in self._pending_lines:
                        continue
                    when, line, waiting = self._pending_lines.pop(cls)
                    if waiting and time.monotonic() - when >= WAITING_STALE_S:
                        self._record.event("line_dropped", text=line, waited_s=round(time.monotonic() - when, 1))
                        continue
                    parts.append(line)
                if parts:
                    text = " ".join(parts)
                    self._record.event("commentary", id=None, text=text, waited_s=round(time.monotonic() - t0, 1),
                                       voice_speaking=self._session.agent_state == "speaking")
                    self._session.current_agent.duplex_session.append_commentary(text)
                t0 = time.monotonic()
                continue
            await asyncio.sleep(0.1)

    async def _settle_progress(self, w: int, calls: list[tuple[str, str, dict]]) -> None:
        """A step recorded as done at an earlier look stands now, unless this look moved the progress below it: the
        second pilot had a step recorded while the hand was still on it and withdrawn six seconds later. Standing, it
        is published, told to the voice and noted for the model's next message; withdrawn, nothing was ever said."""
        if self._pending_progress is None or self._pending_progress[1] == w:
            return
        done, _, rests = self._pending_progress
        self._pending_progress = None
        lowered = any(c == "set_progress" and isinstance(a.get("done"), int) and a["done"] < done for _, c, a in calls)
        if lowered or done <= self._build.step:
            self._record.event("progress_withdrawn", w=w, done=done)
            return
        result = await self._commit_progress(done, rests)
        self._notes.append(f"{result} Your pending call stood.")
        self._to_voice(self._progress_line(done), "state", False, w)

    def _repeats(self, said: str) -> bool:
        """Whether `said` says what the last say said, within SAY_REPEAT_S of it."""
        if self._last_say is None or time.monotonic() - self._last_say[0] > SAY_REPEAT_S:
            return False
        return difflib.SequenceMatcher(None, self._last_say[1].lower(), said.lower()).ratio() >= SAY_REPEAT_RATIO

    async def _move(self, done, args: dict | None = None) -> tuple[str, str | None]:
        """Move the build to `done` steps done, record and publish it. Returns the tool's result and the line that
        tells the voice, or None when nothing moved. `args` carries the call's seen and basis for the record."""
        build = self._build
        rests = {"seen": (args or {}).get("seen"), "basis": (args or {}).get("basis")}
        total = len(build.guide.steps)
        if not isinstance(done, int) or not 0 <= done <= total:
            return f"Ignored: done must be a whole number from 0 to {total}.", None
        if done == build.step:
            return f"Unchanged: {done} of {total} steps were already recorded as done.", None
        if done > build.step:
            if self._pending_progress is not None and self._pending_progress[0] == done:
                self._pending_progress = None  # said twice: it stands now
                return await self._commit_progress(done, rests), self._progress_line(done)
            self._pending_progress = (done, self._look_w, rests)
            self._record.event("progress_pending", w=self._look_w, done=done, **rests)
            return (f"Recorded as pending: {done} of {total} steps done stands at your next look unless that look "
                    "shows otherwise; the assistant is told then."), None
        build.set_step(done)  # index of the step the user is on = the number of steps done
        self._record.event("step", done=None, reopened=build.step + 1, now=build.step + 1, **rests)
        await publish_build(build)
        where = self._where()
        return f"Recorded: {where}. The assistant is told.", f"Progress: {where}."

    def _where(self) -> str:
        build = self._build
        total = len(build.guide.steps)
        return (f"all {total} steps done, the build is finished" if build.finished else
                f"{build.step} of {total} steps done; the user is on step {build.step + 1} "
                f"({build.guide.steps[build.step].brick})")

    def _progress_line(self, done: int) -> str:
        return f"Progress: {self._where()}."

    async def _commit_progress(self, done: int, rests: dict) -> str:
        """The build moves up to `done`, is recorded and published with what it rests on (seen, basis); returns the
        tool result, the line for the voice being _progress_line."""
        build = self._build
        picture = build.picture
        build.set_step(done)
        self._record.event("step", done=build.step, now=None if build.finished else build.step + 1, **rests)
        if build.finished:
            self._record.event("build", finished=True, took_s=round(time.monotonic() - build.started, 1))
        await publish_build(build)
        result = f"Recorded: {self._where()}. The assistant is told."
        if picture:
            result += " The picture is taken off the glasses."
        return result

    async def _show(self, step, kind: str, n: int) -> tuple[str, str | None]:
        """Put the picture of step `step` on the glasses (0: take it away), record and publish it. Returns the
        tool's result and the line that tells the voice. The attribute that names the picture goes first, on the
        signalling channel, so the glasses know a picture is coming and show that it is on its way; the bytes
        follow as a byte stream on PICTURE_TOPIC over the reliable data channel, late under a slow network rather
        than missing, and the glasses show the picture once they have it. The time the send took is recorded."""
        build = self._build
        total = len(build.guide.steps)
        if not isinstance(step, int) or not 0 <= step <= total:
            logger.warning("brain: %s #%d tool call show(%s): ignored, not between 0 and %d", kind, n,
                           json.dumps(step), total)
            return f"Ignored: step must be a whole number from 0 to {total}.", None
        before = build.picture
        build.show(step)
        await publish_build(build)
        sent: dict = {}
        if step:
            name, data = build.guide.picture_name(step), build.guide.picture(step).read_bytes()
            t0 = time.perf_counter()
            writer = await get_job_context().room.local_participant.stream_bytes(
                name, total_size=len(data), mime_type="image/png", topic=PICTURE_TOPIC)
            await writer.write(data)
            await writer.aclose()
            sent = {"name": name, "bytes": len(data), "send_ms": round((time.perf_counter() - t0) * 1000)}
            logger.info("picture: %s (%d KB) sent to the glasses in %d ms", name, len(data) // 1024, sent["send_ms"])
        self._record.event("picture", **{"w" if kind == "watch" else "n": n}, step=step or None,
                           before=before or None, **sent)
        if not step:
            return ("The picture is taken away; the glasses show the camera.",
                    "Picture: the glasses show the camera again, no picture.")
        brick = build.guide.steps[step - 1].brick
        return (f"The glasses show the picture of step {step} ({brick}).",
                f"Picture: the glasses now show the picture of step {step} ({brick}).")
