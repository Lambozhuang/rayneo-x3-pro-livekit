"""Which camera frames the model gets to see.

Every frame the model sees stays in its context for the rest of the call and
is paid for again on every turn (a Live turn carries the whole history; at
MEDIA_RESOLUTION_HIGH that is 280 tokens a frame). Measured: with the SDK's
default sampler a five-minute call reached 45k image tokens per turn and the
model's time to first audio went from 2 s to 9 s. So frames are rationed:

- while the wearer is speaking, `speaking_fps` (default 0.5): they are usually
  showing something or asking about it;
- while they are silent, `silent_fps` (default 0): nothing. The model does not
  need a live feed of a table nobody is talking about;
- one frame on demand, when the model calls the `look` tool before judging a
  step. That frame is the freshest possible, and it is the one it should judge.

"Speaking" is `session.user_state`, which is only meaningful with a local VAD
on the session (agent.py loads Silero). Without one, Gemini's server-side turn
detection sets that state when the *model* starts generating, so the SDK's
default sampler ends up sending 1 fps while the agent talks and 0.3 fps the
rest of the time, the opposite of the intent.
"""

from __future__ import annotations

import logging
import time

from livekit import rtc
from livekit.agents.voice import AgentSession

logger = logging.getLogger("rayneo-agent.camera")


class CameraSampler:
    def __init__(self, *, speaking_fps: float, silent_fps: float) -> None:
        self.speaking_fps = speaking_fps
        self.silent_fps = silent_fps
        self._last: float | None = None
        self._requested = 0

    def request(self, frames: int = 1) -> None:
        """Let the next `frames` frames through regardless of who is talking."""
        self._requested = max(self._requested, frames)

    def __call__(self, frame: rtc.VideoFrame, session: AgentSession) -> bool:
        if self._requested > 0:
            self._requested -= 1
            self._last = time.time()
            logger.info("look: frame sent on request")
            return True
        fps = self.speaking_fps if session.user_state == "speaking" else self.silent_fps
        if fps <= 0:
            return False
        now = time.time()
        if self._last is None or now - self._last >= 1.0 / fps:
            self._last = now
            return True
        return False
