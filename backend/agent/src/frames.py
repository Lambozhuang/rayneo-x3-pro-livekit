"""What a model gets to see of the camera: the crop both paths use, and the GPT path's tap on the frames.

`bottom_square` cuts the picture both architectures show their model, the
table in front of the wearer; `to_frame` turns it back into a video frame for a
realtime model (the Gemini sampler pushes it). `FrameTap` is the GPT path's
AgentSession `video_sampler`: it always answers "drop", so the framework never
forwards video to the speech model, and keeps the newest frame for the code
instead: `latest` (at the glasses' ~15 a second, at most a few tens of
milliseconds old), which the brain (gpt/brain.py) takes per delegation.
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


def bottom_square(frame: rtc.VideoFrame, side: int) -> Image.Image:
    """The bottom square of the frame (its short side wide), scaled down to `side` if larger. The glasses look
    down at the table: the upper part of the portrait frame is wall and the far desk, and dropping it nearly
    doubles the pixels per stud at the same image size. No plate detection, so whatever else is in front of the
    wearer stays in the picture. Both architectures send the model this picture."""
    img = to_image(frame)
    w, h = img.size
    s = min(w, h)
    img = img.crop(((w - s) // 2, h - s, (w - s) // 2 + s, h))
    img.thumbnail((side, side))
    return img


def to_frame(img: Image.Image) -> rtc.VideoFrame:
    """A PIL image as an RGBA video frame, for pushing to a realtime model. RGBA is what the plugins encode from;
    any other type they convert through the rtc FFI first, which cannot convert from RGB24."""
    return rtc.VideoFrame(img.width, img.height, rtc.VideoBufferType.RGBA, img.convert("RGBA").tobytes())


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
