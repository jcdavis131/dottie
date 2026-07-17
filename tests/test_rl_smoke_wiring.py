# Solo personal project, no connection to employer, built with public/free-tier only
"""Wiring tests for scripts/rl_smoke_update.py — the glue between TorchModelPolicy rollouts,
codeact rewards, group advantages, and TorchGRPOStep.

CI-fast by design: everything runs on TINY stub models (a few hundred params, clearly labeled
synthetic) and a char-level duck-typed tokenizer — NOT the pilot checkpoint (the full real-
checkpoint run is `python scripts/rl_smoke_update.py`, which appends measured numbers to
runs/cpu_pilot/MANIFEST.json). These tests pin the glue contracts:

  * RecordingTorchPolicy captures exactly the sampled ids + plain-log-softmax log-probs,
    including tokens the stop-matcher later cuts from the returned text.
  * build_grpo_batch produces the causal shift (actions[i] == full[i+1]), masks exactly the
    generated positions, and right-pads with mask 0.
  * flatten_group_advantages preserves rollout (prompt-major) order and yields all-zero
    advantages for a zero-variance group.
  * compute_r_task is answer-containment on the sanitized FINAL only.
  * append_manifest_section appends without clobbering, and falls back to MANIFEST_GRPO.json.
  * The whole chain (collect_rollouts -> batch -> TorchGRPOStep) runs on a tiny stub LM
    against the REAL sandbox and produces finite stats.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import sys

import pytest
import torch
from torch import nn

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from ava.rl.grpo import EntropyThermostat  # noqa: E402
from ava.rl.grpo_torch import TorchGRPOStep  # noqa: E402


def _load_module():
    path = os.path.join(REPO, "scripts", "rl_smoke_update.py")
    spec = importlib.util.spec_from_file_location("rl_smoke_update", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rl_smoke_update"] = mod  # dataclasses resolves cls.__module__ via sys.modules
    spec.loader.exec_module(mod)
    return mod


smoke = _load_module()


# ─────────────────────────────────────────────────────────────────────────────
# Tiny SYNTHETIC stubs (labeled: test-only, no capability, not Ava)
# ─────────────────────────────────────────────────────────────────────────────


class CharTok:
    """Char-level duck-typed tokenizer: lossless ASCII round-trip, vocab 128."""

    vocab_size = 128

    def encode(self, text: str) -> list:
        return [min(ord(c), 127) for c in text]

    def decode(self, ids: list) -> str:
        return "".join(chr(i) for i in ids)


class ScriptedNextCharLM(nn.Module):
    """SYNTHETIC test LM: emits `script` one char per step, keyed on input length.

    Position-only logits (no content dependence) make every expectation hand-computable:
    given L input tokens, the next char is script[(L - prompt_len) % len(script)] with
    logit 5.0, everything else 0.0.
    """

    def __init__(self, script: str, prompt_len: int):
        super().__init__()
        self.script = script
        self.prompt_len = prompt_len
        self.dummy = nn.Parameter(torch.zeros(1))  # so it owns a parameter

    def forward(self, input_ids=None, **_):
        b, length = input_ids.shape
        logits = torch.zeros(b, length, 128)
        idx = (length - self.prompt_len) % len(self.script)
        logits[:, -1, ord(self.script[idx])] = 5.0
        return logits  # raw-tensor contract of TorchModelPolicy


class TinyRandomLM(nn.Module):
    """SYNTHETIC ~2k-param random LM over the 128-char vocab (dict output like AvaModel)."""

    def __init__(self, seed: int = 0):
        super().__init__()
        torch.manual_seed(seed)
        self.emb = nn.Embedding(128, 8)
        self.head = nn.Linear(8, 128)

    def forward(self, input_ids=None, **_):
        return {"lm_logits": self.head(self.emb(input_ids))}


# ─────────────────────────────────────────────────────────────────────────────
# RecordingTorchPolicy
# ─────────────────────────────────────────────────────────────────────────────


def test_recording_policy_records_ids_and_plain_logprobs():
    tok = CharTok()
    prompt = "hi"
    lm = ScriptedNextCharLM("abc", prompt_len=len(prompt))
    pol = smoke.RecordingTorchPolicy(
        lm, tok, max_new_tokens=3, temperature=0.0, context_window=64, stop_sequences=()
    )
    out = pol(prompt)
    assert out == "abc"
    assert len(pol.records) == 1
    rec = pol.records[0]
    assert rec["prompt_ids"] == tok.encode(prompt)
    assert rec["gen_ids"] == [ord(c) for c in "abc"]
    # old_logp must be the PLAIN log-softmax of the raw logits (one hot 5.0 among 128 zeros)
    expected = float(torch.log_softmax(
        torch.tensor([5.0] + [0.0] * 127), dim=-1)[0])
    for lp in rec["old_logps"]:
        assert lp == pytest.approx(expected, abs=1e-6)


def test_recording_policy_keeps_stop_cut_tokens():
    tok = CharTok()
    prompt = "p"
    lm = ScriptedNextCharLM("aXb", prompt_len=len(prompt))
    pol = smoke.RecordingTorchPolicy(
        lm, tok, max_new_tokens=3, temperature=0.0, context_window=64,
        stop_sequences=("X",),
    )
    out = pol(prompt)
    assert out == "a"                                # text cut at the stop marker
    rec = pol.records[0]
    assert rec["gen_ids"] == [ord("a"), ord("X")]    # ...but the sampled X is recorded
    assert len(rec["old_logps"]) == 2


def test_recording_policy_guards_context_window():
    tok = CharTok()
    lm = ScriptedNextCharLM("a", prompt_len=10)
    pol = smoke.RecordingTorchPolicy(
        lm, tok, max_new_tokens=8, temperature=0.0, context_window=12, stop_sequences=()
    )
    with pytest.raises(ValueError, match="context_window"):
        pol("x" * 10)  # 10 + 8 > 12


def test_recording_policy_one_record_per_turn():
    tok = CharTok()
    lm = ScriptedNextCharLM("ab", prompt_len=1)
    pol = smoke.RecordingTorchPolicy(
        lm, tok, max_new_tokens=2, temperature=0.0, context_window=64, stop_sequences=()
    )
    pol("x")
    lm.prompt_len = 3  # keep alignment for the second scripted call
    pol("xyz")
    assert len(pol.records) == 2
    assert all(len(r["gen_ids"]) == 2 for r in pol.records)


# ─────────────────────────────────────────────────────────────────────────────
# Batch construction
# ─────────────────────────────────────────────────────────────────────────────


def _rollout(prompt_ids, gen_ids, old_logps, **kw):
    defaults = dict(
        prompt_index=0, group_index=0, decode_seed=0, total_gen_tokens=len(gen_ids),
        n_executed_actions=0, terminated="final", reached_final=True, r_task=0.0,
        rl_return=0.0, final_excerpt="", wall_s=0.0,
    )
    defaults.update(kw)
    return smoke.Rollout(prompt_ids=prompt_ids, gen_ids=gen_ids, old_logps=old_logps,
                         **defaults)


def test_build_grpo_batch_causal_shift_mask_and_padding():
    r0 = _rollout([5, 6, 7], [8, 9], [-1.0, -2.0])
    r1 = _rollout([3, 4], [5], [-0.5])
    batch = smoke.build_grpo_batch([r0, r1], [0.1, -0.2])
    assert batch["input_ids"].tolist() == [[5, 6, 7, 8], [3, 4, 0, 0]]
    assert batch["actions"].tolist() == [[6, 7, 8, 9], [4, 5, 0, 0]]
    assert batch["mask"].tolist() == [[0, 0, 1, 1], [0, 1, 0, 0]]
    assert batch["old_logp"].tolist() == [[0, 0, -1.0, -2.0], [0, -0.5, 0, 0]]
    assert batch["advantages"].tolist() == pytest.approx([0.1, -0.2])
    # every masked position's action is a generated token; actions[i] == full[i+1]
    assert batch["actions"][0, 2].item() == 8 and batch["actions"][0, 3].item() == 9


def test_build_grpo_batch_rejects_mismatch():
    r0 = _rollout([1, 2], [3], [-0.1])
    with pytest.raises(ValueError, match="advantages"):
        smoke.build_grpo_batch([r0], [0.1, 0.2])
    bad = _rollout([1, 2], [3, 4], [-0.1])  # one logp for two gen ids
    with pytest.raises(ValueError, match="mismatch"):
        smoke.build_grpo_batch([bad], [0.1])


# ─────────────────────────────────────────────────────────────────────────────
# Advantages / r_task / manifest
# ─────────────────────────────────────────────────────────────────────────────


def test_flatten_group_advantages_order_and_degenerate_group():
    groups = [[1.0, 0.0], [0.5, 0.5]]
    adv = smoke.flatten_group_advantages(groups)
    assert len(adv) == 4
    assert adv[0] > 0 > adv[1]                       # winner/loser of group 0, in order
    assert adv[2] == pytest.approx(0.0, abs=1e-6)    # zero-variance group -> no signal
    assert adv[3] == pytest.approx(0.0, abs=1e-6)


def test_compute_r_task_containment_rules():
    assert smoke.compute_r_task("42", "the answer is 42", True) == 1.0
    assert smoke.compute_r_task("42", "no idea", True) == 0.0
    assert smoke.compute_r_task("42", None, False) == 0.0
    assert smoke.compute_r_task("42", "42", False) == 0.0   # step-cap: no FINAL, no credit
    assert smoke.compute_r_task("", "anything", True) == 0.0


def test_append_manifest_section_appends_and_falls_back(tmp_path):
    manifest = tmp_path / "MANIFEST.json"
    manifest.write_text(json.dumps({"status": "success", "runs": {"base": 1}}))
    out = smoke.append_manifest_section({"x": 1}, str(manifest))
    assert out == str(manifest)
    data = json.loads(manifest.read_text())
    assert data["status"] == "success" and data["runs"] == {"base": 1}   # untouched
    assert data["grpo_smoke"] == {"x": 1}
    # absent manifest -> sibling MANIFEST_GRPO.json
    missing = tmp_path / "sub" / "MANIFEST.json"
    missing.parent.mkdir()
    out2 = smoke.append_manifest_section({"y": 2}, str(missing))
    assert out2 == str(tmp_path / "sub" / "MANIFEST_GRPO.json")
    assert json.loads(open(out2).read()) == {"grpo_smoke": {"y": 2}}


# ─────────────────────────────────────────────────────────────────────────────
# End-to-end wiring on a tiny stub LM (real sandbox, real GRPO step — no capability)
# ─────────────────────────────────────────────────────────────────────────────


def test_full_wiring_tiny_stub_through_real_sandbox_and_grpo_step():
    """collect_rollouts -> flatten_group_advantages -> build_grpo_batch -> TorchGRPOStep on a
    ~2k-param SYNTHETIC LM. The rollouts run through the REAL run_code_act/Sandbox; the stub's
    noise turns earn r_task=0 (expected). Asserts mechanical health only."""
    from ava.datagen.codeact import iter_trajectories

    tok = CharTok()
    lm = TinyRandomLM(seed=0)
    trajs = list(iter_trajectories(seed=0, n=1))
    rollouts, groups = smoke.collect_rollouts(
        lm, tok, trajs,
        group_size=2, temperature=1.0, top_k=0, max_new_tokens=4, context_window=256,
        eos_id=None, seed=0, max_episode_steps=1, timeout_s=3.0, family_pass_rate=0.5,
    )
    assert len(rollouts) == 2 and len(groups) == 1 and len(groups[0]) == 2
    assert all(len(r.gen_ids) >= 1 for r in rollouts)
    assert all(len(r.gen_ids) == len(r.old_logps) for r in rollouts)
    assert all(math.isfinite(r.rl_return) for r in rollouts)

    adv = smoke.flatten_group_advantages(groups)
    batch = smoke.build_grpo_batch(rollouts, adv)
    stepper = TorchGRPOStep(
        lm, torch.optim.SGD(lm.parameters(), lr=0.01),
        EntropyThermostat(kappa=0.5, h_target=0.3), r_outer=1.0,
    )
    stats = stepper.step(
        {"input_ids": batch["input_ids"]}, batch["actions"], batch["old_logp"],
        batch["advantages"], mask=batch["mask"],
    )
    assert stats.batch_size == 2
    assert math.isfinite(stats.loss)
    assert math.isfinite(stats.rl_entropy)
    assert stats.outer_clip_hits == 0                # on-policy: ratios ~1
    assert stats.mean_ratio == pytest.approx(1.0, abs=1e-3)
    assert all(bool(torch.isfinite(p).all()) for p in lm.parameters())
