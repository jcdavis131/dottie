# Solo personal project, no connection to employer, built with public/free-tier only
"""Contract tests for scripts/export_repair_transcripts.py.

The exporter mines a ledger COPY for failure->hint->corrected-code pairs. The
honesty contract under test: rows come ONLY from experiments whose validation
history recovered (fail then ok) — the only case where the ledger contains code
known to fix the recorded failure — and corrected_code is the experiment's
final validated code, never a fabricated per-attempt diff.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_repair_transcripts.py"
_spec = importlib.util.spec_from_file_location("export_repair_transcripts", _SCRIPT)
ert = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ert)

_DDL = """
CREATE TABLE experiments (
    id           TEXT PRIMARY KEY,
    state        TEXT NOT NULL,
    created_ts   REAL NOT NULL,
    updated_ts   REAL NOT NULL,
    hypothesis   TEXT NOT NULL,
    implementation TEXT,
    workspace    TEXT,
    train_metrics TEXT,
    eval_verdict TEXT,
    writeup      TEXT,
    failure      TEXT,
    attempts     INTEGER NOT NULL DEFAULT 0
)
"""

_EINSUM_DETAIL = (
    "Traceback (most recent call last):\n  ...\n"
    "RuntimeError: einsum() operands do not broadcast"
)
_F821_DETAIL = "F821 Undefined name `attn`\n  --> candidate.py:33:24"


def _impl(history, code="import torch\n", dry_run=None):
    return json.dumps({
        "module_name": "TestBlock",
        "target_file": "candidate.py",
        "code": code,
        "shape_assertions": [],
        "dry_run": dry_run or {"class_name": "TestBlock",
                               "init_kwargs": {"hidden": 64},
                               "input_shape": [4, 16, 64]},
        "validation": {"ok": bool(history and history[-1].get("ok")),
                       "attempts": len(history) - 1,
                       "history": history},
    })


def _hyp(name="Test Hypothesis"):
    return json.dumps({"hypothesis_name": name})


def _mkdb(tmp_path):
    db = tmp_path / "ledger_copy_test.sqlite3"
    con = sqlite3.connect(db)
    con.execute(_DDL)
    rows = [
        # Recovered: two fails then ok — yields one row PER failed attempt.
        ("recov1", "rejected", 1.0, _hyp("Recovered One"), _impl([
            {"attempt": 0, "ok": False, "level": "static", "status": "fail",
             "detail": _F821_DETAIL},
            {"attempt": 1, "ok": False, "level": "dry_run", "status": "fail",
             "detail": _EINSUM_DETAIL},
            {"attempt": 2, "ok": True, "level": "dry_run", "status": "pass",
             "detail": "forward ok on input [4, 16, 64] -> (4, 16, 64)"},
        ], code="FIXED_CODE")),
        # Never recovered: no code in the ledger fixes these failures -> 0 rows.
        ("failonly", "failed_validation", 2.0, _hyp(), _impl([
            {"attempt": 0, "ok": False, "level": "dry_run", "status": "fail",
             "detail": _EINSUM_DETAIL},
            {"attempt": 1, "ok": False, "level": "dry_run", "status": "fail",
             "detail": _EINSUM_DETAIL},
        ])),
        # Passed first try: no failure to pair -> 0 rows.
        ("cleanpass", "sota", 3.0, _hyp(), _impl([
            {"attempt": 0, "ok": True, "level": "dry_run", "status": "pass",
             "detail": "forward ok"},
        ])),
    ]
    for rid, state, ts, hyp, impl in rows:
        con.execute(
            "INSERT INTO experiments (id, state, created_ts, updated_ts, hypothesis, "
            "implementation) VALUES (?, ?, ?, ?, ?, ?)",
            (rid, state, ts, ts, hyp, impl))
    # No implementation at all — must be skipped, not crash.
    con.execute(
        "INSERT INTO experiments (id, state, created_ts, updated_ts, hypothesis) "
        "VALUES ('noimpl', 'pending', 4.0, 4.0, ?)", (_hyp(),))
    con.commit()
    con.close()
    return db


def test_only_recovered_experiments_yield_rows(tmp_path):
    rows = ert.extract_rows(_mkdb(tmp_path))
    assert [r["experiment_id"] for r in rows] == ["recov1", "recov1"]
    assert len(rows) == 2  # one per failed attempt


def test_row_schema_and_verbatim_detail(tmp_path):
    rows = ert.extract_rows(_mkdb(tmp_path))
    r0, r1 = rows
    for r in rows:
        for key in ("experiment_id", "experiment_state", "hypothesis_name",
                    "module_name", "dry_run_contract", "attempt", "failure_seq",
                    "n_failed_attempts", "level", "status", "failure_detail",
                    "repair_hint", "hint_source", "corrected_code",
                    "corrected_code_role", "validated_detail"):
            assert key in r, f"missing {key}"
        # corrected code is the FINAL validated code, marked as such
        assert r["corrected_code"] == "FIXED_CODE"
        assert r["corrected_code_role"] == "final_validated_code"
        assert r["n_failed_attempts"] == 2
        assert r["validated_detail"].startswith("forward ok")
    assert r0["failure_detail"] == _F821_DETAIL  # verbatim, no cleanup
    assert (r0["attempt"], r0["failure_seq"]) == (0, 0)
    assert (r1["attempt"], r1["failure_seq"]) == (1, 1)


def test_hint_matches_current_diagnose_failure(tmp_path):
    rows = ert.extract_rows(_mkdb(tmp_path))
    r_f821, r_einsum = rows
    # F821 at level=static now hits the level-scoped _LEVEL_HINTS table
    assert r_f821["repair_hint"] is not None
    assert "UNDEFINED NAME" in r_f821["repair_hint"]
    # einsum dry_run failure hits the targeted _HINTS pattern
    assert r_einsum["repair_hint"] is not None
    assert "EINSUM" in r_einsum["repair_hint"]
    # every row must carry the recomputed-at-export-time disclaimer
    assert "recomputed" in r_f821["hint_source"]


def test_main_writes_jsonl(tmp_path):
    db = _mkdb(tmp_path)
    out = tmp_path / "out" / "repair_transcripts.jsonl"
    rc = ert.main(["--db", str(db), "--out", str(out)])
    assert rc == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["experiment_id"] == "recov1"
