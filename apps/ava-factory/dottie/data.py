"""StreamingShardSampler: feeds the trainer from the live shard pipeline.

The trainer does not own a dataset. It claims PACKED shards from the manifest,
consumes them, and marks them CONSUMED so the janitor can reclaim the disk.
Data is being collected and curated *while this runs*.

Two properties the training loop depends on:

* **task_type-pure batches.** The J-Space routing loss compares `route_probs`
  against a target distribution chosen per `task_type`. A batch mixing
  `automatic` and `safety` docs has no single target, so the KL term would
  regress toward a meaningless average. Batches are therefore drawn from one
  task_type at a time, round-robin weighted by how much of that type is present.

* **starve, don't crash.** An empty queue is the *normal* state at a phase
  boundary, when the collector has not yet produced the next phase's data. The
  sampler blocks and reports DATA_STARVED rather than raising StopIteration into
  the training loop.

Memory: shards are `np.memmap`ed, never read whole. A packed shard is uint16, so
a 100M-token shard costs 200MB of address space and only the touched pages of
RSS.
"""

from __future__ import annotations

import dataclasses
import json
import random
import time
from pathlib import Path
from typing import Iterator

import numpy as np

from dottie.config import TASK_TYPES, DottieConfig
from dottie.pipeline.flow import DataState, FlowConfig, StarvationTracker, trainer_data_state
from dottie.pipeline.manifest import Manifest, Shard, worker_id
from dottie.tokenizer import ENDOFDOC_ID

UNTAGGED_CONCEPT = -1


@dataclasses.dataclass
class Batch:
    input_ids: np.ndarray      # [B, T] int64
    concept_ids: np.ndarray    # [B]    int64, -1 where untagged
    task_type: str
    phase: int
    tokens: int


class _LoadedShard:
    """A packed shard, memmapped, with its docs grouped by task_type."""

    def __init__(self, shard: Shard) -> None:
        self.shard = shard
        idx_path = Path(shard.path).with_suffix("").with_suffix(".idx.json")
        if not idx_path.exists():                     # {stem}.bin -> {stem}.idx.json
            idx_path = Path(str(shard.path).replace(".bin", ".idx.json"))
        meta = json.loads(idx_path.read_text())
        self.tokens: int = meta["tokens"]
        self.tokenizer_sha: str = meta.get("tokenizer_sha", "")
        self.arr = np.memmap(shard.path, dtype=np.uint16, mode="r")

        self.by_task: dict[str, list[dict]] = {t: [] for t in TASK_TYPES}
        for d in meta["docs"]:
            self.by_task.setdefault(d["task_type"], []).append(d)

    def windows(self, task_type: str, seq_len: int, rng: random.Random) -> Iterator[tuple[np.ndarray, int]]:
        """Yield (tokens[seq_len+1], concept_id) windows for one task_type.

        Documents are CONCATENATED, separated by <|endofdoc|>, and then sliced
        into fixed windows -- the standard packing scheme, and the only workable
        one here: the synthetic corpus has a median document length of ~100
        tokens, so a rule of "one window never straddles a document" left phases
        1 and 5 with literally zero usable windows at seq_len=256 and starved
        the trainer forever.

        Only documents of the SAME task_type are concatenated, so the routing
        loss still has a well-defined target for the whole window. The
        concept_id is taken from the first tagged document a window covers
        (UNTAGGED_CONCEPT if it covers none); dottie/jlosses.py masks untagged rows
        out of the reportability loss, so a window of untagged text contributes
        nothing to it rather than contributing noise.
        """
        docs = list(self.by_task.get(task_type) or [])
        if not docs:
            return
        rng.shuffle(docs)
        need = seq_len + 1                        # +1 for the shifted target

        buf: list[np.ndarray] = []
        concepts: list[int] = []
        filled = 0
        for d in docs:
            span = np.asarray(self.arr[d["start"]:d["end"]], dtype=np.int64)
            if span.size == 0:
                continue
            buf.append(span)
            buf.append(np.array([ENDOFDOC_ID], dtype=np.int64))
            concepts.append(int(d["concept_token_id"]))
            filled += span.size + 1

            while filled >= need:
                flat = np.concatenate(buf)
                yield flat[:need], next((c for c in concepts if c >= 0), UNTAGGED_CONCEPT)
                rest = flat[seq_len:]             # stride by seq_len, keep the overlap token
                buf = [rest] if rest.size else []
                filled = rest.size
                concepts = concepts[-1:]          # the doc the remainder came from


