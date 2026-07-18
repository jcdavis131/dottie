# Hermes (codename "openclaw")

The agentic-assistant platform for the dottie monorepo: run tasks as a CodeAct agent,
capture every trace, and close the continuous-improvement loop — **train, eval, iterate,
evolve** — over the machinery that already exists and is tested in this repo.

> Solo personal project, no connection to employer, built with public/free-tier only.

## Honest capability statement (read first)

- **Ollama is the working brain today.** The only backend that can actually do useful tasks
  is `ollama` — a real local model (default `qwen3:32b`) served by Ollama on your box.
- **Ava is the trainee, not the assistant.** The `ava` backend decodes from the factory's
  real smoke-scale checkpoint (~14M-param nano preset, ~90 base + ~25 agentic-branch
  optimizer steps). It has **zero task capability** and emits noise turns — honestly. It
  exists so the training flywheel has a real model to improve, and so the serving path is
  already built for the day a capable checkpoint exists.
- **Echo is plumbing.** The `echo` backend is a deterministic CI harness
  (`plumbing_only=True`), never a capability measurement.
- **Anti-fabrication everywhere.** Unreachable Ollama, missing checkpoint, missing torch,
  no traces yet: Hermes refuses with the true reason (HTTP 503 / `HermesPolicyUnavailable`).
  Every metric in every response is computed from real inputs; `r_task` for open-ended tasks
  is `null` because no automatic verifier exists — it is never invented.

## Architecture

