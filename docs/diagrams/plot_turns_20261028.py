"""Draws three turns of the 2026-10-28 17:23 lab call as swimlanes, one figure each, from the packet capture on the
netem bridge and the agent's record: the wearer asks for a picture and the brain puts it on the glasses; the wearer
asks the brain to look again and GPT-Live answers from its reply; the wearer asks where a brick goes and GPT-Live
answers at once, from the guide and the watch's notes, with no delegation.

Usage: python docs/diagrams/plot_turns_20261028.py, from the repo root. The capture's clock (the netem box) is
aligned to the server's by the onsets of the agent's voice: the first downlink audio packet after a silence against
the agent's state turning to speaking. The glasses' log is aligned by clock.json. The capture lives in traffic/,
which is on this machine only.
"""

import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parents[2]
PLOT = ROOT / "traffic" / "2026-10-16-prestudy" / "plot_livekit.py"
ns = {"__file__": str(PLOT), "__name__": "plot_livekit"}
src = PLOT.read_text(encoding="utf-8")
exec(compile(src[: src.rfind("main()")], str(PLOT), "exec"), ns)
load, GLASSES = ns["load"], ns["GLASSES"]

CAP = ROOT / "traffic" / "2026-10-28-capture" / "glasses-gpt-20261028-2"
RUN = ROOT / "logs" / "20261028-162315-glasses-795c9128"
HERE = Path(__file__).resolve().parent
CALL = "GPT-Live on the glasses, lab, 2026-10-28 17:23"
BRAIN = "brain: gpt-6.1-terra (OpenAI)"
AUDIO_TOP_B, FRAME_TOP_KB, OTHER_TOP_B = 300, 60, 1300  # the lanes' full heights

rows = load(CAP / "packets-enp59s0.csv")
ev = [json.loads(l) for l in (RUN / "events.jsonl").open(encoding="utf-8")]
w0 = next(e for e in ev if e["kind"] == "call")["wall_ms"] / 1000.0
ahead = json.load((RUN / "clock.json").open())["glasses_ahead_of_server_ms"] / 1000.0

# --- clock alignment: capture time minus server time -------------------------------------------------------
dl_all = np.sort(np.array([r[0] for r in rows if r[6] == "63" and r[2] == GLASSES]) - w0)
onsets = [e["t"] for e in ev if e["kind"] == "state" and e["who"] == "voice" and e["new"] == "speaking"]
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
cap_t = lambda r: r[0] - w0 - offset  # capture row -> seconds into the call on the server clock

# the glasses' log of the pictures, on the server clock: {name: {opened, received, shown, cleared}}
glog = {}
for line in (RUN / "glasses.log").open(encoding="utf-8", errors="ignore"):
    m = re.search(r"rayneo-picture.*\): (opened|received|announced|shown).*name=(\S+).* at=(\d+)", line)
    if m:
        glog.setdefault(m.group(2), {})[m.group(1)] = int(m.group(3)) / 1000.0 - ahead - w0

watch_sent = {e["w"]: e for e in ev if e["kind"] == "watch_sent"}
look_sent = {e["n"]: e for e in ev if e["kind"] == "look_sent"}


