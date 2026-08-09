# LONGCAT2_INSIGHTS_SPEC — mapping LongCat 2.0's efficiency doctrine onto Dottie

This doc is the contract for the LongCat 2.0 adoption slice. Status per item: **BUILD-NOW**
(implementable on this box, CPU-only, pytest-gated, no frozen paths touched) or
**SPECED-DEFERRED** (design recorded here; blocked on the `apps/ava-factory/dottie/**` +
`configs/**` freeze, on GPU access, or on external repos).

## TL;DR

- LongCat 2.0 (1.6T params, trained on a non-Nvidia ASIC stack) contributes five transferable
  ideas: streaming-aware indexing, cross-layer index reuse, hierarchical (coarse-to-fine)
  retrieval, n-gram "engram" embedding tables, muP hyperparameter transfer, and multi-tier
  on-policy distillation (MOPD).
- Dottie's analog of LongCat's hardware co-design is free-tier co-design: CPU-only CI, a
  commodity 12GB-VRAM box, append-only JSONL stores. The cheap slice of each insight lands
  now; everything GPU-shaped or freeze-blocked is speced and deferred with a reversal trigger.
- Three items are BUILD-NOW, with non-overlapping file sets and pytest coverage:
  1. Streaming timeline store feeding `harness graph-plan` failure risk (scout-cli).
  2. Coarse-to-fine shard retrieval in the memory layer (ava-skills).
  3. Distillation model-load bugfix + gated multi-tier distillation ladder (ava-factory).

## Context: LongCat 2.0 in one paragraph

LongCat 2.0 pairs a sparse-attention design built hardware-efficiency-first — index layouts
matched to streaming/sequential access, a token-selection index computed once and reused
across layers, and coarse-to-fine hierarchical token retrieval — with "engram embeddings": a
large hash-bucketed table of short n-gram (up to 5-gram) representations, spending cheap
parameter memory so recurring multi-token patterns become single lookups instead of repeated
attention compute. Training stability across scales comes from muP (tune LR/init on a small
proxy, transfer width-invariantly), and post-training uses MOPD: students distilled on their
own sampled trajectories, scored by stronger teachers, tier by tier. The meta-doctrine:
co-design with the hardware actually in use, spend memory where compute is expensive, and
compute shared things once.

---

## 1. Streaming-aware indexing → a real timeline store for the harness

**Status: BUILD-NOW.** Priority 1.

The harness already pins the append-only, 7-field timeline schema
(`apps/scout-cli/bigbang/plugins/harness/cli.py:167` — nodeId, agentId, attempt, latency,
tokens, status, errorClass) and claims `G_history` in every route
(`cli.py:119`), but `graph-plan`'s python fallback admits `"fallback python — no
timeline.jsonl parsed"` (`cli.py:418`) and uses hard-coded per-role failure risk
(`cli.py:401`). This is exactly the layout LongCat's streaming-aware indexing exploits:
never rewrite, only append; index by monotonically growing byte offsets; resume reads from
the last offset instead of re-scanning. And it is "memory over compute": persist mined
per-(role, errorClass) statistics as the file grows instead of recomputing from raw events
on every planning call.

- **Target files:** `apps/scout-cli/bigbang/plugins/harness/timeline.py` (new),
  `apps/scout-cli/bigbang/plugins/harness/cli.py`,
  `apps/scout-cli/bigbang/plugins/harness/manifest.yaml`,
  `apps/scout-cli/tests/test_harness_timeline.py` (new).
- **Design:** `TimelineWriter.append` validates the pinned 7 fields, appends one JSON line to
  `~/.cache/scout/checkpoints/<run_id>/timeline.jsonl` (co-located with `checkpoint.json`)
  plus a sidecar offset index; both files are append-only so writes are O(1) and a torn last
  line is skipped on read. `g_history_stats` mines per-role fail rates / p50 latency /
  errorClass counts with a cache keyed on (path, size, mtime) — files only grow, so growth is
  the version stamp, and only the new tail is parsed. `graph-plan` replaces its constant risk
  with the mined per-role fail rate (clamped to [0.05, 0.9], constant fallback preserved on an
  empty store), and `G_history` becomes a computed summary when events exist. `checkpoint
  list` returns runs newest-first. Existing pinned tests (stickiness guard, verify
  thresholds, roster) are untouched.
- **Effort:** medium.

## 2. Hierarchical (coarse-to-fine) retrieval → ShardStore fine ranking

