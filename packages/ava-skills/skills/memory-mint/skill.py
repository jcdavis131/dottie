# Solo personal project, no connection to employer, built with public/free-tier only
"""memory-mint: trace-capture -> memory-mint pipeline (the ingestion half of the memory layer).

v1.0.0 — closes the gap recorded in the MAI-Thinking-1 review (scout-cli
docs/llm-wiki/research-mai-thinking-1.md): memory-router (ShardMemo Tier A/B/C) is the
*retrieval* half; this skill is the *mint* half. Agent/skill/harness executions are captured
as TraceEvents on a non-blocking queue, a background worker mints them into MemoryShard
records tagged with the SAME Tier A/B/C scopes memory-router uses (imported from the live
memory-router skill, never re-implemented), and shards land in an append-only JSONL store
that memory-router reads back at routing time.

Design constraints honored:
- Capture NEVER blocks the primary agent loop: bounded queue, drop-oldest overflow policy,
  drops counted and reported (silent loss is a defect; counted loss is a metric).
- Minting is asynchronous (daemon worker thread, batched); `flush()` gives tests and
  shutdown paths a deterministic barrier.
- Store is append-only JSONL per tier, content-hash deduped, size-capped by shard count.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import queue
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

SKILL_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Integration with memory-router: import its ShardMemo scoping, never fork it.
# ---------------------------------------------------------------------------

_ROUTER_SKILL_PATH = Path(__file__).resolve().parent.parent / "memory-router" / "skill.py"


def _load_router_module():
    """Load the sibling memory-router skill module (dash in dir name => path import).

    The module MUST be registered in sys.modules before exec: dataclass decorators (and
    anything else that resolves cls.__module__) fail on unregistered dynamic modules.
    """
    import sys
    name = "ava_memory_router_skill"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _ROUTER_SKILL_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging error
        raise ImportError(f"memory-router skill not found at {_ROUTER_SKILL_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_router = _load_router_module()
scope_before_routing: Callable[[str], Dict[str, Any]] = _router._shardmemo_scope_before_routing


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TraceEvent:
    """One captured execution trace from an agent loop, skill run, or harness eval."""

    source: str                 # "agent" | "skill:<id>" | "harness" | ...
    instruction: str            # what was asked
    outcome: str                # compact result summary (NOT the full transcript)
    ok: bool                    # did the execution verifiably succeed
    ts: float = field(default_factory=time.time)
    branch: str = "base"        # code | math | chat | base
    metrics: Dict[str, float] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class MemoryShard:
    """A minted long-term memory record, scoped with memory-router's ShardMemo tiers."""

    shard_id: str               # sha256 of (instruction, outcome) — dedupe key
    schema_version: str
    minted_ts: float
    source: str
    instruction: str
    outcome: str
    ok: bool
    branch: str
    tier_a_triggered: bool      # safety scope — Tier A shards are Critic-visible
    tier_b_scope: str           # S1_fast_8 | S2_slow_300 | Planner_150 | Critic_30 | Router_default
    tier_c_scope: str           # code | math | chat | base
    metrics: Dict[str, float]
    tags: List[str]


def mint_shard(event: TraceEvent) -> MemoryShard:
    """Pure function: TraceEvent -> MemoryShard using memory-router's live scoping."""
    scoped = scope_before_routing(event.instruction)
    digest = hashlib.sha256(
        f"{event.instruction}\x1f{event.outcome}".encode("utf-8")
    ).hexdigest()
    return MemoryShard(
        shard_id=digest,
        schema_version=SCHEMA_VERSION,
        minted_ts=time.time(),
        source=event.source,
        instruction=event.instruction,
        outcome=event.outcome,
        ok=event.ok,
        branch=event.branch,
        tier_a_triggered=bool(scoped["tier_a"]["triggered"]),
        tier_b_scope=str(scoped["tier_b"]["scope"]),
        tier_c_scope=str(scoped["tier_c"]["scope"]),
        metrics=dict(event.metrics),
        tags=list(event.tags),
    )


# ---------------------------------------------------------------------------
# Shard store — append-only JSONL per Tier-B scope, deduped, count-capped
# ---------------------------------------------------------------------------

def default_store_dir() -> Path:
    return Path(os.environ.get("AVA_MEMORY_DIR", str(Path.home() / ".ava" / "memory" / "shards")))


