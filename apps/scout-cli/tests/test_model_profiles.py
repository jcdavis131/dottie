# Solo personal project, no connection to employer, built with public/free-tier only
"""Provider/model profile registry — deepagents-pattern resolution order."""

import json

import pytest

from bigbang.core import model_profiles as mp


@pytest.fixture(autouse=True)
def clean_registry():
    mp.reset_profiles()
    yield
    mp.reset_profiles()
    # restore module defaults for other tests/processes
    mp.register_provider("ollama", num_gpu=0, temperature=0.2)
    mp.register_model("ollama:qwen3:8b", num_ctx=8192)


def test_spec_parsing_first_colon_and_ollama_tags():
    assert mp.parse_spec("openai:gpt-5.4") == ("openai", "gpt-5.4")
    # ollama tags contain colons; unknown prefix folds into the model name
    assert mp.parse_spec("qwen3:8b") == ("ollama", "qwen3:8b")
    assert mp.parse_spec("ollama:qwen3:8b") == ("ollama", "qwen3:8b")
    assert mp.parse_spec("bare-model") == ("ollama", "bare-model")


def test_resolution_order_provider_then_model_then_overrides():
    mp.register_provider("ollama", temperature=0.2, num_gpu=0)
    mp.register_model("ollama:qwen3:8b", temperature=0.7, num_ctx=8192)
    r = mp.resolve("ollama:qwen3:8b", temperature=0.9)
    assert r["provider"] == "ollama" and r["model"] == "qwen3:8b"
    assert r["params"]["temperature"] == 0.9  # call-site wins
    assert r["params"]["num_ctx"] == 8192  # model level survives
    assert r["params"]["num_gpu"] == 0  # provider level survives


def test_none_overrides_do_not_erase():
    mp.register_provider("ollama", temperature=0.2)
    r = mp.resolve("ollama:m", temperature=None)
    assert r["params"]["temperature"] == 0.2


def test_unregistered_spec_resolves_empty_params():
    r = mp.resolve("anthropic:claude-opus-4-8")
    assert r == {"provider": "anthropic", "model": "claude-opus-4-8", "params": {}}


def test_load_profiles_from_json(tmp_path):
    f = tmp_path / "profiles.json"
    f.write_text(
        json.dumps(
            {
                "providers": {"koboldcpp": {"max_length": 512}},
                "models": {"ollama:qwen3:8b": {"num_ctx": 16384}},
            }
        ),
        encoding="utf-8",
    )
    assert mp.load_profiles(f) == 2
    assert mp.resolve("koboldcpp:x")["params"]["max_length"] == 512
    assert mp.resolve("qwen3:8b")["params"]["num_ctx"] == 16384


def test_load_profiles_missing_file_returns_zero(tmp_path):
    assert mp.load_profiles(tmp_path / "absent.json") == 0
