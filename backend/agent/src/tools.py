"""Function tools available to the agent.

Plain @function_tool functions: the framework sends their signatures to the
model and runs them here when the model calls them. They are also the only
channel that reaches gemini-3.1-flash-live-preview mid-session (instructions
and chat context cannot be updated on that model), which is why the build
steps arrive this way rather than in the prompt. On 3.1 the model waits
silently while a tool runs, so nothing slow belongs here; these finish in
microseconds, except end_call, which waits for the goodbye to play out.
"""

import logging
from typing import Literal

from livekit.agents import RunContext, function_tool, get_job_context
from pydantic import BaseModel, Field

from guide import Brick, Build

logger = logging.getLogger("rayneo-agent.tools")


class SeenBrick(BaseModel):
    """One brick on the baseplate, as counted in the camera image."""

    color: str = Field(description="The colour as you see it, e.g. blue, white, tan, red.")
    studs_wide: int = Field(description="Studs along the short side, counted one by one.")
    studs_long: int = Field(description="Studs along the long side, counted one by one.")
    orientation: Literal["horizontal", "vertical"] = Field(
        description="Direction of the long side from the wearer's point of view."
    )
    position: str = Field(
        description="Where it sits relative to the other bricks: rows or columns apart, "
        "which ends line up, touching or not."
    )


@function_tool()
async def get_step(context: RunContext[Build]) -> str:
    """Get the current build step: the part, what to tell the wearer, and what
    the finished step looks like. Call this before giving any instruction, and
    whenever the wearer asks what to do or what comes next.
    """
    return context.userdata.describe()


@function_tool()
async def step_done(context: RunContext[Build], bricks: list[SeenBrick]) -> str:
    """Call when the wearer says the step is done. Look at the camera image
    and list every brick on the baseplate with its studs counted. The result
    tells you whether the right bricks are there and what else to check.

    Args:
        bricks: Every brick currently on the baseplate, one entry each.
    """
    return context.userdata.observe(
        [Brick.seen(b.color, b.studs_wide, b.studs_long, b.orientation) for b in bricks],
        [b.position for b in bricks],
    )


@function_tool()
async def confirm_step(context: RunContext[Build], matches: bool, differences: str) -> str:
    """Give your verdict after step_done confirmed the bricks and told you what
    else the step requires. The step only advances if it matches.

    Args:
        matches: True only if what you see satisfies every point of the requirement.
        differences: What differs, or an empty string if nothing does.
    """
    return context.userdata.confirm(matches, differences)


@function_tool()
async def restart_build(context: RunContext[Build]) -> str:
    """Start the build over from the first step. Only when the wearer asks to
    start again."""
    return context.userdata.restart()


@function_tool()
async def end_call(context: RunContext[Build]) -> str:
    """End the call. Use it when the wearer says goodbye or asks to stop."""
    build = context.userdata
    logger.info(
        "end_call: run=%s at step %d/%d", build.run, build.step + 1, len(build.guide.steps)
    )
    # Let whatever the model is saying finish, then close the room. The
    # glasses are disconnected and return to their connect screen.
    await context.wait_for_playout()
    await get_job_context().delete_room()
    return "The call has ended."