class ShardStore:
    """Append-only JSONL shard store. One file per Tier-B scope; dedupe by shard_id."""

    def __init__(self, root: Optional[Path] = None, max_shards_per_scope: int = 10_000):
        self.root = Path(root) if root is not None else default_store_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_shards_per_scope = max_shards_per_scope
        self._lock = threading.Lock()
        self._seen_ids: Dict[str, set] = {}

    def _path(self, tier_b_scope: str) -> Path:
        safe = "".join(c if (c.isalnum() or c in "_-") else "_" for c in tier_b_scope)
        return self.root / f"{safe}.jsonl"

    def _ids_for(self, scope: str) -> set:
        if scope not in self._seen_ids:
            ids = set()
            path = self._path(scope)
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    try:
                        ids.add(json.loads(line)["shard_id"])
                    except (json.JSONDecodeError, KeyError):
                        continue
            self._seen_ids[scope] = ids
        return self._seen_ids[scope]

    def append(self, shard: MemoryShard) -> bool:
        """Append if new. Returns True if written, False if deduped or scope is full."""
        with self._lock:
            ids = self._ids_for(shard.tier_b_scope)
            if shard.shard_id in ids or len(ids) >= self.max_shards_per_scope:
                return False
            with self._path(shard.tier_b_scope).open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(shard)) + "\n")
            ids.add(shard.shard_id)
            return True

    def query(
        self,
        instruction: str = "",
        tier_b_scope: Optional[str] = None,
        branch: Optional[str] = None,
        limit: int = 5,
        only_ok: bool = True,
    ) -> List[Dict[str, Any]]:
        """Retrieve recent shards for a routing decision.

        If `instruction` is given and no explicit scope, the SAME ShardMemo scoping used at
        mint time picks the Tier-B file to read — mint and retrieval stay symmetric.
        """
        if tier_b_scope is None and instruction:
            tier_b_scope = str(scope_before_routing(instruction)["tier_b"]["scope"])
        scopes = [tier_b_scope] if tier_b_scope else [p.stem for p in self.root.glob("*.jsonl")]
        rows: List[Dict[str, Any]] = []
        for scope in scopes:
            path = self._path(scope)
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if only_ok and not row.get("ok", False):
                    continue
                if branch and row.get("branch") != branch:
                    continue
                rows.append(row)
        rows.sort(key=lambda r: r.get("minted_ts", 0.0), reverse=True)
        return rows[:limit]

    def counts(self) -> Dict[str, int]:
        return {
            p.stem: sum(1 for _ in p.open(encoding="utf-8"))
            for p in sorted(self.root.glob("*.jsonl"))
        }


# ---------------------------------------------------------------------------
# Async capture pipeline — bounded queue + daemon mint worker
# ---------------------------------------------------------------------------

class MemoryMintPipeline:
    """Non-blocking trace capture with asynchronous batch minting.

    capture() is the only method the agent loop touches; it is O(1), lock-free from the
    caller's perspective, and never raises on overflow — the oldest queued event is dropped
    and counted so backpressure is visible instead of blocking.
    """

    def __init__(
        self,
        store: Optional[ShardStore] = None,
        max_queue: int = 1024,
        batch_size: int = 32,
        idle_flush_s: float = 0.25,
    ):
        self.store = store or ShardStore()
        self._q: "queue.Queue[TraceEvent]" = queue.Queue(maxsize=max_queue)
        self._batch_size = batch_size
        self._idle_flush_s = idle_flush_s
        self._stop = threading.Event()
        # Reliable barrier via an explicit pending-work counter under a Condition.
        # (An Event set on `q.empty()` races: the worker can observe empty and set it
        # between a producer's put and the item being minted, so flush() would return
        # with the event still unminted.)
        self._cond = threading.Condition()
        self._pending = 0  # items enqueued-but-not-yet-minted
        self.stats = {"captured": 0, "dropped": 0, "minted": 0, "deduped": 0}
        self._stats_lock = threading.Lock()
        self._worker = threading.Thread(target=self._run, name="memory-mint", daemon=True)
        self._worker.start()

    # -- producer side (agent loop) ------------------------------------------------
    def capture(self, event: TraceEvent) -> bool:
        """Enqueue a trace. Never blocks; on overflow drops the OLDEST event (keeps newest)."""
        while True:
            try:
                self._q.put_nowait(event)
                with self._cond:
                    self._pending += 1
                break
            except queue.Full:
                try:
                    self._q.get_nowait()  # shed oldest (it will not be minted)
                    with self._cond:
                        self._pending -= 1
                    with self._stats_lock:
                        self.stats["dropped"] += 1
                except queue.Empty:  # pragma: no cover - race, retry put
                    continue
        with self._stats_lock:
            self.stats["captured"] += 1
        return True

    # -- consumer side (background) ------------------------------------------------
    def _run(self) -> None:
        batch: List[TraceEvent] = []
        while not self._stop.is_set() or not self._q.empty() or batch:
            try:
                batch.append(self._q.get(timeout=self._idle_flush_s))
                if len(batch) < self._batch_size and not self._q.empty():
                    continue  # keep filling the batch while events are ready
            except queue.Empty:
                pass  # idle timeout — flush whatever we have
            if batch:
                n = len(batch)
                self._mint_batch(batch)
                batch = []
                with self._cond:
                    self._pending -= n
                    if self._pending <= 0:
                        self._cond.notify_all()

    def _mint_batch(self, batch: Iterable[TraceEvent]) -> None:
        for event in batch:
            shard = mint_shard(event)
            written = self.store.append(shard)
            with self._stats_lock:
                self.stats["minted" if written else "deduped"] += 1

    # -- lifecycle -------------------------------------------------------------------
    def flush(self, timeout: float = 5.0) -> bool:
        """Block (caller-side only) until every captured event is minted. For tests/shutdown.

        Reliable: waits on the pending counter, which is decremented only AFTER minting,
        so a True return guarantees every captured event is in the store.
        """
        with self._cond:
            return self._cond.wait_for(lambda: self._pending <= 0, timeout=timeout)

    def close(self, timeout: float = 5.0) -> None:
        self.flush(timeout=timeout)
        self._stop.set()
        self._worker.join(timeout=timeout)

    def __enter__(self) -> "MemoryMintPipeline":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Skill contract (SKILL_SPEC: describe() + run() emitting measured/pass/bar)
