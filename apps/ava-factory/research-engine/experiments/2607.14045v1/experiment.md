# Experiment 2607.14045v1 — LLMs for Qualitative and Mixed-Methods Social Network Analysis

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul18-ava-eval-2607.140
**Date:** 2026-07-18
**Paper:** https://arxiv.org/abs/2607.14045v1 / PDF https://arxiv.org/pdf/2607.14045v1
**Topic:** ava-eval — Frontier Rubric + Eval Harness (importance high)
**Ecosystem:** ava-agi-factory-v6-4/eval_frontier_rubric.py + eval_branch_harness.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14045v1.md

## Abstract
This manuscript explores the integration of Large Language Models (LLMs) into the field of qualitative and mixed-methods social network analysis (SNA). We argue that the primary focus of this integration should be on enhancing the depth and rigor of qualitative SNA, rather than on replacing human researchers with automated systems. We begin by outlining the core principles of qualitative and mixed-methods SNA, emphasizing the importance of understanding the meaning of ties, the role of narratives, and the significance of relational identities. We then discuss how LLMs can be used as powerful tools to augment this work, from assisting with data collection and coding to supporting theory-building and abductive reasoning. We also address the limitations and ethical challenges of using LLMs in this context, including issues of bias, hallucination, and the need for reflexivity. We conclude with a series of research designs and practical recommendations for researchers who want to integrate LLMs into their work in a thoughtful and responsible way.

## Why relevant
FrontierFinance 11-cat rubric (Financial Accuracy, Process Transparency etc), 220 tasks 11543 rubrics, Judge IRA 80.2%, branch eval cap preservation 0.983

## Hypothesis (per program.md)
Based on "LLMs for Qualitative and Mixed-Methods Social Network Analysis", try applying idea to Ava ava-eval.

**What to modify (ONE file only for clean diff):**
- ava-agi-factory-v6-4/eval_frontier_rubric.py + eval_branch_harness.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul18-ava-eval-2607.140 from master in ava-agi-factory-v6-4
2. Read paper PDF + graphify_source/2607.14045v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.14045v1 — trying X"
4. git commit -m "exp: ava-eval 2607.14045v1 — LLMs for Qualitative and Mixed-Methods Social Netw"
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
