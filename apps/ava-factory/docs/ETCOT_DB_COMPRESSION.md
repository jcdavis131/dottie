# ET-CoT: Databases & Compression in the Pretraining Curriculum

Solo personal project, no connection to employer.

Ava's curriculum now teaches **database mechanics** and **data compression /
information theory** as *dynamic state modeling*, not static code
comprehension. Two new deterministic generators emit Execution-Trace
Chain-of-Thought (ET-CoT) docs — triplets of (Input State, Execution Trace,
Final Output) — where the trace is produced by actually running the engine or
algorithm in Python, and the answer is asserted against an independent
recomputation (and, for every codec, a full decoder round-trip) before the
doc is yielded.

```
### Task: <problem + COMPLETE input state: page table / buckets / adjacency / bytes>

<think>
[step 1] <state transition, every number computed by real execution>
[step 2] ...
[.. K steps elided to fit the trace budget; state checkpoint before step N: <true computed state> ..]
[step N] ...
</think>
<answer>
<terminal state: result row, bitstream, quantized tensor, aggregate table>
</answer>
```

## Coverage

**`ava/datagen/db_trace.py`** (`db_trace`, phases 2/3/4) — one family per
primary data model of the "Types of Databases" taxonomy:

| Data model | What the trace simulates |
|---|---|
| Relational (SQL) | real order-4 B-tree: planner cost (full scan vs index seek), per-page-load descent, prune-aware range scans, inserts with split/median promotion |
| Document | collection scan: path extraction (`user.age`), short-circuit predicates, projection |
| Key-Value | FNV-1a-32 computed char-by-char, `hash mod buckets`, linear-probe collision chains |
| Wide Column | byte-offset arithmetic of columnar blocks; SUM reading one column vs whole rows |
| Graph | BFS queue/dist/parent frontier per dequeue; DFS with explicit stack |
| Time Series | window bucketing `(t - t0) // W`, running count/sum/min/max per bucket |
| Vector | exact top-k with expanded squared-Euclidean terms; cosine-similarity top-1; greedy 2-layer HNSW descent whose answer honestly reports greedy-vs-brute-force agreement |
| LSM engine | memtable → sorted L0 runs at 4 entries → compaction into L1 (newest wins, tombstones dropped); GETs trace the memtable → L0 → L1 probe path |
| WAL / ACID | before-image-accurate log records, crash cuts the tail, recovery redoes only transactions whose COMMIT survived |

**`ava/datagen/compress_trace.py`** (`compress_trace`, phases 2/3/4):

| Family | What the trace simulates |
|---|---|
| RLE | byte-by-byte run scanning |
| LZ77 | sliding window (16) + lookahead (8), longest-match search, (offset, length, literal) emission |
| Huffman | frequency table, deterministic heap merges, code assignment, grouped bitstream, ratio |
| Delta+varint | TSDB timestamp deltas packed as LEB128, bit-group breakdown per delta |
| INT8 quantization | `scale = amax/127`, per-element `clamp(round(x/scale))`, dequant error (neural compression) |
| Arithmetic coding + **Equal-Info Windows** | exact `Fraction` interval narrowing; flush the binary expansion of `low` when accumulated information crosses the 8-bit budget, reset per window — window resets are what keep AC output learnable instead of opaque |
| DEFLATE composition | stage-1 LZ77 triples packed as 5-bit offset \| 4-bit length \| Huffman-coded literal; both stages verified by a full unpack→expand decode |
| Magnitude pruning | k smallest \|x\| zeroed (ties by index), threshold + sparsity reported (neural compression alongside INT8 quantization) |

Wiring: `GENERATORS` registry, `configs/sources.yaml` (`synth_db_trace`,
`synth_compress_trace`, 5-6% each at p2/p3/p4, other sources rescaled so
every phase still sums to 1.0), `dolma_config.yaml` phase mixes, spec 02 §B6,
independent re-verification tests in `tests/test_datagen.py`.

## Context-window management (the hard part)

Detailed execution traces are token-hungry; a naive HNSW or B-tree trace can
blow past a phase's sequence length and get truncated mid-state, which is
actively harmful (the model would learn traces that stop without answers).
Five mechanisms keep every doc inside budget:

1. **Phase-sized instances, not truncated traces.** The curriculum phase
   decides the *input size*, so the trace never needs cutting: p2 (seq
   2048/4096) gets micro-traces of 500-4000 chars — the format and per-step
   vocabulary as foundation material; p3 (seq 8k-32k) gets medium instances;
   p4 grows the engine state (jobbench-style growth loop) until docs land in
   the 6000-12000 char long-doc band, and families that cannot grow that far
   (kv_hash, btree_insert, hnsw) are simply excluded from p4. Budgets live in
   `trace_common.PHASE_CHAR_BUDGET` / `PHASE_ELIDE_OVER`.

2. **Checkpoint elision — teach the model to compress its own trace.** At p3,
   traces beyond 28 steps collapse their middle into an explicit
   `[.. K steps elided; state checkpoint before step N: <state> ..]` marker
   whose checkpoint is the *computed true state* at the resume point
   (`trace_common.elide`). The doc stays verifiable end-to-end, and the model
   learns the inference-time skill that actually matters at deployment:
   re-anchoring from a verified state summary instead of replaying every
   step. This is the trace-level analogue of periodic checkpointing in a
   database WAL.

3. **Chunk-safe step markers.** Every trace line is `[step N]`-prefixed and
   every task inlines the complete input state, so Chonkie's
   RecursiveChunker (already phase-aware via `PHASE_CHONKIE_CONFIG` in
   `streaming_data.py`) splits at step boundaries and a training chunk never
   starts mid-state; the p3 checkpoint markers double as re-anchoring points
   for any chunk that lost the trace head.

4. **Equal-Info Windows for the one intrinsically opaque codec.** Plain
   arithmetic coding entangles the whole stream — no prefix is decodable
   without global context, so it is neither learnable nor chunkable. The AC
   family therefore resets the interval every ~8 bits of information; each
   window is independently decodable, which simultaneously makes the
   bitstream learnable and bounds the context any single decode step needs.

5. **Curriculum ordering does the rest.** Because the same families appear
   at increasing scale across p2→p3→p4 (matching the seq_len/YaRN schedule),
   long-context capability is built by *growing verified small skills*, not
   by dropping 30k-token traces on a 4k-context model. Long p4 batches are
   assembled by the existing packing pipeline from whole docs — never by
   splitting a trace across sequence boundaries mid-state.

## The eval side (closing the loop)

`evals/probe_items_gen.py` generates `db_mechanics` and `compression` probe
sets — short exact-match items (FNV-1a slots, B-tree heights, BFS distances,
RLE/varint/Huffman/quantization answers) whose ground truth reuses the very
primitives the generators run, scored by `evals/probes.py` in the branch
harness. Each probe template's fixed stem is registered in
`evals/eval_sets.py` (`SYSTEMS_PROMPTS`) so decontamination strips the probe
surface-forms from training while the differently-phrased ET-CoT docs
survive; `tests/test_probes_systems.py` re-derives every answer independently
and asserts zero stem leakage into the corpora.

## SFT rendering

For `<think>` supervision in the R1 sense, `trace_common.to_chat()` re-renders
any ET-CoT doc as a `<|user|>` / `<|assistant|>` chat sample (task as the user
turn, `<think>…</think><answer>…</answer>` as the assistant turn), and
`sft_sota_2025.py --etcot-mb N` mixes those samples into the chat-branch SFT
pack. Every family takes `(rng, n, elide_over)`, so trace length stays a knob,
not a property of the corpus.
