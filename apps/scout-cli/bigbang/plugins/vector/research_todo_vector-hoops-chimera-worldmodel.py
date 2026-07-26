"""
Research TODO: vector-hoops-chimera-worldmodel
Task ID: vector-hoops-chimera-worldmodel
Target repo: vector-hoops

TODO: Extend scout-cli vector plugin via scout todos to implement Chimera embedding fusion (2403.16933v1) for archetype clustering and interactive world-model state persistence loop from 2607.14076v1. Adds CQS-verified chimera eval and daily guess integration, using recent Meta Llama 1M-context news (tech_ai_52c707a406) for long-horizon fantasy persistence.

Graph Node IDs (verbatim, from ~/workspace/personal-graphify/graph.json):
- concept:vector-hoops
- concept:mtnn
- concept:scout
- concept:ava
- concept:jspace
- concept:graphify

Paper IDs (verbatim):
- 2403.16933v1
- 2607.14076v1
- tech_ai_52c707a406

Link to Graphify:
- ~/workspace/personal-graphify/graph.json nodes: concept:vector-hoops, concept:mtnn, concept:scout, concept:ava, concept:jspace, concept:graphify
- News headline: ~/workspace/your_files/news-briefs/headlines/_by_headline/tech_ai_52c707a406.md
- Daily: ~/workspace/your_files/news-briefs/headlines/tech_ai/2026-07-23.md
- PR: https://github.com/jcdavis131/vector-hoops/pull/8
- Branch: research/vector-hoops-chimera-worldmodel

Rationale: Ranked by recency (2607.14076v1 2026-07-16 + tech_ai_52c707a406 2026-07-23), centrality (scout 67, ava 46, graphify 30, vector-hoops 15, mtnn 14), vector overlap (2403.16933v1 is literal Vector Hoops MTNN chimera paper), and actionable scout-cli plugin change with verifiable tests.

Implementation:
- pipeline/chimera_fusion.py contains chimera_fusion() and worldmodel_state_loop()
- pipeline/test_chimera_worldmodel.py verifies CQS 85.87 baseline
- docs/research/vector-hoops-chimera-worldmodel.md has acceptance criteria

Scout todos discovery:
Run `cd ~/workspace/dottie/apps/scout-cli && scout todos --json --path bigbang/plugins/vector` to see this TODO marker.

This file ensures scout todos plugin will list this research task.
"""

GRAPH_NODES = [
    "concept:vector-hoops",
    "concept:mtnn",
    "concept:scout",
    "concept:ava",
    "concept:jspace",
    "concept:graphify",
]

PAPER_IDS = [
    "2403.16933v1",
    "2607.14076v1",
    "tech_ai_52c707a406",
]


def get_todo():
    return {
        "id": "vector-hoops-chimera-worldmodel",
        "summary": "Extend scout-cli vector plugin via scout todos to implement Chimera embedding fusion (2403.16933v1) for archetype clustering and interactive world-model state persistence loop from 2607.14076v1. Adds CQS-verified chimera eval and daily guess integration, using recent Meta Llama 1M-context news (tech_ai_52c707a406) for long-horizon fantasy persistence.",
        "graph_nodes": GRAPH_NODES,
        "paper_ids": PAPER_IDS,
    }
