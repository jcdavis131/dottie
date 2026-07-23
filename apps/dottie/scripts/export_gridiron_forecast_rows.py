# Solo personal project, no connection to employer, built with public/free-tier only
"""Export forecast-vs-actual player-week rows from vector-gridiron backtest inputs.

Data-flywheel corpus PROPOSAL (L4): nothing auto-ingests this output. The
vector-gridiron repo is treated strictly READ-ONLY (it sits dirty on a claude/*
branch); this exporter lives in apps/dottie and only reads three files:

    <root>/assets/eval_backtest.json          -- the published backtest artifact
    <root>/pipeline/data/feature_manifest.json -- feature/target name registry
    <root>/pipeline/data/train_matrix.npz      -- the backtest's row-level input

What a row IS: the two deterministic as-of baseline forecasts that
build_backtest.py itself scores — last-4-average PPR (feature `f_fpts_ppr`)
and season-to-date PPR (`std_ppr`) — against the actual PPR outcome
(`Y[:, targets.index('fpts_ppr')]`), for every test-season row at a skill
position, with identity and join keys.

What a row is NOT: it carries NO MTNN model prediction. No per-row prediction
artifact exists on disk — build_backtest.py recomputes predictions in memory
from the torch checkpoint on every run, and this exporter must not load models
(static analysis only). Absence is stated rather than imputed.

Integrity cross-check: per position and overall, the mean per-week Spearman of
each baseline vs actual is recomputed from the exported rows with the same
average-rank Spearman as build_backtest.py, printed beside the artifact's own
baseline_last4/baseline_std numbers. Matching values prove these rows are the
true inputs of the published metric, not a lookalike.

Run (from apps/dottie):
    .venv/Scripts/python.exe scripts/export_gridiron_forecast_rows.py ^
        --gridiron-root C:\\Users\\jcdav\\vector-gridiron ^
        --out ..\\..\\tasks\\artifacts\\corpus_proposals\\gridiron_forecast_rows.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# train_mtnn.py:41 — copied, not imported: importing train_mtnn would pull torch.
SKILL = ("QB", "RB", "WR", "TE")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rankdata(a: np.ndarray) -> np.ndarray:
    """Average-rank with ties sharing the mean rank — build_backtest.py's exact
    implementation, kept byte-identical so the cross-check is apples-to-apples."""
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(len(a), dtype=np.float64)
    sa = a[order]
    i = 0
    while i < len(a):
        j = i
        while j + 1 < len(a) and sa[j + 1] == sa[i]:
            j += 1
        ranks[order[i:j + 1]] = 0.5 * (i + j)
        i = j + 1
    return ranks


def spearman(x: np.ndarray, y: np.ndarray) -> Optional[float]:
    if len(x) < 3:
        return None
    rx, ry = _rankdata(np.asarray(x, np.float64)), _rankdata(np.asarray(y, np.float64))
    if rx.std() == 0 or ry.std() == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def _crosscheck(rows: List[Dict[str, Any]], artifact: Dict[str, Any]) -> Dict[str, Any]:
    """Recompute mean per-week baseline Spearman from the exported rows and put
    the artifact's numbers alongside; scored-group rows only, like the backtest."""
    scored = [r for r in rows if r["in_scored_group"]]
    out: Dict[str, Any] = {}
    for g in list(SKILL) + ["ALL"]:
        grp = scored if g == "ALL" else [r for r in scored if r["pos"] == g]
        rhos_l4, rhos_std = [], []
        for w in sorted({r["week"] for r in grp}):
            wk = [r for r in grp if r["week"] == w]
            l4 = spearman(np.array([r["forecast_last4_ppr"] for r in wk]),
                          np.array([r["actual_fpts_ppr"] for r in wk]))
            st = spearman(np.array([r["forecast_std_ppr"] for r in wk]),
                          np.array([r["actual_fpts_ppr"] for r in wk]))
            if l4 is not None:
                rhos_l4.append(l4)
            if st is not None:
                rhos_std.append(st)
        art = artifact["overall"] if g == "ALL" else artifact.get("positions", {}).get(g, {})
        out[g] = {
            "recomputed_last4": round(float(np.mean(rhos_l4)), 4) if rhos_l4 else None,
            "artifact_last4": art.get("baseline_last4"),
            "recomputed_std": round(float(np.mean(rhos_std)), 4) if rhos_std else None,
            "artifact_std": art.get("baseline_std"),
            "n_rows": len(grp),
            "artifact_n_rows": art.get("n_rows"),
        }
    return out


