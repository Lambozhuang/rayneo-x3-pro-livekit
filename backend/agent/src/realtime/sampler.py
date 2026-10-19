"""Which camera frames the model gets, and what each looks like: the bottom square, at one rate while the wearer speaks and another while they do not.

An AgentSession `video_sampler`: the framework calls it with every frame from
the glasses (~15 a second). The rate rule is the framework's own sampler's
(VoiceActivityVideoSampler): a frame is due when 1/speaking_fps seconds have
passed since the last one while the wearer speaks (the API's turn detection
sets the session's user state), 1/silent_fps seconds otherwise. A due frame is
cut to its bottom square scaled to `side` (frames.bottom_square, the table in
front of the wearer) and pushed to the model through the agent's realtime
session, which sends it as one image message into the conversation; the full
frame never goes.

Every frame pushed is also saved into the call's record as a JPEG, with the
step the build was on, so a run can be judged afterwards from what the model
saw. The JPEG encoding goes to one worker thread, in order.
"""

from __future__ import annotations

import io
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from livekit import rtc
from livekit.agents.voice import AgentSession
from PIL import Image

from frames import bottom_square, to_frame
from runlog import RunLog

logger = logging.getLogger("rayneo-agent.camera")


class VoiceActivitySampler:
    def __init__(self, speaking_fps: float, silent_fps: float, side: int, record: RunLog,
                 step: Callable[[], int]) -> None:
        self._speaking_period = 1.0 / speaking_fps
        self._silent_period = 1.0 / silent_fps
        self._side = side
        self._record = record
        self._step = step  # the step the build is on, for the record
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
        speaking = session.user_state == "speaking"
        if now - self._last < (self._speaking_period if speaking else self._silent_period):
            return False
        try:
            rt = session.current_agent.realtime_llm_session
        except RuntimeError:
            return False  # the session is not running yet; the next frame will do
        self._last = now
        img = bottom_square(frame, self._side)
        rt.push_video(to_frame(img))
        self.sent += 1
        self._encoder.submit(self._save, img, self.sent, self.count, self._step(), speaking)
        return False  # pushed above; the framework must not send the full frame too

    def _save(self, img: Image.Image, n: int, seq: int, step: int, speaking: bool) -> None:
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        jpeg = buf.getvalue()
        saved = self._record.photo(jpeg, f"frame{n}-s{step}")
        self._record.event("frame", n=n, frame=seq, step=step, wearer_speaking=speaking,
                           size=f"{img.width}x{img.height}", photo=saved, photo_kb=len(jpeg) // 1024)
