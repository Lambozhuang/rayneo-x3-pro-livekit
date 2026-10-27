"""Draws the study's scores as three line charts into out/chart.png.

    uv run python chart.py

Each panel is one score as a share, whole frames, bricks found and sizes right, against the four pictures of a frame
side: not encoded, then 2, 1 and 0.5 Mbps. One line per condition: a side (1080p, 720p) run without thinking (solid)
or with thinking at effort low (dashed), which produced no thinking and so is a second run of the same call. The sides
768, 512 and 384 not encoded, the rest of the pixel group, are grey dots under the not-encoded point. The numbers come
from score.py.
"""

from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt

import score

matplotlib.use("Agg")

STEPS = [("sq{side}", "not encoded"), ("v2000-{side}", "2 Mbps"), ("v1000-{side}", "1 Mbps"), ("v500-{side}", "0.5 Mbps")]
LINES = [("1080", "none", "1080p, no thinking", "#2a78d6", "-"), ("1080", "low", "1080p, thinking low", "#1baf7a", "--"),
         ("720", "none", "720p, no thinking", "#e34948", "-"), ("720", "low", "720p, thinking low", "#eda100", "--")]
REFS = [("sq768-none", "768 px"), ("sq768-low", "768 px, low"), ("sq512-none", "512 px"), ("sq384-none", "384 px")]
PANELS = [("whole frames", lambda t: (t["whole"], t["frames"])),
          ("bricks found", lambda t: (t["found"], t["bricks"])),
          ("sizes right", lambda t: (t["size"], t["items"] // 2))]
GREY, INK, MUTED, SURFACE = "#9a998f", "#0b0b0b", "#52514e", "#ffffff"

here = Path(__file__).resolve().parent
out = here / "out"


def pct(cond: str, value) -> float:
    k, n = value(score.score(cond)[0])
    return 100 * k / n


def panel(ax, title: str, value) -> None:
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", color=INK, pad=10)
    ax.set_ylim(0, 100)
    ax.set_xlim(-0.6, len(STEPS) - 1 + 0.3)
    ax.set_xticks(range(len(STEPS)), [s for _, s in STEPS], fontsize=10.5, color=MUTED)
    ax.set_yticks(range(0, 101, 25), [f"{p}%" for p in range(0, 101, 25)], fontsize=10.5, color=MUTED)
    ax.grid(axis="y", color="#e6e5e2", linewidth=1)
    ax.tick_params(length=0)
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    for side, run, name, colour, style in LINES:
        ys = [pct(f"{p.format(side=side)}-{run}", value) for p, _ in STEPS]
        ax.plot(range(len(STEPS)), ys, style, marker="o", color=colour, linewidth=2, markersize=7,
                markeredgecolor=SURFACE, markeredgewidth=1.5, label=name, zorder=3)
    labels = []
    for cond, label in REFS:  # the other sides, not encoded, under the not-encoded point
        y = pct(cond, value)
        ax.plot([0], [y], "o", color=GREY, markersize=7, markeredgecolor=SURFACE, markeredgewidth=1.5, zorder=2)
        labels.append((y, label))
    last = 999.0
    for y, label in sorted(labels, reverse=True):  # pushed apart so they never overlap, read top down
        y = min(y, last - 5.5)
        last = y
        ax.annotate(label, (0, y), xytext=(-9, -3.5), textcoords="offset points", ha="right", fontsize=9.5, color=MUTED)


fig, axes = plt.subplots(1, len(PANELS), figsize=(16, 6), facecolor=SURFACE)
for ax, (title, value) in zip(axes, PANELS):
    panel(ax, title, value)
handles, names = axes[0].get_legend_handles_labels()
handles.append(plt.Line2D([], [], marker="o", color=GREY, linestyle="", markersize=7))
names.append("other sides, not encoded")
fig.legend(handles, names, loc="upper left", bbox_to_anchor=(0.04, 0.9), ncol=5, frameon=False, fontsize=11)
fig.suptitle("What the brain's model reads off the plate, by frame side and video bitrate", x=0.045, y=0.99,
             ha="left", fontsize=15, fontweight="bold", color=INK)
fig.text(0.045, 0.945, "39 frames of the 2026-10-22 call, Claude Sonnet 5.5, one call per frame per condition, each condition "
         "run once. Thinking at effort low produced no thinking in any call.", fontsize=10.5, color=MUTED, va="top")
fig.tight_layout(rect=(0.03, 0, 1, 0.85), w_pad=3)
fig.savefig(out / "chart.png", dpi=150)
print(out / "chart.png")
