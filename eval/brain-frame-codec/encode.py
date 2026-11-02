"""Re-encodes the recording as the glasses' encoder does, in H.264 or H.265, and cuts the study's frames from each result.

    uv run python encode.py <recording dir> <h264|hevc> <kbps> [kbps ...]

Scales nothing: the frame stays 1080x1920 as the glasses send it. Encodes with this PC's hardware encoder (h264_amf or
hevc_amf on the AMD Radeon 860M) set as libwebrtc sets MediaCodec on the glasses (README.md of the repo, the camera
paragraph): constant bitrate with a one-second buffer, no B-frames, one keyframe at the start and none after, low-latency
usage, and the profile the glasses negotiate, H.264 constrained baseline or H.265 Main. 15 fps with every input frame
kept and its timestamp passed through, so a frame's index in the result is its index in frames.csv. Then decodes each
result in software (H.264 and H.265 decoding are exact, so the decoder does not matter), takes the frames of
../brain-frame-quality/out/frames.csv, which this study shares, cuts the bottom 1080x1080 square and writes it as JPEG
quality 85, the brain's hand-over photo of such a frame. Writes:

    out/frames.csv                  a copy of the shared frame list, so probe.py and score.py find it here
    out/<codec>-v<kbps>.mp4         the recording encoded at <kbps> kilobits a second
    out/<codec>-v<kbps>/<id>.jpg    the brain's photo from it
    out/sq1080/<id>.jpg             the same frames from the recording as it is, copied from the sibling study, the
                                    upper reference

The AMF encoders take the keyframe plan as -force_key_frames rather than -g, which their low-latency usage ignores; the
script counts the keyframes in each result and prints them, so a stray periodic one would show. The glasses encode with a
Qualcomm encoder, not this one, and WebRTC drops frames when the encoder overshoots, which a file encode never does; the
result holds for the bitrate and the codec, not for the encoder.
"""

import csv
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

QUALITY = 85
SIDE = 1080
CODECS = {
    "h264": ["-c:v", "h264_amf", "-profile:v", "constrained_baseline", "-bf", "0"],
    "hevc": ["-c:v", "hevc_amf", "-profile:v", "main"],
}
COMMON = ["-usage", "lowlatency", "-rc", "cbr", "-g", "100000", "-force_key_frames", "expr:eq(n,0)", "-forced_idr", "1"]
# -g is ignored by h264_amf's low-latency usage but honoured by hevc_amf, whose default of 250 frames would add a keyframe
# every 17 s; the forced first frame is the one keyframe either way.

here = Path(__file__).resolve().parent
out = here / "out"
shared = here.parent / "brain-frame-quality" / "out"
rec = Path(sys.argv[1])
src = rec / "video.mp4"
codec = sys.argv[2]
if codec not in CODECS:
    sys.exit(f"codec must be one of {', '.join(CODECS)}")
kbps_list = [int(k) for k in sys.argv[3:]]
if not kbps_list:
    sys.exit("name at least one bitrate in kbps")

out.mkdir(exist_ok=True)
if not (out / "frames.csv").exists():
    shutil.copy(shared / "frames.csv", out / "frames.csv")
rows = list(csv.DictReader(open(out / "frames.csv")))
pick = "+".join(f"eq(n\\,{r['index']})" for r in rows)

if not (out / "sq1080").exists():
    shutil.copytree(shared / "sq1080", out / "sq1080")
    print(f"{len(list((out / 'sq1080').glob('*.jpg')))} squares copied to out/sq1080 from the sibling study")


def encode(kbps: int) -> Path:
    video = out / f"{codec}-v{kbps}.mp4"
    rate = f"{kbps}k"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-an", *CODECS[codec], *COMMON,
                    "-fps_mode", "passthrough", "-b:v", rate, "-maxrate", rate, "-bufsize", rate, str(video)], check=True)
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=bit_rate,nb_frames:frame=key_frame", "-of", "csv=p=0", str(video)],
                           capture_output=True, text=True, check=True).stdout.split()
    keys = sum(1 for line in probe if line == "1")
    bit_rate, nb_frames = probe[-1].split(",")[:2]
    print(f"{video.name}: {video.stat().st_size / 1e6:.1f} MB, {int(bit_rate) // 1000} kbps, {nb_frames} frames, {keys} keyframes")
    return video


def squares(video: Path, name: str) -> None:
    tmp = out / "tmp"
    tmp.mkdir(exist_ok=True)
    for old in tmp.glob("*.png"):
        old.unlink()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", f"select='{pick}'", "-fps_mode", "vfr",
                    str(tmp / "%03d.png")], check=True)
    pngs = sorted(tmp.glob("*.png"))
    assert len(pngs) == len(rows), f"{len(pngs)} frames decoded for {len(rows)} picked"
    dest = out / name
    dest.mkdir(exist_ok=True)
    for row, png in zip(rows, pngs):
        img = Image.open(png).convert("RGB")
        w, h = img.size
        s = min(w, h)
        img.crop(((w - s) // 2, h - s, (w - s) // 2 + s, h)).save(dest / f"{row['id']}.jpg", quality=QUALITY)
        png.unlink()
    print(f"{len(rows)} squares in {dest.relative_to(here)}")


for kbps in kbps_list:
    squares(encode(kbps), f"{codec}-v{kbps}")
