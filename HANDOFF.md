# HANDOFF — pick up and execute this session's work

**For any assistant (or the operator) resuming Dottie work. Start here —
but the CURRENT operational brief lives in [`CURSOR_HANDOFF.md`](CURSOR_HANDOFF.md)
(kept continuously updated; supersedes the session blocks below for live
state, runbooks and standing orders).**

---

## 📌 Session continuation — 2026-07-22 ~11:35 CDT (supersedes the 00:09 block)

**The product PIVOTED twice today on operator directives — current truth:**
**bluehenre is the org's COMMAND CONSOLE (no 3D world; deleted), on TWO
surfaces:** (1) cozy amber terminal at https://bluehenre-campus.vercel.app
(quick mobile: RUN/ALERTS/DOTTIE/FLEET/HUB/SITES; installable PWA); (2) the
comprehensive **Blue Hen RE org console at https://www.bhenre.com/** —
16 cards (curriculum phases, data flow, manifest, checkpoints, compute,
routing watch, demand, etc.) in that site's own aesthetic, via `parseOrg`
(`status.org`). ⚠ **www.bhenre.com is a DEPLOYMENT ALIAS** (domain still on
the `frontend` project): after every `vercel deploy --prod`, run
`vercel alias set <new-deployment-url> www.bhenre.com` or bhenre goes stale.
Apex bhenre.com = old storefront, untouched. `apps/bluehenre` = index.html
(terminal) + org.html + js/{console,org,twin}.mjs (47 bare-node checks) +
server.mjs + api/{twin-status,fleet,npc-chat}.mjs. Org mission encoded in
SPEC/README: SOTA models faster → insights → revenue.

### Live state
- **Trainer**: tool branch extended to the FULL curriculum (mini.yaml tokens
  750M, commit 8b74c42 saga): resumed through p4_long (seq 4096) at step
  ~1580, lm 0.1405 (best), ~60-90s/step wall. p4 OOM crash-loop was fixed by
  mb=2 + torch.cuda.empty_cache() at ckpt saves + phase transitions
  (dottie/train.py, bind-mounted; 4260c91). mb=1 was a FAILED experiment
  (GPU-starved, 0 steps/40min) — do not repeat. p4→p5 boundary ~step 2098
  (2.3B tokens) is the next risk point; ratchet ckpts every 15 steps.
  **ON COMPLETION** (`"event":"done"` → new tool_final.pt, ~step 2861): run
  the mini eval harness on it (memory: dottie-evaluating-checkpoints) and A/B
  against the pre-extension 275.95 weighted ppl — GPU is free then.
- **Publisher**: "Dottie Status publisher" task now EVERY 10 MIN
  (operator-approved); pushes pipeline+research+hub(network/ecosystem/
  agent-eval/evals/fleet/sites) to gist 929c3c0b…; hosted freshness caps 30
  min. Fleet snapshot + 8 site probes included.
- **Fleet**: 13-14 docker containers healthy; trainer restarts=0 since fix.
- **Console data spine**: local /api/twin-status chain = live :8000/pipeline/
  status → exported file → raw artifacts; /api/fleet = docker CLI 10s cache;
  hosted = gist-feed. Provenance doctrine everywhere.

### Verify (fresh session)
```bash
docker logs --since 10m dottie-factory-trainer-1 | grep '"event": "step"' | tail -1
curl -s https://bluehenre-campus.vercel.app/api/twin-status   # source:"local" via gist-feed
node apps/bluehenre/public/js/twin.contract.test.mjs           # 41 checks
cd apps/bluehenre && vercel deploy --prod --yes                # CLI, NOT the MCP connector
```

### Operator decisions OPEN
1. **Write path** (the named next core item in SPEC): tunnel +
   DOTTIE_CHAT_URL/TWIN_STATUS_URL on Vercel, or a directive-queue gist —
   makes hosted ALERTS/DOTTIE two-way. Read-only (and says so) until then.
2. **Domain**: campus.bhenre.com is free today (operator owns bhenre.com,
   dumbmodel.com, jcamd.com); bluehenre.com is unregistered (~$15/yr, operator
   must run the purchase).
3. Monorepo-review items #2 (eval gate in ckpt promotion) + #3 (CI `|| true`).

---

## (superseded) Session continuation — 2026-07-22 00:09 CDT (continues the 07-21 block below)

**Supersedes the 07-21 block's "Decisions still YOURS": BOTH were decided and executed.**
Local `main` HEAD `ec284b3`, tree clean, 12 session commits (`a7ae0d4`…`ec284b3`).
**PUSHED 2026-07-22: operator said "push everything to origin" — `0decec3..79efda3` (296
commits) is on origin/main; local and origin are identical. The "local-only" caveats in the
blocks below are resolved.**

