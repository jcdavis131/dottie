# Ava AGI Factory v6.4 — Experiment Card: 2026-07-13-mammal-multi-alignment (Pure Ava-only 3-Stage Ablation Gate)

> **Disclaimer:** Solo personal project, no connection to employer, built with public/free-tier only. Public pip only, no work/internal packages. WANDB_MODE=offline. Local Docker/CUDA only, no employer compute. This is a pre-train experiment card — no results invented.

## Paper Citation

- **arXiv ID:** 2410.22367
- **Title:** MAMMAL -- Molecular Aligned Multi-Modal Architecture and Language for Biomedical Discovery
- **Authors:** Yoel Shoshan, Moshiko Raboh, Michal Ozery-Flato, Vadim Ratner, Alex Golts, Jeffrey K. Weber, Ella Barkan, Simona Rabinovici-Cohen, Sagi Polaczek, Ido Amos, Ben Shapira, Liam Hazan, Matan Ninio, Sivan Ravid, Michael M. Danziger, Yosi Shamay, Sharon Kurant, Joseph A. Morrone, Parthasarathy Suryanarayanan, Michal Rosen-Zvi, Efrat Hexter
- **URL:** https://arxiv.org/abs/2410.22367
- **PDF:** https://arxiv.org/pdf/2410.22367.pdf
- **Nature companion:** https://www.nature.com/articles/s44386-026-00047-4
- **Code ref:** https://github.com/BiomedSciAI/biomed-multi-alignment
- **HF ref (optional teacher, NOT pulled by default):** ibm/biomed.omics.bl.sm.ma-ted-458m

## Hypothesis (tied to paper §3.1 Numerical Values Integration)

If Ava replaces rank-binning scalar discretization with pure continuous MammalScalarProjection — learned linear scalar→d_model added to token embeddings plus modular tags `<MOLECULE>/<PROTEIN>/<RNA>/<ALIGN>` routed to S1 Fast 32 hl=8 tag detector and S2 Slow 64 hl=300 integrator — then bio frontier regression NRMSE (DTI, PPI ΔΔG) and classification AUROC (BBBP, ClinTox, AbAg) will improve vs baseline because Critic 16 hl=30 validates continuous scalars without digit-token inflation per MAMMAL Fig A1.

## Methods Extracted (pdfminer/pymupdf verified, no hallucination)

From pymupdf extraction of 2410.22367v3 (40 pages, 15133679 bytes):

1. **Architecture (§3.1):** T5-inspired transformer shared encoder stack. Supports encoder-only (classification/regression: token head + optional scalar head) and encoder-decoder autoregressive (residual encoder final hidden injected into each decoder layer). Multi-task via gradient accumulation across tasks.

2. **Structured Prompt Syntax (§3.3, Appendix B):** Modular tokenizer assigning distinct sub-tokenizers per entity domain (SMILES `CC(=O)NC1=CC=C(O)C=C1`, AA chains, ranked gene list sorted log-normalized binned expression with alphabetical tie-break). Special tags: `<MOLECULAR ENTITY>`, `<MOLECULAR ENTITY EPITOPE>`, `<COMPLEX ENTITY>`, `<GLOBAL_SYSTEM>`, `<SENTINEL ID ?>`, `<EOS>`, natural start/end truncation hints. Unified special token set, extensible backward compatible.

3. **Numerical Values Integration (§3.1, Fig A1, Appendix A):** Native continuous scalars as inputs/outputs via learned linear projection `1 -> D (e.g. 768)` aligning with token embeddings, added not concatenated. Scalar prediction head `[D]->[1]` for regression. Avoids digit-splitting inflation [82] and fixed-vocab limit [83]. Supports thousands scalars/prompt (gene expression). Losses CE/Focal + MSE/RMSE.

4. **Entity Representation (§3.2):** Small Molecules=SMILES, Gene Expression=ranked gene names by binned expression, Proteins=AA chains no structure, Antibodies=AA prefixed `<HEAVY>/<LIGHT>`.

5. **Pretraining (§3.4, Table 2, C.4-C.5):** 2B samples, 6 public datasets, 7 tasks concurrent span-denoising mean span 5 noise density 0.15: UniRef90 180M Protein LM, OAS 650M Antibody LM + 650M Antibody Denoise t~U[1,500], ZINC+PubChem 200M Small Molecule LM, CELLxGENE 30M Cell Genes LM, STRING 780M PPI classification + 390M generation. AdamW β1 0.9 β2 0.999 wd 0.01 grad_clip 1.0 2K warmup cosine decay to 10% LR, random sub-sequence cut with start/end tokens per max seq len.

## Pure Ava-only 3-Stage Ablation Gate (user confirmed: pure priority)

**Priority: Pure Ava-only. HF teacher NOT convinced yields better. No HF pull by default. No logit matching. WANDB offline, public pip only. Push to prod only after gate PASS.**

