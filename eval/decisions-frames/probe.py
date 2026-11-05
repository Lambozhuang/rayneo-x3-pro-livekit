"""Send each frame of a frames file to the Decisions API with the task's text and the eight questions, and score the answers.

    uv run python decisions-frames/probe.py situations.toml                 every frame, detail high
    uv run python decisions-frames/probe.py situations.toml --detail low
    uv run python decisions-frames/probe.py situations.toml --reference     the step's rendered picture goes with the frame
    uv run python decisions-frames/probe.py situations.toml --dry           print each frame's developer text and the questions, send nothing
    uv run python decisions-frames/probe.py situations.toml --side 512      the frame scaled to 512 px before sending
    uv run python decisions-frames/probe.py bricks.toml                     the brick frames with the brick battery

Run from eval/ (the pyproject there). The key is OPENAI_API_KEY in backend/.env. One request a frame carries the developer
text written from the task file, the frame as the brain's 1080 px photo, and the same eight questions every time; the
answers are scored against the `expect` table of the frames file, written to out/<frames>-<detail>[-ref].json (every
answer) and out/<frames>-<detail>[-ref].md (the table), and printed.
"""

import argparse
import base64
import json
import statistics
import sys
import time
import http.client
import tomllib
from pathlib import Path

here = Path(__file__).resolve().parent
root = here.parent.parent
GUIDES = root / "backend" / "agent" / "guides"
HOST, PATH = "api.openai.com", "/v1/decisions"

WRONG_HOW = ["nothing", "not placed yet", "wrong brick", "wrong orientation", "wrong position"]
DIRECTIONS = ["left", "right", "up", "down"]


def load_key() -> str:
    env = root / "backend" / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENAI_API_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit(f"no OPENAI_API_KEY in {env}")


def developer_text(task: dict, step: int) -> str:
    """What the system would tell the model about the build and the step: the scene, the directions, the bricks, what is
    placed already and what the current step asks for. The same text for every look within a step."""
    steps = task["steps"]
    plate = task["plate"]
    placed = "\n".join(f"{i}. {s['brick']}: {s['place']}" for i, s in enumerate(steps[: step - 1], 1)) or "none"
    cur = steps[step - 1]
    return (
        "You see one photo taken just now by the camera of a pair of AR glasses on a person building a small LEGO model, "
        f"\"{task['title']}\", on a {plate}x{plate} baseplate on a desk; loose bricks lie around the plate. Directions on "
        "the plate are as the builder sees it: up is the far edge, down the near edge; vertical means a brick's long side "
        "runs up and down, horizontal that it runs left and right. A brick's size counts its studs: a 1x6 is one stud "
        "wide and six long.\n\n"
        f"The bricks of this build: {', '.join(s['brick'] for s in steps)}.\n\n"
        f"Placed in the steps before:\n{placed}\n\n"
        f"The current step, step {step}: {cur['brick']}, {cur['place']}.\n\n"
        "\"The current step's brick\" in the questions means that brick."
    )


def questions(battery: str = "situations", bricks: list[str] | None = None) -> list[dict]:
    """The situations battery is the eight questions a frame of a build can settle; the bricks battery asks only about
    the brick in the hand, with a choice over the task's bricks so the answer names what it took the brick for."""
    def p(name: str, text: str) -> dict:
        return {"name": name, "type": "predicate", "instructions": text}

    def c(name: str, text: str, values: list[str]) -> dict:
        return {"name": name, "type": "choice", "instructions": text, "choices": [{"value": v} for v in values]}

    if battery == "bricks":
        return [
            p("brick_in_hand", "The builder holds a brick in the air, not resting on the desk or on the baseplate."),
            p("in_hand_is_step", "The brick the builder holds is the current step's brick: the same colour and the same size."),
            c("in_hand_which", "Which brick does the builder hold?", (bricks or []) + ["another brick", "none"]),
        ]
    return [
        p("plate_visible", "The baseplate is in the picture and the picture is sharp enough to see its studs."),
        p("hand_on_plate", "A hand is on the baseplate or on a brick that is on the baseplate."),
        p("brick_in_hand", "The builder holds a brick in the air, not resting on the desk or on the baseplate."),
        p("in_hand_is_step", "The brick the builder holds is the current step's brick: the same colour and the same size."),
        p("step_on_plate", "The current step's brick is on the baseplate with no hand on it."),
        p("step_right", "The current step's brick is on the baseplate, placed exactly as the current step describes."),
        c("step_wrong_how", "What is wrong with the current step's brick on the baseplate?", WRONG_HOW),
        c("off_direction", "If the current step's brick is in the wrong position on the baseplate, which way does it have to move?", DIRECTIONS),
    ]


