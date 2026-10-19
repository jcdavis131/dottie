#!/usr/bin/env python3
"""Canonical content uuid for HELPER FT rows.

Mill backfills ``source.content_uuid`` on a row whose source has none by
hashing this canonical form. The kick gate recomputes the same digest and
verifies ``source.content_uuid``. ``source.uuid`` is always an opaque
dataset id, never a content uuid, even when it is 64 hex. A missing
``source.uuid`` is allowed when a valid ``source.content_uuid`` is present
and verifies.

Included fields: ``state`` and ``questions`` only (top-level selection).
Nested keys inside those objects — including nested ``id`` and
``timestamp`` — stay in the hash. Do not drop keys by name under
``state``/``questions``.
Excluded at the top level only: ``labels``, ids (``id``, ``uuid``,
``trajectory_id``, ``source.uuid``), timestamps, and every other
top-level key. A row with neither ``state`` nor ``questions`` is
``content_uuid.empty``.

Encoding, exactly:
1. Build a JSON object with the included fields that are present (a missing
   field is omitted, not null).
2. Recursively canonicalize that object (depth cap 256, checked before
   descending). JSON loaders also cap nesting iteratively before
   ``json.loads`` recurses.
   ``type(v) is bool`` is left as a JSON bool (``true``/``false``) and is
   checked **before** int/float handling, so bools never collapse with
   ``0``/``1``. Numpy scalars fold to Python bool/int/float only when
   ``numpy`` is already imported; numpy is never imported by this module
   when absent. Any finite float ``f`` with ``abs(f) <= 2**53`` and
   ``f.is_integer()`` becomes ``int(f)`` (so ``1.0`` hashes as ``1``, and
   ``-0.0`` becomes ``0``). Non-integer floats in that range keep their
   ``json.dumps`` repr. Floats with ``abs(f) > 2**53`` refuse as
   ``content_uuid.float_precision`` (encoding is not changed; v3 has none).
   Strings (keys and values) are Unicode NFC. Keys that collide after NFC
   refuse as ``content_uuid.key_collision``. Non-str keys refuse as
   ``content_uuid.unsupported_type``. ``NaN`` and ``±Infinity`` refuse as
   ``content_uuid.non_finite``.
3. ``json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False,
   allow_nan=False)``.
4. UTF-8 encode those JSON bytes.
5. ``sha256`` hex digest of those bytes is the content uuid.

Exact-hash report-only (not folded, by design): ``"1"`` vs ``1``; trailing
or doubled whitespace; case; BOM; zero-width and fullwidth (NFKC-only)
characters. Near-dup scoring is the control for those.

Because labels are excluded, two rows can share a content uuid. The gate
must not silently dedupe:

- identical content + **different** labels → ``content_uuid.label_conflict``
  (refuse, list both row ids)
- identical content + **identical** labels **within one split** →
  ``content_uuid.duplicate``
- identical content + **identical** labels **across train and holdout** →
  ``content_uuid.cross_split_duplicate``
- identical content + **different** labels **across train and holdout** →
  both ``content_uuid.label_conflict`` and ``content_uuid.cross_split_leak``

Usage (Mill)::

    from content_uuid import (
        content_uuid,
        canonical_content_bytes,
        eval_partition_residue,
        in_reserved_eval_partition,
        RESERVED_EVAL_PARTITION_N,
        RESERVED_EVAL_PARTITION_RESIDUES,
    )
    python3 content_uuid.py < row.json
    python3 content_uuid.py --jsonl rows.jsonl
    python3 content_uuid.py --check rows.jsonl
    python3 content_uuid.py --check train.jsonl --holdout holdout.jsonl

N membership is ``eval_partition_residue(key) in RESERVED_EVAL_PARTITION_RESIDUES``
with ``key`` = raw ``source.uuid`` or the lowercase 64-hex ``content_uuid``.
Never ``int(content_uuid, 16)``.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import types
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

_CU_FILE = str(globals().get("__file__") or "")
_CU_DIR = str(Path(__file__).resolve().parent) if "__file__" in globals() else ""
if _CU_DIR and _CU_DIR not in sys.path and not _CU_DIR.startswith("/proc/"):
    sys.path.insert(0, _CU_DIR)

CONTENT_UUID_FIELDS: tuple[str, ...] = ("state", "questions")
SHA256_LEN = 64
_HEX = frozenset("0123456789abcdef")
MAX_DEPTH = 256
MAX_INT_DIGITS = 4300
_MAX_INT = 10 ** MAX_INT_DIGITS
_FLOAT_ABS_MAX = float(2**53)
_NEAR_DUP_INDEX_ATTR = "_dottie_os_content_uuid_near_dup_index"
_KICK_ROWS_ATTR = "_dottie_os_kick_near_dup_rows"
_KICK_FPS_ATTR = "_dottie_os_kick_near_dup_fps"
_NEAR_DUP_TOKENIZER_REL = "apps/dottie-os/scripts/lab/neardup_tokens-v1.py"
_NEAR_DUP_GOLDEN_REL = "apps/dottie-os/scripts/lab/neardup_tokens-v1.golden.json"
# Live Mill tokenizer. CODE_PINS / REQUIRED_PINS pin this sha together with the file.
NEAR_DUP_TOKENIZER_VERSION = "v1"
NEAR_DUP_TOKENIZER_SHA256 = (
    "50d5015a051832608391208b7fc3f48259d6e94443213bb46143a06aa2a4f173"
)
NEAR_DUP_GOLDEN_SHA256 = (
    "69609b85cb779a57f071aabc4a94af300f106ea04617d956135d267454d4b7bc"
)
# Fail-closed v2 slot. Mill vendoring is held pending Critic; do not load or pin v2.
_NEAR_DUP_TOKENIZER_V2_REL = "apps/dottie-os/scripts/lab/neardup_tokens-v2.py"
_NEAR_DUP_GOLDEN_V2_REL = "apps/dottie-os/scripts/lab/neardup_tokens-v2.golden.json"
NEAR_DUP_TOKENIZER_V2_SHA256 = (
    "NEAR_DUP_TOKENIZER_V2_SHA256_PLACEHOLDER_NOT_A_LIVE_FILE"
)
NEAR_DUP_GOLDEN_V2_SHA256 = (
    "NEAR_DUP_TOKENIZER_V2_GOLDEN_SHA256_PLACEHOLDER_NOT_A_LIVE_FILE"
)
_NEAR_DUP_TOKENIZER_PLACEHOLDER_MARKERS = (
    "NEAR_DUP_TOKENIZER_SHA256_PLACEHOLDER_NOT_A_LIVE_FILE",
    "NEAR_DUP_TOKENIZER_PLACEHOLDER",
)
_NEAR_DUP_TOKENIZER_MODULE = None
# Mill N membership. One formula for raw source.uuid and for uuid-less
# content_uuid hex: int(sha256(ascii key).hexdigest(), 16) % 10 in {0, 5}.
RESERVED_EVAL_PARTITION_N = 10
RESERVED_EVAL_PARTITION_RESIDUES: frozenset[int] = frozenset({0, 5})


def _ensure_int_str_digits() -> None:
    """Keep ``MAX_INT_DIGITS`` authoritative even if PYTHONINTMAXSTRDIGITS is set."""
    setter = getattr(sys, "set_int_max_str_digits", None)
    getter = getattr(sys, "get_int_max_str_digits", None)
    if setter is None or getter is None:
        return
    needed = MAX_INT_DIGITS + 32
    current = getter()
    if current == 0:
        return
    if current < needed:
        setter(needed)


_ensure_int_str_digits()


def _shared_near_dup_index() -> dict[str, tuple[str, frozenset[str]]]:
    """Legacy sys bucket. Kick fingerprints are per-kick, not this object.

    Critic FIND_B6_hex_only still calls this; it is never the lookup path.
    """
    bucket = getattr(sys, _NEAR_DUP_INDEX_ATTR, None)
    if not isinstance(bucket, dict):
        bucket = {}
        setattr(sys, _NEAR_DUP_INDEX_ATTR, bucket)
    return bucket


def _kick_near_dup_rows() -> dict[str, Mapping[str, Any]]:
    bucket = getattr(sys, _KICK_ROWS_ATTR, None)
    if not isinstance(bucket, dict):
        bucket = {}
        setattr(sys, _KICK_ROWS_ATTR, bucket)
    return bucket


def _kick_near_dup_fps() -> dict[str, tuple[str, frozenset[str]]]:
    bucket = getattr(sys, _KICK_FPS_ATTR, None)
    if not isinstance(bucket, dict):
        bucket = {}
        setattr(sys, _KICK_FPS_ATTR, bucket)
    return bucket


def reset_kick_near_dup_fingerprints() -> None:
    """Clear per-kick fingerprint state. Call at the start of each kick/gate."""
    _kick_near_dup_rows().clear()
    _kick_near_dup_fps().clear()


def install_kick_near_dup_fingerprints(
    index: Mapping[str, tuple[str, frozenset[str]]],
) -> None:
    """Install sha-pinned N fingerprints for this kick only."""
    fps = _kick_near_dup_fps()
    fps.clear()
    for digest, payload in index.items():
        if type(digest) is not str or len(digest) != SHA256_LEN:
            continue
        if not isinstance(payload, tuple) or len(payload) != 2:
            continue
        fps[digest] = payload


def kick_near_dup_fingerprints_loaded() -> bool:
    """True after this kick installed sha-pinned N fingerprints."""
    return bool(_kick_near_dup_fps())


def _note_kick_near_dup_row(digest: str, row: Mapping[str, Any]) -> None:
    payload = {field: row[field] for field in CONTENT_UUID_FIELDS if field in row}
    _kick_near_dup_rows()[digest] = payload


def _is_sealed_load() -> bool:
    """True when this module was exec'd from a sealed fd, not a lab path."""
    raw = _CU_FILE or str(globals().get("__file__") or "")
    return raw.startswith("/proc/") or raw.startswith("/memfd:") or "memfd:" in raw


