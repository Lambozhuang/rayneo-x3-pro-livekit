"""One call's record, for reading back after the call (deploy/report.py turns it into a page).

RUN_DIR (compose: /app/runs = backend/runs on the host) gets one directory per call,
<UTC start>-<room>:

    events.jsonl   one JSON object per line: t (seconds since the call started), kind, the event's fields;
                   the first, `call`, carries wall_ms, the wall clock of t=0
    brain.txt      the brain's instructions as sent; voice.txt the voice's persona
    ask<n>-s<step>.jpg   every photo sent to the brain, as sent

Without RUN_DIR nothing is written. The log lines on stdout stay as they are; this is
the same story with every field kept. Writes go through one worker thread, in order, so
the call never waits on the disk.
"""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("rayneo-agent.runlog")


class RunLog:
    def __init__(self, root: str | None, room: str) -> None:
        self._t0 = time.monotonic()
        self._wall0 = time.time()
        self.dir: str | None = None
        self._writer: ThreadPoolExecutor | None = None
        self._events = None
        if root:
            self.dir = os.path.join(root, time.strftime("%Y%m%d-%H%M%S", time.gmtime(self._wall0)) + "-" + room)
            os.makedirs(self.dir, exist_ok=True)
            self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="runlog")
            self._events = open(os.path.join(self.dir, "events.jsonl"), "a", encoding="utf-8")
            logger.info("run record in %s", self.dir)

    @property
    def wall_ms(self) -> int:
        """The call's t=0 as wall clock ms, for putting the glasses' lines (their own wall clock) on this axis;
        the directory name gives the same instant to the second only."""
        return round(self._wall0 * 1000)

    def t(self, wall: float | None = None) -> float:
        """Seconds since the call started: now, or at a time.time() stamp (the framework's own timestamps)."""
        return round((wall - self._wall0) if wall is not None else (time.monotonic() - self._t0), 3)

    def event(self, kind: str, **data) -> None:
        if self._writer is None:
            return
        line = json.dumps({"t": self.t(), "kind": kind, **data}, ensure_ascii=False, default=str)
        self._writer.submit(self._append, line)

    def text(self, name: str, content: str) -> None:
        if self._writer is not None:
            self._writer.submit(self._write, name, content.encode("utf-8"))

    def photo(self, jpeg: bytes, name: str) -> str | None:
        """Keep a photo as sent; returns its file name."""
        if self._writer is None:
            return None
        file = f"{name}.jpg"
        self._writer.submit(self._write, file, jpeg)
        return file

    def close(self) -> None:
        if self._writer is not None:
            self._writer.submit(self._events.close)
            self._writer.shutdown(wait=True)
            self._writer = None

    def _append(self, line: str) -> None:
        try:
            self._events.write(line + "\n")
            self._events.flush()
        except Exception:
            logger.exception("could not write an event")

    def _write(self, name: str, data: bytes) -> None:
        try:
            with open(os.path.join(self.dir, name), "wb") as f:
                f.write(data)
        except Exception:
            logger.exception("could not write %s", name)
