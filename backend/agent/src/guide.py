"""The build guide and the state of one run through it.

A guide is a TOML file (see ../guides): a title, a one-line goal, and an
ordered list of steps. Each step names the part to pick up, what to tell the
wearer, and what the camera should show when the step is done. This process
holds the position in that list; the model only ever sees the current step,
through the tools in tools.py. Progress therefore cannot drift with the
conversation, and the log carries the timing of every step.
"""

from __future__ import annotations

import logging
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("rayneo-agent.build")


@dataclass(frozen=True)
class Step:
    part: str
    say: str
    check: str


@dataclass(frozen=True)
class Guide:
    name: str
    title: str
    goal: str
    steps: tuple[Step, ...]


def load_guide(path: str) -> Guide:
    """Read a guide. A relative path is taken from backend/agent, where
    `guides/` lives both in the checkout and in the container."""
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent.parent / p
    with p.open("rb") as f:
        data = tomllib.load(f)
    steps = tuple(Step(**s) for s in data["steps"])
    if not steps:
        raise ValueError(f"{p}: guide has no steps")
    return Guide(name=p.stem, title=data["title"], goal=data["goal"], steps=steps)


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
    attempts: int = 0  # confirm_step calls on the current step
    observed: bool = False  # step_done has been called since the step started
    started: float = field(default_factory=time.monotonic)
    step_started: float = field(default_factory=time.monotonic)

    @property
    def finished(self) -> bool:
        return self.step >= len(self.guide.steps)

    def describe(self) -> str:
        """The current step, as the model should hear about it. The check is
        withheld on purpose: given the expected picture up front, the model
        recited it back as its observation instead of looking."""
        if self.finished:
            return "The build is finished. There are no more steps."
        s = self.guide.steps[self.step]
        return f"Step {self.step + 1} of {len(self.guide.steps)}. Part: {s.part}. Tell the wearer: {s.say}"

    def observe(self, observation: str) -> str:
        """Record what the model saw before it knew what to expect, then hand
        it the check to compare against."""
        if self.finished:
            return self.describe()
        self.observed = True
        logger.info("step %d/%d observed: %s", self.step + 1, len(self.guide.steps), observation)
        return (
            f"This step requires: {self.guide.steps[self.step].check} "
            "Compare that with what you saw, point by point. If your observation did not "
            "cover a point, look at the camera again for it. Then call confirm_step."
        )

    def start(self) -> None:
        logger.info(
            "build: run=%s guide=%s steps=%d", self.run, self.guide.name, len(self.guide.steps)
        )
        self._log_step_start()

    def confirm(self, matches: bool, differences: str) -> str:
        """Record the model's verdict on the current step; advance if it passed."""
        if self.finished:
            return self.describe()
        if not self.observed:
            return "Call step_done with what you see first."
        self.attempts += 1
        n, total = self.step + 1, len(self.guide.steps)
        logger.info(
            "step %d/%d %s after %.0fs attempts=%d: %s",
            n,
            total,
            "done" if matches else "not yet",
            time.monotonic() - self.step_started,
            self.attempts,
            differences or "-",
        )
        if not matches:
            self.observed = False
            return "Not recorded as done. Tell the wearer what to fix; when they say so, look again."
        self.step += 1
        self.attempts = 0
        self.observed = False
        self.step_started = time.monotonic()
        if self.finished:
            logger.info(
                "build finished: run=%s in %.0fs", self.run, time.monotonic() - self.started
            )
            return "That was the last step. The build is complete; congratulate the wearer."
        self._log_step_start()
        return "Recorded. Next: " + self.describe()

    def restart(self) -> str:
        logger.info("build restarted: run=%s at step %d", self.run, self.step + 1)
        self.step = 0
        self.attempts = 0
        self.observed = False
        self.started = self.step_started = time.monotonic()
        self._log_step_start()
        return "Starting over. " + self.describe()

    def _log_step_start(self) -> None:
        s = self.guide.steps[self.step]
        logger.info("step %d/%d start: %s", self.step + 1, len(self.guide.steps), s.part)
