# 6 Local LLMs 2026 — Not Just Smaller Cloud Models — Ava v6.4 Integration

> Solo personal project, no connection to employer, built with public/free-tier only
> Source review: https://share.google/ApbX6CzAGagVjbpGY — 6 local LLMs that prove they're not just smaller versions of cloud models
>
> **Note (post model_1b.py merge/port):** the LongRoPE2 / Peri-LN /
> attention-sinks claim below described the pre-merge `model_1b.py`, which had
> a RoPE rotation bug (see `tasks/plan-longrope2-port.md`). All three have
> since been ported onto the bug-fixed base and are back in the tree, but
> **config-gated and off by default** (`rope_type: longrope2` /
> `use_peri_ln: true` / `n_sinks: N` under a preset's `model:` section) —
> no preset opts in yet, so "Ava already has" below is true of the code, not
> of any currently-trained checkpoint. Sink shape and the attention path also
> differ from the original implementation (GQA-aware); see the plan doc.

## TL;DR — Why Local ≠ Smaller Cloud in 2026

For 2 years local = quantized Llama/Qwen reaching same target differently — compromised versions of cloud APIs. 2026 models are built differently, trained differently, or don't generate text the same way. Common thread: novel approach to at least one part of assumed architecture. Half the problem isn't weights quant — it's KV cache memory growing per token, Llama-2-7B 128K needs 64GB just cache in FP16.

Ava v6.4 already has YaRN RoPE 10k→1M, LongRoPE2 non-uniform 31→25, QK-Norm, Peri-LN, 4 sinks, WSD 736k 92% stable → WSM decay-free EMA, GWTB v2 d_gw=256 k=8 selective 0.3514 phi 4.55x. These 6 models give concrete next hill-climbs.

---

## 1. Zaya1-8B — Compressed Convolutional Attention + Recursive Aggregation

**Key:** 8.4B MoE ~760M active/token, Compressed Convolutional Attention squeezes Q,K,V into shared latent space and sequence mixing with convolutions → 8-fold KV-cache compression no quality drop. Plus Markovian Recursive Self-Aggregation test-time reasoning that combines tail end of multiple parallel reasoning traces into one bounded aggregation context letting model reason longer without carrying full chain. Spotted linear system collapse via 7,400 reasoning tokens beating GPT-5.5/Claude Opus 4.8 wrong, 91.9% AIME 2025 lab number. Local: 7 tok/s BF16 M4 Pro, 42 tok/s MXFP4 vMLX, full parallel-trace version cloud-only for now.

**Ava mapping:**
- Replace standard grouped-query attention with `CompressedConvAttention` optional backend: QKV → shared latent dim d_latent=64, then depthwise conv1d kernel 7 for sequence mixing instead of pure QK dot. KV cache now stores latent not full D → 8× reduction, compatible with our 4 sinks (sinks stay full-dim for BOS stability).
- Implement `MarkovianRecursiveAggregator` for Planner hl150: keep k=4 parallel reasoning traces (as in GWTB top-k), aggregate only tail 256 tokens into bounded context via learned router (entropy tau 0.7). Target: temporal_planning from 150 hl to 200+ without context blowup.
- Hill-climb metric: RULER 4k-128k near-lossless (LongRoPE2 already) + KV mem GB 128k 64GB→8GB + AIME reasoning 7.4k tokens correct.

**Code:** `ava/attention/compressed_conv.py` — class `CompressedConvAttention(nn.Module)` with args `latent_dim=64, conv_kernel=7, compression=8`

---

## 2. VibeThinker-3B — Reasoning Compresses Further

**Key:** 3B dense built on Qwen2.5-Coder-3B, Parametric Compression-Coverage Hypothesis: verifiable reasoning (math/code where answer definitively right/wrong) can be packed into smaller model. Recipe: two-stage supervised + RL phase MaxEnt-guided policy optimization + offline self-distillation. Claims 94.3% AIME 2026, 70.2% GPQA Diamond, 96.1% LeetCode acceptance vs larger models — lab-reported disputed, explicit only for verifiable math/code/STEM not general knowledge, trails on GPQA knowledge-heavy. Same modified AIME 2026 problem as Zaya1 correct while GPT-5.5/Claude Opus 4.8 wrong. Predecessor 1.5B post-trained ~$7,800 vs six figures frontier reasoning.

**Ava mapping:**
- This validates our S1 Fast hl=8 (automatic) vs S2 Slow hl=300 deliberate split: verifiable reasoning can live in tiny S1/S2 towers 160→32 (544 total) not full 1B.
- Implement `vibe_train` recipe for Math/Code branches: stage1 SFT on lean_mathlib + synthetic_math_r1 verifiable, stage2 MaxEnt-guided PPO with reward = proof check / unit tests, stage3 offline self-distillation teacher=base 1B student=router 32 hl=150 + critic 16 hl=30.
- Cost implication: $7,800 1.5B post-train suggests our Alienware RTX 4090 can afford branch fine-tune frozen S1. Target: Math branch AIME >80% with only 32+16 slots.

**Code:** `configs/vibethinker_3b_math.json` + `sft_sota_2025.py` already scaffolds — add maxent flag.

---

## 3. DeepSeek V4 Flash — 284B on Accessible Hardware

**Key:** 284B MoE only ~13B active/token MIT 1M context. Hybrid Compressed Sparse Attention + Heavily Compressed Attention → full 1M tokens ~10% KV cache of V3.2. antirez ds4 DwarfStar 4 self-contained C inference engine by Redis creator, KV cache on disk so streaming from storage, OpenAI/Anthropic-compatible API server + coding agent built-in, needs unified memory Mac 96GB or DGX Spark. Running on Lenovo ThinkStation PGX GB10 Grace Blackwell 128GB LPDDR5x. Also Step-3.5 Flash 197B 11B active sliding window 140K Q4_K_S on same box.

**Ava mapping:**
- Implement hybrid attn: 1 full-attention layer per 3 compressed-sparse/heavily-compressed (mirrors Qwen 3:1 below) — already matches our early/middle/final regime split.
- Disk KV offload: extend `streaming_data.py` to store KV cache shards on disk as ds4 does, enabling 1M streaming on Alienware 128GB without OOM. Our current 1.9MB gz shards 32k docs 10M tokens already split 92/6/2 — add disk streaming flag `--kv-offload disk`.
- Use for data gathering loop: daily 10M tokens packing currently fast md5 13.5s — with Flash approach we can ingest 1M context docs.

**Code:** `ava/attention/sparse_compressed.py` + `scripts/export_ds4.py` + `streaming_data.py` `--kv-disk`

---

## 4. Qwen 3.6 — Gated DeltaNet Fixed-Size State

**Key:** Gated DeltaNet form of linear attention present in most layers roughly three DeltaNet to every full-attention one with fourth acting as precision checkpoint. Where standard attention memory grows per token, linear-attention layer keeps fixed-size recurrent state that never grows with context at all. Stores delta against state already holds, gating adds decay so old info goes away. Qwen3-Coder-Next 80B ultra-sparse MoE only 3B active/token 36 of 48 layers Gated DeltaNet whole fixed state ~18MB at 170K tokens just 12 full-attention layers using 2-head GQA. Q4_K_M ~46GB or Q8_0 ~85GB 170K context vLLM Docker Claude Code 25-40 tok/s on PGX. 27B dense + 35B-A3B MoE 262K native toward 1M, MiniMax M2 had similar but dropped citing reasoning/multi-turn accuracy problems.

**Ava mapping:**
- This is direct replacement for long-context: 3 DeltaNet + 1 full GQA (2-head) pattern. For Ava 1B 48 layers example: 36 DeltaNet + 12 full.
- Fixed state 18MB at 170K vs our current YaRN 1M scales linearly — huge win for phone/edge. Implement `GatedDeltaNet` layer that keeps recurrent state S ∈ R^{d×d} updated S += gating * (k^T v - existing). Matches our Fro norm OroJaR Jacobian disentangle goal (cos 0.45) — DeltaNet delta storage.
- For S1 Fast hl=8 automatic no-RoPE regime: use DeltaNet (fixed state, fast), S2 Slow hl=300 + Planner hl=150 + full attention for precision checkpoints.

**Code:** `ava/attention/gated_deltanet.py` — class `GatedDeltaNetLayer` with decay gating, delta rule, fixed state 18MB benchmark.

---

## 5. DiffusionGemma — Non-Autoregressive Text Diffusion

**Key:** Built on Gemma 4 26B/4B-active MoE base uses discrete text diffusion instead of committing next token left-to-right. Starts from canvas of 256 random tokens refines whole block in parallel with bidirectional attention so start/end influence each other before locked. Text doesn't stream left-to-right; whole block resolves at once like image from noise. 4-bit GGUF Unsloth llama.cpp fork M4 Pro Flappy Bird Flask working code in ~138s across 123 denoising steps 9 blocks bird gravity comically aggressive, needs llama-diffusion-cli visual-diffusion flag not casual workflow yet. Speed: Google 4x speedup 1000+ tok/s H100 compute-heavy vs bandwidth-bound Apple Silicon not same benefit, autoregressive Gemma 4 still wins quality proof of concept, needs ≥16GB VRAM Q4 Apache-2.0.

**Ava mapping:**
- For Planner hl=150 temporal planning + reportability mass 0.06: diffusion enables whole plan block refined bidirectionally — start and end influence each other before lock, ideal for code refactoring, story arcs.
- Implement `DiffusionBlockDecoder` for S2 Slow: instead of autoregressive decode of verbalizable concepts, denoise 256-token canvas in 123 steps × 9 blocks. Use for What-If Lab, career arc ordering.
- Edge: H100 1000+ tok/s parallel denoise vs Apple Silicon bandwidth-bound suggests our ExecuTorch.pte export should target GPU not unified memory for diffusion.

**Code:** `ava/decoding/diffusion_gemma.py` — class `DiscreteDiffusionDecoder` with denoising steps, block size 256, bidirectional attention mask.

---

## 6. Gemma 4 E2B/E4B — On-Phone Multimodal SOTA

**Key:** On-device multimodal text+images+audio, E means effective params E2B ~2B E4B ~4.5B small enough to run on phone punch above weight via MatFormer Matryoshka-style nesting where smaller E2B co-trained inside larger E4B so you can pull smaller without retraining one download multiple targets plus Per-Layer Embeddings which claw back efficiency by giving each decoder layer its own token embeddings in cheap lookup tables. Ran E4B phone-hosted server Oppo Find N5 Snapdragon 8 Elite 16GB RAM llama.cpp Termux OpenAI-compatible API Q8_0 ~4.3GB BF16 multimodal projector +900MB. ~6GB RAM stayed loaded overnight 7-8 tok/s sub-second TTFT though image ~10s encode +10-20s description audio via native conformer encoder tool calling fragile but phone sees/hears/calls tools locally cool.

**Ava mapping:**
- Matryoshka nesting directly maps to our branch system: base 1B contains nano 14M, mini 162M, etc. Train MatFormer-style where E2B inside E4B inside 1B so one checkpoint gives multiple deployment targets — our scale ladder smoke 2M → nano 14M → mini 162M → base 1B already is this.
- Per-Layer Embeddings: each decoder layer its own token embeddings cheap lookup → implement as `PerLayerEmbedding` reduces memory vs shared vocab * layers, compatible with ExecuTorch XNNPACK/CoreML.
- Multimodal: audio conformer encoder + vision projector 900MB → extend `VisionEncoder` already stubbed + new `AudioConformer` for family-brain-os voice notes.
- Phone deploy: 6GB RAM 7-8 tok/s sub-second TTFT matches our tennis DINOv3 ExecuTorch target <50ms, mtnn.pte XNNPACK already. Export Ava Router/Critic/Planner small heads as E2B/E4B.pte.

**Code:** `ava/mobile/matformer.py` + `ava/embeddings/per_layer.py` + `ava/audio/conformer.py`

---

## Unified Ava v6.5 Hill-Climb Plan (from these 6)

1. **Attention compression stack** (Zaya1 + DeepSeek + Qwen): Offer flags `--attn compressed_conv --compression 8`, `--attn gated_deltanet --ratio 3:1 --state-mb 18`, `--attn sparse_compressed --hybrid 10%`. Keep YaRN/LongRoPE2 31→25 as RoPE for full layers. KV cache disk offload via ds4 style.

2. **Reasoning compression** (VibeThinker): verifiable reasoning for math/code branches at $7,800 cost → implement MaxEnt-guided PPO + offline self-distill, target Math 94.3% AIME proxy.

3. **Test-time reasoning aggregation** (Zaya1 Markovian Recursive): Implement for Planner — keep k=4 traces, aggregate tail 256 tokens via entropy temp 0.7 (already GWTB tau), measure phi_hat 4.55x improvement.

4. **Diffusion planning** (DiffusionGemma): Add non-autoregressive decoder option for S2 Slow reportability mass 0.06 verbalization — 256 canvas 123 steps.

5. **Matryoshka + Per-Layer + Multimodal** (Gemma E2B/E4B): Train once get smoke/nano/mini/base via nesting, per-layer embeddings for ExecuTorch 224KB 4 heads already exported → add audio conformer, vision projector 900MB.

6. **Phone-first** (Gemma E4B + Qwen Coder Next): Target Oppo Find N5 class — Q4_K_M 46GB on PGX → quant to Q8_0 4.3GB + projector 900MB =6GB RAM 7-8 tok/s sub-sec TTFT. Our mtnn.pte already XNNPACK, next ava router/critic/planner.pte.

**Preserves solo disclaimer, public pip, free-tier R2/Workers/Supabase/HF ZeroGPU, Home/Work separation BLOCKED_WORK_DRIVE.**

Reports: `your_files/research/impl-*.md` already show keep-or-revert loop works — now add these 6 as new hill-climbs.
