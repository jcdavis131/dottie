"""
harness learned router — optional learned-tier augmentation for `scout harness route --learned`.

Loads the champion weights exported by the orchestrator lane
(apps/ava-factory/reports/orchestrator/champion_weights.json, schema_version 1)
and runs the pinned numpy forward pass to predict a tier / risk / cost for the
goal. The heuristic route envelope stays authoritative: this module only ADDS
keys on top of it.

Provenance-honest contract:
  * success adds learned_tier / learned_probs / risk / cost / model_version /
    gate_passed / learned_source="champion_weights" / infer_impl;
  * any failure (weights missing, weights invalid, numpy unavailable, any
    exception) adds learned_tier=None / learned_fallback="heuristic" /
    learned_reason="<specific reason>" instead — the envelope always says WHY
    it fell back.

learned_route NEVER raises. The caller (cli.py route_cmd) imports this module
lazily for the same reason: plugin discovery (bigbang/core/plugin_loader.py:39-52)
silently swallows plugin import errors, so a module-level defect here would
make the whole harness plugin vanish from the CLI.

Inference implementation, two stages (ava-factory is outside the uv workspace,
so package import is impossible):
  (a) preferred: file-path import of the shared inference module
      apps/ava-factory/orchestrator_infer.py (override: SCOUT_ORCH_INFER);
  (b) fallback: the self-contained numpy implementation below of the FROZEN
      schema_version-1 featurize + forward contract (the shared module is
      built by a parallel lane and may be absent).
Which one served is recorded as infer_impl "shared_module" | "internal".
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
from pathlib import Path
from typing import Any

# .../apps/scout-cli/bigbang/plugins/harness/learned_router.py -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[5]
_DEFAULT_WEIGHTS = _REPO_ROOT / "apps" / "ava-factory" / "reports" / "orchestrator" / "champion_weights.json"
_DEFAULT_INFER = _REPO_ROOT / "apps" / "ava-factory" / "orchestrator_infer.py"

_SCHEMA_VERSION = 1
_N_DENSE = 6
_STD_FLOOR = 1e-6
_GELU_C = 0.7978845608028654  # sqrt(2/pi) at contract precision

# Fallback tier vocab when a (test-supplied) shared module returns a model
# without a config block; the real contract always carries tier_vocab.
_TIER_VOCAB = ["deterministic", "llm", "deep_research", "action_operator", "agentic_epic"]

# Shared repo-wide code/engineering token set — must match
# apps/ava-factory/orchestrator_infer.py CODE_TERMS exactly (frozen contract).
_CODE_TERMS = {
    "code", "build", "test", "deploy", "api", "bug", "fix", "refactor",
    "cli", "pipeline", "json", "python", "script", "repo", "harness",
}

# Matches the chain-signal expression of cli.py:64.
_CHAIN_RE = re.compile(r"(->|then|after|next|→)")
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Module-level cache keyed by (weights path, mtime) so repeated in-process
# calls don't re-read 2.5 MB of JSON (CLI subprocesses are always cold anyway).
# Value: (model_dict, infer_impl, infer_module_or_None)
_MODEL_CACHE: dict[tuple, tuple] = {}


def _fallback(reason: str) -> dict:
    return {"learned_tier": None, "learned_fallback": "heuristic", "learned_reason": reason}


def _resolve_weights_path() -> Path:
    env = os.environ.get("SCOUT_ORCH_MODEL")
    return Path(env) if env else _DEFAULT_WEIGHTS


def _load_shared_infer():
    """File-path import of the shared inference module; None on any failure."""
    env = os.environ.get("SCOUT_ORCH_INFER")
    path = Path(env) if env else _DEFAULT_INFER
    try:
        if not path.exists():
            return None
        spec = importlib.util.spec_from_file_location("orch_infer", str(path))
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if callable(getattr(mod, "load_weights", None)) and callable(getattr(mod, "predict", None)):
            return mod
        return None
    except Exception:
        return None


# --- internal implementation of the frozen schema_version-1 contract ------------

def _internal_load_weights(path: Path) -> dict:
    """Parse + shape-validate champion_weights.json; raises ValueError on mismatch."""
    import numpy as np

    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema_version") != _SCHEMA_VERSION:
        raise ValueError(
            f"unsupported schema_version {doc.get('schema_version')!r} (expected {_SCHEMA_VERSION})"
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


def _internal_predict(model: dict, goal: str) -> dict:
    """Pinned float64 forward pass (mirror of the shared module's featurize+forward)."""
    import numpy as np

    cfg = model["config"]
    n_buckets = int(cfg["n_buckets"])
    w = model["weights"]

    # hash-bucket bag of 1-,2-,3-grams — sha256, NEVER Python hash() (per-process randomized)
    toks = _TOKEN_RE.findall(goal.lower())
    bag: dict[int, float] = {}
    for n in (1, 2, 3):
        for i in range(len(toks) - n + 1):
            gram = " ".join(toks[i : i + n])
            bucket = int.from_bytes(hashlib.sha256(gram.encode("utf-8")).digest()[:8], "big") % n_buckets
            bag[bucket] = bag.get(bucket, 0.0) + 1.0
    embedding = w["embedding"]
    if bag:
        ids = np.asarray(list(bag.keys()), dtype=np.int64)
        cts = np.asarray(list(bag.values()), dtype=np.float64)
        pooled = (cts[:, None] * embedding[ids]).sum(axis=0) / max(1.0, float(cts.sum()))
    else:
        pooled = np.zeros(embedding.shape[1], dtype=np.float64)

    # dense features in config order; chain-signal expression matches cli.py:64
    lower = goal.lower()
    n_words = len(goal.split())
    n_chain_signals = len(_CHAIN_RE.findall(lower)) + (1 if " and " in lower and n_words > 10 else 0)
    dense_map = {
        "n_words": float(n_words),
        "n_chain_signals": float(n_chain_signals),
        "has_code_terms": 1.0 if any(t in _CODE_TERMS for t in toks) else 0.0,
        "latency_ms": 0.0,
        "tokens_est": 0.0,
        "attempt": 1.0,
    }
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


# --- public API -----------------------------------------------------------------

def learned_route(goal: str, heuristic: dict) -> dict:
    """Return keys to merge into the route envelope. Never raises.

    ``heuristic`` is the already-built route envelope; it is accepted for
    signature stability (future blending) but the learned pass is computed
    from the goal text alone — the heuristic fields stay untouched.
    """
    try:
        try:
            import numpy  # noqa: F401 — availability probe only; scout-cli does not pin numpy
        except ImportError:
            return _fallback("numpy unavailable")

        path = _resolve_weights_path()
        if not path.exists():
            return _fallback(f"weights not found at {path}")

        key = (str(path), path.stat().st_mtime)
        cached = _MODEL_CACHE.get(key)
        if cached is None:
            infer_mod = _load_shared_infer()
            if infer_mod is not None:
                impl = "shared_module"
                try:
                    model = infer_mod.load_weights(path)
                except Exception as exc:
                    return _fallback(f"weights invalid: {exc}")
            else:
                impl = "internal"
                try:
                    model = _internal_load_weights(path)
                except Exception as exc:
                    return _fallback(f"weights invalid: {exc}")
            _MODEL_CACHE.clear()  # single-entry cache — one champion per process
            _MODEL_CACHE[key] = (model, impl, infer_mod)
        model, impl, infer_mod = _MODEL_CACHE[key]

        out = infer_mod.predict(model, goal) if impl == "shared_module" else _internal_predict(model, goal)

        try:
            tier_vocab = list(model["config"]["tier_vocab"])
        except Exception:
            tier_vocab = list(_TIER_VOCAB)
        probs_raw = out.get("tier_probs")
        learned_probs = (
            {t: float(p) for t, p in zip(tier_vocab, list(probs_raw), strict=False)} if probs_raw is not None else {}
        )
        return {
            "learned_tier": out.get("tier"),
            "learned_probs": learned_probs,
            "risk": float(out.get("risk", 0.0)),
            "cost": float(out.get("cost", 0.0)),
            "model_version": str(out.get("model_version", "")),
            "gate_passed": bool(out.get("gate_passed", False)),
            "learned_source": "champion_weights",
            "infer_impl": impl,
        }
    except Exception as exc:  # belt-and-braces: this function must never raise
        return _fallback(f"learned route error: {type(exc).__name__}: {exc}")
