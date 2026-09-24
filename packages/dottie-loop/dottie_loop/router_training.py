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

    Outcomes observed by stub executors (``executor: stub``; untagged pre-tag
    traces, whose executors were all stubs, likewise) never label a row and
    are counted in the manifest's ``executors``. The state is rebuilt with the
    same :func:`dottie_loop.backends.system_one_state` the router serves with,
    and a trace carrying ``state_sha256`` must rebuild to that exact hash.
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
    state_sha256,
    system_one_questions,
    system_one_state,
)
from dottie_loop.errors import InvalidInputError, PolicyDeniedError
from dottie_loop.evaluation import EvalBundle, evaluate_gates, promotion_decision
from dottie_loop.hashing import now_iso
from dottie_loop.jev import SCHEMA_ID, jev_dir, load_decision_io
from dottie_loop.provenance import (
    BENCHMARK,
    MIN_PRODUCTION_ROWS,
    PRODUCTION,
    TRAINABLE,
    WEIGHTS,
    eval_set_hashes,
    norm_key,
    row_provenance,
)
from dottie_loop.router import LEGACY_TIER, TIER_BUDGETS
from dottie_loop.router_artifacts import EVAL_SUMMARY, artifact_identity
from dottie_loop.traces import join_outcomes, read_traces

HOLDOUT_FRAC = 0.20
#: Share of benchmark-verified goals held out as the (secondary) benchmark holdout.
BENCH_HOLDOUT_FRAC = 0.20
#: The candidate may not trail the heuristic on the benchmark holdout by more than this.
BENCH_REGRESSION_MARGIN = 0.0
CONSENT = {"capture_training": True, "production_traces_only": False, "trainable_provenance": sorted(TRAINABLE),
           "champion": False}
PACK_FILES = ("train.jsonl", "holdout.jsonl", "holdout_benchmark.jsonl", "provenance.jsonl")
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


def probe_labels(outcome: dict[str, Any], *, allow_upper_bound: bool) -> tuple[dict[str, Any], str] | str:
    """Labels of a ``scout router probe`` outcome, or the reason it gives none.

    The tier label is the probe's minimal sufficient tier: the cheapest tier
    whose real executor produced an answer that passed the goal's verifier.
    ``insufficient`` and ``unavailable`` probes label nothing. An upper-bound
    label (a cheaper tier could not run, so it is unknown whether it would have
    sufficed) labels only under ``allow_upper_bound``.
    """
    probe = outcome.get("probe") if isinstance(outcome.get("probe"), dict) else None
    if probe is None:
        return "refused: benchmark outcome has no probe record"
    status = probe.get("status")
    if status == "labeled_upper_bound" and not allow_upper_bound:
        return "refused: probe label is an upper bound (a cheaper tier was unavailable); pass allow_upper_bound"
    if status not in ("labeled", "labeled_upper_bound"):
        return f"no label: probe status {status}"
    tier = probe.get("minimal_tier")
    if tier not in MOMA_TIERS or outcome.get("verified") is not True:
        return "refused: probe label without a passing verifier"
    labels = {
        "tier": {"type": "choice", "choice": tier},
        "action": {"type": "choice", "choice": "execute"},
        "safe": {"type": "noul", "noul": 1.0},
        "severity": {"type": "score", "score": 0.0},
    }
    source = "tier:probe_minimal_sufficient" if status == "labeled" else "tier:probe_upper_bound"
    return labels, source + ",action:completed"


def _refusal(row: dict[str, Any]) -> str | None:
    """Why a joined row may not become a record (source, provenance, executor), or None."""
    if row.get("source") != "production" or (row.get("outcome") is not None and row.get("outcome_source") != "production"):
        return "refused: source is not production (test/synthetic rows never train)"
    prov = row_provenance(row)
    if prov not in TRAINABLE:
        return f"refused: provenance {prov} never trains a router"
    if row.get("outcome") is not None and row.get("outcome_provenance") not in (None, prov):
        return "refused: route and outcome provenance differ"
    return None


