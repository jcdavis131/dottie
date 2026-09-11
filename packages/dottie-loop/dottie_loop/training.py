"""Training execution contract (spec §21, §21.1, §37B TrainRun).

Every run is fully specified before a GPU starts. :func:`preflight` evaluates the
ten preflight checks and returns a typed verdict; a single failure blocks the run.
:func:`resume_run` enforces the resume rule; :func:`fork_run` links a deliberate
change by ``forked_from``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dottie_loop.dataset import consumer_accepts
from dottie_loop.errors import BlockedError, InvalidInputError
from dottie_loop.hashing import digest, new_id, now_iso
from dottie_loop.schema import active

OBJECTIVES = frozenset({"sft", "grpo", "router"})
#: §21.1 runtime telemetry: every record carries these; heartbeats are a separate, cheaper stream
TELEMETRY_FIELDS = ("run_id", "step", "tokens_seen", "loss_total", "loss_components", "lr", "grad_norm", "throughput", "memory_gb", "data_shard", "selected_distribution", "kl", "reward_components", "checkpoint_write_s", "evaluator_status")
STAGES = ("sft", "selective_replay", "hq_anneal", "grpo")
HARD_STOP_CONDITIONS = (
    "nan_or_inf_loss",
    "unreadable_shard",
    "sample_accounting_mismatch",
    "secret_detector_hit",
    "data_drift_beyond_manifest",
    "checkpoint_corruption",
    "evaluation_unavailable",
)


@dataclass
class TrainRun:
    objective: str
    parent_checkpoint: str
    dataset_manifest: str
    code_commit: str
    tokenizer_hash: str
    model: dict[str, Any]
    optimizer: dict[str, Any]
    batch: dict[str, Any]
    hardware: dict[str, Any]
    budgets: dict[str, float]
    selection: dict[str, Any] = field(default_factory=lambda: {"method": "none", "retain_fraction": 1.0, "coverage_floors": {}})
    anneal: dict[str, Any] = field(default_factory=lambda: {"mixture": None, "start_step": None, "lr_coupling": "coupled"})
    eval_schedule: dict[str, Any] = field(default_factory=lambda: {"smoke_every": 0, "full_at_end": True})
    seed: int = 0
    run_id: str = field(default_factory=lambda: new_id("run_"))
    forked_from: str | None = None
    status: str = "planned"
    schema: str = field(default_factory=lambda: active("train-run"))

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    def config_digest(self) -> str:
        d = self.to_dict()
        for k in ("run_id", "status", "forked_from"):
            d.pop(k, None)
        return digest(d)


def validate_train_run(run: TrainRun) -> None:
    if run.objective not in OBJECTIVES:
        raise InvalidInputError(f"objective must be one of {sorted(OBJECTIVES)}", "objective")
    if run.selection.get("method") not in ("none", "excess_loss"):
        raise InvalidInputError("selection.method must be none|excess_loss", "selection")
    for k in ("max_steps", "max_hours", "max_cost"):
        if k not in run.budgets or float(run.budgets[k]) <= 0:
            raise InvalidInputError(f"budgets.{k} must be explicit and positive", "budgets")
    if not run.eval_schedule.get("full_at_end"):
        raise InvalidInputError("terminal full held-out suite is required", "eval_schedule")
    if run.batch.get("global") != run.batch.get("micro", 0) * run.batch.get("grad_accum", 0):
        raise InvalidInputError("batch.global must equal micro * grad_accum", "batch")


@dataclass
class PreflightInputs:
    manifest: dict[str, Any]
    split_overlap_zero: bool
    tokenizer_roundtrip_ok: bool
    checkpoint_loads: bool
    hardware_ok: bool
    storage_gb_free: float
    storage_gb_needed: float
    metrics_sink_writable: bool
    cancellation_tested: bool
    baseline_eval_fresh: bool


def preflight(run: TrainRun, inp: PreflightInputs) -> dict[str, Any]:
    """The ten §21.1 checks. All must pass; failures are named."""
    validate_train_run(run)
    checks = {
        "manifest_approved_and_hashes_resolve": consumer_accepts(inp.manifest) and inp.manifest.get("dataset_id") == run.dataset_manifest,
        "split_overlap_zero": inp.split_overlap_zero,
        "tokenizer_roundtrip": inp.tokenizer_roundtrip_ok,
        "checkpoint_and_optimizer_load": inp.checkpoint_loads,
        "hardware_satisfies_requirements": inp.hardware_ok,
        "storage_fits_with_margin": inp.storage_gb_free >= inp.storage_gb_needed * 1.2,
        "metrics_sink_and_heartbeat_writable": inp.metrics_sink_writable,
        "cancellation_and_checkpoint_on_signal_tested": inp.cancellation_tested,
        "baseline_eval_bundle_fresh": inp.baseline_eval_fresh,
        "cost_and_time_ceilings_explicit": all(float(run.budgets.get(k, 0)) > 0 for k in ("max_steps", "max_hours", "max_cost")),
    }
    failed = [k for k, v in checks.items() if not v]
    return {"ok": not failed, "checks": checks, "failed": failed, "run_id": run.run_id, "at": now_iso()}


def validate_telemetry(rec: dict[str, Any]) -> None:
    """A telemetry record with a missing field is invalid, not partially useful."""
    missing = [f for f in TELEMETRY_FIELDS if f not in rec]
    if missing:
        raise InvalidInputError(f"telemetry missing {missing}", field="telemetry")


def stop_condition_for(rec: dict[str, Any], *, manifest_shards: set[str] | None = None) -> str | None:
    """Map one telemetry record to the §21.1 hard-stop condition it triggers, if any."""
    validate_telemetry(rec)
    loss = rec["loss_total"]
    if not isinstance(loss, int | float) or loss != loss or loss in (float("inf"), float("-inf")):
        return "nan_or_inf_loss"
    if rec.get("shard_error"):
        return "unreadable_shard"
    dist = rec["selected_distribution"] or {}
    if dist and rec.get("samples_expected") is not None and sum(dist.values()) != rec["samples_expected"]:
        return "sample_accounting_mismatch"
    if rec.get("secret_detector_hits", 0):
        return "secret_detector_hit"
    if manifest_shards is not None and rec["data_shard"] not in manifest_shards:
        return "data_drift_beyond_manifest"
    if rec.get("checkpoint_hash_ok") is False:
        return "checkpoint_corruption"
    if rec["evaluator_status"] == "unavailable":
        return "evaluation_unavailable"
    return None


@dataclass
class HeartbeatMonitor:
    """Heartbeats separate from verbose logs so a hang is detectable cheaply."""

    interval_s: float
    misses_allowed: int = 3
    last_at: float | None = None
    count: int = 0

    def beat(self, at: float) -> None:
        if self.last_at is not None and at < self.last_at:
            raise InvalidInputError("heartbeat time went backwards", field="at")
        self.last_at = at
        self.count += 1

    def hang(self, now: float) -> dict[str, Any]:
        if self.last_at is None:
            return {"hung": self.count == 0 and now > self.interval_s * self.misses_allowed, "reason": "no heartbeat yet", "silent_s": now}
        silent = now - self.last_at
        return {"hung": silent > self.interval_s * self.misses_allowed, "reason": "heartbeat silent", "silent_s": round(silent, 3), "budget_s": self.interval_s * self.misses_allowed}


def hard_stop(condition: str) -> dict[str, Any]:
    if condition not in HARD_STOP_CONDITIONS:
        raise InvalidInputError(f"unknown stop condition {condition!r}", "condition")
    return {"action": "hard_stop", "condition": condition, "at": now_iso()}


def oom_retry(run: TrainRun, new_micro: int) -> TrainRun:
    """OOM may retry ONCE with an explicitly revised batch plan that changes the manifest."""
    if run.forked_from is not None:
        raise BlockedError("OOM already retried once; a second retry is a human decision", "oom_retry")
    forked = fork_run(run, reason="oom_retry")
    forked.batch = {**run.batch, "micro": new_micro, "grad_accum": run.batch["grad_accum"], "global": new_micro * run.batch["grad_accum"]}
    forked.batch["revised_from"] = run.batch.get("global")
    return forked


def resume_run(run: TrainRun, *, checkpoint_verified: bool, recorded_config_digest: str) -> dict[str, Any]:
    """Resume only from a verified checkpoint with the EXACT recorded configuration."""
    if not checkpoint_verified:
        raise BlockedError("checkpoint not verified", dependency="checkpoint")
    if recorded_config_digest != run.config_digest():
        raise BlockedError("configuration differs from the recorded run; fork instead", "config")
    return {"resumed": run.run_id, "at": now_iso()}


def fork_run(run: TrainRun, reason: str) -> TrainRun:
    d = run.to_dict()
    d["run_id"] = new_id("run_")
    d["forked_from"] = run.run_id
    d["status"] = "planned"
    forked = TrainRun(**d)
    forked.hardware = {**forked.hardware, "fork_reason": reason}
    return forked


def reproducibility_check(run_a: TrainRun, run_b: TrainRun, metrics_a: dict[str, float], metrics_b: dict[str, float], *, tolerance: float = 0.01) -> dict[str, Any]:
    """ML-07: an independent rerun must resolve identical inputs and produce compatible metrics.

    Identical inputs = same config digest (run id and lineage excluded) and same seed.
    Compatible = every shared metric within ``tolerance`` (absolute); a metric present
    on one side only is a finding, not silently ignored.
    """
    if tolerance < 0:
        raise InvalidInputError("tolerance must be non-negative", field="tolerance")
    same_inputs = run_a.config_digest() == run_b.config_digest()
    same_seed = run_a.seed == run_b.seed
    shared = sorted(set(metrics_a) & set(metrics_b))
    only_one_side = sorted(set(metrics_a) ^ set(metrics_b))
    deltas = {k: round(abs(float(metrics_a[k]) - float(metrics_b[k])), 6) for k in shared}
    incompatible = [k for k, d in deltas.items() if d > tolerance]
    ok = same_inputs and same_seed and not incompatible and not only_one_side and bool(shared)
    return {"ok": ok, "same_inputs": same_inputs, "same_seed": same_seed, "deltas": deltas, "incompatible": incompatible, "metrics_on_one_side_only": only_one_side, "tolerance": tolerance, "runs": [run_a.run_id, run_b.run_id], "at": now_iso()}
