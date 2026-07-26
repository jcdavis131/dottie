"""Leaks — openswap #7 (GitGuardian / TruffleHog Enterprise -> fully local
secrets scanning). Pure-logic core tests + capability-detection fallback + the
subprocess envelope. Offline and deterministic by construction: the manifest
default-denies the network, detection is monkeypatched, git never runs (patch
text is a fixture), and no test touches the gitleaks binary.

Every fixture secret is assembled by concatenation so the signature pack can
never flag this test file itself during a self-scan of the repo tree."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from bigbang.core import leaks, openswap
from bigbang.plugins.leaks import cli as leaks_cli

ROOT = Path(__file__).resolve().parents[1]

AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"
SECRET40 = "abcd1234EFGH5678ijkl" * 2
GH_TOKEN = "ghp_" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
SLACK = "xoxb-" + "1234567890-AbCdEfGhIjKl"
STRIPE_LIVE = "sk_live_" + "a1B2c3D4e5F6g7H8"
STRIPE_TEST = "sk_test_" + "a1B2c3D4e5F6g7H8"
GOOGLE = "AIza" + "SyA" + "B" * 32
PEM = "-----BEGIN RSA " + "PRIVATE" + " KEY-----"
JWT = ".".join(["eyJhbGciOiJIUzI1NiJ9", "eyJzdWIiOiI0MiJ9", "c2lnbmF0dXJl0aGl"])
VALUE = "q9X2mZ7pL4" + "wR8vN1tK6y"
B64 = "ABCDEFGHIJKLMNOP" + "QRSTUVWXYZabcdefghij"
HEX = "0123456789abcdef" * 4


def _rules_of(diags):
    return [d["rule"] for d in diags]


# ---- specific signatures ----------------------------------------------------


def test_aws_access_key_id_hit_and_position():
    diags = leaks.scan_text(f"x {AWS_KEY} y")
    assert _rules_of(diags) == ["leaks:aws-access-key-id"]
    assert diags[0]["line"] == 1 and diags[0]["col"] == 3
    assert diags[0]["severity"] == "error"


def test_aws_secret_key_context():
    diags = leaks.scan_text(f'aws_secret_access_key = "{SECRET40}"')
    assert _rules_of(diags) == ["leaks:aws-secret-key"]
    assert diags[0]["message"].startswith("AWS secret access key")
    assert "abcd" in diags[0]["message"]  # redaction keeps the first 4 chars


def test_specific_rule_wins_over_entropy_catchall():
    # the token tail alone (36 uniques, entropy ~5.17) would trip
    # high-entropy; span-overlap suppression keeps it a single finding
    diags = leaks.scan_text(f"deploy with {GH_TOKEN} today")
    assert _rules_of(diags) == ["leaks:github-token"]


def test_slack_and_stripe_live_hits():
    diags = leaks.scan_text(f"a {SLACK} b {STRIPE_LIVE} c")
    assert sorted(_rules_of(diags)) == [
        "leaks:slack-token",
        "leaks:stripe-live-key",
    ]
    assert all(d["severity"] == "error" for d in diags)


def test_stripe_test_key_not_flagged():
    assert leaks.scan_text(f"payment key {STRIPE_TEST} ok") == []


def test_pem_header_and_jwt():
    diags = leaks.scan_text(f"{PEM}\nkey body here\n")
    assert _rules_of(diags) == ["leaks:private-key-pem"]
    assert diags[0]["line"] == 1
    jwt = leaks.scan_text(f"bearer {JWT}")
    assert _rules_of(jwt) == ["leaks:jwt"]
    assert jwt[0]["severity"] == "warning"


def test_google_api_key():
    diags = leaks.scan_text(f"maps: {GOOGLE} end")
    assert _rules_of(diags) == ["leaks:google-api-key"]


def test_redaction_fingerprint_entropy():
    d = leaks.scan_text(f"leaked {AWS_KEY} here")[0]
    assert AWS_KEY not in json.dumps(d)  # the secret never leaves whole
    assert "(20 chars)" in d["message"]
    assert re.fullmatch(r"[0-9a-f]{16}", d["fingerprint"])
    assert d["fingerprint"] == leaks.fingerprint("aws-access-key-id", AWS_KEY)
    assert isinstance(d["entropy"], float)


# ---- generic + entropy gates ------------------------------------------------


def test_generic_keyword_entropy_gate():
    diags = leaks.scan_text(f'api_key = "{VALUE}"')
    assert _rules_of(diags) == ["leaks:generic-api-key"]
    assert diags[0]["severity"] == "warning"
    # placeholder values stay quiet: entropy 0.0 is under the keyword gate
    assert leaks.scan_text('password = "aaaaaaaaaaaa"') == []


def test_high_entropy_b64_suggestion():
    diags = leaks.scan_text(f"blob {B64} tail")
    assert _rules_of(diags) == ["leaks:high-entropy"]
    assert diags[0]["severity"] == "suggestion"
    assert leaks.scan_text("blob " + "a" * 48 + " tail") == []


def test_high_entropy_hex_info():
    diags = leaks.scan_text(f"digest {HEX} end")
    assert _rules_of(diags) == ["leaks:high-entropy-hex"]
    assert diags[0]["severity"] == "info"


def test_per_ext_entropy_override():
    cfg = leaks.load_config(None)
    cfg["entropy_by_ext"][".lock"] = {"base64": 6.0}
    text = f"blob {B64} tail"
    assert leaks.scan_text(text, path="deps.lock", config=cfg) == []
    assert len(leaks.scan_text(text, path="deps.env", config=cfg)) == 1


# ---- allowlist escape hatches -----------------------------------------------


def test_allowlist_fingerprint_rule_path_pattern():
    text = f"leaked {AWS_KEY} here"
    fp = leaks.scan_text(text)[0]["fingerprint"]

    cfg = leaks.load_config(None)
    cfg["allow"]["fingerprints"].append(fp)
    assert leaks.scan_text(text, config=cfg) == []

    cfg = leaks.load_config(None)
    cfg["allow"]["rules"].append("aws-access-key-id")
    assert leaks.scan_text(text, config=cfg) == []

    cfg = leaks.load_config(None)
    cfg["allow"]["paths"].append("*/vendored/*")
    assert leaks.scan_text(text, path="src/vendored/x.py", config=cfg) == []
    assert len(leaks.scan_text(text, path="src/app.py", config=cfg)) == 1

    cfg = leaks.load_config(None)
    cfg["allow"]["patterns"].append("EXAMPLE$")
    assert leaks.scan_text(text, config=cfg) == []


def test_disable_builtin_signature():
    cfg = leaks.load_config(None)
    cfg["disable"].append("high-entropy-hex")
    assert leaks.scan_text(f"digest {HEX} end", config=cfg) == []


# ---- config is policy-as-config ---------------------------------------------


def test_load_config_overlay_and_unknown_key(tmp_path):
    overlay = tmp_path / "leaks.json"
    overlay.write_text(
        json.dumps(
            {
                "allow": {"rules": ["jwt"]},
                "entropy": {"hex": 3.4},
                "disable": ["sendgrid-key"],
            }
        ),
        encoding="utf-8",
    )
    cfg = leaks.load_config(str(overlay))
    assert "jwt" in cfg["allow"]["rules"]
    assert cfg["entropy"]["hex"] == 3.4
    assert cfg["entropy"]["base64"] == 4.5  # defaults kept
    assert "sendgrid-key" in cfg["disable"]

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"nope": 1}), encoding="utf-8")
    try:
        leaks.load_config(str(bad))
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_extra_signature_from_config(tmp_path):
    overlay = tmp_path / "org.json"
    overlay.write_text(
        json.dumps(
            {
                "extra_signatures": [
                    {
                        "id": "dottie-token",
                        "pattern": r"\bdtk_[a-z0-9]{10}\b",
                        "severity": "error",
                        "description": "Dottie internal token",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    cfg = leaks.load_config(str(overlay))
    diags = leaks.scan_text("x dtk_abc123def4 y", config=cfg)
    assert _rules_of(diags) == ["leaks:dottie-token"]
    assert diags[0]["severity"] == "error"


def test_bad_extra_signature_regex_raises():
    cfg = leaks.load_config(None)
    cfg["extra_signatures"].append({"id": "bad", "pattern": "("})
    try:
        leaks.build_signatures(cfg)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


# ---- patch text: staged diffs and history -----------------------------------

SHA = "1234567890abcdef1234567890abcdef12345678"
PATCH = f"""commit {SHA}
Author: Dev <dev@example.com>
Date:   Tue Jul 21 10:00:00 2026 -0700

    api_key = "{VALUE}"

