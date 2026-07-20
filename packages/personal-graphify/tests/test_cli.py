# Solo personal project, no connection to employer, built with public/free-tier only
"""CLI wiring: build --cluster passthrough, hook install/uninstall round-trip,
install --platform/--project branches, live graph stats interpolation."""

import json
import sys

import personal_graphify.cli as cli


def _run_cli(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["pgraphify"] + argv)
    cli.main()


def _mini_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (repo / "b.py").write_text(
        "from a import f\n\ndef g():\n    return f()\n", encoding="utf-8"
    )
    return repo


class TestBuildClusterFlag:
    def test_cluster_method_passes_through(self, tmp_path, monkeypatch):
        seen = {}

        def spy(G, method="auto"):
            seen["method"] = method
            for nid in G.nodes:
                G.nodes[nid]["community"] = 0
            return G

        monkeypatch.setattr(cli, "assign_communities", spy)
        repo = _mini_repo(tmp_path)
        out = tmp_path / "out"
        _run_cli(
            monkeypatch,
            ["build", str(repo), "--out", str(out), "--cluster", "spectral"],
        )
        assert seen["method"] == "spectral"
        assert (out / "graph.json").exists()

    def test_cluster_defaults_to_auto(self, tmp_path, monkeypatch):
        seen = {}

        def spy(G, method="auto"):
            seen["method"] = method
            for nid in G.nodes:
                G.nodes[nid]["community"] = 0
            return G

        monkeypatch.setattr(cli, "assign_communities", spy)
        repo = _mini_repo(tmp_path)
        _run_cli(monkeypatch, ["build", str(repo), "--out", str(tmp_path / "out2")])
        assert seen["method"] == "auto"


class TestHookRoundTrip:
    def test_install_then_uninstall_removes_our_hooks(self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        _run_cli(monkeypatch, ["hook", "install", str(repo)])
        post_commit = repo / ".git" / "hooks" / "post-commit"
        post_merge = repo / ".git" / "hooks" / "post-merge"
        assert post_commit.exists() and post_merge.exists()
        assert "Personal Graphify" in post_commit.read_text()

        _run_cli(monkeypatch, ["hook", "uninstall", str(repo)])
        assert not post_commit.exists()
        assert not post_merge.exists()

    def test_uninstall_preserves_preexisting_hook_prefix(self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        hooks = repo / ".git" / "hooks"
        hooks.mkdir(parents=True)
        original = "#!/bin/sh\necho my own hook\n"
        (hooks / "post-commit").write_text(original)

        _run_cli(monkeypatch, ["hook", "install", str(repo)])
        combined = (hooks / "post-commit").read_text()
        assert "echo my own hook" in combined
        assert "# --- Personal Graphify (appended) ---" in combined

        _run_cli(monkeypatch, ["hook", "uninstall", str(repo)])
        after = (hooks / "post-commit").read_text()
        assert after == original
        assert "graphify" not in after.lower()

    def test_uninstall_leaves_foreign_hook_untouched(self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        hooks = repo / ".git" / "hooks"
        hooks.mkdir(parents=True)
        foreign = "#!/bin/sh\nlint-staged\n"
        (hooks / "post-commit").write_text(foreign)
        _run_cli(monkeypatch, ["hook", "uninstall", str(repo)])
        assert (hooks / "post-commit").read_text() == foreign


class TestInstallPlatforms:
    CURSOR = ".cursor/rules/graphify.mdc"
    AGENTS = ".agents/skills/graphify/SKILL.md"

    def test_platform_cursor_only(self, tmp_path, monkeypatch):
        root = tmp_path / "proj"
        root.mkdir()
        _run_cli(monkeypatch, ["install", "--platform", "cursor", str(root)])
        assert (root / self.CURSOR).exists()
        assert not (root / self.AGENTS).exists()

    def test_platform_agents_only(self, tmp_path, monkeypatch):
        root = tmp_path / "proj"
        root.mkdir()
        _run_cli(monkeypatch, ["install", "--platform", "agents", str(root)])
        assert not (root / self.CURSOR).exists()
        assert (root / self.AGENTS).exists()

    def test_platform_all_writes_both(self, tmp_path, monkeypatch):
        root = tmp_path / "proj"
        root.mkdir()
        _run_cli(monkeypatch, ["install", str(root)])
        assert (root / self.CURSOR).exists()
        assert (root / self.AGENTS).exists()

    def test_project_flag_resolves_git_root(self, tmp_path, monkeypatch):
        root = tmp_path / "proj"
        sub = root / "pkg" / "inner"
        sub.mkdir(parents=True)
        (root / ".git").mkdir()
        _run_cli(monkeypatch, ["install", "--project", str(sub)])
        assert (root / self.CURSOR).exists()
        assert not (sub / ".cursor").exists()

    def test_live_stats_interpolated_when_graph_exists(self, tmp_path, monkeypatch):
        root = tmp_path / "proj"
        (root / "graphify-out").mkdir(parents=True)
        (root / "graphify-out" / "graph.json").write_text(
            json.dumps({"nodes": [], "edges": [], "meta": {"nodes": 42, "edges": 99}})
        )
        _run_cli(monkeypatch, ["install", str(root)])
        content = (root / self.CURSOR).read_text()
        assert "42 nodes 99 edges (live at install)" in content
        assert "{{GRAPH_STATS}}" not in content

    def test_no_graph_omits_numbers(self, tmp_path, monkeypatch):
        root = tmp_path / "proj"
        root.mkdir()
        _run_cli(monkeypatch, ["install", str(root)])
        content = (root / self.CURSOR).read_text()
        assert "{{GRAPH_STATS}}" not in content
        assert "464 nodes" not in content  # old stale hardcoded count
        assert (
            "nodes" not in content.splitlines()[8]
        )  # intro line carries no fabricated count
