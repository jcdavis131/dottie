# Solo personal project, no connection to employer, built with public/free-tier only
"""Policy provider tests — honest unavailability, deterministic plumbing, real smoke decode."""

from __future__ import annotations

import pytest

from dottie import resolve
from dottie.policy import (
    AvaPolicy,
    DottiePolicyUnavailable,
    EchoPolicy,
    OllamaPolicy,
    get_policy,
    strip_think,
    transcript_to_messages,
)
from tests.conftest import UNROUTABLE_OLLAMA

# -- transcript parsing -------------------------------------------------------------


def test_transcript_to_messages_roles_and_order():
    transcript = (
        "<|user|>\nWhat is 2+2?\n<|assistant|>\nThought: compute\n```python\n2+2\n```\n"
        "<|user|>\nObservation:\n=> 4"
    )
    msgs = transcript_to_messages(transcript)
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[0]["content"] == "What is 2+2?"
    assert "Observation:" in msgs[2]["content"]


def test_transcript_without_markers_is_user_content():
    msgs = transcript_to_messages("bare prompt")
    assert msgs == [{"role": "user", "content": "bare prompt"}]


def test_strip_think_removes_closed_blocks_only():
    assert strip_think("<think>reasoning</think>\nFINAL: done") == "FINAL: done"
    # An unclosed block is left as-is — we never guess where it ended.
    assert "<think>" in strip_think("<think>never closed FINAL: x")


# -- EchoPolicy ---------------------------------------------------------------------


def test_echo_policy_is_deterministic_and_labeled():
    a, b = EchoPolicy(), EchoPolicy()
    t = "<|user|>\nsome task"
    turns_a = [a(t), a(t), a(t), a(t)]
    turns_b = [b(t), b(t), b(t), b(t)]
    assert turns_a == turns_b  # deterministic
    assert "```python" in turns_a[0] and "```python" in turns_a[1]
    assert "```python" not in turns_a[2]  # third turn is the FINAL (no fence)
    assert "plumbing" in turns_a[2]
    assert turns_a[3] == ""  # exhausted -> honest empty turn
    assert EchoPolicy.plumbing_only is True
    assert EchoPolicy().probe()["plumbing_only"] is True


# -- OllamaPolicy -------------------------------------------------------------------


def test_ollama_unreachable_raises_honest_unavailable():
    p = OllamaPolicy(
        base_url=UNROUTABLE_OLLAMA, connect_timeout_s=2.0, read_timeout_s=2.0
    )
    with pytest.raises(DottiePolicyUnavailable) as ei:
        p("<|user|>\nhello")
    msg = str(ei.value)
    assert "unreachable" in msg and UNROUTABLE_OLLAMA in msg
    assert "fabricate" in msg  # the refusal says it will not fake a reply


def test_ollama_probe_reports_unavailable_honestly():
    probe = OllamaPolicy(base_url=UNROUTABLE_OLLAMA).probe()
    assert probe["available"] is False
    assert "error" in probe and probe["url"] == UNROUTABLE_OLLAMA


def test_ollama_env_config(monkeypatch):
    monkeypatch.setenv("DOTTIE_OLLAMA_URL", "http://example.invalid:1234/")
    monkeypatch.setenv("DOTTIE_OLLAMA_MODEL", "some-model:7b")
    p = OllamaPolicy()
    assert p.base_url == "http://example.invalid:1234"
    assert p.model == "some-model:7b"


# -- AvaPolicy ----------------------------------------------------------------------


def test_ava_policy_docstring_states_smoke_scale_honesty():
    doc = AvaPolicy.__doc__ or ""
    assert "smoke-scale" in doc
    assert "ZERO task capability" in doc
    assert "flywheel" in doc


def test_ava_missing_checkpoint_refuses_honestly(tmp_path):
    p = AvaPolicy(ckpt=str(tmp_path / "nope.pt"))
    with pytest.raises(DottiePolicyUnavailable) as ei:
        p("<|user|>\nhello")
    assert "checkpoint" in str(ei.value)
    probe = p.probe()
    assert probe["available"] is False and "error" in probe


def test_ava_no_candidates_refuses_honestly(monkeypatch, tmp_path):
    # Point every resolution root at an empty dir: no checkpoint can be found.
    monkeypatch.setenv("DOTTIE_ROOT", str(tmp_path))
    monkeypatch.setenv("AVA_FACTORY_ROOT", str(tmp_path))
    monkeypatch.setattr(resolve, "DEFAULT_FACTORY_ROOT", tmp_path)
    p = AvaPolicy()
    with pytest.raises(DottiePolicyUnavailable) as ei:
        p("<|user|>\nhello")
    assert "no ava checkpoint found" in str(ei.value)


@pytest.mark.skipif(
    resolve.default_ava_ckpt() is None,
    reason="no real ava smoke checkpoint on this box (runs/cpu_pilot absent)",
)
def test_ava_real_smoke_decode_emits_a_turn():
    """REAL decode over the real smoke checkpoint. The output is expected to be noise —
    that is the honest emission of a zero-capability checkpoint, not a defect."""
    p = AvaPolicy(
        max_new_tokens=4
    )  # tiny budget: this is a plumbing check, not capability
    turn = p("<|user|>\nsay hello")
    assert isinstance(turn, str)
    # A second call reuses the loaded model and stays deterministic (seeded sampling).
    assert p("<|user|>\nsay hello") == turn


# -- factory ------------------------------------------------------------------------


def test_get_policy_backends():
    assert get_policy("echo").name == "echo"
    assert get_policy("ollama").name == "ollama"
    assert get_policy("ava").name == "ava"
    with pytest.raises(ValueError):
        get_policy("gpt-o-matic")
