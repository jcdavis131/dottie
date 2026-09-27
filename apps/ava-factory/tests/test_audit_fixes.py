"""Regression tests for the audit fixes (honesty architecture).

Covers:
- fix 7: eval_frontier_rubric judges — no additive bonuses; judge unavailable
  => PLAIN mock score labeled judge="mock". The paid API judges (Meta Muse,
  GLM-5.2) and their request-construction tests were removed 2026-09-27 (no
  paid APIs); a guard test keeps them out and pins the qwen3:8b default;
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


def test_judges_without_backend_return_plain_mock_score_labeled_mock(monkeypatch):
    monkeypatch.setenv(
        "OLLAMA_HOST", "http://127.0.0.1:9"
    )  # nothing listens: instant refusal
    import eval_frontier_rubric as fr

    r = _rubric()
    base = fr.CriteriaJudge().score(r, _OUT, "gt")

    for cls in (fr.LocalHFJudge, fr.OllamaJudge):
        j = cls()
        got = j.score(r, _OUT, "gt")
        assert got == base, (
            f"{cls.__name__} must return the PLAIN mock score (no +bonus), got {got} != {base}"
        )
        assert j.label == "mock", (
            f"{cls.__name__} must label fallback scores judge='mock'"
        )


def test_paid_api_judges_stay_removed_and_default_is_local_qwen3_8b(monkeypatch):
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.setenv(
        "OLLAMA_HOST", "http://127.0.0.1:9"
    )  # nothing listens: instant refusal
    import eval_frontier_rubric as fr

    for gone in ("MetaMuseJudge", "Glm52Judge", "_post_openai_chat"):
        assert not hasattr(fr, gone), f"{gone} is a paid-API path and must stay removed"
    # the old paid selectors now fall through to the plain mock judge, never an API
    for name in ("meta", "glm", "glm52", "glm-5.2", "zai"):
        assert type(fr.get_judge(name)) is fr.CriteriaJudge
    assert fr.OllamaJudge().model == "qwen3:8b"
    src = (_REPO / "eval_frontier_rubric.py").read_text(encoding="utf-8")
    for host in ("api.meta.ai", "api.z.ai", "ANTHROPIC_API_KEY"):
        assert host not in src, f"paid endpoint/key {host!r} must stay out of the judge"


def test_no_additive_bonus_literals_in_judge_source():
    src = (_REPO / "eval_frontier_rubric.py").read_text(encoding="utf-8")
    for bonus in ("base + 0.05", "base + 0.06", "base + 0.07", "base + 0.08"):
        assert bonus not in src, f"additive judge bonus {bonus!r} must stay deleted"


# --------------------------------------------- fix 3: blueprint harness gate


def test_eval_branch_harness_real_mode_refuses():
    res = subprocess.run(
        [sys.executable, str(_REPO / "eval_branch_harness.py"), "--mode", "real"],
        capture_output=True,
        text=True,
        cwd=str(_REPO),
        timeout=120,
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
    assert cfg["scale"] == "smoke_cpu_pilot", (
        "pilot exports must carry the smoke scale label"
    )
    assert cfg["tied_keys"], "tied embedding/verbalizer aliases must be recorded"
    assert (out / "model.safetensors").is_file()
    assert "smoke" in (out / "README.md").read_text().lower()

    # tokenizer byte-identical
    src_tok = _REPO / "runs" / "cpu_pilot" / "tokenizer" / "ava_nano_bpe.json"
    if src_tok.exists():
        assert (
            hashlib.sha256((out / "tokenizer.json").read_bytes()).hexdigest()
            == hashlib.sha256(src_tok.read_bytes()).hexdigest()
        )

    # logits round-trip vs the original checkpoint
    assert conv.verify(_PILOT_CKPT, out), (
        "converted safetensors must reproduce original logits"
    )


# --------------------------------- fixes 9/10: deterministic heuristics


def test_logic_pipeline_heuristic_deterministic():
    import logic_textbook_pipeline as ltp

    ex = ltp.gen_jsonl_example("induction")
    assert "reward_heuristic" in ex and "reward_score" not in ex, (
        "field must be renamed reward_heuristic (it is a heuristic, not a reward)"
    )
    scores = {ltp.heuristic_quality_score(ex["text"]) for _ in range(50)}
    assert len(scores) == 1, "same input must always produce the same score"
    assert ex["reward_heuristic"] == ltp.heuristic_quality_score(ex["text"])
    # structure markers must matter deterministically
    assert ltp.heuristic_quality_score(
        "Theorem: x. Proof: y. Example: z. " + "w " * 40
    ) > ltp.heuristic_quality_score("plain filler text " + "w " * 40)


def test_dataset_expansion_filter_deterministic():
    from scripts.dataset_expansion import quality_filter

    good = "# topic\n\nDefinition: d\nTheorem: t\nProof: p\nExample: e\n" + " ".join(
        f"reasoning step number{i} analysis" for i in range(30)
    )
    results = {quality_filter(good) for _ in range(200)}
    assert len(results) == 1, (
        "quality_filter must be deterministic (no random rejection)"
    )
    ok, reason = quality_filter(good)
    assert ok
    assert "heuristic_score" in reason, (
        "reason string must name the heuristic, not 'reward'"
    )

    src = (_REPO / "scripts" / "dataset_expansion.py").read_text(encoding="utf-8")
    assert "random.random()" not in src, (
        "the random 5% rejection penalty must stay removed"
    )


# ----------------------------------------- fix 2: viewer has no fake numbers


def test_viewer_html_has_no_fabricated_metric_literals():
    # Parse the source instead of importing server (fastapi may be absent in
    # the cpu image); VIEWER_HTML is a module-level literal in server.py.
    src = (_REPO / "server.py").read_text(encoding="utf-8")
    start = src.index('VIEWER_HTML = """')
    VIEWER_HTML = src[start : src.index('"""', start + len('VIEWER_HTML = """') + 1)]

    old_fakes = [
        "spider 0.23",
        "eight 0.18",
        "thinking 0.12",
        "focused 0.09",
        "leverage 0.04",
        "0.064",
        "0.23</",
        "AUC 0.91",
        "4.5 tok",
        "early 4.5",
        "veto 72%",
        "mass 0.064",
        ">0.22<",
        "5.2",
        "0/180 blackmail AUC",
    ]
    for lit in old_fakes:
        assert lit not in VIEWER_HTML, (
            f"fabricated metric literal {lit!r} back in VIEWER_HTML"
        )

    # placeholders + real data fetch must be present
    assert "—" in VIEWER_HTML, "metrics must render as placeholders until data arrives"
    assert "/jspace/inspect" in VIEWER_HTML, (
        "viewer must fetch real inspect data on load"
    )
    assert "make eval" in VIEWER_HTML, (
        "viewer must point at `make eval` when no report exists"
    )
