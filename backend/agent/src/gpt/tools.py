"""The two tools of the GPT path.

GPT-Live has no tool channel of its own; tools reach it through the backend
model it delegates to. The voice model knows the steps (prompts.py) and gets
the camera's confirmed changes as context (watch.py); between those it cannot
look for itself, so when the wearer asks it to, check_now fetches the camera's
verdict on a fresh frame. And hanging up, which only a tool can do.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from livekit.agents import RunContext, function_tool, get_job_context

from gpt.watch import Watch
from guide import Build

logger = logging.getLogger("rayneo-agent.tools")


@dataclass
class Run:
    """One call's state, in AgentSession.userdata."""

    build: Build
    watch: Watch


async def publish_build(build: Build) -> None:
    """The run's position to the glasses, as participant attributes (Build.attributes)."""
    await get_job_context().room.local_participant.set_attributes(build.attributes())


@function_tool()
async def check_now(context: RunContext[Run]) -> str:
    """What the camera sees right now: how many steps are done and whether a
    brick is placed wrongly. Call it when the wearer asks you to look, to
    check, or whether something is right. Takes a few seconds."""
    return await context.userdata.watch.check_now()


@function_tool()
async def end_call(context: RunContext[Run]) -> str:
    """End the call. Only when the wearer says goodbye or asks to stop."""
    build = context.userdata.build
    logger.info("end_call: run=%s at step %d/%d", build.run, build.step + 1, len(build.guide.steps))
    # The goodbye is spoken after this result reaches the backend and the voice
    # model, so the room cannot close here. A task waits for whatever the voice
    # is saying now to end, then for the goodbye to start and end, and closes
    # the room; the glasses return to their connect screen.
    await context.userdata.watch.stop()
    asyncio.create_task(_close_after_goodbye(context.session), name="close_after_goodbye")
    return "Say goodbye to the wearer now, in one short sentence; the call closes when you have."


async def _close_after_goodbye(session, start_within: float = 8.0, cap: float = 20.0) -> None:
    t0 = time.monotonic()

    async def until(state_is_speaking: bool, limit: float) -> None:
        while (session.agent_state == "speaking") != state_is_speaking and time.monotonic() - t0 < limit:
            await asyncio.sleep(0.05)

    await until(False, start_within)  # whatever is being said now
    await until(True, start_within)  # the goodbye starts
    await until(False, cap)  # and ends
    await asyncio.sleep(0.5)  # the tail of the audio reaching the glasses
    logger.info("end_call: closing the room after %.1fs", time.monotonic() - t0)
    await get_job_context().delete_room()
