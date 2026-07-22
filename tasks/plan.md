# Plan — Optimize cloud/dev environment for Dottie + scout-cli

## Goal

Make this machine (and future Cursor Cloud agent boots) ready to develop **dottie** and **scout-cli** with zero manual bootstrap: `uv`, Python 3.11, workspace sync, `scout` on PATH, env vars set, smoke verify.

## Decisions (locked)

1. **Tooling truth** matches CI: `uv` + Python 3.11 + workspace sync (`uv.lock`).
2. **Durable config** lives in-repo as `.cursor/environment.json` + idempotent `scripts/dev-env-setup.sh` (survives new agent VMs).
3. **Multi-repo**: dottie is the primary env; `repositoryDependencies` includes `github.com/jcdavis131/scout-cli`.
4. **Out of scope for this pass**: Docker Desktop/fleet, Ollama models, GPU/torch factory train — those need host-specific or secret-backed setup. Scripts detect and report, not fail hard.
5. **Shell**: append a marked block to `~/.bashrc` for `DOTTIE_ROOT`, `AVA_FACTORY_ROOT`, `uv` PATH.

## Deliverables

| Item | Acceptance |
|---|---|
| `scripts/dev-env-setup.sh` | Idempotent; installs uv + py3.11; `uv sync`; puts `scout` on PATH |
| `.cursor/environment.json` | `install` runs the setup script |
| `AGENTS.md` | Points agents at env vars + verify commands |
| Shell profile | `DOTTIE_ROOT` / `AVA_FACTORY_ROOT` / `~/.local/bin` |
| Verify | `make lint`/`forge`/`doctor` smoke + scout-cli pytest subset green |

## Verify

```bash
./scripts/dev-env-setup.sh
source ~/.bashrc
cd "$DOTTIE_ROOT" && make forge && make doctor
cd /agent/repos/scout-cli && uv run pytest tests/ -q --maxfail=5
```
