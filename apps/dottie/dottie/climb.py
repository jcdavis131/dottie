# Solo personal project, no connection to employer, built with public/free-tier only
"""Dottie hill-climb orchestrator — MEASURED, gated improvement (spec-12 / MAI discipline).

One :func:`run_iteration` = a verified-task batch through the REAL engine (real ``r_task`` /
``rl_return`` from :mod:`dottie.tasks` verifiers + the factory's ``codeact_return``), a
measured scoreboard, real flywheel stages (RFT export + memory mint), optional harness
evaluate and GRPO train-step (both honestly gated), and one append-only record in
``<data_dir>/climb/climb_log.jsonl`` carrying EVERYTHING measured plus the config, the git
SHA, and the policy backend identity (ava: checkpoint sha256; ollama: model name).

Promotion gate (:func:`compare_iterations`) — why per-family tolerance maps the
rank-invariance finding onto task families: the MAI finding warns that a candidate winning
at one point of a ladder can silently lose at another, so verdicts must be rank-invariant
across the ladder, never a single aggregate point. For an assistant policy the "ladder" is
the task-family axis: a policy that lifts the OVERALL success rate by over-fitting some
families while sacrificing another looks like a win on the aggregate and is exactly that
trap. Hence ``promote`` requires BOTH (a) overall success rate strictly improves and (b) no
family regresses beyond the configured tolerance — same seeds base, so the comparison is
paired per (family, seed). Missing/unpaired data NEVER yields promote/hold — the verdict is
an honest ``insufficient``.

EG trend (:func:`eg_trend_verdict`): when >= 2 iterations exist at distinct labeled compute
points (e.g. checkpoint train steps), the factory's ``efficiency_gain.eg_trend`` ladder
verdict is reused through ``ava.rl.codeact_eg_gate`` — the same success->error transform
(``success_to_error``) and the same ``RungLadder``/``codeact_eg_gate`` composition; nothing
is reimplemented here. It refuses honestly without the compute labels or a baseline curve.

Honesty ledger (ANTI-FABRICATION):
  * every scoreboard number is aggregated from the real per-task trace records of THIS batch;
  * "success" is defined as ``r_task == 1.0`` (binary families: exact verify; the graded
    ``constraint`` family: fully satisfied). Partial credit still shows in ``mean_r_task``;
  * token costs: no tokenizer is instrumented for these backends, so the recorded cost is
    measured wall time + sandbox ms + CHARACTER totals, explicitly labeled a char proxy —
    never presented as tokens;
  * flywheel stages run for real; a missing sibling is recorded as an honest
    ``status: unavailable`` with the true reason (a stage that ran and failed raises).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from dottie import flywheel, resolve
from dottie.engine import DottieEngine
from dottie.tasks import VerifiedTaskProvider

CLIMB_SCHEMA_VERSION = "1.0.0"

SUCCESS_DEFINITION = (
    "success = (r_task == 1.0): binary families verify exactly; the graded 'constraint' "
    "family counts as success only when fully satisfied (partial credit appears in "
    "mean_r_task, not success_rate)"
)

TOKEN_COST_NOTE = (
    "no tokenizer is instrumented for these backends; chars_* are measured character "
    "totals used as the cost proxy — they are NOT token counts"
)

RANK_INVARIANCE_NOTE = (
    "per-family no-regression tolerance maps the rank-invariance finding onto task "
    "families: an overall win bought by sacrificing a family is the trap; promote needs "
    "overall improvement AND no family regressing beyond tolerance"
)


class ClimbError(RuntimeError):
    """A climb iteration's infrastructure really failed (not a low score — scores are data)."""


@dataclass(frozen=True)
class ClimbConfig:
    """One iteration's configuration — recorded verbatim in the climb log."""

    families: str = "mixed"          # one family name or 'mixed' (cycles all five)
    n: int = 5                       # tasks per iteration
    seed_base: int = 0               # seeds are seed_base .. seed_base+n-1 (pairing key)
    backend: str = "ollama"
    max_steps: int = 8
    use_skills: bool = False
    evaluate: Optional[str] = None   # None | 'mock' | 'real' — harness gate passthrough
    train_step: bool = False         # real GRPO update via flywheel (checkpoint/torch gated)
    compute: Optional[float] = None  # labeled compute point (e.g. ckpt train steps) for EG
    tolerance: float = 0.05          # per-family regression tolerance for the promotion gate


