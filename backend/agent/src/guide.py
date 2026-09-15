"""The build guide and the state of one run through it.

A guide is a TOML file (see ../guides): a title and an ordered list of steps.
Each step names the part to pick up, what to tell the wearer, and what the
baseplate must hold when the step is done. This process holds the position in
that list; the model only ever sees the current step, through the tools in
tools.py. Progress therefore cannot drift with the conversation, and the log
carries the timing of every step.

The model never judges a step. It reports the bricks it sees, each with
counted studs and how it sits relative to another brick, and the report is
compared here against the step's `plate` and `relations`. Earlier versions
asked the model for a verdict or for prose: given the expected picture it
recited it back, asked for prose it skipped counting and wrote down what it
had just told the wearer to do, and asked for a second confirming call it
never made and announced the build complete on its own.
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
class Placement:
    """How the model says a brick sits relative to another one."""

    relative_to: str  # colour of the reference brick, "none" if there is none
    side: str  # above / below / left / right / none
    gap: int  # empty rows or columns between them; 0 when touching
    aligned: str  # which ends line up: left / right / top / bottom / both / none

    def __str__(self) -> str:
        if self.relative_to == "none":
            return "alone"
        return f"{self.side} the {self.relative_to}, gap {self.gap}, {self.aligned} ends aligned"


@dataclass(frozen=True)
class Relation:
    """What the guide requires of one brick relative to another."""

    brick: str  # colour of the brick being placed
    to: str  # colour of the reference brick
    side: tuple[str, ...]  # any of these
    gap: int
    aligned: tuple[str, ...]  # any of these


@dataclass(frozen=True)
class Step:
    part: str
    say: str
    plate: tuple[Brick, ...]
    relations: tuple[Relation, ...]


@dataclass(frozen=True)
class Guide:
    name: str
    title: str
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
            plate=tuple(Brick(b["color"], b["size"], b["orientation"]) for b in s["plate"]),
            relations=tuple(
                Relation(r["brick"], r["to"], tuple(r["side"]), int(r["gap"]), tuple(r["aligned"]))
                for r in s.get("relations", [])
            ),
        )
        for s in data["steps"]
    )
    if not steps:
        raise ValueError(f"{p}: guide has no steps")
    return Guide(name=p.stem, title=data["title"], steps=steps)


def _same_color(a: str, b: str) -> bool:
    a, b = a.lower(), b.lower()
    return a == b or a in b or b in a


def judge(step: Step, bricks: list[Brick], placements: list[Placement]) -> str:
    """Empty if the report satisfies the step, else what is wrong, in words
    the model can pass on to the wearer."""
    want, have = Counter(step.plate), Counter(bricks)
    problems = []
    for b in (want - have).elements():
        problems.append(f"no {b} brick on the baseplate")
    for b in (have - want).elements():
        problems.append(f"the {b} brick is not part of this step")
    if problems:
        return "; ".join(problems)
    for rel in step.relations:
        p = next(
            (p for b, p in zip(bricks, placements) if _same_color(b.color, rel.brick)), None
        )
        if p is None:
            continue  # cannot happen once the plate matched
        if not _same_color(p.relative_to, rel.to):
            problems.append(f"describe the {rel.brick} brick relative to the {rel.to} brick")
            continue
        if p.side not in rel.side:
            problems.append(
                f"the {rel.brick} brick is {p.side} the {rel.to} brick; "
                f"it should be {' or '.join(rel.side)} it"
            )
        if p.gap != rel.gap:
            problems.append(
                f"{p.gap} empty rows between the {rel.brick} and the {rel.to} brick; "
                f"there should be {rel.gap}"
            )
        if p.aligned not in rel.aligned:
            problems.append(
                f"the {rel.brick} brick has its {p.aligned} end lined up; "
                f"its {' or '.join(rel.aligned)} end should line up with the {rel.to} brick"
            )
    return "; ".join(problems)


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
    attempts: int = 0  # step_done calls on the current step
    started: float = field(default_factory=time.monotonic)
    step_started: float = field(default_factory=time.monotonic)

    @property
    def finished(self) -> bool:
        return self.step >= len(self.guide.steps)

    def status(self) -> str:
        if self.finished:
            return f"All {len(self.guide.steps)} steps complete."
        return f"Step {self.step + 1} of {len(self.guide.steps)} is not complete."

    def describe(self) -> str:
        """The current step, as the model should hear about it. What the
        finished step must look like stays here; the model reports and the
        code judges."""
        if self.finished:
            return "The build is finished. There are no more steps."
        s = self.guide.steps[self.step]
        return f"{self.status()} Part: {s.part}. Tell the wearer: {s.say}"

    def observe(self, bricks: list[Brick], placements: list[Placement]) -> str:
        """Judge the reported bricks against the current step and advance on a pass."""
        if self.finished:
            return self.describe()
        s = self.guide.steps[self.step]
        n, total = self.step + 1, len(self.guide.steps)
        self.attempts += 1
        logger.info(
            "step %d/%d observed: %s",
            n,
            total,
            "; ".join(f"{b} ({p})" for b, p in zip(bricks, placements)) or "nothing",
        )
        problems = judge(s, bricks, placements)
        if problems:
            logger.info(
                "step %d/%d not yet after %.0fs attempts=%d: %s",
                n, total, time.monotonic() - self.step_started, self.attempts, problems,
            )
            return (
                f"Step {n} is not complete: {problems}. Tell the wearer what to change; "
                "when they say it is done, look again and call step_done."
            )
        logger.info(
            "step %d/%d done after %.0fs attempts=%d",
            n, total, time.monotonic() - self.step_started, self.attempts,
        )
        self.step += 1
        self.attempts = 0
        self.step_started = time.monotonic()
        if self.finished:
            logger.info(
                "build finished: run=%s in %.0fs", self.run, time.monotonic() - self.started
            )
            return f"Step {n} complete. That was the last step: the build is finished, congratulate the wearer."
        self._log_step_start()
        return f"Step {n} complete. Next: {self.describe()}"

    def start(self) -> None:
        logger.info(
            "build: run=%s guide=%s steps=%d", self.run, self.guide.name, len(self.guide.steps)
        )
        self._log_step_start()

    def restart(self) -> str:
        logger.info("build restarted: run=%s at step %d", self.run, self.step + 1)
        self.step = 0
        self.attempts = 0
        self.started = self.step_started = time.monotonic()
        self._log_step_start()
        return "Starting over. " + self.describe()

    def _log_step_start(self) -> None:
        s = self.guide.steps[self.step]
        logger.info("step %d/%d start: %s", self.step + 1, len(self.guide.steps), s.part)
