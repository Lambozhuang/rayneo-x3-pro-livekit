"""Environment configuration for the GPT path.

Everything named in .env so it can be changed without a rebuild: the voice
model (GPT-Live, priced by the second) and the brain, the vision model that
answers what the voice delegates (one call per delegation, OpenAI or
Anthropic, priced by the token). The experiment switches are logged as one
`experiment:` line at the start of every call, so a run's conditions can be
read back from its log.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, fields

from livekit.plugins.openai.realtime import GPTLiveModel

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
    # The brain (brain.py): who serves the vision model that answers what GPT-Live delegates (openai or
    # anthropic), the model, its reasoning effort (none = no reasoning), the image detail (openai only), and
    # the longest side in px the camera frame is scaled to, and how long an answer may take.
    brain_provider: str
    brain_model: str
    brain_effort: str
    brain_detail: str
    brain_side: int
    brain_timeout: float  # seconds for frame + model call before the wearer is asked to repeat

    @classmethod
    def from_env(cls) -> Settings:
        s = cls(
            live_model=require_env("OPENAI_LIVE_MODEL"),
            voice=os.environ.get("OPENAI_VOICE", "marin"),
            brain_provider=os.environ.get("BRAIN_PROVIDER", "openai"),
            brain_model=require_env("BRAIN_MODEL"),
            brain_effort=os.environ.get("BRAIN_EFFORT", "none"),
            brain_detail=os.environ.get("BRAIN_DETAIL", "high"),
            brain_side=int(os.environ.get("BRAIN_SIDE", "1080")),
            brain_timeout=float(os.environ.get("BRAIN_TIMEOUT", "12")),
        )
        require_env("OPENAI_API_KEY")  # the SDKs and the plugin read their keys themselves
        if s.brain_provider not in ("openai", "anthropic"):
            raise RuntimeError(f"BRAIN_PROVIDER={s.brain_provider!r}: must be openai or anthropic")
        if s.brain_provider == "anthropic":
            require_env("ANTHROPIC_API_KEY")
        logger.info("session model: %s voice=%s brain=%s/%s effort=%s detail=%s side=%d", s.live_model, s.voice,
                    s.brain_provider, s.brain_model, s.brain_effort, s.brain_detail, s.brain_side)
        return s

    def experiment_line(self, guide: str) -> str:
        """Every switch of this run on one log line, for the analysis later."""
        knobs = " ".join(f"{f.name}={getattr(self, f.name)}" for f in fields(self))
        return f"experiment: backend=openai guide={guide} {knobs}"


def build_live_model(settings: Settings) -> GPTLiveModel:
    """The speech model for AgentSession(llm=). The persona goes on the Agent. Client delegation: what the
    voice hands over comes to this process (brain.py), not to a backend model."""
    return GPTLiveModel(model=settings.live_model, voice=settings.voice, delegation="client")
