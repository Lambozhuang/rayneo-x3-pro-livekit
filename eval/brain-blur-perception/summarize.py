"""Tables from probe.py's replies: the sharpness grades per condition and pass, the agreement of the two passes, and
how often the studs were called countable and sizes read.

    cd backend/agent && uv run --no-sync python ../../eval/brain-blur-perception/summarize.py

Prints Markdown: one row per condition with the share of each grade (both passes pooled), the share of photos the two
passes graded alike, the share called studs-countable, and the share of brick entries whose size is "can't tell".
"""

import json
from collections import Counter
from pathlib import Path

here = Path(__file__).resolve().parent
out = here / "out" / "replies"
GRADES = ["clear", "slightly blurry", "blurry"]
ORDER = ["sq1080", "hevc-v1000", "hevc-v500", "hevc-v250", "hevc-v100", "real-open", "real-capped",
         "real-rtt1000", "real-cap500", "real-cap250-pilot2"]
NAMES = {"sq1080": "codec study, as recorded", "hevc-v1000": "codec study, H.265 1 Mbps", "hevc-v500": "codec study, H.265 0.5 Mbps",
         "hevc-v250": "codec study, H.265 0.25 Mbps", "hevc-v100": "codec study, H.265 0.1 Mbps",
         "real-open": "real call, no cap (12:30)", "real-capped": "real call, 0.25 Mbps cap (10:38)",
         "real-rtt1000": "pilot 2 run 4, no cap, +1000 ms", "real-cap500": "pilot 2 run 5, 0.5 Mbps cap",
         "real-cap250-pilot2": "pilot 2 run 6, 0.25 Mbps cap"}


def replies(cond: str, n: int) -> dict[str, dict]:
    d = out / f"{cond}-pass{n}"
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))} if d.exists() else {}


def main() -> None:
    print("| condition | photos | clear | slightly blurry | blurry | not clear | both passes alike | studs countable | sizes can't tell | photo KB |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for cond in ORDER:
        p1, p2 = replies(cond, 1), replies(cond, 2)
        if not p1:
            continue
        grades = Counter()
        alike = countable = total = 0
        sizes = unread = 0
        kb = []
        for fid, r1 in p1.items():
            for r in (r1, p2.get(fid)):
                if r is None or r.get("parsed") is None:
                    continue
                g = r["parsed"]["sharpness"]
                grades[g] += 1
                total += 1
                countable += bool(r["parsed"].get("studs_countable"))
                for b in r["parsed"].get("bricks", []):
                    sizes += 1
                    unread += b.get("size") == "can't tell"
                kb.append(r["photo_kb"])
            r2 = p2.get(fid)
            if r2 and r1.get("parsed") and r2.get("parsed"):
                alike += r1["parsed"]["sharpness"] == r2["parsed"]["sharpness"]
        n = len(p1)
        pct = lambda x, d: f"{100 * x / d:.0f}%" if d else "-"  # noqa: E731
        print(f"| {NAMES[cond]} | {n} | {pct(grades['clear'], total)} | {pct(grades['slightly blurry'], total)} | "
              f"{pct(grades['blurry'], total)} | {pct(total - grades['clear'], total)} | {pct(alike, n) if p2 else '-'} | "
              f"{pct(countable, total)} | {pct(unread, sizes)} | {sorted(kb)[len(kb) // 2] if kb else '-'} |")


if __name__ == "__main__":
    main()
