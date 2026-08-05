"""Pipeline status helpers for the live dashboard (read-only, cheap)."""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any

from dottie.pipeline.demand import read_demand
from dottie.pipeline.flow import (
    FlowConfig,
    collector_should_pause,
    current_training_phase,
    free_gb,
    pick_target_phase,
    trainer_data_state,
)
from dottie.pipeline.manifest import Manifest

_STATES = (
    "RAW",
    "CLAIMED_CURATE",
    "PACKED",
    "CLAIMED_TRAIN",
    "CONSUMED",
    "DELETED",
    "FAILED",
)

# Human-readable shard lifecycle (dashboard glossary).
_STATE_HELP = {
    "RAW": "Fresh text from miners (collectors). Not tokenized yet.",
    "CLAIMED_CURATE": "A curator worker holds this shard and is cleaning/packing it.",
    "PACKED": "Tokenized & quality-gated; ready for the trainer to claim.",
    "CLAIMED_TRAIN": "Trainer (or sampler) currently reading this shard.",
    "CONSUMED": "Fully read by training; janitor may delete when disk is tight.",
    "DELETED": "Removed from disk after consume/eviction; row kept for audit.",
    "FAILED": "Curator/train gave up (bad data, crash). Investigate if this climbs.",
}

# Trainer silent longer than this ⇒ surface as stale on the dashboard.
# This is a floor only: the effective cutoff adapts to the observed logging
# cadence, because a phase transition (e.g. seq 512 → 1024) can legitimately
# stretch the gap between step events from ~3 min to ~15 min.
_STALE_STEP_S = 180.0
_STALE_MAX_S = 3600.0
_STALE_CADENCE_MULT = 2.5


def _stale_threshold_s(
    run_rows: list[dict[str, Any]],
    all_rows: list[dict[str, Any]] | None = None,
) -> float:
    """Staleness cutoff adapted to the trainer's current step cadence.

    Expected gap between step events = tokens covered per logging interval
    divided by the most recent tok/s. The latest tok/s already reflects a new
    phase's speed right after a transition, when the wall-clock gap between
    the last two rows does not (it straddles the boundary).

    Right after a restart the current run has fewer than two step rows and
    this used to collapse to the 180s floor while a P2 recovery legitimately
    takes ~15 min to its first step event -- a guaranteed false 'Trainer
    stale' banner after every one of the run's dozens of restarts. The
    pre-restart rows are the best available cadence estimate; fall back.
    """
    steps = [r for r in run_rows if r.get("event") == "step"]
    if len(steps) < 2 and all_rows:
        steps = [r for r in all_rows if r.get("event") == "step"]
    expected = None
    if len(steps) >= 2:
        try:
            tok_delta = float(steps[-1].get("tokens") or 0) - float(
                steps[-2].get("tokens") or 0
            )
            tok_s = float(steps[-1].get("tok_s") or 0)
            if tok_delta > 0 and tok_s > 0:
                expected = tok_delta / tok_s
            else:
                expected = float(steps[-1]["ts"]) - float(steps[-2]["ts"])
        except (TypeError, ValueError, KeyError):
            expected = None
    if expected is None or expected <= 0:
        return _STALE_STEP_S
    return min(_STALE_MAX_S, max(_STALE_STEP_S, _STALE_CADENCE_MULT * expected))


