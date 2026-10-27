"""Re-encodes the recording at the study's bitrates and cuts the study's frames from each result.

    uv run python encode.py <recording dir> <side> [kbps ...]

Scales the whole frame to <side> wide (720x1280 or 1080x1920, which is the recording as it is) and encodes it with this PC's hardware encoder, h264_amf on the AMD Radeon 860M,
set as WebRTC sends video: low-latency usage, constant bitrate with a one-second buffer, no B-frames, a keyframe
every second, high profile, 15 fps with every input frame kept and its timestamp passed through, so a frame's index
in the result is its index in out/frames.csv. Then decodes each result in software (H.264 decoding is exact, so the
decoder does not matter), takes the frames of out/frames.csv, cuts the bottom square and writes it as JPEG quality 85,
which is the photo the brain would make of such a frame (Image.thumbnail to 768 or 1080 leaves 720 as it is; at 1080
the brain's hand-over photo is this square). Writes:

    out/v<kbps>-<side>.mp4      the recording scaled and encoded at <kbps> kilobits a second, for each in KBPS
    out/v<kbps>-<side>/<id>.jpg the brain's photo from it
    out/sq<side>/<id>.jpg       the same frames scaled the same way and not encoded, the upper reference of the
                                bitrate group, written only when pick_frames.py has not already made that side

The AMF encoder takes the keyframe interval as -force_key_frames rather than -g, which its low-latency usage ignores.
The glasses encode with a Qualcomm encoder, not this one; the result holds for the bitrate, not for the encoder.
"""

import csv
import subprocess
import sys
from pathlib import Path

from PIL import Image

KBPS = tuple(int(k) for k in sys.argv[3:]) or (2000, 1000, 500)  # the study's three, or the ones named
QUALITY = 85

here = Path(__file__).resolve().parent
out = here / "out"
rec = Path(sys.argv[1])
src = rec / "video.mp4"
SIDE = int(sys.argv[2])

SCALE = f"scale={SIDE}:{SIDE * 16 // 9}"
ENCODER = ["-c:v", "h264_amf", "-usage", "lowlatency", "-rc", "cbr", "-bf", "0", "-profile:v", "high",
           "-force_key_frames", "expr:gte(t,n_forced)", "-forced_idr", "1"]

rows = list(csv.DictReader(open(out / "frames.csv")))
ids = [r["id"] for r in rows]
pick = "+".join(f"eq(n\\,{r['index']})" for r in rows)


def encode(kbps: int) -> Path:
    video = out / f"v{kbps}-{SIDE}.mp4"
    rate = f"{kbps}k"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-an", "-vf", SCALE, "-fps_mode", "passthrough",
                    *ENCODER, "-b:v", rate, "-maxrate", rate, "-bufsize", rate, str(video)], check=True)
    return video


def squares(video: Path, name: str) -> None:
    """Decodes the picked frames of `video`, cuts the bottom square of each and writes out/<name>/<id>.jpg."""
    tmp = out / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    for old in tmp.glob("*.png"):
        old.unlink()
    vf = f"select='{pick}',{SCALE}" if video == src else f"select='{pick}'"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", vf, "-fps_mode", "vfr",
                    str(tmp / "%03d.png")], check=True)
    pngs = sorted(tmp.glob("*.png"))
    assert len(pngs) == len(ids), f"{len(pngs)} frames decoded from {video.name}, {len(ids)} expected"
    dest = out / name
    dest.mkdir(exist_ok=True)
    for fid, png in zip(ids, pngs):
        img = Image.open(png).convert("RGB")
        wd, ht = img.size
        assert (wd, ht) == (SIDE, SIDE * 16 // 9), f"{png.name} is {wd}x{ht}"
        img.crop((0, ht - wd, wd, ht)).save(dest / f"{fid}.jpg", "JPEG", quality=QUALITY)
    print(f"{len(pngs)} squares in {dest.relative_to(here)}")


if not (out / f"sq{SIDE}").exists():
    squares(src, f"sq{SIDE}")
for kbps in KBPS:
    video = encode(kbps)
    size = video.stat().st_size
    secs = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                 str(video)], capture_output=True, text=True, check=True).stdout)
    print(f"{video.name}: {size / 1e6:.1f} MB over {secs:.0f} s, {size * 8 / secs / 1e3:.0f} kbps")
    squares(video, f"v{kbps}-{SIDE}")
