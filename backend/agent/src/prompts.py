"""The task as both architectures describe it to their models: the build, the
plate, the direction words and the steps, from the one task file. gpt/prompts.py
and gemini/prompts.py put their own rules around it.
"""

from guide import Guide

# What the wearer is building and how positions are described. The same words
# for the brain (GPT path) and for Gemini, so a judgement of the same plate
# starts from the same conventions.
TASK = """<task>
The wearer is building "{title}": flat LEGO bricks on a green {plate}x{plate} baseplate that is never rotated, placed one at a time in the order below.

Positions are described on the plate as the wearer sees it, like a picture lying in front of them: up is toward the far edge (the top of the photo), down toward the near edge, left and right are the wearer's. Every brick lies flat; a vertical brick has its long side running up and down, a horizontal one left and right.

A brick's size is its studs across by along, such as 1x6 or 2x6; count both before you say a brick is the one a step names.

Each step names its brick and where it goes. The voice gives a step in two parts: first which brick to find, then, once the wearer has it, where it goes. The wearer may show you the brick in their hand before placing it, or just place it.
<steps>
{steps}
</steps>
</task>"""


def steps_text(guide: Guide, indent: str = "") -> str:
    return "\n".join(f"{indent}{i}. {s.brick}: {s.place}" for i, s in enumerate(guide.steps, 1))


def task_block(guide: Guide) -> str:
    return TASK.format(title=guide.title, plate=guide.plate, steps=steps_text(guide))
