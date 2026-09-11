"""Operational state: append-only timeline and the checkpoint transaction (spec §14, §37A).

Checkpoints are the durable truth of a run. The timeline is append-only JSONL with
the seven mandatory fields on EVERY event, including zero-change runs (RT-10);
summaries are derived views and are never written into the log. The checkpoint
transaction writes outputs to a temp path, hashes them, verifies the
postcondition, appends metadata with fsync, then atomically updates the run index
and only then emits the event that unlocks dependents (§10 "Commit ordering").
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dottie_loop.errors import BlockedError, InvalidInputError, VerificationFailedError
from dottie_loop.hashing import digest, file_sha256, new_id, now_iso
from dottie_loop.schema import active, check_compatible

if TYPE_CHECKING:
    from collections.abc import Callable

#: The seven-field minimum (§14). Names match the spec's RunEvent (§37A) exactly.
SEVEN_FIELDS = ("nodeId", "agentId", "attempt", "latency_ms", "tokens_est", "status", "errorClass")
STATUSES = frozenset({"queued", "running", "blocked", "failed", "verified", "completed", "cancelled"})
TOKEN_METHODS = frozenset({"provider_reported", "tokenizer_count", "heuristic_estimate", "measured_zero"})


@dataclass
class RunEvent:
    goal_id: str
    run_id: str
    nodeId: str  # noqa: N815 - spec field name
    agentId: str  # noqa: N815 - spec field name
    attempt: int
    status: str
    latency_ms: int
    tokens_est: int
    token_method: str = "heuristic_estimate"  # noqa: S105 - spec field, not a secret
    errorClass: str | None = None  # noqa: N815 - spec field name
    plan_version: int = 1
    input_hash: str | None = None
    output_hash: str | None = None
    tool_receipts: list[dict[str, Any]] = field(default_factory=list)
    parent_event: str | None = None
    correlation_id: str | None = None
    event_id: str = field(default_factory=lambda: new_id("evt_"))
    at: str = field(default_factory=now_iso)
    schema: str = field(default_factory=lambda: active("run-event"))

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def validate_event(record: dict[str, Any]) -> None:
    """Schema gate on every run path (RT-10). Raises InvalidInputError."""
    check_compatible(record.get("schema", active("run-event")), "run-event")
    missing = [f for f in SEVEN_FIELDS if f not in record]
    if missing:
        raise InvalidInputError(f"run event missing fields: {missing}", field="event")
    if record["status"] not in STATUSES:
        raise InvalidInputError(f"unknown status {record['status']!r}", field="status")
    if not isinstance(record["attempt"], int) or record["attempt"] < 1:
        raise InvalidInputError("attempt must be a positive integer", field="attempt")
    for k in ("latency_ms", "tokens_est"):
        v = record[k]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise InvalidInputError(f"{k} must be a non-negative integer", field=k)
    if record.get("token_method", "heuristic_estimate") not in TOKEN_METHODS:
        raise InvalidInputError("token_method must identify the method", "token_method")
    ec = record.get("errorClass")
    if ec is not None and not isinstance(ec, str):
        raise InvalidInputError("errorClass must be a string or null", field="errorClass")
    if record["status"] == "failed" and not ec:
        raise InvalidInputError("a failed event must carry an errorClass", "errorClass")


def _append_fsync(path: Path, record: dict[str, Any]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.seek(0, os.SEEK_END)
        offset = f.tell()
        f.write(json.dumps(record, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())
    return offset


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # torn tail; a writer is mid-append
    return out


class RunStore:
    """Per-run directory: ``timeline.jsonl``, ``checkpoints.jsonl``, ``index.json``, ``objects/``."""

    def __init__(self, base: Path, run_id: str) -> None:
        self.base = Path(base)
        self.run_id = run_id
        self.dir = self.base / run_id
        self.timeline_path = self.dir / "timeline.jsonl"
        self.checkpoints_path = self.dir / "checkpoints.jsonl"
        self.index_path = self.dir / "index.json"
        self.objects = self.dir / "objects"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.objects.mkdir(exist_ok=True)

    # -- timeline --
    def append(self, event: RunEvent | dict[str, Any]) -> dict[str, Any]:
        record = event.to_dict() if isinstance(event, RunEvent) else dict(event)
        validate_event(record)
        offset = _append_fsync(self.timeline_path, record)
        return {"ok": True, "event_id": record.get("event_id"), "offset": offset}

    def events(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.timeline_path)

    def summary(self) -> dict[str, Any]:
        """Derived view, never written into the log."""
        evs = self.events()
        by_node: dict[str, dict[str, Any]] = {}
        for e in evs:
            by_node[e["nodeId"]] = {"status": e["status"], "attempt": e["attempt"]}
        return {
            "run_id": self.run_id,
            "events": len(evs),
            "nodes": by_node,
            "latency_ms": sum(e["latency_ms"] for e in evs),
            "tokens_est": sum(e["tokens_est"] for e in evs),
        }

    # -- checkpoint transaction (§14) --
    def commit_checkpoint(
        self,
        *,
        node_id: str,
        attempt: int,
        plan_version: int,
        output: bytes,
        upstream_hashes: dict[str, str],
        verifier: Callable[[bytes], dict[str, Any]],
        capability_digest: str,
        versions: dict[str, str] | None = None,
        agent_id: str = "dottie",
        goal_id: str = "",
        latency_ms: int = 0,
        tokens_est: int = 0,
        token_method: str = "measured_zero",  # noqa: S107 - spec field, not a secret
    ) -> dict[str, Any]:
        """Steps 1-6 of the checkpoint transaction. Nothing is visible until step 5."""
        # 1. temp / content-addressed write
        tmp = self.objects / f".tmp-{new_id()}"
        tmp.write_bytes(output)
        # 2. hash + byte count
        content_hash = file_sha256(tmp)
        final = self.objects / content_hash
        tmp.replace(final)
        # 3. postcondition verification
        verdict = verifier(output)
        if not verdict.get("pass"):
            self.append(
                RunEvent(
                    goal_id=goal_id,
                    run_id=self.run_id,
                    nodeId=node_id,
                    agentId=agent_id,
                    attempt=attempt,
                    status="failed",
                    latency_ms=latency_ms,
                    tokens_est=tokens_est,
                    token_method=token_method,
                    errorClass="verification_failed",
                    plan_version=plan_version,
                    output_hash=content_hash,
                )
            )
            raise VerificationFailedError(
                f"postcondition failed for {node_id}", verdict=verdict, output_hash=content_hash
            )
        # 4. append checkpoint metadata + fsync
        checkpoint = {
            "schema": active("checkpoint"),
            "checkpoint_id": new_id("ckpt_"),
            "run_id": self.run_id,
            "plan_version": plan_version,
            "node_id": node_id,
            "attempt": attempt,
            "state_snapshot_version": 1,
            "upstream_hashes": dict(sorted(upstream_hashes.items())),
            "output_ref": str(final.relative_to(self.dir)),
            "output_hash": content_hash,
            "bytes": len(output),
            "verifier_result": verdict,
            "capability_digest": capability_digest,
            "versions": versions or {},
            "completed_at": now_iso(),
        }
        checkpoint["content_hash"] = digest({k: v for k, v in checkpoint.items() if k != "content_hash"})
        _append_fsync(self.checkpoints_path, checkpoint)
        # 5. atomic index update
        index = self._load_index()
        index["nodes"][node_id] = checkpoint["checkpoint_id"]
        index["plan_version"] = plan_version
        self._save_index_atomic(index)
        # 6. timeline event (unlocks dependents)
        self.append(
            RunEvent(
                goal_id=goal_id,
                run_id=self.run_id,
                nodeId=node_id,
                agentId=agent_id,
                attempt=attempt,
                status="completed",
                latency_ms=latency_ms,
                tokens_est=tokens_est,
                token_method=token_method,
                errorClass=None,
                plan_version=plan_version,
                input_hash=digest(upstream_hashes),
                output_hash=content_hash,
            )
        )
        return checkpoint

    def _load_index(self) -> dict[str, Any]:
        if self.index_path.exists():
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        return {"run_id": self.run_id, "plan_version": 1, "nodes": {}}

    def _save_index_atomic(self, index: dict[str, Any]) -> None:
        tmp = self.index_path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(index, f, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(self.index_path)

    def checkpoints(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.checkpoints_path)

    # -- resume (§14) --
    def resume_state(
        self,
        current_upstream_hashes: dict[str, dict[str, str]] | None = None,
        current_policy_digest: str | None = None,
    ) -> dict[str, Any]:
        """Which nodes are reusable? Verifies every referenced object's hash.

        A corrupted or missing checkpoint BLOCKS resume (raises BlockedError);
        the system never guesses a previous output.
        """
        index = self._load_index()
        by_id = {c["checkpoint_id"]: c for c in self.checkpoints()}
        reusable: list[str] = []
        stale: list[str] = []
        for node_id, ckpt_id in index["nodes"].items():
            ckpt = by_id.get(ckpt_id)
            if ckpt is None:
                raise BlockedError(f"checkpoint {ckpt_id} for {node_id} is missing", "checkpoint")
            obj = self.dir / ckpt["output_ref"]
            if not obj.exists() or file_sha256(obj) != ckpt["output_hash"]:
                raise BlockedError(f"checkpoint object for {node_id} is corrupted", "checkpoint")
            body = {k: v for k, v in ckpt.items() if k != "content_hash"}
            if digest(body) != ckpt["content_hash"]:
                raise BlockedError(f"checkpoint metadata for {node_id} is corrupted", "checkpoint")
            expected = (current_upstream_hashes or {}).get(node_id)
            if expected is not None and expected != ckpt["upstream_hashes"]:
                stale.append(node_id)
                continue
            if current_policy_digest is not None and current_policy_digest != ckpt["capability_digest"]:
                stale.append(node_id)
                continue
            reusable.append(node_id)
        return {"run_id": self.run_id, "reusable": reusable, "stale": stale, "plan_version": index["plan_version"]}
