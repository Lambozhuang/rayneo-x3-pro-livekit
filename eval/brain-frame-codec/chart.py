"""Draws everything this study measured as line charts into out/chart.png.

    uv run python chart.py

Eleven panels against the bitrate, the frame as recorded then 1, 0.5 and 0.25 Mbps: the three scores of the result
table, whole frames, bricks found and sizes right as shares, then the rest the replies hold, orientation right, the 1x6
and 1x4 sizes right, the extra bricks and guesses as counts, and the photo's size and the call's timing as medians. One
line per codec and model, each model's lines starting from its own point for the recorded frame: Claude Sonnet 5.5
(effort low, which produced no thinking) solid, gpt-6.1-terra (reasoning off) dashed. The numbers come from score.py and
the reply files; a line stops where a condition was not run.
"""

import json
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent / "brain-frame-quality"))
import score  # noqa: E402

score.out = here / "out"
matplotlib.use("Agg")

STEPS = ["as recorded", "1 Mbps", "0.5 Mbps", "0.25 Mbps"]
RATES = (1000, 500, 250)
MODELS = [("low", "Sonnet 5.5", "-"), ("none-gpt-6.1-terra", "gpt-6.1-terra", "--")]  # reply suffix, name, line style
CODECS = [("h264", "H.264", {"low": "#2a78d6", "none-gpt-6.1-terra": "#e34948"}),
          ("hevc", "H.265", {"low": "#1baf7a", "none-gpt-6.1-terra": "#eda100"})]
INK, MUTED, SURFACE = "#0b0b0b", "#52514e", "#ffffff"


def replies(cond: str) -> list:
    return [json.loads(p.read_text(encoding="utf-8")) for p in (score.out / "replies" / cond).glob("*.json")]


def median(xs) -> float:
    xs = sorted(xs)
    return xs[len(xs) // 2]


def share(cond: str, value) -> float:
    """A score as a percentage, or NaN for a condition with no replies, which leaves a gap in the line."""
    t = score.score(cond)[0]
    if not t["frames"]:
        return float("nan")
    k, n = value(t)
    return 100 * k / n


def by_size(cond: str, size: str) -> float:
    k, n = score.by_size(cond)[size]
    return 100 * k / n if n else float("nan")


def count(cond: str, key: str) -> float:
    t = score.score(cond)[0]
    return t[key] if t["frames"] else float("nan")


def timing(cond: str, key: str, scale: float) -> float:
    rs = replies(cond)
    return median(r[key] for r in rs) / scale if rs else float("nan")


# title, y-axis label, top of the axis or None for automatic, the value of a condition
MAIN = [
    ("Whole frames\n% of the 41 frames with nothing wrong", "%", 100, lambda c: share(c, lambda t: (t["whole"], t["frames"]))),
    ("Bricks found\n% of the 120 labelled bricks", "%", 100, lambda c: share(c, lambda t: (t["found"], t["bricks"]))),
    ("Sizes read right\n% of the bricks found", "%", 100, lambda c: share(c, lambda t: (t["size"], t["items"] // 2))),
]
MORE = [
    ("Orientation read right\n% of the bricks found", "%", 100, lambda c: share(c, lambda t: (t["orient"], t["items"] // 2))),
    ("1x6 rails counted right\n% of the 1x6 found", "%", 100, lambda c: by_size(c, "1x6")),
    ("1x4 rungs counted right\n% of the 1x4 found", "%", 100, lambda c: by_size(c, "1x4")),
    ("Bricks reported but not on the plate\ntotal in 41 frames, lower is better", "bricks", None, lambda c: count(c, "extra")),
    ("Guesses where the label says can't tell\ntotal in 41 frames, lower is better", "items", None, lambda c: count(c, "guess")),
    ("Size of the JPEG sent to the model\nKB, median; a smaller file kept less detail", "KB", None, lambda c: timing(c, "photo_kb", 1)),
    ("Whole model call\nseconds, median of 41", "s", None, lambda c: timing(c, "model_ms", 1000)),
    ("Time to the first output token\nseconds, median of 41", "s", None, lambda c: timing(c, "ttft_ms", 1000)),
]


def panel(ax, title: str, unit: str, top, value) -> None:
    ax.set_title(title, loc="left", fontsize=10.5, fontweight="bold", color=INK, pad=8)
    ax.set_ylabel(unit, fontsize=9.5, color=MUTED)
    ax.set_xlim(-0.3, len(STEPS) - 1 + 0.3)
    ax.set_xticks(range(len(STEPS)), STEPS, fontsize=9.5, color=MUTED)
    ax.tick_params(length=0, labelsize=9.5, labelcolor=MUTED)
    ax.grid(axis="y", color="#e6e5e2", linewidth=1)
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    highest = 0.0
    for suffix, model, style in MODELS:
        ref = value(f"sq1080-{suffix}")
        for codec, codec_name, colours in CODECS:
            ys = [ref] + [value(f"{codec}-v{k}-{suffix}") for k in RATES]
            highest = max([highest] + [y for y in ys if y == y])
            ax.plot(range(len(STEPS)), ys, style, marker="o", color=colours[suffix], linewidth=2, markersize=6,
                    markeredgecolor=SURFACE, markeredgewidth=1.5, label=f"{codec_name}, {model}", zorder=3)
    ax.set_ylim(0, top or highest * 1.25)


def figure(panels, rows: int, cols: int, size, name: str, title: str, note: str, top: float) -> None:
    fig, axes = plt.subplots(rows, cols, figsize=size, facecolor=SURFACE)
    for ax, (t, unit, lim, value) in zip(axes.flat, panels):
        panel(ax, t, unit, lim, value)
    handles, names = axes.flat[0].get_legend_handles_labels()
    for ax in list(axes.flat)[len(panels):]:  # a slot with no panel holds the legend
        ax.axis("off")
        ax.legend(handles, names, loc="center left", frameon=False, fontsize=10.5, title="codec, model",
                  title_fontsize=10.5, alignment="left")
    fig.suptitle(title, x=0.04, y=0.99, ha="left", fontsize=15, fontweight="bold", color=INK)
    fig.text(0.04, 0.955, note, fontsize=10.5, color=MUTED, va="top")
    fig.subplots_adjust(left=0.04, right=0.99, top=top, bottom=0.05, wspace=0.3, hspace=0.55)
    fig.savefig(here / "out" / name, dpi=150)
    print(here / "out" / name)


NOTE = (f"{len(score.labels)} frames of the 2026-10-27 call, one call per frame per condition, encoded as the glasses encode: "
        "constant bitrate, one keyframe, no B-frames, 15 fps.\nSonnet 5.5 ran at effort low (no thinking produced), "
        "gpt-6.1-terra with reasoning off; each model's lines start from its own reading of the frame as recorded.")
figure(MAIN + MORE, 3, 4, (18, 13), "chart.png",
       "What the vision model reads off the plate, by codec, bitrate and model, at 1080", NOTE, 0.88)
