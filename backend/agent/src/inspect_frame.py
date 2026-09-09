"""Ask a Gemini model about saved frames, once per media resolution level.

    uv run --no-sync python src/inspect_frame.py --model gemini-3.8-flash frames/*-full.jpg
    uv run --no-sync python src/inspect_frame.py --model ... --levels low,ultra_high --question "..." a.jpg

Separates "the model cannot see it" from "the model was not given enough
pixels". The Live API shows video at a fixed low token budget per frame; this
sends the same frame through the ordinary generate_content path at low / medium
/ high / ultra_high (per-part `media_resolution`, Gemini 3 only) and prints the
answer and the image token count each time. If the answer only becomes right at
high or above, resolution was the problem. If it never does, it is the camera
(distance, focus, motion blur) or the model. Reads GOOGLE_API_KEY from the
environment / backend/.env like the agent does.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv
from google import genai
from google.genai import types

LEVELS = ["low", "medium", "high", "ultra_high"]

DEFAULT_QUESTION = (
    "List every LEGO piece you can see. For each one give its colour, its shape, "
    "and the exact number of studs (the round bumps) on top. If you cannot count "
    "the studs on a piece, say so rather than guessing."
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", nargs="+", help="JPEG files, e.g. the *-full.jpg written by FRAME_DUMP_DIR")
    ap.add_argument(
        "--model",
        default=os.environ.get("GEMINI_INSPECT_MODEL"),
        help="a non-live Gemini 3 model id; default $GEMINI_INSPECT_MODEL",
    )
    ap.add_argument("--levels", default="low,high,ultra_high", help=f"comma list from {','.join(LEVELS)}")
    ap.add_argument("--question", default=DEFAULT_QUESTION)
    args = ap.parse_args()

    load_dotenv()
    if not args.model:
        ap.error("--model or GEMINI_INSPECT_MODEL is required; the id is never hardcoded")
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        ap.error("GOOGLE_API_KEY is not set")
    levels = [lv.strip() for lv in args.levels.split(",") if lv.strip()]
    bad = [lv for lv in levels if lv not in LEVELS]
    if bad:
        ap.error(f"unknown level(s) {bad}; choose from {LEVELS}")

    # The SDK warns about automatic function calling on every plain
    # generate_content call; there are no tools here, so it is noise.
    logging.getLogger("google_genai").setLevel(logging.ERROR)
    client = genai.Client(api_key=api_key)
    print(f"model: {args.model}")
    print(f"question: {args.question}\n")

    for path in args.image:
        with open(path, "rb") as f:
            data = f.read()
        for level in levels:
            part = types.Part.from_bytes(data=data, mime_type="image/jpeg")
            part.media_resolution = types.PartMediaResolution(level=f"MEDIA_RESOLUTION_{level.upper()}")
            response = client.models.generate_content(model=args.model, contents=[part, args.question])
            usage = response.usage_metadata
            image_tokens = sum(
                d.token_count or 0
                for d in (usage.prompt_tokens_details or [])
                if d.modality == types.MediaModality.IMAGE
            )
            print(f"=== {path} @ {level}  image_tokens={image_tokens} ===")
            print((response.text or "").strip())
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
