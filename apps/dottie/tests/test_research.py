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


def test_dry_run_enforces_output_shape_contract():
    # A module that reduces away the hidden dim violates the drop-in block contract
    # ([b,s,h] -> [b,s,h]) — observed live (ba9b35cd8077). The failure names the contract so
    # the correction pass gets an actionable message, not an integration traceback.
    squeeze = ("import torch\nimport torch.nn as nn\nclass Squeeze(nn.Module):\n"
               "    def forward(self, x):\n        return x.mean(dim=-1)\n")
    r = validate.validate(squeeze, class_name="Squeeze", input_shape=[2, 4, 8])
    assert not r.ok and r.level == "dry_run" and "SAME [batch, seq, hidden]" in r.detail


def test_contract_rejects_forward_with_extra_required_args():
    # A regularizer-style forward(x, gradients) can never be a drop-in block (observed live,
    # 6483a5daea94) — it dies at contract in milliseconds, not after burning correction cycles.
    reg = ("import torch\nimport torch.nn as nn\nclass Reg(nn.Module):\n"
           "    def forward(self, x, gradients):\n        return (gradients ** 2).sum()\n")
    r = validate.validate(reg, class_name="Reg")
    assert not r.ok and r.level == "contract" and "gradients" in r.detail
    # extra args WITH defaults are fine, and helper classes with extra args don't poison the
    # declared block class
    # Block's body is a nonlinearity, not `x * scale`: with scale defaulting to 1.0 that
    # would be a zero-parameter EXACT identity, which the degeneracy gate rightly fails.
    # The signature is what this test is about; keep the body non-degenerate.
    ok_code = ("import torch\nimport torch.nn as nn\n"
               "class Helper(nn.Module):\n"
               "    def forward(self, x, gate):\n        return x * gate\n"
               "class Block(nn.Module):\n"
               "    def forward(self, x, scale=1.0):\n        return torch.tanh(x) * scale\n")
    r2 = validate.validate(ok_code, class_name="Block", input_shape=[2, 4, 8])
    assert r2.ok, r2.detail


def test_block_reading_input_grad_is_caught_before_training(tmp_path):
    """A block that reads `x.grad` must fail validation, not training.

    TODOS §5.3.R10: the standard dry run feeds a LEAF tensor with requires_grad=False. A
    block in the residual stream never sees that — its input is a NON-LEAF activation that
    requires grad, and `.grad` is only ever populated on leaves. So a candidate reading
    `x.grad` gets a tensor in the probe and None in production. Two of the five stored
    failed_training records died exactly this way ('NoneType' has no attribute 'abs' /
    'layout') after passing every other level, including the integration-width probe.
    Gradient-inspecting "regularizer" ideas are a large slice of what this loop proposes,
    so this is the shape of the search space, not an exotic corner.
    """
    # The REAL shape of this bug (from 855144446a22): the block makes its own leaf when the
    # input does not require grad, so it works on the probe's plain tensor -- and silently
    # takes the other path in the residual stream, where x already requires grad, is
    # NON-leaf, and .grad is therefore None.
    reads_grad = """import torch
import torch.nn as nn
class GradReader(nn.Module):
    def __init__(self, dim: int = 64):
        super().__init__()
        self.scale = nn.Parameter(torch.ones(1))
    def forward(self, x):
        with torch.enable_grad():
            xg = x if x.requires_grad else x.detach().requires_grad_(True)
            (xg * xg).sum().backward(retain_graph=True)
            g = xg.grad.abs().mean()          # populated on a leaf, None mid-network
        return x * (1.0 + self.scale * g.detach())
"""
    r = validate.validate(reads_grad, class_name="GradReader",
                          init_kwargs={"dim": 64}, input_shape=[2, 4, 64])
    assert not r.ok
    assert r.level == "residual_stream", r.detail
    assert "x.grad" in r.detail and "torch.autograd.grad" in r.detail   # actionable

    # a block that does NOT touch .grad passes the same probe
    clean = """import torch
import torch.nn as nn
class Clean(nn.Module):
    def __init__(self, dim: int = 64):
        super().__init__()
        self.proj = nn.Linear(dim, dim)
    def forward(self, x):
        return x + torch.tanh(self.proj(x))
"""
    r_ok = validate.validate(clean, class_name="Clean",
                             init_kwargs={"dim": 64}, input_shape=[2, 4, 64])
    assert r_ok.ok, r_ok.detail
    # the canonical dry-run detail survives a passing stream probe
    assert "learnable_params=" in r_ok.detail
    assert r_ok.per_level["residual_stream"]["status"] == "pass"


