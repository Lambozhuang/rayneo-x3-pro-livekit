"""The task as the GPT and Realtime paths describe it to their models: the build, the plate, the direction words and
the steps, from the one task file. gpt/prompts.py and realtime/prompts.py put their own rules around it; gpt/moments.py
takes the direction words alone.
"""

from guide import Guide

# How positions and sizes are described, for every model that sees the photo. The voice does not get this: it only
# repeats the steps' words, and told the geometry it read it out ("up and down", a home run of 2026-11-06).
DIRECTIONS = (
    "Positions are described on the plate as the user sees it, like a picture lying in front of them: up is toward the "
    "far edge (the top of the photo), down toward the near edge, left and right are the user's. Every brick lies flat; a "
    "vertical brick has its long side running up and down, a horizontal one left and right. A brick's size is its studs "
    "across by along, such as 1x6 or 2x6; count both before you say a brick is the one a step names."
)

# What the user is building; the word for the person is "the user" in every model's prompt.
TASK = """<task>
The user is building "{title}": flat LEGO bricks on a green {plate}x{plate} baseplate that is never rotated, placed one at a time in the order below.

{directions}

Each step names its brick and where it goes.
<steps>
{steps}
</steps>
</task>"""


def steps_text(guide: Guide, indent: str = "") -> str:
    return "\n".join(f"{indent}{i}. {s.brick}: {s.place}" for i, s in enumerate(guide.steps, 1))


def task_block(guide: Guide) -> str:
    return TASK.format(title=guide.title, plate=guide.plate, directions=DIRECTIONS, steps=steps_text(guide))
