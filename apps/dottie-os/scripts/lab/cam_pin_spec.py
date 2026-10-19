#!/usr/bin/env python3
"""Cam-signed Swarm HQ pack-pin: canonical bytes, Ed25519 verify, pinned origin.

Signed bytes (UTF-8), byte-for-byte::

    swarm-hq-pin-v1\\n
    + JSON object with sorted keys, no whitespace, of exactly
      {pack_id, sha256_pack, sha256_train, sha256_holdout,
       rows_total, rows_train, rows_holdout, recordedAt}

Kicks use ``swarm-hq-pin-v2`` (Ed25519, ``key_id``, binding
``{pack_id, run_id, lease_owner}``, ``issued_at``/``not_before``/``not_after``
with a 24 h cap and 120 s start-side skew, ``nonce``, sha256
pack/train/holdout, ``code_pins`` (path→sha256 for ``CODE_PINS``),
``git_commit``, and ``expires_at``). v1 remains verify-only for history and
is refused for kicks. Timestamps are ASCII-only strict RFC 3339.

The pin JSON also carries ``cam_sig`` (base64 Ed25519 signature of those
bytes) and ``cam_key_id`` / ``key_id``. Verify only against the public key committed at
``apps/dottie-os/trust/cam_pin_ed25519.pub``. Never read a key from env,
argv, or any other path. The child never fetches a pin; it verifies the
staged v2 file the server already verified.

``stampVerified`` and ``pack_matches`` are advisory only: they are never
sufficient and never required for a pass. Trust is the Cam signature plus
this process's own hashes and row counts of the run-private copies.

HQ origin is ``SWARM_HQ_ORIGIN`` in this module. There is no env, CLI, or
config override. Until Cam sets it by PR, the placeholder refuses.
HTTPS only, certificate verification on, no proxies, no redirects.
``x-agent-token`` is attached only after the URL matches that origin.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

CANONICAL_PREFIX = b"swarm-hq-pin-v1\n"
PIN_FORMAT_V1 = "swarm-hq-pin-v1"
PIN_FORMAT_V2 = "swarm-hq-pin-v2"
CANONICAL_PREFIX_V1 = CANONICAL_PREFIX
CANONICAL_PREFIX_V2 = b"swarm-hq-pin-v2\n"
SIGNED_KEYS = (
    "pack_id",
    "sha256_pack",
    "sha256_train",
    "sha256_holdout",
    "rows_total",
    "rows_train",
    "rows_holdout",
    "recordedAt",
)
SIGNED_KEYS_V2 = (
    "binding",
    "code_pins",
    "expires_at",
    "format",
    "git_commit",
    "head",
    "issued_at",
    "key_id",
    "nonce",
    "not_after",
    "not_before",
    "reserved_content_uuids_min_rows",
    "reserved_content_uuids_sha256",
    "rows_holdout",
    "rows_total",
    "rows_train",
    "sha256_holdout",
    "sha256_pack",
    "sha256_train",
)
BINDING_KEYS_V2 = ("lease_owner", "pack_id", "run_id")
PIN_V2_MAX_LIFETIME = timedelta(hours=24)
PIN_V2_NOT_BEFORE_SKEW = timedelta(seconds=120)
NONCE_HEX_LEN = 64
RFC3339_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,9})?"
    r"(Z|[+-][0-9]{2}:[0-9]{2})$"
)
RUN_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
LEASE_OWNER_RE = RUN_ID_RE
# Cam sets this by PR to the production HTTPS origin, e.g. "https://hq.example".
SWARM_HQ_ORIGIN = ""
SWARM_HQ_AGENT_TOKEN_ENV = "SWARM_HQ_AGENT_TOKEN"
PIN_PATH = "/api/packs/{pack_id}/pin"
HQ_EVENT_PATH = "/api/helper-ft/events/{event}"
HQ_EVENTS = frozenset({"kick", "completion"})
MAX_PIN_BYTES = 64 * 1024
HQ_DEADLINE_SECONDS = 15.0
SHA256_LEN = 64
GIT_SHA_LEN = 40
_HEX = frozenset("0123456789abcdef")
_PLACEHOLDER_ORIGIN = frozenset({"", "unset", "placeholder", "todo", "https://unset.invalid"})
_PUB_NAME = "cam_pin_ed25519.pub"
_KEY_ID_NAME = "cam_pin_key_id"


_MODULE_FILE = str(globals().get("__file__") or "")


def _trust_dir_from_here() -> Path:
    """apps/dottie-os/trust next to this file. Sealed /proc/fd and memfd have no tree."""
    here_raw = _MODULE_FILE or str(globals().get("__file__") or "")
    if not here_raw:
        return Path("/var/empty/dottie-os-sealed-trust")
    here = Path(here_raw).resolve()
    posix = here.as_posix()
    if posix.startswith("/proc/") or posix.startswith("/memfd:"):
        return Path("/var/empty/dottie-os-sealed-trust")
    try:
        return here.parents[2] / "trust"
    except IndexError:
        return Path("/var/empty/dottie-os-sealed-trust")


# Frozen path: apps/dottie-os/trust/cam_pin_ed25519.pub relative to this file.
# Pinned-copy mode rebinds these to <copy-root>/apps/dottie-os/trust/.
CAM_PIN_PUB_PATH = _trust_dir_from_here() / _PUB_NAME
CAM_PIN_KEY_ID_PATH = _trust_dir_from_here() / _KEY_ID_NAME
PINNED_COPY_ROOT: Path | None = None
_DEFAULT_CAM_PIN_PUB_PATH = CAM_PIN_PUB_PATH
_DEFAULT_CAM_PIN_KEY_ID_PATH = CAM_PIN_KEY_ID_PATH
# Exact on-disk sentinel. Cam replaces both trust files in one PR.
PLACEHOLDER_PUB_TEXT = (
    "CAM-PIN-ED25519-PLACEHOLDER\n"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=\n"
)
PLACEHOLDER_KEY_ID_TEXT = "CAM-PIN-KEY-ID-PLACEHOLDER\n"
# Swarm HQ vector test key. Never accepted by CLI or :8765.
DENIED_PUBLIC_KEYS_B64 = frozenset(
    {
        "hgbGCZRFE4CiwVB4rLZ015a8QkWEPPAjZT5UIQKDazk=",
    }
)
PACK_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
RECORDED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
B64_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
INT32_MAX = 2**31
# Repo-relative paths whose HEAD blobs must match the working tree.
# Server layout: apps/dottie-os/trust/ (not <copy-root>/trust/).
TRUST_DIR_REL = "apps/dottie-os/trust"
# Single canonical pin set. kick_helper_ft and the launcher alias this object.
CODE_PINS = (
    "apps/dottie-os/scripts/lab/kick_helper_ft.py",
    "apps/dottie-os/scripts/lab/helper_ft_kickoff.py",
    "apps/dottie-os/scripts/lab/cam_pin_spec.py",
    "apps/dottie-os/scripts/lab/content_uuid.py",
    "apps/dottie-os/scripts/lab/near_dup_tokenizer.py",
    "apps/dottie-os/trust/cam_pin_ed25519.pub",
    "apps/dottie-os/trust/cam_pin_key_id",
    "apps/dottie-os/trust/reserved_content_uuids.jsonl",
    "apps/dottie-os/trust/reserved_near_dup_fingerprints.jsonl",
)
REQUIRED_PINS = CODE_PINS
TRUST_RELPATHS = CODE_PINS
CODE_PIN_MODULE_NAMES = {
    "kick_helper_ft": "apps/dottie-os/scripts/lab/kick_helper_ft.py",
    "helper_ft_kickoff": "apps/dottie-os/scripts/lab/helper_ft_kickoff.py",
    "cam_pin_spec": "apps/dottie-os/scripts/lab/cam_pin_spec.py",
    "content_uuid": "apps/dottie-os/scripts/lab/content_uuid.py",
    "near_dup_tokenizer": "apps/dottie-os/scripts/lab/near_dup_tokenizer.py",
}
ORIGIN_MAIN_REF = "origin/main"
# Twisted Edwards Ed25519 (RFC 8032). Cofactor and canonical checks run in
# this module before cryptography's verify. Not a hardcoded encoding list.
ED25519_P = 2**255 - 19
ED25519_L = 2**252 + 27742317777372353535851937790883648493
ED25519_D = (-121665 * pow(121666, -1, ED25519_P)) % ED25519_P
ED25519_I = pow(2, (ED25519_P - 1) // 4, ED25519_P)
ED25519_IDENTITY = (0, 1)

HQ_PIN_REQUIRED_KEYS = (
    "pack_id",
    "sha256_pack",
    "sha256_train",
    "sha256_holdout",
    "rows_total",
    "rows_train",
    "rows_holdout",
    "recordedAt",
    "kid",
    "cam_sig",
    "cam_key_id",
)
HQ_PIN_ALLOWED_KEYS = frozenset(
    (
        *HQ_PIN_REQUIRED_KEYS,
        "recordedBy",
        "stampVerified",
        "verified",
        "pack_matches",
    )
)
V2_PIN_REQUIRED_KEYS = (
    *SIGNED_KEYS_V2,
    "cam_sig",
)
V2_PIN_ALLOWED_KEYS = frozenset(
    (
        *V2_PIN_REQUIRED_KEYS,
        "recordedBy",
        "stampVerified",
        "verified",
        "pack_matches",
        "kid",
        "cam_key_id",
        "recordedAt",
        "pack_id",
        "run_id",
        "lease_owner",
        "source",
    )
)


class CamPinError(Exception):
    """Pin fetch or verify failed. ``field``, ``expected``, ``actual`` named."""

    def __init__(self, field: str, expected: object, actual: object) -> None:
        self.field = field
        self.expected = expected
        self.actual = actual
        super().__init__(f"HELPER FT refused: {field}: expected {expected} actual {actual}")


def _refuse(field: str, expected: object, actual: object) -> None:
    raise CamPinError(field, expected, actual)


def require_sha256_hex(field: str, value: object) -> str:
    """Strict lowercase hex, 64 chars. No strip, no case-fold."""
    if type(value) is not str or not value:
        _refuse(field, "present", "missing")
    if len(value) != SHA256_LEN or any(ch not in _HEX for ch in value):
        _refuse(field, "64-char lowercase hex", value)
    return value


def require_int(field: str, value: object) -> int:
    if type(value) is bool or type(value) is not int:
        label = "bool" if isinstance(value, bool) else type(value).__name__
        _refuse(field, "int", label)
    if value < 0 or value > INT32_MAX:
        _refuse(field, "int 0..2^31", value)
    return value


def require_pack_id(field: str, value: object) -> str:
    if type(value) is not str or not value:
        _refuse(field, "present", "missing")
    if PACK_ID_RE.fullmatch(value) is None:
        _refuse(field, "ASCII [A-Za-z0-9._-]{1,128}", value)
    return value


def require_recorded_at(field: str, value: object) -> str:
    if type(value) is not str or not value:
        _refuse(field, "present", "missing")
    if RECORDED_AT_RE.fullmatch(value) is None:
        _refuse(field, "YYYY-MM-DDTHH:MM:SS.mmmZ", value)
    return value


def require_b64(field: str, value: object, decoded_len: int) -> bytes:
    """Standard alphabet, padded, round-trips, exact decoded length."""
    if type(value) is not str or not value:
        _refuse(field, "present", "missing")
    if B64_RE.fullmatch(value) is None or len(value) % 4 != 0:
        _refuse(field, "standard padded base64", value)
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        _refuse(field, "standard padded base64", "invalid")
    if len(raw) != decoded_len:
        _refuse(field, f"{decoded_len} bytes", f"len {len(raw)}")
    roundtrip = base64.b64encode(raw).decode("ascii")
    if roundtrip != value:
        _refuse(field, "round-trip base64", value)
    return raw


def canonical_pin_bytes(fields: dict[str, Any]) -> bytes:
    """v1 signed payload (history / verify-only). Swarm HQ v1 must match byte for byte."""
    missing = [key for key in SIGNED_KEYS if key not in fields]
    if missing:
        _refuse(f"cam-pin.{missing[0]}", "present", "missing")
    body = {key: fields[key] for key in SIGNED_KEYS}
    packed = json.dumps(body, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    return CANONICAL_PREFIX + packed.encode("utf-8")


def canonical_pin_bytes_v2(fields: dict[str, Any]) -> bytes:
    """v2 signed payload. r6 / kicks must match this byte for byte."""
    missing = [key for key in SIGNED_KEYS_V2 if key not in fields]
    if missing:
        _refuse(f"cam-pin.{missing[0]}", "present", "missing")
    body = {key: fields[key] for key in SIGNED_KEYS_V2}
    packed = json.dumps(body, separators=(",", ":"), sort_keys=True, ensure_ascii=True)
    return CANONICAL_PREFIX_V2 + packed.encode("ascii")


def require_rfc3339(field: str, value: object) -> datetime:
    """ASCII-only strict RFC 3339 with timezone. No space-separated form."""
    if type(value) is not str or not value:
        _refuse(field, "present", "missing")
    if not value.isascii():
        _refuse(field, "ASCII-only RFC 3339", "non-ascii")
    if RFC3339_RE.fullmatch(value) is None:
        _refuse(field, "strict RFC 3339", value)
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        _refuse(field, "strict RFC 3339", value)
        raise AssertionError("unreachable")
    if parsed.tzinfo is None:
        _refuse(field, "RFC 3339 with timezone", value)
    return parsed.astimezone(timezone.utc)


def require_run_id(field: str, value: object) -> str:
    if type(value) is not str or not value:
        _refuse(field, "present", "missing")
    if RUN_ID_RE.fullmatch(value) is None:
        _refuse(field, "ASCII [A-Za-z0-9._:-]{1,128}", value)
    return value


def require_lease_owner(field: str, value: object) -> str:
    if type(value) is not str or not value:
        _refuse(field, "present", "missing")
    if LEASE_OWNER_RE.fullmatch(value) is None:
        _refuse(field, "ASCII [A-Za-z0-9._:-]{1,128}", value)
    return value


def require_nonce(field: str, value: object) -> str:
    return require_sha256_hex(field, value)


def require_git_commit(field: str, value: object) -> str:
    if type(value) is not str or len(value) != GIT_SHA_LEN or any(ch not in _HEX for ch in value):
        _refuse(field, "40-char lowercase hex", value)
    return value


def require_code_pins(value: object) -> dict[str, str]:
    """Exact CODE_PINS keys, each a 64-char lowercase sha256. No extra paths."""
    if not isinstance(value, dict) or not value:
        _refuse(
            "cam-pin.code_pins",
            "path→sha256 object",
            type(value).__name__ if not isinstance(value, dict) else "empty",
        )
    extra = [key for key in value if key not in CODE_PINS]
    if extra:
        _refuse("cam-pin.code_pins", "CODE_PINS paths", f"unknown {extra[0]}")
    pins: dict[str, str] = {}
    for rel in CODE_PINS:
        if rel not in value:
            _refuse("cam-pin.code_pins", f"pin covering {rel}", "missing")
        pins[rel] = require_sha256_hex(f"cam-pin.code_pins.{rel}", value.get(rel))
    return pins


def code_pins_root() -> Path:
    """Repo or pinned-copy root that holds CODE_PINS paths."""
    if PINNED_COPY_ROOT is not None:
        return Path(PINNED_COPY_ROOT)
    return Path(__file__).resolve().parents[4]


def sha256_file_bytes(path: Path) -> tuple[bytes, str]:
    """One read: return file bytes and sha256. Caller must not re-open the path."""
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        _refuse(str(path), "readable regular file", f"OSError:{exc.errno}")
        raise AssertionError("unreachable") from exc
    try:
        chunks: list[bytes] = []
        while True:
            block = os.read(fd, 1 << 20)
            if not block:
                break
            chunks.append(block)
        buf = b"".join(chunks)
    except OSError as exc:
        _refuse(str(path), "readable regular file", f"OSError:{exc.errno}")
        raise AssertionError("unreachable") from exc
    finally:
        os.close(fd)
    return buf, hashlib.sha256(buf).hexdigest()


def live_code_pins(*, root: Path | None = None) -> dict[str, str]:
    """sha256 of each CODE_PINS path under ``root`` (repo or pinned-copy)."""
    base = Path(root).resolve() if root is not None else code_pins_root().resolve()
    pins: dict[str, str] = {}
    for rel in CODE_PINS:
        path = (base / rel).resolve()
        try:
            path.relative_to(base)
        except ValueError:
            _refuse(f"cam-pin.code_pins.{rel}", f"under {base}", str(path))
        if not path.is_file():
            _refuse(f"cam-pin.code_pins.{rel}", "readable regular file", "missing")
        _buf, digest = sha256_file_bytes(path)
        pins[rel] = digest
    return pins


def verify_code_pins_match(
    code_pins: dict[str, str],
    *,
    root: Path | None = None,
) -> dict[str, str]:
    """Refuse any missing or mismatched CODE_PINS hash against live files."""
    expected = require_code_pins(code_pins)
    live = live_code_pins(root=root)
    for rel in CODE_PINS:
        if expected[rel] != live[rel]:
            _refuse(f"cam-pin.code_pins.{rel}", live[rel], expected[rel])
    return expected


def _require_v2_binding(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        _refuse("cam-pin.binding", "object", type(value).__name__)
    extra = [key for key in value if key not in BINDING_KEYS_V2]
    if extra:
        _refuse("cam-pin.binding", "pack_id,run_id,lease_owner", f"unknown {extra[0]}")
    binding = {
        "pack_id": require_pack_id("cam-pin.binding.pack_id", value.get("pack_id")),
        "run_id": require_run_id("cam-pin.binding.run_id", value.get("run_id")),
        "lease_owner": require_lease_owner(
            "cam-pin.binding.lease_owner", value.get("lease_owner")
        ),
    }
    return binding


def pin_format_of(record: dict[str, Any]) -> str:
    fmt = record.get("format")
    if type(fmt) is str and fmt:
        return fmt
    if "binding" in record and "issued_at" in record:
        return PIN_FORMAT_V2
    return PIN_FORMAT_V1


def verify_v2_lifetime(
    issued_at: datetime,
    not_before: datetime,
    not_after: datetime,
    *,
    now: datetime | None = None,
) -> None:
    """Cap 24 h. 120 s skew on the start side only. No grace past not_after."""
    if not_after < not_before:
        _refuse("cam-pin.not_after", ">= not_before", not_after.isoformat())
    if not_after - not_before > PIN_V2_MAX_LIFETIME:
        _refuse("cam-pin.lifetime", "<= 24h", str((not_after - not_before).total_seconds()))
    if issued_at > not_after:
        _refuse("cam-pin.issued_at", "<= not_after", issued_at.isoformat())
    if not_after - issued_at > PIN_V2_MAX_LIFETIME:
        _refuse("cam-pin.lifetime", "<= 24h from issued_at", str((not_after - issued_at).total_seconds()))
    instant = now if now is not None else datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    instant = instant.astimezone(timezone.utc)
    if instant < not_before - PIN_V2_NOT_BEFORE_SKEW:
        _refuse("cam-pin.not_before", "now within 120s skew", instant.isoformat())
    if instant > not_after:
        _refuse("cam-pin.not_after", "not expired", instant.isoformat())


def sign_pin_v2(fields: dict[str, Any], raw_private: bytes) -> str:
    """Cam-side CLI and tests only. Kick and :8765 must not call this.

    The private key is never read here. ``tools/sign_cam_pin.py`` supplies
    bytes from a path or stdin on Cam's device. Tests generate ephemeral
    keys at runtime.
    """
    message = canonical_pin_bytes_v2(fields)
    return sign_pin_bytes(message, raw_private)


def verify_cam_sig_v1(record: dict[str, Any]) -> None:
    """History: verify a swarm-hq-pin-v1 signature. Not valid for kicks."""
    verify_cam_sig(record)


def verify_cam_sig_v2(record: dict[str, Any]) -> None:
    key_id, public = load_cam_public_key()
    pin_kid = record.get("key_id")
    if type(pin_kid) is not str or not pin_kid:
        _refuse("cam-pin.key_id", "present", "missing")
    if pin_kid != key_id:
        _refuse("cam-pin.key_id", key_id, pin_kid)
    alias = record.get("cam_key_id")
    if alias is not None and alias != pin_kid:
        _refuse("cam-pin.cam_key_id", pin_kid, alias)
    signature = require_b64("cam-pin.cam_sig", record.get("cam_sig"), 64)
    message = canonical_pin_bytes_v2(record)
    public_raw = public.public_bytes(Encoding.Raw, PublicFormat.Raw)
    verify_ed25519(message, signature, public_raw)


def parse_v2_pin_payload(
    payload: object,
    *,
    now: datetime | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Parse and verify a staged swarm-hq-pin-v2. Refuses v1. Never fetches."""
    if not isinstance(payload, dict) or not payload:
        _refuse("cam-pin", "present", "missing")
    fmt = pin_format_of(payload)
    if fmt != PIN_FORMAT_V2:
        _refuse("cam-pin.format", PIN_FORMAT_V2, fmt)
    unknown = [key for key in payload if key not in V2_PIN_ALLOWED_KEYS]
    if unknown:
        _refuse("cam-pin", "v2 pin keys", f"unknown {unknown[0]}")
    for key in V2_PIN_REQUIRED_KEYS:
        if key not in payload:
            _refuse(f"cam-pin.{key}", "present", "missing")
    if payload.get("format") != PIN_FORMAT_V2:
        _refuse("cam-pin.format", PIN_FORMAT_V2, payload.get("format"))
    binding = _require_v2_binding(payload.get("binding"))
    issued_at = require_rfc3339("cam-pin.issued_at", payload.get("issued_at"))
    not_before = require_rfc3339("cam-pin.not_before", payload.get("not_before"))
    not_after = require_rfc3339("cam-pin.not_after", payload.get("not_after"))
    verify_v2_lifetime(issued_at, not_before, not_after, now=now)
    expires_at = require_rfc3339("cam-pin.expires_at", payload.get("expires_at"))
    if payload.get("expires_at") != payload.get("not_after"):
        _refuse("cam-pin.expires_at", payload.get("not_after"), payload.get("expires_at"))
    if expires_at != not_after:
        _refuse("cam-pin.expires_at", not_after.isoformat(), expires_at.isoformat())
    nonce = require_nonce("cam-pin.nonce", payload.get("nonce"))
    code_pins = require_code_pins(payload.get("code_pins"))
    git_commit = require_git_commit("cam-pin.git_commit", payload.get("git_commit"))
    head = require_git_commit("cam-pin.head", payload.get("head"))
    if head != git_commit:
        _refuse("cam-pin.head", git_commit, head)
    record: dict[str, Any] = {
        "format": PIN_FORMAT_V2,
        "key_id": payload["key_id"],
        "binding": binding,
        "issued_at": payload["issued_at"],
        "not_before": payload["not_before"],
        "not_after": payload["not_after"],
        "expires_at": payload["expires_at"],
        "nonce": nonce,
        "code_pins": code_pins,
        "git_commit": git_commit,
        "head": head,
        "sha256_pack": require_sha256_hex("cam-pin.sha256_pack", payload.get("sha256_pack")),
        "sha256_train": require_sha256_hex("cam-pin.sha256_train", payload.get("sha256_train")),
        "sha256_holdout": require_sha256_hex(
            "cam-pin.sha256_holdout", payload.get("sha256_holdout")
        ),
        "pack_id": binding["pack_id"],
        "run_id": binding["run_id"],
        "lease_owner": binding["lease_owner"],
        "cam_sig": payload["cam_sig"],
        "cam_key_id": payload.get("cam_key_id", payload["key_id"]),
        "kid": payload.get("kid", payload["key_id"]),
    }
    if type(record["key_id"]) is not str or not record["key_id"]:
        _refuse("cam-pin.key_id", "present", "missing")
    require_b64("cam-pin.cam_sig", record["cam_sig"], 64)
    if "pack_id" in payload:
        top_pack = require_pack_id("cam-pin.pack_id", payload.get("pack_id"))
        if top_pack != binding["pack_id"]:
            _refuse("cam-pin.pack_id", binding["pack_id"], top_pack)
    for rows_field in ("rows_total", "rows_train", "rows_holdout"):
        if rows_field not in payload:
            _refuse(f"cam-pin.{rows_field}", "present", "missing")
        record[rows_field] = require_int(f"cam-pin.{rows_field}", payload.get(rows_field))
    record["reserved_content_uuids_sha256"] = require_sha256_hex(
        "cam-pin.reserved_content_uuids_sha256",
        payload.get("reserved_content_uuids_sha256"),
    )
    record["reserved_content_uuids_min_rows"] = require_int(
        "cam-pin.reserved_content_uuids_min_rows",
        payload.get("reserved_content_uuids_min_rows"),
    )
    if record["reserved_content_uuids_min_rows"] < 1:
        _refuse(
            "cam-pin.reserved_content_uuids_min_rows",
            ">= 1",
            record["reserved_content_uuids_min_rows"],
        )
    if "recordedBy" in payload:
        record["recordedBy"] = payload["recordedBy"]
    if "stampVerified" in payload:
        record["stampVerified"] = payload["stampVerified"]
    elif "verified" in payload:
        record["stampVerified"] = payload["verified"]
    if "pack_matches" in payload:
        record["pack_matches"] = payload["pack_matches"]
    if "recordedAt" in payload:
        record["recordedAt"] = payload["recordedAt"]
    verify_cam_sig_v2(record)
    if run_id is not None:
        if type(run_id) is not str or not run_id:
            _refuse("run-id", "present", "missing")
        if binding["run_id"] != run_id:
            _refuse("cam-pin.binding.run_id", binding["run_id"], run_id)
    return record


