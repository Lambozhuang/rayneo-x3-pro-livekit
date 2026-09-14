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

from livekit.agents import RunContext, function_tool, get_job_context

from guide import Build

logger = logging.getLogger("rayneo-agent.tools")


@function_tool()
async def get_step(context: RunContext[Build]) -> str:
    """Get the current build step: the part, what to tell the wearer, and what
    the finished step looks like. Call this before giving any instruction, and
    whenever the wearer asks what to do or what comes next.
    """
    return context.userdata.describe()


@function_tool()
async def step_done(context: RunContext[Build], observation: str) -> str:
    """Call when the wearer says the step is done. Look at the camera image
    first and describe what is on the baseplate. The result tells you what the
    step requires so you can compare.

    Args:
        observation: What you see right now: each brick's colour, size and
            orientation, and where it sits relative to the other bricks (which
            ends line up, how many rows apart, left or right, touching or not).
    """
    return context.userdata.observe(observation)


@function_tool()
async def confirm_step(context: RunContext[Build], matches: bool, differences: str) -> str:
    """Give your verdict after step_done showed you what the step requires.
    The step only advances if it matches.

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
