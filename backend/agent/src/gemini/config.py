"""Environment configuration for the Gemini path.

One model does everything, so there is one model to configure: which Gemini
Live model and voice, how many camera frames a second it is shown, how many
tokens it spends on each, and the sliding window over its context. The switches
are logged as one `experiment:` line at the start of every call, so a run's
conditions can be read back from its log.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, fields

from google.genai import types
from livekit.agents.utils import images
from livekit.plugins import google

from env import require_env

logger = logging.getLogger("rayneo-agent.config")

# How the plugin encodes a frame before upload. The frames it gets are already
# the cropped square (sampler.py), so this only has to leave them alone: the
# plugin's default would squeeze them into 1024x1024 at JPEG quality 75. How
# many tokens the model spends on a frame is media_resolution's business.
IMAGE_ENCODE_OPTIONS = images.EncodeOptions(
    format="JPEG",
    quality=85,
    resize_options=images.ResizeOptions(width=4096, height=4096, strategy="scale_aspect_fit"),
)


@dataclass(frozen=True)
class Settings:
    model: str
    voice: str
    # Camera frames a second shown to the model (sampler.py). Every frame stays
    # in the model's context for the rest of the call, so this is the cost knob.
    video_fps: float
    # The side in px of the square cut from each frame (sampler.py).
    side: int
    # Token budget per frame: the API default (70 tokens on Gemini 3 models), or
    # MEDIA_RESOLUTION_LOW / MEDIUM (also 70) / HIGH (280).
    media_resolution: str | None
    # A sliding window over the model's context. Google cuts an audio-and-video
    # session off at two minutes unless compression is configured, so it is
    # always configured; where it bites is the question. The window drops the
    # oldest turns once `trigger` tokens are reached, down to `target`. The
    # defaults sit far above what a trial uses (about 20k tokens for three
    # minutes at one frame a second), so a trial keeps its whole call in
    # context; the model's time to first audio then grows with the call, which
    # the `model:` lines show. None turns compression off.
    context_trigger: int | None
    context_target: int

    @classmethod
    def from_env(cls) -> Settings:
        trigger = os.environ.get("GEMINI_CONTEXT_TRIGGER_TOKENS", "100000")
        s = cls(
            model=require_env("GEMINI_MODEL"),
            voice=os.environ.get("GEMINI_VOICE", "Puck"),
            video_fps=float(os.environ.get("GEMINI_VIDEO_FPS", "1")),
            side=int(os.environ.get("GEMINI_SIDE", "1080")),
            media_resolution=os.environ.get("GEMINI_MEDIA_RESOLUTION") or None,
            context_trigger=None if trigger.lower() == "off" else int(trigger),
            context_target=int(os.environ.get("GEMINI_CONTEXT_TARGET_TOKENS", "50000")),
        )
        require_env("GOOGLE_API_KEY")  # the plugin reads it itself
        if s.video_fps <= 0:
            raise RuntimeError(f"GEMINI_VIDEO_FPS={s.video_fps}: the model must get frames; use a rate above 0")
        logger.info("session model: %s voice=%s video_fps=%s side=%d media_resolution=%s context_compression=%s",
                    s.model, s.voice, s.video_fps, s.side, s.media_resolution or "default", s.context_trigger or "off")
        return s

    def experiment_line(self, guide: str) -> str:
        """Every switch of this run on one log line, for the analysis later."""
        knobs = " ".join(f"{f.name}={getattr(self, f.name)}" for f in fields(self))
        return f"experiment: backend=gemini guide={guide} {knobs}"


def build_live_model(settings: Settings) -> google.realtime.RealtimeModel:
    """The model for AgentSession(llm=). The instructions go on the Agent. Tools
    are left at the model's defaults: on gemini-3.8-live they run in the
    background (NON_BLOCKING) and their results are taken up when the model is
    idle; it has no thinking level to set, and proactive audio is always on, so
    the model may decide a stray sound needs no answer."""
    kw = {}
    if settings.media_resolution:
        kw["media_resolution"] = types.MediaResolution(settings.media_resolution)
    if settings.context_trigger is not None:
        kw["context_window_compression"] = types.ContextWindowCompressionConfig(
            trigger_tokens=settings.context_trigger,
            sliding_window=types.SlidingWindow(target_tokens=settings.context_target),
        )
    return google.realtime.RealtimeModel(
        model=settings.model, voice=settings.voice, image_encode_options=IMAGE_ENCODE_OPTIONS, **kw
    )
