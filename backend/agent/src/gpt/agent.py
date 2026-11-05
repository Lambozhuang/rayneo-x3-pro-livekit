"""The GPT path: GPT-Live speaks, the brain looks by itself every few seconds.

    glasses --audio--> SFU --> this process --ws--> gpt-live-1 (knows every step)
            --video-->     --> FrameTap (frames kept for the brain, none to the voice)
    brain: a frame every few seconds + the lines said since its last look --> one vision call --> what it sees,
           kept to itself, maybe tell, say, set_progress or show
            <--thinking (tell: a fact for later) or commentary (say: the user hears it now; the progress moved)-- brain
            <--audio-- SFU <-- this process <-- gpt-live-1
            <--step list (participant attributes)-- this process (the step is the brain's)

The voice owns the conversation and answers from the steps and from what the
brain has told it; it is told not to hand anything over, and a hand-over it makes
all the same is closed at once (brain.py). No VAD is passed to the session: the
model listens while it speaks and stops on its own.
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict

from livekit import agents, rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    ConversationItemAddedEvent,
    JobContext,
    MetricsCollectedEvent,
    room_io,
)
from livekit.agents.llm import ChatMessage
from livekit.agents.metrics import RealtimeModelMetrics

from camera import watch_camera
from env import language, require_env
from frames import FrameTap
from gpt.brain import TOOLS, Brain, make_model
from gpt.config import Settings, build_live_model
from gpt.prompts import voice_persona
from guide import Build, picked_guide, publish_build
from qoe import LabRun, deliver, write_report
from runlog import RunLog

logger = logging.getLogger("rayneo-agent")

OVER_QUIET_S = 2.0  # the voice has said the build is done once it has been silent this long after it; it pauses up to a second between sentences
OVER_CAP_S = 15.0  # the call ends this long after the last step even if the voice said nothing

server = AgentServer()


# Explicit dispatch: the api puts AGENT_NAME into every token it signs, and
# the agent joins only rooms that name it.
@server.rtc_session(agent_name=require_env("AGENT_NAME"))
async def rayneo_assistant(ctx: JobContext) -> None:
    settings = Settings.from_env()
    lang = language()
    guide = picked_guide(ctx.job.metadata)
    logger.info(settings.experiment_line(guide.name))
    # The lab console's run, when the glasses were started by it (qoe.py); the record goes to the console at the end.
    lab = LabRun.from_metadata(ctx.job.metadata)
    # The call's record (runlog.py): what happened, in order, with every field; deploy/report.py reads it.
    record = RunLog(os.environ.get("RUN_DIR"), ctx.room.name)
    if lab and not record.dir:
        raise RuntimeError("a lab run needs RUN_DIR: the record is what goes to the console")
    record.event("call", wall_ms=record.wall_ms, room=ctx.room.name, lab=asdict(lab) if lab else None, guide=guide.name, language=lang, commit=os.environ.get("GIT_COMMIT") or None,
                 settings=asdict(settings), steps=[s.name for s in guide.steps])
    tap = FrameTap(on_first=lambda f: record.event("camera", first_frame=f"{f.width}x{f.height}"))
    build = Build(guide=guide, run=ctx.room.name)
    session = AgentSession(video_sampler=tap, llm=build_live_model(settings))
    model = make_model(settings.brain_provider, settings.brain_model, settings.brain_detail)
    brain = Brain(session, build, tap, model, settings.brain_effort, settings.brain_watch_side,
                  settings.brain_watch_every, lang, settings.brain_timeout, record)
    persona = voice_persona(guide, lang)
    record.text("brain.txt", brain.instructions)
    record.text("brain-tools.json", json.dumps(
        [{"name": n, "description": d, "input_schema": p} for n, d, p in TOOLS], indent=2))
    record.text("voice.txt", persona)

    # Two bills. The voice model is priced by the second and reports cumulative
    # session time about once a minute (usage:); the brain by the token, on its
    # brain: lines.
    @session.on("metrics_collected")
    def _log_metrics(ev: MetricsCollectedEvent) -> None:
        m = ev.metrics
        if isinstance(m, RealtimeModelMetrics) and m.session_duration:
            logger.info("usage: voice +%.0fs", m.session_duration)

    @session.on("close")
    def _log_close(ev) -> None:
        brain.stop_watching()  # the call is over: no more looks at a camera that has stopped sending
        record.event("closed", reason=str(getattr(ev.reason, "value", ev.reason)), error=str(ev.error) if ev.error else None)
        # The call is over when the session is: end the job now, not when livekit-server closes the room, which is
        # 20 s after the glasses leave (departure_timeout), so the record closes and reaches the console at once.
        ctx.shutdown(reason=f"session closed: {getattr(ev.reason, 'value', ev.reason)}")

    async def _log_usage() -> None:
        brain.stop_watching()
        logger.info("usage: %s camera_frames=%d", session.usage, tap.count)
        record.event("end", voice_s=sum(getattr(u, "session_duration", 0) for u in session.usage.model_usage),
                     camera_frames=tap.count)
        record.close()
        if lab:
            path = write_report(lab, record.dir, record.wall_ms, round(time.time() * 1000),
                                {"steps": len(guide.steps), "done": build.step, "finished": build.finished})
            await asyncio.to_thread(deliver, path, 20)

    ctx.add_shutdown_callback(_log_usage)

    # Both sides as text, into the log and the record (the brain reads the same turns from the session's
    # history); a turn is closed when the audio goes quiet, so these lines trail the speech.
    @session.on("conversation_item_added")
    def _log_turn(ev: ConversationItemAddedEvent) -> None:
        if isinstance(ev.item, ChatMessage):
            logger.info("%s: %s", ev.item.role, ev.item.text_content)
            if ev.item.role in ("user", "assistant"):
                m = ev.item.metrics or {}
                record.event("said", who="wearer" if ev.item.role == "user" else "voice", text=ev.item.text_content,
                             interrupted=ev.item.interrupted,
                             started=record.t(m["started_speaking_at"]) if m.get("started_speaking_at") else None,
                             stopped=record.t(m["stopped_speaking_at"]) if m.get("stopped_speaking_at") else None)

    # The glasses' camera track: the full layer, and what decodes it into the record (camera.py).
    watch_camera(ctx.room, record, logger)

    await session.start(
        agent=Agent(instructions=persona),
        room=ctx.room,
        # GPT-Live's transcript already trails its audio; the framework's
        # pacing of text to playout only added to that on the glasses.
        room_options=room_io.RoomOptions(
            video_input=True, text_output=room_io.TextOutputOptions(sync_transcription=False)
        ),
    )
    duplex = session.current_agent.duplex_session
    duplex.on("delegation_created", brain.on_delegation)

    # The call's timeline in the log: who is speaking when, and what GPT-Live itself reports about handing over
    # (its raw events, so a delegation the plugin did not pass on would still show).
    @session.on("user_state_changed")
    def _log_wearer(ev) -> None:
        logger.info("live: wearer %s -> %s", ev.old_state, ev.new_state)
        record.event("state", who="wearer", old=ev.old_state, new=ev.new_state)

    @session.on("agent_state_changed")
    def _log_voice(ev) -> None:
        logger.info("live: voice %s -> %s", ev.old_state, ev.new_state)
        record.event("state", who="voice", old=ev.old_state, new=ev.new_state)

    def _log_live_event(event: dict) -> None:
        etype = event.get("type", "")
        # GPT-Live bills by the session second: from session.started to session.closed, whose usage is the total
        if etype == "session.started":
            sid = (event.get("session") or {}).get("id")
            logger.info("gpt-live: session started %s (billed from here)", sid or "")
            record.event("live", type="session.started", id=sid)
        elif etype == "session.closed":
            secs = (event.get("usage") or {}).get("seconds")
            logger.info("gpt-live: session closed (%s), %s s billed", event.get("reason"), secs)
            record.event("live", type="session.closed", reason=event.get("reason"), seconds=secs)
        elif etype == "session.delegation.created":
            d = event.get("delegation") or {}
            logger.info("live: event delegation.created id=%s target=%s offset_ms=%s", d.get("id"), d.get("target"),
                        event.get("offset_ms"))
            record.event("live", type="delegation.created", id=d.get("id"), target=d.get("target"),
                         offset_ms=event.get("offset_ms"))
        elif etype in ("session.commentary.appended", "session.thinking.appended", "session.instructions.appended"):
            # the receipt comes at the estimated end of injection, not when it is spoken
            logger.info("live: event %s for %s start_ms=%s end_ms=%s", etype.split(".", 1)[1],
                        event.get("client_event_id"), event.get("start_ms"), event.get("end_ms"))
            record.event("live", type=etype.split(".", 1)[1], for_id=event.get("client_event_id"),
                         start_ms=event.get("start_ms"), end_ms=event.get("end_ms"))
        elif etype == "error":
            logger.warning("live: event error %s", event.get("error"))
            record.event("live", type="error", error=event.get("error"))

    # Everything this process sends to GPT-Live, as it goes on the wire (the plugin's own events too, such as the
    # greeting's commentary from generate_reply); the mic audio is left out. session.start went before this hook.
    def _log_live_sent(event: dict) -> None:
        etype = event.get("type", "")
        if etype == "session.input_audio.append":
            return
        if etype in ("session.commentary.append", "session.thinking.append", "session.instructions.append"):
            logger.info("live: sent %s id=%s delegation=%s: %s", etype.split(".", 1)[1], event.get("event_id"),
                        event.get("delegation_id") or "none", event.get("content"))
            record.event("live_sent", type=etype.split(".", 1)[1], id=event.get("event_id"),
                         delegation=event.get("delegation_id"), content=event.get("content"))
        else:
            logger.info("live: sent %s %s", etype, json.dumps({k: v for k, v in event.items() if k != "type"}))
            record.event("live_sent", type=etype, event=event)

    duplex.on("openai_client_event_queued", _log_live_sent)
    duplex.on("openai_server_event_received", _log_live_event)
    if getattr(duplex, "_session_id", None):  # started before the hook above was in place
        logger.info("gpt-live: session started %s (billed from here; before this line)", duplex._session_id)
        record.event("live", type="session.started", id=duplex._session_id, before_hook=True)

    async def _camera_watch() -> None:
        await asyncio.sleep(10)
        if tap.count == 0:
            logger.warning("camera: no frame 10 s into the call; the glasses are not sending video")
            record.event("camera", none_after_s=10)

    asyncio.create_task(_camera_watch(), name="camera_watch")

    wearer = await ctx.wait_for_participant()
    logger.info("session for user=%s room=%s", wearer.identity, ctx.room.name)
    record.event("wearer", joined=wearer.identity)

    # The glasses' link as the SFU sees it: who comes and goes (with the SFU's reason) and its coarse quality score.
    @ctx.room.on("participant_connected")
    def _log_join(p: rtc.RemoteParticipant) -> None:
        logger.info("link: %s joined", p.identity)
        record.event("wearer", joined=p.identity)

    @ctx.room.on("participant_disconnected")
    def _log_leave(p: rtc.RemoteParticipant) -> None:
        reason = rtc.DisconnectReason.Name(p.disconnect_reason) if p.disconnect_reason is not None else None
        logger.info("link: %s left (%s)", p.identity, reason or "no reason given")
        record.event("wearer", left=p.identity, reason=reason)

    @ctx.room.on("connection_quality_changed")
    def _log_quality(p: rtc.Participant, quality: rtc.ConnectionQuality) -> None:
        if isinstance(p, rtc.RemoteParticipant):
            name = quality.name.removeprefix("QUALITY_").lower()
            logger.info("link: %s quality %s", p.identity, name)
            record.event("quality", who=p.identity, quality=name)
    build.start()
    # The task's bounds in the record: `build` started here, finished when the last step is recorded as done.
    record.event("build", started=True, steps=len(guide.steps))
    record.event("step", done=None, now=1)
    await publish_build(build)
    brain.start_watching()

    # The task ends by itself: once the brain has recorded the last step as done, the voice says so (the Progress
    # commentary), and when it has stopped speaking the glasses are told to hang up through Build.over in the published
    # attributes (BuildSteps.kt), so the wearer has nothing to remember to end a task (the pilot of 2026-11-03). The
    # brain may still move the progress back while the voice speaks; then the wait starts over. The silence is measured
    # here, at the agent's end of the audio; the glasses wait for a second of silence at their own decoder before they
    # hang up (VoiceAssistantScreen.kt), so the last words are heard whatever the network's delay. The session closes
    # as it does whenever the glasses leave.
    async def _end_when_finished() -> None:
        while True:
            while not build.finished:
                await asyncio.sleep(0.5)
            t_finished, spoke, quiet_since = time.monotonic(), False, None
            while build.finished:
                if session.agent_state == "speaking":
                    spoke, quiet_since = True, None
                elif spoke:
                    quiet_since = quiet_since or time.monotonic()
                    if time.monotonic() - quiet_since >= OVER_QUIET_S:
                        break
                if time.monotonic() - t_finished >= OVER_CAP_S:
                    break
                await asyncio.sleep(0.1)
            else:
                continue  # the progress moved back before the end: the build is on again
            build.over = True
            after = time.monotonic() - t_finished
            logger.info("build: over, the voice has %s; the glasses are told to hang up %.1f s after the last step",
                        "said so" if spoke else "said nothing", after)
            record.event("over", after_finish_s=round(after, 1), spoke=spoke)
            await publish_build(build)
            return

    asyncio.create_task(_end_when_finished(), name="end_when_finished")

    # generate_reply on GPT-Live is commentary: a request the model may decline.
    handle = session.generate_reply(
        instructions=(
            "Greet the wearer in one short sentence: you can see their table, and they should say when they are "
            "ready. Nothing else: no task name, no list of what they can do, no step. They have done this before."
        )
    )
    await handle
    if handle.exception() is not None:
        logger.warning("the model declined to greet the wearer")


if __name__ == "__main__":
    agents.cli.run_app(server)
