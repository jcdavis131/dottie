"""The router training loop: traces -> pack -> (GPU host) train -> eval -> human stamp.

``scout router pack|train|eval|promote`` are thin wrappers over this module.

pack
    Real ``source: production`` route traces joined with their run outcomes
    become strict ``jev-decision-schema-1.0.0`` records (validated by
    ``apps/jev-v0/decision_io.py``) plus a provenance sidecar. Labels come from
    what was OBSERVED, never from a model or a template:

    * ``tier`` (Choice over the five tiers): the routed tier when the run
      succeeded there; one tier up when it failed or escalated there; an
      operator correction (``scout harness correct``) always wins. A refused
      run (never executed) gets no tier label.
    * ``action`` (Choice execute/escalate/halt/other): execute on success,
      escalate when any node failed or the recovery ladder escalated, halt
      when the run was refused before executing.
    * ``safe`` (Noul): 1.0 on success, 0.0 when refused, else ok_nodes/n_nodes.
    * ``severity`` (Score 0-1): failed_nodes/n_nodes (absent when refused).

    Test rows are refused, routes with no outcome are skipped (so are partial
    ``--max-nodes`` runs and injected test failures), identical
    records are deduped, contradictory ones dropped on both sides, and at
    least 20% of GOALS (every row of a held-out goal) go to the holdout.
    ``consent.champion`` is false: a pack never promotes anything.

eval
    A checkpoint's tier answers vs the heuristic's recorded tier on the
    holdout, as a §24 :class:`dottie_loop.evaluation.EvalBundle`.
    ``gate_passed`` comes from :func:`evaluate_gates` and
    :func:`promotion_decision`. It never stamps anything; ``promote`` is a
    separate human action (:mod:`dottie_loop.router_artifacts`).
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dottie_loop.backends import (
    MOMA_TIERS,
    TIER_ORDER,
    system_one_questions,
    system_one_state,
)
from dottie_loop.errors import InvalidInputError, PolicyDeniedError
from dottie_loop.evaluation import EvalBundle, evaluate_gates, promotion_decision
from dottie_loop.hashing import now_iso
from dottie_loop.jev import SCHEMA_ID, jev_dir, load_decision_io
from dottie_loop.router import LEGACY_TIER, TIER_BUDGETS
from dottie_loop.router_artifacts import EVAL_SUMMARY, artifact_identity
from dottie_loop.traces import join_outcomes, read_traces

HOLDOUT_FRAC = 0.20
CONSENT = {"capture_training": True, "production_traces_only": True, "champion": False}
PACK_FILES = ("train.jsonl", "holdout.jsonl", "provenance.jsonl")
SLICE_MIN_N = 5
SLICE_MARGIN = 0.05
BOOTSTRAP = 1000
#: Mean tier-budget cost the candidate may spend relative to the heuristic. A
#: router that correctly escalates costs more than one that never does, so 1.0
#: would reject every useful learner; 1.5 is the owner-tunable default
#: (``scout router eval --approved-cost-ratio``), recorded in every bundle.
APPROVED_COST_RATIO = 1.5


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_corrections(path: Path | None) -> dict[str, str]:
    """run_id -> corrected MoMA-lite tier, from ``scout harness correct``'s file."""
    if path is None or not Path(path).is_file():
        return {}
    out: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("tier") in MOMA_TIERS and rec.get("run_id"):
            out[str(rec["run_id"])] = rec["tier"]
    return out


def _next_tier(tier: str) -> str:
    i = TIER_ORDER.index(tier)
    return TIER_ORDER[min(i + 1, len(TIER_ORDER) - 1)]


