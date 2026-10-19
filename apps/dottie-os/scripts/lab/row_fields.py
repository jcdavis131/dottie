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


def mill_v2x_ready() -> bool:
    """True when mill v2.x near_dup/match/is_no_text are live on the pinned module."""
    mill = _pinned_mill()
    return (
        extract_paths_ready()
        and callable(getattr(mill, "near_dup", None))
        and callable(getattr(mill, "match", None))
        and callable(getattr(mill, "is_no_text", None))
    )


def _mill_dummy_fn(mill: Any) -> Any:
    for name in ("dummy_tags", "derive_dummy_shingles", "dummy_shingles", "fp_dummy_tags"):
        fn = getattr(mill, name, None)
        if callable(fn):
            return fn
    return None


def _mill_bucket_attr(mill: Any) -> Any:
    for name in ("FP_BUCKETS", "BUCKET_SIZES", "FINGERPRINT_BUCKETS", "PAD_BUCKETS"):
        val = getattr(mill, name, None)
        if val is not None:
            return val
    return None


def mill_fp_pad_ready() -> bool:
    """True when mill v2.2 exports fingerprint buckets and dummy-tag derivation."""
    mill = _pinned_mill()
    return extract_paths_ready() and _mill_dummy_fn(mill) is not None and _mill_bucket_attr(mill) is not None


def mill_fp_buckets() -> tuple[int, ...]:
    mill = _require_v22()
    raw = _mill_bucket_attr(mill)
    if raw is None:
        _refuse("extract_paths", "mill fingerprint bucket list is missing")
        raise AssertionError("unreachable")
    buckets: list[int] = []
    for item in raw:
        if type(item) is not int or item < 1:
            _refuse("extract_paths", "mill fingerprint bucket list is invalid")
            raise AssertionError("unreachable")
        buckets.append(item)
    if not buckets:
        _refuse("extract_paths", "mill fingerprint bucket list is empty")
        raise AssertionError("unreachable")
    return tuple(buckets)


def mill_min_ref() -> dict[str, int]:
    mill = _require_v22()
    nchar = getattr(mill, "MIN_REF_NCHAR", None)
    b_min = getattr(mill, "MIN_REF_B", None)
    if b_min is None:
        b_min = getattr(mill, "MIN_REF_SHINGLES", None)
    if type(nchar) is not int:
        nchar = 20
    if type(b_min) is not int:
        b_min = 16
    return {"nchar_ge": nchar, "b_ge": b_min}


def mill_dummy_tags(key: bytes, digest: str, public: frozenset[str]) -> frozenset[str]:
    """Recompute mill dummy tags. Never logs the key or the tags."""
    mill = _require_v22()
    fn = _mill_dummy_fn(mill)
    if not callable(fn):
        _refuse("extract_paths", "mill dummy-tag function is missing")
        raise AssertionError("unreachable")
    if type(key) is not bytes or not key:
        _refuse("reserved_near_dup_hmac.hasher", "loaded keyed hasher missing")
        raise AssertionError("unreachable")
    try:
        tags = fn(key, digest, public)
    except TypeError:
        try:
            tags = fn(key=key, digest=digest, public=public)
        except Exception as exc:
            _refuse_mill(exc)
            raise AssertionError("unreachable")
    except Exception as exc:
        _refuse_mill(exc)
        raise AssertionError("unreachable")
    if tags is None:
        _refuse("extract_paths", "mill dummy-tag function returned nothing")
        raise AssertionError("unreachable")
    out: set[str] = set()
    for item in tags:
        if type(item) is not str:
            _refuse("extract_paths", "mill dummy tags are invalid")
            raise AssertionError("unreachable")
        out.add(item)
    return frozenset(out)


def no_text_error_types() -> tuple[type, ...]:
    mill = _require_v22()
    cls = getattr(mill, "NoTextError", None)
    if isinstance(cls, type) and issubclass(cls, BaseException):
        return (cls,)
    return ()


def _mill_trainer_allowlist(mill: Any) -> frozenset[str]:
    for name in ("ALLOW_PATHS", "TRAIN_PATHS", "READABLE_PATHS"):
        val = getattr(mill, name, None)
        if val is not None:
            return frozenset(str(item) for item in val)
    _refuse("extract_paths", "mill trainer allowlist is missing")
    raise AssertionError("unreachable")


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
    """extract_paths pairs on the mill allowlist, after schema check. Fail-closed until v2.2.

    Allowlist is mill's, separate from DENY_KEYS. Paths not on the exact
    allowlist are not trainer input (no free text through case/spacing/lookalike keys).
    """
    mill = _require_v22()
    pairs = extract_paths(row)
    allow = _mill_trainer_allowlist(mill)
    return [item for item in pairs if _pair_path(item) in allow]


def scanned_field_paths(row: object) -> tuple[str, ...]:
    """Gate scan paths from mill extract_paths on this row."""
    return tuple(_pair_path(item) for item in extract_paths(row))


def trainer_read_paths(row: object) -> tuple[str, ...]:
    """Trainer read paths. Same mill extract_paths pairs as the gate."""
    return tuple(_pair_path(item) for item in trainer_input_from_row(row))
