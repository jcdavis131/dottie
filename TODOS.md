# TODOS — Continuous Pipeline

Foreman updates after every dispatch and verification. A task is `done` only when the foreman has
**run its acceptance command and seen it pass** — never on a worker's word.

Tiers: 🟦 Sonnet (mechanical) · 🟪 Opus (correctness-critical) · 👷 foreman/human

---

## Stage 0 — Host prep ✅
- [x] **T0.1** Identify the 1.8GB GPU process — **NOT stray**: it is `vector-hoops/pipeline/sweep_v5.py --epochs 40 --seeds 7,13,21 --device cuda --resume`, a live sweep. Left running. nano/mini (~5-7GB) coexist; base1b needs it gone.
- [x] **T0.2** `docker builder prune -a` → **reclaimed 25.06GB** (est. was 14GB). Volumes untouched.
- [x] **T0.3** Re-measure. C: shows 26.8GB free; Docker freed 25GB *inside* its 45GB ext4 VHDX, which it reuses before growing. Effective headroom ≈ 50GB. `image prune` not needed.
- [x] **T0.4** `.wslconfig` written (`memory=10GB`, `processors=24`, `swap=8GB`, `sparseVhd=true`). ⚠️ Needs `wsl --shutdown` + Docker Desktop restart to apply — **deferred, requires your OK** (stops all distros).
- [x] **T0.5** Volumes `ava_{raw,packed,ckpt,state,reports}` created **and chowned to uid 1000** (docker creates them root-owned; the manifest could not create its DB).

## Stage 1 — Docker infrastructure ✅
- [x] **T1.1** 🟦 `docker/Dockerfile.cpu` — *accept:* streams 2 TinyStories rows in-container ✅
- [x] **T1.2** 🟦 `docker/Dockerfile.gpu` — based on `python:3.11-slim` + cu124 wheels (not `nvidia/cuda:*-runtime`: the wheels vendor their own CUDA libs, saving ~5GB). *accept:* `torch.cuda.is_available()` + bf16 matmul on the 4080 ✅
- [x] **T1.3** 🟦 `docker-compose.yml` (collector×4, curator×6, trainer, server, janitor; named volumes; GPU reservations) — *accept:* `docker compose config` valid ✅
- [x] **T1.4** 🟦 `Makefile`, `.dockerignore`, `.env.example`, `.gitattributes` (CRLF breaks make recipes and shebangs in Linux containers) ✅

## Stage 2 — Manifest + shard flow ✅
- [x] **T2.1** 🟪 `ava/pipeline/manifest.py` — WAL SQLite, `BEGIN IMMEDIATE` atomic claims, leases + requeue, state-machine guards, tokenizer freeze gate, resumable cursors, structural val/test protection
- [x] **T2.2** 🟪 `ava/pipeline/flow.py` — backpressure predicates, `DATA_STARVED`, phase prefetch
- [x] **T2.3** 🟦 `configs/pipeline.yaml` — watermarks sized for this host
- [x] *accept:* **28 tests** — 12 threads + 4 processes over 1000 shards: zero double-claims, zero lost shards. **Negative control:** downgrading to `BEGIN DEFERRED` makes it fail, so the test is not vacuous ✅

## Stage 3 — Collector ✅
- [x] **T3.1** 🟪 `ava/pipeline/collector.py` — HF streaming, backoff+jitter, resumable cursors, 256MB zstd shards, atomic publish (`.tmp`→fsync→`os.replace`→register), backpressure-aware. *accept:* 15 offline tests ✅ + **live**: streamed 500 TinyStories docs, restarted, resumed at cursor 500 with no duplicate doc_ids ✅
- [x] **T3.3** 🟦 `configs/sources.yaml` — 11 sources, all verified `200` + `gated:false` against the HF API. `bigcode/the-stack-smol` excluded (`gated:"auto"`). Per-phase weights sum to 1.0 (asserted)
- [x] **T3.2** 🟦 `ava/datagen/*` — logic / math / encyclopedia / code / chat_safety. 35 tests that check **content**: an independent proof checker re-derives each natural-deduction proof; every math answer is recomputed; every code snippet is re-exec'd; spider→8 / ant→6 / France→Paris never contradicted with ≥40 paraphrases each. Byte-deterministic.
- [x] **T3.4** 👷 **Reconciled.** Deleted the collector's inline toy generators (a stub logic doc, a hardcoded refusal) in favour of `ava/datagen`. Three bugs surfaced: the registry was **relabelling** generator output (needle docs were phase-1 arithmetic stamped phase-4); needle actually lives in `EncyclopediaGenerator`, not `MathGenerator`; and cursors keyed by source alone would make a multi-phase generator resume into the wrong subsequence (now per `(source, phase)`). `synth_code` had no registry entry at all. *accept:* cpu 97 / gpu 56 ✅ + live shard written and inspected ✅