def _mill_tokenizer_path() -> Path:
    here = Path(__file__).resolve()
    if _CU_DIR and not _CU_DIR.startswith("/proc/") and not _is_sealed_load():
        sibling = Path(_CU_DIR) / "neardup_tokens-v1.py"
        if sibling.is_file():
            return sibling
    try:
        return here.parents[4] / _NEAR_DUP_TOKENIZER_REL
    except IndexError:
        return here.parent / "neardup_tokens-v1.py"


def _mill_golden_path() -> Path:
    return _mill_tokenizer_path().with_name("neardup_tokens-v1.golden.json")


def _require_near_dup_golden() -> None:
    """Fail closed unless the CODE_PINS mill golden file matches ``NEAR_DUP_GOLDEN_SHA256``."""
    if _is_sealed_load():
        return
    path = _mill_golden_path()
    if not path.is_file():
        raise ContentUuidError(
            "near_dup_golden",
            NEAR_DUP_GOLDEN_SHA256,
            "missing",
            "near-dup tokenizer golden missing or unreadable",
        )
    digest = hashlib.sha256(_read_tokenizer_bytes(path)).hexdigest()
    if digest != NEAR_DUP_GOLDEN_SHA256:
        raise ContentUuidError(
            "near_dup_golden",
            NEAR_DUP_GOLDEN_SHA256,
            digest,
            "near-dup tokenizer golden sha256 is not the CODE_PINS value",
        )