**Status: BUILD-NOW.** Priority 2.

The memory layer's coarse pass already exists: Tier-B scoping picks exactly one JSONL file
(`packages/ava-skills/skills/memory-mint/skill.py:201-207`). The fine pass is missing —
`query()` sorts by `minted_ts` only (`skill.py:213-224`), so retrieval is recency-only
regardless of content. LongCat's hierarchical indexing prescribes a cheap fine stage over the
narrowed candidates: a lazily built per-scope inverted token index (the same
lazy-build-then-cache pattern `_ids_for()` already uses at `skill.py:164-175`), token-overlap
scoring, and recency as the tiebreaker. Cross-layer reuse applies too: memory-router computes
the Tier-B scope at routing time and `_recall_minted` re-derives the identical scope — it is
now computed once and passed through.

- **Target files:** `packages/ava-skills/skills/memory-mint/skill.py`,
  `packages/ava-skills/skills/memory-router/skill.py`,
  `packages/ava-skills/skills/memory-mint/tests/test_memory_mint.py`,
  `packages/ava-skills/tests/test_memory_router.py`.
- **Design:** `ShardStore` gains a derived (never persisted) per-scope inverted index updated
  incrementally in `append()` and built lazily on first `query()` under the existing lock.
  `query()` keeps its exact signature; with a non-empty instruction, candidates from the
  postings union are ranked by (token-overlap, minted_ts) and recency fills to the limit, so
  result count never drops below today's. Empty-instruction queries are byte-identical to
  current behavior. `_recall_minted` gains an optional `tier_b_scope` passthrough; the frozen
  `MemoryShard` schema is untouched, so existing JSONL rows remain readable.
- **Effort:** medium.

## 3. MOPD → distillation model-load fix and a gated multi-tier ladder

**Status: BUILD-NOW (bugfix + ladder driver + gate).** Priority 1 within the training lane.

Dottie already implements the four distillation modes (mopd/privileged/earlier/offpolicy,
`apps/ava-factory/on_policy_distill.py:779-938`) but two gaps block any honest MOPD claim.
First, a defect: `get_model_from_config` passes `spike_sink_enabled=False`
(`on_policy_distill.py:319`) — a kwarg `DottieModel1B.__init__` does not accept
(`model_1b.py:544-574`) — and the bare `except Exception` at `:325` swallows the TypeError,
so every run silently trains the `MockLM` fallback. Second, there is no tier cascade and no
consumer of any eval verdict (the report-only-gate defect class recorded in HANDOFF item 10).
The LongCat-shaped fix is a ladder: distill tier k, gate the produced checkpoint
(PROMOTE/HOLD per the `tasks/artifacts/design_ckpt_eval_gate.md` policy — never promote on
error), and only a PROMOTED checkpoint becomes the next tier's teacher.

- **Target files:** `apps/ava-factory/on_policy_distill.py` (surgical bugfix),
  `apps/ava-factory/scripts/distill_ladder.py` (new; `scripts/` is not frozen),
  `apps/ava-factory/tests/test_distill_ladder.py` (new),
  `apps/ava-factory/tests/conftest.py` (module registration only).
- **Design:** drop the bogus kwarg, plumb the config's head/tie/multimodal fields, and narrow
  the except to `ImportError` so real construction errors fail loudly (honest-refusal
  invariant). The ladder driver is dependency-injected (train_fn/eval_fn) so the gate logic
  is fully testable on CPU with tiny models and canned metrics; promotions append provenance
  rows (checkpoint sha256, verdict, teacher lineage) to an append-only JSONL. Real ladder
  runs need GPU plus checkpoints that do not exist yet — only the bugfix, driver, gate, and
  tiny-model tests are claimable now, and the tests say so.
- **Effort:** medium.

## 4. Cross-layer reuse / compute-once in the harness route pipeline

**Status: SPECED-DEFERRED (file-set conflict, lowest ceiling).**