def export_rows(root: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    artifact = json.loads((root / "assets" / "eval_backtest.json").read_text("utf-8"))
    data = root / "pipeline" / "data"
    manifest = json.loads((data / "feature_manifest.json").read_text("utf-8"))
    npz = np.load(data / "train_matrix.npz", allow_pickle=True)

    feats: List[str] = list(manifest["features"])
    i_l4, i_std = feats.index("f_fpts_ppr"), feats.index("std_ppr")
    i_y = list(manifest["targets"]).index("fpts_ppr")
    test_season = int(artifact["season"])
    min_group = int(artifact.get("min_group", 8))

    season = npz["season"].astype(int)
    pos = npz["pos"].astype(str)
    sel = (season == test_season) & np.isin(pos, list(SKILL))
    idx = np.nonzero(sel)[0]

    week = npz["week"].astype(int)
    # scored-group rule mirrors build_backtest.py: a (week, position) group is
    # scored only when it has at least min_group rows
    group_n = Counter((int(week[i]), pos[i]) for i in idx)

    Z, M, Y = npz["Z"], npz["mask"], npz["Y"]
    name, gsis, team = npz["name"].astype(str), npz["gsis"].astype(str), npz["team"].astype(str)

    rows: List[Dict[str, Any]] = []
    for i in idx:
        w, p = int(week[i]), pos[i]
        y = float(Y[i, i_y])
        rows.append({
            "season": test_season,
            "week": w,
            "gsis": gsis[i],
            "name": name[i],
            "pos": p,
            "team": team[i],
            "forecast_last4_ppr": round(float(Z[i, i_l4]), 4),
            "forecast_std_ppr": round(float(Z[i, i_std]), 4),
            "forecast_last4_present": int(M[i, i_l4]),
            "forecast_std_present": int(M[i, i_std]),
            "actual_fpts_ppr": None if np.isnan(y) else round(y, 4),
            "in_scored_group": group_n[(w, p)] >= min_group,
        })
    rows.sort(key=lambda r: (r["week"], r["pos"], r["gsis"]))

    summary = {
        "test_season": test_season,
        "min_group": min_group,
        "n_rows": len(rows),
        "weeks": sorted({r["week"] for r in rows}),
        "nan_actuals": sum(1 for r in rows if r["actual_fpts_ppr"] is None),
        "crosscheck": _crosscheck(rows, artifact),
    }
    return rows, summary


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gridiron-root", type=Path, required=True,
                    help="vector-gridiron checkout (read-only)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    rows, summary = export_rows(args.gridiron_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    data = args.gridiron_root / "pipeline" / "data"
    for p in (args.gridiron_root / "assets" / "eval_backtest.json",
              data / "feature_manifest.json", data / "train_matrix.npz"):
        print(f"input: {p.name} sha256={_sha256(p)}")
    print(f"wrote {args.out}: {summary['n_rows']} rows, season {summary['test_season']}, "
          f"weeks {summary['weeks'][0]}-{summary['weeks'][-1]}, "
          f"nan_actuals={summary['nan_actuals']}")
    print("cross-check (recomputed from exported rows vs published artifact):")
    for g, c in summary["crosscheck"].items():
        print(f"  {g:>3} last4 {c['recomputed_last4']} vs {c['artifact_last4']} | "
              f"std {c['recomputed_std']} vs {c['artifact_std']} | "
              f"n {c['n_rows']} vs artifact {c['artifact_n_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
