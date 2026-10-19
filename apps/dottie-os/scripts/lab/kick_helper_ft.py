#!/usr/bin/env python3
"""Stage-5 HELPER factory-trainer kick: point-of-use pack integrity, then kickoff.

The trust anchor is Cam's Ed25519 signature over the canonical pin bytes
(see ``cam_pin_spec.py``), verified against the public key committed at
``apps/dottie-os/trust/cam_pin_ed25519.pub``. Swarm HQ is only a transport:
``stampVerified`` and ``pack_matches`` are advisory and never sufficient.
The HQ origin is the hardcoded ``cam_pin_spec.SWARM_HQ_ORIGIN`` (HTTPS, no
redirects, no proxies). There is no ``SWARM_HQ_URL`` env, CLI, or config
override. Redis is never read.

This process hashes and counts the run-private copies itself and compares
those to the signed pin and MANIFEST. ``--cam-pin``, a pin env var, and a
local pin file are refused before hashing or kickoff. After the gate
passes, this script POSTs ``/train/kickoff``; ``inbox: latest`` is never
sent. Copies are 0400 in a 0700 directory. The trainer is passed only those
run-dir copy paths (no source-pack fallback). The same process on the
training host waits for the trainer to exit, then re-hashes those recorded
paths. Completion ``result`` and ``sha256_evidence`` come from the 0400
evidence file this process wrote, never from scraped stdout. Nonzero trainer
exit, a signal, or a timeout is ``REFUSED`` even when hashes match. This
process POSTs a kick event and a completion event to the pinned HQ origin.

There is no skip flag or skip env var. Does not promote, does not touch serve,
:8770, champion files, or the LIVE gate.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import shutil
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

_LAB = str(Path(__file__).resolve().parent)
if _LAB not in sys.path:
    sys.path.insert(0, _LAB)

import cam_pin_spec

PACK_FILE = "curated_pack_v2.jsonl"
TRAIN_FILE = "curated_pack_v2_train.jsonl"
HOLDOUT_FILE = "curated_pack_v2_holdout.jsonl"
MANIFEST_FILE = "MANIFEST.json"
DEFAULT_LOG_NAME = "helper_ft.log"
DEFAULT_KICKOFF_URL = "http://127.0.0.1:8765/train/kickoff"
SWARM_HQ_AGENT_TOKEN_ENV = cam_pin_spec.SWARM_HQ_AGENT_TOKEN_ENV
PIN_SOURCE = "swarm-hq-cam-pin"
HQ_PIN_REQUIRED_KEYS = cam_pin_spec.HQ_PIN_REQUIRED_KEYS
HQ_PIN_ALLOWED_KEYS = cam_pin_spec.HQ_PIN_ALLOWED_KEYS
CHUNK = 1 << 20
SHA256_LEN = 64
_HEX = frozenset("0123456789abcdef")
_GATE_OK = object()
TRAINER_PATH_FILES: dict[str, str] = {
    "pack": PACK_FILE,
    "train": TRAIN_FILE,
    "holdout": HOLDOUT_FILE,
    "manifest": MANIFEST_FILE,
}
PATH_KEY_BY_SHA = {
    "sha256_pack": "pack",
    "sha256_train": "train",
    "sha256_holdout": "holdout",
}
INTEGRITY_EVIDENCE_NAME = "integrity_evidence.json"
INTEGRITY_EVIDENCE_LINE_PREFIX = "HELPER_FT_INTEGRITY_EVIDENCE"
CHECKPOINT_MATCH = "MATCH"
CHECKPOINT_REFUSED = "REFUSED"
CHECKPOINT_UNSCORED = "unscored"
STATE_LEAK_KEYS = frozenset(
    {"risk_hint", "halt_class", "provenance", "agent_config", "category"}
)
# The 20261018-185133 pack (sha256_pack a73c792f…) put gold labels in
# state.meta.risk_hint on all 60 L3 rows. Refuse those keys at any depth.
INBOX_LATEST_TOKENS = frozenset(
    {"latest", "inbox_latest", "inbox-latest", "inbox:latest"}
)
INBOX_LATEST_PATH_MARKERS = (
    "inbox_latest",
    "inbox-latest",
    "inbox:latest",
    "20260919-093515-host-meta",
)
LIVE_INBOX_LATEST_DIR = "runs/inbox/20260919-093515-host-meta"

# (manifest sha field, on-disk file, MANIFEST row field, pin row field)
ARTIFACTS: tuple[tuple[str, str, str, str], ...] = (
    ("sha256_pack", PACK_FILE, "rows", "rows_total"),
    ("sha256_train", TRAIN_FILE, "train_rows", "rows_train"),
    ("sha256_holdout", HOLDOUT_FILE, "holdout_rows", "rows_holdout"),
)

_FORBIDDEN_SKIP_ENV = (
    "DOTTIE_SKIP_HELPER_FT_GATE",
    "HELPER_FT_SKIP_INTEGRITY",
    "SKIP_INTEGRITY",
)
_FORBIDDEN_PIN_ENV = (
    "CAM_PIN",
    "HELPER_FT_CAM_PIN",
    "DOTTIE_CAM_PIN",
    "SWARM_HQ_PIN",
)
_FORBIDDEN_PIN_FILES = (
    "cam-pin.json",
    "cam_pin.json",
    "pin.json",
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


def _script_sha256() -> str:
    return sha256_file(Path(__file__).resolve())


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
    try:
        return cam_pin_spec.require_sha256_hex(field, value)
    except cam_pin_spec.CamPinError as exc:
        _refuse(exc.field, exc.expected, exc.actual)


def _require_int(field: str, value: object) -> int:
    try:
        return cam_pin_spec.require_int(field, value)
    except cam_pin_spec.CamPinError as exc:
        _refuse(exc.field, exc.expected, exc.actual)
        raise AssertionError("unreachable") from exc


def _refuse_skip_env() -> None:
    for name in _FORBIDDEN_SKIP_ENV:
        value = os.environ.get(name)
        if value:
            _refuse(name, "unset", value)


def _refuse_pin_env() -> None:
    """A pin env var is a paste path. Refuse before hashing or kickoff."""
    for name in _FORBIDDEN_PIN_ENV:
        if os.environ.get(name):
            _refuse(name, "unset", "set")


def _refuse_local_pin_files(pack_root: Path) -> None:
    """A local pin file is a paste path. Refuse before hashing or kickoff."""
    for filename in _FORBIDDEN_PIN_FILES:
        path = pack_root / filename
        try:
            present = os.path.lexists(path)
        except OSError as exc:
            _refuse(filename, "absent", f"OSError:{exc.errno}")
        if present:
            _refuse(filename, "absent", "local pin file")


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
        try:
            os.chmod(dest, 0o400)
        except OSError:
            if os.name != "nt":
                raise
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


def _no_duplicate_hq_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            _refuse("cam-pin", "unique keys", f"duplicate {key}")
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


def _require_cam_pin(record: object, pack_id: str) -> dict[str, Any]:
    """Bind the verified Cam-signed pin to this pack_id. Exact match, no strip."""
    if not isinstance(record, dict) or not record:
        _refuse("cam-pin", "present", "missing")
    pin_pack = record.get("pack_id")
    if type(pin_pack) is not str or not pin_pack:
        _refuse("cam-pin.pack_id", "present", "missing")
    if pin_pack != pack_id:
        _refuse("cam-pin.pack_id", pack_id, pin_pack)
    pin: dict[str, Any] = {
        "pack_id": pack_id,
        "source": PIN_SOURCE,
        "recordedAt": record.get("recordedAt"),
        "kid": record.get("kid"),
        "cam_key_id": record.get("cam_key_id"),
        "cam_sig": record.get("cam_sig"),
    }
    if "recordedBy" in record:
        pin["recordedBy"] = record["recordedBy"]
    if "stampVerified" in record:
        pin["stampVerified"] = record["stampVerified"]
    if "pack_matches" in record:
        pin["pack_matches"] = record["pack_matches"]
    for sha_field, _filename, _manifest_rows, pin_rows in ARTIFACTS:
        pin[sha_field] = _require_sha256_hex(f"cam-pin.{sha_field}", record.get(sha_field))
        pin[pin_rows] = _require_int(f"cam-pin.{pin_rows}", record.get(pin_rows))
    return pin


def _parse_hq_pin_payload(payload: object) -> dict[str, Any]:
    try:
        return cam_pin_spec.parse_hq_pin_payload(payload)
    except cam_pin_spec.CamPinError as exc:
        _refuse(exc.field, exc.expected, exc.actual)


def fetch_cam_pin(pack_id: str) -> dict[str, Any]:
    """GET the pinned-origin pin and verify Cam's Ed25519 signature. Never Redis."""
    if type(pack_id) is not str or not pack_id:
        _refuse("pack_id", "present", "missing")
    try:
        return cam_pin_spec.fetch_signed_pin(pack_id)
    except cam_pin_spec.CamPinError as exc:
        _refuse(exc.field, exc.expected, exc.actual)


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


