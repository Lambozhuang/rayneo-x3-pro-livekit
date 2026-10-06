"""The loop that looks and tells: camera -> gate -> judge -> state machine -> GPT-Live.

Every frame from the glasses comes through here (FrameTap). The gate (gate.py)
passes a frame only when the whole plate is in view, no hand is over it and it
has been still for a moment; the judge (judge_cv.py by default, judge_vlm.py
with JUDGE=vlm) then answers about the current step only; the state machine
(progress.py) needs `confirm` agreeing answers before anything counts. The
code owns the step: the voice model never decides where the build stands.

What reaches GPT-Live:
- a step newly confirmed, or a brick confirmed wrong, as *commentary*
  (generate_reply with instructions starting "Camera:"), so the voice says it
  in its own words right away. Commentary waits while the voice is speaking
  and only the newest one is kept: two events a second apart must not become
  two overlapping sentences;
- nothing per frame. Early versions put every verdict into the model's
  context and it narrated the camera from stale notes;
- check_now (tools.py) answers from the state here, no new model call: the
  step the code is on, the last verdict and how old it is, or why the camera
  has had no clear view.

Two timing layers in the log: `judge:` lines carry the judge's own latency per
frame; `voice:` lines the delay from a commentary to the voice starting to
speak. The glasses measure the wearer's wait separately (`latency:` lines).
"""

from __future__ import annotations

import asyncio
import io
import logging
import time

from livekit import rtc
from livekit.agents import AgentSession
from PIL import Image

from frames import FrameTap
from gate import Decision, Gate
from guide import Build
from judge_cv import Verdict
from progress import Event, Kind, Tracker

logger = logging.getLogger("rayneo-agent.watch")

FRAME_TIMEOUT = 3.0  # no camera frame for this long: log once, keep waiting
STATS_EVERY = 30.0   # seconds between `watch: N frames ...` summary lines


def to_image(frame: rtc.VideoFrame) -> Image.Image:
    f = frame if frame.type == rtc.VideoBufferType.RGB24 else frame.convert(rtc.VideoBufferType.RGB24)
    return Image.frombytes("RGB", (f.width, f.height), bytes(f.data))


class Watch:
    def __init__(
        self, session: AgentSession, build: Build, judge, gate: Gate, tap: FrameTap, publish,
        gap: float = 0.5, confirm: int = 2,
    ) -> None:
        self._session = session
        self._build = build
        self._judge = judge
        self._gate = gate
        self._tap = tap
        self._publish = publish
        self._gap = gap
        self.tracker = Tracker(len(build.guide.steps), confirm, step=build.step + 1)
        self._task: asyncio.Task | None = None
        self.last: tuple[Verdict, int, float] | None = None  # last verdict, the step it was about, when
        self._last_gate: Decision | None = None
        self._gate_since = time.monotonic()  # when the gate's current reason started
        self._last_judged = 0.0
        self._pending_say: str | None = None  # commentary held back while the voice speaks
        self._camera_quiet = False
        self._frames = self._passed = self._judged = 0  # since the last stats line
        self._stats_at = time.monotonic()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="watch")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    # ------------------------------------------------------------------ for the voice

    def check_now(self) -> str:
        """What the camera knows right now, from the state here; no model call."""
        text = self._state_text()
        logger.info("check_now: %s", text)
        return text

    def _state_text(self) -> str:
        build, tr = self._build, self.tracker
        total = len(build.guide.steps)
        if tr.finished:
            return f"Camera now: all {total} steps are done. The build is finished."
        n = tr.step
        head = f"Camera now: steps 1 to {n - 1} are done; " if n > 1 else "Camera now: nothing is done yet; "
        head += f"the wearer is on step {n} ({build.guide.steps[n - 1].name})."
        now = time.monotonic()
        if self.last is not None and self.last[1] == n and now - self.last[2] < 10:
            v, _, at = self.last
            age = f"{now - at:.0f} seconds ago"
            if v.answer == "correct":
                return head + f" The last clear look, {age}, showed the step {n} brick in place; it is being confirmed, do not announce it as done yet."
            if v.answer == "wrong":
                return head + f" The last clear look, {age}, showed step {n} placed wrongly: {v.reason}."
            if v.answer == "not_placed":
                return head + f" The last clear look, {age}, showed the step {n} brick not on the plate yet."
            return head + f" The last look, {age}, could not see the place of step {n}."
        g = self._last_gate
        why = g.why if g is not None else "no frame"
        since = now - self._gate_since
        if why in ("ok", "settling"):
            return head + f" The plate is in view; the step {n} brick has not been seen in place yet."
        hint = {"no plate": "the green plate is not in the picture",
                "plate cut": "part of the plate is outside the picture",
                "plate partial": "the plate is too small or at a bad angle",
                "hand": "a hand is over the plate",
                "moving": "the picture is moving",
                "settling": "the picture has only just gone still",
                "no frame": "no camera frames are arriving"}.get(why, why)
        return head + (f" The camera has had no clear view of step {n} for {since:.0f} seconds: {hint}. "
                       "Ask the wearer to keep the whole plate in view, hands away, and hold still for a second.")

    # ------------------------------------------------------------------ the loop

    async def _run(self) -> None:
        logger.info("watch: on, judge=%s gap=%.1fs confirm=%d still=%.1fs",
                    type(self._judge).__name__, self._gap, self.tracker.confirm, self._gate.still_s)
        while True:
            try:
                frame = await self._tap.next_frame(FRAME_TIMEOUT)
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
            if not d.ask or self.tracker.finished or time.monotonic() - self._last_judged < self._gap:
                continue
            step = self.tracker.step
            try:
                v: Verdict = await self._judge.ajudge(img, step)
            except Exception as e:
                if type(e).__name__ == "APITimeoutError":
                    logger.warning("judge: call stalled, dropping the frame")
                else:
                    logger.exception("judge: failed")
                    await asyncio.sleep(1)
                continue
            self._last_judged = time.monotonic()
            self._judged += 1
            self.last = (v, step, self._last_judged)
            logger.info("judge: step %d %s %.0f ms %s%s skin=%.2f motion=%s", step, v.answer, v.seconds * 1000, v.reason,
                        f" {v.info}" if v.info else "", d.skin, f"{d.motion:.1f}" if d.motion is not None else "-")
            if self._tap.dumping:
                self._tap.dump(await asyncio.to_thread(_jpeg, img), f"s{step}-{v.answer}")
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
            if self._tap.dumping and not d.ask:
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
                self._say(f"Camera: step {ev.step} is done and it was the last one. Tell the wearer it is right, "
                          "then that the build is finished, and congratulate them.")
            else:
                nxt = build.guide.steps[build.step]
                self._say(f"Camera: step {ev.step} is done. Tell the wearer it is right in a few words, "
                          f"then give step {ev.step + 1}: {nxt.say}")
        elif ev.kind == Kind.WRONG:
            logger.info("step %d wrong: %s", ev.step, ev.text)
            self._say(f"Camera, on step {ev.step}: {ev.text}. Tell the wearer in one short sentence what to move or swap.")

    # ------------------------------------------------------------------ commentary

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
        t0 = time.monotonic()
        handle = self._session.generate_reply(instructions=text)

        def _done(h) -> None:
            if h.exception() is not None:
                logger.warning("watch: the voice model declined the commentary")

        handle.add_done_callback(_done)
        asyncio.create_task(self._time_voice(t0), name="time_voice")

    async def _time_voice(self, t0: float, limit: float = 10.0) -> None:
        """Log how long the voice took to start speaking after a commentary."""
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
