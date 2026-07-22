# Dottie — Self-Evolving LLM Factory + Agent OS

![CI](https://github.com/jcdavis131/dottie/actions/workflows/ci.yml/badge.svg)
![Python 3.11](https://img.shields.io/badge/python-3.11-blue)
![uv](https://img.shields.io/badge/uv-workspace-black)
![License MIT](https://img.shields.io/badge/license-MIT-green)
![Solo Project](https://img.shields.io/badge/solo-personal%20project%20%E2%80%94%20no%20employer%20tie-lightgrey)

**Train your own LLM to power your own harness + skills ecosystem to build and deploy to a Hermes/OpenClaw-style assistant.**

Dottie is a *closed-loop MLOps factory*: data → train → eval gate → serve → agent → skills → build → deploy → traces → retrain. The agent's only tool is `scout` — a self-evolving CLI it knows how to extend when a task needs a new capability.

> Solo personal project, no connection to employer, built with public/free-tier only (R2/Workers/Supabase/HF ZeroGPU, ONNX WASM, public pip).

**Live Console:** https://arxiviq.com (Control Plane fetches `dottie/main/apps/ava-factory/` with legacy fallback)
**Architecture Map:** [Dottie Architecture Map artifact](https://agent.meta.ai/s/dottie-architecture-map) — 4 mermaid diagrams (flywheel, train→serve, use site, single CLI doctrine)

---

## Why Dottie? MLOps from First Principles

| Principle | How Dottie Implements |
|---|---|
| **Reproducibility** | `uv` workspace, `pyproject.toml` pin-free light packages, `requirements.txt` + Docker for factory, `train.sh` deterministic, `DOTTIE_ROOT` env |
| **Data Versioning** | Streaming manifests `fineweb-edu score>=2`, `proof-pile-2`, synthetic Phi Method B logic, `openwiki` + personal brain; curator x6 `clean·dedup·decon·tag concept+task_type`, packed `P0-P5` 98/1/1 split, 13-gram decontam vs eval |
| **Training** | WSD warmup 2k stable 736k 92% decay 2e-5, YaRN 10k→1M, J-Space 4 workspaces S1 Fast 32 hl8 + S2 Slow 64 hl300 + Critic 16 hl30 + Planner 32 hl150, losses: reportability + broadcast 20% + selectivity + MI cos 0.45 + router KL; presets nano 13.8M (50M toks 10min) → mini 171M (2.5B 3-5d) → base1b 1.4B (100M/day) |
| **Eval Gate** | `ava-open-harness` — J-Space tests, frontier rubric 11 cats (Financial Accuracy, Process Transparency, Risk/Ethical, Coverage, Attribution, Numerical Accuracy, Logical Coherence, Citation Grounding, Instruction Following, Edge Case, Client-Ready Polish), safety blackmail, spider-ant, france-china, soccer-rugby, `test_no_mock.py` anti-mock guard. Only passing ckpt promoted |
| **Serving** | `apps/ava-factory/dottie/serve_engine.py` FastAPI hot-reload `/generate /jspace/inspect /tools`, QK-Norm, streaming, tool calling |
| **Agent OS** | `apps/dottie` — Hermes/OpenClaw style: `engine.py + flywheel.py + policy.py + resolve.py + status.py`, demand queue, task inbox, BENIGN=brain, policy=guardrails |
| **Single CLI Doctrine** | **LLM tool list = [scout]**. All capabilities via `scout --json ...`. Self-evolution via `scout forge new/from-openapi/from-mcp → cat → edit → test → skill install`. See below |
| **Skills = J-Space** | `memory-router` (Router+Arbitration veto), `memory-mint`, `code-bench` exec-verified 3s timeout [0.25,0.45,0.05,0.25], `jspace-inspector`, `eval-harness-runner`, `safety-scanner` Llama Guard 3 ONNX F1 0.939, `logic-prover` Phi B, `openwiki-sync`, `family-brain-wiki` |
| **Build & Deploy** | `scout` scaffolds web artifact + deploys to Vercel/R2/Supabase/HF ZeroGPU free-tier, client-only shareable, 5-min smoke `nano count-params + pytest -q` |
| **Observability** | `reports/dottie_telemetry.jsonl` (gitignored, local) + `dottie_live_status.json` → arxiviq Control Plane, `STATUS.json` transient, `logs/cron-*`, `ava-skills` traces, hill-climb dashboard |

---

## 🐾 Single CLI Doctrine — One Tool to Rule Them All

This is the core MLOps trick: **the LLM + harness only have ONE tool: `scout`**.

```bash
scout --json --help                    # discover universe
scout --json forge list                # what tools exist
scout --json tools list                # registry
scout --json ava status                # factory status
scout --json ava train --preset nano
scout --json ava eval --task frontier_rubric,jspace_all
```

**When harness needs a new capability mid-task:**

```bash
# LLM realizes it needs GitHub API
scout --json forge new github --description "GitHub API wrapper" --domains api.github.com --network
scout --json github hello              # verify loads
scout --json forge cat github          # read current cli.py
scout --json forge edit github --code '<full real impl with httpx>'  # LLM implements
scout --json forge test github         # smoke test
scout skill install github --target dottie  # teach Dottie for next session, now ~/.dottie-claw/skills/github/SKILL.md

# Auto from OpenAPI
scout --json forge from-openapi --name linear --url https://api.linear.app/openapi.json
scout --json forge from-mcp --name notion --url https://mcp.notion.com/sse

# Retry original task with new tool
scout --json github run --arg "jcdavis131/dottie"
```

Contract: every plugin uses `make_plugin_app() + ok(data, command, example, discover) + emit() + examples_epilog`, manifest declares `capabilities: network.filesystem.secrets` default deny, `--json` for LLM parsing.

Forge engine: `apps/scout-cli/bigbang/plugins/forge/cli.py` — shipped `4528f85`, self-evolution verified `new demo_tool → hello → test pass → rm`.

---

## Monorepo Layout

| Path | Was | What it is |
|---|---|---|
| `apps/ava-factory` | ava-agi-factory-v6-4 | Model factory: data pipeline, trainer, FastAPI server, CPU-pilot chain, research engine |
| `apps/scout-cli` | scout-cli | `scout` CLI (ex-BigBang) — 20+ plugins, forge engine, arxiviq console |
| `apps/scout-rtx` | scout-rtx | Windows RTX hill-climb runner + bigbang-bridge (torch==2.9.1 cu128 hard-pin, excluded from uv workspace) |
| `packages/ava-skills` | ava-skills | Skill system: 9 skills incl. memory-mint/router, MSFT Agent Framework Skills v1.11.0 compatible |
| `packages/ava-open-harness` | ava-open-harness | Eval gate: J-Space tests, frontier rubric, anti-mock |
| `packages/personal-graphify` | personal-graphify | Code knowledge-graph CLI/library (Ollama-first) |

Root `pyproject.toml` is a virtual uv workspace over the four light packages. `apps/scout-rtx` and `apps/ava-factory` are deliberately excluded.

```bash
uv sync                    # install 4 workspace members editable
uv run pytest packages/ava-skills
uv run pytest apps/scout-cli/tests
scout --json forge list
scout --json system doctor
```

---

## Quickstart — 5 Minutes to Self-Evolving Agent

```bash
git clone https://github.com/jcdavis131/dottie.git && cd dottie
export DOTTIE_ROOT=$(pwd)

# 1. Install base (free-tier, no GPU needed for nano)
uv sync
pip install -e apps/scout-cli

# 2. Single CLI discovery
scout --help
scout --json forge list
scout --json ava status

# 3. Run factory in smoke mode (CPU)
cd apps/ava-factory
python scripts/dottie_continuous_loop.py --mode monitor   # shows stale/data_starved as day0
python scripts/dottie_continuous_loop.py --mode data --tokens 500000  # fast 10M in ~13s md5
python scripts/dottie_continuous_loop.py --mode train --preset nano    # needs Alienware RTX for full, smoke nano quick

# 4. Teach scout a new tool (self-evolution)
scout forge new weather --description "Open-Meteo weather" --domains api.open-meteo.com --network
scout --json weather hello
scout forge edit weather --instructions   # how to implement real logic

# 5. Open control plane
cd ../scout-cli && scout rtx dashboard   # opens arxiviq console
```

---

## Training — Phases P0→P5, YaRN Long Context

- **P0 logic 0-50B** 2k RoPE 10k — Phi Method B textbooks, syllogisms, FOL, Lean valid-by-construction
- **P1 math 50B-350B** 4k — open-web-math, proof-pile-2
- **P2 foundation 350B-6T** 35% edu — fineweb-edu
- **P3 reasoning 6T-11T** 8k→32k RoPE 500k — mixed reasoning
- **P4 long 11T-13.8T** 128k YaRN 1M — long context
- **P5 anneal 13.8T-15T** edu>=4.5 — high-quality annealing + site traces RL reward>0.8

All packed via `dottie/telemetry.py → reports/dottie_telemetry.jsonl → dottie_live_status.json` (gitignored, not committed — check arxiviq for live).

---

## Eval Gate — Anti-Mock, Frontier Rubric

```bash
scout --json ava eval --task jspace_all,frontier_rubric,safety_blackmail
# or directly
uv run pytest packages/ava-open-harness -q
```

Guard: `tests/test_no_mock.py` ensures no hardcoded scores (old Ava blueprint bug sha256 concept→randn). Frontier rubric 11 categories weighted clipped 0-1, judge IRA 80.2% vs human 79.6%.

Only passing checkpoints promoted to serving.

---

## Scout CLI — The Agent OS

20+ plugins, all capability-declared, JSON-friendly:

- `scout ava` — brain, factory, frontier eval, Ollama routing qwen3:32b
- `scout forge` — **self-evolution engine** (new/from-openapi/from-mcp/cat/edit/test/rm)
- `scout tools` — universal registry (openapi/mcp/cli/docker/python)
- `scout skill` — teach Dottie-claw/Claude/Cursor/OpenClaw
- `scout system` — doctor, audit, policy, scaffold
- `scout rtx` — offload to Alienware RTX 4080/4090, GH releases auto-sync hourly
- `scout graphify` — personal brain query/path/task/ecosystem
- `scout write/lab/brain/family/...` — authentic writing, passive lab, memory

See `apps/scout-cli/README.md`.

---

## Telemetry & Cleanup (Top-Tier MLOps Hygiene)

**This repo now follows clean factory hygiene (fixed 2026-07-19):**

- `STATUS.json`, `dottie_live_status.json`, `dottie_telemetry.jsonl`, `ava_telemetry.jsonl`, `bench_pipeline.json`, `last_ecosystem_check.json`, `results.tsv`, `autoresearch_*.json` are **gitignored** — generated every 4h/hourly by crons, not source. Verified via CI job `Verify no telemetry tracked`.
- `reports/` only keeps curated real reports: `REPORT_REAL.md`, `branch_eval_results_real.json`, `safety_eval.json`, etc.
- Research experiments `research-engine/experiments/<arxiv>/experiment.md` ARE committed (curated knowledge), but `run.log` / results tsv are ignored.
- `runs/cpu_pilot/` keeps only text evidence (MANIFEST.json, tokenizer, reports) — binaries `*.pt/*.bin` ignored, regenerable via `scripts/cpu_pilot_e2e.py`.
- CI: `.github/workflows/ci.yml` — uv sync, ruff, pytest skills+harness+scout-cli, forge smoke test, eval gate quick, telemetry hygiene check.

---

## Roadmap

- [x] Monorepo canonical cutover 2026-07-18 (6 repos subtree-merged, crons migrated)
- [x] Forge self-evolution engine 4528f85
- [x] Telemetry hygiene + CI 2026-07-19
- [ ] Wire `scout ava train/eval/data/status/telemetry` wrapper over `dottie_continuous_loop.py` modes (so harness only calls scout)
- [ ] Train mini 171M 2.5B on Alienware, promote to serve as Dottie brain (replace qwen3:32b default)
- [ ] dottie.site Hermes-style chat uses Dottie LLM + forge tools live
- [ ] Close flywheel: site traces → P5 anneal RL

---

## License

MIT — Solo personal project, no connection to employer, built with public/free-tier only.

See `LICENSE` (to be added) and per-package READMEs.
