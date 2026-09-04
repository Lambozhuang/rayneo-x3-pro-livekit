"""Entrypoint for the RayNeo X3 Pro live assistant.

This process registers with livekit-server under AGENT_NAME and waits to be
dispatched. The api service puts that name into every join token it signs, so
the agent turns up in exactly the rooms the backend created for authenticated
users and nowhere else. Nothing connects to this process; it is reachable only
through the room.
"""

import logging
import os

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    SessionUsageUpdatedEvent,
    room_io,
)

from config import build_session_model, require_env
from prompts import SYSTEM_INSTRUCTIONS
from tools import remember_note

load_dotenv()  # backend/.env, found by walking up from this file

logger = logging.getLogger("rayneo-agent")

# On Linux the default context is "forkserver", and the forkserver preloads
# livekit.agents.inference._warmup, which initialises the native local VAD and
# turn-detection models. That native library needs AVX2; on a CPU without it
# (the 2012 Mac mini this was first deployed on, Ivy Bridge) the forkserver
# dies with SIGILL on every job and the worker registers but can never take a
# call. We use a realtime speech-to-speech model and never touch those models,
# so "spawn" costs nothing but a slower cold start. Leave it unset on modern
# CPUs: the framework then picks forkserver on Linux and spawn everywhere
# else, and passing "forkserver" explicitly would fail on Windows, which has
# no such context.
server = AgentServer(
    **({"multiprocessing_context": ctx} if (ctx := os.environ.get("AGENT_MP_CONTEXT")) else {}),  # type: ignore[arg-type]
)


# Explicit dispatch. With a name set the server never auto-joins new rooms; it
# waits for a token (or a dispatch API call) that names it. The api puts
# AGENT_NAME into every token it signs.
# https://docs.livekit.io/agents/server/agent-dispatch/
@server.rtc_session(agent_name=require_env("AGENT_NAME"))
async def rayneo_assistant(ctx: JobContext) -> None:
    session = AgentSession(
        **build_session_model(),
        # The default video_sampler is kept on purpose. It is
        # VoiceActivityVideoSampler(speaking_fps=1.0, silent_fps=0.3), and at
        # 640x480 a frame measured at exactly 63 input image tokens -- so about
        # 1130 tokens/min while the wearer is silent and 3780 while speaking,
        # against 1500 tokens/min for the audio. Overriding it means passing
        # video_sampler=VoiceActivityVideoSampler(...) from livekit.agents.voice
        # here. Lowering silent_fps is the lever with the best ratio of savings
        # to lost context; media_resolution on the model in config.py is not one
        # -- MEDIA_RESOLUTION_MEDIUM changed the measured token count by zero.
        # https://docs.livekit.io/agents/logic/sessions/#video-sampling
    )

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

    await session.start(
        agent=Agent(
            instructions=SYSTEM_INSTRUCTIONS,
            tools=[remember_note],
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

    # No opening greeting on purpose. gemini-3.1-flash-live-preview rejects
    # send_client_content after the first model turn, so the plugin ignores
    # session.generate_reply() on 3.1 models and just logs a warning. The
    # wearer speaks first.
    # https://docs.livekit.io/agents/models/realtime/plugins/gemini/#gemini-3-1-compatibility


if __name__ == "__main__":
    agents.cli.run_app(server)
