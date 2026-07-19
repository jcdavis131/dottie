# RUNBOOK — the automated research loop on your 4080 box

This is the exact sequence to run Dottie's 4-worker **automated research loop** on your own
machine (the box with the RTX 4080, Docker Desktop, and Ollama). The loop is a closed cycle —
**ideation → implementation → training → evaluation** — over a SQLite ledger, hill-climbing a
single baseline metric. It never talks to the public internet and never fabricates a number.

> Solo personal project, no connection to employer, built with public/free-tier only.

## What the loop is

Four workers, one ledger (`data/research/ledger.sqlite3`), one baseline to beat:

| worker | command | what it does |
|---|---|---|
| ideation | `ideate` | Drives the Ollama model to ground N hypotheses in the current real baseline + recorded dead ends. Refuses honestly if Ollama is unreachable. |
| implementation | `implement` | Drafts the next pending hypothesis into code and runs the **4-level validator** (`syntax → contract → static → dry_run`). Unsound code never reaches the trainer. |
| training | `train` | Runs the **proxy micro-benchmark** — a real gradient run of the generated module — and records the measured metric. |
| evaluation | `evaluate` | Compares the measured metric to the baseline, direction-aware; promotes to **SOTA** only on a real improvement, else `rejected`. |

Experiment states flow `pending → ready_for_training → evaluation_pending → sota | rejected`, with
`failed_validation` / `failed_training` as honest dead ends. Every score comes from a real
measurement in `train.py` / `evaluate.py` — nothing here is invented.

## Honesty contract (read before you trust a number)

- **Ollama unreachable → honest refusal.** `ideate` and `implement` exit non-zero with a true
  reason (`ollama_unavailable`) rather than emitting a fabricated hypothesis or fabricated code.
- **The 4-level validator is the chokepoint.** A hypothesis that does not pass `syntax`,
  `contract`, `static`, and `dry_run` is marked `failed_validation` and never touches the trainer.
  A level that cannot run (e.g. `ruff` or `torch` absent) is reported as such, never assumed pass.
