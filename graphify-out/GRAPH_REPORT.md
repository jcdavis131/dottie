# Personal Graphify Report

Solo personal project, no connection to employer, built with public/free-tier only.

**Nodes:** 474 · **Edges:** 1075 · **Communities:** 18

Token estimate: ~1500 tokens per scoped query vs ~31100 naive → **20.7× reduction** (mirrors upstream 71.5×).

## God Nodes (highest-degree concepts)

- **extract.py** (file) — degree 58 — file `/home/hatch/workspace/your_files/personal-graphify/src/personal_graphify/extract.py` — community 2
- **cli.py** (file) — degree 56 — file `/home/hatch/workspace/your_files/personal-graphify/src/personal_graphify/cli.py` — community 1
- **INSTALL_GUIDE.md** (doc) — degree 51 — file `/home/hatch/workspace/your_files/personal-graphify/INSTALL_GUIDE.md` — community 3
- **query.py** (file) — degree 42 — file `/home/hatch/workspace/your_files/personal-graphify/src/personal_graphify/query.py` — community 0
- **serve.py** (file) — degree 40 — file `/home/hatch/workspace/your_files/personal-graphify/src/personal_graphify/serve.py` — community 1
- **README.md** (doc) — degree 33 — file `/home/hatch/workspace/your_files/personal-graphify/README.md` — community 2
- **AGENTIC_GUIDE.md** (doc) — degree 32 — file `/home/hatch/workspace/your_files/personal-graphify/AGENTIC_GUIDE.md` — community 7
- **Personal Graphify** (tool) — degree 31 — file `` — community 2
- **SKILL.md** (doc) — degree 31 — file `/home/hatch/workspace/your_files/personal-graphify/skills/graphify-personal/SKILL.md` — community 2
- **SKILL.md** (doc) — degree 26 — file `/home/hatch/workspace/your_files/personal-graphify/.agents/skills/graphify/SKILL.md` — community 2
- **report.py** (file) — degree 24 — file `/home/hatch/workspace/your_files/personal-graphify/src/personal_graphify/report.py` — community 2
- **file:/home/hatch/workspace/your_files/personal-graphify/src/personal_graphify/templates/graphify.mdc** (inferred_ref) — degree 24 — file `` — community 2
- **file:/home/hatch/workspace/your_files/personal-graphify/.cursor/rules/graphify.mdc** (inferred_ref) — degree 24 — file `` — community 2
- **cmd_build** (function) — degree 23 — file `/home/hatch/workspace/your_files/personal-graphify/src/personal_graphify/cli.py` — community 1
- **Ava AGI Factory v6.4** (ml_concept) — degree 22 — file `` — community 2

## Communities

