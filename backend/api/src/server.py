"""The one HTTP service the glasses talk to.

Implements LiveKit's standard token endpoint. livekit-server only verifies
join tokens; something holding the API secret has to sign them, and in a real
product that something is the backend that knows who the user is. This is it.
The glasses POST /getToken with their credential, get back a short-lived JWT
plus the server URL, and connect to livekit-server with that. The agent is
never reachable from the client; it is dispatched into the room by name.
https://docs.livekit.io/frontends/build/authentication/endpoint/
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import timedelta

from aiohttp import web
from dotenv import load_dotenv
from livekit import api

import auth

logger = logging.getLogger("rayneo-api")


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set. See backend/.env.example.")
    return value


async def get_token(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        raise web.HTTPBadRequest()

    user = auth.authenticate(request, body)

    # A fresh room per request, named after the user. Explicit dispatch below
    # means the agent only ever joins rooms whose token asked for it, so a
    # stale room name cannot strand the glasses with no agent; the fresh
    # suffix just keeps two calls by the same user from colliding.
    room = f"{user}-{uuid.uuid4().hex[:8]}"

    token = (
        api.AccessToken(require_env("LIVEKIT_API_KEY"), require_env("LIVEKIT_API_SECRET"))
        .with_identity(user)
        .with_name(body.get("participant_name") or "RayNeo X3 Pro")
        .with_grants(api.VideoGrants(room_join=True, room=room))
        # Which agent to dispatch into the room. Nothing else the client sends
        # in room_config is honoured; the agent is the backend's choice.
        .with_room_config(
            api.RoomConfiguration(
                agents=[api.RoomAgentDispatch(agent_name=require_env("AGENT_NAME"))]
            )
        )
        # Only the initial connection checks expiry. Once connected, the server
        # keeps issuing refreshed tokens for reconnects, so a call outliving
        # this TTL is unaffected. Short because self-hosted LiveKit cannot
        # revoke a token.
        # https://docs.livekit.io/frontends/reference/tokens-grants/#self-hosted
        .with_ttl(timedelta(minutes=10))
    )
    if body.get("participant_metadata"):
        token = token.with_metadata(body["participant_metadata"])
    if body.get("participant_attributes"):
        token = token.with_attributes(body["participant_attributes"])

    url = require_env("LIVEKIT_PUBLIC_URL")
    logger.info("issued token: user=%s room=%s url=%s", user, room, url)
    return web.json_response(
        {"server_url": url, "participant_token": token.to_jwt()}, status=201
    )


async def health(_: web.Request) -> web.Response:
    return web.Response(text="OK")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    load_dotenv()  # backend/.env, found by walking up from this file

    auth.check_config()
    for name in ("LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "LIVEKIT_PUBLIC_URL", "AGENT_NAME"):
        require_env(name)
    url = os.environ["LIVEKIT_PUBLIC_URL"]
    if "127.0.0.1" in url or "localhost" in url:
        logger.warning(
            "LIVEKIT_PUBLIC_URL is %s, which on the glasses means the glasses. "
            "Set it to an address the headset can reach.",
            url,
        )

    app = web.Application()
    app.add_routes([web.post("/getToken", get_token), web.get("/health", health)])
    host = os.environ.get("API_HOST", "0.0.0.0")
    port = int(os.environ.get("API_PORT", "3000"))
    logger.info("token endpoint: http://%s:%s/getToken (AUTH_MODE=%s)", host, port, auth.mode())
    web.run_app(app, host=host, port=port, print=None)


if __name__ == "__main__":
    main()
