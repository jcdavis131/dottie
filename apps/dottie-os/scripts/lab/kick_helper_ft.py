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
import base64
import errno
import hashlib
import json
import math
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.request
import uuid
from collections import Counter, defaultdict
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Mapping, NoReturn

_LAB = str(Path(__file__).resolve().parent)
if _LAB not in sys.path:
    sys.path.insert(0, _LAB)

import cam_pin_spec
import content_uuid

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
GIT_SHA_LEN = 40
_HEX = frozenset("0123456789abcdef")
FORGE_ENTRYPOINT_PINS_ENV = "FORGE_ENTRYPOINT_PINS"
FORGE_PINS_SOURCE_COMMIT_ENV = "FORGE_PINS_SOURCE_COMMIT"
ENTRYPOINT_PIN_BASENAMES = ("kick_helper_ft.py", "cam_pin_spec.py")
PINS_JSON_NAME = "PINS.json"
PINNED_COPY_DEPTH = 4
PINNED_COPY_REASON = "pinned-copy"
PINNED_COPY_KICK_REL = "apps/dottie-os/scripts/lab/kick_helper_ft.py"
PINNED_COPY_SPEC_REL = "apps/dottie-os/scripts/lab/cam_pin_spec.py"
PINNED_COPY_UUID_REL = "apps/dottie-os/scripts/lab/content_uuid.py"
PINNED_COPY_PUB_REL = "trust/cam_pin_ed25519.pub"
PINNED_COPY_KEY_ID_REL = "trust/cam_pin_key_id"
PINNED_COPY_REQUIRED_RELS = (
    PINNED_COPY_KICK_REL,
    PINNED_COPY_SPEC_REL,
    PINNED_COPY_UUID_REL,
    PINNED_COPY_PUB_REL,
    PINNED_COPY_KEY_ID_REL,
)
PINS_JSON_MAX_BYTES = 64 * 1024
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
# Historical 185133 key names. The gate does **not** refuse on names alone:
# a denylist key with a constant or uncorrelated value must pass. Detection
# is pack-level value predictiveness (see collect_state_leaks).
LEAK_MIN_SUPPORT = 2
LEAK_U_THRESHOLD = 0.50
LEAK_LIFT_MARGIN = 0.20
LEAK_NEAR_PERFECT_ACC = 0.999
LEAK_B64_MIN_LEN = 8
LEAK_B64_MAX_DECODED = 256
LEAK_BOOL_TRUE = "__bool__:true"
LEAK_BOOL_FALSE = "__bool__:false"
LEAK_NULL = "__null__"
LEAK_ABSENT = "__absent__"
LEAK_KEY_COUNT_SUFFIX = ".__key_count__"
LEAK_PRESENT_SUFFIX = ".__present__"
_LEAK_BOOKKEEPING_KEYS = frozenset(
    {
        "schema",
        "id",
        "questions",
        "labels",
        "source",
        "consent",
        "tier",
        "trajectory_id",
    }
)
_LEAK_PACK_JSONL = frozenset({PACK_FILE, TRAIN_FILE, HOLDOUT_FILE})
_LEAK_B64_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
_LEAK_FORMAT_CATS = frozenset({"Cc", "Cf", "Mn", "Me"})
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


def _running_script() -> Path:
    return Path(__file__).resolve()


def discover_pinned_copy_root(script: Path | None = None) -> Path | None:
    """PINS.json lives four directories above kick_helper_ft.py. No git."""
    path = Path(script) if script is not None else _running_script()
    try:
        root = path.resolve().parents[PINNED_COPY_DEPTH]
    except IndexError:
        return None
    pins = root / PINS_JSON_NAME
    if pins.is_file():
        return root
    return None


def canonical_pins_map_json(payload: Mapping[str, Any]) -> bytes:
    """sha256 of this blob is the map digest. Sorted keys, compact separators."""
    return json.dumps(
        payload, separators=(",", ":"), sort_keys=True, ensure_ascii=True
    ).encode("utf-8")


def _no_duplicate_pins_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            _refuse(PINS_JSON_NAME, "unique keys", f"duplicate {key}")
        seen[key] = value
    return seen


def _read_capped_file(path: Path, *, field: str, max_bytes: int) -> bytes:
    try:
        fd = os.open(path, _open_flags_read())
    except OSError as exc:
        _refuse(field, "readable regular file", f"OSError:{exc.errno}")
    try:
        raw = b""
        while True:
            block = os.read(fd, CHUNK)
            if not block:
                break
            raw += block
            if len(raw) > max_bytes:
                _refuse(field, f"at most {max_bytes} bytes", len(raw))
    except OSError as exc:
        _refuse(field, "readable regular file", f"OSError:{exc.errno}")
    finally:
        os.close(fd)
    return raw


