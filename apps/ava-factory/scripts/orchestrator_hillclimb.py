#!/usr/bin/env python3
"""Orchestrator hill-climb: REAL training over a small config grid + honest gate.

Trains the orchestrator router (hash-bucket embedding + MLP, pinned
schema_version-1 contract shared with ``orchestrator_model.py`` /
``orchestrator_infer.py``) over exactly eight named config variants, picks the
champion by validation tier accuracy (split_bucket 8), evaluates it on the
held-out bucket 9, and applies a strict promotion gate against two baselines.

Provenance discipline (mirrors the never-promote-on-error gate of
``scripts/distill_ladder.py:54-78`` and the 'insufficient' verdict of
``apps/dottie/dottie/climb.py``):
  * every number in every report is a measured output of THIS run;
  * a failing gate is reported as failed — the champion still ships to
    ``champion_weights.json`` but marked ``gate_passed: false``;
  * counterfactual rewards are unobserved, so no "regret" is fabricated —
    agreement-conditional reward statistics are reported instead, with an
    explicit note;
  * the gate NEVER passes on missing/NaN metrics or on < 10 measured
    held-out records.

Cross-lane inputs, both handled gracefully when absent:
  * corpus (``data/orchestration/corpus.jsonl``, built by a parallel lane) —
    falls back to an embedded seeded battery labeled by the scout-cli harness
    heuristics; reports carry corpus_source 'l2_corpus' or
    'embedded_battery_fallback';
  * model code (``orchestrator_model.py`` / ``orchestrator_infer.py``) —
    falls back to an in-script trainer/inference pair implementing the
    IDENTICAL pinned architecture and export format; reports carry trainer
    'orchestrator_model' or 'embedded_fallback'.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import math
import random
import re
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import numpy as np

_AVA = Path(__file__).resolve().parents[1]  # apps/ava-factory
_REPO = Path(__file__).resolve().parents[3]  # repo root

if str(_AVA) not in sys.path:
    sys.path.insert(0, str(_AVA))

# Cross-lane model modules: prefer the real pair, fall back to the in-script
# clones below (identical pinned architecture + export schema).
try:
    import orchestrator_infer as _oi
    import orchestrator_model as _om

    TRAINER = "orchestrator_model"
except Exception:  # pragma: no cover - exercised only when the lane is absent
    _oi = None
    _om = None
    TRAINER = "embedded_fallback"

DENSE_FEATURES = (
    "n_words",
    "n_chain_signals",
    "has_code_terms",
    "latency_ms",
    "tokens_est",
    "attempt",
)
# FIXED order — MOMA_TIERS key order of apps/scout-cli/bigbang/plugins/harness/cli.py:29-35.
TIER_VOCAB = (
    "deterministic",
    "llm",
    "deep_research",
    "action_operator",
    "agentic_epic",
)
# The harness failure set, apps/scout-cli/bigbang/plugins/harness/timeline.py:28.
FAILURE_STATUSES = {"fail", "failed", "error", "timeout"}
HIDDEN_DIM = 64

# Exactly eight named variants; seed = 100 + index (+ --seed-offset).
VARIANTS = [
    {"name": "v1", "n_buckets": 4096, "embed_dim": 16, "lr": 1e-3, "beta": 1.0, "reward_mode": "raw"},
    {"name": "v2", "n_buckets": 4096, "embed_dim": 16, "lr": 3e-3, "beta": 1.0, "reward_mode": "raw"},
    {"name": "v3", "n_buckets": 4096, "embed_dim": 32, "lr": 1e-3, "beta": 1.0, "reward_mode": "raw"},
    {"name": "v4", "n_buckets": 8192, "embed_dim": 16, "lr": 1e-3, "beta": 1.0, "reward_mode": "raw"},
    {"name": "v5", "n_buckets": 4096, "embed_dim": 16, "lr": 1e-3, "beta": 0.5, "reward_mode": "raw"},
    {"name": "v6", "n_buckets": 4096, "embed_dim": 16, "lr": 1e-3, "beta": 2.0, "reward_mode": "raw"},
    {"name": "v7", "n_buckets": 4096, "embed_dim": 16, "lr": 1e-3, "beta": 1.0, "reward_mode": "binary"},
    {"name": "v8", "n_buckets": 8192, "embed_dim": 32, "lr": 3e-3, "beta": 1.0, "reward_mode": "raw"},
]

_STD_FLOOR = 1e-6
_GELU_C = 0.7978845608028654  # sqrt(2/pi) at the contract-pinned precision
_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Matches the chain-signal expression of apps/scout-cli/bigbang/plugins/harness/cli.py:64.
_CHAIN_RE = re.compile(r"(->|then|after|next|→)")
# Pinned shared set (identical to orchestrator_infer.CODE_TERMS).
_CODE_TERMS = {
    "code", "build", "test", "deploy", "api", "bug", "fix", "refactor",
    "cli", "pipeline", "json", "python", "script", "repo", "harness",
}


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


# ---------------------------------------------------------------------------
# Embedded fallback: numpy inference (pinned math, used only when
# orchestrator_infer is absent).
# ---------------------------------------------------------------------------


def _cfg_field(config, key):
    if isinstance(config, dict):
        return config[key]
    return getattr(config, key)


def _fb_featurize(goal_text: str, dense: dict | None, config):
    """sha256 hash-bucket 1/2/3-gram bag + dense vector (pinned contract)."""
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
    vec = np.zeros(len(dense_features), dtype=np.float64)
    for j, feat in enumerate(dense_features):
        val = dense.get(feat)
        if val is None:
            vec[j] = 0.0
        elif isinstance(val, bool):
            vec[j] = 1.0 if val else 0.0
        else:
            vec[j] = float(val)
    return list(bag.keys()), list(bag.values()), vec


def _fb_gelu_tanh(u: np.ndarray) -> np.ndarray:
    return 0.5 * u * (1.0 + np.tanh(_GELU_C * (u + 0.044715 * u**3)))


def _fb_load_weights(path) -> dict:
    """Minimal schema_version-1 loader with shape checks (fallback only)."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("schema_version") != 1:
        raise ValueError(f"unsupported schema_version {doc.get('schema_version')!r}")
    cfg = doc["config"]
    n_buckets, embed_dim = int(cfg["n_buckets"]), int(cfg["embed_dim"])
    hidden_dim, n_dense = int(cfg["hidden_dim"]), len(cfg["dense_features"])
    n_tiers = len(cfg["tier_vocab"])
    shapes = {
        "embedding": (n_buckets, embed_dim),
        "w1": (embed_dim + n_dense, hidden_dim),
        "b1": (hidden_dim,),
        "w_tier": (hidden_dim, n_tiers),
        "b_tier": (n_tiers,),
        "w_risk": (hidden_dim,),
        "w_cost": (hidden_dim,),
    }
    weights = {}
    for name, shape in shapes.items():
        arr = np.asarray(doc["weights"][name], dtype=np.float64)
        if arr.shape != shape:
            raise ValueError(f"weights field '{name}' has shape {arr.shape}, expected {shape}")
        weights[name] = arr
    weights["b_risk"] = float(doc["weights"]["b_risk"])
    weights["b_cost"] = float(doc["weights"]["b_cost"])
    norms = {
        "dense_mean": np.asarray(doc["norms"]["dense_mean"], dtype=np.float64),
        "dense_std": np.asarray(doc["norms"]["dense_std"], dtype=np.float64),
    }
    return {
        "schema_version": 1,
        "model_version": doc["model_version"],
        "gate_passed": bool(doc.get("gate_passed", False)),
        "trained_at": doc.get("trained_at"),
        "provenance": doc.get("provenance", {}),
        "config": cfg,
        "norms": norms,
        "weights": weights,
    }


