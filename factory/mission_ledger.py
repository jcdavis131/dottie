"""Transactional SQLite ledger for auditable model missions."""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from factory.config import FactoryError
from factory.mission_process import terminate_process_tree
from factory.mission_schema import LEGAL_TRANSITIONS, Mission, MissionState

if TYPE_CHECKING:
    from collections.abc import Iterator


def _json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class Ledger:
    """Mutable local state with serialized claims and append-only evidence."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS missions (
                    id TEXT PRIMARY KEY,
                    mission_json TEXT NOT NULL,
                    mission_hash TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    state TEXT NOT NULL,
                    active_attempt_id TEXT,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL REFERENCES missions(id),
                    ordinal INTEGER NOT NULL,
                    parent_attempt_id TEXT REFERENCES attempts(id),
                    created_at REAL NOT NULL,
                    UNIQUE(mission_id, ordinal)
                );
                CREATE TABLE IF NOT EXISTS attempt_runtime (
                    attempt_id TEXT PRIMARY KEY REFERENCES attempts(id),
                    scratch_path TEXT,
                    process_pid INTEGER,
                    process_identity TEXT,
                    train_pid INTEGER,
                    train_identity TEXT,
                    eval_pid INTEGER,
                    eval_identity TEXT,
                    train_exit_code INTEGER,
                    train_seconds REAL,
                    eval_exit_code INTEGER,
                    eval_seconds REAL
                );
                CREATE TABLE IF NOT EXISTS transitions (
                    id INTEGER PRIMARY KEY,
                    mission_id TEXT NOT NULL REFERENCES missions(id),
                    attempt_id TEXT REFERENCES attempts(id),
                    from_state TEXT,
                    to_state TEXT NOT NULL,
                    reason TEXT,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS provenance (
                    attempt_id TEXT PRIMARY KEY REFERENCES attempts(id),
                    document_json TEXT NOT NULL,
                    document_hash TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    attempt_id TEXT NOT NULL REFERENCES attempts(id),
                    role TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    provenance_hash TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(attempt_id, role)
                );
                CREATE TABLE IF NOT EXISTS evaluation_claims (
                    attempt_id TEXT PRIMARY KEY REFERENCES attempts(id),
                    claimed_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS promotion_transactions (
                    id TEXT PRIMARY KEY,
                    mission_id TEXT NOT NULL REFERENCES missions(id),
                    attempt_id TEXT NOT NULL REFERENCES attempts(id),
                    provenance_hash TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    shipper TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    completed_at REAL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_pending_promotion
                ON promotion_transactions(mission_id) WHERE state='pending';
                CREATE TABLE IF NOT EXISTS promotion_outputs (
                    transaction_id TEXT NOT NULL REFERENCES promotion_transactions(id),
                    ordinal INTEGER NOT NULL,
                    source_path TEXT NOT NULL,
                    destination_path TEXT NOT NULL,
                    stage_path TEXT NOT NULL,
                    expected_hash TEXT NOT NULL,
                    PRIMARY KEY(transaction_id, ordinal)
                );
                """
            )
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(attempt_runtime)")
            }
            if "process_pid" not in columns:
                connection.execute(
                    "ALTER TABLE attempt_runtime ADD COLUMN process_pid INTEGER"
                )
            if "process_identity" not in columns:
                connection.execute(
                    "ALTER TABLE attempt_runtime ADD COLUMN process_identity TEXT"
                )
            for name, kind in (
                ("train_pid", "INTEGER"),
                ("train_identity", "TEXT"),
                ("eval_pid", "INTEGER"),
                ("eval_identity", "TEXT"),
            ):
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE attempt_runtime ADD COLUMN {name} {kind}"
                    )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @contextlib.contextmanager
    def _immediate(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def propose(self, mission: Mission, source_path: Path) -> None:
        document = mission.canonical()
        text = _json_text(document)
        digest = hashlib.sha256(text.encode()).hexdigest()
        with self._immediate() as connection:
            try:
                connection.execute(
                    "INSERT INTO missions VALUES (?, ?, ?, ?, ?, NULL, ?)",
                    (
                        mission.id,
                        text,
                        digest,
                        str(Path(source_path).resolve()),
                        MissionState.PROPOSED.value,
                        time.time(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise FactoryError(f"mission {mission.id!r} already exists") from exc
            connection.execute(
                "INSERT INTO transitions "
                "(mission_id, from_state, to_state, reason, created_at) "
                "VALUES (?, NULL, ?, ?, ?)",
                (mission.id, MissionState.PROPOSED.value, "proposed", time.time()),
            )

    def _row(self, connection: sqlite3.Connection, mission_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM missions WHERE id=?", (mission_id,)
        ).fetchone()
        if row is None:
            raise FactoryError(f"unknown mission {mission_id!r}")
        return row

    def transition(
        self,
        mission_id: str,
        target: MissionState | str,
        *,
        reason: str = "",
        attempt_id: str | None = None,
    ) -> None:
        try:
            target_state = MissionState(target)
        except (TypeError, ValueError) as exc:
            raise FactoryError(f"unknown transition target {target!r}") from exc
        with self._immediate() as connection:
            row = self._row(connection, mission_id)
            current = MissionState(row["state"])
            if target_state not in LEGAL_TRANSITIONS[current]:
                raise FactoryError(
                    f"illegal transition {current.value} -> {target_state.value}"
                )
            connection.execute(
                "UPDATE missions SET state=? WHERE id=?",
                (target_state.value, mission_id),
            )
            connection.execute(
                "INSERT INTO transitions "
                "(mission_id, attempt_id, from_state, to_state, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    mission_id,
                    attempt_id or row["active_attempt_id"],
                    current.value,
                    target_state.value,
                    reason,
                    time.time(),
                ),
            )

    def assert_mission(self, mission: Mission) -> None:
        text = _json_text(mission.canonical())
        digest = hashlib.sha256(text.encode()).hexdigest()
        with contextlib.closing(self._connect()) as connection:
            row = self._row(connection, mission.id)
            stored_digest = hashlib.sha256(row["mission_json"].encode()).hexdigest()
            if digest != row["mission_hash"] or stored_digest != row["mission_hash"]:
                raise FactoryError("mission lineage integrity check failed")

    def claim(self, mission_id: str) -> str | None:
        with self._immediate() as connection:
            row = self._row(connection, mission_id)
            if row["state"] != MissionState.READY.value:
                return None
            mission_document = json.loads(row["mission_json"])
            candidate_capacity = int(
                mission_document["resources"]["max_parallel_jobs"]
            )
            active_rows = connection.execute(
                "SELECT mission_json FROM missions WHERE state IN (?, ?)",
                (MissionState.RUNNING.value, MissionState.EVALUATING.value),
            ).fetchall()
            occupied = len(active_rows)
            active_capacities = [
                int(json.loads(active["mission_json"])["resources"]["max_parallel_jobs"])
                for active in active_rows
            ]
            capacity = min([candidate_capacity, *active_capacities])
            if occupied >= capacity:
                return None
            attempt_id = row["active_attempt_id"]
            if attempt_id is None:
                ordinal = connection.execute(
                    "SELECT COALESCE(MAX(ordinal), 0) + 1 FROM attempts "
                    "WHERE mission_id=?",
                    (mission_id,),
                ).fetchone()[0]
                attempt_id = f"{mission_id}-{ordinal}-{uuid.uuid4().hex[:8]}"
                connection.execute(
                    "INSERT INTO attempts VALUES (?, ?, ?, NULL, ?)",
                    (attempt_id, mission_id, ordinal, time.time()),
                )
                connection.execute(
                    "INSERT INTO attempt_runtime(attempt_id) VALUES (?)", (attempt_id,)
                )
            changed = connection.execute(
                "UPDATE missions SET state=?, active_attempt_id=? "
                "WHERE id=? AND state=?",
                (
                    MissionState.RUNNING.value,
                    attempt_id,
                    mission_id,
                    MissionState.READY.value,
                ),
            ).rowcount
            if changed != 1:
                return None
            connection.execute(
                "INSERT INTO transitions "
                "(mission_id, attempt_id, from_state, to_state, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    mission_id,
                    attempt_id,
                    MissionState.READY.value,
                    MissionState.RUNNING.value,
                    "claimed",
                    time.time(),
                ),
            )
            return str(attempt_id)

    def claim_evaluation(self, mission_id: str, attempt_id: str) -> None:
        with self._immediate() as connection:
            row = self._row(connection, mission_id)
            owner = connection.execute(
                "SELECT mission_id FROM attempts WHERE id=?", (attempt_id,)
            ).fetchone()
            if owner is None:
                raise FactoryError(f"unknown attempt {attempt_id!r}")
            if owner["mission_id"] != mission_id:
                raise FactoryError("evaluation attempt does not belong to mission")
            if (
                row["active_attempt_id"] != attempt_id
                or row["state"] != MissionState.EVALUATING.value
            ):
                raise FactoryError("only the active evaluating attempt can be evaluated")
            try:
                connection.execute(
                    "INSERT INTO evaluation_claims VALUES (?, ?)",
                    (attempt_id, time.time()),
                )
            except sqlite3.IntegrityError as exc:
                raise FactoryError("evaluation attempt is already claimed") from exc

    def fail_active(self, mission_id: str, attempt_id: str, reason: str) -> None:
        with self._immediate() as connection:
            row = self._row(connection, mission_id)
            if row["active_attempt_id"] != attempt_id:
                return
            current = MissionState(row["state"])
            if current == MissionState.CANCELLED or current not in {
                MissionState.RUNNING,
                MissionState.EVALUATING,
            }:
                return
            connection.execute(
                "UPDATE missions SET state=? WHERE id=?",
                (MissionState.FAILED.value, mission_id),
            )
            connection.execute(
                "INSERT INTO transitions "
                "(mission_id, attempt_id, from_state, to_state, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    mission_id,
                    attempt_id,
                    current.value,
                    MissionState.FAILED.value,
                    reason,
                    time.time(),
                ),
            )

    def set_runtime(self, attempt_id: str, **values: Any) -> None:
        allowed = {
            "scratch_path",
            "train_exit_code",
            "train_seconds",
            "eval_exit_code",
            "eval_seconds",
        }
        if not values or values.keys() - allowed:
            raise FactoryError("invalid attempt runtime fields")
        fields = ", ".join(f"{key}=?" for key in values)
        with self._immediate() as connection:
            changed = connection.execute(
                f"UPDATE attempt_runtime SET {fields} WHERE attempt_id=?",  # noqa: S608
                (*values.values(), attempt_id),
            ).rowcount
            if changed != 1:
                raise FactoryError(f"unknown attempt {attempt_id!r}")

    def register_process(
        self,
        mission_id: str,
        attempt_id: str,
        phase: str,
        process_pid: int,
        process_identity: str,
    ) -> bool:
        """Register a launch only while its exact attempt still owns the phase."""
        expected = {
            "train": MissionState.RUNNING.value,
            "eval": MissionState.EVALUATING.value,
        }
        if phase not in expected:
            raise FactoryError(f"unknown process phase {phase!r}")
        audit_fields = {
            "train": ("train_pid", "train_identity"),
            "eval": ("eval_pid", "eval_identity"),
        }
        pid_field, identity_field = audit_fields[phase]
        audit_queries = {
            "train": (
                "SELECT train_pid, train_identity FROM attempt_runtime "
                "WHERE attempt_id=?"
            ),
            "eval": (
                "SELECT eval_pid, eval_identity FROM attempt_runtime "
                "WHERE attempt_id=?"
            ),
        }
        statements = {
            "train": (
                "UPDATE attempt_runtime SET process_pid=?, process_identity=?, "
                "train_pid=COALESCE(train_pid, ?), "
                "train_identity=COALESCE(train_identity, ?) "
                "WHERE attempt_id=? AND process_pid IS NULL"
            ),
            "eval": (
                "UPDATE attempt_runtime SET process_pid=?, process_identity=?, "
                "eval_pid=COALESCE(eval_pid, ?), "
                "eval_identity=COALESCE(eval_identity, ?) "
                "WHERE attempt_id=? AND process_pid IS NULL"
            ),
        }
        with self._immediate() as connection:
            row = self._row(connection, mission_id)
            if (
                row["active_attempt_id"] != attempt_id
                or row["state"] != expected[phase]
            ):
                return False
            changed = connection.execute(
                statements[phase],
                (
                    process_pid,
                    process_identity,
                    process_pid,
                    process_identity,
                    attempt_id,
                ),
            ).rowcount
            if changed != 1:
                return False
            audit = connection.execute(
                audit_queries[phase],
                (attempt_id,),
            ).fetchone()
            if (
                audit is None
                or audit[pid_field] != process_pid
                or audit[identity_field] != process_identity
            ):
                raise FactoryError("immutable process audit identity changed")
            return True

    def clear_process(
        self, attempt_id: str, process_pid: int, process_identity: str
    ) -> None:
        """Clear cancellation fields without erasing immutable launch audit."""
        with self._immediate() as connection:
            connection.execute(
                "UPDATE attempt_runtime SET process_pid=NULL, process_identity=NULL "
                "WHERE attempt_id=? AND process_pid=? AND process_identity=?",
                (attempt_id, process_pid, process_identity),
            )

    def add_provenance(self, attempt_id: str, document: dict[str, Any]) -> str:
        text = _json_text(document)
        digest = hashlib.sha256(text.encode()).hexdigest()
        with self._immediate() as connection:
            try:
                connection.execute(
                    "INSERT INTO provenance VALUES (?, ?, ?, ?)",
                    (attempt_id, text, digest, time.time()),
                )
            except sqlite3.IntegrityError as exc:
                raise FactoryError("provenance is immutable") from exc
        return digest

    def _begin_promotion(
        self,
        mission_id: str,
        attempt_id: str,
        reviewer: str,
        shipper: str,
        provenance_hash: str,
        outputs: list[dict[str, str]],
    ) -> str:
        if not reviewer.strip() or not shipper.strip():
            raise FactoryError("reviewer and shipper approval actors are required")
        if reviewer.strip().casefold() == shipper.strip().casefold():
            raise FactoryError("reviewer and shipper must be distinct actors")
        with self._immediate() as connection:
            mission = self._row(connection, mission_id)
            if (
                mission["state"] != MissionState.PASSED.value
                or mission["active_attempt_id"] != attempt_id
            ):
                raise FactoryError("only the active passed attempt can promote")
            provenance = connection.execute(
                "SELECT document_json, document_hash FROM provenance WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if provenance is None:
                raise FactoryError("attempt has no canonical provenance")
            actual = hashlib.sha256(
                _json_text(json.loads(provenance["document_json"])).encode()
            ).hexdigest()
            if actual != provenance_hash or provenance["document_hash"] != provenance_hash:
                raise FactoryError("provenance integrity check failed")
            transaction_id = uuid.uuid4().hex
            now = time.time()
            connection.execute(
                "INSERT INTO promotion_transactions VALUES (?, ?, ?, ?, ?, ?, "
                "'pending', ?, NULL)",
                (
                    transaction_id,
                    mission_id,
                    attempt_id,
                    provenance_hash,
                    reviewer.strip(),
                    shipper.strip(),
                    now,
                ),
            )
            connection.executemany(
                "INSERT INTO promotion_outputs VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        transaction_id,
                        index,
                        output["source_path"],
                        output["destination_path"],
                        output["stage_path"],
                        output["expected_hash"],
                    )
                    for index, output in enumerate(outputs)
                ],
            )
            return transaction_id

    def pending_promotion(self, mission_id: str) -> dict[str, Any] | None:
        with contextlib.closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM promotion_transactions "
                "WHERE mission_id=? AND state='pending'",
                (mission_id,),
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["outputs"] = [
                dict(item)
                for item in connection.execute(
                    "SELECT * FROM promotion_outputs WHERE transaction_id=? "
                    "ORDER BY ordinal",
                    (row["id"],),
                )
            ]
            return result

    def _rollback_promotion(self, transaction_id: str) -> None:
        with self._immediate() as connection:
            connection.execute(
                "UPDATE promotion_transactions SET state='rolled_back', completed_at=? "
                "WHERE id=? AND state='pending'",
                (time.time(), transaction_id),
            )

    def _finalize_promotion(
        self,
        transaction_id: str,
    ) -> None:
        with self._immediate() as connection:
            transaction = connection.execute(
                "SELECT * FROM promotion_transactions WHERE id=? AND state='pending'",
                (transaction_id,),
            ).fetchone()
            if transaction is None:
                raise FactoryError("promotion transaction is not pending")
            mission_id = str(transaction["mission_id"])
            attempt_id = str(transaction["attempt_id"])
            reviewer = str(transaction["reviewer"])
            shipper = str(transaction["shipper"])
            provenance_hash = str(transaction["provenance_hash"])
            row = self._row(connection, mission_id)
            if (
                row["state"] != MissionState.PASSED.value
                or row["active_attempt_id"] != attempt_id
            ):
                raise FactoryError("only the active passed attempt can promote")
            provenance = connection.execute(
                "SELECT document_json, document_hash FROM provenance WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if provenance is None:
                raise FactoryError("attempt has no canonical provenance")
            actual = hashlib.sha256(
                _json_text(json.loads(provenance["document_json"])).encode()
            ).hexdigest()
            if actual != provenance_hash or provenance["document_hash"] != provenance_hash:
                raise FactoryError("provenance integrity check failed")
            try:
                connection.executemany(
                    "INSERT INTO approvals VALUES (?, ?, ?, ?, ?)",
                    [
                        (
                            attempt_id,
                            "reviewer",
                            reviewer.strip(),
                            provenance_hash,
                            time.time(),
                        ),
                        (
                            attempt_id,
                            "shipper",
                            shipper.strip(),
                            provenance_hash,
                            time.time(),
                        ),
                    ],
                )
            except sqlite3.IntegrityError as exc:
                raise FactoryError("promotion approvals already recorded") from exc
            connection.execute(
                "UPDATE missions SET state=? WHERE id=?",
                (MissionState.PROMOTED.value, mission_id),
            )
            connection.execute(
                "UPDATE promotion_transactions SET state='completed', completed_at=? "
                "WHERE id=? AND state='pending'",
                (time.time(), transaction_id),
            )
            connection.execute(
                "INSERT INTO transitions "
                "(mission_id, attempt_id, from_state, to_state, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    mission_id,
                    attempt_id,
                    MissionState.PASSED.value,
                    MissionState.PROMOTED.value,
                    "explicit reviewer and shipper approved promotion",
                    time.time(),
                ),
            )

    def status(self, mission_id: str) -> dict[str, Any]:
        with contextlib.closing(self._connect()) as connection:
            row = self._row(connection, mission_id)
            result = dict(row)
            result["mission"] = json.loads(result.pop("mission_json"))
            attempt_id = result["active_attempt_id"]
            result["provenance"] = None
            result["approvals"] = []
            if attempt_id:
                provenance = connection.execute(
                    "SELECT document_json FROM provenance WHERE attempt_id=?",
                    (attempt_id,),
                ).fetchone()
                if provenance:
                    result["provenance"] = json.loads(provenance[0])
                result["approvals"] = [
                    dict(item)
                    for item in connection.execute(
                        "SELECT role, actor, provenance_hash, created_at "
                        "FROM approvals WHERE attempt_id=? ORDER BY role",
                        (attempt_id,),
                    )
                ]
            return result

    def attempt(self, attempt_id: str) -> dict[str, Any]:
        with contextlib.closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT attempts.*, attempt_runtime.scratch_path, "
                "attempt_runtime.process_pid, attempt_runtime.process_identity, "
                "attempt_runtime.train_pid, attempt_runtime.train_identity, "
                "attempt_runtime.eval_pid, attempt_runtime.eval_identity, "
                "attempt_runtime.train_exit_code, attempt_runtime.train_seconds, "
                "attempt_runtime.eval_exit_code, attempt_runtime.eval_seconds "
                "FROM attempts JOIN attempt_runtime "
                "ON attempts.id=attempt_runtime.attempt_id WHERE attempts.id=?",
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise FactoryError(f"unknown attempt {attempt_id!r}")
            return dict(row)

    def provenance(self, attempt_id: str) -> tuple[dict[str, Any], str]:
        with contextlib.closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT document_json, document_hash FROM provenance WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise FactoryError("attempt has no canonical provenance")
            document = json.loads(row[0])
            digest = hashlib.sha256(_json_text(document).encode()).hexdigest()
            if digest != row[1]:
                raise FactoryError("provenance integrity check failed")
            return document, str(row[1])

    def running_count(self) -> int:
        with contextlib.closing(self._connect()) as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM missions WHERE state IN (?, ?)",
                    (MissionState.RUNNING.value, MissionState.EVALUATING.value),
                ).fetchone()[0]
            )

    def resume(self, mission_id: str) -> str:
        with self._immediate() as connection:
            row = self._row(connection, mission_id)
            current = MissionState(row["state"])
            if current not in {
                MissionState.FAILED,
                MissionState.REJECTED,
                MissionState.CANCELLED,
            }:
                raise FactoryError(f"cannot resume mission in state {current.value}")
            parent = row["active_attempt_id"]
            ordinal = connection.execute(
                "SELECT COALESCE(MAX(ordinal), 0) + 1 FROM attempts WHERE mission_id=?",
                (mission_id,),
            ).fetchone()[0]
            attempt_id = f"{mission_id}-{ordinal}-{uuid.uuid4().hex[:8]}"
            connection.execute(
                "INSERT INTO attempts VALUES (?, ?, ?, ?, ?)",
                (attempt_id, mission_id, ordinal, parent, time.time()),
            )
            connection.execute(
                "INSERT INTO attempt_runtime(attempt_id) VALUES (?)", (attempt_id,)
            )
            connection.execute(
                "UPDATE missions SET state=?, active_attempt_id=? WHERE id=?",
                (MissionState.READY.value, attempt_id, mission_id),
            )
            connection.execute(
                "INSERT INTO transitions "
                "(mission_id, attempt_id, from_state, to_state, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    mission_id,
                    attempt_id,
                    current.value,
                    MissionState.READY.value,
                    "resume",
                    time.time(),
                ),
            )
            return attempt_id

    def cancel(self, mission_id: str) -> None:
        with self._immediate() as connection:
            row = self._row(connection, mission_id)
            state = MissionState(row["state"])
            if MissionState.CANCELLED not in LEGAL_TRANSITIONS[state]:
                raise FactoryError(f"cannot cancel mission in state {state.value}")
            attempt_id = row["active_attempt_id"]
            if state in {MissionState.RUNNING, MissionState.EVALUATING} and attempt_id:
                runtime = connection.execute(
                    "SELECT process_pid, process_identity FROM attempt_runtime "
                    "WHERE attempt_id=?",
                    (attempt_id,),
                ).fetchone()
                if runtime is not None and runtime["process_pid"] is not None:
                    if not runtime["process_identity"]:
                        raise FactoryError(
                            "refusing cancellation without process identity"
                        )
                    terminate_process_tree(
                        int(runtime["process_pid"]), str(runtime["process_identity"])
                    )
            connection.execute(
                "UPDATE missions SET state=? WHERE id=?",
                (MissionState.CANCELLED.value, mission_id),
            )
            connection.execute(
                "INSERT INTO transitions "
                "(mission_id, attempt_id, from_state, to_state, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    mission_id,
                    attempt_id,
                    state.value,
                    MissionState.CANCELLED.value,
                    "operator cancel",
                    time.time(),
                ),
            )