def figure(window, out, title, ask, answers, data_lane=False, quote_thinking=None):
    """One swimlane figure of the window (seconds into the call). `ask` brackets the wearer's question, so its last
    audio packet can be found; `answers` lists (label, event time) moments whose first downlink audio packet ends a
    span from that packet. A picture sent in the window adds a span to its showing on the glasses."""
    a, b = window
    E = lambda kind, **kw: [e for e in ev if e["kind"] == kind and a <= e["t"] <= b and all(e.get(k) == v for k, v in kw.items())]
    ul_pk = [(cap_t(r), r[3]) for r in rows if r[6] == "63" and r[1] == GLASSES and a <= cap_t(r) <= b]
    dl_pk = [(cap_t(r), r[3]) for r in rows if r[6] == "63" and r[2] == GLASSES and a <= cap_t(r) <= b]
    ul_audio, dl_audio = [x for x, _ in ul_pk], [x for x, _ in dl_pk]
    other_dl = [(cap_t(r), r[3]) for r in rows if r[6] == "" and r[2] == GLASSES and r[3] >= 200 and a <= cap_t(r) <= b]
    frames = {}
    for r in rows:
        if r[6] == "100" and r[1] == GLASSES and a <= cap_t(r) <= b:
            f = frames.setdefault(r[7], [0, 0.0])
            f[0] += r[3]
            f[1] = max(f[1], cap_t(r))
    frame_t = np.array([f[1] for f in frames.values()])
    frame_kb = np.array([f[0] / 1000 for f in frames.values()])

    def intervals(who):
        out_, start = [], None
        for e in [e for e in ev if e["kind"] == "state" and e["who"] == who]:
            if e["new"] == "speaking":
                start = e["t"]
            elif e["old"] == "speaking" and start is not None:
                out_.append((start, e["t"]))
                start = None
        return [(s, e) for s, e in out_ if e >= a and s <= b]

    lanes = ["wearer's voice", "agent's voice", "camera video"] + (["data to the glasses"] if data_lane else []) + ["GPT-Live (OpenAI)", "agent", BRAIN]
    y = {name: i for i, name in enumerate(reversed(lanes))}
    fig, ax = plt.subplots(figsize=(14, 7.4 + 0.7 * data_lane))
    h = 0.3

    def packets(pk, lane, color, top_b, lw=0.6):
        xs = [x for x, _ in pk]
        tops = [y[lane] - h + 2 * h * min(n, top_b) / top_b for _, n in pk]
        ax.vlines(xs, y[lane] - h, tops, color=color, linewidth=lw, alpha=0.85)

    def caption(who, lane, width):
        """GPT-Live's transcripts over a voice lane; a caption that would run into the one before it goes on a second row."""
        char_w = (b - a) / 11.2 * 0.055  # seconds per character of 7.5 pt text on these axes
        end, row = -1e9, 0
        for e in [e for e in ev if e["kind"] == "said" and e["who"] == who and e.get("started") and e["started"] <= b and e["t"] >= a]:
            txt = e["text"].strip()
            w = width if e["started"] >= a else 40  # a transcript that began before the window is cut shorter
            txt = '"' + txt[:w] + ("…" if len(txt) > w else "") + '"'
            x = max(e["started"], a + 0.05)
            row = 1 - row if x < end + 0.1 else 0
            ax.text(x, y[lane] + h + 0.04 + 0.2 * row, txt, fontsize=7.5, va="bottom")
            end = x + len(txt) * char_w

    # the two voices, packet by packet, with GPT-Live's transcripts
    packets(ul_pk, "wearer's voice", "tab:green", AUDIO_TOP_B)
    for s_, e_ in intervals("wearer"):
        ax.plot([max(s_, a), min(e_, b)], [y["wearer's voice"] - h - 0.08] * 2, color="black", linewidth=2)
    caption("wearer", "wearer's voice", 60)
    packets(dl_pk, "agent's voice", "tab:red", AUDIO_TOP_B)
    caption("voice", "agent's voice", 70)

    # camera video, one line per frame
    ax.vlines(frame_t, y["camera video"] - h, y["camera video"] - h + 2 * h * np.minimum(frame_kb, FRAME_TOP_KB) / FRAME_TOP_KB,
              color="tab:blue", linewidth=0.9, alpha=0.85)
    ax.text(b - 0.1, y["camera video"] + h + 0.04, f"{len(frame_t) / (b - a):.0f} frames/s, {frame_kb.mean():.0f} kB per frame on average",
            fontsize=7.5, ha="right", va="bottom")

    yg, ya, yv = y["GPT-Live (OpenAI)"], y["agent"], y[BRAIN]
    for yy in (yg, ya, yv):
        ax.axhline(yy, color="gray", linewidth=0.5, alpha=0.3)
    purple = dict(arrowstyle="-|>", color="tab:purple", linewidth=1.4, shrinkA=0, shrinkB=0)
    orange = dict(arrowstyle="-|>", color="tab:orange", linewidth=1.4, shrinkA=0, shrinkB=0)
    thin = dict(orange, linewidth=0.8, alpha=0.7)

    # the watch: the brain's own looks, one after another, each a request to its model and the reply
    for back in [e for e in ev if e["kind"] == "watch_back" and e["t"] >= a and watch_sent[e["w"]]["t"] <= b]:
        s = watch_sent[back["w"]]
        s_t, b_t = max(s["t"], a), min(back["t"], b)
        ax.barh(yv, b_t - s_t, left=s_t, height=0.3, color="tab:orange", alpha=0.35)
        if s["t"] >= a:
            ax.annotate("", xy=(s["t"], yv), xytext=(s["t"], ya - 0.05), arrowprops=thin)
        if back["t"] <= b:
            ax.annotate("", xy=(back["t"], ya - 0.05), xytext=(back["t"], yv), arrowprops=thin)
        ax.text((s_t + b_t) / 2, yv, f'#{back["w"]}', fontsize=6.5, ha="center", va="center", color="saddlebrown")
    for e in E("watch_dropped"):
        ax.text(watch_sent[e["w"]]["t"] + 0.05, yv + 0.2, f'#{e["w"]} dropped', fontsize=6.5, ha="left", va="bottom", color="tab:orange")

    # delegations: GPT-Live hands over, the agent prepares the look, the model replies, the agent answers in commentary
    for d in E("live", type="delegation.created"):
        t_del = d["t"]
        n = next(e["n"] for e in ev if e["kind"] == "delegation" and e["id"] == d["id"])
        ls = look_sent[n]
        lb = next(e for e in ev if e["kind"] == "look_back" and e["n"] == n)
        ax.annotate("", xy=(t_del, ya + 0.05), xytext=(t_del, yg), arrowprops=purple)
        ax.text(t_del - 0.08, (yg + ya) / 2, "delegation", fontsize=7.5, ha="right", va="center", color="tab:purple")
        ax.barh(ya, ls["t"] - t_del, left=t_del, height=0.3, color="tab:orange")
        ax.text(t_del - 0.08, ya + 0.1, f'prepares the look, {ls["prep_ms"]} ms', fontsize=7.5, ha="right", va="bottom", color="tab:orange")
        ax.annotate("", xy=(ls["t"], yv), xytext=(ls["t"], ya - 0.05), arrowprops=orange)
        ax.text(ls["t"] - 0.08, ya - 0.3, f'request: {ls["photo_kb"]} kB photo + the call so far', fontsize=7.5, ha="right", va="center", color="tab:orange")
        ax.barh(yv, lb["t"] - ls["t"], left=ls["t"], height=0.3, color="tab:orange", alpha=0.7)
        ax.text((ls["t"] + lb["t"]) / 2, yv - 0.22, f'{lb["model_ms"] / 1000:.1f} s until the reply, both internet legs included', fontsize=7.5, ha="center", va="top", color="tab:orange")
        ax.annotate("", xy=(lb["t"], ya - 0.05), xytext=(lb["t"], yv), arrowprops=orange)
        what = ", ".join(f'{c[0]}({", ".join(f"{k} {v}" for k, v in c[1].items())})' for c in lb["calls"]) or "words for the voice"
        ax.text(lb["t"] + 0.08, yv + 0.3, "reply: " + what, fontsize=7.5, ha="left", va="center", color="tab:orange")
        for x in (t_del, lb["t"]):
            ax.axvline(x, color="black", linewidth=0.7, linestyle=":", alpha=0.6)

    # what the agent sends GPT-Live, and GPT-Live's receipts
    for e in E("live_sent", type="commentary.append"):
        ax.annotate("", xy=(e["t"], yg), xytext=(e["t"], ya + 0.05), arrowprops=purple)
        label = 'commentary "Picture: …"' if e["content"].startswith("Picture") else "commentary"
        ax.text(e["t"] + 0.1, (yg + ya) / 2, label, fontsize=7.5, ha="left", va="center", color="tab:purple")
    for e in E("live_sent", type="thinking.append"):
        ax.annotate("", xy=(e["t"], yg), xytext=(e["t"], ya + 0.05), arrowprops=dict(purple, linestyle="--", linewidth=1.1))
        ax.text(e["t"] + 0.08, (yg + ya) / 2 + 0.2, "thinking", fontsize=7.5, ha="left", va="center", color="tab:purple")
    for e in E("live"):
        if e["type"] in ("commentary.appended", "thinking.appended"):
            ax.annotate("", xy=(e["t"], ya + 0.05), xytext=(e["t"], yg), arrowprops=dict(purple, color="tab:gray", linewidth=0.8))
    if quote_thinking:
        key = max(e for e in E("live_sent", type="thinking.append") if e["t"] < quote_thinking)
        ax.text(key["t"] - 0.1, yg - 0.2, '"' + key["content"][8:70] + '…"', fontsize=7.5, ha="right", va="center", color="tab:purple")

    # the watch's say: held for a second look, then dropped or spoken
    for e in E("say_held"):
        ax.plot([e["t"]], [ya + 0.35], marker="o", markerfacecolor="white", color="tab:orange", markersize=6)
        ax.text(e["t"] + 0.08, ya + 0.35, "say held", fontsize=7, ha="left", va="center", color="tab:orange")
    for e in E("say_dropped"):
        ax.plot([e["t"]], [ya + 0.35], marker="x", color="tab:orange", markersize=6)
        ax.text(e["t"] + 0.08, ya + 0.35, "dropped", fontsize=7, ha="left", va="center", color="tab:orange")
    for st in E("step"):
        ax.plot([st["t"]], [ya], marker="^", color="black", markersize=8)
        ax.text(st["t"] + 0.08, ya - 0.08, f'step list → {st["now"]}', fontsize=7.5, ha="left", va="top")

    # the picture: the agent's send, its bytes on the data channel, and the glasses' log of receiving and showing it
    pics = E("picture") if data_lane else []
    for pic in pics:
        yd = y["data to the glasses"]
        packets(other_dl, "data to the glasses", "tab:cyan", OTHER_TOP_B, lw=1.2)
        g = glog[pic["name"]]
        ax.annotate("", xy=(pic["t"], yd + h + 0.02), xytext=(pic["t"], ya - 0.05), arrowprops=dict(arrowstyle="-|>", color="tab:cyan", linewidth=1.4, shrinkA=0, shrinkB=0))
        ax.text(pic["t"] - 0.08, yg + 0.5, f'sends the picture, {pic["send_ms"]} ms', fontsize=7.5, ha="right", va="center", color="tab:cyan")
        for key in ("received", "shown"):
            ax.plot([g[key]], [yd + h + 0.08], marker="v", color="tab:cyan", markersize=7, clip_on=False)
        ax.text(g["shown"] + 0.1, yd + h + 0.04, f'the glasses log it received {(g["received"] - pic["t"]) * 1000:.0f} ms and shown '
                f'{(g["shown"] - pic["t"]) * 1000:.0f} ms after the agent sent it', fontsize=7.5, ha="left", va="bottom", color="tab:cyan")
        n_pk = sum(1 for x, n in other_dl if pic["t"] - 0.05 <= x <= g["received"])
        ax.text(pic["t"] - 0.1, yd + h + 0.04, f'{pic["name"]}, {pic["bytes"] / 1000:.1f} kB in {n_pk} packets', fontsize=7.5, ha="right", va="bottom", color="tab:cyan")

    # the spans: the wearer's last audio packet to the first packet of each answer, and to the picture on the glasses
    dense = [x for i, x in enumerate(ul_audio) if sum(1 for u in ul_audio[max(0, i - 20):i + 1] if x - 0.3 < u <= x) >= 10]
    last_up = max(x for x in dense if ask[0] <= x <= ask[1])
    ax.axvline(last_up, color="black", linewidth=1.6)
    top = len(lanes) - 0.25
    spans = [(label, min(x for x in dl_audio if x >= t_ - 0.1), "black") for label, t_ in answers]
    spans += [(f"the picture shown on the glasses", glog[p["name"]]["shown"], "tab:cyan") for p in pics]
    for i, (label, x, color) in enumerate(spans):
        ax.axvline(x, color=color, linewidth=1.6)
        yy = top + 0.45 * i
        ax.annotate("", xy=(x, yy), xytext=(last_up, yy), arrowprops=dict(arrowstyle="<->", color=color, linewidth=1.4, shrinkA=0, shrinkB=0))
        ax.text((last_up + x) / 2, yy + 0.05, f"wearer's last audio packet → {label}, {x - last_up:.1f} s", fontsize=8.5, ha="center", va="bottom", fontweight="bold", color=color)

    ax.set_yticks(range(len(lanes)))
    ax.set_yticklabels(reversed(lanes))
    ax.set_ylim(-0.75, top + 0.45 * len(spans) + 0.15)
    ax.set_xlim(a, b)
    ax.set_xlabel("seconds into the call (server clock; the capture aligned by the onsets of the agent's voice, the glasses' log by clock.json)")
    ax.grid(axis="x", alpha=0.3)
    handles = [
        Line2D([], [], color="tab:green", linewidth=2, label=f"one audio packet, glasses → server; height = its size, lane height = {AUDIO_TOP_B} B"),
        Line2D([], [], color="black", linewidth=2, label="the wearer's turn as GPT-Live transcribed it"),
        Line2D([], [], color="tab:red", linewidth=2, label=f"one audio packet, server → glasses; height = its size, lane height = {AUDIO_TOP_B} B"),
        Line2D([], [], color="tab:blue", linewidth=2, label=f"one video frame, glasses → server; height = its size, lane height = {FRAME_TOP_KB} kB"),
        Line2D([], [], color="tab:purple", linewidth=1.4, label="commentary: the agent to GPT-Live, spoken; grey: GPT-Live's receipt"),
        Line2D([], [], color="tab:purple", linewidth=1.1, linestyle="--", label="thinking: the agent to GPT-Live, not spoken"),
        Line2D([], [], color="tab:orange", linewidth=1.4, label="the agent's request to the brain's model and its reply; dark: a delegation, light: watch look #n"),
        Line2D([], [], color="tab:orange", linewidth=0, marker="o", markerfacecolor="white", label="say held: the watch wants to speak and waits for a second look to agree; x: dropped"),
    ]
    if data_lane:
        handles.insert(4, Line2D([], [], color="tab:cyan", linewidth=2, label=f"one non-RTP packet, server → glasses (RTCP, signalling, the data channel); lane height = {OTHER_TOP_B} B"))
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.09), ncol=2, fontsize=8, frameon=False)
    ax.set_title(f"{CALL}, {a:.0f}–{b:.0f} s: {title}", fontsize=10.5)
    fig.tight_layout()
    fig.savefig(HERE / out, dpi=130)
    print(out, f"last uplink audio packet {last_up:.2f}; " + "; ".join(f"{l} {x:.2f}" for l, x, _ in spans))


figure((96.5, 113.0), "turn-20261028-picture.png",
       "the wearer asks for a picture, the brain puts step 2's picture on the glasses, GPT-Live says so",
       ask=(97.0, 100.0), answers=[("GPT-Live's first audio packet", 100.96)], data_lane=True)
figure((222.5, 238.5), "turn-20261028-delegation.png",
       "the wearer asks the brain to look again, GPT-Live fills the wait, then answers from the brain's reply",
       ask=(223.5, 225.5), answers=[("GPT-Live's first audio packet, a filler", 226.16), ("the answer's first audio packet", 229.08)])
figure((236.5, 251.0), "turn-20261028-direct.png",
       "the wearer asks where the brick goes, GPT-Live answers at once with no delegation",
       ask=(238.5, 240.7), answers=[("GPT-Live's first audio packet", 240.55)], quote_thinking=240.5)