`_score_intent` recompiles string regex patterns per call (`harness/cli.py:50`),
`_complexity` re-runs `re.findall` (`cli.py:63`), and `ops` re-reads and re-parses its JSON
inputs on every invocation (`cli.py:206-217`). The remedy — module-level compiled patterns, a
single shared feature pass, an mtime-keyed JSON cache, and an `elapsed_ms` measurement hook —
is behavior-preserving and small, but it edits the same `harness/cli.py` the BUILD-NOW
timeline item edits, and the MCP server dispatches each tool call as a fresh subprocess, so
the payoff is limited to tests and any future long-lived in-process server. Deferred to the
change immediately after item 1 lands, on the same regression net (the pinned harness tests).
Likewise deferred: per-tier token/latency/attempt budgets as a `harness budget` gate — its
defaults must be pre-registered in a dated review artifact before any run data is examined,
which belongs in its own session together with the required HANDOFF refresh.

## 5. Engram embeddings → hashed n-gram table for DottieModel1B

**Status: SPECED-DEFERRED (freeze-blocked; profiler first).**

The model-side design is a config-gated, default-off `EngramEmbedding` (hash-bucketed
2..5-gram table, zero-init scalar gate for byte-identical logits at init, AdamW-managed,
causal hashing that must pass the T6.1 causality suite) added into the token-embedding sum in
`model_1b.py`, sized by a torch-free numpy corpus profiler that measures n-gram recurrence
and hash-collision rates per bucket count so the parameter spend is evidence-backed rather
than assumed. Both pieces target `apps/ava-factory/dottie/**`, which is FROZEN (bind-mounted
into the live trainer), so no code lands now. Before any implementation, the house convention
applies: a dated adopt/decline review artifact in `tasks/artifacts/` with hardware arithmetic
for the 12GB-VRAM box and a recorded reversal trigger, then a numbered spec in
`apps/ava-factory/specs/` following the Spec 11 pattern (default-off gate, regression test,
measured accept criteria on nano before any base1b decision). The vector-MTNN variant (an
engram pattern token in `TransformerFusion`) is likewise deferred: the training entrypoints
that could earn the accuracy claim live in external vector-* repos and must pass the
candidate-then-promote scoreboard gate there.

## 6. muP → width-invariant transfer across the nano/mini/base1b ladder

**Status: SPECED-DEFERRED (module + coordinate check are cheap; wiring is freeze-blocked).**

muP is genuinely absent from the repo; the scale ladder trains as three independent runs with
hand-set WSD schedules. The recorded design: a root-level `apps/ava-factory/mup.py` (root is
not frozen) with a `MupSpec`, muP-style init mirroring `init_weights`, an optional
`logit_scale` constructor arg (default 1.0, byte-identical) because the tied lm-head forbids
textbook output-layer scaling, and param groups riding the existing per-group
`lr_scale` multiplier in the trainer. Muon-managed matrices are excluded from muP lr scaling
until the interaction with Muon's own width-dependent RMS rescale is measured. The CPU
coordinate check (activation scale bounded across widths under muP, growing without it) is
implementable, but the optimizer/config wiring touches frozen `dottie/train.py` and
`configs/**`, and the transfer claim itself (proxy-tuned LR within 2x of directly tuned after
a fixed token budget, seeds 0/1/2) requires GPU runs. Lands as Spec 14 with a dated review
artifact first, once a session can also carry the freeze-lift diffs.

## 7. True on-policy rollouts for the MOPD tier

**Status: SPECED-DEFERRED (depends on item 3's bugfix; small).**

The current "mopd" mode computes reverse KL on dataloader batches — off-policy data with an
on-policy loss. The defining MOPD property is distilling on student-sampled trajectories with
the KL masked to generated positions only. Design: a `rollout_batch` sampling primitive
(sequential, no KV cache — correct first, fast later), a `--rollout` flag on the mopd mode,
and a generated-positions-only mask into the existing `reverse_kl_loss`
(`on_policy_distill.py:183-239`), with rollout entropy logged so degenerate early-student
rollouts are visible rather than hidden. Deferred one step behind item 3 because until the
model-load fix lands, rollout code would only ever exercise the mock model.

---

## Verification

- Item 1: `cd apps/scout-cli && uv run pytest tests/test_harness_timeline.py tests/test_harness_vector.py`
- Item 2: `cd packages/ava-skills && uv run pytest skills/memory-mint/tests/test_memory_mint.py tests/test_memory_router.py`
- Item 3: `cd apps/ava-factory && AVA_FACTORY_ROOT="$PWD" uv run pytest tests/test_distill_ladder.py tests/test_audit_fixes.py`

All three run CPU-only. No frozen path (`apps/ava-factory/dottie/**`, `configs/**`) is
modified by any BUILD-NOW item.

---

Solo personal project, no connection to employer, built with public/free-tier only.
