"""Critic attack suite for dottie#91 @ ce30a3f4e73950fd0f0197da631b1739267822ac (B4a/B4b re-attack, S21).

r2 (2026-10-19, for 0ac51f7e): the test-fixture name apps/x/uncurated_package.py left the production
allowlist, so P2 no longer expects it to pass; P3 expects the real guard to REFUSE it (safe false positive).
Nothing else changed.

Every test asserts the SECURE behaviour; a FAIL is a finding.
M: token / trigger / secret surface in a NEW workflow file a PR could add (Forge's checks must go RED).
N: B4a regression - YAML escape / alias / tag spoofs (must stay RED).
O: every `uses:` in every workflow pinned to a 40-hex sha.
P: S21 path pattern - false negatives must be refused, legit names must pass (real guard, real shell).
Q: vendored loader accepts valid GitHub workflow YAML (fail-closed is safe; this measures friction).
Run:  WT=/workspace/review/dottie-91/wt-ce30 python3 -m unittest -v test_critic_91_ce30_r2
Read-only w.r.t. GitHub. Temp dirs prefixed critic-91-ce30-. No sockets.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

WT = Path(os.environ.get("WT", "/workspace/review/dottie-91/wt-ce30"))
os.environ["WT"] = str(WT)
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_critic_91_af2d as A  # noqa: E402

CI_TEXT = (WT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
P = "permissions:\n  contents: read\n"
H = "name: x\non:\n  pull_request:\n    branches: [main]\n" + P + "jobs:\n"
S = "    runs-on: ubuntu-latest\n    steps:\n      - run: echo ok\n"
J = H + "  b:\n    runs-on: ubuntu-latest\n    steps:\n"
PAT = "${{ secrets.MY_PAT }}"

M_MUST_RED = {
    "pull_request_target": "name: x\non: [pull_request_target]\n" + P + "jobs:\n  b:\n" + S,
    "workflow_run": "name: x\non:\n  workflow_run:\n    workflows: [CI]\n    types: [completed]\n" + P + "jobs:\n  b:\n" + S,
    "reusable_external_secrets_inherit": H + "  b:\n    uses: evil/r/.github/workflows/x.yml@main\n    secrets: inherit\n",
    "unpinned_third_party_action": J + "      - uses: evil/action@main\n",
    "github_script_with_pat": J + "      - uses: actions/github-script@v7\n        with:\n          github-token: " + PAT
        + "\n          script: github.rest.repos.createCommitStatus({owner:'o',repo:'r',sha:context.sha,state:'success',context:'pack-guard'})\n",
    "gh_cli_pat_env": J + "      - run: gh api repos/o/r/statuses/$GITHUB_SHA -f state=success -f context=pack-guard\n        env:\n          GH_TOKEN: " + PAT + "\n",
    "git_clone_embeds_token": J + "      - run: git clone https://x-access-token:${{ github.token }}@github.com/o/r\n",
    "checkout_mixed_case_persists": J + "      - uses: Actions/Checkout@v4\n",
    "job_Permissions_mixed_case": H + "  b:\n    Permissions:\n      checks: write\n" + S,
    "top_Permissions_mixed_case": "name: x\non: [pull_request]\n" + P + "Permissions: write-all\njobs:\n  b:\n" + S,
}
M_CONTROLS = {
    "new_wf_no_permissions": "name: x\non: [pull_request]\njobs:\n  b:\n" + S,
    "new_yaml_ext_no_permissions": ("zz.yaml", "name: x\non: [pull_request]\njobs:\n  b:\n" + S),
    "top_write_all": "name: x\non: [pull_request]\npermissions: write-all\njobs:\n  b:\n" + S,
    "top_permissions_empty_value": "name: x\non: [pull_request]\npermissions:\njobs:\n  b:\n" + S,
    "job_write_all": H + "  b:\n    permissions: write-all\n" + S,
    "job_actions_write": H + "  b:\n    permissions:\n      actions: write\n" + S,
    "job_id_token_write": H + "  b:\n    permissions:\n      id-token: write\n" + S,
    "job_pull_requests_write": H + "  b:\n    permissions:\n      pull-requests: write\n" + S,
    "job_pages_write": H + "  b:\n    permissions:\n      pages: write\n" + S,
    "job_checks_statuses_write": H + "  b:\n    permissions:\n      checks: write\n      statuses: write\n" + S,
    "job_contents_write": H + "  b:\n    permissions:\n      contents: write\n" + S,
    "job_quoted_permissions_key": H + "  b:\n    \"permissions\":\n      checks: write\n" + S,
    "checkout_persist_string_false": J + "      - uses: actions/checkout@v4\n        with:\n          persist-credentials: 'false'\n",
    "checkout_no_with": J + "      - uses: actions/checkout@" + "a" * 40 + "\n",
}
N_MUST_RED = {
    "dq_hex_escape_name": H + '  b:\n    name: "pack\\x2dguard"\n' + S,
    "dq_u4_escape_name": H + '  b:\n    name: "\\u0070ack-guard"\n' + S,
    "dq_U8_escape_name": H + '  b:\n    name: "pack\\U0000002dguard"\n' + S,
    "dq_hex_escape_job_id": H + '  "pack\\x2dguard":\n' + S,
    "dq_backslash_newline_name": H + '  b:\n    name: "pack\\\n      -guard"\n' + S,
    "alias_from_workflow_name": "name: &n pack-guard\non: [pull_request]\n" + P + "jobs:\n  b:\n    name: *n\n" + S,
    "alias_in_flow_job": "name: &n pack-guard\non: [pull_request]\n" + P + "jobs: {b: {name: *n, runs-on: ubuntu-latest, steps: [{run: echo}]}}\n",
    "anchor_in_seq_item": "name: x\non: [pull_request]\n" + P + "env:\n  L:\n    - &n pack-guard\njobs:\n  b:\n    name: *n\n" + S,
    "anchor_in_flow_seq": "name: x\non: [pull_request]\n" + P + "env: {L: [&n pack-guard]}\njobs:\n  b:\n    name: *n\n" + S,
    "verbatim_tag_then_anchor": "name: x\nenv:\n  N: !<tag:yaml.org,2002:str> &n pack-guard\non: [pull_request]\n" + P + "jobs:\n  b:\n    name: *n\n" + S,
    "tag_then_anchor": "name: !!str &n pack-guard\non: [pull_request]\n" + P + "jobs:\n  b:\n    name: *n\n" + S,
    "merge_key": "name: x\non: [pull_request]\n" + P + "x-base: &b\n  name: pack-guard\njobs:\n  b:\n    <<: *b\n" + S,
}
Q_VALID = {
    "unindented_sequence": J.replace("    steps:\n", "    steps:\n    - run: echo ok\n"),
    "plain_multiline_scalar": J + "      - run: echo one\n          two\n",
    "anchor_alias_in_env": "name: x\non: [pull_request]\n" + P + "env:\n  A: &a v\n  B: *a\njobs:\n  b:\n" + S,
    "multiline_flow_sequence": H + "  b:\n    runs-on: ubuntu-latest\n    strategy:\n      matrix:\n        py: [\n          '3.10',\n          '3.11'\n        ]\n    steps:\n      - run: echo\n",
    "dq_escape_in_run": J + "      - run: \"echo \\\"hi\\\"\\n\"\n",
    "doc_start_marker": "---\n" + H + "  b:\n" + S,
}

PROBE = r"""
import json, sys
from pathlib import Path
sys.modules["yaml"] = None
sys.path.insert(0, sys.argv[1] + "/apps/dottie-os/tests")
import test_ultradata_factory as T
root = Path(sys.argv[2]); ci = (root / ".github/workflows/ci.yml").read_text()
try:
    T._assert_pack_guard_check_name_unique(ci, root); T._assert_pack_guard_names_unique(root)
    T._assert_read_only_token_and_checkouts(ci, root)
    print(json.dumps("GREEN"))
