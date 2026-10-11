"""The GPT path: GPT-Live speaks, the brain looks when it is asked to.

    glasses --audio--> SFU --> this process --ws--> gpt-live-1 (knows every step's wording)
            --video-->     --> FrameTap (frames kept for the brain, none to the voice)
    gpt-live-1 --delegation (id + the wearer's words)--> brain: next frame + the call so far
                                                         --> one vision call --> a reply, maybe confirm_step_correct
            <--commentary on that delegation-- brain (the voice says it in its own words)
            <--audio-- SFU <-- this process <-- gpt-live-1
            <--step list (participant attributes)-- this process (the step is the brain's)

The voice owns the conversation and answers what needs no eyes by itself; it
hands the rest over (client delegation, brain.py). No VAD is passed to the
session: the model listens while it speaks and stops on its own. The Gemini
path (gemini/) is untouched; the reference-model stream (render.py) stays
wired but unused by the flat-layout guides.
"""

import asyncio
import json
import logging
import os
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

from frames import FrameTap
from gpt.brain import TOOLS, Brain, make_model, publish_build
from gpt.config import Settings, build_live_model, language, require_env
from gpt.prompts import voice_persona
from guide import Build, load_guide
from render import ModelState, ModelStream, stream_enabled
from runlog import RunLog

logger = logging.getLogger("rayneo-agent")

server = AgentServer()


# Explicit dispatch: the api puts AGENT_NAME into every token it signs, and
# the agent joins only rooms that name it.
@server.rtc_session(agent_name=require_env("AGENT_NAME"))
async def rayneo_assistant(ctx: JobContext) -> None:
    settings = Settings.from_env()
    lang = language()
    guide = load_guide(require_env("BUILD_GUIDE"))
    logger.info(settings.experiment_line(guide.name))
    # The call's record (runlog.py): what happened, in order, with every field; deploy/report.py reads it.
    record = RunLog(os.environ.get("RUN_DIR"), ctx.room.name)
    record.event("call", room=ctx.room.name, guide=guide.name, language=lang, commit=os.environ.get("GIT_COMMIT") or None,
                 settings=asdict(settings), steps=[s.name for s in guide.steps])
    tap = FrameTap(on_first=lambda f: record.event("camera", first_frame=f"{f.width}x{f.height}"))
    build = Build(guide=guide, run=ctx.room.name)
    stream = ModelStream(guide.model, ModelState()) if guide.model and stream_enabled() else None
    if stream is not None:
        ctx.add_shutdown_callback(stream.stop)
    session = AgentSession(video_sampler=tap, llm=build_live_model(settings))
    model = make_model(settings.brain_provider, settings.brain_model, settings.brain_effort, settings.brain_detail)
    brain = Brain(session, build, tap, model, settings.brain_side, lang, settings.brain_timeout, record)
    persona = voice_persona(guide, lang)
    record.text("brain.txt", brain.instructions)
    record.text("brain-tools.json", json.dumps([{"name": n, "description": d, "input_schema": p} for n, d, p in TOOLS],
                                               indent=2))
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
        record.event("closed", reason=str(getattr(ev.reason, "value", ev.reason)), error=str(ev.error) if ev.error else None)

    async def _log_usage() -> None:
        logger.info("usage: %s camera_frames=%d", session.usage, tap.count)
        record.event("end", voice_s=sum(getattr(u, "session_duration", 0) for u in session.usage.model_usage),
                     camera_frames=tap.count)
        record.close()

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

    @ctx.room.on("track_subscribed")
    def _want_full_video(
        track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant
    ) -> None:
        if publication.kind == rtc.TrackKind.KIND_VIDEO:
            if publication.simulcasted:  # the rtc SDK raises otherwise; the glasses send one layer
                publication.set_video_quality(rtc.VideoQuality.VIDEO_QUALITY_HIGH)
            logger.info(
                "video from %s: published %dx%d %s simulcast=%s",
                participant.identity, publication.width, publication.height,
                publication.mime_type, publication.simulcasted,
            )

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
            logger.info("live: event %s", etype.split(".", 1)[1])
            record.event("live", type=etype.split(".", 1)[1])
        elif etype == "error":
            logger.warning("live: event error %s", event.get("error"))
            record.event("live", type="error", error=event.get("error"))

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
    if stream is not None:
        await stream.start(ctx.room.local_participant)
        build.model, build.model_nodes = stream.state, tuple(stream.nodes)
    build.start()
    record.event("step", done=None, now=1)
    await publish_build(build)

    # generate_reply on GPT-Live is commentary: a request the model may decline.
    handle = session.generate_reply(
        instructions=(
            "Greet the wearer in one short sentence: say you can see through their "
            "glasses and will guide them through this build, and ask them to say "
            "when they are ready. Do not describe any step yet."
        )
    )
    await handle
    if handle.exception() is not None:
        logger.warning("the model declined to greet the wearer")


if __name__ == "__main__":
    agents.cli.run_app(server)
