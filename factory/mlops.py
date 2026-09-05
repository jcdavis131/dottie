"""MLOps line: the one training queue for the box (spec §3).

A job runs in its repo, logs to factory/runs/<job>/<stamp>.log, and is judged by a
gate read from the report file its own eval writes. Nothing here copies a
checkpoint into a site: `promote` prints the steps once, and only after a pass.
"""

from __future__ import annotations

import json
import time
from typing import Any

from factory.config import (
    Factory,
    FactoryError,
    git_head,
    load_json,
    now_stamp,
    run_cmd,
    save_json,
    table,
)

OUTCOMES = ("pass", "fail", "no_report", "no_metric", "skipped", "preflight_failed")


def cuda_status() -> str:
    try:
        import torch
    except Exception:
        return "unknown (torch not importable here)"
    try:
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception as e:
        return f"unknown ({type(e).__name__})"


def preflight(f: Factory, job: dict) -> list[str]:
    """Every missing prerequisite, named. Empty means the job can start."""
    problems: list[str] = []
    repo = f.repo_dir(job["repo"])
    if not repo.is_dir():
        return [f"repo {job['repo']} is not checked out at {repo}"]
    for rel in job.get("needs", []):
        if not (repo / rel).exists():
            problems.append(f"missing {job['repo']}/{rel}")
    if job.get("needs_cuda"):
        cuda = cuda_status()
        if cuda != "cuda":
            problems.append(f"needs CUDA; torch reports {cuda}")
    return problems


def _lookup(doc: Any, dotted: str) -> Any:
    cur = doc
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def _compare(value: float, op: str, threshold: float) -> bool:
    return {
        ">=": value >= threshold,
        "<=": value <= threshold,
        ">": value > threshold,
        "<": value < threshold,
    }[op]


def gate(f: Factory, job: dict) -> dict:
    g = job["gate"]
    report = f.repo_dir(job["repo"]) / g["report"]
    out = {
        "report": str(report),
        "metric": g["metric"],
        "op": g["op"],
        "threshold": g["threshold"],
        "baseline": g.get("baseline"),
        "value": None,
        "outcome": "no_report",
    }
    if not report.is_file():
        return out
    try:
        doc = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return out
    value = _lookup(doc, g["metric"])
    if not isinstance(value, int | float) or isinstance(value, bool):
        out["outcome"] = "no_metric"
        return out
    out["value"] = value
    out["outcome"] = "pass" if _compare(value, g["op"], g["threshold"]) else "fail"
    return out


def run(f: Factory, job: dict, *, smoke: bool = False) -> dict:
    stamp = now_stamp()
    run_dir = f.runs_dir / job["id"]
    run_dir.mkdir(parents=True, exist_ok=True)
    log = run_dir / f"{stamp}.log"
    repo = f.repo_dir(job["repo"])
    result: dict[str, Any] = {
        "job": job["id"],
        "dag_node": job.get("dag_node"),
        "repo": job["repo"],
        "smoke": smoke,
        "stamp": stamp,
        "head": None,
        "cmd": None,
        "rc": None,
        "seconds": None,
        "gate": "skipped",
        "gate_detail": None,
        "problems": [],
        "log": str(log),
    }
    problems = preflight(f, job)
    if problems:
        result.update(problems=problems, gate="preflight_failed")
        save_json(run_dir / f"{stamp}.json", result)
        return result
    result["head"] = git_head(repo)
    cmd = job["smoke"] if smoke else job["run"]
    result["cmd"] = cmd
    t0 = time.monotonic()
    env = {**f.env, **{k: str(v) for k, v in (job.get("env") or {}).items()}}
    rc = run_cmd(cmd, repo, log=log, env=env)
    if rc == 0 and not smoke and job.get("eval"):
        rc = run_cmd(job["eval"], repo, log=log, env=env)
    result["rc"] = rc
    result["seconds"] = round(time.monotonic() - t0, 1)
    if not smoke:
        detail = gate(f, job)
        result["gate"] = detail["outcome"] if rc == 0 else "fail"
        result["gate_detail"] = detail
    save_json(run_dir / f"{stamp}.json", result)
    return result


