# Security — First Class

## Principles

1. **No secrets in repo** — ever. `bb secrets set` only. `.gitignore` includes `.env`, `secrets.json`.
2. **Default deny** — plugins/tools declare `manifest.yaml` capabilities:
```yaml
capabilities:
  network: {enabled: true, domains: [api.example.com]}
  filesystem: {write: false, paths: []}
  secrets: {allow: [EXAMPLE_TOKEN]}
```
3. **Vault** — file store `~/.local/share/bigbang/secrets.json` (0600) is where `bb secrets set` writes. Reads are layered: OS keyring (read-fallback only, if installed) → env `BB_SECRET_<KEY>` → vault file. There is no keyring write path today.
4. **Audit** — every bb invocation → `~/.local/share/bigbang/audit.jsonl` with ts, command, safe args (no secret values), duration
5. **Policy enforcement** — `bigbang/core/policy.py:check_permission()` — **network** enforcement is wired (mcp/tools/openapi call paths, plus a persisted user-level allowlist at `~/.config/bigbang/policy.yaml`, default-deny); **fs_write** enforcement is wired on tasks export, rft export, and graphify sync write paths; **secret** allowlists are enforced by the engine when manifests declare them
6. **Isolation** — tool types:
   - openapi: httpx with domain allowlist
   - mcp: MCP SDK client, server URL must be allowlisted
   - docker: runs in container, no host fs by default
   - cli: subprocess with restricted env

## Future Hardening (v0.5)

- age encryption for vault file (currently 0600 plaintext)
- sigstore signing for plugins (verify manifest sig on load)
- pipx isolation for python tools
- Tailscale ACL for remote MCP exposure
- OPA/Rego for complex policies
