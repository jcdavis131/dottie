#!/usr/bin/env python3
"""Aggregate bench/results.json into per-workflow + category metrics.

Usage: python3 bench/metrics.py [--in DIR] [--out DIR]

Writes <out>/metrics.json with, per workflow: runs, success_rate, p50/p95
latency_ms, total tokens_est, and a 0..1 score (success_rate; blocked=0).
Also emits category rollups and a single harness score.
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    f, c = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[f] + (xs[c] - xs[f]) * (k - f), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=str(HERE / "out"))
    ap.add_argument("--out", dest="out", default=str(HERE / "out"))
    args = ap.parse_args()

    res = json.loads((Path(args.inp) / "results.json").read_text())["results"]
    per, cats = {}, {}
    for r in res:
        lat = [r["latency_ms"]] if r.get("latency_ms") is not None else []
        ok = bool(r.get("ok"))
        per[r["id"]] = {
            "name": r["name"], "category": r.get("category"),
            "runs": 1, "success_rate": 1.0 if ok else 0.0,
            "status": r.get("status", "ran"),
            "p50_latency_ms": pct(lat, 0.5), "p95_latency_ms": pct(lat, 0.95),
            "tokens_est": r.get("tokens_est", 0),
            "exit_code": r.get("exit_code"),
            "correctness": r.get("correctness", ""),
            "score": 1.0 if ok else 0.0,
        }
        cat = r.get("category", "uncategorized")
        cats.setdefault(cat, {"workflows": [], "scores": []})
        cats[cat]["workflows"].append(r["id"])
        cats[cat]["scores"].append(1.0 if ok else 0.0)

    cat_roll = {c: {"n": len(v["workflows"]), "workflows": v["workflows"],
                    "mean_score": round(sum(v["scores"]) / len(v["scores"]), 3)}
                for c, v in cats.items()}
    all_scores = [p["score"] for p in per.values()]
    metrics = {
        "n_workflows": len(per),
        "harness_score": round(sum(all_scores) / len(all_scores), 3) if all_scores else 0.0,
        "n_ok": sum(1 for p in per.values() if p["score"] == 1.0),
        "n_blocked": sum(1 for p in per.values() if p["status"] == "blocked"),
        "total_tokens_est": sum(p["tokens_est"] for p in per.values()),
        "per_workflow": per,
        "by_category": cat_roll,
        "notes": ("tokens_est is a chars/4 heuristic on captured subprocess "
                  "output — an estimate, not metered LLM usage. score=1 only on "
                  "checker pass; blocked counts as 0, never as success."),
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(f"metrics: harness_score={metrics['harness_score']} "
          f"ok={metrics['n_ok']}/{metrics['n_workflows']} "
          f"blocked={metrics['n_blocked']} tokens_est={metrics['total_tokens_est']}")
    print(f"metrics: wrote {out / 'metrics.json'}")


if __name__ == "__main__":
    main()