def test_candidate_that_hardcodes_the_dry_run_width_is_caught(tmp_path):
    """A block that only works at its declared width must fail validation, not training.

    TODOS §5.3.R8: validation ran at the model's self-declared `input_shape` (hidden=64)
    while factory_trainer swaps the block into a model with d_model=256, overriding
    dim-like constructor kwargs. A candidate that hardcodes a head count or reshape to 64
    passed every level and died at integration — costing a full model build and probe to
    learn what a second dry run finds in about a second. Replaying the stored
    failed_training records, this catches 2 of 5 (the other 3 only misbehave on real
    training data, which no forward probe reaches).
    """
    hardcoded = """import torch
import torch.nn as nn
class Hardcoded(nn.Module):
    def __init__(self, dim: int = 64):
        super().__init__()
        self.proj = nn.Linear(dim, dim)
    def forward(self, x):
        b, s, _ = x.shape
        # the bug: head split assumes hidden == 64, not x.shape[-1]
        h = x.reshape(b, s, 8, 8)
        return self.proj(h.reshape(b, s, 64))
"""
    r_declared = validate.validate(hardcoded, class_name="Hardcoded",
                                   init_kwargs={"dim": 64}, input_shape=[2, 4, 64])
    assert not r_declared.ok
    assert r_declared.level == "integration_width", r_declared.detail
    assert "integration width 256" in r_declared.detail
    assert "x.shape[-1]" in r_declared.detail          # actionable, not just a traceback

    # a width-agnostic block passes both probes
    agnostic = """import torch
import torch.nn as nn
class Agnostic(nn.Module):
    def __init__(self, dim: int = 64):
        super().__init__()
        self.scale = nn.Parameter(torch.ones(1))
    def forward(self, x):
        return x + self.scale * torch.tanh(x)
"""
    r_ok = validate.validate(agnostic, class_name="Agnostic",
                             init_kwargs={"dim": 64}, input_shape=[2, 4, 64])
    assert r_ok.ok, r_ok.detail


def test_integration_width_probe_tolerates_symbolic_shapes(tmp_path):
    """A declared input_shape may contain placeholders like "hidden" — never assume ints.

    Found by replaying stored candidates: `int('hidden')` raised straight out of validate(),
    which would have broken this level for every candidate declaring a symbolic shape.
    """
    code = """import torch
import torch.nn as nn
class Sym(nn.Module):
    def forward(self, x):
        return torch.tanh(x)
"""
    f = tmp_path / "sym.py"
    f.write_text(code, encoding="utf-8")
    for shape in (["batch", "seq", "hidden"], [2, 4], None, [2, 4, 256]):
        r = validate.dry_run_at_integration_width(f, class_name="Sym",
                                                  init_kwargs={}, input_shape=shape)
        assert r.ok, f"{shape} -> {r.detail}"


def test_dry_run_rejects_degenerate_no_op_block():
    # TODOS §5.3.R: MLBR — the loop's first "SOTA" — passed all four levels while being a
    # no-op (zero learnable params; forward = x + scalar). It then "won" at smoke scale by
    # REPLACING a real block. Verbatim shape of that module:
    noop = ("import torch\nimport torch.nn as nn\nclass NoOp(nn.Module):\n"
            "    def __init__(self, lam: float = 1.0):\n        super().__init__()\n"
            "        self.lam = lam\n"
            "    def forward(self, x):\n"
            "        s = torch.log(torch.sum(torch.exp(self.lam * x), dim=-1, keepdim=True))\n"
            "        c = -torch.sum(s) / (x.shape[0] * x.shape[1])\n"
            "        return x + c.unsqueeze(-1).unsqueeze(-1)\n")
    r = validate.validate(noop, class_name="NoOp", input_shape=[4, 16, 64])
    assert not r.ok and r.level == "dry_run"
    assert "degenerate block" in r.detail and "0 learnable parameters" in r.detail


def test_dry_run_allows_zero_init_parameterized_block():
    # The gate must NOT reject the legitimate zero-init pattern (identity at init, but
    # parameterized so it can learn) — that is a real design, not a degenerate one.
    layerscale = ("import torch\nimport torch.nn as nn\nclass LayerScale(nn.Module):\n"
                  "    def __init__(self, hidden: int = 64):\n        super().__init__()\n"
                  "        self.gamma = nn.Parameter(torch.zeros(hidden))\n"
                  "        self.proj = nn.Linear(hidden, hidden)\n"
                  "    def forward(self, x):\n        return x + self.gamma * self.proj(x)\n")
    r = validate.validate(layerscale, class_name="LayerScale",
                          init_kwargs={"hidden": 64}, input_shape=[4, 16, 64])
    assert r.ok, r.detail
    assert "learnable_params=4224" in r.detail


def test_dry_run_sanitizes_untrusted_input_shape():
    # A model-declared junk shape ([-1, -1, 8] observed live) must not fail torch.randn —
    # non-positive dims fall back per-dimension and good code still validates.
    r = validate.validate(GOOD_CODE, class_name="SeqMeanMix", input_shape=[-1, -1, 64])
    assert r.ok, r.detail


def test_repeated_identical_failure_escalates_feedback():
    # A corrector stuck in a loop (identical failure twice running) gets an explicit
    # do-something-different note appended to the feedback from the second retry on.
    seen = []
    def stuck(code, feedback):
        seen.append(feedback)
        return code  # resubmits the same broken code every time
    out = validate.validate_with_correction("def bad(:", stuck, max_retries=3)
    assert not out.ok and len(seen) == 3
    assert "same failure" not in seen[0]
    assert all("same failure" in f for f in seen[1:])


