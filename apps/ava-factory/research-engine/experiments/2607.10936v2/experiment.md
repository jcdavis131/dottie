# Experiment 2607.10936v2 — Bandit PCA with Minimax Optimal Regret

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul16-ava-training-2607.109
**Date:** 2026-07-16
**Paper:** https://arxiv.org/abs/2607.10936v2 / PDF https://arxiv.org/pdf/2607.10936v2
**Topic:** ava-training — Efficient Single-GPU LLM Training (importance critical)
**Ecosystem:** ava-agi-factory-v6-4/train_1b_deepspeed.py + model_1b.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.10936v2.md

## Abstract
We study the bandit-feedback version of online principal component analysis (Bandit PCA): in each round $t = 1,\dots,T$, the adversary selects a $d \times d$ symmetric gain matrix $G_t$ with spectrum in $[0,1]$ and rank at most $r$; the learner simultaneously selects a unit vector $w_t \in S^{d-1}$ and receives the reward $w_t^\top G_t w_t$. The learner receives no other feedback, and aims to minimize the regret against the best unit vector in hindsight. This problem was introduced by Kotlowski and Neu (2019), who gave an algorithm with regret $O(d\sqrt{rT \log T})$ and showed the lower bound of $Ω(r\sqrt{T/\log T})$. We improve upon both of these bounds and essentially bridge the gap between them, establishing the minimax regret of order $r\sqrt{dT}$ up to polylogarithmic factors in $d$ and $T$. The upper bound is attained by a novel algorithm, which combines online mirror descent on the spectrahedron of (real) density matrices with a multiscale exploration scheme in which the eigenspaces with different spectral magnitudes are updated at different rates. For the lower bound, we construct an adaptive adversary that refines a hidden large-reward subspace based on the learner's actions, in such a way that low regret is impossible without estimating the subspace; as a result, lower-bounding the regret reduces to studying the arising subspace estimation problem. Finally, we discuss connections of Bandit PCA with adaptive-measurement quantum tomography.

## Why relevant
WSD schedule (warmup 2k stable 736k 92% decay), Muon + AdamW, YaRN NTK-aware QK-Norm 10k->1M, single-GPU nanochat from Karpathy autoresearch

## Hypothesis (per program.md)
Based on "Bandit PCA with Minimax Optimal Regret", try applying idea to Ava ava-training.

**What to modify (ONE file only for clean diff):**
- ava-agi-factory-v6-4/train_1b_deepspeed.py + model_1b.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul16-ava-training-2607.109 from master in ava-agi-factory-v6-4
2. Read paper PDF + graphify_source/2607.10936v2.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.10936v2 — trying X"
4. git commit -m "exp: ava-training 2607.10936v2 — Bandit PCA with Minimax Optimal Regret"
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
Generated 2026-07-16 by autoresearch-runner cron
