"""Stdlib-only checks for the dottie-os UltraData factory + hop helpers.

No Hugging Face download, no FT, no LIVE/champion. Run with:

    python3 -m unittest discover -s apps/dottie-os/tests -v
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
SCRIPTS = APP / "scripts"
LAB = SCRIPTS / "lab"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

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


SWARM_HQ_PIN_CONTRACT_REQUIRED = (
    "pack_id",
    "sha256_pack",
    "sha256_train",
    "sha256_holdout",
    "rows_total",
    "rows_train",
    "rows_holdout",
    "pack_matches",
    "recordedBy",
    "recordedAt",
    "kid",
)
SWARM_HQ_PIN_CONTRACT_ALLOWED = frozenset((*SWARM_HQ_PIN_CONTRACT_REQUIRED, "stampVerified", "verified"))
SWARM_HQ_AGENT_TOKEN_FIXTURE = "test-swarm-hq-agent-token"
SWARM_HQ_PIN_FIXTURE = {
    "pack_id": "curated_pack_v2-contract",
    "sha256_pack": "11" * 32,
    "sha256_train": "22" * 32,
    "sha256_holdout": "33" * 32,
    "rows_total": 2,
    "rows_train": 1,
    "rows_holdout": 1,
    "pack_matches": True,
    "recordedBy": "cam",
    "recordedAt": "2026-10-19T00:00:00Z",
    "kid": "cam-stamp-kid-1",
    "stampVerified": True,
}


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
        "recordedAt": "2026-10-19T00:00:00Z",
        "kid": "cam-stamp-kid-1",
        "stampVerified": True,
    }
    pin.update(overrides)
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

    def read(self) -> bytes:
        return self._body

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


def _start_hq_http_mock(owner: unittest.TestCase) -> None:
    owner.hq_pins = {}
    owner.hq_error = None
    owner.hq_http_status = None
    owner.hq_requests = []
    owner.hq_saw_agent_token = False
    os.environ["SWARM_HQ_URL"] = "https://swarm-hq.test"
    os.environ["SWARM_HQ_AGENT_TOKEN"] = SWARM_HQ_AGENT_TOKEN_FIXTURE

    def fake_urlopen(request: object, timeout: object = None) -> _FakeHqHttpResponse:
        url = getattr(request, "full_url", None) or str(request)
        method = request.get_method() if hasattr(request, "get_method") else "GET"
        owner.hq_requests.append(url)
        owner.assertEqual(method, "GET")
        owner.assertTrue(str(url).startswith("https://"), url)
        owner.assertIn("/api/packs/", str(url))
        owner.assertTrue(str(url).endswith("/pin"), url)
        token = _request_header(request, "x-agent-token")
        if not token:
            raise _hq_http_error(str(url), 401)
        owner.hq_saw_agent_token = True
        if owner.hq_http_status in (401, 404):
            raise _hq_http_error(str(url), owner.hq_http_status)
        if owner.hq_error is not None:
            raise urllib.error.URLError(owner.hq_error)
        pack_id = _pack_id_from_pin_url(str(url))
        pin = owner.hq_pins.get(pack_id)
        if pin is None:
            raise _hq_http_error(str(url), 404)
        return _FakeHqHttpResponse(json.dumps(pin).encode("utf-8"))

    owner._urlopen_patcher = patch("urllib.request.urlopen", side_effect=fake_urlopen)
    owner._urlopen_patcher.start()


def _stop_hq_http_mock(owner: unittest.TestCase) -> None:
    owner._urlopen_patcher.stop()
    os.environ.pop("SWARM_HQ_URL", None)
    os.environ.pop("SWARM_HQ_AGENT_TOKEN", None)


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
            self.assertEqual(body.get("pin", {}).get("recordedBy"), "cam")
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
        self.assertEqual(on_disk["anchor_source"], "swarm-hq-cam-pin")

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

    def test_pin_missing_stamp_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest, stampVerified=False)
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(len(self.hq_requests), 1)
        self.assertEqual(ctx.exception.field, "cam-pin.stampVerified")
        self.assertEqual(ctx.exception.expected, True)

    def test_pin_non_cam_recorded_by_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest, recordedBy="agent")
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(len(self.hq_requests), 1)
        self.assertEqual(ctx.exception.field, "cam-pin.recordedBy")
        self.assertEqual(ctx.exception.expected, "cam")
        self.assertEqual(ctx.exception.actual, "agent")

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

    def test_pin_pack_matches_false_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            pin = self._pin(manifest, pack_matches=False)
            self.assertTrue(pin["stampVerified"])
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest)
            rc = kick_helper_ft.main(_cli_args(dest))
        self.assertEqual(self.kickoff_calls, [])
        self.assertEqual(rc, 1)
        self.assertEqual(ctx.exception.field, "cam-pin.pack_matches")
        self.assertEqual(ctx.exception.expected, True)
        self.assertIs(ctx.exception.actual, False)

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
        src = Path(kick_helper_ft.__file__).read_text(encoding="utf-8")
        self.assertIn("SWARM_HQ_URL", src)
        self.assertIn("SWARM_HQ_AGENT_TOKEN", src)
        self.assertIn("x-agent-token", src)
        self.assertIn("/api/packs/", src)
        self.assertIn("/pin", src)
        self.assertIn("https://", src)
        self.assertNotIn("import redis", src)
        self.assertNotIn("from redis", src)
        option_strings = [
            flag
            for action in kick_helper_ft.build_parser()._actions
            for flag in action.option_strings
        ]
        self.assertNotIn("--cam-pin", option_strings)
        os.environ["SWARM_HQ_URL"] = "http://swarm-hq.test"
        before = list(self.hq_requests)
        with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
            kick_helper_ft.fetch_cam_pin("curated_pack_v2-test")
        self.assertEqual(self.hq_requests, before)
        self.assertEqual(ctx.exception.field, "SWARM_HQ_URL")
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
                target.write_bytes(target.read_bytes() + b"x")

            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(
                    dest, log_path=log_path, start_training=start)
            files = list(log_path.parent.glob("pack_integrity_evidence_*.json"))
            self.assertEqual(len(files), 1)
            on_disk = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertFalse(on_disk["ok"])
        self.assertEqual(ctx.exception.field, "sha256_pack")
        self.assertEqual(len(self.kickoff_calls), 1)

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
            result = helper_ft_kickoff.handle_train_kickoff(body)
        self.assertFalse(result["ok"])
        self.assertEqual(result["field"], "sha256_pack")

    def test_handler_accepts_matching_named_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            self._pin(manifest)
            body = _fresh_kickoff_body(dest, manifest)
            result = helper_ft_kickoff.handle_train_kickoff(body)
        self.assertTrue(result["ok"])
        self.assertEqual(result["pack_id"], manifest["pack_id"])

    def test_forge_runner_kickoff_never_accepts_latest(self) -> None:
        repo = Path(__file__).resolve().parents[3]
        loop_src = repo / "packages" / "dottie-loop"
        runner_path = loop_src / "scripts" / "forge_runner.py"
        src = runner_path.read_text(encoding="utf-8")
        self.assertIn("helper_ft_kickoff.py", src)
        self.assertIn('inbox.strip().lower() == "latest"', src)
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
    return {
        "mode": "helper-ft",
        "pack_id": manifest["pack_id"],
        "run_id": run_id,
        "checked_at": now,
        "sha256_pack": shas["sha256_pack"],
        "sha256_train": shas["sha256_train"],
        "sha256_holdout": shas["sha256_holdout"],
        "expected_shas": dict(shas),
        "pin": _cam_pin(manifest),
        "paths": {
            "pack": str(dest / "curated_pack_v2.jsonl"),
            "train": str(dest / "curated_pack_v2_train.jsonl"),
            "holdout": str(dest / "curated_pack_v2_holdout.jsonl"),
            "manifest": str(dest / "MANIFEST.json"),
        },
        "evidence": {
            "ok": True,
            "pack_id": manifest["pack_id"],
            "run_id": run_id,
            "checked_at": now,
            "computed_shas": dict(shas),
            "expected_shas": dict(shas),
            "pin": _cam_pin(manifest),
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
            _flip_one_ascii_byte(dest / "curated_pack_v2.jsonl")
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
            (dest / "curated_pack_v2_train.jsonl").write_bytes(
                (dest / "curated_pack_v2_train.jsonl").read_bytes() + b"\n"
            )
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
        self.assertTrue(self.hq_requests)
        self.assertTrue(self.hq_requests[0].endswith("/pin"))

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
        self.assertEqual(payload["field"], "sha256_pack")
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

    def test_http_pack_matches_false_refuses_before_trainer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            pin = self._pin(manifest, pack_matches=False)
            self.assertTrue(pin["stampVerified"])
            body = _fresh_kickoff_body(dest, manifest)
            response = self.client.post("/train/kickoff", json=body)
        payload = response.json()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["field"], "cam-pin.pack_matches")
        self.assertEqual(payload["expected"], True)
        self.assertIs(payload["actual"], False)
        self.assertEqual(self.launches, [])

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
                    body["pin"][field] = wrong
                    body["evidence"]["pin"][field] = wrong
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
            _flip_one_ascii_byte(dest / "curated_pack_v2.jsonl")
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
            train = dest / "curated_pack_v2_train.jsonl"
            train.write_bytes(train.read_bytes() + b'{"id":"extra-row"}\n')
            response = self.client.post("/train/kickoff", json=body)
        payload = response.json()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["field"], "rows_train")
        self.assertEqual(payload["expected"], 1)
        self.assertEqual(payload["actual"], 2)
        self.assertEqual(self.launches, [])


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
        self.assertEqual(
            set(SWARM_HQ_PIN_FIXTURE),
            set(SWARM_HQ_PIN_CONTRACT_REQUIRED) | {"stampVerified"},
        )
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


if __name__ == "__main__":
    unittest.main()
