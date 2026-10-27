"""Picks the study's frames from the recording and cuts them as the brain's photo is cut.

    uv run python pick_frames.py <recording dir> [every]

Takes every `every`-th frame of video.mp4 (default 86, about 40 frames of the 3433) and writes:

    out/frames.csv          one line per frame: id, its index in the video (0-based), seconds into the recording,
                            and the glasses' wall clock when it arrived (video.csv), so a frame can be placed in
                            the call's record
    out/frames/<id>.png     the frame as decoded, 1080x1920 after the MP4's rotation, lossless
    out/sq<side>/<id>.jpg   the frame as the brain gets it: the bottom 1080x1080 square, Image.thumbnail to the
                            side, JPEG quality 85 (backend/agent/src/frames.py bottom_square, gpt/brain.py _jpeg),
                            for each side in SIDES

The recording has every camera frame (video.csv: 0 skipped), so video index n is video.csv line n+1.
"""

import csv
import subprocess
import sys
from pathlib import Path

from PIL import Image

SIDES = (1080, 768, 512, 384)
QUALITY = 85

here = Path(__file__).resolve().parent
out = here / "out"
rec = Path(sys.argv[1])
every = int(sys.argv[2]) if len(sys.argv) > 2 else 86

frames = out / "frames"
frames.mkdir(parents=True, exist_ok=True)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(rec / "video.mp4"),
                "-vf", f"select='not(mod(n\\,{every}))'", "-fps_mode", "vfr",
                str(frames / "%03d.png")], check=True)
pngs = sorted(frames.glob("*.png"))

rows = list(csv.DictReader(open(rec / "video.csv")))
assert all(r["recorded"] == "1" for r in rows), "a skipped frame breaks the index mapping"
t0 = int(rows[0]["arrived_ms"])
with open(out / "frames.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["id", "index", "t_s", "arrived_ms"])
    for k, png in enumerate(pngs):
        n = k * every
        fid = f"f{k:02d}"
        png = png.rename(frames / f"{fid}.png")
        arrived = int(rows[n]["arrived_ms"])
        w.writerow([fid, n, f"{(arrived - t0) / 1000:.1f}", arrived])
        img = Image.open(png).convert("RGB")
        wd, ht = img.size
        s = min(wd, ht)
        square = img.crop(((wd - s) // 2, ht - s, (wd - s) // 2 + s, ht))
        for side in SIDES:
            d = out / f"sq{side}"
            d.mkdir(exist_ok=True)
            im = square.copy()
            im.thumbnail((side, side))
            im.save(d / f"{fid}.jpg", "JPEG", quality=QUALITY)
print(f"{len(pngs)} frames, every {every}th, squares at {SIDES}")