def load_pinned_copy_mode(script: Path | None = None) -> dict[str, Any] | None:
    """If PINS.json is present, verify the staged copy and skip every git lookup.

    Layout (copy root = four parents of kick_helper_ft.py)::

        PINS.json
        apps/dottie-os/scripts/lab/*.py
        trust/cam_pin_ed25519.pub
        trust/cam_pin_key_id

    ``PINS.json`` is ``{"head": <40-hex>, "files": {<repo-rel-path>: <sha256>}}``.
    Required files are hashed at those exact relative paths. A basename-only
    pin is a missing entry.
    """
    path = Path(script) if script is not None else _running_script()
    root = discover_pinned_copy_root(path)
    if root is None:
        return None
    pins_path = root / PINS_JSON_NAME
    raw = _read_capped_file(pins_path, field=PINS_JSON_NAME, max_bytes=PINS_JSON_MAX_BYTES)
    file_sha = hashlib.sha256(raw).hexdigest()
    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_pins_keys)
    except UnicodeDecodeError:
        _refuse(PINS_JSON_NAME, "utf-8 JSON", "invalid encoding")
    except ValueError:
        _refuse(PINS_JSON_NAME, "JSON object", "invalid JSON")
    if not isinstance(parsed, dict):
        _refuse(PINS_JSON_NAME, '{"head","files"}', type(parsed).__name__)
    extra = set(parsed) - {"head", "files"}
    if extra or "head" not in parsed or "files" not in parsed:
        _refuse(PINS_JSON_NAME, '{"head","files"}', sorted(parsed))
    head = _require_git_commit_hex("head", parsed["head"])
    files_raw = parsed["files"]
    if not isinstance(files_raw, dict) or not files_raw:
        _refuse(
            "files",
            "JSON object",
            type(files_raw).__name__ if not isinstance(files_raw, dict) else "empty",
        )
    files: dict[str, str] = {}
    for key, value in files_raw.items():
        rel = _require_relative_pin_path("files", key)
        files[rel] = _require_sha256_hex(f"files.{rel}", value)
    kick_live = path.resolve()
    spec_live = (kick_live.parent / "cam_pin_spec.py").resolve()
    uuid_live = (kick_live.parent / "content_uuid.py").resolve()
    expected_kick = (root / PINNED_COPY_KICK_REL).resolve()
    expected_spec = (root / PINNED_COPY_SPEC_REL).resolve()
    expected_uuid = (root / PINNED_COPY_UUID_REL).resolve()
    if kick_live != expected_kick:
        _refuse(PINNED_COPY_KICK_REL, str(expected_kick), str(kick_live))
    if spec_live != expected_spec:
        _refuse(PINNED_COPY_SPEC_REL, str(expected_spec), str(spec_live))
    if uuid_live != expected_uuid:
        _refuse(PINNED_COPY_UUID_REL, str(expected_uuid), str(uuid_live))
    live_by_rel = {
        PINNED_COPY_KICK_REL: kick_live,
        PINNED_COPY_SPEC_REL: spec_live,
        PINNED_COPY_UUID_REL: uuid_live,
        PINNED_COPY_PUB_REL: (root / PINNED_COPY_PUB_REL).resolve(),
        PINNED_COPY_KEY_ID_REL: (root / PINNED_COPY_KEY_ID_REL).resolve(),
    }
    for rel in PINNED_COPY_REQUIRED_RELS:
        if rel not in files:
            _refuse("files", f"pin covering {rel}", "missing")
        target = live_by_rel[rel]
        if not target.is_file():
            _refuse(rel, "readable regular file", "missing")
        actual = sha256_file(target)
        if files[rel] != actual:
            _refuse(f"files.{rel}", actual, files[rel])
    for rel, expected in files.items():
        target = (root / rel).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            _refuse(f"files.{rel}", f"under {root}", str(target))
        if not target.is_file():
            _refuse(rel, "readable regular file", "missing")
        actual = sha256_file(target)
        if expected != actual:
            _refuse(f"files.{rel}", actual, expected)
    payload = {"files": files, "head": head}
    map_sha = hashlib.sha256(canonical_pins_map_json(payload)).hexdigest()
    trust_blobs = {
        PINNED_COPY_PUB_REL: files[PINNED_COPY_PUB_REL],
        PINNED_COPY_KEY_ID_REL: files[PINNED_COPY_KEY_ID_REL],
        PINNED_COPY_SPEC_REL: files[PINNED_COPY_SPEC_REL],
        "HEAD": head,
    }
    return {
        "root": root,
        "pins_path": pins_path,
        "head": head,
        "files": files,
        "map_sha256": map_sha,
        "file_sha256": file_sha,
        "trust_blobs": trust_blobs,
        "reason": PINNED_COPY_REASON,
    }


def _script_git_sha() -> str | None:
    if discover_pinned_copy_root() is not None:
        return None
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


def _require_git_commit_hex(field: str, value: object) -> str:
    if type(value) is not str or len(value) != GIT_SHA_LEN or any(ch not in _HEX for ch in value):
        _refuse(field, "40-char lowercase hex", value)
    return value


def _require_relative_pin_path(field: str, value: object) -> str:
    if type(value) is not str or not value or value.startswith("/") or "\\" in value:
        _refuse(field, "relative POSIX path", value)
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        _refuse(field, "relative POSIX path", value)
    return value


def _entrypoint_live_files() -> dict[str, Path]:
    return {
        "kick_helper_ft.py": Path(__file__).resolve(),
        "cam_pin_spec.py": Path(cam_pin_spec.__file__).resolve(),
    }


def load_entrypoint_pins(*, git_sha: str | None) -> tuple[dict[str, str], str]:
    """Load runner pin map + source commit. Null git sha is allowed only here.

    ``FORGE_ENTRYPOINT_PINS`` is a JSON object mapping relative paths to
    sha256 hex, and must cover ``kick_helper_ft.py`` and ``cam_pin_spec.py``.
    ``FORGE_PINS_SOURCE_COMMIT`` is the 40-hex commit those pins were hashed
    from. A missing ``script_git_sha`` (private verified copy) is accepted
    only when both env vars are present and well formed. Missing or
    malformed pins refuse even when ``git_sha`` is present.
    """
    if git_sha is not None and (
        type(git_sha) is not str
        or len(git_sha) != GIT_SHA_LEN
        or any(ch not in _HEX for ch in git_sha)
    ):
        _refuse("script_git_sha", "40-char lowercase hex or null", git_sha)
    pins_raw = os.environ.get(FORGE_ENTRYPOINT_PINS_ENV)
    commit_raw = os.environ.get(FORGE_PINS_SOURCE_COMMIT_ENV)
    if not pins_raw:
        _refuse("entrypoint_pins", "JSON map from FORGE_ENTRYPOINT_PINS", "missing")
    if not commit_raw:
        _refuse(
            "pins_source_commit",
            "40-char lowercase hex from FORGE_PINS_SOURCE_COMMIT",
            "missing",
        )
    commit = _require_git_commit_hex("pins_source_commit", commit_raw)
    try:
        parsed = json.loads(pins_raw)
    except ValueError:
        _refuse("entrypoint_pins", "JSON object", "invalid JSON")
    if not isinstance(parsed, dict) or not parsed:
        _refuse(
            "entrypoint_pins",
            "JSON object",
            type(parsed).__name__ if not isinstance(parsed, dict) else "empty",
        )
    pins: dict[str, str] = {}
    by_base: dict[str, str] = {}
    for key, value in parsed.items():
        rel = _require_relative_pin_path("entrypoint_pins", key)
        digest = _require_sha256_hex(f"entrypoint_pins.{rel}", value)
        pins[rel] = digest
        base = Path(rel).name
        if base in by_base:
            _refuse("entrypoint_pins", f"unique basename {base}", rel)
        by_base[base] = digest
    live = _entrypoint_live_files()
    for basename in ENTRYPOINT_PIN_BASENAMES:
        if basename not in by_base:
            _refuse("entrypoint_pins", f"pin covering {basename}", "missing")
        actual = sha256_file(live[basename])
        if by_base[basename] != actual:
            _refuse(f"entrypoint_pins.{basename}", actual, by_base[basename])
    return pins, commit


