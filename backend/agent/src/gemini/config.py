"""Environment configuration for the Gemini path.

One model does everything, so there is one model to configure: which Gemini
Live model, how many camera frames a second it is shown, how many
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
# the cropped square (sampler.py), so this only has to leave them alone: no
# resizing (the plugin's default would squeeze them into 1024x1024 at JPEG
# quality 75, and a ResizeOptions scales a smaller frame up). How many tokens
# the model spends on a frame is media_resolution's business.
IMAGE_ENCODE_OPTIONS = images.EncodeOptions(format="JPEG", quality=85, resize_options=None)

# The voice the glasses-only prototype (rayneo-x3-pro-gemini-live) speaks in, so the two sound the same.
VOICE = "Kore"

# Both sides are transcribed for the log in US English. Left to itself the transcription guesses the language per
# utterance and writes English speech down as Spanish or Japanese; the model answers in English (the prompt).
TRANSCRIPTION = types.AudioTranscriptionConfig(language_codes=["en-US"])


@dataclass(frozen=True)
class Settings:
    model: str
    # Camera frames a second shown to the model (sampler.py). Every frame stays
    # in the model's context for the rest of the call, so this is the cost knob.
    video_fps: float
    # The side in px of the square cut from the middle of each frame (sampler.py); Google recommends 768.
    side: int
    # Token budget per frame: the API default (70 tokens on Gemini 3 models), or
    # MEDIA_RESOLUTION_LOW / MEDIUM (also 70) / HIGH (280, the most the Live
    # API gives a frame). At 280 the model reads colours and large shapes but
    # not small detail.
    media_resolution: str | None
    # Background reasoning on gemini-3.8-live-extended-thinking: low, medium or
    # high. That model reasons while it streams audio and takes this level;
    # gemini-3.8-live has no level to set. Required with the one, refused with
    # the other, so a run's conditions are never implied.
    thinking_level: str | None

    @classmethod
    def from_env(cls) -> Settings:
        s = cls(
            model=require_env("GEMINI_MODEL"),
            video_fps=float(os.environ.get("GEMINI_VIDEO_FPS", "1")),
            side=int(os.environ.get("GEMINI_SIDE", "768")),
            media_resolution=os.environ.get("GEMINI_MEDIA_RESOLUTION") or None,
            thinking_level=os.environ.get("GEMINI_THINKING_LEVEL") or None,
        )
        require_env("GOOGLE_API_KEY")  # the plugin reads it itself
        if s.video_fps <= 0:
            raise RuntimeError(f"GEMINI_VIDEO_FPS={s.video_fps}: the model must get frames; use a rate above 0")
        thinking_model = "thinking" in s.model
        if thinking_model and s.thinking_level not in ("low", "medium", "high"):
            raise RuntimeError(f"GEMINI_THINKING_LEVEL={s.thinking_level!r}: {s.model} needs low, medium or high")
        if s.thinking_level and not thinking_model:
            raise RuntimeError(f"GEMINI_THINKING_LEVEL is set but {s.model} has no thinking level; unset it")
        logger.info("session model: %s thinking=%s voice=%s video_fps=%s side=%d media_resolution=%s", s.model,
                    s.thinking_level or "none", VOICE, s.video_fps, s.side, s.media_resolution or "default")
        return s

    def experiment_line(self) -> str:
        """Every switch of this run on one log line, for the analysis later."""
        knobs = " ".join(f"{f.name}={getattr(self, f.name)}" for f in fields(self))
        return f"experiment: backend=gemini {knobs}"


def build_live_model(settings: Settings) -> google.realtime.RealtimeModel:
    """The model for AgentSession(llm=). The instructions go on the Agent.
    The session is set up as the glasses-only prototype sets up its own: the
    voice Kore and a sliding window over the context at the API's own trigger
    and target; both sides are transcribed in US English.
    Google cuts an audio-and-video session off at two minutes unless
    compression is configured, so it always is. Proactive audio is always on,
    so the model may decide a stray sound needs no answer. The
    extended-thinking model gets its thinking level."""
    kw = {}
    if settings.thinking_level:
        kw["thinking_config"] = types.ThinkingConfig(thinking_level=types.ThinkingLevel(settings.thinking_level.upper()))
    if settings.media_resolution:
        kw["media_resolution"] = types.MediaResolution(settings.media_resolution)
    return google.realtime.RealtimeModel(
        model=settings.model,
        voice=VOICE,
        image_encode_options=IMAGE_ENCODE_OPTIONS,
        input_audio_transcription=TRANSCRIPTION,
        output_audio_transcription=TRANSCRIPTION,
        context_window_compression=types.ContextWindowCompressionConfig(sliding_window=types.SlidingWindow()),
        **kw,
    )
