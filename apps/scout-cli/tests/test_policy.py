"""Decision-matrix tests for the policy engine (findings #13/#14)."""

import pytest
import typer

from bigbang.core import policy


def _manifest(enabled=True, domains=None, fs_write=False):
    return {
        "name": "t",
        "capabilities": {
            "network": {
                "enabled": enabled,
                "domains": domains if domains is not None else [],
            },
            "filesystem": {"write": fs_write},
        },
    }


class TestManifestNetworkMatrix:
    def test_network_disabled_denies(self):
        ok, reason = policy.check_permission(
            _manifest(enabled=False), "network", "https://a.com"
        )
        assert not ok
        assert "disabled" in reason

    def test_enabled_empty_domains_denies_everything(self):
        # documented default-deny: enabling network without domains allows nothing
        ok, reason = policy.check_permission(
            _manifest(domains=[]), "network", "https://a.com"
        )
        assert not ok
        assert "default-deny" in reason or "empty" in reason

    def test_matching_domain_allows(self):
        ok, _ = policy.check_permission(
            _manifest(domains=["api.example.com"]),
            "network",
            "https://api.example.com/v1/x",
        )
        assert ok

    def test_subdomain_allows(self):
        ok, _ = policy.check_permission(
            _manifest(domains=["example.com"]), "network", "https://api.example.com/v1"
        )
        assert ok

    def test_url_mismatch_denies(self):
        ok, reason = policy.check_permission(
            _manifest(domains=["example.com"]), "network", "https://evil.org/x"
        )
        assert not ok
        assert "not in allowlist" in reason

    def test_non_http_resource_mismatch_denies(self):
        # (a) explicit deny on domain mismatch for non-http resource shapes
        ok, _reason = policy.check_permission(
            _manifest(domains=["example.com"]), "network", "evil.org"
        )
        assert not ok

    def test_non_http_resource_match_allows(self):
        ok, _ = policy.check_permission(
            _manifest(domains=["example.com"]), "network", "example.com"
        )
        assert ok

    def test_fs_write_denied_by_default(self):
        ok, _reason = policy.check_permission(_manifest(), "fs_write", "/tmp/x")
        assert not ok

    def test_fs_write_allowed_when_declared(self):
        ok, _ = policy.check_permission(_manifest(fs_write=True), "fs_write", "/tmp/x")
        assert ok

    def test_enforce_or_raise_exits_on_deny(self):
        with pytest.raises(typer.Exit):
            policy.enforce_or_raise(
                _manifest(enabled=False), "network", "https://a.com"
            )


class TestUserAllowlist:
    @pytest.fixture(autouse=True)
    def _policy_file(self, tmp_path, monkeypatch):
        self.fp = tmp_path / "policy.yaml"
        monkeypatch.setenv("BIGBANG_POLICY_FILE", str(self.fp))

    def test_missing_file_materializes_default_local_only(self):
        ok, _ = policy.check_user_url("http://localhost:8787/sse")
        assert ok
        assert self.fp.exists(), (
            "default policy file should be created for the user to edit"
        )
        ok2, _reason = policy.check_user_url("https://api.example.com/x")
        assert not ok2

    def test_user_added_domain_allows(self):
        self.fp.write_text("network:\n  allowed_domains: [api.example.com]\n")
        ok, _ = policy.check_user_url("https://api.example.com/v1")
        assert ok
        ok2, _ = policy.check_user_url("https://other.com")
        assert not ok2

    def test_empty_allowlist_denies_all(self):
        self.fp.write_text("network:\n  allowed_domains: []\n")
        ok, reason = policy.check_user_url("http://localhost:1")
        assert not ok
        assert "default-deny" in reason

    def test_unparseable_policy_fails_closed(self):
        self.fp.write_text("network: [unclosed")
        ok, _ = policy.check_user_url("http://localhost:1")
        assert not ok

    def test_enforce_user_url_or_raise(self):
        self.fp.write_text("network:\n  allowed_domains: []\n")
        with pytest.raises(typer.Exit):
            policy.enforce_user_url_or_raise("https://example.com", context="test")


class TestFsWriteEnforcementWired:
    def test_tasks_rft_graphify_manifests_declare_fs_write(self):
        # the call sites added in tasks export / rft export / graphify sync rely on this
        from pathlib import Path

        for plugin in ("tasks", "rft", "graphify"):
            mf = policy.load_manifest(Path("bigbang/plugins") / plugin)
            ok, reason = policy.check_permission(mf, "fs_write", "/anywhere")
            assert ok, f"{plugin}: {reason}"
