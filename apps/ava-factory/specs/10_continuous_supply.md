# Spec 10 — Continuous Supply, Streaming Ingestion & Storage at Scale

- **Spec ID:** 10_continuous_supply
- **Worker tier:** 🟪 Opus for the control loop and reproducibility (T10.1–T10.7) — a silent bug here
  silently overfits the model or makes runs unreproducible; 🟦 Sonnet for compaction/eviction/observability
  (T10.8–T10.10) once the invariants below are fixed.
- **Dependencies:** 02_data_generation (generators stream + are byte-deterministic), the manifest +
  flow modules already shipped (`ava/pipeline/manifest.py`, `ava/pipeline/flow.py`, `configs/pipeline.yaml`),
  03_tokenizer (freeze gate), 04_model_and_configs (curriculum weights, seq-len per phase).
- **Consumers:** the trainer (`ava/data.py`, `ava/train.py`), the collector/curator/janitor service
  loops, and the eval harness (frozen snapshots).

## Purpose

Turn the *primitives* that already exist — backpressure predicates, `phase_next` prefetch, `DATA_STARVED`,
hash-stable splits, delete-after-consume — into a **curriculum-aware, stay-ahead control loop** that runs
data production a few steps ahead of the GPU, streams that data through ingestion/curation/training in
**bounded memory**, and stores a **continuously expanding corpus** so that any `(phase, task_type, split)`
subset is available when and where it is needed, on a single 28GB drive, reproducibly.

This spec does **not** re-implement Stage 2/4. It is the governor, the reproducible view, and the retention
policy layered on top of them. Everything here is a pure function of the manifest + a config plus a small
number of new service behaviors, in the exact style of `ava/pipeline/flow.py` (cheap to poll, no hidden
state, assert the *property* not the absence of a crash).

## Existing API surface these tasks must build on (do not reinvent)

`ava/pipeline/manifest.py` (`Manifest`):
- `tokens_ready(phase: int, *, split: str = "train") -> int` — PACKED-train tokens available for a phase. **The runway measure.**
- `claim(stage, *, by, phases=None, splits=None) -> Shard | None` — atomic, `ORDER BY phase ASC, created_at ASC`. Trainer forced to `splits=("train",)`.
- `add_shard(id, *, source, phase, path, split="train", bytes_, docs, sha256, state=RAW) -> bool` — idempotent (INSERT OR IGNORE).
- `get_cursor(source) -> (position|None, docs_seen)` / `set_cursor(source, position, docs_seen)` — the resumable production cursor. Multi-phase producers encode phase in the `source` key (e.g. `"synth_ency:p2"`), per the T3.4 fix.
- `mark_deleted(shard_ids) -> int` (refuses val/test), `requeue_expired() -> [ids]`, `counts_by_state()`, `consumed_shards(limit)`.
- `freeze_tokenizer(sha256, vocab_size)` / `tokenizer_sha() -> str|None` — the pack gate.
- `upsert_run(run_id, *, preset, step, phase, status)` / `log_metric(run_id, key, value)` — observability sink.
- `shards` table columns: `id (TEXT PK), source, phase, split, state, path, bytes, tokens, docs, sha256, tokenizer_sha, attempts, claimed_by, lease_expires_at, error, created_at, updated_at`. `tokens_ready` sums the `tokens` column over `state=PACKED`. The table is **not** `WITHOUT ROWID`, so the implicit `rowid` is monotonic in registration order — **it is the watermark primitive (T10.5)**. Claim hot path is indexed `(state, phase, created_at)`.

`ava/pipeline/flow.py`: `FlowConfig.load()`, `free_gb()`, `collector_should_pause()`, `prefetch_phases()`,
`starved_phase()`, `trainer_data_state() -> (DataState, str)`, `StarvationTracker`. New logic extends these;
it does not replace them.

`configs/pipeline.yaml`: `disk{low_water_gb, janitor_trigger_gb, critical_gb}`, `backpressure{raw_max_bytes,
packed_ahead_max_tokens, packed_min_tokens, starved_*}`, `retention{delete_consumed, keep_*_checkpoints}`,
`collector{prefetch_phases}`, `splits{train,val,test}`.

## New config (append to `configs/pipeline.yaml`)

```yaml
pacing:
  lead_steps: 400            # keep >= this many trainer steps of runway per active phase
  lead_phase_next_frac: 0.5  # phase_next must reach this fraction of lead before the trainer arrives
  setpoint_hysteresis: 0.15  # +/- band around lead to avoid effort chatter
  effort_min: 0.05           # floor so a phase never fully starves of workers
  control_period_s: 5

reproducibility:
  pin_watermark: true        # runs read shards with rowid <= run.watermark
  record_in_checkpoint: true # watermark + tokenizer_sha + curriculum_weights persisted with ckpt

storage:
  compact_below_bytes: 67_108_864   # merge PACKED shards under 64MB per (phase,split,seq_len)
  compact_target_bytes: 268_435_456
  evict_high_water_gb: 15           # above janitor_trigger, below low_water: begin curriculum-aware eviction
  evict_order: [oversupplied_phase, oldest, lowest_edu_score]  # never val/test, never a phase < lead

replay:
  allow_replay: true         # when unique supply for a phase is exhausted
  reshuffle_on_replay: true
  min_repeat_window_docs: 5_000_000  # a doc must not recur within this many docs
```

