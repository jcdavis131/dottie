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
from typing import TYPE_CHECKING

import numpy as np

from dottie.config import TASK_TYPES, DottieConfig
from dottie.pipeline.flow import (
    DataState,
    FlowConfig,
    StarvationTracker,
    trainer_data_state,
)
from dottie.pipeline.manifest import Manifest, Shard, worker_id
from dottie.tokenizer import ENDOFDOC_ID

if TYPE_CHECKING:
    from collections.abc import Iterator

UNTAGGED_CONCEPT = -1


@dataclasses.dataclass
class Batch:
    input_ids: np.ndarray  # [B, T] int64
    concept_ids: np.ndarray  # [B]    int64, -1 where untagged
    task_type: str
    phase: int
    tokens: int


class _LoadedShard:
    """A packed shard, memmapped, with its docs grouped by task_type."""

    def __init__(self, shard: Shard) -> None:
        self.shard = shard
        idx_path = Path(shard.path).with_suffix("").with_suffix(".idx.json")
        if not idx_path.exists():  # {stem}.bin -> {stem}.idx.json
            idx_path = Path(str(shard.path).replace(".bin", ".idx.json"))
        meta = json.loads(idx_path.read_text())
        self.tokens: int = meta["tokens"]
        self.tokenizer_sha: str = meta.get("tokenizer_sha", "")
        self.arr = np.memmap(shard.path, dtype=np.uint16, mode="r")

        self.by_task: dict[str, list[dict]] = {t: [] for t in TASK_TYPES}
        for d in meta["docs"]:
            self.by_task.setdefault(d["task_type"], []).append(d)

    def windows(
        self, task_type: str, seq_len: int, rng: random.Random
    ) -> Iterator[tuple[np.ndarray, int]]:
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
        (UNTAGGED_CONCEPT if it covers none); ava/jlosses.py masks untagged rows
        out of the reportability loss, so a window of untagged text contributes
        nothing to it rather than contributing noise.
        """
        docs = list(self.by_task.get(task_type) or [])
        if not docs:
            return
        rng.shuffle(docs)
        need = seq_len + 1  # +1 for the shifted target

        buf: list[np.ndarray] = []
        concepts: list[int] = []
        filled = 0
        for d in docs:
            span = np.asarray(self.arr[d["start"] : d["end"]], dtype=np.int64)
            if span.size == 0:
                continue
            buf.append(span)
            buf.append(np.array([ENDOFDOC_ID], dtype=np.int64))
            concepts.append(int(d["concept_token_id"]))
            filled += span.size + 1

            while filled >= need:
                flat = np.concatenate(buf)
                yield (
                    flat[:need],
                    next((c for c in concepts if c >= 0), UNTAGGED_CONCEPT),
                )
                rest = flat[seq_len:]  # stride by seq_len, keep the overlap token
                buf = [rest] if rest.size else []
                filled = rest.size
                concepts = concepts[-1:]  # the doc the remainder came from


class StreamingShardSampler:
    def __init__(
        self,
        cfg: DottieConfig,
        manifest: Manifest,
        flow: FlowConfig,
        *,
        seed: int = 1234,
        worker: str | None = None,
        packed_dir: str = "/packed",
    ) -> None:
        self.cfg = cfg
        self.m = manifest
        self.flow = flow
        self.worker = worker or worker_id()
        self.packed_dir = packed_dir
        self.rng = random.Random(seed)
        self.starve = StarvationTracker(flow)
        self._task_cursor = 0
        self._held: _LoadedShard | None = None
        self._last_renew = 0.0

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
        s = self.m.claim(
            "train",
            by=self.worker,
            phases=[phase],
            lease_seconds=self.flow.train_lease_seconds,
        )
        if s is None:
            return None
        try:
            loaded = _LoadedShard(s)
        except Exception as exc:  # missing/corrupt .bin or .idx.json
            # fail(), not crash: a poison row (e.g. a PACKED row whose file the
            # curator never wrote) would otherwise kill the trainer on every
            # restart until a human deleted it. fail() retries then parks it.
            self.m.fail(s.id, by=self.worker, error=f"load failed: {exc}")
            return None
        expected = self.m.tokenizer_sha()
        if expected and loaded.tokenizer_sha and loaded.tokenizer_sha != expected:
            self.m.fail(s.id, by=self.worker, error="tokenizer sha mismatch")
            return None
        self._last_renew = time.monotonic()
        return loaded

    def _release(self, loaded: _LoadedShard) -> None:
        try:
            self.m.complete(loaded.shard.id, by=self.worker)
        except Exception as exc:
            # Lease expired mid-consumption and the shard was requeued: another
            # (or a future) claim now owns it. Losing the CONSUMED mark means
            # some repetition; killing the GPU loop over bookkeeping is worse.
            print(f"[sampler] complete({loaded.shard.id}) lost the lease: {exc}")

    def _renew_maybe(self) -> None:
        """Keep the train lease alive while consuming a large shard.

        A packed shard takes the trainer hours; without renewal the lease
        lapses, requeue_expired() hands the shard back to PACKED, and every
        re-claim ratchets `attempts` toward the cap (see rescue_stranded).
        """
        if self._held is None:
            return
        now = time.monotonic()
        if now - self._last_renew < 300:
            return
        self._last_renew = now
        try:
            ok = self.m.renew(
                self._held.shard.id,
                by=self.worker,
                lease_seconds=self.flow.train_lease_seconds,
            )
            if not ok:
                print(
                    f"[sampler] lost lease on {self._held.shard.id}; "
                    "it was requeued and may be re-served"
                )
        except Exception as exc:
            print(f"[sampler] lease renew failed: {exc}")

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

    def __enter__(self) -> StreamingShardSampler:
        # Any shard whose owner died is fair game again.
        self.m.requeue_expired()
        # And any PACKED shard whose attempts hit the cap through ordinary
        # crash-restarts (not poison -- those live in FAILED) is claimable again.
        rescued = self.m.rescue_stranded()
        if rescued:
            print(
                f"[sampler] rescued {len(rescued)} stranded PACKED shards "
                "(attempts reset)"
            )
        return self

    def __exit__(self, *exc) -> None:
        self.release_held()

    def _wait_for_data(self, phase: int, log=print) -> _LoadedShard:
        """Block until a shard for `phase` is claimable. Never raises on empty."""
        while True:
            state, msg = trainer_data_state(
                self.m, self.flow, phase=phase, disk_path=self.packed_dir
            )
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

    def _present_task_types(self, loaded: _LoadedShard) -> list[str]:
        """Task types in this shard, each EXACTLY ONCE, rotated for fairness.

        The old round-robin drew len(TASK_TYPES) times regardless of how many
        types were present, so a single-type shard (the P2 norm: 100%
        `automatic`) had its every window yielded 4x per claim -- a silent 4x
        data repetition that inflated tokens_done while unique tokens crawled.
        The cursor now only rotates which type leads from shard to shard.
        """
        present = [t for t in TASK_TYPES if loaded.by_task.get(t)]
        if not present:
            return []
        k = self._task_cursor % len(present)
        self._task_cursor += 1
        return present[k:] + present[:k]

    def batches(
        self, phase: int, seq_len: int, micro_batch: int, log=print
    ) -> Iterator[Batch]:
        """Endless stream of task_type-pure batches for `phase`."""
        while True:
            loaded = self._held or self._wait_for_data(phase, log=log)
            self._held = loaded
            produced = False

            for tt in self._present_task_types(loaded):
                buf_x: list[np.ndarray] = []
                buf_c: list[int] = []
                for win, cid in loaded.windows(tt, seq_len, self.rng):
                    buf_x.append(win)
                    buf_c.append(cid)
                    if len(buf_x) == micro_batch:
                        produced = True
                        self._renew_maybe()
                        yield Batch(
                            input_ids=np.stack(buf_x),
                            concept_ids=np.asarray(buf_c, dtype=np.int64),
                            task_type=tt,
                            phase=phase,
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
