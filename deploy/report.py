#!/usr/bin/env python3
"""One call's record as one page.

    python3 deploy/report.py backend/runs/<call> [more calls]     -> <call>/report.html

Reads what the agent wrote under RUN_DIR (backend/agent/src/runlog.py): events.jsonl,
the photos and the prompts. The page has the call at a glance (settings, steps done,
looks, how long the brain and the wearer waited, anything that went wrong), a timeline
of who spoke when and every look, and then the call in order. With the glasses' log and
clock offset beside the record (deploy/pull_run.py writes glasses.log and clock.json) the
timeline also shows the wearer's voice at the microphone and the agent's voice as it
reached the glasses, and a GPT-Live call gets one stacked bar per hand-over that splits
the wait from the wearer's last word to the answer in their ear into its stages: the
network up with GPT-Live hearing the turn end and handing over, the brain's preparation
and model, GPT-Live taking up the answer, the network down. For a GPT-Live call each
hand-over is one card: what the wearer said, the photo and the whole input the brain
got, its reply and tool call, what reached the voice and when the voice started
speaking. For a one-model call (Gemini, OpenAI Realtime) there are no hand-overs: the
timeline shows the frames the model was shown and its set_progress calls, and each call
is a row with the newest frame before it. Only stdlib, so it runs on the backend host as is.
"""

import html
import json
import os
import re
import sys
from statistics import median

PX = 6  # timeline px per second
LANE = 22
# The stages of one hand-over's wait, in order, with their colours (categorical, validated for this dark surface).
STAGES = [("up", "network up, GPT-Live hearing the turn end and handing over", "#3987e5"),
          ("prep", "brain: photo and prompt", "#199e70"),
          ("model", "brain: the model", "#c98500"),
          ("voice", "GPT-Live taking up the answer", "#d55181"),
          ("down", "network down to the glasses", "#008300")]

CSS = """
body{font-family:sans-serif;background:#111;color:#ddd;margin:16px 24px;font-size:14px}
a{color:#9cf}h1{font-size:20px}h2{font-size:16px;margin-top:28px}
table.kv td{padding:1px 12px 1px 0;vertical-align:top}table.kv td:first-child{color:#888}
.bad{color:#f77}.warn{color:#fc6}.ok{color:#7d7}.dim{color:#777}.wearer{color:#7d7}.voice{color:#eee}
.tl{overflow-x:auto;border:1px solid #333;background:#161616}
.row{display:flex;gap:12px;padding:3px 0;border-top:1px solid #222}.row .t{color:#777;min-width:56px;font-family:monospace}
.card{border:1px solid #444;border-left:4px solid #888;margin:6px 0;padding:8px 10px;background:#181818}
.card.done{border-left-color:#5b5}.card.not{border-left-color:#c93}.card.failed{border-left-color:#d44}
.card.dropped{border-left-color:#555}.card img{width:360px;float:left;margin:0 12px 6px 0}
.card .body{overflow:hidden}.card .clear{clear:both}
pre{white-space:pre-wrap;background:#1d1d1d;padding:8px;font-size:12px;margin:4px 0}
summary{cursor:pointer;color:#9cf}.tag{font-family:monospace;color:#888}
table.stages{border-collapse:collapse;margin-top:8px}table.stages td,table.stages th{padding:2px 10px;text-align:right;font-variant-numeric:tabular-nums}
table.stages th{color:#888;font-weight:normal}table.stages td:first-child,table.stages th:first-child{text-align:left}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:middle}
"""


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def mmss(t: float | None) -> str:
    if t is None:
        return "-"
    return f"{int(t) // 60:02d}:{t % 60:04.1f}"


def stats(xs: list[float]) -> str:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return "-"
    return f"{xs[0] / 1000:.1f} / {median(xs) / 1000:.1f} / {xs[-1] / 1000:.1f} s (n={len(xs)})"


def spans(events: list[dict], who: str, state: str, end: float) -> list[tuple[float, float]]:
    """When `who` was in `state`, from its state changes."""
    out, start = [], None
    for e in events:
        if e["kind"] != "state" or e["who"] != who:
            continue
        if e["new"] == state and start is None:
            start = e["t"]
        elif e["old"] == state and start is not None:
            out.append((start, e["t"]))
            start = None
    if start is not None:
        out.append((start, end))
    return out


