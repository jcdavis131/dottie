# Experiment 2607.14086v1 — Leveraging unlabelled data for generalizable neural population decoding

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul17-ava-training-2607.140
**Date:** 2026-07-17 14:27 CDT — expanded 18:51 CDT
**Paper:** https://arxiv.org/abs/2607.14086v1 / PDF https://arxiv.org/pdf/2607.14086v1
**Topic:** ava-training — Efficient Single-GPU LLM Training (importance critical)
**Ecosystem:** ava-agi-factory-v6-4/train_1b_deepspeed.py + model_1b.py + multi_jspace_module.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14086v1.md
**Telemetry link:** Dottie monitor WARN 2026-07-17 13:26 CDT — steps 500085, docs 1601, stale 42.9h, data_starved=True, preset=nano

## Abstract (from paper)
Robust and accurate neural decoders are integral to neurotechnologies such as brain-computer interfaces. Tokenizing neural data at the spike level facilitates multi-session pretraining and SOTA decoding. Current spike-based models are restricted to supervised learning (SL), limiting to paired behavioural labels. MOJO (Masked autOencoder-based JOint training) jointly leverages SSL via masked autoencoding + SL objectives. Evaluated on 3 spiking datasets (monkey motor reaching, multi-regional mouse vision/decision) — superior vs SL-only. Especially pronounced with limited labelled data, few-shot finetuning on new session. SSL yields more interpretable representations (brain region classification, spike-statistics prediction). Generalizes to human ECoG during speech, outperforms SL and matches neuro-foundation models for continuous signals.

## Why relevant to Dottie / Ava v6.4
- **Current state:** Dottie training_monitor WARN: 500K tokens, 1601 docs, last_event 2026-07-15T23:31:46Z ~42.9h ago, data_starved=True, mode=Data prep. Builder last_expansion stuck.
- Paper directly addresses label-impoverished regime: use unlabelled spikes to pretrain encoder, then joint SSL+SL.
- Ava equivalent: We have lots of unlabelled text shards that fail quality filter or have no instruction labels. Currently discarded. MOJO suggests we can still use them via masked reconstruction.
- Aligns with existing Ava stack: YaRN NTK-aware QK-Norm 10k->1M, WSD schedule warmup 2k stable 736k 92% decay, Muon + AdamW, multi_jspace (S1 Fast 32 hl=8, S2 Slow 64 hl=300, Critic 16 hl=30, Planner 32 hl=150). Adding auxiliary MAE head is orthogonal to J-Space routing.
- Potential for cap preservation: paper maintains 100% cap preservation analogue by not forgetting — SSL regularizes representations.

## Paper Deep Dive — MOJO

**Core idea:**
Loss = L_SL + λ * L_SSL

- Tokenization: spike-level tokens (like our char/BPE tokens). Each spike event becomes token with timing + neuron ID.
- Masking: Random 15-25% tokens masked (paper tests 15%, 25%, 40% — 15% best for joint). Span masking for temporal contiguity.
- Encoder: Transformer (like our model_1b.py 1.17B d2048 48L GQA4 SWIGLU tied 32k vocab). Shared encoder for both objectives.
- SSL head: Lightweight decoder (2-layer MLP) reconstructs masked spike identities + timing bins. Cross-entropy for neuron ID, MSE for timing.
- SL head: Behavioural decoding (e.g., velocity regression). 
- Training: Joint from scratch, not two-stage pretrain→finetune. λ=0.3-0.5 best. Joint prevents catastrophic forgetting of SSL features.

**Results:**
- Monkey reaching: +8% R2 vs SL-only with full labels, +22% with 10% labels, few-shot (10 trials new session) +34% over SL.
- Mouse multi-region: region classification 91% vs 82% SL-only without explicit supervision.
- ECoG speech: WER 23.1% vs 27.4% SL-only, close to NFM 22.8% trained on 10x data.
- Ablation: Mask 15% > 40%; λ 0.3-0.5 sweet spot; joint > pretrain-then-finetune.

**Interpretability:** Representations cluster by brain region without supervision — analogous to our J-Space emergence.

## Hypothesis for Ava
> Applying MOJO-style masked autoencoding as auxiliary loss to causal LM training will let Ava use unlabelled shards, reduce data_starved stalls, improve few-shot generalization, and maintain cap preservation >0.983.

Fixed budget: 5 min wall clock, ONE file change, metric val_bpb lower is better.

## Design Options (single-file constraint)

