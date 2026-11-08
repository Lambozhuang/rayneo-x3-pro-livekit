"""The build guide and the state of one run through it.

A guide is a directory under ../guides with a `task.toml` (a title and an
ordered list of steps); a bare .toml file works too. Each step has a name for
the list on the glasses, the brick and where it goes.

`Build` holds the run's position in that list and logs the timing of every
step. The brain on the GPT path, or the model's set_progress call on the
Realtime path, moves it (`set_step`) when it judges from the camera how many
steps are built; `publish_build` sends the position to the
glasses. Each step also has a picture, `step-<n>.png` beside the task file,
drawn by render_pictures.py from the step's colour and cells; the brain sends
it to the glasses when the wearer asks to see a step (brain.py `show`), and
`Build.picture` says which one is on the glasses. `Build.act` tells the
glasses what the agent does this instant, for the element on their screen
that moves with the conversation (`act_now`), and `Build.hint` is the line of
words the glasses show above that element.

A guide can also be one trial of a game of the user study (`Guide.game`): the
placement game has an `anchor` brick fixed on the plate and its steps are the
rounds, each the movable brick at one target (gpt/place.py). Its pictures show
the anchor and the round's target only.
"""

from __future__ import annotations

import json
import logging
import re
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
    # The brick as render_pictures.py draws it in the step's picture, never sent to a model: its colour as
    # tasks/sheet.html draws it, "#rrggbb", and its footprint as drawn on the sheet, [col0, row0, col1, row1]
    # inclusive, columns left to right and rows from the far edge. A round plate covers its square but not the corners
    # and is drawn as a disc.
    color: str
    cells: tuple[int, int, int, int]
    # In a round of the placement game, where the hint asks the user to put the brick first, one row or one column off
    # the target ("one row below the target"); empty in a build's step (gpt/place.py).
    offset: str = ""

    @property
    def round(self) -> bool:
        return "round plate" in self.brick


@dataclass(frozen=True)
class Guide:
    name: str
    title: str
    steps: tuple[Step, ...]
    directory: Path  # where the task file and the step pictures are
    plate: int = 16  # studs per side of the baseplate
    game: str = ""  # "" for a build; "place" for a trial of the placement game, whose steps are its rounds (gpt/place.py)
    anchor: Step | None = None  # a brick fixed on the plate before a game begins, drawn in every picture; games only

    def picture_name(self, step: int) -> str:
        """File name of the picture of step `step`, numbered as the wearer counts; the glasses show it under this name."""
        return f"step-{step}.png"

    def picture(self, step: int) -> Path:
        return self.directory / self.picture_name(step)