## Stage 4 — Curator ✅
- [x] **T4.1** 🟪 `clean.py` — normalize / is_english / Gopher heuristics / edu_score / PII scrub (conservative: leaves `0xDEADBEEF`, bare digit runs)
- [x] **T4.2** 🟪 `dedup.py` — sha256 exact + MinHash LSH (9×13 bands @ 0.8) in its own WAL DB; `add_if_new` is check-and-insert in one `BEGIN IMMEDIATE` for cross-replica safety
- [x] **T4.3** 🟪 `decontaminate.py` — 13-gram + short-phrase floor (≥5 words). **Both directions tested**: every eval prompt is removed; "Spiders possess eight legs." is kept
- [x] **T4.4** 🟪 `split.py` — `bucket(sha1(doc_id))`, order-invariant, rerun-stable
- [x] **T4.5** 🟪 `pack.py` — uint16 `.bin` + `.idx.json`, vocab≤65535 asserted, frozen-tokenizer gate
- [x] **T4.6** 🟦 `curator.py` service loop; SIGTERM-graceful; `fail()` never crashes the container
- [x] *accept:* 19 curator tests, **62/62 suite** ✅
- [x] **Deviation accepted:** `complete()` **before** deleting raw. Spec said the reverse; the worker was right — deleting first then crashing would requeue a row whose raw file is gone, losing data. Worst case now is an inert orphaned file.

## Stage 5 — Tokenizer bootstrap + throughput gate 🟡
- [x] **T5.1** 🟦 Bootstrap corpus collected across phases 0/1/2/5 (synthetic + tinystories)
- [x] **T5.2** 🟦 `ava/tokenizer.py` — byte-level BPE, specials pinned to ids 0–5, atomic save, sha256 → manifest. **Live:** nano 8192-vocab trained on the real corpus, `roundtrip=ok chars/token=3.28`, frozen as `8f609ef4b82e`. 11 tests
- [x] **T5.3** 👷 **Data plane proven end-to-end:** collector → curator → 16 PACKED shards, 0 RAW, 0 FAILED, `raw_bytes=0` (raw deleted after packing). 373,438 tokens across train/val/test; packed uint16 decodes back to the source text
- [x] **T5.4** 🟦 `scripts/bench_pipeline.py` — *accept:* curation tok/s ≥ 3× trainer tok/s. **Measured (nano, host CUDA):** collector ~438k tok/s, curator **62.4k tok/s**, trainer **10.1k tok/s**, ratio **6.15×** → GATE PASS. JSON: `reports/bench_pipeline.json`

### Bugs found by running it (not by reading it)
- **`pack.py` crashed on every HF shard** (`TypeError: TextInputSequence must be str`): `d.get("concept", "")` returns `None` for an explicit JSON null, and only synthetic docs carry a concept.
- Worse, the fallback tagged untagged docs with `<|endofdoc|>`. HF is most of the corpus, so the reportability loss would have learned to "report" end-of-document. Untagged docs now carry `UNTAGGED_CONCEPT = -1` and `ava/jlosses.py` masks them out of the report loss.
- `decode()` stripped `<|user|>`/`<|assistant|>`, which are real tokens in the chat corpus, not decoration. `skip_special` is now explicit: default on for serving, off for round-trip fidelity.

## Stage 6 — Model + trainer ✅
- [x] **T6.1** 🟪 Model fixes — **the big one.** *accept:* 28 tests ✅
  - [x] Causal mask (SDPA). Bare transformer stack now measures **exactly 0.0** logit change at positions < t
  - [x] **J-Space was non-causal**: it mean-pooled the whole sequence and broadcast it everywhere (measured leak ~0.20). Now **chunk-recurrent** — broadcast into chunk *c* comes only from chunks < *c*
  - [x] `rotate_half` half-split (was interleaved, disagreeing with cos/sin → garbage rotation)
  - [x] `_prev_workspaces` detach + batch guard (backward-through-freed-graph on step 2)
  - [x] `JacobianLens.top_concepts` implemented (was dead → `verbalizable_mass` constant 0.06)
  - [x] Verbalizer tied to lm_head (was allocating 2×[V,D] per workspace, discarding one)
  - [x] **Initialization** wired: init loss 196 → **9.07** vs ln(8192)=9.011. Overfits one batch to 0.05/30 steps
  - [x] GQA + SwiGLU + gradient checkpointing (config-gated, causality-tested)
  - [x] Param counts corrected: nano 13.8M, mini 171.3M (was 270M — `tie_verbalizer` must stay true), base1b **1409M** (spec said 1.17B)
- [x] **T6.2** 🟪 `ava/jlosses.py` — combined objective with blueprint weights
- [x] **T6.3** 🟪 `ava/data.py` — `StreamingShardSampler`: memmapped shards, `task_type`-pure batches, blocks with `DATA_STARVED` not a crash, hands its claim back on exit. 8 tests
- [x] **T6.4** 🟪 `ava/train.py` — WSD, phase manager + RoPE transitions, grad-accum, bf16 autocast, AdamW8bit, checkpoint/`--resume`, `metrics.jsonl`, `--branch chat --init` with a real `load_state_dict`. 7 tests
- [x] **NANO SMOKE PASSED** on the RTX 4080: `lm 9.053 → 3.400` in 30 steps at **~18–20k tok/s**, 13.79M params, checkpoint written, `--resume` verified (run A ends step 10 @ 7.605 → run B resumes and reaches step 20 @ 5.84, matching the single-run 5.947 within data-order variance)

