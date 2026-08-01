# Factory review

> **Status 2026-08-01:**
> - 🔴 Dockerfile missing `COPY dottie/` — **FIXED** (`f41718b`), and worse than reported:
>   `.dockerignore` excludes `data/` and `reports/` while the Dockerfile COPYs both, and a
>   COPY whose source is fully dockerignored is a hard BUILD failure, not a skip. So the
>   image likely could not build, let alone boot. Added a `!data/nano/tokenizer/` negation
>   and removed the `reports/` COPY (compose mounts `ava_reports:/reports`).
>   **Not build-verified** — Docker Desktop is down and starting it would raise the trainer
>   stack over FROZEN paths. Verified statically; run `docker build -t ava-serve apps/ava-factory`.
> - 🔴 `_point_latest_at` promotes every checkpoint unconditionally — **STILL OPEN**.
>   Re-checked: `grep -c "verdict\|eg_trend" dottie/train.py` is still **0**. Unfixable
>   here — `apps/ava-factory/dottie/**` is FROZEN and bind-mounted into the live trainer.
>   Operator's call.
> - 🟡 items below are NOT re-verified; treat them as of 2026-07-22.

## Findings
- 🔴 apps/ava-factory/dottie/train.py:498 — `_point_latest_at()` repoints `ckpt/latest` unconditionally after every checkpoint save (and again at :505 for final), and the serve engine hot-reloads it within ~5s; no eval verdict (`eg_trend`, `run_harness`) is consulted anywhere in the promotion path, so every checkpoint — including regressed ones — is silently promoted to live serving; the "gate" is report-only.
- 🔴 apps/ava-factory/Dockerfile:38 — the slim serve image COPYs `ava/` but never `dottie/`, yet server.py:22 does `from dottie.serve_engine import get_engine`, so the shipped "Stage 8 self-host package" dies with ModuleNotFoundError at boot (docker/Dockerfile.cpu:20-22 even documents this exact failure mode).
- 🟡 apps/ava-factory/server.py:303 — `/generate`, `/chat`, `/jspace/inspect`, and the WebSocket accept unbounded `text` with no length cap, and GenerateReq has no field constraints (tiny positive `temperature` yields inf/NaN → 500); generation in serve_engine.py:250 re-runs a full forward per token with no KV cache while holding the engine-wide RLock, so one large-prompt request blocks `/health` and every other route — a trivial single-request DoS.
- 🟡 apps/ava-factory/server.py:493 — the mutating `/jspace/intervene` route is "gated" only by the client-supplied `?mode=research` query param plus a server-wide env flag; with `ENABLE_JSPACE_WRITE=1` set and the server bound to 0.0.0.0:8000, any unauthenticated network client can run interventions (bearer auth exists only on `/assistant`, and is opt-in default-off).
- 🟡 apps/ava-factory/requirements.txt:1 — three inconsistent dependency universes: requirements.txt floor-pins with several fully unpinned entries (dolma, nemo-curator, safetensors, einops, websockets; only prefect==3.4.0 exact), Dockerfile:25-29 installs a different unpinned subset ignoring requirements.txt, docker/requirements.{cpu,gpu}.txt exact-pin; ava-factory is excluded from the uv workspace by design (root pyproject.toml:13) so nothing locks the env the README tells users to `pip install`.
- 🟢 apps/ava-factory/dottie/serve_engine.py:47 — env-dependent defaults (`/state/tokenizer.json` absolute path, `host.docker.internal:8100` in server.py:408) plus a fixed reseed to 1234 on every `generate()` call (:254) make "temperature sampling" deterministic across identical requests and stomp the process-wide torch RNG; the trainer itself seeds correctly (train.py:257-259, RNG state in checkpoints), so README's repro claims mostly hold for training.

## Risk
- Regressed or corrupted-but-loadable checkpoints go live automatically within ~5s of being written; nobody notices until users see bad output — the eval harness runs but its verdict changes nothing.
- The standalone serve image cannot boot at all, so any self-host deploy following the Dockerfile header instructions fails; and once fixed, one oversized `/generate` request can hang the whole server.
- Unpinned/inconsistent deps mean train and serve images can drift to different torch/tokenizers versions, breaking checkpoint/shard compatibility that docker/requirements.cpu.txt explicitly calls load-bearing.

## Recommendation
1. Wire the gate: have the trainer (or a promotion script) run the eval harness and only call `_point_latest_at` on a "promote" verdict; keep a `latest_candidate` pointer for ungated checkpoints.
2. Add `COPY dottie/ /app/dottie/` to the slim Dockerfile and a CI smoke test that builds it and hits `/health`.
3. Add Pydantic field constraints (max text length, `temperature: float = Field(0.8, gt=0.01, le=4)`) and a shared bearer-token dependency on `/jspace/intervene`; then converge on the exact-pin docker/requirements files as the single dependency source.

## Evidence
```
dottie/train.py:494  if step % cfg.training.checkpoint_every_steps == 0 or step == total_steps:
dottie/train.py:497      save_ckpt(p, model=model, opt=opt, ...)
dottie/train.py:498      _point_latest_at(ckpt_dir, p)          # no eval consulted
dottie/serve_engine.py:9  "Hot-reload ... polls mtime + content every ~5s"
$ grep -rn "verdict\|eg_trend" dottie/train.py scripts/dottie_continuous_loop.py
(no matches — promote/hold verdicts from efficiency_gain.py:123 are report-only)
$ grep -n "COPY" Dockerfile | grep dottie
(no matches; server.py:22 imports dottie.serve_engine)
```
