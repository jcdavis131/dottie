#!/usr/bin/env python3
"""Import seam: field paths, DENY_KEYS, and denied-field schema come from mill.

Do not author path lists, DENY_KEYS, schema rules, CAP, SAMPLE_MARGIN, or
BUCKETS here. Mill tokenizer v2.2 owns ``extract_paths(row)`` (ordered
json_path strings), ``get_by_path(row, json_path)`` path round-trips, and
``check_denied(row)`` which raises mill ``DeniedFieldError``. The trainer
reads row values only through ``get_by_path``. The gate and the trainer
import this module only.

Until v2.2 is vendored, every extract_paths / get_by_path / check_denied /
trainer / gate-tokenize call fail-closes. v1 stays pinned for near-dup
tokens, HMAC, and the rest of the kick.
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


class DeniedFieldError(RowFieldsError):
    """Mill ``check_denied`` refused a denied field. Catch and refuse the row."""


def _refuse(field: str, reason: str) -> None:
    raise RowFieldsError(field, reason)


def _pinned_mill() -> Any:
    """The hashed mill module already loaded by content_uuid. Never a second copy."""
    return sys.modules.get(_PINNED_MILL_MODULE)


def extract_paths_ready() -> bool:
    mill = _pinned_mill()
    return (
        callable(getattr(mill, "extract_paths", None))
        and callable(getattr(mill, "check_denied", None))
        and callable(getattr(mill, "get_by_path", None))
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
    for name in ("BUCKETS", "FP_BUCKETS", "BUCKET_SIZES", "FINGERPRINT_BUCKETS", "PAD_BUCKETS"):
        val = getattr(mill, name, None)
        if val is not None:
            return val
    return None


def mill_constants_ready() -> bool:
    """True when mill v2.2 exports CAP, SAMPLE_MARGIN, and BUCKETS. Gate never defines them."""
    mill = _pinned_mill()
    cap = getattr(mill, "CAP", None)
    margin = getattr(mill, "SAMPLE_MARGIN", None)
    return (
        extract_paths_ready()
        and type(cap) is int
        and type(margin) in (int, float)
        and _mill_bucket_attr(mill) is not None
    )


def mill_fp_pad_ready() -> bool:
    """True when mill v2.2 exports buckets, dummy tags, CAP, and SAMPLE_MARGIN."""
    mill = _pinned_mill()
    return mill_constants_ready() and _mill_dummy_fn(mill) is not None


def mill_cap() -> int:
    mill = _require_v22()
    cap = getattr(mill, "CAP", None)
    if type(cap) is not int or cap < 1:
        _refuse("extract_paths", "mill CAP is missing")
        raise AssertionError("unreachable")
    return cap


def mill_sample_margin() -> float:
    mill = _require_v22()
    margin = getattr(mill, "SAMPLE_MARGIN", None)
    if type(margin) is int:
        return float(margin)
    if type(margin) is not float:
        _refuse("extract_paths", "mill SAMPLE_MARGIN is missing")
        raise AssertionError("unreachable")
    return margin


def mill_buckets() -> tuple[int, ...]:
    mill = _require_v22()
    raw = _mill_bucket_attr(mill)
    if raw is None:
        _refuse("extract_paths", "mill bucket list is missing")
        raise AssertionError("unreachable")
    buckets: list[int] = []
    for item in raw:
        if type(item) is not int or item < 1:
            _refuse("extract_paths", "mill bucket list is invalid")
            raise AssertionError("unreachable")
        buckets.append(item)
    if not buckets:
        _refuse("extract_paths", "mill bucket list is empty")
        raise AssertionError("unreachable")
    return tuple(buckets)


def mill_fp_buckets() -> tuple[int, ...]:
    """Fingerprint pad buckets. Same mill ``BUCKETS`` export; never a second list."""
    return mill_buckets()


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
    mill = _pinned_mill()
    mill_denied = getattr(mill, "DeniedFieldError", None) if mill is not None else None
    if isinstance(mill_denied, type) and isinstance(exc, mill_denied):
        _raise_denied(exc)
        raise AssertionError("unreachable")
    field = getattr(exc, "field", None)
    reason = getattr(exc, "reason", None)
    if type(field) is not str:
        field = "extract_paths"
    if type(reason) is not str:
        reason = str(exc)
    _refuse(field, reason)
    raise AssertionError("unreachable")


def _raise_denied(exc: BaseException) -> None:
    field = getattr(exc, "field", None)
    reason = getattr(exc, "reason", None)
    if type(field) is not str:
        field = "extract_paths"
    if type(reason) is not str:
        reason = str(exc)
    raise DeniedFieldError(field, reason)


def _run_check_denied(mill: Any, row: object) -> None:
    try:
        mill.check_denied(row)
    except DeniedFieldError:
        raise
    except Exception as exc:
        _refuse_mill(exc)


def _path_from_item(item: object) -> str:
    if type(item) is str and item:
        return item
    if isinstance(item, (tuple, list)) and item and type(item[0]) is str:
        return item[0]
    if isinstance(item, Mapping) and type(item.get("path")) is str:
        return item["path"]
    _refuse("extract_paths", "item has no json_path")
    raise AssertionError("unreachable")


def extract_paths(row: object) -> Sequence[str]:
    """Ordered json_path strings from mill v2.2. Fail-closed until vendored.

    Path round-trips, not byte spans. Values come from ``get_by_path``.
    """
    mill = _require_v22()
    _run_check_denied(mill, row)
    try:
        raw = mill.extract_paths(row)
    except DeniedFieldError:
        raise
    except Exception as exc:
        _refuse_mill(exc)
        raise AssertionError("unreachable")
    if raw is None:
        _refuse("extract_paths", "mill extract_paths returned nothing")
        raise AssertionError("unreachable")
    paths: list[str] = []
    for item in raw:
        paths.append(_path_from_item(item))
    return tuple(paths)


def check_denied(row: object) -> None:
    """Mill v2.2 denied-field schema check. Raises DeniedFieldError. Fail-closed until vendored."""
    mill = _require_v22()
    try:
        _run_check_denied(mill, row)
    except DeniedFieldError:
        raise


def get_by_path(row: object, json_path: object) -> Any:
    """Mill v2.2 path round-trip. Fail-closed until vendored. Never walks the row here."""
    mill = _require_v22()
    fn = getattr(mill, "get_by_path", None)
    if not callable(fn):
        _refuse("extract_paths", "mill get_by_path is missing")
        raise AssertionError("unreachable")
    if type(json_path) is not str or not json_path:
        _refuse("extract_paths", "json_path missing")
        raise AssertionError("unreachable")
    try:
        return fn(row, json_path)
    except DeniedFieldError:
        raise
    except Exception as exc:
        _refuse_mill(exc)
        raise AssertionError("unreachable")


def gate_tokens(row: object) -> frozenset[str]:
    """Tokenize ``get_by_path`` values for each ``extract_paths`` path. Fail-closed until v2.2."""
    mill = _require_v22()
    try:
        check_denied(row)
    except DeniedFieldError:
        raise
    tokenize = getattr(mill, "message_tokens", None)
    if not callable(tokenize):
        _refuse("extract_paths", "mill tokenizer has no message_tokens")
        raise AssertionError("unreachable")
    tokens: set[str] = set()
    for json_path in extract_paths(row):
        raw = get_by_path(row, json_path)
        if type(raw) is bytes:
            raw = raw.decode("utf-8")
        extracted = tokenize(raw)
        is_no_text = getattr(mill, "is_no_text", None)
        if callable(is_no_text) and is_no_text(extracted):
            continue
        tokens.update(extracted)
    return frozenset(tokens)


def trainer_input_from_row(row: Mapping[str, Any]) -> Sequence[tuple[str, Any]]:
    """Trainer values: mill ``get_by_path`` on ``extract_paths`` only. No row subscript or ``.get``.

    ``check_denied`` raises DeniedFieldError; catch and refuse the row.
    """
    try:
        check_denied(row)
    except DeniedFieldError:
        raise
    paths = extract_paths(row)
    out: list[tuple[str, Any]] = []
    for json_path in paths:
        out.append((json_path, get_by_path(row, json_path)))
    return out


def scanned_field_paths(row: object) -> tuple[str, ...]:
    """Gate scan paths from mill extract_paths on this row."""
    return tuple(extract_paths(row))


def trainer_read_paths(row: object) -> tuple[str, ...]:
    """Trainer read paths. Same mill extract_paths as the gate; values via get_by_path."""
    return tuple(json_path for json_path, _value in trainer_input_from_row(row))