def _entrypoint_event_fields(evidence: Mapping[str, Any]) -> dict[str, Any]:
    pins = evidence.get("entrypoint_pins")
    commit = evidence.get("pins_source_commit")
    if not isinstance(pins, dict) or not pins:
        _refuse("entrypoint_pins", "recorded pin map", "missing")
    if type(commit) is not str:
        _refuse("pins_source_commit", "40-char lowercase hex", commit)
    fields: dict[str, Any] = {
        "entrypoint_pins": dict(pins),
        "pins_source_commit": commit,
    }
    if evidence.get("script_git_sha_reason") == PINNED_COPY_REASON:
        for key in (
            "head",
            "pins_map_sha256",
            "pins_file_sha256",
            "pinned_copy_root",
            "script_git_sha_reason",
        ):
            value = evidence.get(key)
            if value is None:
                _refuse(key, "pinned-copy evidence", "missing")
            fields[key] = value
        fields["script_git_sha"] = None
    return fields


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


def _read_file_buffer(src: Path, field: str) -> bytes:
    """Read the whole regular file through one held fd. No path reopen."""
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
        chunks: list[bytes] = []
        while True:
            block = os.read(fd, CHUNK)
            if not block:
                break
            chunks.append(block)
        return b"".join(chunks)
    except OSError as exc:
        _refuse(field, "readable regular file", f"OSError:{exc.errno}")
        raise AssertionError("unreachable")
    finally:
        os.close(fd)


def _write_buffer_exclusive(dest: Path, buf: bytes, field: str) -> None:
    """Write ``buf`` through O_CREAT|O_EXCL, fsync, fchmod 0400. Same bytes hashed."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        out_fd = os.open(dest, _open_flags_write(), 0o600)
    except OSError as exc:
        _refuse(field, "exclusive writable copy", f"OSError:{exc.errno}")
    try:
        view = memoryview(buf)
        offset = 0
        while offset < len(buf):
            offset += os.write(out_fd, view[offset:])
        if hasattr(os, "fsync"):
            os.fsync(out_fd)
        if os.name == "posix" and hasattr(os, "fchmod"):
            os.fchmod(out_fd, 0o400)
        else:
            os.chmod(dest, 0o400)
        written = os.fstat(out_fd)
        try:
            named = os.lstat(dest)
        except OSError as exc:
            _refuse(field, "same inode", f"OSError:{exc.errno}")
        if (written.st_dev, written.st_ino) != (named.st_dev, named.st_ino):
            _refuse(field, "same inode", "path swapped")
    except OSError as exc:
        _refuse(field, "writable copy", f"OSError:{exc.errno}")
    finally:
        os.close(out_fd)


def _copy_and_hash(src: Path, dest: Path, field: str) -> str:
    """Read into a buffer, hash that buffer, write the same buffer to a private copy.

    The trainer must read only the private copy. Hashing a stream while writing
    and then reopening a shared path leaves a TOCTOU window (B-RACE).
    """
    buf = _read_file_buffer(src, field)
    digest = hashlib.sha256(buf).hexdigest()
    _write_buffer_exclusive(dest, buf, field)
    return digest


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


def normalize_leak_key(key: object) -> str:
    """NFKC, strip format/combining marks, casefold, drop spaces and `_-.`."""
    text = unicodedata.normalize("NFKC", str(key))
    text = "".join(ch for ch in text if unicodedata.category(ch) not in _LEAK_FORMAT_CATS)
    return re.sub(r"[\s_\-.]+", "", text.casefold())


def _is_message_key(key: object) -> bool:
    return normalize_leak_key(key) == "message"


def _is_leak_synthetic_path(path: str) -> bool:
    """Presence and key-count features are categorical, never noul copies."""
    return (
        path == "__key_count__"
        or path.endswith(LEAK_KEY_COUNT_SUFFIX)
        or path.endswith(LEAK_PRESENT_SUFFIX)
    )


def _leak_entropy(counts: Mapping[object, int], n: int) -> float:
    if n <= 0:
        return 0.0
    total = 0.0
    for count in counts.values():
        if count:
            p = count / n
            total -= p * math.log2(p)
    return total


def _theil_u(values: list[object], golds: list[object]) -> float:
    """Uncertainty coefficient U(gold|field) = MI(field; gold) / H(gold)."""
    n = len(values)
    if n == 0:
        return 0.0
    h_gold = _leak_entropy(Counter(golds), n)
    if h_gold == 0.0:
        return 0.0
    by_value: dict[object, list[object]] = defaultdict(list)
    for value, gold in zip(values, golds):
        by_value[value].append(gold)
    h_cond = 0.0
    for group in by_value.values():
        h_cond += (len(group) / n) * _leak_entropy(Counter(group), len(group))
    return (h_gold - h_cond) / h_gold


def _conditional_accuracy(
    values: list[object],
    golds: list[object],
    *,
    min_support: int = LEAK_MIN_SUPPORT,
) -> tuple[float, int, float]:
    """Per-value majority classifier on values with support >= min_support.

    Returns (accuracy, n_supported, majority_baseline_on_supported).
    """
    by_value: dict[object, list[object]] = defaultdict(list)
    for value, gold in zip(values, golds):
        by_value[value].append(gold)
    correct = 0
    supported: list[object] = []
    for group in by_value.values():
        if len(group) < min_support:
            continue
        supported.extend(group)
        predicted = Counter(group).most_common(1)[0][0]
        correct += sum(1 for gold in group if gold == predicted)
    if not supported:
        return 0.0, 0, 0.0
    baseline = Counter(supported).most_common(1)[0][1] / len(supported)
    return correct / len(supported), len(supported), baseline


def _field_predicts_gold(values: list[object], golds: list[object]) -> bool:
    """True when repeated field values predict gold above the majority baseline.

    Thresholds (not per-fixture):
    - Skip constants (1 distinct value) and unique-per-row fields (cardinality
      == n). Those can be ids or a non-predictive flag; unique values can
      memorize any labeling.
    - MIN_SUPPORT=2: a value must appear at least twice before it counts as a
      repeated predictor. Small-n packs therefore fail closed only when a
      repeated value is a pure (or near-pure) gold slice.
    - Fail-closed: conditional accuracy >= LEAK_NEAR_PERFECT_ACC on the
      supported rows (perfect / near-perfect copies, including n=3 A,A,B).
    - Partial leaks: Theil's U(gold|field) >= 0.50 (field explains at least
      half of gold entropy) AND accuracy is at least 20pp above the
      majority-class baseline. That catches a field that matches gold on
      most but not all rows without flagging mixed ``status: execute``
      cycling or ordinary lang/tool constants.
    """
    n = len(values)
    if n < LEAK_MIN_SUPPORT:
        return False
    if len(set(golds)) <= 1:
        # A constant gold cannot be leaked; any co-occurring field would
        # look like a perfect predictor.
        return False
    n_unique = len(set(values))
    if n_unique <= 1 or n_unique >= n:
        return False
    accuracy, supported, baseline = _conditional_accuracy(values, golds)
    if supported < LEAK_MIN_SUPPORT:
        return False
    if accuracy >= LEAK_NEAR_PERFECT_ACC:
        return True
    u_score = _theil_u(values, golds)
    return u_score >= LEAK_U_THRESHOLD and accuracy >= baseline + LEAK_LIFT_MARGIN


def _row_gold_choice(row: Mapping[str, Any]) -> str | None:
    labels = row.get("labels")
    if not isinstance(labels, Mapping):
        return None
    action = labels.get("action")
    if isinstance(action, Mapping):
        choice = action.get("choice")
        if type(choice) is str and choice:
            return choice
    domain = labels.get("domain")
    if isinstance(domain, Mapping):
        choice = domain.get("choice")
        if type(choice) is str and choice:
            return choice
    return None


def _row_gold_noul(row: Mapping[str, Any]) -> float | None:
    labels = row.get("labels")
    if not isinstance(labels, Mapping):
        return None
    safe = labels.get("safe")
    if not isinstance(safe, Mapping):
        return None
    noul = safe.get("noul")
    if isinstance(noul, (int, float)) and type(noul) is not bool:
        return round(float(noul), 6)
    return None


def _canonical_leak_value(value: object) -> object:
    if type(value) is bool:
        return LEAK_BOOL_TRUE if value else LEAK_BOOL_FALSE
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value
    if value is None:
        return LEAK_NULL
    return str(value)


def _json_blobs(text: str) -> list[object]:
    blobs: list[object] = []
    decoder = json.JSONDecoder()
    idx = 0
    length = len(text)
    while idx < length:
        ch = text[idx]
        if ch in "{[":
            try:
                obj, end = decoder.raw_decode(text, idx)
            except ValueError:
                idx += 1
                continue
            blobs.append(obj)
            idx = end
            continue
        idx += 1
    return blobs


def _maybe_b64_text(text: str) -> str | None:
    blob = text.strip()
    if len(blob) < LEAK_B64_MIN_LEN or len(blob) % 4:
        return None
    if not _LEAK_B64_RE.fullmatch(blob):
        return None
    try:
        raw = base64.b64decode(blob, validate=True)
        decoded = raw.decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    if not decoded or decoded == text or len(decoded) > LEAK_B64_MAX_DECODED:
        return None
    return decoded


def _walk_leak_value(
    value: object,
    path: str,
    into: dict[str, object],
    *,
    from_message: bool,
) -> None:
    if isinstance(value, Mapping):
        if not from_message:
            count_path = f"{path}{LEAK_KEY_COUNT_SUFFIX}" if path else "__key_count__"
            into[count_path] = len(value)
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            child_is_message = from_message or _is_message_key(key)
            _walk_leak_value(child, child_path, into, from_message=child_is_message)
        return
    if isinstance(value, list):
        for idx, child in enumerate(value):
            _walk_leak_value(child, f"{path}[{idx}]", into, from_message=from_message)
        return
    if isinstance(value, str):
        for idx, blob in enumerate(_json_blobs(value)):
            _walk_leak_value(
                blob, f"{path}.<json{idx}>", into, from_message=False
            )
        decoded = _maybe_b64_text(value)
        if decoded is not None:
            _walk_leak_value(decoded, f"{path}.<b64>", into, from_message=False)
        if not from_message:
            into[path] = _canonical_leak_value(value)
        return
    if from_message:
        return
    into[path] = _canonical_leak_value(value)


def _fields_from_row(row: Mapping[str, Any]) -> dict[str, object]:
    into: dict[str, object] = {}
    state = row.get("state")
    if isinstance(state, Mapping):
        into["state" + LEAK_KEY_COUNT_SUFFIX] = len(state)
        for key, child in state.items():
            if _is_message_key(key):
                _walk_leak_value(
                    child, f"state.{key}", into, from_message=True
                )
            else:
                _walk_leak_value(
                    child, f"state.{key}", into, from_message=False
                )
    scored_keys = [
        key for key in row if key != "state" and str(key) not in _LEAK_BOOKKEEPING_KEYS
    ]
    into["__key_count__"] = len(scored_keys) + (1 if isinstance(state, Mapping) else 0)
    for key in scored_keys:
        _walk_leak_value(
            row[key], str(key), into, from_message=_is_message_key(key)
        )
    return into


def _unique_pack_rows(recorded_paths: Mapping[str, str]) -> list[dict[str, Any]]:
    """Dedup by id. Prefer the pack file so train∪holdout is not double-counted."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in ("pack", "train", "holdout"):
        raw = recorded_paths.get(key)
        if type(raw) is not str or not raw:
            continue
        path = Path(raw)
        chunk: list[dict[str, Any]] = []
        for obj in _iter_jsonl_objects(path, path.name):
            rid = _row_id(obj)
            if rid != "?" and rid in seen:
                continue
            seen.add(rid)
            chunk.append(obj)
        if key == "pack" and chunk:
            return chunk
        rows.extend(chunk)
    return rows