### Bugs found by running it (again, not by reading it)
- **The sampler starved the trainer forever.** It refused to let a window straddle a document; the synthetic corpus has a **median doc of ~100 tokens**, so at `seq_len=256` phases 1 and 5 produced *zero* windows. Docs are now concatenated with `<|endofdoc|>` separators — but only within one `task_type`, so the routing-KL target stays well defined.
- **`modulation` was a loss term that could never fire.** It computed `cos(bc, bc.detach())` against `cos(0, bc)`; `cos(x,x) ≡ 1`, so the hinge was `relu(0.5 − 1.0) = 0` for every input that has ever existed. Now compares `cos(fused+bc, bc)` vs `cos(fused, bc)` and is measurably decreasing (0.4965 → 0.4704 over 30 steps).
- **`selectivity` was gameable and invisible**: raw slot variance can be minimized by shrinking every activation, and at ~2.6e-7 it was being logged as `0.0` by `round(v, 5)`. Now scale-normalized and logged to 4 significant figures.
- **The trainer leaked its shard lease on every exit.** Four runs locked all 936k phase-0 tokens in `CLAIMED_TRAIN`, and the next run starved on data it already owned. Added `Manifest.release_claim()` — a clean handback that, unlike `fail()`, does **not** burn an attempt (three ordinary restarts would otherwise have parked a good shard in `FAILED`).

> `--resume` is **loss-continuous, not bit-exact**. Model/optimizer/step/phase/RNG restore exactly, but the shard set is live, so data order cannot be reproduced. Bit-exactness needs an as-of manifest watermark (T10.5).
- [x] **T6.5** 🟦 `ava/pipeline/janitor.py` — watermarks, delete CONSUMED (never val/test), ckpt rotation ✅

## Stage 7 — Real evaluation harness ✅
- [x] **T7.1** 🟪 `evals/perplexity.py` — val/test PPL on heldout bins (`scripts/build_eval_data.py` builds tokenizer + heldout) ✅
- [x] **T7.2** 🟪 `evals/probes.py` + `evals/probe_items/*.jsonl` (200 items/set, seed 1234) ✅
- [x] **T7.3** 🟪 `evals/jspace_tests.py` + `evals/interventions.py` — real `_emit` hooks; `concept_vector` uses `concept_token()` fallback for multi-piece BPE (deviation from spec 06 single-token assert) ✅
- [x] **T7.4** 🟪 `evals/needle.py` — native 1024 + YaRN 2048 pass-key retrieval ✅
- [x] **T7.5** 🟪 `evals/run_harness.py` → `reports/branch_eval_results_real.json` + `REPORT_REAL.md`. *accept:* eval tests **6 passed**; harness smoke **37–56s** wall; full suite **120 cpu + 89 gpu** ✅

## Stage 8 — Live serving
- [x] **T8.1** 🟪 `ava/serve_engine.py` — real `generate` / `inspect` / `intervene` (+ `runs/serve_audit.jsonl`) ✅
- [x] **T8.2** 🟪 `server.py` — fix `from typing import Optional` (import-time `NameError`), pydantic-v2 `Field(alias="from")`, wire to engine, keep the 403 gate, add `/health` `/generate` `/report` ✅
- [x] **T8.3** 🟪 Hot-reload `ckpt/latest` — experiment against the model *while it trains* ✅
- [x] **T8.4** 🟦 `scripts/make_report.py` → self-contained `reports/index.html` (no CDN). *accept:* 18040 bytes; `cdn|https://fonts` count 0; also writes `report_real.html`
- [x] **T8.5** 🟦 `scripts/smoke_live.sh` (+ `smoke_live_checks.py`, root `Dockerfile`/`run.sh`) — *accept (partial):* `AVA_SMOKE_DRY_RUN=1` → **SMOKE PASS** (health/generate/inspect/intervene-403/eval_branch/report/intervene-write via ASGI fake engine); missing ckpt → clear **SMOKE FAIL ckpt** (non-zero). **Full live** `AVA_CKPT=runs/chat/ava_nano_chat.pt bash scripts/smoke_live.sh` **deferred to T9.1** (ckpt absent). Also: minimal Stage-8 `Dockerfile` + `run.sh` (compose remains primary).

## Stage 9 — Scale ladder
- [x] **T9.1** 👷 nano smoke: all five services, ~10 min. Gate = *the loop works* — *done 2026-07-10:* nano `base_final.pt` step **3662** / ~30M tok; trainer **already_done** + compose `restart: on-failure` (no resume spin); collectors/curators/janitor/server healthy; `AVA_BASE_URL=http://127.0.0.1:8000 bash scripts/smoke_live.sh` → **SMOKE PASS** on base weights; short chat fork `/ckpt/chat/chat_final.pt` (80 steps). Full chat budget (3M tok) remains T9.5.
- [ ] **T9.2** 👷 mini (171M, ~2.5B tokens, 3–5 days). Watch `hl_est → target`, `route_probs` separating by `task_type`, val PPL ↓. Serve throughout — *in progress 2026-07-10:* 32k tok (`d5ac2900acde`); trainer stepping (**~step 140+**, ~7–8k tok/s steady, ~9.7GB VRAM, loss 11.5→~0.24 on synth P0 — expected template collapse, not quality). P0 runway ~304M. **Disk fix shipped:** host `/host_disk` probe + trainer-starved-only raw-cap bypass (was filling ~40GB RAW while VHDX reported 987GB free). Collectors auto-pause below 12GB host free; janitor eviction live. Server stopped (GPU). ETA ~3–4 days at ~7.5k tok/s.
- [ ] **T9.3** 👷 **GO/NO-GO** for base1b, on mini's `reports/eval_real.json`. Also decide the base1b trim: 1409M × (bf16 weights + grads + AdamW8bit) = 8.4GB before activations, against ~11.6GB. Options: drop `n_fusion_layers` 28→24 (−92M), or narrow the workspaces
- [ ] **T9.4** 👷 base1b milestones M1 2B → M2 10B → M3 30B+
- [ ] **T9.5** 👷 Branch fine-tunes (code/math/chat) from any stable checkpoint

