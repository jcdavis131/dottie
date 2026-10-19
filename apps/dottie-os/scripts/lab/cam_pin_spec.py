#!/usr/bin/env python3
"""Cam-signed Swarm HQ pack-pin: canonical bytes, Ed25519 verify, pinned origin.

Signed bytes (UTF-8), byte-for-byte::

    swarm-hq-pin-v1\\n
    + JSON object with sorted keys, no whitespace, of exactly
      {pack_id, sha256_pack, sha256_train, sha256_holdout,
       rows_total, rows_train, rows_holdout, recordedAt}

The pin JSON also carries ``cam_sig`` (base64 Ed25519 signature of those
bytes) and ``cam_key_id``. Verify only against the public key committed at
``apps/dottie-os/trust/cam_pin_ed25519.pub``. Never read a key from env,
argv, or any other path.

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
import json
import os
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
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
# Cam sets this by PR to the production HTTPS origin, e.g. "https://hq.example".
SWARM_HQ_ORIGIN = ""
SWARM_HQ_AGENT_TOKEN_ENV = "SWARM_HQ_AGENT_TOKEN"
PIN_PATH = "/api/packs/{pack_id}/pin"
MAX_PIN_BYTES = 64 * 1024
HQ_DEADLINE_SECONDS = 15.0
SHA256_LEN = 64
_HEX = frozenset("0123456789abcdef")
_PLACEHOLDER_ORIGIN = frozenset({"", "unset", "placeholder", "todo", "https://unset.invalid"})
_PLACEHOLDER_KEY_ID = frozenset({"", "unset", "placeholder", "todo", "replace-me", "changeme"})
_PUB_NAME = "cam_pin_ed25519.pub"
# Frozen path: apps/dottie-os/trust/cam_pin_ed25519.pub relative to this file.
CAM_PIN_PUB_PATH = Path(__file__).resolve().parents[2] / "trust" / _PUB_NAME
# Repo-relative paths whose HEAD blobs must match the working tree.
TRUST_RELPATHS = (
    "apps/dottie-os/trust/cam_pin_ed25519.pub",
    "apps/dottie-os/scripts/lab/cam_pin_spec.py",
)
ORIGIN_MAIN_REF = "origin/main"

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
    if type(value) is not int:
        label = "bool" if isinstance(value, bool) else type(value).__name__
        _refuse(field, "int", label)
    return value


def canonical_pin_bytes(fields: dict[str, Any]) -> bytes:
    """Exact signed payload. Swarm HQ must match this byte for byte."""
    missing = [key for key in SIGNED_KEYS if key not in fields]
    if missing:
        _refuse(f"cam-pin.{missing[0]}", "present", "missing")
    body = {key: fields[key] for key in SIGNED_KEYS}
    packed = json.dumps(body, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    return CANONICAL_PREFIX + packed.encode("utf-8")


def sign_pin_bytes(message: bytes, raw_private: bytes) -> str:
    if len(raw_private) != 32:
        _refuse("cam_sig", "32-byte Ed25519 seed", f"len {len(raw_private)}")
    key = Ed25519PrivateKey.from_private_bytes(raw_private)
    return base64.b64encode(key.sign(message)).decode("ascii")


def raw_public_from_private(raw_private: bytes) -> bytes:
    key = Ed25519PrivateKey.from_private_bytes(raw_private)
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def encode_private_raw(raw_private: bytes) -> bytes:
    key = Ed25519PrivateKey.from_private_bytes(raw_private)
    return key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())


def _parse_pub_file(text: str) -> tuple[str, bytes]:
    if not text or not text.strip():
        _refuse("cam_pin.pubkey", "Ed25519 public key", "empty")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        _refuse("cam_pin.pubkey", "key_id and base64 pubkey", "placeholder")
    key_id, b64 = lines[0], lines[1]
    if key_id.lower() in _PLACEHOLDER_KEY_ID:
        _refuse("cam_pin.pubkey", "Ed25519 public key", "placeholder")
    try:
        raw = base64.b64decode(b64, validate=True)
    except (ValueError, TypeError):
        _refuse("cam_pin.pubkey", "base64 Ed25519 public key", "invalid")
    if len(raw) != 32:
        _refuse("cam_pin.pubkey", "32-byte public key", f"len {len(raw)}")
    return key_id, raw


def load_cam_public_key() -> tuple[str, Ed25519PublicKey]:
    """Load the committed pubkey. Never env, argv, or another path."""
    path = CAM_PIN_PUB_PATH
    if path.name != _PUB_NAME or path.parent.name != "trust":
        _refuse("cam_pin.pubkey", str(CAM_PIN_PUB_PATH), str(path))
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        _refuse("cam_pin.pubkey", "present", "missing")
    except OSError as exc:
        _refuse("cam_pin.pubkey", "readable file", f"OSError:{exc.errno}")
    key_id, raw = _parse_pub_file(text)
    return key_id, Ed25519PublicKey.from_public_bytes(raw)


def verify_ed25519(message: bytes, signature: bytes, public_raw: bytes) -> None:
    """Verify Ed25519 over ``message``. Tests may pass a vector key; runtime uses trust/."""
    if len(public_raw) != 32:
        _refuse("cam_pin.pubkey", "32-byte public key", f"len {len(public_raw)}")
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
    sig_b64 = record.get("cam_sig")
    if type(sig_b64) is not str or not sig_b64:
        _refuse("cam-pin.cam_sig", "present", "missing")
    try:
        signature = base64.b64decode(sig_b64, validate=True)
    except (ValueError, TypeError):
        _refuse("cam-pin.cam_sig", "base64 Ed25519 signature", "invalid")
    message = canonical_pin_bytes(record)
    public_raw = public.public_bytes(Encoding.Raw, PublicFormat.Raw)
    verify_ed25519(message, signature, public_raw)


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists():
            return parent
    _refuse("git", "repository", "missing")
    raise AssertionError("unreachable")


def _git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
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
    """True when HEAD is origin/main or an ancestor of it."""
    head_proc = _git(root, ["rev-parse", "HEAD"])
    head = head_proc.stdout.strip()
    if head_proc.returncode != 0 or not head:
        _refuse("HEAD", "git rev-parse", head_proc.stderr.strip() or "missing")
    anc = _git(root, ["merge-base", "--is-ancestor", "HEAD", ORIGIN_MAIN_REF])
    return anc.returncode == 0, head


def require_committed_trust() -> dict[str, str]:
    """Refuse dirty trust files and a HEAD that is not on origin/main.

    Compares ``git hash-object`` of each trust path to ``git ls-tree HEAD``.
    Records those blob shas and the HEAD sha for evidence.
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
        _refuse("HEAD", f"ancestor of {ORIGIN_MAIN_REF}", head)
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
    """Open one HQ GET. Tests patch this. Production uses the no-redirect opener."""
    return build_hq_opener().open(request, timeout=timeout)


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
    recorded_at = payload.get("recordedAt")
    if type(recorded_at) is not str or not recorded_at:
        _refuse("cam-pin.recordedAt", "present", "missing")
    kid = payload.get("kid")
    if type(kid) is not str or not kid:
        _refuse("cam-pin.kid", "present", "missing")
    cam_key_id = payload.get("cam_key_id")
    if type(cam_key_id) is not str or not cam_key_id:
        _refuse("cam-pin.cam_key_id", "present", "missing")
    cam_sig = payload.get("cam_sig")
    if type(cam_sig) is not str or not cam_sig:
        _refuse("cam-pin.cam_sig", "present", "missing")
    record: dict[str, Any] = {key: payload[key] for key in HQ_PIN_REQUIRED_KEYS}
    record["pack_id"] = payload["pack_id"]
    if type(record["pack_id"]) is not str or not record["pack_id"]:
        _refuse("cam-pin.pack_id", "present", "missing")
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


