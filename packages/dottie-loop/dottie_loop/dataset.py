"""Data acquisition, QA, curation, splitting, packing, manifests and deletion
propagation (spec §17–§20, §37B DatasetManifest).

Every dataset release passes a hard-block chain::

    acquire → consent → redact → validate → qualify → curate → split → pack → release

and must satisfy the accounting invariant::

    raw = excluded_consent + excluded_privacy + invalid + quarantined
        + deduplicated + train + validation + test

A single failed required check blocks publication (ML-02): the pipeline emits a
diagnostic report, never a trainable manifest.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dottie_loop.capture import export_eligibility, redact_record
from dottie_loop.errors import InvalidInputError, PolicyDeniedError, UnexecutableError
from dottie_loop.hashing import digest, file_sha256, new_id, now_iso
from dottie_loop.schema import active

BUCKETS = (
    "excluded_consent",
    "excluded_privacy",
    "invalid",
    "quarantined",
    "deduplicated",
    "train",
    "validation",
    "test",
)
KNOWN_LICENSES = frozenset({"private-opt-in", "public-domain", "mit", "apache-2.0", "cc-by-4.0", "cc0"})


@dataclass
class Source:
    id: str
    license: str
    consent_version: str | None
    records: list[dict[str, Any]]
    checksum: str = ""

    def __post_init__(self) -> None:
        if not self.checksum:
            self.checksum = digest(self.records)


@dataclass
class QAThresholds:
    max_duplicate_rate: float = 0.20
    max_contamination_rate: float = 0.0
    min_records: int = 1
    dev_fraction: float = 0.1
    test_fraction: float = 0.1
    max_tokens: int = 4096


# --- curation helpers (§19) ------------------------------------------------------------


def exact_key(rec: dict[str, Any]) -> str:
    """Canonicalized text + tool sequence + artifact hashes."""
    return digest(
        {
            "text": _norm(json.dumps(rec.get("turns", []), sort_keys=True)),
            "tools": [t.get("name") for t in rec.get("tool_calls", [])],
            "artifacts": rec.get("lineage", {}).get("source_hashes", []),
        }
    )


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def shingles(text: str, k: int = 5) -> set[str]:
    toks = _norm(text).split()
    if len(toks) < k:
        return {" ".join(toks)} if toks else set()
    return {" ".join(toks[i : i + k]) for i in range(len(toks) - k + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def record_text(rec: dict[str, Any]) -> str:
    return " ".join(str(t.get("text", "")) for t in rec.get("turns", []))


def near_duplicate(a: dict[str, Any], b: dict[str, Any], threshold: float = 0.8) -> bool:
    return jaccard(shingles(record_text(a)), shingles(record_text(b))) >= threshold


def benchmark_fingerprints(items: list[str]) -> set[str]:
    return {hashlib.sha256(_norm(s).encode()).hexdigest() for s in items}


def contaminated(rec: dict[str, Any], fingerprints: set[str], bench_shingles: list[set[str]]) -> bool:
    text = record_text(rec)
    if hashlib.sha256(_norm(text).encode()).hexdigest() in fingerprints:
        return True
    sh = shingles(text)
    return any(jaccard(sh, bs) >= 0.5 for bs in bench_shingles)


# --- the pipeline (§18) -------------------------------------------------------------------


@dataclass
class PipelineResult:
    ok: bool
    report: dict[str, Any]
    manifest: dict[str, Any] | None = None
    shards: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def run_pipeline(
    sources: list[Source],
    *,
    consent_ledger: dict[str, dict[str, Any]],
    deletion_holds: set[str],
    benchmark_items: list[str],
    thresholds: QAThresholds | None = None,
    pipeline_commit: str = "unknown",
    seed: str = "dottie-loop",
) -> PipelineResult:
    """Run the hard-block chain. ``ok=False`` means a diagnostic only, no manifest."""
    th = thresholds or QAThresholds()
    failures: list[str] = []
    counts: dict[str, int] = dict.fromkeys(BUCKETS, 0)
    per_source: dict[str, dict[str, int]] = {}

    # acquire: license + consent known, checksum stable
    for s in sources:
        if s.license not in KNOWN_LICENSES:
            failures.append(f"source {s.id}: unknown license {s.license!r}")
        if s.license == "private-opt-in" and not s.consent_version:
            failures.append(f"source {s.id}: private source without consent version")
        if s.checksum != digest(s.records):
            failures.append(f"source {s.id}: checksum drifted")
    raw = [(s, r) for s in sources for r in s.records]
    counts_raw = len(raw)
    if counts_raw < th.min_records:
        failures.append(f"only {counts_raw} raw records (< {th.min_records})")

    eligible: list[dict[str, Any]] = []
    redaction_totals: dict[str, int] = {}
    for s, rec in raw:
        ps = per_source.setdefault(s.id, dict.fromkeys(BUCKETS, 0))
        # consent
        elig = export_eligibility(rec, consent_ledger=consent_ledger, deletion_holds=deletion_holds)
        if not elig["eligible"] and any("consent" in r or "deletion" in r or "purpose" in r for r in elig["reasons"]):
            counts["excluded_consent"] += 1
            ps["excluded_consent"] += 1
            continue
        # redact (into a new object, never in place)
        red, rep = redact_record(rec)
        for k, v in rep.items():
            redaction_totals[k] = redaction_totals.get(k, 0) + v
        if rec.get("data_class") == "P3" or rep.get("keyish", 0) or rep.get("secret", 0):
            # a secret detector hit is quarantined metadata only — never trained
            counts["excluded_privacy"] += 1
            ps["excluded_privacy"] += 1
            continue
        # validate + qualify
        if not elig["eligible"]:
            counts["invalid"] += 1
            ps["invalid"] += 1
            continue
        if not red.get("turns"):
            counts["invalid"] += 1
            ps["invalid"] += 1
            continue
        red["_source"] = s.id
        eligible.append(red)

    # curate: exact + near dedupe, contamination
    seen: dict[str, str] = {}
    curated: list[dict[str, Any]] = []
    for rec in eligible:
        ps = per_source[rec["_source"]]
        k = exact_key(rec)
        if k in seen or any(near_duplicate(rec, c) for c in curated):
            counts["deduplicated"] += 1
            ps["deduplicated"] += 1
            continue
        seen[k] = rec["trace_id"]
        curated.append(rec)
    fps = benchmark_fingerprints(benchmark_items)
    bench_sh = [shingles(b) for b in benchmark_items]
    kept: list[dict[str, Any]] = []
    contaminated_n = 0
    for rec in curated:
        if contaminated(rec, fps, bench_sh):
            contaminated_n += 1
            counts["quarantined"] += 1
            per_source[rec["_source"]]["quarantined"] += 1
            continue
        kept.append(rec)
    if not kept:
        failures.append("no eligible records survive consent/privacy/validation/curation; nothing to release")
    dup_rate = counts["deduplicated"] / max(1, len(eligible))
    if dup_rate > th.max_duplicate_rate:
        failures.append(f"duplicate rate {dup_rate:.2f} exceeds {th.max_duplicate_rate}")
    contam_rate = contaminated_n / max(1, len(curated))
    if contam_rate > th.max_contamination_rate:
        failures.append(f"contamination rate {contam_rate:.2f} exceeds {th.max_contamination_rate}")

    # split: grouped by session, then temporal; never split turns of one session
    groups: dict[str, list[dict[str, Any]]] = {}
    for rec in kept:
        groups.setdefault(rec.get("session_id", rec["trace_id"]), []).append(rec)
    ordered = sorted(groups.items(), key=lambda kv: (min(r.get("captured_at", "") for r in kv[1]), kv[0]))
    n = len(ordered)
    n_test = int(n * th.test_fraction)
    n_dev = int(n * th.dev_fraction)
    test_groups = ordered[n - n_test :] if n_test else []
    dev_groups = ordered[n - n_test - n_dev : n - n_test] if n_dev else []
    train_groups = ordered[: n - n_test - n_dev]
    splits = {
        "train": [r for _, rs in train_groups for r in rs],
        "validation": [r for _, rs in dev_groups for r in rs],
        "test": [r for _, rs in test_groups for r in rs],
    }
    for name, recs in splits.items():
        counts[name] = len(recs)
        for r in recs:
            per_source[r["_source"]][name] += 1
    if kept and counts["train"] == 0:
        failures.append("no training records after split; a release needs a train split")
    overlap = _overlap_report(splits)
    if overlap["session_overlap"] or overlap["exact_overlap"]:
        failures.append("split isolation failed")

    # pack: token bounds and round-trip
    shards: dict[str, list[dict[str, Any]]] = {}
    for name, recs in splits.items():
        packed = []
        for r in recs:
            toks = _tokenize(record_text(r))
            if len(toks) > th.max_tokens:
                failures.append(f"record {r['trace_id']} exceeds max tokens without lossless packing")
                continue
            packed.append({"trace_id": r["trace_id"], "tokens": toks, "n_tokens": len(toks), "source": r["_source"]})
        shards[name] = packed

    # accounting invariant (§18)
    accounted = sum(counts[b] for b in BUCKETS)
    if accounted != counts_raw:
        failures.append(f"accounting mismatch: raw {counts_raw} != buckets {accounted}")
    for sid, ps in per_source.items():
        src_raw = next(len(s.records) for s in sources if s.id == sid)
        if sum(ps.values()) != src_raw:
            failures.append(f"accounting mismatch for source {sid}")

    report = {
        "schema": "dataset-qa-report-1.0.0",
        "counts": {"raw": counts_raw, **counts, "eligible": len(eligible)},
        "per_source": per_source,
        "redaction": redaction_totals,
        "duplicate_rate": round(dup_rate, 4),
        "contamination_rate": round(contam_rate, 4),
        "overlap": overlap,
        "failures": failures,
        "hard_block": bool(failures),
        "generated_at": now_iso(),
    }
    if failures:
        return PipelineResult(ok=False, report=report, manifest=None, shards={})
    manifest = {
        "schema": active("dataset-manifest"),
        "dataset_id": f"pair-sft-{now_iso()[:10]}.{new_id()[:6]}",
        "sources": [{"id": s.id, "consent_version": s.consent_version, "license": s.license, "checksum": s.checksum} for s in sources],
        "pipeline_commit": pipeline_commit,
        "redaction_version": "redactor-1.0.0",
        "qa_report_hash": digest(report),
        "counts": {"raw": counts_raw, "eligible": len(eligible), "train": counts["train"], "dev": counts["validation"], "test": counts["test"]},
        "splits": {"strategy": "grouped-temporal", "seed": seed},
        "tokenizer": {"id": "whitespace-1.0.0", "hash": digest("whitespace-1.0.0"), "max_length": th.max_tokens},
        "shards": [{"path": f"{name}.jsonl", "sha256": digest(recs), "records": len(recs)} for name, recs in shards.items()],
        "exclusions": {b: counts[b] for b in BUCKETS if b not in ("train", "validation", "test")},
        "trace_ids": sorted(r["trace_id"] for recs in splits.values() for r in recs),
        "approved_by": None,
        "status": "candidate",
        "created_at": now_iso(),
    }
    return PipelineResult(ok=True, report=report, manifest=manifest, shards=shards)


def _tokenize(text: str) -> list[str]:
    return text.split()


def _overlap_report(splits: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    sessions = {k: {r.get("session_id") for r in v} for k, v in splits.items()}
    exact = {k: {exact_key(r) for r in v} for k, v in splits.items()}
    names = list(splits)
    sess_overlap = []
    ex_overlap = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            if sessions[a] & sessions[b]:
                sess_overlap.append((a, b))
            if exact[a] & exact[b]:
                ex_overlap.append((a, b))
    return {"session_overlap": sess_overlap, "exact_overlap": ex_overlap}


# --- release (§20) --------------------------------------------------------------------------


def write_release(result: PipelineResult, out_dir: Path) -> dict[str, Any]:
    """Publish immutable shards + manifest with resolving hashes. Requires ok=True."""
    if not result.ok or result.manifest is None:
        raise UnexecutableError("cannot release: QA hard-blocked", field="manifest")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = dict(result.manifest)
    shard_entries = []
    for name, recs in result.shards.items():
        p = out_dir / f"{name}.jsonl"
        p.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in recs), encoding="utf-8")
        shard_entries.append({"path": p.name, "sha256": file_sha256(p), "records": len(recs)})
    manifest["shards"] = shard_entries
    (out_dir / "qa_report.json").write_text(json.dumps(result.report, indent=1, sort_keys=True), encoding="utf-8")
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return manifest


def approve_manifest(manifest: dict[str, Any], reviewer: str, out_dir: Path | None = None) -> dict[str, Any]:
    """Independent reviewer signs the exact manifest; hashes must resolve first."""
    if out_dir is not None:
        for sh in manifest["shards"]:
            p = Path(out_dir) / sh["path"]
            if not p.exists() or file_sha256(p) != sh["sha256"]:
                raise UnexecutableError(f"shard hash does not resolve: {sh['path']}", "shards")
    if manifest.get("status") == "invalidated":
        raise PolicyDeniedError("manifest was invalidated by a deletion", field="status")
    approved = {**manifest, "approved_by": reviewer, "status": "approved", "approved_at": now_iso()}
    approved["manifest_hash"] = digest({k: v for k, v in approved.items() if k != "manifest_hash"})
    return approved


def consumer_accepts(manifest: dict[str, Any]) -> bool:
    """A consumer rejects an unapproved or hash-incomplete manifest (§37B)."""
    if manifest.get("status") != "approved" or not manifest.get("approved_by"):
        return False
    return all(sh.get("sha256") for sh in manifest.get("shards", []))


# --- deletion propagation (§17) ---------------------------------------------------------------


class Lineage:
    """Tracks trace → manifest → train run → checkpoint lineage for deletion propagation."""

    def __init__(self) -> None:
        self.traces: dict[str, dict[str, Any]] = {}  # trace_id -> {deletion_key, tombstoned}
        self.manifests: dict[str, dict[str, Any]] = {}
        self.train_runs: dict[str, dict[str, Any]] = {}  # run_id -> {dataset_id, checkpoint, contaminated}
        self.receipts: list[dict[str, Any]] = []
        self.holds: dict[str, dict[str, Any]] = {}  # deletion_key -> {kind: legal|deletion, by, at}

    def to_dict(self) -> dict[str, Any]:
        return {"traces": self.traces, "manifests": self.manifests, "train_runs": self.train_runs, "receipts": self.receipts, "holds": self.holds}

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(str(path) + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> Lineage:
        ln = cls()
        if Path(path).exists():
            d = json.loads(Path(path).read_text(encoding="utf-8"))
            for k in ("traces", "manifests", "train_runs", "receipts", "holds"):
                setattr(ln, k, d.get(k, getattr(ln, k)))
        return ln

    def hold(self, deletion_key: str, *, kind: str, by: str) -> dict[str, Any]:
        """Runbook D step 2 (deletion hold blocks export/training) or a legal hold that blocks deletion."""
        if kind not in ("deletion", "legal"):
            raise InvalidInputError("hold kind must be deletion|legal", field="kind")
        rec = {"kind": kind, "by": by, "at": now_iso()}
        self.holds[deletion_key] = rec
        return {"deletion_key_ref": digest(deletion_key)[:16], **rec}

    def exportable(self, trace_id: str) -> bool:
        m = self.traces.get(trace_id)
        return bool(m) and not m["tombstoned"] and m["deletion_key"] not in self.holds

    def register_trace(self, trace_id: str, deletion_key: str) -> None:
        self.traces[trace_id] = {"deletion_key": deletion_key, "tombstoned": False}

    def register_manifest(self, manifest: dict[str, Any]) -> None:
        self.manifests[manifest["dataset_id"]] = manifest

    def register_train_run(self, run_id: str, dataset_id: str, checkpoint: str) -> None:
        self.train_runs[run_id] = {"dataset_id": dataset_id, "checkpoint": checkpoint, "contaminated": False}

    def promotable(self, checkpoint: str) -> bool:
        return not any(r["checkpoint"] == checkpoint and r["contaminated"] for r in self.train_runs.values())

    def delete(self, deletion_key: str, operator: str) -> dict[str, Any]:
        """Steps 1-7 of §17 deletion propagation. Returns a non-sensitive receipt."""
        hold = self.holds.get(deletion_key)
        if hold and hold["kind"] == "legal":
            receipt = {"schema": active("deletion-receipt"), "request_id": new_id("del_"), "subject_ref": digest(deletion_key)[:16], "stores_checked": ["traces", "manifests", "train_runs"], "counts": {"traces_tombstoned": 0, "manifests_invalidated": 0, "train_runs_contaminated": 0}, "affected_dataset_ids": [], "affected_checkpoints": [], "status": "held", "exceptions_under_hold": ["legal hold placed by " + hold["by"]], "operator": operator, "at": now_iso()}
            self.receipts.append(receipt)
            return receipt
        trace_ids = [t for t, m in self.traces.items() if m["deletion_key"] == deletion_key]
        for t in trace_ids:
            self.traces[t]["tombstoned"] = True
        affected_manifests = [m["dataset_id"] for m in self.manifests.values() if set(m.get("trace_ids", [])) & set(trace_ids)]
        for d in affected_manifests:
            self.manifests[d]["status"] = "invalidated"
        affected_runs = [r for r, m in self.train_runs.items() if m["dataset_id"] in affected_manifests]
        for r in affected_runs:
            self.train_runs[r]["contaminated"] = True
        receipt = {
            "schema": active("deletion-receipt"),
            "request_id": new_id("del_"),
            "subject_ref": digest(deletion_key)[:16],
            "stores_checked": ["traces", "manifests", "train_runs"],
            "counts": {"traces_tombstoned": len(trace_ids), "manifests_invalidated": len(affected_manifests), "train_runs_contaminated": len(affected_runs)},
            "affected_dataset_ids": affected_manifests,
            "affected_checkpoints": [self.train_runs[r]["checkpoint"] for r in affected_runs],
            "status": "complete",
            "exceptions_under_hold": [],
            "operator": operator,
            "at": now_iso(),
        }
        self.receipts.append(receipt)
        return receipt


def canary_deletion_test(lineage: Lineage, manifest: dict[str, Any]) -> dict[str, Any]:
    """Runbook B step 16: prove deletion propagates on a NON-production canary record
    before the release is marked usable. Runs on a deep copy; the real lineage is untouched."""
    probe = copy.deepcopy(lineage)
    canary_trace = new_id("trc_canary_")
    canary_key = new_id("del_canary_")
    probe.register_trace(canary_trace, canary_key)
    m = {**manifest, "trace_ids": [*manifest.get("trace_ids", []), canary_trace]}
    probe.register_manifest(m)
    probe.register_train_run(new_id("run_canary_"), m["dataset_id"], checkpoint="ckpt_canary_probe")
    receipt = probe.delete(canary_key, operator="canary-deletion-test")
    ok = (
        receipt["status"] == "complete"
        and receipt["counts"]["traces_tombstoned"] == 1
        and m["dataset_id"] in receipt["affected_dataset_ids"]
        and not probe.promotable("ckpt_canary_probe")
        and lineage.to_dict() != probe.to_dict()
    )
    return {"ok": ok, "dataset_id": m["dataset_id"], "canary_trace_ref": digest(canary_trace)[:12], "receipt_status": receipt["status"], "promotion_blocked": not probe.promotable("ckpt_canary_probe"), "at": now_iso()}


def mark_release_usable(manifest: dict[str, Any], proof: dict[str, Any]) -> dict[str, Any]:
    """A release is usable only after approval AND a passing canary deletion proof for THIS manifest."""
    if manifest.get("status") != "approved":
        raise UnexecutableError("only an approved manifest can be marked usable", "status")
    if not proof.get("ok") or proof.get("dataset_id") != manifest.get("dataset_id"):
        raise UnexecutableError("canary deletion proof missing, failed, or for another dataset", "deletion_proof")
    return {**manifest, "usable": True, "deletion_proof": {k: proof[k] for k in ("canary_trace_ref", "receipt_status", "promotion_blocked", "at")}}