## Stage 10 — Continuous supply, streaming ingestion & storage at scale (cross-cutting; underpins Stages 6–9)
The primitives already exist — backpressure + `phase_next` prefetch + `DATA_STARVED` (`flow.py`, T2.2),
`StreamingShardSampler` (T6.3), janitor watermarks (T8.5). This stage turns them into a **curriculum-aware,
stay-ahead control loop** over **bounded memory** feeding a **bounded, versioned, ever-growing store**.
Nothing here re-implements Stage 2/4; it is the governor, the reproducible view, and the retention policy on top.

- [ ] **T10.1** 🟪 `ava/pipeline/pacer.py` — **curriculum pacing controller.** Reads the trainer's live phase + consumption rate from the manifest and holds a target **lead buffer** of PACKED tokens per phase (≥ `lead_steps × global_batch_tokens`, for `phase_current` **and** `phase_next`), continuously reweighting collector + datagen effort toward the phase the trainer will reach next. A setpoint on runway, not the existing on/off backpressure. *accept:* a simulated trainer draining P0→P5 at varying tok/s never sees `DATA_STARVED` > a few s at any transition; per-phase runway stays in `[lead, high-water]` across a replayed trace. Deps: T2.2, T6.3.
- [ ] **T10.2** 🟪 **Infinite-generator governor** — `ava/datagen/*` emit unbounded data; gate production per `(source, phase)` on that phase's runway *deficit* so P0 can't overproduce and evict P5's disk budget. Deterministic resume (extends the per-`(source,phase)` cursor from T3.4). *accept:* under a tight disk cap all six phases still reach their lead target, no phase starves another, byte-deterministic across restart. Deps: T3.2, T3.4, T10.1.
- [ ] **T10.3** 🟪 **Bounded-memory streaming ingestion** — trainer/curator RSS stays flat regardless of corpus size: `np.memmap` the uint16 `.bin` (no full-shard loads), fixed-size prefetch queues across claim→decompress→collate, a bounded shuffle buffer (shard-shuffle + intra-buffer), pinned-memory + async H2D double-buffering to overlap load with compute, and no-padding sequence packing at each phase's seq-len. Extends T6.3. *accept:* trainer RSS bounded across a 100k-step run over a corpus ≥ 50× RAM; GPU util ≥ target at prefetch depth 2; **zero** pad tokens in `task_type`-pure batches. Deps: T6.3, T4.5.
- [ ] **T10.4** 🟪 **Live throughput invariant** (makes T5.4 continuous) — `curation_tok/s ≥ trainer_tok/s` **and** `production_tok/s ≥ trainer_tok/s` enforced as a *running* gauge; the pacer scales curator/collector replicas (compose) or trips backpressure when the ratio dips. *accept:* an injected trainer speedup auto-triggers more curator concurrency and the ratio recovers within N min. Deps: T5.4, T10.1.
- [ ] **T10.5** 🟪 **Reproducible dataset view / as-of watermark** — an expanding store makes "resume" ambiguous. Pin each run to a manifest **watermark** (monotonic shard-registration id) so resume and re-run see a deterministic, replayable data order; record `watermark + tokenizer_hash + curriculum_weights` in the checkpoint. *accept:* kill+resume at step K reads the identical next-shard sequence bit-for-bit; a fresh run at the same watermark+seed reproduces `metrics.jsonl` order. Deps: T2.1, T6.4.
- [ ] **T10.6** 🟪 **Frozen eval snapshots vs. growing train** — val/test buckets grow too as generation continues; freeze a **named val/test snapshot** (shard-id set) per scale rung so PPL/probe numbers are comparable across M1→M2→M3 while train keeps expanding. Structural val/test protection (T2.1) already prevents leakage; this adds comparability. *accept:* two milestones evaluate on byte-identical val/test token streams; new data never silently changes a past milestone's eval set. Deps: T2.1, T7.1.
- [ ] **T10.7** 🟪 **Unique-token accounting + replay policy** — define epoch semantics under single-pass delete-after-consume when a phase's *unique* supply < what the trainer needs (likely for base1b's ~20B). Track unique-tokens-seen per phase via the dedup DB (T4.2); on exhaustion either block for fresh collection or do **controlled** replay with a re-shuffle and a logged `replay_epoch` — never silent back-to-back re-showing of the same synthetic docs (memorization). *accept:* a phase forced into replay shows re-shuffled order + `replay_epoch`, and dedup confirms no doc repeats within window W. Deps: T4.2, T10.1.
- [ ] **T10.8** 🟦 **Shard compaction + addressable index** — many small shards hurt open/seek and manifest bloat; a compactor merges undersized PACKED shards per `(phase, split, seq_len)` and maintains a compact index so any `(phase, task_type, split)` subset is directly addressable without a full scan. Respects the frozen-tokenizer + val/test gates. *accept:* post-compaction shard count ↓, mean shard ≈ target size, sampler reads an unchanged token stream (sha256 of concatenated tokens per subset stable). Deps: T4.5, T2.1.
- [x] **T10.9** 🟦 **Storage retention + disk high-water eviction** — on a single 28GB drive an ever-growing corpus needs more than delete-CONSUMED: high-water eviction that sheds the *least-curriculum-useful* RAW/PACKED first (over-supplied phases, oldest, lowest `edu_score`), **never** val/test, **never** a phase under its lead target. Extends the janitor (T8.5). *accept:* under a synthetic disk-fill, eviction keeps free-disk in band and never drops a phase below lead; no val/test byte ever deleted. Deps: T8.5, T10.1. — *done 2026-07-10:* `ava/pipeline/eviction.py` + janitor wire-up; lead floor = `packed_min_tokens`; `storage.evict_high_water_gb` in `pipeline.yaml`; tests in `tests/test_eviction.py`. (Full pacer lead_steps still T10.1.)
- [ ] **T10.10** 🟦 **Supply observability** — `metrics.jsonl` + `/report` expose per-phase runway (steps & tokens), lead/lag vs setpoint, `DATA_STARVED` counters, production/curation/train tok/s + ratios, unique-tokens-per-phase, disk headroom, and `replay_epoch`s. This is how a human confirms "steady state = success" (PLAN.md). *accept:* a nano smoke shows all six phases' runway live; a forced starvation is visible within one scrape interval. Deps: T8.4, T10.1.

