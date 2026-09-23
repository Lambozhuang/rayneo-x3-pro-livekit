"""Function tools of the GPT path.

The backend model (gpt-6-luna, behind GPT-Live) calls these; the framework runs
them here and sends the result back, and the voice model speaks the outcome.
None of them lets a model declare a step done: check_step asks the vision model
(vision.py) and the code advances the build only on a `built` verdict. Every
tool that moves the build also pushes the new position to the glasses.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from livekit.agents import RunContext, function_tool, get_job_context

from gpt.vision import VisionCheck
from guide import Build

logger = logging.getLogger("rayneo-agent.tools")


@dataclass
class Run:
    """One call's state, in AgentSession.userdata: the build and its checker."""

    build: Build
    vision: VisionCheck


async def publish_build(build: Build) -> None:
    """The run's position to the glasses, as participant attributes (Build.attributes)."""
    await get_job_context().room.local_participant.set_attributes(build.attributes())


@function_tool()
async def get_step(context: RunContext[Run]) -> str:
    """Get the current build step: the part and what to tell the wearer. Call
    this before giving any instruction, whenever the wearer asks what to do,
    what comes next, or to repeat the step. Tell them only this step."""
    return context.userdata.build.describe()


@function_tool()
async def check_step(context: RunContext[Run]) -> str:
    """Look through the camera and check whether the current step is built.
    Call it when the wearer says the step is done, asks whether it is right, or
    asks you to check. The result says what the camera shows and the verdict.
    When the step is built it is recorded here and the next step is returned;
    you cannot mark a step done yourself, and the wearer saying "done" is a
    request to check, not a confirmation."""
    run = context.userdata
    build = run.build
    if build.finished:
        return "The build is already finished; there is nothing left to check."
    n = build.step + 1
    try:
        v = await run.vision.check(build)
    except asyncio.TimeoutError:
        logger.warning("check: no camera frame within 3 s")
        return "No camera frame arrived in three seconds. Tell the wearer you cannot see right now and to try again."
    except Exception:
        logger.exception("check: vision call failed")
        return "The camera check failed. Tell the wearer to try again in a moment."

    if v.state == "built":
        build.complete_step()  # logs the step timing; the code moves on, not the model
        await publish_build(build)
        if build.finished:
            return (
                f"Step {n} is built: {v.what_i_see} That was the last step. Tell the wearer it is "
                "right and that the build is finished, and congratulate them."
            )
        return (
            f"Step {n} is built: {v.what_i_see} Recorded; the build has moved on. Tell the wearer "
            f"it is right, then give them the next step. {build.describe()}"
        )
    if v.state == "not_built":
        return (
            f"Step {n} is not built as described. Seen: {v.what_i_see} Problem: {v.problem} "
            "Tell the wearer what to change; the step stays open, check again when they say so."
        )
    if v.state == "in_progress":
        return (
            f"Step {n} is not finished yet. Seen: {v.what_i_see} Still to do: {v.problem} Tell the "
            "wearer what is left and to say when it is done; then check again."
        )
    return (
        f"Could not see well enough to judge step {n}. Seen: {v.what_i_see} Ask the wearer to hold "
        "the bricks closer to the camera and check again."
    )


@function_tool()
async def look(context: RunContext[Run], question: str) -> str:
    """Look through the camera to answer a question about what the wearer is
    holding or doing, without judging the step: which brick this is, how many
    studs, where something sits. `question` is one concrete question in the
    wearer's terms. The result is what the camera shows and the answer."""
    run = context.userdata
    if run.build.finished:
        return "The build is finished; there is no step to relate the picture to."
    try:
        v = await run.vision.check(run.build, question)
    except asyncio.TimeoutError:
        logger.warning("look: no camera frame within 3 s")
        return "No camera frame arrived in three seconds. Tell the wearer you cannot see right now."
    except Exception:
        logger.exception("look: vision call failed")
        return "The camera check failed. Tell the wearer to try again in a moment."
    return f"Seen: {v.what_i_see} Answer: {v.answer}"


@function_tool()
async def previous_step(context: RunContext[Run]) -> str:
    """Go back to the previous step. Use it when the wearer says the previous
    step was not actually finished or came out wrong. The result is that step."""
    build = context.userdata.build
    result = build.reopen_previous_step()
    await publish_build(build)
    return result


@function_tool()
async def restart_build(context: RunContext[Run]) -> str:
    """Start the build over from the first step. Only when the wearer asks to
    start again."""
    build = context.userdata.build
    result = build.restart()
    await publish_build(build)
    return result


@function_tool()
async def end_call(context: RunContext[Run]) -> str:
    """End the call. Use it when the wearer says goodbye or asks to stop."""
    build = context.userdata.build
    logger.info("end_call: run=%s at step %d/%d", build.run, build.step + 1, len(build.guide.steps))
    # The voice model is saying goodbye while this runs and cannot be told to
    # wait; give its speech up to a moment to start and let it finish, then
    # close the room. The glasses return to their connect screen.
    t0 = time.monotonic()
    while context.session.agent_state != "speaking" and time.monotonic() - t0 < 2.0:
        await asyncio.sleep(0.05)
    while context.session.agent_state == "speaking" and time.monotonic() - t0 < 10.0:
        await asyncio.sleep(0.05)
    await get_job_context().delete_room()
    return "The call has ended."
