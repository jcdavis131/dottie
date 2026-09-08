"""Tests for the fail-closed distillation ladder driver.

Covers:
- scripts/distill_ladder.py gate: HOLD on error/NaN/missing, PROMOTE only
  within tolerance, ladder stops on HOLD, provenance log rows are honest;
- the CLI dry-runs (exit 0) and refuses a real run (exit 2).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(_REPO / "scripts"))
from distill_ladder import TierSpec, gate_decision, run_ladder

# ------------------------------------------------- gate: never promote on error


def test_gate_holds_on_error_and_nan():
    assert gate_decision({"error": "harness exploded"}, None)["verdict"] == "HOLD"
    assert gate_decision({"weighted_ppl": float("nan")}, None)["verdict"] == "HOLD"
    assert gate_decision({"weighted_ppl": float("inf")}, None)["verdict"] == "HOLD"
    assert gate_decision({}, None)["verdict"] == "HOLD"

    first = gate_decision({"weighted_ppl": 10.0}, None)
    assert first["verdict"] == "PROMOTE"
    assert "baseline" in first["reason"]

    within = gate_decision(
        {"weighted_ppl": 10.19}, {"weighted_ppl": 10.0}, ppl_tol=0.02
    )
    assert within["verdict"] == "PROMOTE"

    regressed = gate_decision(
        {"weighted_ppl": 10.3}, {"weighted_ppl": 10.0}, ppl_tol=0.02
    )
    assert regressed["verdict"] == "HOLD"
    assert "10.3" in regressed["reason"] and "10" in regressed["reason"]


# ------------------------------------------------- ladder driver


def _tier(name: str, teachers=None) -> TierSpec:
    return TierSpec(
        name=name,
        student_config="configs/base1b.yaml",
        student_ckpt=None,
        teachers=teachers if teachers is not None else [("generic", "base.pt")],
        mode="mopd",
        tokens=1000,
    )


def test_ladder_stops_on_hold_and_logs_provenance(tmp_path):
    t1 = _tier("mini", teachers=[("generic", "base.pt")])
    t2 = _tier("nano")

    def train_fn(tier):
        p = tmp_path / f"{tier.name}.pt"
        p.write_bytes(b"ckpt-" + tier.name.encode())
        return p

    ppl = {"mini": 10.0, "nano": 12.0}  # nano regressed beyond 2% tol

    def eval_fn(ckpt_path):
        return {"weighted_ppl": ppl[Path(ckpt_path).stem]}

    results = run_ladder([t1, t2], train_fn, eval_fn, tmp_path)
    assert [r["verdict"] for r in results] == ["PROMOTE", "HOLD"]

    rows = [
        json.loads(line)
        for line in (tmp_path / "ladder_promotions.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 2
    mini_ckpt = tmp_path / "mini.pt"
    assert rows[0]["verdict"] == "PROMOTE"
    assert rows[0]["sha256"] == hashlib.sha256(b"ckpt-mini").hexdigest()
    assert rows[1]["verdict"] == "HOLD"
    # tier 1's promoted student became tier 2's teacher
    assert rows[1]["teacher_lineage"] == [str(mini_ckpt)]
    assert t2.teachers == [("generic", str(mini_ckpt))]

    # 3-tier variant: tier 2 HOLDs, tier 3 must never run
    out2 = tmp_path / "three"
    t1b, t2b, t3b = _tier("mini"), _tier("nano"), _tier("pico")

    def train_fn2(tier):
        p = out2 / f"{tier.name}.pt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"ckpt-" + tier.name.encode())
        return p

    results2 = run_ladder([t1b, t2b, t3b], train_fn2, eval_fn, out2)
    assert [r["verdict"] for r in results2] == ["PROMOTE", "HOLD"]
    rows2 = (out2 / "ladder_promotions.jsonl").read_text().splitlines()
    assert len(rows2) == 2, "tier 3 ran after a HOLD — regressed teacher distilled"


def test_ladder_dry_run_cli(tmp_path):
    pytest.importorskip("yaml")
    ladder = tmp_path / "ladder.yaml"
    ladder.write_text(
        "tiers:\n"
        "  - name: mini\n"
        "    student_config: configs/base1b.yaml\n"
        "    student_ckpt: null\n"
        "    teachers:\n"
        "      - domain: generic\n"
        "        ckpt: base.pt\n"
        "    mode: mopd\n"
        "    tokens: 1000\n"
    )

    dry = subprocess.run(
        [sys.executable, "scripts/distill_ladder.py", "--ladder", str(ladder), "--dry-run"],
        cwd=_REPO,
        capture_output=True,
        text=True,
    )
    assert dry.returncode == 0, dry.stderr
    plan = json.loads(dry.stdout)
    assert plan["tiers"][0]["name"] == "mini"

    real = subprocess.run(
        [sys.executable, "scripts/distill_ladder.py", "--ladder", str(ladder)],
        cwd=_REPO,
        capture_output=True,
        text=True,
    )
    assert real.returncode == 2, "real run must refuse honestly, not fabricate"
    assert "refus" in (real.stderr + real.stdout).lower()
