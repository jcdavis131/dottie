# Experiment 2607.14070v1 — Screening of Biosecurity Features in Metagenomic Data with Evo 2 Probes

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul18-ava-eval-2607.140
**Date:** 2026-07-18
**Paper:** https://arxiv.org/abs/2607.14070v1 / PDF https://arxiv.org/pdf/2607.14070v1
**Topic:** ava-eval — Frontier Rubric + Eval Harness (importance high)
**Ecosystem:** ava-agi-factory-v6-4/eval_frontier_rubric.py + eval_branch_harness.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14070v1.md

## Abstract
Genomic foundation models such as Evo 2 learn rich sequence representations, but their value for biosecurity screening is largely unexplored. We ask how much biosecurity-relevant signal is linearly accessible in these representations by training minimal linear and attention probes on frozen Evo 2 layer-26 activations, without fine-tuning the underlying model. Across held-out metagenomic test sets, the probes detect antimicrobial resistance (AMR) with strong discrimination: a linear probe reaches a region-level ROC-AUC of 0.888 (mean-pool), rising to 0.977 with a single-head attention probe. The probes resolve finer-grained AMR drug-class subcategories and separate them from unrelated functional genes, providing additional evidence that the learned signal is not explained solely by generic functional-gene status. Bacterial virulence is also decodable, though more weakly (region-level ROC-AUC 0.833). The AMR probe retains comparable ranking performance on simulated short reads without retraining, enabling evaluation before assembly in settings where assembly is computationally costly or unreliable. It achieves a read-level ROC-AUC of 0.898 (mean-pool), comparable to the mean-pooled full-region result. Within SynGenome, AMR-associated prompt labels are only weakly recoverable from Evo 1.5-generated sequences; these prompt-derived labels do not establish the function of the generated response sequences. A complementary sparse-autoencoder analysis recovers interpretable resistance

## Why relevant
FrontierFinance 11-cat rubric (Financial Accuracy, Process Transparency etc), 220 tasks 11543 rubrics, Judge IRA 80.2%, branch eval cap preservation 0.983

## Hypothesis (per program.md)
Based on "Screening of Biosecurity Features in Metagenomic Data with Evo 2 Probes", try applying idea to Ava ava-eval.

**What to modify (ONE file only for clean diff):**
- ava-agi-factory-v6-4/eval_frontier_rubric.py + eval_branch_harness.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul18-ava-eval-2607.140 from master in ava-agi-factory-v6-4
2. Read paper PDF + graphify_source/2607.14070v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.14070v1 — trying X"
4. git commit -m "exp: ava-eval 2607.14070v1 — Screening of Biosecurity Features in Metagenomic D"
5. Run: `uv run train.py > run.log 2>&1` OR `python -m ava.train --preset nano_quick --max-steps 20 > run.log 2>&1`
6. Extract: grep "^val_bpb:\|^peak_vram_mb:\|^cap_preservation:" run.log
7. Log to results.tsv: commit val_bpb memory_gb status description
8. If improved, keep branch, else git reset

## Expected outcome
- If improved: val_bpb decreases OR cap_preservation increases, create follow-up task [AVA-EXP-KEEP]
- If discarded: log reason, try next paper

## Complexity weighting (per program.md)
Simpler is better — weigh complexity cost vs improvement magnitude.
Deletion that maintains or improves is great win.

---
Generated 2026-07-18 by autoresearch-runner cron
