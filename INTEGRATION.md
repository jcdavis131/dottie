# Scout Integration STAT — v0.6.0

## Repos
- **scout-cli**: https://github.com/jcdavis131/scout-cli — primary control plane, cmd `scout`
- **scout-rtx**: https://github.com/jcdavis131/scout-rtx — Alienware RTX offload fork

## Integration
1. scout-cli includes `rtx` plugin (bigbang/plugins/rtx/) — status/queue/results/programs/dashboard/sync
2. scout-rtx includes bigbang-bridge/ manifest that tells scout how to talk to it
3. Flow: `scout rtx queue add` → queue.json (git or Tailscale) → Alienware run-autonomous → results.jsonl → `scout rtx results --best`

## Install everywhere
```bash
pip install git+https://github.com/jcdavis131/scout-cli.git
scout --help
scout rtx status
```

On Alienware:
```powershell
git clone https://github.com/jcdavis131/scout-rtx.git
.\scripts\setup-win.ps1 -Program programs\program-ava.md
```

## Dashboard
Web artifact `rtx-offload-dashboard` also available locally in ts-spaces/, integrated via `scout rtx dashboard`

## Personal Graphify (baked in)
Requires `pgraphify` from private `~/personal-graphify` (`uv tool install -e ~/personal-graphify`).

```bash
scout graphify status
scout graphify query "how does Scout connect to Ava?"
scout graphify ecosystem          # rebuild multi-root personal brain
scout graphify sync               # copy scout graph → personal-graphify/references/spaces/
```

Docs: `docs/llm-wiki/graphify-integration.md`. Ava routes graphify keywords to this plugin.
