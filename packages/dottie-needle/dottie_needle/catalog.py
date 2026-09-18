"""Dottie's real tool catalog as grammar ToolSpecs.

Every entry is grounded in a real surface: the scout-cli / dottie_loop CLI
(commands enumerated from ``dottie_loop/cli.py``), the leaks scanner, and the
handoff freshness script. This catalog feeds both the Tier 1 bench and the
Tier 2 training-data pipeline, so train-time and eval-time schemas agree.
"""

from __future__ import annotations

from dottie_needle.grammar import ToolSpec


def build_catalog() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="leaks_scan",
            description="Scan the repo for leaked secrets",
            parameters={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "config": {"type": "string", "default": "leaks.json"},
                    "fail_on": {"type": "string", "enum": ["error", "warning"], "default": "error"},
                },
            },
            triggers=("leak", "secret"),
        ),
        ToolSpec(
            name="handoff_check",
            description="Verify HANDOFF.md freshness against git HEAD",
            parameters={"type": "object", "properties": {}},
            triggers=("handoff",),
        ),
        ToolSpec(
            name="lint",
            description="Run ruff lint over a path",
            parameters={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "fix": {"type": "boolean", "default": False},
                },
            },
            triggers=("lint", "ruff"),
        ),
        ToolSpec(
            name="goal_submit",
            description="Submit a goal to the Dottie job queue",
            parameters={
                "type": "object",
                "required": ["title"],
                "properties": {
                    "title": {"type": "string", "minLength": 1, "maxLength": 200},
                    "kind": {"type": "string", "enum": ["board", "verify", "build"], "default": "build"},
                },
            },
            triggers=("submit",),
        ),
        ToolSpec(
            name="goal_status",
            description="Show the status of a queued goal",
            parameters={
                "type": "object",
                "required": ["goal_id"],
                "properties": {"goal_id": {"type": "string", "pattern": r"^g[0-9]+$"}},
            },
            triggers=("status",),
        ),
        ToolSpec(
            name="plan_validate",
            description="Validate the plan graph: acyclic, all dependencies resolve",
            parameters={
                "type": "object",
                "properties": {"graph": {"type": "string", "default": "plan.json"}},
            },
            triggers=("plan",),
        ),
        ToolSpec(
            name="loop_run",
            description="Run one goal end to end: intake -> plan -> execute -> verify -> checkpoint",
            parameters={
                "type": "object",
                "required": ["goal_id"],
                "properties": {
                    "goal_id": {"type": "string", "pattern": r"^g[0-9]+$"},
                    "dry_run": {"type": "boolean", "default": False},
                },
            },
            triggers=("loop",),
        ),
        ToolSpec(
            name="loop_evaluate",
            description="Score a finished loop run against its acceptance checks",
            parameters={
                "type": "object",
                "required": ["run_id"],
                "properties": {"run_id": {"type": "string", "minLength": 1}},
            },
            triggers=("evaluate", "score"),
        ),
        ToolSpec(
            name="reward_compute",
            description="Recompute the reward for a captured run from its feedback",
            parameters={
                "type": "object",
                "required": ["run_id"],
                "properties": {"run_id": {"type": "string", "minLength": 1}},
            },
            triggers=("reward",),
        ),
        ToolSpec(
            name="forge_submit",
            description="Submit a job to the Forge queue for the Alienware runner",
            parameters={
                "type": "object",
                "required": ["spec_path"],
                "properties": {
                    "spec_path": {"type": "string", "minLength": 1},
                    "priority": {"type": "integer", "minimum": 0, "maximum": 10, "default": 5},
                },
            },
            triggers=("forge",),
        ),
        ToolSpec(
            name="forge_runners",
            description="List registered Forge runners and their last heartbeat",
            parameters={"type": "object", "properties": {}},
            triggers=("runner",),
        ),
        ToolSpec(
            name="bench_smoke",
            description="Run the smoke benchmark suite and report pass/fail",
            parameters={
                "type": "object",
                "properties": {
                    "suite": {"type": "string", "enum": ["smoke", "full"], "default": "smoke"},
                },
            },
            triggers=("bench", "smoke", "benchmark"),
        ),
        ToolSpec(
            name="approval_issue",
            description="Issue a one-time approval token for a gated action",
            parameters={
                "type": "object",
                "required": ["action", "scope"],
                "properties": {
                    "action": {"type": "string", "minLength": 1},
                    "scope": {"type": "string", "minLength": 1},
                    "ttl_seconds": {"type": "integer", "minimum": 60, "maximum": 86400, "default": 3600},
                },
            },
            triggers=("approval", "approve"),
        ),
        ToolSpec(
            name="approval_consume",
            description="Consume an approval token to authorize the gated action",
            parameters={
                "type": "object",
                "required": ["token"],
                "properties": {"token": {"type": "string", "pattern": r"^apv_[a-z0-9]{16}$"}},
            },
        ),
        ToolSpec(
            name="dataset_release",
            description="Run the hard-block QA chain over captured traces and write shards plus manifest",
            parameters={
                "type": "object",
                "required": ["source"],
                "properties": {
                    "source": {"type": "string", "minLength": 1},
                    "shard_size": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 1000},
                },
            },
            triggers=("dataset",),
        ),
        ToolSpec(
            name="train_preflight",
            description="Run the ten training preflight checks; exits non-zero naming every failure",
            parameters={"type": "object", "properties": {}},
            triggers=("preflight",),
        ),
        ToolSpec(
            name="eval_gates",
            description="Evaluate the seven promotion gates over an eval bundle",
            parameters={
                "type": "object",
                "required": ["bundle"],
                "properties": {"bundle": {"type": "string", "minLength": 1}},
            },
            triggers=("gates",),
        ),
        ToolSpec(
            name="incident_drill",
            description="Run the restore-drill checklist; fails unless every item is proven",
            parameters={
                "type": "object",
                "properties": {
                    "checklist": {"type": "string", "default": "restore"},
                },
            },
            triggers=("drill", "incident"),
        ),
    ]


def get(names: list[str]) -> list[ToolSpec]:
    by_name = {t.name: t for t in build_catalog()}
    return [by_name[n] for n in names]
