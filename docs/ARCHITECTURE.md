# Architecture v0.4 — Real MCP SDK + OpenAPI Codegen + Ava Ollama Router

## Vision
BigBang is *the* universal router: one CLI to rule all internet tools (OpenAPI, MCP, CLI, Docker, Python) with security-first, agent-native, Ava-brained.

## What's New in v0.4 (from v0.3.1)

- **Real MCP SDK**: `bigbang/core/mcp_client.py` uses `mcp>=1.28.1` with `sse_client` + `streamablehttp_client` fallback and `ClientSession.list_tools/call_tool`. `bb mcp list-tools <server>` and `bb mcp call <server> <tool> '{"arg":...}'` hit real servers.
- **OpenAPI Codegen**: `bigbang/core/openapi.py` fetches spec (with NO_PROXY sanitization), parses ops (including Swagger 2.0 host/basePath), generates `bigbang/plugins/<name>/{cli.py, manifest.yaml, __init__.py}` with Typer commands, policy enforcement via `enforce_or_raise`, auth headers from vault. Limit 25 ops. E2E: `bb tools add petstore --type openapi --url https://petstore.swagger.io/v2/swagger.json` → `bb tools generate petstore` → `bb petstore findPetsByStatus --status available`.
- **Ava Ollama Router**: `bigbang/core/llm.py` resilient Ollama detection (localhost:11434, host.docker.internal:11434, 2s timeout, DNS-safe via thread), `OLLAMA_URLS`, `PREFERRED_MODELS` qwen3:32b preferred. `bb ava status` shows models, `bb ava route "<task>"` tries Ollama JSON routing then heuristic fallback. `bb agent run "<task>"` uses same router to produce plan of bb commands.
- **Proxy Fix**: `bigbang/core/http_utils.py` `sanitize_no_proxy_env()` strips `[::1]` brackets and IPv6 CIDR entries (`::`, `fd8b:...`) that break `httpx` URLPattern (`Invalid port: ':1]'`). Called on import in all network modules; `trust_env=True` (cleaned env) instead of False.
- **Policy Enforcement**: Every network call now: manifest caps check before fetch/call via `enforce_or_raise(manifest, "network", url)`. OpenAPI tool add stores domain as `netloc` (petstore.swagger.io), not full spec URL, so allowlist matches real API base.
- **Security Still First**: vault 0600 + keyring + BB_SECRET_ env, audit.jsonl, default deny `network.domains`, `fs.write`, `secrets.allow`.

## Core Flow v0.4
```
User/Agent -> bb <plugin> <cmd> --json (Typer + Rich)
  -> http_utils.sanitize_no_proxy_env()
  -> policy.py enforce_or_raise(manifest.yaml caps, network domain)
  -> security.py vault get_secret (for auth)
  -> registry.py lookup
  -> adapter:
     openapi: fetch_spec -> parse_operations -> call_openapi (httpx + _resolve_base_url) OR generated plugin cli.py (each op -> Typer cmd with enforce)
     mcp: list_mcp_tools_sync(url) via sse_client -> ClientSession.list_tools()
  -> output.py valid JSON + audit.py log
  -> Ava: llm.py get_ollama_base() + ollama_chat(model=qwen3:32b, json_mode) -> route picker
```

## Key Components

**Security**:
- `core/security.py` Vault: 0600 file at `~/.local/share/bigbang/secrets.json`, keyring optional, env fallback.
- `core/policy.py` `check_permission()` + `enforce_or_raise()` — red error Exit 1, default deny.
- `core/audit.py` `~/.local/share/bigbang/audit.jsonl`
- `core/http_utils.py` NEW — NO_PROXY sanitization, fix Hatch egress proxy `hatch-egress-proxy:3128`.