def glasses(d: str, call: dict, end: float) -> dict | None:
    """The glasses' speech edges on the call's time axis, from glasses.log and clock.json beside the record:
    {"mic": [(a, b)], "heard": [(a, b)]}, the wearer's voice at the microphone and the agent's voice as decoded
    on the glasses. Bursts separated by less than a second are one utterance. None when any of the three
    pieces (the two files, the record's wall_ms) is missing: without them nothing can be placed."""
    log, clock = os.path.join(d, "glasses.log"), os.path.join(d, "clock.json")
    if not (call.get("wall_ms") and os.path.exists(log) and os.path.exists(clock)):
        return None
    ahead = json.load(open(clock, encoding="utf-8"))["glasses_ahead_of_server_ms"]
    at_t = lambda at: (int(at) - ahead - call["wall_ms"]) / 1000  # noqa: E731
    edges = {"wearer": [], "agent": []}
    hung_up = end  # when the app left the call; a burst still open then ends there
    for line in open(log, encoding="utf-8", errors="replace"):
        m = re.search(r"rayneo-speech.*: (wearer|agent) sound (starts|stops) at=(\d+)", line)
        if m and -2 <= at_t(m.group(3)) <= end + 2:
            edges[m.group(1)].append((m.group(2), at_t(m.group(3))))
        m = re.search(r"rayneo-call.*: call ends room=(\S+) at=(\d+)", line)
        if m and m.group(1) == call.get("room"):
            hung_up = at_t(m.group(2))
    out = {}
    for who, key in (("wearer", "mic"), ("agent", "heard")):
        bursts, start = [], None
        for kind, t in edges[who]:
            if kind == "starts":
                start = t
            elif start is not None:
                bursts.append((start, max(t, start)))
                start = None
        if start is not None:
            bursts.append((start, max(start, hung_up)))
        merged = []
        for a, b in bursts:
            if merged and a - merged[-1][1] < 1.0:
                merged[-1] = (merged[-1][0], b)
            else:
                merged.append((a, b))
        out[key] = merged
    return out


def stages(looks: dict[int, dict], ears: dict | None) -> list[dict]:
    """One hand-over's wait split into STAGES, in seconds, for every look that got an answer: from the wearer's
    last word at the microphone to the answer in their ear; without the glasses' log, from the hand-over to
    GPT-Live starting to speak. The hand-over is the turn's end as GPT-Live judged it: the record's own "wearer
    stopped speaking" trails it, since the framework closes the turn when the transcript arrives. A stage is
    None when its edge is not in the record."""
    rows = []
    for n, look in sorted(looks.items()):
        d, sent, back, v = look.get("delegation"), look.get("look_sent"), look.get("look_back"), look.get("voice_started")
        if d is None or back is None:
            continue
        mic = max((b for a, b in ears["mic"] if d["t"] - 6 <= b <= d["t"] + 0.3), default=None) if ears else None
        heard = None
        if ears and v is not None:
            heard = min((a for a, b in ears["heard"] if v["t"] - 0.2 <= a <= v["t"] + 3), default=None)
        row = {"n": n, "outcome": outcome(look), "was_speaking": bool(v and v.get("was_speaking")),
               "up": (d["t"] - mic) if mic is not None else None,
               "prep": (sent["t"] - d["t"]) if sent else None,
               "model": (back["t"] - sent["t"]) if sent else None,
               "voice": (v["t"] - back["t"]) if v else None,
               "down": (heard - v["t"]) if heard is not None and v else None}
        rows.append(row)
    return rows


def stage_chart(rows: list[dict]) -> str:
    """The stacked bars and the table: one row per look, the stages left to right in STAGES' colours."""
    if not rows:
        return '<span class="dim">no answered hand-over to split</span>'
    px = 40  # per second
    width = int(max(sum(r[k] or 0 for k, _, _ in STAGES) for r in rows) * px) + 140
    h = 24
    svg = [f'<svg width="{width}" height="{h * len(rows) + 20}" font-size="11" font-family="sans-serif">']
    for i, r in enumerate(rows):
        y, x = i * h, 40
        svg.append(f'<a href="#look{r["n"]}"><text x="4" y="{y + 15}" fill="#ddd">#{r["n"]}</text></a>')
        for key, label, colour in STAGES:
            if r[key] is None or r[key] <= 0:
                continue
            w = r[key] * px
            dim = ' opacity="0.55"' if key == "voice" and r["was_speaking"] else ""
            note = " (approximate: GPT-Live was still speaking when the answer came)" if dim else ""
            svg.append(f'<rect x="{x:.1f}" y="{y + 4}" width="{max(w - 2, 1):.1f}" height="{h - 8}" rx="2" fill="{colour}"{dim}>'
                       f'<title>#{r["n"]} {label}: {r[key] * 1000:.0f} ms{note}</title></rect>')
            x += w
        total = sum(r[k] or 0 for k, _, _ in STAGES)
        svg.append(f'<text x="{x + 4:.1f}" y="{y + 15}" fill="#aaa">{total:.1f} s</text>')
    svg.append("</svg>")
    legend = " &nbsp; ".join(f'<span class="sw" style="background:{c}"></span>{esc(label)}' for _, label, c in STAGES)
    head = "".join(f"<th>{k}</th>" for k, _, _ in STAGES)
    body = []
    for r in rows:
        cells = "".join(f"<td>{r[k] * 1000:.0f}</td>" if r[k] is not None else '<td class="dim">-</td>' for k, _, _ in STAGES)
        total = sum(r[k] or 0 for k, _, _ in STAGES)
        body.append(f'<tr><td><a href="#look{r["n"]}">#{r["n"]}</a> {r["outcome"]}</td>{cells}<td><b>{total * 1000:.0f}</b></td></tr>')
    rows_html = "".join(body)
    note = ("<p class='dim'>ms. From the wearer's last word at the microphone to the answer decoded on the glasses when "
            "glasses.log and clock.json are beside the record; without them the first and last stages are missing and "
            "the total runs from the hand-over to GPT-Live starting to speak. A faded voice stage is "
            "approximate: GPT-Live was still speaking when the answer came. - : that edge is not in the record.</p>")
    return ('<div class="tl">' + "".join(svg) + "</div><p class='dim'>" + legend + "</p>"
            f'<table class="stages"><tr><th>look</th>{head}<th>total</th></tr>{rows_html}</table>' + note)


