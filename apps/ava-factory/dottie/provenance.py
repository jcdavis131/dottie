"""Canonical lineage-v1 and checkpoint integrity helpers."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
import struct
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from dottie.license_policy import LicensePolicyError, validate_dataset_source

LINEAGE_SCHEMA = "dottie.lineage/v1"
HASH_CHUNK_BYTES = 1 << 20
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class IntegrityError(ValueError):
    """Lineage or checkpoint metadata is missing, malformed, or inconsistent."""


def _canonical_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise IntegrityError(f"facts are not canonical JSON: {exc}") from exc
    return text.encode("utf-8")


def hash_facts(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _update_raw(digest: Any, payload: bytes | memoryview) -> None:
    view = memoryview(payload).cast("B")
    for offset in range(0, len(view), HASH_CHUNK_BYTES):
        digest.update(view[offset : offset + HASH_CHUNK_BYTES])


def _update_header(digest: Any, tag: bytes, length: int) -> None:
    digest.update(tag)
    digest.update(struct.pack(">Q", length))


def _update_scalar(digest: Any, tag: bytes, payload: bytes) -> None:
    _update_header(digest, tag, len(payload))
    _update_raw(digest, payload)


def _mapping_key(value: object) -> bytes:
    if value is None:
        return b"n"
    if isinstance(value, bool):
        return b"b1" if value else b"b0"
    if isinstance(value, int):
        return b"i" + str(value).encode("ascii")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise IntegrityError("unsupported non-finite float")
        return b"f" + struct.pack(">d", value)
    if isinstance(value, str):
        return b"s" + value.encode("utf-8")
    if isinstance(value, bytes):
        return b"y" + value
    if isinstance(value, np.generic):
        return b"g" + str(value.dtype).encode("ascii") + _mapping_key(value.item())
    if isinstance(value, tuple):
        parts = [_mapping_key(item) for item in value]
        return b"u" + b"".join(
            struct.pack(">Q", len(part)) + part for part in parts
        )
    raise IntegrityError(f"unsupported mapping key: {type(value).__name__}")


def _tensor_chunks(tensor: Any, max_elements: int):
    if int(tensor.numel()) <= max_elements:
        yield tensor
        return
    shape = tuple(int(size) for size in tensor.shape)
    split_dim = next((dim for dim, size in enumerate(shape) if size > 1), None)
    if split_dim is None:
        yield tensor
        return
    trailing = math.prod(shape[split_dim + 1 :])
    width = max(1, max_elements // max(1, trailing))
    for start in range(0, shape[split_dim], width):
        piece = tensor.narrow(split_dim, start, min(width, shape[split_dim] - start))
        yield from _tensor_chunks(piece, max_elements)


def _update_typed(digest: Any, value: object) -> None:
    if value is None:
        _update_header(digest, b"n", 0)
        return
    if isinstance(value, bool):
        _update_scalar(digest, b"b", b"1" if value else b"0")
        return
    if isinstance(value, int):
        _update_scalar(digest, b"i", str(value).encode("ascii"))
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise IntegrityError("unsupported non-finite float")
        _update_scalar(digest, b"f", struct.pack(">d", value))
        return
    if isinstance(value, str):
        _update_scalar(digest, b"s", value.encode("utf-8"))
        return
    if isinstance(value, bytes):
        _update_header(digest, b"y", len(value))
        _update_raw(digest, value)
        return
    if dataclasses.is_dataclass(value):
        fields = dataclasses.fields(value)
        _update_header(digest, b"d", len(fields))
        for field in fields:
            _update_typed(digest, field.name)
            _update_typed(digest, getattr(value, field.name))
        return
    if isinstance(value, np.generic):
        _update_header(digest, b"g", 2)
        _update_typed(digest, str(value.dtype))
        _update_typed(digest, value.item())
        return
    if isinstance(value, np.ndarray):
        if value.dtype.hasobject:
            raise IntegrityError("unsupported object-dtype ndarray")
        _update_header(digest, b"a", 3)
        _update_typed(digest, value.dtype.str)
        _update_typed(digest, list(value.shape))
        _update_header(digest, b"r", int(value.nbytes))
        buffer_elements = max(1, HASH_CHUNK_BYTES // max(1, value.dtype.itemsize))
        iterator = np.nditer(
            value,
            flags=["external_loop", "buffered", "zerosize_ok"],
            op_flags=["readonly"],
            order="C",
            buffersize=buffer_elements,
        )
        for chunk in iterator:
            contiguous = np.ascontiguousarray(chunk)
            _update_raw(digest, memoryview(contiguous).cast("B"))
        return
    if all(
        hasattr(value, attr)
        for attr in (
            "detach",
            "cpu",
            "contiguous",
            "clone",
            "untyped_storage",
            "numel",
            "element_size",
            "narrow",
        )
    ):
        tensor = value.detach()
        _update_header(digest, b"t", 3)
        _update_typed(digest, str(tensor.dtype))
        _update_typed(digest, list(tensor.shape))
        raw_length = int(tensor.numel()) * int(tensor.element_size())
        _update_header(digest, b"r", raw_length)
        max_elements = max(1, HASH_CHUNK_BYTES // max(1, tensor.element_size()))
        for piece in _tensor_chunks(tensor, max_elements):
            cpu_piece = piece.cpu().contiguous().clone()
            _update_raw(digest, bytes(cpu_piece.untyped_storage()))
        return
    if isinstance(value, Mapping):
        keys = sorted(value, key=_mapping_key)
        _update_header(digest, b"m", len(keys))
        for key in keys:
            _update_typed(digest, key)
            _update_typed(digest, value[key])
        return
    if isinstance(value, list):
        _update_header(digest, b"l", len(value))
        for item in value:
            _update_typed(digest, item)
        return
    if isinstance(value, tuple):
        _update_header(digest, b"u", len(value))
        for item in value:
            _update_typed(digest, item)
        return
    raise IntegrityError(f"unsupported digest value: {type(value).__name__}")


def typed_digest(value: object) -> str:
    """Hash nested resume state with explicit type and boundary framing."""
    digest = hashlib.sha256()
    _update_typed(digest, value)
    return digest.hexdigest()


def _require_hash(value: object, field: str) -> str:
    if not isinstance(value, str) or _HEX64_RE.fullmatch(value) is None:
        raise IntegrityError(f"{field} must be a lowercase 64-hex sha256")
    return value


def _plain_facts(value: object) -> object:
    if dataclasses.is_dataclass(value):
        return _plain_facts(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _plain_facts(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_facts(item) for item in value]
    return value


def _source_claim_eligible(row: Mapping[str, object]) -> bool:
    if row.get("source_kind") != "hf":
        return False
    try:
        validate_dataset_source(
            gated=row.get("source_gated"),
            license_id=row.get("source_license"),
            revision=row.get("source_revision"),
        )
    except LicensePolicyError:
        return False
    return True


def create_lineage(
    *,
    tokenizer_sha256: str,
    config: object,
    curriculum: object,
    shards: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build deterministic lineage from facts observed by the training run."""
    _require_hash(tokenizer_sha256, "tokenizer_sha256")
    if config is None:
        raise IntegrityError("config facts are unavailable")
    if curriculum is None:
        raise IntegrityError("curriculum facts are unavailable")
    if not shards:
        raise IntegrityError("lineage requires at least one observed shard")
    normalized_shards: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in shards:
        shard_id = row.get("id")
        if not isinstance(shard_id, str) or not shard_id:
            raise IntegrityError("manifest shard id must be a non-empty string")
        if shard_id in seen:
            raise IntegrityError(f"duplicate manifest shard id {shard_id!r}")
        seen.add(shard_id)
        revision = row.get("source_revision")
        if not isinstance(revision, str) or not revision:
            raise IntegrityError(f"manifest shard {shard_id} source_revision missing")
        source_kind = row.get("source_kind")
        if not isinstance(source_kind, str) or not source_kind:
            raise IntegrityError(f"manifest shard {shard_id} source_kind missing")
        normalized_shards.append({
            "id": shard_id,
            "packed_bin_sha256": _require_hash(
                row.get("packed_bin_sha256"),
                f"manifest shard {shard_id} packed_bin_sha256",
            ),
            "packed_idx_sha256": _require_hash(
                row.get("packed_idx_sha256"),
                f"manifest shard {shard_id} packed_idx_sha256",
            ),
            "source_kind": source_kind,
            "source_license": row.get("source_license"),
            "source_gated": row.get("source_gated"),
            "source_revision": revision,
            "source_entry_sha256": _require_hash(
                row.get("source_entry_sha256"),
                f"manifest shard {shard_id} source_entry_sha256",
            ),
        })
    normalized_shards.sort(key=lambda row: row["id"])
    body: dict[str, Any] = {
        "schema": LINEAGE_SCHEMA,
        "tokenizer_sha256": tokenizer_sha256,
        "config": _plain_facts(config),
        "curriculum": _plain_facts(curriculum),
        "shards": normalized_shards,
        "claim_eligible": all(
            _source_claim_eligible(row) for row in normalized_shards
        ),
    }
    body["digest"] = hash_facts(body)
    return body


