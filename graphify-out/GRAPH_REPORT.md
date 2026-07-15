# Personal Graphify Report

Solo personal project, no connection to employer, built with public/free-tier only.

**Nodes:** 727 · **Edges:** 1713 · **Communities:** 49

Token estimate: ~1500 tokens per scoped query vs ~52750 naive → **35.2× reduction** (mirrors upstream 71.5×).

## God Nodes (highest-degree concepts)

- **func:command** (inferred_ref) — degree 57 — file `` — community 0
- **func:emit** (inferred_ref) — degree 56 — file `` — community 0
- **cli.py** (file) — degree 54 — file `/home/hatch/workspace/bigbang-cli/bigbang/plugins/agent/cli.py` — community 1
- **graphify-integration.md** (doc) — degree 49 — file `/home/hatch/workspace/bigbang-cli/docs/llm-wiki/graphify-integration.md` — community 4
- **cli.py** (file) — degree 48 — file `/home/hatch/workspace/bigbang-cli/bigbang/plugins/ava/cli.py` — community 1
- **cli.py** (file) — degree 46 — file `/home/hatch/workspace/bigbang-cli/bigbang/plugins/auth/cli.py` — community 0
- **README.md** (doc) — degree 40 — file `/home/hatch/workspace/bigbang-cli/README.md` — community 6
- **openapi.py** (file) — degree 35 — file `/home/hatch/workspace/bigbang-cli/bigbang/core/openapi.py` — community 1
- **cli.py** (file) — degree 35 — file `/home/hatch/workspace/bigbang-cli/bigbang/plugins/mcp/cli.py` — community 1
- **cli.py** (file) — degree 34 — file `/home/hatch/workspace/bigbang-cli/bigbang/plugins/tools/cli.py` — community 1
- **cli.py** (file) — degree 34 — file `/home/hatch/workspace/bigbang-cli/bigbang/plugins/tasks/cli.py` — community 0
- **llm.py** (file) — degree 28 — file `/home/hatch/workspace/bigbang-cli/bigbang/core/llm.py` — community 1
- **Ava AGI Factory v6.4** (ml_concept) — degree 27 — file `` — community 1
- **func:Argument** (inferred_ref) — degree 27 — file `` — community 0
- **tasks-plugin.md** (doc) — degree 26 — file `/home/hatch/workspace/bigbang-cli/docs/llm-wiki/tasks-plugin.md` — community 10

## Communities

- **Community 0** — 157 nodes — types [('inferred_ref', 77), ('function', 74), ('module', 3), ('file', 2), ('symbol', 1)] — sample: doctor_cmd, _save, _save, _sanitize_identifier, _sanitize_cmd_name
- **Community 1** — 131 nodes — types [('symbol', 44), ('module', 33), ('function', 22), ('file', 20), ('inferred_ref', 9)] — sample: Ava AGI Factory v6.4, Ollama qwen3:32b local, cli.py, sys, pathlib
- **Community 2** — 88 nodes — types [('concept', 45), ('function', 11), ('file', 10), ('product', 5), ('doc', 5)] — sample: Stripe, Davis Family Brain, MTNN v5_concat_b2_h160_t32_d48, Ava Planner hl150, Vector Hoops 12,966 seasons
- **Community 3** — 65 nodes — types [('inferred_ref', 38), ('function', 26), ('file', 1)] — sample: set_json_mode, check_permission, discovery.py, fetch_openapi, discover_mcp_tools
- **Community 4** — 41 nodes — types [('concept', 36), ('ml_concept', 3), ('doc', 1), ('business_metric', 1)] — sample: graphify-integration.md, Graphify Integration — LLM Wik, What is Personal Graphify?, Install & Outputs (for referen, outputs:
- **Community 5** — 39 nodes — types [('inferred_ref', 22), ('function', 17)] — sample: _load_manifest, discover_plugins, list_plugin_names, get_all_manifests, _load
- **Community 6** — 33 nodes — types [('concept', 32), ('doc', 1)] — sample: README.md, BigBang CLI — One CLI to Rule , Vision: Why One CLI?, Add any tool in 5 seconds, Use them — human or agent
- **Community 7** — 30 nodes — types [('concept', 24), ('doc', 2), ('file', 2), ('tool', 1), ('integration', 1)] — sample: Personal Graphify, security-model.md, Security Model — LLM Wiki, Principles, Manifest Capability Examples
- **Community 8** — 24 nodes — types [('inferred_ref', 11), ('module', 5), ('function', 4), ('symbol', 3), ('file', 1)] — sample: mcp_client.py, asyncio, _mcp_http_client_factory, list_mcp_tools_sync, call_mcp_tool_sync
- **Community 9** — 23 nodes — types [('function', 11), ('inferred_ref', 9), ('module', 2), ('file', 1)] — sample: emit, security.py, stat, set_secret, get_secret
- **Community 10** — 20 nodes — types [('concept', 19), ('doc', 1)] — sample: tasks-plugin.md, Tasks Plugin — LLM Wiki (Wired, Why Tasks Matters, Implementation File, Core Function
- **Community 11** — 16 nodes — types [('concept', 15), ('doc', 1)] — sample: architecture.md, Architecture v0.4.1 — LLM Wiki, TL;DR for LLM, Core Flow v0.4.1, Security Checklist v0.4.1 (sti
- **Community 12** — 9 nodes — types [('module', 2), ('symbol', 2), ('class', 2), ('file', 1), ('function', 1)] — sample: context.py, pydantic_settings, BaseSettings, pydantic, Field
- **Community 13** — 6 nodes — types [('function', 3), ('inferred_ref', 2), ('file', 1)] — sample: http_utils.py, _clean_no_proxy_value, sanitize_no_proxy_env, get_httpx_client_kwargs, func:count
- **Community 15** — 4 nodes — types [('function', 3), ('inferred_ref', 1)] — sample: manifest, get_manifest, test_plugin_list_security_firs, func:list_plugin_names

## Surprising Connections (cross-community, cross-file)

- `context.py` [imports] → `Path` — [EXTRACTED] — files differ? True — communities (12, 1)
- `security.py` [imports] → `Path` — [EXTRACTED] — files differ? True — communities (9, 1)
- `security.py` [imports] → `json` — [EXTRACTED] — files differ? True — communities (9, 1)
- `http_utils.py` [imports] → `os` — [EXTRACTED] — files differ? True — communities (13, 1)
- `mcp_client.py` [imports] → `annotations` — [EXTRACTED] — files differ? True — communities (8, 1)
- `mcp_client.py` [imports] → `Any` — [EXTRACTED] — files differ? True — communities (8, 1)
- `mcp_client.py` [imports] → `Dict` — [EXTRACTED] — files differ? True — communities (8, 1)
- `mcp_client.py` [imports] → `List` — [EXTRACTED] — files differ? True — communities (8, 1)
- `mcp_client.py` [imports] → `Optional` — [EXTRACTED] — files differ? True — communities (8, 1)
- `mcp_client.py` [imports] → `httpx` — [EXTRACTED] — files differ? True — communities (8, 1)
- `cli.py` [imports] → `typer` — [EXTRACTED] — files differ? True — communities (2, 1)
- `cli.py` [imports] → `typer` — [EXTRACTED] — files differ? True — communities (2, 1)

## Suggested Questions (ask via `pgraphify query`)

- `pgraphify query "what connects auth to database?"`
- `pgraphify query "where is turnover retention logic?"`
- `pgraphify query "how does Ava J-space Planner interact with Critic?"`
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
