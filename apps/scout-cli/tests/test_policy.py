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


class TestDomainMatchBypasses:
    """Regression: the 2026-07-22 monorepo review reproduced two allowlist
    bypasses against the legacy substring matcher. Matching is host-only now:
    exact host or dot-suffix subdomain — never a substring of path or a crafted
    hostname."""

    @pytest.fixture(autouse=True)
    def _policy_file(self, tmp_path, monkeypatch):
        self.fp = tmp_path / "policy.yaml"
        monkeypatch.setenv("BIGBANG_POLICY_FILE", str(self.fp))

    def test_allowlisted_host_in_path_does_not_bypass(self):
        # bypass #1: "localhost" allowlisted, attacker URL carries it in the PATH
        self.fp.write_text("network:\n  allowed_domains: [localhost]\n")
        ok, reason = policy.check_user_url("http://evil.com/localhost")
        assert not ok, "substring-in-path must not satisfy the allowlist"
        assert "evil.com" in reason

    def test_allowlisted_host_as_hostname_prefix_does_not_bypass(self):
        # bypass #2: "127.0.0.1" allowlisted, attacker registers 127.0.0.1.evil.com
        self.fp.write_text("network:\n  allowed_domains: [127.0.0.1]\n")
        ok, _ = policy.check_user_url("http://127.0.0.1.evil.com/x")
        assert not ok, "crafted hostname carrying the allowlisted host must not pass"

    def test_exact_and_subdomain_still_allowed(self):
        self.fp.write_text("network:\n  allowed_domains: [example.com]\n")
        assert policy.check_user_url("https://example.com/x")[0]
        assert policy.check_user_url("https://api.example.com/x")[0]
        assert not policy.check_user_url("https://notexample.com/x")[0]  # no suffix trick

    def test_legacy_full_url_manifest_entry_matches_by_host_only(self):
        m = {"name": "t", "capabilities": {"network": {
            "enabled": True, "domains": ["https://api.github.com"]}}}
        assert policy.check_permission(m, "network", "https://api.github.com/repos")[0]
        assert not policy.check_permission(m, "network", "https://evil.com/https://api.github.com")[0]


class TestSecretsDefaultDeny:
    """Regression: an EMPTY capabilities.secrets.allow used to grant EVERY secret
    (default-allow) — the opposite of the documented default-deny."""

    def test_empty_allowlist_denies_every_secret(self):
        m = {"name": "t", "capabilities": {"secrets": {"allow": []}}}
        ok, reason = policy.check_permission(m, "secret", "OPENAI_API_KEY")
        assert not ok
        assert "default-deny" in reason

    def test_missing_secrets_block_denies(self):
        ok, _ = policy.check_permission({"name": "t", "capabilities": {}}, "secret", "ANY")
        assert not ok

    def test_named_secret_allowed_others_denied(self):
        m = {"name": "t", "capabilities": {"secrets": {"allow": ["GH_TOKEN"]}}}
        assert policy.check_permission(m, "secret", "GH_TOKEN")[0]
        assert not policy.check_permission(m, "secret", "OPENAI_API_KEY")[0]
