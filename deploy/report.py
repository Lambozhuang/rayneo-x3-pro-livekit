#!/usr/bin/env python3
"""One call's record as one page.

    python3 deploy/report.py backend/runs/<call> [more calls]     -> <call>/report.html

Reads what the agent wrote under RUN_DIR (backend/agent/src/runlog.py): events.jsonl,
the photos, brain.txt and voice.txt. The page has the call at a glance (settings, steps
done, looks, how long the brain and the wearer waited, anything that went wrong), a
timeline of who spoke when and every look, and then the call in order, each hand-over
as one card: what the wearer said, the photo and the whole input the brain got, its
reply and tool call, what reached the voice and when the voice started speaking.
Only stdlib, so it runs on the backend host as is.
"""

import html
import json
import os
import sys
from statistics import median

PX = 6  # timeline px per second
LANE = 22

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


def outcome(look: dict) -> str:
    if "look_failed" in look:
        return "failed"
    if "look_dropped" in look and "look_back" not in look:
        return "dropped"
    back = look.get("look_back")
    if back is None:
        return "dropped"
    return "done" if back.get("done") or back.get("progress") is not None else "not"  # done: records before set_progress


def timeline(events: list[dict], looks: dict[int, dict], end: float) -> str:
    width = int(end * PX) + 80
    lanes = ["wearer", "voice", "brain", "steps"]
    h = LANE * len(lanes) + 24
    x = lambda t: 60 + t * PX  # noqa: E731
    svg = [f'<svg width="{width}" height="{h}" font-size="11" font-family="sans-serif">']
    for i, name in enumerate(lanes):
        svg.append(f'<text x="4" y="{i * LANE + 15}" fill="#888">{name}</text>')
    for s in range(0, int(end) + 1, 10):
        svg.append(f'<line x1="{x(s)}" y1="0" x2="{x(s)}" y2="{h - 18}" stroke="#262626"/>'
                   f'<text x="{x(s) - 12}" y="{h - 4}" fill="#666">{mmss(s)[:5]}</text>')
    for lane, who, colour in ((0, "wearer", "#4a4"), (1, "voice", "#bbb")):
        for a, b in spans(events, who, "speaking", end):
            svg.append(f'<rect x="{x(a):.1f}" y="{lane * LANE + 4}" width="{max((b - a) * PX, 1):.1f}" height="{LANE - 8}" '
                       f'fill="{colour}"><title>{who} speaking {mmss(a)}-{mmss(b)}</title></rect>')
    colours = {"done": "#5b5", "not": "#c93", "failed": "#d44", "dropped": "#555"}
    for n, look in looks.items():
        d = look.get("delegation")
        if d is None:
            continue
        stop = (look.get("look_back") or look.get("look_failed") or look.get("look_dropped") or {}).get("t", d["t"])
        o = outcome(look)
        tip = f"#{n} {o} {mmss(d['t'])}-{mmss(stop)}: {(look.get('look_back') or {}).get('reply', '')}"
        svg.append(f'<a href="#look{n}"><rect x="{x(d["t"]):.1f}" y="{2 * LANE + 4}" width="{max((stop - d["t"]) * PX, 2):.1f}" '
                   f'height="{LANE - 8}" fill="{colours[o]}"><title>{esc(tip)}</title></rect>'
                   f'<text x="{x(d["t"]) + 2:.1f}" y="{2 * LANE + 15}" fill="#111">{n}</text></a>')
        v = look.get("voice_started")
        if v is not None:
            svg.append(f'<line x1="{x(v["t"]):.1f}" y1="{LANE + 1}" x2="{x(v["t"]):.1f}" y2="{2 * LANE - 1}" stroke="#9cf" '
                       f'stroke-width="2"><title>voice starts answer #{n}</title></line>')
    for e in events:
        if e["kind"] == "live" and e.get("type") == "delegation.created" and not any(
                (lk.get("delegation") or {}).get("id") == e.get("id") for lk in looks.values()):
            svg.append(f'<line x1="{x(e["t"]):.1f}" y1="{2 * LANE}" x2="{x(e["t"]):.1f}" y2="{3 * LANE}" stroke="#f44" '
                       f'stroke-width="3"><title>GPT-Live delegated, nothing reached the brain</title></line>')
        if e["kind"] == "step" and e.get("done"):
            svg.append(f'<line x1="{x(e["t"]):.1f}" y1="{3 * LANE + 2}" x2="{x(e["t"]):.1f}" y2="{4 * LANE - 2}" stroke="#5b5" '
                       f'stroke-width="2"/><text x="{x(e["t"]) + 3:.1f}" y="{3 * LANE + 15}" fill="#7d7">{e["done"]}</text>')
    svg.append("</svg>")
    return '<div class="tl">' + "".join(svg) + "</div>"