def _fb_forward(w: dict, bucket_ids, counts, dense_vec) -> dict:
    wt = w["weights"]
    embedding = wt["embedding"]
    if bucket_ids:
        ids = np.asarray(bucket_ids, dtype=np.int64)
        cts = np.asarray(counts, dtype=np.float64)
        pooled = (cts[:, None] * embedding[ids]).sum(axis=0) / max(1.0, float(cts.sum()))
    else:
        pooled = np.zeros(embedding.shape[1], dtype=np.float64)
    dn = (np.asarray(dense_vec, dtype=np.float64) - w["norms"]["dense_mean"]) / np.maximum(
        w["norms"]["dense_std"], _STD_FLOOR
    )
    x = np.concatenate([pooled, dn])
    h = _fb_gelu_tanh(x @ wt["w1"] + wt["b1"])
    tier_logits = h @ wt["w_tier"] + wt["b_tier"]
    e = np.exp(tier_logits - np.max(tier_logits))
    tier_probs = e / e.sum()
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


# ---------------------------------------------------------------------------
# Embedded fallback: torch trainer (identical pinned architecture + export;
# used only when orchestrator_model is absent).
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _FbConfig:
    n_buckets: int = 4096
    embed_dim: int = 16
    hidden_dim: int = 64
    dense_features: tuple = DENSE_FEATURES
    tier_vocab: tuple = TIER_VOCAB
    seed: int = 0
    lr: float = 1e-3
    beta: float = 1.0
    weight_cap: float = 4.0
    epochs: int = 20
    batch_size: int = 64
    risk_loss_w: float = 0.5
    cost_loss_w: float = 0.1


