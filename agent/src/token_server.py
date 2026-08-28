"""Join-token endpoint for the glasses.

Implements LiveKit's standard token endpoint so the Android client's
`TokenSource.fromEndpoint()` can fetch room credentials. The glasses hold no
LiveKit API secret and no Google key of their own; they ask for a token and
connect with it.
https://docs.livekit.io/frontends/build/authentication/endpoint/

Development only. There is no authentication on this endpoint, so anything that
can reach it can mint a token for our server. Run it only while the glasses are
actually in use, and never expose it beyond the local network.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import timedelta

from aiohttp import web
from dotenv import load_dotenv
from livekit import api

from config import require_env

logger = logging.getLogger("rayneo-agent.token-server")

routes = web.RouteTableDef()


@routes.post("/getToken")
async def get_token(request: web.Request) -> web.Response:
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
        # Client SDKs pack agent dispatch info in here. agent.py uses automatic
        # dispatch and has no agent_name, so a named request would go
        # unfulfilled and the wearer would sit in a silent room. Log it instead
        # of forwarding something nothing will answer. To support it later,
        # build an api.RoomConfiguration proto and pass that to
        # with_room_config() - it rejects a plain dict, despite what the docs
        # example implies.
        logger.warning("ignoring room_config from client: %s", body["room_config"])

    url = public_url()
    logger.info("issued token: room=%s url=%s", room, url)
    return web.json_response(
        {"server_url": url, "participant_token": token.to_jwt()}, status=201
    )


def public_url() -> str:
    """The server URL handed to the glasses, which is not always our own.

    The agent runs alongside livekit-server and can always reach it on loopback.
    The glasses reach it from wherever they are, so the two can need different
    addresses: `LIVEKIT_URL` is what this process and the agent dial, and
    `LIVEKIT_PUBLIC_URL` overrides what gets advertised to the headset.
    """
    return os.environ.get("LIVEKIT_PUBLIC_URL") or require_env("LIVEKIT_URL")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    load_dotenv(".env.local")

    url = public_url()
    if "127.0.0.1" in url or "localhost" in url:
        logger.warning(
            "advertising %s to the glasses, which resolves to the headset itself. "
            "Set LIVEKIT_PUBLIC_URL to this machine's LAN IP. Forwarding the ports "
            "over USB is not a substitute: `adb reverse` gets the headset a token "
            "and a signaling session but cannot carry media, because the client "
            "never gathers a loopback ICE candidate. See the README.",
            url,
        )

    app = web.Application()
    app.add_routes(routes)
    # Defaults to all interfaces because the glasses have to reach this from the
    # LAN. Set TOKEN_SERVER_HOST=127.0.0.1 to keep it local while testing.
    host = os.environ.get("TOKEN_SERVER_HOST", "0.0.0.0")
    port = int(os.environ.get("TOKEN_SERVER_PORT", "3000"))
    logger.info("token endpoint: http://%s:%s/getToken", host, port)
    web.run_app(app, host=host, port=port, print=None)


if __name__ == "__main__":
    main()
