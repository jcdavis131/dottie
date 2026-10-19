"""Critic attack suite for dottie#91 @ f8f1911681672a70db1570d26942bdb7af7133d0 (S21/S24/S25 re-attack).

Every test asserts the SECURE behaviour; a FAIL is a finding.
R: secrets / token reachable outside step `with:`/`env:` (workflow env, job env, reusable secrets/with,
   container/services, if:, run-name, expression variants) -> Forge's workflow checks must go RED.
T: trigger allowlist + local actions outside .github/ (unowned composite code).
C: controls already RED at f8f1 (regression).
U: allowlisted action shas == the official tag commits (verified via `git ls-remote`, 2026-10-19).
V: content-level pack evasions against the real guard (name-based guard is blind to these).
W: S21 unicode / NFKC / homoglyph / allowlist-neighbour controls (must stay refused).
Run:  WT=/workspace/review/dottie-91/wt-f8f1 python3 -m unittest -v test_critic_91_f8f1
Read-only w.r.t. GitHub. Temp dirs prefixed critic-91-f8f1-. No sockets.
"""
from __future__ import annotations

import gzip
import io
import os
import re
import shutil
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

WT = Path(os.environ.get("WT", "/workspace/review/dottie-91/wt-f8f1"))
os.environ["WT"] = str(WT)
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_critic_91_af2d as A  # noqa: E402
import test_critic_91_ce30 as C  # noqa: E402  (probe(): runs Forge's 3 workflow checks on a temp root)

P, H, S, J = C.P, C.H, C.S, C.J
PAT = "${{ secrets.MY_PAT }}"
CO = "      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683\n        with:\n          persist-credentials: false\n"
RUN_REPO = "      - run: python3 apps/x/post.py\n"

R_MUST_RED = {
    "workflow_env_secret": "name: x\non: [pull_request]\n" + P + "env:\n  T: " + PAT + "\njobs:\n  b:\n    runs-on: ubuntu-latest\n    steps:\n" + CO + RUN_REPO,
    "job_env_secret": H + "  b:\n    runs-on: ubuntu-latest\n    env:\n      T: " + PAT + "\n    steps:\n" + CO + RUN_REPO,
    "reusable_secrets_map": H + "  b:\n    uses: ./.github/workflows/r.yml\n    secrets:\n      T: " + PAT + "\n",
    "reusable_with_secret": H + "  b:\n    uses: ./.github/workflows/r.yml\n    with:\n      t: " + PAT + "\n",
    "container_credentials_secret": H + "  b:\n    runs-on: ubuntu-latest\n    container:\n      image: alpine\n      credentials:\n        password: " + PAT + "\n    steps:\n      - run: echo\n",
    "services_env_secret": H + "  b:\n    runs-on: ubuntu-latest\n    services:\n      s:\n        image: alpine\n        env:\n          T: " + PAT + "\n    steps:\n      - run: echo\n",
    "job_if_secret": H + "  b:\n    if: ${{ secrets.MY_PAT != '' }}\n" + S,
    "run_name_secret": "name: x\nrun-name: " + PAT + "\non: [pull_request]\n" + P + "jobs:\n  b:\n" + S,
    "toJSON_secrets": H + "  b:\n    runs-on: ubuntu-latest\n    env:\n      ALL: ${{ toJSON(secrets) }}\n    steps:\n" + RUN_REPO,
    "secrets_index_syntax": J + "      - run: python3 x.py\n        env:\n          T: ${{ secrets['MY_PAT'] }}\n",
    "secrets_paren_expr": J + "      - run: python3 x.py\n        env:\n          T: ${{ (secrets).MY_PAT }}\n",
    "secrets_in_format": J + "      - run: python3 x.py\n        env:\n          T: ${{ format('{0}', secrets.MY_PAT) }}\n",
    "workflow_env_github_token": "name: x\non: [pull_request]\n" + P + "env:\n  GH_TOKEN: ${{ github.token }}\njobs:\n  b:\n    runs-on: ubuntu-latest\n    steps:\n" + RUN_REPO,
    "github_index_token": J + "      - run: python3 x.py\n        env:\n          T: ${{ github['token'] }}\n",
}
T_MUST_RED = {
    "trigger_issue_comment": "name: x\non: [issue_comment]\n" + P + "jobs:\n  b:\n" + S,
    "trigger_repository_dispatch": "name: x\non: [repository_dispatch]\n" + P + "jobs:\n  b:\n" + S,
    "trigger_pull_request_review": "name: x\non: [pull_request_review]\n" + P + "jobs:\n  b:\n" + S,
    "local_action_outside_dot_github": J + "      - uses: ./apps/x\n",
}
C_CONTROLS = {
    "step_env_secret": J + "      - run: python3 x.py\n        env:\n          T: " + PAT + "\n",
    "secret_no_space": J + "      - run: python3 x.py\n        env:\n          T: ${{secrets.MY_PAT}}\n",
    "curl_api_token": J + "      - run: curl -H \"Authorization: Bearer ${{ github.token }}\" https://api.github.com/repos/o/r/statuses/x\n",
    "docker_tag": J + "      - uses: docker://alpine:3\n",
    "docker_digest": J + "      - uses: docker://alpine@sha256:" + "a" * 64 + "\n",
    "allowlisted_sha_other_repo": J + "      - uses: evil/checkout@11bd71901bbe5b1630ceea73d27597364c9af683\n",
    "allowlisted_sha_subpath": J + "      - uses: actions/checkout/sub@11bd71901bbe5b1630ceea73d27597364c9af683\n",
    "On_mixed_case": "name: x\nOn: [pull_request_target]\n" + P + "jobs:\n  b:\n" + S,
    "on_quoted_prt": "name: x\n\"on\": [pull_request_target]\n" + P + "jobs:\n  b:\n" + S,
    "on_flow_prt": "name: x\non: {pull_request_target: {branches: [main]}}\n" + P + "jobs:\n  b:\n" + S,
    "trigger_mixed_case": "name: x\non: [Pull_Request_Target]\n" + P + "jobs:\n  b:\n" + S,
}