def parse_kick_pin_payload(
    payload: object,
    *,
    now: datetime | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Kick path: v2 only. v1 is verify-only history and is refused here."""
    if not isinstance(payload, dict) or not payload:
        _refuse("cam-pin", "present", "missing")
    fmt = pin_format_of(payload)
    if fmt != PIN_FORMAT_V2:
        _refuse("cam-pin.format", PIN_FORMAT_V2, fmt)
    return parse_v2_pin_payload(payload, now=now, run_id=run_id)


def _ed25519_decode_point(raw: bytes, *, field: str) -> tuple[int, int]:
    """RFC 8032 decompression. Refuses non-canonical y (>= p) and off-curve."""
    if len(raw) != 32:
        _refuse(field, "32-byte compressed point", f"len {len(raw)}")
    y = int.from_bytes(raw, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    if y >= ED25519_P:
        _refuse(field, "canonical Ed25519 point of order > 8", "non-canonical y >= p")
    y2 = (y * y) % ED25519_P
    u = (y2 - 1) % ED25519_P
    v = (ED25519_D * y2 + 1) % ED25519_P
    x2 = (u * pow(v, -1, ED25519_P)) % ED25519_P
    x = pow(x2, (ED25519_P + 3) // 8, ED25519_P)
    if (x * x - x2) % ED25519_P != 0:
        x = (x * ED25519_I) % ED25519_P
    if (x * x - x2) % ED25519_P != 0:
        _refuse(field, "canonical Ed25519 point of order > 8", "not on curve")
    if x == 0 and sign:
        _refuse(field, "canonical Ed25519 point of order > 8", "non-canonical sign")
    if (x & 1) != sign:
        x = ED25519_P - x
    return x, y


def _ed25519_add(p1: tuple[int, int], p2: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = p1
    x2, y2 = p2
    t = (ED25519_D * x1 * x2 * y1 * y2) % ED25519_P
    x3 = ((x1 * y2 + x2 * y1) * pow(1 + t, -1, ED25519_P)) % ED25519_P
    y3 = ((y1 * y2 + x1 * x2) * pow(1 - t, -1, ED25519_P)) % ED25519_P
    return x3, y3


def _ed25519_mul8(point: tuple[int, int]) -> tuple[int, int]:
    doubled = _ed25519_add(point, point)
    doubled = _ed25519_add(doubled, doubled)
    return _ed25519_add(doubled, doubled)


def _ed25519_scalarmult(point: tuple[int, int], scalar: int) -> tuple[int, int]:
    """Affine double-and-add. Used for the [L]A prime-order check."""
    result = ED25519_IDENTITY
    addend = point
    k = int(scalar)
    if k < 0:
        _refuse("cam_pin.pubkey", "non-negative scalar", k)
    while k:
        if k & 1:
            result = _ed25519_add(result, addend)
        addend = _ed25519_add(addend, addend)
        k >>= 1
    return result


def require_ed25519_point(raw: bytes, *, field: str) -> tuple[int, int]:
    """Refuse non-canonical encodings, [8]A == identity, and [L]A != identity."""
    point = _ed25519_decode_point(raw, field=field)
    if _ed25519_mul8(point) == ED25519_IDENTITY:
        _refuse(field, "canonical prime-order Ed25519 point", "small-order ([8]A == identity)")
    if _ed25519_scalarmult(point, ED25519_L) != ED25519_IDENTITY:
        _refuse(field, "canonical prime-order Ed25519 point", "mixed-order ([L]A != identity)")
    return point


def require_ed25519_signature(signature: bytes, *, field: str = "cam-pin.cam_sig") -> None:
    """Refuse small-order/mixed-order R, non-canonical R, and S >= L."""
    if len(signature) != 64:
        _refuse(field, "64-byte signature", f"len {len(signature)}")
    require_ed25519_point(signature[:32], field=f"{field}.R")
    scalar = int.from_bytes(signature[32:], "little")
    if scalar >= ED25519_L:
        _refuse(f"{field}.S", "S < L", scalar)


def sign_pin_bytes(message: bytes, raw_private: bytes) -> str:
    if len(raw_private) != 32:
        _refuse("cam_sig", "32-byte Ed25519 seed", f"len {len(raw_private)}")
    key = Ed25519PrivateKey.from_private_bytes(raw_private)
    require_ed25519_point(raw_public_from_private(raw_private), field="cam_pin.pubkey")
    signature = key.sign(message)
    require_ed25519_signature(signature, field="cam-pin.cam_sig")
    return base64.b64encode(signature).decode("ascii")


def raw_public_from_private(raw_private: bytes) -> bytes:
    key = Ed25519PrivateKey.from_private_bytes(raw_private)
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def encode_private_raw(raw_private: bytes) -> bytes:
    key = Ed25519PrivateKey.from_private_bytes(raw_private)
    return key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n")


def _parse_pub_file(text: str) -> tuple[str, bytes]:
    if not text or not text.strip():
        _refuse("cam_pin.pubkey", "Ed25519 public key", "empty")
    if _normalize_newlines(text) == PLACEHOLDER_PUB_TEXT:
        _refuse("cam_pin.pubkey", "Ed25519 public key", "placeholder")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        _refuse("cam_pin.pubkey", "key_id and base64 pubkey", "placeholder")
    key_id, b64 = lines[0], lines[1]
    raw = require_b64("cam_pin.pubkey", b64, 32)
    encoded = base64.b64encode(raw).decode("ascii")
    if encoded in DENIED_PUBLIC_KEYS_B64:
        _refuse("cam_pin.pubkey", "Cam production key", "denied test key")
    require_ed25519_point(raw, field="cam_pin.pubkey")
    return key_id, raw


def bind_pinned_copy_trust(copy_root: Path) -> None:
    """Point Cam trust files at the server layout: <copy-root>/apps/dottie-os/trust/."""
    global CAM_PIN_PUB_PATH, CAM_PIN_KEY_ID_PATH, PINNED_COPY_ROOT
    root = Path(copy_root).resolve()
    trust_dir = root / "apps" / "dottie-os" / "trust"
    pub = trust_dir / _PUB_NAME
    kid = trust_dir / _KEY_ID_NAME
    if pub.name != _PUB_NAME or pub.parent.name != "trust":
        _refuse("cam_pin.pubkey", str(trust_dir / _PUB_NAME), str(pub))
    if kid.name != _KEY_ID_NAME or kid.parent.name != "trust":
        _refuse("cam_pin.key_id", str(trust_dir / _KEY_ID_NAME), str(kid))
    try:
        pub.resolve().relative_to(root)
        kid.resolve().relative_to(root)
    except ValueError:
        _refuse("cam_pin.pubkey", f"under {root / TRUST_DIR_REL}", str(pub))
    PINNED_COPY_ROOT = root
    CAM_PIN_PUB_PATH = pub
    CAM_PIN_KEY_ID_PATH = kid


def clear_pinned_copy_trust() -> None:
    """Restore default trust paths. Tests only; production pinned-copy never unbinds."""
    global CAM_PIN_PUB_PATH, CAM_PIN_KEY_ID_PATH, PINNED_COPY_ROOT
    PINNED_COPY_ROOT = None
    CAM_PIN_PUB_PATH = _DEFAULT_CAM_PIN_PUB_PATH
    CAM_PIN_KEY_ID_PATH = _DEFAULT_CAM_PIN_KEY_ID_PATH


def _read_trust_file_nofollow(path: Path, field: str) -> str:
    """Read a regular trust file with O_NOFOLLOW. Never follows a symlink."""
    buf, _digest = sha256_file_bytes(path)
    try:
        return buf.decode("utf-8")
    except UnicodeDecodeError:
        _refuse(field, "utf-8 text", "invalid encoding")
        raise AssertionError("unreachable")


def load_cam_key_id() -> str:
    """Committed cam_key_id. Never env, argv, or another path."""
    path = CAM_PIN_KEY_ID_PATH
    if path.name != _KEY_ID_NAME or path.parent.name != "trust":
        _refuse("cam_pin.key_id", str(CAM_PIN_KEY_ID_PATH), str(path))
    try:
        text = _read_trust_file_nofollow(path, "cam_pin.key_id")
    except FileNotFoundError:
        _refuse("cam_pin.key_id", "present", "missing")
    except OSError as exc:
        _refuse("cam_pin.key_id", "readable file", f"OSError:{exc.errno}")
    if _normalize_newlines(text) == PLACEHOLDER_KEY_ID_TEXT or not text.strip():
        _refuse("cam_pin.key_id", "committed key id", "placeholder")
    key_id = text.strip()
    if not key_id:
        _refuse("cam_pin.key_id", "committed key id", "empty")
    return key_id


def load_cam_public_key() -> tuple[str, Ed25519PublicKey]:
    """Load the committed pubkey. Never env, argv, or another path."""
    path = CAM_PIN_PUB_PATH
    if path.name != _PUB_NAME or path.parent.name != "trust":
        _refuse("cam_pin.pubkey", str(CAM_PIN_PUB_PATH), str(path))
    try:
        text = _read_trust_file_nofollow(path, "cam_pin.pubkey")
    except FileNotFoundError:
        _refuse("cam_pin.pubkey", "present", "missing")
    except OSError as exc:
        _refuse("cam_pin.pubkey", "readable file", f"OSError:{exc.errno}")
    key_id, raw = _parse_pub_file(text)
    committed_id = load_cam_key_id()
    if key_id != committed_id:
        _refuse("cam_pin.key_id", committed_id, key_id)
    require_ed25519_point(raw, field="cam_pin.pubkey")
    return key_id, Ed25519PublicKey.from_public_bytes(raw)


def verify_ed25519(message: bytes, signature: bytes, public_raw: bytes) -> None:
    """Production verify. Denies the HQ vector test key in every environment."""
    if len(public_raw) != 32:
        _refuse("cam_pin.pubkey", "32-byte public key", f"len {len(public_raw)}")
    encoded = base64.b64encode(public_raw).decode("ascii")
    if encoded in DENIED_PUBLIC_KEYS_B64:
        _refuse("cam_pin.pubkey", "Cam production key", "denied test key")
    require_ed25519_point(public_raw, field="cam_pin.pubkey")
    require_ed25519_signature(signature, field="cam-pin.cam_sig")
    public = Ed25519PublicKey.from_public_bytes(public_raw)
    try:
        public.verify(signature, message)
    except InvalidSignature:
        _refuse("cam-pin.cam_sig", "valid Cam Ed25519 signature", "invalid")


def verify_cam_sig(record: dict[str, Any]) -> None:
    key_id, public = load_cam_public_key()
    pin_kid = record.get("cam_key_id")
    if type(pin_kid) is not str or not pin_kid:
        _refuse("cam-pin.cam_key_id", "present", "missing")
    if pin_kid != key_id:
        _refuse("cam-pin.cam_key_id", key_id, pin_kid)
    signature = require_b64("cam-pin.cam_sig", record.get("cam_sig"), 64)
    message = canonical_pin_bytes(record)
    public_raw = public.public_bytes(Encoding.Raw, PublicFormat.Raw)
    verify_ed25519(message, signature, public_raw)


def repo_root() -> Path:
    if PINNED_COPY_ROOT is not None:
        _refuse("git", "skipped in pinned-copy", "pinned-copy")
    here = Path(__file__).resolve()
    try:
        staged = here.parents[4]
    except IndexError:
        staged = None
    if staged is not None and (staged / "PINS.json").is_file():
        _refuse("git", "skipped in pinned-copy", "pinned-copy")
    for parent in here.parents:
        if (parent / ".git").exists():
            return parent
    _refuse("git", "repository", "missing")
    raise AssertionError("unreachable")


def _git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    if PINNED_COPY_ROOT is not None:
        _refuse("git", "skipped in pinned-copy", "pinned-copy")
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError as exc:
        _refuse("git", "available", f"OSError:{getattr(exc, 'errno', None)}")
        raise AssertionError("unreachable") from exc


def _ls_tree_blob(root: Path, relpath: str) -> str:
    proc = _git(root, ["ls-tree", "HEAD", "--", relpath])
    if proc.returncode != 0 or not proc.stdout.strip():
        _refuse("trust.blob", f"{relpath} in HEAD", "missing")
    parts = proc.stdout.split()
    if len(parts) < 3 or parts[1] != "blob":
        _refuse("trust.blob", f"{relpath} blob", proc.stdout.strip())
    return parts[2]


def _hash_object(path: Path) -> str:
    proc = _git(repo_root(), ["hash-object", str(path)])
    sha = proc.stdout.strip()
    if proc.returncode != 0 or len(sha) != 40:
        _refuse("trust.blob", "git hash-object", sha or proc.stderr.strip())
    return sha


def _head_is_on_main(root: Path) -> tuple[bool, str]:
    """Local-ref hint: HEAD is origin/main or an ancestor of that local ref.

    Not a hard gate. ``git update-ref`` can spoof origin/main without a
    network fetch. Branch protection plus CODEOWNERS are the authoritative
    boundary. The check is kept as a recorded local hint.
    """
    head_proc = _git(root, ["rev-parse", "HEAD"])
    head = head_proc.stdout.strip()
    if head_proc.returncode != 0 or not head:
        _refuse("HEAD", "git rev-parse", head_proc.stderr.strip() or "missing")
    anc = _git(root, ["merge-base", "--is-ancestor", "HEAD", ORIGIN_MAIN_REF])
    return anc.returncode == 0, head


def require_committed_trust() -> dict[str, str]:
    """Refuse dirty trust files. Record a local origin/main ancestry hint.

    Compares ``git hash-object`` of each trust path to ``git ls-tree HEAD``.
    Records those blob shas and the HEAD sha for evidence. The ancestry
    check is a local-ref hint, not a substitute for GitHub branch protection
    plus CODEOWNERS (``git update-ref`` can spoof ``origin/main`` without a
    network fetch).
    """
    root = repo_root()
    blobs: dict[str, str] = {}
    for relpath in TRUST_RELPATHS:
        path = root / relpath
        committed = _ls_tree_blob(root, relpath)
        if not path.is_file():
            _refuse("trust.blob", relpath, "missing")
        working = _hash_object(path)
        if working != committed:
            _refuse("trust.blob", committed, working)
        blobs[relpath] = committed
    on_main, head = _head_is_on_main(root)
    if not on_main:
        _refuse("HEAD", f"hint: ancestor of {ORIGIN_MAIN_REF}", head)
    blobs["HEAD"] = head
    return blobs


def pinned_origin() -> str:
    origin = SWARM_HQ_ORIGIN
    if type(origin) is not str or origin.lower() in _PLACEHOLDER_ORIGIN or not origin:
        _refuse("SWARM_HQ_ORIGIN", "https origin", "placeholder")
    if not origin.startswith("https://"):
        _refuse("SWARM_HQ_ORIGIN", "https URL", origin)
    parsed = urllib.parse.urlparse(origin)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        _refuse("SWARM_HQ_ORIGIN", "https origin", origin)
    return origin.rstrip("/")


def _origin_netloc(origin: str) -> str:
    return urllib.parse.urlparse(origin).netloc


def pin_url(pack_id: str) -> str:
    if type(pack_id) is not str or not pack_id:
        _refuse("pack_id", "present", "missing")
    origin = pinned_origin()
    return origin + "/api/packs/" + urllib.parse.quote(pack_id, safe="") + "/pin"


def _url_is_pinned(url: str, origin: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    want = urllib.parse.urlparse(origin)
    return (
        parsed.scheme == "https"
        and parsed.netloc == want.netloc
        and parsed.username is None
        and parsed.password is None
    )


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        del req, fp, msg, headers, newurl
        _refuse("cam-pin", "no redirect", f"HTTP {code}")
        return None

    def http_error_301(self, req, fp, code, msg, headers):  # type: ignore[no-untyped-def]
        _refuse("cam-pin", "no redirect", f"HTTP {code}")

    http_error_302 = http_error_301
    http_error_303 = http_error_301
    http_error_307 = http_error_301
    http_error_308 = http_error_301


def build_hq_opener() -> urllib.request.OpenerDirector:
    ctx = ssl.create_default_context()
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = True
    https = urllib.request.HTTPSHandler(context=ctx)
    # Empty ProxyHandler disables env proxies (trust_env=False equivalent).
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirectHandler,
        https,
    )
    return opener


def open_hq(request: urllib.request.Request, *, timeout: float) -> Any:
    """Open one HQ request (GET pin or POST event). Tests patch this."""
    return build_hq_opener().open(request, timeout=timeout)


def event_url(event: str) -> str:
    if type(event) is not str or event not in HQ_EVENTS:
        _refuse("hq.event", "kick|completion", event)
    origin = pinned_origin()
    return origin + "/api/helper-ft/events/" + event


def _require_event_payload(event: str, payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        _refuse("hq.event", "JSON object", type(payload).__name__)
    body: dict[str, Any] = dict(payload)
    if event == "kick":
        required = ("run_id", "sha256_pack", "sha256_train", "sha256_holdout")
    elif event == "completion":
        required = (
            "run_id",
            "sha256_evidence",
            "sha256_pack",
            "sha256_train",
            "sha256_holdout",
            "result",
            "exit_code",
        )
    else:
        _refuse("hq.event", "kick|completion", event)
        raise AssertionError("unreachable")
    for key in required:
        if key not in body:
            _refuse(f"hq.event.{key}", "present", "missing")
    run_id = body.get("run_id")
    if type(run_id) is not str or not run_id:
        _refuse("hq.event.run_id", "present", "missing")
    sha_keys = ("sha256_pack", "sha256_train", "sha256_holdout")
    if event == "completion":
        sha_keys = ("sha256_evidence", *sha_keys)
    for key in sha_keys:
        require_sha256_hex(f"hq.event.{key}", body.get(key))
    if event == "completion":
        result = body.get("result")
        if result not in ("MATCH", "REFUSED"):
            _refuse("hq.event.result", "MATCH|REFUSED", result)
        exit_code = body.get("exit_code")
        if exit_code is not None and type(exit_code) is not int:
            _refuse("hq.event.exit_code", "int or null", type(exit_code).__name__)
    return body


def post_hq_event(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST a kick or completion event to the pinned origin. No redirects.

    ``x-agent-token`` is attached only after the URL matches ``pinned_origin()``.
    A placeholder origin refuses the same way pin GETs refuse.
    Tests patch ``open_hq``.
    """
    if type(event) is not str or event not in HQ_EVENTS:
        _refuse("hq.event", "kick|completion", event)
    origin = pinned_origin()
    token = os.environ.get(SWARM_HQ_AGENT_TOKEN_ENV)
    if type(token) is not str or not token:
        _refuse(SWARM_HQ_AGENT_TOKEN_ENV, "present", "missing")
    body = _require_event_payload(event, payload)
    url = event_url(event)
    if not _url_is_pinned(url, origin):
        _refuse("hq.event", f"origin {origin}", url)
    blob_out = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=blob_out,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-agent-token": token,
        },
    )
    deadline = time.monotonic() + HQ_DEADLINE_SECONDS
    timeout = HQ_DEADLINE_SECONDS
    try:
        response = open_hq(request, timeout=timeout)
        try:
            status = getattr(response, "status", None) or response.getcode()
            if status is not None and 300 <= int(status) < 400:
                _refuse("cam-pin", "no redirect", f"HTTP {status}")
            if status not in (200, None) and int(status) != 200:
                if int(status) == 401:
                    _refuse("cam-pin", "authorized", "HTTP 401")
                if int(status) == 404:
                    _refuse("cam-pin", "present", "HTTP 404")
                _refuse("hq.event", "HTTPS Swarm HQ event", f"HTTP {status}")
            blob = _read_capped(response, deadline)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
    except CamPinError:
        raise
    except urllib.error.HTTPError as exc:
        if 300 <= int(exc.code) < 400:
            _refuse("cam-pin", "no redirect", f"HTTP {exc.code}")
        if exc.code == 401:
            _refuse("cam-pin", "authorized", "HTTP 401")
        if exc.code == 404:
            _refuse("cam-pin", "present", "HTTP 404")
        _refuse("hq.event", "HTTPS Swarm HQ event", f"HTTP {exc.code}")
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None) or exc
        _refuse("hq.event", "HTTPS Swarm HQ event", f"unreachable:{reason}")
    except OSError as exc:
        _refuse("hq.event", "HTTPS Swarm HQ event", f"OSError:{getattr(exc, 'errno', None)}")
    if not blob:
        return {"ok": True}
    try:
        raw = blob.decode("utf-8")
    except UnicodeDecodeError:
        _refuse("hq.event", "utf-8 JSON", "invalid encoding")
    try:
        parsed = json.loads(raw) if raw else {}
    except ValueError:
        _refuse("hq.event", "JSON object", "invalid JSON")
    if parsed in (None, ""):
        return {"ok": True}
    if not isinstance(parsed, dict):
        _refuse("hq.event", "JSON object", type(parsed).__name__)
    if parsed.get("ok") is False:
        _refuse("hq.event", "ok", parsed)
    return parsed if parsed else {"ok": True}