def _read_tokenizer_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    proc_fd = str(path).startswith("/proc/")
    if not proc_fd and hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ContentUuidError(
            "near_dup_tokenizer",
            "vendored Mill tokenizer",
            f"OSError:{getattr(exc, 'errno', None)}",
            "near-dup tokenizer missing or unreadable",
        ) from exc
    try:
        chunks: list[bytes] = []
        while True:
            block = os.read(fd, 1 << 20)
            if not block:
                break
            chunks.append(block)
        return b"".join(chunks)
    except OSError as exc:
        raise ContentUuidError(
            "near_dup_tokenizer",
            "readable file",
            f"OSError:{getattr(exc, 'errno', None)}",
            "near-dup tokenizer unreadable",
        ) from exc
    finally:
        os.close(fd)


def _sealed_tokenizer_origin() -> Path | None:
    """Resolve mill only from a sealed ``/proc/`` fd. Disk misses fail closed."""
    existing = sys.modules.get("neardup_tokens_v1")
    existing_file = getattr(existing, "__file__", None)
    if isinstance(existing_file, str) and existing_file.startswith("/proc/"):
        return Path(existing_file)
    try:
        spec = importlib.util.find_spec("neardup_tokens_v1")
    except (ValueError, ModuleNotFoundError):
        spec = None
    found = Path(spec.origin) if spec is not None and spec.origin else None
    if found is not None and str(found).startswith("/proc/"):
        return found
    return None


def require_near_dup_tokenizer_version(version: object) -> str:
    """Bind the gate to v1. The v2 slot is a fail-closed placeholder until Mill vendors it."""
    if type(version) is not str or not version:
        raise ContentUuidError(
            "near_dup_tokenizer.version",
            NEAR_DUP_TOKENIZER_VERSION,
            "missing",
            "near-dup tokenizer version missing",
        )
    if version == "v2":
        raise ContentUuidError(
            "near_dup_tokenizer.version",
            NEAR_DUP_TOKENIZER_SHA256,
            NEAR_DUP_TOKENIZER_V2_SHA256,
            "near-dup tokenizer v2 is a fail-closed placeholder",
        )
    if version != NEAR_DUP_TOKENIZER_VERSION:
        raise ContentUuidError(
            "near_dup_tokenizer.version",
            NEAR_DUP_TOKENIZER_VERSION,
            version,
            "near-dup tokenizer version is not the pinned v1",
        )
    return version


def _is_no_text(value: object) -> bool:
    """True for Mill v2's NO_TEXT sentinel. Never bool()/len()/iter() the value."""
    if value is None:
        return False
    name = type(value).__name__
    if name in {"NoText", "NO_TEXT"}:
        return True
    mill = sys.modules.get("neardup_tokens_v1") or sys.modules.get("neardup_tokens_v2")
    sentinel = getattr(mill, "NO_TEXT", None) if mill is not None else None
    return sentinel is not None and value is sentinel


