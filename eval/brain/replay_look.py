"""Replay one look of a recorded call through the brain's own model clients (Anthropic, or openai:VAR:effort), exactly as sent (the run's brain.txt,
turns, notice, words, photo), under several model configs, keeping the thinking text.

    replay_look.py <run dir> <look n> <repeats> <MODEL_ENV_VAR:effort> [...]   -> <run dir>/replay-look<n>.json/.html
"""
import asyncio, html, json, os, sys, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend", "agent", "src"))
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, "backend", ".env"))
import gpt.brain as B

run, n, repeats, configs = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4:]
events = [json.loads(l) for l in open(os.path.join(run, "events.jsonl"), encoding="utf-8")]
sent = next(e for e in events if e["kind"] == "look_sent" and e["n"] == n)
back = next(e for e in events if e["kind"] == "look_back" and e["n"] == n)
instructions = open(os.path.join(run, "brain.txt"), encoding="utf-8").read()
photo = open(os.path.join(run, sent["photo"]), "rb").read()
turns = [tuple(t) for t in sent["turns"]]


async def one(provider, var, effort):
    model = os.environ[var]
    got = {}
    if provider == "openai":
        m = B.OpenAIModel(model, effort, "high")
        create = m._client.responses.create

        async def keep(**kw):
            if "reasoning" in kw:  # return a summary of the reasoning
                kw["reasoning"] = {**kw["reasoning"], "summary": "auto"}
            got["resp"] = r = await create(**kw)
            return r
        m._client.responses.create = keep
    else:
        m = B.AnthropicModel(model, effort)
        create = m._client.messages.create

        async def keep(**kw):
            if kw.get("thinking", {}).get("type") == "adaptive":  # return the thinking text (5.x omits it by default)
                kw["thinking"] = {**kw["thinking"], "display": "summarized"}
            got["resp"] = r = await create(**kw)
            return r
        m._client.messages.create = keep
    t0 = time.perf_counter()
    try:
        reply, calls, u = await m.ask(instructions, turns, sent["notice"], sent["words"], photo, "replay")
    except Exception as e:
        return {"model": model, "effort": effort, "error": f"{type(e).__name__}: {e}"[:300]}
    secs = time.perf_counter() - t0
    if provider == "openai":
        thinking = "\n".join(x.text for o in got["resp"].output if o.type == "reasoning" for x in (o.summary or []))
    else:
        thinking = "\n".join(getattr(b, "thinking", "") or "" for b in got["resp"].content if b.type == "thinking")
    return {"model": model, "effort": effort, "secs": round(secs, 2), "reply": reply, "calls": calls,
            "confirm": any(c == "confirm_step_correct" and a.get("step") == sent["step"] for c, a in calls),
            "thinking": thinking, "usage": u}


async def main():
    rows = []
    for spec in configs:
        parts = spec.split(":")
        provider, var, effort = parts if len(parts) == 3 else ["anthropic", *parts]
        for _ in range(repeats):
            r = await one(provider, var, effort)
            rows.append(r)
            print(f"{r['model']} {effort}: {r.get('secs')} s confirm={r.get('confirm')} | {r.get('reply', r.get('error'))[:150]}")
    out = os.path.join(run, f"replay-look{n}" + (os.environ.get("TAG") or ""))
    json.dump({"look": n, "step": sent["step"], "recorded_reply": back["reply"], "rows": rows},
              open(out + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    page = [f"<meta charset=utf-8><style>body{{font-family:sans-serif;background:#111;color:#ddd;margin:20px}}"
            f"td{{vertical-align:top;padding:6px 10px;border-top:1px solid #333}}pre{{white-space:pre-wrap;font-size:12px;"
            f"background:#1b1b1b;padding:8px}}.ok{{color:#7d7}}.bad{{color:#f77}}summary{{color:#9cf;cursor:pointer}}</style>",
            f"<h2>Look #{n} replayed (step {sent['step']}), {repeats}x per config</h2>",
            f"<img src='{sent['photo']}' width=540 style='float:left;margin-right:16px'>",
            f"<p>wearer: {html.escape(sent['words'])}</p><p>recorded reply: {html.escape(back['reply'])}</p>"
            f"<p>truth: the step is right (four empty columns, ends level), so the right answer confirms step {sent['step']}.</p>"
            "<div style='clear:both'></div><table>"]
    for r in rows:
        ok = r.get("confirm")
        page.append(f"<tr><td>{r['model']}<br>{r['effort']}<br>{r.get('secs')} s<br>"
                    f"<span class={'ok' if ok else 'bad'}>{'confirm' if ok else 'no confirm'}</span></td>"
                    f"<td>{html.escape(r.get('reply') or r.get('error') or '')}<details><summary>thinking "
                    f"({(r.get('usage') or {}).get('thinking')} tokens)</summary><pre>{html.escape(r.get('thinking') or '')}"
                    f"</pre></details></td></tr>")
    open(out + ".html", "w", encoding="utf-8").write("".join(page) + "</table>")
    print(out + ".html")

asyncio.run(main())
