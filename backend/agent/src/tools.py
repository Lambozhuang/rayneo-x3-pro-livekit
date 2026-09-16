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


async def publish_build(build: Build) -> None:
    """Push the run's position to the glasses as participant attributes; see
    Build.attributes. Called at start and after every tool that moves it."""
    await get_job_context().room.local_participant.set_attributes(build.attributes())


@function_tool()
async def get_step(context: RunContext[Build]) -> str:
    """Get the current build step: the part and what to tell the wearer. Call
    this before giving any instruction, whenever the wearer asks what to do
    or what comes next, and whenever you are unsure which step you are on.
    """
    return context.userdata.describe()


@function_tool()
async def step_done(context: RunContext[Build]) -> str:
    """Record that the current step is built, and get the next one. Call this
    last: after you have looked at the camera, said what you see, and it
    matches the step. The wearer saying they are done is a request to check,
    not a confirmation. Until this has been called the step is not done and
    you must not tell them to move on. The result is the next step, or that
    the build is finished."""
    result = context.userdata.complete_step()
    await publish_build(context.userdata)
    return result


@function_tool()
async def reopen_previous_step(context: RunContext[Build]) -> str:
    """Go back to the previous step. Use it when a step was marked done too
    early: the wearer says it was not finished, or you can now see it is not
    built as instructed. The result is that step again."""
    result = context.userdata.reopen_previous_step()
    await publish_build(context.userdata)
    return result


@function_tool()
async def restart_build(context: RunContext[Build]) -> str:
    """Start the build over from the first step. Only when the wearer asks to
    start again."""
    result = context.userdata.restart()
    await publish_build(context.userdata)
    return result


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
