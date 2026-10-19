"""The build guide and the state of one run through it.

A guide is a directory under ../guides with a `task.toml` (a title and an
ordered list of steps); a bare .toml file works too. Each step has a name for
the list on the glasses, the brick and where it goes.

`Build` holds the run's position in that list and logs the timing of every
step. The brain on the GPT path, or the model's set_progress call on the
Realtime path, moves it (`set_step`) when it judges from the camera how many
steps are built; `publish_build` sends the position to the
glasses.
"""

from __future__ import annotations

import json
import logging
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("rayneo-agent.build")

@dataclass(frozen=True)
class Step:
    name: str  # one line for the list on the glasses
    brick: str  # which brick, e.g. "purple 2x4"
    place: str  # where it goes, against the bricks before it; the models get `brick` and `place`
    # The brick's footprint as drawn on the sheet, [col0, row0, col1, row1] inclusive, columns left to right and rows
    # from the far edge; for drawings, never sent to a model.
    cells: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class Guide:
    name: str
    title: str
    steps: tuple[Step, ...]
    plate: int = 16  # studs per side of the baseplate


def load_guide(path: str) -> Guide:
    """Read a guide. A relative path is taken from backend/agent, where
    `guides/` lives both in the checkout and in the container."""
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent.parent / p
    toml = p / "task.toml" if p.is_dir() else p
    with toml.open("rb") as f:
        data = tomllib.load(f)
    steps = tuple(
        Step(name=s["name"], brick=s["brick"], place=s["place"], cells=tuple(s["cells"]) if "cells" in s else None)
        for s in data["steps"]
    )
    if not steps:
        raise ValueError(f"{toml}: guide has no steps")
    return Guide(name=p.stem, title=data["title"], steps=steps, plate=int(data.get("plate", 16)))


def picked_guide(metadata: str) -> Guide:
    """The build the glasses picked for this call: the api puts {"task": <name>}
    into the agent's dispatch metadata, in every token it signs."""
    task = json.loads(metadata or "{}").get("task")
    if not task:
        raise ValueError("the dispatch metadata names no task")
    return load_guide(f"guides/{task}")


@dataclass
class Build:
    """One run through a guide; lives in AgentSession.userdata.

    One call is one run: the state starts at step 0 when the job starts and is
    gone when the room closes. `run` is the room name, unique per call, so the
    log lines of one run can be pulled out with a grep.
    """

    guide: Guide
    run: str
    step: int = 0  # index of the current step; len(steps) once finished
    started: float = field(default_factory=time.monotonic)
    step_started: float = field(default_factory=time.monotonic)

    @property
    def finished(self) -> bool:
        return self.step >= len(self.guide.steps)

    def attributes(self) -> dict[str, str]:
        """The run as participant attributes, for the list on the glasses:
        every step's name, newline-separated, and the index of the current
        one (equal to the count once finished). Attributes ride the signalling
        channel and are re-sent after a reconnect, which a data message is
        not, so a wearer who dropped out for a while still sees the right step."""
        return {
            "rayneo.build.title": self.guide.title,
            "rayneo.build.steps": "\n".join(s.name for s in self.guide.steps),
            "rayneo.build.step": str(self.step),
        }

    def where(self) -> str:
        """The recorded progress, as a model is told it."""
        total = len(self.guide.steps)
        if self.finished:
            return f"all {total} steps recorded as done"
        return (f"{self.step} of {total} steps recorded as done; the wearer is on step {self.step + 1} "
                f"({self.guide.steps[self.step].brick})")

    def set_step(self, step: int) -> bool:
        """Move to step index `step` (0-based; len(steps) = finished) because a
        model judged the build to be there. Every step passed is logged with
        its time. Returns whether anything changed."""
        step = max(0, min(step, len(self.guide.steps)))
        if step == self.step:
            return False
        n, total = self.step + 1, len(self.guide.steps)
        if step > self.step:
            for k in range(self.step, step):
                logger.info("step %d/%d done after %.0fs", k + 1, total, time.monotonic() - self.step_started)
                self.step_started = time.monotonic()
        else:
            logger.info("step %d/%d reopened (build seen at step %d)", n, total, step + 1)
        self.step = step
        self.step_started = time.monotonic()
        if self.finished:
            logger.info("build finished: run=%s in %.0fs", self.run, time.monotonic() - self.started)
        else:
            self._log_step_start()
        return True

    def start(self) -> None:
        """The task begins now: the wearer is in the call. The time it takes is counted from here, not from
        when this object was made while the call was still being set up."""
        self.started = self.step_started = time.monotonic()
        logger.info(
            "build: run=%s guide=%s steps=%d", self.run, self.guide.name, len(self.guide.steps)
        )
        self._log_step_start()

    def _log_step_start(self) -> None:
        s = self.guide.steps[self.step]
        logger.info("step %d/%d start: %s", self.step + 1, len(self.guide.steps), s.name)


async def publish_build(build: Build) -> None:
    """The run's position to the glasses, as participant attributes (Build.attributes)."""
    from livekit.agents import get_job_context

    await get_job_context().room.local_participant.set_attributes(build.attributes())
