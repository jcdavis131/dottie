"""Stdlib-only checks for the dottie-os UltraData factory + hop helpers.

No Hugging Face download, no FT, no LIVE/champion. Run with:

    python3 -m unittest discover -s apps/dottie-os/tests -v
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import re
import shutil
import unicodedata
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

try:
    import yaml
except ImportError:
    yaml = None  # dottie-os-smoke does not install PyYAML; use the stdlib extractor.

APP = Path(__file__).resolve().parents[1]
SCRIPTS = APP / "scripts"
LAB = SCRIPTS / "lab"
TESTS = APP / "tests"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import cam_pin_vector_helper  # noqa: E402
from ed25519_torsion_vectors import (  # noqa: E402
    ALL_ZERO,
    ED25519_L,
    IDENTITY,
    NON_IDENTITY_TORSION_ENCODINGS,
    ORDER2,
    TORSION_ENCODINGS,
    mixed_order_encodings,
)
from sidecar.curation.ultradata_curriculum import (  # noqa: E402
    LEGACY_SCHEMA,
    SCHEMA,
    classify_tool_action,
    ensure_tier_consent,
    first_tool_call,
    holdout_split,
    l3_multihead_labels,
    leaks_decontam,
    load_jsonl,
    l3_questions,
    make_row,
    read_rows,
    split_row,
    summarize,
    write_jsonl,
    write_pack,
    write_provenance,
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


smoke_pack_v2 = _load("smoke_pack_v2", SCRIPTS / "smoke_pack_v2.py")
patch_hf = _load("patch_hf_to_system_one", SCRIPTS / "patch_hf_to_system_one.py")
finalize_manifest = _load("finalize_manifest", LAB / "finalize_manifest.py")
kick_helper_ft = _load("kick_helper_ft", LAB / "kick_helper_ft.py")
helper_ft_kickoff = _load("helper_ft_kickoff", LAB / "helper_ft_kickoff.py")
cam_pin_spec = kick_helper_ft.cam_pin_spec


def _row(*, rid: str, action: str, pair_id: str | None = None, source: str = "openbmb/UltraData-SFT-Agent-2609") -> dict:
    row = make_row(
        rid=rid,
        tier="L3",
        source={"hf": source, "split": "train"},
        state={"message": f"tool=read_file; detail={rid}"},
        questions={"action": {"type": "choice", "criteria": {"execute": "ok"}}},
        labels=l3_multihead_labels(action),
    )
    if pair_id:
        row["pair_id"] = pair_id
    return row


class HeuristicTests(unittest.TestCase):
    def test_schema_id_is_frozen(self) -> None:
        # One contract: dottie-os emits System One's frozen schema; the old id is read-only.
        self.assertEqual(SCHEMA, "jev-decision-schema-1.0.0")
        self.assertEqual(LEGACY_SCHEMA, "dottie-os-decision-schema-1.0.0")

    def test_classify_halt_on_rm_rf(self) -> None:
        self.assertEqual(classify_tool_action("shell", {"cmd": "rm -rf /tmp/x"}), "halt")

    def test_classify_execute_on_read(self) -> None:
        self.assertEqual(classify_tool_action("read_file", {"path": "README.md"}), "execute")

    def test_classify_escalate_on_sudo(self) -> None:
        self.assertEqual(classify_tool_action("shell", {"cmd": "sudo systemctl restart nginx"}), "escalate")

    def test_first_tool_call_from_messages(self) -> None:
        messages = [
            {"role": "user", "content": "list files"},
            {
                "role": "assistant",
                "tool_calls": [
                    {"function": {"name": "ls", "arguments": {"path": "."}}},
                ],
            },
        ]
        self.assertEqual(first_tool_call(messages), ("ls", {"path": "."}))

    def test_leaks_decontam_blocks_arxiviq_leak(self) -> None:
        self.assertTrue(leaks_decontam("compare arxiviq vs openjev"))
        self.assertFalse(leaks_decontam("tool=read_file; detail=src/app.py"))

    def test_l3_labels_and_consent_keep_champion_false(self) -> None:
        labels = l3_multihead_labels("halt")
        self.assertEqual(labels["action"]["choice"], "halt")
        self.assertLess(labels["safe"]["noul"], 0.2)
        row = ensure_tier_consent(_row(rid="u1", action="halt"))
        self.assertFalse(row["consent"]["champion"])
        self.assertTrue(row["consent"]["public_hf"])
        self.assertEqual(row["schema"], SCHEMA)


class HoldoutAndIoTests(unittest.TestCase):
    def test_holdout_keeps_pairs_and_meets_frac(self) -> None:
        rows = [
            _row(rid="a1", action="execute", pair_id="pair-nimble-1"),
            _row(rid="a2", action="escalate", pair_id="pair-nimble-1"),
            _row(rid="b1", action="execute"),
            _row(rid="c1", action="halt"),
            _row(rid="d1", action="execute"),
        ]
        train, hold = holdout_split(rows, seed=20260921, frac=0.20)
        self.assertEqual(len(train) + len(hold), len(rows))
        self.assertGreaterEqual(len(hold) / len(rows), 0.20)
        train_pairs = {r.get("pair_id") for r in train if r.get("pair_id")}
        hold_pairs = {r.get("pair_id") for r in hold if r.get("pair_id")}
        self.assertFalse(train_pairs & hold_pairs)

    def test_write_load_jsonl_roundtrip(self) -> None:
        rows = [_row(rid="r1", action="execute"), _row(rid="r2", action="halt")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pack.jsonl"
            write_jsonl(path, rows)
            loaded = load_jsonl(path)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["id"], "r1")

    def test_summarize_counts_champion_zero(self) -> None:
        rows = [_row(rid="s1", action="execute"), _row(rid="s2", action="escalate")]
        summary = summarize(rows)
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["champion_true_count"], 0)
        self.assertEqual(summary["schema"], SCHEMA)


def _strict_row(rid: str, action: str = "execute") -> dict:
    return make_row(
        rid=rid,
        tier="L3",
        source={"hf": "openbmb/UltraData-SFT-Agent-2609", "split": "train"},
        state={"message": f"tool=read_file; detail={rid}"},
        questions=l3_questions(),
        labels=l3_multihead_labels(action),
    )


class StrictSchemaTests(unittest.TestCase):
    def test_split_row_is_strict_jev_plus_provenance(self) -> None:
        record, prov = split_row(_strict_row("x1", "halt"))
        self.assertEqual(sorted(record), ["id", "labels", "questions", "schema", "state"])
        self.assertEqual(record["schema"], SCHEMA)
        self.assertEqual(prov["tier"], "L3")
        self.assertFalse(prov["consent"]["champion"])
        self.assertEqual(prov["id"], "x1")

    def test_split_row_refuses_what_the_frozen_validator_refuses(self) -> None:
        bad = _row(rid="b1", action="execute")  # one-option choice, no instructions
        with self.assertRaises(ValueError):
            split_row(bad)

    def test_read_rows_reads_strict_and_legacy_layouts(self) -> None:
        rows = [_strict_row("s1"), _strict_row("s2", "escalate")]
        legacy = {**_strict_row("old1"), "schema": LEGACY_SCHEMA}
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "curated_pack_v2.jsonl"
            self.assertEqual(write_pack(pack, rows), {})
            write_provenance(Path(tmp) / "curated_pack_v2_provenance.jsonl", rows, {"s2": "holdout"})
            on_disk = load_jsonl(pack)
            self.assertTrue(all("tier" not in r and "consent" not in r for r in on_disk))
            joined = read_rows(pack)
            self.assertEqual([r["tier"] for r in joined], ["L3", "L3"])
            self.assertEqual(joined[1]["split"], "holdout")
            old = Path(tmp) / "old.jsonl"
            write_jsonl(old, [legacy])
            upgraded = read_rows(old)
        self.assertEqual(upgraded[0]["schema"], SCHEMA)
        self.assertFalse(upgraded[0]["consent"]["champion"])

    def test_smoke_reads_strict_pack_with_sidecar(self) -> None:
        rows = [_strict_row(f"t{i}") for i in range(5)]
        train, hold = holdout_split(rows, seed=1, frac=0.20)
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp)
            write_pack(staging / "curated_pack_v2.jsonl", rows)
            write_pack(staging / "curated_pack_v2_train.jsonl", train)
            write_pack(staging / "curated_pack_v2_holdout.jsonl", hold)
            write_provenance(staging / "curated_pack_v2_provenance.jsonl", rows, {})
            report = smoke_pack_v2.smoke(staging)
        self.assertEqual(report["tiers"], {"L3": 5})
        self.assertEqual(report["l3_actions"], {"execute": 5})


class PackSmokeTests(unittest.TestCase):
    def test_smoke_pack_v2_on_tiny_fixture(self) -> None:
        rows = [_row(rid=f"p{i}", action="execute") for i in range(8)]
        train, hold = holdout_split(rows, seed=20260921, frac=0.20)
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp)
            write_jsonl(staging / "curated_pack_v2.jsonl", rows)
            write_jsonl(staging / "curated_pack_v2_train.jsonl", train)
            write_jsonl(staging / "curated_pack_v2_holdout.jsonl", hold)
            report = smoke_pack_v2.smoke(staging)
        self.assertEqual(report["total"], 8)
        self.assertEqual(report["champion_true"], 0)
        self.assertGreaterEqual(report["holdout_rows"] / report["total"], 0.20)

    def test_smoke_cli_exits_zero(self) -> None:
        rows = [_row(rid=f"q{i}", action="execute") for i in range(5)]
        train, hold = holdout_split(rows, seed=1, frac=0.20)
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp)
            write_jsonl(staging / "curated_pack_v2.jsonl", rows)
            write_jsonl(staging / "curated_pack_v2_train.jsonl", train)
            write_jsonl(staging / "curated_pack_v2_holdout.jsonl", hold)
            rc = smoke_pack_v2.main(["--staging", str(staging)])
        self.assertEqual(rc, 0)


class ManifestAndPatchTests(unittest.TestCase):
    def test_finalize_manifest_hashes_pack(self) -> None:
        rows = [_row(rid="m1", action="execute"), _row(rid="m2", action="halt")]
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "ultradata_harvest_20260922-120000"
            dest.mkdir()
            write_jsonl(dest / "curated_pack_v2.jsonl", rows)
            write_jsonl(dest / "curated_pack_v2_train.jsonl", rows[1:])
            write_jsonl(dest / "curated_pack_v2_holdout.jsonl", rows[:1])
            (dest / "curated_pack_v2_summary.json").write_text(
                json.dumps({"counts": {"total": 2, "by_tier": {"L3": 2}}}),
                encoding="utf-8",
            )
            rc = finalize_manifest.main(dest)
            manifest = json.loads((dest / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(rc, 0)
        self.assertEqual(manifest["rows"], 2)
        self.assertEqual(manifest["train_rows"], 1)
        self.assertEqual(manifest["holdout_rows"], 1)
        self.assertEqual(len(manifest["sha256_pack"]), 64)
        self.assertEqual(len(manifest["sha256_train"]), 64)
        self.assertEqual(len(manifest["sha256_holdout"]), 64)
        self.assertFalse(manifest["champion_touched"])
        self.assertFalse(manifest["live_gate_touched"])
        self.assertFalse(manifest["ft_kicked"])
        self.assertTrue(manifest["consent_champion_false"])

    def test_finalize_manifest_missing_train_fails(self) -> None:
        rows = [_row(rid="m1", action="execute"), _row(rid="m2", action="halt")]
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "ultradata_harvest_x"
            dest.mkdir()
            write_jsonl(dest / "curated_pack_v2.jsonl", rows)
            write_jsonl(dest / "curated_pack_v2_holdout.jsonl", rows[:1])
            with self.assertRaises(SystemExit) as ctx:
                finalize_manifest.main(dest)
        self.assertIn("missing train", str(ctx.exception))

    def test_finalize_manifest_missing_holdout_fails(self) -> None:
        rows = [_row(rid="m1", action="execute"), _row(rid="m2", action="halt")]
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "ultradata_harvest_x"
            dest.mkdir()
            write_jsonl(dest / "curated_pack_v2.jsonl", rows)
            write_jsonl(dest / "curated_pack_v2_train.jsonl", rows[:1])
            with self.assertRaises(SystemExit) as ctx:
                finalize_manifest.main(dest)
        self.assertIn("missing holdout", str(ctx.exception))

    def test_patch_hf_is_idempotent(self) -> None:
        stub = (
            "from __future__ import annotations\n"
            "import argparse\n"
            "def main():\n"
            "    parser = argparse.ArgumentParser()\n"
            '    parser.add_argument("--dataset", choices=["ag_news"])\n'
            "    args = parser.parse_args()\n"
            "    print(args.dataset)\n"
            'if __name__ == "__main__":\n'
            "    main()\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "hf_to_system_one.py"
            target.write_text(stub, encoding="utf-8")
            first = patch_hf.patch(target)
            second = patch_hf.patch(target)
            text = target.read_text(encoding="utf-8")
        self.assertIn("import", first["changed"])
        self.assertIn("dispatch", first["changed"])
        self.assertEqual(second["changed"], [])
        self.assertIn("pack_v2", text)
        self.assertIn("curate_pack_v2", text)
        self.assertFalse(text.startswith("\ufeff"))

    def test_harvest_module_import_does_not_run(self) -> None:
        harvest = _load("run_ultradata_harvest", LAB / "run_ultradata_harvest.py")
        self.assertTrue(callable(harvest.main))
        self.assertTrue((harvest.APP_ROOT / "sidecar" / "curation" / "ultradata_curriculum.py").is_file())


def _write_helper_pack(dest: Path) -> dict:
    """Tiny inbox pack whose MANIFEST hashes are computed from the files, never hardcoded."""
    rows = [_row(rid="k1", action="execute"), _row(rid="k2", action="halt")]
    train, hold = rows[:1], rows[1:]
    pack = dest / "curated_pack_v2.jsonl"
    train_path = dest / "curated_pack_v2_train.jsonl"
    hold_path = dest / "curated_pack_v2_holdout.jsonl"
    write_jsonl(pack, rows)
    write_jsonl(train_path, train)
    write_jsonl(hold_path, hold)
    manifest = {
        "pack_id": "curated_pack_v2-test",
        "rows": 2,
        "train_rows": 1,
        "holdout_rows": 1,
        "sha256_pack": kick_helper_ft.sha256_file(pack),
        "sha256_train": kick_helper_ft.sha256_file(train_path),
        "sha256_holdout": kick_helper_ft.sha256_file(hold_path),
        "champion_touched": False,
        "live_gate_touched": False,
        "ft_kicked": False,
        "consent_champion_false": True,
    }
    (dest / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


SWARM_HQ_PIN_CONTRACT_REQUIRED = kick_helper_ft.HQ_PIN_REQUIRED_KEYS
SWARM_HQ_PIN_CONTRACT_ALLOWED = kick_helper_ft.HQ_PIN_ALLOWED_KEYS
SWARM_HQ_AGENT_TOKEN_FIXTURE = "test-swarm-hq-agent-token"
TEST_CAM_PRIVATE = base64.b64decode("RcEEdi7r4yRF6hbT98+itrc4A5q7nXNg/b/DTBv1Ptw=")
TEST_CAM_KEY_ID = "cam-pin-ed25519-1"
PINNED_HQ_ORIGIN = "https://swarm-hq.test"
HQ_VECTOR_PATH = APP / "tests" / "fixtures" / "cam-pin-vector.json"
HQ_VECTOR_SHA256 = "ef12aada8b666079513f716fd9dee7c88176fa302050699ce76460b7aa180666"
_TEST_TRUST_BLOBS = {
    "apps/dottie-os/trust/cam_pin_ed25519.pub": "test-pub-blob",
    "apps/dottie-os/trust/cam_pin_key_id": "test-key-id-blob",
    "apps/dottie-os/scripts/lab/cam_pin_spec.py": "test-spec-blob",
    "HEAD": "test-head-sha",
}
DENIED_VECTOR_PUB_B64 = "hgbGCZRFE4CiwVB4rLZ015a8QkWEPPAjZT5UIQKDazk="


def _blob_patches(
    *,
    dirty: str | None = None,
    on_main: bool = True,
    head: str = "deadbeef",
) -> tuple[object, object, object]:
    """Mock git blob compares. Never writes apps/dottie-os/trust/."""
    root = cam_pin_spec.repo_root()
    committed = {rel: f"blob-{idx}" for idx, rel in enumerate(cam_pin_spec.TRUST_RELPATHS)}

    def ls(_root: Path, relpath: str) -> str:
        return committed[relpath]

    def hasher(path: Path) -> str:
        resolved = Path(path).resolve()
        for rel, sha in committed.items():
            if resolved == (root / rel).resolve():
                if rel == dirty:
                    return "dirty-" + sha
                return sha
        return "other"

    return (
        patch.object(cam_pin_spec, "_ls_tree_blob", side_effect=ls),
        patch.object(cam_pin_spec, "_hash_object", side_effect=hasher),
        patch.object(cam_pin_spec, "_head_is_on_main", return_value=(on_main, head)),
    )


def _sign_pin(pin: dict) -> dict:
    signed = dict(pin)
    signed.setdefault("cam_key_id", TEST_CAM_KEY_ID)
    message = cam_pin_spec.canonical_pin_bytes(signed)
    signed["cam_sig"] = cam_pin_spec.sign_pin_bytes(message, TEST_CAM_PRIVATE)
    return signed


SWARM_HQ_PIN_FIXTURE = _sign_pin(
    {
        "pack_id": "curated_pack_v2-contract",
        "sha256_pack": "11" * 32,
        "sha256_train": "22" * 32,
        "sha256_holdout": "33" * 32,
        "rows_total": 2,
        "rows_train": 1,
        "rows_holdout": 1,
        "pack_matches": True,
        "recordedBy": "cam",
        "recordedAt": "2026-10-19T00:00:00.000Z",
        "kid": "cam-stamp-kid-1",
        "stampVerified": True,
        "cam_key_id": TEST_CAM_KEY_ID,
    }
)


def _cam_pin(manifest: dict, **overrides: object) -> dict:
    pin = {
        "pack_id": manifest["pack_id"],
        "sha256_pack": manifest["sha256_pack"],
        "sha256_train": manifest["sha256_train"],
        "sha256_holdout": manifest["sha256_holdout"],
        "rows_total": manifest["rows"],
        "rows_train": manifest["train_rows"],
        "rows_holdout": manifest["holdout_rows"],
        "pack_matches": True,
        "recordedBy": "cam",
        "recordedAt": "2026-10-19T00:00:00.000Z",
        "kid": "cam-stamp-kid-1",
        "stampVerified": True,
        "cam_key_id": TEST_CAM_KEY_ID,
    }
    pin.update(overrides)
    if "cam_sig" not in overrides:
        pin = _sign_pin(pin)
    return pin


def _hq_http_error(url: str, code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "error", hdrs={}, fp=BytesIO(b""))


def _request_header(request: object, name: str) -> str:
    getter = getattr(request, "get_header", None)
    if callable(getter):
        for candidate in (name, "-".join(part.capitalize() for part in name.split("-"))):
            value = getter(candidate)
            if value:
                return str(value)
    raw = getattr(request, "headers", {}) or {}
    lowered = {str(key).lower(): str(value) for key, value in dict(raw).items()}
    return lowered.get(name.lower(), "")


class _FakeHqHttpResponse:
    """urllib-compatible HTTPS response for mocked Swarm HQ pin GETs."""

    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            return self._body
        return self._body[:n]

    def close(self) -> None:
        return None

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> "_FakeHqHttpResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _pack_id_from_pin_url(url: str) -> str:
    marker = "/api/packs/"
    start = url.index(marker) + len(marker)
    rest = url[start:]
    if rest.endswith("/pin"):
        rest = rest[: -len("/pin")]
    return urllib.parse.unquote(rest)


def _refresh_hashes(dest: Path, **overrides: object) -> dict:
    pack = dest / "curated_pack_v2.jsonl"
    train_path = dest / "curated_pack_v2_train.jsonl"
    hold_path = dest / "curated_pack_v2_holdout.jsonl"
    manifest = json.loads((dest / "MANIFEST.json").read_text(encoding="utf-8"))
    manifest["sha256_pack"] = kick_helper_ft.sha256_file(pack)
    manifest["sha256_train"] = kick_helper_ft.sha256_file(train_path)
    manifest["sha256_holdout"] = kick_helper_ft.sha256_file(hold_path)
    manifest["rows"] = sum(1 for line in pack.read_text(encoding="utf-8").splitlines() if line.strip())
    manifest["train_rows"] = sum(1 for line in train_path.read_text(encoding="utf-8").splitlines() if line.strip())
    manifest["holdout_rows"] = sum(1 for line in hold_path.read_text(encoding="utf-8").splitlines() if line.strip())
    manifest.update(overrides)
    (dest / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def _flip_one_ascii_byte(path: Path) -> None:
    """Change one file byte without adding a JSONL row or breaking UTF-8."""
    raw = bytearray(path.read_bytes())
    for idx, byte in enumerate(raw):
        if 65 <= byte <= 90 or 97 <= byte <= 122:
            raw[idx] = 88 if byte != 88 else 89
            path.write_bytes(bytes(raw))
            return
    raise AssertionError(f"no ASCII letter to flip in {path}")


def _cli_args(dest: Path, log_path: Path | None = None) -> list[str]:
    argv = ["--pack", str(dest)]
    if log_path is not None:
        argv.extend(["--log", str(log_path)])
    return argv


FORGE_PINS_SOURCE_COMMIT_FIXTURE = "c" * 40


def _live_entrypoint_pins() -> dict[str, str]:
    return {
        "apps/dottie-os/scripts/lab/kick_helper_ft.py": kick_helper_ft.sha256_file(
            Path(kick_helper_ft.__file__).resolve()
        ),
        "apps/dottie-os/scripts/lab/cam_pin_spec.py": kick_helper_ft.sha256_file(
            Path(cam_pin_spec.__file__).resolve()
        ),
    }


def _install_forge_entrypoint_pins(owner: unittest.TestCase) -> None:
    pins = _live_entrypoint_pins()
    os.environ[kick_helper_ft.FORGE_ENTRYPOINT_PINS_ENV] = json.dumps(pins)
    os.environ[kick_helper_ft.FORGE_PINS_SOURCE_COMMIT_ENV] = FORGE_PINS_SOURCE_COMMIT_FIXTURE
    owner.forge_entrypoint_pins = pins
    owner.forge_pins_source_commit = FORGE_PINS_SOURCE_COMMIT_FIXTURE


def _clear_forge_entrypoint_pins() -> None:
    os.environ.pop(kick_helper_ft.FORGE_ENTRYPOINT_PINS_ENV, None)
    os.environ.pop(kick_helper_ft.FORGE_PINS_SOURCE_COMMIT_ENV, None)


def _start_hq_http_mock(owner: unittest.TestCase) -> None:
    _install_forge_entrypoint_pins(owner)
    owner.hq_pins = {}
    owner.hq_error = None
    owner.hq_http_status = None
    owner.hq_redirect = None
    owner.hq_requests = []
    owner.hq_posts: list[dict] = []
    owner.hq_tokens_by_url: list[tuple[str, str]] = []
    owner.hq_saw_agent_token = False
    owner._origin_saved = cam_pin_spec.SWARM_HQ_ORIGIN
    cam_pin_spec.SWARM_HQ_ORIGIN = PINNED_HQ_ORIGIN
    os.environ["SWARM_HQ_URL"] = "https://evil-hq.example"
    os.environ["SWARM_HQ_AGENT_TOKEN"] = SWARM_HQ_AGENT_TOKEN_FIXTURE

    def fake_open_hq(request: object, timeout: object = None) -> _FakeHqHttpResponse:
        url = getattr(request, "full_url", None) or str(request)
        method = request.get_method() if hasattr(request, "get_method") else "GET"
        token = _request_header(request, "x-agent-token")
        owner.hq_tokens_by_url.append((str(url), token))
        owner.assertTrue(str(url).startswith(PINNED_HQ_ORIGIN), url)
        if method == "POST":
            raw = getattr(request, "data", None) or b""
            if isinstance(raw, str):
                raw = raw.encode("utf-8")
            body = json.loads(raw.decode("utf-8")) if raw else {}
            owner.hq_posts.append(
                {"url": str(url), "method": method, "body": body, "token": token}
            )
            owner.assertIn("/api/helper-ft/events/", str(url))
            owner.assertTrue(
                str(url).endswith("/kick") or str(url).endswith("/completion"),
                url,
            )
            if not token:
                raise _hq_http_error(str(url), 401)
            owner.hq_saw_agent_token = True
            if owner.hq_redirect is not None:
                code, location = owner.hq_redirect
                raise _hq_http_error(location, code)
            if owner.hq_http_status in (301, 302, 303, 307, 308):
                raise _hq_http_error(str(url), owner.hq_http_status)
            if owner.hq_http_status in (401, 404):
                raise _hq_http_error(str(url), owner.hq_http_status)
            if owner.hq_error is not None:
                raise urllib.error.URLError(owner.hq_error)
            return _FakeHqHttpResponse(b'{"ok":true}')
        owner.hq_requests.append(url)
        owner.assertEqual(method, "GET")
        owner.assertIn("/api/packs/", str(url))
        owner.assertTrue(str(url).endswith("/pin"), url)
        if not token:
            raise _hq_http_error(str(url), 401)
        owner.hq_saw_agent_token = True
        if owner.hq_redirect is not None:
            code, location = owner.hq_redirect
            raise _hq_http_error(location, code)
        if owner.hq_http_status in (301, 302, 303, 307, 308):
            raise _hq_http_error(str(url), owner.hq_http_status)
        if owner.hq_http_status in (401, 404):
            raise _hq_http_error(str(url), owner.hq_http_status)
        if owner.hq_error is not None:
            raise urllib.error.URLError(owner.hq_error)
        pack_id = _pack_id_from_pin_url(str(url))
        pin = owner.hq_pins.get(pack_id)
        if pin is None:
            raise _hq_http_error(str(url), 404)
        return _FakeHqHttpResponse(json.dumps(pin).encode("utf-8"))

    owner._urlopen_patcher = patch.object(cam_pin_spec, "open_hq", side_effect=fake_open_hq)
    owner._urlopen_patcher.start()
    test_pub = Ed25519PublicKey.from_public_bytes(
        cam_pin_spec.raw_public_from_private(TEST_CAM_PRIVATE)
    )
    owner._key_patcher = patch.object(
        cam_pin_spec,
        "load_cam_public_key",
        return_value=(TEST_CAM_KEY_ID, test_pub),
    )
    owner._key_patcher.start()
    owner._trust_patcher = patch.object(
        cam_pin_spec,
        "require_committed_trust",
        return_value=dict(_TEST_TRUST_BLOBS),
    )
    owner._trust_patcher.start()


def _stop_hq_http_mock(owner: unittest.TestCase) -> None:
    owner._urlopen_patcher.stop()
    owner._key_patcher.stop()
    owner._trust_patcher.stop()
    cam_pin_spec.SWARM_HQ_ORIGIN = owner._origin_saved
    os.environ.pop("SWARM_HQ_URL", None)
    os.environ.pop("SWARM_HQ_AGENT_TOKEN", None)
    _clear_forge_entrypoint_pins()


def _stage_run_private(dest: Path) -> Path:
    run_private = Path(tempfile.mkdtemp(prefix="inputs-", dir=str(dest.parent)))
    os.chmod(run_private, 0o700)
    for name in (
        "curated_pack_v2.jsonl",
        "curated_pack_v2_train.jsonl",
        "curated_pack_v2_holdout.jsonl",
        "MANIFEST.json",
    ):
        target = run_private / name
        shutil.copyfile(dest / name, target)
        os.chmod(target, 0o400)
    return run_private


def _wrap_hash_fns(*targets: tuple[object, str]) -> tuple[list[str], list[tuple[object, str, object]]]:
    calls: list[str] = []
    originals: list[tuple[object, str, object]] = []
    for obj, name in targets:
        orig = getattr(obj, name)
        originals.append((obj, name, orig))

        def _make(label: str, fn: object) -> object:
            def wrapped(*args: object, **kwargs: object) -> object:
                calls.append(label)
                return fn(*args, **kwargs)

            return wrapped

        setattr(obj, name, _make(name, orig))
    return calls, originals


def _restore_hash_fns(originals: list[tuple[object, str, object]]) -> None:
    for obj, name, orig in originals:
        setattr(obj, name, orig)


class HelperFtIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.kickoff_calls: list[dict] = []
        _start_hq_http_mock(self)

        def fake_post(body: dict, url: str | None = None) -> dict:
            self.kickoff_calls.append(body)
            self.assertNotEqual(body.get("inbox"), "latest")
            self.assertEqual(body.get("mode"), "helper-ft")
            recorded_by = body.get("pin", {}).get("recordedBy")
            if recorded_by is not None:
                self.assertIsInstance(recorded_by, str)
            return {"ok": True, "checkpoint_id": "ckpt-test"}

        self._orig_post = kick_helper_ft.post_kickoff
        kick_helper_ft.post_kickoff = fake_post

    def tearDown(self) -> None:
        kick_helper_ft.post_kickoff = self._orig_post
        _stop_hq_http_mock(self)
        for name in kick_helper_ft._FORBIDDEN_PIN_ENV:
            os.environ.pop(name, None)

    def _pin(self, manifest: dict, **overrides: object) -> dict:
        pin = _cam_pin(manifest, **overrides)
        self.hq_pins[manifest["pack_id"]] = pin
        return pin

    def test_match_lets_training_start(self) -> None:
        started: list[Path] = []
        original: Path | None = None

        def start(pack_dir: Path, evidence: dict, log_path: Path) -> None:
            started.append(pack_dir)
            self.assertTrue(evidence["ok"])
            self.assertEqual(evidence["pack_id"], "curated_pack_v2-test")
            self.assertEqual(evidence["anchor_source"], "swarm-hq-cam-pin")
            self.assertEqual(evidence["computed_shas"], evidence["expected_shas"])
            self.assertEqual(evidence["computed_shas"], evidence["manifest_shas"])
            self.assertEqual(log_path.name, "helper_ft.log")
            self.assertNotEqual(pack_dir.resolve(), original.resolve() if original else pack_dir)
            self.assertTrue((pack_dir / "curated_pack_v2.jsonl").is_file())
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(pack_dir.stat().st_mode), 0o700)
                self.assertEqual(
                    stat.S_IMODE((pack_dir / "curated_pack_v2.jsonl").stat().st_mode),
                    0o400,
                )

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            original = dest
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            log_path = Path(tmp) / "runs" / "helper_ft.log"
            evidence = kick_helper_ft.kick(
                dest, log_path=log_path, start_training=start)
            on_disk = json.loads(Path(evidence["evidence_path"]).read_text(encoding="utf-8"))
            rec = json.loads(
                Path(on_disk["checkpoint_integrity_evidence_path"]).read_text(encoding="utf-8")
            )
            rc = kick_helper_ft.main(_cli_args(dest, log_path))
        self.assertEqual(len(started), 1)
        self.assertGreaterEqual(len(self.kickoff_calls), 1)
        self.assertEqual(len(self.hq_requests), 2)
        self.assertTrue(
            self.hq_requests[0].startswith("https://swarm-hq.test/api/packs/"),
            self.hq_requests[0],
        )
        self.assertTrue(self.hq_requests[0].endswith("/pin"), self.hq_requests[0])
        kickoff_body = self.kickoff_calls[0]
        self.assertNotIn("inbox", kickoff_body)
        self.assertEqual(kickoff_body["pack_id"], "curated_pack_v2-test")
        self.assertEqual(kickoff_body["sha256_pack"], manifest["sha256_pack"])
        self.assertEqual(kickoff_body["sha256_train"], manifest["sha256_train"])
        self.assertEqual(kickoff_body["sha256_holdout"], manifest["sha256_holdout"])
        self.assertIn("run_private_dir", kickoff_body)
        self.assertIn("paths", kickoff_body)
        self.assertEqual(kickoff_body["expected_shas"]["sha256_pack"], manifest["sha256_pack"])
        self.assertEqual(kickoff_body["pin"]["pack_id"], "curated_pack_v2-test")
        self.assertEqual(kickoff_body["pin"]["recordedBy"], "cam")
        self.assertTrue(kickoff_body["pin"]["stampVerified"])
        self.assertTrue(kickoff_body["pin"]["pack_matches"])
        self.assertEqual(kickoff_body["pin"]["recordedAt"], "2026-10-19T00:00:00.000Z")
        self.assertEqual(kickoff_body["pin"]["kid"], "cam-stamp-kid-1")
        self.assertEqual(kickoff_body["pin"]["cam_key_id"], TEST_CAM_KEY_ID)
        self.assertTrue(kickoff_body["pin"]["cam_sig"])
        self.assertEqual(kickoff_body["pin"]["rows_total"], 2)
        self.assertEqual(kickoff_body["pin"]["rows_train"], 1)
        self.assertEqual(kickoff_body["pin"]["rows_holdout"], 1)
        self.assertTrue(kickoff_body["evidence"]["ok"])
        self.assertEqual(rc, 0)
        self.assertEqual(evidence["expected_shas"]["sha256_pack"], manifest["sha256_pack"])
        self.assertEqual(on_disk["computed_shas"], evidence["computed_shas"])
        self.assertEqual(on_disk["anchor_source"], "swarm-hq-cam-pin")
        dumped = json.dumps(on_disk) + json.dumps(kickoff_body)
        self.assertNotIn(SWARM_HQ_AGENT_TOKEN_FIXTURE, dumped)
        self.assertNotIn("x-agent-token", dumped.lower())
        self.assertTrue(self.hq_saw_agent_token)
        self.assertEqual(on_disk["checkpoint_id"], "ckpt-test")
        self.assertTrue(on_disk["run_id"])
        self.assertIn("pack_integrity_evidence_" + on_disk["run_id"], on_disk["evidence_path"])
        self.assertEqual(on_disk["host"], evidence["host"])
        self.assertTrue(on_disk["checked_at"].endswith("Z"))
        self.assertEqual(on_disk["row_counts"]["curated_pack_v2.jsonl"]["actual"], 2)
        self.assertEqual(on_disk["row_counts"]["curated_pack_v2_train.jsonl"]["actual"], 1)
        self.assertEqual(on_disk["row_counts"]["curated_pack_v2_holdout.jsonl"]["actual"], 1)
        self.assertNotEqual(Path(on_disk["evidence_path"]).parent, dest)
        self.assertTrue(Path(on_disk["paths"]["train"]).is_absolute())
        self.assertIn("script_git_sha", on_disk)
        self.assertTrue(on_disk["script_sha256"])
        self.assertEqual(len(on_disk["script_sha256"]), 64)
        self.assertEqual(on_disk["kickoff_url"], kick_helper_ft.DEFAULT_KICKOFF_URL)
        self.assertIn("post_train_shas", on_disk)
        self.assertEqual(on_disk["anchor_source"], "swarm-hq-cam-pin")
        self.assertTrue(all(u.startswith(PINNED_HQ_ORIGIN) for u in self.hq_requests))
        self.assertFalse(any("evil-hq.example" in u for u, _tok in self.hq_tokens_by_url))
        run_private = Path(kickoff_body["run_private_dir"]).resolve()
        self.assertEqual(set(kickoff_body["paths"]), {"pack", "train", "holdout", "manifest"})
        self.assertNotIn("pack_dir", kickoff_body["paths"])
        for path in kickoff_body["paths"].values():
            self.assertEqual(Path(path).resolve().parent, run_private)
            self.assertNotEqual(Path(path).resolve().parent, dest.resolve())
        self.assertEqual(kickoff_body["trainer_config"]["paths"], kickoff_body["paths"])
        self.assertEqual(kickoff_body["trainer_argv"], kick_helper_ft.build_trainer_argv(kickoff_body["paths"]))
        self.assertEqual(on_disk["paths"], kickoff_body["paths"])
        self.assertEqual(rec["status"], "MATCH")
        self.assertEqual(rec["host"], on_disk["host"])
        self.assertEqual(rec["paths"], kickoff_body["paths"])
        self.assertEqual(rec["computed_shas"], on_disk["computed_shas"])
        self.assertTrue(rec["match"])

    def test_one_byte_change_in_any_file_refuses(self) -> None:
        files = (
            "curated_pack_v2.jsonl",
            "curated_pack_v2_train.jsonl",
            "curated_pack_v2_holdout.jsonl",
        )
        fields = ("sha256_pack", "sha256_train", "sha256_holdout")
        for filename, field in zip(files, fields, strict=True):
            with self.subTest(file=filename):
                started: list[Path] = []

                def start(pack_dir: Path, evidence: dict, log_path: Path) -> None:
                    started.append(pack_dir)

                with tempfile.TemporaryDirectory() as tmp:
                    dest = Path(tmp) / "inbox-pack"
                    dest.mkdir()
                    manifest = _write_helper_pack(dest)
                    self._pin(manifest)
                    target = dest / filename
                    _flip_one_ascii_byte(target)
                    with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                        kick_helper_ft.kick(dest, start_training=start)
                    rc = kick_helper_ft.main(_cli_args(dest))
                self.assertEqual(started, [])
                self.assertEqual(self.kickoff_calls, [])
                self.assertEqual(rc, 1)
                self.assertEqual(ctx.exception.field, field)
                self.assertNotEqual(ctx.exception.expected, ctx.exception.actual)
                self.assertIn(field, str(ctx.exception))
                self.assertIn("expected", str(ctx.exception))
                self.assertIn("actual", str(ctx.exception))

    def test_missing_manifest_field_refuses(self) -> None:
        started: list[Path] = []

        def start(pack_dir: Path, evidence: dict, log_path: Path) -> None:
            started.append(pack_dir)

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            original = _write_helper_pack(dest)
            self._pin(original)
            manifest_path = dest / "MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            del manifest["sha256_train"]
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest, start_training=start)
            rc = kick_helper_ft.main(_cli_args(dest))
        self.assertEqual(started, [])
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(rc, 1)
        self.assertEqual(ctx.exception.field, "sha256_train")
        self.assertEqual(ctx.exception.expected, "present")
        self.assertEqual(ctx.exception.actual, "missing")

    def test_pack_and_manifest_rewritten_together_refuses(self) -> None:
        started: list[Path] = []

        def start(pack_dir: Path, evidence: dict, log_path: Path) -> None:
            started.append(pack_dir)

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            ticket = _write_helper_pack(dest)
            self._pin(ticket)
            pack = dest / "curated_pack_v2.jsonl"
            _flip_one_ascii_byte(pack)
            host_manifest = json.loads((dest / "MANIFEST.json").read_text(encoding="utf-8"))
            host_manifest["sha256_pack"] = kick_helper_ft.sha256_file(pack)
            (dest / "MANIFEST.json").write_text(json.dumps(host_manifest, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest, start_training=start)
            rc = kick_helper_ft.main(_cli_args(dest))
        self.assertEqual(started, [])
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(rc, 1)
        self.assertEqual(ctx.exception.field, "sha256_pack")
        self.assertEqual(ctx.exception.expected, ticket["sha256_pack"])
        self.assertEqual(ctx.exception.actual, host_manifest["sha256_pack"])
        self.assertNotEqual(ctx.exception.expected, ctx.exception.actual)

    def test_swap_after_check_does_not_affect_training(self) -> None:
        trained_bytes: list[bytes] = []

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            pack = dest / "curated_pack_v2.jsonl"
            original = pack.read_bytes()

            def start(copy_dir: Path, evidence: dict, log_path: Path) -> None:
                pack.write_bytes(original + b"SWAPPED")
                trained_bytes.append((copy_dir / "curated_pack_v2.jsonl").read_bytes())
                self.assertNotEqual(copy_dir.resolve(), dest.resolve())

            evidence = kick_helper_ft.kick(dest, start_training=start)
            self.assertEqual(pack.read_bytes(), original + b"SWAPPED")
            self.assertTrue(evidence["ok"])
            self.assertEqual(evidence["post_train_shas"]["sha256_pack"], evidence["computed_shas"]["sha256_pack"])
        self.assertEqual(trained_bytes, [original])
        self.assertEqual(len(self.kickoff_calls), 1)

    def test_symlinked_file_refuses(self) -> None:
        started: list[Path] = []

        def start(pack_dir: Path, evidence: dict, log_path: Path) -> None:
            started.append(pack_dir)

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            pack = dest / "curated_pack_v2.jsonl"
            elsewhere = dest / "elsewhere.jsonl"
            elsewhere.write_bytes(pack.read_bytes())
            pack.unlink()
            try:
                os.symlink(elsewhere, pack)
            except OSError as exc:
                self.skipTest(f"cannot create symlink: {exc}")
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest, start_training=start)
            rc = kick_helper_ft.main(_cli_args(dest))
        self.assertEqual(started, [])
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(rc, 1)
        self.assertEqual(ctx.exception.field, "curated_pack_v2.jsonl")
        self.assertEqual(ctx.exception.expected, "regular file")
        self.assertEqual(ctx.exception.actual, "symlink")

    def test_missing_anchor_refuses(self) -> None:
        started: list[Path] = []

        def start(pack_dir: Path, evidence: dict, log_path: Path) -> None:
            started.append(pack_dir)

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            _write_helper_pack(dest)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest, start_training=start)
            rc = kick_helper_ft.main(_cli_args(dest))
        self.assertEqual(started, [])
        self.assertEqual(self.kickoff_calls, [])
        self.assertGreaterEqual(len(self.hq_requests), 1)
        self.assertEqual(rc, 1)
        self.assertEqual(ctx.exception.field, "cam-pin")
        self.assertEqual(ctx.exception.expected, "present")
        self.assertEqual(ctx.exception.actual, "HTTP 404")

    def test_pin_mismatching_manifest_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            host = json.loads((dest / "MANIFEST.json").read_text(encoding="utf-8"))
            host["sha256_pack"] = "a" * 64
            (dest / "MANIFEST.json").write_text(json.dumps(host, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(ctx.exception.field, "sha256_pack")
        self.assertEqual(ctx.exception.expected, manifest["sha256_pack"])
        self.assertEqual(ctx.exception.actual, "a" * 64)

    def test_pin_for_different_pack_id_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest, pack_id="other-pack")
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(len(self.hq_requests), 1)
        self.assertEqual(ctx.exception.field, "cam-pin.pack_id")
        self.assertEqual(ctx.exception.expected, manifest["pack_id"])
        self.assertEqual(ctx.exception.actual, "other-pack")

    def test_stamp_verified_false_is_advisory_and_not_sufficient(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            pin = self._pin(manifest, stampVerified=False)
            self.assertIs(pin["stampVerified"], False)
            evidence = kick_helper_ft.kick(dest)
        self.assertTrue(evidence["ok"])
        self.assertEqual(len(self.kickoff_calls), 1)

    def test_recorded_by_is_advisory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest, recordedBy="agent")
            evidence = kick_helper_ft.kick(dest)
        self.assertTrue(evidence["ok"])
        self.assertEqual(len(self.kickoff_calls), 1)

    def test_pin_one_sha_off_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest, sha256_train="0" * 64)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(len(self.hq_requests), 1)
        self.assertEqual(ctx.exception.field, "sha256_train")
        self.assertEqual(ctx.exception.expected, "0" * 64)

    def test_pack_matches_false_is_advisory_never_sufficient(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            pin = self._pin(manifest, pack_matches=False)
            self.assertTrue(pin["stampVerified"])
            self.assertIs(pin["pack_matches"], False)
            evidence = kick_helper_ft.kick(dest)
        self.assertTrue(evidence["ok"])
        self.assertEqual(len(self.kickoff_calls), 1)

    def test_pin_one_row_count_off_refuses(self) -> None:
        cases = (
            ("rows_total", 99),
            ("rows_train", 0),
            ("rows_holdout", 7),
        )
        for field, wrong in cases:
            with self.subTest(field=field):
                self.kickoff_calls.clear()
                with tempfile.TemporaryDirectory() as tmp:
                    dest = Path(tmp) / "inbox-pack"
                    dest.mkdir()
                    manifest = _write_helper_pack(dest)
                    pin = self._pin(manifest, **{field: wrong})
                    self.assertTrue(pin["stampVerified"])
                    self.assertTrue(pin["pack_matches"])
                    self.assertEqual(pin["sha256_pack"], manifest["sha256_pack"])
                    with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                        kick_helper_ft.kick(dest)
                    rc = kick_helper_ft.main(_cli_args(dest))
                self.assertEqual(self.kickoff_calls, [])
                self.assertEqual(rc, 1)
                self.assertEqual(ctx.exception.field, field)
                self.assertEqual(ctx.exception.expected, wrong)
                self.assertNotEqual(ctx.exception.actual, wrong)

    def test_pin_missing_row_field_refuses(self) -> None:
        for field in ("rows_total", "rows_train", "rows_holdout"):
            with self.subTest(field=field):
                self.kickoff_calls.clear()
                with tempfile.TemporaryDirectory() as tmp:
                    dest = Path(tmp) / "inbox-pack"
                    dest.mkdir()
                    manifest = _write_helper_pack(dest)
                    pin = self._pin(manifest)
                    del pin[field]
                    with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                        kick_helper_ft.kick(dest)
                    rc = kick_helper_ft.main(_cli_args(dest))
                self.assertEqual(self.kickoff_calls, [])
                self.assertEqual(rc, 1)
                self.assertEqual(ctx.exception.field, f"cam-pin.{field}")
                self.assertEqual(ctx.exception.expected, "present")
                self.assertEqual(ctx.exception.actual, "missing")

    def test_pack_matches_true_is_not_enough_when_disk_sha_differs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            pin = self._pin(manifest)
            self.assertTrue(pin["stampVerified"])
            self.assertTrue(pin["pack_matches"])
            _flip_one_ascii_byte(dest / "curated_pack_v2_train.jsonl")
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
            rc = kick_helper_ft.main(_cli_args(dest))
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(rc, 1)
        self.assertEqual(ctx.exception.field, "sha256_train")
        self.assertEqual(ctx.exception.expected, pin["sha256_train"])
        self.assertNotEqual(ctx.exception.actual, pin["sha256_train"])

    def test_pack_matches_true_is_not_enough_when_disk_row_count_differs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            pin = self._pin(manifest)
            self.assertTrue(pin["stampVerified"])
            self.assertTrue(pin["pack_matches"])
            train = dest / "curated_pack_v2_train.jsonl"
            train.write_bytes(train.read_bytes() + b'{"id":"extra-row"}\n')
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
            rc = kick_helper_ft.main(_cli_args(dest))
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(rc, 1)
        self.assertEqual(ctx.exception.field, "rows_train")
        self.assertEqual(ctx.exception.expected, 1)
        self.assertEqual(ctx.exception.actual, 2)

    def test_pin_api_unreachable_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            _write_helper_pack(dest)
            self.hq_error = "timed out"
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(len(self.hq_requests), 1)
        self.assertTrue(self.hq_requests[0].startswith("https://swarm-hq.test/api/packs/"))
        self.assertEqual(ctx.exception.field, "cam-pin")
        self.assertEqual(ctx.exception.expected, "HTTPS Swarm HQ pin")
        self.assertIn("unreachable", str(ctx.exception.actual))

    def test_pin_fetch_is_https_swarm_hq_not_redis_or_paste(self) -> None:
        spec_src = Path(cam_pin_spec.__file__).read_text(encoding="utf-8")
        src = Path(kick_helper_ft.__file__).read_text(encoding="utf-8")
        self.assertIn("SWARM_HQ_ORIGIN", spec_src)
        self.assertNotIn("SWARM_HQ_URL_ENV", src)
        self.assertIn("SWARM_HQ_AGENT_TOKEN", spec_src)
        self.assertIn("x-agent-token", spec_src)
        self.assertIn("/api/packs/", spec_src)
        self.assertIn("/pin", spec_src)
        self.assertIn("https://", spec_src)
        self.assertNotIn("import redis", src)
        self.assertNotIn("from redis", src)
        option_strings = [
            flag
            for action in kick_helper_ft.build_parser()._actions
            for flag in action.option_strings
        ]
        self.assertNotIn("--cam-pin", option_strings)
        cam_pin_spec.SWARM_HQ_ORIGIN = "http://swarm-hq.test"
        before = list(self.hq_requests)
        with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
            kick_helper_ft.fetch_cam_pin("curated_pack_v2-test")
        self.assertEqual(self.hq_requests, before)
        self.assertEqual(ctx.exception.field, "SWARM_HQ_ORIGIN")
        self.assertEqual(ctx.exception.expected, "https URL")

    def test_cam_pin_cli_is_unknown_argument_before_hash_or_kickoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            argv = _cli_args(dest) + ["--cam-pin", json.dumps(_cam_pin(manifest))]
            _args, unknown = kick_helper_ft.build_parser().parse_known_args(argv)
            hash_calls, originals = _wrap_hash_fns(
                (kick_helper_ft, "_copy_and_hash"),
                (kick_helper_ft, "sha256_file"),
            )
            try:
                rc = kick_helper_ft.main(argv)
            finally:
                _restore_hash_fns(originals)
        self.assertEqual(unknown[0], "--cam-pin")
        self.assertEqual(rc, 1)
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(hash_calls, [])
        self.assertEqual(self.hq_requests, [])

    def test_pin_env_var_refuses_before_hash_or_kickoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            os.environ["CAM_PIN"] = json.dumps(_cam_pin(manifest))
            hash_calls, originals = _wrap_hash_fns(
                (kick_helper_ft, "_copy_and_hash"),
                (kick_helper_ft, "sha256_file"),
            )
            try:
                with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                    kick_helper_ft.kick(dest)
                rc = kick_helper_ft.main(_cli_args(dest))
            finally:
                os.environ.pop("CAM_PIN", None)
                _restore_hash_fns(originals)
        self.assertEqual(rc, 1)
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(hash_calls, [])
        self.assertEqual(self.hq_requests, [])
        self.assertEqual(ctx.exception.field, "CAM_PIN")
        self.assertEqual(ctx.exception.expected, "unset")
        self.assertEqual(ctx.exception.actual, "set")

    def test_local_pin_file_refuses_before_hash_or_kickoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            (dest / "cam-pin.json").write_text(
                json.dumps(_cam_pin(manifest)), encoding="utf-8"
            )
            hash_calls, originals = _wrap_hash_fns(
                (kick_helper_ft, "_copy_and_hash"),
                (kick_helper_ft, "sha256_file"),
            )
            try:
                with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                    kick_helper_ft.kick(dest)
                rc = kick_helper_ft.main(_cli_args(dest))
            finally:
                _restore_hash_fns(originals)
        self.assertEqual(rc, 1)
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(hash_calls, [])
        self.assertEqual(ctx.exception.field, "cam-pin.json")
        self.assertEqual(ctx.exception.expected, "absent")
        self.assertEqual(ctx.exception.actual, "local pin file")

    def test_train_hook_direct_call_refuses(self) -> None:
        with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
            kick_helper_ft.default_start_training(Path("."), {}, Path("helper_ft.log"))
        self.assertEqual(ctx.exception.field, "start_training")
        self.assertEqual(ctx.exception.expected, "via kick() after integrity gate")
        self.assertEqual(ctx.exception.actual, "direct call")

    def test_skip_env_does_not_open_the_gate(self) -> None:
        started: list[Path] = []

        def start(pack_dir: Path, evidence: dict, log_path: Path) -> None:
            started.append(pack_dir)

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            os.environ["DOTTIE_SKIP_HELPER_FT_GATE"] = "1"
            try:
                with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                    kick_helper_ft.kick(dest, start_training=start)
            finally:
                del os.environ["DOTTIE_SKIP_HELPER_FT_GATE"]
        self.assertEqual(started, [])
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(ctx.exception.field, "DOTTIE_SKIP_HELPER_FT_GATE")
        option_strings = [
            flag
            for action in kick_helper_ft.build_parser()._actions
            for flag in action.option_strings
        ]
        for banned in (
            "--force",
            "--skip",
            "--no-verify",
            "--override",
            "--cam-pin",
            "--expected-sha256-pack",
            "--expected-sha256-train",
            "--expected-sha256-holdout",
            "--anchor-source",
        ):
            self.assertNotIn(banned, option_strings)

    def test_post_train_copy_mismatch_marks_evidence_not_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            log_path = Path(tmp) / "runs" / "helper_ft.log"

            def start(copy_dir: Path, evidence: dict, log_path: Path) -> None:
                target = copy_dir / "curated_pack_v2.jsonl"
                os.chmod(target, 0o600)
                target.write_bytes(target.read_bytes() + b"x")
                os.chmod(target, 0o400)

            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(
                    dest, log_path=log_path, start_training=start)
            files = list(log_path.parent.glob("pack_integrity_evidence_*.json"))
            self.assertEqual(len(files), 1)
            on_disk = json.loads(files[0].read_text(encoding="utf-8"))
            ckpt = log_path.parent / "ckpt-test" / "integrity_evidence.json"
            rec = json.loads(ckpt.read_text(encoding="utf-8"))
            status = kick_helper_ft.checkpoint_integrity_status(log_path.parent / "ckpt-test")
        self.assertFalse(on_disk["ok"])
        self.assertEqual(ctx.exception.field, "sha256_pack")
        self.assertEqual(len(self.kickoff_calls), 1)
        self.assertEqual(rec["status"], "REFUSED")
        self.assertEqual(rec["host"], on_disk["host"])
        self.assertEqual(rec["paths"], on_disk["paths"])
        self.assertFalse(rec["match"])
        self.assertEqual(status, "REFUSED")

    def test_refused_run_never_leaves_ok_true_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            _write_helper_pack(dest)
            log_path = Path(tmp) / "runs" / "helper_ft.log"
            with self.assertRaises(kick_helper_ft.KickRefused):
                kick_helper_ft.kick(dest, log_path=log_path)
            files = list(log_path.parent.glob("pack_integrity_evidence_*.json"))
            self.assertEqual(len(files), 1)
            on_disk = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertFalse(on_disk["ok"])
        self.assertEqual(self.kickoff_calls, [])

    def test_missing_file_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            (dest / "curated_pack_v2_train.jsonl").unlink()
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(ctx.exception.field, "curated_pack_v2_train.jsonl")
        self.assertEqual(ctx.exception.expected, "present")
        self.assertEqual(ctx.exception.actual, "missing")

    def test_missing_manifest_file_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            (dest / "MANIFEST.json").unlink()
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(ctx.exception.field, "MANIFEST.json")
        self.assertEqual(ctx.exception.expected, "present")
        self.assertEqual(ctx.exception.actual, "missing")

    def test_row_count_mismatch_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            host = json.loads((dest / "MANIFEST.json").read_text(encoding="utf-8"))
            host["rows"] = 99
            (dest / "MANIFEST.json").write_text(json.dumps(host, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(ctx.exception.field, "rows_total")
        self.assertEqual(ctx.exception.expected, 2)
        self.assertEqual(ctx.exception.actual, 99)

    def test_row_count_rejects_bool_and_str(self) -> None:
        for bad in (True, "2", 2.0):
            with self.subTest(bad=bad):
                self.kickoff_calls.clear()
                with tempfile.TemporaryDirectory() as tmp:
                    dest = Path(tmp) / "inbox-pack"
                    dest.mkdir()
                    manifest = _write_helper_pack(dest)
                    self._pin(manifest)
                    host = json.loads((dest / "MANIFEST.json").read_text(encoding="utf-8"))
                    host["train_rows"] = bad
                    (dest / "MANIFEST.json").write_text(json.dumps(host, indent=2) + "\n", encoding="utf-8")
                    with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                        kick_helper_ft.kick(dest)
                self.assertEqual(self.kickoff_calls, [])
                self.assertEqual(ctx.exception.field, "train_rows")
                self.assertEqual(ctx.exception.expected, "int")

    def test_missing_row_field_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            host = json.loads((dest / "MANIFEST.json").read_text(encoding="utf-8"))
            del host["holdout_rows"]
            (dest / "MANIFEST.json").write_text(json.dumps(host, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(ctx.exception.field, "holdout_rows")
        self.assertEqual(ctx.exception.expected, "present")
        self.assertEqual(self.kickoff_calls, [])

    def test_pack_id_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            host = json.loads((dest / "MANIFEST.json").read_text(encoding="utf-8"))
            del host["pack_id"]
            (dest / "MANIFEST.json").write_text(json.dumps(host, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(ctx.exception.field, "pack_id")
        self.assertEqual(ctx.exception.expected, "present")
        self.assertEqual(self.kickoff_calls, [])

    def test_champion_touched_must_be_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            host = json.loads((dest / "MANIFEST.json").read_text(encoding="utf-8"))
            host["champion_touched"] = True
            (dest / "MANIFEST.json").write_text(json.dumps(host, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(ctx.exception.field, "champion_touched")
        self.assertEqual(ctx.exception.expected, False)
        self.assertEqual(self.kickoff_calls, [])

    def test_duplicate_manifest_keys_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            original = (dest / "MANIFEST.json").read_text(encoding="utf-8")
            (dest / "MANIFEST.json").write_text(
                original.replace('"pack_id":', '"pack_id": "dup",\n  "pack_id":', 1),
                encoding="utf-8",
            )
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(ctx.exception.field, "MANIFEST.json")
        self.assertEqual(ctx.exception.expected, "unique keys")
        self.assertEqual(self.kickoff_calls, [])

    def test_holdout_identical_to_train_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            _write_helper_pack(dest)
            train = (dest / "curated_pack_v2_train.jsonl").read_bytes()
            (dest / "curated_pack_v2_holdout.jsonl").write_bytes(train)
            (dest / "curated_pack_v2.jsonl").write_bytes(train + train)
            manifest = _refresh_hashes(dest)
            self._pin(manifest)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(ctx.exception.field, "split")
        self.assertEqual(ctx.exception.expected, "train and holdout distinct")
        self.assertEqual(self.kickoff_calls, [])

    def test_holdout_row_hash_leak_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            _write_helper_pack(dest)
            rows = [
                _row(rid="a1", action="execute"),
                _row(rid="a2", action="halt"),
                _row(rid="a1", action="execute"),
            ]
            write_jsonl(dest / "curated_pack_v2_train.jsonl", rows[:2])
            write_jsonl(dest / "curated_pack_v2_holdout.jsonl", [rows[0]])
            write_jsonl(dest / "curated_pack_v2.jsonl", rows)
            manifest = _refresh_hashes(dest)
            self._pin(manifest)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(ctx.exception.field, "split")
        self.assertIn("row-hash leak", str(ctx.exception.actual))
        self.assertEqual(self.kickoff_calls, [])

    def test_holdout_trajectory_id_leak_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            _write_helper_pack(dest)
            train_row = _row(rid="same-id", action="execute")
            hold_row = _row(rid="same-id", action="halt")
            write_jsonl(dest / "curated_pack_v2_train.jsonl", [train_row])
            write_jsonl(dest / "curated_pack_v2_holdout.jsonl", [hold_row])
            write_jsonl(dest / "curated_pack_v2.jsonl", [train_row, hold_row])
            manifest = _refresh_hashes(dest)
            self._pin(manifest)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(ctx.exception.field, "split")
        self.assertIn("trajectory_id leak", str(ctx.exception.actual))
        self.assertEqual(self.kickoff_calls, [])

    def test_pack_not_union_of_splits_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            _write_helper_pack(dest)
            extra = _row(rid="extra", action="execute")
            train = [_row(rid="t1", action="execute")]
            hold = [_row(rid="h1", action="halt")]
            write_jsonl(dest / "curated_pack_v2_train.jsonl", train)
            write_jsonl(dest / "curated_pack_v2_holdout.jsonl", hold)
            write_jsonl(dest / "curated_pack_v2.jsonl", train + hold + [extra])
            manifest = _refresh_hashes(dest)
            self._pin(manifest)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(ctx.exception.field, "split")
        self.assertEqual(ctx.exception.actual, "row-set mismatch")
        self.assertEqual(self.kickoff_calls, [])

    def test_invalid_encoding_is_clean_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            (dest / "MANIFEST.json").write_bytes(b'{"pack_id": "x"\xff}')
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(ctx.exception.field, "MANIFEST.json")
        self.assertEqual(ctx.exception.expected, "utf-8 text")
        self.assertEqual(ctx.exception.actual, "invalid encoding")
        self.assertEqual(self.kickoff_calls, [])

    def test_kickoff_failure_updates_evidence(self) -> None:
        def boom(body: dict, url: str | None = None) -> dict:
            self.kickoff_calls.append(body)
            raise kick_helper_ft.KickRefused("kickoff", "ok", {"ok": False})

        kick_helper_ft.post_kickoff = boom
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            log_path = Path(tmp) / "runs" / "helper_ft.log"
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest, log_path=log_path)
            files = list(log_path.parent.glob("pack_integrity_evidence_*.json"))
            self.assertEqual(len(files), 1)
            on_disk = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertFalse(on_disk["ok"])
        self.assertEqual(on_disk["field"], "kickoff")
        self.assertEqual(ctx.exception.field, "kickoff")
        self.assertEqual(len(self.kickoff_calls), 1)

    def test_checks_fail_closed_if_row_file_or_manifest_removed(self) -> None:
        src = Path(kick_helper_ft.__file__).read_text(encoding="utf-8")
        self.assertIn("if rows_field not in manifest", src)
        self.assertIn("if actual_rows != expected_rows", src)
        self.assertIn('_refuse(filename, "present", "missing")', src)
        self.assertIn("_regular_file_in_pack(pack_root, MANIFEST_FILE)", src)
        self.assertIn("FileNotFoundError", src)

    def test_handler_refuses_inbox_latest_and_missing_evidence(self) -> None:
        latest = helper_ft_kickoff.handle_train_kickoff(
            {"mode": "helper-ft", "inbox": "latest", "pack_id": "p", "evidence": {"ok": True, "pack_id": "p"}}
        )
        self.assertFalse(latest["ok"])
        self.assertEqual(latest["field"], "inbox")
        self.assertEqual(latest["actual"], "latest")
        missing = helper_ft_kickoff.handle_train_kickoff({"mode": "helper-ft", "pack_id": "p"})
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["field"], "evidence")
        validate = helper_ft_kickoff.handle_train_kickoff({"mode": "inbox-validate"})
        self.assertFalse(validate["ok"])
        self.assertEqual(validate["field"], "mode")
        not_ok = helper_ft_kickoff.handle_train_kickoff(
            {"mode": "helper-ft", "pack_id": "p", "evidence": {"ok": False, "pack_id": "p"}}
        )
        self.assertFalse(not_ok["ok"])
        self.assertEqual(not_ok["field"], "evidence.ok")
        mismatched = helper_ft_kickoff.handle_train_kickoff(
            {
                "mode": "helper-ft",
                "pack_id": "named-pack",
                "evidence": {"ok": True, "pack_id": "other-pack"},
            }
        )
        self.assertFalse(mismatched["ok"])
        self.assertEqual(mismatched["field"], "pack_id")

    def test_handler_refuses_sha_mismatch_on_named_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            body = _fresh_kickoff_body(dest, manifest)
            body["sha256_pack"] = "a" * 64
            body["expected_shas"]["sha256_pack"] = "a" * 64
            body["pin"]["sha256_pack"] = "a" * 64
            body["evidence"]["expected_shas"]["sha256_pack"] = "a" * 64
            body["evidence"]["computed_shas"]["sha256_pack"] = "a" * 64
            body["evidence"]["pin"]["sha256_pack"] = "a" * 64
            result = helper_ft_kickoff.handle_train_kickoff(
                body, launch_trainer=lambda _b: {"ok": True, "launched": True}
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["field"], "pin")

    def test_handler_accepts_matching_named_pack(self) -> None:
        launched: list[dict] = []

        def stub(body: dict) -> dict:
            launched.append(body)
            return {"ok": True, "checkpoint_id": "ckpt", "launched": True}

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            body = _fresh_kickoff_body(dest, manifest)
            result = helper_ft_kickoff.handle_train_kickoff(body, launch_trainer=stub)
        self.assertTrue(result["ok"])
        self.assertEqual(result["pack_id"], manifest["pack_id"])
        self.assertEqual(len(launched), 1)

    def test_forge_runner_kickoff_never_accepts_latest(self) -> None:
        repo = Path(__file__).resolve().parents[3]
        loop_src = repo / "packages" / "dottie-loop"
        runner_path = loop_src / "scripts" / "forge_runner.py"
        src = runner_path.read_text(encoding="utf-8")
        self.assertIn("helper_ft_kickoff.py", src)
        self.assertIn("inbox_latest", src)
        self.assertIn("latest", src)
        self.assertIn('body.get("mode") == "inbox-validate"', src)
        if str(loop_src) not in sys.path:
            sys.path.insert(0, str(loop_src))
        runner = _load("forge_runner_kickoff", runner_path)
        refused = runner.handle_train_kickoff(
            {"mode": "helper-ft", "inbox": "latest", "evidence": {"ok": True, "pack_id": "p"}, "pack_id": "p"}
        )
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["field"], "inbox")
        missing = runner.handle_train_kickoff({"mode": "helper-ft", "pack_id": "p"})
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["field"], "evidence")

    def test_default_evidence_lives_in_run_dir_not_inbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            evidence = kick_helper_ft.kick(dest)
            evidence_path = Path(evidence["evidence_path"])
            self.assertTrue(evidence_path.is_file())
            self.assertFalse(str(evidence_path).startswith(str(dest.resolve())))
            self.assertIn(evidence["run_id"], evidence_path.name)


def _fresh_kickoff_body(dest: Path, manifest: dict, *, run_id: str = "helper-ft-test-run") -> dict:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    shas = {
        "sha256_pack": manifest["sha256_pack"],
        "sha256_train": manifest["sha256_train"],
        "sha256_holdout": manifest["sha256_holdout"],
    }
    pin = _cam_pin(manifest)
    run_private = _stage_run_private(dest)
    trainer_paths = {
        "pack": str((run_private / "curated_pack_v2.jsonl").resolve()),
        "train": str((run_private / "curated_pack_v2_train.jsonl").resolve()),
        "holdout": str((run_private / "curated_pack_v2_holdout.jsonl").resolve()),
        "manifest": str((run_private / "MANIFEST.json").resolve()),
    }
    return {
        "mode": "helper-ft",
        "pack_id": manifest["pack_id"],
        "run_id": run_id,
        "checked_at": now,
        "sha256_pack": shas["sha256_pack"],
        "sha256_train": shas["sha256_train"],
        "sha256_holdout": shas["sha256_holdout"],
        "expected_shas": dict(shas),
        "pin": pin,
        "run_private_dir": str(run_private.resolve()),
        "paths": dict(trainer_paths),
        "evidence": {
            "ok": True,
            "pack_id": manifest["pack_id"],
            "run_id": run_id,
            "checked_at": now,
            "computed_shas": dict(shas),
            "expected_shas": dict(shas),
            "manifest_shas": dict(shas),
            "pin": dict(pin),
            "paths": dict(trainer_paths),
            "run_private_dir": str(run_private.resolve()),
        },
    }


class HelperFtKickoffHttpTests(unittest.TestCase):
    """Real :8765 handler via its WSGI test client. Trainer launch is stubbed below the gate."""

    def setUp(self) -> None:
        self.launches: list[dict] = []
        _start_hq_http_mock(self)

        def stub_trainer(body: dict) -> dict:
            self.launches.append(body)
            return {"ok": True, "checkpoint_id": "stub-ckpt"}

        self.client = helper_ft_kickoff.TestClient(launch_trainer=stub_trainer)

    def tearDown(self) -> None:
        _stop_hq_http_mock(self)

    def _pin(self, manifest: dict, **overrides: object) -> dict:
        pin = _cam_pin(manifest, **overrides)
        self.hq_pins[manifest["pack_id"]] = pin
        return pin

    def test_http_no_evidence_refuses_before_trainer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            body = _fresh_kickoff_body(dest, manifest)
            del body["evidence"]
            response = self.client.post("/train/kickoff", json=body)
        payload = response.json()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["field"], "evidence")
        self.assertEqual(self.launches, [])

    def test_http_stale_evidence_run_id_refuses_before_trainer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            body = _fresh_kickoff_body(dest, manifest, run_id="run-current")
            body["evidence"]["run_id"] = "run-previous"
            response = self.client.post("/train/kickoff", json=body)
        payload = response.json()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["field"], "evidence.run_id")
        self.assertEqual(self.launches, [])

    def test_http_stale_evidence_timestamp_refuses_before_trainer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            body = _fresh_kickoff_body(dest, manifest)
            old = "2020-01-01T00:00:00Z"
            body["checked_at"] = old
            body["evidence"]["checked_at"] = old
            response = self.client.post("/train/kickoff", json=body)
        payload = response.json()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["field"], "checked_at")
        self.assertEqual(self.launches, [])

    def test_http_evidence_shas_mismatch_files_refuses_before_trainer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            body = _fresh_kickoff_body(dest, manifest)
            target = Path(body["run_private_dir"]) / "curated_pack_v2.jsonl"
            os.chmod(target, 0o600)
            _flip_one_ascii_byte(target)
            os.chmod(target, 0o400)
            response = self.client.post("/train/kickoff", json=body)
        payload = response.json()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["field"], "sha256_pack")
        self.assertNotEqual(payload["expected"], payload["actual"])
        self.assertEqual(self.launches, [])

    def test_http_ok_true_is_not_enough_without_matching_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            body = _fresh_kickoff_body(dest, manifest)
            self.assertTrue(body["evidence"]["ok"])
            train = Path(body["run_private_dir"]) / "curated_pack_v2_train.jsonl"
            os.chmod(train, 0o600)
            train.write_bytes(train.read_bytes() + b"\n")
            os.chmod(train, 0o400)
            response = self.client.post("/train/kickoff", json=body)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["field"], "sha256_train")
        self.assertEqual(self.launches, [])

    def test_http_other_helper_ft_routes_refuse_before_trainer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            body = _fresh_kickoff_body(dest, manifest)
            body["inbox"] = "latest"
            latest = self.client.post("/train/kickoff", json=body)
            inbox_route = self.client.post("/inbox/latest", json=body)
            start = self.client.post("/train/start", json=body)
            validate = self.client.post("/train/inbox-validate", json={"mode": "inbox-validate"})
            get_kickoff = self.client.get("/train/kickoff")
            query = self.client.post("/train/kickoff?inbox=latest", json=_fresh_kickoff_body(dest, manifest))
        for response, field in (
            (latest, "inbox"),
            (inbox_route, "inbox"),
            (start, "route"),
            (validate, "route"),
            (get_kickoff, "method"),
            (query, "inbox"),
        ):
            payload = response.json()
            self.assertEqual(response.status_code, 400)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["field"], field)
        self.assertEqual(self.launches, [])

    def test_http_matching_pack_rehashes_then_calls_trainer_stub(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            body = _fresh_kickoff_body(dest, manifest)
            response = self.client.post("/train/kickoff", json=body)
        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["launched"])
        self.assertEqual(payload["checkpoint_id"], "stub-ckpt")
        self.assertEqual(len(self.launches), 1)
        self.assertEqual(self.launches[0]["pack_id"], manifest["pack_id"])
        self.assertEqual(self.launches[0]["pin"]["recordedBy"], "cam")
        launch = self.launches[0]
        run_private = Path(launch["run_private_dir"]).resolve()
        self.assertEqual(launch["trainer_config"]["paths"], launch["paths"])
        self.assertEqual(set(launch["paths"]), {"pack", "train", "holdout", "manifest"})
        for path in launch["paths"].values():
            self.assertEqual(Path(path).resolve().parent, run_private)
        self.assertEqual(payload["paths"], launch["paths"])
        self.assertEqual(payload["post_train_paths"], launch["paths"])
        self.assertEqual(payload["post_train_host"], launch["trainer_config"]["host"])
        self.assertEqual(payload["trust_blobs"], _TEST_TRUST_BLOBS)
        self.assertEqual(payload["head_sha"], _TEST_TRUST_BLOBS["HEAD"])
        self.assertTrue(self.hq_requests)
        self.assertTrue(self.hq_requests[0].endswith("/pin"))

    def test_http_source_pack_paths_refused_no_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            body = _fresh_kickoff_body(dest, manifest)
            body["paths"] = {
                "pack": str((dest / "curated_pack_v2.jsonl").resolve()),
                "train": str((dest / "curated_pack_v2_train.jsonl").resolve()),
                "holdout": str((dest / "curated_pack_v2_holdout.jsonl").resolve()),
                "manifest": str((dest / "MANIFEST.json").resolve()),
                "pack_dir": str(dest.resolve()),
            }
            response = self.client.post("/train/kickoff", json=body)
        payload = response.json()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertTrue(str(payload["field"]).startswith("paths."))
        self.assertEqual(self.launches, [])

    def test_http_waits_for_trainer_process_before_rehash(self) -> None:
        waits: list[int] = []

        class FakeProc:
            def wait(self) -> int:
                waits.append(1)
                return 0

        def stub(body: dict) -> dict:
            self.launches.append(body)
            return {"ok": True, "checkpoint_id": "stub-ckpt", "process": FakeProc()}

        client = helper_ft_kickoff.TestClient(launch_trainer=stub)
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            body = _fresh_kickoff_body(dest, manifest)
            response = client.post("/train/kickoff", json=body)
        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(waits, [1])

    def test_http_missing_pin_refuses_before_trainer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            body = _fresh_kickoff_body(dest, manifest)
            del body["pin"]
            response = self.client.post("/train/kickoff", json=body)
        payload = response.json()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["field"], "pin")
        self.assertEqual(self.launches, [])

    def test_http_pin_mismatch_files_refuses_before_trainer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            body = _fresh_kickoff_body(dest, manifest)
            body["pin"]["sha256_pack"] = "a" * 64
            body["sha256_pack"] = "a" * 64
            body["evidence"]["pin"]["sha256_pack"] = "a" * 64
            response = self.client.post("/train/kickoff", json=body)
        payload = response.json()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["field"], "pin")
        self.assertEqual(self.launches, [])

    def test_http_body_pin_without_hq_provenance_refuses_before_trainer(self) -> None:
        hash_calls, originals = _wrap_hash_fns((helper_ft_kickoff, "_sha256_file"))
        try:
            with tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / "inbox-pack"
                dest.mkdir()
                manifest = _write_helper_pack(dest)
                body = _fresh_kickoff_body(dest, manifest)
                self.assertEqual(body["pin"]["recordedBy"], "cam")
                self.assertTrue(body["pin"]["stampVerified"])
                response = self.client.post("/train/kickoff", json=body)
        finally:
            _restore_hash_fns(originals)
        payload = response.json()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["field"], "cam-pin")
        self.assertEqual(payload["expected"], "present")
        self.assertEqual(payload["actual"], "HTTP 404")
        self.assertEqual(self.launches, [])
        self.assertEqual(hash_calls, [])
        self.assertTrue(self.hq_requests)

    def test_http_pack_matches_false_is_advisory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            pin = self._pin(manifest, pack_matches=False)
            self.assertTrue(pin["stampVerified"])
            body = _fresh_kickoff_body(dest, manifest)
            body["pin"] = dict(pin)
            body["evidence"]["pin"] = dict(pin)
            response = self.client.post("/train/kickoff", json=body)
        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(self.launches), 1)

    def test_http_one_row_count_off_refuses_before_trainer(self) -> None:
        cases = (
            ("rows_total", 99),
            ("rows_train", 0),
            ("rows_holdout", 7),
        )
        for field, wrong in cases:
            with self.subTest(field=field):
                self.launches.clear()
                with tempfile.TemporaryDirectory() as tmp:
                    dest = Path(tmp) / "inbox-pack"
                    dest.mkdir()
                    manifest = _write_helper_pack(dest)
                    pin = self._pin(manifest, **{field: wrong})
                    self.assertTrue(pin["stampVerified"])
                    self.assertTrue(pin["pack_matches"])
                    body = _fresh_kickoff_body(dest, manifest)
                    body["pin"] = dict(pin)
                    body["evidence"]["pin"] = dict(pin)
                    response = self.client.post("/train/kickoff", json=body)
                payload = response.json()
                self.assertEqual(response.status_code, 400)
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["field"], field)
                self.assertEqual(payload["expected"], wrong)
                self.assertNotEqual(payload["actual"], wrong)
                self.assertEqual(self.launches, [])

    def test_http_missing_row_field_refuses_before_trainer(self) -> None:
        for field in ("rows_total", "rows_train", "rows_holdout"):
            with self.subTest(field=field):
                self.launches.clear()
                with tempfile.TemporaryDirectory() as tmp:
                    dest = Path(tmp) / "inbox-pack"
                    dest.mkdir()
                    manifest = _write_helper_pack(dest)
                    pin = self._pin(manifest)
                    del pin[field]
                    body = _fresh_kickoff_body(dest, manifest)
                    response = self.client.post("/train/kickoff", json=body)
                payload = response.json()
                self.assertEqual(response.status_code, 400)
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["field"], f"cam-pin.{field}")
                self.assertEqual(payload["expected"], "present")
                self.assertEqual(payload["actual"], "missing")
                self.assertEqual(self.launches, [])

    def test_http_pack_matches_true_is_not_enough_when_disk_sha_differs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            pin = self._pin(manifest)
            self.assertTrue(pin["stampVerified"])
            self.assertTrue(pin["pack_matches"])
            body = _fresh_kickoff_body(dest, manifest)
            target = Path(body["run_private_dir"]) / "curated_pack_v2.jsonl"
            os.chmod(target, 0o600)
            _flip_one_ascii_byte(target)
            os.chmod(target, 0o400)
            response = self.client.post("/train/kickoff", json=body)
        payload = response.json()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["field"], "sha256_pack")
        self.assertNotEqual(payload["expected"], payload["actual"])
        self.assertEqual(self.launches, [])

    def test_http_pack_matches_true_is_not_enough_when_disk_row_count_differs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            pin = self._pin(manifest)
            self.assertTrue(pin["stampVerified"])
            self.assertTrue(pin["pack_matches"])
            body = _fresh_kickoff_body(dest, manifest)
            train = Path(body["run_private_dir"]) / "curated_pack_v2_train.jsonl"
            os.chmod(train, 0o600)
            train.write_bytes(train.read_bytes() + b'{"id":"extra-row"}\n')
            os.chmod(train, 0o400)
            response = self.client.post("/train/kickoff", json=body)
        payload = response.json()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["field"], "rows_train")
        self.assertEqual(payload["expected"], 1)
        self.assertEqual(payload["actual"], 2)
        self.assertEqual(self.launches, [])


class HelperFtCritic3dacTests(unittest.TestCase):
    """Critic 3dac3417 blockers, should-fix, and nits. Each test goes red if the fix is removed."""

    def setUp(self) -> None:
        self.kickoff_calls: list[dict] = []
        self.launches: list[dict] = []
        _start_hq_http_mock(self)

        def fake_post(body: dict, url: str | None = None) -> dict:
            self.kickoff_calls.append(body)
            return {"ok": True, "checkpoint_id": "ckpt-test"}

        self._orig_post = kick_helper_ft.post_kickoff
        kick_helper_ft.post_kickoff = fake_post
        self.client = helper_ft_kickoff.TestClient(
            launch_trainer=lambda body: self.launches.append(body) or {"ok": True, "launched": True}
        )

    def tearDown(self) -> None:
        kick_helper_ft.post_kickoff = self._orig_post
        _stop_hq_http_mock(self)

    def _pin(self, manifest: dict, **overrides: object) -> dict:
        pin = _cam_pin(manifest, **overrides)
        self.hq_pins[manifest["pack_id"]] = pin
        return pin

    def test_placeholder_origin_refuses_even_if_env_url_set(self) -> None:
        cam_pin_spec.SWARM_HQ_ORIGIN = ""
        os.environ["SWARM_HQ_URL"] = "https://evil-hq.example"
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
            rc = kick_helper_ft.main(_cli_args(dest))
        self.assertEqual(rc, 1)
        self.assertEqual(ctx.exception.field, "SWARM_HQ_ORIGIN")
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(self.hq_requests, [])
        self.assertEqual(self.hq_posts, [])

    def test_placeholder_origin_refuses_hq_events_same_as_kick(self) -> None:
        cam_pin_spec.SWARM_HQ_ORIGIN = ""
        os.environ["SWARM_HQ_URL"] = "https://evil-hq.example"
        payload = {
            "run_id": "helper-ft-placeholder",
            "sha256_pack": "11" * 32,
            "sha256_train": "22" * 32,
            "sha256_holdout": "33" * 32,
        }
        with self.assertRaises(cam_pin_spec.CamPinError) as kick_ctx:
            cam_pin_spec.post_hq_event("kick", payload)
        completion = {
            **payload,
            "sha256_evidence": "44" * 32,
            "result": "MATCH",
            "exit_code": 0,
        }
        with self.assertRaises(cam_pin_spec.CamPinError) as done_ctx:
            cam_pin_spec.post_hq_event("completion", completion)
        self.assertEqual(kick_ctx.exception.field, "SWARM_HQ_ORIGIN")
        self.assertEqual(kick_ctx.exception.expected, "https origin")
        self.assertEqual(kick_ctx.exception.actual, "placeholder")
        self.assertEqual(done_ctx.exception.field, "SWARM_HQ_ORIGIN")
        self.assertEqual(done_ctx.exception.actual, "placeholder")
        self.assertEqual(self.hq_posts, [])
        self.assertEqual(self.hq_requests, [])

    def test_invalid_cam_sig_refuses_cli_and_handler(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            pin = self._pin(manifest, cam_sig=base64.b64encode(b"\x00" * 64).decode("ascii"))
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
            body = _fresh_kickoff_body(dest, manifest)
            body["pin"] = dict(pin)
            body["evidence"]["pin"] = dict(pin)
            response = self.client.post("/train/kickoff", json=body)
        self.assertEqual(ctx.exception.field, "cam-pin.cam_sig.R")
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["field"], "cam-pin.cam_sig.R")
        self.assertEqual(self.launches, [])

    def test_https_to_http_redirect_refuses_and_never_sends_token(self) -> None:
        self.hq_redirect = (302, "http://127.0.0.2/api/packs/x/pin")
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(ctx.exception.field, "cam-pin")
        self.assertEqual(ctx.exception.expected, "no redirect")
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(len(self.hq_requests), 1)
        self.assertTrue(self.hq_requests[0].startswith(PINNED_HQ_ORIGIN))
        self.assertFalse(any("127.0.0.2" in url for url, _tok in self.hq_tokens_by_url))
        self.assertFalse(any(url.startswith("http://") for url, _tok in self.hq_tokens_by_url))

    def test_https_to_other_host_redirect_refuses_and_never_sends_token(self) -> None:
        self.hq_redirect = (302, "https://evil.example/api/packs/x/pin")
        body_pin_pack = None
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            body = _fresh_kickoff_body(dest, manifest)
            body_pin_pack = manifest["pack_id"]
            response = self.client.post("/train/kickoff", json=body)
        payload = response.json()
        self.assertEqual(payload["field"], "cam-pin")
        self.assertEqual(payload["expected"], "no redirect")
        self.assertEqual(self.launches, [])
        self.assertTrue(all(u.startswith(PINNED_HQ_ORIGIN) for u in self.hq_requests))
        self.assertFalse(any("evil.example" in url for url, _tok in self.hq_tokens_by_url))
        self.assertEqual(body_pin_pack, "curated_pack_v2-test")

    def test_pin_response_over_64kib_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            pin = self._pin(manifest)
            pin["kid"] = "k" * (cam_pin_spec.MAX_PIN_BYTES)
            self.hq_pins[manifest["pack_id"]] = pin
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(ctx.exception.field, "cam-pin")
        self.assertEqual(ctx.exception.expected, f"<={cam_pin_spec.MAX_PIN_BYTES} bytes")
        self.assertEqual(self.kickoff_calls, [])

    def test_pack_id_whitespace_refused_cli_and_8765(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            padded = " " + manifest["pack_id"] + " "
            pin = self._pin(manifest, pack_id=padded)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
            body = _fresh_kickoff_body(dest, manifest)
            body["pin"] = dict(pin)
            body["evidence"]["pin"] = dict(pin)
            response = self.client.post("/train/kickoff", json=body)
        self.assertEqual(ctx.exception.field, "cam-pin.pack_id")
        self.assertEqual(ctx.exception.expected, "ASCII [A-Za-z0-9._-]{1,128}")
        self.assertEqual(ctx.exception.actual, padded)
        self.assertEqual(self.kickoff_calls, [])
        self.assertIn(response.json()["field"], {"cam-pin.pack_id", "pin.pack_id"})
        self.assertEqual(self.launches, [])

    def test_hq_duplicate_keys_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            pin = self._pin(manifest)
            raw = json.dumps(pin)
            raw = raw.replace('"kid":', '"kid": "dup", "kid":', 1)

            def fake_dup(request: object, timeout: object = None) -> _FakeHqHttpResponse:
                self.hq_requests.append(getattr(request, "full_url", ""))
                return _FakeHqHttpResponse(raw.encode("utf-8"))

            with patch.object(cam_pin_spec, "open_hq", side_effect=fake_dup):
                with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                    kick_helper_ft.kick(dest)
        self.assertEqual(ctx.exception.field, "cam-pin")
        self.assertEqual(ctx.exception.expected, "unique keys")
        self.assertEqual(self.kickoff_calls, [])

    def test_kickoff_pin_fetch_differs_from_cli_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            pin = self._pin(manifest)
            body = _fresh_kickoff_body(dest, manifest)
            other = _sign_pin({**pin, "recordedAt": "1999-01-01T00:00:00.000Z"})
            self.hq_pins[manifest["pack_id"]] = other
            response = self.client.post("/train/kickoff", json=body)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["field"], "pin")
        self.assertEqual(self.launches, [])

    def test_computed_shas_omitted_tampered_run_private_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            body = _fresh_kickoff_body(dest, manifest)
            del body["evidence"]["computed_shas"]
            target = Path(body["run_private_dir"]) / "curated_pack_v2_holdout.jsonl"
            os.chmod(target, 0o600)
            _flip_one_ascii_byte(target)
            os.chmod(target, 0o400)
            response = self.client.post("/train/kickoff", json=body)
        payload = response.json()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["field"], "sha256_holdout")
        self.assertEqual(self.launches, [])

    def test_inbox_tamper_ignored_run_private_hashed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            body = _fresh_kickoff_body(dest, manifest)
            _flip_one_ascii_byte(dest / "curated_pack_v2.jsonl")
            response = self.client.post("/train/kickoff", json=body)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(len(self.launches), 1)

    def test_default_launch_trainer_never_launches(self) -> None:
        result = helper_ft_kickoff.default_launch_trainer({"mode": "helper-ft"})
        self.assertIs(result.get("ok"), False)
        self.assertEqual(result["field"], "trainer")
        self.assertNotEqual(result.get("launched"), True)

    def test_real_route_inbox_latest_and_no_evidence_refused(self) -> None:
        client = helper_ft_kickoff.TestClient()
        latest = client.post(
            "/train/kickoff",
            json={"mode": "helper-ft", "inbox": "latest", "pack_id": "p", "evidence": {"ok": True, "pack_id": "p"}},
        )
        missing = client.post("/train/kickoff", json={"mode": "helper-ft", "pack_id": "p"})
        self.assertEqual(latest.status_code, 400)
        self.assertEqual(latest.json()["field"], "inbox")
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.json()["field"], "evidence")
        repo = Path(__file__).resolve().parents[3]
        loop_src = repo / "packages" / "dottie-loop"
        if str(loop_src) not in sys.path:
            sys.path.insert(0, str(loop_src))
        runner = _load("forge_runner_route", loop_src / "scripts" / "forge_runner.py")
        app = runner.helper_ft_wsgi_app()
        client2 = helper_ft_kickoff.TestClient()
        client2.app = app
        latest2 = client2.post(
            "/train/kickoff",
            json={"mode": "helper-ft", "inbox": "latest", "pack_id": "p", "evidence": {"ok": True, "pack_id": "p"}},
        )
        missing2 = client2.post("/train/kickoff", json={"mode": "helper-ft", "pack_id": "p"})
        self.assertEqual(latest2.json()["field"], "inbox")
        self.assertEqual(missing2.json()["field"], "evidence")

    def test_uppercase_sha_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            upper = manifest["sha256_pack"].upper()
            self._pin(manifest, sha256_pack=upper)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(ctx.exception.field, "cam-pin.sha256_pack")
        self.assertEqual(self.kickoff_calls, [])

    def test_manifest_duplicate_keys_refused_by_8765(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            body = _fresh_kickoff_body(dest, manifest)
            man = Path(body["run_private_dir"]) / "MANIFEST.json"
            os.chmod(man, 0o600)
            text = man.read_text(encoding="utf-8")
            man.write_text(text.replace('"pack_id":', '"pack_id": "dup",\n  "pack_id":', 1), encoding="utf-8")
            os.chmod(man, 0o400)
            response = self.client.post("/train/kickoff", json=body)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["field"], "MANIFEST.json")
        self.assertEqual(response.json()["expected"], "unique keys")
        self.assertEqual(self.launches, [])

    def test_sign_and_gen_tools_never_write_private_key_to_stdout_pin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            priv = Path(tmp) / "cam.priv"
            gen = _load("gen_cam_pin_key", APP / "tools" / "gen_cam_pin_key.py")
            rc = gen.main(["--private-key", str(priv), "--key-id", "cam-pin-ed25519-tool"])
            self.assertEqual(rc, 0)
            self.assertTrue(priv.is_file())
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(priv.stat().st_mode), 0o600)
            pin_path = Path(tmp) / "pin.json"
            pin_path.write_text(
                json.dumps(
                    {
                        "pack_id": "p",
                        "sha256_pack": "11" * 32,
                        "sha256_train": "22" * 32,
                        "sha256_holdout": "33" * 32,
                        "rows_total": 1,
                        "rows_train": 1,
                        "rows_holdout": 0,
                        "recordedAt": "2026-10-19T00:00:00.000Z",
                    }
                ),
                encoding="utf-8",
            )
            sign = _load("sign_cam_pin", APP / "tools" / "sign_cam_pin.py")
            from io import StringIO
            buf = StringIO()
            old = sys.stdout
            sys.stdout = buf
            try:
                rc2 = sign.main(["--private-key", str(priv), "--pin", str(pin_path)])
            finally:
                sys.stdout = old
            self.assertEqual(rc2, 0)
            out = buf.getvalue()
            self.assertNotIn(priv.read_bytes().hex(), out)
            self.assertTrue(out.strip())

    def test_committed_pubkey_placeholder_refuses_runtime(self) -> None:
        self._key_patcher.stop()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / "inbox-pack"
                dest.mkdir()
                manifest = _write_helper_pack(dest)
                self._pin(manifest)
                with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                    kick_helper_ft.kick(dest)
            self.assertEqual(ctx.exception.field, "cam_pin.pubkey")
            self.assertEqual(self.kickoff_calls, [])
            pub = cam_pin_spec.CAM_PIN_PUB_PATH.read_text(encoding="utf-8").lower()
            self.assertTrue("placeholder" in pub or "replace-me" in pub)
        finally:
            test_pub = Ed25519PublicKey.from_public_bytes(
                cam_pin_spec.raw_public_from_private(TEST_CAM_PRIVATE)
            )
            self._key_patcher = patch.object(
                cam_pin_spec, "load_cam_public_key", return_value=(TEST_CAM_KEY_ID, test_pub)
            )
            self._key_patcher.start()

    def _restart_trust_patcher(self) -> None:
        self._trust_patcher = patch.object(
            cam_pin_spec, "require_committed_trust", return_value=dict(_TEST_TRUST_BLOBS)
        )
        self._trust_patcher.start()

    def test_dirty_key_file_refused(self) -> None:
        self._trust_patcher.stop()
        try:
            ls_p, hash_p, head_p = _blob_patches(dirty="apps/dottie-os/trust/cam_pin_ed25519.pub")
            with ls_p, hash_p, head_p:
                with self.assertRaises(cam_pin_spec.CamPinError) as ctx:
                    cam_pin_spec.require_committed_trust()
                self.assertEqual(ctx.exception.field, "trust.blob")
                with tempfile.TemporaryDirectory() as tmp:
                    dest = Path(tmp) / "inbox-pack"
                    dest.mkdir()
                    manifest = _write_helper_pack(dest)
                    self._pin(manifest)
                    with self.assertRaises(kick_helper_ft.KickRefused) as kick_ctx:
                        kick_helper_ft.kick(dest)
                    self.assertEqual(kick_ctx.exception.field, "trust.blob")
                    response = self.client.post("/train/kickoff", json={"mode": "helper-ft"})
                payload = response.json()
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["field"], "trust.blob")
                self.assertEqual(self.kickoff_calls, [])
                self.assertEqual(self.launches, [])
        finally:
            self._restart_trust_patcher()

    def test_dirty_origin_constant_refused(self) -> None:
        self._trust_patcher.stop()
        try:
            ls_p, hash_p, head_p = _blob_patches(dirty="apps/dottie-os/scripts/lab/cam_pin_spec.py")
            with ls_p, hash_p, head_p:
                with self.assertRaises(cam_pin_spec.CamPinError) as ctx:
                    cam_pin_spec.require_committed_trust()
                self.assertEqual(ctx.exception.field, "trust.blob")
                with tempfile.TemporaryDirectory() as tmp:
                    dest = Path(tmp) / "inbox-pack"
                    dest.mkdir()
                    manifest = _write_helper_pack(dest)
                    self._pin(manifest)
                    with self.assertRaises(kick_helper_ft.KickRefused) as kick_ctx:
                        kick_helper_ft.kick(dest)
                    self.assertEqual(kick_ctx.exception.field, "trust.blob")
                    response = self.client.post("/train/kickoff", json={"mode": "helper-ft"})
                payload = response.json()
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["field"], "trust.blob")
                self.assertEqual(self.kickoff_calls, [])
                self.assertEqual(self.launches, [])
        finally:
            self._restart_trust_patcher()

    def test_head_not_on_main_refused(self) -> None:
        self._trust_patcher.stop()
        try:
            ls_p, hash_p, head_p = _blob_patches(on_main=False, head="deadbeef")
            with ls_p, hash_p, head_p:
                with self.assertRaises(cam_pin_spec.CamPinError) as ctx:
                    cam_pin_spec.require_committed_trust()
                self.assertEqual(ctx.exception.field, "HEAD")
                self.assertEqual(ctx.exception.actual, "deadbeef")
                with tempfile.TemporaryDirectory() as tmp:
                    dest = Path(tmp) / "inbox-pack"
                    dest.mkdir()
                    manifest = _write_helper_pack(dest)
                    self._pin(manifest)
                    with self.assertRaises(kick_helper_ft.KickRefused) as kick_ctx:
                        kick_helper_ft.kick(dest)
                    self.assertEqual(kick_ctx.exception.field, "HEAD")
                    response = self.client.post("/train/kickoff", json={"mode": "helper-ft"})
                payload = response.json()
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["field"], "HEAD")
                self.assertEqual(payload["actual"], "deadbeef")
                self.assertEqual(self.kickoff_calls, [])
                self.assertEqual(self.launches, [])
        finally:
            self._restart_trust_patcher()

    def test_rehash_after_training_not_when_kickoff_returns(self) -> None:
        def start(pack_dir: Path, evidence: dict, log_path: Path) -> None:
            del evidence, log_path
            target = pack_dir / "curated_pack_v2.jsonl"
            os.chmod(target, 0o600)
            _flip_one_ascii_byte(target)
            os.chmod(target, 0o400)

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest, start_training=start)
        self.assertEqual(len(self.kickoff_calls), 1)
        self.assertEqual(ctx.exception.field, "sha256_pack")

    def test_trainer_argv_and_evidence_use_only_run_dir_paths(self) -> None:
        captured: list[dict] = []

        def kickoff(body: dict) -> dict:
            captured.append(body)
            return {"ok": True, "checkpoint_id": "ckpt-host"}

        def start(copy_dir: Path, evidence: dict, log_path: Path) -> dict:
            del log_path
            self.assertEqual(evidence["paths"]["pack"], str((copy_dir / "curated_pack_v2.jsonl").resolve()))
            return {"ok": True, "checkpoint_id": "ckpt-host"}

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            evidence = kick_helper_ft.kick(dest, start_training=start, kickoff=kickoff)
            body = captured[0]
            run_private = Path(evidence["run_private_dir"]).resolve()
            ckpt = Path(evidence["checkpoint_integrity_evidence_path"])
            rec = json.loads(ckpt.read_text(encoding="utf-8"))
        self.assertEqual(len(captured), 1)
        self.assertEqual(set(body["paths"]), {"pack", "train", "holdout", "manifest"})
        self.assertNotIn("pack_dir", body["paths"])
        self.assertEqual(body["trainer_config"]["paths"], body["paths"])
        self.assertEqual(body["trainer_argv"], kick_helper_ft.build_trainer_argv(body["paths"]))
        for path in (*body["paths"].values(), *body["trainer_argv"][1::2]):
            resolved = Path(path).resolve()
            self.assertEqual(resolved.parent, run_private)
            self.assertNotEqual(resolved.parent, dest.resolve())
            self.assertFalse(str(resolved).startswith(str(dest.resolve()) + os.sep))
        self.assertEqual(rec["paths"], body["paths"])
        self.assertEqual(rec["paths"], evidence["paths"])
        self.assertEqual(rec["host"], evidence["host"])
        self.assertEqual(rec["host"], socket.gethostname())
        self.assertEqual(rec["status"], "MATCH")
        self.assertEqual(rec["computed_shas"], evidence["computed_shas"])
        self.assertEqual(rec["pin_shas"], evidence["expected_shas"])
        self.assertEqual(rec["manifest_shas"], evidence["manifest_shas"])

    def test_mid_run_chmod_edit_writes_refused_checkpoint_evidence(self) -> None:
        def start(copy_dir: Path, evidence: dict, log_path: Path) -> None:
            del evidence, log_path
            target = copy_dir / "curated_pack_v2.jsonl"
            os.chmod(target, 0o600)
            target.write_bytes(target.read_bytes() + b"x")
            os.chmod(target, 0o400)

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            log_path = Path(tmp) / "runs" / "helper_ft.log"
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest, log_path=log_path, start_training=start)
            ckpt_dir = log_path.parent / "ckpt-test"
            rec = json.loads((ckpt_dir / "integrity_evidence.json").read_text(encoding="utf-8"))
        self.assertEqual(ctx.exception.field, "sha256_pack")
        self.assertEqual(rec["status"], "REFUSED")
        self.assertEqual(rec["host"], socket.gethostname())
        self.assertFalse(rec["match"])

    def test_missing_checkpoint_evidence_is_unscored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ckpt = Path(tmp) / "ckpt-missing"
            ckpt.mkdir()
            self.assertEqual(kick_helper_ft.checkpoint_integrity_status(ckpt), "unscored")
            self.assertEqual(
                kick_helper_ft.checkpoint_integrity_status(Path(tmp) / "no-such-ckpt"),
                "unscored",
            )

    def test_script_git_sha_null_records_script_sha256(self) -> None:
        with patch.object(kick_helper_ft, "_script_git_sha", return_value=None):
            with tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / "inbox-pack"
                dest.mkdir()
                manifest = _write_helper_pack(dest)
                self._pin(manifest)
                evidence = kick_helper_ft.kick(dest)
                rec = json.loads(
                    Path(evidence["checkpoint_integrity_evidence_path"]).read_text(
                        encoding="utf-8"
                    )
                )
        self.assertIsNone(evidence["script_git_sha"])
        self.assertIsNone(rec["script_git_sha"])
        self.assertEqual(len(evidence["script_sha256"]), 64)
        self.assertEqual(evidence["script_sha256"], kick_helper_ft._script_sha256())
        self.assertEqual(evidence["entrypoint_pins"], self.forge_entrypoint_pins)
        self.assertEqual(evidence["pins_source_commit"], self.forge_pins_source_commit)
        self.assertEqual(rec["entrypoint_pins"], self.forge_entrypoint_pins)
        self.assertEqual(rec["pins_source_commit"], self.forge_pins_source_commit)
        self.assertEqual(evidence["kickoff_url"], kick_helper_ft.DEFAULT_KICKOFF_URL)
        self.assertEqual(evidence["trust_blobs"], _TEST_TRUST_BLOBS)
        self.assertTrue(evidence["post_train_shas"])
        kick_posts = [p for p in self.hq_posts if str(p["url"]).endswith("/kick")]
        done_posts = [p for p in self.hq_posts if str(p["url"]).endswith("/completion")]
        self.assertEqual(kick_posts[0]["body"]["entrypoint_pins"], self.forge_entrypoint_pins)
        self.assertEqual(kick_posts[0]["body"]["pins_source_commit"], self.forge_pins_source_commit)
        self.assertEqual(done_posts[0]["body"]["entrypoint_pins"], self.forge_entrypoint_pins)
        self.assertEqual(done_posts[0]["body"]["pins_source_commit"], self.forge_pins_source_commit)

    def test_entrypoint_pins_both_present_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            evidence = kick_helper_ft.kick(dest)
            on_disk = json.loads(Path(evidence["evidence_path"]).read_text(encoding="utf-8"))
            rec = json.loads(
                Path(evidence["checkpoint_integrity_evidence_path"]).read_text(
                    encoding="utf-8"
                )
            )
        self.assertTrue(evidence["script_git_sha"])
        self.assertEqual(evidence["entrypoint_pins"], self.forge_entrypoint_pins)
        self.assertEqual(evidence["pins_source_commit"], FORGE_PINS_SOURCE_COMMIT_FIXTURE)
        self.assertEqual(on_disk["entrypoint_pins"], self.forge_entrypoint_pins)
        self.assertEqual(on_disk["pins_source_commit"], FORGE_PINS_SOURCE_COMMIT_FIXTURE)
        self.assertEqual(rec["entrypoint_pins"], self.forge_entrypoint_pins)
        self.assertEqual(rec["pins_source_commit"], FORGE_PINS_SOURCE_COMMIT_FIXTURE)
        kick_posts = [p for p in self.hq_posts if str(p["url"]).endswith("/kick")]
        done_posts = [p for p in self.hq_posts if str(p["url"]).endswith("/completion")]
        self.assertEqual(len(kick_posts), 1)
        self.assertEqual(len(done_posts), 1)
        self.assertEqual(kick_posts[0]["body"]["entrypoint_pins"], self.forge_entrypoint_pins)
        self.assertEqual(kick_posts[0]["body"]["pins_source_commit"], FORGE_PINS_SOURCE_COMMIT_FIXTURE)
        self.assertEqual(done_posts[0]["body"]["entrypoint_pins"], self.forge_entrypoint_pins)
        self.assertEqual(done_posts[0]["body"]["pins_source_commit"], FORGE_PINS_SOURCE_COMMIT_FIXTURE)
        dumped = json.dumps(on_disk) + json.dumps(rec) + json.dumps(kick_posts[0]["body"])
        self.assertNotIn(SWARM_HQ_AGENT_TOKEN_FIXTURE, dumped)

    def test_entrypoint_pins_missing_refuses(self) -> None:
        os.environ.pop(kick_helper_ft.FORGE_ENTRYPOINT_PINS_ENV, None)
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(ctx.exception.field, "entrypoint_pins")
        self.assertEqual(ctx.exception.actual, "missing")
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(self.hq_posts, [])

    def test_pins_source_commit_missing_refuses(self) -> None:
        os.environ.pop(kick_helper_ft.FORGE_PINS_SOURCE_COMMIT_ENV, None)
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(ctx.exception.field, "pins_source_commit")
        self.assertEqual(ctx.exception.actual, "missing")
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(self.hq_posts, [])

    def test_pins_source_commit_malformed_refuses(self) -> None:
        os.environ[kick_helper_ft.FORGE_PINS_SOURCE_COMMIT_ENV] = "NotAGitSha"
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(ctx.exception.field, "pins_source_commit")
        self.assertEqual(ctx.exception.expected, "40-char lowercase hex")
        self.assertEqual(ctx.exception.actual, "NotAGitSha")
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(self.hq_posts, [])

    def test_null_git_sha_refuses_without_entrypoint_pins(self) -> None:
        os.environ.pop(kick_helper_ft.FORGE_ENTRYPOINT_PINS_ENV, None)
        os.environ.pop(kick_helper_ft.FORGE_PINS_SOURCE_COMMIT_ENV, None)
        with patch.object(kick_helper_ft, "_script_git_sha", return_value=None):
            with tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / "inbox-pack"
                dest.mkdir()
                manifest = _write_helper_pack(dest)
                self._pin(manifest)
                with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                    kick_helper_ft.kick(dest)
        self.assertEqual(ctx.exception.field, "entrypoint_pins")
        self.assertEqual(ctx.exception.actual, "missing")
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(self.hq_posts, [])

    def test_integrity_evidence_line_parses_and_matches_file_sha(self) -> None:
        buf = StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            log_path = Path(tmp) / "runs" / "helper_ft.log"
            with redirect_stdout(buf):
                evidence = kick_helper_ft.kick(dest, log_path=log_path)
            ckpt = Path(evidence["checkpoint_integrity_evidence_path"])
            prefix = kick_helper_ft.INTEGRITY_EVIDENCE_LINE_PREFIX + " "
            stdout_lines = [
                line for line in buf.getvalue().splitlines() if line.startswith(prefix)
            ]
            log_text = log_path.read_text(encoding="utf-8")
            file_sha = kick_helper_ft.sha256_file(ckpt)
            parsed = kick_helper_ft.parse_integrity_evidence_line(stdout_lines[0])
            rec = json.loads(ckpt.read_text(encoding="utf-8"))
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(ckpt.stat().st_mode), 0o400)
        self.assertEqual(len(stdout_lines), 1)
        self.assertIn(stdout_lines[0], log_text)
        self.assertEqual(stdout_lines[0], evidence["integrity_evidence_line"])
        self.assertEqual(parsed["sha256_evidence"], file_sha)
        self.assertEqual(parsed["sha256_evidence"], evidence["sha256_evidence"])
        self.assertEqual(parsed["sha256_pack"], evidence["computed_shas"]["sha256_pack"])
        self.assertEqual(parsed["sha256_train"], evidence["computed_shas"]["sha256_train"])
        self.assertEqual(parsed["sha256_holdout"], evidence["computed_shas"]["sha256_holdout"])
        self.assertEqual(parsed["result"], "MATCH")
        self.assertEqual(evidence["result"], "MATCH")
        self.assertEqual(evidence["integrity_evidence"]["status"], "MATCH")
        self.assertEqual(rec["exit_code"], 0)
        self.assertEqual(parsed["host"], evidence["host"])

    def test_post_hoc_edit_of_integrity_evidence_no_longer_matches_logged_sha(self) -> None:
        buf = StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            log_path = Path(tmp) / "runs" / "helper_ft.log"
            with redirect_stdout(buf):
                evidence = kick_helper_ft.kick(dest, log_path=log_path)
            ckpt = Path(evidence["checkpoint_integrity_evidence_path"])
            prefix = kick_helper_ft.INTEGRITY_EVIDENCE_LINE_PREFIX + " "
            line = [
                row for row in buf.getvalue().splitlines() if row.startswith(prefix)
            ][0]
            parsed = kick_helper_ft.parse_integrity_evidence_line(line)
            self.assertEqual(parsed["sha256_evidence"], kick_helper_ft.sha256_file(ckpt))
            if os.name == "posix":
                os.chmod(ckpt, 0o600)
            ckpt.write_bytes(ckpt.read_bytes() + b"\n")
            if os.name == "posix":
                os.chmod(ckpt, 0o400)
            edited = kick_helper_ft.sha256_file(ckpt)
        self.assertNotEqual(edited, parsed["sha256_evidence"])
        self.assertEqual(parsed["result"], "MATCH")

    def test_fake_stdout_match_line_does_not_change_kick_result_or_sha(self) -> None:
        fake_sha = "ab" * 32
        fake_line = (
            "INTEGRITY_EVIDENCE "
            f"sha256_evidence={fake_sha} sha256_pack={fake_sha} "
            f"sha256_train={fake_sha} sha256_holdout={fake_sha} "
            "result=MATCH host=forged"
        )
        also_fake = (
            f"{kick_helper_ft.INTEGRITY_EVIDENCE_LINE_PREFIX} "
            f"sha256_evidence={'cd' * 32} sha256_pack={'cd' * 32} "
            f"sha256_train={'cd' * 32} sha256_holdout={'cd' * 32} "
            "result=MATCH host=forged"
        )

        def start(pack_dir: Path, evidence: dict, log_path: Path) -> dict:
            del pack_dir, evidence, log_path
            print(fake_line, flush=True)
            print(also_fake, flush=True)
            return {"ok": True, "exit_code": 0}

        buf = StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            log_path = Path(tmp) / "runs" / "helper_ft.log"
            with redirect_stdout(buf):
                evidence = kick_helper_ft.kick(
                    dest, log_path=log_path, start_training=start
                )
            ckpt = Path(evidence["checkpoint_integrity_evidence_path"])
            file_sha = kick_helper_ft.sha256_file(ckpt)
            rec = json.loads(ckpt.read_text(encoding="utf-8"))
        stdout = buf.getvalue()
        self.assertIn(fake_line, stdout)
        self.assertEqual(evidence["result"], "MATCH")
        self.assertEqual(evidence["sha256_evidence"], file_sha)
        self.assertNotEqual(evidence["sha256_evidence"], fake_sha)
        self.assertNotEqual(evidence["sha256_evidence"], "cd" * 32)
        self.assertEqual(rec["status"], "MATCH")
        self.assertEqual(rec["exit_code"], 0)
        self.assertEqual(evidence["integrity_evidence"]["status"], "MATCH")
        posts = [p for p in self.hq_posts if str(p["url"]).endswith("/completion")]
        self.assertTrue(posts)
        self.assertEqual(posts[-1]["body"]["sha256_evidence"], file_sha)
        self.assertEqual(posts[-1]["body"]["result"], "MATCH")

    def test_trainer_exit_1_refuses_even_when_hashes_match(self) -> None:
        def start(pack_dir: Path, evidence: dict, log_path: Path) -> dict:
            del pack_dir, evidence, log_path
            proc = subprocess.Popen([sys.executable, "-c", "raise SystemExit(1)"])
            return {"ok": True, "process": proc}

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            log_path = Path(tmp) / "runs" / "helper_ft.log"
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest, log_path=log_path, start_training=start)
            rec = json.loads(
                (log_path.parent / "ckpt-test" / "integrity_evidence.json").read_text(
                    encoding="utf-8"
                )
            )
        self.assertEqual(ctx.exception.field, "trainer.exit")
        self.assertEqual(rec["status"], "REFUSED")
        self.assertEqual(rec["exit_code"], 1)
        self.assertFalse(rec["match"])
        self.assertEqual(rec["computed_shas"]["sha256_pack"], manifest["sha256_pack"])
        posts = [p for p in self.hq_posts if str(p["url"]).endswith("/completion")]
        self.assertTrue(posts)
        self.assertEqual(posts[-1]["body"]["result"], "REFUSED")
        self.assertEqual(posts[-1]["body"]["exit_code"], 1)

    def test_trainer_sigkill_refuses_even_when_hashes_match(self) -> None:
        def start(pack_dir: Path, evidence: dict, log_path: Path) -> dict:
            del pack_dir, evidence, log_path
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"]
            )
            os.kill(proc.pid, signal.SIGKILL)
            return {"ok": True, "process": proc}

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            log_path = Path(tmp) / "runs" / "helper_ft.log"
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest, log_path=log_path, start_training=start)
            rec = json.loads(
                (log_path.parent / "ckpt-test" / "integrity_evidence.json").read_text(
                    encoding="utf-8"
                )
            )
        self.assertEqual(ctx.exception.field, "trainer.exit")
        self.assertEqual(rec["status"], "REFUSED")
        self.assertEqual(rec["exit_code"], -signal.SIGKILL)
        self.assertEqual(rec["signal"], signal.SIGKILL)
        self.assertFalse(rec["match"])
        self.assertEqual(rec["computed_shas"]["sha256_pack"], manifest["sha256_pack"])
        posts = [p for p in self.hq_posts if str(p["url"]).endswith("/completion")]
        self.assertTrue(posts)
        self.assertEqual(posts[-1]["body"]["result"], "REFUSED")
        self.assertEqual(posts[-1]["body"]["exit_code"], -signal.SIGKILL)

    def test_trainer_exit_0_with_matching_hashes_is_match(self) -> None:
        def start(pack_dir: Path, evidence: dict, log_path: Path) -> dict:
            del pack_dir, evidence, log_path
            proc = subprocess.Popen([sys.executable, "-c", "raise SystemExit(0)"])
            return {"ok": True, "process": proc}

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            evidence = kick_helper_ft.kick(dest, start_training=start)
            ckpt = Path(evidence["checkpoint_integrity_evidence_path"])
            rec = json.loads(ckpt.read_text(encoding="utf-8"))
            file_sha = kick_helper_ft.sha256_file(ckpt)
        self.assertEqual(evidence["result"], "MATCH")
        self.assertEqual(evidence["sha256_evidence"], file_sha)
        self.assertEqual(rec["status"], "MATCH")
        self.assertEqual(rec["exit_code"], 0)
        self.assertTrue(rec["match"])
        self.assertEqual(rec["computed_shas"], evidence["computed_shas"])

    def test_trainer_timeout_refuses_even_when_hashes_match(self) -> None:
        def start(pack_dir: Path, evidence: dict, log_path: Path) -> dict:
            del pack_dir, evidence, log_path
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"]
            )
            return {"ok": True, "process": proc, "wait_timeout": 0.05}

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            log_path = Path(tmp) / "runs" / "helper_ft.log"
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest, log_path=log_path, start_training=start)
            rec = json.loads(
                (log_path.parent / "ckpt-test" / "integrity_evidence.json").read_text(
                    encoding="utf-8"
                )
            )
        self.assertEqual(ctx.exception.field, "trainer.exit")
        self.assertEqual(ctx.exception.actual, "timeout")
        self.assertEqual(rec["status"], "REFUSED")
        self.assertTrue(rec["timeout"])
        self.assertFalse(rec["match"])
        self.assertEqual(rec["computed_shas"]["sha256_pack"], manifest["sha256_pack"])

    def test_kick_posts_hq_kick_and_completion_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            evidence = kick_helper_ft.kick(dest)
            ckpt = Path(evidence["checkpoint_integrity_evidence_path"])
            file_sha = kick_helper_ft.sha256_file(ckpt)
        self.assertEqual(len(self.hq_posts), 2)
        kick_post, completion_post = self.hq_posts
        self.assertEqual(kick_post["url"], PINNED_HQ_ORIGIN + "/api/helper-ft/events/kick")
        self.assertEqual(completion_post["url"], PINNED_HQ_ORIGIN + "/api/helper-ft/events/completion")
        self.assertEqual(kick_post["token"], SWARM_HQ_AGENT_TOKEN_FIXTURE)
        self.assertEqual(completion_post["token"], SWARM_HQ_AGENT_TOKEN_FIXTURE)
        self.assertEqual(kick_post["body"]["run_id"], evidence["run_id"])
        self.assertEqual(kick_post["body"]["sha256_pack"], evidence["computed_shas"]["sha256_pack"])
        self.assertEqual(kick_post["body"]["sha256_train"], evidence["computed_shas"]["sha256_train"])
        self.assertEqual(kick_post["body"]["sha256_holdout"], evidence["computed_shas"]["sha256_holdout"])
        self.assertNotIn("sha256_evidence", kick_post["body"])
        self.assertEqual(completion_post["body"]["run_id"], evidence["run_id"])
        self.assertEqual(completion_post["body"]["sha256_evidence"], file_sha)
        self.assertEqual(completion_post["body"]["sha256_evidence"], evidence["sha256_evidence"])
        self.assertEqual(
            completion_post["body"]["sha256_pack"], evidence["post_train_shas"]["sha256_pack"]
        )
        self.assertEqual(
            completion_post["body"]["sha256_train"], evidence["post_train_shas"]["sha256_train"]
        )
        self.assertEqual(
            completion_post["body"]["sha256_holdout"], evidence["post_train_shas"]["sha256_holdout"]
        )
        self.assertEqual(completion_post["body"]["result"], "MATCH")
        self.assertEqual(completion_post["body"]["exit_code"], 0)
        self.assertFalse(any("evil-hq.example" in u for u, _tok in self.hq_tokens_by_url))
        dumped = json.dumps(kick_post["body"]) + json.dumps(completion_post["body"])
        self.assertNotIn(SWARM_HQ_AGENT_TOKEN_FIXTURE, dumped)

    def test_not_for_train_pack_refused_on_production_shaped_kick(self) -> None:
        def kickoff(body: dict) -> dict:
            return helper_ft_kickoff.handle_train_kickoff(
                body,
                launch_trainer=lambda _b: {"ok": True, "checkpoint_id": "ckpt-prod"},
            )

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            man_path = dest / "MANIFEST.json"
            payload = json.loads(man_path.read_text(encoding="utf-8"))
            payload["not_for_train"] = True
            man_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            manifest = _refresh_hashes(dest, not_for_train=True)
            self._pin(manifest)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest, kickoff=kickoff)
            handler = helper_ft_kickoff.handle_train_kickoff(
                _fresh_kickoff_body(dest, manifest),
                launch_trainer=lambda _b: {"ok": True, "checkpoint_id": "ckpt-prod"},
            )
        self.assertEqual(ctx.exception.field, "not_for_train")
        self.assertEqual(ctx.exception.expected, False)
        self.assertIn("MANIFEST.not_for_train", ctx.exception.actual)
        self.assertFalse(handler.get("ok"))
        self.assertEqual(handler["field"], "not_for_train")
        self.assertEqual(self.hq_posts, [])

    def test_not_for_train_row_refused_without_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            _write_helper_pack(dest)
            train = dest / "curated_pack_v2_train.jsonl"
            row = json.loads(train.read_text(encoding="utf-8").splitlines()[0])
            row["not_for_train"] = True
            train.write_text(json.dumps(row) + "\n", encoding="utf-8")
            pack = dest / "curated_pack_v2.jsonl"
            rows = [json.loads(line) for line in pack.read_text(encoding="utf-8").splitlines() if line.strip()]
            rows[0]["not_for_train"] = True
            pack.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            manifest = _refresh_hashes(dest)
            self._pin(manifest)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(ctx.exception.field, "not_for_train")
        self.assertTrue(any("not_for_train" in str(item) for item in ctx.exception.actual))

    def test_smoke_run_does_not_post_hq_and_leaves_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            man_path = dest / "MANIFEST.json"
            payload = json.loads(man_path.read_text(encoding="utf-8"))
            payload["not_for_train"] = True
            man_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            manifest = _refresh_hashes(dest, not_for_train=True)
            self._pin(manifest)
            log_path = Path(tmp) / "runs" / "helper_ft.log"
            evidence = kick_helper_ft.kick(dest, log_path=log_path, smoke=True)
            run_private = Path(evidence.get("run_private_dir") or "")
            ckpt = log_path.parent / "smoke"
            survivors = [
                p
                for p in (dest, run_private, ckpt)
                if p and os.path.lexists(p)
            ]
        self.assertTrue(evidence["smoke"])
        self.assertIsNone(evidence.get("checkpoint_id"))
        self.assertNotIn("checkpoint_integrity_evidence_path", evidence)
        self.assertEqual(evidence["checkpoint_integrity_status"], "unscored")
        self.assertEqual(survivors, [])
        self.assertEqual(self.hq_posts, [])
        self.assertNotEqual(evidence.get("result"), None)

    def test_wait_returncode_not_overridden_by_ok_dict(self) -> None:
        class FakeProc:
            def wait(self) -> int:
                return 1

        info = kick_helper_ft.wait_for_training_exit(
            {"ok": True, "checkpoint_id": "ckpt-test", "exit_code": 0, "process": FakeProc()}
        )
        self.assertEqual(info["exit_code"], 1)
        self.assertTrue(info["waited"])

        def kickoff(body: dict) -> dict:
            del body
            proc = subprocess.Popen([sys.executable, "-c", "raise SystemExit(1)"])
            return {"ok": True, "checkpoint_id": "ckpt-test", "process": proc}

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            log_path = Path(tmp) / "runs" / "helper_ft.log"
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest, log_path=log_path, kickoff=kickoff)
            rec = json.loads(
                (log_path.parent / "ckpt-test" / "integrity_evidence.json").read_text(
                    encoding="utf-8"
                )
            )
        self.assertEqual(ctx.exception.field, "trainer.exit")
        self.assertEqual(rec["status"], "REFUSED")
        self.assertEqual(rec["exit_code"], 1)

    def test_integrity_evidence_emitted_once_by_kick_not_8765(self) -> None:
        def kickoff(body: dict) -> dict:
            return helper_ft_kickoff.handle_train_kickoff(
                body,
                launch_trainer=lambda _b: {"ok": True, "checkpoint_id": "ckpt-once"},
            )

        buf = StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            with redirect_stdout(buf):
                evidence = kick_helper_ft.kick(dest, kickoff=kickoff)
        prefix = kick_helper_ft.INTEGRITY_EVIDENCE_LINE_PREFIX + " "
        lines = [line for line in buf.getvalue().splitlines() if line.startswith(prefix)]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0], evidence["integrity_evidence_line"])
        self.assertEqual(evidence["result"], "MATCH")

    def _write_action_rows_pack(
        self, dest: Path, rows: list[dict], *, pack_id: str
    ) -> dict:
        train, hold = rows[:-1], rows[-1:]
        write_jsonl(dest / "curated_pack_v2.jsonl", rows)
        write_jsonl(dest / "curated_pack_v2_train.jsonl", train)
        write_jsonl(dest / "curated_pack_v2_holdout.jsonl", hold)
        (dest / "MANIFEST.json").write_text(
            json.dumps(
                {
                    "pack_id": pack_id,
                    "rows": len(rows),
                    "train_rows": len(train),
                    "holdout_rows": len(hold),
                    "champion_touched": False,
                    "live_gate_touched": False,
                    "ft_kicked": False,
                    "consent_champion_false": True,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return _refresh_hashes(dest)

    def test_constant_suspicious_key_is_not_a_leak(self) -> None:
        """Names alone do not refuse: same key, constant non-predictive value."""
        self.assertEqual(
            kick_helper_ft.STATE_LEAK_KEYS,
            frozenset({"risk_hint", "halt_class", "provenance", "agent_config", "category"}),
        )
        actions = ["execute", "execute", "halt", "halt"]
        for key in ("risk_hint", "halt_class", "provenance", "agent_config", "category"):
            with tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / "inbox-pack"
                dest.mkdir()
                rows = [_row(rid=f"c-{key}-{idx}", action=action) for idx, action in enumerate(actions)]
                for row in rows:
                    row["state"] = {
                        "message": row["state"]["message"],
                        "meta": {key: "review"},
                    }
                manifest = self._write_action_rows_pack(
                    dest, rows, pack_id=f"const-{key}"
                )
                self._pin(manifest)
                evidence = kick_helper_ft.kick(dest)
            self.assertEqual(evidence["result"], "MATCH", msg=key)

    def test_gold_aligned_nested_field_is_a_pack_level_leak(self) -> None:
        actions = ["execute", "execute", "halt", "halt"]
        for key in ("risk_hint", "halt_class", "provenance", "agent_config", "category"):
            with tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / "inbox-pack"
                dest.mkdir()
                rows = [_row(rid=f"g-{key}-{idx}", action=action) for idx, action in enumerate(actions)]
                for row, action in zip(rows, actions, strict=True):
                    row["state"] = {
                        "message": row["state"]["message"],
                        "meta": {key: action},
                    }
                manifest = self._write_action_rows_pack(
                    dest, rows, pack_id=f"gold-{key}"
                )
                self._pin(manifest)
                with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                    kick_helper_ft.kick(dest)
            self.assertEqual(ctx.exception.field, "state.leak")
            self.assertTrue(
                any(key in str(item) for item in ctx.exception.actual),
                msg=key,
            )

    def test_top_level_gold_aligned_field_refused(self) -> None:
        actions = ["execute", "execute", "halt", "halt"]
        for key in ("risk_hint", "halt_class", "provenance", "agent_config", "category"):
            with tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / "inbox-pack"
                dest.mkdir()
                rows = [_row(rid=f"t-{key}-{idx}", action=action) for idx, action in enumerate(actions)]
                for row, action in zip(rows, actions, strict=True):
                    row[key] = action
                manifest = self._write_action_rows_pack(
                    dest, rows, pack_id=f"top-{key}"
                )
                self._pin(manifest)
                with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                    kick_helper_ft.kick(dest)
            self.assertEqual(ctx.exception.field, "state.leak")
            self.assertTrue(
                any(key in str(item) for item in ctx.exception.actual),
                msg=key,
            )

    def test_formatting_leaks_are_not_state_leak_gate(self) -> None:
        """Tool names, key shapes, and truncation markers are Mill's pack-time job."""
        actions = ["execute", "execute", "halt", "halt"]
        rows = [_row(rid=f"fmt-{idx}", action=action) for idx, action in enumerate(actions)]
        for row in rows:
            row["state"] = {
                "message": "tool=read_file; detail=src/app.py…",
                "meta": {"tool": "read_file", "keys": ["cmd", "path"]},
            }
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = self._write_action_rows_pack(
                dest, rows, pack_id="formatting-not-leak"
            )
            self._pin(manifest)
            evidence = kick_helper_ft.kick(dest)
        self.assertEqual(evidence["result"], "MATCH")
        self.assertNotIn("state.leak", json.dumps(evidence))

    def test_185133_shaped_synthetic_l3_leaks_refused_on_all_hooks(self) -> None:
        """Replica of 185133: 60 L3 rows with state.meta.risk_hint == gold label.

        The live pack (sha256_pack a73c792f…) is not in this tree and is not
        committed. Synthetic rows only.
        """
        actions = (["execute", "escalate", "halt"] * 20)
        rows = []
        for idx, action in enumerate(actions):
            row = _row(rid=f"l3-{idx:03d}", action=action)
            gold = row["labels"]["action"]["choice"]
            self.assertEqual(gold, action)
            row["state"] = {
                "message": row["state"]["message"],
                "meta": {"risk_hint": gold},
            }
            rows.append(row)
        self.assertEqual(len(rows), 60)
        train, hold = rows[:48], rows[48:]

        def kickoff(body: dict) -> dict:
            return helper_ft_kickoff.handle_train_kickoff(
                body,
                launch_trainer=lambda _b: {"ok": True, "checkpoint_id": "ckpt-leak"},
            )

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            write_jsonl(dest / "curated_pack_v2.jsonl", rows)
            write_jsonl(dest / "curated_pack_v2_train.jsonl", train)
            write_jsonl(dest / "curated_pack_v2_holdout.jsonl", hold)
            (dest / "MANIFEST.json").write_text(
                json.dumps(
                    {
                        "pack_id": "curated_pack_v2-synthetic-185133-shape",
                        "rows": 60,
                        "train_rows": 48,
                        "holdout_rows": 12,
                        "champion_touched": False,
                        "live_gate_touched": False,
                        "ft_kicked": False,
                        "consent_champion_false": True,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            manifest = _refresh_hashes(dest)
            self.assertNotEqual(
                manifest["sha256_pack"],
                "a73c792fb0c70373d77867002304058ef14946027ad4fa6f2121e79216d99f7d",
            )
            self._pin(manifest)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest, kickoff=kickoff)
            handler = helper_ft_kickoff.handle_train_kickoff(
                _fresh_kickoff_body(dest, manifest),
                launch_trainer=lambda _b: {"ok": True, "checkpoint_id": "ckpt-leak"},
            )
            loop_src = Path(__file__).resolve().parents[3] / "packages" / "dottie-loop"
            if str(loop_src) not in sys.path:
                sys.path.insert(0, str(loop_src))
            runner = _load("forge_runner_state_leak", loop_src / "scripts" / "forge_runner.py")
            runner_out = runner.handle_train_kickoff(_fresh_kickoff_body(dest, manifest))
        listed = ctx.exception.actual
        self.assertEqual(ctx.exception.field, "state.leak")
        self.assertEqual(ctx.exception.expected, "absent")
        self.assertIsInstance(listed, list)
        self.assertLessEqual(len(listed), 10)
        self.assertGreaterEqual(len(listed), 1)
        self.assertTrue(any("risk_hint" in str(item) for item in listed))
        self.assertEqual(len(listed), len(set(listed)))
        self.assertFalse(handler.get("ok"))
        self.assertEqual(handler["field"], "state.leak")
        self.assertLessEqual(len(handler["actual"]), 10)
        self.assertTrue(any("risk_hint" in str(item) for item in handler["actual"]))
        self.assertFalse(runner_out.get("ok"))
        self.assertEqual(runner_out["field"], "state.leak")

    def test_stripped_rows_without_state_leaks_go_through(self) -> None:
        """Stripped re-cut: L3 rows keep gold in labels only, never in state."""
        actions = ["execute", "escalate", "halt", "execute", "halt"]
        rows = [_row(rid=f"strip-{idx}", action=action) for idx, action in enumerate(actions)]
        train, hold = rows[:4], rows[4:]
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            write_jsonl(dest / "curated_pack_v2.jsonl", rows)
            write_jsonl(dest / "curated_pack_v2_train.jsonl", train)
            write_jsonl(dest / "curated_pack_v2_holdout.jsonl", hold)
            (dest / "MANIFEST.json").write_text(
                json.dumps(
                    {
                        "pack_id": "curated_pack_v2-stripped-recut",
                        "rows": 5,
                        "train_rows": 4,
                        "holdout_rows": 1,
                        "champion_touched": False,
                        "live_gate_touched": False,
                        "ft_kicked": False,
                        "consent_champion_false": True,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            manifest = _refresh_hashes(dest)
            self._pin(manifest)
            evidence = kick_helper_ft.kick(dest)
        self.assertEqual(evidence["result"], "MATCH")
        self.assertNotIn("state.leak", json.dumps(evidence))
        dumped = json.dumps(rows)
        self.assertNotIn("risk_hint", dumped)
        self.assertNotIn("halt_class", dumped)
        self.assertNotIn("agent_config", dumped)

    def test_inbox_latest_kickoff_is_refused(self) -> None:
        latest = helper_ft_kickoff.handle_train_kickoff(
            {"mode": "helper-ft", "inbox": "latest", "pack_id": "p", "evidence": {"ok": True, "pack_id": "p"}}
        )
        colon = helper_ft_kickoff.handle_train_kickoff(
            {
                "mode": "helper-ft",
                "inbox": "inbox:latest",
                "pack_id": "p",
                "evidence": {"ok": True, "pack_id": "p"},
            }
        )
        http = helper_ft_kickoff.TestClient().post(
            "/train/kickoff",
            json={"mode": "helper-ft", "inbox": "latest", "pack_id": "p", "evidence": {"ok": True, "pack_id": "p"}},
        )
        query = helper_ft_kickoff.TestClient().post(
            "/train/kickoff?inbox=latest",
            json={"mode": "helper-ft", "pack_id": "p", "evidence": {"ok": True, "pack_id": "p"}},
        )
        self.assertFalse(latest["ok"])
        self.assertEqual(latest["field"], "inbox")
        self.assertEqual(latest["actual"], "latest")
        self.assertEqual(colon["field"], "inbox")
        self.assertEqual(http.status_code, 400)
        self.assertEqual(http.json()["field"], "inbox")
        self.assertEqual(query.json()["field"], "inbox")

    def test_inbox_latest_aliases_refused(self) -> None:
        alias = helper_ft_kickoff.handle_train_kickoff(
            {
                "mode": "helper-ft",
                "inbox_latest": True,
                "pack_id": "p",
                "evidence": {"ok": True, "pack_id": "p"},
            }
        )
        pathed = helper_ft_kickoff.handle_train_kickoff(
            {
                "mode": "helper-ft",
                "pack_id": "p",
                "run_private_dir": "/runs/inbox/20260919-093515-host-meta",
                "evidence": {"ok": True, "pack_id": "p", "run_id": "r", "checked_at": "2026-10-19T00:00:00Z"},
            }
        )
        loop_src = Path(__file__).resolve().parents[3] / "packages" / "dottie-loop"
        if str(loop_src) not in sys.path:
            sys.path.insert(0, str(loop_src))
        runner = _load("forge_runner_latest_aliases", loop_src / "scripts" / "forge_runner.py")
        runner_latest = runner.handle_train_kickoff(
            {"mode": "helper-ft", "inbox": "latest", "evidence": {"ok": True, "pack_id": "p"}, "pack_id": "p"}
        )
        self.assertEqual(alias["field"], "inbox_latest")
        self.assertEqual(pathed["field"], "run_private_dir")
        self.assertFalse(runner_latest.get("ok"))
        self.assertEqual(runner_latest["field"], "inbox")
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "runs" / "inbox" / "20260919-093515-host-meta"
            dest.mkdir(parents=True)
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
            rc = kick_helper_ft.main(["--pack", "inbox:latest"])
        self.assertEqual(ctx.exception.field, "pack")
        self.assertEqual(rc, 1)

    def test_8765_training_routes_and_8769_absent_from_lab(self) -> None:
        self.assertEqual(helper_ft_kickoff.DEFAULT_PORT, 8765)
        self.assertEqual(helper_ft_kickoff.TRAINING_START_ROUTES, (("POST", "/train/kickoff"),))
        self.assertEqual(helper_ft_kickoff.JEV_AVA_TRAINING_START_ROUTES, ())
        for name in helper_ft_kickoff.OTHER_HELPER_FT_START_PATHS:
            payload = helper_ft_kickoff.dispatch("POST", name, {"mode": "helper-ft"})[1]
            self.assertFalse(payload["ok"])
            self.assertIn(payload["field"], {"route", "inbox"})
        allowed = helper_ft_kickoff.dispatch("POST", "/train/kickoff", None)[1]
        self.assertEqual(allowed["field"], "body")
        roots = (
            Path(__file__).resolve().parents[1],
            Path(__file__).resolve().parents[3] / "packages" / "dottie-loop",
        )
        hits: list[str] = []
        for root in roots:
            if not root.is_dir():
                continue
            for path in root.rglob("*.py"):
                if path.name.startswith("test_"):
                    continue
                text = path.read_text(encoding="utf-8")
                if "8769" in text:
                    hits.append(str(path.relative_to(root) if path.is_relative_to(root) else path))
        self.assertEqual(hits, [])

    def test_write_evidence_uses_mkstemp(self) -> None:
        src = Path(kick_helper_ft.__file__).read_text(encoding="utf-8")
        self.assertIn("mkstemp", src)
        self.assertIn("os.replace", src)
        self.assertIn("0o400", src)

    def test_codeowners_covers_trust_and_pin_spec(self) -> None:
        root = Path(__file__).resolve().parents[3]
        text = (root / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
        self.assertIn("apps/dottie-os/trust/", text)
        self.assertIn("apps/dottie-os/trust/cam_pin_ed25519.pub", text)
        self.assertIn("apps/dottie-os/trust/cam_pin_key_id", text)
        self.assertIn("apps/dottie-os/scripts/lab/cam_pin_spec.py", text)
        self.assertIn("apps/dottie-os/scripts/lab/kick_helper_ft.py", text)
        self.assertIn("apps/dottie-os/tests/cam_pin_vector_helper.py", text)
        self.assertIn("/.github/", text)
        self.assertIn("/apps/dottie-os/tests/", text)
        self.assertIn(".github/workflows/ci.yml", text)
        self.assertIn("@jcdavis131", text)
        self.assertIn("required code-owner review", text)

    def test_ci_diffs_trust_after_suite(self) -> None:
        root = Path(__file__).resolve().parents[3]
        ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("git diff --exit-code apps/dottie-os/trust/", ci)

    def test_denied_vector_public_key_refused_in_verify_path(self) -> None:
        raw = base64.b64decode(DENIED_VECTOR_PUB_B64, validate=True)
        message = cam_pin_spec.canonical_pin_bytes(
            {
                "pack_id": "p",
                "sha256_pack": "11" * 32,
                "sha256_train": "22" * 32,
                "sha256_holdout": "33" * 32,
                "rows_total": 1,
                "rows_train": 1,
                "rows_holdout": 0,
                "recordedAt": "2026-10-19T00:00:00.000Z",
            }
        )
        for name, spec in (
            ("cli", kick_helper_ft.cam_pin_spec),
            ("handler", helper_ft_kickoff.cam_pin_spec),
        ):
            with self.subTest(name=name):
                with self.assertRaises(cam_pin_spec.CamPinError) as ctx:
                    spec.verify_ed25519(message, b"\x00" * 64, raw)
                self.assertEqual(ctx.exception.field, "cam_pin.pubkey")
                self.assertEqual(ctx.exception.actual, "denied test key")
                self.assertIn(DENIED_VECTOR_PUB_B64, spec.DENIED_PUBLIC_KEYS_B64)

    def test_cli_and_8765_hard_refuse_vector_test_key_even_if_loaded(self) -> None:
        """Production fetch must deny the HQ vector key even if load_cam_public_key returned it."""
        vector = json.loads(HQ_VECTOR_PATH.read_text(encoding="utf-8"))
        denied_pub = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(vector["public_key_b64"], validate=True)
        )
        pin = dict(vector["pin"])
        pin["cam_sig"] = vector["cam_sig"]
        pin["cam_key_id"] = vector["cam_key_id"]
        pin["kid"] = "cam-stamp-kid-1"
        pin["stampVerified"] = True
        pin["pack_matches"] = True
        self.hq_pins[pin["pack_id"]] = pin
        self._key_patcher.stop()
        try:
            with patch.object(
                cam_pin_spec, "load_cam_public_key", return_value=(vector["cam_key_id"], denied_pub)
            ):
                with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                    kick_helper_ft.fetch_cam_pin(pin["pack_id"])
                self.assertEqual(ctx.exception.actual, "denied test key")
                result = helper_ft_kickoff.fetch_cam_pin(pin["pack_id"])
                self.assertFalse(result.get("ok"))
                self.assertEqual(result["actual"], "denied test key")
        finally:
            test_pub = Ed25519PublicKey.from_public_bytes(
                cam_pin_spec.raw_public_from_private(TEST_CAM_PRIVATE)
            )
            self._key_patcher = patch.object(
                cam_pin_spec, "load_cam_public_key", return_value=(TEST_CAM_KEY_ID, test_pub)
            )
            self._key_patcher.start()

    def test_cam_key_id_mismatch_refused_cli_and_8765(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest, cam_key_id="not-the-committed-id")
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
            rc = kick_helper_ft.main(_cli_args(dest))
            body = _fresh_kickoff_body(dest, manifest)
            body["pin"]["cam_key_id"] = "not-the-committed-id"
            body["evidence"]["pin"]["cam_key_id"] = "not-the-committed-id"
            self.hq_pins[manifest["pack_id"]]["cam_key_id"] = "not-the-committed-id"
            response = self.client.post("/train/kickoff", json=body)
        self.assertEqual(rc, 1)
        self.assertEqual(ctx.exception.field, "cam-pin.cam_key_id")
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["field"], "cam-pin.cam_key_id")
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(self.launches, [])

    def test_placeholder_key_id_and_pub_sentinels_refuse(self) -> None:
        pub = cam_pin_spec.CAM_PIN_PUB_PATH.read_text(encoding="utf-8")
        key_id = cam_pin_spec.CAM_PIN_KEY_ID_PATH.read_text(encoding="utf-8")
        self.assertEqual(pub.replace("\r\n", "\n"), cam_pin_spec.PLACEHOLDER_PUB_TEXT)
        self.assertEqual(key_id.replace("\r\n", "\n"), cam_pin_spec.PLACEHOLDER_KEY_ID_TEXT)
        with self.assertRaises(cam_pin_spec.CamPinError) as pub_ctx:
            cam_pin_spec._parse_pub_file(pub)
        self.assertEqual(pub_ctx.exception.actual, "placeholder")
        with self.assertRaises(cam_pin_spec.CamPinError) as id_ctx:
            cam_pin_spec.load_cam_key_id()
        self.assertEqual(id_ctx.exception.actual, "placeholder")

    def test_b64_must_be_standard_padded_roundtrip_64_bytes(self) -> None:
        raw = bytes(range(64))
        good = base64.b64encode(raw).decode("ascii")
        self.assertEqual(cam_pin_spec.require_b64("cam-pin.cam_sig", good, 64), raw)
        with self.assertRaises(cam_pin_spec.CamPinError):
            cam_pin_spec.require_b64("cam-pin.cam_sig", good.rstrip("="), 64)
        url_safe = base64.urlsafe_b64encode(raw).decode("ascii")
        self.assertNotEqual(url_safe, good)
        with self.assertRaises(cam_pin_spec.CamPinError):
            cam_pin_spec.require_b64("cam-pin.cam_sig", url_safe, 64)
        with self.assertRaises(cam_pin_spec.CamPinError):
            cam_pin_spec.require_b64("cam-pin.cam_sig", base64.b64encode(b"\x00" * 32).decode("ascii"), 64)
        pin = dict(SWARM_HQ_PIN_FIXTURE)
        pin["cam_sig"] = good.rstrip("=")
        self.hq_pins[pin["pack_id"]] = pin
        for name, fetch in (("cli", kick_helper_ft.fetch_cam_pin), ("handler", helper_ft_kickoff.fetch_cam_pin)):
            with self.subTest(name=name):
                if name == "cli":
                    with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                        fetch(pin["pack_id"])
                    self.assertEqual(ctx.exception.field, "cam-pin.cam_sig")
                else:
                    result = fetch(pin["pack_id"])
                    self.assertFalse(result.get("ok"))
                    self.assertEqual(result["field"], "cam-pin.cam_sig")

    def test_recorded_at_must_match_millis_z(self) -> None:
        with self.assertRaises(cam_pin_spec.CamPinError) as ctx:
            cam_pin_spec.require_recorded_at("cam-pin.recordedAt", "2026-10-19T00:00:00Z")
        self.assertEqual(ctx.exception.field, "cam-pin.recordedAt")
        pin = dict(SWARM_HQ_PIN_FIXTURE)
        pin["recordedAt"] = "2026-10-19T00:00:00Z"
        pin = {**pin, "cam_sig": pin["cam_sig"]}
        self.hq_pins[pin["pack_id"]] = pin
        with self.assertRaises(kick_helper_ft.KickRefused) as cli_ctx:
            kick_helper_ft.fetch_cam_pin(pin["pack_id"])
        self.assertEqual(cli_ctx.exception.field, "cam-pin.recordedAt")
        result = helper_ft_kickoff.fetch_cam_pin(pin["pack_id"])
        self.assertFalse(result.get("ok"))
        self.assertEqual(result["field"], "cam-pin.recordedAt")

    def test_pack_id_ascii_only(self) -> None:
        with self.assertRaises(cam_pin_spec.CamPinError):
            cam_pin_spec.require_pack_id("cam-pin.pack_id", "pack id")
        with self.assertRaises(cam_pin_spec.CamPinError):
            cam_pin_spec.require_pack_id("cam-pin.pack_id", "päck")
        with self.assertRaises(cam_pin_spec.CamPinError):
            cam_pin_spec.require_pack_id("cam-pin.pack_id", "a" * 129)
        pin = dict(SWARM_HQ_PIN_FIXTURE)
        pin["pack_id"] = "bad/id"
        self.hq_pins["bad/id"] = pin
        with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
            kick_helper_ft.fetch_cam_pin("bad/id")
        self.assertEqual(ctx.exception.field, "cam-pin.pack_id")
        result = helper_ft_kickoff.fetch_cam_pin("bad/id")
        self.assertFalse(result.get("ok"))
        self.assertEqual(result["field"], "cam-pin.pack_id")

    def test_rows_refuse_bool_float_and_over_int32(self) -> None:
        with self.assertRaises(cam_pin_spec.CamPinError) as bool_ctx:
            cam_pin_spec.require_int("cam-pin.rows_total", True)
        self.assertEqual(bool_ctx.exception.actual, "bool")
        with self.assertRaises(cam_pin_spec.CamPinError) as float_ctx:
            cam_pin_spec.require_int("cam-pin.rows_train", 101.0)
        self.assertEqual(float_ctx.exception.actual, "float")
        with self.assertRaises(cam_pin_spec.CamPinError) as over_ctx:
            cam_pin_spec.require_int("cam-pin.rows_holdout", 2**31 + 1)
        self.assertEqual(over_ctx.exception.field, "cam-pin.rows_holdout")
        pin = dict(SWARM_HQ_PIN_FIXTURE)
        pin["rows_total"] = True
        self.hq_pins[pin["pack_id"]] = pin
        with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
            kick_helper_ft.fetch_cam_pin(pin["pack_id"])
        self.assertEqual(ctx.exception.field, "cam-pin.rows_total")
        result = helper_ft_kickoff.fetch_cam_pin(pin["pack_id"])
        self.assertFalse(result.get("ok"))
        self.assertEqual(result["field"], "cam-pin.rows_total")

    def test_vector_helper_never_reads_trust(self) -> None:
        src = Path(cam_pin_vector_helper.__file__).read_text(encoding="utf-8")
        self.assertNotIn("CAM_PIN_PUB_PATH", src)
        self.assertNotIn("load_cam_public_key", src)
        self.assertNotIn("CAM_PIN_KEY_ID_PATH", src)
        self.assertIn("Never reads trust", src)
        pub = cam_pin_spec.raw_public_from_private(TEST_CAM_PRIVATE)
        fields = {
            "pack_id": "p",
            "sha256_pack": "11" * 32,
            "sha256_train": "22" * 32,
            "sha256_holdout": "33" * 32,
            "rows_total": 1,
            "rows_train": 1,
            "rows_holdout": 0,
            "recordedAt": "2026-10-19T00:00:00.000Z",
        }
        message = cam_pin_spec.canonical_pin_bytes(fields)
        sig = base64.b64decode(
            cam_pin_spec.sign_pin_bytes(message, TEST_CAM_PRIVATE), validate=True
        )
        cam_pin_vector_helper.verify_with_key(
            message, sig, base64.b64encode(pub).decode("ascii")
        )

    def test_same_cam_pin_spec_module(self) -> None:
        self.assertIs(helper_ft_kickoff.cam_pin_spec, cam_pin_spec)
        self.assertIs(kick_helper_ft.cam_pin_spec, cam_pin_spec)
        self.assertEqual(cam_pin_spec.SWARM_HQ_ORIGIN, PINNED_HQ_ORIGIN)
        spec_src = Path(cam_pin_spec.__file__).read_text(encoding="utf-8")
        self.assertNotIn("os.environ.get(\"SWARM_HQ_URL\")", spec_src)
        self.assertNotIn("SWARM_HQ_URL_ENV", spec_src)
        self.assertIn('SWARM_HQ_ORIGIN = ""', spec_src)


class Ed25519CofactorTests(unittest.TestCase):
    """SF-A: decode + [8]A == identity, not a hardcoded encoding list. Never writes trust/."""

    def test_module_does_not_hardcode_torsion_encodings(self) -> None:
        src = Path(cam_pin_spec.__file__).read_text(encoding="utf-8")
        self.assertIn("[8]A", src)
        self.assertIn("[L]A", src)
        self.assertIn("y >= p", src)
        self.assertIn("S < L", src)
        self.assertNotIn("26e8958f", src)
        self.assertNotIn("c7176a70", src)
        self.assertEqual(len(TORSION_ENCODINGS), 14)
        self.assertEqual(len(NON_IDENTITY_TORSION_ENCODINGS), 7)

    def test_each_of_14_encodings_refused_as_public_key(self) -> None:
        self.assertEqual(len(TORSION_ENCODINGS), 14)
        for name, raw in TORSION_ENCODINGS:
            with self.subTest(name=name, encoding=raw.hex()):
                with self.assertRaises(cam_pin_spec.CamPinError) as ctx:
                    cam_pin_spec.require_ed25519_point(raw, field="cam_pin.pubkey")
                self.assertEqual(ctx.exception.field, "cam_pin.pubkey")
                with self.assertRaises(cam_pin_spec.CamPinError):
                    cam_pin_spec.verify_ed25519(b"msg", raw + bytes(32), raw)

    def test_small_order_r_refused_with_valid_key(self) -> None:
        pub = cam_pin_spec.raw_public_from_private(TEST_CAM_PRIVATE)
        for name, raw in TORSION_ENCODINGS:
            with self.subTest(name=name):
                sig = raw + bytes(32)
                with self.assertRaises(cam_pin_spec.CamPinError) as ctx:
                    cam_pin_spec.verify_ed25519(b"msg", sig, pub)
                self.assertEqual(ctx.exception.field, "cam-pin.cam_sig.R")

    def test_s_greater_or_equal_l_refused(self) -> None:
        pub = cam_pin_spec.raw_public_from_private(TEST_CAM_PRIVATE)
        for label, scalar in (("L", ED25519_L), ("L+1", ED25519_L + 1), ("max", (1 << 256) - 1)):
            with self.subTest(scalar=label):
                sig = pub + scalar.to_bytes(32, "little")
                with self.assertRaises(cam_pin_spec.CamPinError) as ctx:
                    cam_pin_spec.verify_ed25519(b"msg", sig, pub)
                self.assertEqual(ctx.exception.field, "cam-pin.cam_sig.S")
                self.assertEqual(ctx.exception.expected, "S < L")

    def test_small_order_key_forgery_refused_from_temp_trust(self) -> None:
        """Small-order key in a temp trust dir + R=small-order, S=0 must be refused."""
        pub_b64 = base64.b64encode(IDENTITY).decode("ascii")
        sig_b64 = base64.b64encode(IDENTITY + bytes(32)).decode("ascii")
        pin = {
            "pack_id": "p",
            "sha256_pack": "11" * 32,
            "sha256_train": "22" * 32,
            "sha256_holdout": "33" * 32,
            "rows_total": 1,
            "rows_train": 1,
            "rows_holdout": 0,
            "recordedAt": "2026-10-19T00:00:00.000Z",
            "cam_key_id": "cam-pin-ed25519-1",
            "cam_sig": sig_b64,
        }
        with tempfile.TemporaryDirectory() as tmp:
            trust = Path(tmp) / "trust"
            trust.mkdir()
            pub_path = trust / "cam_pin_ed25519.pub"
            kid_path = trust / "cam_pin_key_id"
            pub_path.write_text("cam-pin-ed25519-1\n" + pub_b64 + "\n", encoding="utf-8")
            kid_path.write_text("cam-pin-ed25519-1\n", encoding="utf-8")
            with patch.object(cam_pin_spec, "CAM_PIN_PUB_PATH", pub_path):
                with patch.object(cam_pin_spec, "CAM_PIN_KEY_ID_PATH", kid_path):
                    with self.assertRaises(cam_pin_spec.CamPinError) as load_ctx:
                        cam_pin_spec.load_cam_public_key()
                    self.assertEqual(load_ctx.exception.field, "cam_pin.pubkey")
                    with self.assertRaises(cam_pin_spec.CamPinError) as verify_ctx:
                        cam_pin_spec.verify_cam_sig(pin)
                    self.assertIn(verify_ctx.exception.field, {"cam_pin.pubkey", "cam-pin.cam_sig.R"})
                    with self.assertRaises(cam_pin_spec.CamPinError) as raw_ctx:
                        cam_pin_spec.verify_ed25519(
                            cam_pin_spec.canonical_pin_bytes(pin),
                            IDENTITY + bytes(32),
                            IDENTITY,
                        )
                    self.assertEqual(raw_ctx.exception.field, "cam_pin.pubkey")
        self.assertTrue(cam_pin_spec.CAM_PIN_PUB_PATH.as_posix().endswith("apps/dottie-os/trust/cam_pin_ed25519.pub"))
        committed = cam_pin_spec.CAM_PIN_PUB_PATH.read_text(encoding="utf-8")
        self.assertEqual(committed.replace("\r\n", "\n"), cam_pin_spec.PLACEHOLDER_PUB_TEXT)
        self.assertNotEqual(IDENTITY, ALL_ZERO)
        self.assertEqual(ORDER2[0], 0xEC)

    def test_mixed_order_key_and_r_refused(self) -> None:
        pub = cam_pin_spec.raw_public_from_private(TEST_CAM_PRIVATE)
        mixed = mixed_order_encodings(pub)
        self.assertEqual(len(mixed), 7)
        torsion_raw = {raw for _name, raw in NON_IDENTITY_TORSION_ENCODINGS}
        for name, raw in mixed:
            with self.subTest(name=name, encoding=raw.hex()):
                self.assertNotEqual(raw, pub)
                self.assertNotIn(raw, torsion_raw)
                with self.assertRaises(cam_pin_spec.CamPinError) as key_ctx:
                    cam_pin_spec.require_ed25519_point(raw, field="cam_pin.pubkey")
                self.assertEqual(key_ctx.exception.field, "cam_pin.pubkey")
                self.assertIn("mixed-order", str(key_ctx.exception.actual))
                with self.assertRaises(cam_pin_spec.CamPinError) as r_ctx:
                    cam_pin_spec.verify_ed25519(b"msg", raw + bytes(32), pub)
                self.assertEqual(r_ctx.exception.field, "cam-pin.cam_sig.R")
                self.assertIn("mixed-order", str(r_ctx.exception.actual))

    def test_generated_prime_order_key_still_verifies(self) -> None:
        private = Ed25519PrivateKey.generate()
        raw_pub = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        message = b"prime-order-ok"
        signature = private.sign(message)
        cam_pin_spec.require_ed25519_point(raw_pub, field="cam_pin.pubkey")
        cam_pin_spec.verify_ed25519(message, signature, raw_pub)

    def test_origin_main_ancestry_is_documented_as_hint(self) -> None:
        spec = Path(cam_pin_spec.__file__).read_text(encoding="utf-8")
        readme = (APP / "README.md").read_text(encoding="utf-8")
        self.assertIn("local-ref hint", spec)
        self.assertIn("git update-ref", spec)
        self.assertIn("hint: ancestor of", spec)
        self.assertIn("hint only", readme)
        self.assertIn("git update-ref", readme)


class CamPinCanonicalSpecTests(unittest.TestCase):
    """Byte-for-byte signed payload. Uses the in-test key, never trust/."""

    def test_canonical_bytes_are_prefix_plus_sorted_minified_json(self) -> None:
        fields = {
            "pack_id": "p",
            "sha256_pack": "11" * 32,
            "sha256_train": "22" * 32,
            "sha256_holdout": "33" * 32,
            "rows_total": 3,
            "rows_train": 2,
            "rows_holdout": 1,
            "recordedAt": "2026-10-19T00:00:00.000Z",
        }
        packed = json.dumps(fields, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
        self.assertEqual(cam_pin_spec.CANONICAL_PREFIX, b"swarm-hq-pin-v1\n")
        self.assertEqual(
            cam_pin_spec.canonical_pin_bytes(fields),
            b"swarm-hq-pin-v1\n" + packed.encode("utf-8"),
        )
        self.assertEqual(
            packed,
            '{"pack_id":"p","recordedAt":"2026-10-19T00:00:00.000Z","rows_holdout":1,"rows_total":3,"rows_train":2,"sha256_holdout":"'
            + "33" * 32
            + '","sha256_pack":"'
            + "11" * 32
            + '","sha256_train":"'
            + "22" * 32
            + '"}',
        )
        pub = cam_pin_spec.raw_public_from_private(TEST_CAM_PRIVATE)
        sig = base64.b64decode(cam_pin_spec.sign_pin_bytes(cam_pin_spec.canonical_pin_bytes(fields), TEST_CAM_PRIVATE), validate=True)
        cam_pin_spec.verify_ed25519(cam_pin_spec.canonical_pin_bytes(fields), sig, pub)
        tampered = dict(fields)
        tampered["recordedAt"] = "2026-10-19T00:00:01Z"
        with self.assertRaises(cam_pin_spec.CamPinError):
            cam_pin_spec.verify_ed25519(cam_pin_spec.canonical_pin_bytes(tampered), sig, pub)
        pub_path = cam_pin_spec.CAM_PIN_PUB_PATH.read_text(encoding="utf-8")
        self.assertNotIn(base64.b64encode(pub).decode("ascii"), pub_path)


class CamPinVectorTests(unittest.TestCase):
    """HQ-shipped cross-implementation vector. Test key never loaded from trust/."""

    def _vector(self) -> dict:
        self.assertTrue(HQ_VECTOR_PATH.is_file(), HQ_VECTOR_PATH)
        raw = HQ_VECTOR_PATH.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), HQ_VECTOR_SHA256)
        return json.loads(raw.decode("utf-8"))

    def _verify_paths(self) -> tuple[tuple[str, object], ...]:
        return (
            ("cli", kick_helper_ft.cam_pin_spec),
            ("handler", helper_ft_kickoff.cam_pin_spec),
        )

    def test_vector_file_sha256_matches_hq_a2cf90e5(self) -> None:
        raw = HQ_VECTOR_PATH.read_bytes()
        self.assertEqual(len(raw), 2548)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), HQ_VECTOR_SHA256)

    def test_vector_canonical_and_sig_cli_and_8765(self) -> None:
        vector = self._vector()
        pin = vector["pin"]
        canonical = vector["canonical"]
        packed = json.dumps(pin, sort_keys=True, separators=(",", ":"))
        self.assertEqual(packed, canonical)
        self.assertEqual(vector["prefix"].encode("utf-8"), cam_pin_spec.CANONICAL_PREFIX)
        message = cam_pin_spec.CANONICAL_PREFIX + canonical.encode("utf-8")
        sig_b64 = vector.get("cam_sig") or pin.get("cam_sig")
        sig = base64.b64decode(sig_b64, validate=True)
        for name, spec in self._verify_paths():
            with self.subTest(name=name):
                self.assertEqual(json.dumps(pin, sort_keys=True, separators=(",", ":")), canonical)
                self.assertEqual(spec.canonical_pin_bytes(pin), message)
                cam_pin_vector_helper.verify_with_key(message, sig, vector["public_key_b64"])
        with self.assertRaises(cam_pin_spec.CamPinError) as ctx:
            cam_pin_spec.verify_ed25519(
                message, sig, base64.b64decode(vector["public_key_b64"], validate=True)
            )
        self.assertEqual(ctx.exception.actual, "denied test key")
        pub_path = cam_pin_spec.CAM_PIN_PUB_PATH.read_text(encoding="utf-8")
        self.assertNotIn(vector["public_key_b64"].strip(), pub_path)
        self.assertNotIn(DENIED_VECTOR_PUB_B64, pub_path)
        self.assertIn("CAM-PIN-ED25519-PLACEHOLDER", pub_path)

    def test_vector_tampered_recorded_at_refused_cli_and_8765(self) -> None:
        vector = self._vector()
        pin = dict(vector["pin"])
        sig_b64 = vector.get("cam_sig") or pin.get("cam_sig")
        sig = base64.b64decode(sig_b64, validate=True)
        tampered = vector["tampered"]
        tamper_pin = tampered["pin"] if isinstance(tampered, dict) and "pin" in tampered else tampered
        self.assertEqual(json.dumps(tamper_pin, sort_keys=True, separators=(",", ":")), tampered["canonical"])
        self.assertNotEqual(tamper_pin["recordedAt"], pin["recordedAt"])
        for name, spec in self._verify_paths():
            with self.subTest(name=name):
                message = spec.canonical_pin_bytes(tamper_pin)
                with self.assertRaises(cam_pin_spec.CamPinError):
                    cam_pin_vector_helper.verify_with_key(message, sig, vector["public_key_b64"])
        pub_path = cam_pin_spec.CAM_PIN_PUB_PATH.read_text(encoding="utf-8")
        self.assertNotIn(vector["public_key_b64"].strip(), pub_path)


class SwarmHqPinContractTests(unittest.TestCase):
    """Freeze GET /api/packs/<pack_id>/pin for CLI and :8765 fetch_cam_pin."""

    def setUp(self) -> None:
        _start_hq_http_mock(self)

    def tearDown(self) -> None:
        _stop_hq_http_mock(self)

    def _fetchers(self) -> tuple[tuple[str, object], ...]:
        return (
            ("cli", kick_helper_ft.fetch_cam_pin),
            ("handler", helper_ft_kickoff.fetch_cam_pin),
        )

    def _result(self, name: str, fetch: object, pack_id: str) -> dict:
        if name == "cli":
            try:
                pin = fetch(pack_id)
            except kick_helper_ft.KickRefused as exc:
                return {
                    "ok": False,
                    "field": exc.field,
                    "expected": exc.expected,
                    "actual": exc.actual,
                }
            return {"ok": True, "pin": pin}
        return fetch(pack_id)

    def test_contract_keys_frozen_for_cli_and_handler(self) -> None:
        self.assertTrue(set(SWARM_HQ_PIN_CONTRACT_REQUIRED) <= set(SWARM_HQ_PIN_FIXTURE))
        self.assertTrue(set(SWARM_HQ_PIN_FIXTURE) <= set(SWARM_HQ_PIN_CONTRACT_ALLOWED))
        self.assertEqual(kick_helper_ft.HQ_PIN_ALLOWED_KEYS, SWARM_HQ_PIN_CONTRACT_ALLOWED)
        self.assertEqual(helper_ft_kickoff.HQ_PIN_ALLOWED_KEYS, SWARM_HQ_PIN_CONTRACT_ALLOWED)
        self.assertEqual(kick_helper_ft.HQ_PIN_REQUIRED_KEYS, SWARM_HQ_PIN_CONTRACT_REQUIRED)
        self.assertEqual(helper_ft_kickoff.HQ_PIN_REQUIRED_KEYS, SWARM_HQ_PIN_CONTRACT_REQUIRED)

    def test_contract_fixture_accepted_by_cli_and_handler(self) -> None:
        fixture = dict(SWARM_HQ_PIN_FIXTURE)
        self.hq_pins[fixture["pack_id"]] = fixture
        for name, fetch in self._fetchers():
            with self.subTest(name=name):
                result = self._result(name, fetch, fixture["pack_id"])
                self.assertTrue(result.get("ok"))
                pin = result["pin"]
                self.assertEqual(pin["pack_id"], fixture["pack_id"])
                self.assertEqual(pin["sha256_pack"], fixture["sha256_pack"])
                self.assertEqual(pin["rows_total"], 2)
                self.assertEqual(pin["rows_train"], 1)
                self.assertEqual(pin["rows_holdout"], 1)
                self.assertIs(pin["pack_matches"], True)
                self.assertEqual(pin["recordedAt"], fixture["recordedAt"])
                self.assertEqual(pin["kid"], fixture["kid"])
                self.assertTrue(pin["stampVerified"])
                self.assertTrue(self.hq_saw_agent_token)

    def test_contract_missing_agent_token_refused_by_cli_and_handler(self) -> None:
        os.environ.pop("SWARM_HQ_AGENT_TOKEN", None)
        self.hq_pins[SWARM_HQ_PIN_FIXTURE["pack_id"]] = dict(SWARM_HQ_PIN_FIXTURE)
        for name, fetch in self._fetchers():
            with self.subTest(name=name):
                result = self._result(name, fetch, SWARM_HQ_PIN_FIXTURE["pack_id"])
                self.assertIsNot(result.get("ok"), True)
                self.assertEqual(result["field"], "SWARM_HQ_AGENT_TOKEN")
                self.assertEqual(result["expected"], "present")
                self.assertEqual(result["actual"], "missing")
        self.assertEqual(self.hq_requests, [])
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            _write_helper_pack(dest)
            rc = kick_helper_ft.main(_cli_args(dest))
        self.assertEqual(rc, 1)

    def test_contract_401_refused_by_cli_and_handler(self) -> None:
        self.hq_http_status = 401
        self.hq_pins[SWARM_HQ_PIN_FIXTURE["pack_id"]] = dict(SWARM_HQ_PIN_FIXTURE)
        for name, fetch in self._fetchers():
            with self.subTest(name=name):
                result = self._result(name, fetch, SWARM_HQ_PIN_FIXTURE["pack_id"])
                self.assertIsNot(result.get("ok"), True)
                self.assertEqual(result["field"], "cam-pin")
                self.assertEqual(result["expected"], "authorized")
                self.assertEqual(result["actual"], "HTTP 401")

    def test_contract_404_refused_by_cli_and_handler(self) -> None:
        for name, fetch in self._fetchers():
            with self.subTest(name=name):
                result = self._result(name, fetch, SWARM_HQ_PIN_FIXTURE["pack_id"])
                self.assertIsNot(result.get("ok"), True)
                self.assertEqual(result["field"], "cam-pin")
                self.assertEqual(result["expected"], "present")
                self.assertEqual(result["actual"], "HTTP 404")

    def test_contract_unknown_key_refused_by_cli_and_handler(self) -> None:
        fixture = dict(SWARM_HQ_PIN_FIXTURE)
        fixture["extra"] = "nope"
        self.hq_pins[fixture["pack_id"]] = fixture
        for name, fetch in self._fetchers():
            with self.subTest(name=name):
                result = self._result(name, fetch, fixture["pack_id"])
                self.assertIsNot(result.get("ok"), True)
                self.assertEqual(result["field"], "cam-pin")
                self.assertEqual(result["expected"], "HQ pin keys")
                self.assertEqual(result["actual"], "unknown extra")

    def test_contract_missing_required_key_refused_by_cli_and_handler(self) -> None:
        fixture = dict(SWARM_HQ_PIN_FIXTURE)
        del fixture["kid"]
        self.hq_pins[fixture["pack_id"]] = fixture
        for name, fetch in self._fetchers():
            with self.subTest(name=name):
                result = self._result(name, fetch, fixture["pack_id"])
                self.assertIsNot(result.get("ok"), True)
                self.assertEqual(result["field"], "cam-pin.kid")
                self.assertEqual(result["expected"], "present")
                self.assertEqual(result["actual"], "missing")

    def test_contract_verified_alias_accepted_by_cli_and_handler(self) -> None:
        fixture = dict(SWARM_HQ_PIN_FIXTURE)
        del fixture["stampVerified"]
        fixture["verified"] = True
        self.hq_pins[fixture["pack_id"]] = fixture
        for name, fetch in self._fetchers():
            with self.subTest(name=name):
                result = self._result(name, fetch, fixture["pack_id"])
                self.assertTrue(result.get("ok"))
                self.assertIs(result["pin"]["stampVerified"], True)


LEAKGATE_EVAL_DIR = TESTS / "fixtures" / "leakgate_eval"
LEAKGATE_MANIFEST_SHA256 = "81209b912e35e7c9850e09a155d25595e76cd3b67051a464a4f92a7f4b9adb56"
LEAKGATE_FIXTURES_JSONL_SHA256 = "3562f36139c6c70a270d9689ad5ec0071e480ea82cc0b26daed997d8663307dc"
LEAKGATE_GEN_PY_SHA256 = "d2df1fbfd45081aebf01261517c59eaccb9e4b93a11e372ed12f88a39207eb74"
LEAKGATE_SOURCE_JSON_SHA256 = "8cd184c53874dea20b858dc11fdb30f0193fa8c72744901b4215e8c23718cfe3"
LEAKGATE_VALIDATE_PY_SHA256 = "f7fb4e2101040923fd7e08e318d1294c2f9a4204c745700ffdb0eb3e5a90c425"
LEAKGATE_GEN_TS = "20261018-230457"
LEAKGATE_GEN_PRODUCED_AT = "2026-10-18T23:04:57-05:00"
REPO_ROOT = APP.parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PACK_GUARD_JOB = "pack-guard"
DOTTIE_OS_SMOKE_JOB = "dottie-os-smoke"
PACK_GUARD_STEP_NAME = "Refuse tracked pack artifacts"
PACK_GUARD_ROOT_PACK = "curated_pack_x.jsonl"
PACK_GUARD_FIXTURES_PACK = (
    "apps/dottie-os/tests/fixtures/leakgate_eval/packs/a/curated_pack_v2.jsonl"
)
# Guard step: {name, run, shell}. shell is the GHA custom-shell form with {0}
# as the script-file placeholder. -p is a bash invocation flag (privileged:
# ignore BASH_ENV/ENV and exported functions). GitHub substitutes {0} then
# execs the string; -p is passed through.
PACK_GUARD_SHELL = (
    "/usr/bin/bash --noprofile --norc -p -euo pipefail {0}"
)
PACK_GUARD_STEP_KEYS = frozenset({"name", "run", "shell"})
PACK_GUARD_CHECKOUT_PIN = (
    "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683"
)
PACK_GUARD_CHECKOUT_KEYS = frozenset({"uses", "with"})
PACK_GUARD_CHECKOUT_WITH = {"persist-credentials": False}
PACK_GUARD_ALLOWED_USES = frozenset(
    {
        PACK_GUARD_CHECKOUT_PIN,
        "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
        "astral-sh/setup-uv@d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86",
    }
)
PACK_GUARD_USES_PIN_RE = re.compile(
    r"^[^@\s]+(?:/[^@\s]+)+@[0-9a-f]{40}$"
)
PACK_GUARD_USES_LINE_RE = re.compile(
    r"^\s+(?:- )?uses:\s*['\"]?([^\s'\"#]+)", re.MULTILINE
)
PACK_GUARD_GHA_KEYS = frozenset(
    {
        "name",
        "on",
        "permissions",
        "jobs",
        "runs-on",
        "steps",
        "uses",
        "with",
        "secrets",
        "env",
        "defaults",
        "concurrency",
        "timeout-minutes",
        "if",
        "continue-on-error",
        "needs",
        "strategy",
        "container",
        "services",
        "outputs",
        "environment",
        "shell",
        "working-directory",
        "id",
        "run",
        "persist-credentials",
        "fetch-depth",
        "path",
        "ref",
        "github-token",
        "script",
        "run-name",
        "runs",
        "using",
        "image",
        "main",
        "pre",
        "post",
        "inputs",
    }
)
PACK_GUARD_ALLOWED_TRIGGERS = frozenset(
    {"push", "pull_request", "schedule", "workflow_dispatch"}
)
PACK_GUARD_LOCAL_USES_PREFIX = "./.github/"
PACK_GUARD_EXPR_RE = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
PACK_GUARD_GITHUB_SAFE = frozenset(
    {
        "actor",
        "api_url",
        "base_ref",
        "event_name",
        "job",
        "ref",
        "ref_name",
        "repository",
        "repository_id",
        "repository_owner",
        "run_attempt",
        "run_id",
        "run_number",
        "server_url",
        "sha",
        "workflow",
        "workspace",
    }
)
PACK_GUARD_DOCKER_DIGEST_RE = re.compile(
    r"^docker://\S+@sha256:[0-9a-f]{64}$"
)
PACK_GUARD_SECRETS_INHERIT_RE = re.compile(
    r"secrets:\s+inherit\b", re.IGNORECASE
)
PACK_GUARD_API_POST_RE = re.compile(
    r"github-script|\bgh\b.*\bapi\b|/statuses/|check-runs|check_runs|"
    r"createCommitStatus|api\.github\.com",
    re.IGNORECASE | re.DOTALL,
)
PACK_GUARD_CLONE_TOKEN_RE = re.compile(
    r"x-access-token:|\$\{\{\s*(github\.token|secrets\.)|"
    r"https://[^/\s]*:[^/@\s]+@github\.com",
    re.IGNORECASE,
)
PACK_GUARD_SECRETS_RE = re.compile(r"\$\{\{\s*secrets\.", re.IGNORECASE)
# pack-guard and dottie-os-smoke: exactly {runs-on, steps}. No needs, name,
# timeout-minutes, if, continue-on-error, defaults, env, container, services.
PACK_GUARD_JOB_KEYS = frozenset({"runs-on", "steps"})
PACK_GUARD_JOB_FORBIDDEN_KEYS = frozenset(
    {"if", "continue-on-error", "needs", "strategy", "name", "permissions"}
)
PACK_GUARD_RUNS_ON = "ubuntu-latest"
PACK_GUARD_LOOKALIKE_RE = re.compile(r"pack[-_ ]?guard")
# S21: per-segment NFKC+alnum, refuse curatedpack / ultradataharvest;
# exact-path allowlist only. Shared with the pack-guard CI python.
PACK_GUARD_PATH_NEEDLES = ("curatedpack", "ultradataharvest")
PACK_GUARD_PATH_ALLOWLIST_PROD = frozenset(
    {
        "docs/curated-packing-notes.md",
        "scripts/run_ultradata_harvest.py",
        "apps/dottie-os/scripts/lab/run_ultradata_harvest.py",
    }
)
# Test-only name: S21 normalizes to contain curatedpack. Factory tests
# pass this set explicitly; CI PATH_PY A= is production only.
PACK_GUARD_PATH_ALLOWLIST_TEST = frozenset(
    {
        "apps/x/uncurated_package.py",
    }
)
PACK_GUARD_PATH_ALLOWLIST = PACK_GUARD_PATH_ALLOWLIST_PROD
PACK_GUARD_PATH_TRANSLIT = {
    "\u0430": "a",
    "\u0435": "e",
    "\u043e": "o",
    "\u0440": "p",
    "\u0441": "c",
    "\u0445": "x",
    "\u0443": "y",
    "\u0456": "i",
    "\u0458": "j",
    "\u0455": "s",
    "\u0501": "d",
    "\u03bf": "o",
    "\u039f": "o",
    "\u0410": "a",
    "\u0415": "e",
    "\u041e": "o",
    "\u0420": "p",
    "\u0421": "c",
    "\u0425": "x",
    "\u0423": "y",
    "\u0406": "i",
}
_PACK_GUARD_ALLOW_REPR = (
    "{" + ",".join(repr(p) for p in sorted(PACK_GUARD_PATH_ALLOWLIST_PROD)) + "}"
)
# Exact (path, sha256) pins for tracked jsonl/gz/sqlite/JSONL-shaped blobs.
PACK_GUARD_BLOB_PIN = frozenset(
    {
        ('.scout/missions/slasso-analytics-trace-ops/timeline.jsonl',
         '9a325a18793f798ba7b99d1792c432f7796b53998a087714a52055a61c285947'),
        ('.scout/missions/slasso-sota-20260815/timeline.jsonl',
         '7ff5d62b75028568e461b006102679c9b0dc569695c54329558ff93d73eec81a'),
        ('apps/arxiviq-factory/sample/pack_sample.jsonl',
         '76b1865557ca8d0d002bca90f5901baf14dc3a3dd3581af1b93e11d12078ea32'),
        ('apps/arxiviq-factory/sources/enrich.jsonl.gz',
         'e94e4d7f2cc41515e21a672789417ba9e872644b81059e3bb752f755f2b9f258'),
        ('apps/arxiviq-factory/sources/paper_skills.jsonl.gz',
         '2d7aed11f43d2ea927ae61d1ebec5272a1ee7849ee3da70175707714cbee25f7'),
        ('apps/arxiviq-factory/sources/papers.jsonl.gz',
         '78c04d61dabd5128e76390f120c4a83644320361aa6dbb725791489a1064a3a3'),
        ('apps/arxiviq-factory/sources/ror.jsonl.gz',
         '456c8942ebbe7ac408575aacd960ae923c7f4c6719499f61c509dc753d4c6fdd'),
        ('apps/arxiviq-factory/sources/teacher.jsonl.gz',
         '89fe1378a8f57a8033549d260398c9f8989735e0406e748c5c9a71c6924488b1'),
        ('apps/atlas-outcomes/sample/pack_sample.jsonl',
         '889a230a6714cec02f30863f1254777f5edbd0b5d0e34b4d28c6efd417a4906e'),
        ('apps/atlas-outcomes/sources/flows.jsonl.gz',
         '6c0e7305d69e1afab7756e4bf6fc3a30c8019c187884eefc4da7029d1a152f3e'),
        ('apps/atlas-outcomes/sources/gauges.jsonl.gz',
         '5de5a28331aac5ed67a3c728e2e1bc9f3aee7c4c143c52aa8277323f390d26ae'),
        ('apps/atlas-outcomes/sources/warnings.jsonl.gz',
         'ca5d4e7756e2cc78922f36e7df0bb651012d3bba06e692915b12e92b04ce8b93'),
        ('apps/ava-factory/data/orchestration/label_corrections.jsonl',
         'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'),
        ('apps/ava-factory/evals/probe_items/arithmetic.jsonl',
         '40cea14a7187795a57591e92eee7500c6d2320390a3688b7ee240c679e519c1e'),
        ('apps/ava-factory/evals/probe_items/code_out.jsonl',
         'd45b230a5dbdfe87a848bdb483e5be583fd6554ebcd4b4e52c7827c0b9023447'),
        ('apps/ava-factory/evals/probe_items/compression.jsonl',
         '2d7e41c994922aa0759b4d94fc1ad9d81f7431566c3db3b12f5eca6d1a069a65'),
        ('apps/ava-factory/evals/probe_items/db_mechanics.jsonl',
         '93961f3b50ea7c69b50e16398ab0c6fe62a7a01aa6f005fc72e58e84a3d9341a'),
        ('apps/ava-factory/evals/probe_items/facts.jsonl',
         '57ea34817d140b4ec17f9636b7e16c840213e24e5548220f25164f3a44d456f0'),
        ('apps/ava-factory/evals/probe_items/modus_ponens.jsonl',
         'eb356044b1ef9531144e6693862a84f63a2a46160971e3ea76ffd880a5c00b53'),
        ('apps/ava-factory/evals/probe_items/safety.jsonl',
         '2cbd55400958cce7cdbb03b71dbc9cb0bdb26d349c4b0e9ec3ac274b42c4328c'),
        ('apps/ava-factory/evals/probe_items/safety_words.jsonl',
         'c1beb5675d891b164cac5450903d93a3b183079189559423ce130b1c681996aa'),
        ('apps/ava-factory/evals/probe_items/tool_selection.jsonl',
         '085cecc134e903ce0cd7378869e9d4ac1af66f83a48fd5944475750e7a38f519'),
        ('apps/ava-factory/runs/cpu_pilot/reports/agentic/metrics_nano.jsonl',
         'f85a63c03418254d6992d57b3dee028db40478a19f062c069afc9a295f848d1b'),
        ('apps/ava-factory/runs/cpu_pilot/reports/agentic/train_stdout.log',
         'fc52388204eefbe1648731b2d95966f95dca71e715e296989f30ce3b5797398e'),
        ('apps/ava-factory/runs/cpu_pilot/reports/base/metrics_nano.jsonl',
         'baed1fb07ae051f2bd2e66263c55b4763e3c52c7526077d2d260f669a94153a7'),
        ('apps/ava-factory/runs/cpu_pilot/reports/base/train_stdout.log',
         '0a9aa58ab4e85fd30dda07ae1e7e8ce7d348b56117d1cd21461953893922099e'),
        ('apps/ava-factory/scripts/fixtures/probe_error_analysis/generations.jsonl',
         '5d595408b7ed3c8f5cbfce2c7b27dad46783f123ebd1d5510f1efa1de8837ed5'),
        ('apps/dottie-harness-api/bundles/ultra/runs/slasso-lattice-v2/timeline.jsonl',
         '4c831ffc6c1477b12fdef9d2281c086a1076bd554e93022b149e088b3e812864'),
        ('apps/dottie-harness-api/lib/analytics_store.jsonl',
         'd147afa804d77408741e94c31ba4e1366d345bf2717bc8d6fd3a5f5ed03b1622'),
        ('apps/dottie-harness-api/lib/flags.jsonl',
         '5b5c7f6feb61e690dfd58463129f5caf8c79ed2ab5f96e5643a4547c3cbee868'),
        ('apps/dottie-harness-api/lib/trace.jsonl',
         'b13997a7fa502a9bc39e2333b59423c01c88de3f2e33c056bb99d4ad98ae60f5'),
        ('apps/jev-v0/fixtures/synthetic_decisions.jsonl',
         '53b3910239275e764ddbd301ea84db2fd0d12cec8fdb2ac25ce570316bce9057'),
        ('bundles/analytics/store.jsonl',
         'd147afa804d77408741e94c31ba4e1366d345bf2717bc8d6fd3a5f5ed03b1622'),
        ('bundles/coordination/timeline.jsonl',
         '6a6312c0573f7b1d1dfb51a617e387a9401a08ccc32fbb890832fce408c9835e'),
        ('bundles/flags/flags.jsonl',
         '5b5c7f6feb61e690dfd58463129f5caf8c79ed2ab5f96e5643a4547c3cbee868'),
        ('bundles/ultra/runs/slasso-analytics-trace-ops/timeline.jsonl',
         'e6dee7dd595c19767169d0019319b7043ac453a320c2630ad45290496c8e6d86'),
        ('bundles/ultra/runs/slasso-sota-20260815/timeline.jsonl',
         'f70acb6cfad1729de4b0b702cd9964265f56da40eac97c24eef0334730315803'),
        ('dottie/bundles/ultra/runs/slasso-analytics-trace-ops/timeline.jsonl',
         '9a325a18793f798ba7b99d1792c432f7796b53998a087714a52055a61c285947'),
        ('dottie/bundles/ultra/runs/slasso-sota-20260815/timeline.jsonl',
         '7ff5d62b75028568e461b006102679c9b0dc569695c54329558ff93d73eec81a'),
        ('examples/goldens.jsonl',
         'e5f9bc06179b760c5f4af47a2c418c85dc1e446e911b6a518d3b2c6edda79149'),
        ('goals/frontend-swarm-hoops-level-everywhere/hidden_files/timeline.jsonl',
         '5f5c7a96c9a788cf38cb610f4ab185fca2cc6dca51f0c5b428c34793cc3f8648'),
        ('goals/orchestrator-scout-prime-always-on/hidden_files/timeline.jsonl',
         '5f5c7a96c9a788cf38cb610f4ab185fca2cc6dca51f0c5b428c34793cc3f8648'),
        ('hidden_files/cron_health.jsonl',
         'cc13e680f4e5e822ce6ae53d0d3081ca11a3d7ad2eb501a01d33831be802c759'),
        ('hidden_files/timeline.jsonl',
         '8330896c15ef7d19cd2255578476147b47b96142c90c9edd0f366ee3f3bbe0c4'),
        ('hidden_files/timeline_cml_research.jsonl',
         '73938bf034d752dd530d0c7bb7a21ad35c6706b20e37f64a80c4d0504b4490b7'),
        ('hidden_files/timeline_dottie_sota.jsonl',
         '2c5b3d6b744599feecc264520c9aead5844c9ef9263474aa79456875a48b6ace'),
        ('hidden_files/trace-orchestration-2026-08-17.jsonl',
         '6d22cda61c3b7d4642ff09b12f563b661ce8a0f64fcff678e35f7f526c4779ba'),
        ('lessons/ledger.jsonl',
         'b880667916ce90997d5d4a58aed6e66586610dd104934e79b4e8ad86162cbfd6'),
        ('packages/dottie-loop/dottie_loop/benchmarks/router_bench_v1.jsonl',
         '5f21340e79c89ef9bd99efc1c1705330dee182377eb728563c7e412b59392f4e'),
        ('pipeline/runs/slasso-analytics-trace-ops/timeline.jsonl',
         '9a325a18793f798ba7b99d1792c432f7796b53998a087714a52055a61c285947'),
        ('tasks/artifacts/corpus_proposals/gridiron_forecast_rows/gridiron_forecast_rows.jsonl',
         '42504913eb5ab860bc282c65f4fdee1f827aaeb958068ef082e656dd070aa959'),
        ('tasks/artifacts/corpus_proposals/oapen_open_books/oapen_open_books.jsonl',
         '5f2a0c2cfb7c7bfd1fa18a72221baff4c3cece1c46e28ad6d6495996db512e40'),
        ('tasks/artifacts/corpus_proposals/repair_transcripts/repair_transcripts.jsonl',
         'e6cadb84f9ec048c458790641aba60013df493a8a927eb2bac49bcb5937ea556'),
        ('tasks/artifacts/ledger_copy.sqlite3',
         '5150bdf0c9bfc12d8a1fc277cb92d02f739847c883f0421b686ea98f10b489c4'),
        ('workspace/skills/lessons/ledger.jsonl',
         'f6c4b7b47d414a790f0ce7b5f757b696172cec0749b284bb805b79437603e16b'),
    }
)
# KNOWN_LEGACY is separate from PACK_GUARD_BLOB_PIN and from any folder
# exemption list. These two files wait for a move decision from Cam and Mill.
# Allowed only at this exact path with this exact sha256; any copy, rename,
# new path, or changed content is refused.
PACK_GUARD_KNOWN_LEGACY = frozenset(
    {
        ('apps/ava-factory/data/orchestration/corpus.jsonl',
         'bf57c470a6f3d287f06857457ca7012f1b8d1551c5c921c2aaf1f6bc1ef04127'),
        ('tasks/artifacts/corpus_proposals/repair_transcripts/repair_sft_unified.jsonl',
         '61a55d528b3945f4a488e0ffd077d7bff49d7344f24409d3441a6120004646be'),
    }
)

# Synthetic critic-tree pin for vendored 0b05 M2. Exact (path, sha256)
# only; not a folder exemption. No production path is in this set.
PACK_GUARD_BLOB_PIN_TEST = frozenset(
    {
        ("apps/x/fixtures/rows.jsonl",
         "d023f31446388bb420186f66819c5648e107b829d39aaee6352f23289a8aa999"),
    }
)
PACK_GUARD_BLOB_MAX = 3 * 1024 * 1024
_PACK_GUARD_INNER = r"""
out=G('cat-file','--batch',inp=raw).stdout
i=0
while i<len(out):
 nl=out.find(bytes([10]),i)
 if nl<0:break
 hdr=out[i:nl].split()
 if len(hdr)<3:
  i=nl+1
  continue
 sz=int(hdr[2]);st=nl+1;oid=hdr[0].decode()
 if sz>CAP:
  B[oid]=None
  i=st+sz+1
  continue
 B[oid]=out[st:st+sz];i=st+sz+1
def jl(b):
 n=0;sk=0
 for line in b.split(bytes([10])):
  s=line.strip()
  if not s:continue
  if s[:1] not in b'{[':
   sk+=1
   if sk>8:return 0
   continue
  try:json.loads(s)
  except Exception:
   sk+=1
   if sk>8:return 0
   continue
  n+=1
  if n>=2:return 1
 return 0
def jarr(b):
 try:v=json.loads(b)
 except Exception:return 0
 if isinstance(v,list) and len(v)>=2 and all(isinstance(x,dict) and ('messages' in x) for x in v[:8]):return 1
 return 0
def tarv7(b):
 if len(b)<512:return 0
 fld=b[148:156]
 try:st=int(fld.replace(bytes([0]),b' ').strip() or b'0',8)
 except Exception:return 0
 if sum(b[:148])+256+sum(b[156:512])!=st:return 0
 name=b[:100].split(bytes([0]),1)[0]
 return 1 if name and all(32<=c<127 for c in name) else 0
def b64d(b):
 al=bytes(list(range(65,91))+list(range(97,123))+list(range(48,58)))
 ok=al+b'+/';ou=al+b'-_'
 parts=[]
 for ln in b.split(bytes([10])):
  s=b''.join(ln.split())
  if s and len(s)>=32 and len(s)%4==0 and all((c in ok or c in ou or c==61) for c in s):parts.append(s)
 s=b''.join(parts)
 if len(s)<32 or len(s)%4:return b''
 try:return base64.b64decode(s,validate=True)
 except Exception:
  try:return base64.b64decode(s,altchars=b'-_',validate=True)
  except Exception:return b''
def hexd(b):
 s=b.strip()
 if len(s)<64 or len(s)%2:return b''
 if not all((48<=c<=57 or 65<=c<=70 or 97<=c<=102) for c in s):return b''
 try:return bytes.fromhex(s.decode('ascii'))
 except Exception:return b''
PK3=b'PK'+bytes([3,4]);PK5=b'PK'+bytes([5,6]);PK7=b'PK'+bytes([7,8])
Z7=b'7z'+bytes([0xbc,0xaf,0x27,0x1c])
RAR=bytes([0x52,0x61,0x72,0x21,0x1a,0x07])
LZ4=bytes([4,0x22,0x4d,0x18]);Z=bytes([0x1f,0x9d]);LZMA=bytes([0x5d,0,0,0x80,0])
GZ=bytes([0x1f,0x8b]);GZ8=bytes([0x1f,0x8b,0x08])
XZ=bytes([0xfd])+b'7zXZ'+bytes([0]);ZST=bytes([0x28,0xb5,0x2f,0xfd])
SQL=b'SQLite format 3'+bytes([0])
def packy(b):
 return bad(b) or b.startswith((GZ,b'BZh',XZ,ZST,SQL,LZ4,Z,LZMA,b'PAR1')) or GZ8 in b or jl(b) or jarr(b)
def bad(b):
 if b is None or len(b)>CAP:return 1
 if b.startswith((LFS,LFS2,LFS3)):return 1
 if PK3 in b or PK5 in b or PK7 in b:return 1
 if RAR in b or Z7 in b:return 1
 if len(b)>261 and b[257:262]==b'ustar':return 1
 if tarv7(b) or (len(b)>1023 and tarv7(b[512:])):return 1
 return 0
def s26(p):
 m,o=info.get(p,('',''))
 if m in ('120000','160000'):return 1
 b=B.get(o,b'')
 if bad(b):return 1
 if isinstance(b,bytes):
  h=hashlib.sha256(b).hexdigest()
  if (p,h) in PIN or (p,h) in LEG or (p,h) in TP:return 0
 cf=p.casefold()
 ext=any(cf.endswith(e) for e in EXT) or '.jsonl.' in cf or '.ndjson.' in cf
 mag=isinstance(b,bytes) and (b.startswith((GZ,b'BZh',XZ,ZST,SQL,LZ4,Z,LZMA,b'PAR1')) or GZ8 in b)
 if isinstance(b,bytes) and (ext or mag or jl(b) or jarr(b)):return 1
 if isinstance(b,bytes):
  dcd=b64d(b)
  if dcd and packy(dcd):return 1
  hx=hexd(b)
  if hx and packy(hx):return 1
 return 0
"""
_PACK_GUARD_INNER_EXEC = (
    "exec('"
    + _PACK_GUARD_INNER.strip("\n")
    .replace("\\", "\\\\")
    .replace("'", "\\'")
    .replace("\n", "\\n")
    + "')"
)
PACK_GUARD_PATH_PY = (
    "import sys,unicodedata,subprocess,os,json,base64,hashlib;"
    f"A={_PACK_GUARD_ALLOW_REPR};"
    f"N={PACK_GUARD_PATH_NEEDLES!r};"
    "C=str.maketrans({"
    "'\\u0430':'a','\\u0435':'e','\\u043e':'o','\\u0440':'p','\\u0441':'c',"
    "'\\u0445':'x','\\u0443':'y','\\u0456':'i','\\u0458':'j','\\u0455':'s',"
    "'\\u0501':'d','\\u03bf':'o','\\u039f':'o','\\u0410':'a','\\u0415':'e',"
    "'\\u041e':'o','\\u0420':'p','\\u0421':'c','\\u0425':'x','\\u0423':'y',"
    "'\\u0406':'i'"
    "});"
    "nrm=lambda s:''.join(ch for ch in unicodedata.normalize('NFKC',s)"
    ".translate(C).casefold() if ch.isalnum());"
    "hit=lambda s:(lambda segs:any(n in x for x in segs for n in N) or "
    "any(n in ''.join(segs) for n in N) or any(ord(c)>127 for c in s))"
    "([nrm(y) for y in s.split('/')]);"
    "PIN=frozenset("
    f"{tuple(sorted(PACK_GUARD_BLOB_PIN))!r}"
    ");"
    "LEG=frozenset("
    f"{tuple(sorted(PACK_GUARD_KNOWN_LEGACY))!r}"
    ");"
    "TP=frozenset("
    f"{tuple(sorted(PACK_GUARD_BLOB_PIN_TEST))!r}"
    ");"
    f"CAP={PACK_GUARD_BLOB_MAX};"
    "EXT=('.zip','.tar','.tgz','.7z','.rar','.gz','.bz2','.xz',"
    "'.zst','.jsonl','.ndjson','.lz4','.lzma','.z01','.parquet',"
    "'.z','.db','.sqlite','.sqlite3');"
    "LFS=b'version https://git-lfs.github.com/spec/v1';"
    "LFS2=b'version https://hawser.github.com/spec/v1';"
    "LFS3=b'version http://git-media.io/v/2';"
    "ge={'PATH':'/usr/bin:/bin','HOME':'/nonexistent',"
    "'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null',"
    "'GIT_NO_REPLACE_OBJECTS':'1'};"
    "G=lambda *a,inp=None:subprocess.run(["
    "'/usr/bin/git','--no-replace-objects',"
    "'-c','core.fsmonitor=false','-c','core.hooksPath=/dev/null',*a"
    "],capture_output=True,env=ge,input=inp);"
    "parse=lambda out,tree:{p.decode('utf-8','surrogateescape'):"
    "(w[0].decode(),(w[2] if tree else w[1]).decode())"
    " for rec in out.split(bytes([0])) if rec and bytes([9]) in rec"
    " for meta,p in [rec.split(bytes([9]),1)] for w in [meta.split()]};"
    "info={};"
    "info.update(parse(G('ls-files','-z','--stage').stdout,0));"
    "sha=(sys.argv[2] if len(sys.argv)>2 and sys.argv[2] else"
    " G('rev-parse','HEAD').stdout.decode().strip());"
    "info.update(parse(G('ls-tree','-r','-z','--full-tree',sha).stdout,1)"
    " if sha else {});"
    "raw=b''.join((o+chr(10)).encode() for m,o in info.values() if o);"
    "B={};"
    f"{_PACK_GUARD_INNER_EXEC};"
    "names=[s for p in open(sys.argv[1],'rb').read().split(bytes([0]))"
    " if p for s in [p.decode('utf-8','surrogateescape')]];"
    "hits=[s for s in names if (s not in A and hit(s)) or s26(s)];"
    "[sys.stdout.write(s.encode('utf-8','backslashreplace').decode()"
    "+chr(10)) for s in hits];"
    "sys.exit(0 if hits else 1)"
)
PACK_GUARD_PATH_RE = PACK_GUARD_PATH_PY
PACK_GUARD_GREP_RE = PACK_GUARD_PATH_PY
PACK_GUARD_ENV_PATH = "/usr/bin:/bin"
PACK_GUARD_ENV_HOME = "/nonexistent"
PACK_GUARD_ENV_LC_ALL = "C"
PACK_GUARD_ENV_SCRUB_RE = re.compile(
    r"PATH=/usr/bin:/bin \\\n\s+HOME=/nonexistent \\\n\s+LC_ALL=C \\\n"
)
PACK_GUARD_ENV_INLINE = (
    f"PATH={PACK_GUARD_ENV_PATH} HOME={PACK_GUARD_ENV_HOME} "
    f"LC_ALL={PACK_GUARD_ENV_LC_ALL}"
)
PACK_GUARD_CODEOWNERS_GITHUB = "/.github/"
PACK_GUARD_CODEOWNERS_TESTS = "/apps/dottie-os/tests/"
PACK_GUARD_CODEOWNERS_FACTORY = (
    "apps/dottie-os/tests/test_ultradata_factory.py"
)
PACK_GUARD_CODEOWNERS_CRITIC = "apps/dottie-os/tests/test_critic_91_*.py"
PACK_GUARD_CODEOWNERS_OWNER = "@jcdavis131"
PACK_GUARD_CHECKOUT_USES_RE = re.compile(
    r"^actions/checkout@[0-9a-fA-F]{40}$"
)
PACK_GUARD_SHELL_EUO = "-euo pipefail"
# S6: ci.yml top-level keys and the trigger block on main (a3872eab).
PACK_GUARD_WORKFLOW_KEYS = frozenset({"name", "on", "permissions", "jobs"})
PACK_GUARD_ON_BLOCK = (
    "on:\n"
    "  push:\n"
    "    branches: [main]\n"
  "  pull_request:\n"
    "    branches: [main]\n"
)
PACK_GUARD_PERMISSIONS_BLOCK = "permissions:\n  contents: read\n"
# Half of 2561 tracked files when the floor was set, rounded down.
PACK_GUARD_LS_FILES_FLOOR = 1280
PACK_GUARD_EARLIER_BAN_RE = re.compile(
    r"GITHUB_ENV|GITHUB_PATH|read-tree|\breset\b|update-index|sparse"
    r"|excludesFile|info/exclude|update-ref|--orphan|\bstash\b"
    r"|\bgit\b(?:[\t ]+\S+)*[\t ]+rm\b",
    re.IGNORECASE,
)
PACK_GUARD_GIT_ENV_KEYS = frozenset(
    {"GIT_INDEX_FILE", "GIT_DIR", "GIT_WORK_TREE"}
)
CRITIC_91_MUTATIONS_SHA256 = (
    "039fc431010be21b1ef5fab8d8d0c1c32311321a3bd4b474a5fe14152176471f"
)
CRITIC_91_136F_SHA256 = (
    "f8edfd4ddd0ba6405870cacdc642a0413a50e68aca4e62d4db2e7e3eff31b282"
)
CRITIC_91_AF2D_SHA256 = (
    "7f8ca3fec9e50dd45e2e53b4a86bb7ce575c5e1600d9e1f11335f57405bbb510"
)
CRITIC_91_50D2_SHA256 = (
    "32a310671d274481fbef2b98007e75ae7ed2205ebf82e1c4281e622508caeaa2"
)
CRITIC_91_CE30_SHA256 = (
    "d2295e285f0babb054e3c898c7cd5816d6b32db6c865ad7eac35209e6a671fd3"
)
CRITIC_91_F8F1_SHA256 = (
    "4cdf999eef803bd20ee448a3c836230fcf9fe294bf2b3c11a20ffeba081986a0"
)
CRITIC_91_0B05_SHA256 = (
    "36130a164b5130b8404b05986308ad551396cedd02fb17abff6c8f899b4daeaf"
)
CRITIC_91_0AC5_SHA256 = (
    "ba9182224c1b1f681319768a6734b3403a3ef58007fb26463205229ee43e3474"
)
LEAKGATE_TRACKED_NAMES = frozenset(
    {
        "EVAL_ONLY",
        "MANIFEST.json",
        "README.md",
        "gen.py",
        "source.json",
        "validate.py",
    }
)
SYNTHETIC_UUID_RE = re.compile(r"^synthetic-\d{3}$")
RFC4122_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
# Hex ids, not JSON decimal literals: ≥10 hex chars with at least one a-f.
HEX_ID_10_RE = re.compile(
    r"(?i)(?<![0-9a-f])(?=[0-9a-f]{10,})[0-9a-f]*[a-f][0-9a-f]*(?![0-9a-f])"
)
# Real UltraData row ids (S5/S9): anywhere in source.json raw text.
AGENT_ID_RE = re.compile(r"(Code|General)_Agent_\d{6}", re.IGNORECASE)


def _assert_source_json_is_synthetic(raw: str) -> None:
    """Fail if source.json raw text or payload looks like real UltraData.

    Isolated from sha pins so a mutated copy still goes red when
    HelperFtLeakGateEvalTests.setUpClass is stubbed.
    """
    lowered = raw.lower()
    if "ultradata" in lowered:
        raise AssertionError("source.json must not contain an ultradata substring")
    if "openbmb" in lowered:
        raise AssertionError("source.json must not contain an openbmb substring")
    agent_ids = [match.group(0) for match in AGENT_ID_RE.finditer(raw)]
    if agent_ids:
        raise AssertionError(f"real agent ids: {agent_ids[:5]}")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise AssertionError("source.json must be a JSON object")
    if payload.get("synthetic") is not True:
        raise AssertionError("source.json must set synthetic: true")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise AssertionError("source.json rows must be a list")
    if len(rows) != 16:
        raise AssertionError(f"source.json rows {len(rows)} != 16")
    uuids = _source_uuid_values(payload)
    if len(uuids) != 16:
        raise AssertionError(f"uuid values {len(uuids)} != 16")
    if len(set(uuids)) != 16:
        raise AssertionError("uuid values must be unique")
    for value in uuids:
        if SYNTHETIC_UUID_RE.fullmatch(value) is None:
            raise AssertionError(f"non-synthetic uuid: {value!r}")
    rfc = RFC4122_UUID_RE.findall(raw)
    if rfc:
        raise AssertionError(f"rfc4122 uuids: {rfc[:5]}")
    hex_ids = HEX_ID_10_RE.findall(raw)
    if hex_ids:
        raise AssertionError(f"10+ hex-char ids: {hex_ids[:5]}")


def _source_uuid_values(obj: object) -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "uuid":
                found.append(value if isinstance(value, str) else str(value))
            found.extend(_source_uuid_values(value))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_source_uuid_values(item))
    return found


