"""Orchestrator router training — torch side of the orchestrator model pair.

Trains a small hash-bucket embedding + MLP that routes a goal to one of the
five MOMA tiers (tier_vocab order is FIXED — it is the MOMA_TIERS key order of
apps/scout-cli/bigbang/plugins/harness/cli.py:29-35), plus a risk head
(sigmoid) and a cost head (predicts ln(1+tokens_est)).

The featurizer lives in ``orchestrator_infer.py`` (same directory) and is
imported FROM there so training and deployment share one implementation.
``save_weights`` exports the pinned schema_version-1 JSON that
``orchestrator_infer.load_weights`` consumes; matrices are stored in x@W
orientation, i.e. torch ``nn.Linear.weight`` TRANSPOSED, floats rounded to 6
decimals. The activation is nn.GELU(approximate="tanh") so the numpy
tanh-approximation forward matches to within the export-rounding tolerance.
"""

from __future__ import annotations

import datetime
import json
import math
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

# Same-directory import: both modules are top-level files in apps/ava-factory.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from orchestrator_infer import featurize

_DENSE_FEATURES = (
    "n_words",
    "n_chain_signals",
    "has_code_terms",
    "latency_ms",
    "tokens_est",
    "attempt",
)
# FIXED order — MOMA_TIERS key order of apps/scout-cli/bigbang/plugins/harness/cli.py:29-35.
_TIER_VOCAB = (
    "deterministic",
    "llm",
    "deep_research",
    "action_operator",
    "agentic_epic",
)
_STD_FLOOR = 1e-6


@dataclass
class OrchConfig:
    """Training + architecture configuration (defaults are the champion recipe)."""

    n_buckets: int = 4096
    embed_dim: int = 16
    hidden_dim: int = 64
    dense_features: tuple = _DENSE_FEATURES
    tier_vocab: tuple = _TIER_VOCAB
    seed: int = 0
    lr: float = 1e-3
    beta: float = 1.0
    weight_cap: float = 4.0
    epochs: int = 20
    batch_size: int = 64
    risk_loss_w: float = 0.5
    cost_loss_w: float = 0.1


