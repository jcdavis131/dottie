# Solo personal project, no connection to employer, built with public/free-tier only
"""Contract tests for scripts/export_gridiron_forecast_rows.py.

The exporter reads vector-gridiron backtest INPUTS (train_matrix.npz,
feature_manifest.json, assets/eval_backtest.json) strictly read-only and emits
baseline-forecast-vs-actual player-week rows for the backtest's test season.
Honesty contract under test: only test-season skill-position rows, no model
predictions fabricated, scored-group flag mirrors the backtest's MIN_GROUP
rule, and the average-rank Spearman matches build_backtest.py's definition.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np

_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "export_gridiron_forecast_rows.py"
)
_spec = importlib.util.spec_from_file_location("export_gridiron_forecast_rows", _SCRIPT)
egf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(egf)


def _mkroot(tmp_path):
    """Synthetic gridiron root: 2 seasons, QB group of 3 (scored), TE group of 2
    (below min_group), one K row and one prior-season row (both excluded)."""
    root = tmp_path / "gridiron"
    (root / "assets").mkdir(parents=True)
    data = root / "pipeline" / "data"
    data.mkdir(parents=True)

    (root / "assets" / "eval_backtest.json").write_text(
        json.dumps(
            {
                "computed_at": "2026-01-01 00:00:00",
                "season": 2025,
                "weeks": [2],
                "min_group": 3,
                "positions": {"QB": {"baseline_last4": 1.0, "baseline_std": 1.0}},
                "overall": {"baseline_last4": 1.0, "baseline_std": 1.0, "n_rows": 5},
            }
        ),
        encoding="utf-8",
    )

    (data / "feature_manifest.json").write_text(
        json.dumps(
            {
                "features": ["f_fpts_ppr", "std_ppr"],
                "targets": ["fpts_ppr"],
            }
        ),
        encoding="utf-8",
    )

    #                 season week pos   last4 std   actual
    rows = [
        (2025, 2, "QB", "A", 20.0, 19.0, 25.0),
        (2025, 2, "QB", "B", 15.0, 14.0, 18.0),
        (2025, 2, "QB", "C", 10.0, 11.0, 9.0),
        (2025, 2, "TE", "D", 8.0, 7.0, 10.0),
        (2025, 2, "TE", "E", 5.0, 6.0, 4.0),
        (2025, 2, "K", "F", 9.0, 9.0, 9.0),  # not a SKILL pos -> excluded
        (2024, 2, "QB", "G", 20.0, 19.0, 25.0),  # not the test season -> excluded
    ]
    Z = np.array([[r[4], r[5]] for r in rows], dtype=np.float64)
    mask = np.ones_like(Z)
    mask[3, 1] = 0.0  # player D's std_ppr is missing
    Y = np.array([[r[6]] for r in rows], dtype=np.float64)
    np.savez_compressed(
        data / "train_matrix.npz",
        Z=Z,
        mask=mask,
        Y=Y,
        season=np.array([r[0] for r in rows], dtype=np.int32),
        week=np.array([r[1] for r in rows], dtype=np.int32),
        pos=np.array([r[2] for r in rows]),
        gsis=np.array([f"00-{i:07d}" for i in range(len(rows))]),
        name=np.array([r[3] for r in rows]),
        team=np.array(["XX"] * len(rows)),
    )
    return root


def test_spearman_matches_backtest_definition():
    # perfectly monotone -> 1.0; anti-monotone -> -1.0
    assert egf.spearman(np.array([1.0, 2.0, 3.0]), np.array([10.0, 20.0, 30.0])) == 1.0
    assert egf.spearman(np.array([1.0, 2.0, 3.0]), np.array([3.0, 2.0, 1.0])) == -1.0
    # ties get average ranks (build_backtest._rankdata behaviour)
    ranks = egf._rankdata(np.array([1.0, 1.0, 2.0]))
    assert ranks.tolist() == [0.5, 0.5, 2.0]
    # degenerate (constant) input -> None, not a fabricated number
    assert egf.spearman(np.array([1.0, 1.0, 1.0]), np.array([1.0, 2.0, 3.0])) is None


def test_filters_to_test_season_skill_positions(tmp_path):
    rows, summary = egf.export_rows(_mkroot(tmp_path))
    assert len(rows) == 5  # K row and 2024 row are gone
    assert {r["pos"] for r in rows} == {"QB", "TE"}
    assert {r["season"] for r in rows} == {2025}


def test_row_schema_and_scored_group_flag(tmp_path):
    rows, summary = egf.export_rows(_mkroot(tmp_path))
    for r in rows:
        for key in (
            "season",
            "week",
            "gsis",
            "name",
            "pos",
            "team",
            "forecast_last4_ppr",
            "forecast_std_ppr",
            "forecast_last4_present",
            "forecast_std_present",
            "actual_fpts_ppr",
            "in_scored_group",
        ):
            assert key in r, f"missing {key}"
    by_name = {r["name"]: r for r in rows}
    assert by_name["A"]["in_scored_group"] is True  # QB group n=3 >= min_group 3
    assert by_name["D"]["in_scored_group"] is False  # TE group n=2 < 3
    assert by_name["D"]["forecast_std_present"] == 0  # masked feature surfaced
    assert by_name["A"]["forecast_last4_ppr"] == 20.0
    assert by_name["A"]["actual_fpts_ppr"] == 25.0


def test_crosscheck_recomputes_baseline_spearman(tmp_path):
    rows, summary = egf.export_rows(_mkroot(tmp_path))
    # QB group is perfectly monotone in last4 -> recomputed rho 1.0, and the
    # summary carries the artifact's number next to it for the audit diff.
    qb = summary["crosscheck"]["QB"]
    assert qb["recomputed_last4"] == 1.0
    assert qb["artifact_last4"] == 1.0
    assert summary["n_rows"] == 5


def test_main_writes_jsonl(tmp_path):
    root = _mkroot(tmp_path)
    out = tmp_path / "out" / "gridiron_forecast_rows.jsonl"
    rc = egf.main(["--gridiron-root", str(root), "--out", str(out)])
    assert rc == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    assert json.loads(lines[0])["season"] == 2025