def _throttle_state(metrics: list[dict[str, Any]]) -> tuple[bool, str]:
    """Detect a power-throttled GPU from throughput collapse.

    On battery the driver caps this laptop's GPU at ~17-22W and tok/s drops
    ~6x; for three days that state was indistinguishable from a hang (14.5h of
    'silent gaps'). A recent step whose tok/s is far below the phase median is
    throttling, not staleness -- steps ARE landing, just slowly.
    """
    try:
        srows = [r for r in metrics if r.get("event") == "step" and r.get("tok_s")]
        if not srows:
            return False, ""
        phase = srows[-1].get("phase")
        rows = [r for r in srows if r.get("phase") == phase]
        latest = float(rows[-1].get("tok_s") or 0)
        hist = sorted(float(r["tok_s"]) for r in rows[:-1][-20:])
        if latest <= 0 or len(hist) < 3:
            return False, ""
        med = hist[len(hist) // 2]
        if med <= 0 or latest >= 0.4 * med:
            return False, ""
        watts = rows[-1].get("gpu_power_w")
        detail = (
            f"tok/s {latest:.0f} is {latest / med:.0%} of the phase median "
            f"{med:.0f}"
            + (f"; GPU drawing {watts:.0f}W" if watts else "")
            + " — host likely on battery or power-saving. Plug in / set "
            "High Performance to restore ~6x throughput."
        )
        return True, detail
    except (TypeError, ValueError, KeyError):
        return False, ""


_ROUTE_NAMES = ("automatic", "deliberate", "critic", "planner")


def _curriculum(preset: str) -> dict[str, Any] | None:
    """Load phase names / budgets from the preset YAML (best-effort)."""
    try:
        from dottie.config import DottieConfig

        cfg = DottieConfig.load(preset)
    except Exception:
        return None
    phases: list[dict[str, Any]] = []
    cum = 0
    for i, p in enumerate(cfg.phases):
        tok = int(p.tokens or 0)
        short = p.name.split("_", 1)[-1].replace("_", " ") if "_" in p.name else p.name
        phases.append(
            {
                "index": i,
                "name": p.name,
                "short": short,
                "tokens": tok,
                "seq": int(p.seq),
                "rope_base": int(p.rope_base),
                "ntk": float(p.ntk),
                "mix": dict(p.mix),
                "token_start": cum,
                "token_end": cum + tok,
            }
        )
        cum += tok
    out: dict[str, Any] = {
        "tokens_total": int(cfg.training.tokens_total),
        "tokens_per_step": int(cfg.training.tokens_per_step),
        "checkpoint_every_steps": int(cfg.training.checkpoint_every_steps),
        "metrics_every_steps": int(cfg.training.metrics_every_steps),
        "lr_max": float(cfg.training.wsd.lr_max),
        "lr_min": float(cfg.training.wsd.lr_min),
        "warmup_steps": int(cfg.training.wsd.warmup_steps),
        "phases": phases,
    }
    tpp_tgt = cfg.training.tokens_per_param_target
    if tpp_tgt is not None:
        out["tokens_per_param_target"] = float(tpp_tgt)
    return out


def _objective(preset: str) -> dict[str, Any] | None:
    """Static loss-formula weights/targets for the dashboard's equation card.

    Mirrors ava/jlosses.py's ``loss = lm + (...)*j_weight + half_life*hl_weight
    + inter_mi*w + routing_KL*w`` — read once from the preset YAML so the
    dashboard can label the aux-loss small multiples with the same numbers
    the trainer is actually optimizing against.
    """
    try:
        from dottie.config import DottieConfig

        cfg = DottieConfig.load(preset)
    except Exception:
        return None
    j = cfg.jspace
    return {
        "grad_clip": float(cfg.training.optimizer.grad_clip),
        "j_weight": dict(j.j_weight),
        "base_loss_weights": dict(j.base_loss_weights),
        "hl_weight": dict(j.hl_weight),
        "half_life_target": dict(j.half_life),
        "inter_mi_weight": float(j.inter_mi_weight),
        "inter_mi_cos_target": float(j.inter_mi_cos_target),
        "routing_weight": float(j.routing_weight),
    }


def _watch(
    last_step: dict[str, Any] | None,
    *,
    curriculum: dict[str, Any] | None,
    trainer_phase: int,
    series: dict[str, list[Any]],
) -> dict[str, Any]:
    """Operator tidbits for watching / evaluating a live run."""
    out: dict[str, Any] = {
        "dominant_route": None,
        "route_entropy": None,
        "j_aux_share": None,
        "lm_vs_total": None,
        "phase_progress": None,
        "run_progress": None,
        "steps_to_ckpt": None,
        "lm_delta_10": None,
        "grad_vs_clip": None,
        "hints": [],
    }
    if not last_step:
        out["hints"].append("No step metrics yet — waiting for trainer.")
        return out

    routes = last_step.get("route_probs") or []
    if isinstance(routes, list) and routes:
        probs = [float(x) for x in routes]
        dom_i = max(range(len(probs)), key=lambda i: probs[i])
        name = _ROUTE_NAMES[dom_i] if dom_i < len(_ROUTE_NAMES) else f"r{dom_i}"
        out["dominant_route"] = {"name": name, "p": round(probs[dom_i], 4)}
        # Shannon entropy (nats → bits)
        ent = 0.0
        for p in probs:
            if p > 1e-12:
                ent -= p * math.log(p, 2)
        out["route_entropy"] = round(ent, 3)
        if probs[dom_i] > 0.75:
            out["hints"].append(
                f"Route collapsed toward {name} ({probs[dom_i]:.0%}) — check task mix."
            )
        if ent < 1.0:
            out["hints"].append("Low route entropy — router may be under-exploring.")

    lm = last_step.get("lm_loss", last_step.get("lm"))
    total = last_step.get("total")
    if lm is not None and total is not None and float(total) > 1e-9:
        lm_f, tot_f = float(lm), float(total)
        out["lm_vs_total"] = {"lm": round(lm_f, 4), "total": round(tot_f, 4)}
        aux = max(0.0, tot_f - lm_f)
        out["j_aux_share"] = round(aux / tot_f, 3)
        if out["j_aux_share"] > 0.5:
            out["hints"].append("J-aux >50% of total loss — LM signal diluted.")
        if lm_f < 0.05:
            out["hints"].append(
                "lm very low — possible memorization / easy batch; watch val later."
            )

    losses = [v for v in (series.get("lm_loss") or []) if v is not None]
    if len(losses) >= 2:
        # Compare last point to ~10 steps earlier in the current-run series.
        prev = losses[max(0, len(losses) - 2)]
        out["lm_delta_10"] = round(float(losses[-1]) - float(prev), 4)
        if out["lm_delta_10"] > 0.05:
            out["hints"].append(
                "lm rising vs prior log — demand may request more examples."
            )

    gnorm = last_step.get("grad_norm")
    if gnorm is not None:
        out["grad_vs_clip"] = round(float(gnorm), 3)
        if float(gnorm) > 5.0:
            out["hints"].append(
                f"grad_norm {float(gnorm):.1f} high — instability risk."
            )

    tokens_done = last_step.get("tokens")
    step = last_step.get("step")
    if curriculum and tokens_done is not None:
        total_tok = int(curriculum.get("tokens_total") or 0)
        if total_tok > 0:
            out["run_progress"] = {
                "tokens_done": int(tokens_done),
                "tokens_total": total_tok,
                "frac": round(min(1.0, int(tokens_done) / total_tok), 4),
            }
        phases = curriculum.get("phases") or []
        if 0 <= trainer_phase < len(phases):
            ph = phases[trainer_phase]
            start, end = int(ph["token_start"]), int(ph["token_end"])
            span = max(1, end - start)
            within = max(0, min(span, int(tokens_done) - start))
            out["phase_progress"] = {
                "phase": trainer_phase,
                "name": ph["name"],
                "short": ph["short"],
                "seq": ph["seq"],
                "mix": ph["mix"],
                "tokens_in_phase": within,
                "phase_tokens": span,
                "frac": round(within / span, 4),
                "token_start": start,
                "token_end": end,
            }
        ck_every = int(curriculum.get("checkpoint_every_steps") or 0)
        if ck_every and step is not None:
            out["steps_to_ckpt"] = int(ck_every - (int(step) % ck_every)) % ck_every
            if out["steps_to_ckpt"] == 0:
                out["steps_to_ckpt"] = 0

    mass = last_step.get("verbalizable_mass")
    if mass is not None and float(mass) < 0.1:
        out["hints"].append("verbalizable_mass low — concepts not yet readable.")
    if mass is not None and float(mass) > 0.99:
        out["hints"].append("verbalizable_mass ~1 — check broadcast isn't saturating.")

    if not out["hints"]:
        out["hints"].append("Signals look nominal for this stage.")
    return out


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    ys = sorted(xs)
    mid = len(ys) // 2
    if len(ys) % 2:
        return ys[mid]
    return 0.5 * (ys[mid - 1] + ys[mid])


def _timing_estimate(
    last_step: dict[str, Any] | None,
    *,
    curriculum: dict[str, Any] | None,
    series: dict[str, list[Any]],
    run_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Wall/effective elapsed + ETA from curriculum tokens and recent tok/s.

    ``eta_total_s`` is the estimated wall-clock for the full planned run at the
    current throughput (tokens_total / tok_s). ``eta_remaining_s`` is what's
    left. ``elapsed_effective_s`` is tokens_done / tok_s (downtime-agnostic);
    ``elapsed_wall_s`` is last−first step timestamps in the current run window
    when available (includes idle/crash gaps inside that window).
    """
    if not last_step or not curriculum:
        return None
    tokens_done = last_step.get("tokens")
    tokens_total = int(curriculum.get("tokens_total") or 0)
    tps = int(curriculum.get("tokens_per_step") or 0)
    if tokens_done is None or tokens_total <= 0:
        return None

    tok_samples: list[float] = []
    for v in (series.get("tok_s") or [])[-20:]:
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f > 0:
            tok_samples.append(f)
    last_tok = last_step.get("tok_s")
    if last_tok is not None:
        try:
            lf = float(last_tok)
            if lf > 0 and not tok_samples:
                tok_samples.append(lf)
        except (TypeError, ValueError):
            pass
    tok_s = _median(tok_samples)
    if tok_s is None or tok_s <= 0:
        return None

    done = max(0, int(tokens_done))
    remaining = max(0, tokens_total - done)
    elapsed_eff = done / tok_s
    eta_rem = remaining / tok_s
    eta_tot = tokens_total / tok_s

    elapsed_wall: float | None = None
    rows = run_rows or []
    ts_vals = []
    for row in rows:
        ts = row.get("ts")
        if ts is None:
            continue
        try:
            ts_vals.append(float(ts))
        except (TypeError, ValueError):
            continue
    if len(ts_vals) >= 2:
        elapsed_wall = max(0.0, ts_vals[-1] - ts_vals[0])

    step = last_step.get("step")
    steps_total = max(1, tokens_total // tps) if tps > 0 else None
    steps_done = int(step) if step is not None else None
    steps_remaining = None
    if steps_total is not None and steps_done is not None:
        steps_remaining = max(0, steps_total - steps_done)

    return {
        "tok_s": round(tok_s, 1),
        "tokens_done": done,
        "tokens_total": tokens_total,
        "tokens_remaining": remaining,
        "elapsed_effective_s": round(elapsed_eff, 1),
        "elapsed_wall_s": None if elapsed_wall is None else round(elapsed_wall, 1),
        "eta_remaining_s": round(eta_rem, 1),
        "eta_total_s": round(eta_tot, 1),
        "steps_done": steps_done,
        "steps_total": steps_total,
        "steps_remaining": steps_remaining,
        "basis": "median_tok_s_last_20" if len(tok_samples) > 1 else "last_tok_s",
    }


def _tokens_per_param(
    last_step: dict[str, Any] | None,
    *,
    preset: str,
    curriculum: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Train-to-Test / Chinchilla gauge: tokens seen ÷ analytic param count."""
    if not last_step:
        return None
    tokens = last_step.get("tokens")
    if tokens is None:
        return None
    try:
        from dottie.config import DottieConfig

        n_params = int(DottieConfig.load(preset).analytic_param_count())
    except Exception:
        return None
    if n_params <= 0:
        return None
    tpp = float(tokens) / float(n_params)
    target = None
    if curriculum and curriculum.get("tokens_per_param_target") is not None:
        target = float(curriculum["tokens_per_param_target"])
    else:
        try:
            from dottie.config import DottieConfig

            tgt = DottieConfig.load(preset).training.tokens_per_param_target
            if tgt is not None:
                target = float(tgt)
        except Exception:
            target = None
    chinchilla = 20.0
    if tpp < 15.0:
        regime = "undertrain"
    elif tpp < 40.0:
        regime = "chinchilla-band"
    else:
        regime = "overtrain"
    out: dict[str, Any] = {
        "tokens": int(tokens),
        "params": n_params,
        "tpp": round(tpp, 3),
        "chinchilla_ref": chinchilla,
        "regime": regime,
    }
    if target is not None:
        out["t2t_target"] = target
        out["t2t_frac"] = round(tpp / target, 4) if target > 0 else None
    if regime == "undertrain":
        out["hint"] = (
            "TPP below ~15 — Chinchilla/T2T prefer more unique tokens per param."
        )
    elif regime == "overtrain":
        out["hint"] = "Overtrain regime — good for test-time sampling footprint."
    return out


def _current_run_rows(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = _step_rows(metrics)
    if not rows:
        return []
    start = 0
    prev = int(rows[0]["step"])
    for i in range(1, len(rows)):
        cur = int(rows[i]["step"])
        if cur < prev:
            start = i
        prev = cur
    return rows[start:]


def _reports_dir() -> Path:
    # Provenance-honest chain: Hatch VM vs Docker vs local
    # 1) explicit AVA_REPORTS_DIR
    # 2) DOTTIE_TELEMETRY_DIR / AVA_TELEMETRY_DIR (Dottie factory)
    # 3) repo-root/reports (Hatch workspace)
    env = os.environ.get("AVA_REPORTS_DIR")
    if env and Path(env).exists():
        return Path(env)
    env2 = os.environ.get("DOTTIE_TELEMETRY_DIR") or os.environ.get("AVA_TELEMETRY_DIR")
    if env2 and Path(env2).exists():
        return Path(env2)
    # repo-root discovery: pipeline_status is dottie/pipeline_status.py, reports is ../../reports
    try:
        repo_reports = Path(__file__).resolve().parents[1] / "reports"
        if repo_reports.exists():
            return repo_reports
    except Exception:
        pass
    # fallback original (Docker default /reports)
    return Path("/reports")


def _state_db() -> str:
    return os.environ.get("AVA_STATE_DB", "/state/manifest.db")


def _ckpt_dir() -> Path:
    return Path(os.environ.get("AVA_CKPT_DIR", "/ckpt"))


def _disk_probe_label() -> str:
    env = os.environ.get("AVA_DISK_PROBE")
    if env and Path(env).exists():
        return env
    if Path("/host_disk").exists():
        return "/host_disk"
    return "/"


def _tail_jsonl(
    path: Path, n: int = 120, max_bytes: int = 262_144
) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        # Read the last max_bytes then take the last n lines — cheap for
        # growing files without loading a run's whole history off disk.
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - max_bytes))
            raw = f.read().decode("utf-8", errors="replace")
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        out: list[dict[str, Any]] = []
        for ln in lines[-n:]:
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
        return out
    except OSError:
        return []


def _step_rows(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in metrics:
        if row.get("event") not in (None, "step"):
            if row.get("event") != "step":
                continue
        step = row.get("step")
        loss = row.get("lm_loss", row.get("lm", row.get("total")))
        if step is None or loss is None:
            continue
        rows.append(row)
    return rows


# Scalar fields lifted straight from each metrics-jsonl "step" row into the
# per-run series the dashboard charts. ava/train.py:340-349 is the writer:
# lm/total plus the LossBreakdown aux terms (ava/jlosses.py's loss formula),
# the optimizer/throughput readouts, and the J-space workspace scalars.
_SERIES_FIELDS = (
    "tok_s",
    "grad_norm",
    "lr",
    "report",
    "broadcast",
    "selectivity",
    "modulation",
    "half_life",
    "inter_mi",
    "routing",
    "verbalizable_mass",
    "broadcast_strength",
)


def current_run_series(metrics: list[dict[str, Any]]) -> dict[str, list[Any]]:
    """Keep only the latest contiguous run (drop pre-restart history).

    A restart is detected when ``step`` decreases vs the previous step row.
    """
    empty: dict[str, list[Any]] = {
        "step": [],
        "lm_loss": [],
        "phase": [],
        "total": [],
        **{k: [] for k in _SERIES_FIELDS},
    }
    rows = _step_rows(metrics)
    if not rows:
        return empty

    start = 0
    prev = int(rows[0]["step"])
    for i in range(1, len(rows)):
        cur = int(rows[i]["step"])
        if cur < prev:
            start = i
        prev = cur
    run = rows[start:]

    series: dict[str, list[Any]] = {k: [] for k in empty}
    for row in run:
        series["step"].append(row.get("step"))
        series["lm_loss"].append(row.get("lm_loss", row.get("lm", row.get("total"))))
        series["phase"].append(row.get("phase"))
        series["total"].append(row.get("total"))
        for k in _SERIES_FIELDS:
            series[k].append(row.get(k))
    return series


# Full-history charts render more points than a step-count axis can show
# sanely across restarts (step resets each time), so downsample to this many
# before returning -- keeps the dashboard payload and SVG path length bounded
# on a run that's been going for days, without needing the browser to do it.
_FULL_SERIES_MAX_POINTS = 600


def full_run_series(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    """The whole read window's history, restarts and all -- unlike
    ``current_run_series`` this does NOT drop pre-restart data.

    x-axis for callers should be ``cum_step``, not the raw ``step``: the
    trainer's own step counter resets (or rolls back to the last checkpoint)
    on every restart, so it isn't monotonic across this series the way it is
    within a single ``current_run_series`` window -- plotting raw step here
    would draw a line that jumps backward and self-intersects. ``cum_step``
    instead keeps counting up across restarts (continuing from the last
    cumulative value rather than resetting), so it reads as "total training
    progress" the way an operator actually thinks about it. The original
    ``step`` is still returned alongside for exact correlation with logs, and
    ``ts`` (wall-clock) is returned too for anyone who wants it.

    ``restarts`` is a list of ``{"cum_step": ..., "ts": ...}`` -- both
    coordinate systems, since either might be the active chart axis.
    """
    rows = _step_rows(metrics)  # _step_rows already guarantees step is not None
    keys = ("step", "cum_step", "ts", "lm_loss", "phase", "total", *_SERIES_FIELDS)
    if not rows:
        return {"series": {k: [] for k in keys}, "restarts": []}

    cum_steps: list[int] = []
    restarts: list[dict[str, Any]] = []
    offset = 0
    prev_step: int | None = None
    for row in rows:
        raw = int(row["step"])
        if prev_step is not None and raw < prev_step:
            # Restart: continue counting up from the last cumulative value
            # instead of jumping backward.
            offset = cum_steps[-1] + 1 - raw
            ts = row.get("ts")
            restarts.append(
                {"cum_step": raw + offset, "ts": float(ts) if ts is not None else None}
            )
        cum_steps.append(raw + offset)
        prev_step = raw

    paired = list(zip(rows, cum_steps, strict=False))
    if len(paired) > _FULL_SERIES_MAX_POINTS:
        stride = math.ceil(len(paired) / _FULL_SERIES_MAX_POINTS)
        sampled = paired[::stride]
        if sampled[-1] is not paired[-1]:
            sampled.append(paired[-1])  # always keep the latest point
        paired = sampled

    series: dict[str, list[Any]] = {k: [] for k in keys}
    for row, cum in paired:
        series["step"].append(row.get("step"))
        series["cum_step"].append(cum)
        series["ts"].append(row.get("ts"))
        series["lm_loss"].append(row.get("lm_loss", row.get("lm", row.get("total"))))
        series["phase"].append(row.get("phase"))
        series["total"].append(row.get("total"))
        for k in _SERIES_FIELDS:
            series[k].append(row.get(k))
    return {"series": series, "restarts": restarts}


def _phase_runway(
    tokens_by_phase: dict[str, int],
    *,
    packed_min: int,
    trainer_phase: int,
    target_phase: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in range(6):
        n = int(tokens_by_phase.get(str(p), 0))
        fill = min(1.0, n / packed_min) if packed_min > 0 else 0.0
        out.append(
            {
                "phase": p,
                "tokens": n,
                "packed_min": packed_min,
                "fill": round(fill, 3),
                "ok": n >= packed_min,
                "is_trainer": p == trainer_phase,
                "is_target": p == target_phase,
            }
        )
    return out


def _gates(
    *,
    disk_free: float | None,
    low_water: float,
    raw_bytes: int,
    raw_max: int,
    tokens_by_phase: dict[str, int],
    packed_min: int,
    trainer_phase: int,
    collector_paused: bool,
    by_state: dict[str, int],
) -> list[dict[str, Any]]:
    p_ready = int(tokens_by_phase.get(str(trainer_phase), 0))
    raw_ok = raw_bytes < raw_max
    # Soft quality proxy: active queue not dominated by FAILED.
    failed = int(by_state.get("FAILED", 0))
    active = max(
        1,
        sum(
            int(by_state.get(s, 0))
            for s in (
                "RAW",
                "CLAIMED_CURATE",
                "PACKED",
                "CLAIMED_TRAIN",
                "FAILED",
            )
        ),
    )
    fail_frac = failed / active
    return [
        {
            "id": "D1",
            "name": "host free",
            "ok": disk_free is not None and disk_free >= low_water,
            "value": None if disk_free is None else f"{disk_free:.1f} GB",
            "target": f"≥ {low_water:g} GB",
        },
        {
            "id": "D2",
            "name": f"P{trainer_phase} runway",
            "ok": p_ready >= packed_min,
            "value": f"{p_ready / 1e6:.0f}M tok",
            "target": f"≥ {packed_min / 1e6:.0f}M",
        },
        {
            "id": "D3",
            "name": "collectors",
            "ok": not collector_paused,
            "value": "paused" if collector_paused else "active",
            "target": "not disk-paused",
        },
        {
            "id": "D4",
            "name": "raw headroom",
            "ok": raw_ok,
            "value": f"{raw_bytes / 1e9:.2f} / {raw_max / 1e9:.1f} GB",
            "target": "below raw_max",
        },
        {
            "id": "D5",
            "name": "fail rate",
            "ok": fail_frac < 0.15,
            "value": f"{failed} failed ({fail_frac:.0%})",
            "target": "< 15% of active",
        },
    ]


def _mode(
    *,
    last_step: dict[str, Any] | None,
    starved: bool,
    age_s: float | None,
    stale_after_s: float,
    gates: list[dict[str, Any]],
    recovering: bool = False,
    throttled: bool = False,
    throttle_detail: str = "",
) -> dict[str, Any]:
    """Operator-facing mode: data_prep vs training vs blocked."""
    d1 = next((g for g in gates if g["id"] == "D1"), None)
    disk_bad = d1 is not None and not d1["ok"]
    if disk_bad:
        return {
            "id": "blocked",
            "label": "Disk pressure",
            "detail": "Host free below low-water — collectors pause; free space before data prep.",
        }
    if starved or last_step is None:
        return {
            "id": "data_prep",
            "label": "Data prep",
            "detail": "Building packed runway for the trainer phase (collect → curate → pack).",
        }
    if age_s is not None and age_s > stale_after_s:
        return {
            "id": "stale",
            "label": "Trainer stale",
            "detail": (
                f"No trainer activity for {age_s:.0f}s (> {stale_after_s:.0f}s "
                f"expected at the current phase's cadence) — check GPU / CUDA / "
                f"trainer logs, and whether the host is on battery or asleep."
            ),
        }
    if throttled:
        return {
            "id": "throttled",
            "label": "GPU throttled",
            "detail": throttle_detail or "Throughput far below phase median.",
        }
    if recovering:
        return {
            "id": "recovering",
            "label": "Trainer recovering",
            "detail": (
                "Restarted and resuming from the latest checkpoint; the first "
                "post-resume step event is pending (~10-15 min at P2 cadence)."
            ),
        }
    return {
        "id": "training",
        "label": "Training",
        "detail": "GPU stepping; watch loss, tok/s, runway, and checkpoints.",
    }


def collect_status(preset: str | None = None) -> dict[str, Any]:
    preset = preset or os.environ.get("AVA_PRESET", "nano")
    db = _state_db()
    reports = _reports_dir()
    ckpt = _ckpt_dir()

    by_state = dict.fromkeys(_STATES, 0)
    tokens_by_phase: dict[str, int] = {str(p): 0 for p in range(6)}
    raw_bytes = 0
    tok_sha = None
    total = 0
    manifest_ok = True
    manifest_err = None
    trainer_phase = 0
    target_phase = 0
    pause = {"paused": False, "reason": ""}
    data_state = "UNKNOWN"
    data_detail = ""
    cfg: FlowConfig | None = None

    try:
        cfg = FlowConfig.load()
    except Exception:
        cfg = None

    try:
        with Manifest(db) as m:
            counts = m.counts_by_state()
            for k, v in counts.items():
                by_state[k] = int(v)
            total = sum(by_state.values())
            raw_bytes = int(m.raw_bytes())
            tok_sha = (m.tokenizer_sha() or "")[:12] or None
            for p in range(6):
                tokens_by_phase[str(p)] = int(m.tokens_ready(p))
            trainer_phase = int(current_training_phase(m, preset=preset))
            if cfg is not None:
                target_phase = int(pick_target_phase(m, cfg))
                pr = collector_should_pause(m, cfg, phase=target_phase)
                pause = {"paused": bool(pr.paused), "reason": pr.reason or ""}
                state, detail = trainer_data_state(m, cfg, phase=trainer_phase)
                data_state = state.value
                data_detail = detail
            else:
                target_phase = trainer_phase
    except Exception as e:
        manifest_ok = False
        manifest_err = str(e)

    metrics_path = reports / f"metrics_{preset}.jsonl"
    # Generous enough to cover a run's whole history at typical logging
    # cadence (metrics_every_steps=10 => 8000 rows is ~80k steps); full_series
    # downsamples for the chart anyway, current_run_series only needs the
    # tail since its last restart.
    metrics = _tail_jsonl(metrics_path, 8000, max_bytes=6_000_000)

    latest_ptr = ckpt / "latest"
    latest_target = None
    if latest_ptr.is_file():
        try:
            latest_target = latest_ptr.read_text(encoding="utf-8").strip()
        except OSError:
            latest_target = None

    ckpt_files = []
    if ckpt.is_dir():
        try:
            for p in sorted(
                ckpt.glob("*.pt"), key=lambda x: x.stat().st_mtime, reverse=True
            )[:8]:
                ckpt_files.append(
                    {
                        "name": p.name,
                        "mb": round(p.stat().st_size / (1024 * 1024), 1),
                        "mtime": int(p.stat().st_mtime),
                        "age_s": int(time.time() - p.stat().st_mtime),
                    }
                )
        except OSError:
            pass

    series = current_run_series(metrics)
    full_series = full_run_series(metrics)
    run_rows = _current_run_rows(metrics)

    last_step = run_rows[-1] if run_rows else None
    if last_step is None:
        for row in reversed(metrics):
            if row.get("event") == "step" or ("lm" in row or "lm_loss" in row):
                last_step = row
                break
        if last_step is None and metrics:
            last_step = metrics[-1]
    if last_step and "lm_loss" not in last_step and "lm" in last_step:
        last_step = {**last_step, "lm_loss": last_step["lm"]}

    disk = None
    try:
        disk = round(free_gb("/"), 2)
    except Exception:
        disk = None
    disk_probe = _disk_probe_label()

    starved = False
    for row in metrics[-20:]:
        if row.get("event") == "data_starved":
            starved = True
    if last_step and last_step.get("event") == "data_starved":
        starved = True
    if last_step and last_step.get("event") == "step":
        starved = False
        last_ts = float(last_step.get("ts") or 0)
        for row in metrics[-20:]:
            if (
                row.get("event") == "data_starved"
                and float(row.get("ts") or 0) > last_ts
            ):
                starved = True
                break
    if data_state == "DATA_STARVED":
        starved = True

    # Liveness age: seconds since the trainer emitted ANY event, not just a
    # step. A trainer that logged `resumed` 90s ago is alive and recovering;
    # measuring staleness from the last *step* branded every restart window
    # (model build + resume + first 10 steps, ~15 min at P2) as a hang.
    age_s = None
    for row in reversed(metrics):
        ts = row.get("ts")
        if ts is None:
            continue
        try:
            age_s = max(0.0, time.time() - float(ts))
        except (TypeError, ValueError):
            continue
        break
    # Recovering = restarted and no step yet: the newest step/model_built-ish
    # marker decides. (demand_published/checkpoint rows are skipped -- both
    # follow steps and resumes alike, so they identify neither state.)
    recovering = False
    for row in reversed(metrics):
        ev = row.get("event")
        if ev == "step":
            break
        if ev in (
            "model_built",
            "resumed",
            "phase_enter",
            "branch_forked",
            "trainer_crash",
        ):
            recovering = True
            break
    stale_after_s = _stale_threshold_s(run_rows, all_rows=metrics)
    stale = bool(age_s is not None and age_s > stale_after_s and not starved)
    throttled, throttle_detail = _throttle_state(metrics)

    low_water = float(cfg.low_water_gb) if cfg else 12.0
    packed_min = int(cfg.packed_min_tokens) if cfg else 200_000_000
    raw_max = int(cfg.raw_max_bytes) if cfg else 4_000_000_000
    critical = float(cfg.critical_gb) if cfg else 5.0

    gates = _gates(
        disk_free=disk,
        low_water=low_water,
        raw_bytes=raw_bytes,
        raw_max=raw_max,
        tokens_by_phase=tokens_by_phase,
        packed_min=packed_min,
        trainer_phase=trainer_phase,
        collector_paused=bool(pause.get("paused")),
        by_state=by_state,
    )
    mode = _mode(
        last_step=last_step,
        starved=starved,
        age_s=age_s,
        stale_after_s=stale_after_s,
        gates=gates,
        recovering=recovering,
        throttled=throttled,
        throttle_detail=throttle_detail,
    )
    runway = _phase_runway(
        tokens_by_phase,
        packed_min=packed_min,
        trainer_phase=trainer_phase,
        target_phase=target_phase,
    )

    # Pipeline funnel counts for data-prep view.
    funnel = {
        "raw": int(by_state.get("RAW", 0)),
        "curating": int(by_state.get("CLAIMED_CURATE", 0)),
        "packed": int(by_state.get("PACKED", 0)),
        "training": int(by_state.get("CLAIMED_TRAIN", 0)),
        "consumed": int(by_state.get("CONSUMED", 0)),
        "failed": int(by_state.get("FAILED", 0)),
    }

    demand_snap = read_demand()
    demand_payload = None
    if demand_snap is not None:
        demand_payload = {
            "step": demand_snap.step,
            "trainer_phase": demand_snap.trainer_phase,
            "age_s": round(max(0.0, time.time() - demand_snap.ts), 1),
            "curate_stricter": demand_snap.curate_stricter,
            "boost_task_types": dict(demand_snap.boost_task_types),
            "reasons": list(demand_snap.reasons)[:5],
            "phases": [
                {
                    "phase": p.phase,
                    "tokens_ready": p.tokens_ready,
                    "deficit": p.deficit,
                    "effort": p.effort,
                    "actions": list(p.actions),
                }
                for p in demand_snap.phases
                if p.effort > 0 or p.actions
            ],
        }

    curriculum = _curriculum(preset)
    objective = _objective(preset)
    watch = _watch(
        last_step,
        curriculum=curriculum,
        trainer_phase=trainer_phase,
        series=series,
    )
    timing = _timing_estimate(
        last_step,
        curriculum=curriculum,
        series=series,
        run_rows=run_rows,
    )
    if timing is not None:
        watch["timing"] = timing
    tpp = _tokens_per_param(last_step, preset=preset, curriculum=curriculum)
    if tpp is not None:
        watch["tokens_per_param"] = tpp
        if tpp.get("hint"):
            watch["hints"].append(tpp["hint"])

    return {
        "ts": time.time(),
        "preset": preset,
        "mode": mode,
        "demand": demand_payload,
        "curriculum": curriculum,
        "objective": objective,
        "watch": watch,
        "lifecycle": {
            "states": list(_STATES),
            "help": dict(_STATE_HELP),
            "order": [
                "RAW",
                "CLAIMED_CURATE",
                "PACKED",
                "CLAIMED_TRAIN",
                "CONSUMED",
                "FAILED",
                "DELETED",
            ],
        },
        "manifest": {
            "ok": manifest_ok,
            "error": manifest_err,
            "db": db,
            "total_shards": total,
            "by_state": by_state,
            "funnel": funnel,
            "raw_bytes": raw_bytes,
            "raw_gb": round(raw_bytes / (1024**3), 3),
            "raw_max_gb": round(raw_max / 1e9, 2),
            "raw_fill": round(min(1.0, raw_bytes / raw_max), 3) if raw_max else 0.0,
            "tokenizer_sha": tok_sha,
            "tokens_ready_by_phase": tokens_by_phase,
        },
        "disk_free_gb": disk,
        "disk": {
            "free_gb": disk,
            "probe": disk_probe,
            "low_water_gb": low_water,
            "critical_gb": critical,
            "below_low_water": disk is not None and disk < low_water,
            "below_critical": disk is not None and disk < critical,
        },
        "flow": {
            "trainer_phase": trainer_phase,
            "target_phase": target_phase,
            "data_state": data_state,
            "data_detail": data_detail,
            "collector_pause": pause,
            "packed_min_tokens": packed_min,
            "phase_runway": runway,
            "gates": gates,
        },
        "ckpt": {
            "latest_pointer": latest_target,
            "files": ckpt_files,
        },
        "trainer": {
            "metrics_path": str(metrics_path),
            "n_points": len(metrics),
            "last": last_step,
            "series": series,
            "full_series": full_series["series"],
            "restarts": full_series["restarts"],
            "data_starved": starved,
            "age_s": None if age_s is None else round(age_s, 1),
            "age_basis": "any_trainer_event",
            "recovering": recovering,
            "throttled": throttled,
            "stale": stale,
            "stale_after_s": round(stale_after_s, 1),
            # Every model_built in the metrics window is one trainer process
            # start; the chart-anchored `restarts` (step-counter decreases)
            # undercounts because back-to-back crashes resume from the same
            # checkpoint without a step in between.
            "restarts_window": sum(
                1 for r in metrics if r.get("event") == "model_built"
            ),
        },
        "eval": {
            "json_exists": (
                (reports / "eval_mini_base.json").is_file()
                or (reports / "branch_eval_results_real.json").is_file()
                or Path("/host_reports/eval_mini_base.json").is_file()
                or Path("/app/reports/branch_eval_results_real.json").is_file()
            ),
            "report_html": (reports / "index.html").is_file()
            or Path("/app/reports/index.html").is_file(),
            "active": (
                "eval_mini_base.json"
                if (reports / "eval_mini_base.json").is_file()
                or Path("/host_reports/eval_mini_base.json").is_file()
                else (
                    "branch_eval_results_real.json"
                    if (reports / "branch_eval_results_real.json").is_file()
                    else None
                )
            ),
        },
    }
