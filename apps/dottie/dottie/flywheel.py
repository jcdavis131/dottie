# Solo personal project, no connection to employer, built with public/free-tier only
"""The Dottie flywheel — the continuous-improvement surface, honestly gated.

Four real operations over real artifacts, each returning structured results with real
counts/paths (never invented metrics), each refusing honestly when its inputs are absent:

  * :func:`export_rft_dataset` — dottie traces -> the scout-cli RFT ETL's audit.jsonl input
    shape -> the REAL ETL (``apps/scout-cli/bigbang/plugins/rft/etl.py``) -> versioned RFT
    dataset JSONL.
  * :func:`mint_memories` — completed task traces -> ava-skills memory-mint (real pipeline:
    bounded queue, async worker, ShardMemo-scoped shards on disk).
  * :func:`evaluate` — real subprocess run of the ava-open-harness gate
    (``python -m harness run``); returns the real report paths + parsed meta.
  * :func:`train_step` — real subprocess run of the factory's proven
    ``scripts/rl_smoke_update.py`` (rollout -> reward -> ONE real GRPO update), refusing
    honestly when no checkpoint tree or no torch exists.

Gating philosophy: :class:`FlywheelUnavailable` = a prerequisite is absent (caller can fix it);
:class:`FlywheelError` = the real operation ran and failed (stderr/stdout excerpts included).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from dottie import resolve
from dottie.engine import DottieEngine


class FlywheelUnavailable(RuntimeError):
    """A flywheel stage's prerequisite is honestly absent (traces, checkpoint, torch, sibling)."""


class FlywheelError(RuntimeError):
    """A flywheel stage ran for real and failed; the message carries the true cause."""


# ---------------------------------------------------------------------------
# Module loading helpers (file-path imports, registered in sys.modules first —
# the memory-mint skill itself documents why registration must precede exec).
# ---------------------------------------------------------------------------

