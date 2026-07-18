# Plan: T10.9 curriculum-aware high-water eviction (janitor)

## Goal
Extend the janitor with one owner for disk tidy: existing CONSUMED reclaim + ckpt
rotation, plus curriculum-aware eviction of oversupplied RAW/PACKED train shards
when free disk falls below `storage.evict_high_water_gb`. Collectors already pause
on dead phases via pacer/backpressure; this sheds the expanding-store tail.

## Design
- Thin policy module `ava/pipeline/eviction.py` (pure ranking + protect rules).
- Janitor calls it after CONSUMED reclaim when `free_gb < evict_high_water_gb`.
- Never val/test; never PACKED that would drop `tokens_ready(phase)` below
  `packed_min_tokens` (lead floor until full pacer lands).
- Prefer: phases behind trainer current, then oversupplied runway, then oldest.
- Prefer RAW before PACKED within the same priority band.
- Manifest: allow `RAW -> DELETED` for janitor; `mark_deleted` accepts RAW|PACKED|CONSUMED.

## Acceptance
- Unit tests: oversupplied P0 RAW deleted under pressure; P3 at lead protected;
  val refused; synthetic free_gb injection.
- Existing janitor tests still green.
- `configs/pipeline.yaml` gains `storage.evict_high_water_gb`.
- TODOS T10.9 annotated.
