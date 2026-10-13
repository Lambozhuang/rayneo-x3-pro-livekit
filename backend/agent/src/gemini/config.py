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
# the cropped square (sampler.py), so this only has to leave them alone: no
# resizing (the plugin's default would squeeze them into 1024x1024 at JPEG
# quality 75, and a ResizeOptions scales a smaller frame up). How many tokens
# the model spends on a frame is media_resolution's business.
IMAGE_ENCODE_OPTIONS = images.EncodeOptions(format="JPEG", quality=85, resize_options=None)


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
    # MEDIA_RESOLUTION_LOW / MEDIUM (also 70) / HIGH (280, the most the Live
    # API gives a frame). At 70 the model cannot count studs; at 280 it reads
    # colours and large shapes and still misreads a brick's length.
    media_resolution: str | None
    # A sliding window over the model's context. Google cuts an audio-and-video
    # session off at two minutes unless compression is configured, so it is
    # always configured; where it bites is the question. The window drops the
    # oldest turns once `trigger` tokens are reached, down to `target`. The
    # defaults sit above what a trial uses (three minutes at one frame a second
    # is about 20k tokens at the default resolution, about 58k at HIGH), so a
    # trial keeps its whole call in context; the model's time to first audio
    # then grows with the call, which the `model:` lines show. None turns
    # compression off.
    context_trigger: int | None
    context_target: int
    # BCP-47 code the wearer's audio is transcribed in, for the `user:` lines of
    # the log. Left to itself the transcription guesses the language per
    # utterance and writes English speech down as Spanish or Japanese. It does
    # not touch the model's own speech; the prompt pins that.
    transcript_language: str
    # Background reasoning on gemini-3.8-live-extended-thinking: low, medium or
    # high. That model reasons while it streams audio and takes this level;
    # gemini-3.8-live has no level to set. Required with the one, refused with
    # the other, so a run's conditions are never implied.
    thinking_level: str | None

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
            transcript_language=os.environ.get("GEMINI_TRANSCRIPT_LANGUAGE", "en-US"),
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
        logger.info("session model: %s thinking=%s voice=%s video_fps=%s side=%d media_resolution=%s "
                    "context_compression=%s", s.model, s.thinking_level or "none", s.voice, s.video_fps, s.side,
                    s.media_resolution or "default", s.context_trigger or "off")
        return s

    def experiment_line(self, guide: str) -> str:
        """Every switch of this run on one log line, for the analysis later."""
        knobs = " ".join(f"{f.name}={getattr(self, f.name)}" for f in fields(self))
        return f"experiment: backend=gemini guide={guide} {knobs}"


def build_live_model(settings: Settings) -> google.realtime.RealtimeModel:
    """The model for AgentSession(llm=). The instructions go on the Agent. Tools
    are left at the model's defaults: on the 3.8 Live models they run in the
    background (NON_BLOCKING) and their results are taken up when the model is
    idle. Proactive audio is always on, so the model may decide a stray sound
    needs no answer. The extended-thinking model gets its thinking level."""
    kw = {}
    if settings.thinking_level:
        kw["thinking_config"] = types.ThinkingConfig(thinking_level=types.ThinkingLevel(settings.thinking_level.upper()))
    if settings.media_resolution:
        kw["media_resolution"] = types.MediaResolution(settings.media_resolution)
    if settings.context_trigger is not None:
        kw["context_window_compression"] = types.ContextWindowCompressionConfig(
            trigger_tokens=settings.context_trigger,
            sliding_window=types.SlidingWindow(target_tokens=settings.context_target),
        )
    return google.realtime.RealtimeModel(
        model=settings.model,
        voice=settings.voice,
        image_encode_options=IMAGE_ENCODE_OPTIONS,
        input_audio_transcription=types.AudioTranscriptionConfig(language_codes=[settings.transcript_language]),
        **kw,
    )
