#!/usr/bin/env python3
"""Multi-tier distillation ladder: tier-cascade DRIVER and PROMOTE/HOLD GATE.

Solo personal project, no connection to employer, built with public/free-tier only

WHAT THIS IS. The orchestration + gate layer for cascaded distillation: tier k's
PROMOTED student becomes tier k+1's teacher. It sequences tiers, applies the
promote/hold gate between them, and writes an append-only provenance log
(`ladder_promotions.jsonl`: checkpoint sha256, verdict, reason, teacher lineage).

WHAT THIS IS NOT. It does not train and it does not evaluate. Real ladder runs
require a GPU and real checkpoints that DO NOT EXIST YET — `run_ladder` takes
`train_fn` / `eval_fn` as explicit injected callables so the gate logic is fully
testable on CPU, and `main()` refuses (exit 2) rather than fabricate a run when
invoked without `--dry-run`.

GATE POLICY (follows tasks/artifacts/design_ckpt_eval_gate.md, repo root):
  - NEVER promote on error: a candidate whose eval carries an "error" key, or
    whose weighted_ppl is missing/NaN/inf/non-numeric, is a HOLD, full stop.
  - First clean candidate PROMOTEs and records the baseline.
  - After that, PROMOTE only when weighted_ppl <= incumbent * (1 + ppl_tol).
  - A HOLD STOPS the ladder immediately: later tiers never run, so a regressed
    teacher is never distilled from.

Modes per tier mirror on_policy_distill.py (--mode at :779-938):
mopd / privileged / earlier / offpolicy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path

VALID_MODES = ("mopd", "privileged", "earlier", "offpolicy")


@dataclass
class TierSpec:
    name: str
    student_config: str  # path to a yaml model config
    student_ckpt: str | None
    teachers: list[tuple[str, str]]  # (domain, ckpt path)
    mode: str  # one of VALID_MODES
    tokens: int
    ppl_tol: float = 0.02


def gate_decision(
    candidate: dict, incumbent: dict | None, ppl_tol: float = 0.02
) -> dict:
    """PURE promote/hold gate. Never promotes on error; only two verdicts exist.

    Returns {"verdict": "PROMOTE"|"HOLD", "reason": str}.
    """
    if "error" in candidate:
        return {
            "verdict": "HOLD",
            "reason": f"eval reported an error: {candidate['error']!r} — never promote on error",
        }
    wp = candidate.get("weighted_ppl")
    if not isinstance(wp, (int, float)) or isinstance(wp, bool):
        return {
            "verdict": "HOLD",
            "reason": f"weighted_ppl missing or non-numeric ({wp!r}) — never promote on error",
        }
    if math.isnan(wp) or math.isinf(wp):
        return {
            "verdict": "HOLD",
            "reason": f"weighted_ppl is not finite ({wp}) — never promote on error",
        }
    if incumbent is None:
        return {"verdict": "PROMOTE", "reason": "first promotion — baseline recorded"}
    ceiling = incumbent["weighted_ppl"] * (1 + ppl_tol)
    if wp <= ceiling:
        return {
            "verdict": "PROMOTE",
            "reason": (
                f"weighted_ppl {wp:.6g} <= incumbent {incumbent['weighted_ppl']:.6g} "
                f"* (1 + {ppl_tol}) = {ceiling:.6g}"
            ),
        }
    return {
        "verdict": "HOLD",
        "reason": (
            f"weighted_ppl {wp:.6g} > incumbent {incumbent['weighted_ppl']:.6g} "
            f"* (1 + {ppl_tol}) = {ceiling:.6g}"
        ),
    }


def _sha256(path) -> str:
    """sha256 hexdigest of the file bytes, or "missing" if the file does not exist."""
    p = Path(path)
    if not p.exists():
        return "missing"
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_ladder(
    tiers: list[TierSpec], train_fn, eval_fn, out_dir: Path
) -> list[dict]:
    """Run tiers in order through train -> eval -> gate.

    train_fn(tier) -> checkpoint path; eval_fn(ckpt_path) -> metrics dict with
    "weighted_ppl". Both are injected so the driver is testable on CPU.

    On PROMOTE the promoted checkpoint replaces every teacher ckpt of the NEXT
    tier (tier k's student teaches tier k+1). On HOLD the ladder stops
    immediately — a regressed teacher is never distilled from.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "ladder_promotions.jsonl"

    incumbent: dict | None = None
    results: list[dict] = []
    for i, tier in enumerate(tiers):
        ckpt_path = train_fn(tier)
        metrics = eval_fn(ckpt_path)
        decision = gate_decision(metrics, incumbent, tier.ppl_tol)

        row = {
            "ts": time.time(),
            "tier": tier.name,
            "ckpt": str(ckpt_path),
            "sha256": _sha256(ckpt_path),
            "verdict": decision["verdict"],
            "reason": decision["reason"],
            "weighted_ppl": metrics.get("weighted_ppl"),
            "teacher_lineage": [c for _, c in tier.teachers],
        }
        with log_path.open("a") as f:
            f.write(json.dumps(row) + "\n")

        results.append(
            {"tier": tier.name, "verdict": decision["verdict"], "ckpt": str(ckpt_path)}
        )

        if decision["verdict"] != "PROMOTE":
            # HOLD stops the ladder: later tiers never see a regressed teacher.
            break
        incumbent = {
            "weighted_ppl": metrics["weighted_ppl"],
            "ckpt": str(ckpt_path),
        }
        if i + 1 < len(tiers):
            nxt = tiers[i + 1]
            nxt.teachers = [(domain, str(ckpt_path)) for domain, _ in nxt.teachers]
    return results


def load_ladder_yaml(path) -> list[TierSpec]:
    """Parse {tiers: [{name, student_config, student_ckpt, teachers, mode, tokens, ppl_tol}]}."""
    import yaml  # lazy: keep the module importable without pyyaml

    with Path(path).open() as f:
        doc = yaml.safe_load(f) or {}
    tiers: list[TierSpec] = []
    for t in doc.get("tiers", []):
        mode = t["mode"]
        if mode not in VALID_MODES:
            raise ValueError(f"tier {t.get('name')!r}: unknown mode {mode!r}, expected one of {VALID_MODES}")
        tiers.append(
            TierSpec(
                name=t["name"],
                student_config=t["student_config"],
                student_ckpt=t.get("student_ckpt"),
                teachers=[(x["domain"], x["ckpt"]) for x in t.get("teachers", [])],
                mode=mode,
                tokens=int(t["tokens"]),
                ppl_tol=float(t.get("ppl_tol", 0.02)),
            )
        )
    return tiers


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ladder", required=True, help="ladder yaml (tiers: [...])")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="print the parsed tier plan as json and exit 0 (no training)",
    )
    args = ap.parse_args()

    tiers = load_ladder_yaml(args.ladder)
    if args.dry_run:
        plan = [
            {
                "name": t.name,
                "student_config": t.student_config,
                "student_ckpt": t.student_ckpt,
                "teachers": [{"domain": d, "ckpt": c} for d, c in t.teachers],
                "mode": t.mode,
                "tokens": t.tokens,
                "ppl_tol": t.ppl_tol,
            }
            for t in tiers
        ]
        print(json.dumps({"tiers": plan}, indent=2))
        return 0

    # Honest refusal, not a fabricated run.
    print(
        "refusing: real ladder runs need GPU + real checkpoints; "
        "wire train_fn/eval_fn explicitly via run_ladder()",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
