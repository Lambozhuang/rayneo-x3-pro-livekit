"""Draws one turn of the clean-network GPT-Live capture of 2026-10-16 as a swimlane: what the glasses sent and
received packet by packet, what the agent, GPT-Live and the vision model did, on one time axis.

Usage: python docs/diagrams/plot_turn.py, from the repo root. The capture's clock (the netem box) is aligned to
the server's by the onsets of the agent's voice: the first downlink audio packet after a silence against the
agent's state turning to speaking.
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CAP = ROOT / "traffic" / "2026-10-16-prestudy"
PLOT = CAP / "plot_livekit.py"
ns = {"__file__": str(PLOT), "__name__": "plot_livekit"}
src = PLOT.read_text(encoding="utf-8")
exec(compile(src[: src.rfind("main()")], str(PLOT), "exec"), ns)
load, GLASSES = ns["load"], ns["GLASSES"]

RUN = CAP / "glasses-gpt-good" / "20261016-154745-glasses-9c6f2d48"
WINDOW = (53.0, 71.0)  # seconds into the call, server clock
OUT = Path(__file__).resolve().parent / "turn-swimlane.png"

rows = load(CAP / "glasses-gpt-good" / "packets-enp59s0.csv")
ev = [json.loads(l) for l in (RUN / "events.jsonl").open(encoding="utf-8")]
w0 = next(e for e in ev if e["kind"] == "call")["wall_ms"] / 1000.0

# --- clock alignment: capture time minus server time -------------------------------------------------------
dl_all = np.sort(np.array([r[0] for r in rows if r[6] == "63" and r[2] == GLASSES]) - w0)
onsets = [e["t"] for e in ev if e["kind"] == "state" and e["who"] == "voice" and e["new"] == "speaking"]
# first downlink audio packet of a burst of speech: a gap before it (DTX sends one packet every 400 ms in silence,
# speech one every 20 ms) and at least ten packets in the 0.3 s after it
gap_before = np.r_[True, np.diff(dl_all) > 0.1]
dense_after = np.array([np.searchsorted(dl_all, x + 0.3) - i >= 10 for i, x in enumerate(dl_all)])
bursts = dl_all[gap_before & dense_after]
diffs = []
for o in onsets:
    near = bursts[(bursts > o - 1.0) & (bursts < o + 1.0)]
    if len(near):
        diffs.append(near[np.argmin(abs(near - o))] - o)
offset = float(np.median(diffs))
print(f"clock offset capture - server: {offset * 1000:.0f} ms from {len(diffs)} onsets, spread {np.std(diffs) * 1000:.0f} ms")

t = lambda r: r[0] - w0 - offset  # capture row -> seconds into the call on the server clock
a, b = WINDOW
ul_pk = [(t(r), r[3]) for r in rows if r[6] == "63" and r[1] == GLASSES and a <= t(r) <= b]
dl_pk = [(t(r), r[3]) for r in rows if r[6] == "63" and r[2] == GLASSES and a <= t(r) <= b]
ul_audio, dl_audio = [x for x, _ in ul_pk], [x for x, _ in dl_pk]
AUDIO_TOP_B = 300  # the voice lanes' full height, in bytes on the wire
# video frames: the packets of one frame share an RTP timestamp; a frame is placed at its last packet's time
frames = {}
for r in rows:
    if r[6] == "100" and r[1] == GLASSES and a <= t(r) <= b:
        f = frames.setdefault(r[7], [0, 0.0])
        f[0] += r[3]
        f[1] = max(f[1], t(r))
frame_t = np.array([f[1] for f in frames.values()])
frame_kb = np.array([f[0] / 1000 for f in frames.values()])
FRAME_TOP_KB = 60  # the lane's full height

E = lambda kind, **kw: [e for e in ev if e["kind"] == kind and a <= e["t"] <= b and all(e.get(k) == v for k, v in kw.items())]
def intervals(who):
    out, start = [], None
    for e in E("state", who=who):
        if e["new"] == "speaking":
            start = e["t"]
        elif e["old"] == "speaking" and start is not None:
            out.append((start, e["t"]))
            start = None
    return out

# --- figure ------------------------------------------------------------------------------------------------------
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

lanes = ["wearer's voice", "agent's voice", "camera video", "GPT-Live (OpenAI)", "agent", "Claude Sonnet 5.5 (Anthropic)"]
y = {name: i for i, name in enumerate(reversed(lanes))}
fig, ax = plt.subplots(figsize=(14, 7.2))
h = 0.3

# wearer's voice: uplink audio packets (DTX: sent only while the APM hears speech) and GPT-Live's own turn
def packets(pk, lane, color):
    xs = [x for x, _ in pk]
    tops = [y[lane] - h + 2 * h * min(n, AUDIO_TOP_B) / AUDIO_TOP_B for _, n in pk]
    ax.vlines(xs, y[lane] - h, tops, color=color, linewidth=0.6, alpha=0.8)

packets(ul_pk, "wearer's voice", "tab:green")
for s_, e_ in intervals("wearer"):
    ax.plot([s_, e_], [y["wearer's voice"] - h - 0.08] * 2, color="black", linewidth=2)

# agent's voice: downlink audio packets and what was said
packets(dl_pk, "agent's voice", "tab:red")
for e in E("said", who="voice"):
    if e.get("started") and e["started"] >= a:
        txt = e["text"].strip()
        ax.text(e["started"], y["agent's voice"] + h + 0.04, f'"{txt[:52]}{"…" if len(txt) > 52 else ""}"', fontsize=7.5, va="bottom")

# camera video: one line per frame, its height the frame's size
ax.vlines(frame_t, y["camera video"] - h, y["camera video"] - h + 2 * h * np.minimum(frame_kb, FRAME_TOP_KB) / FRAME_TOP_KB,
          color="tab:blue", linewidth=0.9, alpha=0.85)
ax.text(b - 0.1, y["camera video"] + h + 0.04, f"{len(frame_t) / (b - a):.0f} frames/s, {frame_kb.mean():.0f} kB per frame on average",
        fontsize=7.5, ha="right", va="bottom")

# the three processes and the messages between them, each arrow in the direction the message travels
yg, ya, yv = y["GPT-Live (OpenAI)"], y["agent"], y["Claude Sonnet 5.5 (Anthropic)"]
for yy in (yg, ya, yv):
    ax.axhline(yy, color="gray", linewidth=0.5, alpha=0.3)
purple = dict(arrowstyle="-|>", color="tab:purple", linewidth=1.4, shrinkA=0, shrinkB=0)
orange = dict(arrowstyle="-|>", color="tab:orange", linewidth=1.4, shrinkA=0, shrinkB=0)
ls, lb = E("look_sent")[0], E("look_back")[0]
t_del = E("live", type="delegation.created")[0]["t"]
t_com = E("live_sent", type="commentary.append")[0]["t"]
t_rcpt = E("live", type="commentary.appended")[0]["t"]
ax.annotate("", xy=(t_del, ya + 0.05), xytext=(t_del, yg), arrowprops=purple)
ax.text(t_del - 0.08, (yg + ya) / 2, "delegation", fontsize=7.5, ha="right", va="center", color="tab:purple")
ax.annotate("", xy=(ls["t"], yv), xytext=(ls["t"], ya - 0.05), arrowprops=orange)
ax.text(ls["t"] + 0.08, ya - 0.3, f'request: {ls["photo_kb"]} kB photo + the call so far', fontsize=7.5, ha="left", va="center", color="tab:orange")
ax.barh(yv, lb["t"] - ls["t"], left=ls["t"], height=0.3, color="tab:orange", alpha=0.6)
ax.text((ls["t"] + lb["t"]) / 2, yv - 0.22, f'{lb["model_ms"] / 1000:.1f} s until the reply, both internet legs included', fontsize=7.5, ha="center", va="top", color="tab:orange")
ax.annotate("", xy=(lb["t"], ya - 0.05), xytext=(lb["t"], yv), arrowprops=orange)
ax.text(lb["t"] - 0.08, yv + 0.3, f'reply: step {lb["progress"]} done', fontsize=7.5, ha="right", va="center", color="tab:orange")
ax.annotate("", xy=(t_com, yg), xytext=(t_com, ya + 0.05), arrowprops=purple)
ax.text(t_com - 0.08, (yg + ya) / 2, "commentary", fontsize=7.5, ha="right", va="center", color="tab:purple")
ax.annotate("", xy=(t_rcpt, ya + 0.05), xytext=(t_rcpt, yg), arrowprops=dict(purple, color="tab:gray", linewidth=1.0))
ax.text(t_rcpt + 0.08, (yg + ya) / 2, "receipt", fontsize=7.5, ha="left", va="center", color="tab:gray")
# the agent's own work: preparing the look, and publishing the step list to the glasses
ax.barh(ya, ls["t"] - t_del, left=t_del, height=0.3, color="tab:orange")
ax.text(t_del + 0.1, ya + 0.2, f'prepares the look, {ls["prep_ms"]} ms', fontsize=7.5, ha="left", va="bottom", color="tab:orange")
st = E("step")[0]
ax.plot([st["t"]], [ya], marker="^", color="black", markersize=8)
ax.text(st["t"] + 0.08, ya - 0.08, f'step list → {st["now"]}', fontsize=7.5, ha="left", va="top")

# the chain's instants through every lane
last_up = max(x for x in ul_audio if x < t_del and sum(1 for u in ul_audio if x - 0.3 < u <= x) >= 10)
first_answer = min(x for x in dl_audio if x >= E("voice_started")[0]["t"] - 0.1)
for x in (t_del, lb["t"]):
    ax.axvline(x, color="black", linewidth=0.7, linestyle=":", alpha=0.6)
top = len(lanes) - 0.35
for x in (last_up, first_answer):
    ax.axvline(x, color="black", linewidth=1.6)
ax.annotate("", xy=(first_answer, top), xytext=(last_up, top), arrowprops=dict(arrowstyle="<->", color="black", linewidth=1.4, shrinkA=0, shrinkB=0))
ax.text((last_up + first_answer) / 2, top + 0.05, f"TTC on the bridge: wearer's last audio packet → answer's first audio packet, {first_answer - last_up:.1f} s",
        fontsize=8.5, ha="center", va="bottom", fontweight="bold")

ax.set_yticks(range(len(lanes)))
ax.set_yticklabels(reversed(lanes))
ax.set_ylim(-0.75, len(lanes) + 0.1)
ax.set_xlim(a, b)
ax.set_xlabel("seconds into the call (server clock; the capture is aligned by the onsets of the agent's voice)")
ax.grid(axis="x", alpha=0.3)
ax.legend(handles=[
    Line2D([], [], color="tab:green", linewidth=2, label=f"one audio packet, glasses → server; height = its size, lane height = {AUDIO_TOP_B} B"),
    Line2D([], [], color="black", linewidth=2, label="the wearer's turn as GPT-Live transcribed it"),
    Line2D([], [], color="tab:red", linewidth=2, label=f"one audio packet, server → glasses; height = its size, lane height = {AUDIO_TOP_B} B"),
    Line2D([], [], color="tab:blue", linewidth=2, label=f"one video frame, glasses → server; height = its size, lane height = {FRAME_TOP_KB} kB"),
    Line2D([], [], color="tab:purple", linewidth=1.4, label="a message between GPT-Live and the agent, in the arrow's direction"),
    Line2D([], [], color="tab:orange", linewidth=1.4, label="the agent's request to Sonnet 5.5 and its reply; the bar is the time it is out"),
], loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=2, fontsize=8, frameon=False)
ax.set_title("GPT-Live on the glasses, clean network, 2026-10-16 15:47, turn 2: the wearer asks what is next, the plate is checked, GPT-Live answers", fontsize=11)
fig.tight_layout()
fig.savefig(OUT, dpi=130)
print(OUT, f"last uplink audio packet {last_up:.2f} s, delegation {t_del:.2f}, look back {lb['t']:.2f}, first answer packet {first_answer:.2f}")