# ---------------------------------------------------------------------------
# Identity: git SHA + policy backend identity (all really probed, never guessed)
# ---------------------------------------------------------------------------

def git_identity() -> Dict[str, Any]:
    """Real ``git rev-parse`` of the dottie monorepo root; honest null when not a repo."""
    root = resolve.dottie_root()
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                             text=True, timeout=10)
        if sha.returncode != 0:
            return {"sha": None, "note": f"git rev-parse failed: {sha.stderr.strip()[:200]}"}
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                               capture_output=True, text=True, timeout=10)
        return {
            "sha": sha.stdout.strip(),
            "dirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None,
        }
    except (OSError, subprocess.SubprocessError) as e:
        return {"sha": None, "note": f"git not runnable: {type(e).__name__}: {e}"}


def _sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def policy_identity(backend: str) -> Dict[str, Any]:
    """What exactly generated the turns — resolvable identity per backend, honest otherwise.

    ava: the resolved checkpoint path + its real sha256 (the comparable identity across train
    steps); ollama: server URL + model name; echo: labeled plumbing policy. An injected /
    unknown backend (e.g. a test's scripted solver) is recorded as not resolvable."""
    if backend == "ollama":
        from dottie.policy import OllamaPolicy

        p = OllamaPolicy()
        return {"backend": "ollama", "url": p.base_url, "model": p.model}
    if backend == "ava":
        env_ckpt = os.environ.get("DOTTIE_AVA_CKPT")
        ckpt = Path(env_ckpt) if env_ckpt else resolve.default_ava_ckpt()
        if ckpt is None or not Path(ckpt).is_file():
            return {"backend": "ava", "ckpt": str(ckpt) if ckpt else None,
                    "ckpt_sha256": None,
                    "note": "no ava checkpoint resolvable — identity honestly unknown"}
        return {"backend": "ava", "ckpt": str(ckpt),
                "ckpt_sha256": _sha256_file(Path(ckpt)),
                "ckpt_bytes": Path(ckpt).stat().st_size}
    if backend == "echo":
        return {"backend": "echo", "plumbing_only": True,
                "note": "deterministic CI plumbing policy; never a capability claim"}
    return {"backend": backend,
            "note": "unknown/injected backend — identity not resolvable by dottie"}


# ---------------------------------------------------------------------------
# Scoreboard — pure aggregation over the REAL per-task results
# ---------------------------------------------------------------------------

def _mean(xs: Sequence[float]) -> Optional[float]:
    return round(sum(xs) / len(xs), 4) if xs else None


