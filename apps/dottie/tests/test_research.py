# Solo personal project, no connection to employer, built with public/free-tier only
"""Tests for the research loop — ledger state machine, 4-level validator + self-correction,
constrained prompts + JSON parsing, the four workers end-to-end (real CPU training, honest
promote/reject/fail paths), and honest Ollama refusal. CPU-only, no network."""

from __future__ import annotations

import json

import pytest

from dottie.research import evaluate, ideation, implementation, logger, prompts, train, validate
from dottie.research.ledger import (
    Ledger, Baseline, IllegalTransition,
    PENDING, READY_FOR_TRAINING, EVALUATION_PENDING, SOTA, REJECTED,
    FAILED_VALIDATION, FAILED_TRAINING,
)
from tests.conftest import UNROUTABLE_OLLAMA


# --------------------------------------------------------------------------- fixtures / stand-ins

GOOD_CODE = '''import torch
import torch.nn as nn
class SeqMeanMix(nn.Module):
    def __init__(self, dim: int = 64):
        super().__init__()
        self.mix = nn.Linear(dim, dim)
    def forward(self, x):
        # [batch, seq, dim] -> [batch, seq, dim]
        assert x.dim() == 3
        ctx = x.mean(dim=1, keepdim=True)
        return x + self.mix(ctx)
'''
NAN_CODE = '''import torch
import torch.nn as nn
class Diverge(nn.Module):
    def __init__(self, dim: int = 64):
        super().__init__()
        self.w = nn.Linear(dim, dim)
    def forward(self, x):
        return self.w(x) / torch.zeros_like(x)   # -> NaN/Inf, unstable
'''

HYP = {"hypothesis_name": "SeqMeanMix", "theoretical_intuition": "mix seq via mean + residual",
       "mathematical_formulation": "$y=x+W\\,mean_s(x)$",
       "pytorch_implementation_strategy": "nn.Linear over pooled ctx",
       "expected_outcome": "lower proxy_loss", "search_domain": "attention"}


def impl_json(code=GOOD_CODE, name="SeqMeanMix", shape=None):
    return json.dumps({"module_name": name, "target_file": f"ava/models/{name.lower()}.py",
                       "code": code, "init_kwargs": {"dim": 64},
                       "input_shape": shape or [8, 16, 64], "shape_assertions": "residual"})


def make_policy(code=GOOD_CODE, name="SeqMeanMix"):
    def policy(prompt: str) -> str:
        if "Principal ML Engineer" in prompt or "failed automated validation" in prompt:
            return "```json\n" + impl_json(code, name) + "\n```"
        return json.dumps(HYP)
    return policy


@pytest.fixture()
def led(tmp_path):
    L = Ledger(tmp_path / "ledger.sqlite3")
    L.seed_baseline(Baseline("proxy_loss", 4.5, higher_is_better=False,
                             architecture="ava-nano", experiment_id=None, updated_ts=0.0,
                             notes="proxy baseline"))
    return L


# --------------------------------------------------------------------------- ledger

def test_ledger_state_machine_and_baseline(led):
    e = led.create(HYP)
    assert e.state == PENDING and e.name == "SeqMeanMix"
    led.transition(e.id, READY_FOR_TRAINING, implementation={"code": "x"}, workspace="/w")
    led.transition(e.id, EVALUATION_PENDING, train_metrics={"proxy_loss": 2.0})
    with pytest.raises(IllegalTransition):
        led.transition(e.id, PENDING)  # cannot go backwards
    led.transition(e.id, SOTA, eval_verdict={"promote": True})
    with pytest.raises(IllegalTransition):
        led.transition(e.id, REJECTED)  # terminal
    b = led.get_baseline()
    assert b.improves(2.0) and not b.improves(5.0)  # lower is better
    led.promote_baseline(e.id, 2.0)
    assert led.get_baseline().metric_value == 2.0
    assert led.counts()["sota"] == 1


