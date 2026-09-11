"""Canonical JSON, content hashes and time helpers shared by every record type.

Artifact identity is a content hash (spec §07 "Artifact identity"); every digest in
this package is sha256 over canonical JSON (sorted keys, compact separators,
UTF-8), so two processes computing the digest of the same payload agree byte for
byte. ``hash()`` is never used for anything durable.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def digest(obj: Any) -> str:
    """sha256 of the canonical JSON form of ``obj``."""
    return sha256_hex(canonical_json(obj))


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def now_iso() -> str:
    """RFC3339 in UTC with second precision — the storage form for every timestamp."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: object) -> datetime:
    """Parse an RFC3339 timestamp (``Z`` or offset) to an aware UTC datetime."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        raw = value[:-1] + "+00:00" if value.endswith("Z") else value
        dt = datetime.fromisoformat(raw)
    else:
        raise ValueError(f"not an RFC3339 timestamp: {value!r}")
    if dt.tzinfo is None:
        raise ValueError(f"timestamp has no timezone: {value!r}")
    return dt.astimezone(UTC)


def age_seconds(value: object, now: datetime | None = None) -> float:
    now = now or datetime.now(UTC)
    return (now - parse_iso(value)).total_seconds()


def new_id(prefix: str = "") -> str:
    raw = uuid.uuid4().hex
    return f"{prefix}{raw}" if prefix else raw


def hashed_subject(subject: str, salt: str) -> str:
    """Pseudonymous identity: sha256(salt || subject), 32 hex chars."""
    return hashlib.sha256(f"{salt}\x00{subject}".encode()).hexdigest()[:32]
