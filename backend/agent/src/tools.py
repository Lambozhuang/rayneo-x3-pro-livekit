"""Function tools available to the agent."""

import logging

from livekit.agents import RunContext, function_tool

logger = logging.getLogger("rayneo-agent.tools")


@function_tool()
async def remember_note(context: RunContext, note: str) -> str:
    """Save a short note so the wearer can recall it later.

    Use this when the wearer explicitly asks you to remember something, like
    where they parked or something to pick up on the way home.

    Args:
        note: The thing to remember, in the wearer's own words.
    """
    # Placeholder. This exists to prove tool calling works end to end; notes go
    # to the log and nowhere else.
    logger.info("remember_note fired: %s", note)
    return f"Saved: {note}"
