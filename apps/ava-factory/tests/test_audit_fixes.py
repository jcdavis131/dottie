"""Regression tests for the audit fixes (honesty architecture).

Covers:
- fix 1: on_policy_distill.reverse_kl_loss works on real tensors (the old
  `isinstance(x, type(torch) and ...)` bug raised TypeError whenever torch
  was installed, killing the real KD path);
- fix 7: eval_frontier_rubric judges — no additive bonuses; keys absent =>
  PLAIN mock score labeled judge="mock"; real path constructs a proper
  authenticated POST (stubbed HTTP layer);
- fix 8: convert_to_hf real conversion round-trips the CPU-pilot checkpoint
  bit-faithfully (skipped if the pilot ckpt is absent);
- fixes 9/10: dataset heuristics are deterministic (same input -> same score,
  no random rejection) and renamed away from "reward";
- fix 2/15: server.VIEWER_HTML contains none of the old fabricated metric
  literals and fetches real data instead.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_PILOT_CKPT = _REPO / "runs" / "cpu_pilot" / "base" / "base_final.pt"


# ---------------------------------------------------------------- fix 1: KD


def test_reverse_kl_loss_real_tensors():
    torch = pytest.importorskip("torch")
    import torch.nn.functional as F

    from on_policy_distill import reverse_kl_loss

    torch.manual_seed(0)
    s = torch.randn(2, 4, 8)
    t = torch.randn(2, 4, 8)

    loss = reverse_kl_loss(s, t)
    assert isinstance(loss, torch.Tensor), "real tensors must produce a real tensor loss"

    log_ps = F.log_softmax(s, dim=-1)
    log_pt = F.log_softmax(t, dim=-1)
    manual = (log_ps.exp() * (log_ps - log_pt)).sum(-1).mean()
    assert torch.allclose(loss, manual, atol=1e-6)
    assert loss.item() > 0.0  # KL(p||q) > 0 for distinct distributions

    # KL(p||p) == 0
    zero = reverse_kl_loss(s, s)
    assert abs(float(zero)) < 1e-6

    # masked reduction path
    mask = torch.ones(2, 4)
    mask[:, -1] = 0
    masked = reverse_kl_loss(s, t, mask=mask)
    manual_masked = ((log_ps.exp() * (log_ps - log_pt)).sum(-1) * mask).sum() / mask.sum()
    assert torch.allclose(masked, manual_masked, atol=1e-6)


def test_reverse_kl_loss_gradient_flows():
    torch = pytest.importorskip("torch")
    from on_policy_distill import reverse_kl_loss

    torch.manual_seed(1)
    s = torch.randn(1, 3, 6, requires_grad=True)
    t = torch.randn(1, 3, 6)
    loss = reverse_kl_loss(s, t)
    loss.backward()
    assert s.grad is not None and torch.isfinite(s.grad).all()


# ------------------------------------------------- fix 7: judges, no bonuses


def _rubric():
    import eval_frontier_rubric as fr

    return fr.Rubric(
        id="R-TEST-01",
        category="Numerical Accuracy",
        criterion="Must mention key evidence: cash $160M",
        weight=1.0,
        eval_instructions="check",
        ground_truth_ref="cash $160M",
        required=False,
    )


_OUT = "Analysis: cash $160M runway per 10-Q p.12 with calculation and risk disclosed in detail here"


def _clear_judge_keys(monkeypatch):
    for k in ("META_API_KEY", "META_MUSE_API_KEY", "ZAI_API_KEY", "GLM_API_KEY",
              "ANTHROPIC_API_KEY", "META_MUSE_API_URL", "ZAI_OPENAI_URL", "GLM_MODEL"):
        monkeypatch.delenv(k, raising=False)


def test_judges_without_keys_return_plain_mock_score_labeled_mock(monkeypatch):
    _clear_judge_keys(monkeypatch)
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")  # nothing listens: instant refusal
    import eval_frontier_rubric as fr

    r = _rubric()
    base = fr.CriteriaJudge().score(r, _OUT, "gt")

    for cls in (fr.MetaMuseJudge, fr.Glm52Judge, fr.LocalHFJudge, fr.OllamaJudge):
        j = cls()
        got = j.score(r, _OUT, "gt")
        assert got == base, f"{cls.__name__} must return the PLAIN mock score (no +bonus), got {got} != {base}"
        assert j.label == "mock", f"{cls.__name__} must label fallback scores judge='mock'"


class _FakeResp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": '{"score": 0.7, "reason": "ok"}'}}]}


def _stub_post(monkeypatch, calls):
    import requests

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.update(url=url, json=json, headers=headers, timeout=timeout)
        return _FakeResp()

    monkeypatch.setattr(requests, "post", fake_post)


def test_meta_muse_judge_real_request_construction(monkeypatch):
    _clear_judge_keys(monkeypatch)
    monkeypatch.setenv("META_API_KEY", "test-key")
    calls = {}
    _stub_post(monkeypatch, calls)
    import eval_frontier_rubric as fr

    j = fr.MetaMuseJudge()
    score = j.score(_rubric(), _OUT, "gt")
    assert score == 0.7
    assert j.label == "meta"
    assert calls["url"] == "https://api.meta.ai/v1/chat/completions"
    assert calls["headers"]["Authorization"] == "Bearer test-key"
    assert calls["json"]["model"] == "muse-spark-1.1"
    assert any("Criterion" in m["content"] for m in calls["json"]["messages"])


def test_glm_judge_real_request_construction(monkeypatch):
    _clear_judge_keys(monkeypatch)
    monkeypatch.setenv("ZAI_API_KEY", "zai-test-key")
    calls = {}
    _stub_post(monkeypatch, calls)
    import eval_frontier_rubric as fr

    j = fr.Glm52Judge()
    score = j.score(_rubric(), _OUT, "gt")
    assert score == 0.7
    assert j.label == "glm-5.2"
    assert calls["url"] == "https://api.z.ai/api/paas/v4/chat/completions"
    assert calls["headers"]["Authorization"] == "Bearer zai-test-key"
    assert calls["json"]["model"] == "glm-5.2"


def test_no_additive_bonus_literals_in_judge_source():
    src = (_REPO / "eval_frontier_rubric.py").read_text(encoding="utf-8")
    for bonus in ("base + 0.05", "base + 0.06", "base + 0.07", "base + 0.08"):
        assert bonus not in src, f"additive judge bonus {bonus!r} must stay deleted"


# --------------------------------------------- fix 3: blueprint harness gate


def test_eval_branch_harness_real_mode_refuses():
    res = subprocess.run(
        [sys.executable, str(_REPO / "eval_branch_harness.py"), "--mode", "real"],
        capture_output=True, text=True, cwd=str(_REPO), timeout=120,
    )
    assert res.returncode != 0, "--mode real must refuse (blueprint mock only)"
    assert "evals.run_harness" in (res.stderr + res.stdout)


# ------------------------------------------------ fix 8: real conversion


@pytest.mark.skipif(not _PILOT_CKPT.exists(), reason="cpu_pilot checkpoint not built")
def test_convert_to_hf_round_trip(tmp_path):
    pytest.importorskip("torch")
    pytest.importorskip("safetensors")
    import convert_to_hf as conv

    out = conv.export(_PILOT_CKPT, tmp_path / "export", None, None, None, None)

    cfg = json.loads((out / "config.json").read_text())
    assert cfg["model_type"] == "ava-nano"
    assert cfg["d_model"] == 256 and cfg["vocab_size"] == 8192
    assert 13_000_000 < cfg["param_count"] < 16_000_000
    assert cfg["scale"] == "smoke_cpu_pilot", "pilot exports must carry the smoke scale label"
    assert cfg["tied_keys"], "tied embedding/verbalizer aliases must be recorded"
    assert (out / "model.safetensors").is_file()
    assert "smoke" in (out / "README.md").read_text().lower()

    # tokenizer byte-identical
    src_tok = _REPO / "runs" / "cpu_pilot" / "tokenizer" / "ava_nano_bpe.json"
    if src_tok.exists():
        assert (hashlib.sha256((out / "tokenizer.json").read_bytes()).hexdigest()
                == hashlib.sha256(src_tok.read_bytes()).hexdigest())

    # logits round-trip vs the original checkpoint
    assert conv.verify(_PILOT_CKPT, out), "converted safetensors must reproduce original logits"


# --------------------------------- fixes 9/10: deterministic heuristics


def test_logic_pipeline_heuristic_deterministic():
    import logic_textbook_pipeline as ltp

    ex = ltp.gen_jsonl_example("induction")
    assert "reward_heuristic" in ex and "reward_score" not in ex, \
        "field must be renamed reward_heuristic (it is a heuristic, not a reward)"
    scores = {ltp.heuristic_quality_score(ex["text"]) for _ in range(50)}
    assert len(scores) == 1, "same input must always produce the same score"
    assert ex["reward_heuristic"] == ltp.heuristic_quality_score(ex["text"])
    # structure markers must matter deterministically
    assert ltp.heuristic_quality_score("Theorem: x. Proof: y. Example: z. " + "w " * 40) > \
        ltp.heuristic_quality_score("plain filler text " + "w " * 40)


def test_dataset_expansion_filter_deterministic():
    from scripts.dataset_expansion import quality_filter

    good = ("# topic\n\nDefinition: d\nTheorem: t\nProof: p\nExample: e\n"
            + " ".join(f"reasoning step number{i} analysis" for i in range(30)))
    results = {quality_filter(good) for _ in range(200)}
    assert len(results) == 1, "quality_filter must be deterministic (no random rejection)"
    ok, reason = quality_filter(good)
    assert ok
    assert "heuristic_score" in reason, "reason string must name the heuristic, not 'reward'"

    src = (_REPO / "scripts" / "dataset_expansion.py").read_text(encoding="utf-8")
    assert "random.random()" not in src, "the random 5% rejection penalty must stay removed"


# ----------------------------------------- fix 2: viewer has no fake numbers


def test_viewer_html_has_no_fabricated_metric_literals():
    # Parse the source instead of importing server (fastapi may be absent in
    # the cpu image); VIEWER_HTML is a module-level literal in server.py.
    src = (_REPO / "server.py").read_text(encoding="utf-8")
    start = src.index('VIEWER_HTML = """')
    VIEWER_HTML = src[start:src.index('"""', start + len('VIEWER_HTML = """') + 1)]

    old_fakes = [
        "spider 0.23", "eight 0.18", "thinking 0.12", "focused 0.09",
        "leverage 0.04", "0.064", "0.23</", "AUC 0.91", "4.5 tok",
        "early 4.5", "veto 72%", "mass 0.064", ">0.22<", "5.2",
        "0/180 blackmail AUC",
    ]
    for lit in old_fakes:
        assert lit not in VIEWER_HTML, f"fabricated metric literal {lit!r} back in VIEWER_HTML"

    # placeholders + real data fetch must be present
    assert "—" in VIEWER_HTML, "metrics must render as placeholders until data arrives"
    assert "/jspace/inspect" in VIEWER_HTML, "viewer must fetch real inspect data on load"
    assert "make eval" in VIEWER_HTML, "viewer must point at `make eval` when no report exists"
