"""Critic attack suite for dottie#91 @ 50d2e0f82e6f28a265858fc4e02f8dc262ccdfcb (B4 re-attack, S19-S21).

Every test asserts the SECURE behaviour; a FAIL is a finding.
H: uniqueness parser spoofs under the CI path (dottie-os-smoke: no PyYAML -> vendored loader).
   H1 = spoofs GitHub resolves to exactly `pack-guard` (must be RED); H2 = controls.
I: GITHUB_TOKEN scope - a check run / commit status named pack-guard can be POSTed by PR code.
J: CODEOWNERS location, precedence, last-match-wins, coverage of the guard's test process.
K: S19 env vectors against the real guard (step `run` under its real `shell:`).
L: S21 path regex false negatives / false positives against the real guard.
Run:  WT=/workspace/review/dottie-91/wt-50d2 python3 -m unittest -v test_critic_91_50d2
Optional parity: CRITIC_PYYAML_PY=/path/to/python-with-pyyaml re-runs H under PyYAML.
Read-only w.r.t. GitHub. Writes only temp dirs prefixed critic-91-50d2-. No sockets.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

WT = Path(os.environ.get("WT", "/workspace/review/dottie-91/wt-50d2"))
os.environ["WT"] = str(WT)
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_critic_91_af2d as A  # noqa: E402  (reuses mkrepo/run_guard/GUARD/SHELL)

CI_TEXT = (WT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
HDR = "name: x\non:\n  pull_request:\n    branches: [main]\njobs:\n"
STEPS = "    runs-on: ubuntu-latest\n    steps:\n      - run: echo ok\n"

# H1: GitHub (YAML 1.2 core + anchors/aliases, supported in Actions since 2025) resolves each
# of these to a job whose check-run name is exactly `pack-guard`.
REAL_SPOOFS = {
    "alias_from_workflow_name": "name: &n pack-guard\non: [pull_request]\njobs:\n  b:\n    name: *n\n" + STEPS,
    "alias_from_env_block": "name: x\nenv:\n  N: &n pack-guard\non: [pull_request]\njobs:\n  b:\n    name: *n\n" + STEPS,
    "dq_hex_escape_name": HDR + '  b:\n    name: "pack\\x2dguard"\n' + STEPS,
    "dq_u4_escape_name": HDR + '  b:\n    name: "\\u0070ack-guard"\n' + STEPS,
    "dq_U8_escape_name": HDR + '  b:\n    name: "pack\\U0000002dguard"\n' + STEPS,
    "dq_hex_escape_job_id": HDR + '  "pack\\x2dguard":\n' + STEPS,
    "dq_u4_escape_job_id": HDR + '  "\\u0070ack-guard":\n' + STEPS,
}
# H2: already refused at 50d2 (regression controls).
CONTROLS = {
    "anchor_inline_on_name": HDR + "  a:\n    name: &n pack-guard\n" + STEPS + "  b:\n    name: *n\n" + STEPS,
    "merge_key": "name: x\non: [pull_request]\nx-base: &b\n  name: pack-guard\njobs:\n  b:\n    <<: *b\n" + STEPS,
    "tag_str": HDR + "  b:\n    name: !!str pack-guard\n" + STEPS,
    "folded_block": HDR + "  b:\n    name: >-\n      pack-guard\n" + STEPS,
    "matrix_expr_name": HDR + "  b:\n    name: ${{ matrix.n }}\n    strategy:\n      matrix:\n        n: [pack-guard]\n" + STEPS,
    "reusable_caller_id": HDR + "  pack-guard:\n    uses: ./.github/workflows/r.yml\n",
    "dup_jobs_key": HDR + "  b:\n" + STEPS + "jobs:\n  c:\n" + STEPS,
    "dup_name_last_wins": HDR + "  b:\n    name: ok\n    name: pack-guard\n" + STEPS,
    "unparseable_fails_closed": "name: x\non: [pull_request\njobs: {\n",
    "complex_key": HDR + "  ? pack-guard\n  : runs-on: ubuntu-latest\n",
    "crlf": (HDR + "  b:\n    name: pack-guard\n" + STEPS).replace("\n", "\r\n"),
    "bom": "\ufeff" + HDR + "  b:\n    name: pack-guard\n" + STEPS,
    "flow_doc": "{name: x, on: [pull_request], jobs: {pack-guard: {runs-on: ubuntu-latest, steps: [{run: echo}]}}}\n",
    "yaml_ext": ("zz.yaml", HDR + "  pack-guard:\n" + STEPS),
}

PROBE = r"""
import json, sys
from pathlib import Path
if sys.argv[1] == "noyaml":
    sys.modules["yaml"] = None
