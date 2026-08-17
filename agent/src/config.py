"""Environment configuration and the session model factory."""

from __future__ import annotations

import logging
import os
from typing import Any

from livekit.plugins import google

logger = logging.getLogger("rayneo-agent.config")


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. Copy agent/.env.example to agent/.env.local and fill it in."
        )
    return value


def build_session_model() -> dict[str, Any]:
    """Build the model half of the session as AgentSession keyword arguments.

    Returning kwargs rather than a single object is the one seam worth having:
    today this is a realtime speech-to-speech model, but a half-cascade setup
    would return {"llm": ..., "tts": ...} from here and agent.py would not
    change. Callers stay unaware of which shape they got.
    """
    model = _require("GEMINI_MODEL")
    logger.info("session model: %s", model)

    return {
        "llm": google.realtime.RealtimeModel(
            model=model,
            api_key=_require("GOOGLE_API_KEY"),
            voice=os.environ.get("GEMINI_VOICE", "Puck"),
        )
    }
