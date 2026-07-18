# Architecture v0.4.1 — LLM Wiki (Tasks Wired)

**Solo personal project, no connection to employer, built with public/free-tier only**

## TL;DR for LLM
BigBang CLI v0.4.1 = v0.4 real MCP SDK + OpenAPI codegen + Ava Ollama router + Google Tasks plugin `bb tasks` wired via `hatch_gws_cli`. One binary `bb` proxies 12 plugins, each with `manifest.yaml` capability caps, vault 0600, audit log. Token-efficient via graphify: `graphify-out/graph.json` ~2k tokens vs 123k naive.

## Core Flow v0.4.1
```
User: bb tasks add "Ship Turnover Shield"
  -> plugin_loader.discover_plugins() finds bigbang/plugins/tasks/cli.py
  -> tasks/cli.py sanitize_no_proxy_env() (fixes Hatch [::1] bug)
  -> _run_gws(["tasks","insert","--params",'{"tasklist":"@default"}'], {"title":...})
     -> subprocess hatch_gws_cli tasks tasks insert (Hatch-managed OAuth)
     -> Google Tasks API (Lina's Morning/Afternoon lists)
  -> emit({"created": {...}}, command="tasks add") -> JSON if --json else Rich
  -> audit.py append audit.jsonl with command, timestamp, no secret

Agent: bb agent run "my Lina morning todos"
  -> core/llm.py get_ollama_base() tries localhost:11434, host.docker.internal:11434 2s timeout, DNS-safe
  -> if Ollama up: ollama_chat(model=qwen3:32b, json_mode) -> {"plan": ["bb tasks lists", "bb tasks list --tasklist ..."]}
  -> else: heuristic _heuristic_plan() keyword "lina" -> builtin_hints["lina"] -> "bb tasks lists" + search
  -> payload plan 0.92 confidence -> user sees plan, would execute stepwise with policy checks

Ava: bb ava route "my tasks"
  -> _ollama_available() cached 30s TTL
  -> _heuristic_route() sees "task"/"todo"/"lina" -> picked_tool tasks, command bb tasks list confidence 0.92
```

## Security Checklist v0.4.1 (still holds)
- [x] Vault 0600 `~/.local/share/bigbang/secrets.json` + keyring + BB_SECRET_ env — tasks plugin uses 0 secrets, auth via Hatch GWS
- [x] Policy `enforce_or_raise(manifest, "network", url)` before any fetch/call — tasks has network.enabled=false, so no external net directly
- [x] Manifest caps in every plugin v0.4.0 — tasks manifest allows fs write only to llm-wiki/
- [x] Audit logging hook in output.py — all tasks commands emit -> audit tail_events() -> sync-bb can import
- [x] NO_PROXY sanitization — prevents proxy bypass / SSRF via malformed [] IPv6
- [x] No finance, local-first, public/free-tier only, disclaimer footer on generated files + llm-wiki

## New Core Components

### `core/http_utils.py` (NEW in v0.4)
```python
def sanitize_no_proxy_env():
  for k in ["no_proxy","NO_PROXY"]:
    v = os.environ.get(k)
    if not v: continue
    parts = [p.strip() for p in v.split(",")]
    cleaned = [p for p in parts if p not in ("[::1]","[fd8b:4f84:7d32:99::1]","[fd8b:4f84:7d32:99::2]") and "::" not in p and not p.startswith("[")]
    os.environ[k] = ",".join(cleaned)
  # auto-called on import
```

### `core/mcp_client.py` (NEW v0.4)
- `from mcp.client.sse import sse_client; from mcp.client.streamablehttp import streamablehttp_client; from mcp.client.session import ClientSession`
- `_mcp_http_client_factory()` calls sanitize_no_proxy_env() + trust_env=True cleaned
- `list_mcp_tools_sync(url)` -> asyncio.run(list_mcp_tools(url)) -> sse_client(url) -> ClientSession.list_tools() -> fallback streamablehttp
- `call_mcp_tool_sync(url, tool_name, args)`

