# Ava v6.4 - Curriculum-First Continuous Data + Train Loop
Solo personal project, no connection to employer, built with public/free-tier only

## Goal
Collect datasets in curriculum order, start training immediately on phase 0, build phase 1 while training phase 0, etc. Never OOM. Use open-source tooling (Chonkie etc.) from https://github.com/alvinreal/awesome-opensource-ai

## Current State (v6.4)
- 6 phases in dolma_config.yaml: phase0_logic 0-50B (2048 ctx), phase1_math 50-350B (4096), phase2_foundation 350B-6T (4096), phase3_reasoning 6T-11.25T (8k-32k), phase4_long 11.25T-13.8T (32k-131k), phase5_anneal 13.8T-15T (131k)
- Branches: base, code, math, chat after 736k stable checkpoint (WSD)
- Streaming infra already: streaming_data.py with ShardIterator (1 fh per source), MultiSourceWeightedStream, ShuffleBuffer fixed 10k, batched() constant memory
- NEW: Chonkie integration - ChonkieChunkerWrapper with TokenChunker, RecursiveChunker, SentenceChunker, CodeChunker. 505KB wheel, 49MB installed, no bloat, just CHONK. Pipeline .chunk_with + .refine_with(overlap). Uses character tokenizer for zero-RAM.
- logic_textbook_pipeline.py now has streaming mode: rotating 100MB gzipped jsonl, reward filter >0.8, backpressure, 1 file handle.

## Architecture: Two Background Agents + Shared Lake

```
[Awesome Open Source Toolchain]
  Dolma (dedup) + NeMo Curator (filter dclm_score edu_score) + Chonkie (chunk) + Datasets streaming
       ↓
[Data Builder Agent - Background #1] ----writes----> data/streaming_shards/{source}/shard_XXXXX.jsonl.gz (100MB rotating)
       ↓ checkpoint: checkpoints/stream_builder_state.json
[File System Lake + Manifest: data/manifest.jsonl]
       ↓ watches new shards
[Trainer Agent - Background #2] <---reads--- streaming_data.py AvaStreamingDataset with Chonkie chunking
       ↓ torch + DeepSpeed Zero3 + WSD 736k + YaRN 10k->1M + Multi-JSpace
[Checkpoints: ava_stable_736k.pt, ava_{branch}_final_800k.pt]
```

## Open Source Stack Selection (from awesome-opensource-ai)

**Data Acquisition & Prep:**
- Dolma (AI2) - dedup, CC/Wikipedia/Stack pipeline
- NeMo Curator (NVIDIA) - phase-aware filtering dclm 0.0->0.85, edu 2.0->4.5, reward 0.7->0.8 (already in nemo_curator_pipeline.yaml)
- Datatrove (HF) - alternative to Dolma for large-scale processing
- Chonkie - chunking lib that just works, feature-rich, fast, lightweight, 32+ integrations. Chunkers: TokenChunker fixed-size, SentenceChunker, RecursiveChunker hierarchical, Semantic/Late/Code/Neural/Slumber. Tokenizers: character/word/tiktoken/transformers. Refine: OverlapRefinery, EmbeddingsRefinery. This solves the memory blowup.
- Unstructured - for PDF parsing if needed
- Datasets (HF) with streaming=True - constant memory iteration
- WebDataset - tar shard streaming

**Training:**
- Transformers + DeepSpeed Zero3 bf16 (already)
- Accelerate (already)

**Orchestration / Observability:**
- Workflows via native bash + file watcher, could plug Prefect/Celery later
- W&B for dashboard

## Detailed Step-by-Step Todo (trackable)

### Phase 0 - Infra Hardening (done, need commit)
- [x] 0.1 Add chonkie>=1.4.1, tiktoken, psutil, webdataset to requirements.txt
- [x] 0.2 Implement ChonkieChunkerWrapper in streaming_data.py with get_phase_chunker_config()
- [x] 0.3 Add PHASE_CHONKIE_CONFIG mirroring YaRN schedule: 2048 overlap128 recursive markdown for phase0, 4096 overlap256 for phase1, etc.
- [x] 0.4 Patch AvaStreamingDataset.batched() to chunk via chonkie first, then tokenize per-chunk
- [x] 0.5 Verify memory flat: shuffle_buffer only + batch + 1 doc chunks, 1 fh per source
- [x] 0.6 Update logic_textbook_pipeline.py streaming mode 100MB rotating shards

### Phase 1 - Data Builder Agent (Background)
- [ ] 1.1 Create data_builder_agent.py:
  - reads dolma_config.yaml phases in order
  - maintains builder_state.json {current_phase, phase_progress_tokens, total_shards_written, last_checkpoint}
  - for phase0_logic: targets synthetic_logic_textbooks_phi_B 60% (50B goal but demo 5 shards), metamath 20%, lean 15%, fol 5%
  - uses existing ShardIterator pattern but as WRITER: generate Phi Method B textbooks, filter reward >0.8, gzip jsonl 100MB
  - integrates Chonkie: if doc > chunk_size, pre-chunk with RecursiveChunker markdown recipe, write chunks as separate jsonl lines (preserves definitions)
  - backpressure: if data/streaming_shards/{source} has >20 pending shards, sleep 5s
  - checkpoint every 1000 writes to checkpoints/
