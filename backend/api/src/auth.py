"""Who is asking for a token.

`authenticate()` turns a request into a user id or raises 401. It is the one
place the product's identity story plugs in, and the only thing AUTH_MODE
changes. Everything downstream (room name, LiveKit grants, which agent) only
ever sees the user id.

    dev     Anyone. The id is whatever the client sent as participant_identity,
            or "glasses". For a private LAN with the headset, and nothing else.
    static  One shared bearer token, AUTH_STATIC_TOKEN. For a small group
            sharing a test deployment. Same id rule as dev.
    jwt     A JWT issued by an account system we do not have yet, verified
            with AUTH_JWT_KEY (HMAC secret or PEM public key, per
            AUTH_JWT_ALGORITHM). The id is its `sub` claim. This is what a
            product runs.

The credential always travels as `Authorization: Bearer <...>`, which every
LiveKit client SDK's endpoint TokenSource can send. A query string would also
work but ends up in access logs, so it is not accepted.
"""

from __future__ import annotations

import logging
import os

import jwt
from aiohttp import web

logger = logging.getLogger("rayneo-api.auth")

MODES = ("dev", "static", "jwt")


def mode() -> str:
    m = os.environ.get("AUTH_MODE", "").strip()
    if m not in MODES:
        raise RuntimeError(f"AUTH_MODE must be one of {MODES}, got {m!r}. See backend/.env.example.")
    return m


def check_config() -> None:
    """Fail at startup, not on the first request, if the mode is misconfigured."""
    m = mode()
    if m == "dev":
        logger.warning(
            "AUTH_MODE=dev: /getToken accepts every request. Anyone who can reach "
            "this port can start a Gemini session on this account. Private LAN only."
        )
    elif m == "static" and not os.environ.get("AUTH_STATIC_TOKEN"):
        raise RuntimeError("AUTH_MODE=static needs AUTH_STATIC_TOKEN")
    elif m == "jwt" and not os.environ.get("AUTH_JWT_KEY"):
        raise RuntimeError("AUTH_MODE=jwt needs AUTH_JWT_KEY")


def authenticate(request: web.Request, body: dict) -> str:
    """Return the user id for this request, or raise HTTPUnauthorized."""
    m = mode()
    credential = _bearer(request)

    if m == "dev":
        return _claimed_identity(body)

    if m == "static":
        if credential != os.environ["AUTH_STATIC_TOKEN"]:
            raise _unauthorized(request, "bad or missing static token")
        return _claimed_identity(body)

    # jwt
    if not credential:
        raise _unauthorized(request, "missing bearer token")
    try:
        claims = jwt.decode(
            credential,
            os.environ["AUTH_JWT_KEY"],
            algorithms=[os.environ.get("AUTH_JWT_ALGORITHM", "HS256")],
            options={"require": ["sub", "exp"]},
        )
    except jwt.PyJWTError as e:
        raise _unauthorized(request, f"invalid jwt: {e}")
    return str(claims["sub"])


def _bearer(request: web.Request) -> str | None:
    header = request.headers.get("Authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def _claimed_identity(body: dict) -> str:
    return str(body.get("participant_identity") or "glasses")


def _unauthorized(request: web.Request, why: str) -> web.HTTPUnauthorized:
    logger.warning("rejected token request from %s: %s", request.remote, why)
    return web.HTTPUnauthorized()