def _load_mill_near_dup_tokenizer(*, version: str | None = None) -> Any:
    require_near_dup_tokenizer_version(
        NEAR_DUP_TOKENIZER_VERSION if version is None else version
    )
    origin: Path | None = None
    if _is_sealed_load():
        origin = _sealed_tokenizer_origin()
    else:
        path = _mill_tokenizer_path()
        origin = path if path.is_file() else None
    if origin is None:
        raise ContentUuidError(
            "near_dup_tokenizer",
            "vendored Mill tokenizer",
            "missing",
            "near-dup tokenizer missing or unreadable",
        )
    buf = _read_tokenizer_bytes(origin)
    digest = hashlib.sha256(buf).hexdigest()
    if digest != NEAR_DUP_TOKENIZER_SHA256:
        raise ContentUuidError(
            "near_dup_tokenizer",
            NEAR_DUP_TOKENIZER_SHA256,
            digest,
            "near-dup tokenizer sha256 is not the CODE_PINS value",
        )
    _require_near_dup_golden()
    try:
        text = buf.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContentUuidError(
            "near_dup_tokenizer",
            "utf-8",
            "invalid encoding",
            "near-dup tokenizer is not utf-8",
        ) from exc
    if any(marker in text for marker in _NEAR_DUP_TOKENIZER_PLACEHOLDER_MARKERS):
        raise ContentUuidError(
            "near_dup_tokenizer",
            "Mill vendored tokenizer",
            "placeholder",
            "near-dup tokenizer is a placeholder; Mill has not vendored the live file",
        )
    try:
        code = compile(text, str(origin), "exec")
    except SyntaxError as exc:
        raise ContentUuidError(
            "near_dup_tokenizer",
            "importable module",
            "syntax",
            "near-dup tokenizer could not be loaded",
        ) from exc
    mod = types.ModuleType("neardup_tokens_v1")
    mod.__file__ = str(origin)
    exec(code, mod.__dict__)
    if getattr(mod, "NEAR_DUP_TOKENIZER_PLACEHOLDER", False):
        raise ContentUuidError(
            "near_dup_tokenizer",
            "Mill vendored tokenizer",
            "placeholder",
            "near-dup tokenizer is a placeholder; Mill has not vendored the live file",
        )
    if not callable(getattr(mod, "message_tokens", None)):
        raise ContentUuidError(
            "near_dup_tokenizer",
            "message_tokens",
            "missing",
            "Mill tokenizer has no message_tokens function",
        )
    sys.modules["neardup_tokens_v1"] = mod
    return mod


def _row_state_message(value: Any) -> str | None:
    """Mill tokenizes only a ``state.message`` string. Anything else is untokenized."""
    if type(value) is str:
        return value
    if isinstance(value, Mapping):
        state = value.get("state")
        if isinstance(state, Mapping) and type(state.get("message")) is str:
            return state["message"]
        if type(value.get("message")) is str:
            return value["message"]
    return None


def near_dup_tokens(value: Any) -> frozenset[str]:
    """Message-only tokens via the vendored Mill v1 tokenizer. No Forge tokenize logic.

    Rows with no tokenizable ``state.message`` string are refused (v1). A v2
    ``NO_TEXT`` sentinel is also refused. Callers must not truthiness-skip.
    """
    mill = _load_mill_near_dup_tokenizer(version=NEAR_DUP_TOKENIZER_VERSION)
    message = _row_state_message(value)
    if message is None:
        raise ContentUuidError(
            "near_dup_tokens",
            "tokenizable state.message str",
            "missing",
            "row has no tokenizable state.message",
        )
    try:
        extracted = mill.message_tokens(message)
    except TypeError as exc:
        raise ContentUuidError(
            "near_dup_tokenizer",
            "state.message str",
            type(value).__name__,
            "Mill tokenizer refused the message",
        ) from exc
    if _is_no_text(extracted):
        raise ContentUuidError(
            "near_dup_tokens",
            "tokenizable state.message str",
            "NO_TEXT",
            "Mill tokenizer returned NO_TEXT",
        )
    try:
        tokens = frozenset(extracted)
    except TypeError as exc:
        raise ContentUuidError(
            "near_dup_tokens",
            "token set",
            type(extracted).__name__,
            "Mill tokenizer did not return a token set",
        ) from exc
    return tokens


def record_near_dup_fingerprint(digest: str, row: Mapping[str, Any]) -> None:
    payload = {field: row[field] for field in CONTENT_UUID_FIELDS if field in row}
    _kick_near_dup_fps()[digest] = (row_id(row), near_dup_tokens(payload))


def lookup_near_dup_fingerprint(digest: str) -> tuple[str, frozenset[str]] | None:
    fps = _kick_near_dup_fps()
    found = fps.get(digest)
    if isinstance(found, tuple) and len(found) == 2:
        return found
    row = _kick_near_dup_rows().get(digest)
    if not isinstance(row, Mapping):
        return None
    tokens = near_dup_tokens(row)
    noted = (row_id(row) if "id" in row else "n", tokens)
    fps[digest] = noted
    return noted


