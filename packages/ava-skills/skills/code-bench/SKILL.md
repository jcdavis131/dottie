---
name: code-bench
description: Exec-verified Python generation (P2 code)
triggers:
- code
- bench
- exec
j_space_target: S2
half_life: 350
broadcast_target: 0.22
reportability_target: 0.065
dependencies:
- numpy
connectors: []
provider: none
version: 2.1.0
precedes:
- eval-harness-runner
requires:
- safety-scanner
- logic-prover
complementary:
- logic-prover
---

# Code Bench

Runs candidate Python snippets in a subprocess sandbox (`exec_verify`) and checks stdout
against expected output. Mock mode exec-verifies a small built-in task set and reports the
real pass rate; real mode refuses until a model `generate()` path is wired into the same
`exec_verify` loop. Run with `python -m skills.loader run code-bench --mode mock`.

Solo personal project, no connection to employer, built with public/free-tier only.