def test_correction_feedback_shows_the_models_own_last_edit():
    # TODOS §5.2.c: the corrector used to see only the traceback, so it could not tell WHICH
    # of its edits had just failed. From the second retry on it now also gets a unified diff
    # of its own previous edit — and an explicit callout when it changed nothing at all.
    seen = []
    # a real edit first, then the SAME code again — exercising both feedback branches
    codes = ["def still_bad(:", "def still_bad(:"]

    def edits(code, feedback):
        seen.append(feedback)
        return codes[min(len(seen) - 1, len(codes) - 1)]

    out = validate.validate_with_correction("def bad(:", edits, max_retries=3)
    assert not out.ok
    assert "PREVIOUS EDIT" not in seen[0]             # nothing edited yet on the first pass
    assert "YOUR PREVIOUS EDIT" in seen[1] and "--- previous_attempt" in seen[1]
    assert "+def still_bad(:" in seen[1]              # the actual edit is visible
    # third pass: the corrector resubmitted identical code -> called out explicitly
    assert "BYTE-IDENTICAL" in seen[2]


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
    # a wrapper object around the list ({"hypotheses": [...]}) is unwrapped — observed live
    hs2 = prompts.parse_hypotheses(json.dumps({"hypotheses": [HYP, HYP]}))
    assert len(hs2) == 2 and hs2[0]["hypothesis_name"] == "SeqMeanMix"
    # per-item wrappers ([{"hypothesis": {...}}]) are unwrapped too — observed live
    hs3 = prompts.parse_hypotheses(json.dumps([{"hypothesis": HYP}, {"idea": HYP}]))
    assert len(hs3) == 2 and hs3[1]["hypothesis_name"] == "SeqMeanMix"
    # a mid-word-corrupted key ("hypo,thesis_name") is repaired by canonical-skeleton match —
    # observed live 2026-07-20 (ideation_raw_1784519718_bf6793.txt killed a whole 3-idea batch)
    mangled = dict(HYP)
    mangled["hypo,thesis_name"] = mangled.pop("hypothesis_name")
    hs4 = prompts.parse_hypotheses(json.dumps([mangled]))
    assert hs4[0]["hypothesis_name"] == "SeqMeanMix" and "hypo,thesis_name" not in hs4[0]
    with pytest.raises(ValueError):
        prompts.parse_hypotheses('{"hypothesis_name": "incomplete"}')
    with pytest.raises(ValueError):
        prompts.parse_hypotheses('{"hypotheses": "not a list"}')
    impl, dry = prompts.parse_implementation(impl_json())
    assert impl["module_name"] == "SeqMeanMix" and dry["input_shape"] == [8, 16, 64]
    with pytest.raises(ValueError):
        prompts.parse_implementation('{"module_name":"x"}')  # no code


# --------------------------------------------------------------------------- workers end-to-end

def _implement(led, tmp_path, policy):
    ideation.run_ideation(led, policy, bottleneck="spikes", n_ideas=1)
    return implementation.run_implementation(led, policy, workspace_root=tmp_path / "ws")


def _implement_with(led, tmp_path, policy, *, max_retries):
    ideation.run_ideation(led, policy, bottleneck="spikes", n_ideas=1)
    return implementation.run_implementation(led, policy, workspace_root=tmp_path / "ws",
                                             max_retries=max_retries)


def test_unparseable_correction_is_retried_not_fatal(led, tmp_path):
    """A malformed CORRECTION reply must not abort the experiment.

    TODOS 5.3.R4: measured over the 59 stored failed_validation records, 6 (10%) died
    because the corrector's own reply was unparseable JSON -- while the INITIAL parse
    re-prompts up to max_retries for that exact failure. The model got several chances
    before its first attempt and none after. One garbled reply must cost a retry, not
    the whole candidate.
    """
    calls = {"corrections": 0}

    def policy(prompt: str) -> str:
        if "failed automated validation" in prompt:          # the corrector's call
            calls["corrections"] += 1
            if calls["corrections"] == 1:
                return "Sure! Here is the fixed module: <not json>"   # garbled, recoverable
            # NOTE: same class name as the initial parse. validate_with_correction pins
            # class_name from the FIRST parse, so a correction that renames the class can
            # never validate no matter how good the code is (see TODOS follow-up).
            return impl_json(GOOD_CODE.replace("SeqMeanMix", "Broken"), "Broken")
        if "Principal ML Engineer" in prompt:
            return impl_json("def broken(:", "Broken")                # fails L1 syntax
        return json.dumps(HYP)

    r = _implement(led, tmp_path, policy)
    assert calls["corrections"] == 2                  # retried instead of giving up
    assert r["state"] == READY_FOR_TRAINING           # and the candidate was recovered


def test_corrector_failure_is_distinguished_from_a_bad_candidate(led, tmp_path):
    """A run abandoned because the LLM died must not look like a validation failure.

    TODOS 5.3.R4: 48e0f39d8225 stopped at attempts=2 of --max-retries 5 with no reason
    recorded. `validate_with_correction` breaks early when the CORRECTOR raises and logs
    it only to `history`, while the stored failure was built from the last validation
    result alone. So "Ollama was down" and "the candidate is broken" were indistinguishable
    in the ledger -- and the short `attempts` count feeds the conversion analysis.
    """
    calls = {"n": 0}

    def policy(prompt: str) -> str:
        if "failed automated validation" in prompt:      # the corrector's call
            calls["n"] += 1
            raise RuntimeError("ollama connection reset")
        if "Principal ML Engineer" in prompt:
            return impl_json("def broken(:", "Broken")
        return json.dumps(HYP)

    r = _implement(led, tmp_path, policy)
    assert r["state"] == FAILED_VALIDATION
    assert calls["n"] == 1                                # stopped at the FIRST corrector death
    assert r["attempts"] == 1 and r["corrector_error"]    # the short count now has a reason
    assert "ollama connection reset" in r["corrector_error"]
    # and the human-readable failure says WHOSE fault it was, not just where it stopped
    failure = led.get(r["experiment"]).failure or ""
    assert "the corrector itself failed" in failure
    assert "ollama connection reset" in failure


