"""Environment configuration for the GPT path.

Everything named in .env so it can be changed without a rebuild: the voice
model (GPT-Live, priced by the second) and the brain, the vision model that
looks through the camera every few seconds (OpenAI or Anthropic, priced by the
token). The experiment switches are logged as one
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
    # The brain (brain.py): who serves the vision model (openai or anthropic), the model, its reasoning effort for
    # every look (none = no reasoning), the image detail (openai only), and how long one look may take before it
    # is given up.
    brain_provider: str
    brain_model: str
    brain_effort: str
    brain_detail: str
    brain_service_tier: str  # OpenAI's processing tier for the brain's calls: default, priority (steadier latency, twice the price) or flex
    brain_transport: str  # how the brain reaches OpenAI: ws (one persistent WebSocket, 0.3 s faster a look) or http
    quick_model: str  # the quick look's Decisions model (gpt/quick.py), gpt-6-luna
    quick_detail: str  # the quick look's image detail: low (512 px, 0.34 s) or high (1080 px, 0.41 s)
    quick_every: float  # seconds between quick looks; 0 turns the quick look off
    brain_timeout: float
    # The brain's looks (brain.py, watch): the side in px their frame is scaled to, and the shortest time in
    # seconds from the start of one to the start of the next. Required: they decide how many requests a call
    # makes.
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
            brain_service_tier=os.environ.get("BRAIN_SERVICE_TIER", "default"),
            brain_transport=require_env("BRAIN_TRANSPORT"),
            quick_model=require_env("BRAIN_QUICK_MODEL"),
            quick_detail=require_env("BRAIN_QUICK_DETAIL"),
            quick_every=float(require_env("BRAIN_QUICK_EVERY")),
            brain_timeout=float(os.environ.get("BRAIN_TIMEOUT", "12")),
            brain_watch_side=int(require_env("BRAIN_WATCH_SIDE")),
            brain_watch_every=float(require_env("BRAIN_WATCH_EVERY")),
        )
        require_env("OPENAI_API_KEY")  # the SDKs and the plugin read their keys themselves
        if s.brain_provider not in ("openai", "anthropic"):
            raise RuntimeError(f"BRAIN_PROVIDER={s.brain_provider!r}: must be openai or anthropic")
        if s.brain_provider == "anthropic":
            require_env("ANTHROPIC_API_KEY")
        if s.brain_service_tier not in ("default", "priority", "flex"):
            raise RuntimeError(f"BRAIN_SERVICE_TIER={s.brain_service_tier!r}: must be default, priority or flex")
        if s.brain_transport not in ("ws", "http"):
            raise RuntimeError(f"BRAIN_TRANSPORT={s.brain_transport!r}: must be ws or http")
        if s.quick_detail not in ("low", "high"):
            raise RuntimeError(f"BRAIN_QUICK_DETAIL={s.quick_detail!r}: must be low or high")
        if s.quick_every < 0:
            raise RuntimeError(f"BRAIN_QUICK_EVERY={s.quick_every}: seconds between quick looks, 0 for none")
        if s.brain_watch_side <= 0 or s.brain_watch_every <= 0:
            raise RuntimeError(f"BRAIN_WATCH_SIDE={s.brain_watch_side} BRAIN_WATCH_EVERY={s.brain_watch_every}: "
                               "use values above 0")
        logger.info("session model: %s voice=%s brain=%s/%s effort=%s detail=%s tier=%s transport=%s watch_side=%d "
                    "watch_every=%ss quick=%s/%s every %ss",
                    s.live_model, s.voice, s.brain_provider, s.brain_model, s.brain_effort, s.brain_detail,
                    s.brain_service_tier, s.brain_transport, s.brain_watch_side, s.brain_watch_every, s.quick_model,
                    s.quick_detail, s.quick_every)
        return s

    def experiment_line(self, guide: str) -> str:
        """Every switch of this run on one log line, for the analysis later."""
        knobs = " ".join(f"{f.name}={getattr(self, f.name)}" for f in fields(self))
        return f"experiment: backend=openai guide={guide} {knobs}"


def build_live_model(settings: Settings) -> GPTLiveModel:
    """The speech model for AgentSession(llm=). The persona goes on the Agent. The session needs a delegation
    target; client means a hand-over, which the persona tells the voice not to make, comes to this process, where
    brain.py closes it at once, and not to a backend model."""
    return GPTLiveModel(model=settings.live_model, voice=settings.voice, delegation="client")
