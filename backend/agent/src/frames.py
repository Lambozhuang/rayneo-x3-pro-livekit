"""The camera, tapped: every frame from the glasses arrives here, none reaches the model.

`FrameTap` is an AgentSession `video_sampler` that always answers "drop", so
the framework never forwards video to the speech model, and keeps the frames
for the code instead: `next_frame()` waits for the next one to arrive, which at
the glasses' frame rate is a few tens of milliseconds, so whatever asks for a
picture gets one taken after it asked. That is the whole point: the vision
check judges the frame taken when the wearer said "done", never an older one.

FRAME_DUMP_DIR keeps a copy of every frame that was actually sent to a vision
model, named after what it was sent for, one subdirectory per call.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

from livekit import rtc
from livekit.agents.voice import AgentSession

logger = logging.getLogger("rayneo-agent.frames")


class FrameTap:
    def __init__(self, dump_dir: str | None = None, dump_max: int = 60) -> None:
        self.count = 0  # frames seen, for the log: zero means the video path is broken
        self._waiters: list[asyncio.Future[rtc.VideoFrame]] = []
        self._dump_dir: str | None = None
        self._dump_max = dump_max
        self._dumped = 0
        self._writer: ThreadPoolExecutor | None = None
        if dump_dir:
            self._dump_dir = os.path.join(dump_dir, time.strftime("%Y%m%d-%H%M%S"))
            os.makedirs(self._dump_dir, exist_ok=True)
            self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="framedump")
            logger.info("dumping up to %d checked frames to %s", dump_max, self._dump_dir)

    def __call__(self, frame: rtc.VideoFrame, session: AgentSession) -> bool:
        self.count += 1
        if self.count == 1:
            logger.info("camera: first frame %dx%d", frame.width, frame.height)
        for fut in self._waiters:
            if not fut.done():
                fut.set_result(frame)
        self._waiters.clear()
        return False  # the speech model never sees video

    async def next_frame(self, timeout: float = 3.0) -> rtc.VideoFrame:
        """The next frame to arrive. Raises asyncio.TimeoutError if the camera is silent."""
        fut: asyncio.Future[rtc.VideoFrame] = asyncio.get_running_loop().create_future()
        self._waiters.append(fut)
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            if fut in self._waiters:
                self._waiters.remove(fut)

    def dump(self, jpeg: bytes, name: str) -> None:
        """Keep a copy of an encoded frame, if FRAME_DUMP_DIR is set."""
        if self._dump_dir is None or self._writer is None or self._dumped >= self._dump_max:
            return
        self._dumped += 1
        path = os.path.join(self._dump_dir, f"{self._dumped:03d}-{name}.jpg")
        self._writer.submit(self._write, path, jpeg)

    @staticmethod
    def _write(path: str, data: bytes) -> None:
        try:
            with open(path, "wb") as f:
                f.write(data)
        except Exception:
            logger.exception("could not write %s", path)
