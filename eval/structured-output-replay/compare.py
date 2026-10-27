"""Puts each look's original decisions beside the replayed ones and counts where they agree.

    uv run python compare.py <record dir>

Per look: the set_progress value (- when not called), the number of notes and of says, and the start of the reply,
original on the left and replay on the right; then the counts of looks where progress, notes and says agree. A
replay that was not valid JSON shows as "not json".
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay import looks  # noqa: E402

here = Path(__file__).resolve().parent
rec = Path(sys.argv[1])


def original(back: dict) -> dict:
    prog, notes, says = None, 0, 0
    for name, args in back["calls"]:
        if name == "set_progress":
            prog = args.get("done")
        elif name == "note":
            notes += 1
        elif name == "say":
            says += 1
    return {"progress": prog, "notes": notes, "says": says, "reply": back["reply"]}


def replayed(r: dict) -> dict | None:
    p = r.get("parsed")
    if not isinstance(p, dict):
        return None
    sp = p.get("set_progress")
    return {"progress": sp.get("done") if isinstance(sp, dict) else None,
            "notes": len(p.get("note") or []), "says": len(p.get("say") or []), "reply": p.get("reply", "")}


def cell(d: dict) -> str:
    return f"{'-' if d['progress'] is None else d['progress']:>2} {d['notes']}n {d['says']}s"


agree = {"progress": 0, "notes": 0, "says": 0, "all": 0}
n = 0
print(f"{'look':<5}{'original':<12}{'replay':<12}  reply (original | replay)")
for look in looks(rec):
    p = here / "out" / f"{look['id']}.json"
    if not p.exists():
        continue
    o = original(look["back"])
    r = replayed(json.loads(p.read_text(encoding="utf-8")))
    n += 1
    if r is None:
        print(f"{look['id']:<5}{cell(o):<12}{'not json':<12}")
        continue
    same = {k: o[k] == r[k] for k in ("progress", "notes", "says")}
    for k, v in same.items():
        agree[k] += v
    agree["all"] += all(same.values())
    mark = "" if all(same.values()) else " <-"
    print(f"{look['id']:<5}{cell(o):<12}{cell(r):<12}{mark:<3}{o['reply'][:50]!r} | {r['reply'][:50]!r}")
print()
print(f"{n} looks: progress agrees in {agree['progress']}, notes in {agree['notes']}, says in {agree['says']}, "
      f"all three in {agree['all']}")
