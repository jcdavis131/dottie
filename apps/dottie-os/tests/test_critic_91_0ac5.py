"""Critic attack suite for dottie#91 @ 0ac51f7e6d3e4f4c25baf308a1582d4c87fead1a (S24 quote-aware scan / S26 content re-attack).

r2 (2026-10-19, Critic ruling (b) at d56d7ca0): csv_rows moves from F to F_ACCEPTED_LEFTOVER - CSV pack rows are
an accepted inherent leftover bounded by the 3 MiB per-file cap; it is asserted to PASS so any change is visible.
Every other F case (7z, RAR, gzip-behind, PNG chunks, tar-behind, b64 header/url, hex, comment-first JSONL,
JSON arrays) must still be REFUSED. Nothing else changed.

Every test asserts the SECURE behaviour; a FAIL is a finding.
A: S24 controls at 0ac5 (nested quoted }}, '' escapes, YAML quoting/escape rebuilds, folded/literal splits,
   github.<prop> casing/abuse, docker/node local actions) - must stay RED.
B: S24 gaps - unbraced `if:` expressions are never scanned (github.token / toJSON(github) oracle).
C: S24 over-refusal - read-only github metadata props that should stay GREEN (friction, low).
D: S24 must-GREEN controls (allowlisted props, digest-pinned docker, folded `$`/`{{` split is not an expr).
E: S26 controls (zip behind any prefix, cap+1, pure base64, exempt-dir subfolder, zip in exempt dir).
F: S26 content evasions that still pass the real guard.
G: S26 exemption scope - exemption is per folder (new files pass), any */fixtures|fixture/ dir is exempt,
   and exempt/OKP paths can have their CONTENT swapped for rows.
H: S26 cap boundary: exactly 3 MiB passes (by design; asserted so a change is visible).
Run:  WT=/workspace/review/dottie-91/wt-0ac5 python3 -m unittest -v test_critic_91_0ac5_r2
Read-only w.r.t. GitHub. Temp dirs prefixed critic-91-0ac5- (via 0b05 helpers: critic-91-0b05-). No sockets.
No holdout / N rows are used; all rows are synthetic.
"""
from __future__ import annotations

import base64
import gzip
import json
import os
import struct
import sys
import unittest
import zlib
from pathlib import Path

WT = Path(os.environ.get("WT", "/workspace/review/dottie-91/wt-0ac5"))
os.environ["WT"] = str(WT)
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_critic_91_0b05 as B  # noqa: E402  (probe(), _guard(), jenv(), H/J/P/S, ROWS, _zip_bytes, _v7_tar_bytes)

H, J, P, S, jenv, ROWS = B.H, B.J, B.P, B.S, B.jenv, B.ROWS
CAP = 3 * 1024 * 1024
RR = "    steps:\n      - run: python3 apps/x/post.py\n"
ACT = ".github/actions/a/action.yml"

A_RED = {
    "nested_format_quoted_close": jenv("${{ format('{0}', format('}}{0}', secrets.MY_PAT)) }}"),
    "escaped_sq_then_close": jenv("${{ format('it''s }}{0}', secrets.MY_PAT) }}"),
    "yaml_sq_doubling_raw_vs_parsed": jenv("'${{ ''}}'' && secrets.MY_PAT }}'"),
    "yaml_dq_x27_quote": jenv('"${{ \\x27}}\\x27 && secrets.MY_PAT }}"'),
    "folded_block_split_expr": H + "  b:\n    runs-on: ubuntu-latest\n    env:\n      T: >-\n        ${{ format('}}{0}',\n        secrets.MY_PAT) }}\n" + RR,
    "literal_block_split_expr": H + "  b:\n    runs-on: ubuntu-latest\n    env:\n      T: |\n        ${{ format('}}{0}',\n        github.token) }}\n" + RR,
    "GITHUB_TOKEN_upper": jenv("${{ GITHUB.TOKEN }}"),
    "GitHub_index_Token": jenv("${{ GitHub['Token'] }}"),
    "paren_github_token": jenv("${{ (github).token }}"),
    "or_chain_token": jenv("${{ github.sha || github.token }}"),
    "workspace_then_index": jenv("${{ github.workspace['x'] }}"),
    "github_event_path": jenv("${{ github.event_path }}"),
    "github_action_path": jenv("${{ github.action_path }}"),
    "event_title_into_run": J + "      - run: echo \"${{ github.event.pull_request.title }}\"\n",
    "head_ref_into_run": J + "      - run: git log ${{ github.head_ref }}\n",
    "docker_local_Dockerfile": (J + "      - uses: ./.github/actions/a\n",
                                {ACT: "name: a\nruns:\n  using: docker\n  image: Dockerfile\n", ".github/actions/a/Dockerfile": "FROM alpine:latest\n"}),
    "node_NODE20_main_outside": (J + "      - uses: ./.github/actions/a\n",
                                 {ACT: "name: a\nruns:\n  using: NODE20\n  main: ../../../apps/x/e.js\n", "apps/x/e.js": "//\n"}),
    "node_post_outside": (J + "      - uses: ./.github/actions/a\n",
                          {ACT: "name: a\nruns:\n  using: node20\n  main: index.js\n  post: ../../../apps/x/e.js\n",
                           ".github/actions/a/index.js": "//\n", "apps/x/e.js": "//\n"}),
    "node_main_symlink_outside": (J + "      - uses: ./.github/actions/a\n",
                                  {ACT: "name: a\nruns:\n  using: node20\n  main: index.js\n",
                                   ".github/actions/a/index.js": ("symlink", "../../../apps/x/e.js"), "apps/x/e.js": "//\n"}),
}
B_RED = {
    # `if:` is an expression without ${{ }}; a step-per-prefix ladder leaks the token as an oracle in public logs
    "unbraced_step_if_token": J + "      - if: startsWith(github.token, 'ghs_')\n        run: echo\n",
    "unbraced_step_if_toJSON_github": J + "      - if: contains(toJSON(github), 'ghs_')\n        run: echo\n",
    "unbraced_job_if_token": H + "  b:\n    if: startsWith(github.token, 'ghs_')\n" + S,
}
C_GREEN = {p: jenv("${{ github.%s }}" % p) for p in
           ("ref_name", "base_ref", "server_url", "api_url", "repository_owner", "repository_id", "run_attempt", "job")}
