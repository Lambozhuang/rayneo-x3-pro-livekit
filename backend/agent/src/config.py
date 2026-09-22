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


def video_fps() -> tuple[float, float]:
    """(speaking, silent) frames per second for the camera sampler; see sampler.py."""
    return (
        float(os.environ.get("VIDEO_SPEAKING_FPS", "0.5")),
        float(os.environ.get("VIDEO_SILENT_FPS", "0")),
    )


def language() -> str:
    """The language the agent speaks, whatever it hears. Gemini's native-audio
    models pick a language on their own and switch mid-conversation when the
    input sounds foreign (a cough transcribed as German was enough), and the
    voice changes with it. Pinning it in the prompt is Google's recommended
    fix."""
    return os.environ.get("AGENT_LANGUAGE", "English")


def _context_compression() -> dict[str, Any]:
    """A sliding window over the model's context. Every frame and every word of
    a Live session stays in context and is re-read on every turn; measured on
    gemini-3.8-live, a five-minute call grew to 50k input tokens a turn and
    the model's time to first audio from 2 s to 9 s. The window drops the
    oldest turns once `trigger` is reached, down to `target`. Recent frames,
    which are the ones that matter, survive; the greeting does not need to.
    `GEMINI_CONTEXT_TRIGGER_TOKENS=off` disables it."""
    trigger = os.environ.get("GEMINI_CONTEXT_TRIGGER_TOKENS", "24000")
    if trigger.lower() == "off":
        return {}
    target = int(os.environ.get("GEMINI_CONTEXT_TARGET_TOKENS", "12000"))
    return {
        "context_window_compression": types.ContextWindowCompressionConfig(
            trigger_tokens=int(trigger),
            sliding_window=types.SlidingWindow(target_tokens=target),
        )
    }


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
    compression = _context_compression()
    # Tools run in the background by default: the model keeps talking while a
    # tool runs ("let me have a look") and takes up the result once it has
    # finished speaking (WHEN_IDLE). Gemini's own default is BLOCKING: silence
    # until the tool returns, then a second round trip for the reply, which
    # made every step change a ~3 s pause. `blocking` restores that for A/B.
    tool_behavior = types.Behavior[os.environ.get("GEMINI_TOOL_BEHAVIOR", "non_blocking").upper()]
    logger.info(
        "session model: %s media_resolution=%s context_compression=%s tools=%s",
        model, resolution or "default",
        compression["context_window_compression"].trigger_tokens if compression else "off",
        tool_behavior.value.lower(),
    )

    return {
        "llm": google.realtime.RealtimeModel(
            model=model,
            api_key=require_env("GOOGLE_API_KEY"),
            voice=os.environ.get("GEMINI_VOICE", "Puck"),
            image_encode_options=IMAGE_ENCODE_OPTIONS,
            **({"media_resolution": types.MediaResolution(resolution)} if resolution else {}),
            **compression,
            tool_behavior=tool_behavior,
            tool_response_scheduling=types.FunctionResponseScheduling.WHEN_IDLE,
        )
    }
