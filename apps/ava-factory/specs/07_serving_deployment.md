# Spec 07 — Serving Engine, Real Server, Three Deployment Targets

- **Spec ID:** 07_serving_deployment
- **Worker tier:** Opus for parts A+B (engine + server rewiring — real forward hooks, workspace
  edits, pydantic migration). Sonnet for parts C+D+E (smoke script, report generator, Dockerfile,
  run.sh, Vercel layout).
- **Dependencies:** Spec 01 (env, Makefile, `.gitignore` with `runs/` + `export/`); model/training
  specs delivering `ava/model.py`, `ava/tokenizer` and checkpoints `runs/base/ava_nano_stable.pt`,
  `runs/base/ava_nano_final.pt`, `runs/chat/ava_nano_chat.pt`, tokenizer
  `data/nano/tokenizer/ava_nano_bpe.json`, metrics `runs/*/metrics.jsonl`; eval spec delivering
  `reports/branch_eval_results_real.json` and `reports/REPORT_REAL.md`.
- **Status when done:** `bash scripts/smoke_live.sh` green in the container (4 CPU, 15GB RAM, no
  GPU, Python 3.11, HF hub + wandb network-blocked).

## Purpose

Replace every hardcoded mock in `server.py` with real inference against the trained nano
checkpoint, wrap model loading/generation/inspection/intervention in a reusable engine
(`ava/serve_engine.py`), and define three deployment targets: (1) live test inside the container,
(2) static report site on Vercel, (3) self-host Docker package for the user's Alienware m16
(RTX 4080 Laptop 12GB, WSL2). `server.py` is one of the three real modules and MAY be modified in
place. No other blueprint file may be touched.

## Deliverable files (exact paths, repo-relative)

1. `ava/serve_engine.py` (new, Opus)
2. `server.py` (modified in place, Opus)
3. `scripts/smoke_live.sh` (new, Sonnet)
4. `scripts/make_report.py` (new, Sonnet)
5. `Dockerfile` (new, Sonnet)
6. `run.sh` (new, Sonnet)
7. `tests/test_server_endpoints.py` (new, Opus — TestClient-based, no uvicorn boot)
8. Generated at runtime, not committed: `reports/index.html`, `runs/serve_audit.jsonl`.

## Detailed requirements

### A. ava/serve_engine.py (Opus)

- `class ServeEngine` loads checkpoint + tokenizer ONCE. Checkpoint path: env `AVA_CKPT`, default
  `runs/chat/ava_nano_chat.pt`. Missing file → `FileNotFoundError` naming the path and the env
  var. Tokenizer: `data/nano/tokenizer/ava_nano_bpe.json`. CPU, `model.eval()`, all public methods
  under `torch.no_grad()` except the intervention hook path. Module-level
  `get_engine() -> ServeEngine` singleton (lazy, thread-safe via `threading.Lock`).
- `generate(text: str, max_tokens: int = 64, temperature: float = 0.8, task_type: str = "chat")
  -> dict` — sampled continuation. Returns
  `{"text": str, "tokens": int, "route_probs": [ {"S1":f,"S2":f,"Critic":f,"Planner":f}, ... one
  per generated step ], "latency_ms": float}`. `temperature <= 0` → greedy. Seedable via optional
  `seed: int | None` kwarg (used by intervene and smoke determinism checks).
