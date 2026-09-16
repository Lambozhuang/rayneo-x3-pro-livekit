#!/usr/bin/env python3
"""The conversation, live, out of the agent's JSON log.

    cd backend && docker compose logs -f --no-log-prefix agent | python3 ../deploy/watch.py

One line per event, coloured: the wearer in green, the agent in white, the
build's progress in yellow, timings in cyan, anything WARNING or worse in red.
Everything else (SDK chatter, usage totals) is dropped; `-v` keeps it dim.
Only stdlib, so it runs on the lab PC as is.
"""

import json
import sys

GREEN, WHITE, YELLOW, CYAN, RED, DIM, RESET = (
    "\033[32m", "\033[1;37m", "\033[33m", "\033[36m", "\033[1;31m", "\033[2m", "\033[0m",
)

KEEP = (
    ("user:", GREEN, "you  "),
    ("assistant:", WHITE, "agent"),
    ("latency:", CYAN, "wait "),
    ("model:", CYAN, "model"),
    ("look:", YELLOW, "look "),
    ("camera:", YELLOW, "call "),
    ("step ", YELLOW, "build"),
    ("build", YELLOW, "build"),
    ("end_call", YELLOW, "build"),
    ("session for", YELLOW, "call "),
    ("session model:", YELLOW, "call "),
)


def render(line: str, verbose: bool) -> str | None:
    try:
        rec = json.loads(line)
    except ValueError:
        return f"{DIM}{line}{RESET}" if verbose else None
    msg = str(rec.get("message", ""))
    when = str(rec.get("timestamp", ""))[11:19]
    level = rec.get("level", "INFO")
    if level not in ("INFO", "DEBUG"):
        return f"{when} {RED}{level[:5]:<5} {msg}{RESET}"
    for prefix, colour, tag in KEEP:
        if msg.startswith(prefix):
            body = msg[len(prefix):].strip() if prefix.endswith(":") else msg
            return f"{when} {colour}{tag} {body}{RESET}"
    return f"{when} {DIM}      {msg[:160]}{RESET}" if verbose else None


def main() -> None:
    verbose = "-v" in sys.argv[1:]
    for raw in sys.stdin:
        out = render(raw.rstrip("\n"), verbose)
        if out is not None:
            print(out, flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