def load_guide(path: str, pictures: bool = True) -> Guide:
    """Read a guide. A relative path is taken from backend/agent, where
    `guides/` lives both in the checkout and in the container. Every step's
    picture has to be there too, unless `pictures` is false, which only
    render_pictures.py, about to draw them, passes."""
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent.parent / p
    toml = p / "task.toml" if p.is_dir() else p
    with toml.open("rb") as f:
        data = tomllib.load(f)
    steps = []
    for i, s in enumerate(data["steps"], 1):
        try:
            step = Step(name=s["name"], brick=s["brick"], place=s["place"], color=s["color"], cells=tuple(s["cells"]),
                        offset=str(s.get("offset", "")))
        except KeyError as e:
            raise ValueError(f"{toml}: step {i} has no {e.args[0]}") from None
        if not re.fullmatch(r"#[0-9a-f]{6}", step.color) or len(step.cells) != 4:
            raise ValueError(f"{toml}: step {i} has a bad color or cells")
        steps.append(step)
    if not steps:
        raise ValueError(f"{toml}: guide has no steps")
    steps = tuple(steps)
    game = str(data.get("game", ""))
    if game not in ("", "place"):
        raise ValueError(f"{toml}: game {game!r} is not one this agent plays")
    anchor = None
    if "anchor" in data:
        a = data["anchor"]
        try:
            anchor = Step(name=a.get("name", a["brick"]), brick=a["brick"], place=a["place"], color=a["color"], cells=tuple(a["cells"]))
        except KeyError as e:
            raise ValueError(f"{toml}: the anchor has no {e.args[0]}") from None
    if game == "place" and anchor is None:
        raise ValueError(f"{toml}: the placement game needs an [anchor] brick")
    guide = Guide(name=p.stem, title=data["title"], steps=steps, directory=toml.parent, plate=int(data.get("plate", 16)),
                  game=game, anchor=anchor)
    if pictures:
        missing = [guide.picture_name(n) for n in range(1, len(steps) + 1) if not guide.picture(n).is_file()]
        if missing:
            raise ValueError(f"{toml.parent}: no picture {', '.join(missing)}; run `python render_pictures.py` in "
                             "backend/agent")
    return guide


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
    picture: int = 0  # the step whose picture the glasses show, numbered as the wearer counts; 0 shows the camera
    over: bool = False  # the task is over: the glasses hang up on seeing it (gpt/agent.py, VoiceAssistantScreen.kt)
    act: str = ""  # what the agent does this instant, for the glasses' element: "yes 3", "not 4", "looking 5", or nothing
    acts: int = 0  # how many acts this run has published; the count in the value makes every act a change
    hint: str = ""  # the line of words the glasses show above the element, what to do now; games only so far (gpt/place.py)

    @property
    def finished(self) -> bool:
        return self.step >= len(self.guide.steps)

    def attributes(self) -> dict[str, str]:
        """The run as participant attributes: the title, every step's name, newline-separated, the index of the
        current step (equal to the count once finished), for the list on the glasses, and the name of the picture the
        glasses are to show (PICTURE_ATTRIBUTE, empty when the square is to show the camera), which brain.py sends them
        right after as a byte stream on PICTURE_TOPIC. Only the index and the picture change during a call. Attributes ride
        the signalling channel and are re-sent after a reconnect, which a data message is not, so a wearer who
        dropped out for a while still sees the right step and the right picture. `rayneo.call.over` is "1" once the
        task is over (the build finished and the voice has said so, gpt/agent.py): the glasses end the call on it.
        `rayneo.agent` is what the agent does this instant (`act_now`): the glasses' element flashes green or red on
        "yes n" and "not n" and shows the plate being judged while it reads "looking n" (AgentDots.kt). `rayneo.hint`
        is the line of words above the element, what to do now, empty for none (PhaseHint in Phase.kt)."""
        return {
            "rayneo.build.title": self.guide.title,
            "rayneo.build.steps": "\n".join(s.name for s in self.guide.steps),
            "rayneo.build.step": str(self.step),
            PICTURE_ATTRIBUTE: self.guide.picture_name(self.picture) if self.picture else "",
            "rayneo.call.over": "1" if self.over else "",
            "rayneo.agent": self.act,
            "rayneo.hint": self.hint,
        }

    def where(self) -> str:
        """The recorded progress and what the glasses show, as a model is told it."""
        total = len(self.guide.steps)
        glasses = (f"the glasses show the picture of step {self.picture}" if self.picture else
                   "the glasses show the camera's view, no picture")
        if self.finished:
            return f"all {total} steps recorded as done; {glasses}"
        return (f"{self.step} of {total} steps recorded as done; the wearer is on step {self.step + 1} "
                f"({self.guide.steps[self.step].brick}); {glasses}")

    def set_step(self, step: int) -> bool:
        """Move to step index `step` (0-based; len(steps) = finished) because a
        model judged the build to be there. Every step passed is logged with
        its time, and a picture on the glasses goes away: it was about the step
        just left. Returns whether anything changed."""
        step = max(0, min(step, len(self.guide.steps)))
        if step == self.step:
            return False
        if self.picture:
            logger.info("picture of step %d taken off the glasses: the progress moved", self.picture)
            self.picture = 0
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

    def show(self, step: int) -> None:
        """Put the picture of step `step` (numbered as the wearer counts, 1 to the count) on the glasses, or take
        the picture away (0), because a model was asked to."""
        if step:
            logger.info("picture of step %d/%d put on the glasses", step, len(self.guide.steps))
        else:
            logger.info("picture of step %d taken off the glasses", self.picture)
        self.picture = step

    def act_now(self, kind: str) -> None:
        """What the agent does this instant, for the glasses: "yes" or "not" when the second line (gpt/moments.py)
        says the brick in the hand is or is not the step's, "looking" while the brain judges a placement it was called
        to (brain.py), "" when that judgement is in. The value carries a running count, so two acts of one kind in a
        row both reach the glasses as a change of the attribute; publish_build sends it."""
        if kind:
            self.acts += 1
            self.act = f"{kind} {self.acts}"
        else:
            self.act = ""

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


# The byte streams that carry a step's picture to the glasses, and the attribute that names the one to show
# (Pictures.kt reads both). The names are not the build's: the glasses show whatever picture the agent sends.
PICTURE_TOPIC = "rayneo.picture"
PICTURE_ATTRIBUTE = "rayneo.picture"


async def publish_build(build: Build) -> None:
    """The run's position and the picture to show to the glasses, as participant attributes (Build.attributes)."""
    from livekit.agents import get_job_context

    await get_job_context().room.local_participant.set_attributes(build.attributes())


async def send_picture(build: Build, step: int) -> dict:
    """Send the picture of step `step` (numbered as the wearer counts) to the glasses as a byte stream on
    PICTURE_TOPIC, over the reliable data channel, late under a slow network rather than missing; the glasses show it
    once they have it and its name is the one the attribute published before names (Pictures.kt). Returns the name,
    the size and the time the send took, for the record."""
    from livekit.agents import get_job_context

    name, data = build.guide.picture_name(step), build.guide.picture(step).read_bytes()
    t0 = time.perf_counter()
    writer = await get_job_context().room.local_participant.stream_bytes(
        name, total_size=len(data), mime_type="image/png", topic=PICTURE_TOPIC)
    await writer.write(data)
    await writer.aclose()
    sent = {"name": name, "bytes": len(data), "send_ms": round((time.perf_counter() - t0) * 1000)}
    logger.info("picture: %s (%d KB) sent to the glasses in %d ms", name, len(data) // 1024, sent["send_ms"])
    return sent