def outcome(look: dict) -> str:
    if "look_failed" in look:
        return "failed"
    if "look_dropped" in look and "look_back" not in look:
        return "dropped"
    back = look.get("look_back")
    if back is None:
        return "dropped"
    return "done" if back.get("done") or back.get("progress") is not None else "not"  # done: records before set_progress


def timeline(events: list[dict], looks: dict[int, dict], watches: dict[int, dict], end: float, one_model: bool,
             ears: dict | None) -> str:
    width = int(end * PX) + 80
    # a GPT-Live call: who speaks, the brain's looks, the steps; a one-model call has no brain: the frames shown to
    # the model and its tool calls instead, and a wearer lane only when the record has the wearer's state (Realtime;
    # Gemini has no local VAD). With the glasses' log: the wearer's voice at the microphone above what the model
    # heard, the agent's voice as it reached the glasses below it.
    wearer = not one_model or any(e["kind"] == "state" and e.get("who") == "wearer" for e in events)
    lanes = (["wearer"] if wearer else []) + (["voice", "frames", "tool", "steps"] if one_model else
                                              ["voice", "brain"] + (["watch"] if watches else []) + ["steps"])
    if ears:
        v = lanes.index("voice") + 1
        lanes = (["mic"] if wearer else []) + lanes[:v] + ["heard"] + lanes[v:]
    h = LANE * len(lanes) + 24
    x = lambda t: 60 + t * PX  # noqa: E731
    y = lambda name: lanes.index(name) * LANE  # noqa: E731
    svg = [f'<svg width="{width}" height="{h}" font-size="11" font-family="sans-serif">']
    for i, name in enumerate(lanes):
        svg.append(f'<text x="4" y="{i * LANE + 15}" fill="#888">{name}</text>')
    for s in range(0, int(end) + 1, 10):
        svg.append(f'<line x1="{x(s)}" y1="0" x2="{x(s)}" y2="{h - 18}" stroke="#262626"/>'
                   f'<text x="{x(s) - 12}" y="{h - 4}" fill="#666">{mmss(s)[:5]}</text>')
    for who, colour in (("wearer", "#4a4"), ("voice", "#bbb")):
        if who not in lanes:
            continue
        for a, b in spans(events, who, "speaking", end):
            svg.append(f'<rect x="{x(a):.1f}" y="{y(who) + 4}" width="{max((b - a) * PX, 1):.1f}" height="{LANE - 8}" '
                       f'fill="{colour}"><title>{who} speaking {mmss(a)}-{mmss(b)}</title></rect>')
    if ears:
        for lane, colour, what in (("mic", "#2d7a2d", "wearer at the microphone"), ("heard", "#777", "agent's voice on the glasses")):
            if lane not in lanes:
                continue
            for a, b in ears[lane]:
                svg.append(f'<rect x="{x(a):.1f}" y="{y(lane) + 4}" width="{max((b - a) * PX, 1):.1f}" height="{LANE - 8}" '
                           f'fill="{colour}"><title>{what} {mmss(a)}-{mmss(b)}</title></rect>')
    if one_model:
        for e in events:
            if e["kind"] == "frame":
                svg.append(f'<line x1="{x(e["t"]):.1f}" y1="{y("frames") + 6}" x2="{x(e["t"]):.1f}" y2="{y("frames") + LANE - 6}" '
                           f'stroke="#69c"><title>frame {e["n"]} ({e.get("photo") or ""}) at step {e.get("step")}</title></line>')
            elif e["kind"] == "tool":
                colour = "#d44" if e.get("ignored") else "#c93" if e.get("unchanged") else "#5b5"
                svg.append(f'<a href="#tool{e["n"]}"><rect x="{x(e["t"]) - 2:.1f}" y="{y("tool") + 4}" width="5" height="{LANE - 8}" '
                           f'fill="{colour}"><title>#{e["n"]} set_progress({e.get("done")}) at {mmss(e["t"])}</title></rect></a>')
    colours = {"done": "#5b5", "not": "#c93", "failed": "#d44", "dropped": "#555",
                 "unfinished": "#555"}
    for n, look in looks.items():
        d = look.get("delegation")
        if d is None:
            continue
        stop = (look.get("look_back") or look.get("look_failed") or look.get("look_dropped") or {}).get("t", d["t"])
        o = outcome(look)
        tip = f"#{n} {o} {mmss(d['t'])}-{mmss(stop)}: {(look.get('look_back') or {}).get('reply', '')}"
        svg.append(f'<a href="#look{n}"><rect x="{x(d["t"]):.1f}" y="{y("brain") + 4}" width="{max((stop - d["t"]) * PX, 2):.1f}" '
                   f'height="{LANE - 8}" fill="{colours[o]}"><title>{esc(tip)}</title></rect>'
                   f'<text x="{x(d["t"]) + 2:.1f}" y="{y("brain") + 15}" fill="#111">{n}</text></a>')
        v = look.get("voice_started")
        if v is not None:
            svg.append(f'<line x1="{x(v["t"]):.1f}" y1="{y("voice") + 1}" x2="{x(v["t"]):.1f}" y2="{y("voice") + LANE - 1}" stroke="#9cf" '
                       f'stroke-width="2"><title>voice starts answer #{n}</title></line>')
    for w, look in watches.items():
        sent = look.get("watch_sent")
        if sent is None:
            continue
        stop = (look.get("watch_back") or look.get("watch_failed") or look.get("watch_dropped") or {}).get("t", sent["t"])
        o = watch_outcome(look)
        what = " ".join(f'{k}: {look[k]["text"]}' for k in ("note", "say") if k in look)
        tip = f"watch {w} {o} {mmss(sent['t'])}-{mmss(stop)} {what}"
        bar = (f'<rect x="{x(sent["t"]):.1f}" y="{y("watch") + 4}" width="{max((stop - sent["t"]) * PX, 2):.1f}" '
               f'height="{LANE - 8}" fill="{WATCH_COLOURS[o]}" stroke="#111"><title>{esc(tip)}</title></rect>')
        svg.append(bar if o == "nothing" else f'<a href="#watch{w}">{bar}</a>')
    for e in events:
        if e["kind"] == "live" and e.get("type") == "delegation.created" and not any(
                (lk.get("delegation") or {}).get("id") == e.get("id") for lk in looks.values()):
            svg.append(f'<line x1="{x(e["t"]):.1f}" y1="{y("brain")}" x2="{x(e["t"]):.1f}" y2="{y("brain") + LANE}" stroke="#f44" '
                       f'stroke-width="3"><title>GPT-Live delegated, nothing reached the brain</title></line>')
        if e["kind"] == "step" and e.get("done"):
            svg.append(f'<line x1="{x(e["t"]):.1f}" y1="{y("steps") + 2}" x2="{x(e["t"]):.1f}" y2="{y("steps") + LANE - 2}" stroke="#5b5" '
                       f'stroke-width="2"/><text x="{x(e["t"]) + 3:.1f}" y="{y("steps") + 15}" fill="#7d7">{e["done"]}</text>')
    svg.append("</svg>")
    return '<div class="tl">' + "".join(svg) + "</div>"


