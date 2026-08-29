"""Tests for Glimmer provider — local Muse Glimmer 30B agent."""

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bigbang.core import glimmer as gm
from bigbang.core import llm as llm_mod


def test_glimmer_models_in_preferred():
    assert "muse-glimmer:30b" in llm_mod.PREFERRED_MODELS
    assert llm_mod.PREFERRED_MODELS[0] == "muse-glimmer:30b"


def test_glimmer_models_constant():
    assert len(gm.GLIMMER_MODELS) >= 3
    assert any("glimmer" in m for m in gm.GLIMMER_MODELS)


def test_reasoning_levels():
    assert set(gm.REASONING_LEVELS.keys()) == {"low", "medium", "high", "xhigh"}
    for lvl, prompt in gm.REASONING_LEVELS.items():
        assert isinstance(prompt, str) and len(prompt) > 10
        assert lvl in prompt.lower() or "reasoning" in prompt.lower()


def test_build_system_prompt():
    for lvl in ["low", "medium", "high", "xhigh"]:
        sp = gm.build_system_prompt(lvl)
        assert isinstance(sp, str)
        assert len(sp) > 50
        assert "Glimmer" in sp or "glimmer" in sp.lower() or "Reasoning" in sp
    sp_extra = gm.build_system_prompt("medium", extra="You are coding assistant")
    assert "coding assistant" in sp_extra


def test_build_messages_text_only():
    msgs = gm.build_messages("hello world", reasoning="low")
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert msgs[1]["content"] == "hello world"
    assert "images" not in msgs[1]


def test_build_messages_with_history():
    msgs = gm.build_messages("followup", history=[{"role": "assistant", "content": "hi"}])
    assert len(msgs) == 3


def test_encode_image_missing():
    assert gm._encode_image_to_b64("/nonexistent/path.png") is None


def test_encode_image_real(tmp_path):
    p = tmp_path / "img.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    b64 = gm._encode_image_to_b64(str(p))
    assert b64 is not None
    import base64
    decoded = base64.b64decode(b64)
    assert decoded.startswith(b"\x89PNG")


def test_get_glimmer_endpoint_env(monkeypatch):
    monkeypatch.setenv("GLIMMER_BASE", "http://myhost:11434")
    ep = gm.get_glimmer_endpoint(timeout=0.1)
    assert ep == "http://myhost:11434"
    monkeypatch.delenv("GLIMMER_BASE", raising=False)


def test_glimmer_chat_offline(monkeypatch):
    monkeypatch.setattr(gm, "get_glimmer_endpoint", lambda timeout=2.0: None)
    res = gm.glimmer_chat("hi", timeout=1)
    assert res["ok"] is False
    assert "ollama" in res["error"].lower() or "not reachable" in res["error"].lower()


def test_glimmer_available_offline(monkeypatch):
    monkeypatch.setattr(gm, "get_glimmer_endpoint", lambda timeout=2.0: None)
    assert gm.is_glimmer_available(timeout=0.5) is False


def test_best_glimmer_fallback(monkeypatch):
    monkeypatch.setattr(gm, "list_ollama_models", lambda base=None, timeout=2.0: [])
    model = gm.get_best_glimmer_model(base="http://localhost:11434", timeout=0.1)
    assert model == "muse-glimmer:30b"


def test_best_glimmer_picks_glimmer(monkeypatch):
    monkeypatch.setattr(gm, "list_ollama_models", lambda base=None, timeout=2.0: ["llama3:8b", "muse-glimmer:30b", "qwen3:14b"])
    model = gm.get_best_glimmer_model(base="http://localhost:11434")
    assert "glimmer" in model.lower()


def test_glimmer_plugin_cli_exists():
    from bigbang.plugins.glimmer import cli as gcli
    assert hasattr(gcli, "app")
    assert gcli.app is not None


def test_llm_glimmer_alias():
    assert hasattr(llm_mod, "GLIMMER_MODELS")
    assert "muse-glimmer:30b" in llm_mod.GLIMMER_MODELS