sys.path.insert(0, sys.argv[2] + "/apps/dottie-os/tests")
import test_ultradata_factory as T
root = Path(sys.argv[3]); ci = (root / ".github/workflows/ci.yml").read_text()
try:
    T._assert_pack_guard_check_name_unique(ci, root); T._assert_pack_guard_names_unique(root)
    print(json.dumps("GREEN"))
except AssertionError as e:
    print(json.dumps("RED " + str(e)[:120]))
"""


def probe(body, fname="zz.yml", py=sys.executable, mode="noyaml"):
    root = Path(tempfile.mkdtemp(prefix="critic-91-50d2-"))
    try:
        wf = root / ".github/workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(CI_TEXT, encoding="utf-8")
        (wf / fname).write_text(body, encoding="utf-8", newline="")
        o = subprocess.run([py, "-c", PROBE, mode, str(WT), str(root)], capture_output=True, text=True)
        return json.loads(o.stdout.strip().splitlines()[-1]) if o.stdout.strip() else "ERR " + o.stderr[-160:]
    finally:
        shutil.rmtree(root, ignore_errors=True)


class H_ParserSpoofs(unittest.TestCase):
    def _run(self, cases, py=sys.executable, mode="noyaml"):
        for cid, body in cases.items():
            fname, body = body if isinstance(body, tuple) else ("zz.yml", body)
            with self.subTest(case=cid):
                self.assertTrue(probe(body, fname, py, mode).startswith("RED"), f"{cid} accepted by Forge's uniqueness check")

    def test_h1_real_spoofs_red_ci_loader(self):
        self._run(REAL_SPOOFS)

    def test_h2_controls_red_ci_loader(self):
        self._run(CONTROLS)

    @unittest.skipUnless(os.environ.get("CRITIC_PYYAML_PY"), "set CRITIC_PYYAML_PY for PyYAML parity")
    def test_h3_real_spoofs_red_pyyaml(self):
        self._run(REAL_SPOOFS, os.environ["CRITIC_PYYAML_PY"], "yaml")

    def test_h4_ci_path_has_no_pyyaml(self):
        # dottie-os-smoke = setup-python 3.11 + pip install cryptography only -> vendored loader is the CI path.
        job = A.job_text(CI_TEXT, "dottie-os-smoke")
        self.assertNotIn("pyyaml", job.lower(), "if PyYAML were installed H1 would be moot; it is not")


def jobs_with_checkout(text):
    out = {}
    for m in re.finditer(r"^  ([A-Za-z0-9_-]+):\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)", text.split("\njobs:\n", 1)[1], re.M | re.S):
        out[m.group(1)] = m.group(2)
    return out


class I_TokenScope(unittest.TestCase):
    """A check run / commit status named `pack-guard` can be created with the job's GITHUB_TOKEN
    (it is attributed to the github-actions app, so pinning the required check to the Actions
    app does NOT stop it). PR-controlled code in dottie-os-smoke runs after a checkout that
    persists the token in .git/config. Only a read-only token closes this."""

    def test_i1_every_workflow_read_only_token(self):
        bad = []
        for p in sorted((WT / ".github/workflows").glob("*.y*ml")):
            t = p.read_text(encoding="utf-8")
            m = re.search(r"^permissions:\s*(.*?)(?=^\S)", t, re.M | re.S)
            if not m or re.search(r"\bwrite\b|write-all", m.group(1)) or m.group(1).strip() in ("", "{}") and "permissions: {}" not in t:
                bad.append(p.name)
        self.assertEqual(bad, [], "workflows inherit the repo-default token scope (checks/statuses may be write)")

    def test_i2_repo_code_jobs_do_not_persist_token(self):
        bad = []
        for job, body in jobs_with_checkout(CI_TEXT).items():
            if "actions/checkout@" in body and "persist-credentials: false" not in body:
                bad.append(job)
        self.assertEqual(bad, [], "checkout persists GITHUB_TOKEN in .git/config for PR-controlled code")


def co_rules():
    rules = []
    for l in (WT / ".github/CODEOWNERS").read_text().splitlines():
        if l.strip() and not l.lstrip().startswith("#"):
            pat, *owners = l.split()
            rules.append((pat, owners))
    return rules


def co_match(pat, path):
    anchored = pat.startswith("/")
    p = pat.lstrip("/")
    if p.endswith("/"):
        return path.startswith(p) if anchored or "/" in p.rstrip("/") else ("/" + path).find("/" + p) >= 0
    if "/" in p.rstrip("/") or anchored:
        return fnmatch.fnmatchcase(path, p) or path.startswith(p + "/")
    return any(fnmatch.fnmatchcase(seg, p) for seg in path.split("/"))


def owner_of(path):
    own = None
    for pat, owners in co_rules():  # last match wins
        if co_match(pat, path):
            own = owners
    return own


class J_Codeowners(unittest.TestCase):
    def test_j1_single_codeowners_in_dot_github(self):
        # GitHub precedence: .github/ > root > docs/; first found wins, base-branch copy is used for review.
        found = [str(p.relative_to(WT)) for p in (WT / ".github/CODEOWNERS", WT / "CODEOWNERS", WT / "docs/CODEOWNERS") if p.exists()]
        self.assertEqual(found, [".github/CODEOWNERS"])

    def test_j2_protected_paths_last_match_cam(self):
        for path in (".github/CODEOWNERS", ".github/workflows/ci.yml", ".github/workflows/zz-new.yaml",
                     ".github/actions/x/action.yml", "apps/dottie-os/tests/test_ultradata_factory.py",
                     "apps/dottie-os/tests/test_critic_91_af2d.py", "apps/dottie-os/trust/cam_pin_key_id"):
            with self.subTest(path=path):
                self.assertEqual(owner_of(path), ["@jcdavis131"])

    def test_j3_guard_test_process_fully_owned(self):
        # dottie-os-smoke runs `unittest discover -s apps/dottie-os/tests`: every module there shares
        # the process with TrackedPackArtifactGuardTests and can monkeypatch it before it runs.
        for path in ("apps/dottie-os/tests/ed25519_torsion_vectors.py", "apps/dottie-os/tests/fixtures/x.json",
                     "apps/dottie-os/tests/test_aaa_new.py", "apps/dottie-os/tests/__init__.py"):
            with self.subTest(path=path):
                self.assertEqual(owner_of(path), ["@jcdavis131"])

    def test_j4_new_test_module_can_neuter_uniqueness(self):
        """Live demo in WT: a spoof workflow + an unowned test_aaa_*.py that no-ops the check."""
        wf = WT / ".github/workflows/zz-critic-50d2.yml"
        pr = WT / "apps/dottie-os/tests/test_aaa_critic_50d2_probe.py"
        try:
            wf.write_text(HDR + "  b:\n    name: pack-guard\n" + STEPS)
            # Hide only the attacker's own file; Forge's red self-mutations keep working, so nothing else goes red.
            pr.write_text("import test_ultradata_factory as T\n_o = T._workflow_yaml_paths\n"
                          "T._workflow_yaml_paths = lambda root: [p for p in _o(root) if p.name != 'zz-critic-50d2.yml']\n")
            o = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "apps/dottie-os/tests",
                                "-p", "test_[au]*.py", "-k", "TrackedPackArtifactGuardTests"],
                               cwd=WT, capture_output=True, text=True)
            self.assertNotEqual(o.returncode, 0, "spoof workflow passes once an unowned test module patches the check")
        finally:
            wf.unlink(missing_ok=True)
            pr.unlink(missing_ok=True)

    def test_j5_vendored_suites_are_hash_checked(self):
        # test_critic_91_*_suite_is_vendored only asserts the sha string appears in a comment.
        src = (WT / "apps/dottie-os/tests/test_ultradata_factory.py").read_text()
        body = src.split("def test_critic_91_af2d_suite_is_vendored", 1)[1].split("\n    def ", 1)[0]
        self.assertRegex(body, r"sha256\(|hashlib", "vendored-suite test never hashes the file")


ENV_VECTORS = None


class K_EnvVectors(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="critic-91-50d2-"))
        ev = self.tmp / "evil"
        ev.mkdir()
        for b in ("git", "grep", "python3", "env", "bash"):
            (ev / b).write_text("#!/bin/sh\nexit 0\n")
            (ev / b).chmod(0o755)
        (self.tmp / "be.sh").write_text("exit 0\n")
        pp = self.tmp / "pp"
        pp.mkdir()
        (pp / "sitecustomize.py").write_text("import os; os._exit(0)\n")
        (pp / "re.py").write_text("import os; os._exit(0)\n")
        (self.tmp / "gc").write_text("[core]\n\tfsmonitor = /bin/true\n")
        self.v = {"BASH_ENV": f"{self.tmp}/be.sh", "ENV": f"{self.tmp}/be.sh", "PATH": f"{ev}:/usr/bin:/bin",
                  "PYTHONPATH": str(pp), "PYTHONHOME": str(pp), "PYTHONSTARTUP": f"{self.tmp}/be.sh",
                  "LD_PRELOAD": "/nonexistent-critic.so", "LD_LIBRARY_PATH": str(ev), "GIT_DIR": "/nonexistent",
                  "GIT_INDEX_FILE": "/dev/null", "GIT_WORK_TREE": "/tmp", "GIT_CONFIG_PARAMETERS": "'core.fsmonitor=/bin/true'",
                  "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": "/tmp",
                  "GIT_CONFIG_GLOBAL": f"{self.tmp}/gc", "GIT_OBJECT_DIRECTORY": "/nonexistent",
                  "GIT_ALTERNATE_OBJECT_DIRECTORIES": "/tmp", "GIT_NAMESPACE": "x", "GIT_EXEC_PATH": str(ev),
                  "HOME": str(self.tmp), "XDG_CONFIG_HOME": str(self.tmp), "IFS": "x", "CDPATH": "/tmp",
                  "GLOBIGNORE": "*", "POSIXLY_CORRECT": "1", "LC_ALL": "tr_TR.UTF-8", "GREP_OPTIONS": "-v"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_k_env_vectors_pack_still_refused(self):
        for k, val in self.v.items():
            with self.subTest(var=k):
                r = Path(tempfile.mkdtemp(prefix="critic-91-50d2-"))
                try:
                    self.assertNotEqual(A.run_guard(A.mkrepo(r, [A.PACK]), {k: val}), 0)
                finally:
                    shutil.rmtree(r, ignore_errors=True)


S21_MUST_CATCH = ["apps/x/curatedpack.jsonl", "apps/x/CURATED_PACK_v2.jsonl", "apps/x/Curated-Packs.JSONL",
                  "curated_pack/rows.jsonl", "a/b/c/d/e/f/curated-pack.jsonl", "apps/x/curated\u2013pack.jsonl",
                  "apps/x/\uff43urated_pack.jsonl", "apps/x/ultradata_harvest_v1.jsonl",
                  "apps/x/curated.pack.jsonl", "apps/x/curated pack.jsonl", "apps/x/curated__pack.jsonl",
                  "apps/x/ultradata_harvest.jsonl", "apps/x/ultradata-harvest.jsonl", "apps/x/curated/pack.jsonl"]
S21_MUST_PASS = ["docs/curated-packing-notes.md", "apps/x/uncurated_package.py", "scripts/run_ultradata_harvest.py"]


class L_S21Regex(unittest.TestCase):
    def _rc(self, name):
        r = Path(tempfile.mkdtemp(prefix="critic-91-50d2-"))
        try:
            return A.run_guard(A.mkrepo(r, [name]))
        finally:
            shutil.rmtree(r, ignore_errors=True)

    def test_l1_false_negatives(self):
        for n in S21_MUST_CATCH:
            with self.subTest(path=n):
                self.assertNotEqual(self._rc(n), 0, f"{n!r} not refused")

    def test_l2_false_positives(self):
        for n in S21_MUST_PASS:
            with self.subTest(path=n):
                self.assertEqual(self._rc(n), 0, f"{n!r} refused (legit name)")


if __name__ == "__main__":
    unittest.main()
