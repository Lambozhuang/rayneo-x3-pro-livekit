"""Function tools available to the agent.

Plain @function_tool functions: the framework sends their signatures to the
model and runs them here when the model calls them. They are also the only
channel that reaches gemini-3.1-flash-live-preview mid-session (instructions
and chat context cannot be updated on that model), which is why the build
steps arrive this way rather than in the prompt. show_view and highlight_part
change what the reference model stream shows (render.py); they raise
StopResponse because there is nothing to say about a display change. Tools are
declared non-blocking (config.py): the model talks over them and takes the
result up when it is idle. look is the one that waits, for the frame it asked
for, so its result lands after the picture; end_call waits for the goodbye.
"""

import asyncio
import logging

from livekit.agents import RunContext, function_tool, get_job_context
from livekit.agents.llm import StopResponse

from guide import Build
from render import VIEWS

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
async def look(context: RunContext[Build]) -> str:
    """Get one fresh camera frame of what the wearer sees right now. Camera
    frames otherwise reach you only while the wearer is speaking, so call this
    before judging whether a step is built, whenever the wearer asks you to
    check something, and whenever you would otherwise be guessing from an old
    picture. Judge the frame that arrives after this call."""
    if context.userdata.request_look is None:
        return "No camera in this session."
    logger.info("look: requested")
    try:
        # Answer only once the frame has gone to the model, so the result
        # always lands after the picture it refers to.
        await asyncio.wait_for(context.userdata.request_look(), timeout=3)
    except asyncio.TimeoutError:
        logger.warning("look: no camera frame within 3 s")
        return "No frame came from the camera in three seconds; tell the wearer you cannot see right now."
    context.userdata.saw_frame()
    return "You now have a fresh frame; judge from it."


@function_tool()
async def step_done(context: RunContext[Build]) -> str:
    """Record that the current step is built, and get the next one. Call this
    last: after you have looked at the camera, said what you see, and it
    matches the step. It is refused unless you called look during this step
    within the last 20 seconds. The wearer saying they are done is a request
    to check, not a confirmation. Until this has been called the step is not
    done and you must not tell them to move on. The result is the next step,
    or that the build is finished."""
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
async def show_view(context: RunContext[Build], view: str) -> str:
    """Turn the reference model on the wearer's display. `view` is one of
    front, back, left, right, top, front-left, front-right (a fixed view), or
    spin to let it rotate again. Use it when the wearer asks to see a side, or
    when a fixed view shows where a brick goes better than the rotation."""
    model = context.userdata.model
    if model is None:
        return "There is no model display in this session."
    view = view.strip().lower().replace(" ", "-").replace("_", "-")
    if view != "spin" and view not in VIEWS:
        return f"Unknown view {view!r}. Use one of: spin, {', '.join(VIEWS)}."
    model.show(view)
    logger.info("model: view=%s", view)
    raise StopResponse()  # done; nothing to say about it


@function_tool()
async def highlight_part(context: RunContext[Build], step: int) -> str:
    """Highlight one step's brick in the reference model on the wearer's
    display: that brick in colour, the rest grey. `step` is the step number
    (1-based); 0 shows every brick in colour. The current step's brick is
    highlighted automatically whenever a step starts, so this is for pointing
    at another one, or at the whole build."""
    build = context.userdata
    if build.model is None:
        return "There is no model display in this session."
    if not 0 <= step <= len(build.guide.steps):
        return f"There is no step {step}; steps are 1 to {len(build.guide.steps)}."
    build.highlight(None if step == 0 else step - 1)
    logger.info("model: highlight %s", "none" if step == 0 else f"step {step}")
    raise StopResponse()  # done; nothing to say about it


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
