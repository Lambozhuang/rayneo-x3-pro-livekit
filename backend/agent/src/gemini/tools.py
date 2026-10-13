"""The one tool: set_progress, how far the build is.

A @function_tool: the framework sends its signature and docstring to the model
and runs it here when the model calls it. The docstring is the tool's rule book:
when to call it and when not to. On gemini-3.8-live tools run in the background
and the result is taken up when the model is idle; it states what was recorded
and nothing else, since the model takes any instruction in it as a new turn and
repeats what it already said. Only this call moves the build; the step list on
the glasses follows it (publish_build).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from livekit.agents import RunContext, function_tool

from guide import Build, publish_build
from runlog import RunLog

logger = logging.getLogger("rayneo-agent.tools")


@dataclass
class Call:
    """AgentSession.userdata: the run and its record."""

    build: Build
    record: RunLog
    tool_calls: int = 0


@function_tool()
async def set_progress(context: RunContext[Call], done: int) -> str:
    """Records how far the build is: the number of steps, counted from step 1, that the camera shows built right,
    from 0 to the number of the last step. It can go up by more than one, or down when an earlier step turns out
    wrong. The step list on the glasses follows it, so what you say should say the same, and progress recorded
    higher than the plate shows leaves the wearer building on a mistake. Call it only when the frame lets you tell
    and the number differs from the recorded progress; leave it out when part of the build is hidden or too small
    to judge, and when the wearer only says they are done without the frame showing it. The result only confirms
    what was recorded; it needs no reply.

    Args:
        done: how many steps, from step 1, are built right
    """
    call = context.userdata
    build, record = call.build, call.record
    call.tool_calls += 1
    n, total = call.tool_calls, len(build.guide.steps)
    if not isinstance(done, int) or not 0 <= done <= total:
        logger.warning("tool: #%d set_progress(%r): ignored, not between 0 and %d", n, done, total)
        record.event("tool", n=n, name="set_progress", done=done, ignored=True)
        return f"Not recorded: done must be a whole number from 0 to {total}. Still {build.where()}."
    before = build.step
    if not build.set_step(done):
        logger.info("tool: #%d set_progress(%d): unchanged, %d done", n, done, done)
        record.event("tool", n=n, name="set_progress", done=done, before=before, unchanged=True)
        return f"Progress unchanged: {build.where()}."
    logger.info("tool: #%d set_progress(%d): %d done -> %d done", n, done, before, done)
    if build.step > before:
        record.event("step", done=build.step, now=None if build.finished else build.step + 1)
    else:
        record.event("step", done=None, reopened=build.step + 1, now=build.step + 1)
    record.event("tool", n=n, name="set_progress", done=done, before=before)
    await publish_build(build)
    if build.finished:
        return f"Recorded: all {total} steps are done, the build is finished."
    return f"Recorded: {build.where()}."
