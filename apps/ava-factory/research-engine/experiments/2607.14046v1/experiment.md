# Experiment 2607.14046v1 — Earthquaker-AI: A Retrieval-Augmented Generation Framework with Rubric-Based Assessment for Primary School Earthquake Education

Solo personal project, no connection to employer, built with public/free-tier only

**Branch:** autoresearch/jul18-ava-eval-2607.140
**Date:** 2026-07-18
**Paper:** https://arxiv.org/abs/2607.14046v1 / PDF https://arxiv.org/pdf/2607.14046v1
**Topic:** ava-eval — Frontier Rubric + Eval Harness (importance high)
**Ecosystem:** ava-agi-factory-v6-4/eval_frontier_rubric.py + eval_branch_harness.py
**Graphify source:** /home/hatch/workspace/ava-research-engine/graphify_source/2607.14046v1.md

## Abstract
This paper presents Earthquaker-AI, a hybrid educational framework building upon a previously implemented educational robotics project by integrating a conversational AI assistant based on Retrieval-Augmented Generation. It aims to enhance earthquake preparedness and conscious action among primary-school students. The system extends the award-winning STEM project Earthquaker moving from mechanical simulation with Lego WeDo2 to cognitive and metacognitive processing. The robotics component uses Lego WeDo2 automation to simulate seismic response, letting students interact with sensors and actuators as tangible representations of protective actions. The assistant operates as a guided learning mechanism aligning student responses with safety guidelines, while providing rubric-based verbal feedback that supports self-regulated learning and calmness under emergency conditions. Earthquaker-AI follows a progressive learning trajectory aligned with cognitive development. In early grades, the focus is on basic recognition of safety actions through multiple-choice questions, assessed via a two-dimensional rubric. In middle grades, students identify correct action sequences through multiple-choice questions, evaluated via a three-axis rubric. In upper grades, the approach shifts to verbal production, requiring short written responses assessed via a four-dimensional rubric that includes clarity of expression. The dialogic module uses RAG to match student queries semantically with official

## Why relevant
FrontierFinance 11-cat rubric (Financial Accuracy, Process Transparency etc), 220 tasks 11543 rubrics, Judge IRA 80.2%, branch eval cap preservation 0.983

## Hypothesis (per program.md)
Based on "Earthquaker-AI: A Retrieval-Augmented Generation Framework with Rubric-Based Assessment for Primary School Earthquake Education", try applying idea to Ava ava-eval.

**What to modify (ONE file only for clean diff):**
- ava-agi-factory-v6-4/eval_frontier_rubric.py + eval_branch_harness.py
- For training ideas: `model_1b.py` OR `multi_jspace_module.py` OR `train_1b_deepspeed.py`
- For MCP ideas: `bigbang-cli/bigbang/core/mcp_client.py` or `openapi.py`
- For Graphify ideas: `scripts/graphify_research.py`

**Fixed time budget:** 5 minutes wall clock (Karpathy style) — metric val_bpb lower is better, or cap preservation 0.983

**Steps:**
1. git checkout -b autoresearch/jul18-ava-eval-2607.140 from master in ava-agi-factory-v6-4
2. Read paper PDF + graphify_source/2607.14046v1.md
3. Modify ONE file — cite paper in comment: "# From arxiv:2607.14046v1 — trying X"
4. git commit -m "exp: ava-eval 2607.14046v1 — Earthquaker-AI: A Retrieval-Augmented Generation F"
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