def _read_capped(response: Any, deadline: float) -> bytes:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        _refuse("cam-pin", "HQ deadline", "expired")
    try:
        blob = response.read(MAX_PIN_BYTES + 1)
    except OSError as exc:
        _refuse("cam-pin", "HTTPS Swarm HQ pin", f"OSError:{getattr(exc, 'errno', None)}")
    if time.monotonic() > deadline:
        _refuse("cam-pin", "HQ deadline", "expired")
    if blob is None:
        _refuse("cam-pin", "utf-8 JSON", "empty")
    if len(blob) > MAX_PIN_BYTES:
        _refuse("cam-pin", f"<={MAX_PIN_BYTES} bytes", len(blob))
    return blob


def _no_duplicate_hq_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            _refuse("cam-pin", "unique keys", f"duplicate {key}")
        seen[key] = value
    return seen


def parse_hq_pin_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        _refuse("cam-pin", "present", "missing")
    unknown = [key for key in payload if key not in HQ_PIN_ALLOWED_KEYS]
    if unknown:
        _refuse("cam-pin", "HQ pin keys", f"unknown {unknown[0]}")
    for key in HQ_PIN_REQUIRED_KEYS:
        if key not in payload:
            _refuse(f"cam-pin.{key}", "present", "missing")
    recorded_at = require_recorded_at("cam-pin.recordedAt", payload.get("recordedAt"))
    kid = payload.get("kid")
    if type(kid) is not str or not kid:
        _refuse("cam-pin.kid", "present", "missing")
    cam_key_id = payload.get("cam_key_id")
    if type(cam_key_id) is not str or not cam_key_id:
        _refuse("cam-pin.cam_key_id", "present", "missing")
    cam_sig = payload.get("cam_sig")
    if type(cam_sig) is not str or not cam_sig:
        _refuse("cam-pin.cam_sig", "present", "missing")
    require_b64("cam-pin.cam_sig", cam_sig, 64)
    record: dict[str, Any] = {key: payload[key] for key in HQ_PIN_REQUIRED_KEYS}
    record["pack_id"] = require_pack_id("cam-pin.pack_id", payload["pack_id"])
    record["sha256_pack"] = require_sha256_hex("cam-pin.sha256_pack", payload.get("sha256_pack"))
    record["sha256_train"] = require_sha256_hex("cam-pin.sha256_train", payload.get("sha256_train"))
    record["sha256_holdout"] = require_sha256_hex("cam-pin.sha256_holdout", payload.get("sha256_holdout"))
    record["rows_total"] = require_int("cam-pin.rows_total", payload.get("rows_total"))
    record["rows_train"] = require_int("cam-pin.rows_train", payload.get("rows_train"))
    record["rows_holdout"] = require_int("cam-pin.rows_holdout", payload.get("rows_holdout"))
    record["recordedAt"] = recorded_at
    record["kid"] = kid
    record["cam_key_id"] = cam_key_id
    record["cam_sig"] = cam_sig
    if "recordedBy" in payload:
        record["recordedBy"] = payload["recordedBy"]
    if "stampVerified" in payload:
        record["stampVerified"] = payload["stampVerified"]
    elif "verified" in payload:
        record["stampVerified"] = payload["verified"]
    if "pack_matches" in payload:
        record["pack_matches"] = payload["pack_matches"]
    verify_cam_sig(record)
    return record