def _fb_group_weights(records, *, beta: float, weight_cap: float) -> list[float]:
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for rec in records:
        g = rec["group"]
        sums[g] = sums.get(g, 0.0) + float(rec["reward"])
        counts[g] = counts.get(g, 0) + 1
    means = {g: sums[g] / counts[g] for g in sums}
    return [
        min(math.exp((float(r["reward"]) - means[r["group"]]) / beta), weight_cap)
        for r in records
    ]


def _fb_train_model(cfg: _FbConfig, records: list[dict], *, time_budget_s=None):
    """Advantage-weighted CE + risk BCE + cost MSE on the pinned net."""
    import torch
    from torch import nn
    from torch.nn import functional as F

    t0 = time.monotonic()
    torch.manual_seed(cfg.seed)
    random.seed(cfg.seed)
    np.random.seed(cfg.seed)
    n = len(records)
    if n == 0:
        raise ValueError("fallback trainer requires at least one record")

    def dvec(dense):
        vec = np.zeros(len(cfg.dense_features), dtype=np.float64)
        dense = dense or {}
        for j, feat in enumerate(cfg.dense_features):
            val = dense.get(feat)
            if val is None:
                vec[j] = 0.0
            elif isinstance(val, bool):
                vec[j] = 1.0 if val else 0.0
            else:
                vec[j] = float(val)
        return vec

    dense_mat = np.stack([dvec(r.get("dense")) for r in records])
    dense_mean = dense_mat.mean(axis=0)
    dense_std = np.maximum(dense_mat.std(axis=0), _STD_FLOOR)
    norms = {"dense_mean": dense_mean, "dense_std": dense_std}
    dn_t = torch.tensor((dense_mat - dense_mean) / dense_std, dtype=torch.float32)

    feats = [_fb_featurize(r["goal_text"], r.get("dense"), cfg) for r in records]
    y = torch.tensor([cfg.tier_vocab.index(r["label_tier"]) for r in records], dtype=torch.long)
    risk_t = torch.tensor([float(r["risk_target"]) for r in records], dtype=torch.float32)
    cost_t = torch.tensor([float(r["cost_target"]) for r in records], dtype=torch.float32)
    wts = torch.tensor(
        _fb_group_weights(records, beta=cfg.beta, weight_cap=cfg.weight_cap),
        dtype=torch.float32,
    )

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.embedding = nn.Embedding(cfg.n_buckets, cfg.embed_dim)
            self.fc1 = nn.Linear(cfg.embed_dim + len(cfg.dense_features), cfg.hidden_dim)
            self.act = nn.GELU(approximate="tanh")
            self.tier_head = nn.Linear(cfg.hidden_dim, len(cfg.tier_vocab))
            self.risk_head = nn.Linear(cfg.hidden_dim, 1)
            self.cost_head = nn.Linear(cfg.hidden_dim, 1)

        def forward(self, bucket_idx, counts, dense):
            emb = self.embedding(bucket_idx)
            pooled = (counts.unsqueeze(-1) * emb).sum(dim=1) / counts.sum(
                dim=1, keepdim=True
            ).clamp(min=1.0)
            h = self.act(self.fc1(torch.cat([pooled, dense], dim=-1)))
            return (
                self.tier_head(h),
                self.risk_head(h).squeeze(-1),
                self.cost_head(h).squeeze(-1),
            )

    net = Net()
    opt = torch.optim.Adam(net.parameters(), lr=cfg.lr)
    history: dict = {"epoch_loss": [], "stopped_early": False, "n_train": n}
    order = list(range(n))
    for _epoch in range(cfg.epochs):
        if time_budget_s is not None and time.monotonic() - t0 > time_budget_s:
            history["stopped_early"] = True
            break
        random.shuffle(order)
        losses = []
        for start in range(0, n, cfg.batch_size):
            idx = order[start : start + cfg.batch_size]
            max_len = max(1, max(len(feats[i][0]) for i in idx))
            bucket_idx = torch.zeros(len(idx), max_len, dtype=torch.long)
            counts = torch.zeros(len(idx), max_len, dtype=torch.float32)
            for row, i in enumerate(idx):
                ids, cts, _ = feats[i]
                if ids:
                    bucket_idx[row, : len(ids)] = torch.tensor(ids, dtype=torch.long)
                    counts[row, : len(cts)] = torch.tensor(cts, dtype=torch.float32)
            sel = torch.tensor(idx, dtype=torch.long)
            tier_logits, risk_logit, cost_pred = net(bucket_idx, counts, dn_t[sel])
            ce = F.cross_entropy(tier_logits, y[sel], reduction="none")
            loss = (
                (wts[sel] * ce).mean()
                + cfg.risk_loss_w
                * F.binary_cross_entropy_with_logits(risk_logit, risk_t[sel])
                + cfg.cost_loss_w * F.mse_loss(cost_pred, cost_t[sel])
            )
            opt.zero_grad()
            loss.backward()
            opt.step()
            losses.append(float(loss.item()))
        history["epoch_loss"].append(sum(losses) / len(losses))
    history["epochs_run"] = len(history["epoch_loss"])
    history["wall_time_s"] = time.monotonic() - t0
    return net, norms, history


