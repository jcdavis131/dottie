---
name: logic-prover
description: Generate synthetic logic corpora (truth tables + syllogisms), Phi-style Method B
triggers:
- logic
- prover
- phi
- truth table
j_space_target: S2
half_life: 300
broadcast_target: 0.22
reportability_target: 0.065
dependencies:
- numpy
connectors: []
provider: none
version: 2.1.0
precedes:
- code-bench
requires:
- safety-scanner
complementary:
- code-bench
---

# Logic Prover

Generates synthetic propositional-logic training data: full AND/OR/IMPLIES truth tables and
template syllogisms, each record self-verified at generation time. Mock mode counts a small
sample; real mode writes structured JSONL to `out_dir` (default `data/raw/logic/`) and
reports the actual records and bytes written. A 50B-token corpus is a long-term aspiration,
not something this skill produces. Run with `python -m skills.loader run logic-prover`.

Solo personal project, no connection to employer, built with public/free-tier only.
