"""Start the backend on a server from this PC, with the architecture chosen.

    python deploy/backend.py lab openai      the lab PC runs GPT-Live and the vision model
    python deploy/backend.py home gemini     the home machine runs Gemini Live
    python deploy/backend.py lab down        the lab PC stops all three containers

Over ssh it pulls the server's checkout forward, writes AGENT_BACKEND into
backend/.env there, builds and starts the three containers, and waits for the
agent to register with livekit-server. It stops with the agent's log when the
agent does not register, which is how a missing key in .env shows up. Running
it again is safe; the agent is restarted every time, so a call in progress
is cut off.
"""

import subprocess
import sys

SERVERS = {  # ssh alias and the repo's path there, relative to the home directory
    "lab": ("ylab-pc", "services/rayneo-x3-pro-livekit"),
    "home": ("lambos-ubuntu", "Workspace/rayneo-x3-pro-livekit"),
}
ACTIONS = ("openai", "gemini", "down")

if len(sys.argv) != 3 or sys.argv[1] not in SERVERS or sys.argv[2] not in ACTIONS:
    sys.exit(f"usage: python deploy/backend.py {{{'|'.join(SERVERS)}}} {{{'|'.join(ACTIONS)}}}")
host, repo = SERVERS[sys.argv[1]]
backend = sys.argv[2]

if backend == "down":
    sys.exit(subprocess.run(["ssh", host, f"cd ~/{repo}/backend && docker compose down"]).returncode)

script = f"""
set -eu
cd ~/{repo}
# The checkout has to be on main: a pull on another branch succeeds and quietly runs old code (it did, for a day).
branch=$(git rev-parse --abbrev-ref HEAD)
[ "$branch" = main ] || {{ echo "the server's checkout is on $branch, not main; fix it there: git checkout main" >&2; exit 1; }}
git pull --ff-only
echo "at $(git describe --always --dirty) on main"
cd backend
sed -i 's/^AGENT_BACKEND=.*/AGENT_BACKEND={backend}/' .env
grep -q '^AGENT_BACKEND={backend}$' .env || {{ echo "AGENT_BACKEND is not in .env" >&2; exit 1; }}
export GIT_COMMIT=$(git describe --always --dirty)
docker compose build -q
docker compose up -d livekit api
since=$(date -u +%Y-%m-%dT%H:%M:%S)
docker compose up -d --force-recreate agent
for i in $(seq 30); do
    docker compose logs --no-log-prefix --since "$since" agent | grep -q '"registered worker"' && {{ echo "agent registered, backend {backend}"; exit 0; }}
    docker compose ps --status running --format '{{{{.Service}}}}' | grep -qx agent || break
    sleep 1
done
echo "the agent did not register; its log:" >&2
docker compose logs --no-log-prefix --since "$since" agent >&2
exit 1
"""
sys.exit(subprocess.run(["ssh", host, script]).returncode)
