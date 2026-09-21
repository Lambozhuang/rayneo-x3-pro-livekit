"""The build guide and the state of one run through it.

A guide is a directory under ../guides with a `task.toml` (a title and an
ordered list of steps) and, optionally, a `model.glb` of the finished build
that the agent streams to the glasses as a rotating reference (render.py); a
bare .toml file is a guide without a model. Each step names the part to pick
up, what to tell the wearer, a one-line name for the list on the glasses, and
which node of the model it is, so that brick can be highlighted. This process
holds the position in that list; the model knows the names (they are in its
prompt, so it and the wearer can both say "step two") but sees a step's
instructions only through the tools in tools.py, one step at a time. Progress therefore cannot drift with the
conversation, and the log carries the timing of every step.

The model judges when a step is done, from the camera. The code does not check
the bricks: hand-written geometry does not generalise past a flat 2D layout,
and the real fix for the model over-declaring completion is to ground it
against a reference image, not to encode every shape here. That is the next
architecture (a separate photo model sees one fresh frame against a reference);
until then the model decides and calls step_done.
"""

from __future__ import annotations

import logging
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from render import ModelState

logger = logging.getLogger("rayneo-agent.build")


@dataclass(frozen=True)
class Step:
    part: str
    say: str
    name: str  # one line for the list on the glasses; defaults to `part`
    node: str | None = None  # node name in model.glb; defaults to the "stepNN" prefix


@dataclass(frozen=True)
class Guide:
    name: str
    title: str
    steps: tuple[Step, ...]
    model: Path | None = None  # model.glb of the finished build, if the guide has one


def load_guide(path: str) -> Guide:
    """Read a guide. A relative path is taken from backend/agent, where
    `guides/` lives both in the checkout and in the container."""
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent.parent / p
    toml, model = (p / "task.toml", p / "model.glb") if p.is_dir() else (p, None)
    with toml.open("rb") as f:
        data = tomllib.load(f)
    steps = tuple(
        Step(part=s["part"], say=s["say"], name=s.get("name", s["part"]), node=s.get("node", f"step{i:02d}"))
        for i, s in enumerate(data["steps"], 1)
    )
    if not steps:
        raise ValueError(f"{toml}: guide has no steps")
    return Guide(
        name=p.stem, title=data["title"], steps=steps,
        model=model if model is not None and model.exists() else None,
    )


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
    # Asks the camera sampler for one fresh frame; the `look` tool calls it.
    # Set by agent.py; None in tests and in console mode, where there is no camera.
    request_look: Callable[[], None] | None = field(default=None, repr=False)
    # The streamed reference model, when the guide has one (render.py): its
    # state, which the tools change, and the node names in the GLB, so a step
    # can be turned into the node to highlight. None without a model.
    model: ModelState | None = field(default=None, repr=False)
    model_nodes: tuple[str, ...] = ()

    @property
    def finished(self) -> bool:
        return self.step >= len(self.guide.steps)

    def status(self) -> str:
        if self.finished:
            return f"All {len(self.guide.steps)} steps complete."
        return f"Step {self.step + 1} of {len(self.guide.steps)}."

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

    def describe(self) -> str:
        """The current step, as the model should hear about it."""
        if self.finished:
            return "The build is finished. There are no more steps."
        s = self.guide.steps[self.step]
        return f"{self.status()} Part: {s.part}. Tell the wearer: {s.say}"

    def complete_step(self) -> str:
        """Advance to the next step. The model calls this once it is satisfied,
        from the camera, that the current step is done."""
        if self.finished:
            return self.describe()
        n, total = self.step + 1, len(self.guide.steps)
        logger.info(
            "step %d/%d done after %.0fs", n, total, time.monotonic() - self.step_started
        )
        self.step += 1
        self.step_started = time.monotonic()
        if self.finished:
            logger.info(
                "build finished: run=%s in %.0fs", self.run, time.monotonic() - self.started
            )
            self.highlight(None)
            return f"Step {n} complete. That was the last step: the build is finished, congratulate the wearer."
        self._log_step_start()
        return f"Step {n} complete. Next: {self.describe()}"

    def reopen_previous_step(self) -> str:
        """Go back one step: the model marked one done too early and the
        wearer, or a second look, says it is not. Logged so a run's score
        shows the false completion."""
        if self.step == 0:
            return "Already at the first step. " + self.describe()
        self.step -= 1
        self.step_started = time.monotonic()
        logger.info("step %d/%d reopened", self.step + 1, len(self.guide.steps))
        self.highlight(self.step)
        return "Reopened. " + self.describe()

    def start(self) -> None:
        logger.info(
            "build: run=%s guide=%s steps=%d", self.run, self.guide.name, len(self.guide.steps)
        )
        self._log_step_start()

    def restart(self) -> str:
        logger.info("build restarted: run=%s at step %d", self.run, self.step + 1)
        self.step = 0
        self.started = self.step_started = time.monotonic()
        self._log_step_start()
        return "Starting over. " + self.describe()

    def _log_step_start(self) -> None:
        s = self.guide.steps[self.step]
        logger.info("step %d/%d start: %s", self.step + 1, len(self.guide.steps), s.part)
        self.highlight(self.step)

    def node_for(self, index: int) -> str | None:
        """The model node of step `index` (0-based), by the step's `node` prefix."""
        prefix = self.guide.steps[index].node or ""
        return next((n for n in self.model_nodes if n.startswith(prefix)), None)

    def highlight(self, index: int | None) -> None:
        """Highlight step `index`'s brick in the streamed model, or none. Steps
        do this as they start; the highlight_part tool does it on request."""
        if self.model is None:
            return
        node = None if index is None else self.node_for(index)
        if index is not None and node is None:
            logger.warning(
                "model: no node for step %d (%r) in %s", index + 1, self.guide.steps[index].node, self.model_nodes
            )
        self.model.highlight = node