def sent_input(sent: dict) -> str:
    """The messages after the system prompt, one turn per paragraph (records before the turns format: one text;
    records with the call so far: one message, its parts one per paragraph)."""
    if "input" in sent:
        return sent["input"]
    if "said" in sent:
        return "\n\n".join(["[photo]" if sent.get("photo") else "[no photo]", sent["said"], sent["notice"], sent["words"]])
    turn = lambda role, text: role + ": " + text.replace("\n", "\n    ")  # noqa: E731
    last = ["[photo]" if sent.get("photo") or sent.get("frame") is not None else "[no photo]", sent["notice"],
            sent["words"]]
    return "\n\n".join([turn(r, t) for r, t in sent.get("turns", [])] + [turn("user", "\n".join(last))])


def ttft(usage: dict) -> str:
    """", first output after N ms" when the request was streamed (Anthropic, from 2026-10-19), else nothing."""
    return f', first output after {usage["ttft_ms"]} ms' if usage.get("ttft_ms") is not None else ""


def watch_outcome(look: dict) -> str:
    """What a watch look came to: failed, dropped (a delegation came while it ran), unfinished (the call ended while
    it ran), progress, say, note or nothing."""
    if "watch_failed" in look:
        return "failed"
    back = look.get("watch_back")
    if back is None:
        return "dropped" if "watch_dropped" in look else "unfinished"
    if back.get("progress") is not None:
        return "progress"
    return ("say" if "say" in look else "held" if "say_held" in look else "note" if "note" in look
            else "nothing")


WATCH_COLOURS = {"progress": "#5b5", "say": "#a6d", "held": "#d8b", "note": "#69c", "nothing": "#444", "failed": "#d44", "dropped": "#555",
                 "unfinished": "#555"}