def sent_input(sent: dict) -> str:
    """The messages after the system prompt, one turn per paragraph (records before the turns format: one text)."""
    if "input" in sent:
        return sent["input"]
    turn = lambda role, text: role + ": " + text.replace("\n", "\n    ")  # noqa: E731
    last = ["[photo]" if sent.get("photo") or sent.get("frame") is not None else "[no photo]", sent["notice"],
            sent["words"]]
    return "\n\n".join([turn(r, t) for r, t in sent.get("turns", [])] + [turn("user", "\n".join(last))])


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
        out.append(f'<span class="dim">model {back["model_ms"]} ms, total {back["total_ms"]} ms &middot; in {u.get("in")} '
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


def problems(events: list[dict], looks: dict[int, dict]) -> list[str]:
    out = []
    ids = {(lk.get("delegation") or {}).get("id") for lk in looks.values()}
    for e in events:
        k, t = e["kind"], mmss(e["t"])
        if k == "look_failed":
            out.append(f'<a href="#look{e["n"]}">#{e["n"]}</a> {t} failed: {esc(e["error"])}')
        elif k == "look_dropped":
            out.append(f'<a href="#look{e["n"]}">#{e["n"]}</a> {t} dropped for #{e["by"]}')
        elif k == "look_back" and e.get("ignored_confirm") is not None:
            out.append(f'<a href="#look{e["n"]}">#{e["n"]}</a> {t} confirm_step_correct({e["ignored_confirm"]}) ignored')
        elif k == "look_back" and e.get("ignored_progress") is not None:
            out.append(f'<a href="#look{e["n"]}">#{e["n"]}</a> {t} set_progress({e["ignored_progress"]}) ignored')
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
    last_back = None
    for e in events:
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

    out = [f"<!doctype html><meta charset='utf-8'><title>{esc(name)}</title><style>{CSS}</style>",
           f"<h1>{esc(name)}</h1><table class='kv'>"]
    kv = [("guide", f"{call.get('guide')} ({call.get('language')})"), ("commit", call.get("commit") or "unknown"),
          ("length", mmss(end)), ("steps done", f"{len(done)}/{steps}"),
          ("looks", f"{len(looks)}: " + ", ".join(f"{outcomes.count(o)} {o}" for o in ("done", "not", "failed", "dropped")
                                                   if outcomes.count(o))),
          ("brain model / total (min / median / max)", f"{stats(model_ms)} &nbsp; / &nbsp; {stats(total_ms)}"),
          ("hand-over to voice speaking", stats(wait_ms)),
          ("GPT-Live billed", f"{billed} s" if billed is not None else "-"),
          ("camera frames", end_ev.get("camera_frames", "-"))]
    kv += [(k, v) for k, v in (call.get("settings") or {}).items()]
    out += [f"<tr><td>{esc(k)}</td><td>{v if k.startswith(('looks', 'brain', 'hand')) else esc(v)}</td></tr>" for k, v in kv]
    out.append("</table><p><a href='brain.txt'>brain instructions</a> &middot; <a href='brain-tools.json'>brain tools</a> &middot; <a href='voice.txt'>voice persona</a>"
               " &middot; <a href='events.jsonl'>events.jsonl</a></p>")

    bad = problems(events, looks)
    out.append("<h2>Went wrong</h2>" + ("<br>".join(f'<span class="bad">{b}</span>' for b in bad) if bad
                                         else '<span class="ok">nothing flagged</span>'))
    out.append("<h2>Timeline</h2>" + timeline(events, looks, end)
               + "<p class='dim'>brain bars run from the hand-over to the reply: green = progress set, orange = progress unchanged, "
                 "red = failed, grey = dropped; click one for its card. Blue tick on the voice lane = the voice starts that "
                 "answer. Red tick on the brain lane = GPT-Live delegated and nothing arrived. Numbers on the steps lane = "
                 "step done.</p>")

    out.append("<h2>The call</h2>")
    for e in events:
        k, t = e["kind"], f'<span class="t">{mmss(e["t"])}</span>'
        if k == "said":
            spoke = f" (spoke {mmss(e['started'])}-{mmss(e['stopped'])})" if e.get("started") is not None else ""
            cut = " [interrupted]" if e.get("interrupted") else ""
            out.append(f'<div class="row">{t}<span class="{e["who"]}">{e["who"]}: {esc(e["text"])}'
                       f'<span class="dim">{spoke}{cut}</span></span></div>')
        elif k == "delegation":
            out.append(f'<div class="row">{t}<div style="flex:1">{card(e["n"], looks[e["n"]], thinking.get(e["n"], []))}</div></div>')
        elif k == "step":
            what = ((f"step {e['done']} done, " if e.get("done") else "") + (f"step {e['reopened']} reopened, " if e.get("reopened") else "")
                    + (f"now step {e['now']}" if e.get("now") else "build finished"))
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
