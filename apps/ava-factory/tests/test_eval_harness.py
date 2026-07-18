"""Eval harness correctness tests."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from ava.config import AvaConfig
from ava.model import build_model
from ava.tokenizer import AvaTokenizer
from evals.common import prep_eval
from evals.interventions import WorkspaceSwap, concept_vector
from evals.run_harness import run_harness, write_reports

_REPO = Path(__file__).resolve().parent.parent
_NANO_TOK = _REPO / "data" / "nano" / "tokenizer" / "ava_nano_bpe.json"


@pytest.fixture(scope="module")
def nano_random_model():
    if not _NANO_TOK.exists():
        pytest.skip("run scripts/build_eval_data.py first")
    torch.manual_seed(0)
    model = build_model(AvaConfig.load("nano")).eval()
    tok = AvaTokenizer.load(_NANO_TOK)
    return model, tok


def test_intervention_changes_logits(nano_random_model):
    model, tok = nano_random_model
    prep_eval(model)
    w1, w2 = "spider", "ant"
    pids = tok.encode("The animal is")
    with torch.no_grad():
        base = model(input_ids=torch.tensor([pids]))["lm_logits"]
    with WorkspaceSwap(model, tok, "system2", w1, w2):
        with torch.no_grad():
            swapped = model(input_ids=torch.tensor([pids]))["lm_logits"]
    assert not torch.allclose(base, swapped, atol=1e-5)
    with torch.no_grad():
        again = model(input_ids=torch.tensor([pids]))["lm_logits"]
    torch.testing.assert_close(base, again, atol=1e-5, rtol=1e-5)


def test_concept_vector_real_ids(nano_random_model):
    model, tok = nano_random_model
    word = "spider"
    vec, tid = concept_vector(model, tok, word)
    assert tid == tok.concept_token(word)
    row = model.lm_head.weight[tid]
    expected = torch.nn.functional.normalize(row, dim=0)
    torch.testing.assert_close(vec, expected, atol=1e-6, rtol=1e-6)
    torch.testing.assert_close(vec, row / row.norm(), atol=1e-6, rtol=1e-6)


def test_harness_smoke(nano_random_model, monkeypatch, tmp_path):
    model, tok = nano_random_model
    import evals.common as ec
    import evals.run_harness as rh

    held = _REPO / "data" / "nano" / "heldout_phase0.bin"
    if not held.exists():
        pytest.skip("heldout bins missing")

    report_json = tmp_path / "branch_eval_results_real.json"
    report_md = tmp_path / "REPORT_REAL.md"
    monkeypatch.setattr(rh, "REPORT_JSON", report_json)
    monkeypatch.setattr(rh, "REPORT_MD", report_md)

    def fake_load(ckpt, preset, device, **kw):
        return model, tok, "random-init"

    monkeypatch.setattr(rh, "load_model", fake_load)
    monkeypatch.setattr(ec, "heldout_path", lambda preset, phase: _REPO / "data" / "nano" / f"heldout_phase{phase}.bin")

    results = run_harness(
        preset="nano",
        base_ckpt="none",
        chat_ckpt="none",
        device="cpu",
        probe_n=5,
        skip_needle=True,
    )
    write_reports(results)
    assert "meta" in results

    def _finite_leaves(obj):
        if isinstance(obj, dict):
            for v in obj.values():
                yield from _finite_leaves(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from _finite_leaves(v)
        elif isinstance(obj, (int, float)):
            yield obj

    for branch in ("base", "chat"):
        jspace = results[branch]["jspace"]
        assert isinstance(jspace, list) and len(jspace) == 5
        for t in jspace:
            for v in _finite_leaves(t.get("measured", {})):
                assert math.isfinite(v)

    md = report_md.read_text(encoding="utf-8")
    for name in ("spider_ant", "france_china", "soccer_rugby", "spanish_french", "safety_blackmail"):
        assert name in md
    assert any(w in md for w in ("PASS", "FAIL", "MEASURED"))