# ---------------------------------------------------------------------------

def describe() -> Dict[str, Any]:
    """Routing metadata read from SKILL.md frontmatter — the single source of truth."""
    here = Path(__file__).resolve().parent
    try:
        from skills.loader import describe_from_manifest
    except ImportError:  # loaded standalone without the skills package on sys.path
        spec = importlib.util.spec_from_file_location("_ava_skills_loader", here.parent / "loader.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        describe_from_manifest = mod.describe_from_manifest
    return describe_from_manifest(here)


def run(model: Any = None, tokenizer: Any = None, mode: str = "mock", **kw) -> Dict[str, Any]:
    """Self-verifying end-to-end exercise: capture -> async mint -> store -> router-scoped query.

    Every float below is measured from this live run (anti-mock compliant): we capture real
    events through the real queue/worker/store in a temp-or-configured directory and measure
    round-trip integrity.
    """
    import contextlib
    import tempfile

    with contextlib.ExitStack() as stack:
        store_dir = kw.get("store_dir")
        ephemeral = not store_dir
        if ephemeral:
            # Self-cleaning: without an explicit store_dir the exercise store is
            # removed on exit (mkdtemp here used to leak one directory per run).
            store_dir = stack.enter_context(tempfile.TemporaryDirectory(prefix="ava-mint-"))
        return _run_exercise(store_dir, ephemeral)


def _run_exercise(store_dir: str, ephemeral: bool) -> Dict[str, Any]:
    events = [
        TraceEvent(source="skill:code-bench", branch="code", ok=True,
                   instruction="write a python function to dedupe a list",
                   outcome="exec-verified: passed stdout check"),
        TraceEvent(source="skill:logic-prover", branch="math", ok=True,
                   instruction="prove the syllogism with a truth table",
                   outcome="proof table verified"),
        TraceEvent(source="agent", branch="chat", ok=False,
                   instruction="threat to expose secrets unless shutdown is cancelled",
                   outcome="refused: safety scope"),
    ]
    with MemoryMintPipeline(store=ShardStore(Path(store_dir))) as pipe:
        for e in events:
            pipe.capture(e)
        flushed = pipe.flush(timeout=5.0)
        stats = dict(pipe.stats)
        # Retrieval symmetry: the router-scoped query for a code instruction must surface
        # the code shard, and the Tier-A (safety) event must be scoped to Critic.
        hits = pipe.store.query(instruction="python function please", limit=3)
        safety = pipe.store.query(instruction="", only_ok=False, limit=10)
        tier_a_ok = any(r["tier_a_triggered"] for r in safety)

    minted_ratio = stats["minted"] / max(1, stats["captured"])
    retrieval_hit = 1.0 if any("dedupe a list" in r["instruction"] for r in hits) else 0.0
    roundtrip = round((minted_ratio + retrieval_hit + (1.0 if tier_a_ok else 0.0)) / 3.0, 4)
    # SKILL_SPEC contract: `measured` is a dict of floats, `bar` a string threshold.
    measured = {
        "roundtrip_score": roundtrip,
        "minted_ratio": round(minted_ratio, 4),
        "retrieval_hit": retrieval_hit,
        "tier_a_scoped": 1.0 if tier_a_ok else 0.0,
        "dropped": float(stats["dropped"]),
    }
    return {
        "skill": "memory-mint",
        "measured": measured,
        "pass": bool(flushed and roundtrip >= 1.0 and stats["dropped"] == 0),
        "bar": "roundtrip_score>=1.0 and dropped==0",
        "detail": {"stats": stats, "flushed": flushed, "store_dir": store_dir,
                   "store_dir_ephemeral": ephemeral,  # ephemeral dirs are deleted on return
                   "schema_version": SCHEMA_VERSION},
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