def watch_card(w: int, look: dict) -> str:
    """A watch look that did something or went wrong: its photo, what it wrote, what went to the voice."""
    sent, back, o = look.get("watch_sent"), look.get("watch_back"), watch_outcome(look)
    out = [f'<div class="card {"failed" if o == "failed" else "done" if o == "progress" else "not"}" id="watch{w}">']
    if sent and sent.get("photo"):
        out.append(f'<a href="{esc(sent["photo"])}"><img src="{esc(sent["photo"])}"></a>')
    out.append(f'<div class="body"><b>watch {w}</b> {mmss((sent or {}).get("t"))} &nbsp; {o}<br>')
    if sent:
        out.append(f'step {sent["step"]} &middot; frame {sent["frame"]} ({sent["frame_size"]} at {sent["side"]} px, '
                   f'{sent["frame_age_ms"]} ms old), {sent["photo_kb"]} KB<br>')
    for kind in ("note", "say"):
        if kind in look:
            out.append(f'<p>{kind}: {esc(look[kind]["text"])}</p>')
    if "say_held" in look:
        fate = look.get("say_confirmed") or look.get("say_dropped") or {}
        how = (f"sent: watch {fate['by']} said so too" if "say_confirmed" in look else
               f"dropped: hand-over #{fate['by_delegation']} came" if fate.get("by_delegation") else
               f"dropped: watch {fate['by']} said nothing" if fate else "still held when the call ended")
        out.append(f'<p>say, held for the next look: {esc(look["say_held"]["text"])}<br>'
                   f'<span class="dim">{how}</span></p>')
    if back:
        u = back.get("usage") or {}
        calls = ", ".join(f"{c}({json.dumps(a)})" for c, a in back.get("calls", [])) or "no tool call"
        out.append(f'<span class="tag">{esc(calls)}</span>'
                   + (f' <span class="bad">ignored: {esc(back["ignored_progress"])} is not a number of steps</span>'
                      if back.get("ignored_progress") is not None else "") + "<br>")
        out.append(f'<span class="dim">model {back["model_ms"]} ms{ttft(u)}, total {back["total_ms"]} ms &middot; in {u.get("in")} '
                   f'(cached {u.get("cached")}, written {u.get("written")}) out {u.get("out")} stop {esc(u.get("stop"))}'
                   f'</span><br>')
    if "watch_failed" in look:
        out.append(f'<span class="bad">{esc(look["watch_failed"]["error"])}</span><br>')
    c = look.get("commentary")
    if c:
        out.append(f'<details><summary>to the voice at {mmss(c["t"])}' + (" (it was speaking)" if c.get("voice_speaking") else "")
                   + f'</summary><pre>{esc(c["text"])}</pre></details>')
    if sent:
        out.append(f'<details><summary>input as sent</summary><pre>{esc(sent_input(sent))}</pre></details>')
    out.append('</div><div class="clear"></div></div>')
    return "".join(out)


def card(n: int, look: dict, thinking: list[str]) -> str:
    d, sent, back = look.get("delegation", {}), look.get("look_sent"), look.get("look_back")
    o = outcome(look)
    out = [f'<div class="card {o}" id="look{n}">']
    if sent and sent.get("photo"):
        out.append(f'<a href="{esc(sent["photo"])}"><img src="{esc(sent["photo"])}"></a>')
    out.append('<div class="body">')
    head = {"done": '<span class="ok">progress set</span>', "not": "progress unchanged",
            "failed": '<span class="bad">failed</span>', "dropped": '<span class="dim">dropped</span>'}[o]
    out.append(f'<b>#{n}</b> {mmss(d.get("t"))} <span class="tag">{esc(d.get("id"))}</span> &nbsp; {head}<br>')
    asked = (sent or {}).get("words", d.get("asked_with"))
    out.append(f'<span class="wearer">wearer: {esc(asked or d.get("words")) or "(none)"}</span>'
               + ("" if d.get("words") else ' <span class="warn">(no words came with the hand-over: the wearer\'s '
                                            'last lines in the history)</span>') + "<br>")
    if sent:
        frame = (f'frame {sent["frame"]} ({sent["frame_size"]}, {sent["frame_age_ms"]} ms old), {sent["photo_kb"]} KB'
                 if sent.get("frame") is not None else '<span class="bad">no photo: no camera frame yet</span>')
        out.append(f'step {sent["step"]} &middot; {frame} &middot; sent {sent["prep_ms"]} ms after the hand-over<br>')
    if back:
        u = back.get("usage") or {}
        calls = ", ".join(f"{c}({json.dumps(a)})" for c, a in back.get("calls", [])) or "no tool call"
        out.append(f'<p>{esc(back.get("reply"))}</p>')
        out.append(f'<span class="tag">{esc(calls)}</span>'
                   + (f' <span class="bad">ignored: the current step was not {esc(back["ignored_confirm"])}</span>'
                      if back.get("ignored_confirm") is not None else "")
                   + (f' <span class="bad">ignored: {esc(back["ignored_progress"])} is not a number of steps</span>'
                      if back.get("ignored_progress") is not None else "") + "<br>")
        out.append(f'<span class="dim">model {back["model_ms"]} ms{ttft(u)}, total {back["total_ms"]} ms &middot; in {u.get("in")} '
                   f'(cached {u.get("cached")}, written {u.get("written")}) out {u.get("out")} (thinking {u.get("thinking")}) '
                   f'stop {esc(u.get("stop"))}</span><br>')
    if "look_failed" in look:
        out.append(f'<span class="bad">{esc(look["look_failed"]["error"])}</span><br>')
    if "look_dropped" in look:
        out.append(f'<span class="dim">dropped: hand-over #{look["look_dropped"]["by"]} came while it ran</span><br>')
    c = look.get("commentary")
    if c:
        out.append(f'<details><summary>to the voice at {mmss(c["t"])}'
                   + (" (it was speaking)" if c.get("voice_speaking") else "") + "</summary>"
                   f'<pre>{esc(c["text"])}' + "".join(f"\nthinking: {esc(t)}" for t in thinking) + "</pre></details>")
    v, s = look.get("voice_started"), look.get("voice_silent")
    if v:
        out.append(f'voice started {v["after_commentary_ms"]} ms after the answer, '
                   f'<b>{v["after_delegation_ms"] / 1000:.1f} s</b> after the hand-over'
                   + (" (it was speaking when the answer came)" if v.get("was_speaking") else "") + "<br>")
    elif s:
        out.append(f'<span class="warn">voice {esc(s["why"])}</span><br>')
    if sent:
        out.append(f'<details><summary>input as sent</summary><pre>{esc(sent_input(sent))}</pre></details>')
    out.append('</div><div class="clear"></div></div>')
    return "".join(out)


