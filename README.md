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

## Scout v3.3 → Dottie integration (harness + vector v0.8)

Scout Execution Bundle v3.3-OODA-Agentic-MoMA-Graph-Checkpoint is the reference harness we now port into `scout` as two v0.8 plugins so any Hatch harness can call one CLI.

**Single-source entry:** `bundles/cli.sh` (in Scout repo) → `python3 -m bigbang.cli "$@"` with `PYTHONPATH=~/workspace/dottie/apps/scout-cli`. Any agent/harness calls that path:

```bash
bundles/cli.sh --json harness route "compare Stripe vs Lemon Squeezy Aug 2026"
bundles/cli.sh --json vector eval hoops
scout --json harness verify --score 8.2 --prev 8.0
```

**Harness plugin:** `bigbang/plugins/harness/cli.py` v0.8 — MoMA-lite router + graph memory GARNet + checkpoint + recovery + pacing + verification, mapped directly:

- **MoMA-lite** — 5 tiers deterministic cheap / llm medium / deep_research heavy 9K / action_operator medium-verify / agentic_epic checkpointed 13-swarm predicts capability before full LLM cost-performance optimal (router.ultra.js port)
- **GARNet / Graph Memory** — G_workflow current DAG nodes+edges+status live in checkpoint + G_history timeline.jsonl patterns/failure types → pick (role,LLM) per MDP, MoMA profiles caps, moma history graph + workflow graph
- **Checkpoint Manager** — LangGraph-style pause/resume days later pickup exactly, DAG version never mutates in place version++ controlled replan, required fields nodeId/agentId/attempt/latency/tokens/status/errorClass, path `~/.cache/scout/checkpoints/<runId>/checkpoint.json` or `bundles/ultra/runs/<runId>/checkpoint.json`
- **Bounded Recovery Ladder** — FailureTaxonomy5 + SideEffectClasses READ safe / WRITE_IDEMPOTENT 1× / WRITE_DESTRUCTIVE never auto / EXTERNAL_NOTIFY never speculative + ladder retry1→patch→replan→escalate cannot skip
- **Verification Economics** — CriticEconomics budget3 threshold8.0 PASS epic, early-exit delta<0.3 resist marginal, first retry 80% value, EvalHooks6 correctness/reliability/coherence/tool_failures/hallucination/comms_quality, SuggestibilityGuard best vs worst critique [BLOCKER] file: evidence → fix concrete single-resp, PECHamsterWheelGuard memory-is-diff epic semantic vs working 1500 chars immediate write BLOCKED/DONE/PLANNED not metrics-dance (EvalHooks 6)
- **Communication Pacing** — HandoffEnvelope 7 required + ScoutCommsBus sub-swarm, PacingFilter Observe max3 parallel / Orient 180s / concurrency4 / tempo:13 Never:00 timing>speed, relevantAgents cap 5-6 medium, 13 only epic (CrewAI >5-6 noisy needs filtering)
- **Stickiness Guard** — deep-research Stripe vs Lemon Squeezy Aug 2026 must recall Launched = live URL + 3 users + payments/analytics by Aug31 11:59pm CT America/Chicago locked without re-asking + sources min5 graded A/B/C freshness Aug2026 contradiction matrix

Dottie uses these shapes directly: strategist L1 3-lens history-penalized, planner L2 DAG side-effect tags, executor L3 pacing-filtered swarm + OODA inner loop per node, L4 critic+forensic verification-econ.

**Vector plugin:** `bigbang/plugins/vector/cli.py` v0.8 — dumbmodel.com unified MTNN pipeline, six models, four daily games, one joint cross-sport trunk — era-honest, leak-free, provenance-honest:

- **Games** hoops 64-d 18 towers 12966 players Recall@10 0.977 Purity@20 0.6717 composite 0.7937 / pitch 24-d 633 WC 2018/2022 difficulty-band 40-80% solve / gridiron 32-d MAE 4.268 R2 0.39 nflverse / equities 64-d 17 towers 2700 FY 2015-2024 280 tickers sector_purity@10 0.174 text_tower 384-d MiniLM / unified 64-d sport-agnostic Stage1 ablation configs full/no_supcon/no_coral/no_grl/no_vicreg/task_only losses SupCon→G3 CORAL→G3 GRL→G2 VICReg var+cov task w=2.0 anchor G1
- **Shared lib** `vector/shared/towers.py` ResidualTower cat([x·m,m])→96h→24d skip + L2-norm + TransformerFusion 4-layer d_model128 4 heads CLS→64-d, `losses.py` InfoNCE SupCon CORAL GRL GradReverse λ0.3 VICReg, `normalize.py` per-season z-score era-honest / per-90 tournament-z / per-ticker FY median-impute + z-score + per90
- **Pipeline** `build_features.py → build_vectors.py → train_mtnn.py → gated test_skills.py → regen_assets.py` artifacts vectors.json mtnn_meta.json skills.json eval_scoreboard.json mtnn.onnx, provenance public data only, leak-free player-split not season-split, season-split Recall 1.0 mem bug fixed
- **House rule** unified Stage1 v0 frozen encoders non-destructive Δ G1 per-sport recall / G2 sport invariance / G3 silhouette archetype coherence / G4 hit-rate random baseline does each alignment loss earn keep