def observed_labels(row: dict[str, Any], corrections: dict[str, str]) -> tuple[dict[str, Any], str] | None:
    """Labels from a joined trace row's observed outcome, or None when nothing was observed."""
    outcome = row.get("outcome")
    routed = (row.get("decision") or {}).get("tier")
    if not isinstance(outcome, dict) or routed not in MOMA_TIERS:
        return None
    if outcome.get("truncated") or outcome.get("injected_failure"):
        return None  # a partial run (--max-nodes) or an injected test failure observed nothing real
    n = int(outcome.get("n_nodes") or 0)
    ok_nodes = int(outcome.get("ok_nodes") or 0)
    failed = int(outcome.get("failed_nodes") or 0)
    refused = outcome.get("ok") is False
    escalated = bool(outcome.get("escalated"))
    success = not refused and n > 0 and failed == 0 and not escalated
    labels: dict[str, Any] = {}
    source = []
    corrected = corrections.get(str(outcome.get("run_id") or ""))
    if corrected:
        labels["tier"] = {"type": "choice", "choice": corrected}
        source.append("tier:operator_correction")
    elif success:
        labels["tier"] = {"type": "choice", "choice": routed}
        source.append("tier:succeeded_at_routed_tier")
    elif not refused and n > 0:
        labels["tier"] = {"type": "choice", "choice": _next_tier(routed)}
        source.append("tier:insufficient_at_routed_tier")
    if refused:
        labels["action"] = {"type": "choice", "choice": "halt"}
        labels["safe"] = {"type": "noul", "noul": 0.0}
        source.append("action:refused_before_execution")
    elif n == 0:
        return None
    elif success:
        labels["action"] = {"type": "choice", "choice": "execute"}
        labels["safe"] = {"type": "noul", "noul": 1.0}
        labels["severity"] = {"type": "score", "score": 0.0}
        source.append("action:completed")
    else:
        labels["action"] = {"type": "choice", "choice": "escalate"}
        labels["safe"] = {"type": "noul", "noul": round(ok_nodes / n, 4)}
        labels["severity"] = {"type": "score", "score": round(failed / n, 4)}
        source.append("action:failed_or_escalated")
    return labels, ",".join(source)


def _record_key(rec: dict[str, Any], with_labels: bool) -> str:
    body = {"state": rec["state"], "questions": rec["questions"]}
    if with_labels:
        body["labels"] = rec["labels"]
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()


def split_by_goal(goals: dict[str, int], seed: int, frac: float = HOLDOUT_FRAC) -> set[str]:
    """Held-out goal hashes: whole goals, shuffled, until >= frac of rows are held out."""
    order = sorted(goals)
    random.Random(seed).shuffle(order)
    target = math.ceil(sum(goals.values()) * frac)
    held: set[str] = set()
    n = 0
    for g in order:
        if n >= target:
            break
        held.add(g)
        n += goals[g]
    return held


