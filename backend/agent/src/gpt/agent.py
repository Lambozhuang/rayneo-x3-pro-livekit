"""The GPT path: GPT-Live voice, a delegated backend model, a separate vision check.

    glasses --audio--> SFU --> this process --ws--> gpt-live-1 <--delegation--> backend (blind)
            --video-->     --> FrameTap ---(one frame on demand)--> vision model, one call each
            <--audio-- SFU <-- this process <---------------------- gpt-live-1
            <--step attributes, model render track-- this process (Build = the one truth)

The voice model owns the conversation: turn-taking, barge-in, when to speak. It
hands anything about the build to the backend model, which calls our tools
(tools.py); check_step takes the next camera frame and asks the vision model
(vision.py), and the code moves the build on. No VAD is passed to the session:
the model listens while it speaks and stops on its own, and a framework VAD
would only cut the playout of a sentence the model keeps saying.
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
from gpt.tools import Run, check_step, end_call, get_step, look, previous_step, publish_build, restart_build
from gpt.vision import VisionCheck
from guide import Build, load_guide
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
    # Every camera frame lands in the tap and none reaches the speech model;
    # the vision check takes the next one when it is asked.
    tap = FrameTap(os.environ.get("FRAME_DUMP_DIR"), int(os.environ.get("FRAME_DUMP_MAX", "60")))
    build = Build(guide=guide, run=ctx.room.name)
    vision = VisionCheck(openai_client(), settings.check_model, settings.check_effort, guide, tap, lang)
    stream = ModelStream(guide.model, ModelState()) if guide.model and stream_enabled() else None
    if stream is not None:
        ctx.add_shutdown_callback(stream.stop)
    session: AgentSession[Run] = AgentSession(
        userdata=Run(build=build, vision=vision),
        video_sampler=tap,
        llm=build_live_model(settings, backend_instructions(guide, lang, model=stream is not None)),
    )

    # Two bills, two lines. The voice model is priced by the second and reports
    # cumulative session time about once a minute (usage:); the backend by the
    # token, one line per response it completes (model:). The vision model's
    # tokens are on the check: lines (vision.py).
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

    # The wearer's wait, measured on the glasses (ReplyLatency.kt): their last
    # word to the agent's audio arriving, from the SFU's speaker events, so it
    # does not depend on any turn detection here.
    @ctx.room.on("data_received")
    def _log_latency(pkt: rtc.DataPacket) -> None:
        if pkt.topic == "rayneo.latency":
            logger.info("latency: %s", pkt.data.decode("utf-8", "replace"))

    # Both sides as text. GPT-Live transcribes both; a turn is closed by the
    # framework when the audio goes quiet, so these lines trail the speech.
    @session.on("conversation_item_added")
    def _log_turn(ev: ConversationItemAddedEvent) -> None:
        if isinstance(ev.item, ChatMessage):
            logger.info("%s: %s", ev.item.role, ev.item.text_content)

    # Ask the SFU for the largest layer of every video track; it would
    # otherwise pick by bandwidth estimate. Registered before start() so it
    # covers the initial subscription.
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
        agent=Agent(
            instructions=voice_persona(guide, lang, model=stream is not None),
            tools=[get_step, check_step, look, previous_step, restart_build, end_call],
        ),
        room=ctx.room,
        room_options=room_io.RoomOptions(video_input=True),
    )

    wearer = await ctx.wait_for_participant()
    logger.info("session for user=%s room=%s", wearer.identity, ctx.room.name)
    if stream is not None:
        await stream.start(ctx.room.local_participant)
        build.model, build.model_nodes = stream.state, tuple(stream.nodes)
    build.start()
    await publish_build(build)
    await vision.prepare()

    # generate_reply on GPT-Live is commentary: a request the model may
    # decline. If it does, the wearer hears nothing until they speak.
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
