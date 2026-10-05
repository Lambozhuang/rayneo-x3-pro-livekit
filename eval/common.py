"""Shared by the eval scripts: paths of the recorded run, truth loading, frame list, plate mask, image encoding.

FRAMES is the folder the scripts read frames from; set_frames("frames_1080p15") switches every script to the derived
call-quality frames. Results go under RESULTS/<route>: vlm (routes B/C, vlm_judge.py), cv (route D, cv_judge.py),
gate (gate_eval.py); replays sit next to the judge they used.
"""
from __future__ import annotations

import io
import json
import sys
import tomllib
from pathlib import Path

import numpy as np
from PIL import Image

AGENT_SRC = Path(__file__).resolve().parent.parent / "backend" / "agent" / "src"
sys.path.insert(0, str(AGENT_SRC))
from gate import plate_bbox  # noqa: E402,F401  (the agent's code; re-exported for the eval scripts)
from judge_cv import components  # noqa: E402,F401

ROOT = Path(__file__).resolve().parent
TRUCK = ROOT / "truck"
RUN = TRUCK / "run1"
FRAMES = RUN / "frames"
RESULTS = TRUCK / "results"  # subfolders vlm / cv / gate
# The task the recording follows: the agent's own guide file, so eval and agent share one layout.
TASK = ROOT.parent / "backend" / "agent" / "guides" / "truck" / "task.toml"
SHEETS = RUN / "sheets"
CLIP_ORDER = ["run1_part1", "run1_part2_p1", "run1_part2_p2"]


def set_frames(name: str | None):
    """Switch the frame source for every script (None = the full-resolution frames)."""
    global FRAMES
    FRAMES = RUN / (name or "frames")


def frames_tag() -> str:
    """'' for the full-resolution frames, '_1080p15' for frames_1080p15, used in result file names."""
    return "" if FRAMES.name == "frames" else "_" + FRAMES.name.replace("frames_", "")


def load():
    """(steps, events): steps are the task.toml [[steps]] as dicts with a 1-based "step" added
    (keys: step, part, name, say, color, cells, where, checks); events is truck/events.json."""
    with TASK.open("rb") as f:
        task = tomllib.load(f)
    steps = [{"step": i, **s} for i, s in enumerate(task["steps"], 1)]
    events = json.loads((TRUCK / "events.json").read_text(encoding="utf-8"))
    return steps, events


def tkey(clip: str, sec: float) -> tuple[int, float]:
    return CLIP_ORDER.index(clip), sec


def frame_list() -> list[tuple[str, int]]:
    out = []
    for clip in CLIP_ORDER:
        for p in sorted((FRAMES / clip).glob("*.jpg")):
            out.append((clip, int(p.stem) - 1))
    return out


def to_jpeg(img: Image.Image, q: int = 90) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=q)
    return buf.getvalue()


def to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def task() -> dict:
    """The raw task file (title, plate, colours, steps)."""
    with TASK.open("rb") as f:
        return tomllib.load(f)