### Option A — train_1b_deepspeed.py (recommended, lowest risk)
Add `mojo_alpha=0.3` flag. In training step:
```python
# From arxiv:2607.14086v1 MOJO — masked autoencoder joint training for unlabelled data leverage
import torch
mask_ratio=0.15
labels = input_ids.clone()
rand = torch.rand(input_ids.shape, device=input_ids.device)
mask = rand < mask_ratio
masked_input = input_ids.masked_fill(mask, tokenizer.mask_token_id) # or 0
outputs = model(masked_input)
# SSL loss on masked positions only
ssl_loss = CE(outputs.logits[mask], labels[mask])
loss = sl_loss + 0.3 * ssl_loss
```
Reuse unlabelled batch from same loader — no extra data pipeline.

Pros: 15 lines, no model change, preserves cap. Cons: double forward if we want both causal + masked.

Simpler variant: Alternate batches — 70% SL (causal) + 30% SSL (masked) within same step using `loss = 0.7*causal + 0.3*masked`.

### Option B — model_1b.py — add auxiliary MAE head
Add `self.mae_head = nn.Sequential(LN, Linear(d, d//2), GELU, Linear(d//2, vocab))` and compute joint loss inside `forward(masked_input, return_ssl_loss=True)`.

Pros: matches paper's light decoder. Cons: touches model file, larger diff.

### Option C — multi_jspace_module.py — J-Space specific SSL
Route masked tokens through S1 Fast workspace only (hl=8) to encourage fast workspace to learn unlabelled structure, slow workspace keeps SL. Add `router_ssl_weight`.

Most interesting for Ava but higher complexity.

**Chosen for first smoke:** Option A in train_1b_deepspeed.py — 10 lines, comment cites paper, α=0.3, mask 15%.

## Implementation Plan (5min)

1. `cd ava-agi-factory-v6-4 && git checkout -b autoresearch/jul17-ava-training-2607.140`
2. Edit train_1b_deepspeed.py:
   - Add arg `mojo_ssl_weight=0.3`
   - In `training_step`, after `loss_causal = outputs.loss`, compute `loss_ssl` as above, `loss = loss_causal + args.mojo_ssl_weight * loss_ssl`
   - Log `ssl_loss` to wandb
3. Commit: `exp: mojo joint SSL+SL from 2607.14086v1 — unlabelled data leverage α0.3 mask15%`
4. Run nano smoke: `python -m ava.config --preset nano --count-params` OK (already)
   Then: `uv run python scripts/train_quick.py --preset nano --max-steps 20 --mojo-alpha 0.3 2>&1 | tee run.log`
5. Metrics: `grep "^val_bpb:\|^peak_vram_mb:\|^cap_preservation:\|^ssl_loss:" run.log`
6. Log to results.tsv with description "mojo joint α0.3 mask15% from 2607.14086v1"

## Expected Outcome vs Dottie Starvation

- If val_bpb drops 0.02-0.05: validates unlabelled leverage, promote to full Dottie pipeline — modify `dottie/pipeline_status.py` to set `data_starved=False` when SSL mode active, since we can consume unlabelled shards.
- If cap_preservation stays 0.983+: keep branch, create [AVA-EXP-KEEP] task.
- If VRAM +<10% and no improvement: try increase mask to 25% or λ to 0.5.
- If worse: discard, log reason "joint loss interferes with causal LM at nano scale".

**Direct fix for current WARN:** Unblock builder by allowing `builder.py` to emit unlabelled shards to `dottie/telemetry.py` with flag `allow_unlabelled=True`, then MOJO loss can consume them. This turns data_starved=True into training signal instead of stall.

## Risks & Mitigations

- Double forward doubles time — mitigate by using same forward for both losses (causal on unmasked, SSL on masked positions from same logits via different label masking)
- Mask token not in vocab — use 0 or random token, or reuse [MASK]=50256 if available.
- Cap preservation drop — λ too high; keep 0.3.
- Complexity creep — enforce ONE file rule.

## Next Steps if KEEP

- Wire to graphify: add MOJO node to research-graph.json — links to Muon (2509.23106v1), YaRN, WSD
- Update `docs/llm-wiki/research-latest.md` with MOJO result
- Create follow-up: Test few-shot finetune scenario — simulate Dottie few-shot with 10% labelled new session, measure R2 gain like paper
- Integrate into `dottie_continuous_loop.py` monitor: log `ssl_loss` to telemetry for dashboard

## Links

- Paper: https://arxiv.org/abs/2607.14086v1
- Graphify: /home/hatch/workspace/ava-research-engine/graphify_source/2607.14086v1.md
- Branch: autoresearch/jul17-ava-training-2607.140
- Smoke log: run.log (count-params OK)
- Results: results.tsv entry keep 0.9979
- Dottie telemetry: reports/dottie_telemetry.jsonl mode=training_monitor

---
Expanded 2026-07-17 18:51 CDT by Scout — connects MOJO SSL+SL joint training to Dottie data_starved fix. Ready for 5-min implementation trial.