def test_illegal_target_and_unknown_field(led):
    e = led.create(HYP)
    with pytest.raises(Exception):
        led.transition(e.id, "banana")
    with pytest.raises(Exception):
        led.set_fields(e.id, not_a_field=1)


# --------------------------------------------------------------------------- validator

def test_validator_levels():
    assert validate.validate(GOOD_CODE, class_name="SeqMeanMix", input_shape=[4, 16, 64]).ok
    assert validate.validate("def f(:\n x").level == "syntax"
    r = validate.validate("import torch.nn as nn\nclass X(nn.Module):\n    def g(self):return 1\n")
    assert r.level == "contract" and not r.ok
    r = validate.validate("import os\nimport torch.nn as nn\nclass X(nn.Module):\n"
                          "    def forward(self,x):return x\n")
    assert r.level == "contract" and "illegal imports" in r.detail
    # undefined name (torch not imported) -> static (ruff) or dry_run
    r = validate.validate("import torch.nn as nn\nclass X(nn.Module):\n"
                          "    def forward(self,x):return torch.relu(x)\n",
                          class_name="X", input_shape=[2, 4, 8])
    assert not r.ok and r.level in ("static", "dry_run")
    r = validate.validate(NAN_CODE, class_name="Diverge", input_shape=[2, 4, 8])
    assert r.level == "dry_run" and "NaN" in r.detail


def test_self_correction_fix_and_giveup():
    out = validate.validate_with_correction("def bad(:", lambda c, f: GOOD_CODE,
                                             class_name="SeqMeanMix", input_shape=[4, 16, 64])
    assert out.ok and out.attempts == 1
    out2 = validate.validate_with_correction("def bad(:", lambda c, f: "def still(:",
                                              max_retries=3)
    assert not out2.ok and out2.attempts == 3
    # a corrector that itself raises (LLM down mid-correction) stops honestly
    def dying(c, f):
        raise RuntimeError("ollama died")
    out3 = validate.validate_with_correction("def bad(:", dying, max_retries=3)
    assert not out3.ok and out3.attempts == 1


# --------------------------------------------------------------------------- prompts

def test_prompts_and_parsing():
    b = Baseline("val_loss", 3.09, False, "ava-nano", None, 0.0)
    p = prompts.ideation_prompt(b, bottleneck="loss spikes", failed_hypotheses=["DeadIdea"], n_ideas=2)
    assert "val_loss = 3.09" in p and "DeadIdea" in p and "SEARCH SPACE" in p
    hs = prompts.parse_hypotheses("noise\n```json\n" + json.dumps([HYP]) + "\n```")
    assert len(hs) == 1 and hs[0]["hypothesis_name"] == "SeqMeanMix"
    with pytest.raises(ValueError):
        prompts.parse_hypotheses('{"hypothesis_name": "incomplete"}')
    impl, dry = prompts.parse_implementation(impl_json())
    assert impl["module_name"] == "SeqMeanMix" and dry["input_shape"] == [8, 16, 64]
    with pytest.raises(ValueError):
        prompts.parse_implementation('{"module_name":"x"}')  # no code


# --------------------------------------------------------------------------- workers end-to-end

def _implement(led, tmp_path, policy):
    ideation.run_ideation(led, policy, bottleneck="spikes", n_ideas=1)
    return implementation.run_implementation(led, policy, workspace_root=tmp_path / "ws")


def test_full_cycle_promote(led, tmp_path):
    r = _implement(led, tmp_path, make_policy())
    assert r["state"] == READY_FOR_TRAINING and r["attempts"] == 0
    rt = train.run_training(led, config={"steps": 30, "seeds": [0, 1]})
    assert rt["state"] == EVALUATION_PENDING and rt["metrics"]["proxy_loss"] > 0
    re = evaluate.run_evaluation(led)
    assert re["state"] == SOTA                       # beat baseline 4.5
    assert led.get_baseline().metric_value == rt["metrics"]["proxy_loss"]


