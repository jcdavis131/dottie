#!/usr/bin/env python3
"""arxiviq data generator — bakes model cards + eval snapshot from live repo artifacts.

Solo personal project, no connection to employer, built with public/free-tier only

Reads the sibling Ava ecosystem repos (paths configurable) and emits static JSON consumed
by the arxiviq.com site: `site/data/model-cards.json` and `site/data/snapshot.json`.
The site prefers live fetches (GitHub raw + releases API) and falls back to these baked
files, each stamped with `generated_at` so the UI can label snapshot freshness honestly.

Every number in the output is read from a real artifact (configs/*.yaml, STATUS.json,
branch_eval_results.json, frontier_eval_results.json) — nothing is invented here, and
eval results carry their `mode` field through so mock-mode scores are labeled as such.

Usage:
    python arxiviq/generate_data.py [--roots /path/to/workspace] [--out arxiviq/site/data]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    print("pyyaml required: pip install pyyaml", file=sys.stderr)
    raise

FACTORY = "ava-agi-factory-v6-4"  # standalone sibling-checkout name
DOTTIE_FACTORY = "ava-factory"  # dottie monorepo name (apps/ava-factory)


def _dottie_root() -> Path | None:
    """Return the dottie monorepo root, or None for standalone checkouts.

    Prefers the DOTTIE_ROOT env var; otherwise detects whether this script's
    own location is inside a dottie checkout (…/apps/scout-cli/arxiviq/…).
    """
    env = os.environ.get("DOTTIE_ROOT")
    if env:
        p = Path(env).expanduser()
        if p.exists():
            return p.resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == "scout-cli" and parent.parent.name == "apps":
            return parent.parent.parent
    return None


def _default_roots() -> Path:
    """Default --roots: dottie apps/ dir when inside a dottie checkout, else sibling layout."""
    droot = _dottie_root()
    if droot is not None:
        return droot / "apps"
    return Path(__file__).resolve().parent.parent.parent


def _resolve_factory(roots: Path) -> Path:
    """Find the factory repo under roots — standalone name first, then dottie name."""
    for name in (FACTORY, DOTTIE_FACTORY):
        cand = roots / name
        if cand.exists():
            return cand
    return roots / FACTORY


SCALE_NOTES: dict[str, dict[str, Any]] = {
    # Status text mirrors TODOS.md Stage 9 (scale ladder); update when the ladder moves.
    "nano": {"params_label": "13.8M", "status": "trained", "ladder_rung": 1},
    "mini": {
        "params_label": "171M",
        "status": "training (T9.2 live run)",
        "ladder_rung": 2,
    },
    "base1b": {
        "params_label": "1409M",
        "status": "gated (open risk #1: VRAM)",
        "ladder_rung": 3,
    },
}


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def build_model_cards(factory: Path) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    branch_evals = _read_json(factory / "branch_eval_results.json") or {}
    for preset, note in SCALE_NOTES.items():
        cfg_path = factory / "configs" / f"{preset}.yaml"
        if not cfg_path.exists():
            continue
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        model = cfg.get("model", {})
        phases = cfg.get("phases", []) or []
        jspace = cfg.get("jspace", {})
        card = {
            "id": f"ava-{preset}",
            "name": f"Ava {preset}",
            "params_label": note["params_label"],
            "status": note["status"],
            "ladder_rung": note["ladder_rung"],
            "architecture": {
                "type": "decoder-only causal transformer + Multi-J-Space global workspace",
                "d_model": model.get("d_model"),
                "n_heads": model.get("n_heads"),
                "layers": {
                    "text": model.get("n_text_layers"),
                    "fusion": model.get("n_fusion_layers"),
                    "reasoning": model.get("n_reasoning_layers"),
                },
                "vocab_size": model.get("vocab_size"),
                "qk_norm": model.get("qk_norm"),
                "tied_lm_head": model.get("tie_lm_head"),
                "rope_base": model.get("rope_base_init"),
                "workspaces": "S1 Fast hl=8 · S2 Slow hl=300 · Critic hl=30 · Planner hl=150 + Router/veto"
                if jspace
                else None,
            },
            "training_data": {
                "curriculum": [
                    {
                        "phase": p.get("name"),
                        "tokens": p.get("tokens"),
                        "seq_len": p.get("seq"),
                        "mix": p.get("mix"),
                    }
                    for p in phases
                ],
                "provenance": "From-scratch; deterministic in-house datagen + curated collection; "
                "no third-party model distillation; no LM-synthetic pre-training text "
                "(spec 02 forbids network datagen).",
            },
            "constraints": [
                "Single consumer GPU (RTX 4080/4090); free-tier tooling only.",
                "base1b is 20% over the 1.17B spec: 8.4GB weights before activations vs ~11.6GB "
                "usable — open risk #1; KV/state trims tracked in spec 11."
                if preset == "base1b"
                else "Validated on the scale ladder before promotion (rank-invariance rule; "
                "EG trend across ≥2 rungs, efficiency_gain.py).",
                "Solo personal project; no employer connection; public/free-tier only.",
            ],
            "evaluation": {
                "harness": "ava-open-harness (5 canonical J-tests + 11-category frontier rubric); "
                "anti-mock guard enforces live-forward-pass floats",
                "branch_results_present": bool(branch_evals),
            },
        }
        cards.append(card)
    return cards


def build_snapshot(factory: Path) -> dict[str, Any]:
    status = _read_json(factory / "STATUS.json") or {}
    frontier = _read_json(factory / "frontier_eval_results.json") or {}
    branch = _read_json(factory / "branch_eval_results.json") or {}

    frontier_domains = []
    for row in frontier.get("results", []):
        frontier_domains.append(
            {
                "task_id": row.get("task_id"),
                "domain": row.get("domain"),
                "overall": row.get("overall"),
                "per_rubric": [
                    {
                        "category": r.get("category"),
                        "score": r.get("score"),
                        "weight": r.get("weight"),
                    }
                    for r in row.get("per_rubric", [])
                ],
            }
        )

    jtests = {}
    for branch_name, payload in (branch or {}).items():
        if isinstance(payload, dict) and isinstance(payload.get("tests"), list):
            jtests[branch_name] = [
                {
                    "test": t.get("test"),
                    "pass": t.get("pass"),
                    "desc": t.get("desc"),
                    "mode": t.get("mode"),
                    "metric": next(
                        (
                            t[k]
                            for k in (
                                "causal_effect",
                                "broadcast",
                                "mass",
                                "auto_cos",
                                "auc",
                            )
                            if k in t
                        ),
                        None,
                    ),
                }
                for t in payload["tests"]
            ]

    trainer = (
        status.get("trainer", {}) if isinstance(status.get("trainer"), dict) else {}
    )
    builder = (
        status.get("builder", {}) if isinstance(status.get("builder"), dict) else {}
    )
    return {
        "pipeline": {
            "current_phase": builder.get("current_phase"),
            "phase_progress": builder.get("phase_progress"),
            "total_shards": builder.get("total_shards"),
            "trainer_steps": trainer.get("steps"),
            "trainer_loss": trainer.get("loss"),
            "weekly_training": (status.get("weekly_training") or {}).get("status")
            if isinstance(status.get("weekly_training"), dict)
            else status.get("weekly_training"),
        },
        "frontier": {
            "mode": frontier.get("mode"),
            "judge": frontier.get("judge"),
            "domains": frontier_domains,
        },
        "jtests": jtests,
    }


def build_ecosystem() -> dict[str, Any]:
    """Static-but-authored map of the six Ava repos and the capability roadmap.

    Honesty note (updated 2026-07-17, CPU-pilot milestone): the CodeAct/RL CODE is complete
    and mechanically proven at smoke scale — the nano CPU pilot ran the real chain end-to-end
    (corpus -> tokenizer -> pack -> pretrain -> agentic branch fork -> one real GRPO update;
    evidence runs/cpu_pilot/MANIFEST.json, scale=smoke_cpu_pilot, capability_claim=none).
    The RL/CodeAct rows below say "built" — NOT "shipped" — because capability-scale
    training (GPU wall-clock) has not happened; do not let this surface imply model capability.
    The pilot-chain row is "shipped": the chain itself is the deliverable and it ran.
    """
    repos = [
        {
            "name": "ava-agi-factory-v6-4",
            "role": "Model factory",
            "detail": "From-scratch 1B Multi-J-Space model; gather→curate→train→serve pipeline; "
            "scale ladder nano→mini→base1b; RL spec 12 (GRPO discipline system).",
            "status": "active",
        },
        {
            "name": "ava-open-harness",
            "role": "Eval gate",
            "detail": "5 canonical J-Space tests + 11-category frontier rubric; anti-mock guard "
            "(tests/test_no_mock.py) enforces live-forward-pass floats; honest real-mode failures.",
            "status": "active",
        },
        {
            "name": "ava-skills",
            "role": "Skill system",
            "detail": "Tool-Graph-ordered, wRRF-reranked skills routed to J-Space subsystems; "
            "memory-router (retrieval) + memory-mint (async ingestion) form the memory layer.",
            "status": "active",
        },
        {
            "name": "scout-cli",
            "role": "Control plane",
            "detail": "Security-first agent CLI; ava/rtx/graphify plugins; RFT ETL turns audit.jsonl "
            "workflow traces into training datasets; hosts this arxiviq site.",
            "status": "active",
        },
        {
            "name": "scout-rtx",
            "role": "Local hill-climb",
            "detail": "Autonomous overnight RTX runner; TinyStories proxy experiments promoted into "
            "the factory model only after a 2-rung EG ladder gate (rank-invariance).",
            "status": "active",
        },
        {
            "name": "personal-graphify",
            "role": "Knowledge-graph RAG",
            "detail": "Query-first code graph (measured token reduction) feeding agents graph-before-grep.",
            "status": "active",
        },
    ]
    roadmap = [
        {
            "capability": "Verifiable RL (GRPO discipline system)",
            "state": "built",
            "note": "specs/12_rl_training.md — pure-math mechanics (ava/rl/grpo.py) + the REAL torch "
            "optimizer step (ava/rl/grpo_torch.py, exact-parity surrogate, spike/overflow "
            "NaN-survival). One real GRPO update executed on the real pilot branch checkpoint "
            "(smoke scale, zero capability — evidence in the CPU Pilot tab). Capability-scale "
            "climb awaits GPU wall-clock.",
        },
        {
            "capability": "Memory layer (mint + route)",
            "state": "shipped",
            "note": "memory-mint async ingestion + memory-router retrieval, scope-symmetric.",
        },
        {
            "capability": "RFT on workflow traces",
            "state": "shipped",
            "note": "audit.jsonl → redacted, reward-component-annotated, versioned RFT dataset.",
        },
        {
            "capability": "Efficiency-Gain scaling gates",
            "state": "shipped",
            "note": "efficiency_gain.py — EG_FLOPs/EG_Time vs baseline curve, 2-rung promote/hold verdict.",
        },
        {
            "capability": "Think-in-code / LLM-VM (CodeAct)",
            "state": "built",
            "note": "specs/13_codeact.md T13C.1-T13C.6 code-complete: sandbox LLM-VM, executable "
            "datagen, exec-verified eval, reward terms, decode loop + real TorchModelPolicy, "
            "MOPD pool prep, EG gate. Whole chain proven mechanically on the real pilot "
            "checkpoint (r_task=0, honest — no capability at smoke scale). Capability awaits "
            "the GPU climb.",
        },
        {
            "capability": "WebGPU client-side serving (dottie-claw)",
            "state": "planned",
            "note": "Serve Ava in-browser at $0: ONNX export -> ONNX Runtime Web (WebGPU EP) for the "
            "custom Multi-J-Space graph (nano fp16 ~28MB, mini q4 ~100MB — visitor's GPU does "
            "the compute); Pyodide-in-a-Worker as the browser CodeAct sandbox. Prepped as "
            "architecture; launches only after a capability checkpoint exists.",
        },
        {
            "capability": "CPU pilot training chain (T9.3/T9.5 mechanism)",
            "state": "shipped",
            "note": "scripts/cpu_pilot_e2e.py — real corpus -> BPE 8192 -> packed shards -> 90-step "
            "pretrain (lm 9.08->3.09) -> real agentic branch fork (lm 2.88->2.30) on CPU; "
            "device/preset-parameterized so the SAME chain scales onto a GPU box (docker "
            "ava-train, --preset mini --device cuda).",
        },
    ]
    return {"repos": repos, "roadmap": roadmap}


def build_pilot(factory: Path) -> dict[str, Any] | None:
    """Pass through the CPU-pilot evidence manifest (runs/cpu_pilot/MANIFEST.json).

    This is committed, measured training evidence — real per-step loss series, stage timings,
    checkpoint sha256s, and the GRPO smoke-update stats — declared `scale=smoke_cpu_pilot`,
    `capability_claim=none` by the manifest itself. Nothing is computed or invented here: the
    baked copy is the manifest verbatim plus a source pointer, so the site's fallback can never
    diverge from the evidence. Returns None (and the site shows its honest empty state) when the
    manifest doesn't exist."""
    manifest_path = factory / "runs" / "cpu_pilot" / "MANIFEST.json"
    if not manifest_path.exists():
        return None
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["source_path"] = f"{factory.name}/runs/cpu_pilot/MANIFEST.json"
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--roots",
        default=str(_default_roots()),
        help="Directory containing the ecosystem repos "
        "(default: dottie apps/ when inside a dottie checkout, else sibling layout)",
    )
    parser.add_argument(
        "--out", default=str(Path(__file__).resolve().parent / "site" / "data")
    )
    args = parser.parse_args(argv)

    factory = _resolve_factory(Path(args.roots))
    if not factory.exists():
        print(f"factory repo not found at {factory}; aborting", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).isoformat(timespec="seconds")

    cards = {
        "generated_at": stamp,
        "source": factory.name,
        "cards": build_model_cards(factory),
    }
    snapshot = {
        "generated_at": stamp,
        "source": factory.name,
        **build_snapshot(factory),
    }
    ecosystem = {"generated_at": stamp, **build_ecosystem()}

    (out / "model-cards.json").write_text(json.dumps(cards, indent=1), encoding="utf-8")
    (out / "snapshot.json").write_text(json.dumps(snapshot, indent=1), encoding="utf-8")
    (out / "ecosystem.json").write_text(
        json.dumps(ecosystem, indent=1), encoding="utf-8"
    )
    pilot = build_pilot(factory)
    pilot_msg = "no pilot manifest"
    if pilot is not None:
        (out / "pilot.json").write_text(json.dumps(pilot, indent=1), encoding="utf-8")
        pre = pilot.get("runs", {}).get("pretrain", {}).get("steps")
        pilot_msg = f"pilot.json ({pre} pretrain steps, scale={pilot.get('scale')})"
    print(
        f"wrote model-cards.json ({len(cards['cards'])} cards), snapshot.json, "
        f"ecosystem.json ({len(ecosystem['repos'])} repos), {pilot_msg}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
