"""Stdlib-only checks for the dottie-os UltraData factory + hop helpers.

No Hugging Face download, no FT, no LIVE/champion. Run with:

    python3 -m unittest discover -s apps/dottie-os/tests -v
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

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


class HelperFtIntegrityTests(unittest.TestCase):
    def test_match_lets_training_start(self) -> None:
        started: list[Path] = []

        def start(pack_dir: Path, evidence: dict, log_path: Path) -> None:
            started.append(pack_dir)
            self.assertTrue(evidence["ok"])
            self.assertEqual(evidence["pack_id"], "curated_pack_v2-test")
            self.assertEqual(evidence["computed_shas"], evidence["expected_shas"])
            self.assertEqual(log_path.name, "helper_ft.log")

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "inbox-pack"
            dest.mkdir()
            manifest = _write_helper_pack(dest)
            log_path = Path(tmp) / "runs" / "helper_ft.log"
            evidence = kick_helper_ft.kick(dest, log_path=log_path, start_training=start)
            on_disk = json.loads((log_path.parent / "pack_integrity_evidence.json").read_text(encoding="utf-8"))
            rc = kick_helper_ft.main(["--pack", str(dest), "--log", str(log_path)])
        self.assertEqual(len(started), 1)
        self.assertEqual(rc, 0)
        self.assertEqual(evidence["expected_shas"]["sha256_pack"], manifest["sha256_pack"])
        self.assertEqual(on_disk["computed_shas"], evidence["computed_shas"])
        self.assertEqual(on_disk["host"], evidence["host"])
        self.assertTrue(on_disk["checked_at"].endswith("Z"))
        self.assertEqual(on_disk["row_counts"]["curated_pack_v2.jsonl"]["actual"], 2)
        self.assertEqual(on_disk["row_counts"]["curated_pack_v2_train.jsonl"]["actual"], 1)
        self.assertEqual(on_disk["row_counts"]["curated_pack_v2_holdout.jsonl"]["actual"], 1)

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
                    _write_helper_pack(dest)
                    target = dest / filename
                    target.write_bytes(target.read_bytes() + b"x")
                    with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                        kick_helper_ft.kick(dest, start_training=start)
                    rc = kick_helper_ft.main(["--pack", str(dest)])
                self.assertEqual(started, [])
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
            _write_helper_pack(dest)
            manifest_path = dest / "MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            del manifest["sha256_train"]
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(kick_helper_ft.KickRefused) as ctx:
                kick_helper_ft.kick(dest, start_training=start)
            rc = kick_helper_ft.main(["--pack", str(dest)])
        self.assertEqual(started, [])
        self.assertEqual(rc, 1)
        self.assertEqual(ctx.exception.field, "sha256_train")
        self.assertEqual(ctx.exception.expected, "present")
        self.assertEqual(ctx.exception.actual, "missing")


if __name__ == "__main__":
    unittest.main()
