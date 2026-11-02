"""The lab console's service-backend role: the call's record delivered to QoE Lab when the call ends.

QoE Lab is the lab's console: it shapes the network, tells the glasses which task to start and when to stop, and
takes a report from every party that has one (its contract: qoe-lab/docs/developer-guide.md, Participant Contract).
In a lab run the glasses pass the console's address and the run's identity, `sid` and `run_id`, through the api into
the agent's dispatch metadata as `{"qoe": {"sid", "run_id", "console"}}`; a call started from the glasses' own list
carries no such key, and nothing here runs.

When the call ends, the record (runlog.py) goes to `POST <console>/task-ended` as the contract says for the role
`service-backend`: the run's identity, the start and the end as wall clock ms, and the record as `log`, which the
console stores verbatim: every event of events.jsonl, the texts beside it (the prompts and the tools as sent), and
where the build stood; the photos stay in the record's directory on this machine. The report is written to
`qoe-pending.json` in the record's directory before the first attempt, so that it survives this process, and deleted
on a 2xx. A 4xx says the report itself is wrong, which no retry mends: the file is renamed `qoe-rejected.json` and kept.
Anything else is retried: for a short while in the call's shutdown callback, then by the agent process, which looks
for pending files under RUN_DIR every minute for as long as it runs (`deliver_pending`).
"""

from __future__ import annotations

import glob
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger("rayneo-agent.qoe")

PENDING = "qoe-pending.json"
REJECTED = "qoe-rejected.json"


@dataclass(frozen=True)
class LabRun:
    """Which run of the console's session this call is, and where the console is."""

    sid: str
    run_id: int
    console: str  # http://<host>:8080, the console's device server

    @staticmethod
    def from_metadata(metadata: str) -> LabRun | None:
        """The run named in the agent's dispatch metadata; None for a call the glasses started by themselves."""
        qoe = json.loads(metadata or "{}").get("qoe")
        if qoe is None:
            return None
        try:
            return LabRun(sid=str(qoe["sid"]), run_id=int(qoe["run_id"]), console=str(qoe["console"]).rstrip("/"))
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"the dispatch metadata's qoe entry is incomplete: {qoe!r}") from e


def write_report(run: LabRun, record_dir: str, started_ms: int, ended_ms: int, build: dict | None) -> str:
    """Compose the report from the record's directory and write it there as PENDING; returns the file's path."""
    events = []
    with open(os.path.join(record_dir, "events.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                events.append(json.loads(line))
    texts = {}
    for name in sorted(os.listdir(record_dir)):
        if name.endswith((".txt", ".json")) and name not in (PENDING, REJECTED):
            with open(os.path.join(record_dir, name), encoding="utf-8") as f:
                texts[name] = f.read()
    report = {
        "console": run.console,
        "body": {
            "sid": run.sid,
            "run_id": run.run_id,
            "role": "service-backend",
            "started_at": started_ms,
            "ended_at": ended_ms,
            "log": {"record": os.path.basename(record_dir), "build": build, "events": events, "texts": texts},
        },
    }
    path = os.path.join(record_dir, PENDING)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False)
    logger.info("qoe: report for sid=%s run_id=%s written, %d events", run.sid, run.run_id, len(events))
    return path


def deliver(path: str, give_up_after_s: float) -> bool:
    """Post the pending report at `path` until the console takes it or `give_up_after_s` have passed.

    Returns whether it is settled: delivered (file deleted) or rejected (file renamed). Each attempt carries
    its own `sent_at`, as the contract asks."""
    deadline = time.monotonic() + give_up_after_s
    wait = 1.0
    while True:
        with open(path, encoding="utf-8") as f:
            report = json.load(f)
        body = dict(report["body"], sent_at=round(time.time() * 1000))
        url = report["console"] + "/task-ended"
        request = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                         headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                answer = response.read().decode("utf-8", "replace")
            logger.info("qoe: %s took the report for sid=%s run_id=%s: %s", url, body["sid"], body["run_id"], answer.strip())
            os.remove(path)
            return True
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:
                logger.error("qoe: %s rejected the report for sid=%s run_id=%s with %d %s; kept as %s", url, body["sid"],
                             body["run_id"], e.code, e.read().decode("utf-8", "replace").strip(), REJECTED)
                os.replace(path, os.path.join(os.path.dirname(path), REJECTED))
                return True
            problem = f"{e.code} {e.reason}"
        except (urllib.error.URLError, OSError) as e:
            problem = str(e)
        if time.monotonic() + wait > deadline:
            logger.warning("qoe: %s did not take the report for sid=%s run_id=%s (%s); it stays in %s", url, body["sid"],
                           body["run_id"], problem, path)
            return False
        logger.info("qoe: %s did not take the report (%s); again in %.0f s", url, problem, wait)
        time.sleep(wait)
        wait = min(wait * 2, 30)


def deliver_pending(root: str | None) -> None:
    """Deliver every report left under `root` (RUN_DIR), now and every minute after, in a thread of its own."""
    if not root:
        return

    def loop() -> None:
        while True:
            for path in sorted(glob.glob(os.path.join(root, "*", PENDING))):
                deliver(path, give_up_after_s=20)
            time.sleep(60)

    threading.Thread(target=loop, name="qoe-pending", daemon=True).start()

