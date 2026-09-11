"""Schema versioning and compatibility (spec §37A "Compatibility").

Readers accept known minor additions but reject unknown major versions. Writers
emit exactly one active version per record type. A record's ``schema`` field is
``<name>-<major>.<minor>.<patch>``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from dottie_loop.errors import InvalidInputError
from dottie_loop.hashing import digest, new_id, now_iso

if TYPE_CHECKING:
    from collections.abc import Callable

#: The one active version per record type (writers emit only these).
ACTIVE_SCHEMAS: dict[str, str] = {
    "goal-envelope": "goal-envelope-1.0.0",
    "plan-graph": "plan-graph-1.0.0",
    "run-event": "run-event-1.0.0",
    "checkpoint": "checkpoint-1.0.0",
    "approval-record": "approval-record-1.0.0",
    "pair-session": "pair-session-1.0.0",
    "pair-reward": "pair-reward-1.0.0",
    "dataset-manifest": "dataset-manifest-1.0.0",
    "train-run": "train-run-1.0.0",
    "eval-bundle": "eval-bundle-1.0.0",
    "release-record": "release-record-1.0.0",
    "loop-decision": "loop-decision-1.0.0",
    "incident-record": "incident-record-1.0.0",
    "deletion-receipt": "deletion-receipt-1.0.0",
    "forge-job": "forge-job-1.0.0",
    "forge-runner": "forge-runner-1.0.0",
    "forge-result": "forge-result-1.0.0",
    "bench-report": "bench-report-1.0.0",
    "scout-result": "scout-result-1.0.0",
}

_SCHEMA_RE = re.compile(r"^([a-z][a-z0-9-]*[a-z0-9])-(\d+)\.(\d+)\.(\d+)$")


def parse_schema(value: object) -> tuple[str, int, int, int]:
    """Split ``name-M.m.p`` into its parts or raise :class:`InvalidInputError`."""
    if not isinstance(value, str):
        raise InvalidInputError("schema must be a string", field="schema")
    m = _SCHEMA_RE.match(value)
    if not m:
        raise InvalidInputError("schema must look like <name>-<major>.<minor>.<patch>", "schema")
    return m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))


def check_compatible(record_schema: object, record_type: str) -> tuple[str, int, int, int]:
    """Accept the active major (any minor/patch); reject other names or majors.

    Returns the parsed tuple so callers can branch on minor if they need to.
    """
    active = ACTIVE_SCHEMAS.get(record_type)
    if active is None:
        raise InvalidInputError(f"unknown record type {record_type!r}", field="schema")
    name, major, minor, patch = parse_schema(record_schema)
    a_name, a_major, _a_minor, _a_patch = parse_schema(active)
    if name != a_name:
        raise InvalidInputError(
            f"schema name {name!r} is not {a_name!r}", field="schema", expected=active
        )
    if major != a_major:
        raise InvalidInputError(
            f"unknown major version {major} for {name} (active {a_major})",
            field="schema",
            expected=active,
        )
    return name, major, minor, patch


def active(record_type: str) -> str:
    try:
        return ACTIVE_SCHEMAS[record_type]
    except KeyError as e:
        raise InvalidInputError(f"unknown record type {record_type!r}", field="schema") from e


def migrate(records: list[dict[str, Any]], *, record_type: str, target: str, migrator: Callable[[dict[str, Any]], dict[str, Any]], id_field: str) -> dict[str, Any]:
    """§37A migrations: deterministic, NEW records (inputs untouched), source ids preserved,
    plus a migration manifest with before/after hashes and counts.

    ``migrator`` maps one old record to its new shape (without ``schema``); the target
    schema is stamped here so a migrator cannot emit a version that is not the target.
    """
    t_name, *_ = parse_schema(target)
    a_name, *_ = parse_schema(active(record_type))
    if t_name != a_name:
        raise InvalidInputError(f"target {target!r} is not a {a_name} schema", field="target")
    out: list[dict[str, Any]] = []
    before: list[str] = []
    after: list[str] = []
    for rec in records:
        if id_field not in rec:
            raise InvalidInputError(f"record lacks {id_field!r}; ids must be preserved", field=id_field)
        new = migrator(dict(rec))
        if new.get(id_field) != rec[id_field]:
            raise InvalidInputError(f"migration changed {id_field!r} for {rec[id_field]!r}", field=id_field)
        new["schema"] = target
        new["migrated_from"] = rec.get("schema")
        out.append(new)
        before.append(digest(rec))
        after.append(digest(new))
    manifest = {
        "migration_id": new_id("mig_"),
        "record_type": record_type,
        "from_schemas": sorted({str(r.get("schema")) for r in records}),
        "to_schema": target,
        "counts": {"in": len(records), "out": len(out)},
        "before_hash": digest(before),
        "after_hash": digest(after),
        "deterministic": True,
        "at": now_iso(),
    }
    return {"records": out, "manifest": manifest}