def test_corrector_parse_retries_are_a_bounded_shared_pool(led, tmp_path):
    """The parse-retry budget must not multiply with the correction budget.

    The first version of this retry gave EVERY correction attempt its own max_retries
    parse retries, nesting the two loops: 5 attempts x 6 calls = 30 policy calls worst
    case against 5 before the retry existed. At ~90 s/call that is 45 min for one
    implement instead of 8 -- a latency regression worse than the ~10% of experiments
    the retry reclaims. The pool is shared across the whole experiment instead.
    """
    # The policy must garble ONCE PER ATTEMPT and then succeed. An always-garbling policy
    # aborts on the first corrector invocation and never exercises the nesting at all --
    # it scores 6 calls on the buggy code, under any sane ceiling, so it would pass while
    # the regression sat there. This is the shape that actually multiplies.
    calls = {"corrections": 0}
    garbled_this_attempt = {"flag": False}

    def policy(prompt: str) -> str:
        if "failed automated validation" in prompt:
            calls["corrections"] += 1
            if not garbled_this_attempt["flag"]:
                garbled_this_attempt["flag"] = True
                return "here you go! <not json>"          # one slip per attempt...
            garbled_this_attempt["flag"] = False
            return impl_json("def still_broken(:", "Broken")   # ...then valid, still failing
        if "Principal ML Engineer" in prompt:
            return impl_json("def broken(:", "Broken")
        return json.dumps(HYP)

    max_retries = 5
    r = _implement_with(led, tmp_path, policy, max_retries=max_retries)
    assert r["state"] == FAILED_VALIDATION
    # Hardcoded, not read from the module: the constant does not exist on the buggy
    # version, and an AttributeError is not the failure this test is meant to report.
    ceiling = max_retries + 3            # max_retries + _PARSE_RETRY_BUDGET
    assert calls["corrections"] <= ceiling, (
        f"{calls['corrections']} policy calls exceeds {ceiling} — the parse-retry pool is "
        "multiplying with the correction budget again")


def test_unloadable_candidate_fails_training_instead_of_retrying_forever(led, tmp_path):
    """A candidate whose own module will not load must not sit in ready_for_training.

    run_training treats ok=False as retryable infrastructure and leaves the experiment
    in ready_for_training. But the module loaded here IS the candidate's artifact, so a
    load/construct failure reproduces identically on every retry -- the experiment would
    be picked up forever and block the queue behind it. factory_trainer.py already draws
    this line (candidate fault -> ok=True/stable=False -> FAILED_TRAINING); this path was
    left inconsistent with it. Observed frequency at the time of the fix: zero. Latent.
    """
    _implement(led, tmp_path, make_policy())
    e = led.next_in_state(READY_FOR_TRAINING)
    # corrupt the written module so importing it raises, exactly as a bad candidate would
    for f in (tmp_path / "ws" / e.id).glob("*.py"):
        f.write_text("this is not valid python (", encoding="utf-8")

    r = train.run_training(led, config={"steps": 5, "seeds": [0]})
    assert r["state"] == FAILED_TRAINING                       # not left retryable
    assert led.get(e.id).state == FAILED_TRAINING
    assert led.next_in_state(READY_FOR_TRAINING) is None       # queue is not blocked


def test_full_cycle_promote(led, tmp_path):
    r = _implement(led, tmp_path, make_policy())
    assert r["state"] == READY_FOR_TRAINING and r["attempts"] == 0
    rt = train.run_training(led, config={"steps": 30, "seeds": [0, 1]})
    assert rt["state"] == EVALUATION_PENDING and rt["metrics"]["proxy_loss"] > 0
    re = evaluate.run_evaluation(led)
    assert re["state"] == SOTA                       # beat baseline 4.5
    assert led.get_baseline().metric_value == rt["metrics"]["proxy_loss"]


def test_baseline_migrations_stay_additive_and_nullable(tmp_path):
    """Any column added to `baseline` must be writable-around by OLDER code.

    TODOS §5.3.R6: the research daemon holds the ledger open for hours and does NOT
    reload, so a migration always lands under a running process executing the previous
    version of this file. That old code writes an explicit column list and reads rows by
    name, which survives added columns — but only while every added column is nullable.
    A future NOT NULL column (or one with no default) would start failing the live
    daemon's writes silently, mid-run, with the ledger as the only record.

    Scope, honestly: SQLite enforces most of this itself — `ADD COLUMN ... NOT NULL`
    without a default is rejected outright once the table has a row, and `baseline` is a
    singleton that always does (verified on sqlite 3.45.1). So the headline disaster is
    mostly unreachable in production, and this test would trip over SQLite's own error
    before reaching its assertion. What it actually guards is the part SQLite does NOT
    check: that the pre-migration INSERT statement still succeeds verbatim, which a future
    CHECK constraint, renamed column, or altered conflict clause would silently break —
    and that re-running the migration is a no-op.
    """
    import sqlite3

    L = Ledger(tmp_path / "m.sqlite3")
    L.seed_baseline(Baseline("m", 1.0, higher_is_better=False, architecture="arch",
                             experiment_id=None, updated_ts=0.0))

    original = ("singleton", "metric_name", "metric_value", "higher_is_better",
                "architecture", "experiment_id", "updated_ts", "notes")
    c = sqlite3.connect(tmp_path / "m.sqlite3")
    cols = {r[1]: r for r in c.execute("PRAGMA table_info(baseline)")}
    added = [name for name in cols if name not in original]
    for name in added:                       # notnull flag is index 3, default is index 4
        assert not cols[name][3] or cols[name][4] is not None, (
            f"migrated column {name!r} is NOT NULL without a default — a daemon running "
            "the previous version of ledger.py would fail every baseline write")

    # the pre-migration write, verbatim: must still succeed
    c.execute(
        "INSERT INTO baseline (singleton, metric_name, metric_value, higher_is_better, "
        "architecture, experiment_id, updated_ts, notes) VALUES (1,?,?,?,?,?,?,?) "
        "ON CONFLICT(singleton) DO UPDATE SET metric_value=excluded.metric_value",
        ("m", 2.0, 0, "arch", "exp123", 123.0, "old-code write"))
    c.commit()
    assert L.get_baseline().metric_value == 2.0        # and new code reads it back

    # running the migration twice must be a no-op, not an error
    Ledger(tmp_path / "m.sqlite3")
    assert L.get_baseline().metric_value == 2.0


