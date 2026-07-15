# Personal Graphify Report

Solo personal project, no connection to employer, built with public/free-tier only.

**Nodes:** 525 · **Edges:** 1250 · **Communities:** 19

Token estimate: ~1500 tokens per scoped query vs ~34250 naive → **22.8× reduction** (mirrors upstream 71.5×).

## God Nodes (highest-degree concepts)

- **cli.py** (file) — degree 66 — file `/home/hatch/workspace/your_files/personal-graphify/src/personal_graphify/cli.py` — community 2
- **extract.py** (file) — degree 62 — file `/home/hatch/workspace/your_files/personal-graphify/src/personal_graphify/extract.py` — community 1
- **query.py** (file) — degree 56 — file `/home/hatch/workspace/your_files/personal-graphify/src/personal_graphify/query.py` — community 0
- **INSTALL_GUIDE.md** (doc) — degree 51 — file `/home/hatch/workspace/your_files/personal-graphify/INSTALL_GUIDE.md` — community 4
- **serve.py** (file) — degree 44 — file `/home/hatch/workspace/your_files/personal-graphify/src/personal_graphify/serve.py` — community 2
- **graphify-public-non-pii.json** (file) — degree 35 — file `/home/hatch/workspace/your_files/personal-graphify/docs/public/graphify-public-non-pii.json` — community 1
- **README.md** (doc) — degree 34 — file `/home/hatch/workspace/your_files/personal-graphify/README.md` — community 1
- **Personal Graphify** (tool) — degree 33 — file `` — community 1
- **AGENTIC_GUIDE.md** (doc) — degree 33 — file `/home/hatch/workspace/your_files/personal-graphify/AGENTIC_GUIDE.md` — community 6
- **func:len** (inferred_ref) — degree 28 — file `` — community 0
- **file:/home/hatch/workspace/your_files/personal-graphify/src/personal_graphify/templates/graphify.mdc** (inferred_ref) — degree 27 — file `` — community 1
- **file:/home/hatch/workspace/your_files/personal-graphify/.cursor/rules/graphify.mdc** (inferred_ref) — degree 27 — file `` — community 1
- **cmd_build** (function) — degree 26 — file `/home/hatch/workspace/your_files/personal-graphify/src/personal_graphify/cli.py` — community 0
- **SKILL.md** (doc) — degree 26 — file `/home/hatch/workspace/your_files/personal-graphify/.agents/skills/graphify/SKILL.md` — community 1
- **report.py** (file) — degree 24 — file `/home/hatch/workspace/your_files/personal-graphify/src/personal_graphify/report.py` — community 1

## Communities

- **Community 0** — 164 nodes — types [('inferred_ref', 105), ('function', 47), ('symbol', 5), ('module', 5), ('file', 2)] — sample: load_ignore_file, group_by_type, Tuple, extract_python, extract_js_generic
- **Community 1** — 99 nodes — types [('concept', 23), ('file', 11), ('integration', 8), ('product', 8), ('ml_concept', 8)] — sample: README.md, Personal Graphify — Knowledge , Install (30 seconds), isolated install (recommended), or pip install -e .
- **Community 2** — 80 nodes — types [('symbol', 36), ('module', 22), ('inferred_ref', 9), ('file', 6), ('function', 6)] — sample: LICENSE, ARR, pathlib, Path, security.py
- **Community 3** — 39 nodes — types [('inferred_ref', 33), ('function', 6)] — sample: is_ignored, is_safe_url, get_ollama_embeddings, _cost_path_for_graph, main
- **Community 4** — 35 nodes — types [('concept', 34), ('doc', 1)] — sample: INSTALL_GUIDE.md, Private GitHub Repo Setup + Cu, 1. Create Private GitHub Repo, Option A — with gh CLI (recomm, Creates private repo github.co
- **Community 5** — 29 nodes — types [('module', 8), ('inferred_ref', 8), ('symbol', 5), ('function', 5), ('file', 3)] — sample: detect.py, os, fnmatch, typing, List
- **Community 6** — 18 nodes — types [('concept', 16), ('doc', 1), ('reference', 1)] — sample: AGENTIC_GUIDE.md, Agentic Guide — Coding Smarter, Why this beats plain Cursor, Architecture (from Graphify do, Personal Overlay — How we mapp
- **Community 7** — 13 nodes — types [('inferred_ref', 9), ('function', 4)] — sample: collect_files, ensure_containment, _ts_extract_symbols, walk, func:resolve
- **Community 8** — 9 nodes — types [('concept', 8), ('doc', 1)] — sample: BUILD_SUMMARY.md, Build Summary — Personal Graph, What you asked, What I built, Also added to ava-skills (your
- **Community 9** — 9 nodes — types [('concept', 7), ('doc', 1), ('metadata', 1)] — sample: graphify.mdc, description: Personal Graphify, 🐾 Personal Graphify SOTA Rule , 1. Understand repo in 30s, 2. Given task, compile to mini
- **Community 10** — 9 nodes — types [('concept', 7), ('doc', 1), ('metadata', 1)] — sample: graphify.mdc, description: Personal Graphify, 🐾 Personal Graphify SOTA Rule , 1. Understand repo in 30s, 2. Given task, compile to mini
- **Community 11** — 8 nodes — types [('inferred_ref', 6), ('function', 2)] — sample: extract_file, extract_all, func:extract_personal_patterns, func:extend, func:extract_python
- **Community 12** — 4 nodes — types [('inferred_ref', 3), ('function', 1)] — sample: hash_id, func:hexdigest, func:md5, func:encode
- **Community 13** — 4 nodes — types [('metadata', 2), ('doc', 1), ('concept', 1)] — sample: SKILL.md, name: graphify-core, description: Graphify core — q, Graphify Core SOTA
- **Community 14** — 1 nodes — types [('doc', 1)] — sample: dependency_links.txt

## Surprising Connections (cross-community, cross-file)

- `extract.py` [imports] → `Path` — [EXTRACTED] — files differ? True — communities (1, 2)
- `extract.py` [imports] → `List` — [EXTRACTED] — files differ? True — communities (1, 5)
- `analyze.py` [imports] → `networkx` — [EXTRACTED] — files differ? True — communities (0, 5)
- `analyze.py` [imports] → `List` — [EXTRACTED] — files differ? True — communities (0, 5)
- `analyze.py` [imports] → `Dict` — [EXTRACTED] — files differ? True — communities (0, 5)
- `report.py` [imports] → `networkx` — [EXTRACTED] — files differ? True — communities (1, 5)
- `report.py` [imports] → `Path` — [EXTRACTED] — files differ? True — communities (1, 2)
- `report.py` [imports] → `List` — [EXTRACTED] — files differ? True — communities (1, 5)
- `report.py` [imports] → `Dict` — [EXTRACTED] — files differ? True — communities (1, 5)
- `export.py` [imports] → `networkx` — [EXTRACTED] — files differ? True — communities (2, 5)
- `query.py` [imports] → `json` — [EXTRACTED] — files differ? True — communities (0, 2)
- `query.py` [imports] → `os` — [EXTRACTED] — files differ? True — communities (0, 5)

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
