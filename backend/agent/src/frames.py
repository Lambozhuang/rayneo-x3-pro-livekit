"""The camera, tapped: every frame from the glasses arrives here, none reaches the model.

`FrameTap` is an AgentSession `video_sampler` that always answers "drop", so
the framework never forwards video to the speech model, and keeps the newest
frame for the code instead: `latest` (at the glasses' ~15 a second, at most a
few tens of milliseconds old), which the brain (gpt/brain.py) takes per
delegation.
"""

from __future__ import annotations

import logging
import time

from livekit import rtc
from livekit.agents.voice import AgentSession
from PIL import Image

logger = logging.getLogger("rayneo-agent.frames")


def to_image(frame: rtc.VideoFrame) -> Image.Image:
    f = frame if frame.type == rtc.VideoBufferType.RGB24 else frame.convert(rtc.VideoBufferType.RGB24)
    return Image.frombytes("RGB", (f.width, f.height), bytes(f.data))


class FrameTap:
    def __init__(self, on_first=None) -> None:
        self._on_first = on_first  # called with the first frame, e.g. to put it in the call's record
        self.count = 0  # frames seen, for the log: zero means the video path is broken
        self.latest: rtc.VideoFrame | None = None  # the newest frame and when it came (time.monotonic())
        self.latest_at = 0.0

    def __call__(self, frame: rtc.VideoFrame, session: AgentSession) -> bool:
        self.count += 1
        self.latest, self.latest_at = frame, time.monotonic()
        if self.count == 1:
            logger.info("camera: first frame %dx%d", frame.width, frame.height)
            if self._on_first is not None:
                self._on_first(frame)
        return False  # the speech model never sees video
