"""Entrypoint for the RayNeo X3 Pro live assistant.

One process does two jobs: it is the LiveKit agent that joins every room and
talks to Gemini, and it serves the join-token endpoint the glasses call first.
The backend is therefore two processes, livekit-server and this.
"""

import asyncio
import logging
import os
import uuid
from datetime import timedelta

from aiohttp import web
from dotenv import load_dotenv
from livekit import agents, api
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

load_dotenv(".env.local")

logger = logging.getLogger("rayneo-agent")

# On Linux the default context is "forkserver", and the forkserver preloads
# livekit.agents.inference._warmup, which initialises the native local VAD and
# turn-detection models. That native library needs AVX2; on a CPU without it
# (the 2012 Mac mini this is deployed on, Ivy Bridge) the forkserver dies with
# SIGILL on every job and the worker registers but can never take a call. We
# use a realtime speech-to-speech model and never touch those models, so
# "spawn" costs nothing but a slower cold start. Leave it unset on modern CPUs:
# the framework then picks forkserver on Linux and spawn everywhere else, and
# passing "forkserver" explicitly would fail on Windows, which has no such
# context.
server = AgentServer(
    **({"multiprocessing_context": ctx} if (ctx := os.environ.get("AGENT_MP_CONTEXT")) else {})  # type: ignore[arg-type]
)


# agent_name is deliberately left unset. Without it the server uses automatic
# dispatch and joins every new room, which is what we want: the token endpoint
# below hands out a fresh room per request, and the agent turns up in it.
# https://docs.livekit.io/agents/server/agent-dispatch/
@server.rtc_session()
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

    # No opening greeting on purpose. gemini-3.1-flash-live-preview rejects
    # send_client_content after the first model turn, so the plugin ignores
    # session.generate_reply() on 3.1 models and just logs a warning. The
    # wearer speaks first.
    # https://docs.livekit.io/agents/models/realtime/plugins/gemini/#gemini-3-1-compatibility


# --- Join-token endpoint -----------------------------------------------------
#
# LiveKit's standard token endpoint, so the Android client's built-in
# TokenSource.fromEndpoint() works unmodified. livekit-server only verifies
# tokens; something holding the API secret has to sign them, and that is this
# process. The glasses hold no LiveKit secret and no Google key: they POST here,
# get a short-lived JWT plus the server URL, and connect with that.
# https://docs.livekit.io/frontends/build/authentication/endpoint/
#
# Anything that can reach this endpoint can start a Gemini session on our bill.
# On a private LAN that is acceptable and TOKEN_SERVER_SECRET stays unset.
# Anywhere else, set it: requests must then carry `?k=<secret>`, the one place
# the glasses can put a credential without changing the app, because
# `token_endpoint` is passed in whole as an adb extra. Only meaningful behind
# TLS; a query string over plain http is readable by everyone on the path.


async def get_token(request: web.Request) -> web.Response:
    secret = os.environ.get("TOKEN_SERVER_SECRET")
    if secret and request.query.get("k") != secret:
        logger.warning("rejected token request from %s", request.remote)
        raise web.HTTPUnauthorized()

    try:
        body = await request.json()
    except ValueError:
        body = {}

    # A fresh room per request. Automatic dispatch only fires when a room is
    # created, so handing out a room name that already exists can drop the
    # glasses into a room the agent has since left.
    room = body.get("room_name") or f"rayneo-{uuid.uuid4().hex[:8]}"

    token = (
        api.AccessToken(require_env("LIVEKIT_API_KEY"), require_env("LIVEKIT_API_SECRET"))
        .with_identity(body.get("participant_identity") or "glasses")
        .with_name(body.get("participant_name") or "RayNeo X3 Pro")
        .with_grants(api.VideoGrants(room_join=True, room=room))
        # Short TTL because self-hosted LiveKit cannot revoke a token. Only the
        # initial connection is affected; reconnects keep working past expiry.
        # https://docs.livekit.io/frontends/reference/tokens-grants/#self-hosted
        .with_ttl(timedelta(hours=1))
    )
    if body.get("participant_metadata"):
        token = token.with_metadata(body["participant_metadata"])
    if body.get("participant_attributes"):
        token = token.with_attributes(body["participant_attributes"])
    if body.get("room_config"):
        # Client SDKs pack agent dispatch info in here. This agent has no
        # agent_name, so a named request would go unfulfilled and the wearer
        # would sit in a silent room. Log it instead of forwarding something
        # nothing will answer.
        logger.warning("ignoring room_config from client: %s", body["room_config"])

    url = public_url()
    logger.info("issued token: room=%s url=%s", room, url)
    return web.json_response(
        {"server_url": url, "participant_token": token.to_jwt()}, status=201
    )


def public_url() -> str:
    """The server URL handed to the glasses, which is not always our own.

    This process reaches livekit-server on loopback. The glasses reach it from
    wherever they are, so the two can need different addresses: `LIVEKIT_URL`
    is what the agent dials, `LIVEKIT_PUBLIC_URL` is what the glasses are told.
    """
    return os.environ.get("LIVEKIT_PUBLIC_URL") or require_env("LIVEKIT_URL")


async def serve_token_endpoint() -> None:
    if not os.environ.get("TOKEN_SERVER_SECRET"):
        logger.warning(
            "TOKEN_SERVER_SECRET is unset: anyone who can reach /getToken can "
            "start a session. Fine on a private LAN, not anywhere else."
        )
    url = public_url()
    if "127.0.0.1" in url or "localhost" in url:
        logger.warning(
            "advertising %s to the glasses, which resolves to the headset itself. "
            "Set LIVEKIT_PUBLIC_URL to this machine's LAN IP. `adb reverse` is not "
            "a substitute: it carries signaling but cannot carry media. See the README.",
            url,
        )

    app = web.Application()
    app.add_routes([web.post("/getToken", get_token)])
    runner = web.AppRunner(app)
    await runner.setup()
    # All interfaces by default because the glasses reach this from the LAN.
    host = os.environ.get("TOKEN_SERVER_HOST", "0.0.0.0")
    port = int(os.environ.get("TOKEN_SERVER_PORT", "3000"))
    await web.TCPSite(runner, host, port).start()
    logger.info("token endpoint: http://%s:%s/getToken", host, port)


# The framework's own HTTP server (health check on :8081) is built inside
# run() and its routes are frozen before any hook fires, so the token endpoint
# gets its own aiohttp site on its own port. `worker_started` is emitted on the
# event loop once the worker is up; the site then lives as long as the process.
@server.on("worker_started")
def _start_token_endpoint() -> None:
    asyncio.ensure_future(serve_token_endpoint())


if __name__ == "__main__":
    agents.cli.run_app(server)