def _executor_refusal(outcome: Any, counts: Counter) -> str | None:
    if not isinstance(outcome, dict):
        return None
    executor = outcome.get("executor")
    if executor == "real":
        counts["real"] += 1
        return None
    if executor == "stub":
        counts["stub"] += 1
        return "refused: stub executor (the outcome observed a stub, not real work)"
    if executor is None:
        counts["untagged"] += 1
        return "refused: outcome has no executor tag (pre-tag trace; its executors were stubs)"
    counts["other"] += 1
    return f"refused: executor {executor!r} is not real work"


def _load_bench_texts(bench_files: list[Path] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in bench_files or []:
        for g in _read_jsonl(Path(p)):
            if g.get("id") and g.get("goal"):
                out[str(g["id"])] = str(g["goal"])
    return out


def _load_eval_texts(eval_sets: list[Path] | None) -> list[str]:
    """Goal-like strings of external eval sets (jsonl: goal/prompt/question/input/text fields)."""
    texts: list[str] = []
    for p in eval_sets or []:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                texts += [str(obj[k]) for k in ("goal", "prompt", "question", "input", "text") if isinstance(obj.get(k), str)]
    return texts


def _build_row(row: dict[str, Any], labels: dict[str, Any], label_source: str, io: Any,
               questions_all: dict[str, Any], bench_texts: dict[str, str]) -> dict[str, Any] | str:
    feats = row.get("features") or {}
    state = system_one_state(row.get("goal_text"), row.get("context"), features=feats, include_text=True)
    if row.get("state_sha256") and state_sha256(state) != row["state_sha256"]:
        return "refused: rebuilt state does not match the served state (train/serve drift)"
    record = {"schema": SCHEMA_ID, "id": f"rt-{row['trace_id']}", "state": state,
              "questions": {q: questions_all[q] for q in labels}, "labels": labels}
    try:
        record = io.validate_record(record)
    except io.SchemaError as err:
        return f"schema: {str(err)[:60]}"
    outcome = row.get("outcome") or {}
    prov = row_provenance(row)
    bench_id = (outcome.get("bench") or {}).get("id") if isinstance(outcome.get("bench"), dict) else None
    meta = {
        "id": record["id"],
        "trace_id": row["trace_id"],
        "goal_sha256": row.get("goal_sha256") or feats.get("goal_sha256"),
        "norm_key": norm_key(row),
        "surface": row.get("surface"),
        "at": row.get("at"),
        "source": row.get("source"),
        "provenance": prov,
        "weight": WEIGHTS[prov],
        "run_id": outcome.get("run_id"),
        "routed_tier": (row.get("decision") or {}).get("tier"),
        "heuristic_tier": (row.get("decision") or {}).get("heuristic_tier"),
        "authority": (row.get("decision") or {}).get("authority"),
        "label_source": label_source,
        "goal_text_captured": "goal_text" in record["state"],
        "context_digest": (record["state"].get("context") or {}).get("digest"),
        "executor": outcome.get("executor"),
        "tokens": outcome.get("tokens"),
        "bench_id": bench_id,
    }
    if bench_id and bench_id in bench_texts:
        # public curated benchmark text, joined from the committed goal set (never from the trace)
        meta["bench_text"] = bench_texts[bench_id]
    return {"record": record, "meta": meta}


def _dedupe(built: list[dict[str, Any]], rejects: Counter) -> list[dict[str, Any]]:
    """One row per (provenance, normalised goal): repeats are duplicates; a goal whose labels contradict drops entirely.

    Within one provenance only: a benchmark row never knocks out a production row.
    The same goal across provenances is resolved by :func:`_split` (it never
    trains while it sits in an eval holdout).
    """

    def goal_key(b: dict[str, Any]) -> str:
        return f"{b['meta']['provenance']}:{b['meta']['norm_key'] or _record_key(b['record'], False)}"

    labels_of: dict[str, set[str]] = defaultdict(set)
    for b in built:
        labels_of[goal_key(b)].add(json.dumps(b["record"]["labels"], sort_keys=True))
    conflicted = {k for k, labs in labels_of.items() if len(labs) > 1}
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    for b in built:
        k = goal_key(b)
        if k in conflicted:
            rejects["conflicting labels"] += 1
            continue
        if k in seen:
            rejects["duplicate"] += 1
            continue
        seen.add(k)
        kept.append(b)
    return kept


def _split(kept: list[dict[str, Any]], seed: int, external: set[str], rejects: Counter) -> dict[str, list[dict[str, Any]]]:
    """Production holdout, disjoint benchmark holdout, then a train split decontaminated against every eval set."""
    prod_keys = Counter(b["meta"]["norm_key"] for b in kept if b["meta"]["provenance"] == PRODUCTION)
    prod_hold = split_by_goal(dict(prod_keys), seed) if len(prod_keys) >= 2 else set()
    bench_keys = Counter(b["meta"]["norm_key"] for b in kept
                         if b["meta"]["provenance"] == BENCHMARK and b["meta"]["norm_key"] not in prod_hold)
    bench_hold = split_by_goal(dict(bench_keys), seed + 1, BENCH_HOLDOUT_FRAC) if len(bench_keys) >= 2 else set()
    out: dict[str, list[dict[str, Any]]] = {"train": [], "holdout": [], "holdout_benchmark": []}
    for b in kept:
        key, prov = b["meta"]["norm_key"], b["meta"]["provenance"]
        if prov == PRODUCTION and key in prod_hold:
            split = "holdout"
        elif prov == BENCHMARK and key in bench_hold:
            split = "holdout_benchmark"
        elif key in prod_hold or key in bench_hold:
            rejects["decontaminated: goal is in an eval holdout of another provenance"] += 1
            continue
        elif key in external:
            rejects["decontaminated: goal is in an external eval set"] += 1
            continue
        else:
            split = "train"
        b["meta"]["split"] = split
        b["meta"]["consent"] = dict(CONSENT)
        out[split].append(b)
    return out


def pack(
    trace_files: list[Path],
    out_dir: Path,
    *,
    seed: int = 20260923,
    corrections_path: Path | None = None,
    version: str | None = None,
    allow_upper_bound: bool = False,
    bench_files: list[Path] | None = None,
    eval_sets: list[Path] | None = None,
) -> dict[str, Any]:
    """Write train / holdouts / provenance / MANIFEST under ``out_dir``. Raises when nothing real is left.

    ``bench_files``: the benchmark goal sets the probe ran (their public goal
    text is joined into the provenance sidecar for the MLP trainer).
    ``eval_sets``: external eval sets whose goals must never train
    (normalised-hash decontamination).
    """
    io = load_decision_io()
    rows, unreadable = read_traces(trace_files)
    corrections = load_corrections(corrections_path)
    bench_texts = _load_bench_texts(bench_files)
    external = eval_set_hashes(_load_eval_texts(eval_sets))
    rejects: Counter = Counter()
    if unreadable:
        rejects["unreadable line"] += unreadable
    built: list[dict[str, Any]] = []
    questions_all = system_one_questions()
    executor_counts: Counter = Counter()
    for row in join_outcomes(rows):
        reason = _refusal(row) or _executor_refusal(row.get("outcome"), executor_counts)
        if reason:
            rejects[reason] += 1
            continue
        if row_provenance(row) == BENCHMARK:
            got: Any = probe_labels(row.get("outcome") or {}, allow_upper_bound=allow_upper_bound) \
                if isinstance(row.get("outcome"), dict) else "no observed outcome"
        else:
            got = observed_labels(row, corrections) or "no observed outcome"
        if isinstance(got, str):
            rejects[got] += 1
            continue
        b = _build_row(row, got[0], got[1], io, questions_all, bench_texts)
        if isinstance(b, str):
            rejects[b] += 1
            continue
        built.append(b)

    kept = _dedupe(built, rejects)
    goals = Counter(b["meta"]["norm_key"] for b in kept)
    if len(goals) < 2:
        raise InvalidInputError(
            f"need real traces with observed outcomes for >= 2 distinct goals; have {len(goals)} "
            f"(rejected: {dict(rejects)})",
            field="traces",
        )
    splits = _split(kept, seed, external, rejects)
    train, hold, bench_hold = splits["train"], splits["holdout"], splits["holdout_benchmark"]
    if not train or not (hold or bench_hold):
        raise InvalidInputError("split left train or holdout empty; collect more distinct goals", field="traces")
    kept = train + hold + bench_hold

    out_dir = Path(out_dir)
    _write_jsonl(out_dir / "train.jsonl", [b["record"] for b in train])
    _write_jsonl(out_dir / "holdout.jsonl", [b["record"] for b in hold])
    _write_jsonl(out_dir / "holdout_benchmark.jsonl", [b["record"] for b in bench_hold])
    _write_jsonl(out_dir / "provenance.jsonl", [b["meta"] for b in kept])
    manifest = _manifest(out_dir, version, seed, kept, splits, executor_counts, rejects, trace_files, external)
    (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _manifest(out_dir: Path, version: str | None, seed: int, kept: list[dict[str, Any]],
              splits: dict[str, list[dict[str, Any]]], executor_counts: Counter, rejects: Counter,
              trace_files: list[Path], external: set[str]) -> dict[str, Any]:
    by_prov = Counter(b["meta"]["provenance"] for b in kept)
    return {
        "pack": version or f"router-pack-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        "schema": SCHEMA_ID,
        "kind": "router-traces",
        "seed": seed,
        "consent": dict(CONSENT),
        "all_rows_production": set(by_prov) == {PRODUCTION},
        "provenance": dict(by_prov),
        "production_rows": by_prov.get(PRODUCTION, 0),
        "weights": {p: WEIGHTS[p] for p in sorted(by_prov)},
        "rows": {"total": len(kept), "train": len(splits["train"]), "holdout": len(splits["holdout"]),
                 "holdout_benchmark": len(splits["holdout_benchmark"]),
                 "holdout_frac": round((len(splits["holdout"]) + len(splits["holdout_benchmark"])) / len(kept), 4),
                 "train_by_provenance": dict(Counter(b["meta"]["provenance"] for b in splits["train"]))},
        "goals": {"total": len({b["meta"]["norm_key"] for b in kept}),
                  "holdout": len({b["meta"]["norm_key"] for b in splits["holdout"]}),
                  "holdout_benchmark": len({b["meta"]["norm_key"] for b in splits["holdout_benchmark"]}),
                  "external_eval_hashes": len(external)},
        "labels": {
            "tier": dict(Counter(b["record"]["labels"]["tier"]["choice"] for b in kept if "tier" in b["record"]["labels"])),
            "action": dict(Counter(b["record"]["labels"]["action"]["choice"] for b in kept)),
            "label_sources": dict(Counter(b["meta"]["label_source"] for b in kept)),
        },
        "goal_text_captured": sum(1 for b in kept if b["meta"]["goal_text_captured"]),
        "with_context": sum(1 for b in kept if b["meta"]["context_digest"]),
        "executors": {"real": executor_counts.get("real", 0), "stub_excluded": executor_counts.get("stub", 0),
                      "untagged_excluded": executor_counts.get("untagged", 0),
                      **({"other_excluded": executor_counts["other"]} if executor_counts.get("other") else {})},
        "rejected": dict(rejects),
        "files": {n: {"sha256": _sha256(out_dir / n), "bytes": (out_dir / n).stat().st_size} for n in PACK_FILES},
        "sources": {str(p): _sha256(p) for p in sorted(trace_files) if p.is_file()},
        "built_at": now_iso(),
        "rules": [
            "rows are real traces only: provenance production (weight 1.0) or benchmark-verified (0.7); "
            "test, teacher, synthetic and outcome-real rows are refused",
            "production labels are observed outcomes or operator corrections; benchmark labels are the probe's "
            "minimal sufficient tier (a real executor's answer passed the goal's verifier)",
            "outcomes not observed by real executors (stub, untagged, other) never label a row",
            "state is rebuilt with the same system_one_state builder the router serves; a trace whose state_sha256 does not match is refused",
            "holdout.jsonl is whole production goals (>= 20% of production rows), the primary gate set; "
            "holdout_benchmark.jsonl is whole benchmark goals, disjoint from it",
            "dedupe and decontamination key on the normalised goal hash: no goal in any holdout or external eval set trains",
            "consent.champion=false: a pack never promotes anything; promotion is a human stamp",
        ],
    }


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
        splits[m.get("norm_key") or m.get("goal_sha256")].add(m.get("split"))
    straddle = sorted(g for g, s in splits.items() if len(s) > 1)
    non_prod = sum(1 for m in prov if m.get("source") != "production")
    untrainable = sum(1 for m in prov if m.get("provenance", PRODUCTION) not in TRAINABLE)
    return {
        "manifest_ok": files_ok and manifest.get("schema") == SCHEMA_ID,
        "split_ok": not straddle,
        "leakage": bool(straddle),
        "privacy_unresolved": False,
        "non_production_rows": non_prod,
        "untrainable_rows": untrainable,
        "provenance": dict(Counter(m.get("provenance", PRODUCTION) for m in prov)),
        "production_rows": sum(1 for m in prov if m.get("provenance", PRODUCTION) == PRODUCTION),
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


def _tier_items(pack_dir: Path, split: str = "holdout.jsonl") -> list[dict[str, Any]]:
    path = Path(pack_dir) / split
    if not path.is_file():
        return []
    hold = _read_jsonl(path)
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
            "text": rec["state"].get("goal_text") or meta.get("bench_text"),
            "provenance": meta.get("provenance", PRODUCTION),
        })
    return items


def eval_items(pack_dir: Path) -> list[dict[str, Any]]:
    """Every tier-labelled item of both holdouts (what a checkpoint must answer)."""
    return _tier_items(pack_dir) + _tier_items(pack_dir, "holdout_benchmark.jsonl")


def is_mlp_weights(checkpoint: Path) -> bool:
    """True for an orchestrator-MLP weights file (schema_version 1 JSON)."""
    checkpoint = Path(checkpoint)
    if not checkpoint.is_file() or checkpoint.suffix != ".json":
        return False
    try:
        return json.loads(checkpoint.read_text(encoding="utf-8")).get("schema_version") == 1
    except (OSError, ValueError, AttributeError):
        return False


def mlp_predictions(weights: Path, items: list[dict[str, Any]]) -> dict[str, str]:
    """The MLP's tier for every item with goal text (CPU, numpy). Items without text get no answer."""
    from dottie_loop import mlp_infer

    model = mlp_infer.load_weights(Path(weights))
    return {it["id"]: mlp_infer.predict(model, it["text"])["tier"] for it in items if it.get("text")}


def checkpoint_predictions(checkpoint: Path, items: list[dict[str, Any]]) -> dict[str, str]:
    """Run a checkpoint on each holdout state: the MLP on CPU, or jev-v0's pointer checkpoint (torch; GPU host)."""
    import importlib.util

    if is_mlp_weights(checkpoint):
        return mlp_predictions(checkpoint, items)
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


def _accuracy(items: list[dict[str, Any]], predictions: dict[str, str]) -> dict[str, Any]:
    if not items:
        return {"n": 0, "candidate_tier_accuracy": None, "heuristic_tier_accuracy": None, "coverage": None}
    n = len(items)
    return {
        "n": n,
        "candidate_tier_accuracy": round(sum(predictions.get(it["id"]) == it["label"] for it in items) / n, 6),
        "heuristic_tier_accuracy": round(sum(it["heuristic"] == it["label"] for it in items) / n, 6),
        "coverage": round(sum(1 for it in items if it["id"] in predictions) / n, 6),
    }


def _bundle(pack_dir: Path, candidate: Path, items: list[dict[str, Any]], predictions: dict[str, str],
            integrity: dict[str, Any], *, evaluator_commit: str, seed: int, approved_cost_ratio: float) -> EvalBundle:
    """The §24 bundle over the PRODUCTION holdout (the primary gate set)."""
    cand_ok = [predictions.get(it["id"]) == it["label"] for it in items]
    heur_ok = [it["heuristic"] == it["label"] for it in items]
    n = len(items)
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
    return EvalBundle(
        candidate={"id": str(candidate), "sha256": artifact_identity(candidate)},
        incumbent={"id": "heuristic:moma-lite", "sha256": "n/a"},
        benchmark_version=str(integrity.get("pack")),
        hidden_set_snapshot=_sha256(Path(pack_dir) / "holdout.jsonl"),
        primary_metric="tier_accuracy",
        candidate_primary=round(sum(cand_ok) / n, 6),
        incumbent_primary=round(sum(heur_ok) / n, 6),
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
        synthetic=integrity["non_production_rows"] > 0 or integrity["untrainable_rows"] > 0
        or integrity["consent_champion"] is not False,
        mock=False,
        evaluator_commit=evaluator_commit,
        evaluated_at=at,
        baseline_evaluated_at=at,
    )


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
    min_production_rows: int = MIN_PRODUCTION_ROWS,
    bench_margin: float = BENCH_REGRESSION_MARGIN,
) -> dict[str, Any]:
    """Build the eval summary for ``candidate`` (not written; see :func:`write_eval_summary`).

    The gate passes only when ALL hold, and ``refusals`` names each that does not:

    1. the pack holds at least ``min_production_rows`` production rows;
    2. the candidate beats the heuristic on the production holdout (the §24
       gates of :func:`dottie_loop.evaluation.evaluate_gates`, task_win first);
    3. it does not trail the heuristic on the benchmark holdout by more than
       ``bench_margin``.
    """
    items = _tier_items(pack_dir)
    bench_items = _tier_items(pack_dir, "holdout_benchmark.jsonl")
    if not items and not bench_items:
        raise InvalidInputError("neither holdout has tier-labelled rows", field="pack")
    integrity = verify_pack(pack_dir)
    refusals: list[str] = []
    if integrity["production_rows"] < min_production_rows:
        refusals.append(f"too few production rows: {integrity['production_rows']} < {min_production_rows} "
                        "(benchmark rows can train candidates but cannot stand in for real use)")
    prod = _accuracy(items, predictions)
    bench = _accuracy(bench_items, predictions)
    if bench["n"] and bench["candidate_tier_accuracy"] < bench["heuristic_tier_accuracy"] - bench_margin:
        refusals.append(f"regresses on the benchmark holdout: {bench['candidate_tier_accuracy']} < "
                        f"heuristic {bench['heuristic_tier_accuracy']} - margin {bench_margin}")
    bundle = gates = None
    if items:
        bundle = _bundle(pack_dir, candidate, items, predictions, integrity, evaluator_commit=evaluator_commit,
                         seed=seed, approved_cost_ratio=approved_cost_ratio)
        gates = evaluate_gates(bundle)
        decision = promotion_decision(gates, canary=canary, approval_valid=False)
        if gates["failed"]:
            refusals.append(f"production holdout gates failed: {gates['failed']}")
        ci = [bundle.ci_low, bundle.ci_high]
    else:
        refusals.append("production holdout is empty: nothing measures real use")
        decision = {"outcome": "block", "reason": "no production holdout", "next_actions": ["collect production traces"],
                    "at": now_iso()}
        ci = None
    # Offline gates passed when nothing failed; the remaining steps (canary, the
    # human spot-check and stamp) are what promotion_decision says is still missing.
    offline_ok = decision["outcome"] in ("hold", "promote") or decision["reason"] == "explicit approval missing"
    gate_passed = not refusals and gates is not None and gates["verdict"] == "pass" and offline_ok
    return {
        "schema": "dottie-router-eval-2",
        "artifact": str(Path(candidate).resolve()),
        "artifact_sha256": artifact_identity(candidate),
        "pack": integrity.get("pack"),
        "predictions_source": predictions_source,
        "metrics": {"candidate_tier_accuracy": prod["candidate_tier_accuracy"],
                    "heuristic_tier_accuracy": prod["heuristic_tier_accuracy"],
                    "n": prod["n"], "paired_diff_ci95": ci, "coverage": prod["coverage"],
                    "benchmark": bench, "production_rows": integrity["production_rows"],
                    "min_production_rows": min_production_rows, "provenance": integrity["provenance"]},
        "bundle": bundle.to_dict() if bundle else None,
        "gates": gates or {"failed": ["no_production_holdout"], "verdict": "fail", "gates": {}},
        "promotion": decision,
        "refusals": refusals,
        "gate_passed": gate_passed,
        "stamped": False,
        "note": "gate_passed is necessary, not sufficient: authority also needs `scout router spotcheck` "
                "marked by a human and `scout router promote --i-have-reviewed`",
    }


def write_eval_summary(candidate: Path, summary: dict[str, Any]) -> Path:
    candidate = Path(candidate)
    path = candidate / EVAL_SUMMARY if candidate.is_dir() else candidate.with_name(EVAL_SUMMARY)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def refuse_synthetic_pack(pack_dir: Path) -> None:
    """Raise unless every row is real (production or benchmark-verified, source production) and champion=false."""
    integrity = verify_pack(pack_dir)
    if integrity["non_production_rows"] or integrity["untrainable_rows"] or integrity["consent_champion"] is not False:
        raise PolicyDeniedError("pack carries test/teacher/synthetic rows or champion consent; refusing", field="pack")
