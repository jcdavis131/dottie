"""Fast-mode tests for the orchestrator hill-climb driver.

Hermetic: never reads the real corpus and never writes the real reports dir —
every run points --corpus/--out at tmp_path. Covers:
- promotion_gate purity: strictly-better-than-both semantics, the
  insufficient-measured-data reason, equal accuracy never passing, and the
  never-pass-on-missing-metric rule;
- an end-to-end fast run over a tiny fixture corpus (2 variants, 3 s budget):
  all three artifacts exist, per-variant train_seconds are measured (> 0), and
  champion_weights.json matches the pinned schema with consistent shapes;
- determinism of variant seeding (identical val_tier_accuracy across two runs);
- the embedded battery fallback when --corpus points at a missing file
  (corpus_source recorded, gate honestly failed on zero measured records);
- a smoke of the in-script fallback trainer/inference pair (the path taken
  when the model modules are absent).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

# The driver lives in scripts/ — same sys.path pattern as test_distill_ladder.py.
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import orchestrator_hillclimb as ohc

# ---------------------------------------------------------------------------
# promotion_gate unit tests (pure function)
# ---------------------------------------------------------------------------


def test_gate_passes_only_when_strictly_better_than_both():
    champ = {"tier_accuracy_measured": 0.8}
    base = {"freq_prior_accuracy_measured": 0.5, "heuristic_accuracy_measured": 0.6}
    out = ohc.promotion_gate(champ, base, 20)
    assert out["gate_passed"] is True
    assert isinstance(out["reason"], str) and out["reason"]

    # Beats one baseline but not the other: no pass.
    worse = ohc.promotion_gate(
        {"tier_accuracy_measured": 0.55}, base, 20
    )
    assert worse["gate_passed"] is False

    # Below both: no pass.
    below = ohc.promotion_gate({"tier_accuracy_measured": 0.3}, base, 20)
    assert below["gate_passed"] is False


def test_gate_never_passes_on_equal_accuracy():
    base = {"freq_prior_accuracy_measured": 0.6, "heuristic_accuracy_measured": 0.6}
    out = ohc.promotion_gate({"tier_accuracy_measured": 0.6}, base, 15)
    assert out["gate_passed"] is False
    assert "does not strictly beat" in out["reason"]


def test_gate_insufficient_measured_data_reason():
    base = {"freq_prior_accuracy_measured": 0.0, "heuristic_accuracy_measured": 0.0}
    out = ohc.promotion_gate({"tier_accuracy_measured": 1.0}, base, 3)
    assert out["gate_passed"] is False
    assert out["reason"] == "insufficient measured held-out data (n=3, need >=10)"


def test_gate_never_passes_on_missing_or_nan_metrics():
    champ = {"tier_accuracy_measured": 0.9}
    missing = ohc.promotion_gate(
        champ,
        {"freq_prior_accuracy_measured": 0.1, "heuristic_accuracy_measured": None},
        12,
    )
    assert missing["gate_passed"] is False
    assert "never pass the gate on missing metrics" in missing["reason"]

    nan = ohc.promotion_gate(
        {"tier_accuracy_measured": float("nan")},
        {"freq_prior_accuracy_measured": 0.1, "heuristic_accuracy_measured": 0.1},
        12,
    )
    assert nan["gate_passed"] is False


# ---------------------------------------------------------------------------
# Fixture corpus + end-to-end fast runs
# ---------------------------------------------------------------------------

_GOALS = [
    "monitor the heartbeat tick for billing",
    "compare stripe vs paddle pricing with sources",
    "schedule a calendar slot and pay the invoice via gmail",
    "build and launch the export factory end-to-end then ship it",
    "run the nightly cron job for search",
    "research the sota paper on routing with triangulation sources",
]
_TIERS = list(ohc.TIER_VOCAB)


def _record(i: int, *, goal: str, tier: str, bucket: int, provenance: str,
            status: str, reward: float, split_key: str, source: str) -> dict:
    n_words = len(goal.split())
    return {
        "schema_version": 1,
        "record_id": f"fix-{i:03d}",
        "source": source,
        "provenance": provenance,
        "provenance_fields": {"label_tier": provenance},
        "features": {
            "goal_text": goal,
            "n_words": n_words,
            "n_chain_signals": 1 if "then" in goal else 0,
            "has_code_terms": "build" in goal,
            "latency_ms": 10.0 + i,
            "tokens_est": 40 + i,
            "attempt": 1,
            "layer": None,
            "phase": None,
            "n_tool_calls": None,
            "duration_s": None,
            "output_tokens": None,
        },
        "label_tier": tier,
        "label_agents_n": 2,
        "reward": reward,
        "latency_ms": 10.0 + i,
        "tokens_est": 40 + i,
        "status": status,
        "errorClass": None if status == "ok" else "TestError",
        "split_key": split_key,
        "split_bucket": bucket,
    }


def _write_fixture_corpus(path: Path) -> None:
    """~80 records: 60 simulated battery-style over buckets 0-9 + 20 measured
    (mixed ok/failed statuses, non-empty goal_text, 12 landing in bucket 9)."""
    rows = []
    for i in range(60):
        rows.append(
            _record(
                i,
                goal=_GOALS[i % len(_GOALS)],
                tier=_TIERS[i % len(_TIERS)],
                bucket=i % 10,
                provenance="simulated",
                status="ok",
                reward=1.0,
                split_key=f"tpl-{i % 6:03d}",
                source="synthetic_battery",
            )
        )
    for j in range(20):
        i = 60 + j
        bucket = 9 if j < 12 else j % 8  # 12 measured records in the held-out bucket
        rows.append(
            _record(
                i,
                goal=_GOALS[(j + 1) % len(_GOALS)] + " for tenant " + str(j),
                tier=_TIERS[j % len(_TIERS)],
                bucket=bucket,
                provenance="measured",
                status="ok" if j % 3 else "failed",
                reward=0.7 if j % 3 else -0.5,
                split_key=f"run-{j:03d}",
                source="workflow_journal",
            )
        )
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _run(tmp_path: Path, corpus: Path, out_name: str, variants: int = 2) -> Path:
    out = tmp_path / out_name
    rc = ohc.main(
        [
            "--corpus", str(corpus),
            "--out", str(out),
            "--variants", str(variants),
            "--time-budget", "3",
        ]
    )
    assert rc == 0
    return out


@pytest.fixture(scope="module")
def fast_run(tmp_path_factory):
    """One shared fast end-to-end run over the fixture corpus."""
    tmp = tmp_path_factory.mktemp("hillclimb")
    corpus = tmp / "corpus.jsonl"
    _write_fixture_corpus(corpus)
    out = _run(tmp, corpus, "out_a")
    return tmp, corpus, out


def test_end_to_end_fast_artifacts(fast_run):
    _tmp, _corpus, out = fast_run
    for name in ("ladder_report.json", "eval_report.json", "champion_weights.json"):
        assert (out / name).exists(), f"missing artifact {name}"

    ladder = json.loads((out / "ladder_report.json").read_text(encoding="utf-8"))
    assert ladder["schema_version"] == 1
    assert ladder["corpus_source"] == "l2_corpus"
    assert len(ladder["variants"]) == 2
    for v in ladder["variants"]:
        assert v["train_seconds"] > 0  # measured, not fabricated
        assert v["n_train"] > 0
        assert v["epochs_run"] >= 1
        assert v["val_tier_accuracy"] is not None

    ev = json.loads((out / "eval_report.json").read_text(encoding="utf-8"))
    assert isinstance(ev["gate"]["reason"], str) and ev["gate"]["reason"]
    assert isinstance(ev["gate"]["gate_passed"], bool)
    assert ev["champion"]["n_measured_holdout"] == 12
    assert ev["champion"]["agreement"]["note"].startswith("counterfactual rewards unobserved")
    assert ev["champion"]["risk_calibration"]["brier"] is not None
    assert len(ev["champion"]["risk_calibration"]["deciles"]) == 10


def test_champion_weights_pinned_schema(fast_run):
    _tmp, _corpus, out = fast_run
    doc = json.loads((out / "champion_weights.json").read_text(encoding="utf-8"))
    for key in ("schema_version", "model_version", "gate_passed", "trained_at",
                "provenance", "config", "norms", "weights"):
        assert key in doc, f"champion weights missing key {key}"
    assert doc["schema_version"] == 1
    assert doc["model_version"].startswith("orch-mlp-v1-v")
    assert doc["provenance"]["corpus_source"] == "l2_corpus"

    cfg = doc["config"]
    w = doc["weights"]
    embed_dim, hidden_dim = cfg["embed_dim"], cfg["hidden_dim"]
    assert cfg["tier_vocab"] == list(ohc.TIER_VOCAB)
    assert cfg["dense_features"] == list(ohc.DENSE_FEATURES)
    assert len(w["embedding"]) == cfg["n_buckets"]
    assert len(w["embedding"][0]) == embed_dim
    assert len(w["w1"]) == embed_dim + 6
    assert len(w["w1"][0]) == hidden_dim
    assert len(w["w_tier"]) == hidden_dim
    assert len(w["b_tier"]) == 5
    assert len(w["w_risk"]) == hidden_dim
    assert isinstance(w["b_risk"], float)


def test_variant_seeding_deterministic(fast_run):
    tmp, corpus, out_a = fast_run
    out_b = _run(tmp, corpus, "out_b")
    accs_a = [v["val_tier_accuracy"] for v in json.loads(
        (out_a / "ladder_report.json").read_text(encoding="utf-8"))["variants"]]
    accs_b = [v["val_tier_accuracy"] for v in json.loads(
        (out_b / "ladder_report.json").read_text(encoding="utf-8"))["variants"]]
    assert accs_a == accs_b


def test_fallback_corpus_when_file_missing(tmp_path):
    out = _run(tmp_path, tmp_path / "does_not_exist.jsonl", "out_fb", variants=1)
    ladder = json.loads((out / "ladder_report.json").read_text(encoding="utf-8"))
    assert ladder["corpus_source"] == "embedded_battery_fallback"
    ev = json.loads((out / "eval_report.json").read_text(encoding="utf-8"))
    assert ev["corpus_source"] == "embedded_battery_fallback"
    # The fallback battery is fully simulated: zero measured records, so the
    # gate must fail with the insufficient-measured reason — never massaged.
    assert ev["gate"]["gate_passed"] is False
    assert ev["gate"]["reason"].startswith("insufficient measured held-out data (n=0")
    doc = json.loads((out / "champion_weights.json").read_text(encoding="utf-8"))
    assert doc["gate_passed"] is False
    assert doc["provenance"]["corpus_source"] == "embedded_battery_fallback"


# ---------------------------------------------------------------------------
# In-script fallback trainer/inference smoke (model-modules-absent path)
# ---------------------------------------------------------------------------


def test_embedded_fallback_trainer_smoke(tmp_path):
    cfg = ohc._FbConfig(n_buckets=256, embed_dim=8, hidden_dim=16, seed=5, epochs=2)
    records = [
        {
            "goal_text": _GOALS[i % len(_GOALS)],
            "dense": {f: float(i % 4) for f in ohc.DENSE_FEATURES},
            "label_tier": _TIERS[i % len(_TIERS)],
            "reward": (-1.0) ** i * 0.5,
            "group": f"g{i % 3}",
            "risk_target": float(i % 2),
            "cost_target": 2.0,
        }
        for i in range(20)
    ]
    net, norms, history = ohc._fb_train_model(cfg, records)
    assert history["epochs_run"] == 2
    assert all(np.isfinite(x) for x in history["epoch_loss"])
    path = tmp_path / "fb_weights.json"
    ohc._fb_save_weights(net, cfg, norms, path, model_version="fb-smoke")
    w = ohc._fb_load_weights(path)
    ids, cts, dv = ohc._fb_featurize("build the pipeline then deploy", None, w["config"])
    out = ohc._fb_forward(w, ids, cts, dv)
    assert out["tier"] in ohc.TIER_VOCAB
    assert np.all(np.isfinite(out["tier_logits"]))
    assert 0.0 < out["risk"] < 1.0
