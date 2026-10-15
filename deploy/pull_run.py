"""Copy a call's record from the lab PC into logs/, build its page beside it, and save the glasses' log next to it.

    python deploy/pull_run.py            the newest call
    python deploy/pull_run.py <call>     that one (a directory name under backend/runs)

Writes logs/<call>/report.html (report.py). With the glasses on adb it also writes two more files:

    glasses.log   the app's call, link and speech lines (rayneo-call bounds each call with its room name;
                  LinkStatsLog.kt, SpeechEdgeLog.kt) from the device's log buffer, which holds every call since
                  the glasses were last launched by glasses.ps1; each line carries the glasses' wall clock
    clock.json    how far the glasses' clock is ahead of the server's, in ms, so those lines can be put on the
                  record's time axis: this PC asks both for the time over adb (USB) and ssh (LAN), neither of
                  which crosses the link under test, several times, and keeps the quickest exchange of each

Without the glasses it says so and leaves both out. logs/ is not in git.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

HOST = "ylab-pc"  # ssh alias of the lab PC
RUNS = "services/rayneo-x3-pro-livekit/backend/runs"  # RUN_DIR there, relative to the home directory

root = Path(__file__).resolve().parent.parent
logs = root / "logs"
logs.mkdir(exist_ok=True)
call = sys.argv[1] if len(sys.argv) > 1 else subprocess.run(
    ["ssh", HOST, f"ls -t {RUNS} | head -1"], check=True, capture_output=True, text=True).stdout.strip()
if not call:
    sys.exit(f"no call records under {HOST}:{RUNS}")
subprocess.run(["scp", "-q", "-r", f"{HOST}:{RUNS}/{call}", str(logs)], check=True)



def clock_ahead_ms(cmd: list[str], tries: int = 5) -> dict:
    """How far the clock `cmd` prints (epoch ns: `date +%s%N`, which GNU date and Android's toybox both give;
    GNU date ignores a width such as %3N) is ahead of this PC's, taken at the middle of the quickest exchange."""
    best = None
    for _ in range(tries):
        t0 = time.time()
        out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()
        t1 = time.time()
        sample = {"ahead_ms": round(int(out) / 1e6 - (t0 + t1) / 2 * 1000), "exchange_ms": round((t1 - t0) * 1000)}
        if best is None or sample["exchange_ms"] < best["exchange_ms"]:
            best = sample
    return best


devices = subprocess.run(["adb", "devices"], capture_output=True, text=True).stdout.splitlines()[1:]
if any(line.strip().endswith("device") for line in devices):
    with open(logs / call / "glasses.log", "w", encoding="utf-8") as f:
        subprocess.run(["adb", "logcat", "-d", "-v", "time", "-s", "rayneo-call", "rayneo-link", "rayneo-speech"], check=True, stdout=f)
    print(logs / call / "glasses.log")
    glasses = clock_ahead_ms(["adb", "shell", "date", "+%s%N"])
    server = clock_ahead_ms(["ssh", HOST, "date +%s%N"])
    clock = {"glasses_ahead_of_server_ms": glasses["ahead_ms"] - server["ahead_ms"],
             "measured_at_ms": round(time.time() * 1000), "glasses": glasses, "server": server}
    (logs / call / "clock.json").write_text(json.dumps(clock, indent=1), encoding="utf-8")
    print(f"{logs / call / 'clock.json'}: glasses clock {clock['glasses_ahead_of_server_ms']:+d} ms against the server's")
else:
    print("no glasses on adb: glasses.log and clock.json not written")

# The page last, since it draws the glasses' side when those two files are there.
subprocess.run([sys.executable, str(root / "deploy" / "report.py"), str(logs / call)], check=True)
