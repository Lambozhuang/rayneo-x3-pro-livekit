"""The whole GPT path at the desk, no glasses: GPT-Live, the brain and the quick look run together as in a call,
fed a recorded call's photos at the times they were taken and the wearer's words as speech at the times they were
said.

    backend/agent/.venv/Scripts/python eval/agent-sim/sim.py <record dir> [--until 160] [--quick-every 1]
        [--brain-model gpt-6.1-terra --effort none --tier priority --transport ws --watch-every 2]

Everything the agent process has runs for real: livekit-agents' AgentSession with the GPT-Live plugin (client
delegation, the persona, the greeting request), the brain with its conversation and tools, the quick look on the
Decisions API, the record (runlog.py) that deploy/report.py reads. What stands in: the room. The microphone is the
wearer's recorded lines as TTS audio (eval/voice-script's ScriptMic and tts), played at the second each was said in
the recorded call; the speaker plays nothing but keeps the voice's audio and its timing (Ear); the camera is the
record's photos, each made the newest frame at the second it was taken, so the quick look sees a frame change every
two seconds rather than fifteen times a second; the step list and the picture bytes go into the record instead of
to glasses. The wearer's lines were answers to another voice, so the dialogue cannot be judged for sense; what the
run shows is the three parts running at once: who speaks when, how long after a frame the quick look's line and the
brain's line reach the voice, whether the two eyes contradict each other, and what a minute costs.

out/<time>-sim-<record>/ holds the record as a call writes it (events.jsonl, photos, prompts), agent.log with the
process's log lines, dialogue.wav (left: the voice, right: the wearer) and report.md. The key comes from
backend/.env.
"""

import argparse
import asyncio
import importlib.util
import io
import json
import logging
import statistics as st
import sys
import threading
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import dotenv
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "backend" / "agent" / "src"))
dotenv.load_dotenv(ROOT / "backend" / ".env")

spec = importlib.util.spec_from_file_location("voice_script", ROOT / "eval" / "voice-script" / "run.py")
vs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vs)

from livekit import rtc  # noqa: E402
from livekit.agents import Agent, AgentSession, ConversationItemAddedEvent  # noqa: E402
from livekit.agents.llm import ChatMessage  # noqa: E402
from livekit.plugins.openai.realtime import GPTLiveModel  # noqa: E402
from openai import OpenAI  # noqa: E402

import gpt.eyes as eyes_mod  # noqa: E402
from frames import FrameTap  # noqa: E402
from gpt.brain import make_model  # noqa: E402
from gpt.consult import TOOLS, Consult  # noqa: E402
from gpt.eyes import Eyes  # noqa: E402
from gpt.prompts import voice_persona  # noqa: E402
from guide import Build, load_guide  # noqa: E402
from prompts import task_block  # noqa: E402
from runlog import RunLog  # noqa: E402


class Writer:
    async def write(self, data: bytes) -> None:
        pass

    async def aclose(self) -> None:
        pass


