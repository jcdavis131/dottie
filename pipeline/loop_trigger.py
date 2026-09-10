#!/usr/bin/env python3
"""loop_trigger.py — closed-loop trigger for continuous Dottie training.

Evaluates production metrics (scoreboard ok_rate, cron health verifier,
eval aggregates) against thresholds from playbooks/closed_loop.yaml and
decides: idle / retrain-queued / canary / promote / rollback / blocked.

SAFETY CONTRACT (hard):
  - NEVER auto-promotes to prod. Promotion requires --approve-prod on the
    command line, and even then only writes a promotion RECORD; the operator
    executes the actual deployment step by hand.
  - Fail-closed: missing or stale metrics -> decision "blocked", exit 2.
  - No synthetic data: every metric is read from committed/real files.
  - Decisions are append-only JSONL audit trail; one LOOP_ALERT line per
    decision goes to stderr so cron logs catch it.

Stdlib only. Usage:
  python3 pipeline/loop_trigger.py --decide [--dry-run]
  python3 pipeline/loop_trigger.py --queue-retrain [--submit-forge]
  python3 pipeline/loop_trigger.py --check-canary
  python3 pipeline/loop_trigger.py --promote --approve-prod
  python3 pipeline/loop_trigger.py --rollback --approve-prod

Exit codes: 0 no-action/cooldown, 1 action taken, 2 blocked (metrics),
3 approval required.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATE_PATH = REPO / "pipeline" / "loop_state.json"
BASELINE_PATH = REPO / "pipeline" / "loop_baseline.json"
DECISIONS_PATH = REPO / "pipeline" / "loop_decisions.jsonl"
QUEUE_DIR = REPO / "pipeline" / "loop_queue" / "pending"
CANARY_PATH = REPO / "pipeline" / "loop_canary.json"


# --------------------------------------------------------------------------
# Minimal YAML-subset parser (flat scalars, nested dicts, scalar lists)
# --------------------------------------------------------------------------
def parse_simple_yaml(path: Path) -> dict:
    """Indent-based subset: nested dicts, scalar values, dash lists."""
    root: dict = {}
    # stack entries: (indent, container, owner_dict, owner_key)
    stack: list[tuple[int, object, dict | None, str | None]] = [(-1, root, None, None)]
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(line) - len(line.lstrip(" "))
            while len(stack) > 1 and indent <= stack[-1][0]:
                stack.pop()
            _, container, owner, okey = stack[-1]
            if stripped.startswith("- "):
                rest = stripped[2:]
                if (isinstance(container, dict) and owner is not None
                        and okey is not None and not container):
                    # placeholder dict for a key whose children are a list
                    new_list: list = []
                    owner[okey] = new_list
                    stack[-1] = (stack[-1][0], new_list, owner, okey)
                    container = new_list
                if isinstance(container, list):
                    if (":" in rest and not rest.lstrip().startswith(('"', "'"))
                            and not rest.rstrip().endswith(":")):
                        # "- key: value" -> list of dicts
                        k, _, v = rest.partition(":")
                        k, v = k.strip(), v.strip()
                        d = {k: _scalar(v)}
                        container.append(d)
                        stack.append((indent, d, None, None))
                    elif rest.rstrip().endswith(":") and ":" in rest:
                        # "- key:" -> list of dicts with nested block
                        k = rest.partition(":")[0].strip()
                        sub: dict = {}
                        d = {k: sub}
                        container.append(d)
                        stack.append((indent, sub, d, k))
                    else:
                        container.append(_scalar(rest))
                # else: stray dash line under a populated dict -> ignore
                continue
            if ":" not in stripped:
                continue
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if not isinstance(container, dict):
                continue
            if val == "":
                child: dict = {}
                container[key] = child
                stack.append((indent, child, container, key))
            else:
                container[key] = _scalar(val)
    return root


def _scalar(val: str):
    if val.startswith('"') and val.endswith('"'):
        return val[1:-1]
    if val.startswith("'") and val.endswith("'"):
        return val[1:-1]
    low = val.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "none", "~"):
        return None
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


# --------------------------------------------------------------------------
# Metrics readers (real files only)
# --------------------------------------------------------------------------
def _repo(p: str) -> Path:
    return REPO / p


def read_scoreboard(path: str) -> dict:
    """Returns {min_ok_rate, agents_below_floor, p50_latency_ms_max, agents}."""
    with open(_repo(path), encoding="utf-8") as f:
        d = json.load(f)
    agents = d.get("agents", {})
    rates = [a.get("ok_rate") for a in agents.values()
             if isinstance(a, dict) and a.get("ok_rate") is not None]
    lat = [a.get("p50_latency_ms") for a in agents.values()
           if isinstance(a, dict) and a.get("p50_latency_ms") is not None]
    return {
        "min_ok_rate": min(rates) if rates else None,
        "mean_ok_rate": (sum(rates) / len(rates)) if rates else None,
        "p50_latency_ms_max": max(lat) if lat else None,
        "agent_count": len(agents),
    }


def read_health_tail(path: str) -> dict:
    """Last line of cron_health.jsonl: {verifier, sota, ts}."""
    last = None
    with open(_repo(path), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                last = line
    if not last:
        raise ValueError(f"{path}: empty health file")
    d = json.loads(last)
    return {"verifier": d.get("verifier"), "sota": d.get("sota"), "ts": d.get("ts")}


def read_eval_score(paths: list) -> dict:
    """Mean score across eval result files; tolerates schema drift.

    Files whose disclaimer/text self-identifies as MOCK are skipped —
    mock numbers must never drive training decisions.
    """
    scores: list[float] = []
    used, mock = [], []
    for p in paths or []:
        fp = _repo(p)
        if not fp.exists():
            continue
        try:
            raw = fp.read_text(encoding="utf-8")
            d = json.loads(raw)
        except Exception:
            continue
        if "mock" in raw[:2000].lower() and "disclaimer" in raw[:2000].lower():
            mock.append(p)
            continue
        items = d.get("results") if isinstance(d, dict) else d
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict):
                    s = it.get("score", it.get("cap_score", it.get("value")))
                    if isinstance(s, (int, float)):
                        scores.append(float(s))
            used.append(p)
        elif isinstance(d, dict):
            for k in ("score", "cap_score", "composite", "mean_score"):
                if isinstance(d.get(k), (int, float)):
                    scores.append(float(d[k]))
                    used.append(p)
                    break
    return {
        "mean_score": (sum(scores) / len(scores)) if scores else None,
        "n": len(scores),
        "files": used,
        "mock_files_skipped": mock,
    }


def count_verified_traces() -> int | None:
    """Count verified preference/trace rows across known bank locations."""
    candidates = [
        REPO / "reports",
        REPO / "apps" / "ava-factory" / "dottie" / "reports",
        REPO / "pipeline",
    ]
    total = 0
    found = False
    for base in candidates:
        if not base.exists():
            continue
        for fp in base.rglob("*.jsonl"):
            name = fp.name
            if "pref_pair" in name or "trace_bank" in name:
                try:
                    total += sum(1 for _ in open(fp, encoding="utf-8"))
                    found = True
                except OSError:
                    continue
    return total if found else None


def file_age_hours(path: Path) -> float | None:
    try:
        return (time.time() - path.stat().st_mtime) / 3600.0
    except OSError:
        return None


# --------------------------------------------------------------------------
# State / baseline / decisions
# --------------------------------------------------------------------------
def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return copy.deepcopy(default)


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


DEFAULT_STATE = {
    "state": "IDLE",
    "last_train_ts": None,
    "last_decision_ts": None,
    "last_train_verified_count": None,
    "prod_checkpoint": None,
    "last_good_checkpoint": None,
    "canary_checkpoint": None,
}


def write_decision(decision: dict, dry_run: bool) -> None:
    decision = dict(decision)
    decision["ts"] = dt.datetime.now(dt.timezone.utc).isoformat()
    line = json.dumps(decision)
    sys.stderr.write(f"LOOP_ALERT {line}\n")
    sys.stderr.flush()
    if not dry_run:
        DECISIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DECISIONS_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------
def evaluate(cfg: dict) -> tuple[dict, dict]:
    """Returns (metrics, decision). Raises FileNotFoundError -> blocked."""
    params = cfg.get("params", {})
    mpaths = params.get("metrics", {})
    th = params.get("thresholds", {})
    timing = params.get("timing", {})

    staleness_h = float(timing.get("staleness_hours", 48))

    # --- gather, fail-closed on missing/stale ---
    missing, stale = [], []
    metrics: dict = {}

    def need(path_key: str, reader, label: str):
        p = mpaths.get(path_key)
        if not p:
            missing.append(f"{label}: path not configured")
            return
        fp = _repo(p)
        if not fp.exists():
            missing.append(f"{label}: {p} not found")
            return
        age = file_age_hours(fp)
        if age is not None and age > staleness_h:
            stale.append(f"{label}: {p} age {age:.1f}h > {staleness_h}h")
        try:
            metrics[label] = reader(p)
        except Exception as e:  # noqa: BLE001
            missing.append(f"{label}: read error {e}")

    need("scoreboard", read_scoreboard, "scoreboard")
    need("health", read_health_tail, "health")

    eval_paths = mpaths.get("evals", [])
    if isinstance(eval_paths, str):
        eval_paths = [eval_paths]
    present = [p for p in eval_paths if _repo(p).exists()]
    # evals are required:false in the playbook: absent/mock evals skip the
    # eval-drop signal instead of blocking the whole trigger.
    metrics["evals"] = read_eval_score(present) if present else {
        "mean_score": None, "n": 0, "files": [],
        "mock_files_skipped": [], "note": "no eval files present",
    }

    if missing or stale:
        return metrics, {
            "action": "blocked",
            "reason": "; ".join(missing + stale),
            "approval_required": False,
            "exit_code": 2,
        }

    # --- compare vs thresholds and baseline ---
    state = load_json(STATE_PATH, DEFAULT_STATE)
    baseline = load_json(BASELINE_PATH, {})
    reasons: list[str] = []

    ver = (metrics["health"] or {}).get("verifier")
    if ver is not None and ver < float(th.get("verifier_floor", 8.0)):
        reasons.append(f"verifier {ver} < floor {th.get('verifier_floor', 8.0)}")

    min_ok = (metrics["scoreboard"] or {}).get("min_ok_rate")
    if min_ok is not None and min_ok < float(th.get("ok_rate_floor", 0.90)):
        reasons.append(f"min agent ok_rate {min_ok:.3f} < floor {th.get('ok_rate_floor', 0.90)}")

    b_ok = (baseline.get("scoreboard") or {}).get("min_ok_rate")
    if min_ok is not None and b_ok is not None:
        drop_pp = (b_ok - min_ok) * 100.0
        if drop_pp > float(th.get("ok_rate_drop_pp", 5.0)):
            reasons.append(f"ok_rate dropped {drop_pp:.1f}pp vs baseline")

    ev = (metrics["evals"] or {}).get("mean_score")
    b_ev = (baseline.get("evals") or {}).get("mean_score")
    if ev is not None and b_ev is not None:
        if (b_ev - ev) > float(th.get("eval_score_drop", 0.02)):
            reasons.append(f"eval score {ev:.4f} dropped {(b_ev - ev):.4f} vs baseline")

    traces = count_verified_traces()
    metrics["verified_traces"] = traces
    last_count = state.get("last_train_verified_count")
    if traces is not None and last_count is not None:
        new = traces - last_count
        metrics["new_verified_traces"] = new
        if new >= int(th.get("min_new_verified_traces", 500)):
            reasons.append(f"{new} new verified traces >= {th.get('min_new_verified_traces', 500)}")

    # --- cooldown ---
    cooldown_h = float(timing.get("cooldown_hours", 24))
    lts = state.get("last_train_ts")
    if lts:
        try:
            age_h = (dt.datetime.now(dt.timezone.utc)
                     - dt.datetime.fromisoformat(lts)).total_seconds() / 3600.0
            if age_h < cooldown_h:
                return metrics, {
                    "action": "cooldown-skip",
                    "reason": f"last train {age_h:.1f}h ago < cooldown {cooldown_h}h",
                    "triggers": reasons,
                    "approval_required": False,
                    "exit_code": 0,
                }
        except ValueError:
            pass

    if not reasons:
        return metrics, {
            "action": "idle",
            "reason": "all metrics within thresholds; no retrain signal",
            "approval_required": False,
            "exit_code": 0,
        }
    return metrics, {
        "action": "retrain-queued",
        "reason": " | ".join(reasons),
        "approval_required": False,
        "exit_code": 1,
    }


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------
def make_retrain_job(cfg: dict) -> dict:
    params = cfg.get("params", {})
    fj = params.get("forge", {})
    job_id = "dottie-grpo-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return {
        "id": job_id,
        "type": fj.get("job_type", "train"),
        "repo": fj.get("repo", "jcdavis131/dottie"),
        "workdir": fj.get("workdir", "forge-jobs/dottie-grpo"),
        "command": fj.get("command", ["echo", "FILL_IN_TRAIN_COMMAND"]),
        "requires": fj.get("requires", {"gpu": True, "min_vram_gb": 6, "cuda": True}),
        "artifacts": fj.get("artifacts", ["checkpoints/dottie-grpo-final", "metrics.json"]),
        "created_by": "loop_trigger",
        "created_at": time.time(),
        "notes": "Auto-queued by closed-loop trigger. No auto-promote: canary + human approval required.",
    }


def action_queue_retrain(cfg: dict, dry_run: bool, submit: bool) -> dict:
    metrics, decision = evaluate(cfg)
    if decision["action"] != "retrain-queued":
        write_decision({**decision, "metrics": _summ(metrics)}, dry_run)
        return decision
    job = make_retrain_job(cfg)
    if not dry_run:
        QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        jp = QUEUE_DIR / f"{job['id']}.json"
        jp.write_text(json.dumps(job, indent=1) + "\n", encoding="utf-8")
        job["queue_path"] = str(jp)
        state = load_json(STATE_PATH, DEFAULT_STATE)
        state["state"] = "RETRAIN_QUEUED"
        state["last_train_ts"] = dt.datetime.now(dt.timezone.utc).isoformat()
        state["last_train_verified_count"] = metrics.get("verified_traces")
        save_json(STATE_PATH, state)
    submitted = None
    if submit and not dry_run:
        try:
            r = subprocess.run(
                [sys.executable, "-m", "forge.cli", "submit",
                 str(QUEUE_DIR / f"{job['id']}.json")],
                cwd=str(Path.home() / "workspace"),
                capture_output=True, text=True, timeout=120,
            )
            submitted = {"rc": r.returncode,
                         "out": (r.stdout + r.stderr)[-500:]}
        except Exception as e:  # noqa: BLE001
            submitted = {"rc": -1, "out": f"submit failed: {e}"}
    decision = {**decision, "job_id": job["id"], "forge_submitted": submitted}
    write_decision({**decision, "metrics": _summ(metrics)}, dry_run)
    return decision


def action_check_canary(cfg: dict, dry_run: bool) -> dict:
    params = cfg.get("params", {})
    th = params.get("thresholds", {})
    state = load_json(STATE_PATH, DEFAULT_STATE)
    baseline = load_json(BASELINE_PATH, {})
    if not CANARY_PATH.exists():
        d = {"action": "blocked", "reason": f"no canary report at {CANARY_PATH}",
             "approval_required": False, "exit_code": 2}
        write_decision(d, dry_run)
        return d
    try:
        can = json.loads(CANARY_PATH.read_text(encoding="utf-8"))
    except ValueError as e:
        d = {"action": "blocked", "reason": f"canary report unreadable: {e}",
             "approval_required": False, "exit_code": 2}
        write_decision(d, dry_run)
        return d
    c_score = can.get("eval_score")
    b_score = (baseline.get("evals") or {}).get("mean_score")
    tol = float(th.get("canary_tolerance", 0.01))
    if c_score is None or b_score is None:
        d = {"action": "blocked",
             "reason": "canary or baseline eval score missing; cannot compare",
             "approval_required": False, "exit_code": 2}
        write_decision(d, dry_run)
        return d
    if c_score >= b_score - tol:
        if not dry_run:
            state["state"] = "AWAITING_APPROVAL"
            state["canary_checkpoint"] = can.get("checkpoint_id")
            save_json(STATE_PATH, state)
        d = {"action": "canary-pass",
             "reason": (f"canary {c_score:.4f} >= baseline {b_score:.4f} - tol {tol}; "
                        "AWAITING HUMAN APPROVAL — no auto-promote"),
             "canary_checkpoint": can.get("checkpoint_id"),
             "approval_required": True, "exit_code": 1}
    else:
        if not dry_run:
            state["state"] = "IDLE"
            state["canary_checkpoint"] = None
            save_json(STATE_PATH, state)
        d = {"action": "canary-fail",
             "reason": (f"canary {c_score:.4f} < baseline {b_score:.4f} - tol {tol}; "
                        "checkpoint discarded"),
             "approval_required": False, "exit_code": 1}
    write_decision(d, dry_run)
    return d


def action_promote(cfg: dict, dry_run: bool, approve_prod: bool) -> dict:
    state = load_json(STATE_PATH, DEFAULT_STATE)
    if state.get("state") != "AWAITING_APPROVAL" or not state.get("canary_checkpoint"):
        d = {"action": "blocked",
             "reason": "no approved canary awaiting promotion (state=%s)" % state.get("state"),
             "approval_required": False, "exit_code": 2}
        write_decision(d, dry_run)
        return d
    if not approve_prod:
        d = {"action": "promote-blocked-needs-approval",
             "reason": "canary passed but --approve-prod not given; promotion NOT performed",
             "canary_checkpoint": state.get("canary_checkpoint"),
             "approval_required": True, "exit_code": 3}
        write_decision(d, dry_run)
        return d
    # Approved: write promotion RECORD only. Operator executes deploy.
    metrics, _ = evaluate(cfg)
    record = {
        "checkpoint_id": state["canary_checkpoint"],
        "approved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "approved_via": "--approve-prod flag (human operator)",
        "metrics_at_promotion": _summ(metrics),
        "deploy_step": "OPERATOR ACTION REQUIRED: deploy checkpoint per runbook; this record is not a deploy.",
    }
    if not dry_run:
        pin = REPO / "pipeline" / f"loop_promotion_{int(time.time())}.json"
        pin.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
        baseline = {
            "scoreboard": metrics.get("scoreboard"),
            "health": metrics.get("health"),
            "evals": metrics.get("evals"),
            "promoted_at": record["approved_at"],
        }
        save_json(BASELINE_PATH, baseline)
        state["state"] = "IDLE"
        state["prod_checkpoint"] = state["canary_checkpoint"]
        state["last_good_checkpoint"] = state["canary_checkpoint"]
        state["canary_checkpoint"] = None
        save_json(STATE_PATH, state)
    d = {"action": "promoted",
         "reason": "human-approved promotion recorded; deploy is operator's step",
         "checkpoint_id": state.get("canary_checkpoint") or record["checkpoint_id"],
         "approval_required": False, "exit_code": 1}
    write_decision(d, dry_run)
    return d


def action_rollback(cfg: dict, dry_run: bool, approve_prod: bool, auto: bool = False) -> dict:
    state = load_json(STATE_PATH, DEFAULT_STATE)
    last_good = state.get("last_good_checkpoint")
    if not last_good:
        d = {"action": "blocked", "reason": "no last_good_checkpoint recorded; cannot rollback",
             "approval_required": False, "exit_code": 2}
        write_decision(d, dry_run)
        return d
    if not approve_prod and not auto:
        d = {"action": "rollback-blocked-needs-approval",
             "reason": "rollback requires --approve-prod; no state changed",
             "approval_required": True, "exit_code": 3}
        write_decision(d, dry_run)
        return d
    record = {
        "restored_checkpoint": last_good,
        "rolled_back_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "approved_via": "--approve-prod flag" if not auto else "auto rollback on regression",
        "deploy_step": "OPERATOR ACTION REQUIRED: point serving at restored checkpoint.",
    }
    if not dry_run:
        pin = REPO / "pipeline" / f"loop_rollback_{int(time.time())}.json"
        pin.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
        state["state"] = "IDLE"
        state["prod_checkpoint"] = last_good
        state["canary_checkpoint"] = None
        save_json(STATE_PATH, state)
    d = {"action": "rolled-back", "reason": f"restored {last_good}; operator redeploys",
         "approval_required": False, "exit_code": 1}
    write_decision(d, dry_run)
    return d


def _summ(metrics: dict) -> dict:
    out = {}
    for k in ("scoreboard", "health", "evals"):
        v = metrics.get(k)
        out[k] = v if isinstance(v, dict) else v
    for k in ("verified_traces", "new_verified_traces"):
        if k in metrics:
            out[k] = metrics[k]
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dottie closed-loop training trigger")
    ap.add_argument("--config", default="playbooks/closed_loop.yaml")
    ap.add_argument("--decide", action="store_true",
                    help="evaluate metrics and write decision only")
    ap.add_argument("--queue-retrain", action="store_true",
                    help="evaluate; if signaled, write Forge job spec to loop queue")
    ap.add_argument("--submit-forge", action="store_true",
                    help="with --queue-retrain, also submit to Forge queue (Alienware runner)")
    ap.add_argument("--check-canary", action="store_true",
                    help="evaluate canary report vs baseline")
    ap.add_argument("--promote", action="store_true",
                    help="record human-approved promotion (needs --approve-prod)")
    ap.add_argument("--rollback", action="store_true",
                    help="record rollback to last-good checkpoint (needs --approve-prod)")
    ap.add_argument("--approve-prod", action="store_true",
                    help="HUMAN approval flag: required for promote/rollback")
    ap.add_argument("--dry-run", action="store_true",
                    help="print decision; write nothing")
    args = ap.parse_args(argv)

    cfg_path = _repo(args.config)
    if not cfg_path.exists():
        sys.stderr.write(f"LOOP_ALERT config missing: {cfg_path}\n")
        return 2
    cfg = parse_simple_yaml(cfg_path)

    n_actions = sum([args.decide, args.queue_retrain, args.check_canary,
                     args.promote, args.rollback])
    if n_actions == 0:
        args.decide = True
    if n_actions > 1:
        sys.stderr.write("LOOP_ALERT pick exactly one action\n")
        return 2

    if args.queue_retrain:
        d = action_queue_retrain(cfg, args.dry_run, args.submit_forge)
    elif args.check_canary:
        d = action_check_canary(cfg, args.dry_run)
    elif args.promote:
        d = action_promote(cfg, args.dry_run, args.approve_prod)
    elif args.rollback:
        d = action_rollback(cfg, args.dry_run, args.approve_prod)
    else:
        metrics, d = evaluate(cfg)
        write_decision({**d, "metrics": _summ(metrics)}, args.dry_run)

    print(json.dumps(d, indent=1))
    return int(d.get("exit_code", 0))


if __name__ == "__main__":
    sys.exit(main())
