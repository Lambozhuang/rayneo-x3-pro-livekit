"""The Gemini path: one model hears, sees, speaks and keeps the progress.

    glasses --audio--> SFU --> this process --ws--> gemini-live (knows every step)
            --video-->     --> FixedRateSampler: one frame a second, cropped to the table, on to the model, a copy into the record
    gemini-live --set_progress(done)--> this process: the build moves, the glasses' step list follows
            <--audio-- SFU <-- this process <-- gemini-live

The model judges the plate from the frames in its own context and calls its one
tool. No VAD is passed to the session: Gemini's own turn detection decides when
the wearer has finished. The log and the call's record (runlog.py) are described
in the README's Logs section.
"""

import asyncio
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
    SessionUsageUpdatedEvent,
    room_io,
)
from livekit.agents.llm import ChatMessage
from livekit.agents.metrics import RealtimeModelMetrics

from env import language, require_env
from gemini.config import Settings, build_live_model
from gemini.prompts import instructions
from gemini.sampler import FixedRateSampler
from gemini.tools import Call, set_progress
from guide import Build, picked_guide, publish_build
from runlog import RunLog

logger = logging.getLogger("rayneo-agent")

server = AgentServer()


# Explicit dispatch: the api puts AGENT_NAME into every token it signs, and
# the agent joins only rooms that name it.
@server.rtc_session(agent_name=require_env("AGENT_NAME"))
async def rayneo_assistant(ctx: JobContext) -> None:
    settings = Settings.from_env()
    lang = language()
    guide = picked_guide(ctx.job.metadata)
    logger.info(settings.experiment_line(guide.name))
    # The call's record (runlog.py): what happened, in order, with every field; deploy/report.py reads it.
    record = RunLog(os.environ.get("RUN_DIR"), ctx.room.name)
    record.event("call", wall_ms=record.wall_ms, room=ctx.room.name, guide=guide.name, language=lang, commit=os.environ.get("GIT_COMMIT") or None,
                 settings=asdict(settings), steps=[s.name for s in guide.steps])
    build = Build(guide=guide, run=ctx.room.name)
    sampler = FixedRateSampler(settings.video_fps, settings.side, record, step=lambda: build.step + 1)
    session = AgentSession(userdata=Call(build, record), video_sampler=sampler, llm=build_live_model(settings))
    prompt = instructions(guide, lang)
    record.text("instructions.txt", prompt)

    # The model's own timing for each reply: from the first server message of a generation to its first audio
    # (ttft), the whole generation (duration), and this turn's tokens, image tokens spelled out: they are the
    # whole cost of the camera, and the only sign that video is arriving at all (a broken video path does not
    # fail the session, the model just describes a picture it never got).
    @session.on("metrics_collected")
    def _log_model(ev: MetricsCollectedEvent) -> None:
        m = ev.metrics
        if isinstance(m, RealtimeModelMetrics):
            image = m.input_token_details.image_tokens
            logger.info("model: ttft=%.2fs duration=%.1fs in=%d (image %d) out=%d", m.ttft, m.duration,
                        m.input_tokens, image, m.output_tokens)
            record.event("model", ttft_ms=round(m.ttft * 1000), duration_ms=round(m.duration * 1000),
                         in_tokens=m.input_tokens, image_tokens=image, out_tokens=m.output_tokens)

    # Cumulative per session, so the last line of a call is its total.
    @session.on("session_usage_updated")
    def _log_usage(ev: SessionUsageUpdatedEvent) -> None:
        for use in ev.usage.model_usage:
            logger.info("usage: %r image_tokens=%s", use, getattr(use, "input_image_tokens", 0))

    @session.on("close")
    def _log_close(ev) -> None:
        record.event("closed", reason=str(getattr(ev.reason, "value", ev.reason)), error=str(ev.error) if ev.error else None)

    async def _end() -> None:
        logger.info("usage: %s camera_frames=%d frames_to_model=%d", session.usage, sampler.count, sampler.sent)
        use = session.usage.model_usage
        record.event("end", in_tokens=sum(getattr(u, "input_tokens", 0) for u in use),
                     image_tokens=sum(getattr(u, "input_image_tokens", 0) for u in use),
                     out_tokens=sum(getattr(u, "output_tokens", 0) for u in use),
                     camera_frames=sampler.count, frames_to_model=sampler.sent)
        record.close()

    ctx.add_shutdown_callback(_end)

    # Both sides as text, into the log and the record: what the model heard the wearer say and what it answered.
    @session.on("conversation_item_added")
    def _log_turn(ev: ConversationItemAddedEvent) -> None:
        if isinstance(ev.item, ChatMessage):
            logger.info("%s: %s", ev.item.role, ev.item.text_content)
            if ev.item.role in ("user", "assistant"):
                record.event("said", who="wearer" if ev.item.role == "user" else "voice", text=ev.item.text_content,
                             interrupted=ev.item.interrupted)

    # When the model speaks, for the timeline. The wearer's side is not logged: without a local VAD the
    # framework's user state follows the model's generation, not the wearer's voice.
    @session.on("agent_state_changed")
    def _log_voice(ev) -> None:
        logger.info("live: voice %s -> %s", ev.old_state, ev.new_state)
        record.event("state", who="voice", old=ev.old_state, new=ev.new_state)

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
        agent=Agent(instructions=prompt, tools=[set_progress]),
        room=ctx.room,
        # Camera frames from the glasses reach the sampler, which crops and pushes them to the model itself.
        room_options=room_io.RoomOptions(video_input=True),
    )

    async def _camera_watch() -> None:
        await asyncio.sleep(10)
        if sampler.count == 0:
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

    # Open the conversation, so the wearer knows the line is live without having to test it.
    await session.generate_reply(
        instructions=(
            "Greet the wearer briefly: say you can see through their glasses and will "
            f'guide them through building "{guide.title}", naming it in a few words, and '
            "ask them to say when they are ready. Do not describe any step yet."
        )
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
