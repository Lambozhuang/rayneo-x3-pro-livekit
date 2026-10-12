"""Copy a call's record from the lab PC into logs/ and build both pages beside it.

    python deploy/pull_run.py            the newest call
    python deploy/pull_run.py <call>     that one (a directory name under backend/runs)

Writes logs/<call>/report.html (report.py) and logs/<call>/rounds.html (rounds.py). logs/ is not in git.
"""

import subprocess
import sys
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
for page in ("report.py", "rounds.py"):
    subprocess.run([sys.executable, str(root / "deploy" / page), str(logs / call)], check=True)
print(logs / call / "rounds.html")