def data_url(path: Path, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def frame_url(path: Path, side: int | None) -> str:
    """The frame as a JPEG data URL, scaled to `side` px when one is given (the stored frames are the brain's 1080 square)."""
    if not side:
        return data_url(path, "image/jpeg")
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.open(path).resize((side, side), Image.LANCZOS).save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def body(frame: dict, task: dict, folder: Path, detail: str, reference: bool, model: str, side: int | None,
         battery: str) -> dict:
    content: list[dict] = []
    if reference:
        content.append({"type": "input_text", "text": "The first picture shows how the plate should look when the current "
                                                      "step is done, the current step's brick outlined; the second is the camera's photo."})
        content.append({"type": "input_image", "detail": detail,
                        "image_url": data_url(GUIDES / frame["task"] / f"step-{frame['step']}.png", "image/png")})
    content.append({"type": "input_image", "detail": detail, "image_url": frame_url(folder / frame["file"], side)})
    return {"model": model,
            "input": [{"role": "developer", "content": developer_text(task, frame["step"])},
                      {"role": "user", "content": content}],
            "questions": questions(battery, [st["brick"] for st in task["steps"]])}


def score(expect: dict, answers: dict, qs: list[dict]) -> list[tuple[str, str, str, bool | None]]:
    """One row a question: name, expected, got, right or None when the frame does not score it. A predicate counts as
    yes at 0.5 and above; off_direction is read only when the frame's wrong_how is wrong position."""
    rows = []
    for q in qs:
        name, a, exp = q["name"], answers.get(q["name"]), expect.get(q["name"])
        if name == "off_direction" and expect.get("step_wrong_how") != "wrong position":
            exp = None
        if a is None or a.get("type") == "refusal":
            rows.append((name, "" if exp is None else str(exp).lower(), "refusal", None if exp is None else False))
        elif q["type"] == "predicate":
            prob = a["probability"]
            rows.append((name, "" if exp is None else str(exp).lower(), f"{prob:.2f}", None if exp is None else (prob >= 0.5) == exp))
        else:
            rows.append((name, "" if exp is None else exp, f"{a['choice']} ({a['confidence']:.2f})", None if exp is None else a["choice"] == exp))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", help="a frames file in this directory, such as situations.toml")
    ap.add_argument("--detail", default="high", choices=["low", "high"])
    ap.add_argument("--reference", action="store_true", help="send the step's rendered picture before the frame")
    ap.add_argument("--side", type=int, help="scale the frame to this many px a side before sending; 1080 as stored otherwise")
    ap.add_argument("--model", default="gpt-6-luna")
    ap.add_argument("--dry", action="store_true", help="print what would be sent and stop")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # the table's marks on a Windows console

    spec = tomllib.loads((here / args.frames).read_text(encoding="utf-8"))
    folder = root / spec["folder"]
    frames = spec["frame"]
    battery = spec.get("questions", "situations")
    tasks = {t: tomllib.loads((GUIDES / t / "task.toml").read_text(encoding="utf-8")) for t in {f["task"] for f in frames}}
    for f in frames:
        if battery == "bricks":  # the held brick is the step's brick: that is how the frames were picked
            f["expect"] = {"brick_in_hand": True, "in_hand_is_step": True, "in_hand_which": f["brick"]}

    if args.dry:
        for f in frames:
            print(f"=== {f['file']}\n{developer_text(tasks[f['task']], f['step'])}\n")
        print("=== questions\n" + json.dumps(questions(battery, [st["brick"] for st in tasks[frames[0]["task"]]["steps"]]), indent=1))
        return

    headers = {"Authorization": f"Bearer {load_key()}", "Content-Type": "application/json"}
    tag = f"{Path(args.frames).stem}-{args.detail}" + (f"-{args.side}" if args.side else "") + ("-ref" if args.reference else "")
    out = here / "out"
    out.mkdir(exist_ok=True)
    results, times = [], []
    names = [q["name"] for q in questions(battery)]
    lines = ["| frame | ms | " + " | ".join(names) + " |", "|" + "---|" * (len(names) + 2)]
    right = scored = 0
    # One connection for the whole run, opened before the first request, as the agent would keep it: the time of a
    # request is then the server's, not a TLS handshake's. A 503 "Decision inference is unavailable" came once on
    # 2026-11-05; such an answer is retried twice after a second.
    conn = http.client.HTTPSConnection(HOST, timeout=60)
    conn.connect()
    retries = 0
    for f in frames:
        b = json.dumps(body(f, tasks[f["task"]], folder, args.detail, args.reference, args.model, args.side, battery))
        for attempt in range(3):
            t0 = time.perf_counter()
            try:
                conn.request("POST", PATH, body=b, headers=headers)
                resp = conn.getresponse()
                raw = resp.read()
            except (http.client.HTTPException, OSError) as e:
                conn.close()
                conn.connect()
                if attempt == 2:
                    sys.exit(f"{f['file']}: {e}")
                retries += 1
                continue
            ms = round((time.perf_counter() - t0) * 1000)
            if resp.status == 200:
                break
            if resp.status in (500, 502, 503, 504) and attempt < 2:
                print(f"  {f['file'].split('__')[0]}: HTTP {resp.status} {raw[:120]!r}, retrying")
                retries += 1
                time.sleep(1.0)
                continue
            sys.exit(f"{f['file']}: HTTP {resp.status}: {raw[:300]!r}")
        data = json.loads(raw)
        answers = {a.get("name"): a for a in data.get("answers", [])}
        rows = score(f.get("expect", {}), answers, questions(battery, [st["brick"] for st in tasks[f["task"]]["steps"]]))
        cells = []
        for _, exp, got, ok in rows:
            mark = "" if ok is None else (" ✓" if ok else f" ✗ ({exp})")
            cells.append(got + mark)
            scored += ok is not None
            right += bool(ok)
        lines.append(f"| {f['file'].split('__')[0]} | {ms} | " + " | ".join(cells) + " |")
        times.append(ms)
        results.append({"file": f["file"], "task": f["task"], "step": f["step"], "ms": ms, "usage": data.get("usage"),
                        "answers": data.get("answers")})
        print(lines[-1])
    summary = (f"\n{right} of {scored} scored answers right; request time median {statistics.median(times):.0f} ms, "
               f"max {max(times)} ms; detail {args.detail}" + (f", {args.side} px" if args.side else ", 1080 px")
               + (", with the step's picture" if args.reference else "")
               + (f"; {retries} retried" if retries else "") + ".")
    print(summary)
    (out / f"{tag}.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    (out / f"{tag}.md").write_text("\n".join(lines) + "\n" + summary + "\n", encoding="utf-8")
    print(f"written {out / f'{tag}.json'} and {out / f'{tag}.md'}")


if __name__ == "__main__":
    main()