class _Cases(unittest.TestCase):
    def red(self, cases):
        for cid, body in cases.items():
            with self.subTest(case=cid):
                self.assertTrue(C.probe(body).startswith("RED"), f"{cid} accepted by Forge's workflow checks")


class R_SecretsOutsideSteps(_Cases):
    def test_r_secret_and_token_surface_red(self):
        self.red(R_MUST_RED)


class T_TriggersAndLocalActions(_Cases):
    def test_t_trigger_allowlist_and_local_actions_red(self):
        self.red(T_MUST_RED)


class C_Controls(_Cases):
    def test_c_controls_red(self):
        self.red(C_CONTROLS)


VERIFIED = {  # git ls-remote, 2026-10-19 03:5x CT
    "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683": "refs/tags/v4.2.2",
    "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065": "refs/tags/v5 = v5.6.0",
    "astral-sh/setup-uv@d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86": "refs/tags/v5.4.2^{}",
}


class U_Pins(unittest.TestCase):
    def test_u1_every_uses_is_a_verified_official_pin(self):
        bad = []
        for p in sorted((WT / ".github/workflows").glob("*.y*ml")):
            for i, l in enumerate(p.read_text().splitlines(), 1):
                m = re.match(r"^\s+(?:- )?uses:\s*['\"]?([^\s'\"#]+)", l)
                if m and not m.group(1).startswith("./") and m.group(1) not in VERIFIED:
                    bad.append(f"{p.name}:{i} {m.group(1)}")
        self.assertEqual(bad, [])

    def test_u2_allowlist_equals_verified_set(self):
        sys.path.insert(0, str(WT / "apps/dottie-os/tests"))
        sys.modules.setdefault("yaml", None)  # type: ignore[arg-type]
        import test_ultradata_factory as T
        self.assertEqual(set(T.PACK_GUARD_ALLOWED_USES), set(VERIFIED))