Install: `pip install --break-system-packages --no-deps -e ~/workspace/dottie/apps/scout-cli` then `scout --json harness route "…"` / `scout --json vector eval hoops` work anywhere. Manifest documents commands in `bundles/manifest.json:scout_cli_v0_8`.

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

- Done: monorepo cutover (six repos subtree-merged, 2026-07-18), forge self-evolution engine (`4528f85`), telemetry hygiene + CI (2026-07-19), scout-cli v0.8 harness+vector plugins live (single-source `bundles/cli.sh` → `python3 -m bigbang.cli`), checkpoint dual-write Dottie Hub ↔ dumbmodel Hub provenance-honest, nano smoke 100 steps deterministic + monitor Training mode fix.
- In progress: hill-climb per proactive ultracode dynamic workflows across all repos (vector-* domain SOTA + unified + Dottie small locally-runnable reasoning base).

### Hill-Climb Roadmap (2026-08-04 audit — global priorities)

1. **Hoops v6 transformer fusion** — ResidualTower cat([x·m,m]) →96h→24d L2 + TransformerFusion 128d 4-head CLS→64d; probe Recall@10 0.438→0.55 leak-free player-split, era-honest per-season z-score, ensure composite 0.7937 holds.
2. **Gridiron bring training back in-repo** — re-pin nflverse pipeline inside `dottie/apps/scout-cli/bigbang/plugins/vector/` (currently external pull), MAE 4.268 R²0.39 Vegas line feature, 32-d advertised 64-d typical — unlocks end-to-end hill-climb without external notebook.
3. **Dottie train first real nano ckpt 1000 steps** — smoke 100 steps already shipped deterministic (`reports/dottie_nano_step100.pt` + `metrics_nano.jsonl` + telemetry), next: Alienware RTX 4080/4090 `./scripts/local_train.sh --preset nano --steps 1000` full weights, MoMA-lite cheap heartbeat→monitor parity, J-space S1/S2/Critic/Planner verbalizable_mass.
4. **Unified push G2 0.6851→0.64 sport-blind** — sport classifier + GRL λ0.3 warmup10ep after 5ep, SupCon→G3 CORAL→G3 VICReg var+cov task w=2.0 ablation table 5 configs full/no_supcon/no_coral/no_grl/no_vicreg/task_only — measure ΔG2/G3/G4, house rule each loss must earn keep.
5. **Pitch promote MTNN to game + telemetry** — difficulty-band 40-80% solve (24-d WC per-90 tournament-z 633 players 2018/2022) → daily puzzle generator in `vector-hub/index.html` Hub (6 models 4 puzzles), wire live telemetry to `reports/dottie_telemetry.jsonl` rolling <5MB.

Run next via single-source wrapper:

```bash
bundles/cli.sh --json harness route "compare Stripe vs Lemon Squeezy Aug 2026"  # deep_research 9K heavy route
bundles/cli.sh --json vector eval hoops   # Recall@10 0.977 Purity@20 0.6717
bundles/cli.sh dottie train --preset nano --steps 100 --force  # smoke deterministic (no torch ok in VM)
python -m bigbang.cli dottie monitor   # should show mode Training steps 100 loss 4.0 not not_running
```

Proactive ultracode dynamic workflows: every repo gets scout-prime→researcher→builder→communicator→operator layered graph, OODA inner-loop per node, MoMA-lite routing, checkpoint per node (required fields nodeId/agentId/attempt/latency/tokens/status/errorClass), recovery ladder retry→patch→replan→escalate, verification econ budget3 threshold8.0 earlyExit Δ<0.3.

## License

MIT — Solo personal project, no connection to employer, built with public/free-tier only. See `LICENSE` and per-package READMEs.
