"""Entrypoint for the RayNeo X3 Pro live assistant.

This process registers with livekit-server under AGENT_NAME and waits to be
dispatched. The api service puts that name into every join token it signs, so
the agent turns up in exactly the rooms the backend created for authenticated
users and nowhere else. Nothing connects to this process; it is reachable only
through the room.
"""

import logging
import os
import sys

from dotenv import load_dotenv
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

from config import build_session_model, language, require_env, video_fps
from framedump import DumpingSampler
from livekit.plugins import silero
from guide import Build, load_guide
from prompts import build_instructions
from render import ModelState, ModelStream, stream_enabled
from sampler import CameraSampler
from tools import (
    end_call, get_step, highlight_part, look, publish_build, reopen_previous_step, restart_build, show_view, step_done,
)

load_dotenv()  # backend/.env, found by walking up from this file

logger = logging.getLogger("rayneo-agent")

# Two knobs for a CPU without AVX2 (the 2012 Mac mini this was first deployed
# on, Ivy Bridge). The framework's job-process warm-up (livekit.agents.ipc
# ._preload) initialises `livekit.local_inference`, the native local VAD and
# turn-detection models, and that library dies with SIGILL there: every job
# process crashes while initialising, the worker registers but can never take
# a call. AGENT_NO_LOCAL_INFERENCE=1 makes that import fail instead, which the
# warm-up catches and logs. We never use those models: turn detection is
# Gemini's, and the VAD below is the Silero plugin's own ONNX runtime.
# AGENT_MP_CONTEXT=spawn is the older half of the same fix, from when the
# warm-up ran in the forkserver. Leave both unset on modern CPUs.
if os.environ.get("AGENT_NO_LOCAL_INFERENCE"):
    sys.modules["livekit.local_inference"] = None  # type: ignore[assignment]