def validate_lineage(
    lineage: object, *, require_claim_eligible: bool = True
) -> str:
    if not isinstance(lineage, dict):
        raise IntegrityError("checkpoint lineage must be an object")
    if lineage.get("schema") != LINEAGE_SCHEMA:
        raise IntegrityError(f"checkpoint lineage schema must be {LINEAGE_SCHEMA}")
    _require_hash(lineage.get("tokenizer_sha256"), "tokenizer_sha256")
    if lineage.get("config") is None:
        raise IntegrityError("checkpoint lineage config facts are unavailable")
    if lineage.get("curriculum") is None:
        raise IntegrityError("checkpoint lineage curriculum facts are unavailable")
    supplied = _require_hash(lineage.get("digest"), "lineage digest")
    shards = lineage.get("shards")
    if not isinstance(shards, list):
        raise IntegrityError("lineage shards must be a list")
    if not shards:
        raise IntegrityError("lineage requires at least one observed shard")
    ids: list[str] = []
    computed_claim_eligible = True
    for row in shards:
        if not isinstance(row, dict):
            raise IntegrityError("lineage shard entries must be objects")
        shard_id = row.get("id")
        if not isinstance(shard_id, str) or not shard_id:
            raise IntegrityError("lineage shard id must be a non-empty string")
        ids.append(shard_id)
        revision = row.get("source_revision")
        if not isinstance(revision, str) or not revision:
            raise IntegrityError(f"lineage shard {shard_id} source_revision missing")
        source_kind = row.get("source_kind")
        if not isinstance(source_kind, str) or not source_kind:
            raise IntegrityError(f"lineage shard {shard_id} source_kind missing")
        computed_claim_eligible &= _source_claim_eligible(row)
        for field in (
            "packed_bin_sha256",
            "packed_idx_sha256",
            "source_entry_sha256",
        ):
            _require_hash(row.get(field), f"lineage shard {shard_id} {field}")
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        raise IntegrityError("lineage shard ids must be unique and sorted")
    if lineage.get("claim_eligible") is not computed_claim_eligible:
        raise IntegrityError("lineage claim eligibility does not match source policy")
    unsigned = dict(lineage)
    unsigned.pop("digest", None)
    actual = hash_facts(unsigned)
    if supplied != actual:
        raise IntegrityError(
            f"lineage digest mismatch: recorded {supplied}, computed {actual}"
        )
    if require_claim_eligible and not computed_claim_eligible:
        raise IntegrityError("lineage is not claim eligible")
    return actual


