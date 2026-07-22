# AGENTS — Dottie cloud/dev bootstrap

Solo personal project. Prefer live evidence over assumptions.

## Environment (required)

```bash
export DOTTIE_ROOT=/agent/repos/dottie   # or your checkout root
export AVA_FACTORY_ROOT="$DOTTIE_ROOT/apps/ava-factory"
export PATH="$HOME/.local/bin:$PATH"     # uv + scout tools
```

On Cursor Cloud / fresh Linux boxes:

```bash
bash scripts/dev-env-setup.sh
source ~/.bashrc
```

Durable config: `.cursor/environment.json` runs that script as `install`.

## Verify (cheapest → richest)

```bash
make forge          # scout forge list
make doctor         # scout system doctor
make lint           # ruff on light packages
make test           # pytest skills + harness + scout-cli
```

Factory GPU train / Docker fleet / Ollama are **optional** here. Missing docker/ollama is not a failed bootstrap.

## Layout pointers

| Path | Role |
|---|---|
| `apps/scout-cli` | `scout` CLI (Single CLI Doctrine) |
| `apps/ava-factory` | trainer/serve; needs `AVA_FACTORY_ROOT` |
| `apps/dottie` | research loop / agent OS |
| `packages/*` | skills, harness, personal-graphify |
| `SPEC.md` / `HANDOFF.md` / `TODOS.md` | product truth + ops |

Sibling checkout (multi-repo env): `/agent/repos/scout-cli`.
