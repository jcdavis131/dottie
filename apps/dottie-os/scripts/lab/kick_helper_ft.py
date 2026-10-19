#!/usr/bin/env python3
"""Stage-5 HELPER factory-trainer kick: point-of-use pack integrity, then train.

Trust comes from CLI anchors (``--expected-sha256-pack`` / ``-train`` /
``-holdout``) taken from the Mill-signed Swarm HQ pack record or the ticket,
not from MANIFEST.json alone. Those anchors must match both MANIFEST.json and
the bytes copied into a run-private directory. Rewriting the pack and the
MANIFEST together on the host still fails.

Files are opened with O_NOFOLLOW (when the OS provides it), hashed while
copied into a fresh 0700 directory, and only those copies are handed to the
train hook. Symlinks, non-regular files, and paths outside the pack directory
are refused. There is no skip flag or skip env var.

Does not promote, does not touch serve, :8770, champion files, or the LIVE gate.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import socket
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, NoReturn

PACK_FILE = "curated_pack_v2.jsonl"
TRAIN_FILE = "curated_pack_v2_train.jsonl"
HOLDOUT_FILE = "curated_pack_v2_holdout.jsonl"
MANIFEST_FILE = "MANIFEST.json"
EVIDENCE_NAME = "pack_integrity_evidence.json"
DEFAULT_LOG_NAME = "helper_ft.log"
CHUNK = 1 << 20
SHA256_LEN = 64
_HEX = frozenset("0123456789abcdef")
_GATE_OK = object()

# (manifest sha field, on-disk file, optional row-count field, CLI / kick kwarg)
ARTIFACTS: tuple[tuple[str, str, str, str], ...] = (
    ("sha256_pack", PACK_FILE, "rows", "--expected-sha256-pack"),
    ("sha256_train", TRAIN_FILE, "train_rows", "--expected-sha256-train"),
    ("sha256_holdout", HOLDOUT_FILE, "holdout_rows", "--expected-sha256-holdout"),
)

_FORBIDDEN_SKIP_ENV = (
    "DOTTIE_SKIP_HELPER_FT_GATE",
    "HELPER_FT_SKIP_INTEGRITY",
    "SKIP_INTEGRITY",
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


def _refuse(field: str, expected: object, actual: object) -> NoReturn:
    raise KickRefused(field, expected, actual)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _open_flags_read() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _open_flags_write() -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def sha256_file(path: Path, chunk: int = CHUNK) -> str:
    """Streaming SHA-256 of file bytes. Never hashes a hardcoded string."""
    digest = hashlib.sha256()
    fd = os.open(path, _open_flags_read())
    try:
        while True:
            block = os.read(fd, chunk)
            if not block:
                break
            digest.update(block)
    finally:
        os.close(fd)
    return digest.hexdigest()


def count_rows(path: Path) -> int:
    with path.open(encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _require_sha256_hex(field: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        _refuse(field, "present", "missing")
    lowered = value.strip().lower()
    if len(lowered) != SHA256_LEN or any(ch not in _HEX for ch in lowered):
        _refuse(field, "64-char hex", value)
    return lowered


def _refuse_skip_env() -> None:
    for name in _FORBIDDEN_SKIP_ENV:
        value = os.environ.get(name)
        if value:
            _refuse(name, "unset", value)


def _resolve_pack_dir(pack_dir: Path) -> Path:
    if pack_dir.is_symlink():
        _refuse("--pack", "real directory", "symlink")
    if not pack_dir.exists():
        _refuse("--pack", "present", "missing")
    if not pack_dir.is_dir():
        _refuse("--pack", "directory", "not a directory")
    return Path(os.path.realpath(pack_dir))


def _contained_in(root: Path, path: Path) -> bool:
    root_real = os.path.realpath(root)
    path_real = os.path.realpath(path)
    try:
        Path(path_real).relative_to(root_real)
    except ValueError:
        return False
    return True


def _regular_file_in_pack(pack_root: Path, filename: str) -> Path:
    """Refuse nested names, symlinks, non-regular files, and escapes."""
    if Path(filename).name != filename or not filename or filename in (".", ".."):
        _refuse(filename, "basename inside pack dir", filename)
    raw = pack_root / filename
    try:
        info = os.lstat(raw)
    except FileNotFoundError:
        _refuse(filename, "present", "missing")
    if stat.S_ISLNK(info.st_mode):
        _refuse(filename, "regular file", "symlink")
    if not stat.S_ISREG(info.st_mode):
        _refuse(filename, "regular file", "non-regular")
    if not _contained_in(pack_root, raw):
        _refuse(filename, f"inside {os.path.realpath(pack_root)}", os.path.realpath(raw))
    return raw


def _copy_and_hash(src: Path, dest: Path, field: str) -> str:
    """Open with O_NOFOLLOW, hash the stream while writing a private copy."""
    try:
        fd = os.open(src, _open_flags_read())
    except OSError as exc:
        if getattr(exc, "errno", None) in (errno.ELOOP, getattr(errno, "EPERM", None)):
            _refuse(field, "regular file", "symlink")
        raise
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            _refuse(field, "regular file", "non-regular")
        digest = hashlib.sha256()
        out_fd = os.open(dest, _open_flags_write(), 0o600)
        try:
            while True:
                block = os.read(fd, CHUNK)
                if not block:
                    break
                digest.update(block)
                os.write(out_fd, block)
        finally:
            os.close(out_fd)
        return digest.hexdigest()
    finally:
        os.close(fd)


def _read_manifest(pack_dir: Path) -> dict[str, Any]:
    manifest_path = _regular_file_in_pack(pack_dir, MANIFEST_FILE)
    fd = os.open(manifest_path, _open_flags_read())
    try:
        chunks: list[bytes] = []
        while True:
            block = os.read(fd, CHUNK)
            if not block:
                break
            chunks.append(block)
        raw = b"".join(chunks)
    finally:
        os.close(fd)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        _refuse(MANIFEST_FILE, "valid JSON object", f"invalid JSON ({exc})")
    if not isinstance(payload, dict):
        _refuse(MANIFEST_FILE, "valid JSON object", type(payload).__name__)
    return payload


def _anchors_from_kwargs(
    expected_sha256_pack: str | None,
    expected_sha256_train: str | None,
    expected_sha256_holdout: str | None,
) -> dict[str, str]:
    values = {
        "--expected-sha256-pack": expected_sha256_pack,
        "--expected-sha256-train": expected_sha256_train,
        "--expected-sha256-holdout": expected_sha256_holdout,
    }
    return {field: _require_sha256_hex(field, value) for field, value in values.items()}


def verify_and_stage(
    pack_dir: Path,
    *,
    expected_sha256_pack: str | None,
    expected_sha256_train: str | None,
    expected_sha256_holdout: str | None,
    anchor_source: str | None,
    run_private: Path,
) -> dict[str, Any]:
    """Copy-hash pack/train/holdout into ``run_private`` and check CLI anchors.

    Returns evidence on success. Raises KickRefused on any failure. Does not
    start training.
    """
    _refuse_skip_env()
    if not isinstance(anchor_source, str) or not anchor_source.strip():
        _refuse("--anchor-source", "present", "missing")
    anchors = _anchors_from_kwargs(
        expected_sha256_pack, expected_sha256_train, expected_sha256_holdout
    )
    pack_root = _resolve_pack_dir(Path(pack_dir))
    run_private = Path(run_private)
    run_private.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(run_private, 0o700)
    except OSError:
        if os.name != "nt":
            raise

    manifest_dest = run_private / MANIFEST_FILE
    _copy_and_hash(_regular_file_in_pack(pack_root, MANIFEST_FILE), manifest_dest, MANIFEST_FILE)
    manifest = _read_manifest(run_private)
    computed_shas: dict[str, str] = {}
    manifest_shas: dict[str, str] = {}
    row_counts: dict[str, dict[str, int | None]] = {}

    for sha_field, filename, rows_field, cli_field in ARTIFACTS:
        src = _regular_file_in_pack(pack_root, filename)
        dest = run_private / filename
        computed = _copy_and_hash(src, dest, sha_field)
        manifest_value = manifest.get(sha_field)
        if not isinstance(manifest_value, str) or not manifest_value:
            _refuse(sha_field, "present", "missing")
        manifest_sha = _require_sha256_hex(sha_field, manifest_value)
        anchor = anchors[cli_field]
        if anchor != manifest_sha:
            _refuse(sha_field, anchor, manifest_sha)
        if anchor != computed:
            _refuse(sha_field, anchor, computed)
        computed_shas[sha_field] = computed
        manifest_shas[sha_field] = manifest_sha

        actual_rows = count_rows(dest)
        expected_rows: int | None
        if rows_field in manifest:
            raw_rows = manifest[rows_field]
            try:
                expected_rows = int(raw_rows)
            except (TypeError, ValueError):
                _refuse(rows_field, "integer row count", raw_rows)
            if actual_rows != expected_rows:
                _refuse(rows_field, expected_rows, actual_rows)
        else:
            expected_rows = None
        row_counts[filename] = {"expected": expected_rows, "actual": actual_rows}

    pack_id = manifest.get("pack_id")
    if not isinstance(pack_id, str) or not pack_id:
        pack_id = pack_root.name

    return {
        "pack_id": pack_id,
        "host": socket.gethostname(),
        "anchor_source": anchor_source.strip(),
        "computed_shas": computed_shas,
        "expected_shas": {
            "sha256_pack": anchors["--expected-sha256-pack"],
            "sha256_train": anchors["--expected-sha256-train"],
            "sha256_holdout": anchors["--expected-sha256-holdout"],
        },
        "manifest_shas": manifest_shas,
        "row_counts": row_counts,
        "run_private_dir": str(run_private),
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
    """Public alias that always refuses: the train hook is not a skip path."""
    _refuse("start_training", "via kick() after integrity gate", "direct call")


def _authorized_start_training(
    pack_dir: Path,
    evidence: dict[str, Any],
    log_path: Path,
    *,
    _gate: object,
) -> dict[str, Any]:
    if _gate is not _GATE_OK:
        _refuse("start_training", "via kick() after integrity gate", "direct call")
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = (
        f"{evidence['checked_at']} HELPER_FT_KICK allowed "
        f"pack_id={evidence['pack_id']} host={evidence['host']} "
        f"anchor_source={evidence['anchor_source']} auto_promote=false "
        f"inputs={pack_dir}\n"
    )
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line)
    return {"training_started": True, "auto_promote": False, "pack_dir": str(pack_dir)}


def kick(
    pack_dir: Path,
    *,
    expected_sha256_pack: str | None = None,
    expected_sha256_train: str | None = None,
    expected_sha256_holdout: str | None = None,
    anchor_source: str | None = None,
    log_path: Path | None = None,
    start_training: StartTraining | None = None,
) -> dict[str, Any]:
    """Verify CLI anchors, stage private copies, then start HELPER training.

    ``start_training`` is a test/injection hook and still runs only after the
    gate. It receives the run-private copy directory, never the original paths.
    CLI and env cannot supply it. There is no skip/override.
    """
    pack_dir = Path(pack_dir)
    log_path = Path(log_path) if log_path is not None else pack_dir / DEFAULT_LOG_NAME
    log_path.parent.mkdir(parents=True, exist_ok=True)
    run_private = Path(tempfile.mkdtemp(prefix="helper-ft-", dir=str(log_path.parent)))
    try:
        os.chmod(run_private, 0o700)
    except OSError:
        if os.name != "nt":
            raise
    evidence = dict(
        verify_and_stage(
            pack_dir,
            expected_sha256_pack=expected_sha256_pack,
            expected_sha256_train=expected_sha256_train,
            expected_sha256_holdout=expected_sha256_holdout,
            anchor_source=anchor_source,
            run_private=run_private,
        )
    )
    evidence_path = log_path.parent / EVIDENCE_NAME
    evidence["evidence_path"] = str(evidence_path)
    write_evidence(evidence, log_path)
    if start_training is None:
        _authorized_start_training(run_private, evidence, log_path, _gate=_GATE_OK)
    else:
        start_training(run_private, evidence, log_path)
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
    parser.add_argument(
        "--expected-sha256-pack",
        default=None,
        help="trust-anchor SHA-256 of curated_pack_v2.jsonl (ticket or Mill-signed HQ record)",
    )
    parser.add_argument(
        "--expected-sha256-train",
        default=None,
        help="trust-anchor SHA-256 of curated_pack_v2_train.jsonl",
    )
    parser.add_argument(
        "--expected-sha256-holdout",
        default=None,
        help="trust-anchor SHA-256 of curated_pack_v2_holdout.jsonl",
    )
    parser.add_argument(
        "--anchor-source",
        default=None,
        help="where the CLI hashes came from, e.g. ticket or mill-signed-swarm-hq",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = kick(
            args.pack,
            expected_sha256_pack=args.expected_sha256_pack,
            expected_sha256_train=args.expected_sha256_train,
            expected_sha256_holdout=args.expected_sha256_holdout,
            anchor_source=args.anchor_source,
            log_path=args.log,
        )
    except KickRefused as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1
    print(json.dumps(evidence, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
