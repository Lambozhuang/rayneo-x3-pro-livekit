"""Which camera frames the model gets: one every 1/fps seconds, whoever is talking.

An AgentSession `video_sampler`: the framework calls it with every frame from
the glasses (~15 a second) and forwards to the model the ones it says yes to.
A fixed rate is the simplest thing that works; every frame the model sees stays
in its context for the rest of the call, so GEMINI_VIDEO_FPS is the cost knob
(config.py). The SDK's own sampler is not used because its "while the user
speaks" rate needs a local VAD to mean that, which this path does without.

Every frame passed is also saved into the call's record, encoded as the plugin
encodes it (config.IMAGE_ENCODE_OPTIONS), so a run can be judged afterwards
from exactly what the model saw. Encoding a 1080p JPEG takes ~100 ms, which
on the event loop would be 100 ms of audio and turn handling delayed, so it
goes to one worker thread, in order; the sampler returns at once.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from livekit import rtc
from livekit.agents.utils import images
from livekit.agents.voice import AgentSession

from gemini.config import IMAGE_ENCODE_OPTIONS
from runlog import RunLog

logger = logging.getLogger("rayneo-agent.camera")


class FixedRateSampler:
    def __init__(self, fps: float, record: RunLog, step: Callable[[], int]) -> None:
        self._period = 1.0 / fps
        self._record = record
        self._step = step  # the current step number (1-based) when a frame goes, for the photo's name
        self._last = 0.0
        self._encoder = ThreadPoolExecutor(max_workers=1, thread_name_prefix="frame-encode")
        self.count = 0  # frames seen, for the log: zero means the video path is broken
        self.sent = 0  # frames the model got

    def __call__(self, frame: rtc.VideoFrame, session: AgentSession) -> bool:
        self.count += 1
        if self.count == 1:
            logger.info("camera: first frame %dx%d", frame.width, frame.height)
            self._record.event("camera", first_frame=f"{frame.width}x{frame.height}")
        now = time.monotonic()
        if now - self._last < self._period:
            return False
        self._last = now
        self.sent += 1
        self._encoder.submit(self._save, frame, self.sent, self.count, self._step())
        return True

    def _save(self, frame: rtc.VideoFrame, n: int, seq: int, step: int) -> None:
        try:
            jpeg = images.encode(frame, IMAGE_ENCODE_OPTIONS)
        except Exception:
            logger.exception("frame %d: could not encode", n)
            return
        saved = self._record.photo(jpeg, f"frame{n}-s{step}")
        self._record.event("frame", n=n, frame=seq, step=step, size=f"{frame.width}x{frame.height}", photo=saved,
                           photo_kb=len(jpeg) // 1024)