def _load_module_from_path(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging error
        raise FlywheelUnavailable(f"cannot load module from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return mod


def _require_traces(engine: DottieEngine) -> List[Dict[str, Any]]:
    traces = list(engine.iter_traces())
    if not traces:
        raise FlywheelUnavailable(
            f"no dottie traces at {engine.traces_path} — run tasks first "
            "(POST /tasks or `python -m dottie run ...`); the flywheel never invents data."
        )
    return traces


# ---------------------------------------------------------------------------
# (a) traces -> RFT dataset via the REAL scout-cli ETL
# ---------------------------------------------------------------------------

def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _trace_to_audit_events(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One dottie trace -> audit.jsonl-shaped events (the ETL's canonical input).

    Timestamps are the REAL task timestamp advanced by each step's REAL measured wall_ms;
    step status mirrors the real sandbox outcome; a terminal ``codeact.final`` event carries
    whether the episode really reached a FINAL (feeds the ETL's r_task_terminal_ok)."""
    events: List[Dict[str, Any]] = []
    ts = float(record["ts"])
    backend = record.get("backend", "unknown")
    for i, step in enumerate(record.get("steps", [])):
        events.append({
            "ts": _iso(ts),
            "command": f"codeact.{backend}.step",
            "args": {
                "task_id": record["task_id"],
                "step": i,
                "code": str(step.get("code", ""))[:400],
                "tools": [c.get("tool") for c in step.get("tool_calls", [])],
            },
            "status": "ok" if step.get("ok") else "error",
            "duration_ms": int(step.get("wall_ms") or 0),
        })
        ts += (float(step.get("wall_ms") or 0)) / 1000.0
    events.append({
        "ts": _iso(ts),
        "command": f"codeact.{backend}.final",
        "args": {"task_id": record["task_id"], "terminated": record.get("terminated")},
        "status": "ok" if record.get("reached_final") else "error",
        "duration_ms": 0,
    })
    return events


def export_rft_dataset(
    data_dir: Optional[str | Path] = None, *, gap_seconds: float = 300.0
) -> Dict[str, Any]:
    """Convert dottie traces into the ETL's audit shape and run the REAL scout-cli ETL.

    Returns the ETL's own summary (schema_version, episodes, records_written, drops, out path)
    plus the real input counts. Episode segmentation is the ETL's real behavior (idle-gap
    based), so tasks run close together can legitimately share an episode."""
    engine = DottieEngine(data_dir)
    traces = _require_traces(engine)
    try:
        etl_path = resolve.rft_etl_path()
    except resolve.DottieResolutionError as e:
        raise FlywheelUnavailable(str(e)) from e
    etl = _load_module_from_path("dottie_rft_etl", etl_path)

    fly_dir = engine.data_dir / "flywheel"
    fly_dir.mkdir(parents=True, exist_ok=True)
    audit_path = fly_dir / "audit.jsonl"      # derived artifact, rebuilt per export
    out_path = fly_dir / "rft_dataset.jsonl"
    n_events = 0
    with audit_path.open("w", encoding="utf-8") as f:
        for record in traces:
            for event in _trace_to_audit_events(record):
                f.write(json.dumps(event) + "\n")
                n_events += 1
    summary = etl.export_dataset(audit_path, out_path, gap_seconds=gap_seconds)
    return {
        "source_traces": len(traces),
        "audit_events_written": n_events,
        "audit_path": str(audit_path),
        "etl_module": str(etl_path),
        **summary,
    }


# ---------------------------------------------------------------------------
# (b) traces -> memory shards via ava-skills memory-mint (real pipeline)
# ---------------------------------------------------------------------------

def mint_memories(data_dir: Optional[str | Path] = None) -> Dict[str, Any]:
    """Feed completed task traces through the REAL memory-mint pipeline.

    Shards land in ``<data_dir>/memory_shards`` (dottie-local store; the global
    ``AVA_MEMORY_DIR`` store is deliberately not touched). Re-minting the same traces
    dedupes by content hash — the returned stats report minted vs deduped honestly."""
    engine = DottieEngine(data_dir)
    traces = _require_traces(engine)
    try:
        skills = resolve.skills_root()
    except resolve.DottieResolutionError as e:
        raise FlywheelUnavailable(str(e)) from e
    mint = _load_module_from_path(
        "dottie_memory_mint", skills / "skills" / "memory-mint" / "skill.py"
    )

    store_dir = engine.data_dir / "memory_shards"
    store = mint.ShardStore(store_dir)
    captured = 0
    with mint.MemoryMintPipeline(store=store) as pipe:
        for record in traces:
            comps = record.get("reward_components", {})
            metrics = {
                k: float(v) for k, v in comps.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            }
            metrics["n_steps"] = float(record.get("n_steps", 0))
            outcome = (
                (record.get("final") or "")[:300]
                if record.get("reached_final")
                else f"no FINAL (terminated={record.get('terminated')})"
            )
            pipe.capture(mint.TraceEvent(
                source=f"dottie:{record.get('backend', 'unknown')}",
                instruction=str(record.get("prompt", ""))[:500],
                outcome=outcome,
                ok=bool(record.get("reached_final")),
                ts=float(record.get("ts", time.time())),
                branch="base",
                metrics=metrics,
                tags=["dottie", str(record.get("backend", "unknown"))],
            ))
            captured += 1
        flushed = pipe.flush(timeout=10.0)
        stats = dict(pipe.stats)
    if not flushed:
        raise FlywheelError(f"memory-mint flush timed out; stats so far: {stats}")
    return {
        "events_captured": captured,
        "stats": stats,
        "store_dir": str(store_dir),
        "shard_counts": store.counts(),
    }


# ---------------------------------------------------------------------------
# (c) eval gate — real ava-open-harness subprocess
# ---------------------------------------------------------------------------

def evaluate(
    data_dir: Optional[str | Path] = None,
    *,
    mode: str = "mock",
    evals: str = "all",
    ckpt: Optional[str] = None,
    tokenizer: Optional[str] = None,
    timeout_s: float = 900.0,
) -> Dict[str, Any]:
    """Shell out to the REAL harness runner (``python -m harness run``).

    Returns the real report paths and the report's own meta (passed/total/wall_s) — parsed
    from the file the harness wrote, never synthesized. ``mode='real'`` needs a --ckpt (the
    harness itself enforces its anti-mock rules and reports honest failures as data)."""
    engine = DottieEngine(data_dir)
    try:
        hroot = resolve.harness_root()
    except resolve.DottieResolutionError as e:
        raise FlywheelUnavailable(str(e)) from e
    out_dir = engine.data_dir / "reports" / time.strftime("harness_%Y%m%dT%H%M%SZ", time.gmtime())
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "harness", "run",
           "--eval", evals, "--mode", mode, "--out-dir", str(out_dir)]
    if ckpt:
        cmd += ["--ckpt", ckpt]
    if tokenizer:
        cmd += ["--tokenizer", tokenizer]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(hroot) + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("DOTTIE_ROOT", str(resolve.dottie_root()))
    t0 = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=str(hroot), env=env, capture_output=True,
                              text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as e:
        raise FlywheelError(f"harness run exceeded {timeout_s}s: {e}") from e
    wall_s = time.monotonic() - t0
    report_json = out_dir / "branch_eval_results_real.json"
    if proc.returncode != 0 or not report_json.exists():
        raise FlywheelError(
            f"harness run failed (rc={proc.returncode}, report_exists={report_json.exists()}). "
            f"stderr: {proc.stderr[-800:]!s} stdout: {proc.stdout[-400:]!s}"
        )
    with report_json.open(encoding="utf-8") as f:
        meta = json.load(f).get("meta", {})
    return {
        "command": cmd,
        "report_json": str(report_json),
        "report_md": str(out_dir / "REPORT_REAL.md"),
        "meta": {k: meta.get(k) for k in
                 ("mode", "backend", "ckpt", "passed", "total", "wall_s", "factory_available")},
        "wall_s": round(wall_s, 3),
        "stdout_tail": proc.stdout[-600:],
    }


# ---------------------------------------------------------------------------
# (d) train step — the factory's proven GRPO smoke update, honestly gated
# ---------------------------------------------------------------------------

def _default_run_dir() -> Optional[Path]:
    """First factory candidate whose runs/cpu_pilot actually holds a trainable checkpoint."""
    for ckpt in resolve.ava_ckpt_candidates():
        if ckpt.is_file():
            return ckpt.parent.parent  # .../runs/cpu_pilot/<branch>/x.pt -> runs/cpu_pilot
    return None


def train_step(
    *,
    run_dir: Optional[str | Path] = None,
    device: str = "cpu",
    extra_args: Sequence[str] = (),
    timeout_s: float = 3600.0,
) -> Dict[str, Any]:
    """ONE real GRPO update via the factory's ``scripts/rl_smoke_update.py`` subprocess.

    The script does the whole proven chain itself: real checkpoint -> real decode policy ->
    real sandbox rollouts -> real rewards -> one real torch GRPO step -> mechanical-health
    gate -> manifest append. Dottie only wires ``--run-dir``/``--device`` through and refuses
    honestly (before launching anything) when no checkpoint tree or no torch exists.

    NOTE: the smoke checkpoint has zero capability; r_task ~ 0 is the expected honest result.
    This is mechanical training-loop health, not a capability climb."""
    try:
        script = resolve.rl_smoke_update_script()
    except resolve.DottieResolutionError as e:
        raise FlywheelUnavailable(str(e)) from e

    if run_dir is not None:
        run_dir = Path(run_dir)
        has_ckpt = any(
            (run_dir / rel).is_file()
            for rel in ("agentic/agentic_final.pt", "base/base_final.pt")
        )
        if not has_ckpt:
            raise FlywheelUnavailable(
                f"no checkpoint tree under {run_dir} (looked for agentic/agentic_final.pt and "
                "base/base_final.pt) — refusing to launch a train step against nothing. "
                "Produce checkpoints with the factory's scripts/cpu_pilot_e2e.py."
            )
    else:
        run_dir = _default_run_dir()
        if run_dir is None:
            raise FlywheelUnavailable(
                "no checkpoint tree found; probed: "
                + ", ".join(str(p) for p in resolve.ava_ckpt_candidates())
                + ". Run the factory's scripts/cpu_pilot_e2e.py first."
            )
    if importlib.util.find_spec("torch") is None:
        raise FlywheelUnavailable(
            "train_step needs torch (the GRPO update is a real optimizer step); torch is not "
            "installed in this environment."
        )

    cmd = [sys.executable, str(script), "--run-dir", str(run_dir), "--device", device,
           *list(extra_args)]
    env = dict(os.environ)
    env.setdefault("DOTTIE_ROOT", str(resolve.dottie_root()))
    t0 = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=str(script.parent.parent), env=env,
                              capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as e:
        raise FlywheelError(f"train step exceeded {timeout_s}s: {e}") from e
    wall_s = time.monotonic() - t0
    manifest = Path(run_dir) / "MANIFEST.json"
    if not manifest.exists():
        manifest = Path(run_dir) / "MANIFEST_GRPO.json"
    if proc.returncode != 0:
        raise FlywheelError(
            f"rl_smoke_update failed (rc={proc.returncode}). "
            f"stderr: {proc.stderr[-800:]!s} stdout: {proc.stdout[-400:]!s}"
        )
    return {
        "command": cmd,
        "run_dir": str(run_dir),
        "device": device,
        "returncode": proc.returncode,
        "manifest": str(manifest) if manifest.exists() else None,
        "wall_s": round(wall_s, 3),
        "stdout_tail": proc.stdout[-1200:],
        "capability_claim": "none (smoke-scale mechanical health only)",
    }