# A local VAD, loaded once per process. Turn-taking stays with Gemini; this
# only tells the framework when the *wearer* is talking, which it otherwise
# does not know (Gemini's speech events fire when the model starts answering).
# Two things hang off that: the camera sampler's "speaking" rate (sampler.py),
# and real user-turn timestamps, which make the SDK's e2e_latency meaningful.
def _load_vad(proc: agents.JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server = AgentServer(
    setup_fnc=_load_vad,
    **({"multiprocessing_context": ctx} if (ctx := os.environ.get("AGENT_MP_CONTEXT")) else {}),  # type: ignore[arg-type]
)


# Explicit dispatch. With a name set the server never auto-joins new rooms; it
# waits for a token (or a dispatch API call) that names it. The api puts
# AGENT_NAME into every token it signs.
# https://docs.livekit.io/agents/server/agent-dispatch/
@server.rtc_session(agent_name=require_env("AGENT_NAME"))
async def rayneo_assistant(ctx: JobContext) -> None:
    # Which camera frames the model sees: a few while the wearer speaks, none
    # while they are silent, one whenever the model calls `look`. See
    # sampler.py for why (every frame stays in context and slows every later
    # turn). FRAME_DUMP_DIR wraps the same sampler to also save what it passes.
    speaking_fps, silent_fps = video_fps()
    camera = CameraSampler(speaking_fps=speaking_fps, silent_fps=silent_fps)
    dump_dir = os.environ.get("FRAME_DUMP_DIR")
    sampler = (
        DumpingSampler(camera, dump_dir, int(os.environ.get("FRAME_DUMP_MAX", "60")))
        if dump_dir
        else camera
    )
    # The build guide and this run's position in it. The tools read and
    # advance it through session.userdata; see guide.py. One call is one run.
    build = Build(
        guide=load_guide(require_env("BUILD_GUIDE")), run=ctx.room.name, request_look=camera.request
    )
    # The reference model, if the guide ships one: rendered here, streamed to
    # the glasses as our second video track, the current step's brick
    # highlighted. See render.py. MODEL_STREAM=off keeps the guide without it.
    stream = ModelStream(build.guide.model, ModelState()) if build.guide.model and stream_enabled() else None
    if stream is not None:
        ctx.add_shutdown_callback(stream.stop)
    session = AgentSession(
        userdata=build,
        vad=ctx.proc.userdata["vad"],
        video_sampler=sampler,
        **build_session_model(),
    )
    logger.info("camera: speaking_fps=%s silent_fps=%s", speaking_fps, silent_fps)

    # Usage, straight to the log. `input_image_tokens` is the number to watch:
    # it is the entire cost of the camera, and it is also the only signal that
    # video is working at all -- a broken video path does not make the session
    # fail, it makes the model confidently describe a picture it never got. See
    # the README. `session_usage_updated` is cumulative per session, so the
    # last line of a call is its total.
    @session.on("session_usage_updated")
    def _log_usage(ev: SessionUsageUpdatedEvent) -> None:
        for use in ev.usage.model_usage:
            # repr() hides zero fields, so spell out the image tokens: "absent"
            # and "zero" have to read differently when zero is the bug.
            logger.info(
                "usage: %r image_tokens=%s",
                use,
                getattr(use, "input_image_tokens", 0),
            )

    # The model's own timing for each reply: from the first server message of
    # a generation to its first audio (ttft), the whole generation (duration),
    # and this turn's tokens, image tokens spelled out because the cumulative
    # usage line above hides how many frames one turn carried.
    # (The session-level event is marked deprecated in favour of per-plugin
    # ones, but a RealtimeModel has no event hook of its own; the SDK logs one
    # warning at start-up and keeps delivering.)
    @session.on("metrics_collected")
    def _log_model(ev: MetricsCollectedEvent) -> None:
        m = ev.metrics
        if isinstance(m, RealtimeModelMetrics):
            logger.info(
                "model: ttft=%.2fs duration=%.1fs in=%d (image %d) out=%d",
                m.ttft, m.duration, m.input_tokens,
                m.input_token_details.image_tokens, m.output_tokens,
            )

    # The wearer's wait, measured on the glasses: from their last word to the
    # agent's audio arriving, sent here as a data packet so it sits in this
    # log next to the model timing. The agent cannot measure this itself:
    # Gemini's turn detection never tells us when the wearer stopped, so the
    # SDK's own e2e_latency is empty for this model. See ReplyLatency.kt.
    @ctx.room.on("data_received")
    def _log_latency(pkt: rtc.DataPacket) -> None:
        if pkt.topic == "rayneo.latency":
            logger.info("latency: %s", pkt.data.decode("utf-8", "replace"))

    # Both sides of the conversation as text: what the model heard the wearer
    # say and what it answered. With this a test run can be judged from the
    # log next to the dumped frames, without listening in on the glasses.
    @session.on("conversation_item_added")
    def _log_turn(ev: ConversationItemAddedEvent) -> None:
        if isinstance(ev.item, ChatMessage):
            logger.info("%s: %s", ev.item.role, ev.item.text_content)
            # The SDK's own wait, wearer stopped (local VAD) -> agent audio
            # forwarded, next to the glasses' reply_ms; the difference between
            # the two is the network on the glasses' side.
            e2e = ev.item.metrics.get("e2e_latency") if ev.item.role == "assistant" else None
            if e2e is not None:
                logger.info('latency: {"server_e2e_ms":%d}', round(e2e * 1000))

    # Ask the SFU for the largest layer of every video track. Without this the
    # server picks by its own bandwidth estimate, which in the lab settled on
    # a 360x640 layer -- fine for a video call, useless for reading detail.
    # Registered before start() so it covers the initial subscription.
    @ctx.room.on("track_subscribed")
    def _want_full_video(
        track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant
    ) -> None:
        if publication.kind == rtc.TrackKind.KIND_VIDEO:
            # Only meaningful (and only allowed: the rtc SDK raises otherwise)
            # when the publisher sent several layers. The glasses send one.
            if publication.simulcasted:
                publication.set_video_quality(rtc.VideoQuality.VIDEO_QUALITY_HIGH)
            logger.info(
                "video from %s: published %dx%d %s simulcast=%s",
                participant.identity, publication.width, publication.height,
                publication.mime_type, publication.simulcasted,
            )

    await session.start(
        agent=Agent(
            instructions=build_instructions(build.guide, language(), model=stream is not None),
            tools=[look, get_step, step_done, reopen_previous_step, restart_build, show_view, highlight_part, end_call],
        ),
        room=ctx.room,
        # Camera frames from the glasses stream inline with the audio session.
        room_options=room_io.RoomOptions(video_input=True),
    )

    # The api signed the wearer's token with their user id as the identity, so
    # this is who we are talking to. Today it only goes to the log; per-user
    # memory or preferences would key off it here.
    wearer = await ctx.wait_for_participant()
    logger.info("session for user=%s room=%s", wearer.identity, ctx.room.name)
    if stream is not None:
        await stream.start(ctx.room.local_participant)
        build.model, build.model_nodes = stream.state, tuple(stream.nodes)
    build.start()
    await publish_build(build)

    # Open the conversation, so the wearer knows the line is live without
    # having to test it. One sentence; the first step waits until they say
    # they are ready, so the run starts on their word, not ours. (On 3.1 with
    # older plugins this call was ignored; livekit-agents 1.8.2 supports it on
    # 3.1 and 3.8.)
    await session.generate_reply(
        instructions=(
            "Greet the wearer in one short sentence: say you can see through their "
            "glasses and will guide them through this build, and ask them to say "
            "when they are ready. Do not describe any step yet."
        )
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
