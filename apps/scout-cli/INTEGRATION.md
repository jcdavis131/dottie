# Scout Integration STAT — v0.6.0

## Repos
- **Dottie** (the platform): https://github.com/jcdavis131/dottie. This monorepo holds scout, the router, System One, the dottie-os curation mirror and the sites.
- **scout** (Dottie's CLI, command `scout`): https://github.com/jcdavis131/dottie/tree/main/apps/scout-cli. The standalone `jcdavis131/scout-cli` repo is superseded.
- **scout-rtx**: `apps/scout-rtx` in the monorepo (Alienware RTX offload); https://github.com/jcdavis131/scout-rtx is the standalone copy.

## Integration
1. scout-cli includes `rtx` plugin (bigbang/plugins/rtx/) — status/queue/results/programs/dashboard/sync
2. scout-rtx includes bigbang-bridge/ manifest that tells scout how to talk to it
3. Flow: `scout rtx queue add` → queue.json (git or Tailscale) → Alienware run-autonomous → results.jsonl → `scout rtx results --best`

## Install everywhere
```bash
uv tool install "git+https://github.com/jcdavis131/dottie#subdirectory=apps/scout-cli"
scout --help
scout rtx status
```
Working from a checkout: `uv sync --all-groups` at the repo root, then `uv run scout ...`.

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
