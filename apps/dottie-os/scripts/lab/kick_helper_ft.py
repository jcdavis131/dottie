#!/usr/bin/env python3
"""Stage-5 HELPER factory-trainer kick: point-of-use pack integrity, then kickoff.

Trust comes from CLI anchors (``--expected-sha256-pack`` / ``-train`` /
``-holdout``) taken from the Mill-signed Swarm HQ pack record or the ticket,
not from MANIFEST.json alone. Those anchors must match both MANIFEST.json and
the bytes copied into a run-private directory. Rewriting the pack and the
MANIFEST together on the host still fails.

After the gate passes, this script POSTs ``/train/kickoff`` itself with the
named pack_id, shas, run-private paths and evidence. It never sends
``inbox: latest``. Copies are re-hashed after kickoff; a mismatch sets
``ok: false``.

There is no skip flag or skip env var. Does not promote, does not touch serve,
:8770, champion files, or the LIVE gate.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, NoReturn

PACK_FILE = "curated_pack_v2.jsonl"
TRAIN_FILE = "curated_pack_v2_train.jsonl"
HOLDOUT_FILE = "curated_pack_v2_holdout.jsonl"
MANIFEST_FILE = "MANIFEST.json"
DEFAULT_LOG_NAME = "helper_ft.log"
DEFAULT_KICKOFF_URL = "http://127.0.0.1:8765/train/kickoff"
CHUNK = 1 << 20
SHA256_LEN = 64
_HEX = frozenset("0123456789abcdef")
_GATE_OK = object()

# (manifest sha field, on-disk file, required row-count field, CLI / kick kwarg)
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
KickoffFn = Callable[[dict[str, Any]], Any]


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


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"helper-ft-{stamp}-{uuid.uuid4().hex[:8]}"


def _script_git_sha() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except OSError:
        return None
    sha = proc.stdout.strip()
    return sha if proc.returncode == 0 and sha else None


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
    try:
        fd = os.open(path, _open_flags_read())
    except OSError as exc:
        _refuse(path.name, "readable regular file", f"OSError:{exc.errno}")
    try:
        while True:
            block = os.read(fd, chunk)
            if not block:
                break
            digest.update(block)
    except OSError as exc:
        _refuse(path.name, "readable regular file", f"OSError:{exc.errno}")
    finally:
        os.close(fd)
    return digest.hexdigest()


def count_rows(path: Path) -> int:
    try:
        with path.open(encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except UnicodeDecodeError:
        _refuse(path.name, "utf-8 text", "invalid encoding")
    except OSError as exc:
        _refuse(path.name, "readable text file", f"OSError:{exc.errno}")


def _require_sha256_hex(field: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        _refuse(field, "present", "missing")
    lowered = value.strip().lower()
    if len(lowered) != SHA256_LEN or any(ch not in _HEX for ch in lowered):
        _refuse(field, "64-char hex", value)
    return lowered


def _require_int(field: str, value: object) -> int:
    if type(value) is not int:
        label = "bool" if isinstance(value, bool) else type(value).__name__
        _refuse(field, "int", label)
    return value


def _refuse_skip_env() -> None:
    for name in _FORBIDDEN_SKIP_ENV:
        value = os.environ.get(name)
        if value:
            _refuse(name, "unset", value)


def _resolve_pack_dir(pack_dir: Path) -> Path:
    try:
        if pack_dir.is_symlink():
            _refuse("--pack", "real directory", "symlink")
        if not pack_dir.exists():
            _refuse("--pack", "present", "missing")
        if not pack_dir.is_dir():
            _refuse("--pack", "directory", "not a directory")
        return Path(os.path.realpath(pack_dir))
    except OSError as exc:
        _refuse("--pack", "readable directory", f"OSError:{exc.errno}")


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
    except OSError as exc:
        _refuse(filename, "readable regular file", f"OSError:{exc.errno}")
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
        _refuse(field, "readable regular file", f"OSError:{exc.errno}")
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            _refuse(field, "regular file", "non-regular")
        digest = hashlib.sha256()
        try:
            out_fd = os.open(dest, _open_flags_write(), 0o600)
        except OSError as exc:
            _refuse(field, "writable copy", f"OSError:{exc.errno}")
        try:
            while True:
                block = os.read(fd, CHUNK)
                if not block:
                    break
                digest.update(block)
                os.write(out_fd, block)
        except OSError as exc:
            _refuse(field, "readable regular file", f"OSError:{exc.errno}")
        finally:
            os.close(out_fd)
        return digest.hexdigest()
    finally:
        os.close(fd)


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            _refuse(MANIFEST_FILE, "unique keys", f"duplicate {key}")
        seen[key] = value
    return seen


def _read_manifest(pack_dir: Path) -> dict[str, Any]:
    manifest_path = _regular_file_in_pack(pack_dir, MANIFEST_FILE)
    try:
        fd = os.open(manifest_path, _open_flags_read())
    except OSError as exc:
        _refuse(MANIFEST_FILE, "readable regular file", f"OSError:{exc.errno}")
    try:
        chunks: list[bytes] = []
        while True:
            block = os.read(fd, CHUNK)
            if not block:
                break
            chunks.append(block)
        raw = b"".join(chunks)
    except OSError as exc:
        _refuse(MANIFEST_FILE, "readable regular file", f"OSError:{exc.errno}")
    finally:
        os.close(fd)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _refuse(MANIFEST_FILE, "utf-8 text", "invalid encoding")
    try:
        payload = json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except KickRefused:
        raise
    except ValueError as exc:
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


def _line_identities(path: Path, field: str) -> tuple[list[str], list[str]]:
    hashes: list[str] = []
    ids: list[str] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                hashes.append(hashlib.sha256(line.encode("utf-8")).hexdigest())
                try:
                    obj = json.loads(line)
                except ValueError:
                    _refuse(field, "jsonl row", "invalid JSON")
                if isinstance(obj, dict):
                    tid = obj.get("trajectory_id", obj.get("id"))
                    if isinstance(tid, str) and tid:
                        ids.append(tid)
    except UnicodeDecodeError:
        _refuse(field, "utf-8 text", "invalid encoding")
    except OSError as exc:
        _refuse(field, "readable text file", f"OSError:{exc.errno}")
    return hashes, ids


def _split_soundness(run_private: Path, computed_shas: Mapping[str, str]) -> None:
    if computed_shas["sha256_train"] == computed_shas["sha256_holdout"]:
        _refuse("split", "train and holdout distinct", "identical")
    pack_h, pack_ids = _line_identities(run_private / PACK_FILE, PACK_FILE)
    train_h, train_ids = _line_identities(run_private / TRAIN_FILE, TRAIN_FILE)
    hold_h, hold_ids = _line_identities(run_private / HOLDOUT_FILE, HOLDOUT_FILE)
    leaked_hash = set(train_h) & set(hold_h)
    if leaked_hash:
        _refuse("split", "holdout disjoint from train", f"row-hash leak n={len(leaked_hash)}")
    leaked_id = set(train_ids) & set(hold_ids)
    if leaked_id:
        sample = ",".join(sorted(leaked_id)[:3])
        _refuse("split", "holdout disjoint from train", f"trajectory_id leak {sample}")
    if Counter(pack_h) != Counter(train_h) + Counter(hold_h):
        _refuse("split", "pack == train ∪ holdout", "row-set mismatch")


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

    Returns evidence fields on success. Raises KickRefused on any failure. Does not
    start training or POST kickoff.
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
    pack_id = manifest.get("pack_id")
    if not isinstance(pack_id, str) or not pack_id.strip():
        _refuse("pack_id", "present", "missing")
    if manifest.get("champion_touched") is not False:
        _refuse("champion_touched", False, manifest.get("champion_touched"))

    computed_shas: dict[str, str] = {}
    manifest_shas: dict[str, str] = {}
    row_counts: dict[str, dict[str, int]] = {}
    abs_paths: dict[str, str] = {}

    for sha_field, filename, rows_field, cli_field in ARTIFACTS:
        src = _regular_file_in_pack(pack_root, filename)
        dest = run_private / filename
        computed = _copy_and_hash(src, dest, sha_field)
        if rows_field not in manifest:
            _refuse(rows_field, "present", "missing")
        expected_rows = _require_int(rows_field, manifest[rows_field])
        actual_rows = count_rows(dest)
        if actual_rows != expected_rows:
            _refuse(rows_field, expected_rows, actual_rows)
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
        row_counts[filename] = {"expected": expected_rows, "actual": actual_rows}

    abs_paths = {
        "pack": str((run_private / PACK_FILE).resolve()),
        "train": str((run_private / TRAIN_FILE).resolve()),
        "holdout": str((run_private / HOLDOUT_FILE).resolve()),
        "manifest": str((run_private / MANIFEST_FILE).resolve()),
        "run_private_dir": str(run_private.resolve()),
        "pack_dir": str(pack_root),
    }
    _split_soundness(run_private, computed_shas)

    return {
        "pack_id": pack_id.strip(),
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
        "paths": abs_paths,
        "run_private_dir": str(run_private.resolve()),
        "checked_at": _utc_now(),
        "ok": True,
    }


def write_evidence(evidence: Mapping[str, Any], evidence_path: Path) -> Path:
    """Atomically write evidence JSON (temp file + os.replace)."""
    evidence_path = Path(evidence_path)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = evidence_path.with_name(evidence_path.name + f".{os.getpid()}.tmp")
    payload = (json.dumps(dict(evidence), indent=2) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    fd = os.open(tmp, flags, 0o600)
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)
    os.replace(tmp, evidence_path)
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
        f"run_id={evidence.get('run_id')} anchor_source={evidence['anchor_source']} "
        f"auto_promote=false inputs={pack_dir}\n"
    )
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line)
    return {"training_started": True, "auto_promote": False, "pack_dir": str(pack_dir)}


def post_kickoff(body: dict[str, Any], url: str = DEFAULT_KICKOFF_URL) -> dict[str, Any]:
    """POST the HELPER FT kickoff. Tests mock this; production hits :8765."""
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        _refuse("kickoff", "HTTP success", str(exc.reason) if getattr(exc, "reason", None) else str(exc))
    except OSError as exc:
        _refuse("kickoff", "HTTP success", f"OSError:{getattr(exc, 'errno', None)}")
    try:
        result = json.loads(raw) if raw else {}
    except ValueError:
        _refuse("kickoff", "JSON object", "invalid JSON")
    if not isinstance(result, dict) or result.get("ok") is not True:
        _refuse("kickoff", "ok", result)
    return result


def _recheck_copies(run_private: Path, evidence: dict[str, Any]) -> None:
    post: dict[str, str] = {}
    for sha_field, filename, _rows, _cli in ARTIFACTS:
        actual = sha256_file(run_private / filename)
        post[sha_field] = actual
        expected = evidence["computed_shas"][sha_field]
        if actual != expected:
            evidence["ok"] = False
            evidence["post_train_shas"] = post
            _refuse(sha_field, expected, actual)
    evidence["post_train_shas"] = post


def kick(
    pack_dir: Path,
    *,
    expected_sha256_pack: str | None = None,
    expected_sha256_train: str | None = None,
    expected_sha256_holdout: str | None = None,
    anchor_source: str | None = None,
    log_path: Path | None = None,
    start_training: StartTraining | None = None,
    kickoff: KickoffFn | None = None,
    kickoff_url: str = DEFAULT_KICKOFF_URL,
) -> dict[str, Any]:
    """Verify CLI anchors, stage private copies, POST kickoff, re-check shas.

    ``start_training`` / ``kickoff`` are test injection hooks and still run only
    after the gate. CLI and env cannot supply them. There is no skip/override.
    """
    pack_dir = Path(pack_dir)
    run_id = _new_run_id()
    if log_path is not None:
        log_path = Path(log_path)
        run_dir = log_path.parent
    else:
        run_dir = Path(tempfile.mkdtemp(prefix=f"{run_id}-"))
        log_path = run_dir / DEFAULT_LOG_NAME
    run_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = run_dir / f"pack_integrity_evidence_{run_id}.json"
    run_private = Path(tempfile.mkdtemp(prefix="inputs-", dir=str(run_dir)))
    try:
        os.chmod(run_private, 0o700)
    except OSError:
        if os.name != "nt":
            raise
    evidence: dict[str, Any] = {
        "ok": False,
        "run_id": run_id,
        "checkpoint_id": None,
        "script_git_sha": _script_git_sha(),
        "host": socket.gethostname(),
        "anchor_source": anchor_source,
        "evidence_path": str(evidence_path.resolve()),
        "checked_at": _utc_now(),
    }

    def persist() -> None:
        write_evidence(evidence, evidence_path)

    try:
        staged = verify_and_stage(
            pack_dir,
            expected_sha256_pack=expected_sha256_pack,
            expected_sha256_train=expected_sha256_train,
            expected_sha256_holdout=expected_sha256_holdout,
            anchor_source=anchor_source,
            run_private=run_private,
        )
        evidence.update(staged)
        evidence["run_id"] = run_id
        evidence["checkpoint_id"] = None
        evidence["script_git_sha"] = evidence.get("script_git_sha") or _script_git_sha()
        evidence["evidence_path"] = str(evidence_path.resolve())
        persist()
        body = {
            "mode": "helper-ft",
            "pack_id": evidence["pack_id"],
            "sha256_pack": evidence["computed_shas"]["sha256_pack"],
            "sha256_train": evidence["computed_shas"]["sha256_train"],
            "sha256_holdout": evidence["computed_shas"]["sha256_holdout"],
            "run_private_dir": evidence["run_private_dir"],
            "paths": evidence["paths"],
            "evidence": dict(evidence),
            "evidence_path": evidence["evidence_path"],
            "run_id": run_id,
        }
        if kickoff is not None:
            result = kickoff(body)
        else:
            result = post_kickoff(body, url=kickoff_url)
        if isinstance(result, dict) and result.get("checkpoint_id"):
            evidence["checkpoint_id"] = result["checkpoint_id"]
            persist()
        if start_training is None:
            _authorized_start_training(run_private, evidence, log_path, _gate=_GATE_OK)
        else:
            start_training(run_private, evidence, log_path)
        _recheck_copies(run_private, evidence)
        persist()
        return evidence
    except KickRefused as exc:
        evidence["ok"] = False
        evidence["field"] = exc.field
        evidence["expected"] = exc.expected
        evidence["actual"] = exc.actual
        try:
            persist()
        except OSError:
            pass
        raise
    except Exception as exc:
        evidence["ok"] = False
        evidence["field"] = "kickoff"
        evidence["expected"] = "success"
        evidence["actual"] = f"{type(exc).__name__}: {exc}"
        try:
            persist()
        except OSError:
            pass
        _refuse("kickoff", "success", f"{type(exc).__name__}: {exc}")


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
        help="run log path; evidence JSON is written in that run directory",
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
    parser.add_argument(
        "--kickoff-url",
        default=DEFAULT_KICKOFF_URL,
        help="HELPER FT POST /train/kickoff URL (default 127.0.0.1:8765)",
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
            kickoff_url=args.kickoff_url,
        )
    except KickRefused as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1
    print(json.dumps(evidence, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
