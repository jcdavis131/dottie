#!/usr/bin/env python3
"""Import seam: field paths, DENY_KEYS, and denied-field schema come from mill.

Do not author path lists, DENY_KEYS, or schema rules here. Mill tokenizer
v2.2 owns ``extract_paths(row)`` (ordered ``(json_path, raw_value)`` pairs
with raw byte spans, decoded JSON-string args included) and the schema
check. The gate and the trainer import this module only.

Until v2.2 is vendored, every extract_paths / check_denied / trainer /
gate-tokenize call fail-closes. v1 stays pinned for near-dup tokens,
HMAC, and the rest of the kick.
"""
from __future__ import annotations

import sys
from typing import Any, Mapping, Sequence

MILL_EXTRACT_PATHS_VERSION = "v2.2"
_PINNED_MILL_MODULE = "neardup_tokens_v1"


class RowFieldsError(Exception):
    """Seam refused: mill v2.2 extract_paths / schema check is not live."""

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        super().__init__(f"{field}: {reason}")


def _refuse(field: str, reason: str) -> None:
    raise RowFieldsError(field, reason)


def _pinned_mill() -> Any:
    """The hashed mill module already loaded by content_uuid. Never a second copy."""
    return sys.modules.get(_PINNED_MILL_MODULE)


def extract_paths_ready() -> bool:
    mill = _pinned_mill()
    return callable(getattr(mill, "extract_paths", None)) and callable(
        getattr(mill, "check_denied", None)
    )


def _require_v22() -> Any:
    mill = _pinned_mill()
    if mill is None or not extract_paths_ready():
        _refuse(
            "extract_paths",
            "mill tokenizer v2.2 is not vendored",
        )
        raise AssertionError("unreachable")
    return mill


def _refuse_mill(exc: BaseException) -> None:
    if isinstance(exc, RowFieldsError):
        raise exc
    field = getattr(exc, "field", None)
    reason = getattr(exc, "reason", None)
    if type(field) is not str:
        field = "extract_paths"
    if type(reason) is not str:
        reason = str(exc)
    _refuse(field, reason)
    raise AssertionError("unreachable")


def _run_check_denied(mill: Any, row: object) -> None:
    try:
        mill.check_denied(row)
    except RowFieldsError:
        raise
    except Exception as exc:
        _refuse_mill(exc)


def _pair_path(item: object) -> str:
    if isinstance(item, (tuple, list)) and item and type(item[0]) is str:
        return item[0]
    if isinstance(item, Mapping) and type(item.get("path")) is str:
        return item["path"]
    _refuse("extract_paths", "pair has no json_path")
    raise AssertionError("unreachable")


def extract_paths(row: object) -> Sequence[Any]:
    """Ordered ``(json_path, raw_value, byte_span)`` from mill v2.2. Fail-closed until vendored."""
    mill = _require_v22()
    _run_check_denied(mill, row)
    try:
        pairs = mill.extract_paths(row)
    except RowFieldsError:
        raise
    except Exception as exc:
        _refuse_mill(exc)
        raise AssertionError("unreachable")
    if pairs is None:
        _refuse("extract_paths", "mill extract_paths returned nothing")
        raise AssertionError("unreachable")
    return pairs


def check_denied(row: object) -> None:
    """Mill v2.2 denied-field schema check. Fail-closed until vendored."""
    mill = _require_v22()
    _run_check_denied(mill, row)


def gate_tokens(row: object) -> frozenset[str]:
    """Tokenize extract_paths values via mill. Fail-closed until v2.2."""
    mill = _require_v22()
    pairs = extract_paths(row)
    tokenize = getattr(mill, "message_tokens", None)
    if not callable(tokenize):
        _refuse("extract_paths", "mill tokenizer has no message_tokens")
        raise AssertionError("unreachable")
    tokens: set[str] = set()
    for item in pairs:
        if isinstance(item, Mapping):
            raw = item.get("raw")
            if raw is None:
                raw = item.get("value")
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            raw = item[1]
        else:
            _refuse("extract_paths", "pair is not (json_path, raw_value, ...)")
            raise AssertionError("unreachable")
        if type(raw) is bytes:
            raw = raw.decode("utf-8")
        extracted = tokenize(raw)
        tokens.update(extracted)
    return frozenset(tokens)


def trainer_input_from_row(row: Mapping[str, Any]) -> Sequence[Any]:
    """Same extract_paths pairs, untouched. Fail-closed until v2.2."""
    return extract_paths(row)


def scanned_field_paths(row: object) -> tuple[str, ...]:
    """Gate scan paths from mill extract_paths on this row."""
    return tuple(_pair_path(item) for item in extract_paths(row))


def trainer_read_paths(row: object) -> tuple[str, ...]:
    """Trainer read paths. Same mill extract_paths pairs as the gate."""
    return tuple(_pair_path(item) for item in trainer_input_from_row(row))
