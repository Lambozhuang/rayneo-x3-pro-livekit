"""Keep copies of the frames the model is shown, for looking at with human eyes.

Enabled by FRAME_DUMP_DIR; agent.py never constructs this when it is unset.
Each frame the sampler lets through is written twice: `-full.jpg` is the frame
as it arrived from the glasses (no resize, high JPEG quality), `-sent.jpg` is
what the Gemini plugin actually encodes and uploads (its own resize and
quality). Comparing the two is how you tell a capture problem (blur, distance,
a sideways sensor) from a resolution problem, and `-full.jpg` is the input for
inspect_frame.py.
"""

from __future__ import annotations

import logging
import os
import time

from livekit import rtc
from livekit.agents.utils import images
from livekit.agents.voice import AgentSession, VoiceActivityVideoSampler
from livekit.plugins.google.realtime.realtime_api import DEFAULT_IMAGE_ENCODE_OPTIONS

logger = logging.getLogger("rayneo-agent.framedump")

FULL_QUALITY = images.EncodeOptions(format="JPEG", quality=95)


class DumpingSampler:
    """The default sampler, plus a side effect: frames it keeps also land on disk.

    Sampling decisions are delegated unchanged, so what gets dumped is exactly
    the set of frames the model receives, at the same moments. The write is
    synchronous on the event loop; at one frame a second that is fine for a
    debugging switch and would not be for production, which is why the switch
    exists.
    """

    def __init__(self, directory: str, limit: int) -> None:
        self._inner = VoiceActivityVideoSampler()
        self._dir = directory
        self._limit = limit
        self._count = 0
        os.makedirs(directory, exist_ok=True)
        logger.info("dumping up to %d sampled frames to %s", limit, directory)

    def __call__(self, frame: rtc.VideoFrame, session: AgentSession) -> bool:
        keep = self._inner(frame, session)
        if keep and self._count < self._limit:
            self._count += 1
            stem = os.path.join(self._dir, f"{time.strftime('%H%M%S')}-{self._count:03d}")
            with open(stem + "-full.jpg", "wb") as f:
                f.write(images.encode(frame, FULL_QUALITY))
            with open(stem + "-sent.jpg", "wb") as f:
                f.write(images.encode(frame, DEFAULT_IMAGE_ENCODE_OPTIONS))
            logger.info("frame %d: %dx%d -> %s", self._count, frame.width, frame.height, stem)
        return keep