def test_two_sample_significance_when_baseline_records_spread(led, tmp_path):
    """A baseline with its own SEM must be compared two-sample, not as an exact point.

    TODOS §5.3.R6: comparing a candidate's SEM against a POINT baseline assumes the
    baseline was measured without error. The effective threshold is ~1.4 SE_diff (~84%),
    not the 95% "significant" implies. With both spreads known the honest denominator is
    SE_diff = sqrt(sem_c² + sem_b²), which is strictly LARGER — so a delta that squeaked
    past the one-sample test can and should fail the two-sample one.
    """
    noisy = [4.35, 4.60, 4.40, 4.62, 4.38, 4.58]        # mean 4.485, sem ~0.0455

    def evaluate_against(baseline_sem):
        L = Ledger(tmp_path / f"l_{baseline_sem}.sqlite3")
        L.seed_baseline(Baseline("proxy_loss", 4.6, higher_is_better=False,
                                 architecture="ava-nano", experiment_id=None,
                                 updated_ts=0.0, metric_sem=baseline_sem))
        e = L.create(HYP)
        L.transition(e.id, READY_FOR_TRAINING, implementation={"code": GOOD_CODE}, workspace="/w")
        L.transition(e.id, EVALUATION_PENDING,
                     train_metrics={"proxy_loss": 4.485, "eval_ce_per_batch": noisy,
                                    "integration": "proxy_micro_benchmark", "params": 1000})
        return evaluate.run_evaluation(L)

    # delta = 0.115; candidate sem ~0.0455 -> 2*sem ~0.0910, so it CLEARS a point baseline
    one = evaluate_against(None)
    assert one["verdict"]["significant"] is True
    assert "candidate-only SEM" in one["verdict"]["significance"]
    assert "NO spread" in one["verdict"]["significance"]     # weakness stated, not implied

    # same delta, but a baseline SEM of 0.05 gives SE_diff ~0.0677 -> 2*SE_diff ~0.135 > 0.115
    two = evaluate_against(0.05)
    assert two["verdict"]["significant"] is False
    assert "two-sample SE_diff" in two["verdict"]["significance"]
    assert two["state"] == REJECTED                          # correctly HELD


def test_promotion_records_the_baselines_spread(led, tmp_path):
    """Promotion must carry the winning run's SEM onto the baseline.

    Otherwise every future comparison silently falls back to the weaker point test, and
    the two-sample path above can never engage.
    """
    _implement(led, tmp_path, make_policy())
    e = led.next_in_state(READY_FOR_TRAINING)
    led.transition(e.id, EVALUATION_PENDING,
                   train_metrics={"proxy_loss": 1.0,
                                  "eval_ce_per_batch": [1.0, 1.01, 0.99, 1.0, 1.0, 1.0],
                                  "integration": "proxy_micro_benchmark"})
    r = evaluate.run_evaluation(led)
    assert r["state"] == SOTA
    b = led.get_baseline()
    assert b.metric_sem is not None and b.metric_sem > 0
    assert b.metric_sem_n == 6


def test_contaminated_baseline_is_detected(led, tmp_path):
    """A baseline set by a candidate the loop would NOW reject must not read as trusted.

    TODOS §5.3.R5: `_baseline_provenance` treats any baseline with an `experiment_id` as
    "promoted" — highest trust, no caveat. That trust is retrospective and unchecked: a
    gate added AFTER a promotion never re-examines the number that promotion left behind.
    Measured on the live ledger, the real baseline (factory_lm_loss 5.60506) was ratcheted
    by MLBR, a zero-parameter no-op that the degeneracy gate now fails outright — so every
    comparison since has been against a number set by a module that cannot learn.
    """
    noop = """import torch
import torch.nn as nn
class NoOp(nn.Module):
    def __init__(self, lam: float = 1.0):
        super().__init__()
        self.lam = lam
    def forward(self, x):
        return x + 0.5
"""
    e = led.create(dict(HYP, hypothesis_name="NoOp"))
    led.transition(e.id, READY_FOR_TRAINING, workspace="/w",
                   implementation={"code": noop, "module_name": "NoOp",
                                   "dry_run": {"class_name": "NoOp", "init_kwargs": {},
                                               "input_shape": [2, 4, 8]}})
    led.transition(e.id, EVALUATION_PENDING, train_metrics={"proxy_loss": 1.0})
    led.transition(e.id, SOTA, eval_verdict={"promote": True})
    led.promote_baseline(e.id, 1.0, notes="NoOp")

    caveat = evaluate._baseline_contamination(led, led.get_baseline())
    assert caveat and "CONTAMINATED BASELINE" in caveat
    assert e.id in caveat and "degenerate block" in caveat

    # A hand-seeded baseline has no source experiment: not this check's business
    # (that is _baseline_provenance's), so it must stay silent rather than double-report.
    led2 = Ledger(tmp_path / "l2.sqlite3")
    led2.seed_baseline(Baseline("proxy_loss", 4.5, higher_is_better=False,
                                architecture="ava-nano", experiment_id=None, updated_ts=0.0))
    assert evaluate._baseline_contamination(led2, led2.get_baseline()) is None


