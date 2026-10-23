"""Critic re-attack suite for dottie#91 @ 136f7e36addc1be3b39afe1d4b97e541835ece91.

Every test asserts the SECURE behaviour. A FAIL is a finding.
Part C: real guard block (extracted from WT ci.yml via Forge's loader) run with bash -e
        against temp repos that meet the 1280 floor + ci.yml, GITHUB_SHA pinned to HEAD.
Part D: workflow mutations; passes when Forge's TrackedPackArtifactGuardTests go RED.
Run:  WT=/workspace/review/dottie-91/wt-136f python3 -m unittest -v test_critic_91_136f
Read-only w.r.t. GitHub; Part D rewrites WT ci.yml / adds files and restores them.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Original Critic drop sha256 5bf36a2c791a9bde61e239ec4652ac32ae4c4d51cf483088a48846fe88724dd6
WT = Path(os.environ.get("WT", str(Path(__file__).resolve().parents[3])))
CI = WT / ".github" / "workflows" / "ci.yml"
ORIG = CI.read_text(encoding="utf-8")
FLOOR = 1280
PACK = "apps/x/curated_pack_v2.jsonl"
BASE_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def guard_block() -> str:
    sys.path.insert(0, str(WT / "apps/dottie-os/tests"))
    sys.modules.setdefault("yaml", None)  # type: ignore[arg-type]
    import test_ultradata_factory as T  # noqa: E402
    return str(T._load_pack_guard_step(ORIG)["run"])


GUARD = guard_block()


def genv(extra=None):
    e = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "GITHUB_SHA"}
    e.update(BASE_ENV)
    e.update(extra or {})
    return e


def git(repo, *a, check=True, env=None, inp=None):
    return subprocess.run(["git", *a], cwd=repo, check=check, env=env or genv(),
                          capture_output=True, input=inp)


def mkrepo(tmp: Path, names: list, floor: int = FLOOR - 1, name="r") -> Path:
    """names: str or bytes paths (bytes allow invalid UTF-8)."""
    repo = tmp / name
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    ci = repo / ".github/workflows/ci.yml"
    ci.parent.mkdir(parents=True)
    ci.write_text("name: CI\n")
    fl = repo / "_floor"
    fl.mkdir()
    for i in range(floor):
        (fl / f"{i:04d}").write_text(".\n")
    for n in names:
        b = n if isinstance(n, bytes) else n.encode()
        p = os.path.join(bytes(repo), b)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b"{}\n")
    git(repo, "add", "-f", "-A")
    git(repo, "commit", "-qm", "x")
    return repo


def head(repo) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.decode().strip()


def run_guard(repo, extra_env=None, pre="", sha=None):
    env = genv(extra_env)
    env["GITHUB_SHA"] = sha if sha is not None else head(repo)
    script = (pre + "\n" if pre else "") + GUARD
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
        f.write(script)
    r = subprocess.run(["bash", "-e", f.name], cwd=repo, env=env, capture_output=True, text=True)
    os.unlink(f.name)
    return r.returncode


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class C0_Controls(Base):
    def test_clean_repo_passes(self):
        self.assertEqual(run_guard(mkrepo(self.tmp, ["README"])), 0)

    def test_plain_pack_trips(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, [PACK])), 0)


class C1_ShaValidation(Base):
    def test_tree_sha_refused(self):
        r = mkrepo(self.tmp, ["README"])
        self.assertNotEqual(run_guard(r, sha=git(r, "rev-parse", "HEAD^{tree}").stdout.decode().strip()), 0)

    def test_blob_sha_refused(self):
        r = mkrepo(self.tmp, ["README"])
        self.assertNotEqual(run_guard(r, sha=git(r, "rev-parse", "HEAD:README").stdout.decode().strip()), 0)

    def test_uppercase_sha_still_trips_on_pack(self):
        r = mkrepo(self.tmp, [PACK])
        self.assertNotEqual(run_guard(r, sha=head(r).upper()), 0)

    def test_annotated_tag_sha_refused(self):
        # cat-file -e X^{commit} peels tags; cat-file -t X must equal commit.
        r = mkrepo(self.tmp, ["README"])
        git(r, "tag", "-a", "-m", "t", "t1")
        tag = git(r, "rev-parse", "t1").stdout.decode().strip()
        self.assertNotEqual(run_guard(r, sha=tag), 0)

    def test_github_sha_must_equal_head(self):
        # HEAD tracks a pack, index hollowed, GITHUB_SHA = clean parent -> must fail.
        r = mkrepo(self.tmp, ["README"])
        parent = head(r)
        (r / "apps/x").mkdir(parents=True)
        (r / PACK).write_text("{}\n")
        git(r, "add", "-f", PACK)
        git(r, "commit", "-qm", "pack")
        self.assertNotEqual(run_guard(r, pre=f"git rm -q --cached {PACK}", sha=parent), 0)


class C2_EarlierStepHollowing(Base):
    """What PR-controlled code in the earlier unittest step of the same job can do."""

    def _clean_tree(self, r):
        git(r, "rm", "-q", "--cached", PACK)
        t = git(r, "write-tree").stdout.decode().strip()
        git(r, "reset", "-q")
        return t

    def test_replace_ref_hollows_both_lists(self):
        r = mkrepo(self.tmp, [PACK])
        t = self._clean_tree(r)
        git(r, "replace", git(r, "rev-parse", "HEAD^{tree}").stdout.decode().strip(), t)
        git(r, "rm", "-q", "--cached", PACK)  # index side
        self.assertNotEqual(run_guard(r), 0, "refs/replace hides pack from ls-tree GITHUB_SHA")

    def test_replace_ref_base_env_not_stripped(self):
        r = mkrepo(self.tmp, [PACK])
        t = self._clean_tree(r)
        src = git(r, "rev-parse", "HEAD^{tree}").stdout.decode().strip()
        git(r, "update-ref", f"refs/hide/{src}", t)
        git(r, "rm", "-q", "--cached", PACK)
        self.assertNotEqual(run_guard(r, extra_env={"GIT_REPLACE_REF_BASE": "refs/hide/"}), 0)

    def _shim_dir(self):
        d = self.tmp / "shim"
        d.mkdir()
        (d / "grep").write_text('#!/bin/sh\ncase "$*" in *-zEi*) exit 1;; esac\nexec /usr/bin/grep "$@"\n')
        (d / "grep").chmod(0o755)
        return d

    def test_github_path_grep_shim(self):
        r = mkrepo(self.tmp, [PACK])
        d = self._shim_dir()
        self.assertNotEqual(run_guard(r, extra_env={"PATH": f"{d}:{os.environ['PATH']}"}), 0)

    def test_bash_env_grep_function_shadow(self):
        r = mkrepo(self.tmp, [PACK])
        b = self.tmp / "b.sh"
        b.write_text('grep(){ case "$*" in *-zEi*) return 1;; esac; command grep "$@"; }\n')
        self.assertNotEqual(run_guard(r, extra_env={"BASH_ENV": str(b)}), 0)

    def test_grep_rc2_is_not_a_pass(self):
        r = mkrepo(self.tmp, [PACK])
        d = self.tmp / "shim2"
        d.mkdir()
        (d / "grep").write_text('#!/bin/sh\ncase "$*" in *-zEi*) exit 2;; esac\nexec /usr/bin/grep "$@"\n')
        (d / "grep").chmod(0o755)
        self.assertNotEqual(run_guard(r, extra_env={"PATH": f"{d}:{os.environ['PATH']}"}), 0)

    def test_repo_local_fsmonitor_does_not_run(self):
        r = mkrepo(self.tmp, ["README"])
        mark = self.tmp / "ran"
        hook = self.tmp / "fsm.sh"
        hook.write_text(f"#!/bin/sh\ntouch {mark}\n")
        hook.chmod(0o755)
        git(r, "config", "core.fsmonitor", str(hook))
        run_guard(r)
        self.assertFalse(mark.exists(), ".git/config core.fsmonitor executed inside guard")

    def test_git_config_count_fsmonitor_does_not_run(self):
        r = mkrepo(self.tmp, ["README"])
        mark = self.tmp / "ran2"
        hook = self.tmp / "fsm2.sh"
        hook.write_text(f"#!/bin/sh\ntouch {mark}\n")
        hook.chmod(0o755)
        run_guard(r, extra_env={"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.fsmonitor",
                                "GIT_CONFIG_VALUE_0": str(hook)})
        self.assertFalse(mark.exists(), "GIT_CONFIG_COUNT not stripped")

    def test_home_gitconfig_disables_nothing(self):
        # HOME is kept; a global config enabling a replace base via include must not matter.
        r = mkrepo(self.tmp, [PACK])
        t = self._clean_tree(r)
        git(r, "replace", git(r, "rev-parse", "HEAD^{tree}").stdout.decode().strip(), t)
        git(r, "rm", "-q", "--cached", PACK)
        # GIT_NO_REPLACE_OBJECTS would be the defence; check the guard sets it itself.
        self.assertIn("no-replace-objects", GUARD.replace("GIT_NO_REPLACE_OBJECTS", "no-replace-objects").lower())

    # controls that should (and do) still trip
    def test_assume_unchanged_still_trips(self):
        r = mkrepo(self.tmp, [PACK])
        git(r, "update-index", "--assume-unchanged", PACK)
        self.assertNotEqual(run_guard(r), 0)

    def test_skip_worktree_still_trips(self):
        r = mkrepo(self.tmp, [PACK])
        git(r, "update-index", "--skip-worktree", PACK)
        self.assertNotEqual(run_guard(r), 0)

    def test_sparse_checkout_cone_still_trips(self):
        r = mkrepo(self.tmp, [PACK])
        git(r, "sparse-checkout", "set", "--cone", "_floor")
        self.assertNotEqual(run_guard(r), 0)

    def test_export_ignore_still_trips(self):
        r = mkrepo(self.tmp, [PACK])
        (r / ".gitattributes").write_text("*.jsonl export-ignore\n")
        self.assertNotEqual(run_guard(r), 0)

    def test_safe_directory_unset_fails_closed_not_open(self):
        r = mkrepo(self.tmp, [PACK])
        self.assertNotEqual(run_guard(r, extra_env={"GIT_CEILING_DIRECTORIES": str(self.tmp)}), 0)


class C3_Names(Base):
    def _trips(self, name):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, [name])), 0, repr(name))

    # inside the curated_pack_*.json[l] contract
    def test_invalid_utf8_byte_in_name(self):
        self._trips(b"apps/x/curated_pack_\xff.jsonl")

    def test_trailing_newline_after_ext(self):
        self._trips("apps/x/curated_pack_v2.jsonl\n")

    def test_directory_named_like_pack(self):
        self._trips("apps/x/curated_pack_v2.jsonl/part-0000")

    def test_uppercase_ext(self):
        self._trips("apps/x/CURATED_PACK_v2.JSONL")

    def test_gitlink_named_pack(self):
        r = mkrepo(self.tmp, ["README"])
        git(r, "update-index", "--add", "--cacheinfo", f"160000,{head(r)},apps/x/curated_pack_v2.jsonl")
        git(r, "commit", "-qm", "gl")
        self.assertNotEqual(run_guard(r), 0)

    def test_symlink_named_pack(self):
        r = mkrepo(self.tmp, ["README"])
        (r / "apps/x").mkdir(parents=True)
        os.symlink("/tmp/real.jsonl", r / PACK)
        git(r, "add", "-f", PACK)
        git(r, "commit", "-qm", "ln")
        self.assertNotEqual(run_guard(r), 0)

    def test_lfs_pointer_named_pack(self):
        r = mkrepo(self.tmp, ["README"])
        (r / "apps/x").mkdir(parents=True)
        (r / PACK).write_text("version https://git-lfs.github.com/spec/v1\noid sha256:" + "0" * 64 + "\nsize 9\n")
        git(r, "add", "-f", PACK)
        git(r, "commit", "-qm", "lfs")
        self.assertNotEqual(run_guard(r), 0)

    # outside the literal contract: rename / compression / lookalikes
    def test_compressed_jsonl_gz(self):
        self._trips("apps/x/curated_pack_v2.jsonl.gz")

    def test_compressed_jsonl_zst(self):
        self._trips("apps/x/curated_pack_v2.jsonl.zst")

    def test_cyrillic_a_lookalike(self):
        self._trips("apps/x/curated_p\u0430ck_v2.jsonl")

    def test_zero_width_joiner(self):
        self._trips("apps/x/curated\u200b_pack_v2.jsonl")

    def test_fullwidth_ext(self):
        self._trips("apps/x/curated_pack_v2.\uff4a\uff53\uff4f\uff4e\uff4c")


class C4_Floor(Base):
    def test_floor_is_hardcoded_constant(self):
        # Documented: fails closed if repo shrinks below 1280, never stale-open. Junk padding
        # cannot hide a pack (floor only detects hollow lists). Assert both.
        self.assertIn("PACK_GUARD_LS_FILES_FLOOR=1280", GUARD)
        r = mkrepo(self.tmp, [PACK], floor=5000)
        self.assertNotEqual(run_guard(r), 0)

    def test_below_floor_fails_closed(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, ["README"], floor=10)), 0)


# ---------------- Part D: workflow mutations vs Forge's own tests ----------------
RUNNER = r"""
import sys, unittest
sys.modules['yaml'] = None
sys.path.insert(0, 'apps/dottie-os/tests')
import test_ultradata_factory as T
s = unittest.defaultTestLoader.loadTestsFromTestCase(T.TrackedPackArtifactGuardTests)
r = unittest.TextTestRunner(verbosity=0, stream=open('/dev/null', 'w')).run(s)
print('GREEN' if r.wasSuccessful() else 'RED')
"""
ON = "on:\n  push:\n    branches: [main]\n  pull_request:\n    branches: [main]\n"
SETUP = "        uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065\n"
STEP = "      - name: Refuse tracked pack artifacts\n        run: |\n"
PACK_JOB = "  pack-guard:\n    runs-on: ubuntu-latest\n"
SHELL = '        shell: "/usr/bin/bash --noprofile --norc -p -euo pipefail {0}"\n'
CHECKOUT_WITH = "          persist-credentials: false\n"
assert ON in ORIG and SETUP in ORIG and STEP in ORIG
assert PACK_JOB in ORIG and SHELL in ORIG and CHECKOUT_WITH in ORIG


def sub(a, b):
    def f(t):
        assert a in t, a
        return t.replace(a, b, 1)
    return f


def apply_and_run(tf, extra):
    try:
        CI.write_text(tf(ORIG), encoding="utf-8")
        for rel, txt in extra.items():
            p = WT / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(txt, encoding="utf-8")
        o = subprocess.run([sys.executable, "-c", RUNNER], cwd=WT, capture_output=True, text=True)
        return o.stdout.strip().splitlines()[-1] if o.stdout.strip() else "ERR:" + o.stderr[-200:]
    finally:
        CI.write_text(ORIG, encoding="utf-8")
        for rel in extra:
            (WT / rel).unlink(missing_ok=True)


EVIL_TEST = (
    "import os\n"
    "def setUpModule():\n"
    "    p = os.environ.get('GITHUB_ENV')\n"
    "    if p:\n"
    "        open('/tmp/b.sh','w').write('grep(){ return 1; }\\n')\n"
    "        open(p,'a').write('BASH_ENV=/tmp/b.sh\\n')\n"
)
MUTATIONS = [
    ("pull_request_target_added", sub(ON, ON + "  pull_request_target:\n    branches: [main]\n"), {}),
    ("workflow_run_added", sub(ON, ON + "  workflow_run:\n    workflows: [x]\n"), {}),
    ("on_quoted_key", sub(ON, ON.replace("on:", '"on":', 1) + "  pull_request_target:\n"), {}),
    ("multidoc_second_doc", lambda t: t + "---\nname: CI\non:\n  push:\njobs:\n  other:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo\n", {}),
    ("duplicate_run_key_in_guard", sub(STEP, STEP.replace("run: |", "run: echo ok\n        run: |")), {}),
    ("alias_run_from_anchor", sub(STEP, "      - name: Refuse tracked pack artifacts\n        run: &g |\n"), {}),
    ("earlier_uses_swapped_to_third_party", sub(SETUP, "        uses: evil/setup-python@v5\n"), {}),
    ("earlier_python_test_writes_github_env", lambda t: t, {"apps/dottie-os/tests/test_zz_critic_env.py": EVIL_TEST}),
    ("donewhen_shell_drops_euo_pipefail", sub(SHELL, '        shell: "/usr/bin/bash --noprofile --norc -p {0}"\n'), {}),
    ("donewhen_job_name_override", sub(PACK_JOB, "  pack-guard:\n    name: pack-guard-ci\n    runs-on: ubuntu-latest\n"), {}),
    ("donewhen_checkout_with_ref", sub(CHECKOUT_WITH, "          persist-credentials: false\n          ref: main\n"), {}),
]


class D_WorkflowMutations(unittest.TestCase):
    def test_baseline_green(self):
        self.assertEqual(apply_and_run(lambda t: t, {}), "GREEN")

    def test_mutations_go_red(self):
        for mid, tf, extra in MUTATIONS:
            with self.subTest(mutation=mid):
                self.assertEqual(apply_and_run(tf, extra), "RED", f"{mid} survives Forge's tests")


if __name__ == "__main__":
    unittest.main()