diff --git a/config.py b/config.py
index 0000000..1111111 100644
--- a/config.py
+++ b/config.py
@@ -10,0 +11,2 @@ def settings():
+api_key = "{VALUE}"
+DEBUG = True
@@ -20 +23 @@ def other():
-old = 1
+new = 2
diff --git a/removed.txt b/removed.txt
deleted file mode 100644
index 2222222..0000000
--- a/removed.txt
+++ /dev/null
@@ -1 +0,0 @@
-gone line
"""


def test_parse_patch_added_lines_and_resets():
    entries = leaks.parse_patch(PATCH)
    assert [(e["path"], e["line"]) for e in entries] == [
        ("config.py", 11),
        ("config.py", 12),
        ("config.py", 23),
    ]
    assert entries[0]["content"] == f'api_key = "{VALUE}"'
    assert all(e["commit"] == SHA for e in entries)
    # nothing collected from the deleted file or the commit message block


def test_scan_patch_attaches_commit_and_skips_messages():
    # the commit MESSAGE repeats the leaky line — only the added line counts
    diags, stats = leaks.scan_patch(PATCH)
    assert len(diags) == 1
    d = diags[0]
    assert d["path"] == "config.py" and d["line"] == 11
    assert d["rule"] == "leaks:generic-api-key"
    assert d["commit"] == SHA[:12]
    assert stats == {"added_lines": 3, "files": 1, "commits": 1}


def test_scan_patch_staged_shape_no_commit():
    staged = "\n".join(
        [
            "diff --git a/x.env b/x.env",
            "index 0000000..1111111 100644",
            "--- a/x.env",
            "+++ b/x.env",
            "@@ -0,0 +1 @@",
            f"+leaked {AWS_KEY} here",
            "",
        ]
    )
    diags, stats = leaks.scan_patch(staged)
    assert len(diags) == 1
    assert diags[0]["path"] == "x.env" and diags[0]["line"] == 1
    assert "commit" not in diags[0]
    assert stats["commits"] == 0


# ---- tree walking -----------------------------------------------------------


def test_scan_tree_prunes_skips_counts(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        f"leaked {AWS_KEY} here\n", encoding="utf-8"
    )
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text(
        f"leaked {AWS_KEY} here\n", encoding="utf-8"
    )
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01" + b"x" * 10)
    (tmp_path / "big.txt").write_text("a" * 2048, encoding="utf-8")
    cfg = leaks.load_config(None)
    cfg["max_file_kb"] = 1
    diags, stats = leaks.scan_tree(tmp_path, config=cfg)
    assert len(diags) == 1
    assert diags[0]["path"].endswith("app.py")  # node_modules pruned
    assert stats["files_scanned"] == 1
    assert stats["skipped"] == {"binary": 1, "too-large": 1}


# ---- capability detection: probed, never executed ---------------------------


def test_capability_fallback_when_binaries_absent(monkeypatch):
    monkeypatch.setattr(openswap.shutil, "which", lambda _b: None)
    cap = leaks_cli._capability()
    assert cap["tier"] == openswap.TIER_FALLBACK
    assert cap["native"]["binary"] == "gitleaks"
    assert cap["native"]["found"] is False
    assert set(cap["extras"]) == {"trufflehog", "detect-secrets"}
    assert "never executed" in cap["install_hint"]


# ---- the real CLI in a subprocess -------------------------------------------


def _cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "bigbang.cli", "--json", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        cwd=str(cwd or ROOT),
    )


def test_cli_leaks_hello_envelope():
    r = _cli(["leaks", "hello"])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    assert data["data"]["ready"] is True
    assert "example" in data


def test_cli_leaks_scan_redacts_and_gates(tmp_path):
    f = tmp_path / "cfg.env"
    f.write_text(f"leaked {AWS_KEY} here\n", encoding="utf-8")
    r = _cli(["leaks", "scan", str(f)])
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ok"] is True
    body = data["data"]
    assert body["summary"]["total"] == 1
    assert body["summary"]["by_rule"] == {"leaks:aws-access-key-id": 1}
    assert body["stats"]["files_scanned"] == 1
    assert AWS_KEY not in r.stdout  # redaction holds end-to-end
    # the pre-commit/audit gate hook: same file, gated on errors -> exit 1
    gated = _cli(["leaks", "scan", str(f), "--fail-on", "error"])
    assert gated.returncode == 1