def test_promotion_requires_significance(led, tmp_path):
    # TODOS 5.3.R: the first live "SOTA" (MLBR) beat the baseline by 1.1 SEM — noise —
    # because promotion used a bare `<`. A direction-correct win inside the candidate's
    # own spread must now be HELD, with the arithmetic recorded in the verdict.
    _implement(led, tmp_path, make_policy())
    e = led.next_in_state(READY_FOR_TRAINING)
    noisy = [4.35, 4.60, 4.40, 4.62, 4.38, 4.58]      # mean 4.485, sem ~0.045
    led.transition(e.id, EVALUATION_PENDING,
                   train_metrics={"proxy_loss": 4.485, "eval_ce_per_batch": noisy,
                                  "integration": "proxy_micro_benchmark", "params": 1000})
    r = evaluate.run_evaluation(led)
    v = r["verdict"]
    assert r["state"] == REJECTED                      # beat 4.5, but only by ~0.3 SEM
    assert v["improved"] is True and v["significant"] is False
    assert v["sem"] > 0 and v["sem_n"] == 6 and v["sem_series"] == "eval_ce_per_batch"
    assert v["candidate_params"] == 1000               # param delta visible to the reviewer
    assert "within noise" in r["reason"]
    assert led.get_baseline().metric_value == 4.5      # ratchet did NOT move


def test_capacity_caveat_surfaces_a_shrinking_swap(led, tmp_path):
    # TODOS §5.3.R: the block swap REPLACES a real block, so a parameter-light candidate
    # also removes capacity and can "win" at fixed steps for that reason. Recorded (not
    # gated) so the verdict and write-up state it instead of hiding it.
    _implement(led, tmp_path, make_policy())
    e = led.next_in_state(READY_FOR_TRAINING)
    led.transition(e.id, EVALUATION_PENDING,
                   train_metrics={"proxy_loss": 1.0, "eval_ce_per_batch": [1.0, 1.02, 0.98, 1.01],
                                  "integration": "factory_nano_block_swap",
                                  "replaced_block_params": 786432, "candidate_block_params": 0,
                                  "block_param_delta": -786432})
    r = evaluate.run_evaluation(led)
    v = r["verdict"]
    assert v["block_param_delta"] == -786432
    assert "REMOVED 786,432 parameters" in v["capacity_caveat"]
    assert "Caveats" in led.get(e.id).writeup


def test_hand_seeded_baseline_is_flagged_in_the_verdict(led, tmp_path):
    # TODOS §5.3.R0: the loop's older "SOTA" beat 4.5 — the runbook's hand-seeded
    # placeholder — on a synthetic task. Nothing recorded that the baseline was never
    # measured. The `led` fixture seeds exactly such a placeholder.
    _implement(led, tmp_path, make_policy())
    e = led.next_in_state(READY_FOR_TRAINING)
    led.transition(e.id, EVALUATION_PENDING,
                   train_metrics={"proxy_loss": 9.0, "per_seed": [9.0, 9.1, 8.9],
                                  "integration": "proxy_micro_benchmark"})
    r = evaluate.run_evaluation(led)
    v = r["verdict"]
    assert v["baseline_provenance"] == "hand_seeded"
    assert "HAND-SEEDED placeholder" in v["baseline_caveat"]
    assert "calibrate-baseline" in led.get(e.id).writeup


def test_calibrated_baseline_carries_no_caveat(tmp_path):
    L = Ledger(tmp_path / "cal.sqlite3")
    L.seed_baseline(Baseline("factory_lm_loss", 5.61982, False, "nano", None, 0.0,
                             notes="measured baseline calibration: steps=150 seq=256"))
    kind, caveat = evaluate._baseline_provenance(L.get_baseline())
    assert kind == "calibrated" and caveat is None


def test_promotion_without_a_series_is_held_not_assumed(led, tmp_path):
    # No per-batch series => significance unmeasurable => hold. Never promote on faith.
    _implement(led, tmp_path, make_policy())
    e = led.next_in_state(READY_FOR_TRAINING)
    led.transition(e.id, EVALUATION_PENDING,
                   train_metrics={"proxy_loss": 1.0, "integration": "proxy_micro_benchmark"})
    r = evaluate.run_evaluation(led)
    assert r["state"] == REJECTED and r["verdict"]["significant"] is None
    assert "unmeasurable" in r["verdict"]["significance"]
    assert led.get_baseline().metric_value == 4.5


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


def test_parse_implementation_repairs_double_escaped_code():
    # A one-line code field with literal \n sequences (double-escaped JSON) is decoded; code
    # with real newlines is untouched even when it contains LaTeX-ish backslashes.
    flat = GOOD_CODE.replace("\n", "\\n")
    impl, _ = prompts.parse_implementation(impl_json(code=flat))
    assert impl["code"] == GOOD_CODE
    multiline = "# grad: \\nabla f\n" + GOOD_CODE
    impl2, _ = prompts.parse_implementation(impl_json(code=multiline))
    assert impl2["code"] == multiline


