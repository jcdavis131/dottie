# Dottie

![CI](https://github.com/jcdavis131/dottie/actions/workflows/ci.yml/badge.svg)
![Python 3.11](https://img.shields.io/badge/python-3.11-blue)
![uv](https://img.shields.io/badge/uv-workspace-black)
![License MIT](https://img.shields.io/badge/license-MIT-green)
![Solo Project](https://img.shields.io/badge/solo-personal%20project%20%E2%80%94%20no%20employer%20tie-lightgrey)

Dottie is a closed-loop LLM factory run as one monorepo: data pipeline → train → eval gate → serve → agent → traces → retrain. The agent's only tool is `scout`, a CLI it can extend at runtime when a task needs a new capability.

> Solo personal project, no connection to employer, built with public/free-tier only (R2/Workers/Supabase/HF ZeroGPU, ONNX WASM, public pip).

**The Dottie site** (`apps/bluehenre`, live at https://www.bhenre.com) is the
operator's window into and steering wheel for this loop — one product with three
faces: a **Guide** (Manus/OpenClaw/Hermes-style agentic assistant), a **Hub**
(HuggingFace-style datasets/models/research registry), and a **Monitor**
(Weights&Biases-style real-time view of the local development the org runs) —
differentiated by provenance-honesty by construction. See
`apps/bluehenre/SPEC.md`.

## Monorepo layout

| Path | Was | What it is |
|---|---|---|
| `apps/ava-factory` | ava-agi-factory-v6-4 | Model factory: data pipeline, trainer, FastAPI serve engine, CPU-pilot chain, research engine |
| `apps/scout-cli` | scout-cli | The `scout` CLI (ex-BigBang) — 20+ capability-declared plugins plus the forge engine |
| `apps/scout-rtx` | scout-rtx | Windows RTX hill-climb runner (torch cu128 hard-pin; excluded from the uv workspace) |
| `apps/dottie` | — | Agent OS: engine, flywheel, policy guardrails, demand queue, task inbox |
| `apps/bluehenre` | — | The Dottie site: agentic-assistant Guide + provenance-honest artifact Hub + real-time dev Monitor (SPEC.md) |
| `packages/ava-skills` | ava-skills | Skill system (memory-router, memory-mint, code-bench, safety-scanner, …) |
| `packages/ava-open-harness` | ava-open-harness | Eval gate: J-Space tests, 11-category rubric, anti-mock guard |
| `packages/personal-graphify` | personal-graphify | Code knowledge-graph CLI/library (Ollama-first) |

Root `pyproject.toml` is a virtual uv workspace over the light packages; `apps/scout-rtx` and `apps/ava-factory` are deliberately excluded (heavy, pinned deps).

```bash
uv sync                          # install workspace members editable
uv run pytest packages/ava-skills
uv run pytest apps/scout-cli/tests
scout --json forge list
scout --json system doctor
```

## Single-CLI doctrine

The LLM and harness get exactly one tool: `scout`. Every capability is a plugin behind `scout --json ...`, and the agent adds capabilities itself through the forge engine:

```bash
scout --json forge new github --description "GitHub API wrapper" --domains api.github.com --network
scout --json forge cat github            # read the generated cli.py
scout --json forge edit github --code '<implementation>'
scout --json forge test github           # smoke test
scout skill install github --target dottie   # persist as a skill for the next session

# or generate from a spec
scout --json forge from-openapi --name linear --url https://api.linear.app/openapi.json
scout --json forge from-mcp --name notion --url https://mcp.notion.com/sse
```

Every plugin declares capabilities (`network` / `filesystem` / `secrets`, default deny) in a manifest and speaks `--json`. Forge engine: `apps/scout-cli/bigbang/plugins/forge/cli.py` (shipped in `4528f85`; self-evolution loop verified end-to-end: `new demo_tool → hello → test pass → rm`).

## Quickstart

```bash
git clone https://github.com/jcdavis131/dottie.git && cd dottie
export DOTTIE_ROOT=$(pwd)

uv sync
pip install -e apps/scout-cli

scout --help
scout --json ava status

# factory in smoke mode (CPU, nano preset)
cd apps/ava-factory
python scripts/dottie_continuous_loop.py --mode monitor
python scripts/dottie_continuous_loop.py --mode data --tokens 500000
python scripts/dottie_continuous_loop.py --mode train --preset nano
```

Full-scale training runs on a local RTX box; the nano preset (13.8M params) exists so the whole loop is exercisable on CPU.

## Training

Model presets: nano 13.8M → mini 171M → base1b 1.4B, with a J-Space architecture (four workspaces at different update half-lives: S1 fast, S2 slow, Critic, Planner) and WSD schedule + YaRN context extension. The phase curriculum (P0 logic → P1 math → P2 foundation → P3 reasoning → P4 long-context → P5 anneal) with its token budgets is the design target, not a completed run — actual progress is published to the live console, and training telemetry (`reports/dottie_telemetry.jsonl`, `dottie_live_status.json`) is generated locally and gitignored, never committed.

Data pipeline: streaming manifests (fineweb-edu, proof-pile-2, synthetic logic, openwiki), six-stage curation (clean, dedup, decontamination with 13-gram overlap vs eval sets, tagging), packed with a 98/1/1 split.

## Eval gate

```bash
uv run pytest packages/ava-open-harness -q
```

Checkpoints are only promoted to serving if they pass `ava-open-harness`: J-Space behavioral tests, the 11-category weighted rubric, safety evals, and `test_no_mock.py` — a guard that exists because an earlier version of this project fabricated eval scores, and every number must now come from a live forward pass or fail with a structured error.

## Repo hygiene

- Generated telemetry and status files are gitignored and verified untracked by a CI job (`Verify no telemetry tracked`).
- `reports/` keeps only curated reports; `runs/cpu_pilot/` keeps text evidence (manifest, tokenizer, reports) — checkpoint binaries are regenerable via `scripts/cpu_pilot_e2e.py` and never committed.
- Research experiments under `research-engine/experiments/<arxiv>/` are committed as curated notes; their run logs are not.
- CI (`.github/workflows/ci.yml`): uv sync, ruff, pytest for skills + harness + scout-cli, forge smoke test, quick eval gate, telemetry hygiene check.

## Status

- Done: monorepo cutover (six repos subtree-merged, 2026-07-18), forge self-evolution engine (`4528f85`), telemetry hygiene + CI (2026-07-19).
- In progress: training the mini 171M on local GPU and promoting it through the eval gate to serve as the default brain; wiring `scout ava` as the single wrapper over the continuous-loop modes; closing the flywheel from site traces back into the anneal phase.

## License

MIT — Solo personal project, no connection to employer, built with public/free-tier only. See `LICENSE` and per-package READMEs.
