"""Environment configuration for the GPT path.

Three OpenAI models, all named in .env so they can be changed without a
rebuild: the voice model (GPT-Live, priced by the second), the backend model it
delegates reasoning and tool calls to, and the vision model that judges camera
frames in a separate Responses call. The backend never sees a picture. The
experiment switches are logged as
one `experiment:` line at the start of every call, so a run's conditions can be
read back from its log.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, fields

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
    check_detail: str
    # The camera loop (watch.py): seconds to wait between one verdict and the
    # next frame (0 = back to back), and how many consecutive frames must agree
    # before a change is announced.
    watch_gap: float
    watch_confirm: int

    @classmethod
    def from_env(cls) -> Settings:
        s = cls(
            live_model=require_env("OPENAI_LIVE_MODEL"),
            voice=os.environ.get("OPENAI_VOICE", "marin"),
            backend_model=require_env("OPENAI_BACKEND_MODEL"),
            backend_effort=os.environ.get("OPENAI_BACKEND_EFFORT", "low"),
            check_model=require_env("OPENAI_CHECK_MODEL"),
            # Measured on the 2026-09-22/23 frames: `none` judges as well as
            # `low` in a third of the time; `medium` made the models doubt
            # more, not see more. See vision.py.
            check_effort=os.environ.get("OPENAI_CHECK_EFFORT", "none"),
            check_detail=os.environ.get("OPENAI_CHECK_DETAIL", "high"),
            watch_gap=float(os.environ.get("GPT_WATCH_GAP", "0")),
            watch_confirm=int(os.environ.get("GPT_WATCH_CONFIRM", "2")),
        )
        require_env("OPENAI_API_KEY")  # the SDK and the plugin read it themselves
        logger.info(
            "session model: %s voice=%s backend=%s effort=%s vision=%s effort=%s detail=%s",
            s.live_model, s.voice, s.backend_model, s.backend_effort, s.check_model, s.check_effort, s.check_detail,
        )
        return s

    def experiment_line(self, guide: str) -> str:
        """Every switch of this run on one log line, for the analysis later."""
        knobs = " ".join(f"{f.name}={getattr(self, f.name)}" for f in fields(self))
        return f"experiment: backend=openai guide={guide} {knobs}"


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
