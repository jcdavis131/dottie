# Security Model — LLM Wiki

**Solo personal project, no connection to employer, built with public/free-tier only**

## Principles
1. **Default deny**: Every plugin manifest declares `network.enabled`, `domains`, `filesystem.write/paths`, `secrets.allow`. If not declared → denied via `policy.py enforce_or_raise()`.
2. **Vault 0600**: `~/.local/share/bigbang/secrets.json` chmod 600, optional keyring, fallback `BB_SECRET_<KEY>` env. Never logged — `audit.py` strips `secret/key/token`.
3. **Audit everything**: `core/output.py emit()` logs to `audit.jsonl` with timestamp, command, no secrets.
4. **No finance**: BigBang strictly agents/tools/services, finance stripped in v0.2.0.
5. **Local-first, free-tier only**: No cloud deps unless user opts in (Ollama local, public pip, R2/Workers/Supabase free-tier for Passive Lab).
6. **Proxy hardened**: Hatch `NO_PROXY=...,[::1],fd8b:...` broke `httpx` (`Invalid port ':1]'`). Fix `sanitize_no_proxy_env()` strips `[]` and IPv6 CIDR `::` entries.

## Manifest Capability Examples
```yaml
# tools plugin — allows specific domains (netloc, not full URL)
capabilities:
  network:
    enabled: true
    domains: [petstore.swagger.io, api.github.com]

# tasks plugin — no network, fs write only llm-wiki
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
```

## Enforcement Points
- `tools add` → domain extraction `urlparse(netloc)` not full URL → prevents `petstore.swagger.io/v2/swagger.json` vs `petstore.swagger.io` mismatch (bug fixed in v0.4)
- `tools call`, `generate`, `mcp call/list-tools`, generated plugin per-op command, `openapi.call_openapi()` → all call `enforce_or_raise(manifest, "network", url)` before `httpx.request()`
- `tasks` plugin → `network.enabled=false` → any accidental direct httpx to tasks API would be denied; instead uses `hatch_gws_cli` subprocess which manages OAuth externally (Hatch AC-managed)

## Secret Handling
- `secrets set KEY value` → vault file 0600, `list` never shows values, `get` shows masked `****` in human mode but full in --json (still audit strips)
- `tasks` uses no secret — relies on `hatch_gws_cli tasks status` which stores OAuth token in Hatch secure storage, not in repo or vault.

## Google Tasks Wiring Security
- `hatch_gws_cli tasks status` returns `{"ok":true,"status":"connected","connect_url":...,"disconnect_url":...}` — we never log full URLs in audit? Actually we emit connection object which includes URLs, but audit strips token-like substrings? Should manually redact connect_url in future (todo: add redaction).
- `tasks` commands use params `{"tasklist": "@default"}` — safe, no PII except task titles which user controls.
- `sync-bb` reads audit.jsonl (local) and creates tasks — titles include command names, not secrets.

## Threat Model
- **Proxy injection**: Fixed by sanitize_no_proxy_env stripping `[]` and `::`.
- **SSRF via allowlist bypass**: Fixed by storing domain as netloc not full spec URL.
- **Secret leak via --json**: emit masks secrets in output.py, audit also filters.
- **Over-privileged plugin**: Mitigated by scaffold `--with-manifest` default deny, and `system policy` shows all caps.
- **Graphify ingestion leak**: `docs/llm-wiki/tasks-*.json` export may contain task titles (Lina's Morning tasks). Those are personal but not secrets — stored locally, not committed? Recommend .gitignore llm-wiki/tasks-*.json but include sample. Current implementation writes them but not auto-committed.

## Audit: Verify Yourself
```bash
bb system doctor --json  # vault 0600, audit log exists
bb system policy --json | jq .policies.tasks.capabilities
bb system audit --json | tail -n 20
ls -l ~/.local/share/bigbang/secrets.json  # should be 0600
cat bigbang/plugins/tasks/manifest.yaml
```

# Solo personal project, no connection to employer, built with public/free-tier only
