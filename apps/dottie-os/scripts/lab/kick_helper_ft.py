#!/usr/bin/env python3
"""Stage-5 HELPER factory-trainer kick: point-of-use pack integrity, then train.

Reads a hopped curated pack and its MANIFEST.json on the training host.
Re-hashes pack / train / holdout with streaming SHA-256 and compares them to
the manifest. A mismatch, a missing file, or a missing required field refuses
the kick (non-zero exit). There is no override flag.

On success, writes pack_integrity_evidence.json next to the run log, prints it,
and proceeds to the HELPER train hook. Does not promote, does not touch serve,
:8770, champion files, or the LIVE gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

PACK_FILE = "curated_pack_v2.jsonl"
TRAIN_FILE = "curated_pack_v2_train.jsonl"
HOLDOUT_FILE = "curated_pack_v2_holdout.jsonl"
MANIFEST_FILE = "MANIFEST.json"
EVIDENCE_NAME = "pack_integrity_evidence.json"
DEFAULT_LOG_NAME = "helper_ft.log"

# (manifest sha field, on-disk file, optional row-count field)
ARTIFACTS: tuple[tuple[str, str, str], ...] = (
    ("sha256_pack", PACK_FILE, "rows"),
    ("sha256_train", TRAIN_FILE, "train_rows"),
    ("sha256_holdout", HOLDOUT_FILE, "holdout_rows"),
)

StartTraining = Callable[[Path, dict[str, Any], Path], Any]


class KickRefused(Exception):
    """HELPER FT may not start. ``field``, ``expected``, and ``actual`` are named."""

    def __init__(self, field: str, expected: object, actual: object) -> None:
        self.field = field
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"HELPER FT refused: {field}: expected {expected} actual {actual}"
        )


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    """Streaming SHA-256 of file bytes. Never hashes a hardcoded string."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def count_rows(path: Path) -> int:
    with path.open(encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _refuse(field: str, expected: object, actual: object) -> None:
    raise KickRefused(field, expected, actual)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_manifest(pack_dir: Path) -> dict[str, Any]:
    manifest_path = pack_dir / MANIFEST_FILE
    if not manifest_path.is_file():
        _refuse(MANIFEST_FILE, "present", "missing")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        _refuse(MANIFEST_FILE, "valid JSON object", f"invalid JSON ({exc})")
    if not isinstance(payload, dict):
        _refuse(MANIFEST_FILE, "valid JSON object", type(payload).__name__)
    return payload


def verify_pack(pack_dir: Path) -> dict[str, Any]:
    """Re-hash pack/train/holdout and compare to MANIFEST.json.

    Returns the evidence dict on success. Raises KickRefused on any failure.
    """
    pack_dir = Path(pack_dir)
    manifest = _read_manifest(pack_dir)

    computed_shas: dict[str, str] = {}
    expected_shas: dict[str, str] = {}
    row_counts: dict[str, dict[str, int | None]] = {}

    for sha_field, filename, rows_field in ARTIFACTS:
        expected = manifest.get(sha_field)
        if not isinstance(expected, str) or not expected:
            _refuse(sha_field, "present", "missing")
        path = pack_dir / filename
        if not path.is_file():
            _refuse(filename, "present", "missing")
        actual = sha256_file(path)
        expected_shas[sha_field] = expected
        computed_shas[sha_field] = actual
        if actual != expected:
            _refuse(sha_field, expected, actual)

        actual_rows = count_rows(path)
        expected_rows: int | None
        if rows_field in manifest:
            raw = manifest[rows_field]
            try:
                expected_rows = int(raw)
            except (TypeError, ValueError):
                _refuse(rows_field, "integer row count", raw)
            if actual_rows != expected_rows:
                _refuse(rows_field, expected_rows, actual_rows)
        else:
            expected_rows = None
        row_counts[filename] = {"expected": expected_rows, "actual": actual_rows}

    pack_id = manifest.get("pack_id")
    if not isinstance(pack_id, str) or not pack_id:
        pack_id = pack_dir.name

    return {
        "pack_id": pack_id,
        "host": socket.gethostname(),
        "computed_shas": computed_shas,
        "expected_shas": expected_shas,
        "row_counts": row_counts,
        "checked_at": _utc_now(),
        "ok": True,
    }


def write_evidence(evidence: Mapping[str, Any], log_path: Path) -> Path:
    """Write evidence JSON next to the run log. Returns the evidence path."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path = log_path.parent / EVIDENCE_NAME
    evidence_path.write_text(json.dumps(dict(evidence), indent=2) + "\n", encoding="utf-8")
    return evidence_path


def default_start_training(pack_dir: Path, evidence: dict[str, Any], log_path: Path) -> dict[str, Any]:
    """HELPER train may start. Does not promote and does not touch LIVE/champion."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = (
        f"{evidence['checked_at']} HELPER_FT_KICK allowed "
        f"pack_id={evidence['pack_id']} host={evidence['host']} "
        f"auto_promote=false\n"
    )
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line)
    return {"training_started": True, "auto_promote": False, "pack_dir": str(pack_dir)}


def kick(
    pack_dir: Path,
    *,
    log_path: Path | None = None,
    start_training: StartTraining | None = None,
) -> dict[str, Any]:
    """Verify the pack then start HELPER training. No skip/override."""
    pack_dir = Path(pack_dir)
    log_path = Path(log_path) if log_path is not None else pack_dir / DEFAULT_LOG_NAME
    evidence = dict(verify_pack(pack_dir))
    evidence_path = log_path.parent / EVIDENCE_NAME
    evidence["evidence_path"] = str(evidence_path)
    write_evidence(evidence, log_path)
    starter = start_training or default_start_training
    starter(pack_dir, evidence, log_path)
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pack",
        type=Path,
        required=True,
        help="inbox pack directory (MANIFEST.json + curated_pack_v2*.jsonl)",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="run log path; evidence JSON is written next to it",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = kick(args.pack, log_path=args.log)
    except KickRefused as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1
    print(json.dumps(evidence, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