def eval_partition_residue(key: str) -> int:
    """``int(sha256(key.encode('ascii')).hexdigest(), 16) % 10``.

    Shared by raw ``source.uuid`` and by a uuid-less row's lowercase
    64-hex ``content_uuid``. Do not use the content uuid hex as the int.
    """
    digest = hashlib.sha256(key.encode("ascii")).hexdigest()
    return int(digest, 16) % RESERVED_EVAL_PARTITION_N


def in_reserved_eval_partition(key: str) -> bool:
    return eval_partition_residue(key) in RESERVED_EVAL_PARTITION_RESIDUES


class ContentUuidError(Exception):
    def __init__(self, field: str, expected: object, actual: object, message: str) -> None:
        self.field = field
        self.expected = expected
        self.actual = actual
        super().__init__(message)


try:
    _NEAR_DUP_TOKENIZER_MODULE = _load_mill_near_dup_tokenizer()
except ContentUuidError as exc:
    if exc.actual != "missing":
        raise
    _NEAR_DUP_TOKENIZER_MODULE = None


def _non_finite_label(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    if value > 0:
        return "+Infinity"
    return "-Infinity"


def _has_surrogate(text: str) -> bool:
    return any(0xD800 <= ord(ch) <= 0xDFFF for ch in text)


def _fold_numpy_scalar(value: Any) -> Any:
    """Fold numpy scalars only when numpy is already imported. Never import it."""
    np = sys.modules.get("numpy")
    if np is None:
        return value
    bool_type = getattr(np, "bool_", None)
    if bool_type is not None and isinstance(value, bool_type):
        return bool(value)
    integer_type = getattr(np, "integer", None)
    if integer_type is not None and isinstance(value, integer_type):
        return int(value)
    floating_type = getattr(np, "floating", None)
    if floating_type is not None and isinstance(value, floating_type):
        return float(value)
    return value


def _raise_unsupported(value: Any, path: str) -> None:
    loc = path or "value"
    raise ContentUuidError(
        "content_uuid.unsupported_type",
        "JSON bool/int/float/str/null/list/object",
        type(value).__name__,
        f"unsupported type {type(value).__name__} in {loc}",
    )


def _canonicalize_value(value: Any, path: str = "", depth: int = 0) -> Any:
    """NFC strings; integer-valued floats → int; bools stay bools; refuse NaN/Inf.

    ``type(v) is bool`` is checked before int/float handling so ``True``
    does not collapse with ``1``.
    """
    if depth > MAX_DEPTH:
        loc = path or "value"
        raise ContentUuidError(
            "content_uuid.too_deep",
            f"depth <= {MAX_DEPTH}",
            depth,
            f"nesting deeper than {MAX_DEPTH} at {loc}",
        )
    value = _fold_numpy_scalar(value)
    if type(value) is bool:
        return value
    if type(value) is int:
        if value <= -_MAX_INT or value >= _MAX_INT:
            loc = path or "value"
            raise ContentUuidError(
                "content_uuid.int_too_large",
                f"at most {MAX_INT_DIGITS} digits",
                "oversized int",
                f"integer exceeds {MAX_INT_DIGITS} digits in {loc}",
            )
        return value
    if type(value) is float:
        if math.isnan(value) or math.isinf(value):
            label = _non_finite_label(value)
            loc = path or "value"
            raise ContentUuidError(
                "content_uuid.non_finite",
                "finite JSON number",
                label,
                f"non-finite number ({label}) in {loc}",
            )
        if abs(value) > _FLOAT_ABS_MAX:
            loc = path or "value"
            raise ContentUuidError(
                "content_uuid.float_precision",
                f"abs(float) <= 2**53",
                value,
                f"float exceeds 2**53 magnitude in {loc}",
            )
        if value.is_integer():
            return int(value)
        return value
    if value is None:
        return None
    if isinstance(value, str):
        if _has_surrogate(value):
            loc = path or "value"
            raise ContentUuidError(
                "content_uuid.invalid_unicode",
                "well-formed Unicode",
                "lone surrogate",
                f"lone surrogate in {loc}",
            )
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        payload: dict[str, Any] = {}
        for key, child in value.items():
            if type(key) is not str:
                loc = path or "value"
                raise ContentUuidError(
                    "content_uuid.unsupported_type",
                    "str object key",
                    type(key).__name__,
                    f"non-str key {type(key).__name__} in {loc}",
                )
            child_path = f"{path}.{key}" if path else key
            nfc_key = _canonicalize_value(key, child_path, depth + 1)
            if nfc_key in payload:
                raise ContentUuidError(
                    "content_uuid.key_collision",
                    "NFC-distinct keys",
                    nfc_key,
                    f"NFC key collision {nfc_key!r} in {path or 'object'}",
                )
            payload[nfc_key] = _canonicalize_value(child, child_path, depth + 1)
        return payload
    if isinstance(value, list):
        return [
            _canonicalize_value(child, f"{path}[{idx}]", depth + 1)
            for idx, child in enumerate(value)
        ]
    if isinstance(value, tuple):
        return [
            _canonicalize_value(child, f"{path}[{idx}]", depth + 1)
            for idx, child in enumerate(value)
        ]
    _raise_unsupported(value, path)
    raise AssertionError("unreachable")


def canonical_json_bytes(value: Any) -> bytes:
    """UTF-8 JSON: NFC strings, sorted keys, compact ``,`` / ``:`` separators.

    Integer-valued floats hash as ints (``1.0`` → ``1``, ``-0.0`` → ``0``).
    Bools stay ``true``/``false``. ``allow_nan=False`` so NaN/±Infinity refuse.
    """
    payload = _canonicalize_value(value)
    try:
        text = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except ValueError as exc:
        message = str(exc).lower()
        if "digit" in message:
            raise ContentUuidError(
                "content_uuid.int_too_large",
                f"at most {MAX_INT_DIGITS} digits",
                "oversized int",
                f"integer exceeds {MAX_INT_DIGITS} digits: {exc}",
            ) from exc
        raise ContentUuidError(
            "content_uuid.non_finite",
            "finite JSON number",
            "non-finite",
            f"non-finite number: {exc}",
        ) from exc
    except TypeError as exc:
        raise ContentUuidError(
            "content_uuid.unsupported_type",
            "JSON bool/int/float/str/null/list/object",
            type(payload).__name__,
            f"unsupported type: {exc}",
        ) from exc
    try:
        return unicodedata.normalize("NFC", text).encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContentUuidError(
            "content_uuid.invalid_unicode",
            "well-formed Unicode",
            "encode error",
            f"invalid unicode: {exc}",
        ) from exc


def canonical_content_object(row: Mapping[str, Any]) -> dict[str, Any]:
    """Top-level ``state`` + ``questions`` only.

    Nested ``id`` / ``timestamp`` keys inside those fields are kept.
    """
    if not isinstance(row, Mapping):
        raise ContentUuidError(
            "content_uuid.unsupported_type",
            "JSON object",
            type(row).__name__,
            f"content uuid row must be an object, not {type(row).__name__}",
        )
    if "state" not in row and "questions" not in row:
        raise ContentUuidError(
            "content_uuid.empty",
            "state and/or questions",
            "missing",
            f"empty content on {row_id(row)}",
        )
    payload: dict[str, Any] = {}
    for key in CONTENT_UUID_FIELDS:
        if key in row:
            payload[key] = row[key]
    return payload


def canonical_content_bytes(row: Mapping[str, Any]) -> bytes:
    blob = canonical_json_bytes(canonical_content_object(row))
    _note_kick_near_dup_row(hashlib.sha256(blob).hexdigest(), row)
    return blob


def content_uuid(row: Mapping[str, Any]) -> str:
    """sha256 hex of ``canonical_content_bytes(row)``."""
    if not isinstance(row, Mapping):
        raise ContentUuidError(
            "content_uuid.unsupported_type",
            "JSON object",
            type(row).__name__,
            f"content uuid row must be an object, not {type(row).__name__}",
        )
    try:
        digest = hashlib.sha256(canonical_content_bytes(row)).hexdigest()
    except ContentUuidError as exc:
        raise ContentUuidError(
            exc.field,
            exc.expected,
            exc.actual,
            f"{exc} on {row_id(row)}",
        ) from exc
    return digest


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
    uuid, even when it is 64 hex. A present but malformed
    ``source.content_uuid`` is a forgery.
    """
    source = row.get("source")
    if isinstance(source, Mapping):
        value = source.get("content_uuid")
        if is_sha256_hex(value):
            return str(value)
        if "content_uuid" in source:
            raise ContentUuidError(
                "content_uuid",
                "64 lowercase hex",
                value,
                f"forged content uuid on {row_id(row)}: claimed {value!r} is not 64 lowercase hex",
            )
        return None
    return None


def source_uuid_text(row: Mapping[str, Any]) -> str | None:
    """Raw ``source.uuid`` only. Whitespace is malformed. Top-level uuid is ignored."""
    source = row.get("source")
    if not isinstance(source, Mapping) or "uuid" not in source:
        return None
    value = source.get("uuid")
    if value is None:
        return None
    if type(value) is not str:
        return None
    if value != value.strip() or not value:
        return None
    return value


def verify_content_uuid(row: Mapping[str, Any]) -> str | None:
    """Return the recomputed digest when a claimed content uuid matches.

    A claimed 64-hex uuid that does not match is a forgery: callers refuse.
    A present malformed claim is also a forgery.
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


def find_content_uuid_collisions(
    train: Iterable[Mapping[str, Any]],
    holdout: Iterable[Mapping[str, Any]] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """Return (label_conflicts, within-split duplicates, cross-split messages).

    Never silently drops. Label conflict is always reported when labels
    differ. Same content across train and holdout with different labels is
    also ``cross-split leak``. Same labels spanning train and holdout are
    ``cross-split duplicate``, not ``duplicate``.
    """
    by_uuid: dict[str, list[tuple[str, bytes, str]]] = defaultdict(list)
    _index_collision_rows(train, "train", by_uuid)
    _index_collision_rows(holdout or (), "holdout", by_uuid)
    conflicts: list[str] = []
    duplicates: list[str] = []
    cross: list[str] = []
    for digest, members in by_uuid.items():
        if len(members) < 2:
            continue
        by_labels: dict[bytes, list[tuple[str, str]]] = defaultdict(list)
        for rid, labels, split in members:
            by_labels[labels].append((rid, split))
        splits = {split for _rid, _labels, split in members}
        if len(by_labels) > 1:
            groups = list(by_labels.values())
            left, right = groups[0][0][0], groups[1][0][0]
            conflicts.append(
                f"label conflict: rows {left} and {right} share content uuid "
                f"{digest} with different labels"
            )
            if "holdout" in splits and "train" in splits:
                train_id = next(rid for rid, _labels, split in members if split == "train")
                hold_id = next(rid for rid, _labels, split in members if split == "holdout")
                cross.append(
                    f"cross-split leak: rows {train_id} and {hold_id} share "
                    f"content uuid {digest} with different labels"
                )
            continue
        ids_and_splits = next(iter(by_labels.values()))
        if "train" in splits and "holdout" in splits:
            train_id = next(rid for rid, split in ids_and_splits if split == "train")
            hold_id = next(rid for rid, split in ids_and_splits if split == "holdout")
            cross.append(
                f"cross-split duplicate: rows {train_id} and {hold_id} share "
                f"content uuid {digest} with identical labels"
            )
            continue
        duplicates.append(
            f"duplicate: rows {ids_and_splits[0][0]} and {ids_and_splits[1][0]} "
            f"share content uuid {digest} with identical labels"
        )
    return conflicts, duplicates, cross


def _index_collision_rows(
    rows: Iterable[Mapping[str, Any]],
    split: str,
    by_uuid: dict[str, list[tuple[str, bytes, str]]],
) -> None:
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        digest = content_uuid(row)
        by_uuid[digest].append((row_id(row), canonical_labels_bytes(row), split))


def reject_duplicate_pairs(pairs: list[tuple[Any, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ContentUuidError(
                "content_uuid.duplicate_json_key",
                "unique keys",
                key,
                f"duplicate JSON key {key!r}",
            )
        payload[key] = value
    return payload


def _reject_json_constant(name: str) -> None:
    raise ContentUuidError(
        "content_uuid.non_finite",
        "finite JSON number",
        name,
        f"non-finite JSON constant {name}",
    )


def _json_nesting_depth(text: str) -> int:
    """Iterative brace/bracket depth, ignoring contents of JSON strings."""
    depth = 0
    max_depth = 0
    in_string = False
    escape = False
    for char in text:
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char in "{[":
            depth += 1
            if depth > max_depth:
                max_depth = depth
        elif char in "}]":
            depth -= 1
    return max_depth


def _raise_json_load_error(exc: BaseException) -> None:
    if isinstance(exc, RecursionError):
        raise ContentUuidError(
            "content_uuid.too_deep",
            f"depth <= {MAX_DEPTH}",
            "RecursionError",
            "JSON nesting exceeds depth cap",
        ) from exc
    if isinstance(exc, UnicodeDecodeError):
        raise ContentUuidError(
            "content_uuid.invalid_unicode",
            "utf-8",
            "invalid encoding",
            f"invalid UTF-8: {exc}",
        ) from exc
    if isinstance(exc, json.JSONDecodeError):
        raise ContentUuidError(
            "content_uuid",
            "JSON",
            "invalid JSON",
            f"invalid JSON: {exc}",
        ) from exc
    if isinstance(exc, ValueError):
        message = str(exc).lower()
        if "digit" in message:
            raise ContentUuidError(
                "content_uuid.int_too_large",
                f"at most {MAX_INT_DIGITS} digits",
                "oversized int",
                f"integer exceeds {MAX_INT_DIGITS} digits: {exc}",
            ) from exc
        raise ContentUuidError(
            "content_uuid",
            "JSON",
            type(exc).__name__,
            f"invalid JSON: {exc}",
        ) from exc
    raise ContentUuidError(
        "content_uuid",
        "JSON",
        type(exc).__name__,
        f"invalid JSON: {exc}",
    ) from exc


def decode_json_bytes(buf: bytes) -> str:
    try:
        text = buf.decode("utf-8")
    except UnicodeDecodeError as exc:
        _raise_json_load_error(exc)
        raise AssertionError("unreachable") from exc
    return text


def strict_json_loads(text: str) -> Any:
    if type(text) is not str:
        raise ContentUuidError(
            "content_uuid.unsupported_type",
            "str",
            type(text).__name__,
            f"JSON text must be str, not {type(text).__name__}",
        )
    if text.startswith("\ufeff"):
        raise ContentUuidError(
            "content_uuid",
            "JSON without BOM",
            "BOM",
            "UTF-8 BOM on JSON input",
        )
    depth = _json_nesting_depth(text)
    if depth > MAX_DEPTH:
        raise ContentUuidError(
            "content_uuid.too_deep",
            f"depth <= {MAX_DEPTH}",
            depth,
            f"JSON nesting deeper than {MAX_DEPTH}",
        )
    try:
        payload = json.loads(
            text,
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
        )
    except RecursionError as exc:
        _raise_json_load_error(exc)
    except json.JSONDecodeError as exc:
        _raise_json_load_error(exc)
    except ValueError as exc:
        _raise_json_load_error(exc)
        raise AssertionError("unreachable")
    _reject_oversized_ints(payload)
    return payload


def _reject_oversized_ints(value: Any, path: str = "") -> None:
    if type(value) is int:
        if value <= -_MAX_INT or value >= _MAX_INT:
            loc = path or "value"
            raise ContentUuidError(
                "content_uuid.int_too_large",
                f"at most {MAX_INT_DIGITS} digits",
                "oversized int",
                f"integer exceeds {MAX_INT_DIGITS} digits in {loc}",
            )
        return
    if isinstance(value, Mapping):
        for item_key, item_val in value.items():
            child_path = f"{path}.{item_key}" if path else str(item_key)
            _reject_oversized_ints(item_val, child_path)
        return
    if isinstance(value, list):
        for idx, child in enumerate(value):
            _reject_oversized_ints(child, f"{path}[{idx}]")


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
    parser.add_argument(
        "--holdout",
        type=str,
        default=None,
        help="holdout JSONL for --check (cross-split duplicate and leak)",
    )
    args = parser.parse_args(argv)
    try:
        if args.check:
            train = _load_jsonl(args.check)
            holdout = _load_jsonl(args.holdout) if args.holdout else []
            conflicts, duplicates, cross = find_content_uuid_collisions(train, holdout)
            for line in conflicts + cross + duplicates:
                print(line, file=sys.stderr)
            return 1 if conflicts or duplicates or cross else 0
        if args.jsonl:
            return _print_jsonl_uuids(args.jsonl)
        raw = decode_json_bytes(sys.stdin.buffer.read())
        if not raw.strip():
            print("content_uuid: expected a JSON object on stdin", file=sys.stderr)
            return 2
        row = strict_json_loads(raw)
        if not isinstance(row, dict):
            print("content_uuid: stdin must be a JSON object", file=sys.stderr)
            return 2
        print(content_uuid(row))
        return 0
    except ContentUuidError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (RecursionError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"content_uuid: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


def _iter_jsonl_lines(path: str) -> Iterable[tuple[int, str]]:
    try:
        with open(path, "rb") as handle:
            buf = handle.read()
    except OSError as exc:
        raise ContentUuidError(
            "content_uuid",
            "readable file",
            f"OSError:{getattr(exc, 'errno', None)}",
            f"cannot read {path}: {exc}",
        ) from exc
    text = decode_json_bytes(buf)
    for lineno, line in enumerate(text.splitlines(), 1):
        yield lineno, line


def _print_jsonl_uuids(path: str) -> int:
    failed = False
    try:
        lines = list(_iter_jsonl_lines(path))
    except ContentUuidError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    for lineno, line in lines:
        if not line.strip():
            continue
        try:
            obj = strict_json_loads(line)
        except ContentUuidError as exc:
            print(f"line {lineno}: {exc}")
            failed = True
            continue
        if not isinstance(obj, dict):
            print(f"line {lineno}: not a JSON object")
            failed = True
            continue
        try:
            print(content_uuid(obj))
        except ContentUuidError as exc:
            print(f"line {lineno}: {exc}")
            failed = True
    return 2 if failed else 0


def _load_jsonl(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lineno, line in _iter_jsonl_lines(path):
        if not line.strip():
            continue
        try:
            obj = strict_json_loads(line)
        except ContentUuidError as exc:
            raise ContentUuidError(
                exc.field,
                exc.expected,
                exc.actual,
                f"line {lineno}: {exc}",
            ) from exc
        if not isinstance(obj, dict):
            raise ContentUuidError(
                "content_uuid",
                "JSON object",
                type(obj).__name__,
                f"line {lineno}: not a JSON object",
            )
        rows.append(obj)
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
