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

## 1 — Close the T9.3 gate (tonight, blocking everything downstream)

1.1 [~] **Wait for `tool_final.pt`** (in flight — step ~370/1,144 at 19:30) (monitor fires; ETA ~8h from 15:20 start).
    - 1.1.a If the monitor reports crash/NaN instead: `docker logs dottie-factory-trainer-1`,
      diagnose, restart run — do NOT advance to 1.2 without a finished checkpoint.
1.2 **Run the eval gate against the checkpoint** (real harness, no shortcuts):
    - 1.2.a `cd apps/ava-factory && python eval_branch_harness.py --ckpt /ckpt/tool/tool_final.pt`
      (inside the GPU image: `docker compose exec trainer python eval_branch_harness.py ...`,
      or `server` service with `AVA_SKIP_ENGINE_BOOT=1` off-hours).
    - 1.2.b Compare tool-branch vs `base_final.pt` on: tool_selection routing accuracy
      (router argmax → planner on tool prompts), held-out LM loss on tool_use mix,
      frontier-rubric tool categories.
    - 1.2.c Record verdict in `apps/ava-factory/reports/REPORT_REAL.md` (committed) with
      the raw numbers. Acceptance: tool branch beats base on tool metrics WITHOUT
      >2% LM regression on the general mix.
1.3 **If gate passes → chat branch (T9.4)**: same overlay pattern,
    `docker compose -f docker-compose.yml -f docker-compose.tool-fork.yml run --rm trainer \
     python -m dottie.train --preset mini --branch chat --init /ckpt/base_final.pt --run /ckpt/chat`
    (50M tokens ≈ 90 min). Same gate discipline (1.2) for chat metrics.
1.4 **If gate fails**: file the failure mode in `TODOS.md` §8, adjust the branch spec
    (mix weights / router_bias in `configs/mini.yaml branches:`), rerun once. Two
    failures = stop and rethink the curriculum, not the knobs.

## 2 — Redeploy the fleet on reconciled code (after 1.1, before long collector runs)

2.1 **Rebuild + restart with the reconciled tree** (new datagen union + post-mini sources):
    - 2.1.a `docker compose -f docker-compose.yml -f docker-compose.tool-fork.yml build`
    - 2.1.b `docker compose ... up -d` **only when the trainer is between runs** — never
      yank a mid-run trainer.
    - 2.1.c Acceptance: 14/14 healthy 10 min later; `/pipeline/status` mode sane;
      collector logs show the NEW source keys (synpro, tool_use L2/L3, db/compress traces).
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
5.4 **Report**: the arxiviq Research tab already renders `/research/status`; add the
    SOTA-vs-baseline sparkline once ≥2 sota points exist.

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
7.3 Research tab: 5.4. Factory tab: live tok/s + phase progress from `/pipeline/status`.
7.4 Uptime: the box sleeps → arxiviq shows stale. Either Task Scheduler wake or an
    honest "last seen" badge (prefer the badge; free-tier doctrine).

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
- [ ] test_mcp_serve stdio scenario: 90s deadline exceeded on this box (environmental; retry when idle or raise deadline).
- [ ] 1 × `test_logic_prover` jsonl (ava-skills, pre-existing).
- [x] `test_flow`: same split brain (patched free_gb on the wrong module copy); alias finder fixed it.

### New items (added 2026-07-19 evening)

- [ ] §5: enable `DOTTIE_OLLAMA_MODEL_NIGHT=qwen3:14b` in research_env.local.ps1 the
  morning after tool_final.pt lands (GPU contention gone at night thereafter).
- [ ] §5: ideation raw-dumps now land in logs/ideation_raw_*.txt on parse failure —
  review the first one that appears and extend parse_hypotheses if a new shape shows.
- [~] Curriculum (landed a3abac0/f7d3a68 by parallel forks): megawika staged at
  weight 0 — needs on-box schema check + adapter before enabling; Mind2Web staged —
  needs an action-trace adapter; per-event cross-attestation filter is future curator work.
- [ ] §7: after fleet rebuild, verify the Control Plane source tables show the 30-source
  registry and the new telemetry stream renders.

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
