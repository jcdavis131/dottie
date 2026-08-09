"""Vendored numpy inference for the orchestrator router — numpy + stdlib ONLY.

This is a VENDORED COPY kept in sync with apps/ava-factory/orchestrator_infer.py.
The featurize + forward math is a frozen cross-lane contract (schema_version 1);
any change to the pinned math must land there first and be mirrored here
byte-for-byte. The only local adaptation is ``predict`` returning a fully
JSON-serializable dict (tier_probs as a plain list, no ndarray logits) because
this copy feeds an HTTP response body directly.

Weights JSON schema (schema_version 1), matrices in x@W orientation:
{schema_version:1, model_version, gate_passed, trained_at, provenance,
 config:{n_buckets, embed_dim, hidden_dim,
         dense_features:["n_words","n_chain_signals","has_code_terms",
                         "latency_ms","tokens_est","attempt"],
         tier_vocab:["deterministic","llm","deep_research",
                     "action_operator","agentic_epic"], seed},
 norms:{dense_mean[6], dense_std[6]},
 weights:{embedding[n_buckets][embed_dim], w1[embed_dim+6][hidden], b1[hidden],
          w_tier[hidden][5], b_tier[5], w_risk[hidden], b_risk,
          w_cost[hidden], b_cost}}
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

# Tokens that mark a goal as code/engineering-flavoured. Shared repo-wide —
# consumers must use this exact set (do not fork it locally).
CODE_TERMS = {
    "code", "build", "test", "deploy", "api", "bug", "fix", "refactor",
    "cli", "pipeline", "json", "python", "script", "repo", "harness",
}

# Matches the chain-signal expression of apps/scout-cli/bigbang/plugins/harness/cli.py:64.
_CHAIN_RE = re.compile(r"(->|then|after|next|→)")
_TOKEN_RE = re.compile(r"[a-z0-9]+")

_SCHEMA_VERSION = 1
_N_DENSE = 6
_STD_FLOOR = 1e-6
# sqrt(2/pi) to the precision pinned by the contract.
_GELU_C = 0.7978845608028654


def _cfg_field(config: Any, key: str) -> Any:
    """Read a config field from either a mapping or an attribute-style object."""
    if isinstance(config, dict):
        return config[key]
    return getattr(config, key)


def featurize(
    goal_text: str, dense: dict | None, config: Any
) -> tuple[list[int], list[float], np.ndarray]:
    """Hash-bucket bag-of-ngrams + dense feature vector for one goal.

    Buckets come from sha256 (NEVER Python ``hash()``, which is randomized per
    process). Returns parallel ``bucket_ids``/``counts`` lists (one entry per
    distinct bucket, insertion-ordered) and a float64 dense vector following
    ``config['dense_features']`` order.
    """
    n_buckets = int(_cfg_field(config, "n_buckets"))
    dense_features = list(_cfg_field(config, "dense_features"))

    toks = _TOKEN_RE.findall(goal_text.lower())
    bag: dict[int, float] = {}
    for n in (1, 2, 3):
        for i in range(len(toks) - n + 1):
            gram = " ".join(toks[i : i + n])
            bucket = (
                int.from_bytes(hashlib.sha256(gram.encode("utf-8")).digest()[:8], "big")
                % n_buckets
            )
            bag[bucket] = bag.get(bucket, 0.0) + 1.0

    dense = dense or {}
    dense_vec = np.zeros(len(dense_features), dtype=np.float64)
    for j, feat in enumerate(dense_features):
        val = dense.get(feat)
        if val is None:
            dense_vec[j] = 0.0
        elif isinstance(val, bool):
            dense_vec[j] = 1.0 if val else 0.0
        else:
            dense_vec[j] = float(val)

    return list(bag.keys()), list(bag.values()), dense_vec


def _gelu_tanh(u: np.ndarray) -> np.ndarray:
    """Tanh-approximation GELU — matches the training-side activation exactly."""
    return 0.5 * u * (1.0 + np.tanh(_GELU_C * (u + 0.044715 * u**3)))


def _softmax(logits: np.ndarray) -> np.ndarray:
    e = np.exp(logits - np.max(logits))
    return e / e.sum()


def _as_f64(name: str, raw: Any, shape: tuple[int, ...]) -> np.ndarray:
    try:
        arr = np.asarray(raw, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"weights field '{name}' is not numeric: {exc}") from exc
    if arr.shape != shape:
        raise ValueError(
            f"weights field '{name}' has shape {arr.shape}, expected {shape}"
        )
    return arr


def load_weights(path: str | Path) -> dict:
    """Parse and validate a champion_weights.json (schema_version 1).

    Converts all weight/norm payloads to float64 numpy arrays and checks every
    shape against the config block. Raises ``ValueError`` with a specific
    message on any mismatch — a bad weights file must fail loudly at load
    time, not silently misroute at inference time.
    """
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        doc = json.load(fh)

    if doc.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError(
            f"unsupported schema_version {doc.get('schema_version')!r} "
            f"(expected {_SCHEMA_VERSION}) in {path}"
        )
    for key in ("config", "norms", "weights", "model_version"):
        if key not in doc:
            raise ValueError(f"weights file {path} missing required key '{key}'")

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

    norms_raw = doc["norms"]
    norms = {
        "dense_mean": _as_f64("norms.dense_mean", norms_raw.get("dense_mean"), (n_dense,)),
        "dense_std": _as_f64("norms.dense_std", norms_raw.get("dense_std"), (n_dense,)),
    }

    w_raw = doc["weights"]
    weights = {
        "embedding": _as_f64("embedding", w_raw.get("embedding"), (n_buckets, embed_dim)),
        "w1": _as_f64("w1", w_raw.get("w1"), (embed_dim + n_dense, hidden_dim)),
        "b1": _as_f64("b1", w_raw.get("b1"), (hidden_dim,)),
        "w_tier": _as_f64("w_tier", w_raw.get("w_tier"), (hidden_dim, n_tiers)),
        "b_tier": _as_f64("b_tier", w_raw.get("b_tier"), (n_tiers,)),
        "w_risk": _as_f64("w_risk", w_raw.get("w_risk"), (hidden_dim,)),
        "w_cost": _as_f64("w_cost", w_raw.get("w_cost"), (hidden_dim,)),
    }
    for scalar in ("b_risk", "b_cost"):
        if not isinstance(w_raw.get(scalar), (int, float)):
            raise ValueError(f"weights field '{scalar}' must be a scalar float")
        weights[scalar] = float(w_raw[scalar])

    return {
        "schema_version": doc["schema_version"],
        "model_version": doc["model_version"],
        "gate_passed": bool(doc.get("gate_passed", False)),
        "trained_at": doc.get("trained_at"),
        "provenance": doc.get("provenance", {}),
        "config": cfg,
        "norms": norms,
        "weights": weights,
    }


def forward(
    w: dict, bucket_ids: list[int], counts: list[float], dense_vec: np.ndarray
) -> dict:
    """Pinned float64 forward pass over loaded weights ``w`` (from load_weights)."""
    wt = w["weights"]
    embedding = wt["embedding"]
    embed_dim = embedding.shape[1]

    if bucket_ids:
        ids = np.asarray(bucket_ids, dtype=np.int64)
        cts = np.asarray(counts, dtype=np.float64)
        pooled = (cts[:, None] * embedding[ids]).sum(axis=0) / max(1.0, float(cts.sum()))
    else:
        pooled = np.zeros(embed_dim, dtype=np.float64)

    dn = (np.asarray(dense_vec, dtype=np.float64) - w["norms"]["dense_mean"]) / np.maximum(
        w["norms"]["dense_std"], _STD_FLOOR
    )
    x = np.concatenate([pooled, dn])
    h = _gelu_tanh(x @ wt["w1"] + wt["b1"])

    tier_logits = h @ wt["w_tier"] + wt["b_tier"]
    tier_probs = _softmax(tier_logits)
    tier = w["config"]["tier_vocab"][int(np.argmax(tier_probs))]
    risk = 1.0 / (1.0 + math.exp(-(float(h @ wt["w_risk"]) + wt["b_risk"])))
    cost = float(h @ wt["w_cost"]) + wt["b_cost"]

    return {
        "tier_logits": tier_logits,
        "tier_probs": tier_probs,
        "tier": tier,
        "risk": float(risk),
        "cost": float(cost),
    }


def predict(w: dict, goal_text: str, dense: dict | None = None) -> dict:
    """Predict tier/risk/cost for a goal; JSON-serializable output.

    Derives default dense features from the goal itself (caller-supplied
    ``dense`` entries override). The derived chain-signal expression is the
    exact expression of apps/scout-cli/bigbang/plugins/harness/cli.py:64.
    """
    lower = goal_text.lower()
    toks = _TOKEN_RE.findall(lower)
    n_words = len(goal_text.split())
    n_chain_signals = len(_CHAIN_RE.findall(lower)) + (
        1 if " and " in lower and n_words > 10 else 0
    )
    defaults = {
        "n_words": float(n_words),
        "n_chain_signals": float(n_chain_signals),
        "has_code_terms": 1.0 if any(t in CODE_TERMS for t in toks) else 0.0,
        "latency_ms": 0.0,
        "tokens_est": 0.0,
        "attempt": 1.0,
    }
    if dense:
        defaults.update(dense)

    bucket_ids, counts, dense_vec = featurize(goal_text, defaults, w["config"])
    out = forward(w, bucket_ids, counts, dense_vec)
    return {
        "tier": out["tier"],
        "tier_probs": [float(p) for p in out["tier_probs"]],
        "risk": out["risk"],
        "cost": out["cost"],
        "model_version": w["model_version"],
        "gate_passed": w["gate_passed"],
    }
