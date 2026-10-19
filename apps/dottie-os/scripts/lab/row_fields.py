#!/usr/bin/env python3
"""Single source of truth for near-dup scan paths and the denied-field list.

The near-dup gate and the trainer both import this module. Do not copy these
tuples elsewhere. Readable paths are the raw JSON fields the gate scans;
the trainer reads those same paths as original UTF-8 bytes (no mill
normalize / message_text). Denied fields reach the trainer only after the
schema check.
"""
from __future__ import annotations

from typing import Any, Mapping

# Dotted paths the near-dup gate scans and the trainer reads as raw bytes.
READABLE_PATHS: tuple[str, ...] = ("state.message",)
# Fields the near-dup extractor never reads. Schema-checked before trainer.
DENY_KEYS: tuple[str, ...] = (
    "schema",
    "id",
    "tier",
    "source",
    "labels",
    "questions",
    "consent",
    "trajectory_id",
    "record_id",
    "group_key",
    "state.meta",
)


class _Missing:
    """Sentinel: path absent. Never bool()/len() this value."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "MISSING"


MISSING: Any = _Missing()


def scanned_field_paths() -> tuple[str, ...]:
    """Near-dup gate scan paths. Same object as ``READABLE_PATHS``."""
    return READABLE_PATHS


def trainer_read_paths() -> tuple[str, ...]:
    """Trainer readable-field paths. Same object as ``READABLE_PATHS``."""
    return READABLE_PATHS


def get_by_path(row: object, path: str) -> Any:
    """Return the value at a dotted path, or ``MISSING`` if any step is absent."""
    if type(path) is not str or not path:
        return MISSING
    cur: object = row
    for part in path.split("."):
        if not isinstance(cur, Mapping) or part not in cur:
            return MISSING
        cur = cur[part]
    return cur


def raw_field_bytes(value: object) -> bytes:
    """UTF-8 bytes of a readable field. No NFKC, no casefold, no mill extract."""
    if type(value) is bytes:
        return value
    if type(value) is str:
        return value.encode("utf-8")
    raise TypeError(f"readable field must be str or bytes, got {type(value).__name__}")


def readable_raw_fields(row: object) -> dict[str, bytes]:
    """Raw original bytes for each present readable path. Skips non-str values."""
    out: dict[str, bytes] = {}
    if not isinstance(row, Mapping):
        return out
    for path in READABLE_PATHS:
        value = get_by_path(row, path)
        if value is MISSING:
            continue
        if type(value) is str or type(value) is bytes:
            out[path] = raw_field_bytes(value)
    return out