D_GREEN = {
    "workspace": jenv("${{ github.workspace }}"),
    "sha_ref_run_id": jenv("${{ github.sha }}-${{ github.ref }}-${{ github.run_id }}"),
    "folded_dollar_brace_split_not_expr": H + "  b:\n    runs-on: ubuntu-latest\n    env:\n      T: >-\n        $\n        {{ secrets.MY_PAT }}\n" + RR,
    "docker_digest_pinned": (J + "      - uses: ./.github/actions/a\n",
                             {ACT: "name: a\nruns:\n  using: docker\n  image: docker://alpine@sha256:" + "a" * 64 + "\n"}),
}


class _Cases(unittest.TestCase):
    def check(self, cases, want_red):
        for cid, case in cases.items():
            body, files = case if isinstance(case, tuple) else (case, {})
            with self.subTest(case=cid):
                r = B.probe(body, files)
                if want_red:
                    self.assertTrue(r.startswith("RED"), f"{cid} accepted: {r[:80]}")
                else:
                    self.assertEqual(r, "GREEN", f"{cid} refused: {r[:100]}")


class A_S24Controls(_Cases):
    def test_a_controls_red(self):
        self.check(A_RED, True)


class B_S24UnbracedIf(_Cases):
    def test_b_unbraced_if_expressions_scanned(self):
        self.check(B_RED, True)


class C_S24OverRefusal(_Cases):
    def test_c_readonly_github_metadata_green(self):
        self.check(C_GREEN, False)


class D_S24Green(_Cases):
    def test_d_must_green(self):
        self.check(D_GREEN, False)