def _sidecar_jsonl_paths(pack_dir: Path | str | None) -> list[Path]:
    if pack_dir is None:
        return []
    root = Path(pack_dir)
    if not root.is_dir():
        return []
    found: list[Path] = []
    try:
        for child in root.iterdir():
            if not child.is_file() or child.suffix != ".jsonl":
                continue
            if child.name in _LEAK_PACK_JSONL:
                continue
            found.append(child)
    except OSError:
        return []
    return found


def _fields_from_sidecar(path: Path) -> dict[str, dict[str, object]]:
    """Map row id -> {sidecar.<key>: value} from a companion jsonl."""
    by_id: dict[str, dict[str, object]] = {}
    for obj in _iter_jsonl_objects(path, path.name):
        rid = obj.get("id") or obj.get("trajectory_id")
        if not isinstance(rid, str) or not rid:
            continue
        slot = by_id.setdefault(rid, {})
        for key, child in obj.items():
            if key in ("id", "trajectory_id"):
                continue
            _walk_leak_value(child, f"sidecar.{key}", slot, from_message=_is_message_key(key))
    return by_id


def _load_jsonl_rows(raw: object) -> list[dict[str, Any]]:
    if type(raw) is not str or not raw:
        return []
    path = Path(raw)
    if not path.is_file():
        return []
    return list(_iter_jsonl_objects(path, path.name))


