"""Critic attack suite for dottie#91 @ af2d8da623eab3318e28f252b55342f0672cf80d (pack-guard job).

Every test asserts the SECURE behaviour; a FAIL is a finding.
E: workflow mutations -> Forge's TrackedPackArtifactGuardTests must go RED.
F: static done-when checks on the pack-guard job text.
G: real guard (step `run` under the step's real `shell:`) against temp repos (floor 1280 + ci.yml).
Run:  WT=/workspace/review/dottie-91/wt-af2d python3 -m unittest -v test_critic_91_af2d
Read-only w.r.t. GitHub; E rewrites WT files and restores them.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Original Critic drop sha256 f251c6c9b34b5add838b6f45e93fb538ccb61b0704b5652428440033a0ecfbc5
WT = Path(os.environ.get("WT", str(Path(__file__).resolve().parents[3])))
CI = WT / ".github" / "workflows" / "ci.yml"
ORIG = CI.read_text(encoding="utf-8")
PIN = "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683"
JOB = "  pack-guard:\n    runs-on: ubuntu-latest\n    steps:\n"
CO = f"      - uses: {PIN}\n        with:\n          persist-credentials: false\n"
STEP = "      - name: Refuse tracked pack artifacts\n        run: |\n"
SHELL_LINE = '        shell: "/usr/bin/bash --noprofile --norc -p -euo pipefail {0}"\n'
ON = "on:\n  push:\n    branches: [main]\n  pull_request:\n    branches: [main]\n"
SMOKE = "  dottie-os-smoke:\n    runs-on: ubuntu-latest\n"
LINT = "  lint-and-test:\n    runs-on: ubuntu-latest\n"
for a in (JOB + CO + STEP, SHELL_LINE, ON, SMOKE, LINT):
    assert a in ORIG, a


def _step():
    sys.path.insert(0, str(WT / "apps/dottie-os/tests"))
    sys.modules.setdefault("yaml", None)  # type: ignore[arg-type]
    import test_ultradata_factory as T  # noqa: E402
    return T._load_pack_guard_step(ORIG)


GUARD = str(_step()["run"])
SHELL = str(_step()["shell"])


def job_text(text=ORIG, job="pack-guard"):
    lines = text.splitlines(keepends=True)
    s = next(i for i, l in enumerate(lines) if l == f"  {job}:\n")
    e = next((i for i in range(s + 1, len(lines)) if re.match(r"^  [A-Za-z0-9_-]+:\s*$", lines[i])), len(lines))
    return "".join(lines[s:e])


RUNNER = r"""
import sys, unittest
sys.modules['yaml'] = None
sys.path.insert(0, 'apps/dottie-os/tests')
import test_ultradata_factory as T
s = unittest.defaultTestLoader.loadTestsFromTestCase(T.TrackedPackArtifactGuardTests)
r = unittest.TextTestRunner(verbosity=0, stream=open('/dev/null', 'w')).run(s)
print('GREEN' if r.wasSuccessful() else 'RED')
"""


def sub(a, b):
    def f(t):
        assert a in t, a
        return t.replace(a, b, 1)
    return f


def jobkey(k):
    return sub(JOB, JOB.replace("    steps:\n", k + "    steps:\n"))


def stepkey(k):
    return sub(STEP, "      - name: Refuse tracked pack artifacts\n" + k + "        run: |\n")


def wf(name, body):
    return {f".github/workflows/{name}": body}


SPOOF = "name: x\non:\n  pull_request:\n    branches: [main]\njobs:\n  {jid}:\n{extra}    runs-on: ubuntu-latest\n    steps:\n      - run: echo ok\n"

MUT = [
    ("job_if_false", jobkey("    if: false\n"), {}),
    ("job_continue_on_error", jobkey("    continue-on-error: true\n"), {}),
    ("job_needs", jobkey("    needs: lint-and-test\n"), {}),
    ("job_matrix", jobkey("    strategy:\n      matrix:\n        x: [1]\n"), {}),
    ("job_timeout_0", jobkey("    timeout-minutes: 0\n"), {}),
    ("job_container", jobkey("    container: alpine:3\n"), {}),
    ("job_services", jobkey("    services:\n      s:\n        image: alpine\n"), {}),
    ("job_defaults_shell", jobkey("    defaults:\n      run:\n        shell: bash -c 'exit 0' {0}\n"), {}),
    ("job_env", jobkey("    env:\n      LC_ALL: C.UTF-8\n"), {}),
    ("job_permissions", jobkey("    permissions: {}\n"), {}),
    ("job_concurrency", jobkey("    concurrency:\n      group: g\n      cancel-in-progress: true\n"), {}),
    ("job_runs_on_self_hosted", sub(JOB, JOB.replace("ubuntu-latest", "self-hosted")), {}),
    ("job_name_same", jobkey("    name: pack-guard\n"), {}),
    ("step_if_false", stepkey("        if: false\n"), {}),
    ("step_continue_on_error", stepkey("        continue-on-error: true\n"), {}),
    ("step_working_directory", stepkey("        working-directory: apps\n"), {}),
    ("step_env", stepkey("        env:\n          X: y\n"), {}),
    ("step_timeout_0", stepkey("        timeout-minutes: 0\n"), {}),
    ("shell_no_p", sub(SHELL_LINE, SHELL_LINE.replace(" -p", "")), {}),
    ("shell_no_norc", sub(SHELL_LINE, SHELL_LINE.replace(" --norc", "")), {}),
    ("shell_no_pipefail", sub(SHELL_LINE, SHELL_LINE.replace("-euo pipefail", "-eu")), {}),
    ("shell_relative_bash", sub(SHELL_LINE, SHELL_LINE.replace("/usr/bin/bash", "bash")), {}),
    ("shell_or_true", sub(SHELL_LINE, SHELL_LINE.replace("{0}", "{0} || true")), {}),
    ("checkout_tag_ref", sub(CO, CO.replace(PIN, "actions/checkout@v4")), {}),
    ("checkout_other_sha", sub(CO, CO.replace(PIN, "actions/checkout@" + "b" * 40)), {}),
    ("checkout_fork_owner_same_sha", sub(CO, CO.replace(PIN, PIN.replace("actions/", "evil/"))), {}),
    ("checkout_with_ref", sub(CO, CO + "          ref: ${{ github.event.pull_request.head.sha }}\n"), {}),
    ("checkout_with_fetch_depth", sub(CO, CO + "          fetch-depth: 0\n"), {}),
    ("checkout_persist_true", sub(CO, CO.replace("false", "true")), {}),
    ("step_between_checkout_and_guard", sub(CO + STEP, CO + "      - run: echo hi\n" + STEP), {}),
    ("third_party_before_checkout", sub(JOB + CO, JOB + "      - uses: evil/x@" + "a" * 40 + "\n" + CO), {}),
    ("extra_step_after_guard", sub(SHELL_LINE, SHELL_LINE + "      - run: echo after\n"), {}),
    ("run_drop_no_replace", lambda t: t.replace("              GIT_NO_REPLACE_OBJECTS=1 \\\n", "", 1).replace("/usr/bin/git --no-replace-objects \\", "/usr/bin/git \\", 1), {}),
    ("run_lc_all_utf8", lambda t: t.replace("LC_ALL=C \\\n              GIT_CONFIG_NOSYSTEM", "LC_ALL=C.UTF-8 \\\n              GIT_CONFIG_NOSYSTEM", 1), {}),
    ("run_home_kept", lambda t: t.replace("HOME=/nonexistent \\\n              LC_ALL=C \\\n              GIT_CONFIG_NOSYSTEM", 'HOME="$HOME" \\\n              LC_ALL=C \\\n              GIT_CONFIG_NOSYSTEM', 1), {}),
    ("run_fsmonitor_on", lambda t: t.replace("                -c core.fsmonitor=false \\\n", "", 1), {}),
    ("run_early_exit0", sub(STEP, STEP + "          \\builtin exit 0\n"), {}),
    ("wf_env", sub("jobs:\n", "env:\n  LC_ALL: C.UTF-8\njobs:\n"), {}),
    ("wf_defaults_shell", sub("jobs:\n", "defaults:\n  run:\n    shell: bash -c 'exit 0' {0}\njobs:\n"), {}),
    ("wf_concurrency", sub("jobs:\n", "concurrency:\n  group: ci\n  cancel-in-progress: true\njobs:\n"), {}),
    ("wf_permissions", sub("jobs:\n", "permissions: {}\njobs:\n"), {}),
    ("wf_pull_request_target", sub(ON, ON + "  pull_request_target:\n    branches: [main]\n"), {}),
    ("spoof_other_wf_same_job_id", lambda t: t, wf("zz-spoof.yml", SPOOF.format(jid="pack-guard", extra=""))),
    ("spoof_other_wf_yaml_ext", lambda t: t, wf("zz-spoof.yaml", SPOOF.format(jid="pack-guard", extra=""))),
    ("spoof_other_wf_name_key", lambda t: t, wf("zz-spoof.yml", SPOOF.format(jid="spoof", extra="    name: pack-guard\n"))),
    ("spoof_other_wf_name_quoted", lambda t: t, wf("zz-spoof.yml", SPOOF.format(jid="spoof", extra="    name: 'pack-guard'\n"))),
    ("spoof_other_wf_name_expr", lambda t: t, wf("zz-spoof.yml", SPOOF.format(jid="spoof", extra="    name: ${{ 'pack-guard' }}\n"))),
    ("spoof_other_wf_name_case", lambda t: t, wf("zz-spoof.yml", SPOOF.format(jid="spoof", extra="    name: Pack-Guard\n"))),
    ("spoof_ci_smoke_name", sub(SMOKE, "  dottie-os-smoke:\n    name: pack-guard\n    runs-on: ubuntu-latest\n"), {}),
    ("spoof_ci_lint_name", sub(LINT, "  lint-and-test:\n    name: pack-guard\n    runs-on: ubuntu-latest\n"), {}),
    ("lookalike_job_id_in_ci", sub(SMOKE, "  pack_guard:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo ok\n\n" + SMOKE), {}),
    ("spoof_in_existing_lint_wf", lambda t: t, "LINT_SPOOF"),
    ("spoof_other_wf_4space_indent", lambda t: t, wf("zz-spoof.yml", "name: x\non:\n    pull_request:\n        branches: [main]\njobs:\n    pack-guard:\n        runs-on: ubuntu-latest\n        steps:\n            - run: echo ok\n")),
    ("spoof_other_wf_flow_style", lambda t: t, wf("zz-spoof.yml", "name: x\non: [pull_request]\njobs: {pack-guard: {runs-on: ubuntu-latest, steps: [{run: echo ok}]}}\n")),
]


def apply_and_run(tf, extra):
    if extra == "LINT_SPOOF":
        p = WT / ".github/workflows/lint.yml"
        extra = {".github/workflows/lint.yml": p.read_text().replace(
            "jobs:\n", "jobs:\n  pack-guard:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo ok\n", 1)}
    saved = {}
    try:
        CI.write_text(tf(ORIG), encoding="utf-8")
        for rel, txt in extra.items():
            p = WT / rel
            if p.exists():
                saved[rel] = p.read_text()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(txt, encoding="utf-8")
        o = subprocess.run([sys.executable, "-c", RUNNER], cwd=WT, capture_output=True, text=True)
        return o.stdout.strip().splitlines()[-1] if o.stdout.strip() else "ERR:" + o.stderr[-200:]
    finally:
        CI.write_text(ORIG, encoding="utf-8")
        for rel in extra:
            if rel in saved:
                (WT / rel).write_text(saved[rel])
            else:
                (WT / rel).unlink(missing_ok=True)


class E_Mutations(unittest.TestCase):
    def test_baseline_green(self):
        self.assertEqual(apply_and_run(lambda t: t, {}), "GREEN")

    def test_mutations_go_red(self):
        for mid, tf, extra in MUT:
            with self.subTest(mutation=mid):
                self.assertEqual(apply_and_run(tf, extra), "RED", f"{mid} survives Forge's tests")


class F_DoneWhen(unittest.TestCase):
    J = job_text()

    def test_shell_exact(self):
        self.assertTrue(SHELL.startswith("/usr/bin/bash "))
        self.assertIn("--noprofile --norc", SHELL)
        self.assertIn("-euo pipefail", SHELL)

    def test_job_keys_only_runs_on_steps(self):
        keys = {l.split(":")[0].strip() for l in self.J.splitlines()[1:] if re.match(r"^    [a-z-]+:", l)}
        self.assertEqual(keys, {"runs-on", "steps"})

    def test_exactly_two_steps_checkout_then_guard(self):
        steps = [l for l in self.J.splitlines() if l.startswith("      - ")]
        self.assertEqual(steps, [f"      - uses: {PIN}", "      - name: Refuse tracked pack artifacts"])

    def test_checkout_with_only_persist_false(self):
        self.assertIn(CO + STEP, self.J)

    def test_git_env_allowlist(self):
        body = re.search(r"git_scrub\(\) \{\n(.*?)\n\s*\}", GUARD, re.S).group(1) + " "
        for kv in ("/usr/bin/env -i", "PATH=/usr/bin:/bin", "HOME=/nonexistent", "LC_ALL=C ",
                   "GIT_CONFIG_NOSYSTEM=1", "GIT_CONFIG_GLOBAL=/dev/null", "GIT_NO_REPLACE_OBJECTS=1",
                   "--no-replace-objects", "core.fsmonitor=false", "core.hooksPath=/dev/null"):
            self.assertIn(kv, body, kv)

    def test_no_relative_external_commands(self):
        # every command word is a builtin (\builtin x / [ ), a local function, or /usr/bin/...
        ok_fn = {"git_scrub", "grep_pack", "show_pack_hits", "cleanup"}
        bad = []
        for line in GUARD.splitlines():
            s = re.sub(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"", "Q", line.strip())
            if not s or s.startswith(("#", "}", "{", "-")) or s in ("fi", "then"):
                continue
            for seg in re.split(r"\|\||&&|\||;|\$\(|\bif\b|\bthen\b|!", s):
                w = seg.strip().split(" ")[0] if seg.strip() else ""
                if not w or "=" in w or w.startswith(("/usr/bin/", "\\builtin", '"', "'", ")", "}", "{", "\\")):
                    continue
                if w.rstrip("()") in ok_fn or w in ("fi", "else", "PATH", "HOME", "Q"):
                    continue
                bad.append((w, s[:50]))
        self.assertEqual(bad, [])

    def test_job_name_unique_across_workflows(self):
        hits = []
        for p in sorted((WT / ".github/workflows").glob("*.y*ml")):
            for i, l in enumerate(p.read_text().splitlines(), 1):
                if re.match(r"^  pack[-_ ]?guard:\s*$", l, re.I) or re.match(r"^\s+name:\s*['\"]?pack[-_ ]?guard['\"]?\s*$", l, re.I):
                    hits.append(f"{p.name}:{i}")
        self.assertEqual(hits, ["ci.yml:612"])

    def test_no_repo_code_before_guard(self):
        pre = self.J.split(STEP)[0]
        self.assertNotIn("run:", pre)
        self.assertEqual(re.findall(r"uses: (\S+)", pre), [PIN])

    def test_codeowners_cover_all_workflows_and_itself(self):
        lines = [l.split()[0] for l in (WT / ".github/CODEOWNERS").read_text().splitlines() if l.strip() and not l.startswith("#")]
        self.assertTrue(any(p in lines for p in (".github/", "/.github/", ".github/workflows/", "/.github/workflows/")),
                        "CODEOWNERS owns only ci.yml; a new workflow file needs no Cam review")
        self.assertTrue(any(p in lines for p in (".github/", "/.github/", ".github/CODEOWNERS", "/.github/CODEOWNERS")))

    def test_codeowners_cover_guard_tests(self):
        self.assertIn("apps/dottie-os/tests/test_ultradata_factory.py", (WT / ".github/CODEOWNERS").read_text())


BASE_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def genv(extra=None):
    e = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "GITHUB_SHA"}
    e.update(BASE_ENV)
    e.update(extra or {})
    return e


def git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, check=True, env=genv(), capture_output=True).stdout.decode().strip()


def mkrepo(tmp, names, name="r"):
    repo = tmp / name
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / ".github/workflows").mkdir(parents=True)
    (repo / ".github/workflows/ci.yml").write_text("name: CI\n")
    (repo / "_floor").mkdir()
    for i in range(1279):
        (repo / "_floor" / f"{i:04d}").write_text(".\n")
    for n in names:
        (repo / n).parent.mkdir(parents=True, exist_ok=True)
        (repo / n).write_text("{}\n")
    git(repo, "add", "-f", "-A")
    git(repo, "commit", "-qm", "x")
    return repo


def run_guard(repo, extra_env=None, sha=None):
    env = genv(extra_env)
    env["GITHUB_SHA"] = sha or git(repo, "rev-parse", "HEAD")
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
        f.write(GUARD)
    r = subprocess.run([a.replace("{0}", f.name) for a in SHELL.split()], cwd=repo, env=env, capture_output=True, text=True)
    os.unlink(f.name)
    return r.returncode


PACK = "apps/x/curated_pack_v2.jsonl"


class G_Behaviour(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_control_clean(self):
        self.assertEqual(run_guard(mkrepo(self.tmp, ["README"])), 0)

    def _pr_merge(self, add_then_delete=False, resolution_adds=False):
        r = mkrepo(self.tmp, ["README"])
        git(r, "checkout", "-q", "-b", "pr")
        if resolution_adds:
            (r / "doc").write_text("d\n")
            git(r, "add", "doc")
            git(r, "commit", "-qm", "doc")
        else:
            (r / "apps/x").mkdir(parents=True)
            (r / PACK).write_text("{}\n")
            git(r, "add", "-f", PACK)
            git(r, "commit", "-qm", "add pack")
            if add_then_delete:
                git(r, "rm", "-q", PACK)
                git(r, "commit", "-qm", "rm pack")
        git(r, "checkout", "-q", "main")
        (r / "base").write_text("b\n")
        git(r, "add", "base")
        git(r, "commit", "-qm", "base moves")
        git(r, "merge", "-q", "--no-ff", "--no-commit", "pr")
        if resolution_adds:
            (r / "apps/x").mkdir(parents=True, exist_ok=True)
            (r / PACK).write_text("{}\n")
            git(r, "add", "-f", PACK)
        git(r, "commit", "-qm", "merge refs/pull/1/merge")
        return r

    def test_pack_in_pr_commit_caught_at_merge_sha(self):
        self.assertNotEqual(run_guard(self._pr_merge()), 0)

    def test_pack_added_by_merge_resolution_caught(self):
        self.assertNotEqual(run_guard(self._pr_merge(resolution_adds=True)), 0)

    def test_github_sha_pr_head_vs_merge_checkout_fails_closed(self):
        r = self._pr_merge()
        self.assertNotEqual(run_guard(r, sha=git(r, "rev-parse", "HEAD^2")), 0)

    @unittest.skip(
        "S18: add-then-delete inside a PR is not visible at GITHUB_SHA; "
        "needs squash-only merges (Cam)"
    )
    def test_pack_only_in_pr_history_refused(self):
        self.assertNotEqual(run_guard(self._pr_merge(add_then_delete=True)), 0)

    def test_exported_function_shadow_ignored(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, [PACK]), {"BASH_FUNC_builtin%%": "() { :; }", "BASH_FUNC_cd%%": "() { :; }"}), 0)

    def test_shellopts_bashopts_ignored(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, [PACK]), {"SHELLOPTS": "posix", "BASHOPTS": "expand_aliases"}), 0)

    def test_greek_omicron_lookalike_fails_closed(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, ["apps/x/curated_pack_v2.js\u03bfnl"])), 0)

    def test_ascii_rename_curated_dash_pack(self):
        self.assertNotEqual(run_guard(mkrepo(self.tmp, ["apps/x/curated-pack-v2.jsonl"])), 0)


if __name__ == "__main__":
    unittest.main()
