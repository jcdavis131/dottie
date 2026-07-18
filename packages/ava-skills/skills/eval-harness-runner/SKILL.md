---
name: eval-harness-runner
description: Run ava-open-harness, gate stable checkpoint
triggers:
- harness
- eval
- gate
j_space_target: Planner
half_life: 150
broadcast_target: 0.22
reportability_target: 0.065
dependencies:
- numpy
connectors: []
provider: none
version: 2.1.0
precedes: []
requires:
- jspace-inspector
- safety-scanner
- code-bench
complementary:
- memory-router
---

# Eval Harness Runner

Imports the sibling `ava-open-harness` repo and runs its `run_harness()` over the requested
eval set (default `jspace_all,frontier_rubric`), gating on every requested eval passing.
If the harness cannot run it fails honestly with the error — it never fabricates a pass
count. Run with `python -m skills.loader run eval-harness-runner --mode mock`.

Solo personal project, no connection to employer, built with public/free-tier only.
