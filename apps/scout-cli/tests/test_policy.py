"""Decision-matrix tests for the policy engine (findings #13/#14)."""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest
import typer

from bigbang.core import policy


def _manifest(enabled=True, domains=None, fs_write=False, fs_paths=None):
    fs = {"write": fs_write}
    if fs_paths is not None:
        fs["paths"] = fs_paths
    return {
        "name": "t",
        "capabilities": {
            "network": {
                "enabled": enabled,
                "domains": domains if domains is not None else [],
            },
            "filesystem": fs,
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
        ok, _reason = policy.check_permission(_manifest(), "fs_write", "/srv/x")
        assert not ok

    def test_fs_write_true_without_paths_is_not_enough(self):
        # This test used to assert the OPPOSITE — that write:true alone allowed
        # "/srv/x". That was the hole: it encoded "declaring write grants the
        # whole filesystem" as the contract. Now default-deny, like every other
        # axis.
        ok, reason = policy.check_permission(_manifest(fs_write=True), "fs_write", "/srv/x")
        assert not ok
        assert "default-deny" in reason

    def test_fs_write_allowed_inside_declared_path(self):
        ok, _ = policy.check_permission(
            _manifest(fs_write=True, fs_paths=["/srv"]), "fs_write", "/srv/x"
        )
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
    """The call sites in tasks export / rft export / graphify sync rely on these
    manifests granting the paths they actually write. This class used to assert
    `check_permission(mf, "fs_write", "/anywhere")` was ALLOWED for all three —
    literally naming the resource "/anywhere" and passing. It now pins the real
    contract: the declared subtree is granted, everything else is not."""

    # (plugin, a path its call site really writes) — drawn from the manifests'
    # own capabilities.filesystem.paths, not invented for the test.
    GRANTED = (
        ("tasks", "~/.local/share/bigbang/tasks.json"),
        ("rft", "~/.local/share/bigbang/rft/run.jsonl"),
        ("graphify", "~/personal-graphify/out/graph.json"),
    )

    @pytest.mark.parametrize("plugin,target", GRANTED)
    def test_declared_subtree_is_granted(self, plugin, target):
        mf = policy.load_manifest(Path("bigbang/plugins") / plugin)
        ok, reason = policy.check_permission(mf, "fs_write", str(Path(target).expanduser()))
        assert ok, f"{plugin}: {reason}"

    @pytest.mark.parametrize("plugin,_target", GRANTED)
    def test_anywhere_else_is_denied(self, plugin, _target):
        mf = policy.load_manifest(Path("bigbang/plugins") / plugin)
        ok, reason = policy.check_permission(mf, "fs_write", "/anywhere")
        assert not ok, f"{plugin} still grants /anywhere"
        assert "not in allowlist" in reason

    def test_every_write_manifest_declares_paths(self):
        """Whole-fleet invariant. With enforcement live, a manifest that sets
        write:true and forgets `paths` is not lenient any more — it is broken,
        and it breaks at the write, not at load. Catch it here instead."""
        offenders = []
        for mdir in sorted(Path("bigbang/plugins").iterdir()):
            mf = policy.load_manifest(mdir)
            fs = (mf.get("capabilities") or {}).get("filesystem") or {}
            if fs.get("write") is True and not fs.get("paths"):
                offenders.append(mdir.name)
        assert offenders == [], f"write:true with no paths: {offenders}"

    def test_no_manifest_declares_a_template_placeholder(self):
        """reviewgraph shipped `paths: ["<root>/.scout/"]` — the description's
        prose placeholder leaked into the allowlist. Unenforced it was merely
        inert; enforced it denies every write. Nothing may declare a path that
        was never substituted."""
        offenders = []
        for mdir in sorted(Path("bigbang/plugins").iterdir()):
            fs = (policy.load_manifest(mdir).get("capabilities") or {}).get(
                "filesystem"
            ) or {}
            paths = fs.get("paths") or []
            if isinstance(paths, str):
                paths = [paths]
            for p in paths:
                if "<" in str(p) or ">" in str(p):
                    offenders.append(f"{mdir.name}: {p}")
        assert offenders == [], f"unsubstituted placeholder in paths: {offenders}"


class TestDefaultStorePathsStayInsideTheirAllowlist:
    """Where `paths` earns its keep for the 42 operator-redirectable sites.

    Those sites resolve `Path(db or $SCOUT_*_DB or DB_REL)`, so the operator can
    redirect them and the gate must let them (action "fs_write_arg"). What the
    allowlist can still guarantee is that the DEFAULT — the location the plugin
    picks when nobody redirects it — is inside what the manifest advertises.
    That is a manifest/code consistency invariant, and it is checkable here
    instead of at runtime where it would only fire on the unlucky operator.

    This test is not hypothetical: it is the check that found `tasks` declaring
    "~/workspace/bigbang-cli/docs/llm-wiki/" while writing to the resolved repo
    root, and `reviewgraph` declaring the literal "<root>/.scout/"."""

    # Pure path resolvers, named explicitly rather than matched by pattern. A
    # pattern also caught `_ledger`, which OPENS the sqlite file — calling it
    # from a test created .scout/uptime.db as a side effect and then failed on
    # its own (conn, path) tuple. An explicit list cannot pick up a
    # side-effecting function by accident.
    RESOLVERS = (
        "_db_path",
        "_log_path",
        "_links_db",
        "_out_dir",
        "_out_path",
        "_store_path",
    )

    # Measured floor, not a guess: 23 resolvers across the write-capable fleet.
    # The first version of this test keyed on module-level *_REL constants and
    # reached exactly 2 of 47 plugins while its `checked > 0` guard passed
    # happily — DB_REL lives in bigbang/core/<plugin>.py and is referenced
    # module-qualified, so dir(cli) never saw it. A bare "> 0" floor cannot tell
    # 2 from 23; this one can.
    MIN_RESOLVERS = 20

    def test_every_default_store_path_is_inside_its_manifest_allowlist(self, monkeypatch):
        import importlib
        import inspect

        # $SCOUT_*_DB overrides would make this measure the environment
        for key in [k for k in os.environ if k.startswith("SCOUT_")]:
            monkeypatch.delenv(key, raising=False)

        offenders, exercised = [], []
        for mdir in sorted(Path("bigbang/plugins").iterdir()):
            if not (mdir / "manifest.yaml").exists() or not (mdir / "cli.py").exists():
                continue
            mf = policy.load_manifest(mdir)
            fs = (mf.get("capabilities") or {}).get("filesystem") or {}
            if fs.get("write") is not True:
                continue
            try:
                mod = importlib.import_module(f"bigbang.plugins.{mdir.name}.cli")
            except Exception:
                continue  # import-time deps are a different test's problem
            for name in self.RESOLVERS:
                fn = getattr(mod, name, None)
                if not (inspect.isfunction(fn) and fn.__module__ == mod.__name__):
                    continue
                if len(inspect.signature(fn).parameters) != 1:
                    continue
                try:
                    default = fn(None)  # None = "operator did not redirect me"
                except Exception:
                    continue
                if not isinstance(default, (str, Path)):
                    continue
                exercised.append(f"{mdir.name}.{name}")
                ok, reason = policy.check_permission(mf, "fs_write", str(default))
                if not ok:
                    offenders.append(f"{mdir.name}.{name}(None)={default}: {reason}")

        assert len(exercised) >= self.MIN_RESOLVERS, (
            f"only {len(exercised)} resolvers exercised, expected >= "
            f"{self.MIN_RESOLVERS} — the default-path convention moved and this "
            f"test has quietly stopped covering the fleet: {exercised}"
        )
        assert offenders == [], "defaults outside their own allowlist:\n" + "\n".join(
            offenders
        )

    def test_tasks_export_default_is_inside_its_allowlist(self):
        """Named explicitly because `tasks` takes no destination flag, so its
        default is the ONLY path it ever writes — a mismatch here is a hard
        break, not an edge case."""
        from bigbang.plugins.tasks import cli as tasks_cli

        mf = policy.load_manifest(Path("bigbang/plugins/tasks"))
        target = tasks_cli._repo_root() / "docs" / "llm-wiki" / "tasks-default.json"
        ok, reason = policy.check_permission(mf, "fs_write", str(target))
        assert ok, reason

    def test_graphify_sync_destination_is_inside_its_allowlist(self):
        """The other genuinely unredirectable site: dest is built from
        personal_graphify_home() and a fixed basename; --graph selects the
        SOURCE, not the destination."""
        from bigbang.plugins.graphify import runner

        mf = policy.load_manifest(Path("bigbang/plugins/graphify"))
        dest = (
            runner.personal_graphify_home()
            / "references"
            / "spaces"
            / "scout-cli-graph.json"
        )
        ok, reason = policy.check_permission(mf, "fs_write", str(dest))
        assert ok, reason


class TestFsWritePathAllowlist:
    """capabilities.filesystem.paths was declared in 47 of 56 manifests and
    enforced in none of them: write:true granted the entire filesystem, so a
    manifest narrowing itself to [".scout"] held exactly the authority of one
    asking for "/"."""

    def _mf(self, paths):
        return _manifest(fs_write=True, fs_paths=paths)

    def test_file_inside_declared_directory_allowed(self):
        assert policy.check_permission(self._mf([".scout"]), "fs_write", ".scout/x.db")[0]

    def test_declared_directory_itself_allowed(self):
        assert policy.check_permission(self._mf([".scout"]), "fs_write", ".scout")[0]

    def test_nested_descendant_allowed(self):
        ok, _ = policy.check_permission(
            self._mf([".scout"]), "fs_write", ".scout/deep/er/still.json"
        )
        assert ok

    def test_sibling_directory_denied(self):
        ok, reason = policy.check_permission(self._mf([".scout"]), "fs_write", "public/x")
        assert not ok
        assert "not in allowlist" in reason

    def test_prefix_sharing_sibling_does_not_bypass(self):
        """The separator-boundary case. A bare startswith would let a manifest
        scoped to ".scout" write ".scoutevil/" too — the same bypass shape the
        substring domain matcher had (see TestDomainMatchBypasses)."""
        for evil in (".scoutevil/x", ".scout-backup/x", ".scoutter"):
            ok, _ = policy.check_permission(self._mf([".scout"]), "fs_write", evil)
            assert not ok, f"{evil} escaped a .scout-scoped allowlist"

    def test_dotdot_traversal_out_of_declared_dir_denied(self):
        for escape in (
            ".scout/../../../etc/passwd",
            ".scout/../secrets.env",
            ".scout/sub/../../outside",
        ):
            ok, _ = policy.check_permission(self._mf([".scout"]), "fs_write", escape)
            assert not ok, f"{escape} traversed out of the allowlist"

    def test_dotdot_that_stays_inside_is_allowed(self):
        # ".." is collapsed lexically, not banned: a path that walks out and back
        # in is still inside, and denying it would be wrong.
        ok, _ = policy.check_permission(
            self._mf([".scout"]), "fs_write", ".scout/sub/../kept.db"
        )
        assert ok

    def test_exact_file_entry_grants_only_that_file(self):
        mf = self._mf(["~/.local/share/bigbang/auth.json"])
        assert policy.check_permission(
            mf, "fs_write", str(Path("~/.local/share/bigbang/auth.json").expanduser())
        )[0]
        ok, _ = policy.check_permission(
            mf, "fs_write", str(Path("~/.local/share/bigbang/secrets.json").expanduser())
        )
        assert not ok, "a file entry must not grant its whole directory"

    def test_trailing_separator_on_declared_dir_is_equivalent(self):
        # real manifests write both "~/memory/" and ".scout"
        for decl in ("~/memory/", "~/memory"):
            ok, _ = policy.check_permission(
                self._mf([decl]), "fs_write", str(Path("~/memory/notes.md").expanduser())
            )
            assert ok, f"declared {decl!r} should grant ~/memory/notes.md"

    def test_tilde_expands_on_both_sides(self):
        mf = self._mf(["~/memory/"])
        assert policy.check_permission(mf, "fs_write", "~/memory/notes.md")[0]
        assert policy.check_permission(
            mf, "fs_write", str(Path.home() / "memory" / "notes.md")
        )[0]

    def test_relative_and_absolute_forms_of_same_target_agree(self):
        mf = self._mf([".scout"])
        rel = policy.check_permission(mf, "fs_write", ".scout/x.db")[0]
        absolute = policy.check_permission(
            mf, "fs_write", str(Path.cwd() / ".scout" / "x.db")
        )[0]
        assert rel is absolute is True

    def test_case_folding_follows_the_platform(self):
        """Pins the os.path.normcase in _norm_path. Found by mutation: dropping
        normcase left every other test green, so nothing was holding it. It is
        load-bearing on Windows, where ".SCOUT" and ".scout" are the same
        directory and a case-sensitive compare would deny a legitimate write."""
        mf = self._mf([".scout"])
        ok, _ = policy.check_permission(mf, "fs_write", ".SCOUT/X.DB")
        if sys.platform == "win32":
            assert ok, "NTFS is case-insensitive — .SCOUT/X.DB is inside .scout"
        else:
            assert not ok, "POSIX is case-sensitive — .SCOUT is a different directory"

    def test_forward_slashes_normalize(self):
        # manifests are authored with "/" regardless of host OS
        ok, _ = policy.check_permission(
            self._mf(["~/workspace/projects/"]),
            "fs_write",
            str(Path("~/workspace/projects/a/b.txt").expanduser()),
        )
        assert ok

    def test_any_of_several_declared_paths_matches(self):
        mf = self._mf([".scout", "public"])  # sitemap declares exactly this
        assert policy.check_permission(mf, "fs_write", "public/sitemap.xml")[0]
        assert policy.check_permission(mf, "fs_write", ".scout/sitemap.db")[0]
        assert not policy.check_permission(mf, "fs_write", "private/x")[0]

    def test_bare_string_paths_is_coerced_not_iterated_per_character(self):
        # `paths: .scout` is valid YAML; iterating the str would test each
        # CHARACTER and deny everything, which is safe but inexplicable.
        ok, _ = policy.check_permission(self._mf(".scout"), "fs_write", ".scout/x.db")
        assert ok
        assert not policy.check_permission(self._mf(".scout"), "fs_write", "elsewhere/x")[0]

    def test_empty_list_denies_and_says_default_deny(self):
        ok, reason = policy.check_permission(self._mf([]), "fs_write", ".scout/x")
        assert not ok
        assert "default-deny" in reason

    def test_none_paths_denies(self):
        ok, _ = policy.check_permission(self._mf(None), "fs_write", ".scout/x")
        assert not ok

    def test_write_false_still_denies_before_paths_are_consulted(self):
        # ordering matters: the write flag is the outer gate, so a manifest with
        # a generous paths list but write:false must still be denied on the flag
        ok, reason = policy.check_permission(
            _manifest(fs_write=False, fs_paths=["/"]), "fs_write", "/etc/passwd"
        )
        assert not ok
        assert "disabled" in reason

    def test_reason_names_the_offending_path_and_the_allowlist(self):
        ok, reason = policy.check_permission(self._mf([".scout"]), "fs_write", "/etc/passwd")
        assert not ok
        assert "/etc/passwd" in reason and ".scout" in reason

    def test_enforce_or_raise_exits_on_path_denial(self):
        with pytest.raises(typer.Exit):
            policy.enforce_or_raise(self._mf([".scout"]), "fs_write", "/etc/passwd")

    def test_non_dict_filesystem_block_denies_without_crashing(self):
        mf = {"name": "t", "capabilities": {"filesystem": None}}
        ok, _ = policy.check_permission(mf, "fs_write", ".scout/x")
        assert not ok


class TestUngatedWriteCapablePluginsAreTracked:
    """The hole enforcement does NOT close, pinned so it cannot grow in silence.

    These plugins declare `write: true` and never call the gate on any filesystem
    action, so their `capabilities.filesystem.paths` is documentation rather than
    a bound. Enforcing check_permission cannot fix that — the gate has to be
    *invoked* — and the list is the inverse of reassuring: `auth` writes
    auth.json/secrets.json, `secrets` writes ~/.local/share/bigbang/, `brain`
    writes ~/MEMORY.md and ~/memory/, `skill` writes ~/.claude/skills/.

    Counted with ast, not grep. A grep for "enforce_or_raise" reports `quality`
    and `tools` as gated and gives 14: quality mentions it only in prose ("The
    inverse of an enforce_or_raise call site") and tools imports it but only ever
    calls it with "network". Neither gates a write. The real number is 16."""

    # 16 on 2026-07-25, 15 on 2026-07-28: `auth` now gates in `_save_auth`, the one
    # choke point its seven call sites share. This list shrinking is the only
    # measure of progress on that axis, so it is edited only alongside a real gate.
    KNOWN_UNGATED = frozenset(
        {
            "ava", "brain", "dev_loop", "herd", "lab", "mcp", "quality",
            "reviewgraph", "rtx", "secrets", "skill", "system", "tennis",
            "tools", "write",
        }
    )

    def _ungated(self):
        fs_actions = set(policy.FS_WRITE_ACTIONS)
        out = set()
        for mdir in sorted(Path("bigbang/plugins").iterdir()):
            if not (mdir / "manifest.yaml").exists():
                continue
            fs = (policy.load_manifest(mdir).get("capabilities") or {}).get(
                "filesystem"
            ) or {}
            if fs.get("write") is not True:
                continue
            gated = False
            for f in mdir.rglob("*.py"):
                if "__pycache__" in f.parts:
                    continue
                try:
                    tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
                except Exception:
                    continue
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call) or len(node.args) < 2:
                        continue
                    fn = node.func
                    name = (
                        fn.attr
                        if isinstance(fn, ast.Attribute)
                        else getattr(fn, "id", "")
                    )
                    if name not in ("enforce_or_raise", "check_permission"):
                        continue
                    arg = node.args[1]
                    if isinstance(arg, ast.Constant) and arg.value in fs_actions:
                        gated = True
            if not gated:
                out.add(mdir.name)
        return out

    def test_no_new_plugin_joins_the_ungated_set(self):
        new = self._ungated() - self.KNOWN_UNGATED
        assert new == set(), (
            f"new write-capable plugin(s) with NO fs_write gate: {sorted(new)} — "
            "call enforce_or_raise at the write, or add it here deliberately"
        )

    def test_plugins_that_got_gated_are_removed_from_the_list(self):
        """Guards the other direction, so the list stays honest as gates land."""
        stale = self.KNOWN_UNGATED - self._ungated()
        assert stale == set(), (
            f"{sorted(stale)} now gate their writes — delete them from "
            "KNOWN_UNGATED so the remaining count stays truthful"
        )

    def test_the_gated_majority_is_still_the_majority(self):
        """Floor guard: if the walker breaks, both tests above pass vacuously
        (empty set minus anything is empty)."""
        write_capable = [
            m.name
            for m in sorted(Path("bigbang/plugins").iterdir())
            if (m / "manifest.yaml").exists()
            and ((policy.load_manifest(m).get("capabilities") or {}).get("filesystem")
                 or {}).get("write") is True
        ]
        assert len(write_capable) >= 45, f"only {len(write_capable)} write-capable found"
        assert len(self._ungated()) < len(write_capable), "walker found nothing gated"


class TestFsWriteArgAction:
    """`fs_write_arg` is for destinations the OPERATOR named on the command line.
    It checks the write flag and stops: no allowlist can enumerate every
    directory an operator might legitimately pick, and enforcing `paths` there
    denied `statuspage render --out /var/www/status.html` outright."""

    def test_operator_named_path_outside_allowlist_is_allowed(self):
        mf = _manifest(fs_write=True, fs_paths=[".scout"])
        assert policy.check_permission(mf, "fs_write_arg", "/var/www/status.html")[0]
        # ...and the same path on the plugin-chosen axis is still refused
        assert not policy.check_permission(mf, "fs_write", "/var/www/status.html")[0]

    def test_write_flag_is_still_required(self):
        # the operator may name a destination; they may not thereby grant a
        # plugin a write capability its manifest never claimed
        ok, reason = policy.check_permission(
            _manifest(fs_write=False, fs_paths=["/"]), "fs_write_arg", "/srv/x"
        )
        assert not ok
        assert "disabled" in reason

    def test_empty_paths_does_not_block_an_operator_named_path(self):
        # unlike fs_write, an empty/absent allowlist is irrelevant here
        assert policy.check_permission(
            _manifest(fs_write=True), "fs_write_arg", "/srv/x"
        )[0]

    def test_both_actions_are_declared_in_fs_write_actions(self):
        assert policy.FS_WRITE_ACTIONS == ("fs_write", "fs_write_arg")


class TestRelativeEntriesAnchoredByBase:
    """`base` exists for the plugins that write under a root discovered at
    runtime: tasks resolves _repo_root() by walking up from __file__ for
    pyproject.toml, reviewgraph takes --root. Without it, a relative declared
    entry anchors to the process CWD, which diverges from that root whenever the
    command is invoked from anywhere but the checkout — and tasks' own test
    monkeypatches _repo_root to a temp dir, so the divergence is not theoretical."""

    def test_base_anchors_a_relative_entry(self, tmp_path):
        mf = _manifest(fs_write=True, fs_paths=["docs/llm-wiki"])
        target = tmp_path / "docs" / "llm-wiki" / "tasks-@default.json"
        ok, reason = policy.check_permission(
            mf, "fs_write", str(target), base=str(tmp_path)
        )
        assert ok, reason

    def test_without_base_the_same_target_is_denied(self, tmp_path):
        """Makes `base` load-bearing rather than decorative — if this passed too,
        the parameter would be doing nothing."""
        mf = _manifest(fs_write=True, fs_paths=["docs/llm-wiki"])
        target = tmp_path / "docs" / "llm-wiki" / "tasks-@default.json"
        ok, _ = policy.check_permission(mf, "fs_write", str(target))
        assert not ok, "relative entry must anchor to CWD when no base is given"

    def test_base_does_not_widen_beyond_the_declared_entry(self, tmp_path):
        # a sibling of the declared dir under the SAME base is still refused
        mf = _manifest(fs_write=True, fs_paths=["docs/llm-wiki"])
        ok, _ = policy.check_permission(
            mf, "fs_write", str(tmp_path / "docs" / "secrets.env"), base=str(tmp_path)
        )
        assert not ok

    def test_traversal_out_of_a_based_entry_is_denied(self, tmp_path):
        mf = _manifest(fs_write=True, fs_paths=["docs/llm-wiki"])
        escape = str(tmp_path / "docs" / "llm-wiki" / ".." / ".." / ".ssh" / "id_rsa")
        ok, _ = policy.check_permission(mf, "fs_write", escape, base=str(tmp_path))
        assert not ok

    def test_absolute_and_tilde_entries_ignore_base(self, tmp_path):
        # base must not relocate an entry that already names an absolute location
        mf = _manifest(fs_write=True, fs_paths=["~/.local/share/bigbang/"])
        assert policy.check_permission(
            mf,
            "fs_write",
            str(Path("~/.local/share/bigbang/x.json").expanduser()),
            base=str(tmp_path),
        )[0]
        ok, _ = policy.check_permission(
            mf,
            "fs_write",
            str(tmp_path / ".local" / "share" / "bigbang" / "x.json"),
            base=str(tmp_path),
        )
        assert not ok, "base must not re-root an absolute/~ entry"

    def test_base_is_ignored_by_the_operator_named_action(self, tmp_path):
        # fs_write_arg never consults paths, so base is irrelevant there
        mf = _manifest(fs_write=True, fs_paths=["docs/llm-wiki"])
        assert policy.check_permission(
            mf, "fs_write_arg", "/var/www/out.html", base=str(tmp_path)
        )[0]

    def test_enforce_or_raise_forwards_base(self, tmp_path):
        mf = _manifest(fs_write=True, fs_paths=["docs/llm-wiki"])
        target = str(tmp_path / "docs" / "llm-wiki" / "x.json")
        # forwarded -> allowed, so no Exit
        policy.enforce_or_raise(mf, "fs_write", target, base=str(tmp_path))
        # not forwarded -> denied, so Exit. If enforce_or_raise dropped `base`,
        # the first call would have raised and this test would fail loudly.
        with pytest.raises(typer.Exit):
            policy.enforce_or_raise(mf, "fs_write", target)

    def test_tasks_export_call_site_passes_a_base(self):
        """Pins the wiring, not just the primitive: tasks/cli.py must forward the
        root it resolved, or the manifest's relative entry silently anchors to
        CWD again."""
        src = Path("bigbang/plugins/tasks/cli.py").read_text(encoding="utf-8")
        assert "base=str(root)" in src, (
            "tasks export must pass base=<resolved repo root> to enforce_or_raise"
        )


class TestUnknownActionFailsClosed:
    """Every branch in check_permission is `if action == ...`, so before this
    guard an unrecognized action fell through to `return True, "ok"` — a typo'd
    action name silently granted the thing it looked like it was gating."""

    def test_typo_action_denies(self):
        wide_open = {
            "name": "t",
            "capabilities": {
                "filesystem": {"write": True, "paths": [".scout"]},
                "network": {"enabled": True, "domains": ["example.com"]},
                "secrets": {"allow": ["GH_TOKEN"]},
            },
        }
        for typo in ("fs_wrile", "fs-write", "FS_WRITE", "write", "filesystem", ""):
            ok, reason = policy.check_permission(wide_open, typo, "/etc/passwd")
            assert not ok, f"action {typo!r} fell through to allow"
            assert "unknown policy action" in reason

    def test_enforce_or_raise_exits_on_unknown_action(self):
        with pytest.raises(typer.Exit):
            policy.enforce_or_raise(_manifest(fs_write=True), "fs_wrile", "/etc/passwd")

    def test_all_four_known_actions_are_recognized(self):
        # the inverse guard: a real action must NOT be rejected as unknown
        mf = {
            "name": "t",
            "capabilities": {
                "filesystem": {"write": True, "paths": ["/srv"]},
                "network": {"enabled": True, "domains": ["example.com"]},
                "secrets": {"allow": ["GH_TOKEN"]},
            },
        }
        for action, res in [
            ("network", "https://example.com/x"),
            ("fs_write", "/srv/x"),
            ("fs_write_arg", "/anywhere/x"),
            ("secret", "GH_TOKEN"),
        ]:
            ok, reason = policy.check_permission(mf, action, res)
            assert ok, f"{action}: {reason}"

    def test_known_actions_matches_what_the_tree_actually_passes(self):
        """Drift guard. Every action literal handed to the gate anywhere in
        bigbang/ must be one KNOWN_ACTIONS recognizes, or that call site is now
        failing closed in production and no test would say so.

        Uses ast, not a regex: the first cut regexed the raw file text and
        flagged 'fs_wrile' from the illustrative `enforce_or_raise(mf,
        "fs_wrile", path)` inside policy.py's own COMMENT. A grep cannot tell
        code from prose about code; the parser can."""
        used = set()
        for f in sorted(Path("bigbang").rglob("*.py")):
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or len(node.args) < 2:
                    continue
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name not in ("enforce_or_raise", "check_permission"):
                    continue
                arg = node.args[1]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    used.add(arg.value)
        assert used, "found no gate call sites at all — the walker is broken"
        unknown = used - set(policy.KNOWN_ACTIONS)
        assert unknown == set(), f"call sites use unknown actions: {unknown}"


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


def _make_dir_link(link: Path, target: Path) -> str:
    """Create a directory link, returning the mechanism used or "" if impossible.

    Path.symlink_to needs SeCreateSymbolicLinkPrivilege on Windows (admin or developer
    mode) and raises WinError 1314 without it — measured on this box. A directory
    JUNCTION needs no privilege and os.path.realpath resolves it the same way, so
    it reproduces the escape faithfully.
    """
    try:
        link.symlink_to(target, target_is_directory=True)
        return "symlink"
    except (OSError, NotImplementedError, AttributeError):
        pass
    if sys.platform == "win32":
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, text=True, check=False,
        )
        if proc.returncode == 0 and link.exists():
            return "junction"
    return ""


