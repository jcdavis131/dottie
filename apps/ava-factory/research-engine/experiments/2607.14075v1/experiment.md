# Experiment 2607.14075v1 — VisualRepair: Dynamic Tool Calling and Region Focusing for Visual Software Issue Repair

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul18-ava-eval-2607.140
**Date:** 2026-07-18
**Paper:** https://arxiv.org/abs/2607.14075v1 / PDF https://arxiv.org/pdf/2607.14075v1
**Topic:** ava-eval — Frontier Rubric + Eval Harness (importance high)
**Ecosystem:** ava-agi-factory-v6-4/eval_frontier_rubric.py + eval_branch_harness.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14075v1.md

## Abstract
Automated Program Repair (APR) has witnessed significant progress with the advent of Large Language Models (LLMs). However, as modern software systems increasingly expose rich graphical user interfaces, effectively leveraging visual information from bug screenshots has become essential for understanding bugs and generating accurate fixes in multimodal scenarios. Real-world issue reports frequently contain heterogeneous visual attachments including UI screenshots, IDE snapshots, GIFs, and text-centric images, each with distinct visual patterns and domain-specific semantics that impose substantial perceptual demands on MLLMs. Furthermore, bug screenshots often contain large expanses of uninformative and bug-irrelevant regions, distracting the model's attention and limiting patch diversity. To address these challenges, we propose VisualRepair, an MLLM-based framework for visual software issue repair comprising two core modules: Image Type-aware Tool Calling (ITTC), which classifies input images and dynamically invokes a tailored tool-calling chain for robust visual interpretation, and Dynamic Test-time Region Focusing (DTRF), which grounds multiple bug-related region candidates and refines them via an adaptive zoom-in and zoom-out strategy to improve fault localization and promote diverse patch generation. Extensive experiments on the SWE-bench Multimodal benchmark demonstrate that VisualRepair consistently outperforms state-of-the-art approaches. VisualRepair resolves 196 and 2

## Why relevant
FrontierFinance 11-cat rubric (Financial Accuracy, Process Transparency etc), 220 tasks 11543 rubrics, Judge IRA 80.2%, branch eval cap preservation 0.983

## Hypothesis (per program.md)
Based on "VisualRepair: Dynamic Tool Calling and Region Focusing for Visual Software Issue Repair", try applying idea to Ava ava-eval.

**What to modify (ONE file only for clean diff):**
- ava-agi-factory-v6-4/eval_frontier_rubric.py + eval_branch_harness.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul18-ava-eval-2607.140 from master in ava-agi-factory-v6-4
2. Read paper PDF + graphify_source/2607.14075v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.14075v1 — trying X"
4. git commit -m "exp: ava-eval 2607.14075v1 — VisualRepair: Dynamic Tool Calling and Region Focu"
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
