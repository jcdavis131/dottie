# Personal Graphify Report

Solo personal project, no connection to employer, built with public/free-tier only.

**Nodes:** 972 · **Edges:** 2737 · **Communities:** 47

Token estimate: ~1500 tokens per scoped query vs ~69800 naive → **46.5× reduction** (mirrors upstream 71.5×).

## God Nodes (highest-degree concepts)

- **func:command** (inferred_ref) — degree 92 — file `` — community 0
- **func:emit** (inferred_ref) — degree 90 — file `` — community 0
- **Scout CLI** (tool) — degree 67 — file `` — community 1
- **README.md** (doc) — degree 60 — file `C:\Users\jcdav\scout-cli\README.md` — community 6
- **cli.py** (file) — degree 58 — file `C:\Users\jcdav\scout-cli\bigbang\plugins\agent\cli.py` — community 1
- **cli.py** (file) — degree 53 — file `C:\Users\jcdav\scout-cli\bigbang\plugins\ava\cli.py` — community 1
- **test_cli.py** (file) — degree 53 — file `C:\Users\jcdav\scout-cli\tests\test_cli.py` — community 5
- **func:Option** (inferred_ref) — degree 53 — file `` — community 0
- **func:str** (inferred_ref) — degree 50 — file `` — community 0
- **cli.py** (file) — degree 47 — file `C:\Users\jcdav\scout-cli\bigbang\plugins\auth\cli.py` — community 1
- **Ava AGI Factory v6.4** (ml_concept) — degree 46 — file `` — community 1
- **cli.py** (file) — degree 46 — file `C:\Users\jcdav\scout-cli\bigbang\plugins\write\cli.py` — community 0
- **func:Argument** (inferred_ref) — degree 41 — file `` — community 0
- **func:len** (inferred_ref) — degree 40 — file `` — community 0
- **EXTENDING.md** (doc) — degree 38 — file `C:\Users\jcdav\scout-cli\docs\EXTENDING.md` — community 7

## Communities