def _leak_hits_for_rows(
    rows: list[dict[str, Any]],
    sidecar_by_id: Mapping[str, Mapping[str, object]],
) -> list[str]:
    if not rows:
        return []
    columns: dict[str, list[object | None]] = defaultdict(lambda: [None] * len(rows))
    choices: list[str | None] = []
    nouls: list[float | None] = []
    for idx, row in enumerate(rows):
        choices.append(_row_gold_choice(row))
        nouls.append(_row_gold_noul(row))
        for path, token in _fields_from_row(row).items():
            columns[path][idx] = token
        extra = sidecar_by_id.get(_row_id(row))
        if extra:
            for path, token in extra.items():
                columns[path][idx] = token

    for col in columns.values():
        for idx, token in enumerate(col):
            if token is None:
                col[idx] = LEAK_ABSENT
    for path, col in list(columns.items()):
        if path.endswith(LEAK_PRESENT_SUFFIX) or path.endswith(LEAK_KEY_COUNT_SUFFIX):
            continue
        columns[path + LEAK_PRESENT_SUFFIX] = [
            LEAK_BOOL_FALSE if token == LEAK_ABSENT else LEAK_BOOL_TRUE for token in col
        ]

    found: list[str] = []
    seen: set[str] = set()
    for path, col in columns.items():
        synthetic = _is_leak_synthetic_path(path)
        choice_pairs = [
            (value, gold)
            for value, gold in zip(col, choices)
            if gold is not None
        ]
        if choice_pairs:
            values, golds = [pair[0] for pair in choice_pairs], [pair[1] for pair in choice_pairs]
            if _field_predicts_gold(values, golds):
                if path not in seen:
                    seen.add(path)
                    found.append(path)
                    if len(found) >= 10:
                        return found
        if synthetic:
            continue
        noul_pairs = [
            (value, gold)
            for value, gold in zip(col, nouls)
            if isinstance(value, (int, float))
            and type(value) is not bool
            and gold is not None
        ]
        if noul_pairs:
            values, golds = [pair[0] for pair in noul_pairs], [pair[1] for pair in noul_pairs]
            if _field_predicts_gold(values, golds):
                if path not in seen:
                    seen.add(path)
                    found.append(path)
                    if len(found) >= 10:
                        return found
    return found


def collect_state_leaks(
    recorded_paths: Mapping[str, str],
    pack_dir: Path | str | None = None,
) -> list[str]:
    """Pack-level gold-label leak detector.

    A non-``message`` field leaks when its *repeated* values predict the row
    gold — ``labels.action.choice`` (L3) or ``labels.domain.choice`` (L2),
    and independently ``labels.safe.noul`` for numeric fields — across the
    pack. Key names are not a refuse rule: ``risk_hint`` with a constant
    placeholder must pass; a brand-new key whose values track gold must
    refuse. JSON objects inside strings (including a JSON tail on
    ``message``), base64-encoded labels, top-level extra keys, nested
    state, and ``*.jsonl`` sidecars in ``pack_dir`` are unwrapped and
    scored the same way. JSON ``null`` is the ``__null__`` category;
    a field missing from a row is ``__absent__`` (distinct from null).
    Every column also yields a ``.__present__`` feature, and every
    mapping yields a ``.__key_count__`` feature, so presence-only and
    key-count leaks are scored, not dropped. Train, holdout, and the
    pooled pack are scored separately; a leak on any slice refuses.

    Measure. Let U = Theil's uncertainty coefficient
    ``MI(field; gold) / H(gold)``. Conditional accuracy is the empirical
    per-value majority classifier, restricted to values with support
    ``LEAK_MIN_SUPPORT`` (2). Majority baseline is the most common gold
    among those supported rows.

    Thresholds (statistical defaults, not per-fixture tunings):
    - Constants (1 distinct value) and unique-per-row fields (cardinality
      == n) always pass. Unique fields can memorize any labeling; constants
      cannot separate classes.
    - A constant gold (one class among the rows that have the field) always
      passes: any co-occurring field would look perfect otherwise.
    - Fail closed at small n: accuracy >= ``LEAK_NEAR_PERFECT_ACC`` (0.999)
      on supported rows refuses even a 3-row A,A,B copy. A 2-row A,B copy
      is unique-per-row and passes.
    - Partial leaks: U >= ``LEAK_U_THRESHOLD`` (0.50) and accuracy at least
      ``LEAK_LIFT_MARGIN`` (0.20) above the majority baseline. Half of gold
      entropy plus 20pp lift is "matches on most rows" without flagging a
      mixed ``status`` cycle (~chance) or ordinary ``meta.tool`` / ``lang``.
    """
    sidecar_by_id: dict[str, dict[str, object]] = {}
    for sidecar in _sidecar_jsonl_paths(pack_dir):
        for rid, fields in _fields_from_sidecar(sidecar).items():
            sidecar_by_id.setdefault(rid, {}).update(fields)

    slices: list[tuple[str, list[dict[str, Any]]]] = [
        ("", _unique_pack_rows(recorded_paths)),
        ("train:", _load_jsonl_rows(recorded_paths.get("train"))),
        ("holdout:", _load_jsonl_rows(recorded_paths.get("holdout"))),
    ]
    found: list[str] = []
    seen: set[str] = set()
    for prefix, rows in slices:
        for path in _leak_hits_for_rows(rows, sidecar_by_id):
            item = f"{prefix}{path}" if prefix else path
            if item not in seen:
                seen.add(item)
                found.append(item)
                if len(found) >= 10:
                    return found
    return found


def _training_rows(recorded_paths: Mapping[str, str]) -> list[dict[str, Any]]:
    rows = _load_jsonl_rows(recorded_paths.get("train"))
    if rows:
        return rows
    return _unique_pack_rows(recorded_paths)


def collect_content_uuid_collisions(recorded_paths: Mapping[str, str]) -> list[str]:
    """Refuse label conflicts and report duplicates. Never silently dedupe."""
    rows = _unique_pack_rows(recorded_paths)
    conflicts, duplicates = content_uuid.find_content_uuid_collisions(rows)
    return [*conflicts, *duplicates]


def collect_forged_content_uuids(recorded_paths: Mapping[str, str]) -> list[str]:
    hits: list[str] = []
    for row in _training_rows(recorded_paths):
        try:
            content_uuid.verify_content_uuid(row)
        except content_uuid.ContentUuidError as exc:
            hits.append(str(exc))
            if len(hits) >= 10:
                return hits
    return hits