class OrchestratorNet(nn.Module):
    """Hash-bucket embedding pool + one hidden layer + three heads."""

    def __init__(self, cfg: OrchConfig):
        super().__init__()
        self.cfg = cfg
        n_dense = len(cfg.dense_features)
        self.embedding = nn.Embedding(cfg.n_buckets, cfg.embed_dim)
        self.fc1 = nn.Linear(cfg.embed_dim + n_dense, cfg.hidden_dim)
        self.act = nn.GELU(approximate="tanh")
        self.tier_head = nn.Linear(cfg.hidden_dim, len(cfg.tier_vocab))
        self.risk_head = nn.Linear(cfg.hidden_dim, 1)
        self.cost_head = nn.Linear(cfg.hidden_dim, 1)

    def forward(
        self, bucket_idx: torch.Tensor, counts: torch.Tensor, dense: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """bucket_idx: Long[B,L]; counts: Float[B,L]; dense: Float[B,6] (normalized).

        Pad slots carry count 0.0, so any pad index contributes nothing to the
        pooled sum; the denominator clamp keeps an all-pad (empty-goal) row at
        exactly zero pooled activation.
        """
        emb = self.embedding(bucket_idx)  # [B, L, E]
        pooled = (counts.unsqueeze(-1) * emb).sum(dim=1) / counts.sum(
            dim=1, keepdim=True
        ).clamp(min=1.0)
        x = torch.cat([pooled, dense], dim=-1)
        h = self.act(self.fc1(x))
        tier_logits = self.tier_head(h)
        risk_logit = self.risk_head(h).squeeze(-1)
        cost_pred = self.cost_head(h).squeeze(-1)
        return tier_logits, risk_logit, cost_pred


def group_weights(
    records: list[dict], *, beta: float, weight_cap: float
) -> list[float]:
    """Advantage-derived per-record loss weights (group-relative, clipped).

    The group-relative advantage and the clipped-weight shapes here
    intentionally mirror group_advantages (apps/dottie/dottie/rl/grpo.py:45)
    and the clipped-surrogate outer breaker (grpo.py:149) — standalone
    implementation, imports NOTHING from there. Per-group mean rewards are
    computed over the FULL training set; adv_i = reward_i - group_mean;
    weight_i = min(exp(adv_i / beta), weight_cap). A degenerate group
    (all-equal rewards) yields adv 0 -> weight 1 for every member, matching
    the no-gradient-on-degenerate-group property of grpo.py:45.
    """
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for rec in records:
        g = rec["group"]
        sums[g] = sums.get(g, 0.0) + float(rec["reward"])
        counts[g] = counts.get(g, 0) + 1
    means = {g: sums[g] / counts[g] for g in sums}
    weights = []
    for rec in records:
        adv = float(rec["reward"]) - means[rec["group"]]
        weights.append(min(math.exp(adv / beta), weight_cap))
    return weights


def _dense_vec(dense: dict | None, features: tuple) -> np.ndarray:
    vec = np.zeros(len(features), dtype=np.float64)
    dense = dense or {}
    for j, feat in enumerate(features):
        val = dense.get(feat)
        if val is None:
            vec[j] = 0.0
        elif isinstance(val, bool):
            vec[j] = 1.0 if val else 0.0
        else:
            vec[j] = float(val)
    return vec


def train_model(
    cfg: OrchConfig, records: list[dict], *, time_budget_s: float | None = None
) -> tuple[OrchestratorNet, dict, dict]:
    """Advantage-weighted cross-entropy training over routing records.

    records: dicts with goal_text, dense, label_tier, reward, group,
    risk_target, cost_target. Returns (net, norms, history); norms hold the
    dense_mean/dense_std computed over ``records`` (std floored at 1e-6).
    ``time_budget_s`` is checked at epoch boundaries; an early stop is
    recorded honestly as history['stopped_early'] = True.
    """
    t0 = time.monotonic()
    torch.manual_seed(cfg.seed)
    random.seed(cfg.seed)
    np.random.seed(cfg.seed)

    n = len(records)
    if n == 0:
        raise ValueError("train_model requires at least one record")

    dense_mat = np.stack([_dense_vec(r.get("dense"), cfg.dense_features) for r in records])
    dense_mean = dense_mat.mean(axis=0)
    dense_std = np.maximum(dense_mat.std(axis=0), _STD_FLOOR)
    norms = {"dense_mean": dense_mean, "dense_std": dense_std}
    dn_mat = (dense_mat - dense_mean) / dense_std

    feats = [featurize(r["goal_text"], r.get("dense"), cfg) for r in records]
    y = torch.tensor(
        [cfg.tier_vocab.index(r["label_tier"]) for r in records], dtype=torch.long
    )
    risk_t = torch.tensor([float(r["risk_target"]) for r in records], dtype=torch.float32)
    cost_t = torch.tensor([float(r["cost_target"]) for r in records], dtype=torch.float32)
    wts = torch.tensor(
        group_weights(records, beta=cfg.beta, weight_cap=cfg.weight_cap),
        dtype=torch.float32,
    )
    dn_t = torch.tensor(dn_mat, dtype=torch.float32)

    net = OrchestratorNet(cfg)
    opt = torch.optim.Adam(net.parameters(), lr=cfg.lr)

    history: dict = {"epoch_loss": [], "stopped_early": False, "n_train": n}
    order = list(range(n))
    for epoch in range(cfg.epochs):
        if time_budget_s is not None and time.monotonic() - t0 > time_budget_s:
            history["stopped_early"] = True
            break
        random.shuffle(order)
        epoch_losses = []
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
            epoch_losses.append(float(loss.item()))
        history["epoch_loss"].append(sum(epoch_losses) / len(epoch_losses))
    history["epochs_run"] = len(history["epoch_loss"])
    history["wall_time_s"] = time.monotonic() - t0
    return net, norms, history


def _round1(vec) -> list[float]:
    return [round(float(v), 6) for v in vec]


def _round2(mat) -> list[list[float]]:
    return [[round(float(v), 6) for v in row] for row in mat]


def save_weights(
    net: OrchestratorNet,
    cfg: OrchConfig,
    norms: dict,
    path: str | Path,
    *,
    model_version: str,
    gate_passed: bool = False,
    provenance: dict | None = None,
    trained_at: str | None = None,
) -> Path:
    """Export the pinned schema_version-1 weights JSON.

    Linear weights are transposed to x@W orientation; all floats rounded to 6
    decimals (the documented parity tolerance absorbs this). ``trained_at``
    defaults to the current UTC time; pass an explicit ISO8601 string when a
    byte-reproducible export is required (e.g. determinism checks).
    """
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
                "dense_mean": _round1(norms["dense_mean"]),
                "dense_std": _round1(norms["dense_std"]),
            },
            "weights": {
                "embedding": _round2(net.embedding.weight.tolist()),
                "w1": _round2(net.fc1.weight.t().tolist()),
                "b1": _round1(net.fc1.bias.tolist()),
                "w_tier": _round2(net.tier_head.weight.t().tolist()),
                "b_tier": _round1(net.tier_head.bias.tolist()),
                "w_risk": _round1(net.risk_head.weight.squeeze(0).tolist()),
                "b_risk": round(float(net.risk_head.bias.item()), 6),
                "w_cost": _round1(net.cost_head.weight.squeeze(0).tolist()),
                "b_cost": round(float(net.cost_head.bias.item()), 6),
            },
        }
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return path
