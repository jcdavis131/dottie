---
name: jspace-inspector
description: Inspect J-space slots, run the 5 canonical J-tests via ava-open-harness
triggers:
- inspect
- jspace
- france china
- spider ant
- soccer rugby
- safety
j_space_target: Planner
half_life: 150
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
- memory-router
- safety-scanner
- openwiki-sync
complementary:
- family-brain-wiki
---

# JSpace Inspector

Inspects S1 Fast hl8, S2 Slow hl300, Critic hl30, Planner hl150 slot state. Mock mode emits
seeded slot/broadcast diagnostics; real mode runs all 5 canonical J-tests (spider_ant,
france_china, soccer_rugby, spanish_french, safety_blackmail) via the sibling
`ava-open-harness` registry and aggregates one record per test — tests whose real
intervention wiring is unavailable fail honestly with a per-test error record.

Solo personal project, no connection to employer, built with public/free-tier only.
