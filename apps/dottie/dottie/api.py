# Solo personal project, no connection to employer, built with public/free-tier only
"""Dottie FastAPI surface — submit tasks, inspect traces, drive the flywheel, honest status.

Tasks run in a background thread pool with a bounded admission queue (429 when full); task
state lives in SQLite (stdlib sqlite3) under the dottie data dir. Flywheel endpoints call the
real operations in :mod:`dottie.flywheel` synchronously and map honest gates to HTTP:
prerequisite absent -> 503 with the true reason; a real run that failed -> 500 with the true
cause. ``GET /status`` is the stable, honest JSON described in :mod:`dottie.status`."""

from __future__ import annotations

import inspect
import json
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

from dottie import climb as climb_mod
from dottie import flywheel
from dottie.engine import DottieEngine
from dottie.policy import DottiePolicyUnavailable
from dottie.status import build_status
from dottie.tasks import FAMILIES, VerifiedTaskProvider

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
    error       TEXT,
    family      TEXT,                    -- verified-task family (null for free-form)
    seed        INTEGER,                 -- verified-task seed (null for free-form)
    use_skills  INTEGER NOT NULL DEFAULT 0,
    verifier    TEXT                     -- JSON verifier detail (null until done / free-form)
);
"""

# Columns added after the first release; applied idempotently to pre-existing DBs.
_DB_MIGRATIONS = (
    "ALTER TABLE tasks ADD COLUMN family TEXT",
    "ALTER TABLE tasks ADD COLUMN seed INTEGER",
    "ALTER TABLE tasks ADD COLUMN use_skills INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE tasks ADD COLUMN verifier TEXT",
)


class TaskStore:
    """SQLite task state. One short-lived connection per call (thread-safe by construction)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_DB_SCHEMA)
            for stmt in _DB_MIGRATIONS:
                try:
                    c.execute(stmt)
                except sqlite3.OperationalError:
                    pass  # column already present (fresh schema or already migrated)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=10.0)
        c.row_factory = sqlite3.Row
        return c

    def insert(self, task_id: str, prompt: str, backend: str, max_steps: int,
               family: Optional[str] = None, seed: Optional[int] = None,
               use_skills: bool = False) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO tasks (task_id, created_ts, prompt, backend, max_steps, status, "
                "family, seed, use_skills) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?)",
                (task_id, time.time(), prompt, backend, max_steps,
                 family, seed, int(use_skills)),
            )

    def set_running(self, task_id: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE tasks SET status='running' WHERE task_id=?", (task_id,))

    def finish(self, task_id: str, record: Dict[str, Any]) -> None:
        verifier = record.get("verified_task")
        with self._conn() as c:
            c.execute(
                "UPDATE tasks SET status='done', final=?, terminated=?, n_steps=?, wall_s=?, "
                "reward_components=?, verifier=? WHERE task_id=?",
                (record.get("final"), record.get("terminated"), record.get("n_steps"),
                 record.get("wall_s"), json.dumps(record.get("reward_components", {})),
                 json.dumps(verifier) if verifier is not None else None,
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
        for key in ("reward_components", "verifier"):
            if d.get(key):
                try:
                    d[key] = json.loads(d[key])
                except json.JSONDecodeError:  # pragma: no cover - corrupt row surfaced as-is
                    pass
        d["use_skills"] = bool(d.get("use_skills"))
        # r_task surfaced at the top level for climb tooling (None until done / for free-form).
        comps = d.get("reward_components")
        d["r_task"] = comps.get("r_task") if isinstance(comps, dict) else None
        return d


_FAMILY_LITERAL = Literal["compute", "extract", "tool_chain", "file_ops", "constraint"]
assert set(_FAMILY_LITERAL.__args__) == set(FAMILIES)  # keep the API in lockstep with tasks.py


class TaskSubmit(BaseModel):
    """Free-form ({prompt}) or verified ({family, seed}) task — exactly one form."""

    prompt: Optional[str] = Field(default=None, min_length=1, max_length=20_000)
    family: Optional[_FAMILY_LITERAL] = None
    seed: int = Field(default=0, ge=0)
    backend: Literal["ollama", "ava", "echo"] = "ollama"
    max_steps: int = Field(default=8, ge=1, le=32)
    use_skills: bool = False

    @model_validator(mode="after")
    def _exactly_one_form(self) -> "TaskSubmit":
        if (self.prompt is None) == (self.family is None):
            raise ValueError("provide exactly one of 'prompt' (free-form) or "
                             "'family' (+ optional 'seed', a verified task)")
        return self


class TaskBatch(BaseModel):
    """A climb batch of verified tasks: one family or 'mixed' (cycles all families)."""

    family: Literal["compute", "extract", "tool_chain", "file_ops", "constraint", "mixed"]
    n: int = Field(default=5, ge=1, le=64)
    seeds: Optional[List[int]] = None
    backend: Literal["ollama", "ava", "echo"] = "ollama"
    max_steps: int = Field(default=8, ge=1, le=32)
    use_skills: bool = False

    @model_validator(mode="after")
    def _seeds_match_n(self) -> "TaskBatch":
        if self.seeds is not None and len(self.seeds) != self.n:
            raise ValueError(f"seeds length {len(self.seeds)} != n {self.n}")
        return self


class FlywheelEvaluateBody(BaseModel):
    mode: Literal["mock", "real"] = "mock"
    evals: str = "all"
    ckpt: Optional[str] = None
    tokenizer: Optional[str] = None


class FlywheelTrainStepBody(BaseModel):
    run_dir: Optional[str] = None
    device: Literal["cpu", "cuda"] = "cpu"
    extra_args: List[str] = Field(default_factory=list)


class ClimbBody(BaseModel):
    """One climb-iteration config (mirrors dottie.climb.ClimbConfig)."""

    families: Literal["compute", "extract", "tool_chain", "file_ops", "constraint",
                      "mixed"] = "mixed"
    n: int = Field(default=5, ge=1, le=64)
    seed_base: int = Field(default=0, ge=0)
    backend: Literal["ollama", "ava", "echo"] = "ollama"
    max_steps: int = Field(default=8, ge=1, le=32)
    use_skills: bool = False
    evaluate: Optional[Literal["mock", "real"]] = None
    train_step: bool = False
    compute: Optional[float] = Field(default=None, gt=0)


def create_app(engine: Optional[DottieEngine] = None) -> FastAPI:
    engine = engine or DottieEngine()
    store = TaskStore(engine.data_dir / "dottie.sqlite3")
    workers = int(os.environ.get("DOTTIE_WORKERS", "2"))
    queue_max = int(os.environ.get("DOTTIE_QUEUE_MAX", "32"))
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dottie-task")
    slots = threading.BoundedSemaphore(queue_max)  # bounds queued+running admissions

    app = FastAPI(
        title="Dottie",
        description="Dottie — agentic-assistant platform of the dottie monorepo.",
        version="0.1.0",
    )

    # CORS: the arxiviq console (a public static page) talks to THIS server on the user's own
    # box (localhost). Explicit origin allow-list — never "*": the API can run tasks.
    # arxiviq.vercel.app is where the console is deployed today; arxiviq.com stays listed for
    # the day the domain points back at it (it currently serves a separate control-plane site).
    cors_origins = [
        o.strip()
        for o in os.environ.get(
            "DOTTIE_CORS_ORIGINS",
            "https://arxiviq.vercel.app,https://arxiviq.com,https://www.arxiviq.com,"
            "http://localhost:8100,http://127.0.0.1:8100",
        ).split(",")
        if o.strip()
    ]
    # Chrome Private Network Access: a public HTTPS page fetching a localhost server sends
    # an extra preflight header that must be granted or Chrome blocks the request. Newer
    # Starlette handles it natively (and 400s ungranted PNA preflights); on older versions
    # a fallback middleware adds the grant to CORS-approved preflights.
    cors_kwargs: Dict[str, Any] = dict(
        allow_origins=cors_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["content-type"],
        max_age=600,
    )
    native_pna = "allow_private_network" in inspect.signature(
        CORSMiddleware.__init__).parameters
    if native_pna:
        cors_kwargs["allow_private_network"] = True
    app.add_middleware(CORSMiddleware, **cors_kwargs)
    if not native_pna:  # pragma: no cover - depends on installed starlette version
        @app.middleware("http")
        async def _private_network_preflight(request, call_next):
            response = await call_next(request)
            if (
                request.method == "OPTIONS"
                and request.headers.get("access-control-request-private-network") == "true"
                and "access-control-allow-origin" in response.headers
            ):
                response.headers["Access-Control-Allow-Private-Network"] = "true"
            return response

    provider = VerifiedTaskProvider()

    def _run_task(task_id: str, body: TaskSubmit) -> None:
        try:
            store.set_running(task_id)
            record = engine.run_task(
                body.prompt, backend=body.backend, max_steps=body.max_steps, task_id=task_id,
                family=body.family, seed=body.seed, use_skills=body.use_skills,
            )
            store.finish(task_id, record)
        except DottiePolicyUnavailable as e:
            store.fail(task_id, f"policy_unavailable: {e}")
        except Exception as e:  # real failure recorded honestly, never masked
            store.fail(task_id, f"{type(e).__name__}: {e}")
        finally:
            slots.release()

    def _admit_one(body: TaskSubmit) -> Dict[str, Any]:
        """Insert + schedule one admitted submission (its slot is already acquired)."""
        # Verified form: build now (deterministic) so validation fails fast and the DB stores
        # the REAL prompt the policy will see (minus engine-side context/tool footers).
        prompt = body.prompt
        if body.family is not None:
            prompt = provider.build(body.family, body.seed).prompt
        task_id = uuid.uuid4().hex[:12]
        try:
            store.insert(task_id, prompt, body.backend, body.max_steps,
                         family=body.family,
                         seed=body.seed if body.family is not None else None,
                         use_skills=body.use_skills)
            pool.submit(_run_task, task_id, body)
        except BaseException:
            slots.release()
            raise
        out = {"task_id": task_id, "status": "queued", "backend": body.backend}
        if body.family is not None:
            out["family"] = body.family
            out["seed"] = body.seed
        return out

    @app.post("/tasks", status_code=202)
    def submit_task(body: TaskSubmit) -> Dict[str, Any]:
        if not slots.acquire(blocking=False):
            raise HTTPException(
                status_code=429,
                detail=f"task queue full ({queue_max} queued+running); retry later",
            )
        return _admit_one(body)

    @app.post("/tasks/batch", status_code=202)
    def submit_batch(body: TaskBatch) -> Dict[str, Any]:
        try:
            pairs = provider.batch_seeds(body.family, body.n, body.seeds)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        # All-or-nothing admission: either the whole batch fits in the queue or none of it does.
        acquired = 0
        for _ in pairs:
            if not slots.acquire(blocking=False):
                for _ in range(acquired):
                    slots.release()
                raise HTTPException(
                    status_code=429,
                    detail=(f"queue cannot admit batch of {body.n} "
                            f"({queue_max} queued+running cap); retry later"),
                )
            acquired += 1
        submitted = []
        for fam, seed in pairs:
            submitted.append(_admit_one(TaskSubmit(
                family=fam, seed=seed, backend=body.backend,
                max_steps=body.max_steps, use_skills=body.use_skills,
            )))
        return {"batch_size": len(submitted), "family": body.family, "tasks": submitted}

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

    # One climb at a time: an iteration is a batch of real runs + real flywheel stages, so
    # concurrent climbs would interleave their traces; the lock keeps the record honest.
    climb_lock = threading.Lock()
    app.state.climb_lock = climb_lock

    @app.post("/climb")
    def run_climb(body: ClimbBody) -> Dict[str, Any]:
        if not climb_lock.acquire(blocking=False):
            raise HTTPException(
                status_code=409,
                detail="a climb iteration is already running; retry when it finishes",
            )
        try:
            cfg = climb_mod.ClimbConfig(
                families=body.families, n=body.n, seed_base=body.seed_base,
                backend=body.backend, max_steps=body.max_steps, use_skills=body.use_skills,
                evaluate=body.evaluate, train_step=body.train_step, compute=body.compute,
            )
            # Runs inline in the worker pool (same bounded workers as tasks); the request
            # blocks until the iteration record — with all measured numbers — exists.
            future = pool.submit(climb_mod.run_iteration, cfg, engine.data_dir)
            try:
                return future.result()
            except DottiePolicyUnavailable as e:
                raise HTTPException(status_code=503,
                                    detail=f"policy_unavailable: {e}") from e
            except (flywheel.FlywheelError, climb_mod.ClimbError) as e:
                raise HTTPException(status_code=500, detail=str(e)) from e
        finally:
            climb_lock.release()

    @app.get("/climb/log")
    def climb_log(limit: int = 50) -> Dict[str, Any]:
        limit = max(1, min(limit, 500))
        records = climb_mod.read_log(engine.data_dir)
        return {"count": len(records), "iterations": records[-limit:],
                "log_path": str(climb_mod.climb_log_path(engine.data_dir))}

    # -- research loop (read-only views the arxiviq Research tab renders) -----------------
    def _research_ledger():
        from dottie.research.ledger import Ledger as _Ledger
        from dottie.research import paths as _rpaths
        return _Ledger(_rpaths.ledger_path(engine.data_dir))

    @app.get("/research/status")
    def research_status() -> Dict[str, Any]:
        from dottie.research import logger as _rlog
        return _rlog.build_status(_research_ledger())

    @app.get("/research/experiments")
    def research_experiments(limit: int = 50, state: Optional[str] = None) -> Dict[str, Any]:
        led = _research_ledger()
        exps = led.list(state=state, limit=max(1, min(limit, 200)))
        return {"count": len(exps), "experiments": [
            {"id": e.id, "name": e.name, "state": e.state, "created_ts": e.created_ts,
             "updated_ts": e.updated_ts, "attempts": e.attempts,
             "hypothesis": e.hypothesis, "train_metrics": e.train_metrics,
             "eval_verdict": e.eval_verdict, "writeup": e.writeup, "failure": e.failure}
            for e in exps]}

    @app.get("/status")
    def status() -> Dict[str, Any]:
        return build_status(engine, task_counts=store.counts())

    return app


# Module-level app for `uvicorn dottie.api:app` (uses the default DOTTIE_DATA_DIR).
app = create_app()
