"""Components and ownership (spec §04) and the honest current-state check (§34).

The §04 table is DATA: each component names its responsibility and the artifact
that is authoritative for it. :func:`inventory` looks for each artifact in a tree
and reports ``present`` / ``absent`` from the filesystem, never from the spec's
own status column — that column is what the check is FOR (four of its
``BRANCH`` rows were found to exist on no remote; finding F1 of the review).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dottie_loop.hashing import now_iso

#: (component, responsibility, authoritative artifact relative to the repo root, spec status 2026-09-10)
COMPONENTS: tuple[tuple[str, str, str, str], ...] = (
    ("dottie_application", "engine, RLM, sessions, goals, harness, flywheel endpoints", "apps/dottie", "IMPLEMENTED"),
    ("harness_router_api", "heuristic route, optional learned route, deterministic plan", "apps/dottie-harness-api", "IMPLEMENTED"),
    ("scout_cli", "single tool surface, plugins, policy, audit, agent commands", "apps/scout-cli", "IMPLEMENTED"),
    ("ava_factory", "tokenization, training, GRPO, reward, checkpoint production", "apps/ava-factory", "MECHANICS"),
    ("ava_open_harness", "J-Space, frontier, probes, retrieval, anti-mock evaluation", "packages/ava-open-harness", "IMPLEMENTED"),
    ("ava_skills", "versioned capability packages with manifests and tests", "packages/ava-skills", "IMPLEMENTED"),
    ("personal_graph", "entity and relationship representation", "packages/personal-graphify", "PRESENT"),
    ("slack_ingress", "goal capture, dedupe, thread correlation", "apps/scout-cli/bigbang/plugins/slack", "IMPLEMENTED"),
    ("pair_capture", "opt-in redacted JSONL session telemetry", "packages/dottie-loop/dottie_loop/capture.py", "BRANCH"),
    ("pair_reward", "task-first reward with anti-hacking rules", "packages/dottie-loop/dottie_loop/reward.py", "BRANCH"),
    ("benchmark_builder", "workflow inventory, runner, metrics, report", "packages/dottie-loop/dottie_loop/bench.py", "BRANCH"),
    ("loop_trigger", "freshness, regression, volume, canary, cooldown gates", "packages/dottie-loop/dottie_loop/closed_loop.py", "BRANCH"),
    ("forge", "git-transported remote GPU jobs and results", "scripts/forge_runner.py", "RUNNER ABSENT"),
    ("rubric_rewards", "AdvancedIF-style versioned rubrics, per-criterion audit, hard task gate", "packages/dottie-loop/dottie_loop/rubric.py", "IMPLEMENTED"),
    ("opt_lane", "correctness-gated speed reward with calibrated timing and sandbox provenance", "packages/dottie-loop/dottie_loop/opt_lane.py", "IMPLEMENTED"),
    ("experiment_aira", "AIRA2 splits, hidden consistent eval, resource jobs over LeaseFile", "packages/dottie-loop/dottie_loop/experiment.py", "IMPLEMENTED"),
)


def inventory(root: Path) -> dict[str, Any]:
    """What is actually in the tree, component by component."""
    root = Path(root)
    rows = []
    for name, responsibility, artifact, spec_status in COMPONENTS:
        p = root / artifact
        rows.append({"component": name, "responsibility": responsibility, "artifact": artifact, "present": p.exists(), "kind": "dir" if p.is_dir() else "file" if p.is_file() else None, "spec_status_2026_09_10": spec_status})
    absent = [r["component"] for r in rows if not r["present"]]
    return {"root": str(root), "components": rows, "present": len(rows) - len(absent), "absent": absent, "at": now_iso()}
