# TODOS — the road to the Agentic Assistant platform at arxiviq.com

> Unified execution roadmap, reconciled 2026-07-19. One rule inherited from everything
> that worked so far: **every number is measured, every gate is real, every step names
> its acceptance criterion.** Work top to bottom; parallelize only where marked ∥.
> Solo personal project, no connection to employer, built with public/free-tier only.

## Goal state (updated by the 3-min loop, late night 2026-07-19)

Every unblocked item is DONE (loop tasks #8-#16 cleared overnight). Critical path
remains time-gated: tool_final.pt (trainer ~step 250+, ETA morning) -> eval gate 1.2
(loop-armed: task #17 fires when the monitor does) -> chat branch -> fleet rebuild 2.1
-> DOTTIE_POLICY=factory flip -> arxiviq chat on Dottie's brain.

Overnight loop outcomes: ideation self-correction retry + collision-proof dumps;
implementation prompt no longer invites phantom imports; MegaWika ON-BOX verified
(split was wrong in the staged config — caught by doctrine) with adapter ready for the
2.1 rebuild; FactoryPolicy live-probed; SOTA promotion bundles wired into the runner;
arxiviq live-status gist feed replacing the frozen legacy fallback; assistant brain
badge live. MEASURED: research loop completed its first THREE full hill-climb chains
(train->measure->honest reject at 6.264/5.747/+1 vs baseline 5.620) — conversion went
0/7 pre-fix to 2/5+ post-fix; the machinery is proven, now it's a search problem.

## Standing state (context for every step below)

- `dottie-factory` fleet (13 containers) runs ONLY from `apps/ava-factory`; trainer is
  mid **mini tool-branch (T9.3)**, ~1,144 steps total, bind-mounted code, monitor armed.
- The three-way fork (retired `ava-agi` / workspace `ava-agi-factory-v6-4` / monorepo)
  is **reconciled into the monorepo** (`4aabd3d`, `75ef9a6`): 431 factory tests pass.
  Containers still run pre-reconciliation IMAGE code until step 2.1 rebuilds them.
- Research loop: 4 scheduled tasks, qwen3:8b think=false, baseline `factory_lm_loss
  5.61982`; ideation refills 00:00 nightly.
- Agent OS: J-Space state store (`skills/state_store.py`), Hermes/OpenClaw profiles,
  forge self-evolution loop all live-verified; scout has `reviewgraph`.

---

## 0 — POWER DELIVERY, not drivers (root-caused 2026-07-19 23:56 by the loop)

REBOOT DONE (23:36) — fleet auto-healed 14/14, trainer auto-resumed from
/ckpt/tool/step_1035.pt (crash-resume verified in production). But the reboot did
NOT fix the clocks: SM still pinned at 780 MHz. MEASURED root cause via
`nvidia-smi -q -d PERFORMANCE,POWER`: **Current Power Limit 45 W** (hw max 175 W),
SW Power Cap + SW Thermal Slowdown active since boot. Battery at **13% on AC** —
the box ran down and the system is throttling the GPU while the battery recovers
(or the charger is underpowered). The whole evening's "degraded WSL GPU stack"
(780 MHz, 3-5x slow steps, likely the CUBLAS flakes too) was power delivery.

**PHYSICAL ACTION (user)**: confirm the OEM high-wattage adapter is the one plugged
in (not a USB-C/travel charger); let the battery charge. Verify recovery with
`nvidia-smi --query-gpu=power.limit,clocks.sm --format=csv` → expect ~175 W / >2 GHz.

Meanwhile training still advances at ~38 s/step under the cap: step 1050/1,144 at
23:55, ~94 steps left → tool_final.pt ETA ~01:00–01:30 even without the fix.
Then §1 fires automatically (#17 armed on the monitor).

## 1 — Close the T9.3 gate (blocking everything downstream)

1.1 [~] **Wait for `tool_final.pt`** (step 1110/1,144 at 00:35 2026-07-20; ~20 min out).
    NOTE: the ORIGINAL armed monitor + task #17 did NOT survive the session's machine
    move (task list empty, verified 00:40) — a fresh watch was re-armed from the new
    session (fires on tool_final.pt, container gone, or NaN/CUBLAS signatures). The
    eval-gate harness was smoke-checked in-container (imports + argparse OK).
    - 1.1.a If the monitor reports crash/NaN instead: `docker logs dottie-factory-trainer-1`,
      diagnose, restart run — do NOT advance to 1.2 without a finished checkpoint.
1.2 **Run the eval gate against the checkpoint** (real harness, no shortcuts):
    - **COMMAND CORRECTED 2026-07-20 00:55 (pre-fire)**: `eval_branch_harness.py` is
      MOCK/BLUEPRINT ONLY — its own docstring says every number is fabricated and
      `--mode real` refuses to run. Do NOT gate on it. `evals.run_harness` is real but
      covers base/chat probes only — no tool-routing metric exists yet anywhere.
    - 1.2.a [x] **`evals/tool_gate.py` SHIPPED + smoke-verified in-container** (CPU,
      base-vs-base, exit-code semantics 0/1/3). Read-only manifest access, val-split
      windows, planner-argmax + held-out CE per task_type, JSON verdict to /reports.
    - 1.2.a' **MEASURED CORPUS FINDING (2026-07-20 01:10, reframes T9.3)**: the packed
      corpus contains ZERO tool_selection-labeled docs — val census: 0 docs; full
      metrics history: 0 tool batches ever trained (943 deliberate / 421 automatic /
      81 temporal / 3 safety). The "tool branch" trained on the generic mix; only its
      router_bias prior + freeze pattern differ from base. Tool_use L2/L3 sources
      arrive with the 2.1 rebuild — AFTER this run. Therefore:
      * When tool_final lands: run `python -m evals.tool_gate` (GPU, defaults) →
        honest NONREGRESSION-ONLY verdict (general CE ≤2% + routing sanity).
      * The FULL tool gate (capability) is gated on 2.1 + tool-labeled val data, then
        continued branch training (or re-fork) on real tool batches.
      * DECISION for human: T9.4 chat branch has the same question — check the chat
        mix's task labels exist in the packed corpus BEFORE burning 90 min of GPU.
    - 1.2.b Compare tool-branch vs `base_final.pt` on: tool_selection routing accuracy
      (router argmax → planner on tool prompts), held-out LM loss on tool_use mix,
      frontier-rubric tool categories.
    - 1.2.c Record verdict in `apps/ava-factory/reports/REPORT_REAL.md` (committed) with
      the raw numbers. Acceptance: tool branch beats base on tool metrics WITHOUT
      >2% LM regression on the general mix.
1.3 **CHAT-MIX LABEL CHECK DONE (2026-07-20 01:20 — the 1.2.a' decision item)**:
    T9.4 is better positioned than T9.3 was. p5 train PACKED census: deliberate
    1,065M + temporal 174M + automatic 29M + **safety 22M** — the chat mix's labels
    exist in train (a 50M-token run at safety 0.20 needs ~10M; 22M covers it).
    CAVEAT: val synth_safety shards are MISLABELED (all 1,139 docs `automatic`,
    packed under an older config) → the chat gate can measure general CE + routing
    but NOT safety-specific metrics until val safety is repacked (2.1+). Launching
    T9.4 on this corpus is defensible; gate it like the tool branch (honest
    nonregression + routing) and re-gate on capability post-2.1.

    **If gate passes → chat branch (T9.4)**: same overlay pattern,
    `docker compose -f docker-compose.yml -f docker-compose.tool-fork.yml run --rm trainer \
     python -m dottie.train --preset mini --branch chat --init /ckpt/base_final.pt --run /ckpt/chat`
    (50M tokens ≈ 90 min). Same gate discipline (1.2) for chat metrics.
1.4 **GATE RAN 2026-07-20 01:29 — VERDICT: FAIL (REGRESSED)**. tool_final vs
    base_final on held-out val (GPU, real): general CE **+75.1%** (bound ≤2%);
    deliberate +142%, automatic +46%, temporal −28%; tool checks UNMEASURED (no
    tool-labeled data exists). Full numbers: reports/REPORT_REAL.md + tool_gate.json.
    Failure mode: catastrophic forgetting/overfit to the p3 slice (train lm ~0.15).
    **RECOMMENDATION (needs human sign-off): do NOT knob-and-rerun** — the corpus
    cannot support the branch's purpose (zero tool data); do NOT launch T9.4 on this
    recipe either. Instead: §2.1 rebuild (window is OPEN, trainer exited clean) →
    collect real tool_use data → re-fork with a gentler recipe (lower LR / shorter run
    / replay mix of earlier phases to prevent forgetting). Original knob-rerun
    guidance retired: two failures = rethink curriculum; this failure is structural.

## 2 — Redeploy the fleet on reconciled code (after 1.1, before long collector runs)

2.1 **Rebuild + restart with the reconciled tree** (new datagen union + post-mini sources):
    - 2.1.a [x] Images rebuilt 2026-07-20 01:35 (ava/cpu + ava/gpu, cache-fast).
    - 2.1.b [x] 01:38: collector×4, curator×6, janitor, server recreated on new images.
      **Trainer DELIBERATELY left down** — gate failed; no new run without human
      sign-off (also avoids an exit-0 restart loop on the finished branch command).
    - 2.1.c [x] VERIFIED 01:50: **13/13 healthy**; collector_boot logs **"sources": 30**
      (new registry live — also closes §8's post-rebuild check); `/pipeline/status`
      responds (mode reads stale "training" off the dead trainer's demand.json — decays).
      CAVEAT: collectors correctly PAUSED ("packed runway 3.22B >= max 3.00B") so new
      source keys won't EMIT until a trainer drains runway — 2.2 is blocked on the
      human decision about the next run, not on the rebuild.
2.2 **Verify mixture flow end-to-end**: after 1h, `manifest` tokens_ready per phase
    rises; curator rejects stay <20%; no `unknown generator` errors anywhere.
2.3 **Retire the old checkouts** — AUDITED 2026-07-19 late: workspace clean; retired ava-agi's 97 dirty files all captured by the reconciliation (0 changed since); both safe to rename (they are now strictly historical):
    - 2.3.a `git -C C:\Users\jcdav\ava-agi status` → confirm nothing uncommitted worth saving.
    - 2.3.b Rename both dirs to `*-RETIRED-20260719` (do not delete yet); update
      `AVA_FACTORY_ROOT` in `research_env.local.ps1` to the MONOREPO factory path and
      re-register scheduler tasks; re-run `calibrate-baseline` if the packed corpus moves.
    - 2.3.c After 2 quiet weeks: delete.

## 3 — Promote mini to be Dottie's brain (the "assistant runs on OUR model" milestone)

3.1 **Serve the gated checkpoint**: point `server` service `AVA_CKPT` at the winning
    branch ckpt; `AVA_SKIP_ENGINE_BOOT=0` window (stop trainer first — 12 GB card).
3.2 [x] **Wire dottie engine -> served model** (FactoryPolicy over :8000/chat; DOTTIE_POLICY=factory; live probe green — flip after the gate): `apps/dottie` policy currently defaults to
    Ollama; add a `DOTTIE_POLICY=factory` path that hits `:8000/generate` with the same
    honest-refusal semantics. Acceptance: `apps/dottie` test suite passes with the
    factory policy env set + one real conversation transcript saved to task_logs.
3.3 **A/B against qwen3:8b** on 20 fixed assistant prompts (tool selection, math,
    safety refusal); record per-prompt win/loss in `reports/` — promote only on ≥60% wins
    for tool tasks. Honest outcome if it loses: keep qwen3:8b, file gaps into §5.
3.4 **arxiviq assistant surface**: enable the server's CORS block for arxiviq.com
    (already reconciled in `server.py`), connect the site chat to `/generate`, stream
    tokens, log traces into `task_logs` (P5 anneal feedstock — closes the flywheel).

## 4 — Scale to base1b (only after 3.x proves mini is useful)

4.1 **Grow-init from the promoted mini** (machinery shipped in `89713ff`):
    - 4.1.a `python -m dottie.grow --src /ckpt/<winner>.pt --src-preset mini
      --dst-preset base1b --out /ckpt/base1b/grown_init.pt --validate`
    - 4.1.b Acceptance: `grown_loss` well below `fresh_dst_loss` in the validation
      block; manifest shows zero unexpected `dst_only` tensors.
4.2 **Memory feasibility on the 4080 — measure, don't argue**: `--max-steps 20` smoke
    with `optimizer.name: adamw8bit` (bitsandbytes is already wired in train.py),
    gradient_checkpointing on, micro-batch 1. Record torch peak alloc. If it spills
    >1 GB into sysmem → 4.4 (cloud) is the answer, full stop.
4.3 **Distillation pre-pass (optional, 2× sample efficiency)**: precompute top-8
    teacher logits (Qwen2.5-7B, Apache-2.0) over the M1 shard set (~32 GB disk);
    add a KL term gated by `training.distill:` config. Tokenizer decision first:
    adopting the teacher's tokenizer is the load-bearing choice — spec it before code.
4.4 **M1 milestone (2B tokens)**: local ≈ 2+ weeks 24/7 vs ~1-2 days on one rented
    A100-80GB. Gate at M1 per `configs/base1b.yaml milestones:` — "probes: arithmetic/
    logic clearly above mini" — before ANY further spend.

## 5 — Research loop: keep hill-climbing the architecture (∥ continuous)

5.1 **Tonight's cycle**: ideation refills at 00:00 with qwen3:8b; hourly ticks chew it.
    Morning check: `python -m dottie.research status` — expect ≥3 new experiments tried.
5.2 **Raise the conversion rate** (currently 0 of 7 candidates pass validation):
    - 5.2.a [x] Add `--max-retries 5` (scheduler re-registered 2026-07-19 evening) for the implement worker on the scheduler (cheap now
      that transport bugs are gone — failures are content-level).
    - 5.2.b [~] Nightly window: MECHANISM shipped in research_worker.ps1 (DOTTIE_OLLAMA_MODEL_NIGHT); do NOT enable until the tool run frees the GPU — when the trainer is idle (post-tool_final, pre-next-run),
      let the scheduler use qwen3:14b (`DOTTIE_OLLAMA_MODEL_NIGHT` env in the wrapper,
      22:00–06:00) — 14b stalls only under GPU contention.
    - 5.2.c [ ] (re-scoped) Feed richer context into corrections — research candidates are single modules, so reviewgraph adds little; instead feed the CANDIDATE's own prior-attempt diff. Original idea: output into the correction prompt (the compact
      dependent-signature block) — the corrector currently sees only the traceback.
5.3 [x] **Close the loop into the factory** (sota -> promotion bundle: candidate.py + evidence + ab_nano.py, runner-automatic, human-gated): when an experiment reaches `sota`, generate a
    `deltanet_layers`-style patch PR against `model_1b.py` + a nano A/B run script;
    human-review gate before it touches mini/base1b presets.
5.4 [x] **Report** (sparkline shipped 2026-07-20 00:20 — sota_history now carries
    metric_name/baseline_value from each verdict; site draws seed→sota series for the
    CURRENT metric regime only, retired-regime points counted out loud, not plotted):
    trigger was met tonight — **first real SOTA landed**: MLBR (`23bb41375804`)
    factory_lm_loss 5.61982→5.60506, baseline ratcheted; 2 promotion bundles built
    automatically under `data/research/promotions/` — **HUMAN REVIEW PENDING** (note:
    `bc3dbb74bead` is from the retired proxy_loss regime; review MLBR first).

## 6 — Agent OS hardening (∥ with 1–5)

6.1 [x] **Hermes auto-forge** (successful routines register parseable plugin drafts + human-gated forge_proposal commands): today `after_run` registers a routine sketch into
    skills_library; next: template that sketch into a real `forge new/edit` invocation
    behind `--refine` (human-confirmed), reusing the loop test's contract template.
6.2 **OpenClaw channels**: give `session_context` channels real meaning — `cli`,
    `arxiviq`, `research` — and make the dottie engine read/write the same store
    (`DOTTIE_STATE_DB` shared). Acceptance: a task started via scout is visible in the
    arxiviq assistant's context and vice versa.
6.3 **reviewgraph into the workflow**: pre-commit hook (or `scout system audit` step)
    that runs `reviewgraph blast --diff HEAD` and blocks on new high-fan-in touches
    without tests. Wire `context` into /code-review usage docs.
6.4 [x] **Skill auto-docs** (forge new scaffolds SKILL.md; forge rm cleans it; loop test asserts it): `forge new` should scaffold SKILL.md (frontmatter:
    j_space_target, triggers) so `skill install` works without the manual step the
    loop test had to do.
6.5 [x] **State-store telemetry cron** (watermarked export, hourly hidden task live on this box): hourly `export_telemetry` append into
    `reports/dottie_telemetry.jsonl` (gitignored) so agent activity reaches the
    Control Plane dashboards alongside factory telemetry.

## 7 — arxiviq.com platform polish

7.1 [x] LIVE-STATUS FIXED: site was on the frozen legacy fallback (hygiene keeps repo telemetry uncommitted) — hourly gist feed published from the box, app.js reads gist-first (df6796c). Original item: Control Plane fetches `dottie/main/apps/ava-factory/` — verify all dashboards
    render post-reconciliation (dashboard_html/ecosystem_html/evals_html were merged).
7.2 Assistant tab: 3.4's chat + a visible "which brain" indicator (factory ckpt vs
    Ollama fallback) — honesty in the UI too.
7.3 [x] Research tab: 5.4 (sparkline, shipped). Factory tab: SHIPPED 2026-07-20 —
    telemetry tiles now read the gist payload's v2 `.pipeline` block (tok/s from
    trainer.last, phase+run % from watch.*_progress, mode chip with honest ·stale
    flag); legacy v1 and baked-snapshot fallbacks retained.
7.4 [x] "Last seen" badge shipped 2026-07-20 (the preferred honest option): the source
    badge now reads the gist feed's published_utc — "live · box seen X ago" when <2h,
    "stale · box last seen X ago" beyond (2 missed hourly beats = asleep), old
    behavior when the feed lacks the field. "Live" now means the BOX is live, not
    that a CDN fetch succeeded.

## 8 — Known issues backlog (honest ledger, none import-breaking)

- [x] `test_audit_fixes`: 10 passed — judge layer 3-way merged (workspace .label audit-fixes + monorepo rubric evolution), logic pipeline ported blueprint-judge failures (MetaMuseJudge.label, judge source
  literals) — the judge layer needs its own reconciliation pass vs workspace.
- [x] `test_cpu_pilot_manifest`: fixed — runs/-suffix resolution + honest skip (10 passed/1 skip). Was: 3 × — environmental: expect `runs/cpu_pilot` artifacts;
  regenerate via `scripts/cpu_pilot_e2e.py` or mark skip-if-absent.
- [x] `test_janitor` reclaim count: was the ava/dottie double-import split brain — fixed by the ava.* meta-path alias finder (with 3 other split-brain failures).
- [x] `test_server_endpoints`: retired lineage moved the file report to /report/offline; updated test file ported (18 passed).
- 966 ruff findings in ported legacy code (CI excludes ava-factory; burn down
  opportunistically, never in bulk-reformat commits).
- [x] scout-cli python3-stub tests: swept to sys.executable (25 failures -> 10; survivors below).
- [x] scout-cli Windows portability: WNOHANG guarded, CLI stdout UTF-8, perms asserts POSIX-only — 129/130 green.
- [x] test_mcp_serve stdio scenario: was NOT environmental — real Windows bug, root-caused
  2026-07-20 by elimination (stdin-pipe, minimal-env, no-console, held-lock all refuted;
  live-server child-never-ran vs DEVNULL-0.11s was the discriminator): `_dispatch`'s
  subprocess inherited the MCP stdio transport pipe (overlapped Proactor pipe) as stdin
  and child Python hung in runtime init. Fix: `stdin=subprocess.DEVNULL`. 90s-timeout →
  passes in 2.25s.
- [ ] test_api.py 4 env failures on this box (pre-existing, verified vs HEAD 2026-07-20):
  echo task / task counts / ollama honest-fail / flywheel gate all hit
  `DottieResolutionError: ava-...` — AVA_FACTORY_ROOT resolution, not code. Fix the env
  (research_env.local.ps1 → monorepo factory path, §2.3.b) then re-run.
- [ ] 1 × `test_logic_prover` jsonl (ava-skills, pre-existing).
- [x] `test_flow`: same split brain (patched free_gb on the wrong module copy); alias finder fixed it.

### New items (added 2026-07-19 evening)

- [x] §5: `DOTTIE_OLLAMA_MODEL_NIGHT=qwen3:14b` enabled 2026-07-20 01:50 (tool run done,
  trainer parked → contention gone; NUM_GPU stays 0 per GPU doctrine). Next research
  tick in the 22-06 window picks it up; watch the first 14b ideation for stalls.
- [x] §5: ideation raw-dumps reviewed 2026-07-20 — new shape found (mid-word-corrupted
  key `"hypo,thesis_name"` killed a whole 3-idea batch) and fixed with canonical-skeleton
  key repair in parse_hypotheses (fill-only, deterministic). Swept all 9 accumulated
  dumps: 9/9 now parse (27/27 research tests green).
- [~] Curriculum (landed a3abac0/f7d3a68 by parallel forks): megawika staged at
  weight 0 — needs on-box schema check + adapter before enabling; Mind2Web staged —
  needs an action-trace adapter; per-event cross-attestation filter is future curator work.
- [ ] §7: after fleet rebuild, verify the Control Plane source tables show the 30-source
  registry and the new telemetry stream renders.

### Weekly ops sweep (2026-07-20 00:45 — measured, safe actions taken)

- Done: dangling-image prune reclaimed **6.4 GB**; `git gc` run. Disk: 139 GB free.
- [ ] **Janitor does NOT rotate branch-run checkpoints**: /ckpt/tool = **51 GB** (~29 ×
  1.76 GB, every step file 50→1110 present; the 15-step crash cadence multiplied this).
  After tool_final lands + eval gate passes: keep tool_final + last 2 steps, delete the
  rest (~45 GB back), then extend the janitor's rotation to /ckpt/<branch>/ dirs.
- [ ] Deferred deliberately: build-cache prune (36.5 GB — it speeds the §2.1 rebuild;
  prune AFTER 2.1) and `docker image prune -a` (23 GB more — old images are rollback
  insurance until the rebuilt fleet proves out; prune after 2.2 verification).

## 9 — Ops discipline (standing)

9.1 Monitors: keep the trainer monitor armed each run; add one for collector
    starvation (`tokens_ready` flat >6h → notify).
9.2 Weekly: `git gc` the monorepo, prune Docker images (`docker system df` first),
    check `ava_ckpt` volume growth vs janitor rotation.
9.3 Every session: `git pull` before committing (parallel Claude sessions are active);
    factory suite before any factory push; never leave conflict markers on disk in
    bind-mounted trees (the trainer restart-imports them).
9.4 Lane splits for parallel sessions: two agents racing on the same file
    (`adapters.py`/`sources.yaml`, observed 2026-07-19) resolved cleanly only by
    luck of additive edits — when spawning parallel work, assign disjoint file
    lanes explicitly (curriculum registry vs adapters vs tests), and the second
    lane pulls before touching anything shared.