## Stage 11 — Architecture hill-climb: 2026-07 open-weight review
Candidates from a six-model open-weight review (Zaya1, VibeThinker-3B, DeepSeek V4 Flash, Qwen 3.6, Gemma 4),
mis-filed into `vector-hoops` (a small tabular model with no KV-cache) by a prior session and reverted there.
Mapped here to real tasks against `AvaModel1B`'s actual GQA transformer and open risk #1 (base1b VRAM).
Full contract: `specs/11_arch_hillclimb.md`.
- [x] **T11.2** 🟪 Gated DeltaNet fixed-state layer — `DeltaNetBlock` in `model_1b.py`, swappable for
  `TransformerBlock1B` via `AvaModel1B(deltanet_layers=[...])` on a subset of `fusion_layers` (default
  unset = zero behavior change, checked by a regression test). Sequential delta-rule scan (Yang et al.
  2024), causal by construction — no mask to get wrong, since state at t is built only from tokens ≤ t.
  4 new tests in `tests/test_model.py`, **32/32 passing** (28 existing + 4 new): standalone block
  causality, state-size invariance across L=16→128, full-model causality with a DeltaNet layer mixed in,
  and the default-off regression guard. **Analytic VRAM** (base1b's real config: d_model 2048, 16 heads/4
  KV heads GQA, head_dim 128, 28 fusion layers; 3 DeltaNet : 1 full-attn = 21/7 split): fixed state
  21×1.05MB ≈ 22MB total vs. growing bf16 KV-cache — 2.3x smaller at L=2048, rising to **3.95x at
  L=131072** (7.52GB → 1.90GB). Numbers are this repo's own dims, not the vendor's. **Not yet measured:**
  live `torch.cuda.max_memory_allocated` peak and the needle-in-haystack state-size check at 2x/4x/8x —
  deferred; the GPU is occupied by the live mini run (T9.2) and this doesn't need to jump the queue.
  Not wired into `AvaConfig`/`ava/model.py`/`configs/*.yaml` yet — that's the adoption step, gated on the
  live-GPU numbers above, not a decision to make speculatively.
- [ ] **T11.1** 🟪 Compressed-latent attention block (Zaya1-style) — alternate KV-reduction path, lower
  priority than T11.2.
- [ ] **T11.3** 🟦 Sparse/compressed KV + disk streaming at long context (DeepSeek V4 Flash-style) — blocked
  on a real base1b context target; do not build speculatively.
- [ ] **T11.4** 🟪 MatFormer-nested scale ladder (Gemma 4-style) — training-curriculum redesign, needs its
  own spec (`12_matformer_ladder.md`) before touching `ava/train.py`; do not disturb the in-progress mini run.
- [ ] **T11.6** 🟦 Markovian recursive trace aggregation (Zaya1-style, k=4 parallel traces → bounded 256-tok
  aggregation) — decode-time only, no causality gate needed; needs a `k_traces` path in `ServeEngine.generate`
  that doesn't exist yet. Lower priority; wait for a serve target where 4x sampling cost is affordable.
