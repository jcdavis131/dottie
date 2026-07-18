---
name: safety-scanner
description: Blackmail/leverage detection Critic hl30 early warning 4-5 tok before
  output
triggers:
- safety
- blackmail
- leverage
- critic
j_space_target: Critic
half_life: 30
broadcast_target: 0.22
reportability_target: 0.065
dependencies:
- numpy
connectors: []
provider: none
version: 2.1.0
precedes:
- memory-router
- jspace-inspector
- code-bench
- logic-prover
- openwiki-sync
- family-brain-wiki
- eval-harness-runner
requires: []
complementary: []
---

# Safety Scanner

Tier A safety gate: scores text for blackmail/leverage/threat content. Real mode uses a
deterministic regex baseline (Guard-3 ONNX inference is not wired and refuses honestly);
mock mode runs a labeled scenario set and reports ROC-AUC / AUPRC / FPR@0.5 computed from
the actual per-scenario scores. Paper numbers appear only as `targets`, never as metrics.

Solo personal project, no connection to employer, built with public/free-tier only.
