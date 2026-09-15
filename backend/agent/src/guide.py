"""The build guide and the state of one run through it.

A guide is a TOML file (see ../guides): a title, a one-line goal, and an
ordered list of steps. Each step names the part to pick up, what to tell the
wearer, which bricks the baseplate must hold when the step is done, and how
they relate. This process holds the position in that list; the model only
ever sees the current step, through the tools in tools.py. Progress therefore
cannot drift with the conversation, and the log carries the timing of every
step.

Checking a step is split in two. The model first reports the bricks it sees,
each with counted studs; colour, size and orientation are compared here
against the step's `plate`. Only if they agree is the model told the step's
`check` (positions and alignment) and asked for a verdict. Handing the model
the expected picture up front made it recite the picture back as its
observation; asking for prose made it skip counting and fill in what it had
just told the wearer to do.
"""

from __future__ import annotations

import logging
import time
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("rayneo-agent.build")


@dataclass(frozen=True)
class Brick:
    color: str
    size: str  # "1x4": short side first
    orientation: str  # "horizontal" or "vertical": direction of the long side

    @classmethod
    def seen(cls, color: str, studs_wide: int, studs_long: int, orientation: str) -> Brick:
        a, b = sorted((studs_wide, studs_long))
        return cls(color.strip().lower(), f"{a}x{b}", orientation.strip().lower())

    def __str__(self) -> str:
        return f"{self.color} {self.size} {self.orientation}"


@dataclass(frozen=True)
class Step:
    part: str
    say: str
    check: str
    plate: tuple[Brick, ...]


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
    steps = tuple(
        Step(
            part=s["part"],
            say=s["say"],
            check=s["check"],
            plate=tuple(Brick(b["color"], b["size"], b["orientation"]) for b in s["plate"]),
        )
        for s in data["steps"]
    )
    if not steps:
        raise ValueError(f"{p}: guide has no steps")
    return Guide(name=p.stem, title=data["title"], goal=data["goal"], steps=steps)


def plate_diff(expected: tuple[Brick, ...], seen: list[Brick]) -> str:
    """Empty if the same bricks are on the plate, else what is missing or extra."""
    want, have = Counter(expected), Counter(seen)
    missing = list((want - have).elements())
    extra = list((have - want).elements())
    parts = []
    if missing:
        parts.append("missing: " + ", ".join(map(str, missing)))
    if extra:
        parts.append("not part of this step: " + ", ".join(map(str, extra)))
    return "; ".join(parts)


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
    attempts: int = 0  # checks (step_done) on the current step
    observed: bool = False  # the plate matched and confirm_step is pending
    started: float = field(default_factory=time.monotonic)
    step_started: float = field(default_factory=time.monotonic)

    @property
    def finished(self) -> bool:
        return self.step >= len(self.guide.steps)

    def describe(self) -> str:
        """The current step, as the model should hear about it. What the
        finished step looks like is withheld until the model has reported
        what it sees."""
        if self.finished:
            return "The build is finished. There are no more steps."
        s = self.guide.steps[self.step]
        return f"Step {self.step + 1} of {len(self.guide.steps)}. Part: {s.part}. Tell the wearer: {s.say}"

    def observe(self, bricks: list[Brick], positions: list[str]) -> str:
        """Compare the reported bricks with the step's plate. On a match, hand
        the model the relations to judge; otherwise the step stays open."""
        if self.finished:
            return self.describe()
        s = self.guide.steps[self.step]
        n, total = self.step + 1, len(self.guide.steps)
        self.attempts += 1
        logger.info(
            "step %d/%d observed: %s",
            n,
            total,
            "; ".join(f"{b} ({p})" for b, p in zip(bricks, positions)) or "nothing",
        )
        diff = plate_diff(s.plate, bricks)
        if diff:
            logger.info(
                "step %d/%d not yet after %.0fs attempts=%d: %s",
                n, total, time.monotonic() - self.step_started, self.attempts, diff,
            )
            return (
                f"Not done. The baseplate should hold: {', '.join(map(str, s.plate))}. "
                f"You reported {diff}. Tell the wearer what to change; when they say so, "
                "look again and call step_done."
            )
        self.observed = True
        return (
            f"The right bricks are there. This step also requires: {s.check} Compare that "
            "with what you see, point by point; look at the camera again for anything you "
            "have not checked. Then call confirm_step."
        )

    def start(self) -> None:
        logger.info(
            "build: run=%s guide=%s steps=%d", self.run, self.guide.name, len(self.guide.steps)
        )
        self._log_step_start()

    def confirm(self, matches: bool, differences: str) -> str:
        """Record the model's verdict on the relations; advance if it passed."""
        if self.finished:
            return self.describe()
        if not self.observed:
            return "Call step_done with the bricks you see first."
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
        self.observed = False
        if not matches:
            return "Not recorded as done. Tell the wearer what to fix; when they say so, look again."
        self.step += 1
        self.attempts = 0
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
