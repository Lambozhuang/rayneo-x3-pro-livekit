"""The GPT path: GPT-Live speaks, the code watches the camera and holds the step.

    glasses --audio--> SFU --> this process --ws--> gpt-live-1 (knows every step's wording)
            --video-->     --> FrameTap --> gate --> judge (CV, or a vision model) --> state machine
                                                          --> "Camera: step N is done ..." as commentary to GPT-Live
            <--audio-- SFU <-- this process <---------------- gpt-live-1
            <--step list (participant attributes)-- this process (step index = the state machine's)

The voice model owns the conversation; the code owns the build: the steps are
in the voice's instructions, the camera's confirmed changes arrive as
commentary (watch.py), and check_now answers from the code's state (tools.py).
No VAD is passed to the session: the model listens while it speaks and stops
on its own. The Gemini path (gemini/) is untouched; the reference-model stream
(render.py) stays wired but unused by the flat-layout guides.
"""

import logging
import os

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
from livekit.agents.metrics import LLMMetrics, RealtimeModelMetrics

from frames import FrameTap
from gpt.config import Settings, build_live_model, language, openai_client, require_env
from gpt.prompts import backend_instructions, voice_persona
from gpt.tools import Run, check_now, end_call, publish_build
from gpt.watch import Watch
from guide import Build, load_guide
from gate import Gate
from judge_cv import CVJudge, Layout
from render import ModelState, ModelStream, stream_enabled

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
    tap = FrameTap(os.environ.get("FRAME_DUMP_DIR"), int(os.environ.get("FRAME_DUMP_MAX", "60")))
    build = Build(guide=guide, run=ctx.room.name)
    if settings.judge == "vlm":
        from judge_vlm import VLMJudge

        judge = VLMJudge(openai_client(), guide, settings.check_model, settings.check_effort, settings.check_detail)
    else:
        if settings.colours not in guide.colours:
            raise RuntimeError(f"JUDGE_COLOURS={settings.colours!r}: {guide.name}/task.toml has colour tables {sorted(guide.colours)}")
        judge = CVJudge(Layout.from_guide(guide), guide.colours[settings.colours], settings.focal_px)
    stream = ModelStream(guide.model, ModelState()) if guide.model and stream_enabled() else None
    if stream is not None:
        ctx.add_shutdown_callback(stream.stop)
    session: AgentSession[Run] = AgentSession(
        video_sampler=tap,
        llm=build_live_model(settings, backend_instructions(lang)),
    )
    gate = Gate(settings.gate_still, settings.gate_motion, settings.gate_min_side)
    watch = Watch(session, build, judge, gate, tap, publish_build, gap=settings.watch_gap,
                  confirm=settings.watch_confirm, inflight=settings.watch_inflight,
                  wrong_confirm=settings.watch_wrong_confirm)
    session.userdata = Run(build=build, watch=watch)
    ctx.add_shutdown_callback(watch.stop)

    # Two bills. The voice model is priced by the second and reports cumulative
    # session time about once a minute (usage:); the backend by the token, one
    # line per response (model:). A VLM judge's tokens are on the judge: lines
    # (watch.py); the CV judge costs nothing.
    @session.on("metrics_collected")
    def _log_metrics(ev: MetricsCollectedEvent) -> None:
        m = ev.metrics
        if isinstance(m, RealtimeModelMetrics) and m.session_duration:
            logger.info("usage: voice +%.0fs", m.session_duration)
        elif isinstance(m, LLMMetrics):
            logger.info(
                "model: backend %s in=%d (cached %d) out=%d reasoning=%d",
                m.metadata.model_name if m.metadata else "?", m.prompt_tokens, m.prompt_cached_tokens,
                m.completion_tokens, m.reasoning_tokens,
            )

    async def _log_usage() -> None:
        logger.info("usage: %s camera_frames=%d", session.usage, tap.count)

    ctx.add_shutdown_callback(_log_usage)

    # The wearer's wait, measured on the glasses (ReplyLatency.kt).
    @ctx.room.on("data_received")
    def _log_latency(pkt: rtc.DataPacket) -> None:
        if pkt.topic == "rayneo.latency":
            logger.info("latency: %s", pkt.data.decode("utf-8", "replace"))

    # Both sides as text; a turn is closed when the audio goes quiet, so these
    # lines trail the speech.
    @session.on("conversation_item_added")
    def _log_turn(ev: ConversationItemAddedEvent) -> None:
        if isinstance(ev.item, ChatMessage):
            logger.info("%s: %s", ev.item.role, ev.item.text_content)

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
        agent=Agent(instructions=voice_persona(guide, lang), tools=[check_now, end_call]),
        room=ctx.room,
        # GPT-Live's transcript already trails its audio; the framework's
        # pacing of text to playout only added to that on the glasses.
        room_options=room_io.RoomOptions(
            video_input=True, text_output=room_io.TextOutputOptions(sync_transcription=False)
        ),
    )

    wearer = await ctx.wait_for_participant()
    logger.info("session for user=%s room=%s", wearer.identity, ctx.room.name)
    if stream is not None:
        await stream.start(ctx.room.local_participant)
        build.model, build.model_nodes = stream.state, tuple(stream.nodes)
    build.start()
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
    watch.start()


if __name__ == "__main__":
    agents.cli.run_app(server)
