"""Game B of the user study, "build and report": the user builds one of the sheets from pictures on the glasses, in three
batches, and after each asks the agent what it sees.

    ReportGame --the batch's picture (batch-<k>.png) and the hint line--> the glasses (Build.picture, Build.hint)
    wearer --"what do you see?"--> GPT-Live says "Let me look." --> the brain's next watch look reads the question in the
        history and answers with say: the bricks added since its last report, each its colour, size and place against a
        brick already on the plate --> GPT-Live says it --> ReportGame.on_say: the next hint
    wearer --"next"--> GPT-Live says NEXT_SAID and nothing else --> ReportGame hears it in the voice's transcript
        --> the next batch's picture and the first hint

The agent does not know the sheet: the brain gets no task text, only that the user builds from pictures it cannot see. The
trial moves on the user's words alone, never on the vision, so it keeps moving under any bandwidth, which is what the
block varies. The brain's conversation runs through the trial, so it knows what it has reported. The second line does not
run, there being no step's brick to read. The record has the question (`said` by the wearer, with its end), the look
(`watch_sent` with the saved frame), the report (`say` and `commentary`, `voice_delta` for the first spoken word) and
`batch` for every picture shown; the scoring against the sheet is done afterwards from those. The call ends from the
glasses or the console, as free play does. Decided 2026-11-09 (the study's game-spec.md, outside the repo), replacing the
placement game of 2026-11-08 (gpt/place.py), whose judgements held at 250 and 100 kbit/s while colour and stud counts
did not: the agent must now describe what was built, from the picture alone.
"""

import asyncio
import logging
import re

from gpt.brain import Brain
from guide import Build, publish_build, send_picture
from runlog import RunLog

logger = logging.getLogger("rayneo-agent.report")

# The sheet's steps in each batch, numbered as the wearer counts them: two, two and one brick of the five.
BATCHES = ((1, 2), (3, 4), (5, 5))

# The hint line through a batch, in Lambo's words (2026-11-09).
HINT_PLACE = "Place these bricks, then ask the agent what it sees."
HINT_NEXT = "Say next for the next bricks."
HINT_WHOLE = "Ask for a description of the whole build if you like."

# What the voice says, and nothing else, when the user asks for the next bricks (REPORT_PERSONA); heard here in its
# transcript, letters only, so punctuation and case do not matter.
NEXT_SAID = "Here come the next bricks."


def _letters(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


class ReportGame:
    """Shows the batches and hears the voice; the brain inside does the looking and the reports. Stands where the brain
    stands for gpt/agent.py (start_watching, stop_watching, voice_now, on_delegation, instructions) and passes those on."""

    def __init__(self, brain: Brain, build: Build, record: RunLog) -> None:
        self._brain, self._build, self._record = brain, build, record
        self._batch = 0  # batches shown so far, 0 before the first
        self._advanced = False  # the voice's current turn has already moved the batch on
        brain.on_say = self._reported

    @property
    def instructions(self) -> str:
        return self._brain.instructions

    @property
    def voice_now(self) -> str:
        return self._brain.voice_now

    @voice_now.setter
    def voice_now(self, text: str) -> None:
        """gpt/agent.py feeds the voice's transcript deltas here and clears it when the turn is in the history; the
        sentence for the next batch is heard the moment its letters are all there, once per turn."""
        self._brain.voice_now = text
        if not text:
            self._advanced = False
        elif not self._advanced and _letters(NEXT_SAID) in _letters(text):
            self._advanced = True
            if self._batch < len(BATCHES):
                asyncio.create_task(self._show_batch(self._batch + 1), name="report_batch")
            else:
                logger.info("report: the voice gave the next bricks after the last batch; nothing to show")

    def start_watching(self) -> None:
        self._brain.start_watching()
        asyncio.create_task(self._show_batch(1), name="report_batch")

    def stop_watching(self) -> None:
        self._brain.stop_watching()

    def on_delegation(self, d) -> None:
        self._brain.on_delegation(d)

    async def _show_batch(self, k: int) -> None:
        """Batch `k` begins: the step list marks its first step, its picture and the first hint go to the glasses."""
        build = self._build
        first, last = BATCHES[k - 1]
        self._batch = k
        build.step = first - 1  # the list on the glasses marks the batch's first step; the steps before read as done
        build.hint = HINT_PLACE
        build.show(k)
        await publish_build(build)
        sent = await send_picture(build, k)
        self._record.event("batch", n=k, steps=[first, last], hint=build.hint, **sent)
        logger.info("report: batch %d of %d, steps %d to %d, picture %s", k, len(BATCHES), first, last, sent["name"])

    async def _reported(self, line: str) -> None:
        """The brain gave the voice a line, a report or an answer: the hint says what comes next."""
        build = self._build
        build.hint = HINT_WHOLE if self._batch >= len(BATCHES) else HINT_NEXT
        await publish_build(build)
        self._record.event("report", batch=self._batch, text=line, hint=build.hint)