- **Community 0** — 215 nodes — types [('function', 108), ('inferred_ref', 101), ('file', 3), ('module', 2), ('symbol', 1)] — sample: log_event, parse_operations, _collect_secret_headers, call_openapi, generate_typer_plugin
- **Community 1** — 176 nodes — types [('symbol', 45), ('file', 42), ('module', 38), ('function', 37), ('inferred_ref', 9)] — sample: Ava AGI Factory v6.4, Personal Graphify, Scout CLI, Tennis DINOv3 ExecuTorch, cli.py
- **Community 2** — 121 nodes — types [('concept', 73), ('file', 11), ('ml_concept', 7), ('doc', 7), ('integration', 5)] — sample: Stripe, First $1k/mo passive goal, Turnover Shield, Davis Family Brain, MRR / Paid Users
- **Community 3** — 85 nodes — types [('inferred_ref', 46), ('function', 38), ('file', 1)] — sample: discovery.py, fetch_openapi, discover_mcp_tools, _httpx_client, get_ollama_base
- **Community 4** — 84 nodes — types [('inferred_ref', 44), ('function', 39), ('file', 1)] — sample: tail_events, http_utils.py, _clean_no_proxy_value, sanitize_no_proxy_env, get_httpx_client_kwargs
- **Community 5** — 61 nodes — types [('function', 19), ('inferred_ref', 15), ('module', 12), ('symbol', 12), ('file', 3)] — sample: mcp_client.py, asyncio, _mcp_http_client_factory, list_mcp_tools_sync, call_mcp_tool_sync
- **Community 6** — 54 nodes — types [('concept', 51), ('doc', 2), ('tool', 1)] — sample: INTEGRATION.md, Scout Integration STAT — v0.6., Repos, Integration, Install everywhere
- **Community 7** — 27 nodes — types [('concept', 26), ('doc', 1)] — sample: EXTENDING.md, Extending BigBang CLI v0.5 — A, 30-sec Plugin, edits bigbang/plugins/mytool/m, instantly in bb --help and bb 
- **Community 8** — 20 nodes — types [('concept', 19), ('doc', 1)] — sample: tasks-plugin.md, Tasks Plugin — LLM Wiki (Wired, Why Tasks Matters, Implementation File, Core Function
- **Community 9** — 16 nodes — types [('concept', 15), ('doc', 1)] — sample: architecture.md, Architecture v0.4.1 — LLM Wiki, TL;DR for LLM, Core Flow v0.4.1, Security Checklist v0.4.1 (sti
- **Community 10** — 14 nodes — types [('concept', 13), ('doc', 1)] — sample: quickstart.md, BigBang CLI Quickstart — LLM W, Install & Doctor, Google Tasks Wiring (new v0.4., Universal Tool Registry
- **Community 11** — 12 nodes — types [('function', 7), ('inferred_ref', 5)] — sample: _is_resolvable, _do, _is_resolvable_fast, _do, _open_browser_url
- **Community 12** — 12 nodes — types [('concept', 11), ('doc', 1)] — sample: security-model.md, Security Model — LLM Wiki, Principles, Manifest Capability Examples, tools plugin — allows specific
- **Community 13** — 11 nodes — types [('concept', 8), ('doc', 1), ('reference', 1), ('product', 1)] — sample: graphify-integration.md, Graphify Integration — Scout C, What is baked in, Prerequisites, or: pip install -e ~/personal-
- **Community 14** — 9 nodes — types [('module', 2), ('symbol', 2), ('class', 2), ('file', 1), ('function', 1)] — sample: context.py, pydantic_settings, BaseSettings, pydantic, Field

## Surprising Connections (cross-community, cross-file)

- `context.py` [imports] → `Path` — [EXTRACTED] — files differ? True — communities (14, 1)
- `http_utils.py` [imports] → `os` — [EXTRACTED] — files differ? True — communities (4, 1)
- `mcp_client.py` [imports] → `annotations` — [EXTRACTED] — files differ? True — communities (5, 1)
- `mcp_client.py` [imports] → `Any` — [EXTRACTED] — files differ? True — communities (5, 1)
- `mcp_client.py` [imports] → `Dict` — [EXTRACTED] — files differ? True — communities (5, 1)
- `mcp_client.py` [imports] → `List` — [EXTRACTED] — files differ? True — communities (5, 1)
- `mcp_client.py` [imports] → `Optional` — [EXTRACTED] — files differ? True — communities (5, 1)
- `mcp_client.py` [imports] → `httpx` — [EXTRACTED] — files differ? True — communities (5, 1)
- `cli.py` [imports] → `annotations` — [EXTRACTED] — files differ? True — communities (0, 1)
- `cli.py` [imports] → `Path` — [EXTRACTED] — files differ? True — communities (0, 1)
- `cli.py` [imports] → `List` — [EXTRACTED] — files differ? True — communities (0, 1)
- `cli.py` [imports] → `Optional` — [EXTRACTED] — files differ? True — communities (0, 1)

## Suggested Questions (ask via `pgraphify query`)

- `pgraphify query "what connects auth to database?"`
- `pgraphify query "where is turnover retention logic?"`
- `pgraphify query "how does Ava J-space Planner interact with Critic?"`
- `pgraphify query "how does Scout connect to Ava?"`
- `pgraphify query "trace Stripe webhook to Paid Users MRR"`
- `pgraphify query "show MTNN heads 48→64→k"`

## Rationale & Why

- No # NOTE / # WHY comments found. Consider adding them — they become first-class graph nodes linked to code.

## Personal Ecosystem Overlay

- **Family Brain**: Joint accounts, Betterment buckets, Plaid 5 institutions, Emergency $136.5k
- **Passive Lab**: Turnover Shield $79-$149/mo, 7-13 customers → $1k MRR, Stripe → Supabase → Workers free-tier
- **Ava AGI**: multi_jspace_module.py 4 workspaces S1 hl=8 S2 hl=300 Critic hl=30 Planner hl=150, Router/veto
- **Vector Hoops**: 12,966 player-seasons, MTNN v5_concat_b2_h160_t32_d48_mlp128, CQS 85.87, leakfree 0.7937 composite

> Use `pgraphify path "A" "B"` to trace any two concepts.
