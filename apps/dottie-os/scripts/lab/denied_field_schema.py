#!/usr/bin/env python3
"""Fail-closed schema check for fields the near-dup extractor never reads.

Denied fields can still reach the trainer (labels and questions are the
supervision targets), but only after this gate. Free text in any denied
field refuses the whole row. The trainer reads ``row_fields.READABLE_PATHS``
as raw UTF-8 bytes plus the denied fields that passed. Scan paths and the
deny list live only in ``row_fields``.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable, Mapping

import row_fields

DENIED_FIELDS: tuple[str, ...] = row_fields.DENY_KEYS
TRAINER_READ_PATHS: tuple[str, ...] = row_fields.READABLE_PATHS
SCHEMA_ENUM = frozenset(
    {
        "jev-decision-schema-1.0.0",
        "dottie-os-decision-schema-1.0.0",
    }
)
TIER_ENUM = frozenset({"L0", "L1", "L2", "L3"})
HF_ENUM = frozenset(
    {
        "openbmb/UltraData-SFT-Agent-2609",
        "openbmb/UltraData-Code",
        "openbmb/UltraData-Math",
    }
)
SPLIT_ENUM = frozenset({"train", "test", "validation", "holdout"})
CHOICE_ENUM = frozenset({"execute", "escalate", "halt", "other"})
DOMAIN_ENUM = frozenset(
    {"tool", "web", "algo", "math", "data", "ml", "system", "other"}
)
CONSENT_KEYS = frozenset({"capture_training", "public_hf", "champion"})
SOURCE_KEYS = frozenset(
    {
        "hf",
        "config",
        "split",
        "uuid",
        "row",
        "record_id",
        "content_uuid",
        "revision",
        "repo_name",
        "domain",
    }
)
LABEL_HEADS: dict[str, str] = {
    "action": "choice",
    "safe": "noul",
    "severity": "score",
    "domain": "choice",
    "quality": "score",
    "difficulty": "score",
    "solvable": "noul",
}
QUESTION_HEADS: dict[str, str] = dict(LABEL_HEADS)
QUESTION_INSTRUCTIONS: dict[str, frozenset[str]] = {
    "action": frozenset({"What should the pair-programmer do?"}),
    "safe": frozenset(
        {
            "P(safe to execute)",
            "P(safe / non-destructive snippet)",
        }
    ),
    "severity": frozenset({"Risk severity 0-1"}),
    "domain": frozenset({"Which code domain is this snippet?"}),
    "quality": frozenset({"Snippet quality 0-1 (normalized)"}),
    "difficulty": frozenset({"Problem difficulty 0-1 (length/symbol heuristic)"}),
    "solvable": frozenset({"P(looks like a solvable question)"}),
}
CRITERIA_LIST_ENUM = frozenset(
    {"negligible", "critical", "easy", "hard", "low", "high"}
)
CRITERIA_VALUE_MAX_WORDS = 8
CRITERIA_VALUE_MAX_CHARS = 80
SCORE_LO = 0.0
SCORE_HI = 1.0
ID_RE = re.compile(r"^[a-z0-9._:<>/-]{1,256}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9._:<>/-]{1,64}$")
SOURCE_CONFIG_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
SOURCE_UUID_RE = re.compile(r"^[A-Za-z0-9._:<>/-]{1,256}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
META_STR_KEYS = frozenset(
    {
        "kind",
        "category",
        "lang",
        "tool",
        "risk_hint",
        "hint",
        "tag",
        "flag",
        "uid",
        "agent_config",
        "halt_class",
        "provenance",
        "keep",
        "danger",
    }
)
META_BOOL_KEYS = frozenset({"m", "a", "b"})
META_NUM_KEYS = frozenset({"algo_rel_score"})
META_LIST_KEYS = frozenset({"keys"})
META_NULLABLE = frozenset({"flag"})
META_STR_MAX = 64
META_LIST_MAX = 8


class DeniedFieldError(Exception):
    """Row refused: a denied field failed the schema check."""

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        super().__init__(f"{field}: {reason}")


def _refuse(field: str, reason: str) -> None:
    raise DeniedFieldError(field, reason)


def canonical_id(value: object) -> str | None:
    """Item-8 canonicalize: NFKC, strip, refuse padded/NBSP/case variants."""
    if type(value) is not str:
        return None
    nfkc = unicodedata.normalize("NFKC", value)
    stripped = nfkc.strip()
    if not stripped:
        return None
    if nfkc != value or stripped != nfkc:
        return None
    folded = stripped.casefold()
    if folded != stripped:
        return None
    return folded


def require_id(field: str, value: object) -> str:
    folded = canonical_id(value)
    if folded is None:
        _refuse(field, "id is not canonical (NFKC/strip/casefold, no pad/NBSP)")
        raise AssertionError("unreachable")
    if ID_RE.fullmatch(folded) is None:
        _refuse(field, "id pattern mismatch")
        raise AssertionError("unreachable")
    return folded


def _require_mapping(field: str, value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _refuse(field, f"object required, got {type(value).__name__}")
        raise AssertionError("unreachable")
    return value


def _require_token(field: str, value: object, *, max_len: int = META_STR_MAX) -> str:
    if type(value) is not str:
        _refuse(field, f"str required, got {type(value).__name__}")
        raise AssertionError("unreachable")
    if len(value) > max_len:
        _refuse(field, f"str longer than {max_len}")
        raise AssertionError("unreachable")
    if TOKEN_RE.fullmatch(value) is None:
        _refuse(field, "free text is not allowed")
        raise AssertionError("unreachable")
    return value


def _check_schema(value: object) -> None:
    if type(value) is not str or value not in SCHEMA_ENUM:
        _refuse("schema", "enum mismatch")


def _check_tier(value: object) -> None:
    if type(value) is not str or value not in TIER_ENUM:
        _refuse("tier", "enum mismatch")


def _check_source(value: object) -> None:
    source = _require_mapping("source", value)
    extra = [key for key in source if key not in SOURCE_KEYS]
    if extra:
        _refuse("source", f"unknown key {extra[0]!r}")
    if "hf" in source and source.get("hf") not in HF_ENUM:
        _refuse("source.hf", "enum mismatch")
    if "split" in source and source.get("split") not in SPLIT_ENUM:
        _refuse("source.split", "enum mismatch")
    if "config" in source:
        config = source.get("config")
        if type(config) is not str or SOURCE_CONFIG_RE.fullmatch(config) is None:
            _refuse("source.config", "pattern mismatch")
    if "revision" in source:
        revision = source.get("revision")
        if type(revision) is not str or SOURCE_CONFIG_RE.fullmatch(revision) is None:
            _refuse("source.revision", "pattern mismatch")
    if "uuid" in source:
        uuid_text = source.get("uuid")
        if type(uuid_text) is not str or SOURCE_UUID_RE.fullmatch(uuid_text) is None:
            _refuse("source.uuid", "pattern mismatch")
    if "record_id" in source:
        require_id("source.record_id", source.get("record_id"))
    if "content_uuid" in source:
        digest = source.get("content_uuid")
        if type(digest) is not str or SHA256_RE.fullmatch(digest) is None:
            _refuse("source.content_uuid", "64-char lowercase hex required")
    if "row" in source:
        row_n = source.get("row")
        if type(row_n) is bool or type(row_n) is not int or row_n < 0:
            _refuse("source.row", "non-negative int required")
    if "repo_name" in source:
        _require_token("source.repo_name", source.get("repo_name"), max_len=256)
    if "domain" in source:
        _require_token("source.domain", source.get("domain"))


def _check_consent(value: object) -> None:
    consent = _require_mapping("consent", value)
    extra = [key for key in consent if key not in CONSENT_KEYS]
    if extra:
        _refuse("consent", f"unknown key {extra[0]!r}")
    for key in CONSENT_KEYS:
        if key not in consent:
            continue
        item = consent.get(key)
        if type(item) is not bool:
            _refuse(f"consent.{key}", "bool required")
    if consent.get("champion") is not False:
        _refuse("consent.champion", "must be false")


def _check_numeric(field: str, value: object, *, lo: float, hi: float) -> None:
    if type(value) is bool or type(value) not in (int, float):
        _refuse(field, "number required")
    if not (lo <= float(value) <= hi):
        _refuse(field, f"out of range [{lo}, {hi}]")


def _choice_enum(head: str) -> frozenset[str]:
    if head == "domain":
        return DOMAIN_ENUM
    return CHOICE_ENUM


def _check_labels(value: object) -> None:
    labels = _require_mapping("labels", value)
    extra = [key for key in labels if key not in LABEL_HEADS]
    if extra:
        _refuse("labels", f"unknown key {extra[0]!r}")
    if not labels:
        _refuse("labels", "empty")
    for head, payload in labels.items():
        expected = LABEL_HEADS[head]
        child = _require_mapping(f"labels.{head}", payload)
        extra_child = [key for key in child if key not in {"type", expected}]
        if extra_child:
            _refuse(f"labels.{head}", f"unknown key {extra_child[0]!r}")
        if child.get("type") != expected:
            _refuse(f"labels.{head}.type", f"{expected} required")
        if expected == "choice":
            choice = child.get("choice")
            if choice not in _choice_enum(head):
                _refuse(f"labels.{head}.choice", "enum mismatch")
            continue
        if expected == "score":
            _check_numeric(f"labels.{head}.score", child.get("score"), lo=SCORE_LO, hi=SCORE_HI)
            continue
        if expected == "noul":
            _check_numeric(f"labels.{head}.noul", child.get("noul"), lo=SCORE_LO, hi=SCORE_HI)
            continue
        _refuse(f"labels.{head}.type", "unhandled")


def _check_criteria(field: str, head: str, value: object) -> None:
    if isinstance(value, Mapping):
        extra = [key for key in value if key not in _choice_enum(head) and key not in DOMAIN_ENUM]
        if extra:
            _refuse(field, f"unknown key {extra[0]!r}")
        for key, item in value.items():
            if type(item) is not str:
                _refuse(f"{field}.{key}", "str required")
            if len(item) > CRITERIA_VALUE_MAX_CHARS:
                _refuse(f"{field}.{key}", "str longer than cap")
            words = item.split()
            if len(words) > CRITERIA_VALUE_MAX_WORDS:
                _refuse(f"{field}.{key}", "free text is not allowed")
            if any(ch in item for ch in "\n\r\t"):
                _refuse(f"{field}.{key}", "free text is not allowed")
        return
    if isinstance(value, list):
        if not value or not all(type(item) is str for item in value):
            _refuse(field, "list[str] required")
        extra = [item for item in value if item not in CRITERIA_LIST_ENUM]
        if extra:
            _refuse(field, f"unknown criterion {extra[0]!r}")
        return
    _refuse(field, "object or list[str] required")


def _check_questions(value: object) -> None:
    questions = _require_mapping("questions", value)
    extra = [key for key in questions if key not in QUESTION_HEADS]
    if extra:
        _refuse("questions", f"unknown key {extra[0]!r}")
    if not questions:
        _refuse("questions", "empty")
    for head, payload in questions.items():
        expected = QUESTION_HEADS[head]
        child = _require_mapping(f"questions.{head}", payload)
        extra_child = [key for key in child if key not in {"type", "instructions", "criteria"}]
        if extra_child:
            _refuse(f"questions.{head}", f"unknown key {extra_child[0]!r}")
        if child.get("type") != expected:
            _refuse(f"questions.{head}.type", f"{expected} required")
        if "instructions" in child:
            text = child.get("instructions")
            allowed = QUESTION_INSTRUCTIONS.get(head, frozenset())
            if type(text) is not str or text not in allowed:
                _refuse(f"questions.{head}.instructions", "not in the fixed question set")
        if "criteria" in child:
            _check_criteria(f"questions.{head}.criteria", head, child.get("criteria"))


def _check_meta(value: object) -> None:
    meta = _require_mapping("state.meta", value)
    allowed = META_STR_KEYS | META_BOOL_KEYS | META_NUM_KEYS | META_LIST_KEYS
    extra = [key for key in meta if key not in allowed]
    if extra:
        _refuse("state.meta", f"unknown key {extra[0]!r}")
    for key, item in meta.items():
        field = f"state.meta.{key}"
        if key in META_NULLABLE and item is None:
            continue
        if key in META_BOOL_KEYS:
            if type(item) is not bool:
                _refuse(field, "bool required")
            continue
        if key in META_NUM_KEYS:
            if type(item) is bool or type(item) not in (int, float):
                _refuse(field, "number required")
            continue
        if key in META_LIST_KEYS:
            if not isinstance(item, list) or len(item) > META_LIST_MAX:
                _refuse(field, "short list[str] required")
            for idx, child in enumerate(item):
                _require_token(f"{field}[{idx}]", child)
            continue
        _require_token(field, item, max_len=META_STR_MAX)


def _check_id_field(field: str) -> Callable[[object], None]:
    def check(value: object) -> None:
        require_id(field, value)

    return check


_DENIED_CHECKERS: dict[str, Callable[[object], None]] = {
    "schema": _check_schema,
    "id": _check_id_field("id"),
    "tier": _check_tier,
    "source": _check_source,
    "labels": _check_labels,
    "questions": _check_questions,
    "consent": _check_consent,
    "trajectory_id": _check_id_field("trajectory_id"),
    "record_id": _check_id_field("record_id"),
    "group_key": _check_id_field("group_key"),
    "state.meta": _check_meta,
}
if frozenset(_DENIED_CHECKERS) != frozenset(row_fields.DENY_KEYS):
    raise RuntimeError("denied-field checkers must match row_fields.DENY_KEYS")


def check_denied_fields(row: object) -> None:
    """Refuse the row if any denied field fails. Missing optional fields skip."""
    if not isinstance(row, Mapping):
        _refuse("row", f"object required, got {type(row).__name__}")
    if "state" in row and not isinstance(row.get("state"), Mapping):
        _refuse("state.meta", "state is not an object")
    for path in row_fields.DENY_KEYS:
        checker = _DENIED_CHECKERS.get(path)
        if checker is None:
            _refuse(path, "no schema checker")
            raise AssertionError("unreachable")
        value = row_fields.get_by_path(row, path)
        if value is row_fields.MISSING:
            continue
        checker(value)


def trainer_input_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Raw readable-field bytes plus denied fields that passed the schema check."""
    check_denied_fields(row)
    payload: dict[str, Any] = dict(row_fields.readable_raw_fields(row))
    for path in row_fields.DENY_KEYS:
        value = row_fields.get_by_path(row, path)
        if value is row_fields.MISSING:
            continue
        payload[path] = value
    return payload
