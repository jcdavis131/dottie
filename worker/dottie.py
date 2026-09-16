#!/usr/bin/env python3
"""
dottie.py — Dottie's job queue CLI (stdlib only, zero deps).

Dottie takes the jobs you point at. Drop a job spec in the queue;
the dottie-worker picks it up, does the work with real tools,
and records the result + a 7-field timeline entry.

Usage:
  python3 dottie.py submit --goal "..." [--context "..."] [--repo dottie] [--surface]
  python3 dottie.py list [--state pending|claimed|done|failed]
  python3 dottie.py show <job-id>
  python3 dottie.py status
  python3 dottie.py claim <job-id>          # atomic pending -> claimed
  python3 dottie.py done <job-id> --summary "..." [--artifact PATH ...]
  python3 dottie.py fail <job-id> --error "..."
  python3 dottie.py log --node-id X --agent-id Y --status ok|fail|no_change [--error-class Z]

Queue lives in <repo>/worker/jobs/{pending,claimed,done,failed}/.
Job JSONs are runtime state (gitignored); only .gitkeep files are committed.
Timeline entries go to ~/workspace/timeline/timeline.jsonl (pinned path).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import string
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKER_DIR = Path(__file__).resolve().parent
# Env overrides let a packaged single-file build (dottie.pyz) keep its queue
# and timeline next to the user instead of inside the zip. Defaults preserve
# the classic repo-local layout. When running from inside a zipapp the queue
# cannot live next to the code, so it defaults to ~/.dottie/jobs.
_DEFAULT_JOBS_DIR = WORKER_DIR / "jobs"
if ".pyz" in str(WORKER_DIR):
    _DEFAULT_JOBS_DIR = Path.home() / ".dottie" / "jobs"
JOBS_DIR = Path(os.environ.get("DOTTIE_JOBS_DIR", _DEFAULT_JOBS_DIR))
STATES = ("pending", "claimed", "done", "failed")
TIMELINE_PATH = Path(
    os.environ.get(
        "DOTTIE_TIMELINE",
        Path.home() / "workspace" / "timeline" / "timeline.jsonl",
    )
)


def _now_local_iso() -> str:
    # America/Chicago fixed offset note: CDT (-05:00) in Sep; keep wall-clock honest.
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _new_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    rand = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(4))
    return f"job-{stamp}-{rand}"


def _job_path(job_id: str, state: str) -> Path:
    # Reject path traversal: job ids are internal (job-YYYYMMDD-HHMMSS-xxxx),
    # but claim/show/done/fail take them from CLI args.
    if not job_id or "/" in job_id or "\\" in job_id or ".." in job_id:
        raise ValueError(f"invalid job id: {job_id!r}")
    return JOBS_DIR / state / f"{job_id}.json"


def _find(job_id: str) -> tuple[str, Path] | tuple[None, None]:
    for state in STATES:
        p = _job_path(job_id, state)
        if p.exists():
            return state, p
    return None, None


def _read(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _write(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, p)  # atomic


def cmd_submit(args: argparse.Namespace) -> int:
    job_id = _new_id()
    spec = {
        "id": job_id,
        "goal": args.goal,
        "context": args.context or "",
        "repo": args.repo or "",
        "created_by": args.by or "scout",
        "created_at": _now_local_iso(),
        "surface": bool(args.surface),
        "status": "pending",
    }
    _write(_job_path(job_id, "pending"), spec)
    print(job_id)
    return 0


def _iter_job_files(state: str):
    d = JOBS_DIR / state
    if not d.exists():
        return
    for p in sorted(d.glob("job-*.json")):
        if p.name.endswith(".result.json"):
            continue
        yield p


def cmd_list(args: argparse.Namespace) -> int:
    states = [args.state] if args.state else STATES
    rows = []
    for state in states:
        for p in _iter_job_files(state):
            try:
                spec = _read(p)
            except Exception:
                continue
            rows.append((state, spec.get("id", p.stem), spec.get("goal", "")[:80]))
    if not rows:
        print("(empty)")
        return 0
    for state, jid, goal in rows:
        print(f"{state:8} {jid}  {goal}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    state, p = _find(args.job_id)
    if p is None:
        print(f"not found: {args.job_id}", file=sys.stderr)
        return 1
    spec = _read(p)
    print(f"state: {state}")
    print(json.dumps(spec, indent=2, sort_keys=True))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    counts = {}
    for state in STATES:
        counts[state] = sum(1 for _ in _iter_job_files(state))
    print(json.dumps(counts, sort_keys=True))
    return 0


def cmd_claim(args: argparse.Namespace) -> int:
    src = _job_path(args.job_id, "pending")
    if not src.exists():
        print(f"not pending (or not found): {args.job_id}", file=sys.stderr)
        return 1
    dst = _job_path(args.job_id, "claimed")
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.rename(src, dst)  # atomic on same filesystem
    spec = _read(dst)
    spec["status"] = "claimed"
    spec["claimed_at"] = _now_local_iso()
    spec["claimed_by"] = args.by or "dottie-worker"
    _write(dst, spec)
    print(f"claimed {args.job_id}")
    return 0


def _finish(args: argparse.Namespace, ok: bool) -> int:
    state, p = _find(args.job_id)
    if state != "claimed":
        print(f"job is not claimed (state={state}): {args.job_id}", file=sys.stderr)
        return 1
    spec = _read(p)
    result = {
        "job_id": args.job_id,
        "goal": spec.get("goal", ""),
        "completed_at": _now_local_iso(),
        "completed_by": args.by or "dottie-worker",
        "outcome": "done" if ok else "failed",
        "summary": args.summary or args.error or "",
        "artifacts": list(args.artifact or []),
    }
    spec["status"] = "done" if ok else "failed"
    spec["result"] = result
    dest_state = "done" if ok else "failed"
    dst = _job_path(args.job_id, dest_state)
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.rename(p, dst)
    _write(dst, spec)
    # result sidecar for easy reading
    _write(dst.with_name(f"{args.job_id}.result.json"), result)
    print(f"{dest_state} {args.job_id}")
    return 0


def cmd_done(args: argparse.Namespace) -> int:
    return _finish(args, ok=True)


def cmd_fail(args: argparse.Namespace) -> int:
    return _finish(args, ok=False)


def cmd_log(args: argparse.Namespace) -> int:
    # 7-field timeline entry (nodeId/agentId/attempt/latency_ms/tokens_est/status/errorClass)
    entry = {
        "nodeId": args.node_id,
        "agentId": args.agent_id,
        "attempt": args.attempt,
        "latency_ms": args.latency_ms,
        "tokens_est": args.tokens_est,
        "status": args.status,
        "errorClass": args.error_class,
        "ts": _now_local_iso(),
    }
    TIMELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TIMELINE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    print("logged")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="dottie", description="Dottie's job queue")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("submit", help="submit a job to the queue")
    s.add_argument("--goal", required=True, help="what Dottie should do")
    s.add_argument("--context", default="", help="extra context, paths, constraints")
    s.add_argument("--repo", default="", help="repo/area the job touches")
    s.add_argument("--by", default="scout", help="who submitted")
    s.add_argument("--surface", action="store_true",
                   help="report the result back to main chat when done")
    s.set_defaults(fn=cmd_submit)

    s = sub.add_parser("list", help="list jobs")
    s.add_argument("--state", choices=STATES, default=None)
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("show", help="show a job and its result")
    s.add_argument("job_id")
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("status", help="queue counts as JSON")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("claim", help="atomically claim a pending job")
    s.add_argument("job_id")
    s.add_argument("--by", default="dottie-worker")
    s.set_defaults(fn=cmd_claim)

    s = sub.add_parser("done", help="mark a claimed job done with a summary")
    s.add_argument("job_id")
    s.add_argument("--summary", required=True)
    s.add_argument("--artifact", action="append", default=[])
    s.add_argument("--by", default="dottie-worker")
    s.set_defaults(fn=cmd_done)

    s = sub.add_parser("fail", help="mark a claimed job failed")
    s.add_argument("job_id")
    s.add_argument("--error", required=True)
    s.add_argument("--by", default="dottie-worker")
    s.set_defaults(fn=cmd_fail)

    s = sub.add_parser("log", help="append a 7-field timeline entry")
    s.add_argument("--node-id", required=True)
    s.add_argument("--agent-id", required=True)
    s.add_argument("--attempt", type=int, default=1)
    s.add_argument("--latency-ms", type=int, default=0)
    s.add_argument("--tokens-est", type=int, default=0)
    s.add_argument("--status", required=True, choices=("ok", "fail", "no_change", "completed"))
    s.add_argument("--error-class", default="none")
    s.set_defaults(fn=cmd_log)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
