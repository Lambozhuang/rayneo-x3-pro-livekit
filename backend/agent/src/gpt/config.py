"""Environment configuration for the GPT path.

Three OpenAI models, all named in .env so they can be changed without a
rebuild: the voice model (GPT-Live, priced by the second), the backend model it
delegates reasoning and tool calls to, and the vision model that judges camera
frames in a separate Responses call. The backend never sees a picture.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from livekit.agents.utils import images
from livekit.plugins.openai.realtime import GPTLiveModel
from openai import AsyncOpenAI

logger = logging.getLogger("rayneo-agent.config")


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Copy backend/.env.example to backend/.env and fill it in.")
    return value


def language() -> str:
    """The language the agent speaks, whatever it hears."""
    return os.environ.get("AGENT_LANGUAGE", "English")


# A camera frame as the vision model gets it: the captured size (the glasses
# send 1080p portrait), JPEG at a quality that keeps studs countable.
FRAME_ENCODE_OPTIONS = images.EncodeOptions(
    format="JPEG",
    quality=85,
    resize_options=images.ResizeOptions(width=1920, height=1920, strategy="scale_aspect_fit"),
)


@dataclass(frozen=True)
class Settings:
    live_model: str
    voice: str
    backend_model: str
    backend_effort: str
    check_model: str
    check_effort: str

    @classmethod
    def from_env(cls) -> Settings:
        s = cls(
            live_model=require_env("OPENAI_LIVE_MODEL"),
            voice=os.environ.get("OPENAI_VOICE", "marin"),
            backend_model=require_env("OPENAI_BACKEND_MODEL"),
            backend_effort=os.environ.get("OPENAI_BACKEND_EFFORT", "low"),
            check_model=require_env("OPENAI_CHECK_MODEL"),
            # Measured on the 2026-09-22 frames: `none` and `low` judge alike
            # (13/15), `none` in 2 s against 6 s; `medium` was worse on both.
            check_effort=os.environ.get("OPENAI_CHECK_EFFORT", "none"),
        )
        require_env("OPENAI_API_KEY")  # the SDK and the plugin read it themselves
        logger.info(
            "session model: %s voice=%s backend=%s effort=%s vision=%s effort=%s",
            s.live_model, s.voice, s.backend_model, s.backend_effort, s.check_model, s.check_effort,
        )
        return s


def build_live_model(settings: Settings, backend_instructions: str) -> GPTLiveModel:
    """The speech model for AgentSession(llm=). The voice persona goes on the
    Agent; only the backend's instructions are set here."""
    return GPTLiveModel(
        model=settings.live_model,
        voice=settings.voice,
        delegation="responses",
        responses_options={
            "model": settings.backend_model,
            "instructions": backend_instructions,
            "reasoning": {"effort": settings.backend_effort},
        },
    )


def openai_client() -> AsyncOpenAI:
    return AsyncOpenAI()
