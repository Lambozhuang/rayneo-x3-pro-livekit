"""Write eval/RESULTS.md = eval/results_notes.md (prose) + tables generated from what is on disk
(truck/results/*.jsonl, replay_*.json). The marker <!-- tables --> in the notes is where the tables go.

  python eval/results_table.py

Questions are named Q1..Q29 in the order of truck/rest.json; the first table lists them so that a miss can be
read as "which frame, which brick, what was expected". Every run's configuration is read from its own
prompt.txt header and file name, never from memory; the exact user text of every call is in its jsonl.
"""
from __future__ import annotations

import io
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TRUCK = ROOT / "truck"
RESULTS = TRUCK / "results"

ANS = {"correct": "对", "wrong": "错", "not_placed": "未放", "cannot_see": "看不见", "invalid": "无效", "moving": "移动中"}
CLIP_ORDER = ["run1_part1", "run1_part2_p1", "run1_part2_p2"]
CLIP_LEN = {"run1_part1": 62, "run1_part2_p1": 61, "run1_part2_p2": 25}


def load_json(p):
    return json.loads(p.read_text(encoding="utf-8"))


def questions():
    steps = {s["step"]: s for s in load_json(TRUCK / "layout.json")}
    qs = []
    for i, q in enumerate(load_json(TRUCK / "rest.json"), 1):
        qs.append({"id": f"Q{i}", "key": (q["clip"], q["frame"], q["step"]), "clip": q["clip"].replace("run1_", ""),
                   "sec": int(q["frame"][:3]) - 1, "step": q["step"], "brick": steps[q["step"]]["name"],
                   "expected": q["expected"], "why": q.get("why", "")})
    return qs


def q_table(qs):
    print("| 编号 | 片段 / 秒 | 问第几步 | 那块砖 | 期望答案 | 画面里是什么 |")
    print("|---|---|---|---|---|---|")
    for q in qs:
        print(f"| {q['id']} | {q['clip']} {q['sec']} s | {q['step']} | {q['brick']} | {ANS[q['expected']]} | {q['why']} |")


def header(run_dir: Path) -> dict:
    h = {}
    p = run_dir / "prompt.txt"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines()[:3]:
            for kv in line.split():
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    h[k] = v
    return h


def run_row(path: Path, qs):
    recs = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    byq = {q["key"]: q for q in qs}
    h = header(path.with_suffix(""))
    frames = "1080p15 派生" if "1080p15" in path.stem else "原始 2432×1824"
    ok = 0
    misses = []
    for r in recs:
        q = byq.get((r["clip"], r["frame"], r["step"]))
        qid = q["id"] if q else f"{r['clip']}/{r['frame']}s{r['step']}"
        if r["answer"] == r["expected"]:
            ok += 1
        else:
            misses.append(f"{qid} {ANS[r['expected']]}→{ANS.get(r['answer'], r['answer'])}")
    lat = sorted(r["latency"] for r in recs if r.get("latency"))
    tt = sorted(r["ttft"] for r in recs if r.get("ttft"))
    calls = [r for r in recs if r.get("usage")]
    tok = f"{st.mean(r['usage'].get('in', 0) for r in calls):.0f} / {st.mean(r['usage'].get('out', 0) for r in calls):.0f}" if calls else ""
    widths = [r["photo_size"][0] for r in recs if r.get("photo_size")]
    width = f"{st.median(widths):.0f}" if widths else "?"
    latency = f"{st.median(lat):.1f} / {lat[int(len(lat) * 0.9)]:.1f}" if lat else ""
    ttft = f"{st.median(tt):.1f}" if tt else "未记"
    return (f"| `{path.stem}` | {h.get('prompt', '?')} | {h.get('route', '?')} | {frames}，裁后 {width} px | {ok}/{len(recs)} | "
            f"{'；'.join(misses) or '—'} | {latency} | {ttft} | {tok} |")


def runs(prefix: str, qs):
    print("| 结果文件（模型_图detail_推理_prompt_其他） | prompt | 路线 | 帧源 | 对/总 | 答错的问题（期望→答） | 延迟中位 / p90 s | TTFT 中位 s | token 输入 / 输出 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for p in sorted(RESULTS.glob(f"{prefix}_*.jsonl")):
        print(run_row(p, qs))


def idx(clip, sec):
    return sum(CLIP_LEN[c] for c in CLIP_ORDER[:CLIP_ORDER.index(clip)]) + int(sec)


def replays():
    events = load_json(TRUCK / "events.json")
    for p in sorted(RESULTS.glob("replay_*_c*.json")):
        r = load_json(p)
        frames = "1080p15 派生" if "1080p15" in p.stem else "原始 2432×1824"
        asked = sum(1 for e in r["timeline"] if "answer" in e)
        print(f"\n**`{p.stem}`：{frames}帧，连续确认 {r['confirm']} 次，{r['model']}，判定调用 {asked} 次 / 148 帧**\n")
        print("| 步 | 真值完成（第几帧） | 系统推进（第几帧） | 差（秒） | 错误窗口（帧） | 报错时刻（帧） |")
        print("|---|---|---|---|---|---|")
        facts = r["facts"]
        for s in events["steps"]:
            n = s["step"]
            truth = idx(*s["done"])
            det = next((f for f in facts if f["kind"] == "done" and f["step"] == n), None)
            w = s.get("wrong")
            win = f"{idx(*w['from'])}–{idx(*w['to'])}" if w else ""
            al = ", ".join(str(f["i"]) for f in facts if f["kind"] == "wrong" and f["step"] == n) if w else ""
            if w and not al:
                al = "漏"
            print(f"| {n} | {truth} | {det['i'] if det else '没推进'} | {(det['i'] - truth) if det else ''} | {win} | {al} |")
        wrong_steps = {s["step"] for s in events["steps"] if s.get("wrong")}
        fa = [f"第 {f['step']} 步 @ 帧 {f['i']}（{f['text'].split(': ', 1)[-1]}）" for f in facts if f["kind"] == "wrong" and f["step"] not in wrong_steps]
        print(f"\n误报：{'；'.join(fa) if fa else '无'}")


def body():
    qs = questions()
    print("## 29 问是哪些\n")
    print("帧号 = 片段内秒数 + 1；下表用秒。每问只问当前步，期望答案由真值（events.json）给出。\n")
    q_table(qs)
    print("\n## 29 问各配置结果\n")
    runs("rest_C", qs)
    print()
    runs("rest_B", qs)
    print("\n## 6 问（Q8 Q9 Q13 Q14 Q22 Q23：3 个错 + 各自修正后的帧）各配置结果\n")
    runs("rest6", qs)
    print("\n## 回放\n")
    replays()


def main():
    buf = io.StringIO()
    sys.stdout = buf
    body()
    sys.stdout = sys.__stdout__
    notes = (ROOT / "results_notes.md").read_text(encoding="utf-8")
    out = notes.replace("<!-- tables -->", buf.getvalue())
    (ROOT / "RESULTS.md").write_text(out, encoding="utf-8")
    print("wrote", ROOT / "RESULTS.md", len(out), "chars")


if __name__ == "__main__":
    main()