def _reserved_partition_cfg(manifest: Mapping[str, Any]) -> Mapping[str, Any] | None:
    cfg = manifest.get("reserved_eval_partition")
    if cfg is None:
        return None
    if not isinstance(cfg, Mapping):
        _refuse("reserved_eval_partition", "object with n and k", type(cfg).__name__)
    if "n" not in cfg or "k" not in cfg:
        _refuse("reserved_eval_partition", "n and k (no default)", sorted(cfg))
    modulus = cfg["n"]
    residue = cfg["k"]
    if type(modulus) is not int or isinstance(modulus, bool) or modulus < 2:
        _refuse("reserved_eval_partition.n", "int >= 2", modulus)
    if type(residue) is not int or isinstance(residue, bool) or residue < 0 or residue >= modulus:
        _refuse("reserved_eval_partition.k", f"int in [0, {modulus})", residue)
    raw_shas = cfg.get("content_shas", cfg.get("reserved_content_shas", []))
    if raw_shas is None:
        raw_shas = []
    if not isinstance(raw_shas, list):
        _refuse("reserved_eval_partition.content_shas", "list of sha256 hex", type(raw_shas).__name__)
    shas: set[str] = set()
    for idx, value in enumerate(raw_shas):
        shas.add(_require_sha256_hex(f"reserved_eval_partition.content_shas[{idx}]", value))
    return {"n": modulus, "k": residue, "content_shas": shas}


def collect_reserved_partition(
    manifest: Mapping[str, Any],
    recorded_paths: Mapping[str, str],
) -> list[str]:
    """Refuse training rows in the reserved eval partition (conditions 1 and 2).

    Condition 1: ``int(sha256(uuid_text), 16) % n == k`` with ``n`` and ``k``
    from ``MANIFEST.reserved_eval_partition``. There is no default that passes.
    Condition 2: the row's content uuid (same helper Mill uses) is in
    ``content_shas``. A row satisfies the uuid rule with ``source.uuid`` or a
    content uuid the gate recomputes and verifies. Missing both refuses.
    """
    cfg = _reserved_partition_cfg(manifest)
    if cfg is None:
        return []
    hits: list[str] = []
    modulus = cfg["n"]
    residue = cfg["k"]
    reserved = cfg["content_shas"]
    for row in _training_rows(recorded_paths):
        rid = _row_id(row)
        try:
            verified = content_uuid.verify_content_uuid(row)
        except content_uuid.ContentUuidError as exc:
            hits.append(str(exc))
            if len(hits) >= 10:
                return hits
            continue
        uuid_text = content_uuid.source_uuid_text(row)
        if uuid_text is None and verified is None:
            hits.append(f"{rid}:missing source.uuid")
            if len(hits) >= 10:
                return hits
            continue
        if uuid_text is None:
            uuid_text = verified
        digest = hashlib.sha256(uuid_text.encode("utf-8")).hexdigest()
        if int(digest, 16) % modulus == residue:
            hits.append(f"{rid}:uuid_mod=={residue}")
        content_sha = content_uuid.content_uuid(row)
        if content_sha in reserved:
            hits.append(f"{rid}:reserved content sha {content_sha}")
        if len(hits) >= 10:
            return hits
    return hits


def enforce_pack_gates(
    manifest: Mapping[str, Any],
    recorded_paths: Mapping[str, str],
    *,
    smoke: bool = False,
    pack_dir: Path | str | None = None,
) -> None:
    hits = collect_not_for_train(manifest, recorded_paths)
    if hits and not smoke:
        _refuse("not_for_train", False, hits[:10])
    collisions = collect_content_uuid_collisions(recorded_paths)
    if collisions:
        field = (
            "content_uuid.label_conflict"
            if collisions[0].startswith("label conflict:")
            else "content_uuid.duplicate"
        )
        _refuse(field, "unique content uuid per labels", collisions[:10])
    forged = collect_forged_content_uuids(recorded_paths)
    if forged:
        _refuse("content_uuid", "recomputed digest", forged[:10])
    reserved = collect_reserved_partition(manifest, recorded_paths)
    if reserved:
        _refuse("reserved_eval_partition", "outside reserved slice", reserved[:10])
    leaks = collect_state_leaks(recorded_paths, pack_dir=pack_dir)
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
    return {
        "exit_code": None,
        "signal": None,
        "timeout": False,
        "waited": waited,
        "observed": False,
    }


def _trainer_exit_is_observed(info: Mapping[str, Any]) -> bool:
    if not info.get("waited"):
        return False
    if info.get("timeout"):
        return True
    if info.get("signal") is not None:
        return True
    return info.get("exit_code") is not None


def _trainer_exit_is_bad(info: Mapping[str, Any]) -> bool:
    if not _trainer_exit_is_observed(info):
        return True
    if info.get("timeout"):
        return True
    if info.get("signal") is not None:
        return True
    return info.get("exit_code") not in (0,)


