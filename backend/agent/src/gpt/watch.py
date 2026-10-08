"""The loop that looks and tells: camera -> gate -> judge -> state machine -> GPT-Live.

Shelved: the GPT path runs on the brain (brain.py) since 2026-10-08; this loop,
gate.py, judge_*.py and progress.py are kept as they were (tag lego-harness-v1),
and eval/ still runs the last three.

Every frame from the glasses comes through here (FrameTap). The gate (gate.py)
passes a frame only when the whole plate is in view, no hand is over it and it
has been still for a moment; the judge (judge_cv.py by default, judge_vlm.py
with JUDGE=vlm) then answers about the current step only; the state machine
(progress.py) needs `confirm` agreeing answers before anything counts. The
code owns the step: the voice model never decides where the build stands.

Judging does not wait for the previous verdict: while the gate passes, a new
frame goes to the judge every `gap` seconds with up to `inflight` calls in the
air (a VLM takes ~2.5 s; serial calls made a step take 6 s to confirm). A
verdict that arrives after the step has moved on is dropped.

What reaches GPT-Live:
- a step newly confirmed, or a brick confirmed wrong, as an *instruction*
  (the plugin's append_instructions, which the model follows at once and which
  may cut into its current sentence). Commentary (generate_reply) does not
  interrupt, and holding the note until the voice was quiet made the wearer
  hear "let me check" and only then "yes, that's right";
- nothing per frame. Early versions put every verdict into the model's
  context and it narrated the camera from stale notes;
- each time the wearer starts speaking, once, as *thinking* (silent context,
  append_thinking): where the build stands and the newest verdict, or why the
  camera has had no clear view. It goes in before the voice can reply, so the
  voice always has it; the verdict is about a frame ~2-3 s old (the judge's
  latency), which is the price of never interrupting. check_now (tools.py,
  unregistered) gave the same text on request.

Two timing layers in the log: `judge:` lines carry the judge's own latency per
frame; `voice:` lines the delay from a camera note to the voice starting to
speak, or that it cut into speech. The glasses measure the wearer's wait
separately (`latency:` lines).
"""

from __future__ import annotations

import asyncio
import io
import logging
import time

from livekit.agents import AgentSession
from PIL import Image

from frames import FrameTap, to_image
from gate import Decision, Gate
from guide import Build
from judge_cv import Verdict
from progress import Event, Kind, Tracker

logger = logging.getLogger("rayneo-agent.watch")

FRAME_TIMEOUT = 3.0  # no camera frame for this long: log once, keep waiting
STATS_EVERY = 30.0   # seconds between `watch: N frames ...` summary lines
GATE_DUMP_EVERY = 5.0  # seconds between two kept frames of the same gate reason