def trainer_input_paths(run_private: Path) -> dict[str, str]:
    """Resolved absolute run-dir copy paths. These are the trainer inputs."""
    root = Path(run_private).resolve()
    return {key: str((root / name).resolve()) for key, name in TRAINER_PATH_FILES.items()}


def build_trainer_argv(paths: Mapping[str, str]) -> list[str]:
    return [
        "--pack",
        paths["pack"],
        "--train",
        paths["train"],
        "--holdout",
        paths["holdout"],
        "--manifest",
        paths["manifest"],
    ]


def is_smoke_mode(body: Mapping[str, Any] | None, *, smoke: bool = False) -> bool:
    if smoke:
        return True
    if not isinstance(body, Mapping):
        return False
    if body.get("smoke") is True:
        return True
    return body.get("mode") == "helper-ft-smoke"


def _is_not_for_train_value(value: object) -> bool:
    return value is True or value == 1 or value == "true"


def _iter_jsonl_objects(path: Path, field: str):
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    _refuse(field, "jsonl row", "invalid JSON")
                if isinstance(obj, dict):
                    yield obj
    except UnicodeDecodeError:
        _refuse(field, "utf-8 text", "invalid encoding")
    except OSError as exc:
        _refuse(field, "readable text file", f"OSError:{exc.errno}")


def _row_id(obj: Mapping[str, Any]) -> str:
    for key in ("id", "trajectory_id"):
        value = obj.get(key)
        if isinstance(value, str) and value:
            return value
    return "?"


def collect_not_for_train(
    manifest: Mapping[str, Any],
    recorded_paths: Mapping[str, str],
) -> list[str]:
    hits: list[str] = []
    if _is_not_for_train_value(manifest.get("not_for_train")):
        hits.append("MANIFEST.not_for_train")
    for key in ("pack", "train", "holdout"):
        raw = recorded_paths.get(key)
        if type(raw) is not str or not raw:
            continue
        path = Path(raw)
        field = path.name
        for obj in _iter_jsonl_objects(path, field):
            if _is_not_for_train_value(obj.get("not_for_train")):
                hits.append(f"{field}:{_row_id(obj)}.not_for_train")
    return hits