except AssertionError as e:
    print(json.dumps("RED " + str(e)[:120]))
"""


def probe(body):
    fname, body = body if isinstance(body, tuple) else ("zz.yml", body)
    root = Path(tempfile.mkdtemp(prefix="critic-91-ce30-"))
    try:
        wf = root / ".github/workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(CI_TEXT, encoding="utf-8")
        (wf / fname).write_text(body, encoding="utf-8", newline="")
        o = subprocess.run([sys.executable, "-c", PROBE, str(WT), str(root)], capture_output=True, text=True)
        return json.loads(o.stdout.strip().splitlines()[-1]) if o.stdout.strip() else "ERR " + o.stderr[-160:]
    finally:
        shutil.rmtree(root, ignore_errors=True)


class _Cases(unittest.TestCase):
    def red(self, cases):
        for cid, body in cases.items():
            with self.subTest(case=cid):
                self.assertTrue(probe(body).startswith("RED"), f"{cid} accepted by Forge's workflow checks")


class M_NewWorkflowSurface(_Cases):
    def test_m1_new_workflow_risky_surface_red(self):
        self.red(M_MUST_RED)

    def test_m2_controls_red(self):
        self.red(M_CONTROLS)

    def test_m3_existing_workflows_read_only(self):
        for p in sorted((WT / ".github/workflows").glob("*.y*ml")):
            with self.subTest(wf=p.name):
                t = p.read_text()
                self.assertRegex(t, r"(?m)^permissions:\n  contents: read\n")
                for co in re.findall(r"uses: actions/checkout@\S+\n(?:        .*\n)*", t):
                    self.assertIn("persist-credentials: false", co)


class N_B4aRegression(_Cases):
    def test_n_escape_alias_tag_spoofs_red(self):
        self.red(N_MUST_RED)


class O_UsesPinned(unittest.TestCase):
    def test_o_every_uses_sha_pinned(self):
        bad = []
        for p in sorted((WT / ".github/workflows").glob("*.y*ml")):
            for i, l in enumerate(p.read_text().splitlines(), 1):
                m = re.match(r"^\s+(?:- )?uses:\s*['\"]?([^\s'\"#]+)", l)
                if m and not m.group(1).startswith("./") and not re.search(r"@[0-9a-f]{40}$", m.group(1)):
                    bad.append(f"{p.name}:{i} {m.group(1)}")
        self.assertEqual(bad, [])


P_MUST_CATCH = [
    "apps/x/curated_pack.jsonl", "apps/x/curatedpack.jsonl", "apps/x/curated.pack.jsonl", "apps/x/curated pack.jsonl",
    "apps/x/curated__pack.jsonl", "apps/x/curated/pack.jsonl", "apps/x/ultradata_harvest.jsonl",
    "apps/x/ultradata-harvest.jsonl", "scripts/ultradata_harvest_rows.jsonl",
    "apps/x/run_ultradata_harvest.jsonl", "scripts/run_ultradata_harvest.jsonl", "apps/dottie-os/scripts/lab/run_ultradata_harvest.jsonl",
    "apps/x/v2_ultradata_harvest.jsonl", "apps/x/x-ultradata-harvest.jsonl", "apps/x/mycurated_pack.jsonl",
    "apps/x/2curated_pack.jsonl", "apps/x/curated_packv2.jsonl", "apps/x/curatedpackrows.jsonl",
    "apps/x/curated+pack.jsonl", "apps/x/curated~pack.jsonl", "apps/x/curated,pack.jsonl", "apps/x/ultradata+harvest.jsonl",
]
P_MUST_PASS = ["docs/curated-packing-notes.md", "scripts/run_ultradata_harvest.py",
               "apps/dottie-os/scripts/lab/run_ultradata_harvest.py"]
P_TEST_ONLY_REFUSED = ["apps/x/uncurated_package.py"]  # r2: not in the production allowlist


class P_S21(unittest.TestCase):
    def _rc(self, name):
        r = Path(tempfile.mkdtemp(prefix="critic-91-ce30-"))
        try:
            return A.run_guard(A.mkrepo(r, [name]))
        finally:
            shutil.rmtree(r, ignore_errors=True)

    def test_p1_false_negatives(self):
        for n in P_MUST_CATCH:
            with self.subTest(path=n):
                self.assertNotEqual(self._rc(n), 0, f"{n!r} not refused")

    def test_p2_legit_names_pass(self):
        for n in P_MUST_PASS:
            with self.subTest(path=n):
                self.assertEqual(self._rc(n), 0, f"{n!r} refused")

    def test_p3_test_fixture_name_refused_in_prod(self):
        for n in P_TEST_ONLY_REFUSED:
            with self.subTest(path=n):
                self.assertNotEqual(self._rc(n), 0, f"{n!r} passes: test-only name still in the production allowlist")


class Q_LoaderFriction(unittest.TestCase):
    def test_q_valid_workflow_yaml_accepted(self):
        for cid, body in Q_VALID.items():
            with self.subTest(case=cid):
                self.assertEqual(probe(body), "GREEN", f"valid YAML {cid} rejected")


if __name__ == "__main__":
    unittest.main()