### Done since the 07-21 block
- **Decision A EXECUTED — trained on the new curriculum** (operator picked "extend the mini
  tool-branch"). `659a9da`: mini.yaml tool tokens 300M→390M; resumed step 1144 → done 1487
  (Exited 0, `tool_final.pt`), lm 0.2266→0.1508 (−33%), zero restarts. The step-1250 grad
  spike (6.15) was the new scout_cli/zk_math shards entering — absorbed in one step.
- **Real eval harness now WORKS on this box** (took 5 attempts; procedure + footguns in the
  `dottie-evaluating-checkpoints` memory): frozen 32k tokenizer recovered from the `ava_state`
  volume → `data/mini/tokenizer/ava_bpe_32k.json`; `a811f33` adds `--target-bytes` + guards the
  frozen tokenizer from `--force`. Report-of-record committed (`195a7e0`):
  **tool_final weighted ppl 275.95** (p0 114/p1 162/p2 630/p3 343; random floor ~36k; probes
  0/200 = the documented honest baseline). **A/B on identical bins: pre-extension step_1140 was
  7,813.80 weighted → −96.5%** (attribution = new data + clean arc + full WSD decay, inseparable
  without a control run).
- **Decision B EXECUTED — items 10+11 gates ACTIVE** (operator: "activate the gates"). `35351a7`:
  capacity gate (>10% block deletion cannot promote) + paired-seed significance
  (`Baseline.per_seed`, paired SE, conservative fallback); live 5.73733 baseline backfilled with
  per_seed [5.74331, 5.56278, 5.90589]; **daemon boot line verified `git_sha: 35351a7`**, running
  with `--seeds 0,1,2` default; memory guard refusing LLM stages gracefully until RAM frees.
  Restart gotchas (daemon = parent→child pair; script verifier) in the research-live-state memory;
  `e65e913` fixes the verifier (shared read + BOM detection, proven against the live writer).
- **BLUEHENRE game built end-to-end + deployed** (operator-forked subtasks; `26c287d`,`ec284b3`):
  **live at https://bluehenre-campus.vercel.app** — P1 campus slice → P2 NPC ecosystem →
  P3 quest pillars → P4 run-extraction into factory-shaped curriculum shards; 61/61 contract
  checks; offline-honest NPC chat. The doc's gameplay→GitHub auto-PR pipeline deliberately NOT
  built (operator sign-off required, per its SPEC).

### Operator options open (none blocking)
push to origin (`git fetch` first — 290+ ahead) · p4/p5 heldout bins (need >4096 contiguous tok)
· control extension to isolate the curriculum's share of the −96.5% · delete the dead `bluehenre`
Vercel project · set `DOTTIE_CHAT_URL` in Vercel env for hosted NPCs · stop collectors 3/4
(classifier-blocked for me).

### Gate commands
```bash
git log --oneline -1                                   # ec284b3
# daemon on gated code? (shared read — do NOT trust restart script [3] before e65e913)
powershell -c "$fs=[IO.FileStream]::new('apps/dottie/data/research/logs/run.log','Open','Read','ReadWrite');$sr=[IO.StreamReader]::new($fs);($sr.ReadToEnd() -split \"`n\") -match '\"boot\"' | select -Last 1"   # git_sha 35351a7
cd apps/dottie && AVA_FACTORY_ROOT='C:\Users\jcdav\workspace\ava-agi-factory-v6-4' ./.venv/Scripts/python -m pytest -q   # 211 passed
curl -s https://bluehenre-campus.vercel.app | head -c 200                                # live
```

---

## 📌 Session continuation — 2026-07-21 19:35 CDT (autonomous /loop + /auto-mode run)

**Supersedes the 07-20 block below: its item 00 (git reconcile) and item 9 (curriculum deploy)
are DONE.** Local `main` is the merge `eb81a43` + the 5 session commits below (`a7ae0d4`…),
**COMMITTED but NOT pushed**. See "Committed this session" for the SHAs.

### Done + verified this session
- **Git reconcile COMPLETE** (old item 00) → merge `eb81a43` (`--ours` for logic, origin's ruff
  formatting kept). Targeted suites green; dottie + ava-factory collect clean (206 + 542, 0 errors).
- **Curriculum deploy LIVE** (old item 9) — done the **memory-safe** way: bind-mounted local
  `configs/` + `dottie/datagen/` into the collectors via `docker-compose.tool-fork.yml`
  (`collector:` override), NOT the ~530 MB image build the 07-20 block feared. 7 new sources
  confirmed live in the running collector; collector is PAUSED (no trainer demand — see decision A).
- **scout_cli curriculum bug fixed** — `_dumps` used `sort_keys=True` → taught alphabetical
  envelope keys (`ok` last); real scout emits insertion order (`ok` first). Now matches real
  `contract.py`/`output.py`. 104 datagen tests green.
- **KoboldCpp runner support drafted** (operator's `/auto-mode` ask) — `scout ava infer
  --backend {ollama,koboldcpp}` + `chat_with_metrics()` in scout-cli `core/llm.py` (OpenAI /v1,
  tok/s telemetry, never fabricates on failure) + `scripts/bench_local_runner.py` (measures the
  REAL ollama-vs-kobold delta; the article's "7×" is LM-Studio→Kobold, not Ollama) +
  `tests/test_llm_backends.py` (7 passed). Kobold on :11434 is a zero-code drop-in for the
  existing Ollama path.
- **⚠ scout CLI CRASH found + fixed** — the reconcile's own `ruff check --fix` moved `import
  typer` under `TYPE_CHECKING` in `plugins/planes/cli.py`; typer eval's annotations at runtime →
  `NameError: typer` → the WHOLE `scout` CLI crashed at startup, failing all ~29 subprocess tests
  (130→108). Fixed: runtime `import typer  # noqa: TC002`. scout-cli now **137 passed**. Same
  NameError class the 07-20 block warned about, but caused BY the recommended `ruff --fix` —
  **do NOT blindly `ruff --fix` typer/pydantic/fastapi CLI modules.**

### ⚠ Decisions still YOURS (un-shipped)
- **A. Kick off a training run on the new curriculum.** The mini tool-branch (T9.3) is complete
  (`already_done`, step 1144); the nano `--resume` crashes on an incompatible checkpoint. So
  "train on the curriculum" needs your pick: nano-fresh / resume-a-compatible-ckpt / extend-mini.
  Collector stays paused until a trainer creates demand.
- **B. Items 10 + 11 — still COUPLED, still un-shipped, AND the guard is DORMANT.** The paired-seed
  trainer (`ca9f2f1`) is merged but the running daemon booted at `3b77263` (predates it, never
  live-reloads), so the loop still promotes on within-run spread (the measure that falsely promoted
  `5a7232ffea24`). Activating = `restart_research.ps1` — must be done WITH the item-10 capacity gate
  or it re-contaminates the 5.737 baseline. Detail in the research-loop-live-state memory.

### Committed this session (local `main`, NOT pushed — `git fetch` before any push)
- `a7ae0d4` fix(datagen): scout_cli envelope keys in insertion order (ok first)
- `3aeea2d` ops(factory): memory-safe curriculum deploy (collector bind-mount)
- `f7e3721` feat(scout-cli): KoboldCpp backend + `scout ava infer` + bench + 7 tests
- `feb1900` fix(scout-cli): keep typer a runtime import (planes CLI-crash fix)
- (this doc) docs: refresh HANDOFF to 2026-07-21 state

### Gate commands to verify current state
```bash
git rev-parse --short HEAD                                    # eb81a43 (reconcile done)
cd apps/scout-cli && python -m pytest -q                      # 137 passed
cd apps/ava-factory && AVA_FACTORY_ROOT=$(pwd) ../../apps/dottie/.venv/Scripts/python -m pytest tests --collect-only -q   # 542, 0 errors
docker exec dottie-factory-collector-1 grep -c synth_zk_math /app/configs/sources.yaml    # >0 → deploy live
```

---

## 📌 Session continuation — 2026-07-20 23:50 CDT (autonomous /loop run)

**All work below is committed to local `main` (HEAD `12000d3`), test-verified, and additive to
the git-B0 divergence — nothing pushed.** A long autonomous review+execute loop ran while the
operator was away. What it did, and what is now YOURS to decide:

### Shipped + verified this session (13 commits, `3b77263`…`12000d3`)
- **Curriculum expansion** (the operator's `/auto-mode` ask — scout-cli, compression, DBs, ZK
  math): wired the existing `compression`/`compress_trace`/`db_trace` generators + added two new
  ones — `scout_cli` (using+building the agent CLI, grounded in the real contract) and `zk_math`
  (Schnorr/Fiat-Shamir/Pedersen/Merkle/Shamir, every transcript computed+re-verified).
  `9006865`,`3e03b44`,`8415a6b`. Every phase still sums to 1.0; **501 factory tests green.**
- **SPEC build-priorities #1–#4 closed.** #4 monitor "not_running" fix (`b378bc3`); #3 per-seed
  factory trainer **verified end-to-end on real torch** (`ca9f2f1`,`82fe0d9`); #2 measured
  substantially-done from the ledger (100% param-declaration compliance — `e6d774f`).
- **3 real correctness bugs fixed in packages** (found by review, each with tests):
  `b5c4708` graphify — internal repo path **leaked into the public graph** (rst/qmd/yaml);
  `9e87451` graphify — **dangling ecosystem edges** for every markdown doc (file:/doc: drift);
  `12000d3` harness — **`auc_trapezoid` inflated AUC on ties** (a constant classifier scored 1.0).
  Suites green: graphify **68**, harness **32/11 skip**.

### ⚠ The two decisions that are YOURS (do NOT let a future autonomous tick ship these)
- **Items 10 + 11 are COUPLED — decide together** (TODOS item 11, `76d7aaa`). The paired-seed
  eval gate (item 11, the natural SPEC-#3 completion) lowers the promotion bar ~7×; with the
  capacity gate (item 10) OFF, a capacity-*deleting* swap would then promote and re-contaminate
  the baseline. Paired significance is a net win ONLY alongside item 10. Both are operator calls
  (`evaluate.py:158`). I filed+specced them but deliberately did not ship.
- **Item 9 (NEW) — deploy the new curriculum to the running collectors** (`43bced2`). Committed
  but NOT live: collectors run the baked `ava/cpu:latest` (grep-confirmed 0 of the 3 new
  sources). Needs a local image rebuild in a **memory-ample window** (a `docker build` at
  <~2 GB free risks the VM). ⚠ NUMBERING: this NEW item 9 ≠ the OLD "item 9 WITHDRAWN" noted
  further down — that referred to a since-superseded item.

### Nothing else autonomous remains high-value
The memory-safe review surface is largely exhausted (≈11 functions verified correct across
factory/graphify/ava-skills/harness/scout-cli in addition to the 3 fixes). Remaining work is
git reconcile (#0), the coupled gates (10+11), and the memory-gated deploy (#9) — all yours.

---

The living source of truth is [`TODOS.md`](./TODOS.md) — read its **"YOUR DECISION QUEUE"**
section (search that header) and the **§5.3.R98–R100** entries at the top of the R-log. This
file is just the entry point; `TODOS.md` has the detail and stays current.

## Execute the queue TOP-DOWN — each item is a precondition for the ones below it

1. **Item 00 — reconcile git FIRST.** Local `main` is ahead of `origin/main` (unpushed
   session work) and behind by 2 (a parallel session's ruff reformat that **pruned `typing`
   imports this session's new code still uses**). A naive merge → `NameError: Dict is not
   defined` at import. **Verified procedure (§5.3.R99):**
   ```bash
   git merge origin/main            # resolve conflicts as "keep my logic, take their formatting"
   python -m ruff check --fix ; python -m ruff format   # normalises both sides; removes the NameError
   # then run the suites (see Environment) — a green suite proves the reconciliation held
   ```
2. **Item 0 / 5 — RE-SEED before restarting the daemon**, or the loop rejects every candidate
   against an unreachable baseline (the live baseline is a measured regression, §5.3.R93):
   ```bash
   python -m dottie.research calibrate-baseline --overwrite   # installs ≈5.737, ~6 min
   ```
3. **Item 0 — restart** (only after re-seed):
   ```powershell
   wsl --shutdown ; .\scripts\restart_research.ps1
   ```
4. **Items 1–8** unblock from there, in order. **Item 9 is WITHDRAWN** (was a false alarm —
   `apps/dottie` is green once `AVA_FACTORY_ROOT` is set).

## Environment

Tests **and** the trainer need:
```
AVA_FACTORY_ROOT=C:\Users\jcdav\workspace\ava-agi-factory-v6-4
```
The daemon sets it from the gitignored `apps/dottie/research_orchestration/research_env.local.ps1`.
Without it, `apps/dottie` reports ~36 failures that look like a broken repo and are not
(§5.3.R87). Run each suite from its own root; `apps/dottie` uses `apps/dottie/.venv`.

## Discipline (enforced conventions — TODOS ops §9.3–9.6)

- **`git fetch` before your FIRST commit** — parallel sessions push here (this is exactly how
  the divergence above happened).
- **`python scripts/check_todos_timestamps.py`** before committing any `TODOS.md` edit — it
  rejects fabricated clock times.
- **Read [`scripts/README.md`](./scripts/README.md)** before writing a new script — the
  operational tooling (restart/recovery, run-log reader, mutation audit, and the per-promotion
  `ab_nano.py` verifier) is indexed there.
- Never write a clock time that did not come from `date` or `git log` in the same tick.

## Status note

This file and `TODOS.md` are **local-only until item 00 is done** — `origin/main` does not yet
contain this session's work. After the git reconciliation pushes, this handoff becomes visible
to anyone with the repo. Until then, "pick up" means on this machine.