def test_full_cycle_reject(tmp_path):
    L = Ledger(tmp_path / "l.sqlite3")
    L.seed_baseline(Baseline("proxy_loss", 0.001, False, "ava-nano", None, 0.0))  # unbeatable
    _implement(L, tmp_path, make_policy())
    train.run_training(L, config={"steps": 30, "seeds": [0]})
    re = evaluate.run_evaluation(L)
    assert re["state"] == REJECTED
    # the rejected hypothesis becomes a dead end fed back to ideation
    assert "SeqMeanMix" in ideation.dead_ends(L)


def test_failed_validation_path(led, tmp_path):
    # policy always returns broken code -> validation fails all retries
    def bad_policy(prompt):
        if "Principal ML Engineer" in prompt or "failed automated validation" in prompt:
            return impl_json(code="def broken(:\n", name="Broken")
        return json.dumps(HYP)
    r = _implement(led, tmp_path, bad_policy)
    assert r["state"] == FAILED_VALIDATION and r["attempts"] == 3
    exp = led.get(r["experiment"])
    assert exp.failure and "validation failed" in exp.failure


def test_unparseable_implementation_is_honest_failed_validation(led, tmp_path):
    # policy answers the implementation prompt with prose (no JSON at all) every time ->
    # recorded as failed_validation at the 'parse' level, never an unhandled crash.
    def prose_policy(prompt):
        if "Principal ML Engineer" in prompt or "failed automated validation" in prompt:
            return "Sure! Here is my plan: first I will define a module..."
        return json.dumps(HYP)
    r = _implement(led, tmp_path, prose_policy)
    assert r["state"] == FAILED_VALIDATION and r["level"] == "parse"
    exp = led.get(r["experiment"])
    assert exp.failure and "unparseable" in exp.failure


def test_nan_module_dies_at_validation(led, tmp_path):
    # A module that produces NaN is caught at the dry-run (validation), never reaching training.
    r = _implement(led, tmp_path, make_policy(code=NAN_CODE, name="Diverge"))
    assert r["state"] == FAILED_VALIDATION and r["level"] == "dry_run"


def test_failed_training_unstable(led, tmp_path):
    # A module that passes validation but diverges under training -> failed_training. Exercise the
    # run_training contract with a trainer that reports an unstable (NaN) run.
    _implement(led, tmp_path, make_policy())
    def unstable_trainer(exp, cfg):
        return train.TrainResult(ok=True, stable=False,
                                 metrics={"params": 10}, detail="loss became NaN/Inf, killed")
    rt = train.run_training(led, trainer=unstable_trainer)
    assert rt["state"] == FAILED_TRAINING and rt["reason"] == "unstable"
    assert led.get(rt["experiment"]).failure


def test_honest_ollama_refusal(led):
    from dottie.policy import OllamaPolicy, DottiePolicyUnavailable
    pol = OllamaPolicy(base_url=UNROUTABLE_OLLAMA, connect_timeout_s=2.0, read_timeout_s=2.0)
    with pytest.raises(DottiePolicyUnavailable):
        ideation.run_ideation(led, pol, bottleneck="x", n_ideas=1)


# --------------------------------------------------------------------------- logger / status

def test_logger_and_status(led, tmp_path, monkeypatch):
    monkeypatch.setenv("DOTTIE_DATA_DIR", str(tmp_path))
    logger.log_metric("aux_loss", 0.123, data_dir=str(tmp_path), experiment_id="abc")
    mp = tmp_path / "research" / "metrics.jsonl"
    assert mp.exists() and json.loads(mp.read_text().splitlines()[0])["key"] == "aux_loss"
    s = logger.build_status(led)
    assert s["service"] == "dottie-research" and s["baseline"]["metric_value"] == 4.5
    assert set(s["counts"]) >= {"total", "sota", "pending"}
