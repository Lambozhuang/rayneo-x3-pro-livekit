"""Asks the brain's model to rate each photo's sharpness while describing the plate, twice per photo, over the codec
study's frames and real frames of two calls.

    cd backend/agent && uv run --no-sync python ../../eval/brain-blur-perception/probe.py [condition ...] [--passes=2]

Conditions and where their pictures come from (README):
    sq1080, hevc-v1000, hevc-v500, hevc-v250, hevc-v100   ../brain-frame-codec/out/<condition>/, the 41 frames of that study
    real-open, real-capped                                 out/<condition>/, REAL_N watch photos picked evenly from a call's
                                                           record (REAL_RUNS), copied there by this script
With no condition given, all seven are asked. Replies land in out/replies/<condition>-pass<n>/<id>.json, one per photo
and pass, with the parsed object, the raw text, the token counts and the timing; an existing reply is not asked again.

The call is the brain's as deployed: gpt-6.1-terra at reasoning effort low, the photo at detail high, 1080 px square,
one chat completion per photo with a strict JSON schema. The prompt is the sibling study's description of the plate
(eval/brain-frame-quality/probe.py PROMPT) with one question added: the photo's sharpness in three grades and whether
the studs on the plate can be counted. The sharpness grades are defined for the model in the prompt so that two runs
can be compared. The key is OPENAI_API_KEY from backend/.env.
"""

import asyncio
import base64
import csv
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from openai import AsyncOpenAI

here = Path(__file__).resolve().parent
root = here.parent.parent
out = here / "out"
import importlib.util  # noqa: E402

# the sibling study's probe, for its plate-description prompt and schema; loaded by path, since both files are named probe.py
_spec = importlib.util.spec_from_file_location("frame_quality_probe", here.parent / "brain-frame-quality" / "probe.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

MODEL = "gpt-6.1-terra"  # the brain as deployed (backend/.env on the lab PC: BRAIN_MODEL, BRAIN_EFFORT low, BRAIN_DETAIL high)
EFFORT = "low"
DETAIL = "high"
PARALLEL = 8
CODEC_CONDITIONS = ["sq1080", "hevc-v1000", "hevc-v500", "hevc-v250", "hevc-v100"]
REAL_RUNS = {  # condition -> the call whose watch photos stand for it, both at exposure -4 on the same desk
    "real-open": "20261104-123046-glasses-dfdff7e6",  # no network cap, 181 KB photos
    "real-capped": "20261104-103852-glasses-0013df82",  # 0.25 Mbps uplink cap, 124 KB photos
}
REAL_N = 36

SHARPNESS = """
"sharpness" grades the photo itself, not the build: "clear" when brick edges and studs are crisp, as a camera gives at full quality; "slightly blurry" when edges are soft or smeared but the studs on the plate can still be counted; "blurry" when compression blocks, smearing or softness hide the studs so they cannot be counted. "studs_countable" says whether the studs of the bricks on the plate can be counted in this photo."""

PROMPT = base.PROMPT + SHARPNESS

SCHEMA = json.loads(json.dumps(base.SCHEMA))
SCHEMA["properties"]["sharpness"] = {"type": "string", "enum": ["clear", "slightly blurry", "blurry"]}
SCHEMA["properties"]["studs_countable"] = {"type": "boolean"}
SCHEMA["required"] = ["bricks", "hands", "sharpness", "studs_countable"]


def load_key() -> None:
    env = root / "backend" / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENAI_API_KEY="):
            os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip()
            return
    sys.exit(f"no OPENAI_API_KEY in {env}")


def real_frames(condition: str) -> list[Path]:
    """REAL_N watch photos of the call, evenly spaced over the call, copied once into out/<condition>/."""
    dest = out / condition
    if dest.exists() and len(list(dest.glob("*.jpg"))) >= REAL_N:
        return sorted(dest.glob("*.jpg"))
    src = root / "logs" / REAL_RUNS[condition]
    photos = sorted(src.glob("watch*-s*.jpg"), key=lambda p: int(re.match(r"watch(\d+)-", p.name).group(1)))
    step = len(photos) / REAL_N
    picked = [photos[int(i * step)] for i in range(REAL_N)]
    dest.mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(picked):
        shutil.copy(p, dest / f"r{i:02d}-{p.stem}.jpg")
    return sorted(dest.glob("*.jpg"))


def frames_of(condition: str) -> list[Path]:
    if condition in REAL_RUNS:
        return real_frames(condition)
    ids = [r["id"] for r in csv.DictReader(open(here.parent / "brain-frame-codec" / "out" / "frames.csv"))]
    return [here.parent / "brain-frame-codec" / "out" / condition / f"{fid}.jpg" for fid in ids]


class Probe:
    def __init__(self) -> None:
        load_key()
        self._client = AsyncOpenAI()

    async def ask(self, photo: bytes) -> dict:
        t0 = time.perf_counter()
        resp = await self._client.chat.completions.create(
            model=MODEL, max_completion_tokens=4096, reasoning_effort=EFFORT,
            response_format={"type": "json_schema", "json_schema": {"name": "plate", "schema": SCHEMA, "strict": True}},
            messages=[{"role": "system", "content": PROMPT},
                      {"role": "user", "content": [
                          {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(photo).decode(),
                                                              "detail": DETAIL}},
                          {"type": "text", "text": base.ASK}]}],
        )
        text = (resp.choices[0].message.content or "").strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        u = resp.usage
        details = getattr(u, "completion_tokens_details", None)
        return {"parsed": parsed, "text": text, "model_ms": round((time.perf_counter() - t0) * 1000),
                "in": u.prompt_tokens, "out": u.completion_tokens,
                "thinking": getattr(details, "reasoning_tokens", None) if details else None,
                "stop": resp.choices[0].finish_reason}


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--"))
    passes = int(opts.get("passes", 2))
    conditions = args or CODEC_CONDITIONS + list(REAL_RUNS)
    probe = Probe()
    gate = asyncio.Semaphore(PARALLEL)
    jobs = []
    for cond in conditions:
        for n in range(1, passes + 1):
            dest = out / "replies" / f"{cond}-pass{n}"
            dest.mkdir(parents=True, exist_ok=True)
            for photo in frames_of(cond):
                jobs.append((cond, n, dest / f"{photo.stem}.json", photo))

    async def one(cond: str, n: int, target: Path, photo: Path) -> None:
        if target.exists():
            return
        data = photo.read_bytes()
        async with gate:
            r = await probe.ask(data)
        r.update({"id": photo.stem, "condition": cond, "pass": n, "photo_kb": len(data) // 1024, "model": MODEL,
                  "effort": EFFORT, "detail": DETAIL})
        target.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        p = r["parsed"] or {}
        print(f"{cond} pass{n} {photo.stem}: {p.get('sharpness', '?')}, studs {'countable' if p.get('studs_countable') else 'not'}, "
              f"{r['model_ms']} ms" + ("" if r["parsed"] is not None else " NOT JSON"))

    await asyncio.gather(*(one(*j) for j in jobs))
    print(f"{len(jobs)} photos asked; replies in {out.relative_to(root)}/replies/")


if __name__ == "__main__":
    asyncio.run(main())
