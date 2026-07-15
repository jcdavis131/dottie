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
3. **Vault** — layered: OS keyring (if available) → `~/.local/share/bigbang/secrets.json` 0600 → env `BB_SECRET_<KEY>`
4. **Audit** — every bb invocation → `~/.local/share/bigbang/audit.jsonl` with ts, command, safe args (no secret values), duration
5. **Policy enforcement** — `bigbang/core/policy.py:check_permission()` called before network/fs/secret access in tool adapters (stub now, enforced in v0.4)
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
