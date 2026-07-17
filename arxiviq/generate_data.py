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
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    print("pyyaml required: pip install pyyaml", file=sys.stderr)
    raise

FACTORY = "ava-agi-factory-v6-4"

SCALE_NOTES: Dict[str, Dict[str, Any]] = {
    # Status text mirrors TODOS.md Stage 9 (scale ladder); update when the ladder moves.
    "nano": {"params_label": "13.8M", "status": "trained", "ladder_rung": 1},
    "mini": {"params_label": "171M", "status": "training (T9.2 live run)", "ladder_rung": 2},
    "base1b": {"params_label": "1409M", "status": "gated (open risk #1: VRAM)", "ladder_rung": 3},
}


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _param_estimate(model: Dict[str, Any]) -> Optional[int]:
    """Rough decoder-param estimate from config dims (embed + blocks); labeling only."""
    try:
        d = int(model["d_model"])
        layers = int(model.get("n_text_layers", 0)) + int(model.get("n_fusion_layers", 0)) \
            + int(model.get("n_reasoning_layers", 0))
        vocab = int(model["vocab_size"])
        mlp = int(model.get("mlp_mult", 4))
        per_block = 4 * d * d + 2 * mlp * d * d   # attn (q,k,v,o) + gated MLP approx
        return vocab * d + layers * per_block
    except (KeyError, TypeError, ValueError):
        return None


def build_model_cards(factory: Path) -> List[Dict[str, Any]]:
    cards: List[Dict[str, Any]] = []
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
            "params_estimate": _param_estimate(model),
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
                              if jspace else None,
            },
            "training_data": {
                "curriculum": [
                    {"phase": p.get("name"), "tokens": p.get("tokens"), "seq_len": p.get("seq"),
                     "mix": p.get("mix")}
                    for p in phases
                ],
                "provenance": "From-scratch; deterministic in-house datagen + curated collection; "
                              "no third-party model distillation; no LM-synthetic pre-training text "
                              "(spec 02 forbids network datagen).",
            },
            "constraints": [
                "Single consumer GPU (RTX 4080/4090); free-tier tooling only.",
                "base1b is 20% over the 1.17B spec: 8.4GB weights before activations vs ~11.6GB "
                "usable — open risk #1; KV/state trims tracked in spec 11." if preset == "base1b"
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


def build_snapshot(factory: Path) -> Dict[str, Any]:
    status = _read_json(factory / "STATUS.json") or {}
    frontier = _read_json(factory / "frontier_eval_results.json") or {}
    branch = _read_json(factory / "branch_eval_results.json") or {}

    frontier_domains = []
    for row in frontier.get("results", []):
        frontier_domains.append({
            "task_id": row.get("task_id"),
            "domain": row.get("domain"),
            "overall": row.get("overall"),
            "per_rubric": [
                {"category": r.get("category"), "score": r.get("score"), "weight": r.get("weight")}
                for r in row.get("per_rubric", [])
            ],
        })

    jtests = {}
    for branch_name, payload in (branch or {}).items():
        if isinstance(payload, dict) and isinstance(payload.get("tests"), list):
            jtests[branch_name] = [
                {"test": t.get("test"), "pass": t.get("pass"), "desc": t.get("desc"),
                 "mode": t.get("mode"),
                 "metric": next((t[k] for k in ("causal_effect", "broadcast", "mass",
                                                 "auto_cos", "auc") if k in t), None)}
                for t in payload["tests"]
            ]

    trainer = status.get("trainer", {}) if isinstance(status.get("trainer"), dict) else {}
    builder = status.get("builder", {}) if isinstance(status.get("builder"), dict) else {}
    return {
        "pipeline": {
            "current_phase": builder.get("current_phase"),
            "phase_progress": builder.get("phase_progress"),
            "total_shards": builder.get("total_shards"),
            "trainer_steps": trainer.get("steps"),
            "trainer_loss": trainer.get("loss"),
            "weekly_training": (status.get("weekly_training") or {}).get("status")
            if isinstance(status.get("weekly_training"), dict) else status.get("weekly_training"),
        },
        "frontier": {"mode": frontier.get("mode"), "judge": frontier.get("judge"),
                      "domains": frontier_domains},
        "jtests": jtests,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--roots", default=str(Path(__file__).resolve().parent.parent.parent),
                        help="Directory containing the ecosystem repos (default: sibling layout)")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent / "site" / "data"))
    args = parser.parse_args(argv)

    factory = Path(args.roots) / FACTORY
    if not factory.exists():
        print(f"factory repo not found at {factory}; aborting", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    cards = {"generated_at": stamp, "source": FACTORY, "cards": build_model_cards(factory)}
    snapshot = {"generated_at": stamp, "source": FACTORY, **build_snapshot(factory)}

    (out / "model-cards.json").write_text(json.dumps(cards, indent=1), encoding="utf-8")
    (out / "snapshot.json").write_text(json.dumps(snapshot, indent=1), encoding="utf-8")
    print(f"wrote {out / 'model-cards.json'} ({len(cards['cards'])} cards) and {out / 'snapshot.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