class StreamingShardSampler:
    def __init__(self, cfg: DottieConfig, manifest: Manifest, flow: FlowConfig, *,
                 seed: int = 1234, worker: str | None = None,
                 packed_dir: str = "/packed") -> None:
        self.cfg = cfg
        self.m = manifest
        self.flow = flow
        self.worker = worker or worker_id()
        self.packed_dir = packed_dir
        self.rng = random.Random(seed)
        self.starve = StarvationTracker(flow)
        self._task_cursor = 0
        self._held: _LoadedShard | None = None

    # -- resumable state ----------------------------------------------------

    def state_dict(self) -> dict:
        return {"rng": self.rng.getstate(), "task_cursor": self._task_cursor}

    def load_state_dict(self, s: dict) -> None:
        rng = s["rng"]
        # json round-trip turns tuples into lists
        self.rng.setstate((rng[0], tuple(rng[1]), rng[2]))
        self._task_cursor = s["task_cursor"]

    # -- shard acquisition --------------------------------------------------

    def _claim(self, phase: int) -> _LoadedShard | None:
        s = self.m.claim("train", by=self.worker, phases=[phase])
        if s is None:
            return None
        loaded = _LoadedShard(s)
        expected = self.m.tokenizer_sha()
        if expected and loaded.tokenizer_sha and loaded.tokenizer_sha != expected:
            self.m.fail(s.id, by=self.worker, error="tokenizer sha mismatch")
            return None
        return loaded

    def _release(self, loaded: _LoadedShard) -> None:
        self.m.complete(loaded.shard.id, by=self.worker)

    def release_held(self, reason: str = "trainer exited") -> None:
        """Hand a partially-consumed shard back to PACKED.

        Without this, every training run leaks its in-flight shard: it sits in
        CLAIMED_TRAIN until the lease expires (an hour), and a run restarted
        immediately finds `tokens_ready == 0` and starves on data it already
        owns. `fail()` moves CLAIMED_TRAIN -> PACKED, so the shard is simply
        re-served (its windows are regenerated; a partial shard is not tracked).
        """
        if self._held is None:
            return
        try:
            self.m.release_claim(self._held.shard.id, by=self.worker, note=reason)
        finally:
            self._held = None

    def __enter__(self) -> "StreamingShardSampler":
        # Any shard whose owner died is fair game again.
        self.m.requeue_expired()
        return self

    def __exit__(self, *exc) -> None:
        self.release_held()

    def _wait_for_data(self, phase: int, log=print) -> _LoadedShard:
        """Block until a shard for `phase` is claimable. Never raises on empty."""
        while True:
            state, msg = trainer_data_state(self.m, self.flow, phase=phase,
                                            disk_path=self.packed_dir)
            if state is DataState.CRITICAL_DISK:
                raise RuntimeError(f"refusing to train: {msg}")

            loaded = self._claim(phase)
            if loaded is not None:
                self.starve.record(False)
                return loaded

            warn = self.starve.record(True)
            if warn:
                log(warn)
            time.sleep(self.flow.starved_poll_seconds)

    # -- batching -----------------------------------------------------------

    def _next_task_type(self, loaded: _LoadedShard) -> str | None:
        """Round-robin over task_types actually present in this shard."""
        present = [t for t in TASK_TYPES if loaded.by_task.get(t)]
        if not present:
            return None
        t = present[self._task_cursor % len(present)]
        self._task_cursor += 1
        return t

    def batches(self, phase: int, seq_len: int, micro_batch: int, log=print) -> Iterator[Batch]:
        """Endless stream of task_type-pure batches for `phase`."""
        while True:
            loaded = self._held or self._wait_for_data(phase, log=log)
            self._held = loaded
            produced = False

            for _ in range(len(TASK_TYPES)):
                tt = self._next_task_type(loaded)
                if tt is None:
                    break
                buf_x: list[np.ndarray] = []
                buf_c: list[int] = []
                for win, cid in loaded.windows(tt, seq_len, self.rng):
                    buf_x.append(win)
                    buf_c.append(cid)
                    if len(buf_x) == micro_batch:
                        produced = True
                        yield Batch(
                            input_ids=np.stack(buf_x),
                            concept_ids=np.asarray(buf_c, dtype=np.int64),
                            task_type=tt, phase=phase,
                            tokens=micro_batch * seq_len,
                        )
                        buf_x, buf_c = [], []
                # a trailing partial batch is dropped: a short batch would change
                # the effective tokens-per-step and desync the WSD schedule

            self._release(loaded)
            self._held = None
            if not produced:
                # shard held no window long enough; keep going rather than spin
                continue
