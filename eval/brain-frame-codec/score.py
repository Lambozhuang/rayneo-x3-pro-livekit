"""Scores this study's replies against the shared labels; the sibling study's scorer pointed at this out/.

    uv run python score.py <pictures-thinking> [...]

The labels are ../brain-frame-quality/labels.toml, since the frames are the same; the rules, the colour table and the
tables printed are the sibling's (see its docstring).
"""

import sys
from pathlib import Path

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent / "brain-frame-quality"))
import score as base  # noqa: E402

base.out = here / "out"

if __name__ == "__main__":
    base.main(sys.argv[1:])