def _generate_leakgate_fixtures(
    dest: Path, *, env: dict[str, str] | None = None
) -> Path:
    """Run Mill's vendored gen.py into dest. Fail loudly on hash mismatch."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            sys.executable,
            str(LEAKGATE_EVAL_DIR / "gen.py"),
            "--src",
            str(LEAKGATE_EVAL_DIR / "source.json"),
            "--out",
            str(dest),
            "--ts",
            LEAKGATE_GEN_TS,
            "--produced-at",
            LEAKGATE_GEN_PRODUCED_AT,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"leakgate gen.py failed rc={proc.returncode}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    fx = dest / "fixtures.jsonl"
    man = dest / "MANIFEST.json"
    fx_sha = hashlib.sha256(fx.read_bytes()).hexdigest()
    man_sha = hashlib.sha256(man.read_bytes()).hexdigest()
    if fx_sha != LEAKGATE_FIXTURES_JSONL_SHA256:
        raise AssertionError(
            f"generated fixtures.jsonl sha256 {fx_sha} != {LEAKGATE_FIXTURES_JSONL_SHA256}"
        )
    if man_sha != LEAKGATE_MANIFEST_SHA256:
        raise AssertionError(
            f"generated MANIFEST.json sha256 {man_sha} != {LEAKGATE_MANIFEST_SHA256}"
        )
    return dest


def _write_action_pack(dest: Path, rows: list[dict], *, pack_id: str) -> dict:
    train, hold = rows[:-1], rows[-1:]
    write_jsonl(dest / "curated_pack_v2.jsonl", rows)
    write_jsonl(dest / "curated_pack_v2_train.jsonl", train)
    write_jsonl(dest / "curated_pack_v2_holdout.jsonl", hold)
    (dest / "MANIFEST.json").write_text(
        json.dumps(
            {
                "pack_id": pack_id,
                "rows": len(rows),
                "train_rows": len(train),
                "holdout_rows": len(hold),
                "champion_touched": False,
                "live_gate_touched": False,
                "ft_kicked": False,
                "consent_champion_false": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return _refresh_hashes(dest)


class HelperFtLeakGateEvalTests(unittest.TestCase):
    """Mill leak-gate fixtures: 25 refuse + 25 twins + 6 clean, eval-only."""

    fixture_root: Path
    _fixture_tmp: tempfile.TemporaryDirectory[str]
    index: dict

    @classmethod
    def setUpClass(cls) -> None:
        cls._fixture_tmp = tempfile.TemporaryDirectory()
        cls.fixture_root = _generate_leakgate_fixtures(Path(cls._fixture_tmp.name))
        cls.index = json.loads(
            (cls.fixture_root / "MANIFEST.json").read_text(encoding="utf-8")
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._fixture_tmp.cleanup()

    def setUp(self) -> None:
        self.kickoff_calls: list[dict] = []
        _start_hq_http_mock(self)

        def fake_post(body: dict, url: str | None = None) -> dict:
            self.kickoff_calls.append(body)
            self.assertNotEqual(body.get("inbox"), "latest")
            self.assertIn(body.get("mode"), ("helper-ft", "helper-ft-smoke"))
            return {"ok": True, "checkpoint_id": "ckpt-eval", "exit_code": 0}

        self._orig_post = kick_helper_ft.post_kickoff
        kick_helper_ft.post_kickoff = fake_post

    def tearDown(self) -> None:
        kick_helper_ft.post_kickoff = self._orig_post
        _stop_hq_http_mock(self)

    def _pin(self, manifest: dict, **overrides: object) -> dict:
        pin = _cam_pin(manifest, **overrides)
        self.hq_pins[manifest["pack_id"]] = pin
        return pin

    def test_fixture_manifest_sha256(self) -> None:
        generated = self.fixture_root / "MANIFEST.json"
        fixtures = self.fixture_root / "fixtures.jsonl"
        self.assertEqual(
            hashlib.sha256(generated.read_bytes()).hexdigest(),
            LEAKGATE_MANIFEST_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(fixtures.read_bytes()).hexdigest(),
            LEAKGATE_FIXTURES_JSONL_SHA256,
        )
        committed = LEAKGATE_EVAL_DIR / "MANIFEST.json"
        self.assertEqual(
            hashlib.sha256(committed.read_bytes()).hexdigest(),
            LEAKGATE_MANIFEST_SHA256,
        )
        self.assertEqual(
            hashlib.sha256((LEAKGATE_EVAL_DIR / "gen.py").read_bytes()).hexdigest(),
            LEAKGATE_GEN_PY_SHA256,
        )
        self.assertEqual(
            hashlib.sha256((LEAKGATE_EVAL_DIR / "source.json").read_bytes()).hexdigest(),
            LEAKGATE_SOURCE_JSON_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(
                (LEAKGATE_EVAL_DIR / "validate.py").read_bytes()
            ).hexdigest(),
            LEAKGATE_VALIDATE_PY_SHA256,
        )
        self.assertTrue((LEAKGATE_EVAL_DIR / "EVAL_ONLY").is_file())
        rel = "apps/dottie-os/tests/fixtures/leakgate_eval/"
        listed = subprocess.check_output(
            ["git", "ls-files", rel],
            cwd=REPO_ROOT,
            text=True,
        )
        tracked = {line for line in listed.splitlines() if line}
        expected = {f"{rel}{name}" for name in LEAKGATE_TRACKED_NAMES}
        self.assertEqual(tracked, expected)

    def test_source_json_is_synthetic(self) -> None:
        """Mill source.json is synthetic; do not grep a bare ``uuid`` key.

        The wrapper is ``{"synthetic": true, "rows": [...]}`` with 16
        ``"uuid"`` values matching ``synthetic-NNN``. Forbid UltraData
        text, ``openbmb``, ``(Code|General)_Agent_\\d{6}``, and
        uuid-like (RFC4122 / 10+ hex) ids.
        """
        raw = (LEAKGATE_EVAL_DIR / "source.json").read_text(encoding="utf-8")
        _assert_source_json_is_synthetic(raw)

    def test_mill_leakgate_fixtures_end_to_end(self) -> None:
        cases = self.index["case_list"]
        self.assertEqual(len(cases), 56)
        refuse_n = sum(1 for spec in cases if spec["expect"] == "refuse")
        twin_n = sum(1 for spec in cases if str(spec.get("case") or "").startswith("twin_"))
        clean_n = sum(
            1
            for spec in cases
            if spec["expect"] == "accept" and not spec.get("twin_of")
        )
        self.assertEqual(refuse_n, 25)
        self.assertEqual(twin_n, 25)
        self.assertEqual(clean_n, 6)
        results: list[dict[str, object]] = []
        for spec in cases:
            case_id = spec["case"]
            expect = spec["expect"]
            src = self.fixture_root / "packs" / case_id
            with self.subTest(case=case_id):
                with tempfile.TemporaryDirectory() as tmp:
                    dest = Path(tmp) / case_id
                    shutil.copytree(src, dest)
                    manifest = json.loads((dest / "MANIFEST.json").read_text(encoding="utf-8"))
                    self.assertTrue(manifest.get("not_for_train"))
                    self.assertTrue(manifest.get("eval_only"))
                    self._pin(manifest)
                    got = "accept"
                    field = ""
                    try:
                        evidence = kick_helper_ft.kick(dest, smoke=True)
                        field = str(evidence.get("field") or "")
                    except kick_helper_ft.KickRefused as exc:
                        got = "refuse" if exc.field == "state.leak" else f"refuse:{exc.field}"
                        field = exc.field
                    self.assertEqual(got, expect, msg=f"{case_id} field={field}")
            results.append(
                {
                    "case": case_id,
                    "expect": expect,
                    "got": got,
                    "ok": got == expect,
                }
            )
        ok_n = sum(1 for row in results if row["ok"])
        artifact = Path("/opt/cursor/artifacts/leakgate_56_results.md")
        artifact.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Leak-gate mill fixtures (56/56)",
            "",
            f"MANIFEST.json sha256 `{LEAKGATE_MANIFEST_SHA256}`",
            "",
            "| case | expect | got | ok |",
            "|---|---|---|---|",
        ]
        for row in results:
            mark = "PASS" if row["ok"] else "FAIL"
            lines.append(f"| `{row['case']}` | {row['expect']} | {row['got']} | {mark} |")
        lines.append("")
        lines.append(f"Total {ok_n}/56")
        artifact.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assertEqual(ok_n, 56)

    def test_readme_validate_py_runs_green(self) -> None:
        """README regen: python3 validate.py <out-dir> reports OK 56/56."""
        proc = subprocess.run(
            [sys.executable, "validate.py", str(self.fixture_root)],
            cwd=LEAKGATE_EVAL_DIR,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            proc.returncode,
            0,
            msg=f"stdout={proc.stdout!r} stderr={proc.stderr!r}",
        )
        self.assertIn("OK 56/56", proc.stdout)
        self.assertNotIn("MISMATCH", proc.stdout)

    def test_gen_sha_stable_under_c_locale(self) -> None:
        """S1: gen.py utf-8 opens keep the pinned shas when LC_ALL=C."""
        env = os.environ.copy()
        env["LC_ALL"] = "C"
        env["LANG"] = "C"
        env.pop("PYTHONIOENCODING", None)
        with tempfile.TemporaryDirectory() as tmp:
            dest = _generate_leakgate_fixtures(Path(tmp), env=env)
            self.assertEqual(
                hashlib.sha256((dest / "fixtures.jsonl").read_bytes()).hexdigest(),
                LEAKGATE_FIXTURES_JSONL_SHA256,
            )
            self.assertEqual(
                hashlib.sha256((dest / "MANIFEST.json").read_bytes()).hexdigest(),
                LEAKGATE_MANIFEST_SHA256,
            )


class SourceJsonSyntheticRawTextTests(unittest.TestCase):
    """S5: raw-text bans, independent of HelperFtLeakGateEvalTests sha pins."""

    def _mill_payload(self) -> dict:
        raw = (LEAKGATE_EVAL_DIR / "source.json").read_text(encoding="utf-8")
        payload = json.loads(raw)
        self.assertIsInstance(payload, dict)
        return payload

    def test_mill_source_json_still_passes(self) -> None:
        raw = (LEAKGATE_EVAL_DIR / "source.json").read_text(encoding="utf-8")
        _assert_source_json_is_synthetic(raw)

    def test_four_real_id_placements_go_red_with_setupclass_stubbed(self) -> None:
        mill = self._mill_payload()

        def dump(payload: dict) -> str:
            return json.dumps(payload, ensure_ascii=False)

        def in_message() -> str:
            payload = json.loads(json.dumps(mill))
            payload["rows"][0]["state"]["message"] += " Code_Agent_039442"
            return dump(payload)

        def in_trajectory_id() -> str:
            payload = json.loads(json.dumps(mill))
            payload["rows"][0]["trajectory_id"] = "openbmb/x:General_Agent_112972"
            return dump(payload)

        def openbmb_without_ultradata() -> str:
            payload = json.loads(json.dumps(mill))
            payload["rows"][0]["source"]["hf"] = "openbmb/SFT-Agent-2609"
            raw = dump(payload)
            self.assertNotIn("ultradata", raw.lower())
            return raw

        def in_any_field() -> str:
            payload = json.loads(json.dumps(mill))
            payload["note"] = str(payload.get("note") or "") + " General_Agent_112990"
            return dump(payload)

        def lower_agent() -> str:
            payload = json.loads(json.dumps(mill))
            payload["rows"][0]["state"]["message"] += " code_agent_039442"
            return dump(payload)

        placements = (
            ("Code_Agent_039442 inside a message", in_message),
            ("openbmb/x:General_Agent_112972 in trajectory_id", in_trajectory_id),
            ("openbmb/SFT-Agent-2609 without ultradata", openbmb_without_ultradata),
            ("General_Agent_112990 in any field", in_any_field),
            ("code_agent_039442 lowercase (S9)", lower_agent),
        )

        def _noop_setup(cls: type) -> None:
            return None

        with (
            patch.object(
                HelperFtLeakGateEvalTests,
                "setUpClass",
                classmethod(_noop_setup),
            ),
            patch.object(
                HelperFtLeakGateEvalTests,
                "tearDownClass",
                classmethod(_noop_setup),
            ),
        ):
            for label, mutate in placements:
                with self.subTest(placement=label):
                    raw = mutate()
                    with tempfile.TemporaryDirectory() as tmp:
                        fake_dir = Path(tmp)
                        (fake_dir / "source.json").write_text(
                            raw, encoding="utf-8"
                        )
                        with patch(
                            f"{__name__}.LEAKGATE_EVAL_DIR", fake_dir
                        ):
                            case = HelperFtLeakGateEvalTests(
                                "test_source_json_is_synthetic"
                            )
                            with self.assertRaises(AssertionError):
                                case.test_source_json_is_synthetic()


def _pack_guard_norm_segment(segment: str) -> str:
    folded = (
        unicodedata.normalize("NFKC", segment)
        .translate(str.maketrans(PACK_GUARD_PATH_TRANSLIT))
        .casefold()
    )
    return "".join(ch for ch in folded if ch.isalnum())


def _pack_guard_path_is_banned(
    path: str, extra_allow: frozenset[str] | None = None
) -> bool:
    """S21: exact-path allowlist, else refuse curatedpack/ultradataharvest."""
    posix = path.replace("\\", "/")
    allow = PACK_GUARD_PATH_ALLOWLIST_PROD | (extra_allow or frozenset())
    if posix in allow:
        return False
    segs = [_pack_guard_norm_segment(part) for part in posix.split("/")]
    blob = "".join(segs)
    if any(
        needle in seg
        for seg in segs
        for needle in PACK_GUARD_PATH_NEEDLES
    ) or any(needle in blob for needle in PACK_GUARD_PATH_NEEDLES):
        return True
    return any(ord(ch) > 127 for ch in posix)


def _yaml_parse_fail(message: str) -> None:
    raise AssertionError(f"workflow YAML parse failed: {message}")


def _yaml_hex_escape(s: str, i: int, width: int) -> tuple[str, int]:
    end = i + width
    if end > len(s):
        _yaml_parse_fail("truncated YAML hex escape")
    digits = s[i:end]
    try:
        return chr(int(digits, 16)), end
    except (ValueError, OverflowError) as exc:
        raise AssertionError(
            f"workflow YAML parse failed: bad hex escape {digits!r}"
        ) from exc


def _yaml_read_quoted(s: str, i: int) -> tuple[str, int, bool]:
    """YAML 1.2 quoted scalar. Third flag is True when an escape was decoded."""
    quote = s[i]
    i += 1
    out: list[str] = []
    had_escape = False
    if quote == "'":
        while i < len(s):
            ch = s[i]
            if ch == "'":
                if i + 1 < len(s) and s[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                return "".join(out), i + 1, had_escape
            out.append(ch)
            i += 1
        _yaml_parse_fail("unterminated quoted string")
    if quote != '"':
        _yaml_parse_fail("quoted scalar missing quotes")
    simple = {
        "0": "\0",
        "a": "\a",
        "b": "\b",
        "t": "\t",
        "n": "\n",
        "v": "\v",
        "f": "\f",
        "r": "\r",
        "e": "\x1b",
        " ": " ",
        '"': '"',
        "/": "/",
        "\\": "\\",
        "N": "\u0085",
        "_": "\u00a0",
        "L": "\u2028",
        "P": "\u2029",
    }
    while i < len(s):
        ch = s[i]
        if ch == '"':
            return "".join(out), i + 1, had_escape
        if ch == "\\":
            had_escape = True
            i += 1
            if i >= len(s):
                _yaml_parse_fail("truncated YAML escape")
            nxt = s[i]
            if nxt == "x":
                ch, i = _yaml_hex_escape(s, i + 1, 2)
                out.append(ch)
                continue
            if nxt == "u":
                ch, i = _yaml_hex_escape(s, i + 1, 4)
                out.append(ch)
                continue
            if nxt == "U":
                ch, i = _yaml_hex_escape(s, i + 1, 8)
                out.append(ch)
                continue
            if nxt == "\n":
                i += 1
                continue
            if nxt not in simple:
                _yaml_parse_fail(f"unknown YAML escape \\{nxt}")
            out.append(simple[nxt])
            i += 1
            continue
        out.append(ch)
        i += 1
    _yaml_parse_fail("unterminated quoted string")
    raise AssertionError("unreachable")


def _yaml_parse_quoted(s: str, i: int) -> tuple[str, int]:
    value, end, _had = _yaml_read_quoted(s, i)
    return value, end


_YAML_ANCHORS: dict[str, object] = {}


def _yaml_refuse_tag_or_merge(raw: str, *, what: str) -> None:
    stripped = raw.strip()
    if stripped.startswith("!!") or stripped.startswith("!<"):
        _yaml_parse_fail(f"{what} uses YAML tag")
    if stripped == "<<" or stripped.startswith("<<"):
        _yaml_parse_fail(f"{what} uses YAML merge key")


def _yaml_parse_key(raw: str) -> str:
    stripped = raw.strip()
    if stripped.startswith("?"):
        _yaml_parse_fail("complex YAML key")
    _yaml_refuse_tag_or_merge(stripped, what="workflow key")
    if stripped.startswith("&") or stripped.startswith("*"):
        _yaml_parse_fail("workflow key uses YAML anchor/alias")
    if stripped.startswith(("'", '"')):
        decoded, end, had = _yaml_read_quoted(stripped, 0)
        if end != len(stripped):
            _yaml_parse_fail(f"trailing junk on quoted key {stripped!r}")
        if had:
            _yaml_parse_fail(f"escape sequence in workflow key {decoded!r}")
        key = decoded
    else:
        key = stripped
    folded = key.casefold()
    if folded in PACK_GUARD_GHA_KEYS and key != folded:
        _yaml_parse_fail(f"mixed-case workflow key {key!r}")
    return key


def _yaml_skip_flow_space(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t\n\r":
        i += 1
    if i < len(s) and s[i] == "#":
        while i < len(s) and s[i] not in "\n\r":
            i += 1
        return _yaml_skip_flow_space(s, i)
    return i


def _yaml_parse_plain_flow(s: str, i: int) -> tuple[object, int]:
    start = i
    while i < len(s) and s[i] not in ",]}#\n\r":
        if s[i] == ":" and (i + 1 >= len(s) or s[i + 1] in " ,]}"):
            break
        i += 1
    raw = s[start:i].strip()
    _yaml_refuse_tag_or_merge(raw, what="flow scalar")
    return _parse_yaml_scalar(raw), i


def _yaml_flow_is_complete(s: str) -> bool:
    depth = 0
    in_single = False
    in_double = False
    saw = False
    idx = 0
    while idx < len(s):
        ch = s[idx]
        if in_single:
            if ch == "'":
                if idx + 1 < len(s) and s[idx + 1] == "'":
                    idx += 2
                    continue
                in_single = False
            idx += 1
            continue
        if in_double:
            if ch == "\\":
                idx += 2
                continue
            if ch == '"':
                in_double = False
            idx += 1
            continue
        if ch == "'":
            in_single = True
        elif ch == '"':
            in_double = True
        elif ch in "{[":
            depth += 1
            saw = True
        elif ch in "}]":
            depth -= 1
        idx += 1
    return saw and depth <= 0 and not in_single and not in_double


def _yaml_parse_flow(s: str, i: int) -> tuple[object, int]:
    i = _yaml_skip_flow_space(s, i)
    if i >= len(s):
        _yaml_parse_fail("truncated flow YAML")
    if s[i] in "'\"":
        return _yaml_parse_quoted(s, i)
    if s[i] == "{":
        mapping: dict[str, object] = {}
        i = _yaml_skip_flow_space(s, i + 1)
        if i < len(s) and s[i] == "}":
            return mapping, i + 1
        while True:
            i = _yaml_skip_flow_space(s, i)
            if i < len(s) and s[i] in "'\"":
                key, i, had = _yaml_read_quoted(s, i)
                if had:
                    _yaml_parse_fail(f"escape sequence in workflow key {key!r}")
                _yaml_refuse_tag_or_merge(key, what="flow key")
                folded = key.casefold()
                if folded in PACK_GUARD_GHA_KEYS and key != folded:
                    _yaml_parse_fail(f"mixed-case workflow key {key!r}")
            else:
                start = i
                while i < len(s) and s[i] not in ",]}#\n\r":
                    if s[i] == ":" and (i + 1 >= len(s) or s[i + 1] in " ,]}"):
                        break
                    i += 1
                key = _yaml_parse_key(s[start:i])
            i = _yaml_skip_flow_space(s, i)
            if i >= len(s) or s[i] != ":":
                _yaml_parse_fail("flow mapping missing ':'")
            i += 1
            value, i = _yaml_parse_flow(s, i)
            if key in mapping:
                _yaml_parse_fail(f"duplicate YAML key {key!r}")
            mapping[str(key)] = value
            i = _yaml_skip_flow_space(s, i)
            if i < len(s) and s[i] == ",":
                i += 1
                continue
            if i < len(s) and s[i] == "}":
                return mapping, i + 1
            _yaml_parse_fail("flow mapping not closed")
    if s[i] == "[":
        seq: list[object] = []
        i = _yaml_skip_flow_space(s, i + 1)
        if i < len(s) and s[i] == "]":
            return seq, i + 1
        while True:
            value, i = _yaml_parse_flow(s, i)
            seq.append(value)
            i = _yaml_skip_flow_space(s, i)
            if i < len(s) and s[i] == ",":
                i += 1
                continue
            if i < len(s) and s[i] == "]":
                return seq, i + 1
            _yaml_parse_fail("flow sequence not closed")
    return _yaml_parse_plain_flow(s, i)


def _yaml_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _yaml_strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    for idx, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if idx == 0 or line[idx - 1] in " \t":
                return line[:idx].rstrip()
    return line.rstrip()


def _yaml_skip_blanks(lines: list[str], idx: int) -> int:
    while idx < len(lines):
        stripped = lines[idx].strip()
        if not stripped or stripped.startswith("#"):
            idx += 1
            continue
        break
    return idx


def _yaml_parse_block_scalar(lines: list[str], idx: int, key_indent: int) -> tuple[str, int]:
    idx += 1
    block: list[str] = []
    content_indent: int | None = None
    while idx < len(lines):
        line = lines[idx]
        if not line.strip():
            block.append("")
            idx += 1
            continue
        indent = _yaml_indent(line)
        if indent <= key_indent:
            break
        if content_indent is None:
            content_indent = indent
        block.append(line[content_indent:] if len(line) >= content_indent else "")
        idx += 1
    return "\n".join(block).rstrip("\n") + "\n", idx


def _yaml_parse_value(
    lines: list[str], idx: int, min_indent: int
) -> tuple[object, int]:
    idx = _yaml_skip_blanks(lines, idx)
    if idx >= len(lines):
        return None, idx
    line = _yaml_strip_comment(lines[idx])
    indent = _yaml_indent(line)
    if indent < min_indent:
        return None, idx
    stripped = line.strip()
    if stripped.startswith("- ") or stripped == "-":
        return _yaml_parse_seq(lines, idx, indent)
    return _yaml_parse_map(lines, idx, indent)


def _yaml_parse_map(
    lines: list[str], idx: int, map_indent: int
) -> tuple[dict[str, object], int]:
    mapping: dict[str, object] = {}
    while idx < len(lines):
        idx = _yaml_skip_blanks(lines, idx)
        if idx >= len(lines):
            break
        raw_line = lines[idx]
        line = _yaml_strip_comment(raw_line)
        if not line.strip():
            idx += 1
            continue
        indent = _yaml_indent(line)
        if indent < map_indent:
            break
        if indent > map_indent:
            cont = line.strip()
            if mapping:
                last_key = next(reversed(mapping))
                last_val = mapping[last_key]
                if isinstance(last_val, str) and not cont.startswith("- "):
                    mapping[last_key] = last_val + "\n" + cont
                    idx += 1
                    continue
            _yaml_parse_fail(f"bad indent at {line!r}")
        stripped = line.strip()
        if stripped.startswith("- "):
            break
        if ":" not in stripped:
            _yaml_parse_fail(f"expected mapping key at {stripped!r}")
        if stripped.startswith("{") or stripped.startswith("["):
            value, consumed = _yaml_parse_flow(stripped, 0)
            if not isinstance(value, dict):
                _yaml_parse_fail("expected mapping")
            for key, item in value.items():
                if key in mapping:
                    _yaml_parse_fail(f"duplicate YAML key {key!r}")
                mapping[str(key)] = item
            idx += 1
            break
        key_part, rest = stripped.split(":", 1)
        key = _yaml_parse_key(key_part)
        rest = rest.strip()
        if key in mapping:
            _yaml_parse_fail(f"duplicate YAML key {key!r}")
        if rest in ("|", "|-", "|+", ">", ">-", ">+"):
            mapping[key], idx = _yaml_parse_block_scalar(lines, idx, indent)
            continue
        if rest.startswith("{") or rest.startswith("["):
            buf = rest
            look = idx + 1
            while not _yaml_flow_is_complete(buf) and look < len(lines):
                buf += "\n" + lines[look]
                look += 1
            mapping[key], _ = _yaml_parse_flow(buf, 0)
            idx = look
            continue
        if rest == "":
            nxt = _yaml_skip_blanks(lines, idx + 1)
            if nxt < len(lines):
                nxt_line = _yaml_strip_comment(lines[nxt])
                nxt_indent = _yaml_indent(nxt_line)
                if nxt_indent > indent:
                    mapping[key], idx = _yaml_parse_value(lines, nxt, nxt_indent)
                    continue
                if nxt_indent == indent and nxt_line.strip().startswith("- "):
                    mapping[key], idx = _yaml_parse_seq(
                        lines, nxt, nxt_indent
                    )
                    continue
            mapping[key] = None
            idx += 1
            continue
        mapping[key] = _parse_yaml_scalar(rest, as_name=(key == "name"))
        idx += 1
    return mapping, idx


def _yaml_parse_seq(
    lines: list[str], idx: int, seq_indent: int
) -> tuple[list[object], int]:
    seq: list[object] = []
    while idx < len(lines):
        idx = _yaml_skip_blanks(lines, idx)
        if idx >= len(lines):
            break
        line = _yaml_strip_comment(lines[idx])
        indent = _yaml_indent(line)
        if indent < seq_indent:
            break
        stripped = line.strip()
        if not (stripped.startswith("- ") or stripped == "-"):
            break
        if indent != seq_indent:
            _yaml_parse_fail(f"bad sequence indent at {stripped!r}")
        payload = stripped[1:].strip()
        if payload == "":
            nxt = _yaml_skip_blanks(lines, idx + 1)
            if nxt < len(lines) and _yaml_indent(_yaml_strip_comment(lines[nxt])) > seq_indent:
                value, idx = _yaml_parse_value(
                    lines, nxt, _yaml_indent(_yaml_strip_comment(lines[nxt]))
                )
            else:
                value = None
                idx += 1
            seq.append(value)
            continue
        if payload.startswith("{") or payload.startswith("["):
            value, _ = _yaml_parse_flow(payload, 0)
            seq.append(value)
            idx += 1
            continue
        if ":" in payload and not payload.startswith(("'", '"')):
            nested_line = " " * (seq_indent + 2) + payload
            nested_lines = [nested_line, *lines[idx + 1 :]]
            value, consumed = _yaml_parse_map(nested_lines, 0, seq_indent + 2)
            eaten = max(consumed - 1, 0)
            idx = idx + 1 + eaten
            seq.append(value)
            continue
        seq.append(_parse_yaml_scalar(payload))
        idx += 1
    return seq, idx


def _minimal_yaml_load(text: str) -> object:
    global _YAML_ANCHORS
    _YAML_ANCHORS = {}
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = [line.replace("\t", "  ").rstrip() for line in text.splitlines()]
    idx = 0
    saw_doc = False
    while idx < len(lines):
        stripped = lines[idx].strip()
        if not stripped or stripped.startswith("#"):
            idx += 1
            continue
        if stripped == "---":
            if saw_doc:
                _yaml_parse_fail("second YAML document")
            saw_doc = True
            idx += 1
            continue
        if stripped == "...":
            _yaml_parse_fail("YAML document end marker")
        break
    if idx >= len(lines):
        return {}
    value, nxt = _yaml_parse_value(lines, idx, 0)
    nxt = _yaml_skip_blanks(lines, nxt)
    while nxt < len(lines):
        stripped = lines[nxt].strip()
        if not stripped or stripped.startswith("#"):
            nxt += 1
            continue
        if stripped == "...":
            break
        if stripped == "---":
            _yaml_parse_fail("second YAML document")
        _yaml_parse_fail(f"trailing YAML content {stripped!r}")
    return value if value is not None else {}


def _load_workflow_yaml(text: str) -> object:
    """Vendored YAML 1.2 loader (dottie-os-smoke has no PyYAML). Fail closed."""
    if text.startswith("\ufeff"):
        text = text[1:]
    try:
        return _minimal_yaml_load(text)
    except AssertionError:
        raise
    except Exception as extra:
        raise AssertionError(
            f"workflow YAML parse failed: {extra}"
        ) from extra


def _pack_guard_lookalike_token(value: object) -> bool:
    if value is None:
        return False
    text = value if isinstance(value, str) else str(value)
    if text.casefold() == PACK_GUARD_JOB.casefold():
        return True
    folded = unicodedata.normalize("NFKC", text).casefold()
    return PACK_GUARD_LOOKALIKE_RE.search(folded) is not None


def _iter_parsed_jobs(doc: object) -> list[tuple[str, object | None]]:
    if not isinstance(doc, dict):
        _yaml_parse_fail("workflow YAML is not a mapping")
    jobs = doc.get("jobs")
    if jobs is None:
        return []
    if not isinstance(jobs, dict):
        _yaml_parse_fail("jobs: is not a mapping")
    found: list[tuple[str, object | None]] = []
    for job_id, body in jobs.items():
        name: object | None = None
        if isinstance(body, dict) and "name" in body:
            name = body.get("name")
        found.append((str(job_id), name))
    return found


def _parse_yaml_scalar(raw: str, *, as_name: bool = False) -> object:
    value = _yaml_strip_comment(raw).strip()
    _yaml_refuse_tag_or_merge(
        value, what="job/step name" if as_name else "YAML scalar"
    )
    if value.startswith("*"):
        name = value[1:].strip()
        if name not in _YAML_ANCHORS:
            _yaml_parse_fail(f"unresolved YAML alias *{name}")
        return _YAML_ANCHORS[name]
    if value.startswith("&"):
        body = value[1:]
        end = 0
        while end < len(body) and body[end] not in " \t":
            end += 1
        name, rest = body[:end], body[end:].strip()
        if not name:
            _yaml_parse_fail("empty YAML anchor name")
        parsed: object = (
            _parse_yaml_scalar(rest, as_name=as_name) if rest else None
        )
        _YAML_ANCHORS[name] = parsed
        return parsed
    if value in ("true", "True", "yes", "Yes", "on"):
        return True
    if value in ("false", "False", "no", "No", "off"):
        return False
    if value.startswith(("'", '"')):
        decoded, end, had = _yaml_read_quoted(value, 0)
        if end != len(value):
            _yaml_parse_fail(f"trailing junk on quoted scalar {value!r}")
        if as_name and had:
            _yaml_parse_fail(f"escape sequence in job/step name {decoded!r}")
        return decoded
    return value


def _record_step_key(step: dict[str, object], key: str, value: object) -> None:
    if key in step:
        raise AssertionError(f"duplicate YAML key {key!r} in step")
    step[key] = value


def _parse_gha_step_lines(step_lines: list[str]) -> dict[str, object]:
    """Parse one GitHub Actions `- name:` / `- uses:` step from raw lines."""
    step: dict[str, object] = {}
    first = step_lines[0].lstrip()
    if first.startswith("- "):
        first = first[2:]
    if ":" in first:
        key, raw = first.split(":", 1)
        raw_stripped = raw.strip()
        if re.search(r"[&*]", raw_stripped):
            raise AssertionError(f"YAML anchor/alias on step key {key.strip()!r}")
        _record_step_key(step, key.strip(), _parse_yaml_scalar(raw))
    key_indent = 8
    idx = 1
    while idx < len(step_lines):
        line = step_lines[idx]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            idx += 1
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent != key_indent or ":" not in stripped:
            idx += 1
            continue
        key, raw = stripped.split(":", 1)
        raw = raw.strip()
        if re.search(r"[&*]", raw) and raw not in ("|", "|-", "|+", ">", ">-", ">+"):
            raise AssertionError(f"YAML anchor/alias on step key {key!r}")
        if raw in ("|", "|-", "|+", ">", ">-", ">+"):
            idx += 1
            block: list[str] = []
            content_indent: int | None = None
            while idx < len(step_lines):
                block_line = step_lines[idx]
                if not block_line.strip():
                    block.append("")
                    idx += 1
                    continue
                block_indent = len(block_line) - len(block_line.lstrip(" "))
                if block_indent <= key_indent:
                    break
                if content_indent is None:
                    content_indent = block_indent
                block.append(block_line[content_indent:])
                idx += 1
            text = "\n".join(block).rstrip("\n") + "\n"
            _record_step_key(step, key, text)
            continue
        if raw == "":
            nested: dict[str, object] = {}
            idx += 1
            nested_indent: int | None = None
            while idx < len(step_lines):
                nested_line = step_lines[idx]
                if not nested_line.strip() or nested_line.strip().startswith("#"):
                    idx += 1
                    continue
                nested_line_indent = len(nested_line) - len(nested_line.lstrip(" "))
                if nested_line_indent <= key_indent:
                    break
                if nested_indent is None:
                    nested_indent = nested_line_indent
                if nested_line_indent == nested_indent and ":" in nested_line:
                    nested_key, nested_raw = nested_line.strip().split(":", 1)
                    nested_key = nested_key.strip()
                    if nested_key in nested:
                        raise AssertionError(
                            f"duplicate YAML key {nested_key!r} under {key!r}"
                        )
                    nested[nested_key] = _parse_yaml_scalar(
                        _yaml_strip_comment(nested_raw)
                    )
                idx += 1
            _record_step_key(step, key, nested)
            continue
        _record_step_key(step, key, _parse_yaml_scalar(raw))
        idx += 1
    return step


def _job_line_index(lines: list[str], job: str) -> int:
    header = f"  {job}:"
    for idx, line in enumerate(lines):
        if line.rstrip() == header:
            return idx
    raise AssertionError(f"missing job {job!r} in ci.yml")


def _job_end_index(lines: list[str], start: int) -> int:
    job_header = re.compile(r"^  [A-Za-z0-9_-]+:\s*$")
    for idx in range(start + 1, len(lines)):
        if job_header.match(lines[idx]):
            return idx
    return len(lines)


def _pack_guard_step_from_text(text: str) -> dict[str, object]:
    """Stdlib extractor for the dottie-os-smoke pack-guard step."""
    lines = text.splitlines()
    job_start = _job_line_index(lines, PACK_GUARD_JOB)
    job_lines = lines[job_start : _job_end_index(lines, job_start)]
    step_at: int | None = None
    for idx, line in enumerate(job_lines):
        if line.lstrip().startswith("#"):
            continue
        if line.startswith("      - name:"):
            name = line.split(":", 1)[1].strip().strip("\"'")
            if name == PACK_GUARD_STEP_NAME:
                step_at = idx
                break
    if step_at is None:
        raise AssertionError(
            f"missing step {PACK_GUARD_STEP_NAME!r} in job {PACK_GUARD_JOB!r}"
        )
    step_lines = [job_lines[step_at]]
    for line in job_lines[step_at + 1 :]:
        if line.startswith("      - "):
            break
        if re.match(r"^  [A-Za-z0-9_-]+:\s*$", line):
            break
        step_lines.append(line)
    return _parse_gha_step_lines(step_lines)


def _pack_guard_step_from_yaml(text: str) -> dict[str, object]:
    if yaml is None:
        raise RuntimeError("PyYAML is not available")
    doc = yaml.safe_load(text)
    if not isinstance(doc, dict):
        raise AssertionError("ci.yml is not a YAML mapping")
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict):
        raise AssertionError("ci.yml has no jobs mapping")
    job = jobs.get(PACK_GUARD_JOB)
    if not isinstance(job, dict):
        raise AssertionError(f"missing job {PACK_GUARD_JOB!r}")
    steps = job.get("steps")
    if not isinstance(steps, list):
        raise AssertionError(f"job {PACK_GUARD_JOB!r} has no steps")
    for step in steps:
        if isinstance(step, dict) and step.get("name") == PACK_GUARD_STEP_NAME:
            return step
    raise AssertionError(
        f"missing step {PACK_GUARD_STEP_NAME!r} in job {PACK_GUARD_JOB!r}"
    )


def _load_pack_guard_step(text: str | None = None) -> dict[str, object]:
    raw = CI_WORKFLOW.read_text(encoding="utf-8") if text is None else text
    if yaml is not None:
        return _pack_guard_step_from_yaml(raw)
    return _pack_guard_step_from_text(raw)


def _assert_ci_yml_strict(text: str) -> None:
    """S16: reject a second YAML document and duplicate keys anywhere."""
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if idx == 0 and re.match(r"^---\s*$", line):
            continue
        if re.match(r"^---\s*$", line) or re.match(r"^\.\.\.\s*$", line):
            raise AssertionError(
                f"YAML multi-document marker at line {idx + 1}: {line!r}"
            )
    _assert_no_duplicate_yaml_keys(text)


def _assert_no_duplicate_yaml_keys(text: str) -> None:
    """Indent-stack mapping scanner; skips `|` / `>` block scalars."""
    lines = text.splitlines()
    stack: list[tuple[int, set[str]]] = [(-1, set())]
    in_block_at: int | None = None
    for line in lines:
        if in_block_at is not None:
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip(" "))
            if indent > in_block_at:
                continue
            in_block_at = None
        stripped_full = line.split("#", 1)[0].rstrip()
        if not stripped_full.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = stripped_full.strip()
        while stack and indent < stack[-1][0]:
            stack.pop()
        is_seq = stripped.startswith("- ")
        if is_seq:
            while stack and indent == stack[-1][0]:
                stack.pop()
            stack.append((indent, set()))
            rest = stripped[2:]
            if ":" in rest:
                key, raw = rest.split(":", 1)
                key = key.strip().strip("\"'")
                if key:
                    if key in stack[-1][1]:
                        raise AssertionError(f"duplicate YAML key {key!r}")
                    stack[-1][1].add(key)
                raw = raw.strip()
                if raw in ("|", "|-", "|+", ">", ">-", ">+"):
                    in_block_at = indent
            continue
        if ":" not in stripped:
            continue
        while stack and indent == stack[-1][0]:
            break
        if indent > stack[-1][0]:
            stack.append((indent, set()))
        key, raw = stripped.split(":", 1)
        key = key.strip().strip("\"'")
        if not key:
            continue
        seen = stack[-1][1]
        if key in seen:
            raise AssertionError(f"duplicate YAML key {key!r}")
        seen.add(key)
        raw = raw.strip()
        if raw in ("|", "|-", "|+", ">", ">-", ">+"):
            in_block_at = indent


def _gha_expr_norm(expr: str) -> str:
    return re.sub(r"\s+", "", expr).casefold()


def _iter_gha_exprs(text: str) -> list[str]:
    """GitHub TemplateReader: ${{ }} ends at an unquoted }}; '...' with ''."""
    found: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        start = text.find("${{", i)
        if start < 0:
            break
        j = start + 3
        in_sq = False
        while j < n:
            ch = text[j]
            if in_sq:
                if ch == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        j += 2
                        continue
                    in_sq = False
                j += 1
                continue
            if ch == "'":
                in_sq = True
                j += 1
                continue
            if ch == "}" and j + 1 < n and text[j + 1] == "}":
                found.append(text[start + 3 : j])
                i = j + 2
                break
            j += 1
        else:
            found.append(text[start + 3 :])
            break
    return found


def _gha_expr_is_forbidden(expr: str) -> bool:
    n = _gha_expr_norm(expr)
    if "secrets" in n or "github_token" in n:
        return True
    i = 0
    while True:
        j = n.find("github", i)
        if j < 0:
            return False
        if j > 0 and (n[j - 1].isalnum() or n[j - 1] == "_"):
            i = j + 6
            continue
        end = j + 6
        if end < len(n) and (n[end].isalnum() or n[end] == "_"):
            i = j + 6
            continue
        rest = n[end:]
        if j and n[j - 1] in "(,":
            return True
        if not rest or rest[0] in "[*":
            return True
        if rest.startswith(".*"):
            return True
        if rest[0] != ".":
            return True
        k = 1
        while k < len(rest) and (rest[k].isalnum() or rest[k] == "_"):
            k += 1
        prop = rest[1:k]
        if prop not in PACK_GUARD_GITHUB_SAFE:
            return True
        if k < len(rest) and rest[k] in ".[":
            return True
        i = end + k


def _workflow_body_has_forbidden_expr(body: str) -> bool:
    return any(_gha_expr_is_forbidden(expr) for expr in _iter_gha_exprs(body))


def _gha_if_is_forbidden(raw: object) -> bool:
    """`if:` is evaluated unbraced; scan the whole value as an expression."""
    if raw is None or isinstance(raw, bool):
        return False
    text = raw if isinstance(raw, str) else str(raw)
    if _gha_expr_is_forbidden(text):
        return True
    return _workflow_body_has_forbidden_expr(text)


def _local_uses_norm(raw: str) -> str:
    posix = raw.replace("\\", "/").split("@", 1)[0].strip()
    if posix.startswith("./"):
        posix = posix[2:]
    posix = posix.lstrip("/")
    return os.path.normpath(posix).replace("\\", "/")


def _gha_entry_under_dot_github(root: Path, rel: str, entry: str) -> bool:
    action_dir = (root / rel).parent
    github_root = (root / ".github").resolve()
    target = (action_dir / entry).resolve()
    try:
        target.relative_to(github_root)
    except ValueError:
        return False
    return True


def _assert_local_gha_scanned(
    uses: str, *, rel: str, root: Path, seen: set[str]
) -> None:
    norm = _local_uses_norm(uses)
    if norm != ".github" and not norm.startswith(".github/"):
        raise AssertionError(
            f"{rel} local uses {uses!r} is outside ./.github/"
        )
    if norm in seen:
        return
    seen.add(norm)
    target = root / norm
    files: list[Path] = []
    if target.is_file():
        files.append(target)
    elif target.is_dir():
        for name in ("action.yml", "action.yaml"):
            cand = target / name
            if cand.is_file():
                files.append(cand)
        if not files:
            raise AssertionError(
                f"{rel} local uses {uses!r} has no action.yml"
            )
    else:
        raise AssertionError(f"{rel} local uses {uses!r} does not exist")
    for path in files:
        body = path.read_text(encoding="utf-8")
        _assert_gha_file_surface(
            body,
            rel=str(path.relative_to(root)),
            root=root,
            seen=seen,
            require_workflow=False,
        )


def _assert_one_uses(
    uses: str,
    *,
    rel: str,
    root: Path | None = None,
    seen: set[str] | None = None,
) -> None:
    raw = uses.split("#", 1)[0].strip().strip("\"'")
    repo = REPO_ROOT if root is None else root
    visited = set() if seen is None else seen
    if raw.startswith("./") or raw.startswith(".\\"):
        _assert_local_gha_scanned(raw, rel=rel, root=repo, seen=visited)
        return
    if raw.startswith("docker://"):
        raise AssertionError(f"{rel} refuses docker:// actions {raw!r}")
    owner_repo = raw.split("@", 1)[0]
    if owner_repo != owner_repo.casefold():
        raise AssertionError(f"{rel} mixed-case uses {raw!r}")
    lower = raw.casefold()
    if "github-script" in lower:
        raise AssertionError(f"{rel} refuses actions/github-script")
    if "/.github/workflows/" in lower:
        raise AssertionError(
            f"{rel} external reusable workflow {raw!r}"
        )
    if not PACK_GUARD_USES_PIN_RE.fullmatch(raw):
        raise AssertionError(
            f"{rel} uses {raw!r} is not pinned to a 40-hex sha"
        )
    if raw not in PACK_GUARD_ALLOWED_USES:
        raise AssertionError(f"{rel} uses {raw!r} is not allowlisted")


def _assert_uses_pinned_and_allowlisted(
    text: str, repo_root: Path | None = None
) -> None:
    """S24/S25: every uses: in every workflow file is a 40-hex pin."""
    root = REPO_ROOT if repo_root is None else repo_root
    found = False
    for path in _workflow_yaml_paths(root):
        rel = str(path.relative_to(root))
        body = (
            text
            if path.name == "ci.yml" and path.parent.name == "workflows"
            else path.read_text(encoding="utf-8")
        )
        for match in PACK_GUARD_USES_LINE_RE.finditer(body):
            found = True
            _assert_one_uses(match.group(1), rel=rel, root=root)
    if not found:
        raise AssertionError("workflows have no uses: actions")


def _assert_tests_do_not_write_runner_env(repo_root: Path | None = None) -> None:
    """PR test code must not write GITHUB_ENV / GITHUB_PATH / BASH_ENV."""
    root = REPO_ROOT if repo_root is None else repo_root
    tests = root / "apps" / "dottie-os" / "tests"
    skip = {"test_ultradata_factory.py"}
    skip.update(path.name for path in tests.glob("test_critic_*.py"))
    for path in sorted(tests.glob("test_*.py")):
        if path.name in skip:
            continue
        raw = path.read_text(encoding="utf-8")
        if re.search(r"GITHUB_ENV|GITHUB_PATH|BASH_ENV", raw):
            raise AssertionError(
                f"{path.name} writes GITHUB_ENV/GITHUB_PATH/BASH_ENV; "
                "pack-guard must not share a job with PR-controlled tests"
            )


def _workflow_top_level_keys(text: str) -> list[str]:
    keys: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[0] in " \t" or ":" not in line:
            continue
        keys.append(line.split(":", 1)[0].strip().strip("\"'"))
    if len(keys) != len(set(keys)):
        raise AssertionError(f"duplicate top-level YAML keys: {keys}")
    return keys


def _workflow_on_block(text: str) -> str:
    lines = text.splitlines(keepends=True)
    start: int | None = None
    for idx, line in enumerate(lines):
        if line[:1] in " \t#" or ":" not in line:
            continue
        if line.split(":", 1)[0].strip() == "on":
            start = idx
            break
    if start is None:
        raise AssertionError("ci.yml has no top-level on:")
    end = len(lines)
    for idx in range(start + 1, len(lines)):
        line = lines[idx]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] not in " \t":
            end = idx
            break
    return "".join(lines[start:end]).rstrip("\n") + "\n"


def _workflow_yaml_paths(repo_root: Path) -> list[Path]:
    wf_dir = repo_root / ".github" / "workflows"
    if not wf_dir.is_dir():
        return []
    return sorted(
        path
        for path in wf_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".yml", ".yaml"}
    )


def _assert_workflow_job_unique(
    job: str, repo_root: Path | None = None
) -> None:
    root = REPO_ROOT if repo_root is None else repo_root
    ci_rel = str(Path(".github") / "workflows" / "ci.yml")
    hits: list[str] = []
    for path in _workflow_yaml_paths(root):
        rel = str(path.relative_to(root))
        doc = _load_workflow_yaml(path.read_text(encoding="utf-8"))
        for job_id, _name in _iter_parsed_jobs(doc):
            if job_id == job:
                hits.append(rel)
    expected = [ci_rel]
    if hits != expected:
        raise AssertionError(
            f"{job!r} job name must appear only in ci.yml, found {hits}"
        )


def _assert_pack_guard_check_name_unique(
    text: str, repo_root: Path | None = None
) -> None:
    """B4: YAML-parse every workflow; refuse spoofed pack-guard check names."""
    root = REPO_ROOT if repo_root is None else repo_root
    ci_rel = str(Path(".github") / "workflows" / "ci.yml")
    allowed: tuple[str, str] | None = None
    spoofs: list[str] = []
    wf_dir = root / ".github" / "workflows"
    paths = (
        sorted(
            path
            for path in wf_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".yml", ".yaml"}
        )
        if wf_dir.is_dir()
        else []
    )
    for path in paths:
        rel = str(path.relative_to(root))
        body = text if rel == ci_rel else path.read_text(encoding="utf-8")
        doc = _load_workflow_yaml(body)
        jobs_map = doc.get("jobs") if isinstance(doc, dict) else None
        for job_id, name in _iter_parsed_jobs(doc):
            id_hit = _pack_guard_lookalike_token(job_id)
            name_hit = name is not None and _pack_guard_lookalike_token(name)
            if name is not None and "${{" in str(name):
                spoofs.append(f"{rel} job {job_id!r} name has ${{{{")
            if id_hit:
                if rel == ci_rel and job_id == PACK_GUARD_JOB:
                    if allowed is not None:
                        spoofs.append(f"duplicate ci.yml job id {job_id!r}")
                    allowed = (rel, job_id)
                else:
                    spoofs.append(f"{rel} job id {job_id!r}")
            if name_hit:
                spoofs.append(f"{rel} job {job_id!r} name {name!r}")
        if isinstance(jobs_map, dict):
            for job_id, job_body in jobs_map.items():
                if not isinstance(job_body, dict):
                    continue
                steps = job_body.get("steps")
                if not isinstance(steps, list):
                    continue
                for step in steps:
                    if not isinstance(step, dict) or "name" not in step:
                        continue
                    step_name = step.get("name")
                    if step_name is not None and (
                        _pack_guard_lookalike_token(step_name)
                        or "${{" in str(step_name)
                    ):
                        spoofs.append(
                            f"{rel} job {job_id!r} step name {step_name!r}"
                        )
    if allowed is None:
        raise AssertionError(
            f"missing the single ci.yml job id {PACK_GUARD_JOB!r}"
        )
    if spoofs:
        raise AssertionError(
            "pack-guard check name is spoofable; refuse "
            f"{spoofs}"
        )


def _assert_pack_guard_names_unique(repo_root: Path | None = None) -> None:
    root = REPO_ROOT if repo_root is None else repo_root
    step_re = re.compile(
        rf"^\s+- name:\s*{re.escape(PACK_GUARD_STEP_NAME)}\s*$",
        re.MULTILINE,
    )
    step_hits: list[str] = []
    paths = _workflow_yaml_paths(root)
    for path in paths:
        text = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(root))
        step_hits.extend([rel] * len(step_re.findall(text)))
    expected = [str(Path(".github") / "workflows" / "ci.yml")]
    _assert_workflow_job_unique(PACK_GUARD_JOB, root)
    _assert_workflow_job_unique(DOTTIE_OS_SMOKE_JOB, root)
    if step_hits != expected:
        raise AssertionError(
            f"{PACK_GUARD_STEP_NAME!r} step must appear only in ci.yml, "
            f"found {step_hits}"
        )


def _job_keys_from_text(text: str, job: str | None = None) -> set[str]:
    lines = text.splitlines()
    start = _job_line_index(lines, PACK_GUARD_JOB if job is None else job)
    end = _job_end_index(lines, start)
    keys: list[str] = []
    for line in lines[start + 1 : end]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 4 and ":" in stripped:
            keys.append(stripped.split(":", 1)[0].strip().strip("\"'"))
    if len(keys) != len(set(keys)):
        raise AssertionError(f"duplicate job keys {keys} in {job or PACK_GUARD_JOB!r}")
    return set(keys)


def _job_step_blocks_from_text(
    text: str, job: str | None = None
) -> list[list[str]]:
    lines = text.splitlines()
    start = _job_line_index(lines, PACK_GUARD_JOB if job is None else job)
    job_lines = lines[start : _job_end_index(lines, start)]
    blocks: list[list[str]] = []
    idx = 0
    while idx < len(job_lines):
        line = job_lines[idx]
        if line.startswith("      - "):
            block = [line]
            idx += 1
            while idx < len(job_lines):
                nxt = job_lines[idx]
                if nxt.startswith("      - "):
                    break
                if re.match(r"^  [A-Za-z0-9_-]+:\s*$", nxt):
                    break
                nxt_stripped = nxt.strip()
                nxt_indent = len(nxt) - len(nxt.lstrip(" "))
                if (
                    nxt_indent == 4
                    and nxt_stripped
                    and not nxt_stripped.startswith("#")
                    and ":" in nxt_stripped
                ):
                    break
                block.append(nxt)
                idx += 1
            blocks.append(block)
            continue
        idx += 1
    return blocks


def _step_env_keys(step: dict[str, object]) -> set[str]:
    env = step.get("env")
    if isinstance(env, dict):
        return {str(key) for key in env}
    if not isinstance(env, str) or not env:
        return set()
    found: set[str] = set()
    for key in PACK_GUARD_GIT_ENV_KEYS:
        if key in env:
            found.add(key)
    return found


def _assert_job_keys_exact(text: str, job: str) -> None:
    job_keys = _job_keys_from_text(text, job=job)
    if job_keys != PACK_GUARD_JOB_KEYS:
        raise AssertionError(
            f"job {job!r} keys {sorted(job_keys)} != "
            f"{sorted(PACK_GUARD_JOB_KEYS)}"
        )


def _assert_smoke_job_has_no_hollowing_steps(text: str) -> None:
    """Part A still mutates dottie-os-smoke; keep those edits red."""
    blocks = _job_step_blocks_from_text(text, job=DOTTIE_OS_SMOKE_JOB)
    for block in blocks:
        step = _parse_gha_step_lines(block)
        run = step.get("run")
        run_text = run if isinstance(run, str) else ""
        blob = "\n".join(block)
        hit = PACK_GUARD_EARLIER_BAN_RE.search(f"{run_text}\n{blob}")
        if hit is not None:
            raise AssertionError(
                f"dottie-os-smoke step {step.get('name')!r} is banned: "
                f"{hit.group(0)!r}"
            )
        bad_env = _step_env_keys(step) & PACK_GUARD_GIT_ENV_KEYS
        if bad_env:
            raise AssertionError(
                f"dottie-os-smoke step {step.get('name')!r} sets "
                f"{sorted(bad_env)} in env"
            )
        uses = str(step.get("uses") or "")
        if uses.startswith("actions/checkout"):
            with_ = step.get("with")
            if not isinstance(with_, dict):
                raise AssertionError(
                    "dottie-os-smoke actions/checkout must set "
                    "persist-credentials: false"
                )
            if with_.get("persist-credentials") is not False:
                raise AssertionError(
                    "dottie-os-smoke actions/checkout must set "
                    "persist-credentials: false"
                )
            banned = {"ref", "path", "sparse-checkout"} & set(with_)
            if banned:
                raise AssertionError(
                    "dottie-os-smoke actions/checkout must not set "
                    f"{sorted(banned)}"
                )


def _workflow_permissions_block(text: str) -> str:
    lines = text.splitlines(keepends=True)
    start: int | None = None
    for idx, line in enumerate(lines):
        if line[:1] in " \t#" or ":" not in line:
            continue
        if line.split(":", 1)[0].strip() == "permissions":
            start = idx
            break
    if start is None:
        raise AssertionError("workflow has no top-level permissions:")
    end = len(lines)
    for idx in range(start + 1, len(lines)):
        line = lines[idx]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] not in " \t":
            end = idx
            break
    return "".join(lines[start:end]).rstrip("\n") + "\n"


def _permissions_has_write(value: object) -> bool:
    if isinstance(value, str):
        return "write" in value.casefold()
    if isinstance(value, dict):
        return any(
            "write" in str(item).casefold() for item in value.values()
        )
    return False


def _on_has_forbidden_trigger(on_value: object) -> bool:
    names: list[str] = []
    if on_value is None or isinstance(on_value, bool):
        return True
    if isinstance(on_value, str):
        names = [on_value]
    elif isinstance(on_value, list):
        for item in on_value:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                names.extend(str(key) for key in item)
    elif isinstance(on_value, dict):
        names = [str(key) for key in on_value]
    else:
        return True
    if not names:
        return True
    return any(
        name.casefold() not in PACK_GUARD_ALLOWED_TRIGGERS for name in names
    )


def _dump_strings(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_dump_strings(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(
            f"{key}\n{_dump_strings(item)}" for key, item in value.items()
        )
    return "" if value is None else str(value)


def _assert_step_attack_surface(
    step: object,
    *,
    rel: str,
    job_id: str,
    root: Path,
    seen: set[str],
) -> None:
    if not isinstance(step, dict):
        return
    uses = str(step.get("uses") or "")
    if uses:
        _assert_one_uses(uses, rel=rel, root=root, seen=seen)
    if _gha_if_is_forbidden(step.get("if")):
        raise AssertionError(
            f"{rel} job {job_id!r} if: mentions secrets or github.token"
        )
    uses_fold = uses.casefold()
    with_ = step.get("with")
    if "checkout" in uses_fold:
        if not isinstance(with_, dict) or with_.get(
            "persist-credentials"
        ) is not False:
            raise AssertionError(
                f"{rel} job {job_id!r} checkout must set "
                "persist-credentials: false"
            )
    blob = _dump_strings(step)
    if PACK_GUARD_CLONE_TOKEN_RE.search(blob):
        raise AssertionError(f"{rel} job {job_id!r} embeds a token in a URL")
    if PACK_GUARD_API_POST_RE.search(blob):
        raise AssertionError(
            f"{rel} job {job_id!r} posts statuses/check runs or uses "
            "github-script/gh/curl against the GitHub API"
        )


def _assert_gha_file_surface(
    body: str,
    *,
    rel: str,
    root: Path,
    seen: set[str],
    require_workflow: bool,
) -> None:
    """S24: file-wide expr + trigger allowlist + uses, every GHA YAML file."""
    if _workflow_body_has_forbidden_expr(body):
        raise AssertionError(
            f"{rel} ${{{{ }}}} expression mentions secrets or github.token"
        )
    if PACK_GUARD_SECRETS_INHERIT_RE.search(body):
        raise AssertionError(f"{rel} forbids secrets: inherit")
    doc = _load_workflow_yaml(body)
    if not isinstance(doc, dict):
        raise AssertionError(f"{rel} is not a YAML mapping")
    if _workflow_body_has_forbidden_expr(_dump_strings(doc)):
        raise AssertionError(
            f"{rel} parsed YAML ${{{{ }}}} mentions secrets or github.token"
        )
    on_value = None
    for key, value in doc.items():
        if str(key).casefold() == "on":
            on_value = value
            break
    if require_workflow and _on_has_forbidden_trigger(on_value):
        raise AssertionError(
            f"{rel} on: must be push, pull_request, schedule, "
            "or workflow_dispatch"
        )
    if require_workflow:
        top_perm = doc.get("permissions")
        if top_perm is None or _permissions_has_write(top_perm):
            raise AssertionError(
                f"{rel} must set read-only top-level permissions"
            )
    jobs = doc.get("jobs")
    if isinstance(jobs, dict):
        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                continue
            job_keys = {str(key) for key in job}
            if any(key != key.casefold() for key in job_keys):
                bad = sorted(k for k in job_keys if k != k.casefold())
                if any(k.casefold() in PACK_GUARD_GHA_KEYS for k in bad):
                    raise AssertionError(
                        f"{rel} job {job_id!r} mixed-case keys {bad}"
                    )
            if "permissions" in job and _permissions_has_write(
                job.get("permissions")
            ):
                raise AssertionError(
                    f"{rel} job {job_id!r} widens permissions"
                )
            secrets = job.get("secrets")
            if secrets == "inherit" or secrets is True:
                raise AssertionError(
                    f"{rel} job {job_id!r} forbids secrets: inherit"
                )
            if _gha_if_is_forbidden(job.get("if")):
                raise AssertionError(
                    f"{rel} job {job_id!r} if: mentions secrets or github.token"
                )
            job_uses = str(job.get("uses") or "")
            if job_uses:
                _assert_one_uses(
                    job_uses, rel=rel, root=root, seen=seen
                )
            steps = job.get("steps")
            if not isinstance(steps, list):
                continue
            for step in steps:
                _assert_step_attack_surface(
                    step,
                    rel=rel,
                    job_id=str(job_id),
                    root=root,
                    seen=seen,
                )
    runs = doc.get("runs")
    if isinstance(runs, dict):
        using = str(runs.get("using") or "").casefold()
        if using == "docker":
            image = str(runs.get("image") or "").strip()
            if not PACK_GUARD_DOCKER_DIGEST_RE.fullmatch(image.casefold()):
                raise AssertionError(
                    f"{rel} docker action image must be digest-pinned, "
                    f"got {image!r}"
                )
        if using.startswith("node"):
            for key in ("main", "pre", "post"):
                entry = runs.get(key)
                if not entry:
                    continue
                if not _gha_entry_under_dot_github(root, rel, str(entry)):
                    raise AssertionError(
                        f"{rel} {key}: {entry!r} resolves outside .github/"
                    )
        steps = runs.get("steps")
        if isinstance(steps, list):
            for step in steps:
                _assert_step_attack_surface(
                    step,
                    rel=rel,
                    job_id="runs",
                    root=root,
                    seen=seen,
                )


def _assert_workflow_attack_surface(
    body: str, *, rel: str, root: Path | None = None
) -> None:
    """S24: every workflow file, not just ci.yml."""
    _assert_gha_file_surface(
        body,
        rel=rel,
        root=REPO_ROOT if root is None else root,
        seen=set(),
        require_workflow=True,
    )


def _assert_read_only_token_and_checkouts(
    text: str, repo_root: Path | None = None
) -> None:
    """B4b/S24: contents: read; no job write; drop GITHUB_TOKEN; all workflows."""
    root = REPO_ROOT if repo_root is None else repo_root
    if _workflow_permissions_block(text) != PACK_GUARD_PERMISSIONS_BLOCK:
        raise AssertionError(
            "ci.yml top-level permissions: must be exactly "
            f"{PACK_GUARD_PERMISSIONS_BLOCK!r}"
        )
    _assert_uses_pinned_and_allowlisted(text, root)
    for path in _workflow_yaml_paths(root):
        rel = str(path.relative_to(root))
        body = (
            text
            if path.name == "ci.yml" and path.parent.name == "workflows"
            else path.read_text(encoding="utf-8")
        )
        _assert_workflow_attack_surface(body, rel=rel, root=root)


def _assert_pack_guard_context(text: str) -> dict[str, object]:
    """S4/S6/S7/S8/S16/S17: pack-guard allowlists, unique names, pinned uses."""
    _assert_ci_yml_strict(text)
    top_keys = _workflow_top_level_keys(text)
    if set(top_keys) != PACK_GUARD_WORKFLOW_KEYS:
        raise AssertionError(
            f"workflow keys {top_keys} != {sorted(PACK_GUARD_WORKFLOW_KEYS)}"
        )
    on_block = _workflow_on_block(text)
    if on_block != PACK_GUARD_ON_BLOCK:
        raise AssertionError(
            "workflow on: must equal main's trigger block; "
            f"got {on_block!r}"
        )
    _assert_read_only_token_and_checkouts(text)
    _assert_pack_guard_names_unique()
    _assert_pack_guard_check_name_unique(text)
    _assert_uses_pinned_and_allowlisted(text)
    _assert_tests_do_not_write_runner_env()
    _assert_job_keys_exact(text, PACK_GUARD_JOB)
    pack_keys = _job_keys_from_text(text, job=PACK_GUARD_JOB)
    banned = pack_keys & PACK_GUARD_JOB_FORBIDDEN_KEYS
    if banned:
        raise AssertionError(
            f"pack-guard job has forbidden keys {sorted(banned)} "
            "(no if:/continue-on-error/needs:/strategy/name:)"
        )
    pack_doc = _load_workflow_yaml(text)
    if not isinstance(pack_doc, dict):
        raise AssertionError("ci.yml is not a YAML mapping")
    pack_jobs = pack_doc.get("jobs")
    if not isinstance(pack_jobs, dict):
        raise AssertionError("ci.yml jobs: is not a mapping")
    pack_job = pack_jobs.get(PACK_GUARD_JOB)
    if not isinstance(pack_job, dict):
        raise AssertionError(f"missing job {PACK_GUARD_JOB!r}")
    if pack_job.get("runs-on") != PACK_GUARD_RUNS_ON:
        raise AssertionError(
            f"pack-guard runs-on must be {PACK_GUARD_RUNS_ON!r}, "
            f"got {pack_job.get('runs-on')!r}"
        )
    _assert_job_keys_exact(text, DOTTIE_OS_SMOKE_JOB)
    _assert_smoke_job_has_no_hollowing_steps(text)
    blocks = _job_step_blocks_from_text(text)
    if len(blocks) != 2:
        raise AssertionError(
            f"job {PACK_GUARD_JOB!r} must have exactly 2 steps "
            f"(pinned checkout, then the guard); got {len(blocks)}"
        )
    steps = [_parse_gha_step_lines(block) for block in blocks]
    checkout, guard = steps[0], steps[1]
    if set(checkout) != PACK_GUARD_CHECKOUT_KEYS:
        raise AssertionError(
            f"pack-guard checkout keys {sorted(checkout)} != "
            f"{sorted(PACK_GUARD_CHECKOUT_KEYS)}"
        )
    uses = str(checkout.get("uses") or "")
    if not PACK_GUARD_CHECKOUT_USES_RE.fullmatch(uses):
        raise AssertionError(
            "pack-guard actions/checkout must be pinned to a 40-hex sha; "
            f"got {uses!r}"
        )
    if uses != PACK_GUARD_CHECKOUT_PIN:
        raise AssertionError(
            f"pack-guard checkout uses {uses!r} != {PACK_GUARD_CHECKOUT_PIN!r}"
        )
    with_ = checkout.get("with")
    if with_ != PACK_GUARD_CHECKOUT_WITH:
        raise AssertionError(
            "pack-guard checkout with: must be exactly "
            f"{PACK_GUARD_CHECKOUT_WITH} and nothing else; got {with_!r}"
        )
    if guard.get("name") != PACK_GUARD_STEP_NAME:
        raise AssertionError(
            f"first step after checkout must be {PACK_GUARD_STEP_NAME!r}, "
            f"got {guard.get('name')!r}"
        )
    if set(guard) != PACK_GUARD_STEP_KEYS:
        raise AssertionError(
            f"pack-guard step keys {sorted(guard)} != "
            f"{sorted(PACK_GUARD_STEP_KEYS)}"
        )
    shell = str(guard.get("shell") or "")
    if PACK_GUARD_SHELL_EUO not in shell:
        raise AssertionError(
            "pack-guard shell must include -euo pipefail "
            f"(bash --noprofile --norc -euo pipefail); got {shell!r}"
        )
    if "--noprofile" not in shell or "--norc" not in shell:
        raise AssertionError(
            "pack-guard shell must include --noprofile --norc; "
            f"got {shell!r}"
        )
    if guard.get("shell") != PACK_GUARD_SHELL:
        raise AssertionError(
            f"pack-guard shell {guard.get('shell')!r} != {PACK_GUARD_SHELL!r}"
        )
    run_text = str(guard.get("run") or "")
    if f"PATH={PACK_GUARD_ENV_PATH}" not in run_text:
        raise AssertionError(
            f"pack-guard PATH must be exactly {PACK_GUARD_ENV_PATH!r}"
        )
    if f"HOME={PACK_GUARD_ENV_HOME}" not in run_text:
        raise AssertionError(
            f"pack-guard HOME must be exactly {PACK_GUARD_ENV_HOME!r}"
        )
    if f"LC_ALL={PACK_GUARD_ENV_LC_ALL} " not in run_text:
        raise AssertionError(
            f"pack-guard LC_ALL must be exactly {PACK_GUARD_ENV_LC_ALL!r}"
        )
    if PACK_GUARD_ENV_SCRUB_RE.search(run_text) is None:
        raise AssertionError(
            "pack-guard git_scrub env pin must be "
            f"PATH={PACK_GUARD_ENV_PATH} HOME={PACK_GUARD_ENV_HOME} "
            f"LC_ALL={PACK_GUARD_ENV_LC_ALL}"
        )
    if PACK_GUARD_ENV_INLINE not in run_text:
        raise AssertionError(
            "pack-guard env -i pin must be "
            f"{PACK_GUARD_ENV_INLINE}"
        )
    if "LC_ALL=C.UTF-8" in run_text:
        raise AssertionError("pack-guard LC_ALL=C.UTF-8 is forbidden")
    if 'HOME="$HOME"' in run_text or "HOME=$HOME" in run_text:
        raise AssertionError("pack-guard must not keep the runner HOME")
    if PACK_GUARD_GREP_RE not in run_text:
        raise AssertionError(
            f"pack-guard path match must include {PACK_GUARD_GREP_RE!r}"
        )
    if PACK_GUARD_PATH_RE not in run_text:
        raise AssertionError(
            f"pack-guard path match must include {PACK_GUARD_PATH_RE!r}"
        )
    scrub_m = re.search(r"git_scrub\(\) \{\n(.*?)\n\s*\}", run_text, re.S)
    if scrub_m is None:
        raise AssertionError("pack-guard missing git_scrub function")
    scrub = scrub_m.group(1)
    for pin in (
        "/usr/bin/env -i",
        f"PATH={PACK_GUARD_ENV_PATH}",
        f"HOME={PACK_GUARD_ENV_HOME}",
        f"LC_ALL={PACK_GUARD_ENV_LC_ALL} ",
        "GIT_CONFIG_NOSYSTEM=1",
        "GIT_CONFIG_GLOBAL=/dev/null",
        "GIT_NO_REPLACE_OBJECTS=1",
        "--no-replace-objects",
        "core.fsmonitor=false",
        "core.untrackedCache=false",
        "core.hooksPath=/dev/null",
        "core.quotePath=false",
    ):
        if pin not in scrub:
            raise AssertionError(f"git_scrub must pin {pin!r}")
    return guard


def _pack_guard_git_env() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_") and key != "GITHUB_SHA"
    }
    env.update(
        {
            "GIT_AUTHOR_NAME": "pack-guard-test",
            "GIT_AUTHOR_EMAIL": "pack-guard-test@example.com",
            "GIT_COMMITTER_NAME": "pack-guard-test",
            "GIT_COMMITTER_EMAIL": "pack-guard-test@example.com",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
        }
    )
    return env


def _init_pack_guard_repo(repo: Path) -> dict[str, str]:
    repo.mkdir(parents=True, exist_ok=True)
    env = _pack_guard_git_env()
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        ["git", "config", "user.name", "pack-guard-test"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        ["git", "config", "user.email", "pack-guard-test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )
    return env


def _commit_pack_guard_paths(
    repo: Path, env: dict[str, str], rel_paths: list[str], message: str
) -> None:
    subprocess.run(
        ["git", "add", "-f", "--", *rel_paths],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )


def _seed_pack_guard_floor(repo: Path) -> None:
    """Plant ci.yml plus filler so a temp repo meets PACK_GUARD_LS_FILES_FLOOR."""
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.parent.mkdir(parents=True, exist_ok=True)
    if not ci.exists():
        ci.write_text("name: CI\n", encoding="utf-8")
    floor_dir = repo / "_pack_guard_floor"
    floor_dir.mkdir(exist_ok=True)
    need = PACK_GUARD_LS_FILES_FLOOR - 1
    for idx in range(need):
        (floor_dir / f"{idx:04d}").write_text(".\n", encoding="utf-8")


def _commit_pack_guard_tree(repo: Path, env: dict[str, str], message: str) -> None:
    subprocess.run(
        ["git", "add", "-f", "-A"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )


def _head_blob_sizes(repo: Path) -> list[tuple[int, str]]:
    """HEAD blob sizes from `git ls-tree -r -l` (skips gitlinks)."""
    proc = subprocess.run(
        ["git", "ls-tree", "-r", "-l", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=_pack_guard_git_env(),
    )
    rows: list[tuple[int, str]] = []
    for line in proc.stdout.splitlines():
        meta, path = line.split("\t", 1)
        parts = meta.split()
        if len(parts) < 4 or parts[3] == "-":
            continue
        rows.append((int(parts[3]), path))
    return rows


def _jsonl_parent_dir(path: str) -> str | None:
    folded = path.casefold()
    if not (
        folded.endswith((".jsonl", ".ndjson", ".gz"))
        or ".jsonl." in folded
        or ".ndjson." in folded
    ):
        return None
    return path[: path.rfind("/")] if "/" in path else ""


def _run_pack_guard_script(
    repo: Path,
    run_script: str,
    env: dict[str, str],
    *,
    pin_github_sha: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = dict(env)
    if pin_github_sha and "GITHUB_SHA" not in env:
        pin = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            env=_pack_guard_git_env(),
            capture_output=True,
            text=True,
        )
        if pin.returncode == 0:
            env["GITHUB_SHA"] = pin.stdout.strip()
    return subprocess.run(
        ["bash", "-c", run_script],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


class TrackedPackArtifactGuardTests(unittest.TestCase):
    """CI pack-guard job is the real extracted step, executed with bash."""

    def _run_block(self, text: str | None = None) -> str:
        raw = CI_WORKFLOW.read_text(encoding="utf-8") if text is None else text
        context_step = _assert_pack_guard_context(raw)
        step = _load_pack_guard_step(raw)
        self.assertEqual(set(context_step), PACK_GUARD_STEP_KEYS)
        self.assertEqual(set(step), PACK_GUARD_STEP_KEYS)
        self.assertNotIn("if", step, "pack-guard step must not have if:")
        self.assertNotIn(
            "continue-on-error",
            step,
            "pack-guard step must not set continue-on-error",
        )
        run = step.get("run")
        self.assertIsInstance(run, str)
        self.assertTrue(str(run).strip(), "pack-guard step has an empty run: block")
        return str(run)

    def test_ci_pack_guard_step_is_unconditional(self) -> None:
        text = CI_WORKFLOW.read_text(encoding="utf-8")
        context_step = _assert_pack_guard_context(text)
        step = _load_pack_guard_step(text)
        self.assertEqual(set(context_step), PACK_GUARD_STEP_KEYS)
        self.assertEqual(set(step), PACK_GUARD_STEP_KEYS)
        self.assertEqual(step.get("name"), PACK_GUARD_STEP_NAME)
        self.assertNotIn("if", step)
        self.assertNotIn("continue-on-error", step)
        self.assertEqual(step.get("shell"), PACK_GUARD_SHELL)
        self.assertIn(PACK_GUARD_SHELL_EUO, str(step.get("shell")))
        self.assertIn("--noprofile", str(step.get("shell")))
        self.assertIn("--norc", str(step.get("shell")))
        self.assertNotIn("if", _job_keys_from_text(text))
        self.assertNotIn("continue-on-error", _job_keys_from_text(text))
        self.assertNotIn("needs", _job_keys_from_text(text))
        self.assertNotIn("strategy", _job_keys_from_text(text))
        self.assertNotIn("name", _job_keys_from_text(text))
        self.assertNotIn("working-directory", step)
        self.assertNotIn("env", step)
        self.assertIsInstance(step.get("run"), str)
        self.assertEqual(_job_keys_from_text(text), PACK_GUARD_JOB_KEYS)
        self.assertEqual(
            _job_keys_from_text(text, job=DOTTIE_OS_SMOKE_JOB),
            PACK_GUARD_JOB_KEYS,
        )
        self.assertEqual(
            set(_workflow_top_level_keys(text)), PACK_GUARD_WORKFLOW_KEYS
        )
        self.assertEqual(_workflow_on_block(text), PACK_GUARD_ON_BLOCK)
        self.assertIn(f"PACK_GUARD_LS_FILES_FLOOR={PACK_GUARD_LS_FILES_FLOOR}", str(step.get("run")))
        self.assertIn("/usr/bin/git", str(step.get("run")))
        self.assertIn("/usr/bin/python3 -I -c", str(step.get("run")))
        run_text = str(step.get("run"))
        self.assertIn(f"PATH={PACK_GUARD_ENV_PATH}", run_text)
        self.assertIn(f"HOME={PACK_GUARD_ENV_HOME}", run_text)
        self.assertIn(f"LC_ALL={PACK_GUARD_ENV_LC_ALL} ", run_text)
        self.assertIn(PACK_GUARD_ENV_INLINE, run_text)
        self.assertRegex(run_text, PACK_GUARD_ENV_SCRUB_RE)
        self.assertNotIn("LC_ALL=C.UTF-8", run_text)
        self.assertNotIn('HOME="$HOME"', run_text)
        self.assertNotIn("HOME=$HOME", run_text)
        self.assertIn(PACK_GUARD_PATH_RE, run_text)
        self.assertIn(PACK_GUARD_GREP_RE, run_text)
        self.assertIn("git_scrub ls-files -z", run_text)
        self.assertIn(
            'ls-tree -r -z --full-tree --name-only "$GITHUB_SHA"', run_text
        )
        self.assertNotIn("merge-base", run_text)
        self.assertNotIn("git diff ", run_text)
        self.assertNotIn("git diff-tree", run_text)
        self.assertIn('cat-file -t "$GITHUB_SHA"', run_text)
        self.assertNotIn("^{commit}", run_text)
        self.assertIn("GIT_NO_REPLACE_OBJECTS=1", run_text)
        self.assertIn("--no-replace-objects", run_text)
        self.assertIn("core.fsmonitor=false", run_text)
        self.assertIn("core.hooksPath=/dev/null", run_text)
        self.assertIn("/usr/bin/env -i", run_text)
        self.assertNotIn("ls-tree -r --name-only -z HEAD", run_text)
        stdlib_step = _pack_guard_step_from_text(text)
        self.assertEqual(set(stdlib_step), PACK_GUARD_STEP_KEYS)
        self.assertEqual(stdlib_step.get("name"), step.get("name"))
        self.assertEqual(stdlib_step.get("run"), step.get("run"))
        self.assertEqual("if" in stdlib_step, "if" in step)
        self.assertEqual(
            "continue-on-error" in stdlib_step, "continue-on-error" in step
        )
        if yaml is not None:
            doc = yaml.safe_load(text)
            self.assertIsInstance(doc, dict)
            self.assertNotIn("defaults", doc)
            jobs = doc.get("jobs")
            self.assertIsInstance(jobs, dict)
            job = jobs.get(PACK_GUARD_JOB)
            self.assertIsInstance(job, dict)
            self.assertEqual(set(job), PACK_GUARD_JOB_KEYS)
            self.assertEqual(job.get("runs-on"), PACK_GUARD_RUNS_ON)

    def test_codeowners_cover_github_and_guard_tests(self) -> None:
        path = REPO_ROOT / ".github" / "CODEOWNERS"
        raw = path.read_text(encoding="utf-8")
        owned = [
            line.split()[0]
            for line in raw.splitlines()
            if line.strip() and not line.startswith("#")
        ]
        self.assertIn(PACK_GUARD_CODEOWNERS_GITHUB, owned)
        self.assertIn(PACK_GUARD_CODEOWNERS_TESTS, owned)
        self.assertIn(PACK_GUARD_CODEOWNERS_FACTORY, raw)
        self.assertIn(PACK_GUARD_CODEOWNERS_CRITIC, raw)
        for required in (
            PACK_GUARD_CODEOWNERS_GITHUB,
            PACK_GUARD_CODEOWNERS_TESTS,
            PACK_GUARD_CODEOWNERS_FACTORY,
            PACK_GUARD_CODEOWNERS_CRITIC,
        ):
            for line in raw.splitlines():
                if line.strip().startswith("#") or not line.strip():
                    continue
                parts = line.split()
                if parts[0] == required:
                    self.assertIn(PACK_GUARD_CODEOWNERS_OWNER, parts)
                    break
            else:
                self.fail(f"CODEOWNERS missing {required} @jcdavis131")

    def test_pack_guard_check_name_spoofs_are_red(self) -> None:
        """B4/S20: YAML uniqueness refuses spoofed required-check names."""
        text = CI_WORKFLOW.read_text(encoding="utf-8")
        spoofs = (
            (
                "4space",
                "zz-spoof.yml",
                "name: x\non:\n    pull_request:\n        branches: [main]\n"
                "jobs:\n    pack-guard:\n        runs-on: ubuntu-latest\n"
                "        steps:\n            - run: echo ok\n",
            ),
            (
                "flow",
                "zz-spoof.yml",
                "name: x\non: [pull_request]\n"
                "jobs: {pack-guard: {runs-on: ubuntu-latest, "
                "steps: [{run: echo ok}]}}\n",
            ),
            (
                "Pack-Guard",
                "zz-spoof.yml",
                "name: x\non:\n  pull_request:\n    branches: [main]\njobs:\n"
                "  spoof:\n    name: Pack-Guard\n    runs-on: ubuntu-latest\n"
                "    steps:\n      - run: echo ok\n",
            ),
            (
                "expr",
                "zz-spoof.yml",
                "name: x\non:\n  pull_request:\n    branches: [main]\njobs:\n"
                "  spoof:\n    name: ${{ 'pack-guard' }}\n"
                "    runs-on: ubuntu-latest\n    steps:\n      - run: echo ok\n",
            ),
            (
                "yaml_ext",
                "zz-spoof.yaml",
                "name: x\non:\n  pull_request:\n    branches: [main]\njobs:\n"
                "  pack-guard:\n    runs-on: ubuntu-latest\n"
                "    steps:\n      - run: echo ok\n",
            ),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wf = root / ".github" / "workflows"
            wf.mkdir(parents=True)
            (wf / "ci.yml").write_text(text, encoding="utf-8")
            _assert_pack_guard_check_name_unique(text, root)
            for mid, filename, body in spoofs:
                path = wf / filename
                path.write_text(body, encoding="utf-8")
                with self.subTest(mutation=mid):
                    with self.assertRaises(AssertionError):
                        _assert_pack_guard_check_name_unique(text, root)
                path.unlink()
            (wf / "zz-spoof.yml").write_text(":\n  [ unterminated\n", encoding="utf-8")
            with self.assertRaises(AssertionError):
                _assert_pack_guard_check_name_unique(text, root)
        smoke = "  dottie-os-smoke:\n    runs-on: ubuntu-latest\n"
        lookalike = (
            "  pack_guard:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: echo ok\n\n" + smoke
        )
        mutated = text.replace(smoke, lookalike, 1)
        self.assertNotEqual(mutated, text)
        with self.assertRaises(AssertionError):
            _assert_pack_guard_check_name_unique(mutated)

    def test_vendored_loader_refuses_escape_and_alias_spoofs(self) -> None:
        """B4a: 7 GitHub-resolved pack-guard forms are red on the CI loader."""
        hdr = "name: x\non:\n  pull_request:\n    branches: [main]\njobs:\n"
        steps = "    runs-on: ubuntu-latest\n    steps:\n      - run: echo ok\n"
        spoofs = {
            "alias_from_workflow_name": (
                "name: &n pack-guard\non: [pull_request]\njobs:\n  b:\n"
                "    name: *n\n" + steps
            ),
            "alias_from_env_block": (
                "name: x\nenv:\n  N: &n pack-guard\non: [pull_request]\n"
                "jobs:\n  b:\n    name: *n\n" + steps
            ),
            "dq_hex_escape_name": hdr + '  b:\n    name: "pack\\x2dguard"\n' + steps,
            "dq_u4_escape_name": hdr + '  b:\n    name: "\\u0070ack-guard"\n' + steps,
            "dq_U8_escape_name": hdr
            + '  b:\n    name: "pack\\U0000002dguard"\n'
            + steps,
            "dq_hex_escape_job_id": hdr + '  "pack\\x2dguard":\n' + steps,
            "dq_u4_escape_job_id": hdr + '  "\\u0070ack-guard":\n' + steps,
        }
        self.assertEqual(len(spoofs), 7)
        text = CI_WORKFLOW.read_text(encoding="utf-8")
        global yaml
        saved_yaml = yaml
        try:
            yaml = None
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                wf = root / ".github" / "workflows"
                wf.mkdir(parents=True)
                (wf / "ci.yml").write_text(text, encoding="utf-8")
                for cid, body in spoofs.items():
                    path = wf / "zz-spoof.yml"
                    path.write_text(body, encoding="utf-8")
                    with self.subTest(case=cid):
                        with self.assertRaises(AssertionError):
                            _assert_pack_guard_check_name_unique(text, root)
                    path.unlink()
        finally:
            globals()["yaml"] = saved_yaml

    def test_ci_permissions_and_checkout_token_are_pinned(self) -> None:
        """B4b: contents: read; every checkout drops credentials."""
        text = CI_WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(
            _workflow_permissions_block(text), PACK_GUARD_PERMISSIONS_BLOCK
        )
        _assert_read_only_token_and_checkouts(text)
        widened = text.replace(
            PACK_GUARD_PERMISSIONS_BLOCK,
            "permissions:\n  contents: read\n  checks: write\n",
            1,
        )
        with self.assertRaises(AssertionError):
            _assert_read_only_token_and_checkouts(widened)
        dropped = text.replace(
            "          persist-credentials: false\n",
            "",
            1,
        )
        self.assertNotEqual(dropped, text)
        with self.assertRaises(AssertionError):
            _assert_read_only_token_and_checkouts(dropped)
        job_widen = text.replace(
            "  lint-and-test:\n    runs-on: ubuntu-latest\n",
            "  lint-and-test:\n    permissions:\n"
            "      checks: write\n      statuses: write\n"
            "    runs-on: ubuntu-latest\n",
            1,
        )
        self.assertNotEqual(job_widen, text)
        with self.assertRaises(AssertionError):
            _assert_read_only_token_and_checkouts(job_widen)

    def test_pack_guard_path_pattern_refuses_fourteen_allows_three(self) -> None:
        """S21: shared segment-normalize rule, 22 refused + 3 prod allowlisted."""
        run = self._run_block()
        self.assertIn(PACK_GUARD_PATH_PY, run)
        must_catch = [
            "apps/x/curated_pack.jsonl",
            "apps/x/curatedpack.jsonl",
            "apps/x/curated.pack.jsonl",
            "apps/x/curated pack.jsonl",
            "apps/x/curated__pack.jsonl",
            "apps/x/curated/pack.jsonl",
            "apps/x/ultradata_harvest.jsonl",
            "apps/x/ultradata-harvest.jsonl",
            "scripts/ultradata_harvest_rows.jsonl",
            "apps/x/run_ultradata_harvest.jsonl",
            "scripts/run_ultradata_harvest.jsonl",
            "apps/dottie-os/scripts/lab/run_ultradata_harvest.jsonl",
            "apps/x/v2_ultradata_harvest.jsonl",
            "apps/x/x-ultradata-harvest.jsonl",
            "apps/x/mycurated_pack.jsonl",
            "apps/x/2curated_pack.jsonl",
            "apps/x/curated_packv2.jsonl",
            "apps/x/curatedpackrows.jsonl",
            "apps/x/curated+pack.jsonl",
            "apps/x/curated~pack.jsonl",
            "apps/x/curated,pack.jsonl",
            "apps/x/ultradata+harvest.jsonl",
        ]
        must_pass = [
            "docs/curated-packing-notes.md",
            "scripts/run_ultradata_harvest.py",
            "apps/dottie-os/scripts/lab/run_ultradata_harvest.py",
        ]
        test_only = "apps/x/uncurated_package.py"
        self.assertEqual(len(must_catch), 22)
        self.assertEqual(len(must_pass), 3)
        for name in must_catch:
            self.assertTrue(_pack_guard_path_is_banned(name), name)
        for name in must_pass:
            self.assertFalse(_pack_guard_path_is_banned(name), name)
        self.assertTrue(_pack_guard_path_is_banned(test_only), test_only)
        self.assertFalse(
            _pack_guard_path_is_banned(
                test_only, extra_allow=PACK_GUARD_PATH_ALLOWLIST_TEST
            ),
            test_only,
        )
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for name in must_catch:
                repo = base / hashlib.sha256(name.encode()).hexdigest()[:12]
                env = _init_pack_guard_repo(repo)
                _seed_pack_guard_floor(repo)
                path = repo / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")
                _commit_pack_guard_tree(repo, env, "pack")
                proc = _run_pack_guard_script(repo, run, env)
                self.assertNotEqual(proc.returncode, 0, msg=name)
            for name in must_pass:
                repo = base / ("ok-" + hashlib.sha256(name.encode()).hexdigest()[:12])
                env = _init_pack_guard_repo(repo)
                _seed_pack_guard_floor(repo)
                path = repo / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("ok\n", encoding="utf-8")
                _commit_pack_guard_tree(repo, env, "ok")
                proc = _run_pack_guard_script(repo, run, env)
                self.assertEqual(
                    proc.returncode,
                    0,
                    msg=f"{name} stdout={proc.stdout!r}",
                )

    def test_donewhen_mutations_go_red(self) -> None:
        """Critic done-when: shell -euo, unique pack-guard name, checkout with:."""
        text = CI_WORKFLOW.read_text(encoding="utf-8")
        shell_line = (
            '        shell: "/usr/bin/bash --noprofile --norc -p '
            '-euo pipefail {0}"'
        )
        self.assertIn(shell_line, text)
        cases = (
            (
                "shell_drops_euo_pipefail",
                text.replace(
                    shell_line,
                    '        shell: "/usr/bin/bash --noprofile --norc -p {0}"',
                    1,
                ),
            ),
            (
                "job_name_override",
                text.replace(
                    "  pack-guard:\n    runs-on: ubuntu-latest\n",
                    "  pack-guard:\n    name: pack-guard-ci\n"
                    "    runs-on: ubuntu-latest\n",
                    1,
                ),
            ),
            (
                "checkout_with_ref",
                text.replace(
                    "        with:\n"
                    "          persist-credentials: false\n"
                    "      - name: Refuse tracked pack artifacts\n",
                    "        with:\n"
                    "          persist-credentials: false\n"
                    "          ref: main\n"
                    "      - name: Refuse tracked pack artifacts\n",
                    1,
                ),
            ),
        )
        for mid, mutated in cases:
            with self.subTest(mutation=mid):
                self.assertNotEqual(mutated, text, f"{mid} did not change ci.yml")
                with self.assertRaises(AssertionError):
                    _assert_pack_guard_context(mutated)

    def test_critic_91_suite_is_vendored(self) -> None:
        path = TESTS / "test_critic_91_mutations.py"
        self.assertTrue(path.is_file())
        self.assertEqual(
            hashlib.sha256(path.read_bytes()).hexdigest(),
            CRITIC_91_MUTATIONS_SHA256,
        )

    def test_critic_91_136f_suite_is_vendored(self) -> None:
        path = TESTS / "test_critic_91_136f.py"
        self.assertTrue(path.is_file())
        self.assertEqual(
            hashlib.sha256(path.read_bytes()).hexdigest(),
            CRITIC_91_136F_SHA256,
        )

    def test_critic_91_af2d_suite_is_vendored(self) -> None:
        path = TESTS / "test_critic_91_af2d.py"
        self.assertTrue(path.is_file())
        self.assertEqual(
            hashlib.sha256(path.read_bytes()).hexdigest(),
            CRITIC_91_AF2D_SHA256,
        )

    def test_critic_91_50d2_suite_is_vendored(self) -> None:
        path = TESTS / "test_critic_91_50d2.py"
        self.assertTrue(path.is_file())
        self.assertEqual(
            hashlib.sha256(path.read_bytes()).hexdigest(),
            CRITIC_91_50D2_SHA256,
        )

    def test_critic_91_ce30_suite_is_vendored(self) -> None:
        path = TESTS / "test_critic_91_ce30.py"
        self.assertTrue(path.is_file())
        self.assertEqual(
            hashlib.sha256(path.read_bytes()).hexdigest(),
            CRITIC_91_CE30_SHA256,
        )

    def test_critic_91_f8f1_suite_is_vendored(self) -> None:
        path = TESTS / "test_critic_91_f8f1.py"
        self.assertTrue(path.is_file())
        self.assertEqual(
            hashlib.sha256(path.read_bytes()).hexdigest(),
            CRITIC_91_F8F1_SHA256,
        )

    def test_critic_91_0b05_suite_is_vendored(self) -> None:
        path = TESTS / "test_critic_91_0b05.py"
        self.assertTrue(path.is_file())
        self.assertEqual(
            hashlib.sha256(path.read_bytes()).hexdigest(),
            CRITIC_91_0B05_SHA256,
        )

    def test_critic_91_0ac5_suite_is_vendored(self) -> None:
        path = TESTS / "test_critic_91_0ac5.py"
        self.assertTrue(path.is_file())
        self.assertEqual(
            hashlib.sha256(path.read_bytes()).hexdigest(),
            CRITIC_91_0AC5_SHA256,
        )

    def test_ci_pack_guard_run_block_trips_on_tracked_packs(self) -> None:
        run = self._run_block()
        with tempfile.TemporaryDirectory() as tmp:
            clean = Path(tmp) / "clean"
            env = _init_pack_guard_repo(clean)
            _seed_pack_guard_floor(clean)
            (clean / "README").write_text("ok\n", encoding="utf-8")
            _commit_pack_guard_tree(clean, env, "clean")
            clean_proc = _run_pack_guard_script(clean, run, env)
            self.assertEqual(
                clean_proc.returncode,
                0,
                msg=f"stdout={clean_proc.stdout!r} stderr={clean_proc.stderr!r}",
            )

            root = Path(tmp) / "root"
            env = _init_pack_guard_repo(root)
            _seed_pack_guard_floor(root)
            (root / PACK_GUARD_ROOT_PACK).write_text(
                '{"eval_only": true}\n', encoding="utf-8"
            )
            _commit_pack_guard_tree(root, env, "root pack jsonl")
            root_proc = _run_pack_guard_script(root, run, env)
            self.assertNotEqual(
                root_proc.returncode,
                0,
                msg=f"root pack must trip the guard; stdout={root_proc.stdout!r}",
            )

            nested = Path(tmp) / "fixtures"
            env = _init_pack_guard_repo(nested)
            _seed_pack_guard_floor(nested)
            pack = nested / PACK_GUARD_FIXTURES_PACK
            pack.parent.mkdir(parents=True, exist_ok=True)
            pack.write_text('{"eval_only": true}\n', encoding="utf-8")
            _commit_pack_guard_tree(nested, env, "fixtures pack jsonl")
            nested_proc = _run_pack_guard_script(nested, run, env)
            self.assertNotEqual(
                nested_proc.returncode,
                0,
                msg=(
                    "fixtures pack must trip the guard; "
                    f"stdout={nested_proc.stdout!r}"
                ),
            )

            dashed = Path(tmp) / "dashed"
            env = _init_pack_guard_repo(dashed)
            _seed_pack_guard_floor(dashed)
            dash_pack = dashed / "apps" / "x" / "curated-pack-v2.jsonl"
            dash_pack.parent.mkdir(parents=True, exist_ok=True)
            dash_pack.write_text('{"eval_only": true}\n', encoding="utf-8")
            _commit_pack_guard_tree(dashed, env, "curated-pack jsonl")
            dash_proc = _run_pack_guard_script(dashed, run, env)
            self.assertNotEqual(
                dash_proc.returncode,
                0,
                msg=(
                    "curated-pack-v2.jsonl must trip the guard; "
                    f"stdout={dash_proc.stdout!r}"
                ),
            )

    def test_this_tree_has_no_tracked_pack_artifacts(self) -> None:
        """S26: exact pins + KNOWN_LEGACY must keep this HEAD tree green."""
        blobs = _head_blob_sizes(REPO_ROOT)
        self.assertGreaterEqual(len(blobs), PACK_GUARD_LS_FILES_FLOOR)
        over = [(sz, path) for sz, path in blobs if sz > PACK_GUARD_BLOB_MAX]
        self.assertEqual(
            over,
            [],
            f"tracked blobs exceed CAP={PACK_GUARD_BLOB_MAX}: {over}",
        )
        largest_sz, largest_path = max(blobs)
        self.assertGreater(
            largest_sz,
            2 * 1024 * 1024,
            f"expected the ~2.58 MiB tracked file, got {largest_sz} {largest_path}",
        )
        self.assertLessEqual(largest_sz, PACK_GUARD_BLOB_MAX)
        run = self._run_block()
        self.assertIn(f"CAP={PACK_GUARD_BLOB_MAX}", run)
        self.assertIn("PIN=frozenset", run)
        self.assertIn("LEG=frozenset", run)
        self.assertNotIn("OK=frozenset", run)
        corpus = (
            "apps/ava-factory/data/orchestration/corpus.jsonl"
        )
        repair = (
            "tasks/artifacts/corpus_proposals/repair_transcripts/"
            "repair_sft_unified.jsonl"
        )
        self.assertTrue(
            any(path == corpus for path, _digest in PACK_GUARD_KNOWN_LEGACY)
        )
        self.assertTrue(
            any(path == repair for path, _digest in PACK_GUARD_KNOWN_LEGACY)
        )
        self.assertFalse(
            any(path == corpus for path, _digest in PACK_GUARD_BLOB_PIN)
        )
        self.assertFalse(
            any(path == repair for path, _digest in PACK_GUARD_BLOB_PIN)
        )
        env = _pack_guard_git_env()
        proc = _run_pack_guard_script(REPO_ROOT, run, env)
        self.assertEqual(
            proc.returncode,
            0,
            msg=f"stdout={proc.stdout!r} stderr={proc.stderr!r}",
        )

    def test_known_legacy_pins_exact_path_and_hash(self) -> None:
        """KNOWN_LEGACY: exact path+hash pass; copy or edit is refused."""
        run = self._run_block()
        pairs = sorted(PACK_GUARD_KNOWN_LEGACY)
        self.assertEqual(len(pairs), 2)
        blobs = {
            path: (REPO_ROOT / path).read_bytes() for path, _digest in pairs
        }
        for path, digest in pairs:
            self.assertEqual(hashlib.sha256(blobs[path]).hexdigest(), digest)

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "legacy-ok"
            env = _init_pack_guard_repo(repo)
            _seed_pack_guard_floor(repo)
            for path, data in blobs.items():
                dest = repo / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
            _commit_pack_guard_tree(repo, env, "legacy exact")
            proc = _run_pack_guard_script(repo, run, env)
            self.assertEqual(
                proc.returncode,
                0,
                msg=f"pinned legacy must pass; stdout={proc.stdout!r}",
            )

        for path, data in blobs.items():
            with tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp) / "legacy-copy"
                env = _init_pack_guard_repo(repo)
                _seed_pack_guard_floor(repo)
                copy = repo / "apps" / "x" / Path(path).name
                copy.parent.mkdir(parents=True, exist_ok=True)
                copy.write_bytes(data)
                _commit_pack_guard_tree(repo, env, "legacy copy")
                proc = _run_pack_guard_script(repo, run, env)
                self.assertNotEqual(
                    proc.returncode,
                    0,
                    msg=f"copy of {path} must be refused; stdout={proc.stdout!r}",
                )
                self.assertIn(str(copy.relative_to(repo)), proc.stdout)

            with tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp) / "legacy-edit"
                env = _init_pack_guard_repo(repo)
                _seed_pack_guard_floor(repo)
                dest = repo / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data + b"\n")
                _commit_pack_guard_tree(repo, env, "legacy edit")
                proc = _run_pack_guard_script(repo, run, env)
                self.assertNotEqual(
                    proc.returncode,
                    0,
                    msg=f"edited {path} must be refused; stdout={proc.stdout!r}",
                )
                self.assertIn(path, proc.stdout)

    def test_pack_guard_refuses_blob_over_size_cap(self) -> None:
        """S26 size cap fails closed one byte over 3 MiB, neutral name."""
        run = self._run_block()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            env = _init_pack_guard_repo(repo)
            _seed_pack_guard_floor(repo)
            blob = repo / "apps" / "x" / "weights.bin"
            blob.parent.mkdir(parents=True, exist_ok=True)
            blob.write_bytes(b"A" * (PACK_GUARD_BLOB_MAX + 1))
            _commit_pack_guard_tree(repo, env, "oversize")
            proc = _run_pack_guard_script(repo, run, env)
        self.assertNotEqual(
            proc.returncode,
            0,
            msg=f"oversize blob must trip; stdout={proc.stdout!r}",
        )
        self.assertIn("apps/x/weights.bin", proc.stdout)

    def test_pack_guard_fails_closed_outside_git_repo(self) -> None:
        run = self._run_block()
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "not-a-repo"
            outside.mkdir()
            proc = _run_pack_guard_script(outside, run, _pack_guard_git_env())
        self.assertNotEqual(
            proc.returncode,
            0,
            msg=(
                "guard must not fail open outside a git repo; "
                f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
            ),
        )

    def test_pack_guard_fails_closed_with_null_index(self) -> None:
        run = self._run_block()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            env = _init_pack_guard_repo(repo)
            _seed_pack_guard_floor(repo)
            (repo / PACK_GUARD_ROOT_PACK).write_text(
                '{"eval_only": true}\n', encoding="utf-8"
            )
            _commit_pack_guard_tree(repo, env, "root pack")
            env = dict(env)
            env["GIT_INDEX_FILE"] = "/dev/null"
            proc = _run_pack_guard_script(repo, run, env)
        self.assertNotEqual(
            proc.returncode,
            0,
            msg=(
                "guard must still see a pack when GIT_INDEX_FILE=/dev/null; "
                f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
            ),
        )
        self.assertIn(PACK_GUARD_ROOT_PACK, proc.stdout)

    def test_pack_guard_from_subdirectory_catches_root_pack(self) -> None:
        run = self._run_block()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            env = _init_pack_guard_repo(repo)
            _seed_pack_guard_floor(repo)
            (repo / PACK_GUARD_ROOT_PACK).write_text(
                '{"eval_only": true}\n', encoding="utf-8"
            )
            _commit_pack_guard_tree(repo, env, "root pack jsonl")
            sub = repo / "apps" / "nested"
            sub.mkdir(parents=True)
            proc = _run_pack_guard_script(sub, run, env)
        self.assertNotEqual(
            proc.returncode,
            0,
            msg=(
                "subdirectory must still catch a root pack; "
                f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
            ),
        )
        self.assertIn(PACK_GUARD_ROOT_PACK, proc.stdout)

    def test_pack_guard_github_sha_pack_survives_head_reset(self) -> None:
        """HEAD moved by reset --hard older; pack still at GITHUB_SHA is red."""
        run = self._run_block()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            env = _init_pack_guard_repo(repo)
            _seed_pack_guard_floor(repo)
            _commit_pack_guard_tree(repo, env, "older")
            older = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            pack = repo / "apps" / "x" / "curated_pack_v2.jsonl"
            pack.parent.mkdir(parents=True, exist_ok=True)
            pack.write_text('{"eval_only": true}\n', encoding="utf-8")
            _commit_pack_guard_tree(repo, env, "with pack")
            newer = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            subprocess.run(
                ["git", "reset", "--hard", older],
                cwd=repo,
                env=env,
                check=True,
                capture_output=True,
            )
            env = dict(env)
            env["GITHUB_SHA"] = newer
            proc = _run_pack_guard_script(repo, run, env)
        self.assertNotEqual(
            proc.returncode,
            0,
            msg=(
                "pack at GITHUB_SHA must trip after reset --hard older; "
                f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
            ),
        )
        self.assertTrue(
            "curated_pack_v2.jsonl" in proc.stdout
            or "HEAD" in proc.stdout,
            msg=(
                "reset --hard older must trip (pack at GITHUB_SHA or HEAD "
                f"mismatch); stdout={proc.stdout!r}"
            ),
        )

    def test_pack_guard_ls_tree_without_dash_r_misses_nested_pack(self) -> None:
        """Nested pack unstaged from the index is still red; dropping -r is not."""
        run = self._run_block()
        self.assertIn('ls-tree -r -z --full-tree --name-only "$GITHUB_SHA"', run)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            env = _init_pack_guard_repo(repo)
            _seed_pack_guard_floor(repo)
            pack = repo / PACK_GUARD_FIXTURES_PACK
            pack.parent.mkdir(parents=True, exist_ok=True)
            pack.write_text('{"eval_only": true}\n', encoding="utf-8")
            _commit_pack_guard_tree(repo, env, "nested pack")
            subprocess.run(
                ["git", "rm", "-q", "--cached", "-r", "--", "apps"],
                cwd=repo,
                env=env,
                check=True,
                capture_output=True,
            )
            proc = _run_pack_guard_script(repo, run, env)
            self.assertNotEqual(
                proc.returncode,
                0,
                msg=(
                    "nested pack in GITHUB_SHA tree must trip; "
                    f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
                ),
            )
            weak = run.replace("ls-tree -r -z", "ls-tree -z", 1)
            self.assertNotEqual(weak, run)
            weak_proc = _run_pack_guard_script(repo, weak, env)
        self.assertNotEqual(
            weak_proc.returncode,
            0,
            msg=(
                "ls-tree without -r must go red (nested ci.yml/pack unseen); "
                f"stdout={weak_proc.stdout!r} stderr={weak_proc.stderr!r}"
            ),
        )

    def test_pack_guard_github_sha_unset_or_bogus_is_red(self) -> None:
        run = self._run_block()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            env = _init_pack_guard_repo(repo)
            _seed_pack_guard_floor(repo)
            _commit_pack_guard_tree(repo, env, "clean")
            unset_env = dict(env)
            unset_env.pop("GITHUB_SHA", None)
            unset_proc = _run_pack_guard_script(
                repo, run, unset_env, pin_github_sha=False
            )
            self.assertNotEqual(
                unset_proc.returncode,
                0,
                msg=(
                    "unset GITHUB_SHA must fail closed; "
                    f"stdout={unset_proc.stdout!r} stderr={unset_proc.stderr!r}"
                ),
            )
            bogus = dict(env)
            bogus["GITHUB_SHA"] = "not-a-sha"
            bogus_proc = _run_pack_guard_script(repo, run, bogus)
            self.assertNotEqual(
                bogus_proc.returncode,
                0,
                msg=(
                    "non-hex GITHUB_SHA must fail closed; "
                    f"stdout={bogus_proc.stdout!r} stderr={bogus_proc.stderr!r}"
                ),
            )
            missing = dict(env)
            missing["GITHUB_SHA"] = "0" * 40
            missing_proc = _run_pack_guard_script(repo, run, missing)
            self.assertNotEqual(
                missing_proc.returncode,
                0,
                msg=(
                    "GITHUB_SHA that is not a commit must fail closed; "
                    f"stdout={missing_proc.stdout!r} stderr={missing_proc.stderr!r}"
                ),
            )


class HelperFtLeakGateSyntheticTests(unittest.TestCase):
    """Partial-leak and small-n cases, kept separate from Mill's 56 fixtures."""

    def setUp(self) -> None:
        self.kickoff_calls: list[dict] = []
        _start_hq_http_mock(self)

        def fake_post(body: dict, url: str | None = None) -> dict:
            self.kickoff_calls.append(body)
            return {"ok": True, "checkpoint_id": "ckpt-syn", "exit_code": 0}

        self._orig_post = kick_helper_ft.post_kickoff
        kick_helper_ft.post_kickoff = fake_post

    def tearDown(self) -> None:
        kick_helper_ft.post_kickoff = self._orig_post
        _stop_hq_http_mock(self)

    def _pin(self, manifest: dict, **overrides: object) -> dict:
        pin = _cam_pin(manifest, **overrides)
        self.hq_pins[manifest["pack_id"]] = pin
        return pin

    def test_partial_leak_most_rows_refused(self) -> None:
        actions = ["execute"] * 8 + ["halt"] * 6 + ["escalate"] * 2
        rows = [_row(rid=f"part-{idx}", action=action) for idx, action in enumerate(actions)]
        for idx, row in enumerate(rows):
            gold = row["labels"]["action"]["choice"]
            hint = gold if idx >= 4 else f"noise-{idx}"
            row["state"] = {"message": row["state"]["message"], "meta": {"hint": hint}}
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_action_pack(dest, rows, pack_id="synthetic-partial-leak")
            self._pin(manifest)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(ctx.exception.field, "state.leak")
        self.assertTrue(any("hint" in str(item) for item in ctx.exception.actual))

    def test_small_n_perfect_repeated_values_refused(self) -> None:
        actions = ["execute", "execute", "halt", "halt"]
        rows = [_row(rid=f"sm-{idx}", action=action) for idx, action in enumerate(actions)]
        for row, action in zip(rows, actions, strict=True):
            row["state"] = {"message": row["state"]["message"], "meta": {"tag": action}}
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_action_pack(dest, rows, pack_id="synthetic-small-n-perfect")
            self._pin(manifest)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(ctx.exception.field, "state.leak")

    def test_small_n_constant_and_unique_fields_pass(self) -> None:
        actions = ["execute", "execute", "halt", "halt"]
        rows = [_row(rid=f"ok-{idx}", action=action) for idx, action in enumerate(actions)]
        for idx, row in enumerate(rows):
            row["state"] = {
                "message": row["state"]["message"],
                "meta": {"flag": "review", "uid": f"row-{idx}"},
            }
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_action_pack(dest, rows, pack_id="synthetic-small-n-clean")
            self._pin(manifest)
            evidence = kick_helper_ft.kick(dest)
        self.assertEqual(evidence["result"], "MATCH")


if __name__ == "__main__":
    unittest.main()
