# Scout Integration STAT — v0.6.0

## Repos
- **scout-cli**: https://github.com/jcdavis131/scout-cli — primary control plane, cmd `scout`
- **scout-rtx**: https://github.com/jcdavis131/scout-rtx — Alienware RTX offload fork
- **dottie**: https://github.com/jcdavis131/dottie — monorepo home: `apps/scout-cli`, `apps/scout-rtx`, `apps/ava-factory`, `packages/personal-graphify` (standalone clones above keep working; set `DOTTIE_ROOT` to prefer the monorepo)

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
In the dottie monorepo it lives at `packages/personal-graphify` (`uv tool install -e <dottie>/packages/personal-graphify`); the graphify plugin probes `DOTTIE_ROOT`/`~/workspace/dottie` automatically.

```bash
scout graphify status
scout graphify query "how does Scout connect to Ava?"
scout graphify ecosystem          # rebuild multi-root personal brain
scout graphify sync               # copy scout graph → personal-graphify/references/spaces/
```

Docs: `docs/llm-wiki/graphify-integration.md`. Ava routes graphify keywords to this plugin.