# ---------------------------------------------------------------- S26 ----
def _png_with(ctype, data):
    def ch(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", ihdr) + ch(ctype, data) + ch(b"IDAT", zlib.compress(b"\x00\x00")) + ch(b"IEND", b"")


def _b64_rows_near_cap():
    rows = b"".join(json.dumps({"messages": [{"role": "user", "content": os.urandom(24).hex()}], "label": "halt"}).encode() + b"\n"
                    for _ in range(120000))
    gz = gzip.compress(rows)
    raw_need = ((CAP - 4096) // 77) * 57
    out = base64.encodebytes(gz[:raw_need])
    assert CAP - 8192 < len(out) <= CAP - 1024, len(out)
    return out


ZB = B._zip_bytes()
Z7 = b"7z\xbc\xaf\x27\x1c\x00\x04" + b"\x00" * 40
RAR = b"Rar!\x1a\x07\x00" + b"\x00" * 40
B64_NEAR_CAP = _b64_rows_near_cap()
GZ_BIG = base64.encodebytes(gzip.compress(ROWS * 100))

E_REFUSED = {
    "zip_prefix_1": {"apps/x/r.bin": b"X" + ZB},
    "zip_prefix_4097": {"apps/x/r.bin": b"Q" * 4097 + ZB},
    "zip_prefix_2MiB": {"apps/x/r.bin": b"\0" * (2 * 1024 * 1024) + ZB},
    "cap_plus_1": {"apps/x/r.bin": b"A" * (CAP + 1)},
    "pure_b64_gzip_rows_just_under_cap": {"apps/x/notes.txt": B64_NEAR_CAP},
    "new_subdir_under_exempt_dir": {"apps/ava-factory/data/orchestration/sub/rows.jsonl": ROWS},
    "zip_in_exempt_dir": {"apps/ava-factory/data/orchestration/r.zip": ZB},
    "allowlisted_py_with_jsonl_body": {"scripts/run_ultradata_harvest.py": ROWS},
}
F_EVASIONS = {
    "7z_behind_sfx_stub": {"apps/x/r.bin": b"MZ" + b"\0" * 510 + Z7},
    "rar_behind_sfx_stub": {"apps/x/r.bin": b"MZ" + b"\0" * 510 + RAR},
    "gzip_behind_1_byte": {"apps/x/r.bin": b"X" + gzip.compress(ROWS)},
    "gzip_in_png_private_chunk": {"apps/x/logo.png": _png_with(b"zzRw", gzip.compress(ROWS))},
    "jsonl_in_png_tEXt": {"apps/x/logo.png": _png_with(b"tEXt", b"k\0" + ROWS)},
    "tar_behind_zero_block": {"apps/x/r.bin": b"\0" * 512 + B._v7_tar_bytes()},
    "b64_rows_just_under_cap_with_header_line": {"apps/x/notes.txt": b"-----BEGIN ROWS-----\n" + B64_NEAR_CAP},
    "b64url_rows": {"apps/x/notes.txt": base64.urlsafe_b64encode(gzip.compress(ROWS * 100))},
    "hex_gzip_rows": {"apps/x/notes.txt": gzip.compress(ROWS).hex().encode()},
    "jsonl_with_comment_first_line": {"apps/x/rows.txt": b"# rows\n" + ROWS},
    "json_array_pretty": {"apps/x/rows.json": json.dumps([{"messages": [{"role": "user", "content": "x"}], "label": "halt"}] * 50, indent=2).encode()},
    "json_array_one_line": {"apps/x/rows.json": json.dumps([{"messages": [], "label": "halt"}] * 50).encode()},
}
# r2: Critic ruling (b) - accepted inherent leftover, bounded by the per-file cap. Asserted to PASS.
F_ACCEPTED_LEFTOVER = {
    "csv_rows": {"apps/x/rows.csv": b"id,label\n" + b"1,halt\n" * 200},
}
G_SCOPE = {
    "new_jsonl_in_exempt_dir": {"apps/ava-factory/data/orchestration/new_rows.jsonl": ROWS},
    "new_gz_in_exempt_dir": {"apps/ava-factory/data/orchestration/new_rows.jsonl.gz": gzip.compress(ROWS)},
    "new_any_fixtures_dir_gz": {"apps/x/fixtures/rows.jsonl.gz": gzip.compress(ROWS)},
    "new_root_fixture_dir_sqlite": {"fixture/rows.db": b"SQLite format 3\x00" + b"\0" * 84},
    "okp_sqlite_path_holds_jsonl": {"tasks/artifacts/ledger_copy.sqlite3": ROWS},
}


class E_S26Controls(unittest.TestCase):
    def test_e_refused(self):
        for cid, files in E_REFUSED.items():
            with self.subTest(case=cid):
                self.assertNotEqual(B._guard(files), 0, f"{cid} regressed")


class F_S26Evasions(unittest.TestCase):
    def test_f_content_evasions_refused(self):
        for cid, files in F_EVASIONS.items():
            with self.subTest(case=cid):
                self.assertNotEqual(B._guard(files), 0, f"{cid} passes pack-guard")

    def test_f_accepted_leftover_passes(self):
        for cid, files in F_ACCEPTED_LEFTOVER.items():
            with self.subTest(case=cid):
                self.assertEqual(B._guard(files), 0, f"{cid}: ACCEPTED_LEFTOVER changed behaviour; re-rule it")


class G_S26ExemptionScope(unittest.TestCase):
    def test_g_exemption_is_exact_file_and_content_pinned(self):
        for cid, files in G_SCOPE.items():
            with self.subTest(case=cid):
                self.assertNotEqual(B._guard(files), 0, f"{cid} passes: exemption is per folder / name, not per blob")


class H_S26CapBoundary(unittest.TestCase):
    def test_h_exactly_cap_passes_by_design(self):
        self.assertEqual(B._guard({"apps/x/r.bin": b"A" * CAP}), 0)


if __name__ == "__main__":
    unittest.main()