class TestSymlinkEscape:
    """A symlink inside an allowed directory must not grant what it points at.

    This was a stated KNOWN GAP, left open because blocking it supposedly "needs
    realpath on an existing tree, which the not-yet-created-write case rules out".
    That reason was wrong: os.path.realpath is not strict, so it resolves the
    existing prefix and leaves the rest alone. These tests pin both the fix and
    the fact that the lexical check alone would have let it through.
    """

    def _escape_setup(self, tmp_path):
        allowed = tmp_path / "allowed"
        outside = tmp_path / "outside"
        allowed.mkdir()
        outside.mkdir()
        mech = _make_dir_link(allowed / "escape", outside)
        if not mech:
            pytest.skip("no symlink privilege and no junction support on this platform")
        return allowed, outside, mech

    def test_a_link_out_of_an_allowed_dir_is_denied(self, tmp_path):
        allowed, _outside, _mech = self._escape_setup(tmp_path)
        target = allowed / "escape" / "stolen.txt"
        mf = _manifest(fs_write=True, fs_paths=[str(allowed)])
        ok, reason = policy.check_permission(mf, "fs_write", str(target))
        assert not ok, f"a link escaping {allowed} was allowed: {reason}"

    def test_the_lexical_check_alone_would_have_allowed_it(self, tmp_path):
        """Anti-vacuity, and the whole point. If the string comparison already
        rejected this, the new filesystem gate would be untested decoration and
        the test above would pass for the wrong reason."""
        allowed, _outside, _mech = self._escape_setup(tmp_path)
        target = allowed / "escape" / "stolen.txt"
        root = policy._norm_path(str(allowed))
        lexical = policy._norm_path(str(target))
        assert lexical.startswith(root.rstrip(os.sep) + os.sep), (
            "the lexical prefix check no longer admits this path, so it is not "
            "the symlink gate that denies it — this test proves nothing as written"
        )
        assert not policy._resolves_within(root, lexical)

    def test_the_link_really_points_outside(self, tmp_path):
        """Guards the FIXTURE, not the code: if mklink silently produced a real
        directory instead of a link, every test here would pass vacuously."""
        allowed, outside, _mech = self._escape_setup(tmp_path)
        resolved = Path(os.path.realpath(str(allowed / "escape" / "stolen.txt")))
        assert resolved.parent == Path(os.path.realpath(str(outside)))

    def test_an_ordinary_write_inside_the_allowed_dir_is_still_allowed(self, tmp_path):
        """No-regression: the gate must not deny the normal case it exists to permit."""
        allowed, _outside, _mech = self._escape_setup(tmp_path)
        mf = _manifest(fs_write=True, fs_paths=[str(allowed)])
        ok, reason = policy.check_permission(
            mf, "fs_write", str(allowed / "sub" / "ok.txt")
        )
        assert ok, reason

    def test_a_linked_root_is_still_allowed(self, tmp_path):
        """Both sides are resolved, so an allowed directory that is ITSELF a link
        keeps working — a symlinked /tmp or a redirected data dir must not become
        undeclarable. Denying this would be the obvious way to get the fix wrong."""
        real = tmp_path / "real_store"
        real.mkdir()
        linked = tmp_path / "declared_store"
        if not _make_dir_link(linked, real):
            pytest.skip("no symlink privilege and no junction support on this platform")
        mf = _manifest(fs_write=True, fs_paths=[str(linked)])
        ok, reason = policy.check_permission(mf, "fs_write", str(linked / "db.sqlite"))
        assert ok, reason

    def test_paths_that_do_not_exist_are_unaffected(self, tmp_path):
        """The check is a no-op where there is nothing to resolve, which is what
        makes it safe for the not-yet-created write that supposedly ruled it out."""
        allowed = tmp_path / "never_created"
        mf = _manifest(fs_write=True, fs_paths=[str(allowed)])
        assert not allowed.exists()
        ok, reason = policy.check_permission(mf, "fs_write", str(allowed / "new.txt"))
        assert ok, reason
        ok2, _ = policy.check_permission(mf, "fs_write", str(tmp_path / "elsewhere.txt"))
        assert not ok2
