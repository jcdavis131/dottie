#!/usr/bin/env python3
"""Canonical content uuid for HELPER FT rows.

Mill backfills ``source.content_uuid`` on a row whose source has none by
hashing this canonical form. The kick gate recomputes the same digest and
verifies ``source.content_uuid``. ``source.uuid`` is always an opaque
dataset id, never a content uuid, even when it is 64 hex. A missing
``source.uuid`` is allowed when a valid ``source.content_uuid`` is present
and verifies.

Included fields: ``state`` and ``questions`` only.
Excluded: ``labels``, ids (``id``, ``uuid``, ``trajectory_id``,
``source.uuid``), timestamps, and every other top-level key.

Encoding, exactly:
1. Build a JSON object with the included fields that are present (a missing
   field is omitted, not null).
2. Unicode NFC-normalize every string in that object (keys and values).
3. ``json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)``.
4. UTF-8 encode those JSON bytes.
5. ``sha256`` hex digest of those bytes is the content uuid.

Because labels are excluded, two rows can share a content uuid. The gate
must not silently dedupe:

- identical content + **different** labels → **label conflict** (refuse, list
  both row ids)
- identical content + **identical** labels → **duplicate** (report both ids)

Usage (Mill)::

    from content_uuid import content_uuid, canonical_content_bytes
    python3 content_uuid.py < row.json
    python3 content_uuid.py --jsonl rows.jsonl
    python3 content_uuid.py --check rows.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
from collections import defaultdict
from typing import Any, Iterable, Mapping

CONTENT_UUID_FIELDS: tuple[str, ...] = ("state", "questions")
SHA256_LEN = 64
_HEX = frozenset("0123456789abcdef")


def _nfc_value(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        return {_nfc_value(str(key)): _nfc_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_nfc_value(child) for child in value]
    if isinstance(value, tuple):
        return [_nfc_value(child) for child in value]
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """UTF-8 JSON: NFC strings, sorted keys, compact ``,`` / ``:`` separators."""
    payload = _nfc_value(value)
    text = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return unicodedata.normalize("NFC", text).encode("utf-8")


def canonical_content_object(row: Mapping[str, Any]) -> dict[str, Any]:
    """``state`` + ``questions`` only. Labels, ids, and timestamps stay out."""
    payload: dict[str, Any] = {}
    for key in CONTENT_UUID_FIELDS:
        if key in row:
            payload[key] = row[key]
    return payload


def canonical_content_bytes(row: Mapping[str, Any]) -> bytes:
    return canonical_json_bytes(canonical_content_object(row))


def content_uuid(row: Mapping[str, Any]) -> str:
    """sha256 hex of ``canonical_content_bytes(row)``."""
    return hashlib.sha256(canonical_content_bytes(row)).hexdigest()


def canonical_labels_bytes(row: Mapping[str, Any]) -> bytes:
    labels = row.get("labels")
    return canonical_json_bytes(labels if labels is not None else None)


def is_sha256_hex(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == SHA256_LEN
        and not any(ch not in _HEX for ch in value)
    )


def row_id(row: Mapping[str, Any]) -> str:
    for key in ("id", "trajectory_id"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return "?"


def claimed_content_uuid(row: Mapping[str, Any]) -> str | None:
    """Return ``source.content_uuid`` when it is 64 lowercase hex.

    ``source.uuid`` is always a dataset id. It is never read as a content
    uuid, even when it is 64 hex.
    """
    source = row.get("source")
    if isinstance(source, Mapping):
        value = source.get("content_uuid")
        if is_sha256_hex(value):
            return str(value)
    return None


def source_uuid_text(row: Mapping[str, Any]) -> str | None:
    source = row.get("source")
    if isinstance(source, Mapping):
        value = source.get("uuid")
        if type(value) is str and value.strip():
            return value.strip()
    value = row.get("uuid")
    if type(value) is str and value.strip():
        return value.strip()
    return None


def verify_content_uuid(row: Mapping[str, Any]) -> str | None:
    """Return the recomputed digest when a claimed content uuid matches.

    A claimed 64-hex uuid that does not match is a forgery: callers refuse.
    """
    claimed = claimed_content_uuid(row)
    if claimed is None:
        return None
    actual = content_uuid(row)
    if claimed != actual:
        raise ContentUuidError(
            "content_uuid",
            actual,
            claimed,
            f"forged content uuid on {row_id(row)}: claimed {claimed} computed {actual}",
        )
    return actual


class ContentUuidError(Exception):
    def __init__(self, field: str, expected: object, actual: object, message: str) -> None:
        self.field = field
        self.expected = expected
        self.actual = actual
        super().__init__(message)


def find_content_uuid_collisions(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[list[str], list[str]]:
    """Return (label_conflict messages, duplicate messages). Never silently drops."""
    by_uuid: dict[str, list[tuple[str, bytes]]] = defaultdict(list)
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        digest = content_uuid(row)
        by_uuid[digest].append((row_id(row), canonical_labels_bytes(row)))
    conflicts: list[str] = []
    duplicates: list[str] = []
    for digest, members in by_uuid.items():
        if len(members) < 2:
            continue
        by_labels: dict[bytes, list[str]] = defaultdict(list)
        for rid, labels in members:
            by_labels[labels].append(rid)
        if len(by_labels) > 1:
            groups = list(by_labels.values())
            left, right = groups[0][0], groups[1][0]
            conflicts.append(
                f"label conflict: rows {left} and {right} share content uuid "
                f"{digest} with different labels"
            )
            continue
        ids = [rid for rid, _labels in members]
        duplicates.append(
            f"duplicate: rows {ids[0]} and {ids[1]} share content uuid {digest} "
            f"with identical labels"
        )
    return conflicts, duplicates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--jsonl",
        type=str,
        default=None,
        help="read JSONL rows and print one content uuid per line",
    )
    parser.add_argument(
        "--check",
        type=str,
        default=None,
        help="scan JSONL for label conflicts and duplicates; exit 1 on either",
    )
    args = parser.parse_args(argv)
    if args.check:
        rows = _load_jsonl(args.check)
        conflicts, duplicates = find_content_uuid_collisions(rows)
        for line in conflicts + duplicates:
            print(line, file=sys.stderr)
        return 1 if conflicts or duplicates else 0
    if args.jsonl:
        for row in _load_jsonl(args.jsonl):
            print(content_uuid(row))
        return 0
    raw = sys.stdin.read()
    if not raw.strip():
        print("content_uuid: expected a JSON object on stdin", file=sys.stderr)
        return 2
    row = json.loads(raw)
    if not isinstance(row, dict):
        print("content_uuid: stdin must be a JSON object", file=sys.stderr)
        return 2
    print(content_uuid(row))
    return 0


def _load_jsonl(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
