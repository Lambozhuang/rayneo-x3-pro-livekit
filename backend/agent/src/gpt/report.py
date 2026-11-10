"""Game B of the user study, "build and report": the user builds one of the sheets from pictures on the glasses, in three
batches, and after each asks the agent what it sees.

    ReportGame --the batch's picture (batch-<k>.png), its steps marked (Build.span), its hint line--> the glasses
    wearer --"what do you see?"--> GPT-Live says "Let me look." and hands the question over; the hand-over stays open
        (Brain answer_delegations) and the brain's next look, sent at once, answers with say, tagged
        report_of_the_bricks_just_added: the bricks added since its last report, each its colour, size and place against
        a brick already on the plate --> the line goes back as the hand-over's reply and GPT-Live reads it out
        --> ReportGame.on_say: while the last batch is shown, the trial is finished
    wearer --"next"--> GPT-Live says NEXT_SAID and nothing else --> ReportGame hears it in the voice's transcript
        --> the next batch's picture and hint

The agent does not know the sheet: the brain gets no task text, only that the user builds from pictures it cannot see.
The batches move on the user's word ("next", through the voice's fixed sentence), never on the vision, so the trial keeps
moving under any bandwidth, which is what the block varies. The end comes on the brain's own word: its say in this game
carries `answering` (brain.py SAY_ANSWERING), a line tagged report_of_the_bricks_just_added while the last batch is shown
finishes the trial, and the call ends as a finished build's does (gpt/agent.py: the voice's silence after it, then
Build.over); a line tagged something_else changes nothing, and nothing of the user's speech is read for the end. There
is no description of the whole build and no question about the order. The brain's tell tool is not in this game
(gpt/agent.py): the voice hears nothing but the say lines, each the reply to its hand-over; in the run of 2026-11-09
14:49 a tell had reached it before the question was asked and it answered from that without the brain's say. The brain's
conversation runs through the trial, so it knows what it has reported. The second line does not run, there being no
step's brick to read. The record has the questions (`said` by the wearer, with their ends), the looks (`watch_sent` with
the saved frames), the reports (`say` with `answering`, `commentary`, `voice_delta` for the first spoken word), `report`
for each of the brain's lines (`batch`, `answer` as the brain tagged it, `finished`) and `batch` and `hint` for every
picture shown; the scoring against the sheet is done afterwards from those. The three batches are the structure the
game had before the lab pilot of 2026-11-09 morning (c2cdd65), to which the user returned that evening, after pilot 5:
at 0.15 Mbit/s one description of five bricks left sizes out without the loss showing, while reports of the one or two
bricks just placed showed it; the whole-figure version of that afternoon, with its two questions, is gone, and so is
the description of the whole build that c2cdd65 asked for after the last report.
"""

import asyncio
import logging
import re
import time

from gpt.brain import Brain
from guide import Build, publish_build, send_picture
from runlog import RunLog

logger = logging.getLogger("rayneo-agent.report")

# The sheet's steps in each batch, numbered as the wearer counts them: two, two and one brick of the five.
BATCHES = ((1, 2), (3, 4), (5, 5))

# The hint line of a batch, one fixed text for the whole batch (the user's wording of 2026-11-09 night, after two runs in
# which a hint that changed with the voice's turns was missed or stuck): what to do, in order, for this batch. The last
# batch's asks for no "next" and for nothing after the report (the user's wording of 2026-11-09 evening).
HINT_BATCH = "Place these bricks, then ask the agent what it sees. When it has answered, say next."
HINT_LAST = "Place this brick, then ask the agent what it sees."

# What the voice says, and nothing else, when the user asks for the next bricks (REPORT_PERSONA); heard here in its
# transcript, letters only, so punctuation and case do not matter.
NEXT_SAID = "Here come the next bricks."

# The say label that is a batch's report (brain.py ANSWERING); one while the last batch is shown finishes the trial.
REPORT = "report_of_the_bricks_just_added"


def _letters(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


class ReportGame:
    """Shows the batches, hears the voice for the next one and follows the brain's lines by what they answer; the brain
    inside does the looking and the reports. Stands where the brain stands for gpt/agent.py (start_watching,
    stop_watching, voice_now, on_delegation, instructions) and passes those on."""

    def __init__(self, brain: Brain, build: Build, record: RunLog) -> None:
        self._brain, self._build, self._record = brain, build, record
        self._batch = 0  # batches shown so far, 0 before the first
        self._said = 0  # lines the brain has given the voice, for the record
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
        """Batch `k` begins: the step list marks its steps, its picture and its hint go to the glasses."""
        build = self._build
        first, last = BATCHES[k - 1]
        self._batch = k
        build.step = first - 1  # the list on the glasses marks the batch's steps as current; the steps before read as done
        build.span = last - first + 1
        build.hint = HINT_LAST if k == len(BATCHES) else HINT_BATCH
        build.show(k)
        await publish_build(build)
        sent = await send_picture(build, k)
        self._record.event("batch", n=k, steps=[first, last], **sent)
        self._record.event("hint", batch=k, text=build.hint)
        logger.info("report: batch %d of %d, steps %d to %d, picture %s", k, len(BATCHES), first, last, sent["name"])

    async def _reported(self, line: str, answering: str | None) -> None:
        """The brain gave the voice a line and said what it is: a report while the last batch is shown finishes the
        trial; a report in an earlier batch and anything else change nothing, the batch's hint standing for the batch.
        Nothing slow may be awaited here: the brain's look has BRAIN_TIMEOUT seconds in all (the run of 2026-11-09)."""
        build = self._build
        self._said += 1
        done = answering == REPORT and self._batch >= len(BATCHES) and not build.finished
        if done:
            build.step, build.span = len(build.guide.steps), 1  # finished: gpt/agent.py ends the call once the voice is quiet
            build.hint = ""
            self._record.event("build", finished=True, took_s=round(time.monotonic() - build.started, 1))
            logger.info("report: the last batch is reported; the trial is done")
            await publish_build(build)
        # `answer`, not `kind`: RunLog.event's first parameter is `kind`, and a `kind=` here raised a TypeError (2026-11-09)
        self._record.event("report", batch=self._batch, n=self._said, answer=answering, text=line, finished=done)
