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

from guide import Brick, Build, Placement

logger = logging.getLogger("rayneo-agent.tools")


class SeenBrick(BaseModel):
    """One brick on the baseplate, as counted in the camera image."""

    color: str = Field(description="The colour as you see it, e.g. blue, white, tan, red.")
    studs_wide: int = Field(description="Studs along the short side, counted one by one.")
    studs_long: int = Field(description="Studs along the long side, counted one by one.")
    orientation: Literal["horizontal", "vertical"] = Field(
        description="Direction of the long side from the wearer's point of view."
    )
    relative_to: str = Field(
        description="Colour of the other brick you measured this one against, "
        "or none if it is the only brick on the baseplate."
    )
    side: Literal["above", "below", "left", "right", "none"] = Field(
        description="Which side of that other brick this one is on, from the wearer's point of view."
    )
    gap: int = Field(
        description="Empty rows or columns of studs between this brick and that other "
        "brick, counted; 0 if they touch."
    )
    aligned: Literal["left", "right", "top", "bottom", "both", "none"] = Field(
        description="Which ends of the two bricks line up in the same row or column, "
        "if any."
    )


@function_tool()
async def get_step(context: RunContext[Build]) -> str:
    """Get the current build step: the part and what to tell the wearer. Call
    this before giving any instruction, whenever the wearer asks what to do
    or what comes next, and whenever you are unsure which step you are on.
    """
    return context.userdata.describe()


@function_tool()
async def step_done(context: RunContext[Build], bricks: list[SeenBrick]) -> str:
    """Call when the wearer says the step is done. Look at the camera image
    and list every brick on the baseplate with its studs counted and its
    position relative to another brick. The result says whether the step is
    complete and, if not, what is off.

    Args:
        bricks: Every brick currently on the baseplate, one entry each.
    """
    return context.userdata.observe(
        [Brick.seen(b.color, b.studs_wide, b.studs_long, b.orientation) for b in bricks],
        [Placement(b.relative_to.strip().lower(), b.side, b.gap, b.aligned) for b in bricks],
    )


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
