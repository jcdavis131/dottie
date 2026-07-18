# Solo personal project, no connection to employer, built with public/free-tier only
"""Runner/CLI/registry/task tests + the real-mode smoke test.

The real-mode smoke test is the headline: it loads the factory cpu_pilot
checkpoint (REAL ~14M-param smoke-scale artifact) and runs the wired real
paths end-to-end, asserting real finite floats and the smoke-scale honesty
labels. Skipped when the checkpoint/tokenizer/torch are absent.
"""
import json
import math
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.common import MockModel, MockTokenizer, factory_root  # noqa: E402
from harness.registry import EVAL_REGISTRY, register_eval  # noqa: E402
from harness.runner import (  # noqa: E402
    _try_load_yaml_tasks, resolve_eval_names, run_harness, write_reports,
)
from harness.evals.needle import needle  # noqa: E402
from harness.evals.perplexity import perplexity  # noqa: E402
from harness.evals.probes import probes  # noqa: E402
from harness.evals.openwiki_knowledge import openwiki_knowledge  # noqa: E402

FACTORY = Path(os.environ.get("AVA_FACTORY_ROOT", "/home/user/ava-agi-factory-v6-4"))
CKPT = FACTORY / "runs" / "cpu_pilot" / "base" / "base_final.pt"
TOKENIZER = FACTORY / "runs" / "cpu_pilot" / "tokenizer" / "ava_nano_bpe.json"


def _torch_available() -> bool:
    try:
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


class TestEvalNameResolution:
    def test_unknown_eval_name_is_hard_error(self):
        with pytest.raises(ValueError) as exc:
            resolve_eval_names("definitely_not_an_eval")
        # error must list the valid names, not silently run everything
        assert "spider_ant" in str(exc.value)

    def test_group_name_resolves_to_group_members(self):
        names = resolve_eval_names("jspace")
        assert set(names) == {"spider_ant", "france_china", "soccer_rugby",
                              "spanish_french", "safety_blackmail", "jspace_all"}

    def test_run_harness_rejects_unknown_eval(self):
        with pytest.raises(ValueError):
            run_harness(eval_names="typo_eval", mode="mock")


class TestReportsAndSamples:
    def test_write_reports_shape(self, tmp_path):
        res = run_harness(eval_names=["spider_ant", "perplexity"], mode="mock")
        json_path, md_path = write_reports(res, out_dir=str(tmp_path))
        blob = json.loads(Path(json_path).read_text())
        assert set(blob) == {"meta", "evals"}
        assert set(blob["evals"]) == {"spider_ant", "perplexity"}
        assert blob["meta"]["total"] == 2
        md = Path(md_path).read_text()
        assert "spider_ant" in md and "perplexity" in md

    def test_log_samples_honesty(self):
        # perplexity's mock measured has no per-sample list → MUST be [] (never
        # synthesized); france_china provides real per-prompt details → passed through.
        res = run_harness(eval_names=["perplexity", "france_china"], mode="mock", log_samples=5)
        assert res["evals"]["perplexity"]["log_samples"] == []
        fc = res["evals"]["france_china"]["log_samples"]
        assert fc and all("prompt" in row for row in fc)

    def test_meta_has_no_fabricated_speedup_or_marketing(self):
        res = run_harness(eval_names=["spider_ant"], mode="mock")
        assert "wall_s_theoretical_vllm" not in res["meta"]
        assert "optimization_target" not in res["meta"]
        assert "vllm_available" not in res["meta"]


class TestRegistry:
    def test_duplicate_name_raises(self):
        @register_eval(name="_dup_probe_eval", description="x", group="test")
        def _e1(model, tokenizer, device, **kw):
            return {}
        try:
            with pytest.raises(ValueError):
                @register_eval(name="_dup_probe_eval", description="y", group="test")
                def _e2(model, tokenizer, device, **kw):
                    return {}
        finally:
            EVAL_REGISTRY.pop("_dup_probe_eval", None)


class TestMockSeedVariation:
    @pytest.mark.parametrize("fn", [needle, perplexity, probes, openwiki_knowledge])
    def test_mock_measured_varies_with_seed(self, fn):
        m1 = fn(MockModel(seed=1), MockTokenizer(), "cpu")["measured"]
        m2 = fn(MockModel(seed=2), MockTokenizer(), "cpu")["measured"]
        assert m1 != m2, f"{fn.__name__} mock measured did not vary with seed"


class TestYamlTasks:
    def test_all_11_tasks_ship_and_are_versioned(self):
        tasks = _try_load_yaml_tasks()
        expected = {"spider_ant", "france_china", "soccer_rugby", "spanish_french",
                    "safety_blackmail", "jspace_all", "frontier_rubric", "probes",
                    "perplexity", "needle", "openwiki_knowledge"}
        assert expected <= set(tasks)
        for name in expected:
            t = tasks[name]
            assert str(t["version"]) == "1.0"
            assert t.get("bar") and t.get("group")


_REAL_READY = CKPT.exists() and TOKENIZER.exists() and _torch_available()


@pytest.fixture(scope="module")
def real_report():
    return run_harness(
        eval_names=["spider_ant", "perplexity"],
        mode="real",
        ckpt=str(CKPT),
        tokenizer=str(TOKENIZER),
        ppl_max_windows=6,
    )


@pytest.mark.skipif(not _REAL_READY, reason="cpu_pilot checkpoint/tokenizer or torch absent")
class TestRealModeSmoke:
    """Headline: real end-to-end run on the factory cpu_pilot smoke checkpoint.

    The measured values are honest near-zero capability numbers — that is
    CORRECT at smoke scale; the assertions check realness (finite floats from
    live forwards) and honesty labels, not capability."""

    def test_real_load_succeeded(self, real_report):
        assert real_report["meta"].get("real_load_failed") is not True
        assert real_report["meta"]["mode"] == "real"
        assert real_report["meta"]["factory_available"] is True

    def test_spider_ant_real_measurements(self, real_report):
        sa = real_report["evals"]["spider_ant"]
        assert "error" not in sa, sa.get("error")
        m = sa["measured"]
        for key in ("logP_base_8", "logP_base_6", "logP_int_8", "logP_int_6", "causal_effect"):
            assert isinstance(m[key], float) and math.isfinite(m[key]), key
        # logprobs are real log-softmax sums → strictly negative
        assert m["logP_base_8"] < 0 and m["logP_base_6"] < 0
        assert sa["scale"] == "smoke"
        assert sa["capability_claim"] == "none"

    def test_perplexity_real_measurements(self, real_report):
        pp = real_report["evals"]["perplexity"]
        assert "error" not in pp, pp.get("error")
        m = pp["measured"]
        assert isinstance(m["avg_ppl"], float) and math.isfinite(m["avg_ppl"]) and m["avg_ppl"] > 0
        assert m["tokens"] > 0
        # source honesty: either true heldout bins or explicitly-labeled fallback
        assert m.get("heldout") in (True, False)
        assert pp["scale"] == "smoke"
        assert pp["capability_claim"] == "none"
