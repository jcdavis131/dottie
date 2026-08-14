#!/usr/bin/env python3
"""Recompute a per-agent scoreboard from committed timeline event logs.

WHY: bundles/ultra/runs/*/timeline.jsonl records one JSON event per line for
every harness run, but nothing aggregates those events into a reviewable
per-agent view. This generator recomputes runs, event counts, ok-rate, and
median latency per agentId strictly from the lines on disk. A line that fails
to parse or lacks the agentId/status keys is counted in a per-file
skipped-lines tally and excluded — skipped, never guessed (the exporters-skip,
never-invent precedent from build_runs_readout.mjs). The markdown face states
explicitly that this is history recomputed from committed logs, not live
telemetry.

Called by the playbook engine (scripts/business/playbook.py), which resolves
inputs and injects the timestamp:

    uv run python scripts/business/playbook.py run monitor \\
        --artifact run-scoreboard

Contract: generate(inputs, params, generated_at) ->
{"scoreboard.json": text, "scoreboard.md": text}. Raises FileNotFoundError
when no timeline files resolve; the engine maps that to status
"skipped-missing-input". Pure over the given paths: read-only, deterministic,
no network. Loaded standalone by file path — stdlib only, no package imports.
"""

from __future__ import annotations

import hashlib
import json
import os
import statistics
from pathlib import Path

_METHOD = (
    "recomputed from committed timeline.jsonl event logs; malformed lines skipped"
)
_FRAMING = (
    "This scoreboard is history recomputed from committed event logs, "
    "not live telemetry."
)
_NOT_RECORDED = "(not recorded)"


def _sha256(path: Path) -> str:
    """Hex sha256 of a file's bytes (small local helper; modules stay standalone)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_root() -> Path:
    """Repo root: DOTTIE_ROOT override, else three levels above this module."""
    override = os.environ.get("DOTTIE_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[3]


def _rel(path: Path) -> str:
    """Repo-relative posix path when possible; absolute posix otherwise."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(_repo_root()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _aggregate(
    paths: list[Path],
) -> tuple[dict[str, dict], list[tuple[Path, int]], int, int]:
    """Walk every timeline file; return per-agent stats and per-file skip tallies.

    Returns (per_agent, files, total_events, total_skipped) where per_agent maps
    agentId -> {run_ids, events, ok, latencies} and files is [(path, skipped)].
    """
    per_agent: dict[str, dict] = {}
    files: list[tuple[Path, int]] = []
    total_events = 0
    total_skipped = 0
    for path in sorted(paths):
        skipped = 0
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise FileNotFoundError(f"timeline unreadable: {path}") from exc
        for line in text.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if (
                not isinstance(event, dict)
                or "agentId" not in event
                or "status" not in event
            ):
                skipped += 1
                continue
            agent = per_agent.setdefault(
                str(event["agentId"]),
                {"run_ids": set(), "events": 0, "ok": 0, "latencies": []},
            )
            agent["events"] += 1
            if event["status"] == "ok":
                agent["ok"] += 1
            run_id = event.get("runId")
            if isinstance(run_id, str):
                agent["run_ids"].add(run_id)
            latency = event.get("latency_ms")
            if isinstance(latency, (int, float)) and not isinstance(latency, bool):
                agent["latencies"].append(latency)
            total_events += 1
        files.append((path, skipped))
        total_skipped += skipped
    return per_agent, files, total_events, total_skipped


def _agent_rows(per_agent: dict[str, dict]) -> dict[str, dict]:
    """Reduce raw tallies to the published per-agent numbers."""
    rows: dict[str, dict] = {}
    for agent_id in sorted(per_agent):
        stats = per_agent[agent_id]
        latencies = stats["latencies"]
        rows[agent_id] = {
            "runs": len(stats["run_ids"]),
            "events": stats["events"],
            "ok_rate": round(stats["ok"] / stats["events"], 4),
            "p50_latency_ms": statistics.median(latencies) if latencies else None,
        }
    return rows


def _render_json(
    agents: dict[str, dict],
    files: list[tuple[Path, int]],
    total_events: int,
    total_skipped: int,
    generated_at: str,
) -> str:
    payload = {
        "generated_by": "scripts/business/generators/run_scoreboard.py",
        "generated_at": generated_at,
        "provenance": {
            "classification": "REAL",
            "method": _METHOD,
            "sources": [
                {"path": _rel(path), "sha256": _sha256(path), "skipped_lines": skipped}
                for path, skipped in files
            ],
        },
        "agents": agents,
        "totals": {
            "files": len(files),
            "events": total_events,
            "skipped_lines": total_skipped,
        },
    }
    return json.dumps(payload, sort_keys=True, indent=2) + "\n"


def _render_md(
    agents: dict[str, dict],
    files: list[tuple[Path, int]],
    total_events: int,
    total_skipped: int,
    generated_at: str,
) -> str:
    out = [
        "---",
        "generated_by: scripts/business/generators/run_scoreboard.py",
        f"generated_at: {json.dumps(generated_at)}",
        "classification: REAL",
        f"method: {json.dumps(_METHOD)}",
        "measured: true",
        "sources:",
    ]
    for path, _skipped in files:
        out.append(f"  - path: {json.dumps(_rel(path))}")
        out.append(f"    sha256: {json.dumps(_sha256(path))}")
    out += ["---", "", "# Run scoreboard", "", _FRAMING, ""]
    out.append("| Agent | Runs | Events | OK rate | p50 latency ms |")
    out.append("|---|---|---|---|---|")
    for agent_id, row in agents.items():
        p50 = row["p50_latency_ms"]
        p50_cell = _NOT_RECORDED if p50 is None else str(p50)
        out.append(
            f"| {agent_id} | {row['runs']} | {row['events']} "
            f"| {row['ok_rate']} | {p50_cell} |"
        )
    out += [
        "",
        f"Totals: {len(files)} file(s), {total_events} event(s), "
        f"{total_skipped} skipped line(s).",
        "",
    ]
    return "\n".join(out)


def generate(
    inputs: dict[str, list[Path]],
    params: dict[str, object],
    generated_at: str,
) -> dict[str, str]:
    """Build scoreboard.json and scoreboard.md from timeline event logs."""
    timeline_paths = inputs.get("timelines") or []
    if not timeline_paths:
        raise FileNotFoundError("no timeline files present")
    per_agent, files, total_events, total_skipped = _aggregate(timeline_paths)
    agents = _agent_rows(per_agent)
    return {
        "scoreboard.json": _render_json(
            agents, files, total_events, total_skipped, generated_at
        ),
        "scoreboard.md": _render_md(
            agents, files, total_events, total_skipped, generated_at
        ),
    }