def build_scoreboard(tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate per-task results (family, r_task, rl_return, wall_s, ...) into the measured
    iteration scoreboard. Pure over its inputs; every number is an aggregate of real values."""
    per_family: Dict[str, Dict[str, Any]] = {}
    for fam in sorted({t["family"] for t in tasks}):
        rows = [t for t in tasks if t["family"] == fam]
        per_family[fam] = {
            "n": len(rows),
            "success_rate": round(sum(1 for t in rows if t["r_task"] == 1.0) / len(rows), 4),
            "mean_r_task": _mean([float(t["r_task"]) for t in rows]),
            "mean_rl_return": _mean([float(t["rl_return"]) for t in rows]),
        }
    n = len(tasks)
    overall = {
        "n": n,
        "success_rate": round(sum(1 for t in tasks if t["r_task"] == 1.0) / n, 4) if n else None,
        "mean_r_task": _mean([float(t["r_task"]) for t in tasks]),
        "mean_rl_return": _mean([float(t["rl_return"]) for t in tasks]),
    }
    cost = {
        "wall_s_total": round(sum(float(t.get("wall_s") or 0.0) for t in tasks), 3),
        "sandbox_ms_total": int(sum(int(t.get("sandbox_ms") or 0) for t in tasks)),
        "steps_total": int(sum(int(t.get("n_steps") or 0) for t in tasks)),
        "chars_code_total": int(sum(int(t.get("chars_code") or 0) for t in tasks)),
        "chars_final_total": int(sum(int(t.get("chars_final") or 0) for t in tasks)),
        "token_note": TOKEN_COST_NOTE,
    }
    return {"overall": overall, "per_family": per_family, "cost": cost,
            "success_definition": SUCCESS_DEFINITION}


def _task_row(rec: Dict[str, Any], family: str, seed: int) -> Dict[str, Any]:
    """Distill one engine trace record into the climb-log per-task row (all real values)."""
    comps = rec.get("reward_components", {})
    steps = rec.get("steps", [])
    return {
        "task_id": rec.get("task_id"),
        "family": family,
        "seed": seed,
        "r_task": comps.get("r_task"),
        "rl_return": comps.get("rl_return"),
        "r_exec": comps.get("r_exec"),
        "r_codeuse": comps.get("r_codeuse"),
        "terminated": rec.get("terminated"),
        "reached_final": rec.get("reached_final"),
        "n_steps": rec.get("n_steps"),
        "wall_s": rec.get("wall_s"),
        "sandbox_ms": int(sum(int(s.get("wall_ms") or 0) for s in steps)),
        "chars_code": int(sum(len(s.get("code") or "") for s in steps)),
        "chars_final": len(rec.get("final") or ""),
    }


# ---------------------------------------------------------------------------
# One iteration
# ---------------------------------------------------------------------------

def _flywheel_stage(fn, *args, **kwargs) -> Dict[str, Any]:
    """Run one real flywheel stage; an absent prerequisite becomes an honest recorded
    refusal (status=unavailable + true reason). A stage that ran and FAILED raises
    (``FlywheelError``) — that is infrastructure failure, not data."""
    try:
        return {"status": "ok", **fn(*args, **kwargs)}
    except flywheel.FlywheelUnavailable as e:
        return {"status": "unavailable", "reason": str(e)}


def climb_log_path(data_dir: Optional[str | Path] = None) -> Path:
    engine = DottieEngine(data_dir)
    return engine.data_dir / "climb" / "climb_log.jsonl"


def run_iteration(config: ClimbConfig, data_dir: Optional[str | Path] = None
                  ) -> Dict[str, Any]:
    """Run ONE climb iteration end-to-end and append its record to the climb log.

    Raises ``DottiePolicyUnavailable`` (backend cannot run), ``ValueError`` (bad config),
    ``FlywheelError`` (a flywheel stage ran and failed) — all honest infrastructure
    failures. Low scores are NOT failures; they are the recorded data."""
    engine = DottieEngine(data_dir)
    provider = VerifiedTaskProvider()
    seeds = list(range(config.seed_base, config.seed_base + config.n))
    pairs = provider.batch_seeds(config.families, config.n, seeds)

    t0 = time.monotonic()
    tasks: List[Dict[str, Any]] = []
    for family, seed in pairs:
        rec = engine.run_task(
            family=family, seed=seed, backend=config.backend,
            max_steps=config.max_steps, use_skills=config.use_skills,
        )
        tasks.append(_task_row(rec, family, seed))

    scoreboard = build_scoreboard(tasks)

    # Flywheel stages — REAL calls. They operate over the data dir's full trace log (the
    # export rebuilds; the mint dedupes previously-minted traces by content hash), which the
    # stage results report honestly.
    fly = {
        "export_rft": _flywheel_stage(flywheel.export_rft_dataset, engine.data_dir),
        "mint": _flywheel_stage(flywheel.mint_memories, engine.data_dir),
        "note": ("stages run over the data dir's full trace log; mint dedupes older traces "
                 "(counts reported by the stage itself)"),
    }

    eval_result: Optional[Dict[str, Any]] = None
    if config.evaluate is not None:
        eval_result = _flywheel_stage(flywheel.evaluate, engine.data_dir, mode=config.evaluate)

    train_result: Optional[Dict[str, Any]] = None
    if config.train_step:
        train_result = _flywheel_stage(flywheel.train_step)

    record: Dict[str, Any] = {
        "schema_version": CLIMB_SCHEMA_VERSION,
        "iteration_id": uuid.uuid4().hex[:12],
        "ts": time.time(),
        "config": asdict(config),
        "git": git_identity(),
        "policy_identity": policy_identity(config.backend),
        "tasks": tasks,
        "scoreboard": scoreboard,
        "flywheel": fly,
        "evaluate": eval_result,
        "train_step": train_result,
        "iteration_wall_s": round(time.monotonic() - t0, 3),
    }

    log_path = climb_log_path(engine.data_dir)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as e:  # pragma: no cover - disk failure
        raise ClimbError(f"could not append climb log {log_path}: {e}") from e
    return record


def read_log(data_dir: Optional[str | Path] = None) -> List[Dict[str, Any]]:
    """All recorded iterations, oldest first (partially-written lines skipped)."""
    path = climb_log_path(data_dir)
    out: List[Dict[str, Any]] = []
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


# ---------------------------------------------------------------------------
# Promotion gate — paired per-family comparison with regression tolerance
# ---------------------------------------------------------------------------

def _insufficient(reason: str) -> Dict[str, Any]:
    return {"verdict": "insufficient", "reason": reason}


def compare_iterations(prev: Optional[Dict[str, Any]], curr: Optional[Dict[str, Any]],
                       *, tolerance: float = 0.05) -> Dict[str, Any]:
    """Paired promotion verdict between two iteration records.

    Pairing precondition: identical task sets — same ``families``/``n``/``seed_base`` (so
    every (family, seed) pair exists in both; backend / skills / max_steps are the treatment
    under comparison). ``promote`` iff overall success rate strictly improves AND no family's
    success rate drops by more than ``tolerance`` (the rank-invariance mapping — see module
    docstring). Anything unpaired or missing is an honest ``insufficient``, never a verdict."""
    if prev is None or curr is None:
        missing = [s for s, r in (("prev", prev), ("curr", curr)) if r is None]
        return _insufficient(
            f"need two iterations to compare; missing: {', '.join(missing)}")
    for label, rec in (("prev", prev), ("curr", curr)):
        if not isinstance(rec.get("scoreboard"), dict) or \
                rec["scoreboard"].get("overall", {}).get("success_rate") is None:
            return _insufficient(f"{label} iteration has no measured scoreboard")
    pc, cc = prev.get("config", {}), curr.get("config", {})
    for key in ("families", "n", "seed_base"):
        if pc.get(key) != cc.get(key):
            return _insufficient(
                f"iterations are not paired: config {key!r} differs "
                f"({pc.get(key)!r} vs {cc.get(key)!r}) — same-seeds pairing is required "
                "before any promote/hold verdict"
            )
    prev_tasks = {(t["family"], t["seed"]): t for t in prev.get("tasks", [])}
    curr_tasks = {(t["family"], t["seed"]): t for t in curr.get("tasks", [])}
    if set(prev_tasks) != set(curr_tasks) or not prev_tasks:
        return _insufficient("iterations do not share an identical (family, seed) task set")

    pf, cf = prev["scoreboard"]["per_family"], curr["scoreboard"]["per_family"]
    if set(pf) != set(cf):
        return _insufficient("per-family scoreboards cover different families")
    per_family: Dict[str, Dict[str, Any]] = {}
    for fam in sorted(pf):
        p_sr, c_sr = pf[fam]["success_rate"], cf[fam]["success_rate"]
        delta = round(c_sr - p_sr, 4)
        per_family[fam] = {
            "prev": p_sr, "curr": c_sr, "delta": delta,
            "regressed_beyond_tolerance": delta < -tolerance,
        }
    p_overall = prev["scoreboard"]["overall"]["success_rate"]
    c_overall = curr["scoreboard"]["overall"]["success_rate"]
    overall_delta = round(c_overall - p_overall, 4)

    wins = sum(1 for k in curr_tasks
               if float(curr_tasks[k]["r_task"]) > float(prev_tasks[k]["r_task"]))
    losses = sum(1 for k in curr_tasks
                 if float(curr_tasks[k]["r_task"]) < float(prev_tasks[k]["r_task"]))
    ties = len(curr_tasks) - wins - losses

    regressed = sorted(f for f, d in per_family.items() if d["regressed_beyond_tolerance"])
    reasons: List[str] = []
    if overall_delta <= 0:
        reasons.append(f"overall success rate did not improve (delta {overall_delta:+.4f})")
    if regressed:
        regressed_bits = ", ".join(
            "{} ({:+.4f})".format(f, per_family[f]["delta"]) for f in regressed)
        reasons.append(f"family regression beyond tolerance {tolerance}: {regressed_bits}")
    verdict = "promote" if not reasons else "hold"
    pm = prev["scoreboard"]["overall"].get("mean_rl_return")
    cm = curr["scoreboard"]["overall"].get("mean_rl_return")
    return {
        "verdict": verdict,
        "paired": True,
        "tolerance": tolerance,
        "overall": {"prev": p_overall, "curr": c_overall, "delta": overall_delta},
        "per_family": per_family,
        "paired_tasks": {"n": len(curr_tasks), "wins": wins, "losses": losses, "ties": ties},
        "mean_rl_return": {"prev": pm, "curr": cm,
                           "delta": round(cm - pm, 4) if None not in (pm, cm) else None},
        "reasons": reasons,
        "rank_invariance_note": RANK_INVARIANCE_NOTE,
        "prev_iteration_id": prev.get("iteration_id"),
        "curr_iteration_id": curr.get("iteration_id"),
    }


# ---------------------------------------------------------------------------
# EG trend across compute points — REUSES the factory's machinery, no reimplementation
# ---------------------------------------------------------------------------

def eg_trend_verdict(records: Sequence[Dict[str, Any]],
                     baseline_points: Sequence[Tuple[float, float]],
                     *, error_floor: float = 0.0) -> Dict[str, Any]:
    """Ladder verdict over climb iterations at distinct labeled compute points.

    Reuses (never reimplements) the factory's ``ava.rl.codeact_eg_gate``: each iteration
    carrying a ``config.compute`` label becomes one ``RungLadder`` (candidate success rate =
    that iteration's measured overall success rate) against the caller-supplied baseline
    (compute, success_rate) curve; ``success_to_error`` does the success->error transform and
    ``eg_trend`` applies the rank-invariance promotion rule. Refuses honestly (verdict
    ``insufficient``) when < 2 distinct compute points, no baseline curve, or the EG math is
    undefined for the real numbers (e.g. success at/below the achievable floor)."""
    labeled = [r for r in records
               if isinstance(r.get("config"), dict)
               and r["config"].get("compute") is not None
               and r.get("scoreboard", {}).get("overall", {}).get("success_rate") is not None]
    computes = sorted({float(r["config"]["compute"]) for r in labeled})
    if len(computes) < 2:
        return _insufficient(
            f"need >= 2 iterations at DISTINCT labeled compute points (config.compute); "
            f"have {len(computes)} — refusing to emit a trend verdict from missing data"
        )
    if len(list(baseline_points)) < 2:
        return _insufficient(
            "need a baseline (compute, success_rate) curve with >= 2 points; the trend "
            "verdict is EG vs a baseline scaling curve, which cannot be invented"
        )
    resolve.ensure_factory_on_path()
    from ava.rl.codeact_eg_gate import RungLadder, codeact_eg_gate

    labeled.sort(key=lambda r: float(r["config"]["compute"]))
    ladders = [
        RungLadder(
            rung=f"{r.get('iteration_id', 'iter')}@{float(r['config']['compute']):g}",
            baseline_points=[(float(c), float(s)) for c, s in baseline_points],
            codeact_compute=float(r["config"]["compute"]),
            codeact_success_rate=float(r["scoreboard"]["overall"]["success_rate"]),
        )
        for r in labeled
    ]
    try:
        verdict = codeact_eg_gate(ladders, error_floor=error_floor)
    except ValueError as e:
        return _insufficient(f"EG undefined for the measured numbers: {e}")
    verdict["mode"] = "climb_iterations_vs_baseline"
    verdict["compute_points"] = computes
    return verdict


# ---------------------------------------------------------------------------
# Rendering (CLI) — plain text over the recorded real numbers
# ---------------------------------------------------------------------------

def render_scoreboard(record: Dict[str, Any]) -> str:
    cfg = record.get("config", {})
    sb = record["scoreboard"]
    ident = record.get("policy_identity", {})
    ident_bits = [f"backend={cfg.get('backend')}"]
    if ident.get("model"):
        ident_bits.append(f"model={ident['model']}")
    if ident.get("ckpt_sha256"):
        ident_bits.append(f"ckpt_sha256={ident['ckpt_sha256'][:12]}")
    if ident.get("plumbing_only"):
        ident_bits.append("plumbing_only")
    git = record.get("git", {})
    lines = [
        f"== climb iteration {record.get('iteration_id')}  {' '.join(ident_bits)}  "
        f"families={cfg.get('families')} n={cfg.get('n')} seed_base={cfg.get('seed_base')}  "
        f"git={str(git.get('sha'))[:9]}{'+dirty' if git.get('dirty') else ''} ==",
        f"{'family':<12}{'n':>4}{'success':>10}{'mean_r_task':>13}{'mean_rl_return':>16}",
    ]

    def _row(name: str, d: Dict[str, Any]) -> str:
        return (f"{name:<12}{d['n']:>4}{d['success_rate']:>10.3f}"
                f"{d['mean_r_task']:>13.3f}{d['mean_rl_return']:>16.3f}")

    for fam, d in sb["per_family"].items():
        lines.append(_row(fam, d))
    lines.append(_row("OVERALL", sb["overall"]))
    c = sb["cost"]
    lines.append(
        f"cost: wall {c['wall_s_total']}s, sandbox {c['sandbox_ms_total']}ms, "
        f"steps {c['steps_total']}, chars code={c['chars_code_total']} "
        f"final={c['chars_final_total']} (char proxy, not tokens)"
    )
    for stage in ("export_rft", "mint"):
        s = record.get("flywheel", {}).get(stage, {})
        if s.get("status") == "ok":
            key = "records_written" if stage == "export_rft" else "stats"
            lines.append(f"flywheel {stage}: ok ({key}={s.get(key)})")
        else:
            lines.append(f"flywheel {stage}: unavailable — {s.get('reason', '?')[:160]}")
    for name in ("evaluate", "train_step"):
        s = record.get(name)
        if s is None:
            lines.append(f"{name}: skipped (not requested)")
        elif s.get("status") == "ok":
            detail = s.get("meta") if name == "evaluate" else s.get("capability_claim")
            lines.append(f"{name}: ok ({detail})")
        else:
            lines.append(f"{name}: unavailable — {s.get('reason', '?')[:160]}")
    return "\n".join(lines)


def render_verdict(verdict: Dict[str, Any]) -> str:
    if verdict["verdict"] == "insufficient":
        return f"verdict: INSUFFICIENT — {verdict['reason']}"
    o = verdict["overall"]
    lines = [
        f"verdict vs previous: {verdict['verdict'].upper()} "
        f"(overall {o['prev']:.3f} -> {o['curr']:.3f}, delta {o['delta']:+.4f}; "
        f"tolerance {verdict['tolerance']})",
    ]
    for fam, d in verdict["per_family"].items():
        flag = "  REGRESSED>tol" if d["regressed_beyond_tolerance"] else ""
        lines.append(f"  {fam:<12} {d['prev']:.3f} -> {d['curr']:.3f} ({d['delta']:+.4f}){flag}")
    pt = verdict["paired_tasks"]
    lines.append(f"  paired tasks: {pt['wins']}W/{pt['losses']}L/{pt['ties']}T of {pt['n']}")
    for r in verdict.get("reasons", []):
        lines.append(f"  hold reason: {r}")
    return "\n".join(lines)


def render_report(records: List[Dict[str, Any]], *, tolerance: float = 0.05) -> str:
    """The climb-report table + consecutive paired verdicts over the recorded log."""
    if not records:
        return "no climb iterations recorded yet — run `python -m dottie climb` first"
    lines = [
        f"{'#':>3} {'iteration':<13}{'backend':<10}{'families':<10}{'n':>4}{'seed0':>6}"
        f"{'success':>9}{'mean_rl':>9}{'wall_s':>8}  git",
    ]
    for i, r in enumerate(records):
        cfg, sb = r.get("config", {}), r.get("scoreboard", {})
        ov = sb.get("overall", {})
        git = r.get("git", {})
        sr = ov.get("success_rate")
        mr = ov.get("mean_rl_return")
        lines.append(
            f"{i:>3} {str(r.get('iteration_id')):<13}{str(cfg.get('backend')):<10}"
            f"{str(cfg.get('families')):<10}{cfg.get('n', 0):>4}{cfg.get('seed_base', 0):>6}"
            f"{(f'{sr:.3f}' if sr is not None else 'n/a'):>9}"
            f"{(f'{mr:.3f}' if mr is not None else 'n/a'):>9}"
            f"{str(sb.get('cost', {}).get('wall_s_total', 'n/a')):>8}  "
            f"{str(git.get('sha'))[:9]}{'+dirty' if git.get('dirty') else ''}"
        )
    for i in range(1, len(records)):
        lines.append(f"-- iterations {i - 1} -> {i} --")
        lines.append(render_verdict(
            compare_iterations(records[i - 1], records[i], tolerance=tolerance)))
    return "\n".join(lines)