## Components

### T10.1 — `ava/pipeline/pacer.py`: curriculum pacing controller (🟪)
Pure decision functions, `flow.py`-style. No I/O beyond the manifest + `free_gb`.
- `runway_steps(manifest, cfg, *, phase, batch_tokens) -> float` = `tokens_ready(phase) / batch_tokens`.
- `effort_weights(manifest, cfg, *, current_phase, batch_tokens, n_phases=6) -> dict[int, float]` —
  normalized production effort per phase. Deficit-proportional against the `lead_steps` setpoint
  (with `lead_phase_next_frac` for `current+1`, `effort_min` floor, `setpoint_hysteresis` deadband);
  phases at/over setpoint get `effort_min`. This is the actuator signal the collector/datagen governor
  and curator replica scaler consume — the richer successor to `starved_phase()`.
- `PacerState` may hold an EWMA of consumption tok/s from `metrics.jsonl` to anticipate the drain rate.
- **accept:** a simulated trainer draining P0→P5 at varying tok/s (unit test with a fake `Manifest`
  exposing `tokens_ready`) never drops any *active* phase below `lead_steps` at a transition; per-phase
  runway stays in `[lead·(1-hyst), high-water]`. **Negative control:** replacing `effort_weights` with a
  uniform constant makes the transition test show a starvation window — prove the test is not vacuous.

### T10.2 — infinite-generator governor (🟪, in `pacer.py`)
The synthetic generators (`ava/datagen/*`) accept `generate(target_bytes)` and stream unbounded; the
governor sets each generator run's `target_bytes` from that `(source, phase)`'s runway *deficit*
(`effort_weights`), so P0 cannot overproduce and evict P5's disk budget. Deterministic resume via the
existing `get_cursor`/`set_cursor` (source key carries the phase). The collector loop already calls the
generators post-T3.4; the governor only supplies the per-tick budget + gates on `collector_should_pause`.
- **accept:** under a tight `low_water_gb`/`raw_max_bytes` cap, all six phases reach their lead target and
  no phase starves another; killing and restarting mid-tick resumes at the same cursor and yields
  byte-identical shards (extends the T3.2 determinism guarantee end-to-end).

### T10.3 — bounded-memory streaming ingestion (`ava/data.py`, extends T6.3) (🟪)
`StreamingShardSampler` and the curator readers must keep RSS flat regardless of corpus size:
- `np.memmap` the uint16 `.bin` (never load a full shard); read `[start:end]` slices per `.idx.json`.
- Fixed-size bounded queues across claim → decompress → collate (a producer thread blocks, it does not grow).
- A bounded shuffle: shard-level shuffle of claim order **within the pinned watermark** + a fixed-size
  intra-buffer; no global materialization.
- Pinned-memory host staging + async H2D double-buffering (prefetch depth 2) to overlap load with compute.
- No-padding sequence packing at the phase's seq-len (P0 256 … P4/P5 1024); batches stay `task_type`-pure
  (required by the J-Space routing loss).
- **accept:** trainer RSS bounded within a fixed ceiling across a ≥100k-step run over a corpus ≥50× RAM
  (memmap proven by `/proc/self/status` VmRSS staying flat while VmSize grows); **zero** pad tokens counted
  in emitted batches; GPU util ≥ target at prefetch depth 2.

### T10.4 — live throughput invariant (extends T5.4) (🟪, in `pacer.py`)
Make `curation_tok/s ≥ trainer_tok/s` **and** `production_tok/s ≥ trainer_tok/s` a *running* gauge (EWMA
from `metrics.jsonl`), not a one-shot bench. When the ratio dips, the pacer raises the curator/collector
target replica count (compose scale hint) or trips `collector_should_pause=False` harder; when it is
comfortably above, it relaxes. The T5.4 `3×` gate becomes this invariant's cold-start check.
- **accept:** an injected trainer speedup (fewer grad-accum steps) drives the ratio < 1; the gauge detects
  it within one `control_period_s` and the recommended curator replica count rises; ratio recovers.