def tool_row(e: dict, frame: dict | None) -> str:
    """A Gemini set_progress call: the newest frame the model had been shown before it, and what came of it."""
    out = [f'<div class="card {"failed" if e.get("ignored") else "not" if e.get("unchanged") else "done"}" id="tool{e["n"]}">']
    if frame and frame.get("photo"):
        out.append(f'<a href="{esc(frame["photo"])}"><img src="{esc(frame["photo"])}"></a>')
    out.append('<div class="body">')
    what = (f'<span class="bad">set_progress({esc(e.get("done"))}) ignored: not a number of steps</span>' if e.get("ignored")
            else f'set_progress({e.get("done")}): unchanged' if e.get("unchanged")
            else f'<span class="ok">set_progress({e.get("done")}): {e.get("before")} done &rarr; {e.get("done")} done</span>')
    out.append(f'<b>#{e["n"]}</b> {mmss(e["t"])} &nbsp; {what}<br>')
    if frame:
        out.append(f'<span class="dim">newest frame shown: {frame["n"]} at {mmss(frame["t"])}, {(e["t"] - frame["t"]):.1f} s '
                   f'before the call, {frame.get("size")}, {frame.get("photo_kb")} KB</span><br>')
    else:
        out.append('<span class="bad">no frame had been shown to the model yet</span><br>')
    out.append('</div><div class="clear"></div></div>')
    return "".join(out)


def problems(events: list[dict], looks: dict[int, dict]) -> list[str]:
    out = []
    ids = {(lk.get("delegation") or {}).get("id") for lk in looks.values()}
    for e in events:
        k, t = e["kind"], mmss(e["t"])
        if k == "tool" and e.get("ignored"):
            out.append(f'<a href="#tool{e["n"]}">#{e["n"]}</a> {t} set_progress({esc(e.get("done"))}) ignored')
        elif k == "look_failed":
            out.append(f'<a href="#look{e["n"]}">#{e["n"]}</a> {t} failed: {esc(e["error"])}')
        elif k == "look_dropped":
            out.append(f'<a href="#look{e["n"]}">#{e["n"]}</a> {t} dropped for #{e["by"]}')
        elif k == "look_back" and e.get("ignored_confirm") is not None:
            out.append(f'<a href="#look{e["n"]}">#{e["n"]}</a> {t} confirm_step_correct({e["ignored_confirm"]}) ignored')
        elif k == "look_back" and e.get("ignored_progress") is not None:
            out.append(f'<a href="#look{e["n"]}">#{e["n"]}</a> {t} set_progress({e["ignored_progress"]}) ignored')
        elif k == "watch_failed":
            out.append(f'<a href="#watch{e["w"]}">watch {e["w"]}</a> {t} failed: {esc(e["error"])}')
        elif k == "voice_silent":
            out.append(f'<a href="#look{e["n"]}">#{e["n"]}</a> {t} voice {esc(e["why"])}')
        elif k == "live" and e.get("type") == "error":
            out.append(f"{t} GPT-Live error: {esc(e.get('error'))}")
        elif k == "live" and e.get("type") == "delegation.created" and e.get("id") not in ids:
            out.append(f"{t} GPT-Live delegated ({esc(e.get('id'))}), nothing reached the brain")
        elif k == "camera" and e.get("none_after_s"):
            out.append(f"{t} no camera frame {e['none_after_s']} s into the call")
        elif k == "quality" and e.get("quality") in ("poor", "lost"):
            out.append(f"{t} link quality {e['quality']} ({esc(e['who'])})")
        elif k == "wearer" and e.get("left") and e.get("reason") != "CLIENT_INITIATED":
            out.append(f"{t} {esc(e['left'])} left: {esc(e.get('reason'))}")
        elif k == "closed" and e.get("error"):
            out.append(f"{t} session closed with an error: {esc(e['error'])}")
    return out


