---
name: memory-router
description: Route between S1/S2/Planner bias control + ShardMemo Tier A/B/C scope-before-routing
triggers:
- router
- arbitration
- bias
- memory
- shardmemo
- scope
j_space_target: Router
half_life: 30
broadcast_target: 0.22
reportability_target: 0.065
dependencies:
- numpy
connectors: []
provider: none
version: 2.1.0
precedes:
- jspace-inspector
- openwiki-sync
- family-brain-wiki
requires:
- safety-scanner
complementary:
- eval-harness-runner
---

# Memory Router

Scopes an instruction with ShardMemo Tier A (safety) / Tier B (memory system) / Tier C
(domain), routes S1/S2/Critic/Planner weights, and reports the real KL divergence between
the routed distribution and the branch bias prior (e.g. code `[0.25,0.45,0.05,0.25]`).
Also recalls shards minted by the memory-mint skill when its store is present.

Solo personal project, no connection to employer, built with public/free-tier only.
