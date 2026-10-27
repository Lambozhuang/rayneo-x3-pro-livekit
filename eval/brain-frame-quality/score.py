"""Scores the replies of one or more conditions against labels.toml, field by field.

    uv run python score.py <pictures-thinking> [...]

A reply is the JSON object probe.py asked for: bricks with colour, size, orientation and position, and hands. Bricks
are matched to the label by colour (the five bricks of the flag have five colours, and the model's words for them
are mapped in COLOURS). One rule for every frame:

- a labelled brick the reply has no entry for is missed, unless every item of its label is can't tell, when leaving
  it out is right; a brick labelled held (the hand holds it on the plate) also counts as found when its colour is
  named in hands;
- a colour the label does not have is extra, unless the entry says can't tell for both size and orientation;
- a labelled size or orientation is right when the reply gives the same value (2x4 and 4x2 are the same), and a
  labelled can't tell is right when the reply writes can't tell; a definite value against a labelled can't tell is a
  guess and counts as wrong, whatever the value.

The position and the hands text are not compared here; sheet.py shows them beside the label for a person to judge.
A frame is "whole" when every labelled brick is found, every size and orientation is right (can't tell included) and
nothing is extra.

Prints one table with a row per condition, then the sizes read right by the brick's true size, then a matrix of
frames by condition: `.` whole, `s` a size wrong, `o` an orientation wrong, `g` a guess where the label says can't
tell, `m` a brick missed, `x` an extra brick; several letters when several apply; `!` a reply that was not JSON.
"""

import json
import re
import sys
import tomllib
from pathlib import Path

here = Path(__file__).resolve().parent
out = here / "out"
labels = tomllib.load(open(here / "labels.toml", "rb"))["frame"]

UNREAD = "can't tell"
COLOURS = {  # what the model may call each brick's colour
    "white": ("white",),
    "tan": ("tan", "beige", "cream", "sand", "light yellow", "pale yellow", "khaki", "light brown", "yellowish",
            "light orange"),
    "red": ("red",),
    "blue": ("blue",),
    "dark grey": ("dark grey", "dark gray", "grey", "gray", "dark bluish grey", "dark bluish gray", "black"),
}


def colour_of(text: str) -> str:
    t = re.sub(r"\s*\([^)]*\)", "", text).lower().strip()
    for name, words in COLOURS.items():
        if any(t == w or t.endswith(" " + w) or t.startswith(w) for w in words):
            return name
    return t


def norm_size(size: str) -> str:
    s = size.lower().replace("×", "x").replace(" ", "")
    if "tell" in s or "unclear" in s or "unknown" in s:
        return UNREAD
    m = re.fullmatch(r"(\d{1,2})x(\d{1,2})", s)
    return "x".join(sorted(m.groups(), key=int)) if m else s


def norm_orient(orient: str) -> str:
    o = orient.lower().strip()
    return UNREAD if "tell" in o or "unclear" in o or "unknown" in o else o


def bricks_of(reply: dict) -> dict:
    """The reply's bricks by colour, each {size, orientation}, values normalised."""
    return {colour_of(b["colour"]): {"size": norm_size(b["size"]), "orientation": norm_orient(b["orientation"])}
            for b in reply.get("bricks", [])}


def all_unread(b: dict) -> bool:
    return b["size"] == UNREAD and b["orientation"] == UNREAD


def score(cond: str) -> tuple[dict, dict]:
    tot = {"frames": 0, "whole": 0, "bricks": 0, "found": 0, "items": 0, "size": 0, "orient": 0, "guess": 0,
           "extra": 0, "ms": [], "in": 0}
    marks = {}
    for fr in labels:
        p = out / "replies" / cond / f"{fr['id']}.json"
        if not p.exists():
            marks[fr["id"]] = " "
            continue
        r = json.loads(p.read_text(encoding="utf-8"))
        tot["frames"] += 1
        tot["ms"].append(r["model_ms"])
        tot["in"] += r["in"]
        if not isinstance(r.get("parsed"), dict):
            marks[fr["id"]] = "!"
            continue
        got = bricks_of(r["parsed"])
        hands = r["parsed"].get("hands", "").lower()
        flags = set()
        for b in fr["bricks"]:
            tot["bricks"] += 1
            g = got.pop(b["colour"], None)
            if g is None:
                if all_unread(b) and b.get("relation") == UNREAD:
                    tot["found"] += 1  # a brick with every item can't tell is rightly left out
                elif b.get("held") and b["colour"] in hands:
                    tot["found"] += 1
                else:
                    flags.add("m")
                continue
            tot["found"] += 1
            for item, key, flag in (("size", "size", "s"), ("orientation", "orient", "o")):
                tot["items"] += 1
                want = norm_size(b[item]) if item == "size" else norm_orient(b[item])
                if want == UNREAD:
                    if g[item] == UNREAD:
                        tot[key] += 1
                    else:
                        tot["guess"] += 1
                        flags.add("g")
                elif g[item] == want:
                    tot[key] += 1
                else:
                    flags.add(flag)
        extras = [c for c, g in got.items() if not all_unread(g)]
        if extras:
            tot["extra"] += len(extras)
            flags.add("x")
        if not flags:
            tot["whole"] += 1
        marks[fr["id"]] = "".join(sorted(flags)) or "."
    return tot, marks


BY_SIZE = ("1x4", "1x6", "2x4", "2x6")


def by_size(cond: str) -> dict:
    """For each labelled size, how many bricks found had their size read right, and how many were found."""
    by = {s: [0, 0] for s in BY_SIZE}
    for fr in labels:
        p = out / "replies" / cond / f"{fr['id']}.json"
        if not p.exists():
            continue
        r = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(r.get("parsed"), dict):
            continue
        got = bricks_of(r["parsed"])
        for b in fr["bricks"]:
            g = got.get(b["colour"])
            if g and b["size"] in by:
                by[b["size"]][1] += 1
                by[b["size"]][0] += g["size"] == norm_size(b["size"])
    return by


def main(conds: list[str]) -> None:
    results = {c: score(c) for c in conds}
    print(f"{'condition':<18}{'frames':>7}{'whole':>7}{'found':>8}{'size':>9}{'orient':>9}{'guess':>6}{'extra':>6}"
          f"{'ms p50':>8}{'in/call':>9}")
    for c, (t, _) in results.items():
        if not t["frames"]:
            print(f"{c:<18} no replies")
            continue
        n = t["items"] // 2
        ms = sorted(t["ms"])
        print(f"{c:<18}{t['frames']:>7}{t['whole']:>7}{t['found']:>4}/{t['bricks']:<4}{t['size']:>5}/{n:<4}"
              f"{t['orient']:>5}/{n:<4}{t['guess']:>5}{t['extra']:>6}{ms[len(ms) // 2]:>8}{t['in'] // t['frames']:>9}")
    print()
    print("size read right, by the brick's size (bricks found whose size shows):")
    print(f"{'condition':<18}" + "".join(f"{s:>9}" for s in BY_SIZE))
    for c in conds:
        by = by_size(c)
        print(f"{c:<18}" + "".join(f"{by[s][0]:>5}/{by[s][1]:<3}" for s in BY_SIZE))
    print()
    print(f"{'frame':<6}" + "".join(f"{c:>{max(len(c), 5) + 1}}" for c in conds))
    for fr in labels:
        print(f"{fr['id']:<6}" + "".join(f"{results[c][1][fr['id']]:>{max(len(c), 5) + 1}}" for c in conds))


if __name__ == "__main__":
    main(sys.argv[1:])