def _trainer_stdout_is_spoofed(text: str) -> bool:
    """Trainer stdout is never a result source. Flag MATCH-like evidence lines."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(INTEGRITY_EVIDENCE_LINE_PREFIX):
            return True
        if stripped.startswith("INTEGRITY_EVIDENCE "):
            return True
    return False


def combine_trainer_exits(parts: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Prefer the last waited trainer; unobserved or nonzero/signal/timeout is REFUSED."""
    recorded = _empty_trainer_exit()
    bad: dict[str, Any] | None = None
    for part in parts:
        if not isinstance(part, Mapping):
            continue
        slim = {
            "exit_code": part.get("exit_code"),
            "signal": part.get("signal"),
            "timeout": bool(part.get("timeout")),
            "waited": bool(part.get("waited")),
            "observed": False,
        }
        slim["observed"] = _trainer_exit_is_observed(slim)
        if slim["waited"]:
            recorded = slim
        if _trainer_exit_is_bad(slim) and slim["observed"]:
            bad = slim
    if bad is not None:
        return bad
    if not recorded.get("observed"):
        return _empty_trainer_exit()
    return recorded


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
    info = {
        "exit_code": code,
        "signal": None,
        "timeout": False,
        "waited": True,
        "observed": True,
    }
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
            return {
                "exit_code": None,
                "signal": None,
                "timeout": True,
                "waited": True,
                "observed": True,
            }
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
                return {
                    "exit_code": -sig,
                    "signal": sig,
                    "timeout": False,
                    "waited": True,
                    "observed": True,
                }
            if os.WIFEXITED(status):
                return {
                    "exit_code": os.WEXITSTATUS(status),
                    "signal": None,
                    "timeout": False,
                    "waited": True,
                    "observed": True,
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
            "observed": True,
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
        return {
            "exit_code": code_i,
            "signal": sig,
            "timeout": False,
            "waited": True,
            "observed": True,
        }
    if "exit_code" in launched:
        code = launched.get("exit_code")
        try:
            code_i = int(code) if code is not None else 0
        except (TypeError, ValueError):
            _refuse("trainer.exit", "int exit_code", code)
            raise AssertionError("unreachable")
        info = {
            "exit_code": code_i,
            "signal": None,
            "timeout": False,
            "waited": True,
            "observed": True,
        }
        if code_i < 0:
            info["signal"] = -code_i
        return info
    return _empty_trainer_exit()


def apply_trainer_exit(record: dict[str, Any], exit_info: Mapping[str, Any] | None) -> dict[str, Any]:
    """Record trainer exit on the integrity evidence. Unobserved or bad exit is REFUSED."""
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
        pass
    else:
        try:
            exit_code = int(exit_code)
        except (TypeError, ValueError):
            _refuse("trainer.exit", "int exit_code", exit_code)
            raise AssertionError("unreachable")
    record["exit_code"] = exit_code
    record["trainer_exit_waited"] = bool(info.get("waited"))
    record["trainer_exit_observed"] = _trainer_exit_is_observed(info)
    if signal is not None:
        record["signal"] = signal
    if timeout:
        record["timeout"] = True
    unobserved = not _trainer_exit_is_observed(info)
    bad = unobserved or timeout or signal is not None or exit_code not in (0,)
    if bad and record.get("status") == CHECKPOINT_MATCH:
        record["status"] = CHECKPOINT_REFUSED
        record["match"] = False
        record["field"] = "trainer.exit"
        record["expected"] = 0
        if unobserved:
            record["actual"] = "unobserved"
        elif timeout:
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
    enforce_pack_gates(
        manifest, trainer_paths, smoke=smoke, pack_dir=pack_root
    )

    return {
        "pack_id": pack_id,
        "host": socket.gethostname(),
        "anchor_source": PIN_SOURCE,
        "pin": pin,
        "computed_shas": computed_shas,
        "private_copy_shas": dict(computed_shas),
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
    """Atomically write evidence JSON (mkstemp in the same directory + os.replace).

    Checkpoint ``integrity_evidence.json`` must use
    ``write_integrity_evidence_held`` instead: this replace path is the B-RACE
    window. Overwrite is only for the run-dir pack evidence log.
    """
    evidence_path = Path(evidence_path)
    if evidence_path.name == INTEGRITY_EVIDENCE_NAME:
        write_integrity_evidence_held(dict(evidence), evidence_path)
        return evidence_path
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
    if mode is not None and os.name == "posix":
        os.chmod(evidence_path, mode)
    return evidence_path


def write_integrity_evidence_held(
    record: Mapping[str, Any],
    evidence_path: Path,
) -> dict[str, Any]:
    """O_CREAT|O_EXCL write of checkpoint evidence. Hash the bytes written.

    Completion ``result`` is the in-memory ``record["status"]``, never a
    re-read of a replaceable path. After fsync/fchmod, fstat the held fd
    and refuse if the named path's dev/inode differ (swapper).
    """
    evidence_path = Path(evidence_path)
    public = _public_integrity_record(record)
    payload = (json.dumps(public, indent=2) + "\n").encode("utf-8")
    sha256_evidence = hashlib.sha256(payload).hexdigest()
    status = public.get("status")
    result = status if status in (CHECKPOINT_MATCH, CHECKPOINT_REFUSED) else CHECKPOINT_REFUSED
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(evidence_path):
        try:
            os.chmod(evidence_path, 0o600)
        except OSError:
            pass
        try:
            os.unlink(evidence_path)
        except OSError as exc:
            _refuse(INTEGRITY_EVIDENCE_NAME, "exclusive create", f"OSError:{exc.errno}")
    try:
        fd = os.open(str(evidence_path), _open_flags_write(), 0o600)
    except OSError as exc:
        _refuse(INTEGRITY_EVIDENCE_NAME, "exclusive create", f"OSError:{exc.errno}")
    try:
        view = memoryview(payload)
        offset = 0
        while offset < len(payload):
            offset += os.write(fd, view[offset:])
        if hasattr(os, "fsync"):
            os.fsync(fd)
        if os.name == "posix" and hasattr(os, "fchmod"):
            os.fchmod(fd, 0o400)
        written = os.fstat(fd)
        try:
            named = os.lstat(evidence_path)
        except OSError as exc:
            _refuse(INTEGRITY_EVIDENCE_NAME, "same inode", f"OSError:{exc.errno}")
        if (written.st_dev, written.st_ino) != (named.st_dev, named.st_ino):
            _refuse(INTEGRITY_EVIDENCE_NAME, "same inode", "path swapped")
        if named.st_nlink != 1:
            _refuse(INTEGRITY_EVIDENCE_NAME, "nlink=1", named.st_nlink)
        if os.name == "posix" and stat.S_IMODE(written.st_mode) != 0o400:
            _refuse(
                INTEGRITY_EVIDENCE_NAME,
                "0400",
                oct(stat.S_IMODE(written.st_mode)),
            )
    except KickRefused:
        raise
    except OSError as exc:
        _refuse(INTEGRITY_EVIDENCE_NAME, "held-fd write", f"OSError:{exc.errno}")
    finally:
        os.close(fd)
    return {
        "sha256_evidence": sha256_evidence,
        "integrity_evidence": json.loads(payload.decode("utf-8")),
        "result": result,
        "st_dev": written.st_dev,
        "st_ino": written.st_ino,
    }


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
    sealed: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Emit the human line from the in-memory held-fd write. Never re-parse for result."""
    if sealed is None:
        sealed = write_integrity_evidence_held(record, evidence_path)
    out = dict(sealed)
    line = emit_integrity_evidence_line(
        evidence_path,
        record,
        log_path=log_path,
        sha256_evidence=out["sha256_evidence"],
    )
    out["integrity_evidence_line"] = line
    out["result"] = (
        record["status"]
        if record.get("status") in (CHECKPOINT_MATCH, CHECKPOINT_REFUSED)
        else CHECKPOINT_REFUSED
    )
    return out


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
        public = _public_integrity_record(record)
        public.update(_entrypoint_event_fields(evidence))
        if "script_git_sha" in evidence:
            public["script_git_sha"] = evidence["script_git_sha"]
        if isinstance(evidence.get("private_copy_shas"), Mapping):
            public["private_copy_shas"] = dict(evidence["private_copy_shas"])
        if evidence.get("run_private_dir"):
            public["run_private_dir"] = evidence["run_private_dir"]
        if "stdout_spoof" in evidence:
            public["stdout_spoof"] = bool(evidence["stdout_spoof"])
        if "scorable" in evidence:
            public["scorable"] = bool(evidence["scorable"])
        in_memory_result = (
            record["status"]
            if record.get("status") in (CHECKPOINT_MATCH, CHECKPOINT_REFUSED)
            else CHECKPOINT_REFUSED
        )
        sealed = write_integrity_evidence_held(public, ckpt_path)
        try:
            named = os.lstat(ckpt_path)
        except OSError as exc:
            _refuse(INTEGRITY_EVIDENCE_NAME, "same inode", f"OSError:{exc.errno}")
        if (named.st_dev, named.st_ino) != (sealed["st_dev"], sealed["st_ino"]):
            _refuse(INTEGRITY_EVIDENCE_NAME, "same inode", "path swapped")
        sealed = seal_integrity_evidence(
            ckpt_path, record, log_path=log_path, sealed=sealed
        )
        evidence["checkpoint_integrity_evidence_path"] = str(ckpt_path.resolve())
        evidence["checkpoint_integrity_status"] = record["status"]
        evidence["integrity_evidence_line"] = sealed["integrity_evidence_line"]
        evidence["sha256_evidence"] = sealed["sha256_evidence"]
        evidence["integrity_evidence"] = sealed["integrity_evidence"]
        evidence["result"] = in_memory_result
        if post_completion:
            completion = {
                "run_id": evidence["run_id"],
                "sha256_evidence": sealed["sha256_evidence"],
                "sha256_pack": _sha_from_record(record, "sha256_pack"),
                "sha256_train": _sha_from_record(record, "sha256_train"),
                "sha256_holdout": _sha_from_record(record, "sha256_holdout"),
                "result": in_memory_result,
                "exit_code": record.get("exit_code", 0),
            }
            completion.update(_entrypoint_event_fields(evidence))
            try:
                _post_hq_event("completion", completion)
            except KickRefused as exc:
                refused = dict(public)
                refused["status"] = CHECKPOINT_REFUSED
                refused["match"] = False
                refused["field"] = "hq.event"
                refused["expected"] = "posted"
                refused["actual"] = "hq_post_failed"
                write_integrity_evidence_held(refused, ckpt_path)
                evidence["checkpoint_integrity_status"] = CHECKPOINT_REFUSED
                evidence["result"] = CHECKPOINT_REFUSED
                evidence["hq_post_failed"] = True
                evidence["ok"] = False
                raise KickRefused("hq.event", "posted", "hq_post_failed") from exc
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
    pinned = load_pinned_copy_mode()
    if pinned is not None:
        git_sha = None
        entrypoint_pins = dict(pinned["files"])
        pins_source_commit = pinned["head"]
        cam_pin_spec.bind_pinned_copy_trust(pinned["root"])
        trust_blobs = dict(pinned["trust_blobs"])
    else:
        git_sha = _script_git_sha()
        entrypoint_pins, pins_source_commit = load_entrypoint_pins(git_sha=git_sha)
        try:
            trust_blobs = cam_pin_spec.require_committed_trust()
        except cam_pin_spec.CamPinError as exc:
            _refuse(exc.field, exc.expected, exc.actual)
    evidence: dict[str, Any] = {
        "ok": False,
        "run_id": run_id,
        "checkpoint_id": None,
        "script_git_sha": git_sha,
        "script_sha256": (
            pinned["files"][PINNED_COPY_KICK_REL] if pinned is not None else _script_sha256()
        ),
        "entrypoint_pins": entrypoint_pins,
        "pins_source_commit": pins_source_commit,
        "kickoff_url": kickoff_url,
        "host": socket.gethostname(),
        "anchor_source": PIN_SOURCE,
        "evidence_path": str(evidence_path.resolve()),
        "checked_at": _utc_now(),
        "trust_blobs": trust_blobs,
        "head_sha": trust_blobs.get("HEAD"),
    }
    if pinned is not None:
        evidence["head"] = pinned["head"]
        evidence["pins_map_sha256"] = pinned["map_sha256"]
        evidence["pins_file_sha256"] = pinned["file_sha256"]
        evidence["pinned_copy_root"] = str(pinned["root"])
        evidence["script_git_sha_reason"] = PINNED_COPY_REASON

    def persist() -> None:
        write_evidence(evidence, evidence_path)

    try:
        staged = verify_and_stage(pack_dir, run_private=run_private, smoke=smoke)
        evidence.update(staged)
        evidence["run_id"] = run_id
        evidence["checkpoint_id"] = None
        evidence["script_git_sha"] = git_sha
        evidence["script_sha256"] = evidence.get("script_sha256") or _script_sha256()
        evidence["entrypoint_pins"] = entrypoint_pins
        evidence["pins_source_commit"] = pins_source_commit
        evidence["kickoff_url"] = kickoff_url
        evidence["evidence_path"] = str(evidence_path.resolve())
        evidence["trust_blobs"] = trust_blobs
        evidence["head_sha"] = trust_blobs.get("HEAD")
        if pinned is not None:
            evidence["head"] = pinned["head"]
            evidence["entrypoint_pins"] = dict(pinned["files"])
            evidence["pins_map_sha256"] = pinned["map_sha256"]
            evidence["pins_file_sha256"] = pinned["file_sha256"]
            evidence["pinned_copy_root"] = str(pinned["root"])
            evidence["script_git_sha"] = None
            evidence["script_git_sha_reason"] = PINNED_COPY_REASON
            evidence["script_sha256"] = pinned["files"][PINNED_COPY_KICK_REL]
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
            kick_event = {
                "run_id": run_id,
                "sha256_pack": evidence["computed_shas"]["sha256_pack"],
                "sha256_train": evidence["computed_shas"]["sha256_train"],
                "sha256_holdout": evidence["computed_shas"]["sha256_holdout"],
            }
            kick_event.update(_entrypoint_event_fields(evidence))
            _post_hq_event("kick", kick_event)
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
        captured = StringIO()
        with redirect_stdout(captured):
            if start_training is None:
                started = _authorized_start_training(run_private, evidence, log_path, _gate=_GATE_OK)
            else:
                started = start_training(run_private, evidence, log_path)
        trainer_stdout = captured.getvalue()
        if trainer_stdout:
            sys.stdout.write(trainer_stdout)
            sys.stdout.flush()
        spoofed = _trainer_stdout_is_spoofed(trainer_stdout)
        evidence["stdout_spoof"] = spoofed
        evidence["scorable"] = (not spoofed) and (not smoke)
        persist()
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