- [ ] **T11.7** 🟦 VibeThinker-style 2-stage SFT + MaxEnt RL + self-distill recipe for the Math branch —
  training-recipe candidate for T9.5, not a `model_1b.py` change. `sft_sota_2025.py` is currently a 2-line
  stub; blocked on T9.3/T9.5 same as the rest of branch fine-tuning.
  *2026-07-17 — contract written, still blocked:* MAI-Thinking-1 hill-climbing review integrated
  (`docs/RL_INTEGRATION.md`); buildable GRPO-lite contract with the three-mechanism discipline system
  (entropy thermostat, outer ratio clip, trace-bank recovery), verifiable `rl_return` provider, and
  difficulty-scaled length penalty is now **`specs/12_rl_training.md`** (T12R.1–T12R.4); plan in
  `tasks/plan-rl.md`. GPU-free piece landed now: `efficiency_gain.py` (EG_FLOPs/EG_Time vs baseline
  scaling curve + 2-rung ladder promote/hold verdicts, `tests/test_efficiency_gain.py` 15/15) — use it
  to gate this recipe (and every other lever) across nano→mini before base1b. Implementation of
  T12R.1 (returns provider, GPU-free) may start any time; T12R.2+ stays blocked on T9.3/T9.5.
- [ ] **T11.9** 🟪 CodeAct / LLM-VM — code as the model's action substrate (spec 13, 2026-07-17).
  Turns narrated ReAct (`ava/datagen/react_tools.py`, nothing executes) into an executable action
  space: the model *thinks in code*, running Python in a persistent sandboxed LLM-VM with tools bound
  as callables and real stdout/return values as observations. Contract **`specs/13_codeact.md`**
  (T13C.1–T13C.6); plan `tasks/plan-codeact.md`. An **agentic mode of the spec-12 GRPO loop** (reuses
  the discipline system + difficulty-scaled length penalty), adding `R_exec` (penalize non-executing
  code) and `R_codeuse` (reward independent tool calls, penalize redundant ones — the MAI tool-use
  finding). Builds on existing hooks: `ava/datagen/code_gen.py` `run_sandboxed`, `ava/serve_engine.py`.
  **Sandbox + datagen + eval halves (T13C.1–T13C.3) are GPU-free and may start now**; RL halves inherit
  the T9.3/T9.5 block. Answers the "leverage tools to execute workflows we care about" goal as a
  trainable, verifiable objective.
  *2026-07-17 — T13C.1 landed:* `ava/rl/codeact_sandbox.py` (`Sandbox`/`Observation`) — persistent-
  namespace LLM-VM via a long-lived worker subprocess, per-step wall cap (setsid + killpg), POSIX
  resource caps, guarded `open`/blocked `socket`/`os.fork`, importable-or-source tool binding with
  call accounting, frozen clock + fixed PYTHONHASHSEED for byte-identical replay. `tests/
  test_codeact_sandbox.py` 14/14 (all five accept criteria: namespace persistence, infinite-loop/
  fork-bomb containment, socket/out-of-scratch-write blocked, deterministic replay, no fabrication).
  *T13C.2 landed:* `ava/datagen/codeact.py` (`CodeActGenerator`) — 4 executable families (compute/tool/multistep/recover) with a grounding-share floor; answers computed by running code (no randomness/wall-clock in emitted code ⇒ in-process answer == subprocess-sandbox answer, proven by re-executing every trajectory through the T13C.1 Sandbox). `tests/test_codeact_datagen.py` 10/10. *T13C.3 + T13C.4-rewards landed:* `evals/codeact_eval.py` (real sandbox scoring engine `score_emission` + seed-sensitive `simulate_policy_eval` plumbing check + honest-fail real path, gated on T13C.5) and `ava/rl/codeact_rewards.py` (`r_exec`/`r_codeuse`/`r_len`/`codeact_return`, pure + tested against real sandbox logs). *T13C.4/5/6 GPU-free halves landed 2026-07-17:* `ava/rl/grpo.py` (GRPO-lite discipline mechanics — group advantages, entropy-thermostat integral controller, outer ratio-clip breaker, trace-bank uniform recovery sampling; a synthetic control-systems plant shows the thermostat holds the entropy band ≥10× longer than the κ=0 ablation, 29 tests); `ava/rl/codeact_loop.py` (pluggable-Policy decode/serving loop emit→sandbox→observe→FINAL, sanitized user output + captured trace, driven end-to-end by a model-free `TrajectoryReplayPolicy`, 12 tests) + `ava/rl/codeact_consolidation.py` (MOPD trace-pool prep: verified-only + stratified, 10 tests); `ava/rl/codeact_eg_gate.py` (thin `eg_trend` adapter, success→error transform, 8 tests). `run_codeact_eval` now wired to the real decode loop. Full spec-13/12 suite 133/133 (+1 skip). **Still HARD-GATED on branch fine-tunes (T9.3/T9.5) + GPU (BLOCKED_NO_GPU):** the torch GRPO optimizer step, the real-model policy, the MOPD distillation run, and the EG verdict — each **refuses** rather than fabricating (the honest boundary between built math and the climb itself).
  *2026-07-17 (later): the code-gates are now CLOSED — only resource-gates remain.* The nano CPU pilot (its config's stated purpose) ran REAL end-to-end in-container via `scripts/cpu_pilot_e2e.py`: 17.8MB corpus from 6 real generators → real BPE tokenizer (vocab 8192) → 47 packed shards → 90-step nano pretrain (lm 9.08→3.09) → **real `--branch agentic --init` fork** (lm 2.88→2.30, system1/system2 frozen) — the T9.3/T9.5 *mechanism* executing for the first time. The **real torch GRPO step** (`ava/rl/grpo_torch.py`, exact parity vs the pure-math spec, bandit learning demo 0.28→1.0, spike+overflow NaN-survival) and the **real decode policy** (`ava/rl/codeact_policy.py`, seeded autoregressive decode, machinery-verified on the real nano AvaModel) landed, and `scripts/rl_smoke_update.py` executed a REAL GRPO update on the REAL branch checkpoint from REAL CodeAct rollouts (grad_norm 2.484, param_delta 3.1e-2, bit-identical rerun; honest r_task=0 — a 115-step 14M model emits noise, as expected). Evidence: `runs/cpu_pilot/MANIFEST.json` (scale=smoke_cpu_pilot, capability_claim=none). Adversarial verification: 4 skeptics, 5 findings (1 HIGH — float32 exp-overflow NaN in the ratio backward — fixed with a log-space cap + regression test; rest applied). **Remaining gates are purely resources:** capability-scale climbs (mini+, GPU wall-clock), the MOPD merge, and the EG verdict (needs real 2-rung capability curves).
- [ ] **T11.8** 🟦 Zero-init attention output for router health at init (MAI-Thinking-1 finding, 2026-07-17) —
  uniform attention softmax at init ≈ average pooling → homogenized token representations → softmax *routing*
  (their MoE gate; our J-Space Router) can't differentiate tokens → persistent imbalance from step 0. Fix:
  init attention-output RMSNorm gains to **0** so the net starts as per-token dense layers and cross-token
  interaction fades in. `docs/blueprint/network_init_sota.py` (blueprint scaffolding) currently fills all norm gains with 1.0 — candidate change is
  ~3 lines gated behind a flag. Falsify on nano: routing-KL health + `spider_ant`/`france_china` measured
  early-step, zero-init vs ones-init, same seed; keep only if router imbalance at init measurably improves
  without hurting nano PPL at convergence. Do not disturb the live mini run. Context: `docs/RL_INTEGRATION.md`
  "Second-pass findings".
- Per-layer phone embeddings and discrete-diffusion decoding are recorded as **out of scope** in the spec —
  they target problems (phone deploy, non-causal decoding) this project doesn't have.

## Stage 12 — Workflow data: JobBench + GAIA2 synthetic generators
`workflow_jobbench`/`workflow_gaia2` had been dangling string labels in the blueprint docs
(`dolma_config.yaml`, `streaming_data.py`, `inner_monologue_research.md`) for phases 3-5 since before this
repo had a real `ava/datagen/` at all — referenced in mix weights, never built. This stage builds them for
real, on the actual live nano pipeline (not the 1B blueprint), modeled on the real published benchmarks
(job-bench.github.io: 1,500+ professionals' delegation ratings across ~28 occupations/7 domains;
facebookresearch/meta-agents-research-environments Gaia2: 800 async scenarios/10 universes) without any
network dependency on either — spec 02 forbids it, so both are deterministic template+RNG generators in
the same style as B1-B4.
- [x] **T12.1** 🟦 `ava/datagen/workflow_jobbench.py` — `WorkflowJobBenchGenerator` (phases 3/4/5). 25
  occupations × 3 planted-contradiction families (duplicate line-item, unit mismatch, stale/superseded
  snapshot), every reconciliation computed in Python from the same numbers rendered into the CSV tables —
  never templated as literal text. `task_type` is `deliberate` for duplicate/units, `temporal` for stale
  (recency-dependent). Phase-4 docs GROW their item count until the rendered text clears spec 02's
  6000-char long-doc floor (a fixed item count landed anywhere from ~4000 to ~10000 chars depending which
  occupation's units got drawn — too wide a spread for a single `randint` range).
- [x] **T12.2** 🟦 `ava/datagen/workflow_gaia2.py` — `WorkflowGaia2Generator` (phases 3/4/5, all
  `task_type=temporal`). A deterministic scheduling state machine (candidate time slots + RNG-seeded async
  events fired independently of the agent) over 4 twists mirroring Gaia2's named capability axes:
  adaptability (a slot gets declined), ambiguity (a later explicit time supersedes an earlier vague one),
  deadline pressure (a late constraint prunes the window), collaboration (a second agent's booking must be
  accepted or flagged). The "resolution" text is always the literal replay of the state machine, so it's
  checkable independently of the generator. Phase-4 docs chain further independent scenarios ("same
  universe, later that day") until long enough, since a single scenario averages ~650 chars.
  **Bug caught by the independent test, fixed before merge:** `_ambiguity_doc`'s past-deadline branch was
  silently substituting an unrelated earlier slot instead of flagging the conflict, contradicting its own
  "rather than silently rebooking" text — `_earliest_before(slots, deadline)` fallback removed; past-deadline
  now always flags.
- [x] **T12.3** 🟦 Wired into the live pipeline: registered in `ava/datagen/__init__.py`'s `GENERATORS`;
  added `synth_jobbench`/`synth_gaia2` to `configs/sources.yaml` phases 3/4/5 at the blueprint's own
  intended weights (jobbench 10/10/5%, gaia2 5/15/10% — jobbench skews toward reasoning/p3, gaia2 skews
  toward long/async context/p4, matching `inner_monologue_research.md`'s original framing). Existing
  p3/p4/p5 source weights rescaled down proportionally so every phase still sums to exactly 1.0 (verified
  by script, not by eye).
- [x] **T12.4** 🟦 Tests: both generators added to `tests/test_datagen.py`'s `ALL_GENERATORS` (gets
  determinism/schema/phase-coverage checks for free); plus dedicated correctness tests that independently
  re-derive each doc's answer from its own rendered text (re-sum the CSV tables; re-replay the GAIA2
  scheduling state machine from the parsed slots/deadline/events) rather than trusting the generator's
  internal variables — this is what caught T12.2's ambiguity bug. 50/50 passing.
- [x] **T12.5** 🟦 While verifying T12.4, found `model_1b.py` couldn't run on this dev host at all
  (`torch==2.0.0+cpu`, vs. the docker image's pinned `torch==2.4.0+cu124`) — two version gaps, both fixed
  with no behavior change on 2.4: `RMSNorm.forward` now falls back to the plain
  `x/sqrt(mean(x**2)+eps)*weight` formula when `F.rms_norm` (added in 2.4) isn't present; the attention
  block no longer passes SDPA's `scale=` kwarg (added in 2.1) at all — it pre-scales `q` by `attn_factor`
  instead, which reproduces the identical `(q@k^T)*(attn_factor/sqrt(head_dim))` softmax argument through
  SDPA's own default scale on every torch version SDPA exists in (2.0+). `requirements.txt`'s
  `torch>=2.2.0` loosened to `>=2.0.0` to match; `docker/requirements.gpu.txt`'s now-stale "torch>=2.4 is
  required" comment corrected (2.4 is still pinned there for the fused kernels, just no longer a hard
  requirement for correctness). Full `pytest tests/`: **203 passed, 5 skipped, 0 failed** — the 22
  previously-failing `test_model.py`/`test_jlosses.py` tests (including the causality suite T6.1 was built
  around) now pass on this host too, not just in the pinned docker image.

## Docs
- [x] `PLAN.md`, `TODOS.md`, `ORCHESTRATION.md` rewritten for the continuous pipeline
- [ ] `specs/` refresh — `specs/04` is still accurate; `specs/08` param math needs the J-Space correction
- [x] `specs/10_continuous_supply.md` — contract for Stage 10 (pacer setpoints, infinite-generator governor, bounded-memory streaming, as-of watermark, frozen eval snapshots, replay policy, compaction, curriculum-aware eviction, observability). Grounded in the real `Manifest`/`FlowConfig` API; adds `pacing`/`reproducibility`/`storage`/`replay` config blocks and a `Manifest.claim(max_rowid=...)` extension. Each task carries an acceptance command with a negative control.
- [x] `specs/11_arch_hillclimb.md` — contract for Stage 11 (see above).
- [x] `specs/02_data_generation.md` — added a B5 section for Stage 12's `workflow_jobbench`/`workflow_gaia2`
  generators, in the same contract style as B1-B4.

---

## Open risks
1. **base1b VRAM.** 1409M is 20% over spec. Not yet proven to fit. Decided at T9.3.
2. **`trust_remote_code` sources.** `proof-pile-2` and `github-code` fetch a loader script from HF at runtime; an upstream change can break collection mid-run.
3. **Only `tinystories` (HF) and `synth_logic` (synthetic) were live-run.** The other 5 HF sources are API-verified but not yet pulled. `fineweb-edu`'s `score` field name is taken from the spec, not observed.
4. **Decontamination coupling.** `evals/eval_sets.py` and `ava/datagen/encyclopedia.py` must keep their phrasings distinct; verbatim matching is what separates prompt-form from fact.
5. **`.wslconfig` not applied** — needs `wsl --shutdown`.
6. **Supply may not outrun the GPU at base1b** (~100M tok/day). If `production_tok/s < trainer_tok/s`, T10.7 replay engages; unmitigated it is silent overfitting. This is *the* risk of the continuous premise — measured, not assumed, at Stage 9. Decontam and dedup throughput (T10.4) are the second-order version: if they lag they become the true bottleneck.
7. **Reproducibility of a moving dataset.** Until T10.5's as-of watermark lands, "resume" reads a non-deterministic data order and eval numbers aren't comparable run-to-run.
8. **Eval-set drift.** Continuous generation grows val/test too; without T10.6's frozen snapshots, M1 and M3 PPL are measured on different token streams and can't be compared.
9. **Disk is the binding constraint (28GB) and the store only grows.** Compaction (T10.8) and curriculum-aware eviction (T10.9) are load-bearing, not optional — delete-after-consume alone does not bound a corpus that must stay a few steps ahead across six phases simultaneously.