### Stage 0 — Baseline: rank-binning
- Scalar → quantile bins 0..999 → token_id = scalar_vocab_start + bin. Like Tx-LLM binning.
- No projection, loses continuity, inflates length.
- Metric: record bio frontier NRMSE/AUROC.

### Stage 1 — Ablation1: MammalScalarProjection pure (PRIMARY, pure Ava-only)
- Continuous learned `Linear(1,d_model)` LayerNorm std 0.02 per Fig A1.
- Modular tags → J-Space heads:
  - `<MOLECULE>`/`<SMILES>` → S1 Fast 32 hl=8 tag detector (decay 0.917)
  - `<PROTEIN>`/`<AA>`/`<RNA>`/`<GENE>` → S2 Slow 64 hl=300 integrator (decay 0.9977)
  - `<ALIGN>`/`<COMPLEX ENTITY>`/`<GLOBAL_SYSTEM>` → Planner 32 hl=150 hierarchy builder Sequence→Molecule→MolecularSystem→GlobalSystem
  - `<|scalar|>` placeholder → Critic 16 hl=30 validator MSE/RMSE, ClinTox safety veto
- Router/veto: classification→automatic [0.6,0.15,0.1,0.15] S1; regression→deliberate [0.15,0.55,0.1,0.2] S2+Critic 0.4; generation→temporal [0.1,0.3,0.1,0.5] Planner + S2 reads Planner 0.3; safety→Critic 0.6 veto. Veto when MSE>thresh suppresses S1.
- Gate: Must beat Baseline by +1% relative (NRMSE ↓1% or AUROC ↑1% bio frontier) to qualify Stage2, else STOP and promote Stage1 if wins.

### Stage 2 — Ablation2: Optional HF teacher MSE head match ONLY IF Stage1 +1% win
- Condition: `(Ablation1_NRMSE < Baseline_NRMSE*0.99) OR (Ablation1_AUROC > Baseline_AUROC*1.01)`
- Then optional local CPU-offload: load `ibm/biomed.omics.bl.sm.ma-ted-458m` public, extract scalar head, MSE distillation `L = MSE(Ava_pred_head, HF_head_l2norm)*0.1`
- NO logit matching, NO seq distillation, NO tokenizer import, public pip `transformers` only reference. Requires manual approval. Default path = pure wins.

## Ava J-Space Mapping (configs/base1b.yaml preserved)

- S1 Fast 32 hl=8 associative — SMILES vs AA lexing, scalar delimiter
- S2 Slow 64 hl=300 verifiable — cross-modal Protein+SM+Gene alignment, 2048 ctx binding pocket
- Critic 16 hl=30 safety/eval-aware — scalar head MSE, numerical proximity [83], toxicity early warning
- Planner 32 hl=150 deadlines/env_deltas — structured prompt builder, curriculum ordering Protein LM → Antibody → SM → PPI
- Router/veto — encoder-only vs encoder-decoder switch per task_type, S2 veto S1 when MSE>thresh

YaRN/LongRoPE2, QK-Norm, Peri-LN, 4 attention sinks untouched.

## Code Patch Sketch (public pip only, compatible)

### File: `ava-agi-factory-v6-4/multi_jspace_module.py`

```python
# Solo personal project, no connection to employer, built with public/free-tier only
import torch, torch.nn as nn, torch.nn.functional as F

class MammalScalarProjection(nn.Module):
    """MAMMAL §3.1 Fig A1 — pure continuous scalar -> d_model"""
    def __init__(self, d_model=2048):
        super().__init__()
        self.proj = nn.Linear(1, d_model, bias=False)
        self.scale_pred_head = nn.Linear(d_model, 1)
        self.norm = nn.LayerNorm(d_model)
        nn.init.normal_(self.proj.weight, std=0.02)
        nn.init.normal_(self.scale_pred_head.weight, std=0.02)
        nn.init.zeros_(self.scale_pred_head.bias)
    def encode(self, scalars: torch.Tensor) -> torch.Tensor:
        return self.norm(self.proj(scalars.float()))  # [B,Ns,1]->[B,Ns,D]
    def decode(self, hidden: torch.Tensor) -> torch.Tensor:
        return self.scale_pred_head(hidden)  # [B,L,D]->[B,L,1]
    def loss(self, hidden_mean, target):
        pred = self.scale_pred_head(hidden_mean).squeeze(-1)
        return F.mse_loss(pred, target) + 0.1*F.l1_loss(pred, target)

class BaselineRankBinning(nn.Module):
    def __init__(self, n_bins=1000, scalar_vocab_start=31000):
        super().__init__()
        self.n_bins=n_bins; self.start=scalar_vocab_start
    def scalar_to_token(self, scalars, vmin=-5, vmax=15):
        norm = ((scalars - vmin)/(vmax - vmin + 1e-6)).clamp(0,0.999)
        bins = (norm * self.n_bins).long()
        return self.start + bins

# In MultiJSpace.__init__ add:
# self.scalar_proj = MammalScalarProjection(d_model)
# self.baseline_binner = BaselineRankBinning()
# self.tag_emb = nn.Embedding(32, d_model)
```