def checkpoint_metadata(
    lineage: dict[str, Any],
    *,
    asserted_parent: Mapping[str, object] | None,
    content: Mapping[str, object],
) -> dict[str, Any]:
    lineage_digest = validate_lineage(lineage, require_claim_eligible=False)
    parent_facts = dict(asserted_parent) if asserted_parent is not None else None
    if parent_facts is not None:
        for key, value in parent_facts.items():
            if key.endswith("digest") or key.endswith("sha256"):
                _require_hash(value, f"asserted_parent {key}")
    content_digest = typed_digest(content)
    digest = typed_digest(
        {
            "schema": "dottie.checkpoint/v1",
            "lineage_digest": lineage_digest,
            "asserted_parent": parent_facts,
            "content_digest": content_digest,
        }
    )
    return {
        "lineage": lineage,
        "digest": digest,
        "asserted_parent": parent_facts,
        "content_digest": content_digest,
    }


def validate_checkpoint(
    blob: object,
    *,
    expected_tokenizer_sha256: str | None = None,
    expected_config: object | None = None,
    require_claim_eligible: bool = True,
) -> str:
    """Validate integrity metadata before a consumer uses model weights."""
    if not isinstance(blob, dict):
        raise IntegrityError("checkpoint must be an object with integrity metadata")
    lineage = blob.get("lineage")
    lineage_digest = validate_lineage(
        lineage, require_claim_eligible=require_claim_eligible
    )
    asserted_parent = blob.get("asserted_parent")
    if asserted_parent is not None and not isinstance(asserted_parent, Mapping):
        raise IntegrityError("asserted_parent must be an object or null")
    if asserted_parent is not None:
        for key, value in asserted_parent.items():
            if key.endswith("digest") or key.endswith("sha256"):
                _require_hash(value, f"asserted_parent {key}")
    recorded_content_digest = _require_hash(
        blob.get("content_digest"), "checkpoint content_digest"
    )
    metadata_fields = {"lineage", "digest", "asserted_parent", "content_digest"}
    content = {key: value for key, value in blob.items() if key not in metadata_fields}
    if typed_digest(content) != recorded_content_digest:
        raise IntegrityError("checkpoint content digest mismatch")
    digest = typed_digest(
        {
            "schema": "dottie.checkpoint/v1",
            "lineage_digest": lineage_digest,
            "asserted_parent": asserted_parent,
            "content_digest": recorded_content_digest,
        }
    )
    if blob.get("digest") != digest:
        raise IntegrityError("checkpoint digest mismatch")
    if expected_tokenizer_sha256 is not None:
        _require_hash(expected_tokenizer_sha256, "expected tokenizer sha256")
        if lineage["tokenizer_sha256"] != expected_tokenizer_sha256:
            raise IntegrityError("checkpoint tokenizer hash mismatch")
    if expected_config is not None and lineage.get("config") != _plain_facts(
        expected_config
    ):
        raise IntegrityError("checkpoint config mismatch")
    return digest


