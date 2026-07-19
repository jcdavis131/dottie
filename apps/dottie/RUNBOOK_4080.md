# RUNBOOK — the real climb on your 4080 box

This is the exact sequence to run Dottie's measured hill-climb on your own machine
(the box with the RTX 4080, Docker Desktop, and the finished mini training run),
with Ollama as the working brain and your fresh mini checkpoint as the trainee.

> Solo personal project, no connection to employer, built with public/free-tier only.

## Honest expectations before you start

| backend | what a climb iteration will measure |
|---|---|
| `ollama` | Real task capability of your local model (e.g. `qwen3:32b`). Verified-task success rates here are the first REAL capability numbers in the ecosystem. |
| `ava`    | Your homegrown checkpoint. A smoke/mini-scale checkpoint has **zero task capability** — expect `success_rate 0.0`. That number is the honest baseline the flywheel exists to move. |
| `echo`   | Deterministic plumbing (`plumbing_only`), never a capability measurement. |

Nothing in this runbook fabricates a number: every score comes from the deterministic
verifiers in `dottie/tasks.py` run against what the model actually did.

## 0. One-time setup

```bash
# On your box (WSL2/git bash as appropriate)
cd ~/workspace
git clone https://github.com/jcdavis131/dottie.git   # or: cd dottie && git pull
cd dottie

# Python deps for the dottie app (torch only needed for the ava backend + train-step)
pip install fastapi uvicorn httpx pydantic
pip install torch --index-url https://download.pytorch.org/whl/cu128   # 4080 CUDA build

# Ollama brain
ollama serve &          # if not already running
ollama pull qwen3:32b   # or the model you prefer; set DOTTIE_OLLAMA_MODEL to match
```

## 1. Point the trainee at your fresh mini checkpoint

Your mini run finished inside the `ava-agi` Docker stack, which builds from
`~/workspace/ava-agi-factory-v6-4`. Find the final checkpoint it wrote (the path
depends on the run config — look under `runs/`):

```bash
ls -lt ~/workspace/ava-agi-factory-v6-4/runs/*/          # newest run dir first
cat  ~/workspace/ava-agi-factory-v6-4/runs/<run>/MANIFEST.json   # confirms what it is
```

Then export, adjusting to the real file you found:

```bash
export AVA_FACTORY_ROOT=~/workspace/ava-agi-factory-v6-4
export DOTTIE_AVA_CKPT=~/workspace/ava-agi-factory-v6-4/runs/<run>/<final>.pt
```

If you skip this, dottie falls back to probing `runs/cpu_pilot/agentic/agentic_final.pt`
across factory roots (the CPU-pilot smoke checkpoint), and refuses honestly if none exists.

## 2. Serve dottie (optional but recommended)

```bash
cd ~/workspace/dottie
docker compose -f apps/dottie/docker-compose.dottie.yml up --build -d
curl -s http://localhost:8100/status | python -m json.tool   # real probes: ollama up? ckpt found?
```

The Docker image ships without torch; for the ava backend / train-step inside the
container, `pip install torch` in the container and mount your checkpoint tree — or just
run the climb from the host CLI (below), which uses your host Python and env vars.

With the server up, open **https://arxiviq.vercel.app → Dottie tab → Connect** (default
`http://localhost:8100`). The tab talks to YOUR server from your browser; the API's CORS
allow-list already includes `arxiviq.vercel.app` and `arxiviq.com` (override with
`DOTTIE_CORS_ORIGINS`). Note: `arxiviq.com` itself currently serves your separate
Next.js Dottie control-plane site — the MLOps console with this tab lives on the
`arxiviq.vercel.app` alias until you decide where the domain should point.

## 3. The climb — measured, gated iterations

Run from `apps/dottie` (host CLI):

```bash
cd ~/workspace/dottie/apps/dottie

# (a) Capability baseline with the working brain — the first REAL success rates
python -m dottie climb --families mixed --n 20 --backend ollama --seed-base 0

# (b) Trainee baseline — expect 0.0, recorded honestly with the ckpt's sha256 identity
python -m dottie climb --families mixed --n 20 --backend ava --seed-base 0

# (c) Spin the full flywheel behind an iteration: RFT export + memory mint always run;
#     add the real harness gate and one real GRPO train step:
python -m dottie climb --families mixed --n 20 --backend ava --seed-base 0 \
    --evaluate real --train-step

# (d) After a train step produced a new checkpoint, update DOTTIE_AVA_CKPT and re-run (b)
#     with the SAME --seed-base and --n. The paired gate needs identical task sets.

# Read the ledger: per-iteration scoreboards + paired promote/hold/insufficient verdicts
python -m dottie climb-report
```

The promotion gate is the factory's rank-invariance discipline: `promote` only when the
overall success rate improves AND no task family regresses beyond tolerance. Same-seed
pairs only — unpaired iterations yield an honest `insufficient`, never a verdict.

For an efficiency-gain trend across compute scales, label iterations with real compute
points (`--compute <flops-or-steps>`); with two or more distinct labeled points,
`climb-report` runs the factory's `eg_trend` gate over them.

## 4. What "hill-climb" means from here

1. `ollama` iterations give you a capability ceiling to aim at and generate real traces.
2. Traces feed the flywheel (RFT export, memory mint) automatically each iteration.
3. `--train-step` takes one real GRPO step on the trainee; bigger training happens in
   your `ava-agi` Docker stack, which produces new checkpoints.
4. Each new checkpoint gets a same-seed `ava` iteration; the paired gate decides
   promote/hold. The climb log (`data/climb/climb_log.jsonl`) is the permanent record —
   config, git SHA, checkpoint sha256, every measured number.

## Troubleshooting

- **Ollama unreachable from the container**: the compose file maps
  `host.docker.internal` → host gateway; on the host CLI use
  `DOTTIE_OLLAMA_URL=http://localhost:11434`.
- **arxiviq tab can't connect**: server not running, or the browser blocks
  localhost-from-HTTPS (Chrome/Edge/Firefox allow it; Safari may not), or a
  non-default origin needs adding to `DOTTIE_CORS_ORIGINS`.
- **`policy_unavailable: ... checkpoint`**: `DOTTIE_AVA_CKPT` doesn't point at a real
  file — the refusal message includes the paths that were probed.
- **`train-step` refuses**: it needs the factory checkpoint tree (`base_final.pt`
  marker) reachable via `AVA_FACTORY_ROOT`; the refusal states what's missing.