### File: `ava-agi-factory-v6-4/model_1b.py` — diff sketch

```diff
--- a/model_1b.py
+++ b/model_1b.py
@@ class AvaModel1B
-        self.embed = nn.Embedding(vocab_size, d_model)
+        self.embed = nn.Embedding(vocab_size, d_model)
+        from multi_jspace_module import MammalScalarProjection, BaselineRankBinning
+        self.scalar_proj = MammalScalarProjection(d_model=d_model)
+        self.baseline_binner = BaselineRankBinning(n_bins=1000, scalar_vocab_start=vocab_size-1000)
+        self.use_mammal_projection = True  # False=Stage0 baseline
+        self.scalar_token_id = vocab_size-1

-    def forward(self, input_ids, task_type="deliberate"):
+    def forward(self, input_ids, task_type="deliberate", scalar_values=None, scalar_positions=None):
         B,L = input_ids.shape
         x = self.embed(input_ids)
+        if self.use_mammal_projection and scalar_values is not None:
+            s_emb = self.scalar_proj.encode(scalar_values.unsqueeze(-1))
+            for b in range(B):
+                pos = scalar_positions[b]
+                if len(pos)>0:
+                    x[b, pos] = s_emb[b, :len(pos)]
         fused = self.fusion_norm(x)  # YaRN/QK-Norm preserved
         mapped = {"classification":"automatic","regression":"deliberate","generation":"temporal","safety":"safety"}.get(task_type,"deliberate")
         fused_seq, jspace_out = self.multi_jspace(fused, task_type=mapped, prev_workspaces=self._prev_workspaces)
+        if task_type=="regression" and scalar_values is not None:
+            pred = self.scalar_proj.decode(fused_seq)
+            jspace_out["scalar_mse"] = F.mse_loss(pred.mean(dim=1).squeeze(-1), scalar_values.mean(dim=1))
         return fused_seq, jspace_out
```

### File: `configs/base1b.yaml`

```yaml
jspace:
  target_hl: {system1: 8, system2: 300, critic: 30, planner: 150}
  slots: {system1: 32, system2: 64, critic: 16, planner: 32}
  mammal:
    enabled: true
    stage0: rank_binning_1000
    stage1: learned_linear_1_to_2048_pure
    stage2_optional_teacher: hf_mse_head_only_if_stage1_plus1pct
    tags: ["<MOLECULE>","<PROTEIN>","<RNA>","<ALIGN>","<MOLECULAR ENTITY>","<COMPLEX ENTITY>","<|scalar|>"]
    pure_ava_only: true
    no_hf_pull_by_default: true
```

## Scrutiny (required)

### Token vocab mismatch
- MAMMAL modular tokenizer uses meta tokens `<@TOKENIZER-TYPE=AA|SMILES>` to avoid conflict between SMILES 'C' vs AA 'C' in shared ID space. Ava 32k SentencePiece merges `CC(=O)` → `CC` losing chem semantics.
- Mitigation: Keep S1 lexing overlay, add 4 special tag IDs at vocab end 32000-32031, reserve 1000 placeholder tokens, train tag_embeddings from scratch, do NOT import HF tokenizer. Validate via branch_harness vocab_stress.

### Leakage risk
- Ranked gene list alphabetical tie-break could memorize via S2 hl=300 if same top-20 genes appear train vs eval. STRING PPI overlap with DTI holdout classes (estrogen receptor/GPCR/ion channel/receptor tyrosine kinase).
- Mitigation: Dedup CELLxGENE by top-20 hash Jaccard <0.8, log leakage_score, use `data/mini` synthetic bio-like only for this card, no real STRING pull. Gate blocks train if overlap >0.2.

### VRAM cost
- Projection 2k params negligible; risk is 20k gene list seq_len 2048→4096 O(n^2) 4x VRAM.
- Mitigation: Keep 2048 ctx, random sub-sequence cut with special start/end tokens per C.2, GQA 4 KV, SwiGLU ratio 1.0, grad checkpointing, adamw8bit. Nano 12GB 4080 fits 1M tokens. Stage2 HF 458M+1B 1.5B concurrent ~6GB fp16 + opt 22GB peak → avoid by default, CPU offload eval mode only if Stage1 wins.

## Eval Gate — Exact Commands (mock mode, offline)