def report(d: str) -> str:
    events = [json.loads(line) for line in open(os.path.join(d, "events.jsonl"), encoding="utf-8") if line.strip()]
    end = max(e["t"] for e in events)
    call = next((e for e in events if e["kind"] == "call"), {})
    looks: dict[int, dict] = {}
    thinking: dict[int, list[str]] = {}
    watches: dict[int, dict] = {}
    last_back = None
    for e in events:
        if e["kind"] in ("watch_sent", "watch_back", "watch_failed", "watch_dropped", "note", "say", "say_held",
                         "say_confirmed", "say_dropped", "commentary") and e.get("w"):
            watches.setdefault(e["w"], {})[e["kind"]] = e
        if e["kind"] in ("delegation", "look_sent", "look_back", "look_failed", "look_dropped", "commentary",
                         "voice_started", "voice_silent") and e.get("n"):
            looks.setdefault(e["n"], {})[e["kind"]] = e
        if e["kind"] == "look_back":
            last_back = e["n"]
        if e["kind"] == "thinking" and last_back is not None:
            thinking.setdefault(last_back, []).append(e["text"])

    steps = len(call.get("steps", [])) or "?"
    done = [e for e in events if e["kind"] == "step" and e.get("done")]
    outcomes = [outcome(lk) for lk in looks.values()]
    model_ms = [lk["look_back"]["model_ms"] for lk in looks.values() if "look_back" in lk]
    total_ms = [lk["look_back"]["total_ms"] for lk in looks.values() if "look_back" in lk]
    wait_ms = [lk["voice_started"]["after_delegation_ms"] for lk in looks.values() if "voice_started" in lk]
    end_ev = next((e for e in events if e["kind"] == "end"), {})
    billed = next((e.get("seconds") for e in events if e["kind"] == "live" and e.get("type") == "session.closed"),
                  end_ev.get("voice_s"))
    name = os.path.basename(os.path.normpath(d))
    one_model = "brain_model" not in (call.get("settings") or {})  # Gemini or Realtime: no brain
    tools = [e for e in events if e["kind"] == "tool"]
    frames = [e for e in events if e["kind"] == "frame"]
    turns = [e for e in events if e["kind"] == "model"]
    ears = glasses(d, call, end)

    out = [f"<!doctype html><meta charset='utf-8'><title>{esc(name)}</title><style>{CSS}</style>",
           f"<h1>{esc(name)}</h1><table class='kv'>"]
    began = next((e for e in events if e["kind"] == "build" and e.get("started")), None)
    finished = next((e for e in events if e["kind"] == "build" and e.get("finished")), None)
    task = (f"started {mmss(began['t'])}, " if began else "") + (
        f"finished {mmss(finished['t'])} ({finished['took_s']:.0f} s)" if finished else '<span class="warn">not finished</span>')
    kv = [("guide", f"{call.get('guide')} ({call.get('language')})"), ("commit", call.get("commit") or "unknown"),
          ("t=0 wall clock ms", call.get("wall_ms") or "not recorded"),
          ("length", mmss(end)), ("build", task), ("steps done", f"{len(done)}/{steps}")]
    if one_model:
        kv += [("set_progress calls", f"{len(tools)}: {sum(1 for e in tools if not e.get('unchanged') and not e.get('ignored'))} "
                                      f"moved, {sum(1 for e in tools if e.get('unchanged'))} unchanged, "
                                      f"{sum(1 for e in tools if e.get('ignored'))} ignored"),
               ("model ttft / generation (min / median / max)",
                f"{stats([e['ttft_ms'] for e in turns])} &nbsp; / &nbsp; {stats([e['duration_ms'] for e in turns])}"),
               ("model turns, tokens in (image) / out", f"{len(turns)}, {end_ev.get('in_tokens', '-')} ({end_ev.get('image_tokens', '-')}) "
                                                        f"/ {end_ev.get('out_tokens', '-')}"),
               ("camera frames / shown to the model", f"{end_ev.get('camera_frames', '-')} / {end_ev.get('frames_to_model', len(frames))}")]
    else:
        kv += [("looks", f"{len(looks)}: " + ", ".join(f"{outcomes.count(o)} {o}" for o in ("done", "not", "failed", "dropped")
                                                        if outcomes.count(o))),
               ("brain model / total (min / median / max)", f"{stats(model_ms)} &nbsp; / &nbsp; {stats(total_ms)}"),
               ("hand-over to voice speaking", stats(wait_ms)),
               ("watch looks", f"{len(watches)}: " + ", ".join(
                   f"{n} {o}" for o in WATCH_COLOURS if (n := sum(1 for lk in watches.values() if watch_outcome(lk) == o)))),
               ("watch model (min / median / max)", stats([lk["watch_back"]["model_ms"] for lk in watches.values()
                                                            if "watch_back" in lk])),
               ("GPT-Live billed", f"{billed} s" if billed is not None else "-"),
               ("camera frames", end_ev.get("camera_frames", "-"))]
    kv += [(k, v) for k, v in (call.get("settings") or {}).items()]
    out += [f"<tr><td>{esc(k)}</td><td>{v if k.startswith(('looks', 'brain', 'hand', 'model', 'set_progress', 'build', 'watch')) else esc(v)}</td></tr>" for k, v in kv]
    texts = [(f, label) for f, label in (("brain.txt", "brain instructions"), ("brain-tools.json", "brain tools"),
                                         ("voice.txt", "voice persona"), ("instructions.txt", "instructions"))
             if os.path.exists(os.path.join(d, f))]
    out.append("</table><p>" + " &middot; ".join(f"<a href='{f}'>{label}</a>" for f, label in texts)
               + " &middot; <a href='events.jsonl'>events.jsonl</a></p>")

    bad = problems(events, looks)
    out.append("<h2>Went wrong</h2>" + ("<br>".join(f'<span class="bad">{b}</span>' for b in bad) if bad
                                         else '<span class="ok">nothing flagged</span>'))
    legend = ("<p class='dim'>ticks on the frames lane = a frame shown to the model; marks on the tool lane = set_progress: "
              "green = progress moved, orange = unchanged, red = ignored; click one for its row. Numbers on the steps lane = "
              "step done." + ("" if any(e["kind"] == "state" and e.get("who") == "wearer" for e in events) else
                              " The wearer's speech is not recorded on this path (no local VAD).") + "</p>" if one_model else
              "<p class='dim'>brain bars run from the hand-over to the reply: green = progress set, orange = progress unchanged, "
              "red = failed, grey = dropped; click one for its card. Blue tick on the voice lane = the voice starts that "
              "answer. Red tick on the brain lane = GPT-Live delegated and nothing arrived. Watch bars run from a watch "
              "look to its reply: green = progress set, purple = say, pink = say held for the next look, blue = note, dark = nothing, red = failed, grey = "
              "dropped for a hand-over; click one for its card. Numbers on the steps lane = step done.</p>")
    if ears:
        legend = legend[:-4] + (" Mic lane = the wearer's voice at the microphone, heard lane = the agent's voice decoded on "
                                "the glasses, both from glasses.log placed with clock.json.</p>")
    else:
        legend = legend[:-4] + " No glasses.log, clock.json or wall_ms beside the record: the glasses' side is not shown.</p>"
    out.append("<h2>Timeline</h2>" + timeline(events, looks, watches, end, one_model, ears) + legend)
    if not one_model:
        out.append("<h2>Where the wait goes, per hand-over</h2>" + stage_chart(stages(looks, ears)))

    out.append("<h2>The call</h2>")
    last_frame = None
    for e in events:
        k, t = e["kind"], f'<span class="t">{mmss(e["t"])}</span>'
        if k == "frame":
            last_frame = e
        elif k == "tool":
            out.append(f'<div class="row">{t}<div style="flex:1">{tool_row(e, last_frame)}</div></div>')
        elif k == "model":
            out.append(f'<div class="row">{t}<span class="dim">model: ttft {e["ttft_ms"]} ms, generation {e["duration_ms"]} ms, '
                       f'in {e["in_tokens"]} (image {e["image_tokens"]}) out {e["out_tokens"]}</span></div>')
        elif k == "said":
            spoke = f" (spoke {mmss(e['started'])}-{mmss(e['stopped'])})" if e.get("started") is not None else ""
            cut = " [interrupted]" if e.get("interrupted") else ""
            out.append(f'<div class="row">{t}<span class="{e["who"]}">{e["who"]}: {esc(e["text"])}'
                       f'<span class="dim">{spoke}{cut}</span></span></div>')
        elif k in ("watch_back", "watch_failed") and watch_outcome(watches[e["w"]]) in ("progress", "say", "held", "note", "failed"):
            out.append(f'<div class="row">{t}<div style="flex:1">{watch_card(e["w"], watches[e["w"]])}</div></div>')
        elif k == "delegation":
            out.append(f'<div class="row">{t}<div style="flex:1">{card(e["n"], looks[e["n"]], thinking.get(e["n"], []))}</div></div>')
        elif k == "step":
            what = ((f"step {e['done']} done, " if e.get("done") else "") + (f"step {e['reopened']} reopened, " if e.get("reopened") else "")
                    + (f"now step {e['now']}" if e.get("now") else "last step done"))
            out.append(f'<div class="row">{t}<span class="ok">{what}</span></div>')
        elif k == "build":
            what = f"build started, {e['steps']} steps" if e.get("started") else f"build finished in {e['took_s']:.0f} s"
            out.append(f'<div class="row">{t}<b class="ok">{what}</b></div>')
        elif k == "picture":
            what = (f"picture of step {e['step']} sent to the glasses, {e.get('bytes', 0) // 1024} KB in {e.get('send_ms')} ms"
                    if e.get("step") else "picture off the glasses, the camera again")
            out.append(f'<div class="row">{t}<span class="ok">{what}</span></div>')
        elif k in ("wearer", "quality", "camera", "closed", "end") or (
                k == "live" and e.get("type") in ("error", "session.started", "session.closed")):
            body = {key: v for key, v in e.items() if key not in ("t", "kind")}
            out.append(f'<div class="row">{t}<span class="dim">{k}: {esc(json.dumps(body, ensure_ascii=False))}</span></div>')
    return "".join(out)


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for d in sys.argv[1:]:
        page = os.path.join(d, "report.html")
        with open(page, "w", encoding="utf-8") as f:
            f.write(report(d))
        print(page)


if __name__ == "__main__":
    main()