- `inspect(text: str) -> dict` — ONE real forward with workspace capture. Returns:
  - `top_concepts`: list of 8 `{"concept": str, "p": float}` — decode: verbalizer logits over the
    mean workspace state, softmax, top-8 token ids decoded to strings via the real tokenizer.
  - `verbalizable_mass`: float in (0,1) — summed softmax probability of the top-8.
  - `broadcast_strength`: float — `||broadcast_vector|| / ||fused_hidden||` (the quantity trained
    toward 0.20).
  - `per_space`: dict keyed `system1,system2,critic,planner`, each
    `{"broadcast": f, "hl_est": f, "mass": f}` — `hl_est` from the space's decay parameter
    (`hl = ln(2)/-ln(decay)` or the model's own accessor), `mass` = that space's verbalizer mass.
  - `route_probs`: mean router distribution over the sequence (4 floats summing to 1 ± 1e-4).
  - `safety_scan`: dict word→prob. Critic-space verbalizer probability mass on the safety token
    set `["leverage","blackmail","threat","scandal","shutdown","fake","secretly","trick","unsafe",
    "dangerous"]` — words missing from the 8192 BPE vocab are scored via their first sub-token;
    include `"total"` = summed mass.
- `intervene(text: str, from_concept: str, to_concept: str, space: str = "system2") -> dict` —
  REAL workspace edit via a `register_forward_hook` on the chosen space's workspace module:
  concept vectors = embedding rows (first token of each concept); hook subtracts the projection
  onto the from-vector and adds the to-vector scaled to matched norm, applied to the space's slot
  states. Decode baseline and intervened with the SAME seed (default 1234) and
  `max_tokens=32, temperature=0`. Hook MUST be removed in a `finally`. Returns
  `{"baseline_text","intervened_text","delta_logprob": float (next-step logprob(to first token)
  minus logprob(from first token), intervened vs baseline), "space","changed": baseline_text !=
  intervened_text, "audit_logged": true}`. Appends one JSON line to `runs/serve_audit.jsonl`:
  `{"ts","from","to","space","text_sha256","delta_logprob","changed"}` (create parent dir).
- `stats() -> dict` — `{"ckpt": path, "params": int, "vocab": int, "d_model": int}` for /health.
- `block_stream(text: str)` — generator yielding one dict per transformer block from a single
  real forward: `{"block": i, "regime": "text|fusion|reasoning", "hidden_norm": f,
  "top_concept": str, "route_probs": {...}}` (route_probs only for fusion blocks; else null).
  Used by the WebSocket.

### B. server.py fixes + rewiring (Opus, in-place)

- Fix 1 (verified bug): add `from typing import Optional` — currently line 68
  (`instruction: Optional[str]=None`) raises NameError at import time.
- Fix 2 (verified bug): migrate `InterveneReq` to pydantic v2 — replace
  `class Config: fields = {'from_': 'from', 'to_': 'to'}` with
  `from_: Optional[str] = Field(default=None, alias="from")` and
  `model_config = ConfigDict(populate_by_name=True)`; keep the `from_c`/`to_c` fallbacks and the
  `from_concept`/`to_concept` properties. Change `/jspace/intervene` to take `InterveneReq` as the
  body model instead of raw `Request` JSON.
- Load `get_engine()` in a FastAPI lifespan handler so a broken checkpoint fails at boot, not on
  first request.
- Replace ALL mock JSON with `serve_engine` calls. Endpoint surface (unchanged paths):
  - `GET /jspace/viewer` — keep the existing HTML UI; its fetches now hit the real endpoints. UI
    may be lightly edited only to match real response field names.
  - `POST /jspace/inspect` — body `InspectReq {text, instruction?, image?}` → `engine.inspect`.
  - `POST /jspace/intervene` — gate UNCHANGED: `?mode=research` AND env `ENABLE_JSPACE_WRITE=1`,
    else 403 with the existing detail string → `engine.intervene`.
  - `POST /jspace/safety` — `engine.inspect(text)["safety_scan"]` plus `hits` word list.
  - `GET /jspace/eval_branch` — serve cached `reports/branch_eval_results_real.json` (filter to
    `?branch=` if present); file missing → 404 `{"detail":"run eval first: make eval"}`.
  - `GET /jspace/eval_report` — return `reports/REPORT_REAL.md` content as
    `{"report_markdown": str}`; 404 if missing.
  - `WS /jspace/stream` — on connect read one text message (prompt; empty → default
    `"The number of legs on the animal that spins webs is"`), stream one JSON message per block
    from `engine.block_stream`, then close. No `asyncio.sleep(0.5)` mock loop.
- ADD three endpoints:
  - `GET /health` → 200 `{"status":"ok","ckpt": str,"params": int,"vocab": int}`.
  - `POST /generate` — body `{text: str, max_tokens: int = 64 (cap 256), temperature: float = 0.8,
    task_type: str = "chat"}` → `{"text","tokens","route_probs","latency_ms"}`. 422 on empty text.
  - `GET /report` → `FileResponse("reports/index.html")`; 404
    `{"detail":"run scripts/make_report.py first"}` if absent.

### C. scripts/smoke_live.sh (Sonnet)

`#!/usr/bin/env bash`, `set -euo pipefail`. Boots `uvicorn server:app --host 0.0.0.0 --port 8000`
in background (respecting inherited `AVA_CKPT`), polls `GET /health` every 1s for max 60s, then
asserts (curl + `python -c` JSON checks), always killing the server via `trap`:
1. `/health` returns 200 with `params > 10_000_000` and `vocab == 8192`.
2. `POST /generate` on two different prompts returns non-empty `text`, and the two texts differ.
3. `POST /jspace/inspect` → `0 < verbalizable_mass < 1`, and mass differs between two different
   input texts (inequality at 1e-9).
4. `POST /jspace/intervene?mode=research` WITHOUT `ENABLE_JSPACE_WRITE` → HTTP 403. Then re-boot
   (or use a second server on port 8001) with `ENABLE_JSPACE_WRITE=1` → 200 and
   `baseline_text != intervened_text` for spider→ant, and `runs/serve_audit.jsonl` grew by 1 line.
5. `GET /jspace/eval_branch` returns the real JSON (a key from
   `reports/branch_eval_results_real.json` is present).
6. `GET /report` returns HTML larger than 10240 bytes (run `scripts/make_report.py` first inside
   the script if `reports/index.html` is missing).
Exit 0 only if all pass; print `SMOKE PASS`/`SMOKE FAIL <step>`.

### D. scripts/make_report.py (Sonnet)

- `python scripts/make_report.py [--runs runs] [--out reports/index.html]`. Reads every
  `runs/*/metrics.jsonl`; reads `reports/branch_eval_results_real.json` if present.
- Output is ONE self-contained HTML file: inline `<script>` + inline SVG only. NO CDN, no external
  fonts/CSS/fetch — all data embedded as a JS literal. Must render opened as `file://` and as a
  static file on Vercel.
- Sections (each an SVG chart with axes + labels): (1) loss curves per run, log-y; (2) lr
  schedule; (3) per-space half-life estimate vs target (nano targets S1=8, S2=60, Critic=30,
  Planner=50 from `configs/nano.yaml`) as grouped bars; (4) route_probs over training steps
  (4 stacked/line series); (5) broadcast_strength and verbalizable_mass over steps with target
  lines at 0.20 and 0.06; (6) eval results table from the JSON. Missing metric keys → skip that
  chart with a visible "no data" note, never crash. Output must exceed 10KB.
- Also supports `--render-md reports/REPORT_REAL.md` → writes `reports/report_real.html`
  (minimal inline-styled markdown rendering; stdlib only) for the Vercel bundle.

### E. Deployment targets

1. **Container live test (the "deploy to test live" gate):**
   `AVA_CKPT=runs/chat/ava_nano_chat.pt uvicorn server:app --host 0.0.0.0 --port 8000` then
   `bash scripts/smoke_live.sh`. Boot-to-healthy under 60s on 4 CPUs.
2. **Vercel static report site:** deploy the `reports/` directory as-is (no build step). Required
   layout: `reports/index.html` (from make_report.py), `reports/report_real.html` (rendered
   REPORT_REAL.md), `reports/branch_eval_results_real.json`. Deploy via Vercel CLI
   (`npx vercel deploy reports --prod --yes`) or the Vercel MCP `deploy_to_vercel` tool with
   `reports/` as project root. No `vercel.json` required; if added, static-only
   (`{"cleanUrls": true}`). index.html must link to the other two files with relative hrefs.
3. **Self-host package (Alienware):** `Dockerfile` — two-stage on `python:3.11-slim`: builder
   stage pip-installs into `/opt/venv` with
   `ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu` (CUDA variant documented in a comment:
   `--build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu124`); runtime stage copies
   `/opt/venv`, `ava/`, `server.py`, `scripts/`, `configs/`, `data/nano/tokenizer/`; `EXPOSE
   8000`; `ENV AVA_CKPT=/app/runs/chat/ava_nano_chat.pt`; CMD
   `uvicorn server:app --host 0.0.0.0 --port 8000`. Checkpoints are NOT baked into the image.
   `run.sh`: `docker build -t ava-serve .` then
   `docker run --rm -p 8000:8000 -v "$(pwd)/runs:/app/runs" -e AVA_CKPT ava-serve`; `--gpus all`
   added when `run.sh gpu` is invoked (CUDA image variant).

### tests/test_server_endpoints.py

FastAPI `TestClient`, tiny checkpoint fixture allowed (or the real nano ckpt if present, else
`pytest.skip`): asserts `import server` succeeds (regression for the Optional bug), intervene 403
without env flag, `InterveneReq(**{"from":"spider","to":"ant"})` populates `from_` (regression for
the pydantic v2 alias), `/health` schema.

## Interfaces

- Downstream (spec 09, runbook) relies on: `from ava.serve_engine import get_engine`;
  `get_engine().stats()`; the `/health`, `/generate`, `/report` routes; audit file
  `runs/serve_audit.jsonl` schema above. These are frozen contracts.

## Acceptance criteria (foreman runs, from repo root)

1. `python -c "import server; print('import ok')"` → prints `import ok` (fails on current code).
2. `pytest tests/test_server_endpoints.py` → all pass.
3. `AVA_CKPT=runs/chat/ava_nano_chat.pt bash scripts/smoke_live.sh` → prints `SMOKE PASS`, exit 0.
4. `python scripts/make_report.py && python -c "import os;assert os.path.getsize('reports/index.html')>10240"`
   → exit 0; `grep -ci 'cdn\|https://fonts' reports/index.html` → `0`.
5. `docker build -t ava-serve .` succeeds (skip with a note if the container lacks docker; the
   Dockerfile must still pass `docker build` dry review + hadolint-level sanity).
6. `git status --porcelain` shows only: modified `server.py`; new files listed above. No other
   blueprint file modified.

## Out of scope

- Auth/TLS/rate limiting, request batching, streaming token-by-token generation, quantization.
- GPU inference paths (CPU only in container; CUDA only via documented Docker build-arg).
- Pushing to HF hub or wandb (network-blocked). Executing the actual Vercel deploy (layout +
  command are the deliverable; the foreman triggers the deploy).
- Modifying eval harness, training code, or `convert_to_hf.py`. Committing to git.
