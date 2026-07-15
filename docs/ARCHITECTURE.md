# Architecture v0.3 — Sovereign Control Plane

## Vision
BigBang is *the* universal router: one CLI to rule all internet tools (OpenAPI, MCP, CLI, Docker, Python) with security-first, agent-native, Ava-brained.

## Core Flow
```
User/Agent -> bb <plugin> <cmd> --json (Typer) 
  -> policy.py check (manifest.yaml caps) 
  -> security.py vault (keyring/0600/env) 
  -> registry.py lookup (tool manifest) 
  -> discovery adapter (openapi/mcp/docker) 
  -> execution with audit.py logging -> output.py valid JSON
```

## Key Components (v0.3)

**Security**:
- `core/security.py` Vault: set/get/list with 0600 file, keyring optional, env fallback. Future: age encryption
- `core/policy.py` Capability engine: reads manifest.yaml per plugin/tool, default deny, checks network domains, fs write, secret allowlist
- `core/audit.py` JSONL audit: ~/.local/share/bigbang/audit.jsonl

**Registry**:
- `core/registry.py` Universal store: ~/.local/share/bigbang/registry.json v0.3.0 {tools: {name: {type, url, description, tags, capabilities}}}
- `core/discovery.py` fetch OpenAPI, discover MCP tools (stub, real SDK in v0.4)

**Plugins**:
- secrets, auth, tools (universal), mcp (client+server), agent (planner), system (doctor/audit/policy/scaffold), ava (brain)

**MCP Dual Role**:
- Client: `bb mcp add <name> <url>` + `bb mcp list-tools <name>` + `bb mcp call`
- Server: `bb mcp serve --transport sse --port 8787` exposes every bb_* as MCP tool (manifest built from plugin_loader + registry)

**Ava Role**:
- Router for `bb agent run` and `bb ava route` (currently stub, will call Ollama qwen3:32b)
- Judge for skill promotion via Frontier rubric (future)
- Trainer: `bb ava train` -> docker compose CUDA

## Manifest Spec
```yaml
name: mytool
version: 0.3.0
description: What it does
capabilities:
  network:
    enabled: true
    domains: [api.example.com]
  filesystem:
    write: false
    paths: ["~/workspace/mytool/"]
  secrets:
    allow: [MYTOOL_TOKEN]
```

## Growth
- `bb system scaffold` → new plugin folder + manifest.yaml → auto-discovered, auto-MCP tool
- `bb tools add` → registers external tool in registry.json → searchable via `bb tools search`
- `bb agent bus` → watches audit log for recurring patterns (3x same command) → proposes scaffold

## Next: v0.4
- Real MCP SDK Python client
- OpenAPI → Typer codegen: generate commands from spec paths
- OAuth device flow
- Policy enforcement in adapters (currently check stub)
- Docker/pipx isolation
