# Solo personal project, no connection to employer, built with public/free-tier only
"""Verified-task engine tests.

Two load-bearing honesty proofs:
  * EchoPolicy (echoes the prompt) CANNOT pass any verifier — because the provider guarantees
    the scoring token never appears in the prompt — so r_task=0.0 is recorded honestly,
    proving the verifier bites.
  * A SCRIPTED SOLVER policy (clearly-labeled synthetic plumbing policy, the factory's
    scripted-logits pattern) genuinely solves tasks THROUGH the real sandbox: it emits code,
    the sandbox really executes it, and the FINAL is parsed from the REAL observation text —
    so r_task=1.0 is a real verified success of the machinery (never a capability claim)."""

from __future__ import annotations

import re

import pytest

import dottie.engine as engine_mod


def test_echo_cannot_pass_verifier_r_task_zero_recorded(engine):
    rec = engine.run_task(family="compute", seed=0, backend="echo")
    assert rec["terminated"] == "final"          # echo reached a FINAL...
    comps = rec["reward_components"]
    assert comps["r_task"] == 0.0                # ...but the verifier honestly scored it 0
    assert comps["r_task_note"].startswith("verified: family=compute")
    # rl_return blends the real components; with r_task=0 it is exactly the exec+codeuse part.
    assert comps["rl_return"] == pytest.approx(
        0.2 * comps["r_exec"] + 0.2 * comps["r_codeuse"]
    )
    detail = rec["verified_task"]
    assert detail["family"] == "compute" and detail["seed"] == 0
    assert detail["expected"] not in rec["prompt"]   # the no-leak property, on the real record


def test_no_final_is_a_verified_failure_not_a_crash(engine):
    # max_steps=2 stops EchoPolicy before its FINAL turn -> step_cap -> honest r_task=0.0.
    rec = engine.run_task(family="compute", seed=1, backend="echo", max_steps=2)
    assert rec["terminated"] == "step_cap" and rec["final"] is None
    comps = rec["reward_components"]
    assert comps["r_task"] == 0.0
    assert "no FINAL emitted" in comps["r_task_note"]


def test_prompt_and_family_are_exclusive(engine):
    with pytest.raises(ValueError):
        engine.run_task("free-form", family="compute", backend="echo")
    with pytest.raises(ValueError):
        engine.run_task(backend="echo")   # neither form given


def test_freeform_contract_unchanged(engine):
    rec = engine.run_task("just a prompt", backend="echo")
    assert rec["reward_components"]["r_task"] is None
    assert "verified_task" not in rec and "rl_return" not in rec["reward_components"]


# ---------------------------------------------------------------------------
# Scripted solver policies — synthetic plumbing policies (labeled), REAL execution.
# ---------------------------------------------------------------------------

class _ScriptedSolver:
    """Base: emit one real code block built from the task prompt, then a FINAL whose value is
    parsed from the REAL rendered Observation in the transcript. plumbing_only: this is
    machinery verification with a scripted brain, never a model-capability measurement."""

    name = "scripted-solver"
    plumbing_only = True

    def __init__(self) -> None:
        self._step = 0

    def code_for(self, transcript: str) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

    def final_for(self, transcript: str) -> str:
        got = re.findall(r"=> (\S+)", transcript)[-1].strip("'\"")
        return f"FINAL: computed in the sandbox; the result is {got}."

    def __call__(self, transcript: str) -> str:
        self._step += 1
        if self._step == 1:
            return f"Thought: solve it with real code.\n```python\n{self.code_for(transcript)}\n```"
        if self._step == 2:
            return self.final_for(transcript)
        return ""


class _ComputeSolver(_ScriptedSolver):
    def code_for(self, transcript: str) -> str:
        nums = re.search(r"Data list: (\[[^\]]*\])", transcript).group(1)
        return (f"nums = {nums}\n"
                "sum(x * x for x in nums if x % 2 == 0) - sum(x for x in nums if x % 2 == 1)")


class _ToolChainSolver(_ScriptedSolver):
    def code_for(self, transcript: str) -> str:
        p1, p2 = re.search(r"For parts (\S+) and (\S+):", transcript).groups()
        return (
            f"total = 0\n"
            f"for pid in [{p1!r}, {p2!r}]:\n"
            f"    part = part_lookup(pid)\n"
            f"    total += part['weight_g'] * bin_rate(part['bin'])\n"
            f"total"
        )


class _FileOpsSolver(_ScriptedSolver):
    def code_for(self, transcript: str) -> str:
        body = transcript.split("take these lines:\n", 1)[1].split("\nWrite them", 1)[0]
        return (
            f"lines = {body.splitlines()!r}\n"
            "content = '\\n'.join(l.upper() for l in lines) + '\\n'\n"
            "with open('report.txt', 'w') as f:\n"
            "    f.write(content)\n"
            "import hashlib\n"
            "with open('report.txt', 'rb') as f:\n"
            "    data = f.read()\n"
            "hashlib.sha256(data).hexdigest()[:12]"
        )


def _run_scripted(engine, monkeypatch, family: str, seed: int, solver_cls):
    monkeypatch.setattr(engine_mod, "get_policy", lambda backend, **kw: solver_cls())
    return engine.run_task(family=family, seed=seed, backend="scripted")


def test_scripted_solver_earns_r_task_one_through_real_sandbox(engine, monkeypatch):
    rec = _run_scripted(engine, monkeypatch, "compute", 3, _ComputeSolver)
    assert rec["terminated"] == "final"
    assert rec["steps"][0]["ok"] is True          # the code REALLY ran in the sandbox
    comps = rec["reward_components"]
    assert comps["r_task"] == 1.0
    assert comps["rl_return"] == pytest.approx(1.0 + 0.2 * comps["r_exec"]
                                               + 0.2 * comps["r_codeuse"])
    assert rec["verified_task"]["expected"] in rec["final"]


def test_scripted_tool_chain_solver_uses_real_bound_tools(engine, monkeypatch):
    rec = _run_scripted(engine, monkeypatch, "tool_chain", 5, _ToolChainSolver)
    assert rec["reward_components"]["r_task"] == 1.0
    # The verifier demanded — and the trace shows — REAL recorded calls to both tools.
    called = {c["tool"] for c in rec["steps"][0]["tool_calls"]}
    assert {"part_lookup", "bin_rate"} <= called


def test_scripted_file_ops_solver_writes_in_real_scratch(engine, monkeypatch):
    """Proves the sandbox genuinely allows the write under its scratch dir and that the
    digest of the real file bytes matches the provider's re-derived expectation."""
    rec = _run_scripted(engine, monkeypatch, "file_ops", 2, _FileOpsSolver)
    assert rec["steps"][0]["ok"] is True, rec["steps"][0]["error"]
    assert rec["reward_components"]["r_task"] == 1.0


def test_scripted_solver_fails_honestly_on_wrong_computation(engine, monkeypatch):
    """Same scripted machinery with a wrong program -> the verifier scores 0.0 (it really
    discriminates; passing is not an artifact of the harness)."""

    class _WrongSolver(_ComputeSolver):
        def code_for(self, transcript: str) -> str:
            return super().code_for(transcript) + " + 1"   # off by one, really executed

    rec = _run_scripted(engine, monkeypatch, "compute", 3, _WrongSolver)
    assert rec["steps"][0]["ok"] is True
    assert rec["reward_components"]["r_task"] == 0.0
