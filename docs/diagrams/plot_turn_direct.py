"""Draws one turn of the 2026-10-19 16:00 lab call as a swimlane: the wearer speaks, GPT-Live answers at once with
no delegation, while the brain's watch keeps looking and sending its notes to GPT-Live as thinking.

Usage: python docs/diagrams/plot_turn_direct.py, from the repo root. This call has no packet capture: the voices
come from the glasses' speech edges (SpeechEdgeLog, aligned to the server clock by clock.json) and from GPT-Live's
transcribed turns; the video lane is the glasses' 5 s link statistics. The wearer's microphone edge, with its RMS
threshold of 1000, did not fire on this turn, so only the transcribed turn marks the wearer's speech.
"""

import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "logs" / "20261019-160052-glasses-6010e12e"
WINDOW = (84.0, 107.0)  # seconds into the call, server clock
OUT = Path(__file__).resolve().parent / "turn-swimlane-direct.png"

ev = [json.loads(l) for l in (RUN / "events.jsonl").open(encoding="utf-8")]
w0 = next(e for e in ev if e["kind"] == "call")["wall_ms"]
ahead = json.load((RUN / "clock.json").open())["glasses_ahead_of_server_ms"]
a, b = WINDOW

# the glasses' log: speech edges and the 5 s link statistics, on the server clock
edges, video = {"wearer": [], "agent": []}, []
for line in (RUN / "glasses.log").open(encoding="utf-8", errors="ignore"):
    m = re.search(r"rayneo-speech.*\): (wearer|agent) sound (starts|stops) at=(\d+)", line)
    if m:
        edges[m.group(1)].append((m.group(2), (int(m.group(3)) - ahead - w0) / 1000))
    m = re.search(r"rayneo-link.*\): up video \S+ @([\d.]+)fps sent=(\d+)kbps.* at=(\d+)", line)
    if m:
        video.append(((int(m.group(3)) - ahead - w0) / 1000, float(m.group(1)), int(m.group(2))))


def blocks(who):
    out, start = [], None
    for what, t in edges[who]:
        if what == "starts":
            start = t
        elif start is not None:
            out.append((start, t))
            start = None
    return [(s, e) for s, e in out if e >= a and s <= b]


def E(kind, **kw):
    return [e for e in ev if e["kind"] == kind and a <= e["t"] <= b and all(e.get(k) == v for k, v in kw.items())]


def turns(who):
    out, start = [], None
    for e in [e for e in ev if e["kind"] == "state" and e["who"] == who]:
        if e["new"] == "speaking":
            start = e["t"]
        elif e["old"] == "speaking" and start is not None:
            out.append((start, e["t"]))
            start = None
    return [(s, e) for s, e in out if e >= a and s <= b]


lanes = ["wearer's voice", "agent's voice", "camera video", "GPT-Live (OpenAI)", "agent", "Claude Sonnet 5.5 (Anthropic)"]
y = {name: i for i, name in enumerate(reversed(lanes))}
fig, ax = plt.subplots(figsize=(14, 7.2))
h = 0.3

# wearer: the glasses' microphone edge where it fired, and GPT-Live's transcribed turns
for s, e in blocks("wearer"):
    ax.fill_between([s, e], y["wearer's voice"] - h, y["wearer's voice"] + h, color="tab:green", alpha=0.8)
for s, e in turns("wearer"):
    ax.plot([s, e], [y["wearer's voice"] - h - 0.08] * 2, color="black", linewidth=2)
for e in E("said", who="wearer"):
    if e.get("started") and e["started"] >= a:
        txt = e["text"].strip()
        ax.text(e["started"], y["wearer's voice"] + h + 0.04, f'"{txt[:26]}{"…" if len(txt) > 26 else ""}"', fontsize=7.5, va="bottom")

# agent's voice: the glasses' speaker edge, and what was said
for s, e in blocks("agent"):
    ax.fill_between([s, e], y["agent's voice"] - h, y["agent's voice"] + h, color="tab:red", alpha=0.8)
for e in E("said", who="voice"):
    if e.get("started") and e["started"] >= a:
        txt = e["text"].strip()
        ax.text(e["started"], y["agent's voice"] + h + 0.04, f'"{txt[:60]}{"…" if len(txt) > 60 else ""}"', fontsize=7.5, va="bottom")

# camera video: the 5 s link statistics as a band, lane height = 6 Mbps
vid = [(t, fps, kbps) for t, fps, kbps in video if a - 5 <= t <= b + 5]
for (t, fps, kbps) in vid:
    ax.fill_between([max(t - 5, a), min(t, b)], y["camera video"] - h, y["camera video"] - h + 2 * h * kbps / 6000, color="tab:blue", alpha=0.6)
ax.text(b - 0.1, y["camera video"] + h + 0.04,
        f"from the glasses' 5 s link statistics: {vid[0][1]:.0f} fps, {sum(v[2] for v in vid) / len(vid) / 1000:.1f} Mbps; no packet capture for this call",
        fontsize=7.5, ha="right", va="bottom")

# the three processes
yg, ya, yv = y["GPT-Live (OpenAI)"], y["agent"], y["Claude Sonnet 5.5 (Anthropic)"]
for yy in (yg, ya, yv):
    ax.axhline(yy, color="gray", linewidth=0.5, alpha=0.3)
