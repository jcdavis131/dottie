"""Tests for the orchestrator model pair (torch trainer + numpy-only inference).

Covers:
- REQUIRED torch/numpy parity: a trained net exported via save_weights and
  reloaded through orchestrator_infer must reproduce tier_logits, risk and
  cost within 1e-4 (6-decimal export rounding + float32/float64 mix);
- byte-identical exports across two identical training runs (determinism);
- group-relative advantage weighting shape (higher reward -> larger weight;
  degenerate group -> uniform weight 1.0; cap respected);
- featurize bucket stability across separate interpreter processes (guards
  against accidental use of process-randomized hash());
- the no-torch guard on orchestrator_infer.py;
- empty-goal predict (zero pooled embedding, no NaN);
- load_weights rejecting a shape-mangled weights file.

All records here are self-generated synthetic routing records — this suite
deliberately does NOT read the orchestration corpus (a parallel lane builds
it, and it may not exist yet).
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

# Both modules are top-level files in the ava-factory root — same sys.path
# pattern as tests/test_distill_ladder.py:27-35.
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import orchestrator_infer as oinfer
from orchestrator_model import (
    OrchConfig,
    group_weights,
    save_weights,
    train_model,
)

_WORDS = [
    "build", "compare", "monitor", "deploy", "research", "invoice", "schedule",
    "pipeline", "heartbeat", "sources", "chain", "goal", "launch", "fix",
    "report", "calendar", "benchmark", "loop", "test", "then",
]
_GROUPS = ["g0", "g1", "g2", "g3"]


def _small_cfg(**over) -> OrchConfig:
    # Small dims keep the suite fast; seed pinned per the packet.
    base = {"seed": 7, "n_buckets": 512, "embed_dim": 8, "hidden_dim": 16, "epochs": 2}
    base.update(over)
    return OrchConfig(**base)


def _synthetic_records(n: int, seed: int, cfg: OrchConfig) -> list[dict]:
    rng = random.Random(seed)
    records = []
    for _ in range(n):
        goal = " ".join(rng.choice(_WORDS) for _ in range(rng.randint(3, 12)))
        dense = {
            "n_words": float(rng.randint(1, 40)),
            "n_chain_signals": float(rng.randint(0, 4)),
            "has_code_terms": float(rng.randint(0, 1)),
            "latency_ms": rng.uniform(0.0, 5000.0),
            "tokens_est": rng.uniform(0.0, 9000.0),
            "attempt": float(rng.randint(1, 3)),
        }
        records.append(
            {
                "goal_text": goal,
                "dense": dense,
                "label_tier": rng.choice(list(cfg.tier_vocab)),
                "reward": rng.uniform(-1.0, 1.0),
                "group": rng.choice(_GROUPS),
                "risk_target": rng.random(),
                "cost_target": rng.uniform(0.0, 9.0),
            }
        )
    return records


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    """One real (tiny) training run + export, shared by the read-only tests."""
    cfg = _small_cfg()
    records = _synthetic_records(40, seed=11, cfg=cfg)
    net, norms, history = train_model(cfg, records)
    path = tmp_path_factory.mktemp("weights") / "champion_weights.json"
    save_weights(
        net,
        cfg,
        norms,
        path,
        model_version="test-orch-0",
        provenance={"trainer": "pytest", "corpus_source": "synthetic", "n_train": 40},
    )
    w = oinfer.load_weights(path)
    return cfg, net, norms, path, w, history


def _torch_forward(net, cfg, w, goal: str, dense: dict):
    """Torch-side reference forward for one goal, using the exported norms."""
    bucket_ids, counts, dense_vec = oinfer.featurize(goal, dense, w["config"])
    dn = (dense_vec - w["norms"]["dense_mean"]) / np.maximum(
        w["norms"]["dense_std"], 1e-6
    )
    L = max(1, len(bucket_ids))
    bucket_t = torch.zeros(1, L, dtype=torch.long)
    counts_t = torch.zeros(1, L, dtype=torch.float32)
    if bucket_ids:
        bucket_t[0, : len(bucket_ids)] = torch.tensor(bucket_ids, dtype=torch.long)
        counts_t[0, : len(counts)] = torch.tensor(counts, dtype=torch.float32)
    dense_t = torch.tensor(dn, dtype=torch.float32).unsqueeze(0)
    net.eval()
    with torch.no_grad():
        tier_logits, risk_logit, cost_pred = net(bucket_t, counts_t, dense_t)
    return (
        tier_logits[0].numpy().astype(np.float64),
        float(torch.sigmoid(risk_logit)[0]),
        float(cost_pred[0]),
    )


def test_parity_torch_vs_numpy(trained):
    """REQUIRED: exported weights reproduce the live net within 1e-4."""
    cfg, net, _norms, _path, w, _history = trained
    rng = random.Random(23)
    max_diff = 0.0
    for _ in range(25):
        goal = " ".join(rng.choice(_WORDS) for _ in range(rng.randint(0, 14)))
        dense = {f: rng.uniform(-2.0, 2.0) for f in cfg.dense_features}
        bucket_ids, counts, dense_vec = oinfer.featurize(goal, dense, w["config"])
        got = oinfer.forward(w, bucket_ids, counts, dense_vec)
        ref_logits, ref_risk, ref_cost = _torch_forward(net, cfg, w, goal, dense)
        max_diff = max(
            max_diff,
            float(np.max(np.abs(got["tier_logits"] - ref_logits))),
            abs(got["risk"] - ref_risk),
            abs(got["cost"] - ref_cost),
        )
        assert got["tier"] == cfg.tier_vocab[int(np.argmax(ref_logits))]
    assert max_diff <= 1e-4, f"parity drift {max_diff:.2e} exceeds 1e-4"


def test_training_determinism_byte_identical(tmp_path):
    cfg = _small_cfg()
    records = _synthetic_records(40, seed=11, cfg=cfg)
    paths = []
    for name in ("a.json", "b.json"):
        net, norms, _hist = train_model(cfg, records)
        p = tmp_path / name
        # trained_at pinned so byte-identity tests the training, not the clock.
        save_weights(
            net, cfg, norms, p,
            model_version="det-check", trained_at="2026-01-01T00:00:00Z",
        )
        paths.append(p)
    assert paths[0].read_bytes() == paths[1].read_bytes()


def test_advantage_weighting_shape():
    records = [
        {"group": "g", "reward": 0.9},
        {"group": "g", "reward": 0.1},
        {"group": "flat", "reward": 0.5},
        {"group": "flat", "reward": 0.5},
        {"group": "big", "reward": 100.0},
        {"group": "big", "reward": 0.0},
    ]
    wts = group_weights(records, beta=1.0, weight_cap=4.0)
    # Within one group the higher-reward record gets the larger weight.
    assert wts[0] > wts[1]
    # Degenerate group (all-equal rewards): adv 0 -> weight exactly 1 (uniform),
    # matching the no-gradient-on-degenerate-group property of grpo.py:45.
    assert wts[2] == pytest.approx(1.0)
    assert wts[3] == pytest.approx(1.0)
    # Weights never exceed the cap even for an extreme advantage.
    assert wts[4] == pytest.approx(4.0)
    assert all(w <= 4.0 for w in wts)


def test_featurize_stable_across_processes():
    """Bucket ids must come from sha256, not process-randomized hash()."""
    code = (
        f"import sys; sys.path.insert(0, {str(_REPO)!r})\n"
        "from orchestrator_infer import featurize\n"
        "ids, cts, dv = featurize('build a test pipeline then deploy', None,\n"
        "    {'n_buckets': 4096, 'dense_features': ['n_words', 'n_chain_signals',\n"
        "     'has_code_terms', 'latency_ms', 'tokens_est', 'attempt']})\n"
        "print(ids); print(cts)\n"
    )
    outs = [
        subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        ).stdout
        for _ in range(2)
    ]
    assert outs[0] == outs[1]
    assert outs[0].strip()  # non-empty: the featurizer actually produced buckets


def test_infer_module_has_no_torch_import():
    import re

    src = Path(oinfer.__file__).read_text(encoding="utf-8")
    offenders = [
        line for line in src.splitlines() if re.match(r"^\s*(import|from)\s+torch", line)
    ]
    assert offenders == [], f"orchestrator_infer.py must stay torch-free: {offenders}"


def test_predict_empty_goal(trained):
    _cfg, _net, _norms, _path, w, _history = trained
    out = oinfer.predict(w, "")
    assert out["tier"] in w["config"]["tier_vocab"]
    assert np.all(np.isfinite(out["tier_logits"]))
    assert 0.0 < out["risk"] < 1.0
    assert np.isfinite(out["cost"])
    assert out["tier_probs"] == pytest.approx(
        np.exp(out["tier_logits"]) / np.exp(out["tier_logits"]).sum(), abs=1e-9
    )
    assert out["model_version"] == "test-orch-0"
    assert out["gate_passed"] is False


def test_load_weights_rejects_bad_shapes(trained, tmp_path):
    _cfg, _net, _norms, path, _w, _history = trained
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["weights"]["b1"] = doc["weights"]["b1"][:-1]  # hidden_dim-1: shape mismatch
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="b1"):
        oinfer.load_weights(bad)
    # Wrong schema_version is also rejected, with a clear message.
    doc2 = json.loads(path.read_text(encoding="utf-8"))
    doc2["schema_version"] = 2
    bad2 = tmp_path / "bad2.json"
    bad2.write_text(json.dumps(doc2), encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version"):
        oinfer.load_weights(bad2)


def test_history_is_honest(trained):
    _cfg, _net, _norms, _path, _w, history = trained
    assert history["epochs_run"] == 2
    assert history["stopped_early"] is False
    assert history["n_train"] == 40
    assert len(history["epoch_loss"]) == 2
    assert all(np.isfinite(x) for x in history["epoch_loss"])


def test_time_budget_stops_early():
    cfg = _small_cfg(epochs=50)
    records = _synthetic_records(40, seed=11, cfg=cfg)
    _net, _norms, history = train_model(cfg, records, time_budget_s=0.0)
    assert history["stopped_early"] is True
    assert history["epochs_run"] < 50
