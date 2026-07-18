# Solo personal project, no connection to employer, built with public/free-tier only
"""Dottie FastAPI surface — submit tasks, inspect traces, drive the flywheel, honest status.

Tasks run in a background thread pool with a bounded admission queue (429 when full); task
state lives in SQLite (stdlib sqlite3) under the dottie data dir. Flywheel endpoints call the
real operations in :mod:`dottie.flywheel` synchronously and map honest gates to HTTP:
prerequisite absent -> 503 with the true reason; a real run that failed -> 500 with the true
cause. ``GET /status`` is the stable, honest JSON described in :mod:`dottie.status`."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from dottie import flywheel
from dottie.engine import DottieEngine
from dottie.policy import DottiePolicyUnavailable
from dottie.status import build_status

import os

_DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id     TEXT PRIMARY KEY,
    created_ts  REAL NOT NULL,
    prompt      TEXT NOT NULL,
    backend     TEXT NOT NULL,
    max_steps   INTEGER NOT NULL,
    status      TEXT NOT NULL,           -- queued | running | done | error
    final       TEXT,
    terminated  TEXT,
    n_steps     INTEGER,
    wall_s      REAL,
    reward_components TEXT,              -- JSON
    error       TEXT
);
"""


class TaskStore:
    """SQLite task state. One short-lived connection per call (thread-safe by construction)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_DB_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=10.0)
        c.row_factory = sqlite3.Row
        return c

    def insert(self, task_id: str, prompt: str, backend: str, max_steps: int) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO tasks (task_id, created_ts, prompt, backend, max_steps, status) "
                "VALUES (?, ?, ?, ?, ?, 'queued')",
                (task_id, time.time(), prompt, backend, max_steps),
            )

    def set_running(self, task_id: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE tasks SET status='running' WHERE task_id=?", (task_id,))

    def finish(self, task_id: str, record: Dict[str, Any]) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE tasks SET status='done', final=?, terminated=?, n_steps=?, wall_s=?, "
                "reward_components=? WHERE task_id=?",
                (record.get("final"), record.get("terminated"), record.get("n_steps"),
                 record.get("wall_s"), json.dumps(record.get("reward_components", {})),
                 task_id),
            )

    def fail(self, task_id: str, error: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE tasks SET status='error', error=? WHERE task_id=?",
                      (error[:2000], task_id))

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def list(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM tasks ORDER BY created_ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def counts(self) -> Dict[str, int]:
        with self._conn() as c:
            rows = c.execute("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status").fetchall()
        out = {r["status"]: r["n"] for r in rows}
        out["total"] = sum(out.values())
        return out

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        if d.get("reward_components"):
            try:
                d["reward_components"] = json.loads(d["reward_components"])
            except json.JSONDecodeError:  # pragma: no cover - corrupt row surfaced as-is
                pass
        return d


class TaskSubmit(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    backend: Literal["ollama", "ava", "echo"] = "ollama"
    max_steps: int = Field(default=8, ge=1, le=32)


class FlywheelEvaluateBody(BaseModel):
    mode: Literal["mock", "real"] = "mock"
    evals: str = "all"
    ckpt: Optional[str] = None
    tokenizer: Optional[str] = None


class FlywheelTrainStepBody(BaseModel):
    run_dir: Optional[str] = None
    device: Literal["cpu", "cuda"] = "cpu"
    extra_args: List[str] = Field(default_factory=list)


def create_app(engine: Optional[DottieEngine] = None) -> FastAPI:
    engine = engine or DottieEngine()
    store = TaskStore(engine.data_dir / "dottie.sqlite3")
    workers = int(os.environ.get("DOTTIE_WORKERS", "2"))
    queue_max = int(os.environ.get("DOTTIE_QUEUE_MAX", "32"))
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dottie-task")
    slots = threading.BoundedSemaphore(queue_max)  # bounds queued+running admissions

    app = FastAPI(
        title="Dottie",
        description="Agentic-assistant platform (codename openclaw) — dottie monorepo.",
        version="0.1.0",
    )

    def _run_task(task_id: str, body: TaskSubmit) -> None:
        try:
            store.set_running(task_id)
            record = engine.run_task(
                body.prompt, backend=body.backend, max_steps=body.max_steps, task_id=task_id
            )
            store.finish(task_id, record)
        except DottiePolicyUnavailable as e:
            store.fail(task_id, f"policy_unavailable: {e}")
        except Exception as e:  # real failure recorded honestly, never masked
            store.fail(task_id, f"{type(e).__name__}: {e}")
        finally:
            slots.release()

    @app.post("/tasks", status_code=202)
    def submit_task(body: TaskSubmit) -> Dict[str, Any]:
        if not slots.acquire(blocking=False):
            raise HTTPException(
                status_code=429,
                detail=f"task queue full ({queue_max} queued+running); retry later",
            )
        task_id = uuid.uuid4().hex[:12]
        try:
            store.insert(task_id, body.prompt, body.backend, body.max_steps)
            pool.submit(_run_task, task_id, body)
        except BaseException:
            slots.release()
            raise
        return {"task_id": task_id, "status": "queued", "backend": body.backend}

    @app.get("/tasks/{task_id}")
    def get_task(task_id: str) -> Dict[str, Any]:
        row = store.get(task_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"unknown task_id {task_id!r}")
        return row

    @app.get("/tasks")
    def list_tasks(limit: int = 50) -> Dict[str, Any]:
        limit = max(1, min(limit, 500))
        return {"tasks": store.list(limit=limit), "counts": store.counts()}

    def _flywheel_call(fn, *args, **kwargs) -> Dict[str, Any]:
        try:
            return fn(*args, **kwargs)
        except flywheel.FlywheelUnavailable as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        except flywheel.FlywheelError as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    @app.post("/flywheel/export-rft")
    def flywheel_export_rft() -> Dict[str, Any]:
        return _flywheel_call(flywheel.export_rft_dataset, engine.data_dir)

    @app.post("/flywheel/mint")
    def flywheel_mint() -> Dict[str, Any]:
        return _flywheel_call(flywheel.mint_memories, engine.data_dir)

    @app.post("/flywheel/evaluate")
    def flywheel_evaluate(body: FlywheelEvaluateBody) -> Dict[str, Any]:
        return _flywheel_call(
            flywheel.evaluate, engine.data_dir,
            mode=body.mode, evals=body.evals, ckpt=body.ckpt, tokenizer=body.tokenizer,
        )

    @app.post("/flywheel/train-step")
    def flywheel_train_step(body: FlywheelTrainStepBody) -> Dict[str, Any]:
        # Synchronous by design (personal platform); a real run takes minutes on CPU.
        return _flywheel_call(
            flywheel.train_step,
            run_dir=body.run_dir, device=body.device, extra_args=body.extra_args,
        )

    @app.get("/status")
    def status() -> Dict[str, Any]:
        return build_status(engine, task_counts=store.counts())

    return app


# Module-level app for `uvicorn dottie.api:app` (uses the default DOTTIE_DATA_DIR).
app = create_app()