def _walk_state_leaks(
    value: object,
    *,
    path: str,
    row_id: str,
    found: list[str],
    seen: set[str],
) -> None:
    if len(found) >= 10:
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_s = str(key)
            child_path = f"{path}.{key_s}"
            if key_s in STATE_LEAK_KEYS:
                item = f"{row_id}:{child_path}"
                if item not in seen:
                    seen.add(item)
                    found.append(item)
                    if len(found) >= 10:
                        return
            _walk_state_leaks(
                child, path=child_path, row_id=row_id, found=found, seen=seen
            )
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _walk_state_leaks(
                child, path=f"{path}[{idx}]", row_id=row_id, found=found, seen=seen
            )


def collect_state_leaks(recorded_paths: Mapping[str, str]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for key in ("pack", "train", "holdout"):
        raw = recorded_paths.get(key)
        if type(raw) is not str or not raw:
            continue
        path = Path(raw)
        for obj in _iter_jsonl_objects(path, path.name):
            _walk_state_leaks(
                obj.get("state"),
                path="state",
                row_id=_row_id(obj),
                found=found,
                seen=seen,
            )
            if len(found) >= 10:
                return found
    return found


def enforce_pack_gates(
    manifest: Mapping[str, Any],
    recorded_paths: Mapping[str, str],
    *,
    smoke: bool = False,
) -> None:
    hits = collect_not_for_train(manifest, recorded_paths)
    if hits and not smoke:
        _refuse("not_for_train", False, hits[:10])
    leaks = collect_state_leaks(recorded_paths)
    if leaks:
        _refuse("state.leak", "absent", leaks[:10])


def _looks_like_inbox_latest(value: str) -> bool:
    text = value.replace("\\", "/").lower().strip()
    compact = text.replace(" ", "")
    if text in INBOX_LATEST_TOKENS or compact in INBOX_LATEST_TOKENS:
        return True
    return any(marker.lower() in compact for marker in INBOX_LATEST_PATH_MARKERS)


def refuse_implicit_inbox_pack(pack_dir: Path | str) -> None:
    """CLI/kick must not resolve inbox:latest or the live default inbox dir."""
    raw = str(pack_dir)
    if _looks_like_inbox_latest(raw):
        _refuse("pack", "explicit pack path", raw)


def refuse_inbox_latest(body: Mapping[str, Any] | None) -> None:
    """Kickoff must take an explicit pack path plus a pin. No inbox:latest default."""
    if not isinstance(body, Mapping):
        return
    if "inbox_latest" in body:
        _refuse("inbox_latest", "absent", "present")
    inbox = body.get("inbox")
    if isinstance(inbox, str) and _looks_like_inbox_latest(inbox):
        _refuse("inbox", "named pack_id", inbox)
    if inbox is True:
        _refuse("inbox", "named pack_id", True)
    for key in ("run_private_dir", "pack_dir", "pack"):
        value = body.get(key)
        if isinstance(value, str) and _looks_like_inbox_latest(value):
            _refuse(key, "explicit pack path", value)
    paths = body.get("paths")
    if isinstance(paths, Mapping):
        for key, value in paths.items():
            if isinstance(value, str) and _looks_like_inbox_latest(value):
                _refuse(f"paths.{key}", "explicit pack path", value)


def _force_remove(path: Path) -> None:
    path = Path(path)
    if not os.path.lexists(path):
        return

    def _onerror(func: Any, name: str, _exc: object) -> None:
        try:
            os.chmod(name, 0o700)
            func(name)
        except OSError:
            pass

    try:
        if path.is_symlink() or path.is_file():
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            path.unlink()
            return
        shutil.rmtree(path, onerror=_onerror)
    except OSError:
        pass


def cleanup_smoke_artifacts(
    *,
    checkpoint_dir: Path | None,
    run_private: Path | None,
    inbox: Path | None,
) -> list[str]:
    """Delete smoke ckpt, run-dir copies, and inbox. Return surviving paths."""
    targets: list[tuple[str, Path]] = []
    if checkpoint_dir is not None:
        targets.append(("checkpoint", Path(checkpoint_dir)))
    if run_private is not None:
        targets.append(("run_private", Path(run_private)))
    if inbox is not None:
        targets.append(("inbox", Path(inbox)))
    survivors: list[str] = []
    for label, path in targets:
        _force_remove(path)
        if os.path.lexists(path):
            survivors.append(f"{label}:{path}")
    return survivors


def _empty_trainer_exit(*, waited: bool = False) -> dict[str, Any]:
    return {"exit_code": 0, "signal": None, "timeout": False, "waited": waited}


def _trainer_exit_is_bad(info: Mapping[str, Any]) -> bool:
    if info.get("timeout"):
        return True
    if info.get("signal") is not None:
        return True
    return info.get("exit_code", 0) not in (0,)


def combine_trainer_exits(parts: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Prefer the last waited trainer; any nonzero/signal/timeout wins as REFUSED."""
    recorded = _empty_trainer_exit()
    bad: dict[str, Any] | None = None
    for part in parts:
        if not isinstance(part, Mapping):
            continue
        slim = {
            "exit_code": part.get("exit_code", 0 if not part.get("timeout") else None),
            "signal": part.get("signal"),
            "timeout": bool(part.get("timeout")),
        }
        if part.get("waited"):
            recorded = slim
        if _trainer_exit_is_bad(slim):
            bad = slim
    return bad if bad is not None else recorded


def _wait_process(proc: Any, wait_timeout: object) -> Any:
    wait = proc.wait
    if wait_timeout is None:
        return wait()
    try:
        return wait(timeout=wait_timeout)
    except TypeError:
        return wait()


def _exit_from_wait_rc(rc: object) -> dict[str, Any]:
    if rc is None:
        return _empty_trainer_exit(waited=True)
    try:
        code = int(rc)
    except (TypeError, ValueError):
        _refuse("trainer.exit", "int exit_code", rc)
        raise AssertionError("unreachable")
    info = {"exit_code": code, "signal": None, "timeout": False, "waited": True}
    if code < 0:
        info["signal"] = -code
    return info


def wait_for_training_exit(launched: Mapping[str, Any] | None) -> dict[str, Any]:
    """Block until the trainer the launcher started has exited.

    Launchers that already wait (return after the process exits) are a no-op
    here. A pid or Popen-like ``process`` is waited in this same process.
    Returns ``exit_code`` / ``signal`` / ``timeout``. ``waited`` is True when
    this call observed a process, pid, or explicit launcher exit fields.
    """
    if not isinstance(launched, Mapping):
        return _empty_trainer_exit()
    waited_rc: object | None = None
    saw_process = False
    proc = launched.get("process")
    if proc is not None and hasattr(proc, "wait"):
        saw_process = True
        wait_timeout = launched.get("wait_timeout")
        try:
            waited_rc = _wait_process(proc, wait_timeout)
        except subprocess.TimeoutExpired:
            kill = getattr(proc, "kill", None)
            if callable(kill):
                try:
                    kill()
                    _wait_process(proc, None)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            return {"exit_code": None, "signal": None, "timeout": True, "waited": True}
        if waited_rc is None:
            waited_rc = getattr(proc, "returncode", None)
        # The process wait return code is the source of truth. A launcher dict
        # that also carries exit_code=0 must not hide a nonzero wait().
        return _exit_from_wait_rc(waited_rc)
    pid = launched.get("pid") if launched.get("pid") is not None else launched.get("trainer_pid")
    if pid is not None:
        try:
            _wpid, status = os.waitpid(int(pid), 0)
            del _wpid
            if os.WIFSIGNALED(status):
                sig = os.WTERMSIG(status)
                return {"exit_code": -sig, "signal": sig, "timeout": False, "waited": True}
            if os.WIFEXITED(status):
                return {
                    "exit_code": os.WEXITSTATUS(status),
                    "signal": None,
                    "timeout": False,
                    "waited": True,
                }
            return _exit_from_wait_rc(status)
        except ChildProcessError:
            pass
        except (TypeError, ValueError, OverflowError, OSError) as exc:
            _refuse("trainer.pid", "waitable pid", f"{type(exc).__name__}:{exc}")
    if launched.get("timeout") is True:
        return {
            "exit_code": launched.get("exit_code"),
            "signal": launched.get("signal"),
            "timeout": True,
            "waited": True,
        }
    if launched.get("signal") is not None:
        try:
            sig = int(launched["signal"])
        except (TypeError, ValueError):
            _refuse("trainer.exit", "signal number", launched.get("signal"))
            raise AssertionError("unreachable")
        code = launched.get("exit_code", -sig)
        try:
            code_i = int(code) if code is not None else -sig
        except (TypeError, ValueError):
            _refuse("trainer.exit", "int exit_code", code)
            raise AssertionError("unreachable")
        return {"exit_code": code_i, "signal": sig, "timeout": False, "waited": True}
    if "exit_code" in launched:
        code = launched.get("exit_code")
        try:
            code_i = int(code) if code is not None else 0
        except (TypeError, ValueError):
            _refuse("trainer.exit", "int exit_code", code)
            raise AssertionError("unreachable")
        info = {"exit_code": code_i, "signal": None, "timeout": False, "waited": True}
        if code_i < 0:
            info["signal"] = -code_i
        return info
    return _empty_trainer_exit()


def apply_trainer_exit(record: dict[str, Any], exit_info: Mapping[str, Any] | None) -> dict[str, Any]:
    """Record trainer exit on the integrity evidence. Bad exit forces REFUSED."""
    info = dict(exit_info) if isinstance(exit_info, Mapping) else _empty_trainer_exit()
    timeout = bool(info.get("timeout"))
    signal = info.get("signal")
    if signal is not None:
        try:
            signal = int(signal)
        except (TypeError, ValueError):
            _refuse("trainer.exit", "signal number", signal)
            raise AssertionError("unreachable")
    exit_code = info.get("exit_code")
    if timeout:
        pass
    elif exit_code is None:
        exit_code = 0
    else:
        try:
            exit_code = int(exit_code)
        except (TypeError, ValueError):
            _refuse("trainer.exit", "int exit_code", exit_code)
            raise AssertionError("unreachable")
    record["exit_code"] = exit_code
    if signal is not None:
        record["signal"] = signal
    if timeout:
        record["timeout"] = True
    bad = timeout or signal is not None or exit_code not in (0,)
    if bad and record.get("status") == CHECKPOINT_MATCH:
        record["status"] = CHECKPOINT_REFUSED
        record["match"] = False
        record["field"] = "trainer.exit"
        record["expected"] = 0
        if timeout:
            record["actual"] = "timeout"
        elif signal is not None:
            record["actual"] = f"signal {signal}"
        else:
            record["actual"] = exit_code
    return record


def checkpoint_dir_for(run_dir: Path, checkpoint_id: object) -> Path | None:
    if checkpoint_id is None or checkpoint_id is False:
        return None
    text = str(checkpoint_id).strip()
    if not text or text in {".", ".."} or "/" in text or "\\" in text:
        _refuse("checkpoint_id", "single path segment", checkpoint_id)
    return Path(run_dir) / text


def checkpoint_integrity_status(checkpoint_dir: Path) -> str:
    path = Path(checkpoint_dir) / INTEGRITY_EVIDENCE_NAME
    if not path.is_file():
        return CHECKPOINT_UNSCORED
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return CHECKPOINT_UNSCORED
    if not isinstance(data, dict):
        return CHECKPOINT_UNSCORED
    if data.get("smoke") is True:
        return CHECKPOINT_UNSCORED
    status = data.get("status")
    if status in (CHECKPOINT_MATCH, CHECKPOINT_REFUSED):
        return str(status)
    return CHECKPOINT_UNSCORED


def _require_mode_0400(path: Path, field: str) -> None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        _refuse(field, "present", "missing")
    except OSError as exc:
        _refuse(field, "readable regular file", f"OSError:{exc.errno}")
    if stat.S_ISLNK(info.st_mode):
        _refuse(field, "regular file", "symlink")
    if not stat.S_ISREG(info.st_mode):
        _refuse(field, "regular file", "non-regular")
    if os.name == "posix" and stat.S_IMODE(info.st_mode) != 0o400:
        _refuse(field, "0400", oct(stat.S_IMODE(info.st_mode)))


def rehash_recorded_trainer_paths(
    recorded_paths: Mapping[str, str],
    *,
    pin: Mapping[str, Any],
    manifest_shas: Mapping[str, str],
    host: str,
) -> dict[str, Any]:
    """Re-hash the exact files the trainer read. Same host/process as launch."""
    post: dict[str, str] = {}
    record: dict[str, Any] = {
        "status": CHECKPOINT_MATCH,
        "host": host,
        "paths": {key: recorded_paths[key] for key in TRAINER_PATH_FILES},
        "computed_shas": post,
        "pin_shas": {
            "sha256_pack": pin["sha256_pack"],
            "sha256_train": pin["sha256_train"],
            "sha256_holdout": pin["sha256_holdout"],
        },
        "manifest_shas": dict(manifest_shas),
        "checked_at": _utc_now(),
        "match": True,
    }
    try:
        for sha_field, path_key in PATH_KEY_BY_SHA.items():
            path = Path(recorded_paths[path_key])
            _require_mode_0400(path, sha_field)
            actual = sha256_file(path)
            post[sha_field] = actual
            pin_sha = pin[sha_field]
            man_sha = manifest_shas[sha_field]
            if actual != pin_sha:
                _refuse(sha_field, pin_sha, actual)
            if actual != man_sha:
                _refuse(sha_field, man_sha, actual)
        _require_mode_0400(Path(recorded_paths["manifest"]), MANIFEST_FILE)
    except KickRefused as exc:
        record["status"] = CHECKPOINT_REFUSED
        record["match"] = False
        record["field"] = exc.field
        record["expected"] = exc.expected
        record["actual"] = exc.actual
    record["computed_shas"] = post
    record["checked_at"] = _utc_now()
    return record


def _public_integrity_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if not str(key).startswith("_")}


def verify_and_stage(
    pack_dir: Path,
    *,
    run_private: Path,
    smoke: bool = False,
) -> dict[str, Any]:
    """Copy-hash pack/train/holdout and check them against the Cam HQ pin.

    Returns evidence fields on success. Raises KickRefused on any failure. Does not
    start training or POST kickoff. No MANIFEST-only or ticket fallback.
    """
    _refuse_skip_env()
    _refuse_pin_env()
    refuse_implicit_inbox_pack(pack_dir)
    pack_root = _resolve_pack_dir(Path(pack_dir))
    refuse_implicit_inbox_pack(pack_root)
    _refuse_local_pin_files(pack_root)
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
    if type(pack_id) is not str or not pack_id:
        _refuse("pack_id", "present", "missing")
    if manifest.get("champion_touched") is not False:
        _refuse("champion_touched", False, manifest.get("champion_touched"))
    pin = _require_cam_pin(fetch_cam_pin(pack_id), pack_id)

    computed_shas: dict[str, str] = {}
    manifest_shas: dict[str, str] = {}
    row_counts: dict[str, dict[str, int]] = {}

    for sha_field, filename, rows_field, pin_rows_field in ARTIFACTS:
        src = _regular_file_in_pack(pack_root, filename)
        dest = run_private / filename
        computed = _copy_and_hash(src, dest, sha_field)
        if rows_field not in manifest:
            _refuse(rows_field, "present", "missing")
        expected_rows = _require_int(rows_field, manifest[rows_field])
        actual_rows = count_rows(dest)
        pin_rows = pin[pin_rows_field]
        if pin_rows != expected_rows:
            _refuse(pin_rows_field, pin_rows, expected_rows)
        if pin_rows != actual_rows:
            _refuse(pin_rows_field, pin_rows, actual_rows)
        if actual_rows != expected_rows:
            _refuse(rows_field, expected_rows, actual_rows)
        manifest_value = manifest.get(sha_field)
        if not isinstance(manifest_value, str) or not manifest_value:
            _refuse(sha_field, "present", "missing")
        manifest_sha = _require_sha256_hex(sha_field, manifest_value)
        pin_sha = pin[sha_field]
        if pin_sha != manifest_sha:
            _refuse(sha_field, pin_sha, manifest_sha)
        if pin_sha != computed:
            _refuse(sha_field, pin_sha, computed)
        computed_shas[sha_field] = computed
        manifest_shas[sha_field] = manifest_sha
        row_counts[filename] = {"expected": expected_rows, "actual": actual_rows}

    trainer_paths = trainer_input_paths(run_private)
    _split_soundness(run_private, computed_shas)
    enforce_pack_gates(manifest, trainer_paths, smoke=smoke)

    return {
        "pack_id": pack_id,
        "host": socket.gethostname(),
        "anchor_source": PIN_SOURCE,
        "pin": pin,
        "computed_shas": computed_shas,
        "expected_shas": {
            "sha256_pack": pin["sha256_pack"],
            "sha256_train": pin["sha256_train"],
            "sha256_holdout": pin["sha256_holdout"],
        },
        "manifest_shas": manifest_shas,
        "row_counts": row_counts,
        "paths": trainer_paths,
        "run_private_dir": str(run_private.resolve()),
        "source_pack_dir": str(pack_root),
        "checked_at": _utc_now(),
        "ok": True,
    }


def write_evidence(
    evidence: Mapping[str, Any],
    evidence_path: Path,
    *,
    mode: int | None = None,
) -> Path:
    """Atomically write evidence JSON (mkstemp in the same directory + os.replace)."""
    evidence_path = Path(evidence_path)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(dict(evidence), indent=2) + "\n").encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(
        prefix=evidence_path.name + ".",
        suffix=".tmp",
        dir=str(evidence_path.parent),
    )
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)
    os.replace(tmp_name, evidence_path)
    if mode is None and evidence_path.name == INTEGRITY_EVIDENCE_NAME:
        mode = 0o400
    if mode is not None and os.name == "posix":
        os.chmod(evidence_path, mode)
    return evidence_path


def format_integrity_evidence_line(
    *,
    sha256_evidence: str,
    sha256_pack: str,
    sha256_train: str,
    sha256_holdout: str,
    result: str,
    host: str,
) -> str:
    return (
        f"{INTEGRITY_EVIDENCE_LINE_PREFIX} sha256_evidence={sha256_evidence} "
        f"sha256_pack={sha256_pack} sha256_train={sha256_train} "
        f"sha256_holdout={sha256_holdout} result={result} host={host}"
    )


def parse_integrity_evidence_line(line: str) -> dict[str, str]:
    """Parse the structured operator line. Keys are the sha/result/host fields."""
    text = line.strip()
    if not text.startswith(INTEGRITY_EVIDENCE_LINE_PREFIX + " "):
        _refuse("integrity_evidence_line", INTEGRITY_EVIDENCE_LINE_PREFIX, text[:32])
    parsed: dict[str, str] = {}
    for part in text.split()[1:]:
        key, sep, value = part.partition("=")
        if not sep or not key:
            _refuse("integrity_evidence_line", "key=value fields", part)
        parsed[key] = value
    required = (
        "sha256_evidence",
        "sha256_pack",
        "sha256_train",
        "sha256_holdout",
        "result",
        "host",
    )
    for key in required:
        if key not in parsed:
            _refuse("integrity_evidence_line", key, "missing")
    if parsed["result"] not in (CHECKPOINT_MATCH, CHECKPOINT_REFUSED):
        _refuse("integrity_evidence_line.result", "MATCH|REFUSED", parsed["result"])
    for sha_key in ("sha256_evidence", "sha256_pack", "sha256_train", "sha256_holdout"):
        digest = parsed[sha_key]
        if len(digest) != SHA256_LEN or any(ch not in _HEX for ch in digest):
            _refuse(f"integrity_evidence_line.{sha_key}", "64-char lowercase hex", digest)
    return parsed


def emit_integrity_evidence_line(
    evidence_path: Path,
    record: Mapping[str, Any],
    *,
    log_path: Path | None = None,
    sha256_evidence: str | None = None,
) -> str:
    """Print one human line after the trainer's stdout is closed. Never a result source."""
    evidence_path = Path(evidence_path)
    if os.name == "posix":
        os.chmod(evidence_path, 0o400)
    if sha256_evidence is None:
        sha256_evidence = sha256_file(evidence_path)
    computed = record.get("computed_shas") if isinstance(record.get("computed_shas"), Mapping) else {}
    pin_shas = record.get("pin_shas") if isinstance(record.get("pin_shas"), Mapping) else {}

    def _sha(field: str) -> str:
        value = computed.get(field) or pin_shas.get(field)
        if type(value) is not str or not value:
            _refuse(field, "64-char lowercase hex", value)
        return value

    line = format_integrity_evidence_line(
        sha256_evidence=sha256_evidence,
        sha256_pack=_sha("sha256_pack"),
        sha256_train=_sha("sha256_train"),
        sha256_holdout=_sha("sha256_holdout"),
        result=str(record.get("status") or CHECKPOINT_REFUSED),
        host=str(record.get("host") or socket.gethostname()),
    )
    print(line, flush=True)
    if log_path is not None:
        log = Path(log_path)
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return line


def load_integrity_completion(evidence_path: Path) -> dict[str, Any]:
    """sha256_evidence and parsed JSON from the 0400 file. Never stdout."""
    evidence_path = Path(evidence_path)
    _require_mode_0400(evidence_path, INTEGRITY_EVIDENCE_NAME)
    sha256_evidence = sha256_file(evidence_path)
    try:
        parsed = json.loads(evidence_path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        _refuse(INTEGRITY_EVIDENCE_NAME, "utf-8 JSON", "invalid encoding")
        raise AssertionError("unreachable")
    except OSError as exc:
        _refuse(INTEGRITY_EVIDENCE_NAME, "readable JSON", f"OSError:{exc.errno}")
        raise AssertionError("unreachable")
    except ValueError as exc:
        _refuse(INTEGRITY_EVIDENCE_NAME, "valid JSON object", f"invalid JSON ({exc})")
        raise AssertionError("unreachable")
    if not isinstance(parsed, dict):
        _refuse(INTEGRITY_EVIDENCE_NAME, "JSON object", type(parsed).__name__)
    status = parsed.get("status")
    result = status if status in (CHECKPOINT_MATCH, CHECKPOINT_REFUSED) else CHECKPOINT_REFUSED
    return {
        "sha256_evidence": sha256_evidence,
        "integrity_evidence": parsed,
        "result": result,
    }


def seal_integrity_evidence(
    evidence_path: Path,
    record: Mapping[str, Any],
    *,
    log_path: Path | None = None,
) -> dict[str, Any]:
    """Hash the file this process wrote, then emit the human line."""
    sealed = load_integrity_completion(evidence_path)
    line = emit_integrity_evidence_line(
        evidence_path,
        record,
        log_path=log_path,
        sha256_evidence=sealed["sha256_evidence"],
    )
    sealed["integrity_evidence_line"] = line
    return sealed


def _sha_from_record(record: Mapping[str, Any], field: str) -> str:
    computed = record.get("computed_shas") if isinstance(record.get("computed_shas"), Mapping) else {}
    pin_shas = record.get("pin_shas") if isinstance(record.get("pin_shas"), Mapping) else {}
    value = computed.get(field) or pin_shas.get(field)
    if type(value) is not str or not value:
        _refuse(field, "64-char lowercase hex", value)
    return value


def _post_hq_event(event: str, payload: Mapping[str, Any]) -> None:
    try:
        cam_pin_spec.post_hq_event(event, dict(payload))
    except cam_pin_spec.CamPinError as exc:
        _refuse(exc.field, exc.expected, exc.actual)


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


def _apply_post_train_record(
    evidence: dict[str, Any],
    record: Mapping[str, Any],
    *,
    run_dir: Path,
    log_path: Path | None = None,
    post_completion: bool = True,
) -> None:
    evidence["post_train_shas"] = dict(record.get("computed_shas") or {})
    evidence["post_train_host"] = record["host"]
    evidence["post_train_paths"] = dict(record["paths"])
    evidence["post_train_checked_at"] = record["checked_at"]
    evidence["exit_code"] = record.get("exit_code", 0)
    if record.get("signal") is not None:
        evidence["signal"] = record["signal"]
    if record.get("timeout"):
        evidence["timeout"] = True
    ckpt_dir = checkpoint_dir_for(run_dir, evidence.get("checkpoint_id"))
    if ckpt_dir is not None:
        ckpt_path = ckpt_dir / INTEGRITY_EVIDENCE_NAME
        write_evidence(_public_integrity_record(record), ckpt_path, mode=0o400)
        sealed = seal_integrity_evidence(ckpt_path, record, log_path=log_path)
        evidence["checkpoint_integrity_evidence_path"] = str(ckpt_path.resolve())
        evidence["checkpoint_integrity_status"] = record["status"]
        evidence["integrity_evidence_line"] = sealed["integrity_evidence_line"]
        evidence["sha256_evidence"] = sealed["sha256_evidence"]
        evidence["integrity_evidence"] = sealed["integrity_evidence"]
        evidence["result"] = sealed["result"]
        if post_completion:
            _post_hq_event(
                "completion",
                {
                    "run_id": evidence["run_id"],
                    "sha256_evidence": sealed["sha256_evidence"],
                    "sha256_pack": _sha_from_record(record, "sha256_pack"),
                    "sha256_train": _sha_from_record(record, "sha256_train"),
                    "sha256_holdout": _sha_from_record(record, "sha256_holdout"),
                    "result": sealed["result"],
                    "exit_code": record.get("exit_code", 0),
                },
            )
    if record["status"] != CHECKPOINT_MATCH:
        evidence["ok"] = False
        evidence["result"] = CHECKPOINT_REFUSED


def _recheck_copies(
    run_private: Path,
    evidence: dict[str, Any],
    *,
    run_dir: Path,
    log_path: Path | None = None,
    exit_info: Mapping[str, Any] | None = None,
    smoke: bool = False,
) -> None:
    recorded = evidence.get("paths")
    if not isinstance(recorded, dict):
        recorded = trainer_input_paths(run_private)
    host = socket.gethostname()
    record = rehash_recorded_trainer_paths(
        recorded,
        pin=evidence["pin"],
        manifest_shas=evidence["manifest_shas"],
        host=host,
    )
    apply_trainer_exit(record, exit_info)
    if smoke:
        record["smoke"] = True
    _apply_post_train_record(
        evidence,
        record,
        run_dir=run_dir,
        log_path=log_path,
        post_completion=not smoke,
    )
    if record["status"] != CHECKPOINT_MATCH:
        _refuse(record.get("field", "post_train"), record.get("expected"), record.get("actual"))


def kick(
    pack_dir: Path,
    *,
    log_path: Path | None = None,
    start_training: StartTraining | None = None,
    kickoff: KickoffFn | None = None,
    kickoff_url: str = DEFAULT_KICKOFF_URL,
    smoke: bool = False,
) -> dict[str, Any]:
    """Fetch the Cam HQ pin, stage private copies, POST kickoff, re-check shas.

    ``start_training`` / ``kickoff`` are test injection hooks and still run only
    after the gate. CLI and env cannot supply them. There is no skip/override.
    ``smoke=True`` never posts HQ events, marks evidence unscorable, and
    deletes checkpoint/run-dir copies/inbox before returning.
    """
    _refuse_skip_env()
    _refuse_pin_env()
    refuse_implicit_inbox_pack(pack_dir)
    pack_dir = Path(pack_dir)
    smoke = bool(smoke)
    _refuse_local_pin_files(_resolve_pack_dir(pack_dir))
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
    git_sha = _script_git_sha()
    try:
        trust_blobs = cam_pin_spec.require_committed_trust()
    except cam_pin_spec.CamPinError as exc:
        _refuse(exc.field, exc.expected, exc.actual)
    evidence: dict[str, Any] = {
        "ok": False,
        "run_id": run_id,
        "checkpoint_id": None,
        "script_git_sha": git_sha,
        "script_sha256": _script_sha256(),
        "kickoff_url": kickoff_url,
        "host": socket.gethostname(),
        "anchor_source": PIN_SOURCE,
        "evidence_path": str(evidence_path.resolve()),
        "checked_at": _utc_now(),
        "trust_blobs": trust_blobs,
        "head_sha": trust_blobs.get("HEAD"),
    }

    def persist() -> None:
        write_evidence(evidence, evidence_path)

    try:
        staged = verify_and_stage(pack_dir, run_private=run_private, smoke=smoke)
        evidence.update(staged)
        evidence["run_id"] = run_id
        evidence["checkpoint_id"] = None
        evidence["script_git_sha"] = git_sha
        evidence["script_sha256"] = evidence.get("script_sha256") or _script_sha256()
        evidence["kickoff_url"] = kickoff_url
        evidence["evidence_path"] = str(evidence_path.resolve())
        evidence["trust_blobs"] = trust_blobs
        evidence["head_sha"] = trust_blobs.get("HEAD")
        if smoke:
            evidence["smoke"] = True
        persist()
        trainer_paths = trainer_input_paths(run_private)
        evidence["paths"] = trainer_paths
        trainer_config = {"host": evidence["host"], "paths": trainer_paths}
        trainer_argv = build_trainer_argv(trainer_paths)
        evidence["trainer_config"] = trainer_config
        evidence["trainer_argv"] = trainer_argv
        persist()
        if not smoke:
            _post_hq_event(
                "kick",
                {
                    "run_id": run_id,
                    "sha256_pack": evidence["computed_shas"]["sha256_pack"],
                    "sha256_train": evidence["computed_shas"]["sha256_train"],
                    "sha256_holdout": evidence["computed_shas"]["sha256_holdout"],
                },
            )
        body = {
            "mode": "helper-ft-smoke" if smoke else "helper-ft",
            "pack_id": evidence["pack_id"],
            "sha256_pack": evidence["computed_shas"]["sha256_pack"],
            "sha256_train": evidence["computed_shas"]["sha256_train"],
            "sha256_holdout": evidence["computed_shas"]["sha256_holdout"],
            "expected_shas": dict(evidence["expected_shas"]),
            "pin": dict(evidence["pin"]),
            "run_private_dir": evidence["run_private_dir"],
            "paths": trainer_paths,
            "trainer_config": trainer_config,
            "trainer_argv": trainer_argv,
            "evidence": dict(evidence),
            "evidence_path": evidence["evidence_path"],
            "run_id": run_id,
            "checked_at": evidence["checked_at"],
        }
        if smoke:
            body["smoke"] = True
        if kickoff is not None:
            result = kickoff(body)
            if not isinstance(result, dict) or result.get("ok") is not True:
                if isinstance(result, dict) and result.get("field"):
                    _refuse(result.get("field"), result.get("expected"), result.get("actual"))
                _refuse("kickoff", "ok", result)
        else:
            result = post_kickoff(body, url=kickoff_url)
        if isinstance(result, dict) and result.get("checkpoint_id") and not smoke:
            evidence["checkpoint_id"] = result["checkpoint_id"]
            persist()
        elif smoke:
            evidence["checkpoint_id"] = "smoke"
            persist()
        # Training must finish before the end-of-training re-hash. Wait in this
        # same process/host, then re-hash the recorded run-dir copy paths.
        exits: list[Mapping[str, Any]] = []
        exits.append(wait_for_training_exit(result if isinstance(result, dict) else None))
        if start_training is None:
            started = _authorized_start_training(run_private, evidence, log_path, _gate=_GATE_OK)
            exits.append(wait_for_training_exit(started if isinstance(started, dict) else None))
        else:
            started = start_training(run_private, evidence, log_path)
            exits.append(wait_for_training_exit(started if isinstance(started, dict) else None))
        exit_info = combine_trainer_exits(exits)
        _recheck_copies(
            run_private,
            evidence,
            run_dir=run_dir,
            log_path=log_path,
            exit_info=exit_info,
            smoke=smoke,
        )
        if smoke:
            evidence["smoke"] = True
            ckpt_dir = checkpoint_dir_for(run_dir, evidence.get("checkpoint_id"))
            survivors = cleanup_smoke_artifacts(
                checkpoint_dir=ckpt_dir,
                run_private=run_private,
                inbox=pack_dir,
            )
            evidence["checkpoint_id"] = None
            evidence.pop("checkpoint_integrity_evidence_path", None)
            evidence["checkpoint_integrity_status"] = CHECKPOINT_UNSCORED
            if survivors:
                evidence["ok"] = False
                evidence["result"] = CHECKPOINT_REFUSED
                evidence["survivors"] = survivors
                persist()
                _refuse("smoke.cleanup", "nothing survives", survivors)
        persist()
        return evidence
    except KickRefused as exc:
        evidence["ok"] = False
        evidence["field"] = exc.field
        evidence["expected"] = exc.expected
        evidence["actual"] = exc.actual
        if smoke:
            evidence["smoke"] = True
            ckpt_dir = None
            try:
                ckpt_dir = checkpoint_dir_for(run_dir, evidence.get("checkpoint_id"))
            except KickRefused:
                ckpt_dir = None
            survivors = cleanup_smoke_artifacts(
                checkpoint_dir=ckpt_dir,
                run_private=run_private,
                inbox=pack_dir,
            )
            evidence["checkpoint_id"] = None
            evidence.pop("checkpoint_integrity_evidence_path", None)
            evidence["checkpoint_integrity_status"] = CHECKPOINT_UNSCORED
            if survivors:
                evidence["survivors"] = survivors
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
        "--kickoff-url",
        default=DEFAULT_KICKOFF_URL,
        help="HELPER FT POST /train/kickoff URL (default 127.0.0.1:8765)",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="explicit smoke mode: never post HQ events, unscorable, delete copies/inbox",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, unknown = parser.parse_known_args(argv)
    try:
        if unknown:
            _refuse("argv", "known arguments only", unknown[0])
        evidence = kick(
            args.pack,
            log_path=args.log,
            kickoff_url=args.kickoff_url,
            smoke=bool(args.smoke),
        )
    except KickRefused as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1
    print(json.dumps(evidence, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
