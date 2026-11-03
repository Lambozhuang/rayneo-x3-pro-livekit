"""Plays a scripted build conversation to GPT-Live, with the voice's real prompt and no glasses, brain or camera, and
writes down what the voice said and when.

    cd backend/agent && uv run --no-sync python ../../eval/voice-script/run.py <script> [--model gpt-live-1] [--voice marin]

The script is eval/voice-script/scripts/<script>.json: the build and a list of steps played in order. A step is one of

    {"user": "I'm ready"}                      the wearer says this: OpenAI TTS makes the audio once (cached in out/tts/)
                                                 and it goes to GPT-Live as microphone audio at wall-clock pace
    {"commentary": "Progress: 1 of 5 ..."}     a line the brain would have the voice say now (brain.py say / set_progress)
    {"thinking": "Camera: ..."}                a line the brain would give the voice silently (brain.py tell)
    {"wait": 3}                                seconds of nothing

and may carry "then": "quiet" (the default for user and commentary: wait until the voice has answered and been silent
for QUIET_S, 20 s at most), "then": "none" (go straight on; the default for thinking and wait), or "then": <seconds>;
and "expect": [regex, ...], each of which must match what the voice says between this step and the next, or
"expect_not": [regex, ...], none of which may. The run
starts as a call does: the same persona (gpt/prompts.py voice_persona) and the same greeting request (gpt/agent.py).

The session is the production one: livekit-agents' AgentSession with the GPT-Live plugin, client delegation, no VAD.
Only the ends differ: the microphone is the script's audio (ScriptMic), continuous 20 ms frames with silence between
utterances, as GPT-Live's turn detection expects; the speaker is a sink (Ear) that plays nothing but lets each
segment run its own length on the wall clock before reporting it played, so the session's speaking state keeps real
time, and keeps the audio with its start. A hand-over GPT-Live makes is closed as brain.py closes it, with its last line repeated.

out/<time>-<script>/ gets events.jsonl (every event with its time from the session start), report.md (the dialogue
in order, each voice turn with its length in words and seconds, the latency from the end of what the wearer said
to the voice's answer, the expectations met or not, and the totals) and dialogue.wav (left: the voice as it would
have played; right: the wearer's audio as sent), so the pace can be heard. OPENAI_API_KEY comes from backend/.env.
GPT-Live is billed by the session second and TTS by the character; a two-minute script costs cents.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import struct
import sys
import time
import wave
from pathlib import Path

import dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
AGENT = ROOT / "backend" / "agent"
sys.path.insert(0, str(AGENT / "src"))
os.chdir(AGENT)  # guide.load_guide reads guides/<name> from here
dotenv.load_dotenv(ROOT / "backend" / ".env")

from livekit import rtc  # noqa: E402
from livekit.agents import Agent, AgentSession, ConversationItemAddedEvent  # noqa: E402
from livekit.agents.llm import ChatMessage  # noqa: E402
from livekit.agents.voice import io  # noqa: E402
from livekit.plugins.openai.realtime import GPTLiveModel  # noqa: E402
from openai import OpenAI  # noqa: E402

from gpt.brain import handed_back  # noqa: E402
from gpt.prompts import voice_persona  # noqa: E402
from guide import load_guide  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(name)s %(levelname)s %(message)s")
log = logging.getLogger("voice-script")
log.setLevel(logging.INFO)

SAMPLE_RATE = 24000  # GPT-Live's PCM rate both ways
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * 2  # 16-bit mono
TTS_MODEL = "gpt-4o-mini-tts"
TTS_VOICE = "ash"
QUIET_S = 1.5  # the voice counts as done answering after this much silence; it pauses up to a second between sentences
STEP_TIMEOUT_S = 20.0


class ScriptMic(io.AudioInput):
    """The wearer's microphone: 20 ms frames at wall-clock pace, the queued utterances' audio when there is some and
    silence otherwise, since GPT-Live's turn detection listens to a continuous stream."""

    def __init__(self, clock: Clock) -> None:
        super().__init__(label="script")
        self._clock = clock
        self._frames: asyncio.Queue[rtc.AudioFrame] = asyncio.Queue()
        self._pending = bytearray()
        self._task: asyncio.Task | None = None
        self.utterances: list[dict] = []  # {"t": start, "pcm": bytes}

    def start(self) -> None:
        self._task = asyncio.create_task(self._pump(), name="mic")

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()

    def say(self, pcm: bytes) -> float:
        """Queue an utterance; returns its length in seconds."""
        self.utterances.append({"t": self._clock.now() + len(self._pending) / (SAMPLE_RATE * 2), "pcm": pcm})
        self._pending += pcm
        return len(pcm) / (SAMPLE_RATE * 2)

    async def _pump(self) -> None:
        t0 = time.monotonic()
        n = 0
        while True:
            n += 1
            await asyncio.sleep(max(0.0, t0 + n * FRAME_MS / 1000 - time.monotonic()))
            if self._pending:
                chunk = bytes(self._pending[:FRAME_BYTES]).ljust(FRAME_BYTES, b"\0")
                del self._pending[:FRAME_BYTES]
            else:
                chunk = bytes(FRAME_BYTES)
            self._frames.put_nowait(rtc.AudioFrame(data=chunk, sample_rate=SAMPLE_RATE, num_channels=1,
                                                   samples_per_channel=FRAME_BYTES // 2))

    async def __anext__(self) -> rtc.AudioFrame:
        return await self._frames.get()


class Ear(io.AudioOutput):
    """The speaker: keeps each segment of the voice's audio with the time its playout would have started, and reports
    it played when that much time has passed on the wall clock, or when the session clears it (an interruption)."""

    def __init__(self, clock: Clock) -> None:
        super().__init__(label="script", capabilities=io.AudioOutputCapabilities(pause=False), sample_rate=SAMPLE_RATE)
        self._clock = clock
        self.segments: list[dict] = []  # {"t": start, "pcm": bytearray, "s": pushed seconds, "played": seconds, "interrupted": bool}
        self._cur: dict | None = None
        self._playing: asyncio.Task | None = None

    async def capture_frame(self, frame: rtc.AudioFrame) -> None:
        await super().capture_frame(frame)
        if self._playing is not None and not self._playing.done():
            await asyncio.shield(self._playing)  # one segment plays at a time, as a real speaker has it
        if self._cur is None:
            self._cur = {"t": self._clock.now(), "pcm": bytearray(), "s": 0.0, "played": None, "interrupted": False}
            self.segments.append(self._cur)
            self.on_playback_started(created_at=time.time())  # the session's speaking state follows this
        self._cur["pcm"] += bytes(frame.data)
        self._cur["s"] += frame.duration

    def flush(self) -> None:
        super().flush()
        if self._cur is None:
            return
        seg, self._cur = self._cur, None
        self._playing = asyncio.create_task(self._playout(seg), name="playout")

    def clear_buffer(self) -> None:
        if self._cur is not None:  # cut while still being pushed
            seg, self._cur = self._cur, None
            self._finish(seg, interrupted=True)
        elif self._playing is not None and not self._playing.done():
            self._playing.cancel()

    async def _playout(self, seg: dict) -> None:
        try:
            await asyncio.sleep(max(0.0, seg["t"] + seg["s"] - self._clock.now()))
        except asyncio.CancelledError:
            self._finish(seg, interrupted=True)
            raise
        self._finish(seg, interrupted=False)

    def _finish(self, seg: dict, interrupted: bool) -> None:
        seg["played"] = min(seg["s"], max(0.0, self._clock.now() - seg["t"])) if interrupted else seg["s"]
        seg["interrupted"] = interrupted
        self.on_playback_finished(playback_position=seg["played"], interrupted=interrupted)


class Clock:
    """Seconds since the session started, on the monotonic clock, and the wall time of that start for the model's
    speech metrics."""

    def __init__(self) -> None:
        self.t0 = time.monotonic()
        self.wall0 = time.time()

    def now(self) -> float:
        return time.monotonic() - self.t0

    def of_wall(self, wall: float) -> float:
        return wall - self.wall0


def tts(client: OpenAI, text: str, cache: Path) -> bytes:
    """The wearer's line as 24 kHz PCM, made once per text."""
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{TTS_MODEL}|{TTS_VOICE}|{text}".encode()).hexdigest()[:16]
    f = cache / f"{key}.pcm"
    if not f.exists():
        r = client.audio.speech.create(model=TTS_MODEL, voice=TTS_VOICE, input=text, response_format="pcm",
                                       instructions="A person at a desk talking to an assistant while building something; plain, natural, unhurried.")
        f.write_bytes(r.content)
        (cache / f"{key}.txt").write_text(text, encoding="utf-8")
    return f.read_bytes()


class Run:
    def __init__(self, script: dict, out: Path, model: str, voice: str, language: str) -> None:
        self.script, self.out = script, out
        self.clock = Clock()
        self.events: list[dict] = []
        self.guide = load_guide(f"guides/{script['guide']}", pictures=False)
        self.persona = voice_persona(self.guide, language)
        self.mic = ScriptMic(self.clock)
        self.ear = Ear(self.clock)
        self.session = AgentSession(llm=GPTLiveModel(model=model, voice=voice, delegation="client"))
        self.voice_state = "listening"
        self.voice_quiet_since = self.clock.now()
        self.voice_started_at: float | None = None  # the last time the voice began to speak
        self.voice_stopped_at: float | None = None
        self.said_since_step: list[str] = []
        self.openai = OpenAI()

    def event(self, kind: str, **fields) -> None:
        e = {"t": round(self.clock.now(), 3), "kind": kind, **fields}
        self.events.append(e)
        with open(self.out / "events.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        if kind in ("said", "step", "expect", "delegation"):
            log.info("%6.1f %s %s", e["t"], kind, json.dumps({k: v for k, v in fields.items()}, ensure_ascii=False)[:200])

    async def go(self) -> None:
        s = self.session
        s.input.audio = self.mic
        s.output.audio = self.ear
        self.mic.start()

        @s.on("conversation_item_added")
        def _said(ev: ConversationItemAddedEvent) -> None:
            if isinstance(ev.item, ChatMessage) and ev.item.role in ("user", "assistant"):
                m = ev.item.metrics or {}
                text = ev.item.text_content or ""
                who = "wearer" if ev.item.role == "user" else "voice"
                started = round(self.clock.of_wall(m["started_speaking_at"]), 3) if m.get("started_speaking_at") else None
                stopped = round(self.clock.of_wall(m["stopped_speaking_at"]), 3) if m.get("stopped_speaking_at") else None
                if who == "voice":
                    self.said_since_step.append(text)
                    if started is None:  # the metrics come with room audio; here the state changes stand in
                        started, stopped = self.voice_started_at, self.voice_stopped_at or round(self.clock.now(), 3)
                self.event("said", who=who, text=text, interrupted=ev.item.interrupted, started=started, stopped=stopped)

        @s.on("agent_state_changed")
        def _voice(ev) -> None:
            self.voice_state = ev.new_state
            if ev.new_state == "speaking":
                self.voice_started_at, self.voice_stopped_at = round(self.clock.now(), 3), None
            else:
                self.voice_quiet_since = self.clock.now()
                if ev.old_state == "speaking":
                    self.voice_stopped_at = round(self.clock.now(), 3)
            self.event("state", who="voice", old=ev.old_state, new=ev.new_state)

        @s.on("user_state_changed")
        def _wearer(ev) -> None:
            self.event("state", who="wearer", old=ev.old_state, new=ev.new_state)

        await s.start(agent=Agent(instructions=self.persona))
        duplex = s.current_agent.duplex_session

        last_line: list[str | None] = [None]  # the last brain line the script sent, as brain.py keeps it

        def _handed(d) -> None:  # brain.py on_delegation, without the brain
            self.event("delegation", id=d.id, words=d.pending_transcript.strip())
            duplex.append_commentary(handed_back(last_line[0]), delegation_id=d.id)

        duplex.on("delegation_created", _handed)

        def _live(event: dict) -> None:
            if event.get("type") == "error":
                self.event("live_error", error=event.get("error"))

        duplex.on("openai_server_event_received", _live)

        self.event("start", model=self.session.llm.model if hasattr(self.session.llm, "model") else None,
                   guide=self.guide.name, persona=self.persona)
        handle = s.generate_reply(instructions=(
            "Greet the wearer briefly: say you can see through their glasses and will "
            f'guide them through building "{self.guide.title}", naming it in a few words, and '
            "ask them to say when they are ready. Do not describe any step yet."))
        await handle
        await self.until_quiet(STEP_TIMEOUT_S)

        for i, step in enumerate(self.script["steps"], 1):
            self.said_since_step = []
            kind = next(k for k in ("user", "commentary", "thinking", "wait") if k in step)
            then = step.get("then", "quiet" if kind in ("user", "commentary") else "none")
            self.event("step", n=i, **{kind: step[kind]}, then=then)
            t_step = self.clock.now()
            if kind == "user":
                pcm = await asyncio.to_thread(tts, self.openai, step["user"], HERE / "out" / "tts")
                length = self.mic.say(pcm)
                await asyncio.sleep(length + 0.2)  # the words are out
            elif kind == "commentary":
                duplex.append_commentary(step["commentary"])
                last_line[0] = step["commentary"]
            elif kind == "thinking":
                duplex.append_thinking(step["thinking"])
                last_line[0] = step["thinking"]
            elif kind == "wait":
                await asyncio.sleep(float(step["wait"]))
            if then == "quiet":
                await self.until_quiet(STEP_TIMEOUT_S, spoke_after=t_step)
            elif then != "none":
                await asyncio.sleep(float(then))
            heard = " ".join(self.said_since_step)
            for pattern in step.get("expect", []):
                self.event("expect", n=i, pattern=pattern, ok=re.search(pattern, heard, re.I) is not None, heard=heard)
            for pattern in step.get("expect_not", []):
                self.event("expect", n=i, pattern=f"not {pattern}", ok=re.search(pattern, heard, re.I) is None, heard=heard)

        await asyncio.sleep(1.0)
        self.event("end")
        self.mic.stop()
        await s.aclose()
        llm = s.llm
        if hasattr(llm, "aclose"):
            await llm.aclose()

    async def until_quiet(self, timeout: float, spoke_after: float | None = None) -> None:
        """Wait until the voice has answered (started speaking after `spoke_after`, when given) and then been quiet
        for QUIET_S, or `timeout` seconds."""
        t0 = self.clock.now()
        spoke = spoke_after is None
        while self.clock.now() - t0 < timeout:
            if self.voice_state == "speaking":
                spoke = True
            elif spoke and self.clock.now() - self.voice_quiet_since >= QUIET_S:
                return
            await asyncio.sleep(0.05)
        self.event("timeout", after_s=timeout, spoke=spoke)

    # ------------------------------------------------------------------ what came of it

    def write(self) -> None:
        self.wav()
        self.report()

    def wav(self) -> None:
        end = max([self.clock.now()] + [s["t"] + (s["played"] or 0) for s in self.ear.segments]
                  + [u["t"] + len(u["pcm"]) / (SAMPLE_RATE * 2) for u in self.mic.utterances])
        n = int(end * SAMPLE_RATE) + SAMPLE_RATE
        left, right = bytearray(n * 2), bytearray(n * 2)
        for seg in self.ear.segments:
            played = seg["played"] if seg["played"] is not None else seg["s"]
            pcm = bytes(seg["pcm"][: int(played * SAMPLE_RATE) * 2])
            at = int(seg["t"] * SAMPLE_RATE) * 2
            left[at:at + len(pcm)] = pcm
        for u in self.mic.utterances:
            at = int(u["t"] * SAMPLE_RATE) * 2
            right[at:at + len(u["pcm"])] = u["pcm"]
        frames = bytearray()
        for i in range(0, n * 2, 2):
            frames += left[i:i + 2] + right[i:i + 2]
        with wave.open(str(self.out / "dialogue.wav"), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(bytes(frames))

    def report(self) -> None:
        ev = self.events
        lines = [f"# {self.script.get('name', self.out.name)}", "",
                 f"Build {self.guide.name}, {len(self.script['steps'])} steps of script, {ev[-1]['t']:.0f} s. "
                 "Times are seconds from the session start; a voice turn shows when it started and stopped speaking.", "",
                 "| t | who | s | words | w/s | text |", "|---|---|---|---|---|---|"]
        voice_s = voice_w = 0.0
        turns = 0
        last_wearer_stop = None
        latencies = []
        for e in ev:
            k = e["kind"]
            if k == "step":
                what = {x: e[x] for x in ("user", "commentary", "thinking", "wait") if x in e}
                lines.append(f"| {e['t']:.1f} | step {e['n']} | | | | {esc(json.dumps(what, ensure_ascii=False))} |")
            elif k == "said":
                if e["who"] == "voice" and e.get("started") is not None and e.get("stopped") is not None:
                    d = e["stopped"] - e["started"]
                    w = len(e["text"].split())
                    voice_s += d
                    voice_w += w
                    turns += 1
                    if last_wearer_stop is not None and e["started"] >= last_wearer_stop:
                        latencies.append(e["started"] - last_wearer_stop)
                        last_wearer_stop = None
                    lines.append(f"| {e['started']:.1f}-{e['stopped']:.1f} | voice | {d:.1f} | {w} | {w / d if d else 0:.1f} | "
                                 f"{esc(e['text'])}{' [interrupted]' if e.get('interrupted') else ''} |")
                else:
                    if e["who"] == "wearer" and e.get("started") is not None:
                        last_wearer_stop = e.get("stopped") or e["t"]
                    when = f"{e['started']:.1f}" if e.get("started") is not None else f"{e['t']:.1f}"
                    lines.append(f"| {when} | {e['who']} | | | | {esc(e['text'])} |")
            elif k == "delegation":
                lines.append(f"| {e['t']:.1f} | hand-over | | | | closed at once; words: {esc(e.get('words') or '')} |")
            elif k == "expect":
                lines.append(f"| {e['t']:.1f} | {'met' if e['ok'] else 'NOT met'} | | | | step {e['n']}: `{esc(e['pattern'])}` |")
            elif k == "timeout":
                lines.append(f"| {e['t']:.1f} | timeout | | | | the voice {'did not answer' if not e['spoke'] else 'did not go quiet'} within {e['after_s']:.0f} s |")
            elif k == "live_error":
                lines.append(f"| {e['t']:.1f} | error | | | | {esc(json.dumps(e.get('error')))} |")
        lines += ["", "## Totals", ""]
        total = ev[-1]["t"]
        lines.append(f"- The voice spoke {voice_s:.0f} s of {total:.0f} s ({100 * voice_s / total:.0f}%), {turns} turns, "
                     f"{voice_w / turns if turns else 0:.0f} words a turn, {60 * voice_w / voice_s if voice_s else 0:.0f} words a minute.")
        if latencies:
            latencies.sort()
            lines.append(f"- From the end of the wearer's words to the voice's answer: median {latencies[len(latencies) // 2]:.1f} s, "
                         f"max {max(latencies):.1f} s, over {len(latencies)} answers.")
        met = [e for e in ev if e["kind"] == "expect"]
        if met:
            lines.append(f"- Expectations met: {sum(e['ok'] for e in met)} of {len(met)}.")
        lines.append("")
        (self.out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def esc(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("script", help="name of a script in eval/voice-script/scripts/, without .json")
    ap.add_argument("--model", default=os.environ.get("OPENAI_LIVE_MODEL", "gpt-live-1"))
    ap.add_argument("--voice", default=os.environ.get("OPENAI_VOICE", "marin"))
    ap.add_argument("--language", default=os.environ.get("AGENT_LANGUAGE", "English"))
    args = ap.parse_args()
    script = json.loads((HERE / "scripts" / f"{args.script}.json").read_text(encoding="utf-8"))
    out = HERE / "out" / f"{time.strftime('%Y%m%d-%H%M%S')}-{args.script}"
    out.mkdir(parents=True)
    run = Run(script, out, args.model, args.voice, args.language)
    try:
        asyncio.run(run.go())
    finally:
        run.write()
        print(out / "report.md")
        print(out / "dialogue.wav")


if __name__ == "__main__":
    main()