def test_parse_implementation_repairs_mixed_escaped_code():
    # Observed live (aea41c349279 attempt 3): a correction pass came back with SOME real
    # newlines and SOME literal \n sequences — broken as-is, outside the old flat-only repair.
    lines = GOOD_CODE.rstrip("\n").split("\n")
    mixed = lines[0] + "\\n" + "\n".join(lines[1:])
    impl, _ = prompts.parse_implementation(impl_json(code=mixed))
    assert impl["code"] == "\n".join(lines)


def test_parse_implementation_repairs_flat_code_with_json_invalid_escape():
    # A flat one-liner containing a JSON-invalid escape (a \d in a comment): the JSON-decode
    # path raises, the plain-unescape path repairs it.
    src = ('import torch.nn as nn\nclass DigitGate(nn.Module):  # gates \\d-digit ids\n'
           '    def forward(self, x):\n        return x\n')
    flat = src.replace("\n", "\\n")
    impl, _ = prompts.parse_implementation(impl_json(code=flat))
    assert impl["code"] == src


def test_parse_implementation_leaves_unrepairable_code_unchanged():
    # Broken code no unescape can save passes through untouched — it then fails at the syntax
    # validator honestly instead of being silently rewritten.
    hopeless = "def broken(:\\n    pass"
    impl, _ = prompts.parse_implementation(impl_json(code=hopeless))
    assert impl["code"] == hopeless


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
    # sota_history carries the verdict's metric_name/baseline_value so the dashboard can anchor
    # the hill-climb series at the seed each sota was measured against.
    e = led.create(HYP)
    led.transition(e.id, READY_FOR_TRAINING, implementation={"code": "x"}, workspace="/w")
    led.transition(e.id, EVALUATION_PENDING, train_metrics={"proxy_loss": 2.0})
    led.transition(e.id, SOTA, eval_verdict={"promote": True, "metric": "proxy_loss",
                                             "baseline_value": 4.5, "delta": -2.5})
    h = logger.build_status(led)["sota_history"][0]
    assert h["metric"] == 2.0 and h["metric_name"] == "proxy_loss" and h["baseline_value"] == 4.5


def test_runner_stage_selection_policy():
    # The continuous runner drains the pipeline end-to-end: evaluate first (instant),
    # then train, then implement; ideate only on an empty pipeline and rate-limited.
    from dottie.research.__main__ import _choose_action
    now = 1000.0
    assert _choose_action({"evaluation_pending": 1, "ready_for_training": 2, "pending": 3},
                          now=now, last_ideate_ts=0, ideate_cooldown_s=600) == "evaluate"
    assert _choose_action({"ready_for_training": 1, "pending": 3},
                          now=now, last_ideate_ts=0, ideate_cooldown_s=600) == "train"
    assert _choose_action({"pending": 1}, now=now, last_ideate_ts=0,
                          ideate_cooldown_s=600) == "implement"
    assert _choose_action({}, now=now, last_ideate_ts=0, ideate_cooldown_s=600) == "ideate"
    assert _choose_action({}, now=now, last_ideate_ts=now - 10,
                          ideate_cooldown_s=600) == "idle"     # cooldown holds
    # terminal states never trigger work
    assert _choose_action({"failed_validation": 9, "sota": 1, "rejected": 2},
                          now=now, last_ideate_ts=now, ideate_cooldown_s=600) == "idle"


def test_policy_num_gpu_knob(monkeypatch):
    # DOTTIE_OLLAMA_NUM_GPU pins inference layers (0 = CPU; GPU belongs to training).
    from dottie.policy import OllamaPolicy
    captured = {}
    class _R:
        status_code = 200
        def json(self):
            return {"message": {"content": "ok"}}
    def fake_post(url, json=None, timeout=None):
        captured.update(json)
        return _R()
    import dottie.policy as pol
    monkeypatch.setattr(pol.httpx, "post", fake_post)
    monkeypatch.setenv("DOTTIE_OLLAMA_NUM_GPU", "0")
    OllamaPolicy(base_url="http://x", model="m").complete("hi")
    assert captured["options"]["num_gpu"] == 0
    monkeypatch.delenv("DOTTIE_OLLAMA_NUM_GPU")
    captured.clear()
    OllamaPolicy(base_url="http://x", model="m").complete("hi")
    assert "num_gpu" not in captured["options"]


def test_policy_keep_alive_knob(monkeypatch):
    # DOTTIE_OLLAMA_KEEP_ALIVE bounds how long Ollama keeps the model resident. Measured
    # 2026-07-20: the loop calls every ~4 min, inside Ollama's 5-min default, so on CPU the
    # model squatted ~5.3 GB permanently and starved the WSL VM until the fleet died.
    from dottie.policy import OllamaPolicy
    captured = {}
    class _R:
        status_code = 200
        def json(self):
            return {"message": {"content": "ok"}}
    def fake_post(url, json=None, timeout=None):
        captured.update(json)
        return _R()
    import dottie.policy as pol
    monkeypatch.setattr(pol.httpx, "post", fake_post)
    monkeypatch.setenv("DOTTIE_OLLAMA_KEEP_ALIVE", "30s")
    OllamaPolicy(base_url="http://x", model="m").complete("hi")
    assert captured["keep_alive"] == "30s"
    # unset => absent, so Ollama's own default applies and nothing changes for other users
    monkeypatch.delenv("DOTTIE_OLLAMA_KEEP_ALIVE")
    captured.clear()
    OllamaPolicy(base_url="http://x", model="m").complete("hi")
    assert "keep_alive" not in captured
    # blank is treated as unset, not as the string "" (which Ollama would reject)
    monkeypatch.setenv("DOTTIE_OLLAMA_KEEP_ALIVE", "   ")
    captured.clear()
    OllamaPolicy(base_url="http://x", model="m").complete("hi")
    assert "keep_alive" not in captured


