"""The orchestrator MLP forward pass (schema_version 1), numpy imported lazily.

In-package copy of the frozen featurize + forward contract that
``apps/ava-factory/orchestrator_infer.py`` also implements. It exists so the
router's :class:`dottie_loop.backends.LearnedMLPBackend` works where the
ava-factory tree is absent (an installed scout, the harness-api bundle). The
math is pinned: sha256 hash buckets over 1-3 grams, six dense features in
config order, GELU (tanh) hidden layer, softmax tier head, sigmoid risk,
linear cost. Change it in ava-factory first, then here.

numpy is imported inside each function so importing this module never needs it.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import TYPE_CHECKING, Any

from dottie_loop.backends import _TOKEN_RE, CODE_TERMS, chain_signals

if TYPE_CHECKING:
    from pathlib import Path

SCHEMA_VERSION = 1
DENSE_FEATURES = ("n_words", "n_chain_signals", "has_code_terms", "latency_ms", "tokens_est", "attempt")
_N_DENSE = 6
_STD_FLOOR = 1e-6
_GELU_C = 0.7978845608028654  # sqrt(2/pi) at contract precision


def load_weights(path: Path) -> dict:
    """Parse + shape-validate champion_weights.json; raises ValueError on mismatch."""
    import numpy as np

    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported schema_version {doc.get('schema_version')!r} (expected {SCHEMA_VERSION})"
        )
    for key in ("config", "norms", "weights", "model_version"):
        if key not in doc:
            raise ValueError(f"missing required key '{key}'")
    cfg = doc["config"]
    for key in ("n_buckets", "embed_dim", "hidden_dim", "dense_features", "tier_vocab"):
        if key not in cfg:
            raise ValueError(f"config block missing required key '{key}'")
    n_buckets = int(cfg["n_buckets"])
    embed_dim = int(cfg["embed_dim"])
    hidden_dim = int(cfg["hidden_dim"])
    n_dense = len(cfg["dense_features"])
    n_tiers = len(cfg["tier_vocab"])
    if n_dense != _N_DENSE:
        raise ValueError(f"expected {_N_DENSE} dense_features, got {n_dense}")

    def arr(name: str, raw: Any, shape: tuple) -> np.ndarray:
        try:
            a = np.asarray(raw, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"field '{name}' is not numeric: {exc}") from exc
        if a.shape != shape:
            raise ValueError(f"field '{name}' has shape {a.shape}, expected {shape}")
        return a

    norms_raw = doc["norms"]
    w_raw = doc["weights"]
    norms = {
        "dense_mean": arr("norms.dense_mean", norms_raw.get("dense_mean"), (n_dense,)),
        "dense_std": arr("norms.dense_std", norms_raw.get("dense_std"), (n_dense,)),
    }
    weights = {
        "embedding": arr("embedding", w_raw.get("embedding"), (n_buckets, embed_dim)),
        "w1": arr("w1", w_raw.get("w1"), (embed_dim + n_dense, hidden_dim)),
        "b1": arr("b1", w_raw.get("b1"), (hidden_dim,)),
        "w_tier": arr("w_tier", w_raw.get("w_tier"), (hidden_dim, n_tiers)),
        "b_tier": arr("b_tier", w_raw.get("b_tier"), (n_tiers,)),
        "w_risk": arr("w_risk", w_raw.get("w_risk"), (hidden_dim,)),
        "w_cost": arr("w_cost", w_raw.get("w_cost"), (hidden_dim,)),
    }
    for scalar in ("b_risk", "b_cost"):
        if not isinstance(w_raw.get(scalar), (int, float)) or isinstance(w_raw.get(scalar), bool):
            raise ValueError(f"field '{scalar}' must be a scalar float")
        weights[scalar] = float(w_raw[scalar])

    return {
        "model_version": doc["model_version"],
        "gate_passed": bool(doc.get("gate_passed", False)),
        "config": cfg,
        "norms": norms,
        "weights": weights,
    }


def featurize(goal: str, n_buckets: int) -> dict[str, Any]:
    """Hash-bucket bag of 1-3 grams and the six dense features (in :data:`DENSE_FEATURES` order).

    sha256 buckets, NEVER Python ``hash()`` (per-process randomized). The
    chain-signal count is MoMA-lite's own; latency/tokens/attempt are fixed at
    serve time (0, 0, 1), the frozen contract. :mod:`dottie_loop.mlp_train`
    trains on exactly this.
    """
    toks = _TOKEN_RE.findall(goal.lower())
    bag: dict[int, float] = {}
    for n in (1, 2, 3):
        for i in range(len(toks) - n + 1):
            gram = " ".join(toks[i : i + n])
            bucket = int.from_bytes(hashlib.sha256(gram.encode("utf-8")).digest()[:8], "big") % n_buckets
            bag[bucket] = bag.get(bucket, 0.0) + 1.0
    dense = [float(len(goal.split())), float(chain_signals(goal)),
             1.0 if any(t in CODE_TERMS for t in toks) else 0.0, 0.0, 0.0, 1.0]
    return {"bag": bag, "dense": dense}


def predict(model: dict, goal: str) -> dict:
    """Pinned float64 forward pass (mirror of the shared module's featurize+forward)."""
    import numpy as np

    cfg = model["config"]
    n_buckets = int(cfg["n_buckets"])
    w = model["weights"]

    feats = featurize(goal, n_buckets)
    bag = feats["bag"]
    embedding = w["embedding"]
    if bag:
        ids = np.asarray(list(bag.keys()), dtype=np.int64)
        cts = np.asarray(list(bag.values()), dtype=np.float64)
        pooled = (cts[:, None] * embedding[ids]).sum(axis=0) / max(1.0, float(cts.sum()))
    else:
        pooled = np.zeros(embedding.shape[1], dtype=np.float64)
    dense_map = dict(zip(DENSE_FEATURES, feats["dense"], strict=True))
    dense_vec = np.asarray([dense_map.get(f, 0.0) for f in cfg["dense_features"]], dtype=np.float64)
    dn = (dense_vec - model["norms"]["dense_mean"]) / np.maximum(model["norms"]["dense_std"], _STD_FLOOR)

    x = np.concatenate([pooled, dn])
    u = x @ w["w1"] + w["b1"]
    h = 0.5 * u * (1.0 + np.tanh(_GELU_C * (u + 0.044715 * u**3)))
    tier_logits = h @ w["w_tier"] + w["b_tier"]
    e = np.exp(tier_logits - np.max(tier_logits))
    tier_probs = e / e.sum()
    risk = 1.0 / (1.0 + math.exp(-(float(h @ w["w_risk"]) + w["b_risk"])))
    cost = float(h @ w["w_cost"]) + w["b_cost"]
    return {
        "tier": cfg["tier_vocab"][int(np.argmax(tier_probs))],
        "tier_probs": tier_probs,
        "risk": float(risk),
        "cost": float(cost),
        "model_version": model["model_version"],
        "gate_passed": model["gate_passed"],
    }