- [ ] 1.2 Add data sources beyond synthetic:
  - metamath: stream from HF datasets: lighteval/MATH? Actually use open source: meta-math/MetaMathQA
  - lean: stream from HF lean_workbook
  - All using datasets.load_dataset(..., streaming=True) to avoid RAM
  - NeMo Curator filters via python code: keep if dclm_score>threshold per phase
- [ ] 1.3 Create manifest writer: data/manifest.jsonl with {path, source, phase, tokens_est, timestamp, chonkie_chunks}
- [ ] 1.4 Handle curriculum order guarantee: builder does NOT advance to phase1 until phase0 has min_shards=3 (configurable), writes READY file data/streaming_shards/phase0_logic/.ready
- [ ] 1.5 Run as background daemon via workflow: python data_builder_agent.py --loop forever

### Phase 2 - Trainer Agent (Background)
- [ ] 2.1 Create trainer_agent.py:
  - watches data/streaming_shards/ via glob + polling every 30s (open source watchdog lib optional)
  - uses AvaStreamingDataset(branch, phase=auto, use_chonkie=True, chunker_type=auto)
  - checks for phase0 .ready -> kicks train_1b_deepspeed.py --branch base --data_root data/streaming_shards --streaming --seq_len phase seq --max_steps 736000
  - WSD + RoPE schedule auto from train_1b_deepspeed.py get_rope()
  - saves ava_stable_736k.pt at 736k, triggers branching
  - while training phase0, builder already on phase1 (parallel)
  - checkpoint resume: load last stream_state if exists
- [ ] 2.2 Implement curriculum advance: when tokens_seen crosses PHASE_TOKENS boundary, trainer auto-switches phase (already in _maybe_switch_phase), logs phase switch
- [ ] 2.3 Branch training after stable: when base has ava_stable_736k.pt, trainer loops code/math/chat branches using BRANCH_MIX weights, using chonkie code chunker for code branch

### Phase 3 - Orchestration Loop (Continuous Growth)
- [ ] 3.1 Create orchestrator.sh or workflow definition .jarvis/workflows/curriculum-loop:
  - Phase: spawn parallel agents: data_builder_agent and trainer_agent
  - Use pipeline() not parallel() barrier so builder continuously streams while trainer consumes
  - Pass args: data_root, shuffle_buffer, seq_len per phase
  - Log to logs/
- [ ] 3.2 Add STATUS.json updated every 60s by both agents:
  { "builder": {phase, shards, tokens_est, last_write}, "trainer": {tokens_seen, steps_seen, current_phase, lr, rope_base, loss_est}, "lake": {total_gb, sources} }
- [ ] 3.3 Create heartbeat monitor: check both agents alive, restart if dead
- [ ] 3.4 Push to prod: git commit all, push origin master, workflow launch_async with resume capability

### Phase 4 - Validation & Observability
- [ ] 4.1 Memory test: run builder+trainer with shuffle_buffer 1000 seq_len 2048 batch 2 steps 20, log RSS via psutil, assert <2GB
- [ ] 4.2 Chonkie validation: ensure chunk overlap preserves reasoning chains, test RecursiveChunker vs TokenChunker for logic textbooks
- [ ] 4.3 Eval harness: run eval_branch_harness.py every 5k steps as defined in dolma_config
- [ ] 4.4 Dashboard: wandb_dashboard.py logs half_life curves, broadcast strength per J-Space

## File Map for Other Agents
- streaming_data.py = core constant-memory + ChonkieChunkerWrapper + get_phase_chunker_config()
- data_builder_agent.py = Background Agent 1 (producer)
- trainer_agent.py = Background Agent 2 (consumer)
- CURRICULUM_LOOP_PLAN.md = this plan
- dolma_config.yaml = curriculum source of truth
- checkpoints/stream_state_*.json = stream checkpoints
- data/streaming_shards/*/ = rotating 100MB shards
- data/manifest.jsonl = lake inventory
- STATUS.json = live status for agents

## Execution Order (Curriculum-First)
1. Builder starts phase0_logic, writes 3 shards (~300MB) using Chonkie recursive markdown chunk_size 2048 overlap 128
2. Trainer sees .ready, starts training base with AvaStreamingDataset use_chonkie=True
3. While trainer at 0-50B tokens (phase0), Builder advances to phase1_math, generating ordered curriculum arithmetic->probability, chunk_size 4096
4. Trainer auto-switches to phase1 when tokens_seen >50B, now reading phase1_math shards + continuing phase0 mix
5. Repeat for phase2_foundation (web_edu + code_early + dclm filtered via NeMo Curator), phase3_reasoning (long docs 3x upsampled + JobBench + GAIA2), etc.
6. At 736k steps (13.8T tokens), save stable, branch into code/math/chat

## Why This Fixes Memory Blowup
- Old: load entire 50B+300B+6T into RAM
- New: 1 file handle per source line-buffered gzip, shuffle buffer 10k (~80MB), batch 4*2048 tokens, Chonkie chunks one doc at a time (~2-8 chunks). Peak RAM constant ~200-500MB + model.
- Chonkie uses character tokenizer for init (zero model download) then we tokenize per chunk with ava-tokenizer only.
- Rotating shards with backpressure prevents disk blowup too.

## Commit Checklist
- Add CURRICULUM_LOOP_PLAN.md
- Commit streaming_data.py with Chonkie
- Commit logic_textbook_pipeline.py streaming mode
- Commit requirements.txt with chonkie
- Add STATUS.json placeholder
- Push origin master
