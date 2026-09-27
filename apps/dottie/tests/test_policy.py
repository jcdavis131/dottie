# Solo personal project, no connection to employer, built with public/free-tier only
"""Policy provider tests — honest unavailability, deterministic plumbing, real smoke decode."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

import dottie.policy as policy_mod
from dottie import resolve
from dottie.policy import (
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_NUM_PREDICT,
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


# -- OllamaPolicy request options (fake transport, no network) ------------------------

_OPTION_ENV = (
    "DOTTIE_OLLAMA_MODEL",
    "DOTTIE_OLLAMA_NUM_PREDICT",
    "DOTTIE_OLLAMA_TEMPERATURE",
    "DOTTIE_OLLAMA_NUM_CTX",
    "DOTTIE_OLLAMA_NUM_GPU",
    "DOTTIE_OLLAMA_KEEP_ALIVE",
    "DOTTIE_OLLAMA_THINK",
)


class _FakeOllama:
    """Stands in for ``httpx.post``: records every /api/chat payload, answers 200."""

    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def __call__(self, url, json=None, timeout=None):
        self.payloads.append(json)
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": "FINAL: ok"}},
            request=httpx.Request("POST", url),
        )

    @property
    def options(self) -> dict:
        return self.payloads[-1]["options"]


@pytest.fixture()
def fake_ollama(monkeypatch):
    for var in _OPTION_ENV:
        monkeypatch.delenv(var, raising=False)
    fake = _FakeOllama()
    monkeypatch.setattr(policy_mod.httpx, "post", fake)
    return fake


def test_ollama_default_model_is_the_pulled_qwen3_8b(fake_ollama):
    # qwen3:32b is not pulled on the 4080 box (`ollama list`, 2026-09-27: qwen3:8b only); the
    # research loop already pins qwen3:8b through its env, so only the bare default refused.
    assert DEFAULT_OLLAMA_MODEL == "qwen3:8b"
    p = OllamaPolicy(base_url="http://x")
    assert p.model == "qwen3:8b"
    p("<|user|>\nhello")
    assert fake_ollama.payloads[-1]["model"] == "qwen3:8b"


def test_compose_default_model_matches_the_policy_default():
    app_root = Path(policy_mod.__file__).resolve().parent.parent
    compose = (app_root / "docker-compose.dottie.yml").read_text(encoding="utf-8")
    line = f"DOTTIE_OLLAMA_MODEL: ${{DOTTIE_OLLAMA_MODEL:-{DEFAULT_OLLAMA_MODEL}}}"
    assert line in compose


def test_ollama_caps_every_generation_by_default(fake_ollama):
    """No cap meant a degenerate generation ran until the server stopped it, and
    llama-server's --context-shift keeps sliding the window instead of stopping. Measured
    2026-09-27: one call ran 708 s to 81,920 tokens (done_reason=length)."""
    p = OllamaPolicy(base_url="http://x", model="m")
    assert p("<|user|>\nhello") == "FINAL: ok"  # the CodeAct path
    assert fake_ollama.options["num_predict"] == DEFAULT_OLLAMA_NUM_PREDICT == 2048
    p.complete("hi", temperature=0.9)  # the research path, per-call temperature
    assert fake_ollama.options["num_predict"] == 2048
    # Knobs left unset keep today's request: the 0.2 temperature, no num_ctx.
    p("<|user|>\nhello")
    assert fake_ollama.options["temperature"] == 0.2
    assert "num_ctx" not in fake_ollama.options


def test_ollama_num_predict_env_and_arg(fake_ollama, monkeypatch):
    monkeypatch.setenv("DOTTIE_OLLAMA_NUM_PREDICT", "512")
    OllamaPolicy(base_url="http://x", model="m").complete("hi")
    assert fake_ollama.options["num_predict"] == 512
    # An explicit constructor value beats the env.
    OllamaPolicy(base_url="http://x", model="m", num_predict=64).complete("hi")
    assert fake_ollama.options["num_predict"] == 64
    # 0 or negative = no cap: the key is omitted (Ollama's own default applies).
    for off in ("0", "-1"):
        monkeypatch.setenv("DOTTIE_OLLAMA_NUM_PREDICT", off)
        p = OllamaPolicy(base_url="http://x", model="m")
        assert p.num_predict is None
        p.complete("hi")
        assert "num_predict" not in fake_ollama.options
    # Blank is unset, so the default cap applies.
    monkeypatch.setenv("DOTTIE_OLLAMA_NUM_PREDICT", "  ")
    OllamaPolicy(base_url="http://x", model="m").complete("hi")
    assert fake_ollama.options["num_predict"] == 2048
    # A typo refuses loudly instead of silently running uncapped.
    monkeypatch.setenv("DOTTIE_OLLAMA_NUM_PREDICT", "lots")
    with pytest.raises(ValueError, match="DOTTIE_OLLAMA_NUM_PREDICT"):
        OllamaPolicy(base_url="http://x", model="m")


def test_ollama_temperature_env_precedence(fake_ollama, monkeypatch):
    monkeypatch.setenv("DOTTIE_OLLAMA_TEMPERATURE", "0.7")
    p = OllamaPolicy(base_url="http://x", model="m")
    p("<|user|>\nhello")
    assert fake_ollama.options["temperature"] == 0.7
    p.complete("hi")
    assert fake_ollama.options["temperature"] == 0.7
    # Per-call temperature (the research stages set it) still wins over the env...
    p.complete("hi", temperature=1.0)
    assert fake_ollama.options["temperature"] == 1.0
    # ...and so does an explicit constructor value.
    OllamaPolicy(base_url="http://x", model="m", temperature=0.1).complete("hi")
    assert fake_ollama.options["temperature"] == 0.1
    monkeypatch.setenv("DOTTIE_OLLAMA_TEMPERATURE", "warm")
    with pytest.raises(ValueError, match="DOTTIE_OLLAMA_TEMPERATURE"):
        OllamaPolicy(base_url="http://x", model="m")


def test_ollama_num_ctx_env(fake_ollama, monkeypatch):
    monkeypatch.setenv("DOTTIE_OLLAMA_NUM_CTX", "8192")
    OllamaPolicy(base_url="http://x", model="m").complete("hi")
    assert fake_ollama.options["num_ctx"] == 8192
    OllamaPolicy(base_url="http://x", model="m", num_ctx=4096).complete("hi")
    assert fake_ollama.options["num_ctx"] == 4096
    monkeypatch.setenv("DOTTIE_OLLAMA_NUM_CTX", "0")
    OllamaPolicy(base_url="http://x", model="m").complete("hi")
    assert "num_ctx" not in fake_ollama.options
    monkeypatch.setenv("DOTTIE_OLLAMA_NUM_CTX", "8k")
    with pytest.raises(ValueError, match="DOTTIE_OLLAMA_NUM_CTX"):
        OllamaPolicy(base_url="http://x", model="m")


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
