"""Function tools of the GPT path.

The backend model (gpt-6-luna, behind GPT-Live) calls these; the framework runs
them here and sends the result back, and the voice model speaks the outcome.
None of them lets a model declare a step done: check_step asks the vision model
(vision.py, through the watcher's cache, watch.py) and the code advances the
build only on a `built` verdict. Every tool that moves the build also pushes
the new position to the glasses.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass

from livekit.agents import RunContext, function_tool, get_job_context

from gpt.vision import Verdict
from gpt.watch import Watcher
from guide import Build
from render import VIEWS

logger = logging.getLogger("rayneo-agent.tools")


@dataclass
class Run:
    """One call's state, in AgentSession.userdata."""

    build: Build
    watch: Watcher
    look_image: bool = False  # GPT_LOOK_IMAGE: look also hands the frame itself to the backend


async def publish_build(build: Build) -> None:
    """The run's position to the glasses, as participant attributes (Build.attributes)."""
    await get_job_context().room.local_participant.set_attributes(build.attributes())


def _take_pending(run: Run) -> str:
    """A step the watcher advanced but the voice did not announce, once."""
    if run.watch.pending is None:
        return ""
    n, seen = run.watch.pending
    run.watch.pending = None
    return f"(Step {n} was found built moments ago: {seen} Tell the wearer it is right.) "


@function_tool()
async def get_step(context: RunContext[Run]) -> str:
    """Get the current build step: the part and what to tell the wearer. Call
    this before giving any instruction, whenever the wearer asks what to do,
    what comes next, or to repeat the step. Tell them only this step."""
    run = context.userdata
    return _take_pending(run) + run.build.describe()


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
    if pending := _take_pending(run):
        return pending + ("Then give the next step. " + build.describe() if not build.finished
                          else "That was the last step: the build is finished, congratulate them.")
    if build.finished:
        return "The build is already finished; there is nothing left to check."
    n = build.step + 1
    try:
        v = await run.watch.check()
    except asyncio.TimeoutError:
        logger.warning("check: no camera frame within 3 s")
        return "No camera frame arrived in three seconds. Tell the wearer you cannot see right now and to try again."
    except Exception:
        logger.exception("check: vision call failed")
        return "The camera check failed. Tell the wearer to try again in a moment."

    if v.state == "built":
        build.complete_step()  # logs the step timing; the code moves on, not the model
        run.watch.last = None
        await publish_build(build)
        if build.finished:
            return (
                f"Step {n} is built: {v.what_i_see} That was the last step. Tell the wearer it is "
                "right and that the build is finished, and congratulate them."
            )
        return (
            f"Step {n} is built: {v.what_i_see} Recorded; the build has moved on. Tell the wearer "
            f"in one sentence that it is right, then the next step. {build.describe()}"
        )
    if v.state == "not_built":
        return (
            f"Step {n} is not built as described. Seen: {v.what_i_see} Problem: {v.problem} "
            "Tell the wearer what to change in one sentence; the step stays open, check again when they say so."
        )
    return (
        f"Could not see well enough to judge step {n}. Seen: {v.what_i_see} Ask the wearer to hold "
        "the bricks up steady, closer to the camera, and check again."
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
        v = await run.watch.check(question)
    except asyncio.TimeoutError:
        logger.warning("look: no camera frame within 3 s")
        return "No camera frame arrived in three seconds. Tell the wearer you cannot see right now."
    except Exception:
        logger.exception("look: vision call failed")
        return "The camera check failed. Tell the wearer to try again in a moment."
    if run.look_image:
        _hand_frame_to_backend(context, v, question)
    return f"Seen: {v.what_i_see} Answer: {v.answer}"


def _hand_frame_to_backend(context: RunContext[Run], v: Verdict, question: str) -> None:
    """GPT_LOOK_IMAGE: the backend model sees the frame itself, as a user
    message queued before this tool's result (the raw Live API's
    response.item.create; verified in tmp/poc/gptlive_image.py). The frame
    then stays in the backend's conversation, so this is an experiment switch,
    not the default."""
    if not v.jpeg:
        return
    try:
        context.session.current_agent.duplex_session.send_event({
            "type": "response.item.create",
            "event_id": f"look_img_{int(time.time() * 1000)}",
            "item": {"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": f"The camera frame the wearer's question is about: {question}"},
                {"type": "input_image", "detail": "high",
                 "image_url": "data:image/jpeg;base64," + base64.b64encode(v.jpeg).decode()},
            ]},
        })
        logger.info("look: frame handed to the backend (%d bytes)", len(v.jpeg))
    except Exception:
        logger.exception("look: could not hand the frame to the backend")


@function_tool()
async def previous_step(context: RunContext[Run]) -> str:
    """Go back to the previous step. Use it when the wearer says the previous
    step was not actually finished or came out wrong. The result is that step."""
    run = context.userdata
    result = run.build.reopen_previous_step()
    run.watch.last = None
    run.watch.pending = None
    await publish_build(run.build)
    return result


@function_tool()
async def restart_build(context: RunContext[Run]) -> str:
    """Start the build over from the first step. Only when the wearer asks to
    start again."""
    run = context.userdata
    result = run.build.restart()
    run.watch.last = None
    run.watch.pending = None
    await publish_build(run.build)
    return result


@function_tool()
async def show_view(context: RunContext[Run], view: str) -> str:
    """Turn the reference model on the wearer's display. `view` is one of
    front, back, left, right, top, front-left, front-right (a fixed view), or
    spin to let it rotate again. Use it when the wearer asks to see a side, or
    when a fixed view shows where a brick goes better than the rotation."""
    model = context.userdata.build.model
    if model is None:
        return "There is no model display in this session."
    view = view.strip().lower().replace(" ", "-").replace("_", "-")
    if view != "spin" and view not in VIEWS:
        return f"Unknown view {view!r}. Use one of: spin, {', '.join(VIEWS)}."
    model.show(view)
    logger.info("model: view=%s", view)
    return f"The display now shows the {view} view. Nothing to say about it beyond a word."


@function_tool()
async def highlight_part(context: RunContext[Run], step: int) -> str:
    """Highlight one step's brick in the reference model on the wearer's
    display: that brick in colour, the rest grey. `step` is the step number
    (1-based); 0 shows every brick in colour. The current step's brick is
    highlighted automatically whenever a step starts, so this is for pointing
    at another one, or at the whole build."""
    build = context.userdata.build
    if build.model is None:
        return "There is no model display in this session."
    if not 0 <= step <= len(build.guide.steps):
        return f"There is no step {step}; steps are 1 to {len(build.guide.steps)}."
    build.highlight(None if step == 0 else step - 1)
    logger.info("model: highlight %s", "none" if step == 0 else f"step {step}")
    return "Highlighted on the display. Nothing to say about it beyond a word."


@function_tool()
async def end_call(context: RunContext[Run]) -> str:
    """End the call. Use it when the wearer says goodbye or asks to stop."""
    build = context.userdata.build
    logger.info("end_call: run=%s at step %d/%d", build.run, build.step + 1, len(build.guide.steps))
    # The goodbye is spoken after this result reaches the backend and the voice
    # model, so the room cannot close here. A task waits for whatever the voice
    # is saying now ("one moment") to end, then for the goodbye to start and
    # end, and closes the room; the glasses return to their connect screen.
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
