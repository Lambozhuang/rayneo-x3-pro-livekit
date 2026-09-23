"""Keep copies of the frames the model is shown, for looking at with human eyes.

Enabled by FRAME_DUMP_DIR; agent.py never constructs this when it is unset.
Each call gets its own timestamped subdirectory; old ones are never removed.
Each frame the sampler lets through is written twice: `-full.jpg` is the frame
as it arrived from the glasses (no resize, high JPEG quality), `-sent.jpg` is
what the Gemini plugin actually encodes and uploads (config.py's
IMAGE_ENCODE_OPTIONS). Comparing the two is how you tell a capture problem (blur, distance,
a sideways sensor) from a resolution problem, and `-full.jpg` is the input for
inspect_frame.py.
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

from livekit import rtc
from livekit.agents.utils import images
from livekit.agents.voice import AgentSession

from gemini.config import IMAGE_ENCODE_OPTIONS

logger = logging.getLogger("rayneo-agent.framedump")

FULL_QUALITY = images.EncodeOptions(format="JPEG", quality=95)


class DumpingSampler:
    """A sampler, plus a side effect: frames it keeps also land on disk.

    Sampling decisions are delegated unchanged, so what gets dumped is exactly
    the set of frames the model receives, at the same moments. Encoding two
    JPEGs of a 1080p frame takes ~100 ms, which on the event loop is 100 ms of
    audio and turn handling delayed (the SDK now warns about exactly that), so
    the work goes to one worker thread, in order, and the sampler returns at
    once.
    """

    def __init__(self, inner, directory: str, limit: int) -> None:
        self._inner = inner
        # One subdirectory per call, so runs never mix and nothing is ever
        # deleted; clear old ones by hand when they are no longer wanted.
        self._dir = os.path.join(directory, time.strftime("%Y%m%d-%H%M%S"))
        self._limit = limit
        self._count = 0
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="framedump")
        os.makedirs(self._dir, exist_ok=True)
        logger.info("dumping up to %d sampled frames to %s", limit, self._dir)

    def __call__(self, frame: rtc.VideoFrame, session: AgentSession) -> bool:
        keep = self._inner(frame, session)
        if keep and self._count < self._limit:
            self._count += 1
            stem = os.path.join(self._dir, f"{self._count:03d}")
            self._writer.submit(self._write, frame, stem, self._count)
        return keep

    @staticmethod
    def _write(frame: rtc.VideoFrame, stem: str, n: int) -> None:
        try:
            with open(stem + "-full.jpg", "wb") as f:
                f.write(images.encode(frame, FULL_QUALITY))
            with open(stem + "-sent.jpg", "wb") as f:
                f.write(images.encode(frame, IMAGE_ENCODE_OPTIONS))
            logger.info("frame %d: %dx%d -> %s", n, frame.width, frame.height, stem)
        except Exception:
            logger.exception("frame %d: could not write %s", n, stem)
