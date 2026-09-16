# Dottie Prompt Tuner

Treat prompt templates as tunable hyperparameters — a stdlib-only port of the
[Machine Learning Mastery GridSearchCV idea](https://machinelearningmastery.com/treating-prompt-templates-as-hyperparameters-in-scikit-llm-gridsearchcv/).
Candidate prompts are the hyperparameter grid; k-fold cross-validation picks
the winner. No sklearn, no torch, no pip.

## What it optimizes first

**The autonomy gate** (`tuner/evals/approval_gate.py`): given a Dottie job
spec, classify it `auto` (safe to run hands-free) or `approval` (needs
Cameron's explicit word first). Labels follow the worker's standing rule —
destructive operations (merge, push, close, delete, archive, send) need
approval; read-only work runs free. Two examples are verbatim real queue
records; the rest are labeled from the policy in `worker/README.md`, with
provenance noted per example.

## Run it

Harness self-test — no model needed, verifies the machinery only:

```sh
python3 -m tuner.run_eval --eval approval_gate --backend stub
```

Real model via a CLI (e.g. Ollama):

```sh
python3 -m tuner.run_eval --eval approval_gate --backend cmd \
    --cmd "ollama run qwen3:0.6b" --cv 5
```

Real model via OpenAI-compatible HTTP (e.g. `ollama serve`):

```sh
python3 -m tuner.run_eval --eval approval_gate --backend http \
    --base-url http://localhost:11434/v1 --model qwen3:0.6b --cv 5
```

Unit tests (stub backend only, no model):

```sh
python3 -m unittest tuner.tests.test_tuner -v
```

## What you get

- Best prompt template + cross-validated accuracy, printed like the article.
- `tuner/.runs/<run-id>/results.json` — every candidate, mean accuracy, per-fold scores.
- `tuner/.runs/<run-id>/timeline.jsonl` — one 7-field record per fold
  (nodeId/agentId/attempt/latency_ms/tokens_est/status/errorClass), per the
  Dottie worker's logging discipline.

## Design rules

- **Fail-closed.** A backend crash, timeout, or unparseable reply labels the
  sample `unknown`, which never counts as correct. A broken model can't win
  by accident.
- **Deterministic.** Fixed seed k-fold splits; same data + seed = same result.
- **Honest scope.** 10 examples is a smoke test, not a justification — the
  article says the same about its 4. Grow the eval set from real queue history
  before trusting a winner.
- **Zero-deps.** Stdlib only. The `StubGenerator` is test-only and says so;
  it knows the answers by construction and must never back a real evaluation.

## Adding a new eval

Drop a module in `tuner/evals/` exposing `load()` → `(X, y, templates, labels)`,
register it in `run_eval.py`'s `EVALS`, and run. Good next candidates: the
Dottie dispatch router (which lane a job belongs to) and the Scout
inbox-triage rubric.