def _repo(prep):
    t = Path(tempfile.mkdtemp(prefix="critic-91-f8f1-"))
    r = A.mkrepo(t, ["README"])
    (r / "apps/x").mkdir(parents=True, exist_ok=True)
    prep(r)
    A.git(r, "add", "-f", "-A")
    A.git(r, "commit", "-qm", "evasion")
    return t, r


def _zip(r):
    with zipfile.ZipFile(r / "apps/x/rows.zip", "w") as f:
        f.writestr("curated_pack_v2.jsonl", "{}\n")


def _tar(r):
    with tarfile.open(r / "apps/x/rows.tar", "w") as f:
        b = b"{}\n"
        ti = tarfile.TarInfo("curated_pack_v2.jsonl")
        ti.size = len(b)
        f.addfile(ti, io.BytesIO(b))


LFS = "version https://git-lfs.github.com/spec/v1\noid sha256:" + "a" * 64 + "\nsize 999999\n"
V_EVASIONS = {
    "zip_containing_pack": _zip,
    "tar_containing_pack": _tar,
    "gzip_neutral_name": lambda r: (r / "apps/x/rows.jsonl.gz").write_bytes(gzip.compress(b'{"curated_pack":1}\n')),
    "lfs_pointer_neutral_name": lambda r: (r / "apps/x/rows.bin").write_text(LFS),
    "pack_rows_in_neutral_jsonl": lambda r: (r / "apps/x/rows.jsonl").write_text('{"source":"curated_pack_v2","decision":"halt"}\n' * 50),
    "symlink_to_pack_path": lambda r: os.symlink("../../data/curated_pack_v2.jsonl", r / "apps/x/rows.jsonl"),
}


class V_ContentEvasions(unittest.TestCase):
    def test_v_content_level_evasions_refused(self):
        for cid, prep in V_EVASIONS.items():
            with self.subTest(case=cid):
                t, r = _repo(prep)
                try:
                    self.assertNotEqual(A.run_guard(r), 0, f"{cid} passes the name-based guard")
                finally:
                    shutil.rmtree(t, ignore_errors=True)

    def test_v_gitlink_neutral_name_refused(self):
        t = Path(tempfile.mkdtemp(prefix="critic-91-f8f1-"))
        try:
            r = A.mkrepo(t, ["README"])
            A.git(r, "update-index", "--add", "--cacheinfo", "160000," + "b" * 40 + ",apps/x/vendor")
            A.git(r, "commit", "-qm", "gitlink")
            self.assertNotEqual(A.run_guard(r), 0, "untracked-content gitlink passes")
        finally:
            shutil.rmtree(t, ignore_errors=True)


W_MUST_REFUSE = [
    "apps/x/\uff43\uff55\uff52\uff41\uff54\uff45\uff44_pack.jsonl", "apps/x/\U0001d41c\U0001d42e\U0001d42b\U0001d41a\U0001d42d\U0001d41e\U0001d41d_pack.jsonl",
    "apps/x/\u0441urated_pack.jsonl", "apps/x/curated_p\u0430ck.jsonl", "apps/x/curated\u200b_pack.jsonl", "apps/x/cura\u0301ted_pack.jsonl",
    ".gitx/curated_pack.jsonl", "apps/x/uncurated_package.py.jsonl", "Apps/x/uncurated_package.py", "docs/curated-packing-notes.md/rows.jsonl",
    "apps/curated/pack.jsonl",
]


class W_S21Controls(unittest.TestCase):
    def test_w_unicode_and_allowlist_neighbours_refused(self):
        for n in W_MUST_REFUSE:
            with self.subTest(path=n):
                t = Path(tempfile.mkdtemp(prefix="critic-91-f8f1-"))
                try:
                    self.assertNotEqual(A.run_guard(A.mkrepo(t, [n])), 0)
                finally:
                    shutil.rmtree(t, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