```
                 ┌────────────────────────── Hermes (apps/hermes) ─────────────────────────┐
                 │                                                                         │
  POST /tasks ──▶│  FastAPI api.py ──▶ thread pool ──▶ HermesEngine (engine.py)            │
  GET  /tasks/id │      │ SQLite task state                 │                              │
  GET  /status ──▶ real probes (ollama ping, ckpt stat,     │ policy.py                    │
                 │  sibling resolution, trace counts)       ▼                              │
                 │                        ┌─ OllamaPolicy (HTTP → your qwen3:32b) ─ brain  │
                 │                        ├─ AvaPolicy    (TorchModelPolicy+ckpt) ─ trainee│
                 │                        └─ EchoPolicy   (deterministic)         ─ CI     │
                 │                                          │                              │
                 │        apps/ava-factory/ava/rl: run_code_act ⇄ subprocess Sandbox       │
                 │        (real CodeAct loop, real LLM-VM, codeact_rewards components)     │
                 │                                          │                              │
                 │                    data/traces/traces.jsonl  (one record per task)      │
                 └──────────────────────────────┬──────────────────────────────────────────┘
                                                │ flywheel.py
        ┌───────────────────────┬───────────────┼──────────────────────┬──────────────────┐
        ▼                       ▼               ▼                      ▼                  │
  export_rft_dataset      mint_memories      evaluate             train_step              │
  scout-cli RFT ETL       ava-skills         ava-open-harness     ava-factory             │
  (audit.jsonl shape →    memory-mint        `python -m harness   scripts/                │
  versioned RFT JSONL)    (ShardMemo-scoped  run` (real report    rl_smoke_update.py      │
                          shards on disk)    files)               (real GRPO update)      │
        └───────────────────────┴───────────────┴──────────────────────┴──────► better ava
                                                                                checkpoint
                                                                                ──► AvaPolicy
```

## The flywheel loop

1. **Run tasks** (`POST /tasks`, backend `ollama`): the CodeAct loop drives the model,
   actions execute in the factory's real subprocess sandbox, only the sanitized FINAL
   reaches you; the full trace (code, observations, tool calls, wall times) is captured.
2. **Traces → training data**: `POST /flywheel/export-rft` converts traces into the
   scout-cli audit shape and runs the **real** RFT ETL (redaction, episode segmentation,
   reward *components*, versioned schema).
3. **Traces → memory**: `POST /flywheel/mint` feeds completed tasks through the **real**
   ava-skills memory-mint pipeline; shards are ShardMemo-scoped and recallable by
   memory-router.
4. **Eval gate**: `POST /flywheel/evaluate` shells out to the **real** ava-open-harness
   runner and returns the real report paths (mock mode for plumbing, real mode with a ckpt).
5. **Train step**: `POST /flywheel/train-step` runs the factory's proven
   `scripts/rl_smoke_update.py` — real rollouts → real rewards → **one real GRPO update** →
   mechanical-health gate → manifest append. Refuses honestly if no checkpoint tree exists.
6. **Better checkpoint → AvaPolicy** — and the loop repeats. Today each pass proves the
   mechanics (capability_claim=none); capability comes from scale, not from this code.

## Quickstart (your box)

```bash
# 1. Make sure Ollama is serving your model
ollama serve &            # if not already running
ollama pull qwen3:32b     # once

# 2. Bring up Hermes
docker compose -f apps/hermes/docker-compose.hermes.yml up --build -d

# 3. Honest status (backend availability is really probed)
curl -s http://localhost:8100/status | python -m json.tool

# 4. Run a task with your local model as the brain
curl -s -X POST http://localhost:8100/tasks \
  -H 'content-type: application/json' \
  -d '{"prompt": "How many words are in this sentence? Use the word_count tool.", "backend": "ollama"}'
curl -s http://localhost:8100/tasks/<task_id>

# 5. Spin the flywheel
curl -s -X POST http://localhost:8100/flywheel/export-rft
curl -s -X POST http://localhost:8100/flywheel/mint
curl -s -X POST http://localhost:8100/flywheel/evaluate -H 'content-type: application/json' -d '{"mode":"mock"}'
curl -s -X POST http://localhost:8100/flywheel/train-step -H 'content-type: application/json' -d '{}'
```

No Docker? From the monorepo root:

```bash
pip install fastapi uvicorn httpx pydantic   # torch optional (ava backend / train-step)
cd apps/hermes
python -m hermes status
python -m hermes run "quick plumbing check" --backend echo
python -m hermes serve --port 8100
```

Environment knobs: `HERMES_OLLAMA_URL` (default `http://host.docker.internal:11434`),
`HERMES_OLLAMA_MODEL` (default `qwen3:32b`), `HERMES_DATA_DIR` (default `apps/hermes/data`,
gitignored), `HERMES_AVA_CKPT` (default probes `runs/cpu_pilot/agentic/agentic_final.pt`
across factory roots), `HERMES_WORKERS`, `HERMES_QUEUE_MAX`, `DOTTIE_ROOT`,
`AVA_FACTORY_ROOT`.

Notes for the Docker path: the image deliberately ships **without torch** (multi-GB). The
ollama brain, engine, RFT export, memory mint, and mock-mode eval all work in-container;
the ava backend and train-step refuse honestly until you `pip install torch` in the
container and mount a checkpoint tree (see comments in `docker-compose.hermes.yml`).
`extra_hosts: host.docker.internal:host-gateway` makes your host's Ollama reachable on
Linux; on Docker Desktop (Windows/macOS) the name already resolves.

## Tests

```bash
cd apps/hermes && python -m pytest tests -q
```

Honest CPU tests, no network fabrication: echo end-to-end through the **real** CodeAct
sandbox, unreachable-Ollama honest refusal, missing-checkpoint honest refusal (plus a real
smoke decode when a checkpoint is present, expected to emit noise), API submit/poll/status,
real ETL + real memory-mint runs over real traces, real harness subprocess, and the
train-step honest gates.

## Relation to the WebGPU "dottie-claw" future (planned, not built)

The long-term serving path is a browser-side WebGPU runtime ("dottie-claw") that loads an
exported capable Ava checkpoint and runs the same CodeAct protocol client-side. Hermes is
deliberately shaped for that future: the `Policy` contract (`transcript -> next turn`) is
transport-agnostic, traces/status are stable JSON a web UI (arxiviq) can render, and the
flywheel is the thing that must eventually produce a checkpoint worth exporting. Nothing
about dottie-claw exists yet, and this README makes no claim that it does.
