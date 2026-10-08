"""HTML of the three tool-version runs: each case with the image the model got, the truth, and every reply with its
tool calls; plus the two prompt versions. Writes tmp/brain-report/report.html (not in the repo)."""
import html, json, os, runpy, sys
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, "backend/agent/src")
from PIL import Image
from guide import load_guide
import gpt.brain as B
from gpt.prompts import brain_instructions

CASES = runpy.run_path("eval/brain/cases.py")["CASES"]
runs = [("A: tools, first prompt, no reasoning", "haiku-tools.json"),
        ("B: tools, revised prompt, no reasoning", "haiku-tools2.json"),
        ("C: tools, revised prompt, reasoning low", "haiku-tools2-low.json"),
        ("D: rewritten prompt (v3), no reasoning, 1080", "haiku-v3.json"),
        ("E: rewritten prompt (v3), reasoning medium, 1080", "haiku-v3-medium.json"),
        ("F: v3 + example format fix, Haiku reasoning low", "haiku-v3b-low.json"),
        ("G: v3 + example format fix, Sonnet 5.5 between_tools", "sonnet-v3b.json"),
        ("H: v3 + examples without tool marks + strict tools, Sonnet between_tools", "sonnet-v3c.json"),
        ("I: v3 + examples without tool marks + strict tools, Sonnet reasoning low", "sonnet-v3c-low.json")]
data = [(n, json.load(open(f"eval/brain/results/{f}"))) for n, f in runs]

# what each run sent: the tool paragraph of the first prompt (before the revision) and the revised prompt + tools
FIRST_TOOLS_PARAGRAPH = ("Reply in one or two short sentences of plain facts, not a script: what the photo shows that answers "
    "what the wearer said or asked; it need not be about the current step. Look; do not repeat the descriptions above. If the "
    "current step is not right, say what is wrong and what would make it right. If the plate or the spot is hidden, blurred or "
    "out of the picture, or the photo leaves you unsure, say what you cannot make out; do not say a brick is wrong unless the "
    "photo clearly shows it. The voice knows every step's wording and gives the next step itself; do not repeat step "
    "instructions.\n\nTools: call mark_step_done when the photo shows the current step's brick in place and every one of its "
    "facts holds, never on the wearer's word alone and never when you are unsure; call end_call when the wearer says goodbye "
    "or wants to stop. Your reply still goes to the voice either way.\nWrite in English.\n\n"
    "Tool descriptions:\n- mark_step_done(step): Record that the current step is done. Call it only when the photo shows the "
    "current step's brick in place and every one of its facts holds; not on the wearer's word alone, and not when you are "
    "unsure. step = the current step's number.\n- end_call(): End the call, when the wearer says goodbye or wants to stop.")
guide = load_guide("guides/truck")
NL = chr(10)
revised = (brain_instructions(guide, "English") + NL + NL + "Tool descriptions:" + NL
           + NL.join(f"- {n}: {d}" for n, d, _ in B.TOOLS))

os.makedirs("tmp/brain-report/img_sq", exist_ok=True)
out = ["<meta charset='utf-8'><style>body{font-family:sans-serif;background:#111;color:#ddd;max-width:1600px;margin:auto}"
       "td{vertical-align:top;padding:4px 8px;border-top:1px solid #333}.ok{color:#7d7}.bad{color:#f77}.call{color:#fc6}"
       "img{width:340px}h2{margin-top:36px}pre{white-space:pre-wrap;background:#1b1b1b;padding:10px;font-size:13px}"
       "summary{cursor:pointer;color:#9cf}</style>",
       "<h1>Tool-version brain: 15 cases x 3, frame's bottom square (A-C at 1024, D-G at 1080); Haiku 5.5 unless named</h1>",
       "<p>Each look is standalone: no earlier conversation, the timeline holds one line (the voice just read the current "
       "step). Frames from eval/brain/frames (the last full lab run, 2026-10-07). M, N, O are questions written for the test, not "
       "asked in the run. Green = the step came out right, red = wrong. Tool calls in orange.</p>"]
for name, d in data:
    R = d["rows"]
    ok = sum(r["ok_step"] for r in R)
    secs = sorted(r["secs"] for r in R)
    out.append(f"<p><b>{name}</b>: steps right {ok}/{len(R)}, median {secs[len(secs)//2]:.2f} s, max {secs[-1]:.2f} s</p>")
out.append("<details><summary>The prompt in the repo now (v3 with the last example fix; D-G ran earlier drafts, see git history), with the tool descriptions</summary><pre>"
           + html.escape(revised) + "</pre></details>")
out.append("<details><summary>Prompt A: what differed (the last paragraph and the tool descriptions)</summary><pre>"
           + html.escape(FIRST_TOOLS_PARAGRAPH) + "</pre></details>")

for cid, fr, step, words, after, truth in CASES:
    img = Image.open(f"eval/brain/frames/{fr}.jpg").convert("RGB")
    w, h = img.size; s = min(w, h)
    sq = img.crop(((w - s) // 2, h - s, (w - s) // 2 + s, h)); sq.thumbnail((1024, 1024))
    sq.save(f"tmp/brain-report/img_sq/{cid}.jpg", quality=85)
    out.append(f"<h2>{cid} &nbsp; frame {fr} &nbsp; on step {step}: “{html.escape(words)}”</h2>"
               f"<p><b>Truth:</b> step after = {after}; {html.escape(truth)}</p><table><tr>"
               f"<td><img src='img_sq/{cid}.jpg'></td><td><table>")
    for name, d in data:
        for r in d["rows"]:
            if r["case"] != cid:
                continue
            if "error" in r:
                out.append(f"<tr><td>{name[:2]} #{r['rep']+1}</td><td class=bad>{html.escape(r['error'])}</td></tr>")
                continue
            o = r["out"]; cls = "ok" if r["ok_step"] else "bad"
            calls = ", ".join(f"{c}({json.dumps(a)})" for c, a in o["calls"]) or "no tool call"
            out.append(f"<tr><td style='width:120px'>{name[:2]} #{r['rep']+1}<br>{r['secs']} s<br>"
                       f"<span class={cls}>step → {o['step']}</span></td>"
                       f"<td><span class=call>{html.escape(calls)}</span><br>{html.escape(o['text'])}</td></tr>")
    out.append("</table></td></tr></table>")
open("tmp/brain-report/report.html", "w", encoding="utf-8").write("\n".join(out))
print("tmp/brain-report/report.html")
