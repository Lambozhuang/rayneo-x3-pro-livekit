"""Game B of the user study, "build and report": the user builds one of the sheets in one go from a picture of the whole
figure on the glasses, then asks the agent what it sees, then which brick they placed last.

    ReportGame --the figure's picture (figure.png) and the hint line--> the glasses (Build.picture, Build.hint)
    wearer builds; the brain watches as in a build and says nothing unasked
    wearer --"what do you see?"--> GPT-Live says "Let me look." --> the brain's next watch look reads the question in the
        history and answers with say: every brick on the plate, its colour, size and place, in its own words
        --> GPT-Live reads it out --> ReportGame.on_say: the hint asks for the second question
    wearer --"which brick did I place last?"--> the brain's say, from what it saw while the user built --> ReportGame.on_say:
        the trial is finished, and the call ends as a finished build's does (gpt/agent.py: the voice's silence, then Build.over)

The agent does not know the sheet: the brain gets no task text, only that the user builds from a picture it cannot see.
The brain's conversation runs through the trial. The second line does not run, there being no step's brick to read. The
brain's first line is taken as the description and its second as the answer about the last brick, whatever the user
asked; a line that answers something else counts all the same, and the console's time limit is the backstop (the user's
rule of 2026-11-10: no special cases). The record has the questions (`said` by the wearer, with their ends), the looks
(`watch_sent` with the saved frames), the answers (`say`, `commentary`, `voice_delta` for the first spoken word), `report`
for each of the brain's lines (`kind` "description" or "last") and `hint` for each hint. The spec is the study's game-spec.md, outside the repo, revised
after the first lab pilot of 2026-11-10; the batches and the "next" of 2026-11-09 are gone.
"""

import asyncio
import logging
import time

from gpt.brain import Brain
from guide import Build, publish_build, send_picture
from runlog import RunLog

logger = logging.getLogger("rayneo-agent.report")

# The hint line, one text for the build and one after the first answer (the user's wording of 2026-11-09 and 11-10).
HINT_BUILD = "Build the figure in the picture, then ask the agent what it sees."
HINT_LAST = "Now ask the agent which brick you placed last."


class ReportGame:
    """Shows the figure and counts the brain's lines; the brain inside does the looking and the answers. Stands where
    the brain stands for gpt/agent.py (start_watching, stop_watching, voice_now, on_delegation, instructions) and
    passes those on."""

    def __init__(self, brain: Brain, build: Build, record: RunLog) -> None:
        self._brain, self._build, self._record = brain, build, record
        self._said = 0  # lines the brain has given the voice: the first is the description, the second the last brick
        brain.on_say = self._reported

    @property
    def instructions(self) -> str:
        return self._brain.instructions

    @property
    def voice_now(self) -> str:
        return self._brain.voice_now

    @voice_now.setter
    def voice_now(self, text: str) -> None:
        self._brain.voice_now = text

    def start_watching(self) -> None:
        self._brain.start_watching()
        asyncio.create_task(self._begin(), name="report_begin")

    def stop_watching(self) -> None:
        self._brain.stop_watching()

    def on_delegation(self, d) -> None:
        self._brain.on_delegation(d)

    async def _begin(self) -> None:
        """The trial begins: the whole figure and the build's hint go to the glasses, with every step marked current."""
        build = self._build
        build.step, build.span = 0, len(build.guide.steps)
        build.hint = HINT_BUILD
        build.show(1)
        await publish_build(build)
        sent = await send_picture(build, 1)
        self._record.event("figure", **sent)
        self._record.event("hint", text=build.hint)
        logger.info("report: the figure of %s is on the glasses", build.guide.name)

    async def _reported(self, line: str) -> None:
        """The brain gave the voice a line: the first is the description, after which the hint asks which brick was
        placed last; the second is that answer, which finishes the trial. Nothing slow may be awaited here: the brain's
        look has BRAIN_TIMEOUT seconds in all."""
        build = self._build
        self._said += 1
        done = self._said >= 2
        if done:
            build.step, build.span = len(build.guide.steps), 1  # finished: gpt/agent.py ends the call once the voice is quiet
            build.hint = ""
            self._record.event("build", finished=True, took_s=round(time.monotonic() - build.started, 1))
            logger.info("report: the last brick is answered; the trial is done")
        else:
            build.hint = HINT_LAST
            self._record.event("hint", text=build.hint)
        await publish_build(build)
        self._record.event("report", n=self._said, kind="last" if done else "description", text=line, finished=done)