def _fb_save_weights(
    net,
    cfg: _FbConfig,
    norms: dict,
    path,
    *,
    model_version: str,
    gate_passed: bool = False,
    provenance: dict | None = None,
    trained_at: str | None = None,
) -> Path:
    """Pinned schema_version-1 export: x@W orientation, 6-decimal floats."""
    import torch

    def r1(vec):
        return [round(float(v), 6) for v in vec]

    def r2(mat):
        return [[round(float(v), 6) for v in row] for row in mat]

    path = Path(path)
    if trained_at is None:
        trained_at = (
            datetime.datetime.now(datetime.UTC)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    with torch.no_grad():
        doc = {
            "schema_version": 1,
            "model_version": model_version,
            "gate_passed": bool(gate_passed),
            "trained_at": trained_at,
            "provenance": provenance or {},
            "config": {
                "n_buckets": cfg.n_buckets,
                "embed_dim": cfg.embed_dim,
                "hidden_dim": cfg.hidden_dim,
                "dense_features": list(cfg.dense_features),
                "tier_vocab": list(cfg.tier_vocab),
                "seed": cfg.seed,
            },
            "norms": {
                "dense_mean": r1(norms["dense_mean"]),
                "dense_std": r1(norms["dense_std"]),
            },
            "weights": {
                "embedding": r2(net.embedding.weight.tolist()),
                "w1": r2(net.fc1.weight.t().tolist()),
                "b1": r1(net.fc1.bias.tolist()),
                "w_tier": r2(net.tier_head.weight.t().tolist()),
                "b_tier": r1(net.tier_head.bias.tolist()),
                "w_risk": r1(net.risk_head.weight.squeeze(0).tolist()),
                "b_risk": round(float(net.risk_head.bias.item()), 6),
                "w_cost": r1(net.cost_head.weight.squeeze(0).tolist()),
                "b_cost": round(float(net.cost_head.bias.item()), 6),
            },
        }
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return path


def _model_api():
    """(make_config, train_model, save_weights) from the real pair or fallback."""
    if _om is not None:
        def mk(**kw):
            return _om.OrchConfig(**kw)

        return mk, _om.train_model, _om.save_weights
    return (lambda **kw: _FbConfig(**kw)), _fb_train_model, _fb_save_weights


def _infer_api():
    """(load_weights, featurize, forward) from the real pair or fallback."""
    if _oi is not None:
        return _oi.load_weights, _oi.featurize, _oi.forward
    return _fb_load_weights, _fb_featurize, _fb_forward


# ---------------------------------------------------------------------------
# Corpus loading + embedded battery fallback
# ---------------------------------------------------------------------------


def _load_heuristics():
    """Import the scout-cli harness heuristics (baseline + fallback labeling)."""
    try:
        scout = _REPO / "apps" / "scout-cli"
        if str(scout) not in sys.path:
            sys.path.insert(0, str(scout))
        from bigbang.plugins.harness.cli import (
            INTENT_KEYWORDS,
            _classify_moma,
            _complexity,
            _routed_agents,
            _score_intent,
        )

        return {
            "score": _score_intent,
            "classify": _classify_moma,
            "complexity": _complexity,
            "routed": _routed_agents,
            "keywords": INTENT_KEYWORDS,
        }
    except Exception:
        return None


def _heuristic_label(goal: str, heur: dict) -> str:
    """Replicates the route command's labeling, harness cli.py:98-102."""
    scores = {k: heur["score"](goal, k) for k in heur["keywords"]}
    intent = max(scores, key=lambda k: scores[k]) if max(scores.values()) > 0 else "llm"
    return heur["classify"](goal, intent, heur["complexity"](goal))


# Every template embeds at least one INTENT_KEYWORDS keyword — zero-keyword
# goals are unlabelable (route CLI KeyError at harness cli.py:103).
_FALLBACK_TEMPLATES = [
    "monitor the heartbeat of the {svc} service and alert on every tick",
    "run the uptime monitor tick for the {svc} deployment",
    "compare {a} vs {b} pricing with 5-7 sources and a benchmark matrix",
    "research the sota paper on {topic} with triangulation across sources",
    "compare the {topic} benchmark results vs last quarter sources",
    "schedule a calendar review and pay the {svc} invoice via gmail",
    "book a slot on the calendar then send the {svc} invoice through gmail",
    "build and launch the {svc} factory end-to-end then ship the close the loop report",
    "launch the {svc} rollout end-to-end then build the recovery loop and ship it",
    "ship the {svc} migration loop end-to-end then launch the follow-up factory then build the audit trail and keep track of every step along the way",
    "run the nightly cron job for {svc}",
    "tune the cron cadence for the {svc} digest",
    "research {topic} benchmark sources then compare findings vs the {a} baseline then draft the triangulation matrix",
    "pay the {a} invoice then schedule the {svc} retro on the calendar",
]
_FALLBACK_FILLERS = {
    "svc": ["billing", "ingest", "search", "reporting", "export", "alerting", "archive"],
    "a": ["stripe", "paddle"],
    "b": ["lemon squeezy", "paddle"],
    "topic": ["retrieval", "routing", "distillation", "quantization", "caching"],
}


def build_fallback_corpus(heur: dict, n: int = 300, seed: int = 20260809) -> list[dict]:
    """Seeded embedded battery labeled by the harness heuristics (all simulated)."""
    rng = random.Random(seed)
    records: list[dict] = []
    i = 0
    while len(records) < n:
        tpl = _FALLBACK_TEMPLATES[i % len(_FALLBACK_TEMPLATES)]
        goal = tpl.format(**{k: rng.choice(v) for k, v in _FALLBACK_FILLERS.items()})
        scores = {k: heur["score"](goal, k) for k in heur["keywords"]}
        if max(scores.values()) <= 0:
            i += 1
            continue  # unlabelable goal: never emit (templates should prevent this)
        intent = max(scores, key=lambda k: scores[k])
        complexity = heur["complexity"](goal)
        label = heur["classify"](goal, intent, complexity)
        lower = goal.lower()
        n_words = len(goal.split())
        n_chain = len(_CHAIN_RE.findall(lower)) + (1 if " and " in lower and n_words > 10 else 0)
        toks = _TOKEN_RE.findall(lower)
        split_key = f"tpl-{i % 40:03d}"
        records.append(
            {
                "schema_version": 1,
                "record_id": f"fallback-{i:04d}",
                "source": "embedded_battery",
                "provenance": "simulated",
                "provenance_fields": {"label_tier": "simulated", "reward": "simulated"},
                "features": {
                    "goal_text": goal,
                    "n_words": n_words,
                    "n_chain_signals": n_chain,
                    "has_code_terms": any(t in _CODE_TERMS for t in toks),
                    "latency_ms": 0.0,
                    "tokens_est": 0,
                    "attempt": 1,
                },
                "label_tier": label,
                "label_agents_n": len(heur["routed"](intent, complexity)),
                "reward": 1.0,
                "latency_ms": 0.0,
                "tokens_est": 0,
                "status": "ok",
                "errorClass": None,
                "split_key": split_key,
                "split_bucket": int(hashlib.sha256(split_key.encode()).hexdigest(), 16) % 10,
            }
        )
        i += 1
    return records


def load_corpus(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _to_train_record(rec: dict, reward_mode: str) -> dict:
    feats = rec.get("features", {})
    tokens = rec.get("tokens_est")
    if tokens is None:
        tokens = feats.get("tokens_est") or 0.0
    reward = float(rec.get("reward", 0.0))
    if reward_mode == "binary":
        reward = 1.0 if reward > 0 else (-1.0 if reward < 0 else 0.0)
    status = str(rec.get("status") or "").lower()
    return {
        "goal_text": feats.get("goal_text") or "",
        "dense": {f: feats.get(f) for f in DENSE_FEATURES},
        "label_tier": rec["label_tier"],
        "reward": reward,
        "group": str(rec.get("split_key") or rec.get("record_id") or "unknown"),
        "risk_target": 1.0 if status in FAILURE_STATUSES else 0.0,
        "cost_target": math.log1p(max(0.0, float(tokens))),
    }


# ---------------------------------------------------------------------------
# Evaluation + promotion gate
# ---------------------------------------------------------------------------


def _predict_records(w: dict, records: list[dict], featurize_fn, forward_fn):
    """(pred_tier, pred_risk) per record, using the record's own dense features."""
    out = []
    for rec in records:
        feats = rec.get("features", {})
        dense = {f: feats.get(f) for f in DENSE_FEATURES}
        ids, cts, dv = featurize_fn(feats.get("goal_text") or "", dense, w["config"])
        res = forward_fn(w, ids, cts, dv)
        out.append((res["tier"], float(res["risk"])))
    return out


def _accuracy(preds: list[str], records: list[dict]):
    if not records:
        return None
    hits = sum(1 for p, r in zip(preds, records, strict=False) if p == r["label_tier"])
    return hits / len(records)


def _mean(vals: list[float]):
    return (sum(vals) / len(vals)) if vals else None


def _risk_calibration(risks: list[float], records: list[dict]) -> dict:
    deciles = []
    fails = [
        1.0 if str(r.get("status") or "").lower() in FAILURE_STATUSES else 0.0
        for r in records
    ]
    for d in range(10):
        idx = [i for i, p in enumerate(risks) if min(9, int(p * 10)) == d]
        deciles.append(
            {
                "decile": d,
                "n": len(idx),
                "mean_pred_risk": _mean([risks[i] for i in idx]),
                "observed_failure_rate": _mean([fails[i] for i in idx]),
            }
        )
    brier = _mean([(p - f) ** 2 for p, f in zip(risks, fails, strict=False)])
    return {"deciles": deciles, "brier": brier}


def _is_finite_number(v) -> bool:
    return (
        isinstance(v, (int, float))
        and not isinstance(v, bool)
        and math.isfinite(float(v))
    )


def promotion_gate(champion: dict, baselines: dict, n_measured_holdout: int) -> dict:
    """PURE gate. Never passes on missing/NaN metrics or thin measured data.

    Same spirit as distill_ladder.gate_decision (scripts/distill_ladder.py:54-78,
    never promote on error) and climb.compare_iterations returning
    'insufficient' on unpaired data (apps/dottie/dottie/climb.py).
    """
    if n_measured_holdout < 10:
        return {
            "gate_passed": False,
            "reason": (
                f"insufficient measured held-out data (n={n_measured_holdout}, need >=10)"
            ),
        }
    champ = champion.get("tier_accuracy_measured")
    freq = baselines.get("freq_prior_accuracy_measured")
    heur = baselines.get("heuristic_accuracy_measured")
    for label, v in (
        ("champion.tier_accuracy_measured", champ),
        ("baselines.freq_prior_accuracy_measured", freq),
        ("baselines.heuristic_accuracy_measured", heur),
    ):
        if not _is_finite_number(v):
            return {
                "gate_passed": False,
                "reason": f"{label} missing or non-finite ({v!r}); never pass the gate on missing metrics",
            }
    if champ > freq and champ > heur:
        return {
            "gate_passed": True,
            "reason": (
                f"champion measured accuracy {champ:.6g} strictly beats freq prior "
                f"{freq:.6g} and heuristic {heur:.6g} on n={n_measured_holdout} "
                "measured held-out records"
            ),
        }
    return {
        "gate_passed": False,
        "reason": (
            f"champion measured accuracy {champ:.6g} does not strictly beat both "
            f"baselines (freq prior {freq:.6g}, heuristic {heur:.6g}) "
            f"on n={n_measured_holdout} measured held-out records"
        ),
    }


# ---------------------------------------------------------------------------
# Main hill-climb driver
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", type=Path, default=_AVA / "data" / "orchestration" / "corpus.jsonl")
    ap.add_argument("--out", type=Path, default=_AVA / "reports" / "orchestrator")
    ap.add_argument("--variants", type=int, default=8, help="first N of the fixed grid")
    ap.add_argument("--time-budget", type=float, default=60.0, help="per-variant CPU seconds cap")
    ap.add_argument("--seed-offset", type=int, default=0)
    args = ap.parse_args(argv)

    heur = _load_heuristics()

    if args.corpus.exists():
        corpus_source = "l2_corpus"
        records = load_corpus(args.corpus)
    else:
        corpus_source = "embedded_battery_fallback"
        if heur is None:
            print(
                "corpus absent and harness heuristics unimportable; refusing to fabricate data",
                file=sys.stderr,
            )
            return 2
        records = build_fallback_corpus(heur)
    # Records whose label is outside the fixed vocab cannot be trained on.
    n_bad_label = sum(1 for r in records if r.get("label_tier") not in TIER_VOCAB)
    records = [r for r in records if r.get("label_tier") in TIER_VOCAB]

    train_rows = [r for r in records if int(r.get("split_bucket", -1)) <= 7 and int(r.get("split_bucket", -1)) >= 0]
    val_rows = [r for r in records if int(r.get("split_bucket", -1)) == 8]
    test_rows = [r for r in records if int(r.get("split_bucket", -1)) == 9]
    measured_holdout = [r for r in test_rows if r.get("provenance") == "measured"]
    print(
        f"corpus_source={corpus_source} trainer={TRAINER} "
        f"train={len(train_rows)} val={len(val_rows)} test={len(test_rows)} "
        f"measured_holdout={len(measured_holdout)}"
    )
    if not train_rows or not val_rows:
        print("corpus has an empty train or val split; cannot hill-climb", file=sys.stderr)
        return 2

    make_cfg, train_model, save_weights = _model_api()
    load_weights, featurize_fn, forward_fn = _infer_api()

    args.out.mkdir(parents=True, exist_ok=True)
    variant_rows = []
    trained = []  # (net, cfg, norms) per variant, index-aligned with variant_rows
    with tempfile.TemporaryDirectory(prefix="orch_hillclimb_") as tmpd:
        for idx, variant in enumerate(VARIANTS[: max(0, args.variants)]):
            seed = 100 + idx + args.seed_offset
            cfg = make_cfg(
                n_buckets=variant["n_buckets"],
                embed_dim=variant["embed_dim"],
                hidden_dim=HIDDEN_DIM,
                seed=seed,
                lr=variant["lr"],
                beta=variant["beta"],
            )
            train_recs = [_to_train_record(r, variant["reward_mode"]) for r in train_rows]
            t0 = time.monotonic()
            net, norms, history = train_model(cfg, train_recs, time_budget_s=args.time_budget)
            train_seconds = time.monotonic() - t0

            tmp_path = Path(tmpd) / f"{variant['name']}.json"
            save_weights(
                net, cfg, norms, tmp_path,
                model_version=f"orch-mlp-v1-{variant['name']}",
                provenance={"trainer": TRAINER, "corpus_source": corpus_source, "n_train": len(train_recs)},
            )
            w = load_weights(tmp_path)
            val_preds = [p for p, _ in _predict_records(w, val_rows, featurize_fn, forward_fn)]
            val_acc = _accuracy(val_preds, val_rows)
            epoch_loss = history.get("epoch_loss", [])
            variant_rows.append(
                {
                    "name": variant["name"],
                    "config": {
                        "n_buckets": variant["n_buckets"],
                        "embed_dim": variant["embed_dim"],
                        "hidden_dim": HIDDEN_DIM,
                        "lr": variant["lr"],
                        "beta": variant["beta"],
                        "reward_mode": variant["reward_mode"],
                    },
                    "seed": seed,
                    "n_train": len(train_recs),
                    "epochs_run": history.get("epochs_run", len(epoch_loss)),
                    "stopped_early": bool(history.get("stopped_early", False)),
                    "train_seconds": round(train_seconds, 3),
                    "final_loss": (round(epoch_loss[-1], 6) if epoch_loss else None),
                    "val_tier_accuracy": (round(val_acc, 6) if val_acc is not None else None),
                }
            )
            trained.append((net, cfg, norms))
            print(
                f"[{variant['name']}] train_seconds={train_seconds:.2f} "
                f"epochs={variant_rows[-1]['epochs_run']} "
                f"stopped_early={variant_rows[-1]['stopped_early']} "
                f"val_tier_accuracy={variant_rows[-1]['val_tier_accuracy']}"
            )

        # Champion: best val accuracy, ties broken by lower variant index.
        champ_idx = max(
            range(len(variant_rows)),
            key=lambda i: ((variant_rows[i]["val_tier_accuracy"] or -1.0), -i),
        )
        champ_row = variant_rows[champ_idx]
        champ_name = champ_row["name"]
        model_version = f"orch-mlp-v1-{champ_name}"

        # Held-out (bucket 9) evaluation of the champion.
        champ_w = load_weights(Path(tmpd) / f"{champ_name}.json")
        test_pred = _predict_records(champ_w, test_rows, featurize_fn, forward_fn)
        test_tiers = [p for p, _ in test_pred]
        test_risks = [r for _, r in test_pred]
        measured_idx = [i for i, r in enumerate(test_rows) if r.get("provenance") == "measured"]

        acc_all = _accuracy(test_tiers, test_rows)
        acc_measured = _accuracy(
            [test_tiers[i] for i in measured_idx], [test_rows[i] for i in measured_idx]
        )
        agree = [i for i in range(len(test_rows)) if test_tiers[i] == test_rows[i]["label_tier"]]
        disagree = [i for i in range(len(test_rows)) if i not in set(agree)]
        rewards = [float(r.get("reward", 0.0)) for r in test_rows]
        agreement = {
            "agreement_rate": acc_all,
            "mean_reward_all": _mean(rewards),
            "mean_reward_on_agreement": _mean([rewards[i] for i in agree]),
            "mean_reward_on_disagreement": _mean([rewards[i] for i in disagree]),
            "note": (
                "counterfactual rewards unobserved; agreement-conditional statistics "
                "reported in place of true regret"
            ),
        }
        risk_cal = _risk_calibration(test_risks, test_rows)

        # Baseline (a): frequency prior from the train split (first max in vocab order).
        train_counts = Counter(r["label_tier"] for r in train_rows)
        freq_tier = max(TIER_VOCAB, key=lambda t: train_counts.get(t, 0))
        freq_acc_all = _accuracy([freq_tier] * len(test_rows), test_rows)
        freq_acc_measured = _accuracy(
            [freq_tier] * len(measured_idx), [test_rows[i] for i in measured_idx]
        )

        # Baseline (b): heuristic router — only computable for non-empty goal_text.
        heur_note = (
            "synthetic_battery labels ARE the heuristic's outputs, so heuristic "
            "accuracy is 1.0 on battery records by construction; the meaningful "
            "comparison is the measured subset"
        )
        if heur is not None:
            evaluable = [
                i for i, r in enumerate(test_rows) if (r.get("features", {}).get("goal_text") or "")
            ]
            heur_preds = {
                i: _heuristic_label(test_rows[i]["features"]["goal_text"], heur)
                for i in evaluable
            }
            heur_acc_all = _accuracy(
                [heur_preds[i] for i in evaluable], [test_rows[i] for i in evaluable]
            )
            m_eval = [i for i in evaluable if i in set(measured_idx)]
            heur_acc_measured = _accuracy(
                [heur_preds[i] for i in m_eval], [test_rows[i] for i in m_eval]
            )
            heuristic_block = {
                "accuracy_evaluable": heur_acc_all,
                "n_evaluable": len(evaluable),
                "accuracy_measured": heur_acc_measured,
                "n_evaluable_measured": len(m_eval),
                "note": heur_note,
            }
        else:
            heuristic_block = {
                "accuracy_evaluable": None,
                "n_evaluable": 0,
                "accuracy_measured": None,
                "n_evaluable_measured": 0,
                "note": heur_note + "; harness heuristics unimportable in this run",
            }

        champion_block = {
            "name": champ_name,
            "model_version": model_version,
            "val_tier_accuracy": champ_row["val_tier_accuracy"],
            "tier_accuracy_all": acc_all,
            "tier_accuracy_measured": acc_measured,
            "n_holdout": len(test_rows),
            "n_measured_holdout": len(measured_idx),
            "agreement": agreement,
            "risk_calibration": risk_cal,
        }
        gate = promotion_gate(
            champion_block,
            {
                "freq_prior_accuracy_measured": freq_acc_measured,
                "heuristic_accuracy_measured": heuristic_block["accuracy_measured"],
            },
            len(measured_idx),
        )

        built_at = _utc_now_iso()
        ladder_report = {
            "schema_version": 1,
            "built_at": built_at,
            "corpus_source": corpus_source,
            "trainer": TRAINER,
            "seed_offset": args.seed_offset,
            "time_budget_s": args.time_budget,
            "n_records_dropped_bad_label": n_bad_label,
            "corpus_counts": {
                "train": len(train_rows),
                "val": len(val_rows),
                "test": len(test_rows),
                "measured_holdout": len(measured_idx),
            },
            "variants": variant_rows,
        }
        eval_report = {
            "schema_version": 1,
            "built_at": built_at,
            "corpus_source": corpus_source,
            "trainer": TRAINER,
            "champion": champion_block,
            "baselines": {
                "freq_prior": {
                    "tier": freq_tier,
                    "accuracy_all": freq_acc_all,
                    "accuracy_measured": freq_acc_measured,
                },
                "heuristic": heuristic_block,
            },
            "gate": gate,
            "notes": [
                agreement["note"],
                heur_note,
                (
                    "gate compares measured-subset accuracy only; simulated battery "
                    "records share the heuristic's labeling and cannot certify the model"
                ),
                f"corpus_source={corpus_source}; trainer={TRAINER}; all metrics measured from this run",
            ],
        }
        (args.out / "ladder_report.json").write_text(
            json.dumps(ladder_report, indent=2) + "\n", encoding="utf-8"
        )
        (args.out / "eval_report.json").write_text(
            json.dumps(eval_report, indent=2) + "\n", encoding="utf-8"
        )

        # The champion ALWAYS ships, gate verdict honestly attached.
        champ_net, champ_cfg, champ_norms = trained[champ_idx]
        champ_path = args.out / "champion_weights.json"
        save_weights(
            champ_net,
            champ_cfg,
            champ_norms,
            champ_path,
            model_version=model_version,
            gate_passed=gate["gate_passed"],
            provenance={
                "trainer": TRAINER,
                "corpus_source": corpus_source,
                "n_train": len(train_rows),
            },
        )
        # Sanity: the exported champion must load shape-consistently.
        load_weights(champ_path)

    print(
        f"champion={champ_name} val_tier_accuracy={champ_row['val_tier_accuracy']} "
        f"holdout_tier_accuracy_all={acc_all} gate_passed={gate['gate_passed']} "
        f"reason={gate['reason']!r}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