- **Community 0** — 100 nodes — types [('inferred_ref', 52), ('function', 29), ('module', 8), ('symbol', 7), ('file', 4)] — sample: typing, List, group_by_type, re, Dict
- **Community 1** — 100 nodes — types [('inferred_ref', 40), ('symbol', 30), ('function', 14), ('module', 14), ('file', 2)] — sample: ensure_containment, Any, cli.py, argparse, sys
- **Community 2** — 93 nodes — types [('concept', 25), ('file', 9), ('integration', 8), ('ml_concept', 8), ('product', 7)] — sample: README.md, Personal Graphify — Knowledge , Install (30 seconds), isolated install (recommended), or pip install -e .
- **Community 3** — 35 nodes — types [('concept', 34), ('doc', 1)] — sample: INSTALL_GUIDE.md, Private GitHub Repo Setup + Cu, 1. Create Private GitHub Repo, Option A — with gh CLI (recomm, Creates private repo github.co
- **Community 4** — 35 nodes — types [('inferred_ref', 25), ('function', 9), ('rationale', 1)] — sample: load_ignore_file, is_safe_url, hash_id, extract_python, _ts_extract_symbols
- **Community 5** — 28 nodes — types [('inferred_ref', 9), ('module', 7), ('file', 4), ('symbol', 4), ('function', 3)] — sample: LICENSE, ARR, detect.py, os, fnmatch
- **Community 6** — 22 nodes — types [('inferred_ref', 20), ('function', 2)] — sample: main, main, func:getattr, func:ArgumentParser, func:add_subparsers
- **Community 7** — 18 nodes — types [('concept', 16), ('doc', 1), ('reference', 1)] — sample: AGENTIC_GUIDE.md, Agentic Guide — Coding Smarter, Why this beats plain Cursor, Architecture (from Graphify do, Personal Overlay — How we mapp
- **Community 8** — 12 nodes — types [('concept', 7), ('metadata', 4), ('doc', 1)] — sample: SKILL.md, name: graphify-core, description: Core Graphify ski, version: 1.0.0, provider: ollama
- **Community 9** — 11 nodes — types [('concept', 6), ('metadata', 4), ('doc', 1)] — sample: SKILL.md, name: graphify-agentic, description: Teaches AI agents, version: 1.0.0, provider: ollama
- **Community 10** — 9 nodes — types [('concept', 8), ('doc', 1)] — sample: BUILD_SUMMARY.md, Build Summary — Personal Graph, What you asked, What I built, Also added to ava-skills (your
- **Community 11** — 3 nodes — types [('doc', 1), ('metadata', 1), ('concept', 1)] — sample: graphify.mdc, description: Personal Graphify, 🐾 Personal Graphify Rule — Que
- **Community 12** — 3 nodes — types [('doc', 1), ('metadata', 1), ('concept', 1)] — sample: graphify.mdc, description: Personal Graphify, 🐾 Personal Graphify Rule — Que
- **Community 13** — 1 nodes — types [('doc', 1)] — sample: dependency_links.txt
- **Community 14** — 1 nodes — types [('doc', 1)] — sample: entry_points.txt

## Surprising Connections (cross-community, cross-file)

- `extract.py` [imports] → `Path` — [EXTRACTED] — files differ? True — communities (2, 5)
- `extract.py` [imports] → `List` — [EXTRACTED] — files differ? True — communities (2, 0)
- `report.py` [imports] → `networkx` — [EXTRACTED] — files differ? True — communities (2, 0)
- `report.py` [imports] → `Path` — [EXTRACTED] — files differ? True — communities (2, 5)
- `report.py` [imports] → `List` — [EXTRACTED] — files differ? True — communities (2, 0)
- `report.py` [imports] → `Dict` — [EXTRACTED] — files differ? True — communities (2, 0)
- `export.py` [imports] → `networkx` — [EXTRACTED] — files differ? True — communities (5, 0)
- `query.py` [imports] → `json` — [EXTRACTED] — files differ? True — communities (0, 5)
- `query.py` [imports] → `Path` — [EXTRACTED] — files differ? True — communities (0, 5)
- `cli.py` [imports] → `Path` — [EXTRACTED] — files differ? True — communities (1, 5)
- `cli.py` [imports] → `json` — [EXTRACTED] — files differ? True — communities (1, 5)
- `serve.py` [imports] → `json` — [EXTRACTED] — files differ? True — communities (1, 5)

## Suggested Questions (ask via `pgraphify query`)

- `pgraphify query "what connects auth to database?"`
- `pgraphify query "where is turnover retention logic?"`
- `pgraphify query "how does Ava J-space Planner interact with Critic?"`
- `pgraphify query "trace Stripe webhook to Paid Users MRR"`
- `pgraphify query "show MTNN heads 48→64→k"`

## Rationale & Why

- `NOTE: , # WHY, # HACK, # TODO, # FIXME, # BUG` @ /home/hatch/workspace/your_files/personal-graphify/src/personal_graphify/extract.py:109 — explains nearby code
- `NOTE: / # WHY comments found. Consider adding them — they become first-class graph nodes linked to code.")` @ /home/hatch/workspace/your_files/personal-graphify/src/personal_graphify/report.py:51 — explains nearby code

## Personal Ecosystem Overlay

- **Family Brain**: Joint accounts, Betterment buckets, Plaid 5 institutions, Emergency $136.5k
- **Passive Lab**: Turnover Shield $79-$149/mo, 7-13 customers → $1k MRR, Stripe → Supabase → Workers free-tier
- **Ava AGI**: multi_jspace_module.py 4 workspaces S1 hl=8 S2 hl=300 Critic hl=30 Planner hl=150, Router/veto
- **Vector Hoops**: 12,966 player-seasons, MTNN v5_concat_b2_h160_t32_d48_mlp128, CQS 85.87, leakfree 0.7937 composite

> Use `pgraphify path "A" "B"` to trace any two concepts.
