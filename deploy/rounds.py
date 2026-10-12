"""One call's record as an HTML page with every brain round in full: what went in, what came out, what went to GPT-Live.

    python deploy/rounds.py logs/<call>      -> logs/<call>/rounds.html

report.py is the summary (timeline, waits, what went wrong); this page is every round's prompt in full.
"""

import html
import json
import sys
from pathlib import Path

run = Path(sys.argv[1])
ev = [json.loads(line) for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
brain_txt = (run / "brain.txt").read_text(encoding="utf-8")
tools_txt = (run / "brain-tools.json").read_text(encoding="utf-8")
voice_txt = (run / "voice.txt").read_text(encoding="utf-8")
e = html.escape
call = next(x for x in ev if x["kind"] == "call")


def pre(s: str, cls: str = "") -> str:
    return f'<pre class="{cls}">{e(s)}</pre>'


def details(summary: str, body: str, open_: bool = False) -> str:
    return f'<details{" open" if open_ else ""}><summary>{summary}</summary>{body}</details>'


# group events by round: a round starts at a delegation and runs until the next one
rounds: dict[int, dict] = {}
cur = None
for x in ev:
    k = x["kind"]
    if k == "delegation":
        cur = x["n"]
        rounds[cur] = {"delegation": x, "said_after": [], "live": [], "sent": [], "steps": []}
    if cur is None:
        continue
    r = rounds[cur]
    if k in ("look_sent", "look_back", "commentary", "voice_started", "voice_silent", "look_failed", "look_dropped"):
        r.setdefault(k, x)
    elif k == "said":
        r["said_after"].append(x)
    elif k == "live_sent" and x.get("type") != "session.close":
        r["sent"].append(x)
    elif k == "live" and x.get("type") in ("commentary.appended", "thinking.appended", "instructions.appended"):
        r["live"].append(x)
    elif k == "step":
        r["steps"].append(x)

before = [x for x in ev if x["kind"] == "said" and x["t"] < (rounds[min(rounds)]["delegation"]["t"] if rounds else 1e9)]
start_ev = next((x for x in ev if x["kind"] == "live_sent" and x.get("type") == "session.start"), None)
opening = next((x for x in ev if x["kind"] == "live_sent" and x.get("type") == "commentary.append"
                and not x.get("delegation")), None)

out = [f"""<!doctype html><meta charset="utf-8"><title>rounds {e(run.name)}</title>
<style>
body{{font:14px/1.45 system-ui,sans-serif;margin:24px auto;max-width:1100px;color:#222}}
h1{{font-size:20px}} h2{{font-size:16px;margin:0}}
pre{{white-space:pre-wrap;background:#f6f6f6;padding:8px 10px;border-radius:6px;margin:4px 0}}
.round{{border:1px solid #ccc;border-radius:8px;padding:12px 16px;margin:18px 0}}
.done{{border-color:#2a8;box-shadow:0 0 0 2px #2a83 inset}}
.msg{{margin:4px 0;padding:6px 10px;border-radius:6px}}
.user{{background:#e8f4ea}} .assistant{{background:#eef0f8}}
.lbl{{font-size:11px;color:#777;text-transform:uppercase;letter-spacing:.05em;margin-top:10px}}
.out{{background:#fff7e0}} .live{{background:#e9f3ff}} .said{{background:#f2f2f2}}
img{{max-width:420px;border-radius:6px;display:block;margin:4px 0}}
.meta{{color:#666;font-size:12px}} summary{{cursor:pointer;color:#345}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
</style>
<h1>{e(run.name)} — {e(call["guide"])} — {e(str(call.get("commit")))}</h1>
<p class="meta">settings: {e(json.dumps(call.get("settings"), ensure_ascii=False))}</p>
<p class="meta">steps: {e(" · ".join(call.get("steps", [])))}</p>"""]

out.append(details("brain system prompt (brain.txt, the same on every round)", pre(brain_txt)))
out.append(details("brain tools (brain-tools.json)", pre(tools_txt)))
out.append(details("voice persona (voice.txt)", pre(voice_txt)))
if start_ev:
    out.append(details("session.start as sent to GPT-Live", pre(json.dumps(start_ev.get("event"), indent=2, ensure_ascii=False))))
if opening:
    out.append(details(f"opening commentary sent at {opening['t']:.1f}s", pre(opening.get("content") or "")))
if before:
    out.append('<div class="lbl">before the first delegation</div>' + "".join(
        f'<div class="msg {"user" if s["who"] == "wearer" else "assistant"}">{s["t"]:.1f}s {e(s["who"])}: {e(s["text"])}</div>'
        for s in before))

for n in sorted(rounds):
    r = rounds[n]
    d, ls, lb = r["delegation"], r.get("look_sent"), r.get("look_back")
    done = bool(lb and (lb.get("done") or lb.get("progress") is not None))
    head = f'#{n} at {d["t"]:.1f}s'
    if ls:
        head += f' — step {ls["step"]}'
    if lb:
        head += f' — brain {lb["model_ms"]} ms'
    if done:
        head += " — PROGRESS SET" + (f" to {lb['progress']}" if lb.get("progress") is not None else "")
    out.append(f'<div class="round{" done" if done else ""}"><h2>{e(head)}</h2>')
    out.append(f'<p class="meta">delegation {e(d["id"])}; words that came with it: {e(d.get("words") or "(none)")}</p>')
    if r.get("look_dropped"):
        out.append(f'<p class="meta">dropped: a newer delegation (#{r["look_dropped"].get("by")}) cancelled it</p>')
    if ls:
        out.append('<div class="grid"><div>')
        out.append(f'<div class="lbl">brain input: messages ({len(ls["turns"])} earlier turns, then the last user turn)</div>')
        out.append(details(f'{len(ls["turns"])} earlier turns (the call so far)', "".join(
            f'<div class="msg {role}"><b>{role}</b>: {e(text)}</div>' for role, text in ls["turns"]), open_=False))
        out.append('<div class="lbl">last user turn</div><div class="msg user">')
        if ls.get("photo"):
            out.append(f'<img src="{e(ls["photo"])}" alt="photo"><span class="meta">{e(ls["photo"])}, frame {ls.get("frame")}, '
                       f'{ls.get("frame_size")}, {ls.get("frame_age_ms")} ms old, {ls.get("photo_kb")} KB</span>')
        out.append(pre(ls["notice"]) + pre(ls["words"]) + "</div></div><div>")
    if lb:
        out.append('<div class="lbl">brain output</div>')
        out.append(f'<div class="msg out">{e(lb["reply"] or "(no text)")}</div>')
        out.append(f'<div class="meta">tool calls: {e(json.dumps(lb["calls"], ensure_ascii=False)) if lb["calls"] else "none"}'
                   f'{" — ignored: step " + str(lb["ignored_confirm"]) if lb.get("ignored_confirm") is not None else ""}{" — ignored: " + str(lb["ignored_progress"]) if lb.get("ignored_progress") is not None else ""}</div>')
        out.append(f'<div class="meta">usage: {e(json.dumps(lb.get("usage"), ensure_ascii=False))}; model {lb["model_ms"]} ms, '
                   f'total {lb["total_ms"]} ms</div>')
    if r.get("look_failed"):
        out.append(f'<div class="msg out">failed: {e(r["look_failed"].get("error", ""))}</div>')
    for s in r["sent"]:
        out.append(f'<div class="lbl">sent to GPT-Live at {s["t"]:.1f}s: {e(s.get("type", ""))} '
                   f'(delegation {e(str(s.get("delegation")))})</div><div class="msg live">{e(s.get("content") or "")}</div>')
    for a in r["live"]:
        out.append(f'<div class="meta">receipt {e(a["type"])} at {a["t"]:.1f}s for {e(str(a.get("for_id")))} '
                   f'start_ms={a.get("start_ms")} end_ms={a.get("end_ms")}</div>')
    if r.get("voice_started"):
        v = r["voice_started"]
        out.append(f'<div class="meta">voice started {v.get("after_commentary_ms")} ms after the commentary, '
                   f'{v.get("after_delegation_ms")} ms after the delegation{" (it was speaking when it arrived)" if v.get("was_speaking") else ""}</div>')
    if r.get("voice_silent"):
        out.append(f'<div class="meta">voice silent: {e(r["voice_silent"].get("why", ""))}</div>')
    for st in r["steps"]:
        out.append(f'<div class="meta">step change: done {st.get("done")}, reopened {st.get("reopened")}, now {st.get("now")}</div>')
    if r["said_after"]:
        out.append('<div class="lbl">what was said in this round</div>' + "".join(
            f'<div class="msg {"user" if s["who"] == "wearer" else "assistant"}">{s["t"]:.1f}s {e(s["who"])}: {e(s["text"])}</div>'
            for s in r["said_after"]))
    if ls:
        out.append("</div></div>")
    out.append("</div>")

(run / "rounds.html").write_text("\n".join(out), encoding="utf-8")
print(run / "rounds.html")
