"""Asks the model about every frame of one condition of this study; the sibling study's probe pointed at this out/.

    uv run python probe.py <pictures> <thinking> [frame id ...] [--model=<id>]

Same prompt, schema, model and call as ../brain-frame-quality/probe.py, which this imports; the pictures come from this
directory's out/ (sq1080, h264-v500, hevc-v250, ...) and the replies land in its out/replies/<pictures>-<thinking>/.
"""

import asyncio
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent / "brain-frame-quality"))
import probe as base  # noqa: E402

base.here = here  # it names reply paths relative to this and finds backend/.env two levels up, as from the sibling
base.out = here / "out"

if __name__ == "__main__":
    asyncio.run(base.main())
