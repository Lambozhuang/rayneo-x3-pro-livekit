"""Environment configuration for the OpenAI Realtime path.

One model hears, sees, speaks and keeps the progress, so there is one model to
configure: which OpenAI Realtime model, how often it is shown a camera frame
while the wearer speaks and while they do not, and the side the frame is
scaled to. The switches are logged as one `experiment:` line at the start of
every call, so a run's conditions can be read back from its log.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, fields

from livekit.plugins import openai

from env import require_env

logger = logging.getLogger("rayneo-agent.config")

# The voice the GPT path speaks in by default, so a wearer hears the same voice on both OpenAI paths.
VOICE = "marin"


@dataclass(frozen=True)
class Settings:
    model: str
    # Camera frames a second shown to the model while the wearer speaks and while they do not (sampler.py); the
    # framework's own sampler uses 1 and 0.3. Every frame stays in the model's context, so these are the cost knobs.
    speaking_fps: float
    silent_fps: float
    # The longest side in px of the bottom square cut from each frame (sampler.py, frames.bottom_square).
    side: int

    @classmethod
    def from_env(cls) -> Settings:
        s = cls(
            model=require_env("REALTIME_MODEL"),
            speaking_fps=float(os.environ.get("REALTIME_SPEAKING_FPS", "1")),
            silent_fps=float(os.environ.get("REALTIME_SILENT_FPS", "0.3")),
            side=int(os.environ.get("REALTIME_SIDE", "1080")),
        )
        require_env("OPENAI_API_KEY")  # the plugin reads it itself
        if s.speaking_fps <= 0 or s.silent_fps <= 0:
            raise RuntimeError(f"REALTIME_SPEAKING_FPS={s.speaking_fps} REALTIME_SILENT_FPS={s.silent_fps}: the model "
                               "must get frames; use rates above 0")
        logger.info("session model: %s voice=%s speaking_fps=%s silent_fps=%s side=%d", s.model, VOICE,
                    s.speaking_fps, s.silent_fps, s.side)
        return s

    def experiment_line(self, guide: str) -> str:
        """Every switch of this run on one log line, for the analysis later."""
        knobs = " ".join(f"{f.name}={getattr(self, f.name)}" for f in fields(self))
        return f"experiment: backend=realtime guide={guide} {knobs}"


def build_live_model(settings: Settings) -> openai.realtime.RealtimeModel:
    """The model for AgentSession(llm=). The instructions and the tool go on the Agent. Turn detection, input
    transcription and reasoning are the plugin's and the API's defaults."""
    return openai.realtime.RealtimeModel(model=settings.model, voice=VOICE)
