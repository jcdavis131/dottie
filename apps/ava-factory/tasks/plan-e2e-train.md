# Plan: Train Ava-agi end to end (auto-mode)

Date: 2026-07-10  
Branch: `claude/model-training-workflow-plan-n5vep5`  
Mode: auto — advance until budget / GO-NO-GO gates.

## Live evidence (session open)

- Nano **complete**: `/ckpt/base_final.pt`, step 3662, ~30M tokens; stables `stable_p0`…`p4`.
- Trainer **done-loop**: `restart: unless-stopped` + `--resume` on finished run → exit 0 → restart (31×, then SIGKILL 137).
- Data plane up (collectors/curators/janitor). Server down (GPU exclusivity). Disk ~14 GB free.
- Specs present under `specs/`. Git clean at `62ffb4d`.

## Ladder (what “E2E” means here)

| Rung | Scope | Auto-mode |
|------|--------|-----------|
| **T9.1 nano** | Close loop: stop done-loop, serve `base_final`, chat fork + `smoke_live`, mark TODOS | **Execute** |
| **T9.2 mini** | 171M, ~2.5B tokens, **3–5 days**, vocab 32k | **Running** — babysit; disk backpressure fixed 2026-07-10 |
| **T9.3+** | base1b GO/NO-GO + milestones | **Hard stop** — user decision |

## Auto-mode note (2026-07-10 afternoon)

- Mini healthy: step **150+**, ~5.5–8k tok/s steady (early peak ~12.7k), RestartCount=0, P0 runway ~304M tokens.
- **Bug fixed:** Docker Desktop `free_gb(/raw)` reported ~987GB while host C: was ~8GB; prefetch of empty P1 also bypassed `raw_max`. Collectors filled ~40GB RAW. Fix: host bind-mount probe (`/host_disk` + `AVA_DISK_PROBE`) + only skip raw-cap when *trainer* phase is starved. Janitor eviction now sees real host free.
- Collectors paused at low_water until host ≥12GB; curators+janitor continue; server kept stopped (GPU).
- **Do not start T9.3 / base1b** without explicit user GO.

## T9.1 work

1. Trainer: early-exit when resume already at `total_steps`; compose `restart: on-failure`.
2. Start `server` on `/ckpt/latest` → `base_final.pt`; health + generate.
3. Short chat branch fork (`--branch chat --init base_final --max-steps` smoke-scale) → `chat_final.pt`.
4. `AVA_BASE_URL` / `AVA_CKPT` live smoke (or compose-equivalent).
5. Mark T9.1 done in `TODOS.md`; scoped commit.

## Non-goals this session

- Starting mini without budget confirm.
- base1b / T9.3.
- `docker system prune --volumes`.
- Killing non-ava GPU processes.

## Acceptance (T9.1)

- [x] Trainer does not restart-loop on finished nano (`already_done` + `restart: on-failure`).
- [x] `GET /health` + `POST /generate` against live server + nano weights.
- [x] Chat ckpt at `/ckpt/chat/chat_final.pt` (80-step smoke fork; full 3M = T9.5).
- [x] Live smoke: `AVA_BASE_URL=http://127.0.0.1:8000` → **SMOKE PASS**.
- [x] `TODOS.md` T9.1 checked with measured notes.
