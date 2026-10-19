"""Critic attack suite for dottie#91 (head e93cc12c).

Part A: ci.yml / workflow mutations. Each one is applied to the #91 worktree, then
Forge's own TrackedPackArtifactGuardTests are run (stdlib YAML path, like CI).
A subTest passes when Forge's tests go RED (mutation caught).

Part B: behaviour of the real extracted guard run: block under hostile
conditions an earlier step could create (GITHUB_ENV / GITHUB_PATH / index
rewrites / odd filenames). A test passes when the guard exits non-zero, or for
negative controls, exits 0.

Run:  WT=/workspace/review/dottie-91/wt python3 -m unittest -v test_critic_91_mutations
Read-only w.r.t. GitHub; mutates the local worktree and restores it with git.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Default WT is this repo so discover/CI run the suite in-tree.
# Original Critic drop sha256 0cbbaa78bc4de52a32ccf64a9e5ecb622a670fde381a018c4d185a6c71e355ad
WT = Path(os.environ.get("WT", str(Path(__file__).resolve().parents[3])))
CI = WT / ".github" / "workflows" / "ci.yml"
ORIG = CI.read_text(encoding="utf-8")
STEP = "      - name: Refuse tracked pack artifacts\n        run: |\n"
JOB = "  dottie-os-smoke:\n    runs-on: ubuntu-latest\n    steps:\n"
CHECKOUT = JOB + "      - uses: actions/checkout@v4\n"
EARLIER = "      - name: Tests must not write apps/dottie-os/trust/\n"
ON = "on:\n  push:\n    branches: [main]\n  pull_request:\n    branches: [main]\n"
for anchor in (STEP, JOB, EARLIER, ON):
    assert anchor in ORIG, anchor

RUNNER = r"""
import sys, unittest
sys.modules['yaml'] = None
sys.path.insert(0, 'apps/dottie-os/tests')
import test_ultradata_factory as T
s = unittest.defaultTestLoader.loadTestsFromTestCase(T.TrackedPackArtifactGuardTests)
r = unittest.TextTestRunner(verbosity=0, stream=open('/dev/null', 'w')).run(s)
print('GREEN' if r.wasSuccessful() else 'RED')
"""


def sub(a: str, b: str):
    def f(t: str) -> str:
        assert a in t, a
        return t.replace(a, b, 1)
    return f


def earlier(run: str):
    return sub(EARLIER, f"      - name: prep\n        run: {run}\n" + EARLIER)


def earlier_uses(withs: str):
    return sub(CHECKOUT, JOB + "      - uses: actions/checkout@v4\n        with:\n" + withs)


SECOND_WF = (
    "name: CI\non:\n  pull_request:\n    branches: [main]\njobs:\n"
    "  dottie-os-smoke:\n    runs-on: ubuntu-latest\n    steps:\n"
    "      - name: Refuse tracked pack artifacts\n        run: echo ok\n"
)

# (id, category, ci.yml transform, extra files {relpath: text})
MUTATIONS = [
    # --- my 8 earlier survivors on 8762693b (10 concrete edits) ---
    ("prev_step_shell_exit0", "prev", sub(STEP, STEP.replace("run: |", "shell: bash -c 'exit 0' {0}\n        run: |")), {}),
    ("prev_step_shell_python", "prev", sub(STEP, STEP.replace("run: |", "shell: python {0}\n        run: |")), {}),
    ("prev_step_working_directory", "prev", sub(STEP, STEP.replace("run: |", "working-directory: apps/bluehenre\n        run: |")), {}),
    ("prev_step_env_git_index_file", "prev", sub(STEP, STEP.replace("run: |", "env:\n          GIT_INDEX_FILE: /dev/null\n        run: |")), {}),
    ("prev_job_continue_on_error", "prev", sub(JOB, JOB.replace("    steps:\n", "    continue-on-error: true\n    steps:\n")), {}),
    ("prev_job_if_false", "prev", sub(JOB, JOB.replace("    runs-on", "    if: false\n    runs-on")), {}),
    ("prev_job_defaults_workdir", "prev", sub(JOB, JOB.replace("    steps:\n", "    defaults:\n      run:\n        working-directory: apps/bluehenre\n    steps:\n")), {}),
    ("prev_job_defaults_shell", "prev", sub(JOB, JOB.replace("    steps:\n", "    defaults:\n      run:\n        shell: bash -c 'exit 0' {0}\n    steps:\n")), {}),
    ("prev_workflow_defaults_shell", "prev", sub("jobs:\n", "defaults:\n  run:\n    shell: bash -c 'exit 0' {0}\njobs:\n"), {}),
    ("prev_earlier_git_rm_cached", "prev", earlier("git rm -r -q --cached apps/dottie-os/tests/fixtures || true"), {}),
    # --- (a) env at workflow / job level ---
    ("a_workflow_env_GIT_INDEX_FILE", "a", sub("jobs:\n", "env:\n  GIT_INDEX_FILE: /tmp/none\njobs:\n"), {}),
    ("a_workflow_env_GIT_DIR", "a", sub("jobs:\n", "env:\n  GIT_DIR: /tmp/empty.git\njobs:\n"), {}),
    ("a_workflow_env_GIT_WORK_TREE", "a", sub("jobs:\n", "env:\n  GIT_WORK_TREE: /tmp\njobs:\n"), {}),
    ("a_job_env_GIT_INDEX_FILE", "a", sub(JOB, JOB.replace("    steps:\n", "    env:\n      GIT_INDEX_FILE: /tmp/none\n    steps:\n")), {}),
    ("a_job_env_GIT_DIR", "a", sub(JOB, JOB.replace("    steps:\n", "    env:\n      GIT_DIR: /tmp/empty.git\n    steps:\n")), {}),
    # --- (b) triggers ---
    ("b_pr_paths_ignore_apps", "b", sub(ON, ON + "    paths-ignore: ['apps/**']\n"), {}),
    ("b_pr_paths_docs_only", "b", sub(ON, ON + "    paths: ['docs/**']\n"), {}),
    ("b_pr_branches_never", "b", sub(ON, ON.replace("  pull_request:\n    branches: [main]", "  pull_request:\n    branches: [nope]")), {}),
    ("b_remove_pull_request", "b", sub(ON, "on:\n  push:\n    branches: [main]\n"), {}),
    ("b_pr_types_closed", "b", sub(ON, ON + "    types: [closed]\n"), {}),
    # --- (c) concurrency / permissions / timeout ---
    ("c_workflow_concurrency_cancel", "c", sub("jobs:\n", "concurrency:\n  group: ci\n  cancel-in-progress: true\njobs:\n"), {}),
    ("c_workflow_permissions_none", "c", sub("jobs:\n", "permissions: {}\njobs:\n"), {}),
    ("c_job_concurrency_cancel", "c", sub(JOB, JOB.replace("    steps:\n", "    concurrency:\n      group: g\n      cancel-in-progress: true\n    steps:\n")), {}),
    ("c_job_permissions_none", "c", sub(JOB, JOB.replace("    steps:\n", "    permissions: {}\n    steps:\n")), {}),
    ("c_job_timeout_0", "c", sub(JOB, JOB.replace("    steps:\n", "    timeout-minutes: 0\n    steps:\n")), {}),
    # --- (d) second workflow / matrix ---
    ("d_second_workflow_same_job_and_step", "d", lambda t: t, {".github/workflows/zz-spoof.yml": SECOND_WF}),
    ("d_matrix_renames_check", "d", sub(JOB, JOB.replace("    steps:\n", "    strategy:\n      matrix:\n        x: [1]\n    steps:\n")), {}),
    ("d_job_name_override", "d", sub(JOB, JOB.replace("    runs-on", "    name: dottie-os-smoke-legacy\n    runs-on")), {}),
    # --- (e) earlier steps ---
    ("e_git_config_core_sparseCheckout", "e", earlier("git config core.sparseCheckout true"), {}),
    ("e_git_config_core_excludesFile", "e", earlier("git config core.excludesFile /dev/null"), {}),
    ("e_info_exclude", "e", earlier("echo 'curated_pack_*' >> .git/info/exclude"), {}),
    ("e_git_update_ref", "e", earlier("git update-ref HEAD $(git commit-tree 4b825dc642cb6eb9a060e54bf8d69288fbee4904 -m x)"), {}),
    ("e_checkout_orphan", "e", earlier("git checkout -q --orphan empty"), {}),
    ("e_git_stash", "e", earlier("git stash -q || true"), {}),
    ("e_git_read_tree_empty", "e", earlier("git read-tree --empty"), {}),
    ("e_git_reset_to_empty_tree", "e", earlier("git reset -q $(git commit-tree 4b825dc642cb6eb9a060e54bf8d69288fbee4904 -m x)"), {}),
    ("e_git_C_rm_cached", "e", earlier("git -C . rm -r -q --cached apps/dottie-os/tests/fixtures"), {}),
    ("e_git_c_opt_rm_cached", "e", earlier("git -c core.x=y rm -r -q --cached apps"), {}),
    ("e_github_env_git_index_file", "e", earlier('echo "GIT_INDEX_FILE=/tmp/none" >> "$GITHUB_ENV"'), {}),
    ("e_github_env_git_dir", "e", earlier('git init -q --bare /tmp/e.git && echo "GIT_DIR=/tmp/e.git" >> "$GITHUB_ENV"'), {}),
    ("e_github_env_bash_env", "e", earlier('printf "git(){ :; }\\n" > /tmp/b.sh && echo "BASH_ENV=/tmp/b.sh" >> "$GITHUB_ENV"'), {}),
    ("e_github_path_git_shim", "e", earlier('mkdir -p /tmp/s && printf "#!/bin/sh\\n:\\n" > /tmp/s/git && chmod +x /tmp/s/git && echo /tmp/s >> "$GITHUB_PATH"'), {}),
    ("e_checkout_with_sparse", "e", earlier_uses("          sparse-checkout: apps/dottie-os/scripts\n"), {}),
    ("e_checkout_with_path", "e", earlier_uses("          path: sub\n"), {}),
    ("e_checkout_with_ref_main", "e", earlier_uses("          ref: main\n"), {}),
]


def apply_and_run(transform, extra) -> str:
    try:
        CI.write_text(transform(ORIG), encoding="utf-8")
        for rel, text in extra.items():
            p = WT / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        out = subprocess.run([sys.executable, "-c", RUNNER], cwd=WT, capture_output=True, text=True)
        return out.stdout.strip().splitlines()[-1] if out.stdout.strip() else "ERR:" + out.stderr[-200:]
    finally:
        CI.write_text(ORIG, encoding="utf-8")
        for rel in extra:
            (WT / rel).unlink(missing_ok=True)


class ForgeTestsCatchMutations(unittest.TestCase):
    def test_baseline_green(self):
        self.assertEqual(apply_and_run(lambda t: t, {}), "GREEN")

    def test_mutations_go_red(self):
        for mid, cat, tf, extra in MUTATIONS:
            with self.subTest(mutation=mid, category=cat):
                self.assertEqual(apply_and_run(tf, extra), "RED", f"{mid} survives Forge's tests")


# ---------------- Part B: real guard behaviour ----------------
def guard_block() -> str:
    sys.path.insert(0, str(WT / "apps/dottie-os/tests"))
    sys.modules.setdefault("yaml", None)  # type: ignore[arg-type]
    import test_ultradata_factory as T  # noqa: E402
    return str(T._load_pack_guard_step(ORIG)["run"])


def mkrepo(tmp: Path, names: list[str]) -> Path:
    repo = tmp / "r"
    repo.mkdir()
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, env=env)
    # Meet the pack-guard sanity floor (N=1280, plus .github/workflows/ci.yml).
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.parent.mkdir(parents=True, exist_ok=True)
    ci.write_text("name: CI\n", encoding="utf-8")
    floor = repo / "_floor"
    floor.mkdir()
    for i in range(1279):
        (floor / f"{i:04d}").write_text(".\n", encoding="utf-8")
    for n in names:
        p = repo / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"], cwd=repo, check=True, env=env)
    return repo


def run_guard(repo: Path, extra_env: dict | None = None, pre: str = "") -> int:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("GIT_") and k != "GITHUB_SHA"
    }
    env.update({"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"})
    env.update(extra_env or {})
    if "GITHUB_SHA" not in env:
        pin = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        if pin.returncode == 0:
            env["GITHUB_SHA"] = pin.stdout.strip()
    # GitHub's default for run: is `bash -e {0}` (here: -e + the script)
    script = pre + "\n" + guard_block() if pre else guard_block()
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
        f.write(script)
    return subprocess.run(["bash", "-e", f.name], cwd=repo, env=env, capture_output=True, text=True).returncode


PACK = "apps/x/curated_pack_v2.jsonl"


class GuardBehaviour(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # controls
    def test_control_plain_pack_trips(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, [PACK])), 0)

    def test_control_clean_repo_passes(self):
        self.assertEqual(run_guard(mkrepo(self.tmp, ["README"])), 0)

    # (f) filenames
    def test_f_nonascii_name_trips(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, ["apps/x/curated_pack_é.jsonl"])), 0)

    def test_f_tab_in_name_trips(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, ["apps/x/curated_pack_a\tb.jsonl"])), 0)

    def test_f_newline_in_name_trips(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, ["apps/x/curated_pack_a\nb.jsonl"])), 0)

    def test_f_quote_in_name_trips(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, ['apps/x/curated_pack_a"b.jsonl'])), 0)

    def test_f_space_in_name_trips(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, ["apps/x/curated_pack_a b.jsonl"])), 0)

    def test_f_leading_dash_name_trips(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, ["-e curated_pack_v2.jsonl"])), 0)

    def test_f_uppercase_name_trips(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, ["apps/x/Curated_Pack_v2.JSONL"])), 0)

    # (g) set -e / fail-closed plumbing under bash -e
    def test_g_outside_repo_fails_closed(self):
        d = self.tmp / "nr"; d.mkdir()
        self.assertNotEqual(run_guard(d), 0)

    def test_g_null_index_fails_closed(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, [PACK]), {"GIT_INDEX_FILE": "/dev/null"}), 0)

    # (a)/(e) hostile env an earlier step can export via GITHUB_ENV
    def test_e_missing_index_file_fails_closed(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, [PACK]), {"GIT_INDEX_FILE": str(self.tmp / "none")}), 0)

    def test_e_git_dir_points_at_empty_repo_fails_closed(self):
        repo = mkrepo(self.tmp, [PACK])
        subprocess.run(["git", "init", "-q", "--bare", str(self.tmp / "e.git")], check=True)
        self.assertNotEqual(run_guard(repo, {"GIT_DIR": str(self.tmp / "e.git")}), 0)

    def test_e_git_work_tree_elsewhere_fails_closed(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, [PACK]), {"GIT_WORK_TREE": "/tmp"}), 0)

    def test_e_bash_env_function_shadow_fails_closed(self):
        repo = mkrepo(self.tmp, [PACK])
        b = self.tmp / "b.sh"; b.write_text("git(){ :; }\n")
        self.assertNotEqual(run_guard(repo, {"BASH_ENV": str(b)}), 0)

    def test_e_path_git_shim_fails_closed(self):
        repo = mkrepo(self.tmp, [PACK])
        s = self.tmp / "s"; s.mkdir(); g = s / "git"; g.write_text("#!/bin/sh\n:\n"); g.chmod(0o755)
        self.assertNotEqual(run_guard(repo, {"PATH": f"{s}:{os.environ['PATH']}"}), 0)

    def test_e_read_tree_empty_fails_closed(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, [PACK]), pre="git read-tree --empty"), 0)

    def test_e_reset_to_empty_tree_fails_closed(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, [PACK]), pre="git reset -q $(git -c user.name=t -c user.email=t@t commit-tree 4b825dc642cb6eb9a060e54bf8d69288fbee4904 -m x)"), 0)

    def test_e_core_sparse_checkout_no_effect(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, [PACK]), pre="git config core.sparseCheckout true"), 0)

    def test_e_sparse_checkout_cone_still_lists(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, [PACK, "docs/a"]), pre="git sparse-checkout set --cone docs >/dev/null 2>&1"), 0)

    def test_e_sparse_index_still_lists(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, [PACK, "docs/a"]), pre="git sparse-checkout set --cone --sparse-index docs >/dev/null 2>&1"), 0)

    def test_e_excludes_no_effect(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, [PACK]), pre="echo 'curated_pack_*' >> .git/info/exclude"), 0)

    def test_e_stash_no_effect(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, [PACK]), pre="git stash -q || true"), 0)

    def test_e_orphan_no_effect(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, [PACK]), pre="git checkout -q --orphan e"), 0)

    def test_e_git_dir_points_at_empty_nonbare_repo_fails_closed(self):
        repo = mkrepo(self.tmp, [PACK])
        subprocess.run(["git", "init", "-q", str(self.tmp / "e")], check=True)
        self.assertNotEqual(run_guard(repo, {"GIT_DIR": str(self.tmp / "e" / ".git")}), 0)

    def test_e_update_ref_no_effect(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, [PACK]), pre="git update-ref HEAD $(git -c user.name=t -c user.email=t@t commit-tree 4b825dc642cb6eb9a060e54bf8d69288fbee4904 -m x)"), 0)

    def test_e_git_C_rm_cached_fails_closed(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, [PACK]), pre="git -C . rm -r -q --cached apps"), 0)


if __name__ == "__main__":
    unittest.main()