purple = dict(arrowstyle="-|>", color="tab:purple", linewidth=1.4, shrinkA=0, shrinkB=0)
orange = dict(arrowstyle="-|>", color="tab:orange", linewidth=0.9, shrinkA=0, shrinkB=0)

# the watch: one look after another, each a request to Sonnet and its reply
sent = {e["w"]: e for e in ev if e["kind"] == "watch_sent"}
for back in [e for e in ev if e["kind"] == "watch_back" and a <= e["t"] <= b + 3]:
    s = sent[back["w"]]
    if s["t"] > b:
        continue
    ax.barh(yv, back["t"] - s["t"], left=s["t"], height=0.3, color="tab:orange", alpha=0.6)
    ax.annotate("", xy=(s["t"], yv), xytext=(s["t"], ya - 0.05), arrowprops=orange)
    ax.annotate("", xy=(min(back["t"], b), ya - 0.05), xytext=(min(back["t"], b), yv), arrowprops=orange)
    ax.text((s["t"] + min(back["t"], b)) / 2, yv - 0.22, f'#{back["w"]}', fontsize=7, ha="center", va="top", color="tab:orange")
# the delegation whose reply opens the window
for back in E("look_back"):
    s = next(e for e in ev if e["kind"] == "look_sent" and e["n"] == back["n"])
    ax.barh(yv, back["t"] - max(s["t"], a), left=max(s["t"], a), height=0.3, color="tab:orange")
    ax.annotate("", xy=(back["t"], ya - 0.05), xytext=(back["t"], yv), arrowprops=dict(orange, linewidth=1.4))
    ax.text(back["t"] - 0.08, yv + 0.3, f'reply to delegation #{back["n"]}', fontsize=7.5, ha="right", va="center", color="tab:orange")

# what the agent sends GPT-Live: commentary (spoken) and thinking (not), and GPT-Live's receipts
for e in E("live_sent"):
    if e["type"] == "commentary.append":
        ax.annotate("", xy=(e["t"], yg), xytext=(e["t"], ya + 0.05), arrowprops=purple)
        ax.text(e["t"] + 0.08, (yg + ya) / 2, "commentary", fontsize=7.5, ha="left", va="center", color="tab:purple")
    elif e["type"] == "thinking.append":
        ax.annotate("", xy=(e["t"], yg), xytext=(e["t"], ya + 0.05), arrowprops=dict(purple, linestyle="--", linewidth=1.1))
        ax.text(e["t"] + 0.08, (yg + ya) / 2, "thinking", fontsize=7.5, ha="left", va="center", color="tab:purple")
for e in E("live"):
    if e["type"] in ("commentary.appended", "thinking.appended"):
        ax.annotate("", xy=(e["t"], ya + 0.05), xytext=(e["t"], yg), arrowprops=dict(purple, color="tab:gray", linewidth=0.8))
# the thinking that lands during the wearer's words
key = max((e for e in E("live_sent", type="thinking.append") if e["t"] < 97.5), key=lambda e: e["t"])
ax.text(key["t"] - 0.1, (yg + ya) / 2 - 0.3, f'"{key["content"][8:62]}…"', fontsize=7.5, ha="right", va="center", color="tab:purple")

# instants through every lane: the thinking's arrival and the agent's first sound at the glasses
first_sound = min(s for s, e in blocks("agent") if s > 97)
for x, label, side in [(key["t"], "the brain's note reaches GPT-Live as thinking ", "right"), (first_sound, " GPT-Live's answer sounds at the glasses", "left")]:
    ax.axvline(x, color="black", linewidth=1.4)
    ax.text(x, len(lanes) - 0.1, label, fontsize=8, ha=side, va="bottom")

ax.set_yticks(range(len(lanes)))
ax.set_yticklabels(reversed(lanes))
ax.set_ylim(-0.75, len(lanes) + 0.25)
ax.set_xlim(a, b)
ax.set_xlabel("seconds into the call (server clock; the glasses' log aligned by clock.json)")
ax.grid(axis="x", alpha=0.3)
ax.legend(handles=[
    Patch(color="tab:green", alpha=0.8, label="the wearer's voice at the glasses' microphone (edge threshold 1000; mostly silent here)"),
    Line2D([], [], color="black", linewidth=2, label="the wearer's turn as GPT-Live transcribed it"),
    Patch(color="tab:red", alpha=0.8, label="the agent's voice as decoded on the glasses (edge threshold 500)"),
    Patch(color="tab:blue", alpha=0.6, label="camera video bitrate, lane height = 6 Mbps"),
    Line2D([], [], color="tab:purple", linewidth=1.4, label="commentary: the agent to GPT-Live, spoken"),
    Line2D([], [], color="tab:purple", linewidth=1.1, linestyle="--", label="thinking: the agent to GPT-Live, not spoken"),
    Line2D([], [], color="tab:orange", linewidth=1.4, label="the brain's looks at Sonnet 5.5: watch looks #n, and a delegation"),
], loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=2, fontsize=8, frameon=False)
ax.set_title("GPT-Live on the glasses, lab, 2026-10-19 16:00, 84–107 s: GPT-Live answers the wearer without a delegation while the watch keeps looking", fontsize=10.5)
fig.tight_layout()
fig.savefig(OUT, dpi=130)
print(OUT, f"thinking at {key['t']:.2f}, voice speaking from {[e['t'] for e in E('state', who='voice', new='speaking')]}, "
      f"first sound at the glasses {first_sound:.2f}")
