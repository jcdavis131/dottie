# Experiment 2607.05364v2 — REDDIT: Correcting Model-Generated Timestamp Drift in ASR without Forgetting via Replay-Based Distribution Editing

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul18-ava-eval-2607.053
**Date:** 2026-07-18
**Paper:** https://arxiv.org/abs/2607.05364v2 / PDF https://arxiv.org/pdf/2607.05364v2
**Topic:** ava-eval — Frontier Rubric + Eval Harness (importance high)
**Ecosystem:** ava-agi-factory-v6-4/eval_frontier_rubric.py + eval_branch_harness.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.05364v2.md

## Abstract
Modern autoregressive ASR systems can emit timestamps as decoded tokens, enabling timestamped transcription without frame-level aligners or inference-time post-processing. We show that these generated timestamps can drift across long non-speech spans: the transcript may remain plausible, but the decoded time axis drifts away from the audio. We study this non-speech-induced timestamp drift with self-built gap and long-gap benchmarks across 15 evaluated timestamp-producing ASR and audio-language systems. Naive timestamp-corrected fine-tuning improves alignment but can severely degrade non-target ASR behavior, exposing a forgetting problem. We propose REDDIT(REplay-based Distribution eDITing), a lightweight two-stage post-training framework that corrects timestamps while avoiding this catastrophic forgetting: it first edits timestamp targets under the model's own replayed decoder context while matching the frozen base distribution on non-timestamp tokens, then applies a short edited-prefix refinement stage. In this framework, we construct correction supervision without human transcripts or human timestamp annotations by combining VAD-trimmed speech spans with inserted non-speech gaps and known concatenation offsets. On Whisper-tiny, 34.9 hours of targeted correction audio used and only 1.6% of model parameters updated, raising long-gap mIoU from 38.7% to 95.0% and reducing mixed-gap out-of-domain AAS from 2752 ms to 223 ms while preserving CV-en MER at 41.3% (versus 524.2% for o

## Why relevant
FrontierFinance 11-cat rubric (Financial Accuracy, Process Transparency etc), 220 tasks 11543 rubrics, Judge IRA 80.2%, branch eval cap preservation 0.983

## Hypothesis (per program.md)
Based on "REDDIT: Correcting Model-Generated Timestamp Drift in ASR without Forgetting via Replay-Based Distribution Editing", try applying idea to Ava ava-eval.

**What to modify (ONE file only for clean diff):**
- ava-agi-factory-v6-4/eval_frontier_rubric.py + eval_branch_harness.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul18-ava-eval-2607.053 from master in ava-agi-factory-v6-4
2. Read paper PDF + graphify_source/2607.05364v2.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.05364v2 — trying X"
4. git commit -m "exp: ava-eval 2607.05364v2 — REDDIT: Correcting Model-Generated Timestamp Drift"
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
