"""Environment configuration for the GPT path.

Everything named in .env so it can be changed without a rebuild: the voice
model (GPT-Live, priced by the second) and the brain, the vision model that
answers what the voice delegates and looks by itself in between (OpenAI or
Anthropic, priced by the token). The experiment switches are logged as one
`experiment:` line at the start of every call, so a run's conditions can be
read back from its log.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, fields

from livekit.plugins.openai.realtime import GPTLiveModel

from env import require_env

logger = logging.getLogger("rayneo-agent.config")


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
    # The brain's own looks between delegations (brain.py, watch): the side in px their frame is scaled to, and
    # the shortest time in seconds from the start of one to the start of the next. Required: they decide how
    # many requests a call makes.
    brain_watch_side: int
    brain_watch_every: float

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
            brain_watch_side=int(require_env("BRAIN_WATCH_SIDE")),
            brain_watch_every=float(require_env("BRAIN_WATCH_EVERY")),
        )
        require_env("OPENAI_API_KEY")  # the SDKs and the plugin read their keys themselves
        if s.brain_provider not in ("openai", "anthropic"):
            raise RuntimeError(f"BRAIN_PROVIDER={s.brain_provider!r}: must be openai or anthropic")
        if s.brain_provider == "anthropic":
            require_env("ANTHROPIC_API_KEY")
        if s.brain_watch_side <= 0 or s.brain_watch_every <= 0:
            raise RuntimeError(f"BRAIN_WATCH_SIDE={s.brain_watch_side} BRAIN_WATCH_EVERY={s.brain_watch_every}: "
                               "use values above 0")
        logger.info("session model: %s voice=%s brain=%s/%s effort=%s detail=%s side=%d watch_side=%d "
                    "watch_every=%ss", s.live_model, s.voice, s.brain_provider, s.brain_model, s.brain_effort,
                    s.brain_detail, s.brain_side, s.brain_watch_side, s.brain_watch_every)
        return s

    def experiment_line(self, guide: str) -> str:
        """Every switch of this run on one log line, for the analysis later."""
        knobs = " ".join(f"{f.name}={getattr(self, f.name)}" for f in fields(self))
        return f"experiment: backend=openai guide={guide} {knobs}"


def build_live_model(settings: Settings) -> GPTLiveModel:
    """The speech model for AgentSession(llm=). The persona goes on the Agent. Client delegation: what the
    voice hands over comes to this process (brain.py), not to a backend model."""
    return GPTLiveModel(model=settings.live_model, voice=settings.voice, delegation="client")