- **Training is a proxy micro-benchmark, NOT downstream capability.** The default trainer drops the
  validated module into a tiny sequence model and trains it for real, on CPU/GPU, on a deterministic
  copy/shift task where a module that genuinely mixes sequence information *can* lower the loss. This
  is a real, comparable signal — honestly labelled a proxy — mirroring the ecosystem's proxy-first
  discipline (scout-rtx's TinyStories proxy). It is **not** a claim about 1B-scale model capability.
  The trainer is the pluggable `Trainer` callable in `dottie/research/train.py`; the
  factory-integrated GPU trainer is the swap-in for real capability-scale runs when that hook lands.
- **A run that goes NaN/Inf is killed** and recorded as `failed_training` (unstable) — never
  silently kept.
- **SOTA is declared only on a real, direction-aware improvement** over the baseline.

## 0. Prerequisites

```bash
# On your box (WSL2 / git bash as appropriate)
cd ~/workspace
git clone https://github.com/jcdavis131/dottie.git   # or: cd dottie && git pull
cd dottie/apps/dottie

# Python deps (torch needed only for the training worker's proxy micro-benchmark)
pip install fastapi uvicorn httpx pydantic
pip install torch --index-url https://download.pytorch.org/whl/cu128   # 4080 CUDA build

# Ollama is the brain for ideation + implementation
ollama serve &                 # if not already running
ollama pull qwen3:32b          # or your preferred model
export DOTTIE_OLLAMA_URL=http://localhost:11434
export DOTTIE_OLLAMA_MODEL=qwen3:32b
```

## 1. One-time — seed the baseline

The loop hill-climbs against one baseline. Seed it once (lower `proxy_loss` is better, so no
`--higher-is-better` flag):

```bash
python -m dottie.research seed-baseline \
    --value 4.5 --metric proxy_loss --architecture ava-nano \
    --notes "initial proxy baseline for the ava-nano search"
```

Until this runs, the arxiviq Research tab says *"baseline not seeded yet"* — honestly.

## 2. Run each worker manually (one pass)

Run from `apps/dottie`. Each worker prints JSON and updates the ledger + `status.json`:

```bash
python -m dottie.research ideate --n 3 --bottleneck "early pre-training loss spikes and MoE routing collapse"
python -m dottie.research implement                 # drafts + 4-level-validates the next pending hypothesis
python -m dottie.research train --steps 200         # proxy micro-benchmark; real measured metric
python -m dottie.research evaluate                  # hill-climb: promote to SOTA only on a real gain
python -m dottie.research status                    # the snapshot the arxiviq Research tab renders
```

`python -m dottie.research loop --n 3 --steps 200` runs one full ideate→implement→train→evaluate
pass in order (Ollama gaps degrade honestly to `skipped`) — handy for a single local cycle.

## 2.5 The REAL factory trainer (`--trainer factory`)

The proxy micro-benchmark is the default. The **factory trainer** is the real swap-in: it drops
the validated candidate module into the REAL nano `AvaModel1B` (replacing one fusion-layer
block — the same slot the factory's `deltanet_layers` mechanism swaps), trains the whole model
from scratch on the REAL packed pilot corpus, and measures **held-out LM cross-entropy**
(`factory_lm_loss`, lower is better). Still nano-smoke scale — `capability_claim: none` — but a
real, comparable, capability-relevant metric on real data.

```bash
# One-time per config: measure the UNMODIFIED model under the identical training recipe and
# seed the baseline from that real number (never hand-type a factory baseline):
python -m dottie.research calibrate-baseline --steps 150 --overwrite

# Then train experiments against it:
python -m dottie.research train --steps 150 --trainer factory
python -m dottie.research loop --n 3 --steps 150 --trainer factory
```

Prerequisites: torch (CUDA build for the GPU), the factory checkout on `AVA_FACTORY_ROOT`, and
a packed pilot corpus (run `scripts/cpu_pilot_e2e.py --device cuda` in the factory once — it
probes `runs/cpu_pilot_4080/packed` then `runs/cpu_pilot/packed`). Missing pieces are honest
`ok=False` refusals; a candidate that cannot integrate at the model width or goes NaN is a real
`failed_training` outcome.

## 3. Install the continuous cron loop

For a self-running flywheel, install the four workers on cron:

```bash
# Edit DOTTIE_ROOT (and Ollama env, if not on defaults) at the top of the file first:
$EDITOR apps/dottie/research_orchestration/crontab

crontab apps/dottie/research_orchestration/crontab
```

Cadence (mirrors the closed loop): **ideation daily at midnight** (establishes the frontier),
**implement / train / evaluate hourly** at minutes 15 / 30 / 45 so each stage feeds the next.

**Windows box (no cron):** the same cadence via Task Scheduler —

```powershell
# machine-local env first (Ollama model actually pulled, factory root):
Copy-Item research_orchestration\research_env.local.ps1.example `
          research_orchestration\research_env.local.ps1   # then edit it
powershell -ExecutionPolicy Bypass -File research_orchestration\install_tasks.ps1
```

`research_worker.ps1` holds an exclusive per-worker lock file — a tick that finds the previous
run still going is a silent no-op, exactly the flock -n behaviour. `install_tasks.ps1
-Uninstall` removes all four tasks. Slow local models: set `DOTTIE_OLLAMA_READ_TIMEOUT_S`
(default 300) in the local env file — a timeout still refuses honestly.

**Single-instance via flock.** Each tick runs through `research_worker.sh`, which takes
`flock -n` on a per-worker lock. If a long (e.g. 14-hour) training run is still going, the next
hourly training tick is a silent no-op instead of stacking a second run on the GPU. Nothing races.

## 4. Where the artifacts live

Everything is under `apps/dottie/data/research/`:

| path | what it is |
|---|---|
| `ledger.sqlite3` | the permanent experiment ledger (states, metrics, deltas, verdicts) |
| `workspaces/` | one dir per experiment — the generated + validated candidate module |
| `metrics.jsonl` | append-only real measurements from the training worker |
| `status.json` | the snapshot mirror served at `/research/status` and rendered by arxiviq |
| `logs/*.log` | per-worker stdout/stderr from the cron wrapper (`ideate.log`, `train.log`, …) |

## 5. Watch progress

- `python -m dottie.research status` — baseline, state counts, recent experiments, SOTA history.
- **arxiviq → Research tab** — connect to your local Dottie server (`:8100`, same endpoint as the
  Dottie tab) and it renders `/research/status` live: baseline tiles, the SOTA hill-climb history,
  and the experiment ledger. Serve it with
  `docker compose -f apps/dottie/docker-compose.dottie.yml up --build -d`.
- `tail -f apps/dottie/data/research/logs/*.log` — the raw worker output, including honest refusals.

## Troubleshooting

- **`ollama_unavailable` from ideate/implement**: Ollama isn't serving or `DOTTIE_OLLAMA_URL` /
  `DOTTIE_OLLAMA_MODEL` are wrong — the refusal states which. This is the honest path, not a bug.
- **Everything sits in `pending`**: `implement` hasn't run (or keeps hitting `failed_validation`);
  check `logs/implement.log` for the failing validator level.
- **`train` says "no experiments ready for training"**: nothing has passed validation yet — run
  `implement` first.
- **A cron training tick seemed to skip**: expected — flock skipped it because the previous run (or
  the GPU) was still busy. Check `logs/train.log` for the in-flight run.
- **Research tab shows "unreachable"**: the Dottie server isn't running on `:8100`, or the browser
  blocks localhost-from-HTTPS (Chrome/Edge/Firefox allow it; Safari may not), or a non-default
  origin needs adding to `DOTTIE_CORS_ORIGINS`. See `RUNBOOK_4080.md`.