### T10.5 — reproducible dataset view / as-of watermark (🟪; manifest + `ava/train.py`)
Pin each run to a **watermark** = max `rowid` at run start (or resume). Add
`Manifest.claim(..., max_rowid=None)` so the trainer only ever claims shards registered at or before its
watermark; the corpus may grow underneath it without changing the run's data order. Persist
`{watermark, tokenizer_sha, curriculum_weights}` in the checkpoint and in `upsert_run`.
- **accept:** kill+resume at step K reads the identical next-shard sequence bit-for-bit (assert the claimed
  id stream); a fresh run at the same watermark+seed reproduces `metrics.jsonl` key order. **Negative
  control:** dropping the `max_rowid` filter while concurrently adding shards perturbs the claimed stream —
  the test must catch it.

### T10.6 — frozen eval snapshots vs. growing train (🟪; `evals/`)
val/test buckets grow as generation continues. Freeze a **named snapshot** = the explicit set of val/test
shard ids (or `rowid <= eval_watermark`) per scale rung (`nano`, `mini`, `base1b/M*`), recorded in the run
row. The eval harness reads only that set. Structural val/test protection (T2.1) already blocks leakage;
this adds cross-milestone **comparability**.
- **accept:** two milestones evaluate over byte-identical val/test token streams (sha256 of concatenated
  eval tokens equal); adding new data does not change a past milestone's eval set.

### T10.7 — unique-token accounting + replay policy (🟪; `pacer.py` + dedup DB)
Define epoch semantics under single-pass delete-after-consume when a phase's *unique* supply < what the
trainer needs (expected at base1b ~20B). Track `unique_tokens_seen[phase]` from the dedup DB (T4.2). On
exhaustion: prefer to block for fresh collection (`DATA_STARVED` is acceptable here); if `allow_replay`,
do a **controlled** replay — re-shuffle order, stamp `replay_epoch`, and never re-show a doc within
`min_repeat_window_docs`. Silent back-to-back repetition (memorization) is a bug.
- **accept:** a phase forced into replay logs `replay_epoch` and a re-shuffled order; dedup confirms no
  `doc_id` recurs within the window. **Assert the property**, not merely that it ran.

### T10.8 — shard compaction + addressable index (🟦; `ava/pipeline/compact.py`)
Merge PACKED shards under `compact_below_bytes` per `(phase, split, seq_len)` into ~`compact_target_bytes`
outputs; maintain a compact index (`packed/index.json` or a manifest view) so any `(phase, task_type,
split)` subset is addressable without scanning. Respect the frozen-tokenizer and val/test gates; compaction
is a manifest state transition, not a raw file move (old ids → DELETED, new id → PACKED, atomically).
- **accept:** post-compaction shard count ↓ and mean shard ≈ target; the sampler reads an **unchanged**
  token stream (sha256 of concatenated tokens per subset stable across compaction).

### T10.9 — storage retention + disk high-water eviction (🟦; extends the janitor, T8.5)
Above `evict_high_water_gb` the janitor sheds the least-curriculum-useful RAW/PACKED first, in
`evict_order`: over-supplied phases (runway ≫ lead), then oldest, then lowest `edu_score`. **Never** val/test
(`mark_deleted` already refuses), **never** a phase below its `lead_steps` runway. Delete-after-consume
(existing) handles the common case; this handles the expanding-store tail.
- **accept:** under a synthetic disk-fill, eviction keeps `free_gb` in `[critical, low_water]` and never
  drops a phase below lead; assert no val/test byte is ever deleted (perturb: try to evict a val shard →
  refused).

### T10.10 — supply observability (🟦; `metrics.jsonl` + `/report`)
Emit per phase: runway (steps & tokens), lead/lag vs setpoint, `DATA_STARVED` seconds, production/curation/
train tok/s and their ratios, `unique_tokens_seen`, `replay_epoch`, and disk headroom — via `log_metric`.
Surface them in `scripts/make_report.py`'s `reports/index.html`. This is the instrument panel behind
PLAN.md's "steady state = success."
- **accept:** a nano smoke shows all six phases' runway live; a forced starvation is visible within one
  scrape interval.

## Cross-cutting acceptance (foreman)
1. `pytest tests/test_pacer.py -q` — setpoint controller + governor + throughput gauge, each with a
   negative control that makes the property fail.
2. `pytest tests/test_streaming.py -q` — memmap RSS-flatness, zero-pad packing, `task_type` purity.
3. `pytest tests/test_reproducibility.py -q` — watermark resume bit-exactness; frozen eval snapshot equality.
4. End-to-end during the nano smoke (T9.1): `DATA_STARVED` bursts < a few seconds across all P0→P5
   transitions, disk stays under the high watermark indefinitely, and `reports/index.html` shows the runway
   band holding.

## Out of scope
- The trainer/sampler internals themselves (04/05/T6.3/T6.4) — this spec only adds the streaming
  *invariants* and the `max_rowid` claim filter they must honor.
- Distributed/multi-node supply (single host, single GPU).
- Any new network source (collector's HF streaming is the only network path; unchanged here).
- Changing the split ratios or the decontamination contract (Stage 4).