**Registry / Discovery**:
- `core/registry.py` `~/.local/share/bigbang/registry.json` {tools: {name: {type, url, description, capabilities}}}
- `core/openapi.py` NEW — `fetch_spec()`, `parse_operations()`, `_resolve_base_url()` handles servers[] + Swagger 2.0 host/basePath, `call_openapi()`, `generate_typer_plugin()`.
- `core/mcp_client.py` NEW — `list_mcp_tools()`, `call_mcp_tool()`, sync wrappers, `_mcp_http_client_factory()` with sanitization, fallback SSE→streamablehttp.
- `core/llm.py` NEW — Ollama router, `OLLAMA_URLS`, `PREFERRED_MODELS`, `_CACHED_BASE` 30s TTL, `_is_resolvable()` thread-safe, `extract_json_from_text()`.

**Plugins** (all have `manifest.yaml` v0.4.0 with capabilities):
- `tools` — `add/list/get/rm/search/call/import-openapi/generate` — generate now real codegen.
- `mcp` — `manifest/serve/add/list/list-tools/call` — list-tools/call real.
- `ava` — `status/train/eval/route` — status shows Ollama bases/models, route uses llm.py with fallback.
- `agent` — `run/bus/teach` — run uses `_ollama_plan()` with heuristic fallback, shows planner string.
- `secrets/auth/system/family/vector/tennis` — existing, unchanged but version bumped.

**Generated Plugin Shape** (`bigbang/plugins/<name>/cli.py`):
```python
# Solo personal project, no connection to employer, built with public/free-tier only
import typer, httpx
from bigbang.core.output import emit
from bigbang.core.policy import enforce_or_raise
from bigbang.core.http_utils import sanitize_no_proxy_env
sanitize_no_proxy_env()
app = Typer(name="<name>")
SPEC_SERVERS = [...]
SPEC_HOST = "petstore.swagger.io"
SPEC_BASE = "/v2"
FALLBACK_URL = "https://..."
TOOL_MANIFEST = {"name": "<name>", "capabilities": {"network": {"enabled": True, "domains": ["petstore.swagger.io"]}}}
def _get_base_url(): # handles host + basePath
@app.command("operationId") def op(param: Optional[str] = Typer(...)): 
  enforce_or_raise(TOOL_MANIFEST, "network", url)
  sanitize_no_proxy_env()
  httpx.request(...)
```

## Manifest Spec v0.4
```yaml
name: mytool
version: 0.4.0
description: What it does
capabilities:
  network:
    enabled: true
    domains: [api.example.com, petstore.swagger.io]
  filesystem:
    write: false
    paths: ["~/workspace/mytool/"]
  secrets:
    allow: [MYTOOL_API_KEY]
```

## Security Checklist v0.4
- [x] Vault permissions 0600 verified via `bb system doctor`
- [x] Policy caps in every manifest.yaml
- [x] `enforce_or_raise` before any network call in `tools call`, `tools import-openapi`, `mcp add/list-tools/call`, `openapi.call_openapi`, generated plugin commands
- [x] Audit logging hook in `output.py`
- [x] NO_PROXY sanitization prevents proxy bypass / SSRF via malformed env (IPv6 brackets)
- [x] No finance, local-first, public/free-tier only, disclaimer footer on generated files

## Growth v0.4
- `bb tools add api --type openapi --url <spec>` → `bb tools generate api` → `bb api --help` → per-op commands with policy.
- `bb mcp add myserver https://mcp.example.com/sse` → `bb mcp list-tools myserver` → real SDK.
- `bb ava status` → Ollama detection, models, best_model qwen3:32b.
- `bb ava route "list my GitHub PRs"` → JSON {tool, command, confidence}.
- `bb agent run "summarize petstore available pets"` → plan ["bb petstore findPetsByStatus ..."]

## Next: v0.5 Ideas
- Docker/pipx isolation adapter, real `bb mcp serve` SSE server exposing bb_* tools
- Vector hoops/pitch/gridiron MTNN auto-run via Ava
- OAuth device flow in `auth` plugin
- Skill promotion via Frontier rubric gate

# Solo personal project, no connection to employer, built with public/free-tier only
