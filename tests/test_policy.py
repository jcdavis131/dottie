"""Tests for policy — capability based default-deny"""

import importlib.util

MOD_PATH = "/home/hatch/workspace/dottie/apps/scout-cli/bigbang/core/policy.py"
spec = importlib.util.spec_from_file_location("policy_module", MOD_PATH)
mod = importlib.util.module_from_spec(spec)
import sys

sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def test_default_policy_structure():
    assert hasattr(mod, "DEFAULT_POLICY")
    dp = mod.DEFAULT_POLICY
    assert "allow_network" in dp
    assert dp["allow_network"] is False


def test_domain_matches_exact_and_subdomain():
    assert mod._domain_matches("example.com", "https://example.com/path")
    assert mod._domain_matches("example.com", "https://sub.example.com/x")
    assert not mod._domain_matches("example.com", "https://evil.com")
    assert not mod._domain_matches("example.com", "https://evil.com/example.com")
    # localhost substring attack fixed
    assert not mod._domain_matches("localhost", "http://evil.com/localhost")


def test_host_of_extraction():
    assert mod._host_of("https://example.com/foo") == "example.com"
    assert mod._host_of("127.0.0.1") == "127.0.0.1"
    assert mod._host_of("example.com") == "example.com"


def test_user_policy_file_override(monkeypatch):
    monkeypatch.setenv("BIGBANG_POLICY_FILE", "/tmp/custom_policy.yaml")
    p = mod.user_policy_file()
    assert str(p) == "/tmp/custom_policy.yaml"
    monkeypatch.delenv("BIGBANG_POLICY_FILE", raising=False)
    # default path contains bigbang/policy.yaml
    p2 = mod.user_policy_file()
    assert "bigbang" in str(p2) and "policy.yaml" in str(p2)


def test_load_user_policy_creates_default(tmp_path, monkeypatch):
    fp = tmp_path / "policy.yaml"
    monkeypatch.setattr(mod, "user_policy_file", lambda: fp)
    data = mod.load_user_policy()
    assert isinstance(data, dict)
    assert fp.exists()
    assert "network" in data