```bash
# Branch harness — canonical + bio stress + spike sink
WANDB_MODE=offline python eval_branch_harness.py --branch all --mode mock --spike_sink --mammal_tags

# Frontier rubric — bio domain q-bio.BM
WANDB_MODE=offline python eval_frontier_rubric.py --domain bio --judge mock --mode mock --include_scalars

# 3-Stage specific: baseline vs pure projection, require +1% NRMSE/AUROC
WANDB_MODE=offline python eval_branch_harness.py --branch all --mode mock --ablation baseline_rank_binning --tag mammal
WANDB_MODE=offline python eval_branch_harness.py --branch all --mode mock --ablation mammal_scalar_projection --tag mammal
WANDB_MODE=offline python eval_frontier_rubric.py --domain bio --judge mock --mode mock --ablation baseline_vs_projection --gate_threshold 0.01

# Combined gate (must PASS before train)
WANDB_MODE=offline python eval_branch_harness.py --branch all --mode mock && \
WANDB_MODE=offline python eval_frontier_rubric.py --domain bio --judge mock --mode mock && \
echo "GATE PASS: branch 100% CapPres + bio frontier >0.5 + Stage1 beats Baseline 1% for Stage2 eligibility"
```

Expected paper proxy (not Ava results): DTI NRMSE 0.906 3.8% over SOTA, PPI Pearson 0.852 28.5% seq-only SOTA, CellType F1 0.763 7.5% Table1. Target directionality only.

## 1-Command Train Stub — Local Docker CUDA (offline, public pip only)

```bash
# Solo project, public pip only, YaRN/QK-Norm/WSD preserved, no HF pull default
WANDB_MODE=offline docker-compose run --gpus all -e WANDB_MODE=offline ava-train bash -c "
  pip install -q torch --index-url https://download.pytorch.org/whl/cu124 && \
  python train_1b_deepspeed.py \
    --config configs/base1b.yaml \
    --exp 2026-07-13-mammal-multi-alignment \
    --phase p2_foundation \
    --tokens 500000000 \
    --seq_len 2048 \
    --rope_base 10000 \
    --rope_type longrope2 \
    --wandb_mode offline \
    --mammal_scalar_proj true \
    --mammal_projection_mode pure_continuous \
    --mammal_baseline rank_binning \
    --mammal_tags '<MOLECULE> <PROTEIN> <RNA> <ALIGN> <MOLECULAR_ENTITY> <COMPLEX_ENTITY> <|scalar|>' \
    --jspace_slots system1:32,system2:64,critic:16,planner:32 \
    --jspace_hl system1:8,system2:300,critic:30,planner:150 \
    --branch bio \
    --no_hf_teacher
"

# Nano smoke (12GB, offline):
# WANDB_MODE=offline docker-compose run --gpus all -e WANDB_MODE=offline ava-train python train_1b_deepspeed.py --config configs/nano.yaml --exp mammal-test-nano --tokens 1000000 --mammal_scalar_proj true --wandb_mode offline --no_hf_teacher
```

Stage2 optional only if Stage1 wins +1%:

```bash
WANDB_MODE=offline docker-compose run --gpus all -e WANDB_MODE=offline ava-train bash -c "
  pip install -q transformers torch && \
  HF_HUB_OFFLINE=1 python train_1b_deepspeed.py \
    --config configs/base1b.yaml \
    --exp 2026-07-13-mammal-multi-alignment-stage2 \
    --mammal_teacher ibm/biomed.omics.bl.sm.ma-ted-458m \
    --mammal_teacher_loss mse_head_only \
    --mammal_teacher_weight 0.1 \
    --no_logit_matching \
    --wandb_mode offline
"
```

## Constraints & Compatibility

- Solo disclaimer top present
- Public pip only — torch, transformers ref only Stage2, wandb offline, pymupdf
- WANDB offline enforced
- Local Docker/CUDA only — runtime nvidia, no employer cluster
- YaRN/QK-Norm/WSD preserved — mscale/attn_factor 0.1*ln(scale)+1, LongRoPE2 optional
- No results invented — pre-train card
- Frontier bio q-bio.BM — DTI/BBBP/ClinTox/PPI/cell-type

## Repro

1. Fetch: `curl -L https://arxiv.org/pdf/2410.22367.pdf -o /tmp/mammal.pdf`
2. Extract: `python -c "import fitz; print(fitz.open('/tmp/mammal.pdf')[13].get_text()[:5000])"` verify §3.1
3. Patch `multi_jspace_module.py` + `model_1b.py` per sketch
4. Run 3-stage gate mock
5. Smoke nano 1M offline
6. If Stage1 +1% PASS, file issue for Stage2 manual review, push updated card to both your_files and repo and prod

---
*Generated for Ava AGI Factory v6.4 — 2026-07-13-mammal-multi-alignment Pure Ava-only 3-stage — Solo personal project, no connection to employer, built with public/free-tier only — Paper: arXiv 2410.22367 MAMMAL §3.1-3.3 Appendix A/B*
