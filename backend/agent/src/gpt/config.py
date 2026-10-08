"""Environment configuration for the GPT path.

Everything named in .env so it can be changed without a rebuild: the voice
model (GPT-Live, priced by the second) and the brain, the vision model that
answers what the voice delegates (one Responses call per delegation, priced by
the token). The experiment switches are logged as one `experiment:` line at the
start of every call, so a run's conditions can be read back from its log.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, fields

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


@dataclass(frozen=True)
class Settings:
    live_model: str
    voice: str
    # The brain (brain.py): the vision model that answers what GPT-Live delegates, its reasoning effort, the
    # image detail it is sent, and the longest side in px the camera frame is scaled to.
    brain_model: str
    brain_effort: str
    brain_detail: str
    brain_side: int

    @classmethod
    def from_env(cls) -> Settings:
        s = cls(
            live_model=require_env("OPENAI_LIVE_MODEL"),
            voice=os.environ.get("OPENAI_VOICE", "marin"),
            brain_model=require_env("OPENAI_BRAIN_MODEL"),
            brain_effort=os.environ.get("OPENAI_BRAIN_EFFORT", "none"),
            brain_detail=os.environ.get("OPENAI_BRAIN_DETAIL", "high"),
            brain_side=int(os.environ.get("OPENAI_BRAIN_SIDE", "1024")),
        )
        require_env("OPENAI_API_KEY")  # the SDK and the plugin read it themselves
        logger.info("session model: %s voice=%s brain=%s effort=%s detail=%s side=%d", s.live_model, s.voice,
                    s.brain_model, s.brain_effort, s.brain_detail, s.brain_side)
        return s

    def experiment_line(self, guide: str) -> str:
        """Every switch of this run on one log line, for the analysis later."""
        knobs = " ".join(f"{f.name}={getattr(self, f.name)}" for f in fields(self))
        return f"experiment: backend=openai guide={guide} {knobs}"


def build_live_model(settings: Settings) -> GPTLiveModel:
    """The speech model for AgentSession(llm=). The persona goes on the Agent. Client delegation: what the
    voice hands over comes to this process (brain.py), not to a backend model."""
    return GPTLiveModel(model=settings.live_model, voice=settings.voice, delegation="client")


def openai_client() -> AsyncOpenAI:
    return AsyncOpenAI()