def pin_identity(pin: dict[str, Any]) -> dict[str, Any]:
    """Fields :8765 must match against the staged (or historically fetched) pin."""
    if pin_format_of(pin) == PIN_FORMAT_V2:
        binding = pin.get("binding") if isinstance(pin.get("binding"), dict) else {}
        ident: dict[str, Any] = {
            "format": PIN_FORMAT_V2,
            "key_id": pin.get("key_id"),
            "binding": {
                "pack_id": binding.get("pack_id", pin.get("pack_id")),
                "run_id": binding.get("run_id", pin.get("run_id")),
                "lease_owner": binding.get("lease_owner", pin.get("lease_owner")),
            },
            "issued_at": pin.get("issued_at"),
            "not_before": pin.get("not_before"),
            "not_after": pin.get("not_after"),
            "nonce": pin.get("nonce"),
            "sha256_pack": pin.get("sha256_pack"),
            "sha256_train": pin.get("sha256_train"),
            "sha256_holdout": pin.get("sha256_holdout"),
            "code_pins": pin.get("code_pins"),
            "git_commit": pin.get("git_commit"),
            "head": pin.get("head"),
            "expires_at": pin.get("expires_at"),
            "reserved_content_uuids_sha256": pin.get("reserved_content_uuids_sha256"),
            "reserved_content_uuids_min_rows": pin.get("reserved_content_uuids_min_rows"),
            "cam_sig": pin.get("cam_sig"),
        }
        for rows_field in ("rows_total", "rows_train", "rows_holdout"):
            if rows_field in pin:
                ident[rows_field] = pin.get(rows_field)
        return ident
    return {
        "pack_id": pin.get("pack_id"),
        "sha256_pack": pin.get("sha256_pack"),
        "sha256_train": pin.get("sha256_train"),
        "sha256_holdout": pin.get("sha256_holdout"),
        "rows_total": pin.get("rows_total"),
        "rows_train": pin.get("rows_train"),
        "rows_holdout": pin.get("rows_holdout"),
        "recordedAt": pin.get("recordedAt"),
        "kid": pin.get("kid"),
        "cam_key_id": pin.get("cam_key_id"),
        "cam_sig": pin.get("cam_sig"),
    }