def test_failure_detail_keeps_the_exception_not_the_header(led, tmp_path):
    # TODOS §5.2: stored failures used to be detail[:500] — the HEAD of a traceback, which
    # is boilerplate. Python puts the exception last, so 36 of 40 recent records were
    # unclassifiable. The tail is what identifies the failure mode.
    from dottie.research.implementation import _keep_tail
    tb = ("Traceback (most recent call last):\n"
          + "".join(f'  File "x.py", line {i}, in f\n    call_{i}()\n' for i in range(120))
          + "RuntimeError: shapes cannot be multiplied (4x16 and 64x8)")
    kept = _keep_tail(tb)
    assert "RuntimeError: shapes cannot be multiplied" in kept   # the part that matters
    assert kept.startswith("...[head truncated]...")             # honest about the cut
    assert len(kept) < len(tb)
    short = "degenerate block: 0 learnable parameters"
    assert _keep_tail(short) == short                            # short details untouched


def test_promotion_bundle_from_sota_and_refusals(led, tmp_path):
    # TODOS 5.3: sota -> reviewable bundle; everything else refuses honestly.
    from dottie.research import promote
    e = led.create(HYP)
    led.transition(e.id, READY_FOR_TRAINING,
                   implementation={"code": GOOD_CODE, "module_name": "SeqMeanMix"},
                   workspace="/w")
    led.transition(e.id, EVALUATION_PENDING,
                   train_metrics={"proxy_loss": 2.0, "config": {"steps": 30}})
    with pytest.raises(ValueError, match="not sota"):
        promote.build_promotion(led, e.id, out_root=tmp_path)
    led.transition(e.id, SOTA, eval_verdict={"promote": True, "delta": -2.5})
    promote.build_promotion(led, e.id, out_root=tmp_path)
    bundle = tmp_path / e.id
    assert (bundle / "candidate.py").read_text(encoding="utf-8") == GOOD_CODE
    md = (bundle / "PROMOTION.md").read_text(encoding="utf-8")
    assert "HUMAN-GATED" in md and "SeqMeanMix" in md and "2.0" in md
    ab = (bundle / "ab_nano.py").read_text(encoding="utf-8")
    assert "STEPS = 30" in ab and "candidate.py" in ab
    # idempotent sweep: already-bundled skipped, nothing rebuilt
    summary = promote.build_pending_promotions(led, out_root=tmp_path)
    assert summary["built"] == [] and e.id in summary["already_bundled"]


def test_extract_json_repairs_latex_backslashes_and_truncation():
    # Both defects from the REAL dump ideation_raw_1784494765: raw LaTeX escapes in
    # math fields + a half-emitted trailing element from a token-limit cut.
    import json as _json
    good = dict(HYP)
    good["mathematical_formulation"] = "\alpha + \beta over \mathcal{L}"
    raw_two = _json.dumps([good, good]).replace("\\\\", "\\")   # un-escape -> invalid JSON
    hs = prompts.parse_hypotheses(raw_two)
    assert len(hs) == 2 and "\alpha" in hs[0]["mathematical_formulation"]
    truncated = raw_two[:-1].rsplit("}", 1)[0] + ', {"hypo'    # cut mid-third-element
    hs2 = prompts.parse_hypotheses("[" + truncated.lstrip("[") + "")
    assert len(hs2) >= 1                                        # complete items salvaged
    with pytest.raises(ValueError):
        prompts.parse_hypotheses("no json here at all")


def test_implementation_prompt_does_not_invite_phantom_imports():
    # 3 live experiments burned retries on F821 `arxiviq_logger` — an import OUR OWN
    # prompt suggested while the sandbox has no such module. The prompt must demand a
    # self-contained module instead.
    p = prompts.implementation_prompt(HYP)
    assert "arxiviq_logger" not in p
    assert "SELF-CONTAINED" in p


def test_ideation_retries_once_on_content_failure(led, tmp_path, monkeypatch):
    # Observed live: temp-0.9 ideation omits required keys. One corrective re-ask with
    # the exact error; a second failure stays an honest ValueError with the dump path.
    monkeypatch.setenv("DOTTIE_RESEARCH_LOG_DIR", str(tmp_path))
    calls = []
    def flaky(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return json.dumps([{"hypothesis_name": "incomplete only"}])
        return json.dumps([HYP])
    out = ideation.run_ideation(led, flaky, bottleneck="b")
    assert out["retried"] is True and len(out["created"]) == 1
    assert "# CORRECTION" in calls[1] and "missing required keys" in calls[1]

    def always_bad(prompt):
        return "utter garbage, no json"
    with pytest.raises(ValueError, match="raw completion saved"):
        ideation.run_ideation(led, always_bad, bottleneck="b")
    assert len(list(tmp_path.glob("ideation_raw_*.txt"))) >= 2   # both failures dumped
