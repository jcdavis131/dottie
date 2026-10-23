"""Critic attack suite for dottie#91 @ 0b05ffc836206864573c91691c3d108bc8ed9cd2 (S24 file-wide expr / S26 content re-attack).

Every test asserts the SECURE behaviour; a FAIL is a finding.
X: S24 expression-level bypasses of the file-wide `${{ }}` scan (quote-aware end, whole-context dumps,
   dynamic index, YAML escapes that rebuild `${{`).
Y: S24 trigger / key-shadowing / local-action / docker-image surface.
Z: S24 controls Forge closed at 0b05 (must stay RED) and normal workflows that must stay GREEN.
K: S26 content evasions against the real guard (real shell, real git).
L: S26 allowlist entries skip the S26 content checks.
M: S26 controls (must stay refused) and legit trees that must pass (over-refusal).
N: production pack-guard allowlist must not contain the Critic test-fixture path.
Run:  WT=/workspace/review/dottie-91/wt-0b05 python3 -m unittest -v test_critic_91_0b05
Read-only w.r.t. GitHub. Temp dirs prefixed critic-91-0b05-. No sockets. No holdout/N rows used.
"""
from __future__ import annotations

import base64
import gzip
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

WT = Path(os.environ.get("WT", "/workspace/review/dottie-91/wt-0b05"))
os.environ["WT"] = str(WT)
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_critic_91_af2d as A  # noqa: E402
import test_critic_91_ce30 as C  # noqa: E402

