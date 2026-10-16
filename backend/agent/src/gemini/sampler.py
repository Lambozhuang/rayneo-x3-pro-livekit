"""Which camera frames the model gets, and what each looks like: the middle square, one every 1/fps seconds.

An AgentSession `video_sampler`: the framework calls it with every frame from
the glasses (~15 a second). This one never lets a frame through as it is;
when one is due it crops it to the middle square scaled to `side` x `side`
(frames.center_square; Google recommends 768x768 at 1 FPS for the Live API)
and pushes the cropped frame to the model itself, through the agent's realtime
session,
the same call the framework would have made. A fixed rate is the simplest
thing that works; every frame the model sees stays in its context for the rest
of the call, so GEMINI_VIDEO_FPS is the cost knob (config.py).

Every frame pushed is also saved into the call's record as a JPEG, so a run
can be judged afterwards from what the model saw. The crop runs on the event
loop (a few milliseconds); the JPEG encoding, longer, goes to one worker
thread, in order.
"""

from __future__ import annotations

import io
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from livekit import rtc
from livekit.agents.voice import AgentSession
from PIL import Image

from frames import center_square, to_frame
from runlog import RunLog

logger = logging.getLogger("rayneo-agent.camera")


class FixedRateSampler:
    def __init__(self, fps: float, side: int, record: RunLog) -> None:
        self._period = 1.0 / fps
        self._side = side
        self._record = record
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
        try:
            rt = session.current_agent.realtime_llm_session
        except RuntimeError:
            return False  # the session is not running yet; the next frame will do
        self._last = now
        img = center_square(frame, self._side)
        rt.push_video(to_frame(img))
        self.sent += 1
        self._encoder.submit(self._save, img, self.sent, self.count)
        return False  # pushed above; the framework must not send the full frame too

    def _save(self, img: Image.Image, n: int, seq: int) -> None:
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        jpeg = buf.getvalue()
        saved = self._record.photo(jpeg, f"frame{n}")
        self._record.event("frame", n=n, frame=seq, size=f"{img.width}x{img.height}", photo=saved,
                           photo_kb=len(jpeg) // 1024)