def pack(
    trace_files: list[Path],
    out_dir: Path,
    *,
    seed: int = 20260923,
    corrections_path: Path | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """Write train/holdout/provenance/MANIFEST under ``out_dir``. Raises when nothing real is left."""
    io = load_decision_io()
    rows, unreadable = read_traces(trace_files)
    corrections = load_corrections(corrections_path)
    rejects: Counter = Counter()
    if unreadable:
        rejects["unreadable line"] += unreadable
    built: list[dict[str, Any]] = []
    questions_all = system_one_questions()
    for row in join_outcomes(rows):
        if row.get("source") != "production" or (row.get("outcome") is not None and row.get("outcome_source") != "production"):
            rejects["refused: source is not production (test/synthetic rows never train)"] += 1
            continue
        got = observed_labels(row, corrections)
        if got is None:
            rejects["no observed outcome"] += 1
            continue
        labels, label_source = got
        feats = row.get("features") or {}
        record = {
            "schema": SCHEMA_ID,
            "id": f"rt-{row['trace_id']}",
            "state": system_one_state(feats, row.get("goal_text")),
            "questions": {q: questions_all[q] for q in labels},
            "labels": labels,
        }
        try:
            record = io.validate_record(record)
        except io.SchemaError as err:
            rejects[f"schema: {str(err)[:60]}"] += 1
            continue
        built.append({
            "record": record,
            "meta": {
                "id": record["id"],
                "trace_id": row["trace_id"],
                "goal_sha256": row.get("goal_sha256") or feats.get("goal_sha256"),
                "surface": row.get("surface"),
                "at": row.get("at"),
                "source": row.get("source"),
                "run_id": (row.get("outcome") or {}).get("run_id"),
                "routed_tier": (row.get("decision") or {}).get("tier"),
                "heuristic_tier": (row.get("decision") or {}).get("heuristic_tier"),
                "authority": (row.get("decision") or {}).get("authority"),
                "label_source": label_source,
                "goal_text_captured": "goal_text" in record["state"],
            },
        })

    by_q: dict[str, set[str]] = defaultdict(set)
    for b in built:
        by_q[_record_key(b["record"], False)].add(_record_key(b["record"], True))
    conflicted = {k for k, labs in by_q.items() if len(labs) > 1}
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    for b in built:
        if _record_key(b["record"], False) in conflicted:
            rejects["conflicting labels"] += 1
            continue
        k = _record_key(b["record"], True)
        if k in seen:
            rejects["duplicate"] += 1
            continue
        seen.add(k)
        kept.append(b)

    goals = Counter(b["meta"]["goal_sha256"] for b in kept)
    if len(goals) < 2:
        raise InvalidInputError(
            f"need production traces with observed outcomes for >= 2 distinct goals; have {len(goals)} "
            f"(rejected: {dict(rejects)})",
            field="traces",
        )
    held = split_by_goal(dict(goals), seed)
    for b in kept:
        b["meta"]["split"] = "holdout" if b["meta"]["goal_sha256"] in held else "train"
        b["meta"]["consent"] = dict(CONSENT)
    train = [b for b in kept if b["meta"]["split"] == "train"]
    hold = [b for b in kept if b["meta"]["split"] == "holdout"]
    if not train or not hold:
        raise InvalidInputError("split left train or holdout empty; collect more distinct goals", field="traces")

    out_dir = Path(out_dir)
    _write_jsonl(out_dir / "train.jsonl", [b["record"] for b in train])
    _write_jsonl(out_dir / "holdout.jsonl", [b["record"] for b in hold])
    _write_jsonl(out_dir / "provenance.jsonl", [b["meta"] for b in kept])
    pack_id = version or f"router-pack-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    manifest = {
        "pack": pack_id,
        "schema": SCHEMA_ID,
        "kind": "router-traces",
        "seed": seed,
        "consent": dict(CONSENT),
        "all_rows_production": True,
        "rows": {"total": len(kept), "train": len(train), "holdout": len(hold),
                 "holdout_frac": round(len(hold) / len(kept), 4)},
        "goals": {"total": len(goals), "holdout": len(held)},
        "labels": {
            "tier": dict(Counter(b["record"]["labels"]["tier"]["choice"] for b in kept if "tier" in b["record"]["labels"])),
            "action": dict(Counter(b["record"]["labels"]["action"]["choice"] for b in kept)),
            "label_sources": dict(Counter(b["meta"]["label_source"] for b in kept)),
        },
        "goal_text_captured": sum(1 for b in kept if b["meta"]["goal_text_captured"]),
        "rejected": dict(rejects),
        "files": {n: {"sha256": _sha256(out_dir / n), "bytes": (out_dir / n).stat().st_size} for n in PACK_FILES},
        "sources": {str(p): _sha256(p) for p in sorted(trace_files) if p.is_file()},
        "built_at": now_iso(),
        "rules": [
            "rows are real production harness traces only; test/synthetic rows are refused",
            "labels are observed outcomes (success at the routed tier, failure/escalation, refusal) or operator corrections",
            "holdout is whole goals (>= 20% of rows); no goal straddles the split",
            "consent.champion=false: a pack never promotes anything; promotion is a human stamp",
        ],
    }
    (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def verify_pack(pack_dir: Path) -> dict[str, Any]:
    """Recompute file hashes and the split; the eval's data_integrity evidence."""
    pack_dir = Path(pack_dir)
    try:
        manifest = json.loads((pack_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InvalidInputError(f"pack has no readable MANIFEST.json: {exc}", field="pack") from exc
    files_ok = all(
        (pack_dir / n).is_file() and _sha256(pack_dir / n) == (manifest.get("files", {}).get(n) or {}).get("sha256")
        for n in PACK_FILES
    )
    prov = _read_jsonl(pack_dir / "provenance.jsonl") if (pack_dir / "provenance.jsonl").is_file() else []
    splits: dict[str, set[str]] = defaultdict(set)
    for m in prov:
        splits[m.get("goal_sha256")].add(m.get("split"))
    straddle = sorted(g for g, s in splits.items() if len(s) > 1)
    non_prod = sum(1 for m in prov if m.get("source") != "production")
    return {
        "manifest_ok": files_ok and manifest.get("schema") == SCHEMA_ID,
        "split_ok": not straddle,
        "leakage": bool(straddle),
        "privacy_unresolved": False,
        "non_production_rows": non_prod,
        "consent_champion": (manifest.get("consent") or {}).get("champion"),
        "pack": manifest.get("pack"),
    }


# --- train (GPU host) ----------------------------------------------------------------------


def train_command(pack_dir: Path, out_dir: Path, *, go: bool, steps: int = 200, base_model: str | None = None) -> list[str]:
    """argv for jev-v0's pointer-LoRA trainer on the pack's train split."""
    cmd = [sys.executable, str(jev_dir() / "train_pointer_lora.py"), "--go" if go else "--dry-run",
           "--fixtures", str(Path(pack_dir) / "train.jsonl")]
    if go:
        cmd += ["--out", str(out_dir), "--steps", str(steps)]
    if base_model:
        cmd += ["--base-model", base_model]
    return cmd


# --- eval ----------------------------------------------------------------------------------


def _tier_items(pack_dir: Path) -> list[dict[str, Any]]:
    hold = _read_jsonl(Path(pack_dir) / "holdout.jsonl")
    prov = {m["id"]: m for m in _read_jsonl(Path(pack_dir) / "provenance.jsonl")}
    items = []
    for rec in hold:
        if "tier" not in rec["labels"]:
            continue
        meta = prov.get(rec["id"], {})
        items.append({
            "id": rec["id"],
            "state": rec["state"],
            "label": rec["labels"]["tier"]["choice"],
            "action": rec["labels"].get("action", {}).get("choice"),
            "heuristic": meta.get("heuristic_tier"),
        })
    return items


def checkpoint_predictions(checkpoint: Path, items: list[dict[str, Any]]) -> dict[str, str]:
    """Run jev-v0's pointer checkpoint on each holdout state (needs torch; GPU host)."""
    import importlib.util

    path = jev_dir() / "pointer_infer.py"
    spec = importlib.util.spec_from_file_location("jev_pointer_infer", path)
    if spec is None or spec.loader is None:
        raise InvalidInputError(f"cannot load {path}", field="checkpoint")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    predictor = mod.load_checkpoint(Path(checkpoint))
    question = system_one_questions()["tier"]
    out = {}
    for it in items:
        probs = predictor.probabilities(it["state"], question)
        out[it["id"]] = max(probs, key=lambda k: probs[k])
    return out


def _bootstrap_ci(diffs: list[float], seed: int) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(BOOTSTRAP))
    return means[int(0.025 * BOOTSTRAP)], means[int(0.975 * BOOTSTRAP) - 1]


def _cost(tier: str | None) -> float:
    spec = LEGACY_TIER.get(tier or "", "T4")
    return float(TIER_BUDGETS[spec]["tokens"])


def evaluate(
    pack_dir: Path,
    candidate: Path,
    predictions: dict[str, str],
    *,
    predictions_source: str,
    evaluator_commit: str = "unknown",
    seed: int = 20260923,
    canary: dict[str, Any] | None = None,
    approved_cost_ratio: float = APPROVED_COST_RATIO,
) -> dict[str, Any]:
    """Build the eval summary for ``candidate`` (not written; see :func:`write_eval_summary`)."""
    items = _tier_items(pack_dir)
    if not items:
        raise InvalidInputError("holdout has no tier-labelled rows", field="pack")
    integrity = verify_pack(pack_dir)
    cand_ok = [predictions.get(it["id"]) == it["label"] for it in items]
    heur_ok = [it["heuristic"] == it["label"] for it in items]
    n = len(items)
    cand_acc = sum(cand_ok) / n
    heur_acc = sum(heur_ok) / n
    ci_low, ci_high = _bootstrap_ci([float(c) - float(h) for c, h in zip(cand_ok, heur_ok, strict=True)], seed)
    slices: dict[str, float] = {}
    floors: dict[str, float] = {}
    by_label: dict[str, list[int]] = defaultdict(list)
    for i, it in enumerate(items):
        by_label[it["label"]].append(i)
    for label, idx in sorted(by_label.items()):
        if len(idx) < SLICE_MIN_N:
            continue
        slices[f"tier={label}"] = sum(cand_ok[i] for i in idx) / len(idx)
        floors[f"tier={label}"] = max(0.0, sum(heur_ok[i] for i in idx) / len(idx) - SLICE_MARGIN)
    # Safety regression: a run that needed a human (escalate/halt) routed CHEAPER than
    # its label by the candidate where the heuristic was not.
    safety = 0
    for it in items:
        if it["action"] not in ("escalate", "halt"):
            continue
        p = predictions.get(it["id"])
        cheaper = p in MOMA_TIERS and TIER_ORDER.index(p) < TIER_ORDER.index(it["label"])
        heur_cheaper = it["heuristic"] in MOMA_TIERS and TIER_ORDER.index(it["heuristic"]) < TIER_ORDER.index(it["label"])
        if cheaper and not heur_cheaper:
            safety += 1
    at = now_iso()
    cand_id = artifact_identity(candidate)
    bundle = EvalBundle(
        candidate={"id": str(candidate), "sha256": cand_id},
        incumbent={"id": "heuristic:moma-lite", "sha256": "n/a"},
        benchmark_version=str(integrity.get("pack")),
        hidden_set_snapshot=_sha256(Path(pack_dir) / "holdout.jsonl"),
        primary_metric="tier_accuracy",
        candidate_primary=round(cand_acc, 6),
        incumbent_primary=round(heur_acc, 6),
        ci_low=round(ci_low, 6),
        ci_high=round(ci_high, 6),
        n_items=n,
        slice_results=slices,
        slice_floors=floors,
        regressions={"safety": safety, "authorization": 0, "protected_tests": 0},
        safety_findings=[],
        efficiency={
            "candidate_cost": sum(_cost(predictions.get(it["id"])) for it in items) / n,
            "incumbent_cost": sum(_cost(it["heuristic"]) for it in items) / n,
            "approved_ratio": float(approved_cost_ratio),
        },
        overlap_report=integrity,
        synthetic=integrity["non_production_rows"] > 0 or integrity["consent_champion"] is not False,
        mock=False,
        evaluator_commit=evaluator_commit,
        evaluated_at=at,
        baseline_evaluated_at=at,
    )
    gates = evaluate_gates(bundle)
    decision = promotion_decision(gates, canary=canary, approval_valid=False)
    # Offline gates passed when nothing failed; the remaining steps (canary, the
    # human stamp) are what promotion_decision says is still missing.
    offline_ok = decision["outcome"] in ("hold", "promote") or decision["reason"] == "explicit approval missing"
    gate_passed = gates["verdict"] == "pass" and offline_ok
    return {
        "schema": "dottie-router-eval-1",
        "artifact": str(Path(candidate).resolve()),
        "artifact_sha256": cand_id,
        "pack": integrity.get("pack"),
        "predictions_source": predictions_source,
        "metrics": {"candidate_tier_accuracy": round(cand_acc, 6), "heuristic_tier_accuracy": round(heur_acc, 6),
                    "n": n, "paired_diff_ci95": [round(ci_low, 6), round(ci_high, 6)],
                    "coverage": round(sum(1 for it in items if it["id"] in predictions) / n, 6)},
        "bundle": bundle.to_dict(),
        "gates": gates,
        "promotion": decision,
        "gate_passed": gate_passed,
        "stamped": False,
        "note": "gate_passed is necessary, not sufficient: authority also needs `scout router promote --i-have-reviewed`",
    }


def write_eval_summary(candidate: Path, summary: dict[str, Any]) -> Path:
    candidate = Path(candidate)
    path = candidate / EVAL_SUMMARY if candidate.is_dir() else candidate.with_name(EVAL_SUMMARY)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def refuse_synthetic_pack(pack_dir: Path) -> None:
    """Raise unless the pack says it is production-only and champion=false."""
    integrity = verify_pack(pack_dir)
    if integrity["non_production_rows"] or integrity["consent_champion"] is not False:
        raise PolicyDeniedError("pack carries non-production rows or champion consent; refusing", field="pack")
