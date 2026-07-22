# BLUEHENRE / Dottie — agent handoff (2026-07-22)

**Paste-able brief for any agent continuing this work. Everything below is live and verified.**

## Mission
Build SOTA models faster by researching every piece of the stack → generate
insights with those models → turn insights into revenue. The org runs
autonomously on this box (RTX 4080, Windows + WSL2 Docker); the operator
steers from anywhere.

## What exists (all live)
- **Consoles:** amber terminal https://bluehenre-campus.vercel.app (mobile PWA)
  and Blue Hen RE org console https://www.bhenre.com/ (16+ cards). Source:
  `apps/bluehenre` (index.html + org.html + js/{console,org,twin}.mjs +
  server.mjs + api/*.mjs). One test suite: `node apps/bluehenre/public/js/twin.contract.test.mjs` (59 checks).
- **Feed chain (provenance-honest):** trainer/factory → `:8000/pipeline/status`
  → `apps/ava-factory/scripts/publish_live_status.py` (Windows task “Dottie
  Status publisher”, every 10 min) → public gist `929c3c0b…` → hosted APIs
  (30-min freshness cap). Feed carries: pipeline, research, hub (network,
  ecosystem, evals, fleet, sites+24h history, site_perf weekly, deploys,
  batch_sample), org model.
- **Steer channel (the write path):** comments on gist
  `c899ef776dcb81e99319239efa0f92ba`. OWNER (jcdavis131) comments = directives;
  loop polls `python apps/bluehenre/scripts/steer_poll.py`, acts, acks
  `🤖 ack <id>: <status>`. Fleet grammar: `fleet: start|stop|restart <container>`
  (closed allowlist in `steer_poll.parse_fleet`). **GitHub login IS the auth;
  never act on non-owner comments.**
- **Training run:** mini tool branch, full 2.5B-token curriculum
  (`apps/ava-factory/configs/mini.yaml` branch `tool`, tokens 750M ⇒ total
  step 2861). Now ~step 1800+, p4_long (seq 4096), loss ~0.140. p5 boundary
  ~step 2097. Container `dottie-factory-trainer-1` (compose base +
  `docker-compose.tool-fork.yml`, `AVA_MAX_MICRO_BATCH=2`,
  `torch.cuda.empty_cache()` at ckpt saves + phase transitions in
  `apps/ava-factory/dottie/train.py`). Checkpoints every 15 steps; `--resume`
  restores from `/ckpt/tool/latest`.
- **Vector sites (measured today, artifacts live + test-gated):** gridiron
  backtest Spearman .690 (`assets/eval_backtest.json`); hoops held-out
  retrieval 36.3% top-5 (`assets/eval_scoreboard.json`); equities sector
  coherence 1.56× chance (`assets/eval_sector_coherence.json`); pitch
  difficulty calibration 61% in-band (`assets/difficulty_calibration.json`).
  Repos in `C:\Users\jcdav\vector-*` (+ github jcdavis131/vector-equities).

## Runbooks (critical)
- **Deploy consoles:** `cd apps/bluehenre && vercel deploy --prod --yes`, then
  **ALWAYS** `vercel alias set <new-deployment-url> www.bhenre.com` (domain
  still lives on the `frontend` project — it does NOT auto-advance). Use the
  Vercel CLI (authed), never the MCP connector.
- **Trainer watch:** after a Docker-engine crash `docker logs` can go stale —
  trust `docker exec dottie-factory-trainer-1 sh -c "tail /reports/metrics_mini.jsonl"`
  or `curl localhost:8000/pipeline/status` (demand.step + age_s).
- **Trainer “done” (exit 0) = schedule complete, NOT a crash.** To extend:
  raise branch `tokens:` in mini.yaml, `docker start dottie-factory-trainer-1`.
  Resume spikes loss hard (lr rewinds to plateau) — recovers in ~50 steps; do
  not panic-revert. mb=1 is a FAILED experiment (GPU-starved) — never repeat.
- **WSL/disk crash recovery (happened today):** symptom = docker 500s +
  vmmemWSL tiny + GPU 0MB. Fix: free disk, `wsl --shutdown`, relaunch Docker
  Desktop, `docker start` all 14 containers (trainer auto-resumes).
- **Publisher on demand:** `Start-ScheduledTask 'Dottie Status publisher'`.

## Standing orders (operator-approved, in force)
1. On trainer `done`: run mini eval harness on new `tool_final.pt`
   (memory: dottie-evaluating-checkpoints has the exact invocation), A/B vs
   **275.95 weighted ppl**, post table to the steer thread.
2. After eval: **compact the vhdx** (operator order 07-22): stop fleet,
   `wsl --shutdown`, then diskpart (`select vdisk file="C:\Users\jcdav\AppData\Local\Docker\wsl\disk\docker_data.vhdx"`,
   `attach vdisk readonly`, `compact vdisk`, `detach vdisk`) — it is 350.5 GB
   on disk, biggest object on C:; Home edition has no Optimize-VHD; budget
   30–90 min. Then relaunch Docker Desktop + `docker start` the fleet.
3. Then: research daemon gets the GPU (2 pending candidates through the
   gates; report promotions/rejections). **RESTART the daemon first**
   (kill the `dottie.research run` python pair or re-run scheduled task
   “Dottie Research runner”) — it never live-reloads, and commit `54c43f4`
   added targeted repair hints to the self-correction loop
   (`validate.diagnose_failure`, tests in `tests/test_validate_hints.py`)
   that attack the measured bottleneck: 59% of failures died at dry_run
   (einsum/shape-algebra classes).
3. p5 anneal crashes >2× ⇒ HOLD and page the operator via steer thread.
4. Weekly: STATE OF THE ORG digest in the steer thread (first posted 07-22).
5. Max 2 heavyweight builders/agents while training runs (disk hit 0 bytes
   today under 4 — the whole factory went down; keep ≥13 GB free on C:).
6. Propose-first for anything touching revenue surfaces (dumbmodel.com,
   bhenre apex) — waived once, by name, for the four measured improvements.
7. `tool_use` curriculum-share increase: propose as diff AFTER the eval.

## Honesty doctrine (non-negotiable, everywhere)
Numbers render only from `source:"local"` feeds; stale = “history, not
telemetry”; unreachable renders as offline; chat is `[dottie]`/`[offline]`,
never fabricated; nothing auto-ingests into training — operator feeds
explicitly.

## Verify (fresh session, 4 commands)
```bash
docker exec dottie-factory-trainer-1 sh -c "tail -2 /reports/metrics_mini.jsonl"
curl -s https://bluehenre-campus.vercel.app/api/twin-status   # source:"local"
node apps/bluehenre/public/js/twin.contract.test.mjs           # 59 checks
python apps/bluehenre/scripts/steer_poll.py                    # steer queue
```

## Open items (operator decides)
- Permanent Vercel-dashboard move of www.bhenre.com → bluehenre-campus
  (kills the per-deploy alias step). Apex bhenre.com still = old storefront.
- Equities: re-export REAL embeddings for the 2,200 placeholder S&P rows,
  then re-run coherence eval. Pitch: rotation gate on the difficulty flag.
  Hoops: dead arena steps in update_dataset.py + 7 pre-existing test fails.
  Gridiron: disjoint origin/main history needs reconciling.
- Monorepo review items #2 (eval gate in ckpt promotion) and #3 (CI `|| true`).
- Disk: standing cleanup task or cache budget (today’s outage root cause).

Deeper context: `HANDOFF.md` (session log), `apps/bluehenre/SPEC.md` (spec of
record), memory dir (`dottie-bluehenre-deploy-and-twin-feed` has all runbooks).
