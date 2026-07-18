---
name: memory-mint
description: Trace-capture -> memory-mint ingestion pipeline (async, non-blocking) feeding memory-router
triggers:
- memory
- mint
- trace
- capture
- ingest
- shard
j_space_target: Router
half_life: 30
broadcast_target: 0.22
reportability_target: 0.065
dependencies: []
connectors: []
provider: none
version: 1.0.0
precedes:
- memory-router
requires: []
complementary:
- memory-router
- eval-harness-runner
---

# Memory Mint

The ingestion half of the Ava memory layer (Mem0-style pattern from the MAI-Thinking-1
review). memory-router (ShardMemo Tier A/B/C) retrieves; **memory-mint captures and writes**.

## Pipeline

```
agent loop / skill run / harness eval
      │ capture(TraceEvent)          # O(1), never blocks, drop-oldest + counted on overflow
      ▼
bounded queue ──► daemon mint worker (batched)
                        │ mint_shard()   # scoped with memory-router's LIVE
                        ▼                # _shardmemo_scope_before_routing — imported, not forked
                  ShardStore (append-only JSONL per Tier-B scope, sha256-deduped, count-capped)
                        ▲
memory-router ── query(instruction)     # same scoping picks the shard file: mint/retrieve symmetric
```

## Usage

```python
from skill import MemoryMintPipeline, ShardStore, TraceEvent

pipe = MemoryMintPipeline(store=ShardStore())          # AVA_MEMORY_DIR or ~/.ava/memory/shards
pipe.capture(TraceEvent(source="agent", instruction=..., outcome=..., ok=True, branch="code"))
...                                                     # agent loop never waits
pipe.flush()                                            # deterministic barrier (tests/shutdown)
memories = pipe.store.query(instruction=next_prompt)    # retrieval for the router
```

## Guarantees

- **Non-blocking capture**: bounded queue; overflow sheds the *oldest* event and increments
  `stats["dropped"]` — loss is a visible metric, never a stall of the agent loop.
- **Scoping symmetry**: shards are tiered by the same live memory-router function used at
  retrieval time; Tier-A (safety) events are Critic-scoped and excluded from `only_ok` recall.
- **Dedupe**: `shard_id = sha256(instruction, outcome)`; re-minting an identical trace is a
  counted no-op.
- **Harness gating**: `run()` emits `measured` / `pass` / `bar` from a live end-to-end
  round-trip (anti-mock compliant — no hardcoded scores).

Solo personal project, no connection to employer, built with public/free-tier only.
