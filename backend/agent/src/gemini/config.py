"""Environment configuration for the Gemini path.

One model does everything, so there is one model to configure: which Gemini
Live model and voice, how many camera frames a second it is shown, how many
tokens it spends on each, and the sliding window over its context. The switches
are logged as one `experiment:` line at the start of every call, like the GPT
path's, so a run's conditions can be read back from its log.
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

# How a camera frame is encoded before upload. The plugin's default squeezes
# every frame into 1024x1024 at JPEG quality 75, which threw away most of a
# 1080p capture before Gemini ever saw it. Send frames at their captured size
# instead; how many tokens the model spends on them is media_resolution's
# business. The frames saved in the call record are encoded with these options
# too, so they are what the model saw.
IMAGE_ENCODE_OPTIONS = images.EncodeOptions(
    format="JPEG",
    quality=85,
    resize_options=images.ResizeOptions(width=1920, height=1920, strategy="scale_aspect_fit"),
)


@dataclass(frozen=True)
class Settings:
    model: str
    voice: str
    # Camera frames a second shown to the model (sampler.py). Every frame stays
    # in the model's context for the rest of the call, so this is the cost knob.
    video_fps: float
    # Token budget per frame: the API default, or MEDIA_RESOLUTION_LOW / MEDIUM
    # / HIGH. Gemini 3 models default to a larger budget than 2.5 did.
    media_resolution: str | None
    # A sliding window over the model's context: Live keeps every frame and
    # every word and re-reads them on every turn; measured on gemini-3.8-live,
    # a five-minute call grew to 50k input tokens a turn and the time to first
    # audio from 2 s to 9 s. The window drops the oldest turns once `trigger`
    # tokens are reached, down to `target`. None turns it off.
    context_trigger: int | None
    context_target: int

    @classmethod
    def from_env(cls) -> Settings:
        trigger = os.environ.get("GEMINI_CONTEXT_TRIGGER_TOKENS", "24000")
        s = cls(
            model=require_env("GEMINI_MODEL"),
            voice=os.environ.get("GEMINI_VOICE", "Puck"),
            video_fps=float(os.environ.get("GEMINI_VIDEO_FPS", "1")),
            media_resolution=os.environ.get("GEMINI_MEDIA_RESOLUTION") or None,
            context_trigger=None if trigger.lower() == "off" else int(trigger),
            context_target=int(os.environ.get("GEMINI_CONTEXT_TARGET_TOKENS", "12000")),
        )
        require_env("GOOGLE_API_KEY")  # the plugin reads it itself
        if s.video_fps <= 0:
            raise RuntimeError(f"GEMINI_VIDEO_FPS={s.video_fps}: the model must get frames; use a rate above 0")
        logger.info("session model: %s voice=%s video_fps=%s media_resolution=%s context_compression=%s", s.model,
                    s.voice, s.video_fps, s.media_resolution or "default", s.context_trigger or "off")
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
