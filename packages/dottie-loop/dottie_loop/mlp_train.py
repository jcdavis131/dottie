"""Train the orchestrator MLP router on CPU, from a router pack (numpy, no torch).

Same network and export format as ``apps/ava-factory/orchestrator_model.py``
(schema_version 1: sha256 hash buckets over 1-3 grams, six dense features,
one GELU-tanh hidden layer, softmax tier head, sigmoid risk head, linear cost
head), so :mod:`dottie_loop.mlp_infer` and the shared
``orchestrator_infer.py`` load its output unchanged. This one exists because
the router's own labels (``scout router pack``) should train where they are
made, on a laptop CPU, without torch or a GPU host.

Inputs: the pack's ``train.jsonl`` only (the holdouts are the gate's), with
each row's text (the record's ``goal_text`` when the owner opted in, else the
public benchmark text the pack joined from the committed goal set) and its
provenance weight (production 1.0, benchmark-verified 0.7). A row with no text
is skipped and counted: the MLP featurizes text, and a zero vector would teach
it nothing true. Targets: tier = the label; risk = the label's severity
(0 when absent); cost = ln(1 + measured tokens) (0 when unmeasured).

Output ``gate_passed`` is always false. Only ``scout router eval`` decides
that, and only a human stamp makes the weights authoritative.
numpy is imported inside functions, as in :mod:`dottie_loop.mlp_infer`.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from dottie_loop.backends import TIER_ORDER
from dottie_loop.errors import InvalidInputError
from dottie_loop.hashing import now_iso
from dottie_loop.mlp_infer import DENSE_FEATURES, featurize

_GELU_C = 0.7978845608028654


def training_rows(pack_dir: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """(rows, skipped counts) from a pack's train split: text, tier, weight, risk and cost targets."""
    pack_dir = Path(pack_dir)
    metas: dict[str, dict[str, Any]] = {}
    for line in (pack_dir / "provenance.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            m = json.loads(line)
            metas[m["id"]] = m
    rows: list[dict[str, Any]] = []
    skipped = {"no_text": 0, "no_tier_label": 0, "untrainable_provenance": 0}
    for line in (pack_dir / "train.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        meta = metas.get(rec["id"], {})
        tier = (rec["labels"].get("tier") or {}).get("choice")
        if tier not in TIER_ORDER:
            skipped["no_tier_label"] += 1
            continue
        weight = meta.get("weight")
        if not isinstance(weight, (int, float)) or weight <= 0:
            skipped["untrainable_provenance"] += 1
            continue
        text = rec["state"].get("goal_text") or meta.get("bench_text")
        if not text:
            skipped["no_text"] += 1
            continue
        tokens = meta.get("tokens")
        total = tokens.get("total") if isinstance(tokens, dict) else tokens
        rows.append({
            "id": rec["id"],
            "text": str(text),
            "tier": tier,
            "weight": float(weight),
            "provenance": meta.get("provenance"),
            "risk": float((rec["labels"].get("severity") or {}).get("score", 0.0)),
            "cost": math.log1p(float(total)) if isinstance(total, (int, float)) and total >= 0 else 0.0,
        })
    return rows, skipped


def _gelu(u: Any) -> tuple[Any, Any]:
    import numpy as np

    t = np.tanh(_GELU_C * (u + 0.044715 * u**3))
    g = 0.5 * u * (1.0 + t)
    dg = 0.5 * (1.0 + t) + 0.5 * u * (1.0 - t**2) * _GELU_C * (1.0 + 3 * 0.044715 * u**2)
    return g, dg


def train(
    rows: list[dict[str, Any]],
    *,
    n_buckets: int = 4096,
    embed_dim: int = 16,
    hidden_dim: int = 64,
    epochs: int = 300,
    lr: float = 0.01,
    seed: int = 0,
    risk_w: float = 0.5,
    cost_w: float = 0.1,
) -> dict[str, Any]:
    """Full-batch Adam on CPU. Returns ``{"doc": <schema_version-1 weights>, "history": [...]}``."""
    import numpy as np

    if len(rows) < 2:
        raise InvalidInputError(f"need >= 2 trainable rows with text; have {len(rows)}", field="pack")
    rng = np.random.default_rng(seed)
    n, n_t, n_d = len(rows), len(TIER_ORDER), len(DENSE_FEATURES)
    feats = [featurize(r["text"], n_buckets) for r in rows]
    dense = np.asarray([f["dense"] for f in feats], dtype=np.float64)
    mean, std = dense.mean(axis=0), dense.std(axis=0)
    dn = (dense - mean) / np.maximum(std, 1e-6)
    # sparse bag -> (row, bucket, count/denominator) triples for pooling and its gradient
    r_idx, b_idx, scale = [], [], []
    for i, f in enumerate(feats):
        denom = max(1.0, float(sum(f["bag"].values())))
        for b, c in f["bag"].items():
            r_idx.append(i)
            b_idx.append(b)
            scale.append(c / denom)
    r_idx_a, b_idx_a, scale_a = np.asarray(r_idx, dtype=np.int64), np.asarray(b_idx, dtype=np.int64), np.asarray(scale)
    y = np.asarray([TIER_ORDER.index(r["tier"]) for r in rows])
    w = np.asarray([r["weight"] for r in rows], dtype=np.float64)
    w = w / w.sum()
    risk_t = np.asarray([r["risk"] for r in rows], dtype=np.float64)
    cost_t = np.asarray([r["cost"] for r in rows], dtype=np.float64)

    p: dict[str, Any] = {
        "embedding": rng.normal(0.0, 0.1, (n_buckets, embed_dim)),
        "w1": rng.normal(0.0, math.sqrt(2.0 / (embed_dim + n_d + hidden_dim)), (embed_dim + n_d, hidden_dim)),
        "b1": np.zeros(hidden_dim),
        "w_tier": rng.normal(0.0, math.sqrt(2.0 / (hidden_dim + n_t)), (hidden_dim, n_t)),
        "b_tier": np.zeros(n_t),
        "w_risk": rng.normal(0.0, 0.05, hidden_dim),
        "b_risk": np.zeros(1),
        "w_cost": rng.normal(0.0, 0.05, hidden_dim),
        "b_cost": np.zeros(1),
    }
    m = {k: np.zeros_like(v) for k, v in p.items()}
    v2 = {k: np.zeros_like(v) for k, v in p.items()}
    history = []
    for step in range(1, epochs + 1):
        pooled = np.zeros((n, embed_dim))
        np.add.at(pooled, r_idx_a, scale_a[:, None] * p["embedding"][b_idx_a])
        x = np.concatenate([pooled, dn], axis=1)
        u = x @ p["w1"] + p["b1"]
        h, dh_du = _gelu(u)
        logits = h @ p["w_tier"] + p["b_tier"]
        logits -= logits.max(axis=1, keepdims=True)
        prob = np.exp(logits)
        prob /= prob.sum(axis=1, keepdims=True)
        risk = 1.0 / (1.0 + np.exp(-(h @ p["w_risk"] + p["b_risk"][0])))
        cost = h @ p["w_cost"] + p["b_cost"][0]
        ce = -np.log(prob[np.arange(n), y] + 1e-12)
        bce = -(risk_t * np.log(risk + 1e-12) + (1 - risk_t) * np.log(1 - risk + 1e-12))
        loss = float((w * (ce + risk_w * bce + cost_w * (cost - cost_t) ** 2)).sum())
        # backward
        d_logits = prob.copy()
        d_logits[np.arange(n), y] -= 1.0
        d_logits *= w[:, None]
        d_risk = (risk - risk_t) * w * risk_w
        d_cost = 2.0 * (cost - cost_t) * w * cost_w
        g: dict[str, Any] = {
            "w_tier": h.T @ d_logits, "b_tier": d_logits.sum(axis=0),
            "w_risk": h.T @ d_risk, "b_risk": np.asarray([d_risk.sum()]),
            "w_cost": h.T @ d_cost, "b_cost": np.asarray([d_cost.sum()]),
        }
        dh = d_logits @ p["w_tier"].T + np.outer(d_risk, p["w_risk"]) + np.outer(d_cost, p["w_cost"])
        du = dh * dh_du
        g["w1"] = x.T @ du
        g["b1"] = du.sum(axis=0)
        dx = du @ p["w1"].T
        g_emb = np.zeros_like(p["embedding"])
        np.add.at(g_emb, b_idx_a, scale_a[:, None] * dx[r_idx_a, :embed_dim])
        g["embedding"] = g_emb
        for k in p:  # Adam
            m[k] = 0.9 * m[k] + 0.1 * g[k]
            v2[k] = 0.999 * v2[k] + 0.001 * g[k] ** 2
            p[k] -= lr * (m[k] / (1 - 0.9**step)) / (np.sqrt(v2[k] / (1 - 0.999**step)) + 1e-8)
        if step == 1 or step % 50 == 0 or step == epochs:
            acc = float((prob.argmax(axis=1) == y).mean())
            history.append({"epoch": step, "loss": round(loss, 6), "train_accuracy": round(acc, 6)})

    def r1(a: Any) -> list[float]:
        return [round(float(x), 6) for x in a]

    doc = {
        "schema_version": 1,
        "gate_passed": False,
        "trained_at": now_iso(),
        "config": {"n_buckets": n_buckets, "embed_dim": embed_dim, "hidden_dim": hidden_dim,
                   "dense_features": list(DENSE_FEATURES), "tier_vocab": list(TIER_ORDER), "seed": seed},
        "norms": {"dense_mean": r1(mean), "dense_std": r1(std)},
        "weights": {
            "embedding": [r1(row) for row in p["embedding"]],
            "w1": [r1(row) for row in p["w1"]], "b1": r1(p["b1"]),
            "w_tier": [r1(row) for row in p["w_tier"]], "b_tier": r1(p["b_tier"]),
            "w_risk": r1(p["w_risk"]), "b_risk": round(float(p["b_risk"][0]), 6),
            "w_cost": r1(p["w_cost"]), "b_cost": round(float(p["b_cost"][0]), 6),
        },
    }
    return {"doc": doc, "history": history}


def train_pack(pack_dir: Path, out_path: Path, **kw: Any) -> dict[str, Any]:
    """Train on ``pack_dir``'s train split and write schema_version-1 weights to ``out_path``."""
    from collections import Counter

    pack_dir = Path(pack_dir)
    manifest = json.loads((pack_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    rows, skipped = training_rows(pack_dir)
    result = train(rows, **kw)
    doc = result["doc"]
    body = json.dumps(doc["weights"], sort_keys=True).encode("utf-8")
    doc["model_version"] = f"router-mlp-cpu-{manifest.get('pack')}-{hashlib.sha256(body).hexdigest()[:8]}"
    doc["provenance"] = {
        "trainer": "dottie_loop.mlp_train (numpy, CPU)",
        "pack": manifest.get("pack"),
        "pack_manifest_sha256": hashlib.sha256((pack_dir / "MANIFEST.json").read_bytes()).hexdigest(),
        "rows": len(rows),
        "rows_by_provenance": dict(Counter(r["provenance"] for r in rows)),
        "labels": dict(Counter(r["tier"] for r in rows)),
        "skipped": skipped,
        "history": result["history"],
        "note": "gate_passed is false until `scout router eval` passes; authority needs a human spot-check and stamp",
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc) + "\n", encoding="utf-8")
    return {"weights": str(out_path), "model_version": doc["model_version"], **doc["provenance"]}
