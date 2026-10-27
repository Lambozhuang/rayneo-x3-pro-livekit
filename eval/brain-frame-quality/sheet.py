"""Writes out/sheet.html: every frame's 1080 square beside its label and, when they exist, the model's replies.

    uv run python sheet.py [pictures-thinking ...]

With no argument the sheet shows the labels alone, for checking them against the pictures. Each argument names a
reply directory under out/replies/ (sq768-none, ...), whose reply for the frame is shown in a column of its own.
"""

import csv
import html
import json
import sys
import tomllib
from pathlib import Path

here = Path(__file__).resolve().parent
out = here / "out"
conds = sys.argv[1:]
labels = tomllib.load(open(here / "labels.toml", "rb"))["frame"]
secs = {r["id"]: r["t_s"] for r in csv.DictReader(open(out / "frames.csv"))}

def shown(r: dict) -> str:
    """A JSON reply as lines in the label's form; a reply that was not JSON as its text."""
    o = r.get("parsed")
    if not isinstance(o, dict):
        return r["text"]
    lines = [f"{b['colour']} {b['size']}, {b['orientation']}, {b['position']}" for b in o.get("bricks", [])]
    return "\n".join((lines or ["No bricks on the plate."]) + [f"Hands: {o.get('hands', '')}"])


rows = []
for fr in labels:
    fid = fr["id"]
    # the label in the form the probe asks the reply to take: a line per brick, then the Hands line
    lab = [f"{b['colour']} {b['size']}, {b['orientation']}, {html.escape(b['relation'])}"
           + (" <i>(held: may be listed here or in the Hands line)</i>" if b.get("held") else "")
           for b in fr["bricks"]] or ["No bricks on the plate."]
    hands = fr.get("hidden") or {"none": "no hand on or over the plate", "over": "a hand over the plate",
                                 "on": "a hand on the plate"}[fr["hands"]]
    lab.append(f"Hands: {html.escape(hands)}")
    cells = [f'<td><a href="sq1080/{fid}.jpg" target="_blank"><img src="sq1080/{fid}.jpg" width="640"></a>'
             f'<div class="id">{fid} · {secs[fid]} s · click for full size</div></td>',
             "<td>" + "<br>".join(lab) + "</td>"]
    for c in conds:
        p = out / "replies" / c / f"{fid}.json"
        if p.exists():
            r = json.loads(p.read_text(encoding="utf-8"))
            cells.append(f'<td><pre>{html.escape(shown(r))}</pre><div class="meta">{r["model_ms"]} ms, '
                         f'{r["in"]} in, {r["out"]} out</div></td>')
        else:
            cells.append("<td></td>")
    rows.append("<tr>" + "".join(cells) + "</tr>")

head = "".join(f"<th>{html.escape(c)}</th>" for c in conds)
(out / "sheet.html").write_text(f"""<!doctype html><meta charset="utf-8"><title>brain-frame-quality</title>
<style>body{{font:14px/1.4 Segoe UI,sans-serif;margin:16px}}table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;
padding:6px 8px;vertical-align:top;text-align:left}}pre{{white-space:pre-wrap;margin:0;font:13px/1.35 Consolas,monospace;
max-width:420px}}.id{{font-weight:600}}.meta{{color:#666;margin-top:4px}}</style>
<table><tr><th>frame</th><th>label</th>{head}</tr>{"".join(rows)}</table>""", encoding="utf-8")
print(out / "sheet.html")