class Watch:
    def __init__(
        self, session: AgentSession, build: Build, judge, gate: Gate, tap: FrameTap, publish,
        gap: float = 0.5, confirm: int = 2, inflight: int = 2, wrong_confirm: int | None = None,
    ) -> None:
        self._session = session
        self._build = build
        self._judge = judge
        self._gate = gate
        self._tap = tap
        self._publish = publish
        self._gap = gap
        self._max_inflight = max(1, inflight)
        self.tracker = Tracker(len(build.guide.steps), confirm, step=build.step + 1, wrong_confirm=wrong_confirm)
        self._task: asyncio.Task | None = None
        self._inflight: set[asyncio.Task] = set()
        self._gate_dumped: dict[str, float] = {}  # reason -> when its frame was last kept
        self.last: tuple[Verdict, int, float] | None = None  # last verdict, its step, when its frame was taken
        self._last_gate: Decision | None = None
        self._gate_since = time.monotonic()  # when the gate's current reason started
        self._last_fired = 0.0
        self._camera_quiet = False
        self._frames = self._passed = self._judged = 0  # since the last stats line
        self._stats_at = time.monotonic()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="watch")
            self._session.on("user_state_changed", self._on_user_state)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        for t in self._inflight:
            t.cancel()

    # ------------------------------------------------------------------ for the voice

    def _on_user_state(self, ev) -> None:
        if ev.new_state == "speaking":
            self._think(self._state_text())

    def _think(self, text: str) -> None:
        """Silent context for the voice to answer from; nothing is said because of it."""
        logger.info("watch: thinking: %s", text)
        try:
            self._session.current_agent.duplex_session.append_thinking(text)
        except (RuntimeError, AttributeError):  # not a GPT-Live session
            pass

    def check_now(self) -> str:
        """What the camera knows right now, from the state here; no model call."""
        text = self._state_text()
        logger.info("check_now: %s", text)
        return text

    def _state_text(self) -> str:
        """Where the build stands and what the camera last saw (if within the last 10 s), else why it has had no
        clear view. No ages: the voice has no clock to read them against."""
        build, tr = self._build, self.tracker
        total = len(build.guide.steps)
        if tr.finished:
            return f"Camera now: all {total} steps are done. The build is finished."
        n = tr.step
        head = f"Camera now: steps 1 to {n - 1} are done; " if n > 1 else "Camera now: nothing is done yet; "
        head += f"the wearer is on step {n} ({build.guide.steps[n - 1].name})."
        if self.last is not None and self.last[1] == n and time.monotonic() - self.last[2] < 10:
            v = self.last[0]
            if v.answer == "correct":
                return head + f" The last look showed the step {n} brick in place; it is being confirmed, do not announce it as done yet."
            if v.answer == "wrong":
                return head + f" The last look showed step {n} placed wrongly: {v.reason}."
            if v.answer == "not_placed":
                return head + f" The last look showed the step {n} brick not on the plate yet."
            return head + f" The last look could not see the place of step {n}, most likely a hand over it."
        why = self._last_gate.why if self._last_gate is not None else "no frame"
        if why in ("ok", "settling"):
            return head + f" The plate is in view; the step {n} brick has not been seen in place yet."
        hint = {"no plate": "the green plate is not in the picture",
                "plate cut": "part of the plate is outside the picture",
                "plate partial": "the plate is too small or at a bad angle",
                "hand": "a hand is over the plate",
                "moving": "the picture is moving",
                "no frame": "no camera frames are arriving"}.get(why, why)
        return head + (f" The camera has no clear view of step {n}: {hint}. "
                       "Ask the wearer to keep the whole plate in view, hands away, and hold still for a second.")

    # ------------------------------------------------------------------ the loop

    async def _run(self) -> None:
        logger.info("watch: on, judge=%s gap=%.1fs inflight=%d confirm=%d/%d gate still=%.1fs min_side=%.2f motion<%s",
                    type(self._judge).__name__, self._gap, self._max_inflight, self.tracker.confirm,
                    self.tracker.wrong_confirm, self._gate.still_s, self._gate.min_side, self._gate.motion_max)
        while True:
            try:
                frame = await self._tap.next_frame(FRAME_TIMEOUT)
                taken = time.monotonic()  # the frame's time, ~ when it was captured plus the network
            except asyncio.TimeoutError:
                if not self._camera_quiet:
                    logger.warning("watch: no camera frame for %.0fs", FRAME_TIMEOUT)
                    self._camera_quiet = True
                continue
            self._camera_quiet = False
            try:
                img = await asyncio.to_thread(to_image, frame)
                d = await asyncio.to_thread(self._gate, img)
            except Exception:
                logger.exception("watch: gate failed")
                await asyncio.sleep(1)
                continue
            self._note_gate(d, img)
            now = time.monotonic()
            if (not d.ask or self.tracker.finished or now - self._last_fired < self._gap
                    or len(self._inflight) >= self._max_inflight):
                continue
            self._last_fired = now
            t = asyncio.create_task(self._judge_one(img, self.tracker.step, d, taken), name="judge")
            self._inflight.add(t)
            t.add_done_callback(self._inflight.discard)

    async def _judge_one(self, img: Image.Image, step: int, d: Decision, taken: float) -> None:
        """One frame to the judge; its verdict into the tracker if the step is still the same."""
        try:
            v: Verdict = await self._judge.ajudge(img, step)
        except Exception as e:
            if type(e).__name__ == "APITimeoutError":
                logger.warning("judge: call stalled, dropping the frame")
            else:
                logger.exception("judge: failed")
            return
        self._judged += 1
        logger.info("judge: step %d %s %.0f ms %s%s skin=%.2f motion=%s", step, v.answer, v.seconds * 1000, v.reason,
                    f" {v.info}" if v.info else "", d.skin, f"{d.motion:.1f}" if d.motion is not None else "-")
        if self._tap.dumping:
            self._tap.dump(await asyncio.to_thread(_jpeg, img), f"s{step}-{v.answer}")
        if step != self.tracker.step:
            logger.info("judge: verdict about step %d arrived after the step moved on, dropped", step)
            return
        # calls overlap: a slow verdict on an older frame must not replace a newer one
        if self.last is None or self.last[1] != step or taken >= self.last[2]:
            self.last = (v, step, taken)
        ev = self.tracker.feed(v.answer, v.reason)
        if ev is not None:
            await self._on_event(ev)

    def _note_gate(self, d: Decision, img: Image.Image) -> None:
        """Log the gate's reason when it changes, with the numbers behind it, and keep that frame if dumping."""
        prev = self._last_gate
        self._frames += 1
        self._passed += d.ask
        if prev is None or prev.why != d.why:
            box = ""
            if d.box:
                x0, y0, x1, y1 = d.box
                w, h = img.size
                box = f" box={x1 - x0}x{y1 - y0} of {w}x{h} aspect={(x1 - x0) / max(1, y1 - y0):.2f}"
            logger.info("gate: %s%s%s skin=%.2f motion=%s", d.why,
                        f" (was {prev.why} for {time.monotonic() - self._gate_since:.1f}s)" if prev else "", box, d.skin,
                        f"{d.motion:.1f}" if d.motion is not None else "-")
            self._gate_since = time.monotonic()
            # one frame per reason every few seconds: a flickering gate ate the dump budget in two minutes
            if self._tap.dumping and not d.ask and self._gate_since - self._gate_dumped.get(d.why, 0) > GATE_DUMP_EVERY:
                self._gate_dumped[d.why] = self._gate_since
                name = f"gate-{d.why.replace(' ', '_')}"
                asyncio.get_running_loop().run_in_executor(None, lambda: self._tap.dump(_jpeg(img), name))
        self._last_gate = d
        if time.monotonic() - self._stats_at > STATS_EVERY:
            logger.info("watch: %d frames in %.0fs, gate passed %d, judged %d, at step %d",
                        self._frames, time.monotonic() - self._stats_at, self._passed, self._judged, self.tracker.step)
            self._stats_at = time.monotonic()
            self._frames = self._passed = self._judged = 0

    async def _on_event(self, ev: Event) -> None:
        build = self._build
        if ev.kind in (Kind.DONE, Kind.FINISHED):
            build.set_step(ev.step)  # index of the next step = the number of steps done
            await self._publish(build)
            if ev.kind == Kind.FINISHED:
                self._say(f"Camera, just now: step {ev.step} is done and it was the last one. Tell the wearer it is "
                          "right, then that the build is finished, and congratulate them.")
            else:
                nxt = build.guide.steps[build.step]
                self._say(f"Camera, just now: step {ev.step} is done. Tell the wearer it is right in a few words, "
                          f"then give step {ev.step + 1}: {nxt.say}")
        elif ev.kind == Kind.WRONG:
            logger.info("step %d wrong: %s", ev.step, ev.text)
            self._say(f"Camera, just now: step {ev.step} is placed wrongly: {ev.text}. "
                      "First tell the wearer that this step is not right, then in one short sentence what to move "
                      "or swap.")

    # ------------------------------------------------------------------ the camera's notes to the voice

    def _say(self, text: str) -> None:
        """A camera note the voice acts on now, even mid-sentence. The newest note wins over older ones."""
        text = ("This replaces every earlier camera note. If you are speaking, stop and say this instead. "
                "Do not wait for the wearer to speak first; after that, pause and listen.\n" + text)
        logger.info("watch: commentary: %s", text)
        t0 = time.monotonic()
        speaking = self._session.agent_state == "speaking"
        try:
            self._session.current_agent.duplex_session.append_instructions(text)
        except (RuntimeError, AttributeError):  # not a GPT-Live session: the generic way, no interruption
            handle = self._session.generate_reply(instructions=text)
            handle.add_done_callback(lambda h: h.exception() is not None and logger.warning(
                "watch: the voice model declined the commentary"))
        asyncio.create_task(self._time_voice(t0, speaking), name="time_voice")

    async def _time_voice(self, t0: float, speaking: bool, limit: float = 10.0) -> None:
        """Log how long the voice took to start speaking after a camera note, or that it was already speaking."""
        if speaking:
            logger.info("voice: cut into speech with the camera note")
            return
        while self._session.agent_state != "speaking":
            if time.monotonic() - t0 > limit:
                logger.info("voice: not speaking %.0fs after commentary", limit)
                return
            await asyncio.sleep(0.02)
        logger.info("voice: started %.0f ms after commentary", (time.monotonic() - t0) * 1000)


def _jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()
