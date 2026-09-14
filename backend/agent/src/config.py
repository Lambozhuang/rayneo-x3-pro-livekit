"""Environment configuration and the session model factory."""

from __future__ import annotations

import logging
import os
from typing import Any

from google.genai import types
from livekit.agents.utils import images
from livekit.plugins import google

logger = logging.getLogger("rayneo-agent.config")


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. Copy backend/.env.example to backend/.env and fill it in."
        )
    return value


# How a camera frame is encoded before upload. The plugin's default squeezes
# every frame into 1024x1024 at JPEG quality 75, which threw away most of a
# 1080p capture before Gemini ever saw it. Send frames at their captured size
# instead; how many tokens the model spends on them is media_resolution's
# business. framedump.py writes its `-sent.jpg` with these same options.
IMAGE_ENCODE_OPTIONS = images.EncodeOptions(
    format="JPEG",
    quality=85,
    resize_options=images.ResizeOptions(width=1920, height=1920, strategy="scale_aspect_fit"),
)


def build_session_model() -> dict[str, Any]:
    """Build the model half of the session as AgentSession keyword arguments.

    Returning kwargs rather than a single object is the one seam worth having:
    today this is a realtime speech-to-speech model, but a half-cascade setup
    would return {"llm": ..., "tts": ...} from here and agent.py would not
    change. Callers stay unaware of which shape they got.
    """
    model = require_env("GEMINI_MODEL")
    # How many tokens the model spends per video frame: 70 at the default (and
    # at MEDIA_RESOLUTION_MEDIUM, measured identical), 280 at
    # MEDIA_RESOLUTION_HIGH. The frame is uploaded at the same pixel size
    # either way. Unset means the API default. Env, so it can be A/B'd.
    resolution = os.environ.get("GEMINI_MEDIA_RESOLUTION")
    logger.info("session model: %s media_resolution=%s", model, resolution or "default")

    return {
        "llm": google.realtime.RealtimeModel(
            model=model,
            api_key=require_env("GOOGLE_API_KEY"),
            voice=os.environ.get("GEMINI_VOICE", "Puck"),
            image_encode_options=IMAGE_ENCODE_OPTIONS,
            **({"media_resolution": types.MediaResolution(resolution)} if resolution else {}),
        )
    }
