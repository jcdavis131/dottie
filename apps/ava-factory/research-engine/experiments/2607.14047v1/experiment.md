# Experiment 2607.14047v1 — PhysClaw-0: A Symbiotic Agentic System for Robot Autonomy via Language Corrections

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul18-ava-eval-2607.140
**Date:** 2026-07-18
**Paper:** https://arxiv.org/abs/2607.14047v1 / PDF https://arxiv.org/pdf/2607.14047v1
**Topic:** ava-eval — Frontier Rubric + Eval Harness (importance high)
**Ecosystem:** ava-agi-factory-v6-4/eval_frontier_rubric.py + eval_branch_harness.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14047v1.md

## Abstract
Autonomous data collection governs the volume and quality of real-world trajectories for manipulation policy learning. Existing pipelines reduce human effort via self-resetting, VLM verification, or language-guided correction, yet episode-scoped fixes must be reissued whenever the same failure recurs, so oversight cost grows with session length rather than with the number of distinct problems. We present PhysClaw-0, a human-robot symbiotic agentic system in which corrections are retained and reused across rounds. The collection loop collects, verifies, and resets autonomously, pausing for a remote operator only when a phase exhausts an explicit retry budget. An LLM parser maps each natural-language utterance to a structured adjustment stored in Corrective Memory, so addressed failure modes typically need not be corrected again under the same conditions. On a real-robot desktop-clearing testbed, PhysClaw-0 matches teleoperation episode success while reducing human working time to 16%. Language corrections improve verifier-human agreement in all four evaluated settings and raise average single-attempt success from 12.5% to 47.5% (arm-selection: 20.0% to 50.0%). Policies fine-tuned on PhysClaw-0 data match teleoperation-trained policy success at a fraction of collection human cost.

## Why relevant
FrontierFinance 11-cat rubric (Financial Accuracy, Process Transparency etc), 220 tasks 11543 rubrics, Judge IRA 80.2%, branch eval cap preservation 0.983

## Hypothesis (per program.md)
Based on "PhysClaw-0: A Symbiotic Agentic System for Robot Autonomy via Language Corrections", try applying idea to Ava ava-eval.

**What to modify (ONE file only for clean diff):**
- ava-agi-factory-v6-4/eval_frontier_rubric.py + eval_branch_harness.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul18-ava-eval-2607.140 from master in ava-agi-factory-v6-4
2. Read paper PDF + graphify_source/2607.14047v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.14047v1 — trying X"
4. git commit -m "exp: ava-eval 2607.14047v1 — PhysClaw-0: A Symbiotic Agentic System for Robot A"
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