### `core/openapi.py` (NEW v0.4)
- `fetch_spec(url)` -> httpx + sanitize
- `parse_operations(spec)` -> list of ops with host/basePath/servers handling
- `_resolve_base_url()` -> servers[0].url OR host+basePath OR fallback_url
- `call_openapi(tool, operation, args)` -> enforce_or_raise(manifest, "network", url) -> httpx.request()
- `generate_typer_plugin(name, spec, url)` -> creates `plugins/<name>/{cli.py, manifest.yaml, __init__.py}` with SPEC_HOST, SPEC_BASE, TOOL_MANIFEST, per-op Typer commands with enforce

### `core/llm.py` (NEW v0.4)
- `OLLAMA_URLS = ["http://localhost:11434", "http://host.docker.internal:11434"]`
- `PREFERRED_MODELS = ["qwen3:32b", "qwen3:32b-instruct", ...]`
- `get_ollama_base(timeout=2.0)` -> cached 30s, DNS thread-safe via `_is_resolvable_fast()`
- `ollama_chat(model, messages, json_mode, base, timeout)` -> httpx post /api/chat
- `extract_json_from_text(text)` -> handles ```json + trailing

### `plugins/tasks/cli.py` (NEW v0.4.1)
- Real impl using `subprocess.run(["hatch_gws_cli","tasks",...])` 0.8-1.5s per call
- 11 commands, all emit JSON + disclaimer
- `sync-bb` reads audit.jsonl recent 20 -> creates starter tasks for Turnover Shield, LLM-wiki, graphify
- `export` writes JSON to `docs/llm-wiki/tasks-*.json`

## Manifest Spec v0.4.1 Example (tasks)
```yaml
name: tasks
version: 0.4.0
description: Google Tasks — task lists + tasks CRUD wired into BigBang via hatch_gws_cli, agent-native
capabilities:
  network:
    enabled: false
    domains: []
  filesystem:
    enabled: true
    write: true
    paths: ["~/workspace/bigbang-cli/docs/llm-wiki/", "~/.local/share/bigbang/"]
  secrets:
    allow: []
tags: [productivity, google, tasks, gws]
```

## Growth: Tool Registry + Tasks
- `bb tools add api --type openapi --url ...` -> `bb tools generate api` -> per-op commands with policy netloc
- `bb mcp add server https://.../sse` -> `bb mcp list-tools server` -> real SDK
- `bb tasks add "Build Turnover Shield $79/mo"` -> Google Tasks list -> `bb agent run` can auto-pick tasks high confidence
- `bb tasks sync-bb` -> audit -> tasks -> export -> graphify ingestion

## Verification v0.4.1
- `pytest -q` 6/6
- `bb --help` 12 cmds now (tasks added)
- `bb tasks status --json` -> connected, 2 lists
- `bb tasks lists --json` -> Lina's Morning/Afternoon etag "hMtUqH..."
- `bb tasks list --json` -> tasks in @default (if any)
- `bb tasks add "Test wiki" --json` -> created id
- `bb ava route "my todos"` -> picked_tool tasks confidence 0.92
- `bb agent run "list Lina tasks"` -> plan includes bb tasks lists
- `bb system doctor --json` -> vault 0600, registry, audit OK, ollama down expected

## Graphify Integration Points
- `pgraphify build .` over bigbang-cli -> parses 12 plugins AST (Tree-sitter), builds NetworkX graph: nodes=files/classes/funcs, edges=calls/imports
- `graphify-out/graph.json` queryable: `pgraphify query "tasks sync-bb"` -> subgraph: tasks/cli.py::_run_gws + audit.py::tail_events + hatch_gws_cli wrapper
- `docs/llm-wiki/*.md` are additional markdown nodes — semantic extraction via Ollama qwen3:32b optional
- Token reduction holds: upstream example 428 nodes 614 edges 58 communities ~71.5x

# Solo personal project, no connection to employer, built with public/free-tier only