def fetch_signed_pin(pack_id: str) -> dict[str, Any]:
    """GET the pin from the pinned origin, verify Cam's Ed25519 signature."""
    if type(pack_id) is not str or not pack_id:
        _refuse("pack_id", "present", "missing")
    require_committed_trust()
    origin = pinned_origin()
    token = os.environ.get(SWARM_HQ_AGENT_TOKEN_ENV)
    if type(token) is not str or not token:
        _refuse(SWARM_HQ_AGENT_TOKEN_ENV, "present", "missing")
    url = pin_url(pack_id)
    if not _url_is_pinned(url, origin):
        _refuse("cam-pin", f"origin {origin}", url)
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
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
                _refuse("cam-pin", "HTTPS Swarm HQ pin", f"HTTP {status}")
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
        _refuse("cam-pin", "HTTPS Swarm HQ pin", f"HTTP {exc.code}")
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None) or exc
        _refuse("cam-pin", "HTTPS Swarm HQ pin", f"unreachable:{reason}")
    except OSError as exc:
        _refuse("cam-pin", "HTTPS Swarm HQ pin", f"OSError:{getattr(exc, 'errno', None)}")
    try:
        raw = blob.decode("utf-8")
    except UnicodeDecodeError:
        _refuse("cam-pin", "utf-8 JSON", "invalid encoding")
    try:
        payload = json.loads(raw, object_pairs_hook=_no_duplicate_hq_keys) if raw else None
    except CamPinError:
        raise
    except ValueError:
        _refuse("cam-pin", "JSON object", "invalid JSON")
    return parse_hq_pin_payload(payload)


def pin_identity(pin: dict[str, Any]) -> dict[str, Any]:
    """Fields :8765 must match against the CLI's fetched pin."""
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
