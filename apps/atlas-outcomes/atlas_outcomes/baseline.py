"""Stage 4: CPU baselines on the time-split holdout. Stdlib only.

Three predictors per question, fit on train (weighted by sample_weight, so the
downsampled easy negatives count at their natural rate) and scored on the
holdout (natural distribution, unweighted):

  climatology   the gauge's rate for the calendar month in train, shrunk to the gauge rate
  persistence   today's state carried forward: high_next <- flow above the threshold
                today; warn_next <- a warning in effect over the gauge at T;
                flow_change <- today's 1-day change bucket
  logistic      ridge logistic regression (IRLS) on the numeric features
                (flow_change: one-vs-rest, renormalised)

Noul questions: AUC, accuracy at 0.5, Brier. Score question: accuracy of the
most likely level, multi-class Brier, and mean absolute error of the expected
level. The report goes to data/baseline/ and is copied to BASELINE.json here.
These are the numbers a System One candidate has to beat on the same holdout.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from operator import mul
from pathlib import Path
from typing import Any

from . import PACK_VERSION
from .common import APP_ROOT, DATA, read_jsonl
from .curate import SEED, assemble
from .features import CHANGE_LEVELS, Corpus, bucket_of_change

RIDGE = 1.0
SHRINK = 20.0
FEATURES = [
    "pct_date", "pct_all", "log_flow_over_p90", "above_p90_today", "chg1", "chg3", "chg7",
    "up_present", "up_pct_date", "up_chg1", "up_chg3",
    "warn_active", "warn_gauge_30d", "warn_wfo_7d", "warn_wfo_1d", "doy_sin", "doy_cos",
]


def _lchg(c: float | None) -> float:
    if c is None:
        return 0.0
    return max(-3.0, min(3.0, math.log(max(0.01, 1.0 + c / 100.0))))


def vector(f: dict[str, Any]) -> list[float]:
    ang = 2.0 * math.pi * f["doy"] / 365.0
    up = f.get("up_site") is not None
    return [
        f["pct_date"] / 100.0,
        (50.0 if f["pct_all"] is None else f["pct_all"]) / 100.0,
        max(-6.0, min(6.0, math.log((f["flow"] + 1.0) / (f["p90"] + 1.0)))),
        1.0 if f["flow"] > f["p90"] else 0.0,
        _lchg(f["chg1"]), _lchg(f["chg3"]), _lchg(f["chg7"]),
        1.0 if up else 0.0,
        (f.get("up_pct_date") if up and f.get("up_pct_date") is not None else 50.0) / 100.0,
        _lchg(f.get("up_chg1")), _lchg(f.get("up_chg3")),
        1.0 if f["warn_active"] else 0.0,
        math.log1p(f["warn_gauge_30d"]), math.log1p(f["warn_wfo_7d"]), math.log1p(f["warn_wfo_1d"]),
        math.sin(ang), math.cos(ang),
    ]


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [[*row, b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        if abs(m[c][c]) < 1e-12:
            continue
        for r in range(n):
            if r != c and m[r][c]:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c], strict=True)]
    return [m[i][n] / m[i][i] if abs(m[i][i]) >= 1e-12 else 0.0 for i in range(n)]


class Standardizer:
    def __init__(self, xs: list[list[float]], w: list[float]):
        tw = sum(w)
        d = len(xs[0])
        self.mu = [sum(wi * x[j] for wi, x in zip(w, xs, strict=True)) / tw for j in range(d)]
        self.sd = []
        for j in range(d):
            var = sum(wi * (x[j] - self.mu[j]) ** 2 for wi, x in zip(w, xs, strict=True)) / tw
            self.sd.append(math.sqrt(var) or 1.0)

    def cols(self, xs: list[list[float]]) -> list[list[float]]:
        """Column-major, standardized, with an intercept column first."""
        out = [[1.0] * len(xs)]
        for j in range(len(self.mu)):
            mu, sd = self.mu[j], self.sd[j]
            out.append([(x[j] - mu) / sd for x in xs])
        return out


def fit_logistic(cols: list[list[float]], y: list[float], w: list[float], ridge: float = RIDGE, iters: int = 30) -> list[float]:
    """Weighted ridge logistic regression by IRLS (Newton). The intercept is not penalised."""
    d, n = len(cols), len(y)
    beta = [0.0] * d
    for _ in range(iters):
        eta = [0.0] * n
        for j in range(d):
            if beta[j]:
                bj = beta[j]
                eta = [e + bj * x for e, x in zip(eta, cols[j], strict=True)]
        p = [_sigmoid(e) for e in eta]
        r = [wi * (yi - pi) for wi, yi, pi in zip(w, y, p, strict=True)]
        ww = [wi * pi * (1.0 - pi) for wi, pi in zip(w, p, strict=True)]
        grad = [sum(map(mul, cols[j], r)) - (ridge * beta[j] if j else 0.0) for j in range(d)]
        hess = [[0.0] * d for _ in range(d)]
        for i in range(d):
            wc = list(map(mul, ww, cols[i]))
            for j in range(i, d):
                hess[i][j] = hess[j][i] = sum(map(mul, wc, cols[j]))
            if i:
                hess[i][i] += ridge
        step = _solve(hess, grad)
        beta = [b + s for b, s in zip(beta, step, strict=True)]
        if max(abs(s) for s in step) < 1e-7:
            break
    return beta


def predict(beta: list[float], cols: list[list[float]]) -> list[float]:
    n = len(cols[0])
    eta = [0.0] * n
    for j, bj in enumerate(beta):
        eta = [e + bj * x for e, x in zip(eta, cols[j], strict=True)]
    return [_sigmoid(e) for e in eta]


def auc(scores: list[float], y: list[int]) -> float | None:
    pos = sum(y)
    neg = len(y) - pos
    if not pos or not neg:
        return None
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    u = sum(r for r, yi in zip(ranks, y, strict=True) if yi) - pos * (pos + 1) / 2.0
    return u / (pos * neg)


def noul_metrics(p: list[float], y: list[int]) -> dict[str, Any]:
    a = auc(p, y)
    return {
        "auc": None if a is None else round(a, 4),
        "accuracy": round(sum((pi >= 0.5) == bool(yi) for pi, yi in zip(p, y, strict=True)) / len(y), 4),
        "brier": round(sum((pi - yi) ** 2 for pi, yi in zip(p, y, strict=True)) / len(y), 5),
    }


def score_metrics(dists: list[list[float]], y: list[int]) -> dict[str, Any]:
    k = len(CHANGE_LEVELS)
    acc = sum(max(range(k), key=lambda c: d[c]) == yi for d, yi in zip(dists, y, strict=True)) / len(y)
    brier = sum(sum((d[c] - (1.0 if c == yi else 0.0)) ** 2 for c in range(k)) for d, yi in zip(dists, y, strict=True)) / len(y)
    mae = sum(abs(sum(c * d[c] for c in range(k)) - yi) for d, yi in zip(dists, y, strict=True)) / len(y)
    return {"accuracy": round(acc, 4), "brier_multiclass": round(brier, 5), "mae_expected_level": round(mae, 4)}


def climatology(train: list[dict[str, Any]], key: str, classes: int | None = None) -> Any:
    """(site, month) -> rate (noul) or distribution (score), shrunk to the site, then to the whole train."""
    k = classes or 2

    def target(v: dict[str, Any]) -> int:
        lab = v["row"]["labels"][key]
        return int(lab) if classes is None else lab

    glob = [0.0] * k
    site: dict[str, list[float]] = defaultdict(lambda: [0.0] * k)
    cell: dict[tuple[str, int], list[float]] = defaultdict(lambda: [0.0] * k)
    for v in train:
        w, c = v["meta"]["sample_weight"], target(v)
        glob[c] += w
        site[v["meta"]["site"]][c] += w
        cell[(v["meta"]["site"], v["row"]["features"]["month"])][c] += w
    gt = sum(glob)
    gd = [x / gt for x in glob]

    def shrink(counts: list[float], prior: list[float]) -> list[float]:
        t = sum(counts)
        return [(counts[c] + SHRINK * prior[c]) / (t + SHRINK) for c in range(k)]

    def dist(s: str, month: int) -> list[float]:
        sd = shrink(site[s], gd) if s in site else gd
        return shrink(cell[(s, month)], sd) if (s, month) in cell else sd

    return dist


def run(seed: int = SEED) -> dict[str, Any]:
    kept, info = assemble(Corpus.load(), seed)
    train = [v for v in kept if v["meta"]["split"] == "train"]
    hold = [v for v in kept if v["meta"]["split"] == "holdout"]
    xtr = [vector(v["row"]["features"]) for v in train]
    xho = [vector(v["row"]["features"]) for v in hold]
    w = [v["meta"]["sample_weight"] for v in train]
    st = Standardizer(xtr, w)
    ctr, cho = st.cols(xtr), st.cols(xho)
    report: dict[str, Any] = {
        "holdout": {"rows": len(hold), "days": [info["first_holdout_day"], info["last_day"]]},
        "train": {"rows": len(train), "weighted_rows": round(sum(w), 1)},
        "features": FEATURES,
        "questions": {},
    }
    for key in ("high_next", "warn_next"):
        ytr = [1.0 if v["row"]["labels"][key] else 0.0 for v in train]
        yho = [1 if v["row"]["labels"][key] else 0 for v in hold]
        clim = climatology(train, key)
        p_clim = [clim(v["meta"]["site"], v["row"]["features"]["month"])[1] for v in hold]
        if key == "high_next":
            p_pers = [1.0 if v["row"]["features"]["flow"] > v["row"]["features"]["p90"] else 0.0 for v in hold]
        else:
            p_pers = [1.0 if v["row"]["features"]["warn_active"] else 0.0 for v in hold]
        beta = fit_logistic(ctr, ytr, w)
        p_lr = predict(beta, cho)
        report["questions"][key] = {
            "type": "noul",
            "holdout_positives": sum(yho),
            "holdout_rate": round(sum(yho) / len(yho), 4),
            "climatology": noul_metrics(p_clim, yho),
            "persistence": noul_metrics(p_pers, yho),
            "logistic": noul_metrics(p_lr, yho),
            "logistic_weights": dict(zip(["intercept", *FEATURES], [round(b, 4) for b in beta], strict=True)),
        }
    k = len(CHANGE_LEVELS)
    yho = [v["row"]["labels"]["change_bucket"] for v in hold]
    clim = climatology(train, "change_bucket", classes=k)
    d_clim = [clim(v["meta"]["site"], v["row"]["features"]["month"]) for v in hold]
    d_pers = []
    for v in hold:
        f = v["row"]["features"]
        b = 2 if f["chg1"] is None else bucket_of_change(f["chg1"])
        d_pers.append([1.0 if c == b else 0.0 for c in range(k)])
    per_class = []
    for c in range(k):
        yc = [1.0 if v["row"]["labels"]["change_bucket"] == c else 0.0 for v in train]
        per_class.append(predict(fit_logistic(ctr, yc, w), cho))
    d_lr = []
    for i in range(len(hold)):
        s = sum(per_class[c][i] for c in range(k))
        d_lr.append([per_class[c][i] / s for c in range(k)])
    report["questions"]["flow_change"] = {
        "type": "score",
        "holdout_levels": {CHANGE_LEVELS[c]: yho.count(c) for c in range(k)},
        "climatology": score_metrics(d_clim, yho),
        "persistence": score_metrics(d_pers, yho),
        "logistic": score_metrics(d_lr, yho),
    }
    out = DATA / "baseline"
    out.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    (out / "baseline_report.json").write_text(text, encoding="utf-8")
    (APP_ROOT / "BASELINE.json").write_text(text, encoding="utf-8")
    return report


def score_predictions(pred_path: Path, pack: str = PACK_VERSION) -> dict[str, Any]:
    """A candidate's holdout answers, one JSON line {"id", "answers": {qid: /decide answer}}, on the baseline metrics."""
    hold = {r["id"]: r for r in read_jsonl(DATA / "packs" / pack / "holdout.jsonl")}
    preds = {p["id"]: p["answers"] for p in read_jsonl(pred_path) if p.get("id") in hold}
    if not preds:
        raise SystemExit(f"no prediction ids match {pack}/holdout.jsonl")
    ids = sorted(preds)
    out: dict[str, Any] = {"pack": pack, "holdout_rows": len(hold), "scored_rows": len(ids)}
    for key in ("high_next", "warn_next"):
        y = [int(hold[i]["labels"][key]["noul"] >= 0.5) for i in ids]
        out[key] = noul_metrics([float(preds[i][key]["noul"]) for i in ids], y)
    k = len(CHANGE_LEVELS)
    y = [round(hold[i]["labels"]["flow_change"]["score"]) for i in ids]
    dists = [[float(preds[i]["flow_change"]["probabilities"][str(c)]) for c in range(k)] for i in ids]
    out["flow_change"] = score_metrics(dists, y)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--score", type=Path, default=None, help="score a candidate's holdout predictions (JSONL) instead of fitting baselines")
    args = ap.parse_args(argv)
    if args.score:
        print(json.dumps(score_predictions(args.score), indent=2))
        return 0
    r = run(args.seed)
    for q, m in r["questions"].items():
        print(q, json.dumps({k: m[k] for k in ("climatology", "persistence", "logistic")}))
    return 0