def last_result(f: Factory, job: dict) -> dict | None:
    run_dir = f.runs_dir / job["id"]
    if not run_dir.is_dir():
        return None
    files = sorted(run_dir.glob("*.json"))
    return load_json(files[-1]) if files else None


def ordered(f: Factory) -> list[dict]:
    return sorted(f.jobs(), key=lambda j: (j.get("priority", 5), j["id"]))


def next_job(f: Factory) -> dict | None:
    for job in ordered(f):
        last = last_result(f, job)
        if last and not last.get("smoke") and last.get("gate") == "pass":
            continue  # already passed; promotion is the operator's step
        if not preflight(f, job):
            return job
    return None


def promote(f: Factory, job: dict) -> str:
    last = last_result(f, job)
    if last is None or last.get("smoke"):
        raise FactoryError(
            f"{job['id']}: no full run recorded; `factory train run {job['id']}` first"
        )
    if last.get("gate") != "pass":
        raise FactoryError(
            f"{job['id']}: last run ({last['stamp']}) gate={last.get('gate')}; only a pass can promote"
        )
    d = last.get("gate_detail") or {}
    lines = [
        f"{job['id']} passed its gate at {last['stamp']} (head {last.get('head')}): "
        f"{d.get('metric')}={d.get('value')} {d.get('op')} {d.get('threshold')} (baseline {d.get('baseline')})",
        "Promotion is manual by design (provenance-honest). Steps:",
    ]
    lines += [f"  {i}. {step}" for i, step in enumerate(job.get("promote", []), 1)]
    lines.append(
        f"Then: factory done {job.get('dag_node')} --evidence '{job['id']} {last['stamp']} {d.get('metric')}={d.get('value')}'"
    )
    return "\n".join(lines)


def list_jobs(f: Factory) -> str:
    rows = []
    for job in ordered(f):
        last = last_result(f, job)
        if last is None:
            recent = "never run"
        else:
            kind = "smoke" if last.get("smoke") else "run"
            val = (last.get("gate_detail") or {}).get("value")
            recent = (
                f"{last['stamp']} {kind} rc={last.get('rc')} gate={last.get('gate')}"
                + (f" value={val}" if val is not None else "")
            )
        rows.append(
            [
                f"P{job.get('priority', '?')}",
                job["id"],
                job["repo"],
                "gpu" if job.get("needs_cuda") else "cpu",
                f"{job.get('est_hours', '?')}h",
                recent,
            ]
        )
    return (
        table(rows, ["prio", "job", "repo", "device", "est", "last"])
        + f"\nbox: torch reports {cuda_status()}"
    )


def render_preflight(job_id: str, problems: list[str]) -> str:
    if not problems:
        return f"{job_id}: preflight ok"
    return f"{job_id}: preflight FAILED\n" + "\n".join(f"  - {p}" for p in problems)


def render_gate(d: dict) -> str:
    return (
        f"gate {d['outcome']}: {d['metric']}={d['value']} {d['op']} {d['threshold']} "
        f"(baseline {d['baseline']}) from {d['report']}"
    )


def render_result(r: dict) -> str:
    if r["gate"] == "preflight_failed":
        return render_preflight(r["job"], r["problems"])
    line = f"{r['job']} {'smoke' if r['smoke'] else 'run'} rc={r['rc']} in {r['seconds']}s (head {r['head']}); log {r['log']}"
    if r.get("gate_detail"):
        line += "\n" + render_gate(r["gate_detail"])
    return line


__all__ = [
    "OUTCOMES",
    "cuda_status",
    "gate",
    "last_result",
    "list_jobs",
    "next_job",
    "ordered",
    "preflight",
    "promote",
    "render_gate",
    "render_preflight",
    "render_result",
    "run",
]