def lineage_from_training(*, cfg: object, manifest: Any, shard_ids: list[str]) -> dict:
    tokenizer_sha = manifest.tokenizer_sha()
    if tokenizer_sha is None:
        raise IntegrityError("manifest has no frozen tokenizer hash")
    phases = getattr(cfg, "phases", None)
    if phases is None:
        raise IntegrityError("config has no curriculum phases")
    return create_lineage(
        tokenizer_sha256=tokenizer_sha,
        config=_plain_facts(cfg),
        curriculum=_plain_facts(phases),
        shards=manifest.lineage_shards(shard_ids),
    )


def integrity_report(*, status: str, errors: list[str]) -> dict[str, Any]:
    return {
        "status": status,
        "claim_eligible": status == "clean" and not errors,
        "errors": list(errors),
    }


def exit_code(report: dict[str, Any]) -> int:
    """Classify a report recursively: integrity error > measured failure > clean."""
    if not isinstance(report, dict) or report.get("claim_eligible") is not True:
        return 2

    integrity_error = False
    measured_failure = False

    def visit(node: object) -> None:
        nonlocal integrity_error, measured_failure
        if isinstance(node, dict):
            if "claim_eligible" in node and node["claim_eligible"] is not True:
                integrity_error = True
            if node.get("error"):
                integrity_error = True
            if "errors" in node:
                errors = node["errors"]
                if not isinstance(errors, list) or bool(errors):
                    integrity_error = True
            if node.get("pass") is False:
                measured_failure = True
            if "measured_failures" in node:
                failures = node["measured_failures"]
                if (
                    isinstance(failures, bool)
                    or not isinstance(failures, int)
                    or failures < 0
                ):
                    integrity_error = True
                elif failures > 0:
                    measured_failure = True
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(report)
    if integrity_error:
        return 2
    return 1 if measured_failure else 0


__all__ = [
    "HASH_CHUNK_BYTES",
    "LINEAGE_SCHEMA",
    "IntegrityError",
    "checkpoint_metadata",
    "create_lineage",
    "exit_code",
    "hash_facts",
    "integrity_report",
    "lineage_from_training",
    "sha256_file",
    "typed_digest",
    "validate_checkpoint",
    "validate_lineage",
]