class Participant:
    async def stream_bytes(self, name, total_size, mime_type, topic):
        return Writer()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("record")
    ap.add_argument("--from", dest="start", type=float, default=0.0,
                    help="begin this many seconds into the recorded call, with the progress the record had then")
    ap.add_argument("--until", type=float, default=None, help="stop this many seconds into the recorded call")
    ap.add_argument("--brain-model", default="gpt-6.1-terra")
    ap.add_argument("--effort", default="none")
    ap.add_argument("--tier", default="priority")
    ap.add_argument("--transport", default="ws")
    ap.add_argument("--watch-every", type=float, default=2.0)
    ap.add_argument("--quick-model", default="gpt-6-luna")
    ap.add_argument("--quick-detail", default="low")
    ap.add_argument("--quick-every", type=float, default=1.0)
    ap.add_argument("--voice", default="marin")
    ap.add_argument("--no-consult", action="store_true", help="the eyes alone judge, as BRAIN_CONSULT=off")
    ap.add_argument("--photos", action="store_true", help="play the record's photos and TTS of the transcript even when a recording exists")
    ap.add_argument("--guide", default=None, help="a task directory to use instead of the record's guide, as the task was when it was recorded")
    args = ap.parse_args()

    rec = Path(args.record)
    if not rec.is_absolute():
        rec = ROOT / rec  # the voice harness, imported above, moves the process to backend/agent
    ev = [json.loads(line) for line in open(rec / "events.jsonl", encoding="utf-8")]
    call = ev[0]
    guide_dir = Path(args.guide) if args.guide else ROOT / "backend" / "agent" / "guides" / call["guide"]
    if not guide_dir.is_absolute():
        guide_dir = ROOT / guide_dir
    guide = load_guide(guide_dir / "task.toml")
    photos = [(e["t"], rec / e["photo"]) for e in ev if e["kind"] == "watch_sent" and e.get("photo")]
    words = [(e["started"] if e.get("started") is not None else e["t"], e["text"].strip())
             for e in ev if e["kind"] == "said" and e["who"] == "wearer" and (e.get("text") or "").strip()]
    end = args.until if args.until else max(e["t"] for e in ev) + 5.0
    # a glasses recording (deploy/glasses.ps1 -Record): the video at 15 fps and the wearer's own voice, each frame and
    # chunk stamped with the wall clock it was captured at, which the call event's wall_ms puts on the record's clock
    recording = (rec / "recording" / "video.mp4").exists() and not args.photos
    frame_times: list[float] = []
    mic_pcm, mic_t = b"", 0.0
    if recording:
        rows = [l.split(",") for l in (rec / "recording" / "video.csv").read_text(encoding="utf-8").splitlines()[1:]]
        frame_times = [(int(r[2]) - call["wall_ms"]) / 1000 for r in rows]
        mic_rows = (rec / "recording" / "mic.csv").read_text(encoding="utf-8").splitlines()[1:]
        mic_t = (int(mic_rows[0].split(",")[0]) - call["wall_ms"]) / 1000
        with wave.open(str(rec / "recording" / "mic.wav")) as w:
            rate, raw = w.getframerate(), w.readframes(w.getnframes())
        x = np.frombuffer(raw, dtype=np.int16)
        if rate != vs.SAMPLE_RATE:  # 48 kHz on the glasses, 24 kHz into GPT-Live: the mean of each pair of samples
            step_n = rate // vs.SAMPLE_RATE
            x = x[: len(x) // step_n * step_n].reshape(-1, step_n).mean(axis=1).astype(np.int16)
        mic_end = mic_t + len(x) / vs.SAMPLE_RATE
        if not args.until:
            end = min(frame_times[-1], mic_end)
        skip = max(0.0, args.start - mic_t)  # a stretch begun after the microphone started skips that much audio
        mic_pcm = x[int(skip * vs.SAMPLE_RATE):].tobytes()
        mic_t = max(0.0, mic_t - args.start)
        photos, words = [], []
    photos = [(t - args.start, p) for t, p in photos if args.start <= t <= end]
    words = [(t - args.start, w) for t, w in words if args.start <= t <= end]
    end -= args.start
    # the record's progress when the simulated stretch begins
    done_then = 0
    for e in ev:
        if e["kind"] == "step" and e["t"] <= args.start:
            done_then = e["done"] if e.get("done") is not None else (e["reopened"] - 1 if e.get("reopened") else done_then)

    out = HERE / "out"
    out.mkdir(exist_ok=True)
    if recording:
        print(f"simulating {rec.name} from its recording: {sum(1 for t in frame_times if args.start <= t <= args.start + end)} frames "
              f"at 15 fps, the wearer's own voice from {mic_t:.1f} s, {end:.0f} s")
        speech = []
    else:
        print(f"simulating {rec.name}: {len(photos)} photos, {len(words)} wearer lines, {end:.0f} s")
        openai = OpenAI()
        print("making the wearer's lines as speech...", end=" ", flush=True)
        speech = [(t, text, vs.tts(openai, text, ROOT / "eval" / "voice-script" / "out" / "tts")) for t, text in words]
        print("done")

    clock = vs.Clock()
    mic = vs.ScriptMic(clock)
    ear = vs.Ear(clock)
    session = AgentSession(llm=GPTLiveModel(model="gpt-live-1", voice=args.voice, delegation="client"))
    session.input.audio = mic
    session.output.audio = ear
    persona = voice_persona(guide, "English")
    mic.start()
    await session.start(agent=Agent(instructions=persona))  # first, so the record's t=0 is the call's start

    record = RunLog(str(out), f"sim-{rec.name}")
    run_dir = Path(record.dir)
    logging.basicConfig(level=logging.INFO, filename=run_dir / "agent.log", filemode="w", force=True,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("livekit").setLevel(logging.WARNING)
    log = logging.getLogger("sim")
    tap = FrameTap(on_first=lambda f: record.event("camera", first_frame=f"{f.width}x{f.height}"))
    build = Build(guide=guide, run=run_dir.name)
    model = make_model("openai", args.brain_model, "high", args.tier, args.transport)

    async def no_publish(b) -> None:  # the glasses' step list, into the record instead
        record.event("published", step=b.step, picture=b.picture or None, finished=b.finished)
    eyes_mod.publish_build = no_publish
    import gpt.consult as consult_mod
    import guide as guide_mod
    guide_mod.publish_build = no_publish

    async def show(step: int) -> str:
        build.show(step)
        record.event("picture", step=step)
        return f"Picture: the glasses now show the picture of step {step} ({guide.steps[step - 1].brick})."

    eyes: Eyes
    consult = Consult(session, build, tap, model, args.effort, 1080, "English", record,
                      lambda done, seen, basis: eyes.progress(done, seen, basis))
    eyes = Eyes(session, build, tap, task_block(guide), args.quick_model, args.quick_detail, args.quick_every, record,
                None if args.no_consult else consult.ask, show)

    record.event("call", wall_ms=record.wall_ms, room=run_dir.name, lab=None, guide=guide.name, language="English",
                 commit=None, settings={"sim_of": rec.name, "brain_model": args.brain_model, "brain_effort": args.effort,
                                        "brain_service_tier": args.tier, "brain_transport": args.transport,
                                        "brain_watch_every": args.watch_every, "brain_watch_side": 1080, "brain_detail": "high",
                                        "quick_model": args.quick_model, "quick_detail": args.quick_detail,
                                        "quick_every": args.quick_every, "voice": args.voice, "live_model": "gpt-live-1"},
                 steps=[s.name for s in guide.steps])
    record.text("consult.txt", consult.instructions)
    record.text("consult-tools.json", json.dumps([{"name": n, "description": d, "input_schema": p} for n, d, p in TOOLS], indent=2))
    record.text("voice.txt", persona)

    @session.on("conversation_item_added")
    def _said(e: ConversationItemAddedEvent) -> None:
        if isinstance(e.item, ChatMessage) and e.item.role in ("user", "assistant"):
            m = e.item.metrics or {}
            who = "wearer" if e.item.role == "user" else "voice"
            started = record.t(m["started_speaking_at"]) if m.get("started_speaking_at") else None
            stopped = record.t(m["stopped_speaking_at"]) if m.get("stopped_speaking_at") else None
            if who == "voice" and started is None:
                started, stopped = state["voice_started"], state["voice_stopped"] or record.t()
            record.event("said", who=who, text=e.item.text_content, interrupted=e.item.interrupted, started=started, stopped=stopped)
            if who == "wearer" and (e.item.text_content or "").strip():
                asyncio.create_task(eyes.words(e.item.text_content), name="words")

    @session.on("user_input_transcribed")
    def _interim(e) -> None:
        if not e.is_final and (e.transcript or "").strip():
            record.event("interim", text=e.transcript)
            asyncio.create_task(eyes.words(e.transcript, final=False), name="words_interim")

    state = {"voice_started": None, "voice_stopped": None}

    @session.on("agent_state_changed")
    def _voice(e) -> None:
        if e.new_state == "speaking":
            state["voice_started"], state["voice_stopped"] = record.t(), None
        elif e.old_state == "speaking":
            state["voice_stopped"] = record.t()
        record.event("state", who="voice", old=e.old_state, new=e.new_state)

    @session.on("user_state_changed")
    def _wearer(e) -> None:
        record.event("state", who="wearer", old=e.old_state, new=e.new_state)

    duplex = session.current_agent.duplex_session

    def _handed(d) -> None:
        record.event("delegation", id=d.id, words=d.pending_transcript.strip())
        text = eyes.handed_back()
        record.event("commentary", id=d.id, text=text, source="handed_back", voice_speaking=session.agent_state == "speaking")
        duplex.append_commentary(text, delegation_id=d.id)
    duplex.on("delegation_created", _handed)

    def _live(event: dict) -> None:
        if event.get("type") == "error":
            record.event("live", type="error", error=event.get("error"))
            log.warning("live error %s", event.get("error"))
    duplex.on("openai_server_event_received", _live)

    t_start = clock.now()  # the recorded call's t=start is now
    build.start()
    if done_then:
        build.set_step(done_then)
        record.event("sim_start", at=args.start, done=done_then)
    record.event("build", started=True, steps=len(guide.steps))
    record.event("step", done=None, now=1)
    eyes.start()
    if hasattr(model, "warm"):
        await model.warm()
    session.generate_reply(instructions=(
        f'Greet the wearer in one short sentence: you can see their table, this round is "{guide.title}" in two or '
        "three words, and they should say when they are ready. Do not describe the build or a step."))

    if recording:
        def play_video() -> None:
            """Decodes the recording and makes each frame the newest at the second it was captured, as the camera
            would; the glasses store the frame landscape with a 90 degree rotation, so it is turned upright here."""
            import av
            container = av.open(str(rec / "recording" / "video.mp4"))
            stream = container.streams.video[0]
            # the file's own clock starts at its first frame, which video.csv stamps with the wall clock; a stretch
            # begun partway in seeks to the keyframe before its start instead of decoding everything before it
            if args.start > frame_times[0] + 1.0:
                container.seek(int((args.start - frame_times[0] - 1.0) / float(stream.time_base)), stream=stream)
            late = 0
            try:
                for fr in container.decode(stream):
                    if fr.time is None:
                        continue
                    t = frame_times[0] + fr.time - args.start
                    if t < 0:
                        continue
                    if t > end:
                        break
                    wait = t - (clock.now() - t_start)
                    if wait > 0:
                        time.sleep(wait)
                    elif wait < -0.15:
                        late += 1  # behind: this frame is decoded and dropped, the next one shown on time
                        continue
                    arr = np.ascontiguousarray(np.rot90(fr.to_ndarray(format="rgb24"), k=-1))  # landscape to upright
                    tap(rtc.VideoFrame(arr.shape[1], arr.shape[0], rtc.VideoBufferType.RGB24, arr.tobytes()), session)
            finally:
                container.close()
                if late:
                    log.warning("video: %d frames dropped, the decoder behind by more than 0.15 s", late)
                    record.event("sim_video", dropped=late)
        threading.Thread(target=play_video, name="video", daemon=True).start()

    i_p = i_w = 0
    mic_started = not recording
    while True:
        now = clock.now() - t_start
        if not mic_started and now >= mic_t:
            mic.say(mic_pcm)
            record.event("sim_mic", at=mic_t, length_s=round(len(mic_pcm) / (vs.SAMPLE_RATE * 2), 1))
            mic_started = True
        while i_p < len(photos) and photos[i_p][0] <= now:
            img = Image.open(io.BytesIO(photos[i_p][1].read_bytes())).convert("RGB")
            tap(rtc.VideoFrame(img.width, img.height, rtc.VideoBufferType.RGB24, img.tobytes()), session)
            record.event("sim_frame", photo=photos[i_p][1].name, at=photos[i_p][0])
            i_p += 1
        while i_w < len(speech) and speech[i_w][0] <= now:
            t, text, pcm = speech[i_w]
            mic.say(pcm)
            record.event("sim_said", text=text, at=t, length_s=round(len(pcm) / (vs.SAMPLE_RATE * 2), 1))
            i_w += 1
        if now >= end:
            break
        await asyncio.sleep(0.05)

    await asyncio.sleep(2.0)
    record.event("end", voice_s=sum(getattr(u, "session_duration", 0) for u in session.usage.model_usage), camera_frames=tap.count)

    async def step(name: str, coro) -> None:
        """One shutdown step, given 15 s: a close that hangs (seen once on session.aclose) must not hold the report."""
        try:
            await asyncio.wait_for(coro, 15.0)
        except asyncio.TimeoutError:
            log.warning("shutdown: %s did not finish in 15 s", name)
            print(f"shutdown: {name} did not finish in 15 s; going on")
    await step("eyes", eyes.stop())
    if hasattr(model, "close"):
        await step("model", model.close())
    mic.stop()
    await step("session", session.aclose())
    await step("llm", session.llm.aclose())
    record.close()
    wav(run_dir, clock, t_start, ear, mic)
    report(run_dir)
    print(run_dir / "report.md")


def wav(run_dir: Path, clock, t_start: float, ear, mic) -> None:
    sr = vs.SAMPLE_RATE
    end = max([clock.now()] + [s["t"] + (s["played"] or 0) for s in ear.segments]
              + [u["t"] + len(u["pcm"]) / (sr * 2) for u in mic.utterances])
    n = int(end * sr) + sr
    left, right = bytearray(n * 2), bytearray(n * 2)
    for seg in ear.segments:
        played = seg["played"] if seg["played"] is not None else seg["s"]
        pcm = bytes(seg["pcm"][: int(played * sr) * 2])
        at = int(seg["t"] * sr) * 2
        left[at:at + len(pcm)] = pcm
    for u in mic.utterances:
        at = int(u["t"] * sr) * 2
        right[at:at + len(u["pcm"])] = u["pcm"]
    frames = bytearray()
    for i in range(0, n * 2, 2):
        frames += left[i:i + 2] + right[i:i + 2]
    with wave.open(str(run_dir / "dialogue.wav"), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(bytes(frames))


def report(run_dir: Path) -> None:
    """The run as a timeline and its figures, from the record."""
    ev = [json.loads(line) for line in open(run_dir / "events.jsonl", encoding="utf-8")]
    rows = []
    for e in ev:
        k = e["kind"]
        t = e["t"]
        if k == "said":
            s, st_ = e.get("started"), e.get("stopped")
            when = f"{s:.1f}-{st_:.1f}" if s is not None and st_ is not None else f"{t:.1f}"
            rows.append((s if s is not None else t, f"| {when} | {e['who']} | {esc(e['text'])} |"))
        elif k == "commentary":
            rows.append((t, f"| {t:.1f} | to the voice ({e.get('source', 'brain')}) | {esc(e['text'])} |"))
        elif k == "step" and (e.get("done") is not None or e.get("reopened") is not None):
            rows.append((t, f"| {t:.1f} | progress | done={e.get('done')} reopened={e.get('reopened')} basis={e.get('basis')} |"))
        elif k == "words":
            rows.append((t, f"| {t:.1f} | words | {esc(e['text'])} -> {e['words_kind']} |"))
        elif k == "cut_in":
            rows.append((t, f"| {t:.1f} | cut in | the voice is told to stop for: {esc(e['text'])} |"))
        elif k == "consult_sent":
            rows.append((t, f"| {t:.1f} | consult | {e['reason']} |"))
        elif k == "say_held":
            rows.append((t, f"| {t:.1f} | held ({e.get('say_kind')}) | {esc(e['text'])} |"))
        elif k == "delegation":
            rows.append((t, f"| {t:.1f} | hand-over | closed at once |"))
        elif k in ("quick_failed", "consult_failed", "consult_late"):
            rows.append((t, f"| {t:.1f} | {k} | {esc(e.get('error'))} |"))
        elif k == "live" and e.get("type") == "error":
            rows.append((t, f"| {t:.1f} | live error | {esc(json.dumps(e.get('error')))} |"))
    rows.sort(key=lambda r: r[0])
    looks = [e["ms"] for e in ev if e["kind"] == "consult_back"]
    quick = [e for e in ev if e["kind"] == "quick"]
    voice = [(e["started"], e["stopped"]) for e in ev if e["kind"] == "said" and e["who"] == "voice"
             and e.get("started") is not None and e.get("stopped") is not None]
    total = max(e["t"] for e in ev)
    talk = sum(b - a for a, b in voice)
    starts = sorted(a for a, _ in voice)

    def to_voice(kind_filter):
        lat = []
        for e in ev:
            if e["kind"] == "commentary" and kind_filter(e):
                nxt = [s for s in starts if s >= e["t"]]
                if nxt:
                    lat.append(nxt[0] - e["t"])
        return lat

    def fmt(xs):
        xs = sorted(xs)
        return f"median {st.median(xs):.1f} s, p90 {xs[int(0.9 * len(xs)) - 1 if len(xs) > 1 else 0]:.1f}, max {xs[-1]:.1f} (n={len(xs)})" if xs else "-"

    lines = [f"# {run_dir.name}", "", "| t | who | text |", "|---|---|---|"] + [r for _, r in rows] + ["", "## Figures", ""]
    lines.append(f"- {total:.0f} s; the voice spoke {talk:.0f} s ({100 * talk / total:.0f}%), {len(voice)} turns, "
                 f"{sum(len(e['text'].split()) for e in ev if e['kind'] == 'said' and e['who'] == 'voice') / max(1, len(voice)):.0f} words a turn.")
    lines.append(f"- consults: {len(looks)}, ms median {st.median(looks):.0f}, p90 {sorted(looks)[int(0.9 * len(looks)) - 1]}, max {max(looks)}." if looks else "- consults: none")
    if quick:
        ms = [q["ms"] for q in quick]
        lines.append(f"- quick looks: {len(quick)}, ms median {st.median(ms):.0f}, p90 {sorted(ms)[int(0.9 * len(ms)) - 1]}, max {max(ms)}; "
                     f"tokens median {st.median(q['tokens'] for q in quick):.0f}.")
    lines.append(f"- an eyes' line to the voice's next start: {fmt(to_voice(lambda e: e.get('source') in ('quick', 'quick_look', 'eyes')))}.")
    lines.append(f"- a consult's line to the voice's next start: {fmt(to_voice(lambda e: e.get('source') == 'consult'))}.")
    steps = [e for e in ev if e["kind"] == "step" and e.get("done") is not None]
    lines.append("- progress: " + ", ".join(f"{e['done']} at {e['t']:.0f} s ({e.get('basis')})" for e in steps) + ".")
    reopened = [e for e in ev if e["kind"] == "step" and e.get("reopened") is not None]
    if reopened:
        lines.append("- reopened: " + ", ".join(f"step {e['reopened']} at {e['t']:.0f} s" for e in reopened) + ".")
    lines.append(f"- cut-ins: {sum(1 for e in ev if e['kind'] == 'cut_in')}.")
    lines.append(f"- hand-overs: {sum(1 for e in ev if e['kind'] == 'delegation')}; pokes: {sum(1 for e in ev if e['kind'] == 'poke')}; "
                 f"failed: {sum(1 for e in ev if e['kind'] in ('quick_failed', 'consult_failed'))}, late consults: {sum(1 for e in ev if e['kind'] == 'consult_late')}.")
    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def esc(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    asyncio.run(main())