P, H, S, J = C.P, C.H, C.S, C.J
CI_TEXT = (WT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
CO_SHA = "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683"
RUN_REPO = "      - run: python3 apps/x/post.py\n"


def probe(body, files=None):
    """Forge's workflow checks on a temp root holding real ci.yml + one new workflow + extra files."""
    root = Path(tempfile.mkdtemp(prefix="critic-91-0b05-"))
    try:
        wf = root / ".github/workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(CI_TEXT, encoding="utf-8")
        (wf / "zz.yml").write_text(body, encoding="utf-8", newline="")
        for rel, txt in (files or {}).items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(txt, tuple) and txt[0] == "symlink":
                os.symlink(txt[1], p)
            else:
                p.write_text(txt, encoding="utf-8")
        o = subprocess.run([sys.executable, "-c", C.PROBE, str(WT), str(root)], capture_output=True, text=True)
        return json.loads(o.stdout.strip().splitlines()[-1]) if o.stdout.strip() else "ERR " + o.stderr[-160:]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def jenv(expr):
    """job-level env carrying an expression; a later repo-code step reads it."""
    return H + "  b:\n    runs-on: ubuntu-latest\n    env:\n      T: " + expr + "\n    steps:\n" + RUN_REPO


# --- X: expression-level bypasses (all reach the token / a secret) ---------------------------
X_MUST_RED = {
    # actions/runner TemplateReader ends ${{ }} at the first `}}` OUTSIDE a '...' string; the guard's
    # PACK_GUARD_EXPR_RE `\$\{\{(.*?)\}\}` ends at the first `}}` anywhere, so `secrets` falls outside.
    "quoted_close_then_secret_and": jenv("${{ '}}' && secrets.MY_PAT }}"),
    "quoted_close_in_format": jenv("${{ format('}}{0}', secrets.MY_PAT) }}"),
    "quoted_close_then_token": jenv("${{ '}}' && github.token }}"),
    # whole github context contains .token (GitHub docs warn about toJSON(github))
    "toJSON_github": jenv("${{ toJSON(github) }}"),
    "fromJSON_toJSON_github_token": jenv("${{ fromJSON(toJSON(github)).token }}"),
    "github_star_filter": jenv("${{ join(github.*, ' ') }}"),
    "github_dynamic_index": jenv("${{ github[format('{0}oken', 't')] }}"),
    # YAML double-quoted escapes rebuild `${{` after parsing; raw-text scan never sees it
    "dq_hex_escape_dollar_brace": jenv('"$\\x7B{ secrets.MY_PAT }}"'),
    "dq_u4_escape_dollar": jenv('"\\u0024{{ secrets.MY_PAT }}"'),
}

# --- Y: trigger / key / local-action / docker surface -----------------------------------------
ACT = ".github/actions/a/action.yml"
Y_MUST_RED = {
    # local docker action under .github with an unpinned image: never goes through _assert_one_uses
    "local_docker_action_unpinned_image": (J + "      - uses: ./.github/actions/a\n",
                                           {ACT: "name: a\nruns:\n  using: docker\n  image: docker://alpine:latest\n"}),
    # local node action under .github whose entry point is unowned repo code outside .github/
    "local_node_action_main_outside_dot_github": (J + "      - uses: ./.github/actions/a\n",
                                                  {ACT: "name: a\nruns:\n  using: node20\n  main: ../../../apps/x/index.js\n",
                                                   "apps/x/index.js": "//\n"}),
    # github.event.* attacker-controlled text interpolated into a shell (script injection)
    "event_title_into_run": (J + "      - run: echo \"${{ github.event.pull_request.title }}\"\n", {}),
    "head_ref_into_run": (J + "      - run: git log ${{ github.head_ref }}\n", {}),
}

# --- Z: controls (must stay RED) and normal workflows (must stay GREEN) ------------------------
Z_CONTROLS_RED = {
    # loader refuses any mixed-case key, so `On`/`on` shadowing and `Uses:` cannot reach the checks
    "On_then_on_shadow": ("name: x\nOn: [push]\non: [issue_comment]\n" + P + "jobs:\n  b:\n" + S, {}),
    "quoted_On_then_on_shadow": ("name: x\n\"On\": [push]\non: [workflow_run]\n" + P + "jobs:\n  b:\n" + S, {}),
    "step_Uses_mixed_case_outside_dot_github": (J + "      - Uses: ./apps/x\n", {}),
    "dq_escaped_linebreak_split": H + "  b:\n    runs-on: ubuntu-latest\n    env:\n      T: \"$\\\n        {{ secrets.MY_PAT }}\"\n    steps:\n" + RUN_REPO,
    "workflow_env_secret": ("name: x\non: [pull_request]\n" + P + "env:\n  T: ${{ secrets.MY_PAT }}\njobs:\n  b:\n" + S, {}),
    "multiline_expr": (jenv("${{\n        secrets.MY_PAT\n        }}") if False else
                       H + "  b:\n    runs-on: ubuntu-latest\n    env:\n      T: >-\n        ${{\n        secrets.MY_PAT }}\n    steps:\n" + RUN_REPO, {}),
    "block_scalar_expr": (J + "      - run: |\n          echo ${{ secrets.MY_PAT }}\n", {}),
    "anchor_carries_expr": ("name: x\non: [pull_request]\n" + P + "x-a: &a ${{ secrets.MY_PAT }}\njobs:\n  b:\n    runs-on: ubuntu-latest\n    env:\n      T: *a\n    steps:\n" + RUN_REPO, {}),
    "merge_key_carries_expr": ("name: x\non: [pull_request]\n" + P + "x-e: &e\n  T: ${{ secrets.MY_PAT }}\njobs:\n  b:\n    runs-on: ubuntu-latest\n    env:\n      <<: *e\n    steps:\n" + RUN_REPO, {}),
    "SECRETS_upper": (jenv("${{ SECRETS.MY_PAT }}"), {}),
    "github_index_ws_case": (jenv("${{ github[ 'TOKEN' ] }}"), {}),
    "env_GITHUB_TOKEN": (jenv("${{ env.GITHUB_TOKEN }}"), {}),
    "trigger_flow_seq": ("name: x\non: [push, issue_comment]\n" + P + "jobs:\n  b:\n" + S, {}),
    "trigger_flow_map_quoted": ("name: x\non: {\"pull_request_target\": {}}\n" + P + "jobs:\n  b:\n" + S, {}),
    "trigger_scalar_quoted": ("name: x\non: 'workflow_call'\n" + P + "jobs:\n  b:\n" + S, {}),
    "trigger_list_of_maps": ("name: x\non:\n  - push\n  - issue_comment: {}\n" + P + "jobs:\n  b:\n" + S, {}),
    "trigger_empty": ("name: x\non:\n" + P + "jobs:\n  b:\n" + S, {}),
    "uses_dot_github_dotdot": (J + "      - uses: ./.github/../apps/x\n", {"apps/x/action.yml": "name: a\nruns:\n  using: composite\n  steps: []\n"}),
    "uses_deep_dotdot": (J + "      - uses: ./.github/actions/../../apps/x\n", {"apps/x/action.yml": "name: a\nruns:\n  using: composite\n  steps: []\n"}),
    "uses_githubx_prefix": (J + "      - uses: ./.githubx/a\n", {".githubx/a/action.yml": "name: a\nruns:\n  using: composite\n  steps: []\n"}),
    "uses_backslash_dotdot": (J + "      - uses: .\\.github\\..\\apps\\x\n", {}),
    "uses_repo_root": (J + "      - uses: ./\n", {"action.yml": "name: a\nruns:\n  using: composite\n  steps: []\n"}),
    "composite_scanned_token": (J + "      - uses: ./.github/actions/a\n",
                                {ACT: "name: a\nruns:\n  using: composite\n  steps:\n    - run: echo\n      shell: bash\n      env:\n        T: ${{ github.token }}\n"}),
    "composite_input_default_token": (J + "      - uses: ./.github/actions/a\n",
                                      {ACT: "name: a\ninputs:\n  t:\n    default: ${{ github.token }}\nruns:\n  using: composite\n  steps: []\n"}),
    "nested_composite_escapes": (J + "      - uses: ./.github/actions/a\n",
                                 {ACT: "name: a\nruns:\n  using: composite\n  steps:\n    - uses: ./.github/actions/b\n",
                                  ".github/actions/b/action.yml": "name: b\nruns:\n  using: composite\n  steps:\n    - uses: ./apps/x\n"}),
    "nested_composite_third_party": (J + "      - uses: ./.github/actions/a\n",
                                     {ACT: "name: a\nruns:\n  using: composite\n  steps:\n    - uses: evil/x@" + "a" * 40 + "\n"}),
    "github_script_pinned": (J + "      - uses: actions/github-script@" + "a" * 40 + "\n        with:\n          script: core.info('x')\n", {}),
    "secrets_inherit_two_spaces": (H + "  b:\n    uses: ./.github/workflows/r.yml\n    secrets:  inherit\n",
                                   {".github/workflows/r.yml": "name: r\non: [push]\n" + P + "jobs:\n  b:\n" + S}),
}
Z_MUST_GREEN = {
    "normal_matrix_sha_hashfiles": (
        "name: x\non:\n  push:\n    branches: [main]\n  pull_request: {}\n  workflow_dispatch: {}\n" + P + "jobs:\n  b:\n"
        "    runs-on: ubuntu-latest\n    strategy:\n      matrix:\n        py: ['3.11', '3.12']\n    steps:\n"
        "      - uses: " + CO_SHA + "\n        with:\n          persist-credentials: false\n"
        "      - run: echo ${{ matrix.py }} ${{ github.sha }} ${{ hashFiles('**/requirements.txt') }}\n", {}),
    "schedule_only": ("name: x\non:\n  schedule:\n    - cron: '0 3 * * *'\n" + P + "jobs:\n  b:\n" + S, {}),
    "local_composite_clean": (J + "      - uses: ./.github/actions/a\n",
                              {ACT: "name: a\nruns:\n  using: composite\n  steps:\n    - run: echo ${{ github.sha }}\n      shell: bash\n"}),
}


class _Cases(unittest.TestCase):
    def red(self, cases):
        for cid, case in cases.items():
            body, files = case if isinstance(case, tuple) else (case, {})
            with self.subTest(case=cid):
                self.assertTrue(probe(body, files).startswith("RED"), f"{cid} accepted by Forge's workflow checks")


class X_ExpressionBypasses(_Cases):
    def test_x_expression_bypasses_red(self):
        self.red(X_MUST_RED)


class Y_SurfaceBypasses(_Cases):
    def test_y_trigger_key_local_action_surface_red(self):
        self.red(Y_MUST_RED)


class Z_S24Controls(_Cases):
    def test_z1_closed_cases_stay_red(self):
        self.red(Z_CONTROLS_RED)

    def test_z2_normal_workflows_green(self):
        for cid, (body, files) in Z_MUST_GREEN.items():
            with self.subTest(case=cid):
                self.assertEqual(probe(body, files), "GREEN")

    def test_z3_baseline_real_workflows_green(self):
        self.assertEqual(probe(H + "  b:\n" + S), "GREEN")


# --- S26 against the real guard -----------------------------------------------------------------
def _zip_bytes():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as f:
        f.writestr("rows.jsonl", '{"k":1}\n' * 20)
    return b.getvalue()


def _v7_tar_bytes():
    b = io.BytesIO()
    with tarfile.open(fileobj=b, mode="w", format=tarfile.USTAR_FORMAT) as f:
        d = b'{"k":1}\n' * 20
        ti = tarfile.TarInfo("rows.jsonl")
        ti.size = len(d)
        f.addfile(ti, io.BytesIO(d))
    raw = bytearray(b.getvalue())
    raw[257:265] = b"\0" * 8  # strip ustar magic+version -> pre-POSIX v7 header
    raw[148:156] = b" " * 8
    chk = sum(raw[:512])
    raw[148:156] = b"%06o\0 " % chk
    return bytes(raw)


ROWS = b'{"k":1,"decision":"halt"}\n' * 40
LFS_OID = "oid sha256:" + "a" * 64 + "\nsize 999999\n"
K_EVASIONS = {
    "zip_behind_prefix_neutral_name": {"apps/x/rows.bin": b"#!/bin/sh\nexit 0\n" + _zip_bytes()},
    "split_zip_part_z01": {"apps/x/rows.z01": b"PK\x07\x08" + _zip_bytes()},
    "v7_tar_no_ustar_magic": {"apps/x/rows.bin": _v7_tar_bytes()},
    "lz4_frame": {"apps/x/rows.lz4": b"\x04\x22\x4d\x18" + b"\x00" * 32},
    "unix_compress_Z": {"apps/x/rows.Z": b"\x1f\x9d\x90" + b"\x00" * 32},
    "lzma_alone": {"apps/x/rows.lzma": b"\x5d\x00\x00\x80\x00" + b"\xff" * 8 + b"\x00" * 32},
    "parquet": {"apps/x/rows.parquet": b"PAR1" + b"\x00" * 32 + b"PAR1"},
    "sqlite": {"apps/x/rows.db": b"SQLite format 3\x00" + b"\x00" * 84},
    "base64_pack_in_txt": {"apps/x/notes.txt": base64.encodebytes(gzip.compress(ROWS))},
    "ndjson_ext": {"apps/x/rows.ndjson": ROWS},
    "json_ext_jsonl_body": {"apps/x/rows.json": ROWS},
    "no_extension": {"apps/x/rows": ROWS},
    "jsonl_dot_bak": {"apps/x/rows.jsonl.bak": ROWS},
    "jsonl_under_generic_data_seg": {"apps/x/data/rows.jsonl": ROWS},
    "gzip_under_generic_runs_seg": {"apps/x/runs/rows.jsonl.gz": gzip.compress(ROWS)},
    "gzip_under_lib_seg": {"lib/rows.gz": gzip.compress(ROWS)},
    "lfs_hawser_alias": {"apps/x/rows.bin": ("version https://hawser.github.com/spec/v1\n" + LFS_OID).encode()},
    "lfs_git_media_alias": {"apps/x/rows.bin": ("version http://git-media.io/v/2\n" + LFS_OID).encode()},
}
L_ALLOWLIST_BYPASS = {
    "allowlisted_py_is_zip": {"scripts/run_ultradata_harvest.py": _zip_bytes()},
    "allowlisted_md_is_lfs": {"docs/curated-packing-notes.md": ("version https://git-lfs.github.com/spec/v1\n" + LFS_OID).encode()},
    "allowlisted_py_is_symlink": {"apps/dottie-os/scripts/lab/run_ultradata_harvest.py": ("symlink", "../../../../data/curated_pack_v2.jsonl")},
    "fixture_path_is_gitlink": {"apps/x/uncurated_package.py": ("gitlink", "c" * 40)},
}
M_CONTROLS = {
    "zip_neutral": {"apps/x/rows.bin": _zip_bytes()},
    "gzip_neutral": {"apps/x/rows.bin": gzip.compress(ROWS)},
    "jsonl_neutral": {"apps/x/rows.jsonl": ROWS},
    "JSONL_upper": {"apps/x/rows.JSONL": ROWS},
    "lfs_std": {"apps/x/rows.bin": ("version https://git-lfs.github.com/spec/v1\n" + LFS_OID).encode()},
    "zip_in_fixtures_dir": {"apps/x/fixtures/rows.zip": _zip_bytes()},
    "symlink_dot_github_action": {".github/actions/a": ("symlink", "../../apps/x")},
    "gitlink_neutral": {"apps/x/vendor": ("gitlink", "b" * 40)},
    "lfs_via_gitattributes_filter": {".gitattributes": b"*.bin filter=lfs diff=lfs merge=lfs -text\n",
                                     "apps/x/rows.bin": ("version https://git-lfs.github.com/spec/v1\n" + LFS_OID).encode()},
    # r2: fixtures-folder exemption dropped at 0ac5 (Cam ruling); fixture jsonl must refuse.
    "fixture_jsonl": {"apps/x/fixtures/rows.jsonl": ROWS},
}
M_MUST_PASS = {
    "png_asset": {"apps/x/assets/logo.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 32},
    "json_config": {"apps/x/config.json": b'{"a": 1}\n'},
    "plain_txt": {"docs/notes.txt": b"hello\n"},
    "gitmodules_only_no_gitlink": {".gitmodules": b'[submodule "v"]\n\tpath = apps/x/vendor\n\turl = https://example.invalid/r.git\n'},
    "gitattributes_filter_plain_blob": {".gitattributes": b"*.txt filter=nope\n", "apps/x/a.txt": b"plain\n"},
}


def _guard(files):
    t = Path(tempfile.mkdtemp(prefix="critic-91-0b05-"))
    try:
        r = A.mkrepo(t, ["README"])
        links = []
        for rel, data in files.items():
            p = r / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(data, tuple) and data[0] == "symlink":
                os.symlink(data[1], p)
            elif isinstance(data, tuple) and data[0] == "gitlink":
                links.append((rel, data[1]))
            else:
                p.write_bytes(data)
        A.git(r, "add", "-f", "-A")
        for rel, sha in links:  # after add -A, which would stage the empty gitlink path as deleted
            A.git(r, "update-index", "--add", "--cacheinfo", "160000," + sha + "," + rel)
        A.git(r, "commit", "-qm", "case")
        return A.run_guard(r)
    finally:
        shutil.rmtree(t, ignore_errors=True)


class K_S26ContentEvasions(unittest.TestCase):
    def test_k_content_evasions_refused(self):
        for cid, files in K_EVASIONS.items():
            with self.subTest(case=cid):
                self.assertNotEqual(_guard(files), 0, f"{cid} passes pack-guard")


class L_S26AllowlistSkipsContent(unittest.TestCase):
    def test_l_allowlisted_paths_still_content_checked(self):
        for cid, files in L_ALLOWLIST_BYPASS.items():
            with self.subTest(case=cid):
                self.assertNotEqual(_guard(files), 0, f"{cid} passes: allowlist skips S26")


class M_S26Controls(unittest.TestCase):
    def test_m1_controls_refused(self):
        for cid, files in M_CONTROLS.items():
            with self.subTest(case=cid):
                self.assertNotEqual(_guard(files), 0, f"{cid} regressed")

    def test_m2_legit_trees_pass(self):
        for cid, files in M_MUST_PASS.items():
            with self.subTest(case=cid):
                self.assertEqual(_guard(files), 0, f"{cid} over-refused")

    def test_m3_real_head_tree_passes(self):
        env = A.genv({"GITHUB_SHA": A.git(WT, "rev-parse", "HEAD")})
        with tempfile.NamedTemporaryFile("w", suffix=".sh", prefix="critic-91-0b05-", delete=False) as f:
            f.write(A.GUARD)
        try:
            r = subprocess.run([a.replace("{0}", f.name) for a in A.SHELL.split()], cwd=WT, env=env,
                               capture_output=True, text=True)
        finally:
            os.unlink(f.name)
        self.assertEqual(r.returncode, 0, r.stdout[-300:])


class N_ProdAllowlist(unittest.TestCase):
    def test_n_ci_snippet_excludes_test_fixture_path(self):
        self.assertNotIn("'apps/x/uncurated_package.py'", CI_TEXT[CI_TEXT.index("pack-guard:"):])


if __name__ == "__main__":
    unittest.main()
