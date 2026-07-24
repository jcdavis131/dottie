# BLUEHENRE / Dottie — agent handoff (2026-07-24)

**Paste-able brief for any agent continuing this work. Everything below is live and verified.**

## LATEST (2026-07-24, later) — DEPLOYED + vector cards + Universal MTNN trained

- **Dottie site DEPLOYED to www.bhenre.com** (operator: "deploy") — live-verified
  200s, Hub + honest APIs + real telemetry (~7 min fresh from the box). Commit 2192c57.
- **OAPEN scaled up** (operator: "scale up OAPEN") — 19 unique CC-BY books (query
  starvation + content-dup fixes); full corpus gitignored, bounded sample committed.
  Commit 682ff88.
- **Vector MTNN model cards + Universal MTNN TRAINED** (operator auto-mode: "vector
  model cards for each MTNN and start training the universal MTNN"). Commit 7332bd7.
  - 4 model cards, each honestly classified from its COMMITTED eval: gridiron REAL
    (weekly Spearman 0.6899), hoops REAL (held-out retrieval test top5 0.3633),
    equities PLACEHOLDER (sector purity 0.1742 — 2200/4941 placeholder rows,
    contamination carried), Universal MTNN REAL.
  - **Universal MTNN trained**: `vector-unified/pipeline/train_unified.py --epochs 60`
    (Stage 1), 162s on the free RTX 4080 → `unified_best.pt` (in vector-unified repo).
    Eval: 20,721 players in a shared 64-dim space across hoops/gridiron/pitch; G1
    non-inferiority PASS, G3 silhouette 0.7095 PASS, G2 sport-invariance DEFERRED
    (needs no-GRL baseline), collapse PASS.
  - Hub registry now **3 datasets + 5 models + 10 research**. Suite 100, --check fresh.
- **AWAITING OPERATOR:** redeploy to make the 5-model Hub live (the deployed site
  still shows the pre-vector-card registry); further MTNN stages (--finetune/--market/
  --cultural-text); the G2 no-GRL baseline; the larger OAPEN pull (OAI-PMH/DOAB).

## SESSION COMPLETE STATE (2026-07-24) — Dottie site built, tested, CI-enforced, DEPLOY-READY

The whole `/goal` arc is committed and green. Full detail in the dated blocks below.

**Built + verified this session (all committed, NOT deployed):**
- **Vision realigned + de-gamed** — SPEC of record (three faces), READMEs, TODO;
  the open-world-game metaphor (NPC/campus/persona, `/api/npc-chat`) removed.
- **Hub pillar COMPLETE** — a HuggingFace-style registry of the org's own
  **datasets (3) + models (1) + research (10)**, one static `hub_registry.json`
  rebuilt by a read-only exporter, each card provenance-badged
  (REAL/HONEST-SYNTHETIC/PLACEHOLDER/UNCLASSIFIED). The ava-mini model card shows
  the honest **2,268** ppl and NAMES the retracted 275.95/4103 (never dropped).
  Rendered on org console AND mobile.
- **Guide pillar (buildable half)** — the "what to do next" digest (`nextActions`)
  on org + mobile. ReAct chat trace = Phase 4 (engine-dependent).
- **OAPEN data pipeline** — `pull_oapen_books.py`, `dc.rights`-gated (CC-BY/SA/CC0
  only; ND + NC + unlicensed excluded), 10 CC-BY books, HF-standard card = REAL.
  Adversarially reviewed; a license-gate false-positive (multi-value `dc.rights`)
  was found + FIXED.
- **Deploy safety** — `build_hub_registry.mjs --check` fails if the committed
  registry is stale (a stale registry = rendered ≠ source = a provenance
  violation); a new CI job `bluehenre-checks` enforces the two suites + `--check`
  + JS syntax on every push. Server hardened (generic 500, no `e.message` leak;
  path traversal verified safe).

**Pre-deploy verification (all green now):**
```
node apps/bluehenre/public/js/twin.contract.test.mjs        # 100 checks
node apps/bluehenre/scripts/build_hub_registry.test.mjs     # 9 checks
node apps/bluehenre/scripts/build_hub_registry.mjs --check  # registry fresh
```
**Deploy (operator):** `cd apps/bluehenre && vercel deploy --prod --yes` →
`vercel alias set <url> www.bhenre.com` → update `data/last_good_deployment.txt`.
Deploying also resolves the one standing caveat — every UI slice is verified at
logic/class/syntax level, but pixels are unconfirmed (Chrome extension was down
all session).

**Queued / externally-blocked (nothing else is autonomously buildable):**
vector MTNN model cards (cross-repo eval sourcing — do WITH operator, those repos
had fabrications cleaned earlier); OAPEN scale-up (`--full` + the frozen
`sources.yaml` entry); Phase 3 Monitor runtrack bridge (box-side); Guide ReAct
trace (engine field). Two latent exporter bugs intentionally NOT fixed
(multi-config `dataset_info`, quoted/glob `path:`) — no card triggers them.

## CURRENT STATE (2026-07-24): VISION RE-ALIGNED to the Dottie site (Guide/Hub/Monitor)

- **Operator `/goal` (2026-07-24):** the Dottie site = **a Manus/OpenClaw/Hermes
  agentic assistant (GUIDE) + a HuggingFace datasets/models/research hub (HUB) +
  a Weights&Biases real-time dev monitor (MONITOR)** — one product, three faces,
  differentiated by **provenance-honesty by construction**, built additively on
  the `apps/bluehenre` console. Directive: "UPDATE README, SPEC, TODO … Remove all
  old bits about the open-world game."
- **DONE this session (docs + de-game, committed; NOT deployed):**
  - `apps/bluehenre/SPEC.md` rewritten as the single **spec of record** (three
    faces); the transitional `SPEC_dottie_site.md` was consolidated in and removed.
  - READMEs (root + bluehenre) + root `SPEC.md` realigned to the vision; stale
    `arxiviq.com` console pointers → www.bhenre.com.
  - `tasks/todo.md` created (clean board); `tasks/dottie_site_plan.md` is the
    phased plan (first slice = **Hub Artifact Registry**, substrate already exists).
  - **Open-world-game framing removed from the console code:** the campus/NPC/
    persona metaphor is gone — `fleetRole`/event maps now use functional team
    labels (training/data/curation/ops/serving/research/services) instead of
    campus buildings (labs/servers/archives/finance/hall/proving/gardens); the
    dead game-character fields `persona`/`action` deleted; `/api/npc-chat` →
    `/api/assistant-chat` across `server.mjs`, the Vercel fn (`api/npc-chat.mjs`
    → `api/assistant-chat.mjs`), and both front-ends (drops the `npc`/`dept`
    body params). Contract suite **76/76 green**; all edited JS `node --check`
    clean. **A deploy is pending the operator** (public surface = gated step).
- **Pillars BUILT this session (code-complete, NOT deployed — deploy is the
  operator's gated step):**
  - **Hub Artifact Registry (Pillar 2, Phase 1)** — `build_hub_registry.mjs`
    exporter → static `hub_registry.json` (now **3 datasets**) + `parseHubRegistry`
    + "Hub — Datasets" card with provenance badges (REAL/HONEST-SYNTHETIC/
    PLACEHOLDER/UNCLASSIFIED). Commits 4db3053, 0620e45.
  - **Guide "what to do next" digest (Pillar 1, Phase 2)** — `nextActions()` ranks
    real alerts + research queue + fleet health into the assistant card, each with
    a steer command where unambiguous. Commit 9cec67c. (ReAct chat trace = Phase 4,
    engine-dependent.)
  - Contract suite **92 green**. Visual render NOT yet confirmed (Chrome extension
    was disconnected). To ship: `cd apps/bluehenre && vercel deploy --prod --yes`
    → re-alias www.bhenre.com → update `data/last_good_deployment.txt`.
- **External data expansion (operator: "grounded in external validated sources"):**
  - Rejected library.memoryoftheworld.org (verified shadow library → FORBIDDEN in
    the SOP). `external_book_sources.md`.
  - **OAPEN open-access books PILOTED** (operator: "go with DOAB/OAPEN") —
    `apps/dottie/scripts/pull_oapen_books.py` (read-only, `dc.rights`-gated:
    CC-BY/SA/CC0 only; ND + NC + unlicensed excluded). 10 CC-BY scholarly books,
    license-verified + sha256-pinned, HF-standard card = REAL, in the Hub registry.
    Gate excluded 29/39 scanned. Commit 770a137. Next: `--full` + scale + decon +
    the frozen `sources.yaml` entry (operator).
- **Still queued:** Phase 3 Monitor (runtrack readout — analysis found current-run
  monitoring largely covered by existing cards; the runtrack value is persistent
  cross-run history + comparison, best built box-side with provenance guards);
  mobile terminal-view parity for Hub/Guide. See `tasks/todo.md`.

## CURRENT STATE (late evening 07-23): RUN COMPLETE — fleet RESTORED, compact deferred

- **07-24 ~01:46 UTC: fleet RESTORED** at operator's "restore the fleet" directive.
  Docker Desktop relaunched, 14 containers up (trainer stays down — schedule
  complete), :8000 feed live (200), publisher fired clean, console API back to
  `source: local`, www.bhenre.com/org.html 200. Research daemon RAM-blocked
  again (normal — fleet re-consumed the RAM).
- **vhdx compact NOT done** — operator chose to restore rather than run the
  elevated diskpart. vhdx still 363 GB; C: 37 GB (non-critical). The window is
  cheap to re-open: stop fleet + quit Docker Desktop + wsl --shutdown → vhdx
  frees → operator runs `diskpart /s <compact_vhdx.txt>` in an ELEVATED
  terminal (this session is NOT admin — verified — so the diskpart step is
  always the operator's). I did the fleet-teardown cleanly last time; the only
  blocker is the UAC/elevation for diskpart itself.
- GOAT audit follow-through this session: namespace-collision design note
  (4b43d9e), bare-except sweep complete across non-frozen code, dead-dep
  cleanup. GLM-5.2 learnings analysis running (→ tasks/artifacts/glm52_learnings.md).


**Newest first (post-run arc, all committed):**
- **DATA PROVENANCE AUDIT + fixes (2026-07-24, operator directive "garbage in,
  garbage out")** — `tasks/artifacts/provenance_audit_MASTER.md` + 3 pipeline
  reports + `data_provenance_SOP.md` (the standing rule). Verdict: TRAINING data
  is CLEAN (honest-synthetic + real sources, real decontam, sha-pinned tokenizer).
  - **⚠ EVAL NUMBERS CORRECTION**: the held-out ppl bins were NOT disjoint from
    training (build_eval_data.py used SEED=1234 = the collector's epoch-0 docs).
    So the earlier **275.95 / 2341 / 4103 A/B numbers are UNRELIABLE** (tiny 30k
    bins AND contaminated). FIXED (commit 6ba0ac5): held-out now generated from
    HELDOUT_SEED (disjoint). First trustworthy number: **weighted ppl 2,268**
    over 6.36M honest tokens (tool_final@2861; all 6 phases now scorable). For a
    real baseline A/B, re-run step-1487 on the honest bins.
  - **Public fabrications REMOVED + LIVE** (verified 200 + fabrication gone):
    vector-pitch (957e377 — fake LLM/KV dashboard stack), vector-equities
    (23de1dc — Math.random projection table on a finance site + np.random skills
    + hardcoded metrics; redone against CURRENT origin after a stale-checkout
    divergence), vector-hoops (52a1501 — transductive strip relabeled).
  - Scoreboard errored-run laundering fixed (agent-eval fb758dc, local-only repo).
  - **OPERATOR CALLS (not done, deliberately):** rotate the committed HF_TOKEN in
    ava-factory .env (live secret); #7 baseline-provenance gate (evaluate.py code
    defers it to operator); equities needs a committed checkpoint to regen assets
    (KPI card + skills radar still synthetic-flagged); ~66% synthetic curriculum
    mix; stale config labels (frozen path); dead train_1b_deepspeed.py path.
- **GLM-5.2 / Slime unified trajectory schema BUILT** (`apps/dottie/dottie/
  trajectory_schema.py`, commits 734fb1c → d8955f2 → 30168e8). One
  `Trajectory{steps:[Step{state,action,tool_calls,feedback}], outcome}` + ALL
  FOUR rollout adapters (from_codeact_trace, from_validation_history,
  from_repair_rows, from_agent_eval_events) + `to_sft_records` (one
  source-agnostic learning consumer). 15 tests. ADDITIVE — the four live
  emitters are NOT rewired. REMAINING (gated, operator go-ahead): collapse the
  two live exporters (export_repair_transcripts.py + agent-eval
  export_sft_corpus.py) onto to_sft_records — the only invasive piece; and the
  PPO-critic idea is deferred (frozen + GPU-blocked + horizons ≤8 steps). Design:
  tasks/artifacts/glm52_learnings.md.
- **GLM-5.2 analysis** committed (c8be4a2): GRPO at ava-factory/dottie/rl/grpo.py
  has no critic; index-share rejected (width 256); MIT/decoupled = already our
  posture (scout-cli openswap).
- **openswap adapter family SHIPPED** — 10 native offline replacements for paid
  SaaS in scout-cli (prose/harper, uptime, seo, links, smoke, heartbeat, leaks,
  glitch, certmon, runtrack), stdlib-only, zero new deps. Suite 137→**377**.
  Commits 1328268 (1–8), f5b3920 (9–10). Ranked-50 in
  `tasks/artifacts/openswap_rankings.md`. That family is now a QUALITY BAR.
- **Proof-obligation tracking baked into the validator** (a55e99b, Emira/
  LemmaScript pattern): 15 named obligations across the 6 stages; as_feedback
  names the DISCHARGE-NEXT property; ledger history gains per-attempt
  obligations. Inert until the daemon's next restart. Leg-2 verification-trace
  corpus addendum in CURRICULUM_EXPANSION.md.
- **GOAT (Carmack/Bellard) audit done + 6 hygiene commits**: reports in
  `tasks/artifacts/goat_audit_{monorepo,sites}.md`. Fixed: resolver marker
  (3c84164), dead deps/code across scout-cli/ava-skills/ava-open-harness/
  graphify, and ALL bare `except:` in non-frozen code (graphify+scout-cli;
  dottio was already clean). VERIFIED FINDING: the ~36 dottie engine-test
  failures are a two-`dottie`-package namespace collision (`import dottie.rl`
  resolves to the research pkg, real code in apps/ava-factory/dottie/rl), NOT
  an AVA_FACTORY_ROOT problem and NOT a missing file — the real fix is package
  unification. HELD (need operator): pitch/equities public-data fabrications
  (propose-first), bluehenre package.json (Vercel build risk), ava-factory
  requirements prune (container images), big scoped deletions.
- **Long-bin discriminator RESOLVED the Leg-1 init question**: on a fresh 20MB
  bin build, step-1487 beats step-2861 on 5 of 6 bins INCLUDING the p4 long-doc
  bin (125.9 vs 1,398.7) — seq-4096 training bought only a 3.4-ppl p5-anneal
  template fit. **Init Leg-1 from step-1487 (`tool_final_ext1.pt`)** (steer
  6273012; leg1 doc @e3af093). Bins stashed at
  `apps/ava-factory/data/mini/bins_10x_stash/` (the 275.95-comparable set).

- **Training run FINISHED**: exit 0 at step 2861, 2.4997B tokens, final train
  lm 0.060. New `tool_final.pt` written (old baseline preserved as
  `tool_final_ext1.pt`; step-2861 eval report copied to
  `reports/branch_eval_results_final2861.json`).
- **Eval A/B (posted to steer, identical bins):** step1487 **275.95** →
  stable_p4 **2,341** → step2861 **4,103** weighted ppl on p0–p3 bins. The
  p4/p5 extension traded short-ctx ppl for long-seq training the bins can't
  measure (p4/p5 bins "too short"); bin 1 improved during p5 (mix-narrowing,
  not global decay). Probes ~0 everywhere (modus_ponens 10/200 appears at p4).
- **Leg-1 REVISED accordingly** (`tasks/artifacts/leg1_mini_diff.md` @ccd7f77,
  posted to steer): +0.9B into p3, replay shares mandatory in p4/p5, anneal
  doubling reverted, long-seq-bin build is a boot prerequisite, init-ckpt
  choice is the operator's.
- **Research daemon restarted on today's code** (hard multi-seed promotion
  gate + 100%-coverage hints) BUT its implement stage is RAM-BLOCKED: its own
  guard needs ~6.2GB free to load qwen3:8b (system RAM, NUM_GPU=0); WSL holds
  the box at ~0.5–1.2GB. It retries every ~5 min and self-clears when WSL
  frees memory (log: apps/dottie/data/research/logs/run.log, UTF-16).
- **CRITICAL PATH = the vhdx compact window** (operator-ordered, script ready):
  operator quits Docker Desktop → elevated `wsl --shutdown` + `diskpart /s
  C:\Users\jcdav\.claude\jobs\c2138bb7\tmp\compact_vhdx.txt` (~363GB vhdx,
  30–90 min) → freed RAM unblocks the daemon AND the parked hoops/equities
  suite gates → operator says done → relaunch Docker Desktop + 13-container
  fleet (trainer stays down). Consoles/feed go honest-stale during the window.
- **Classifier holds (do not route around):** fleet-wide `docker stop`, a
  steer post embedding system-command instructions, and one pytest variant
  were denied by the auto-mode classifier late 07-23 — those actions wait for
  the operator's presence.
- ✅ Parked gates CLEARED late 07-23 (RAM window): hoops suite green +
  committed (05bd35e — assets/ dirt in that repo is the site's own daily
  refresh, deliberately uncommitted); equities suite green + contamination
  annotation committed (f36f7de). Hill-climb integration is 100% done.
- Self-healing alias guard live (ee59dfc): frontend-project auto-deploys were
  stealing www.bhenre.com (happened 07-23); the 10-min publisher now probes
  /org.html and re-aliases from the pin file
  apps/bluehenre/data/last_good_deployment.txt (update it on every deploy).

## What landed 2026-07-23 (hill-climb workflow, 22 agents + KG task — all committed)

- **Promotion gate (P0), commit 51a923e:** within-run SEM can NEVER promote;
  ab_nano paired-seed evidence demanded at promotion (subprocess runner,
  refusal on loss/missing/no-verdict); R93 regression test. Retro-flag report
  (tasks/artifacts/ledger_retroflag.md): **2 of 3 historical sota promotions
  were within-run-SEM-only artifacts.** Goes live at the daemon restart.
- **Repair hints, commit 79c699c:** level-scoped _LEVEL_HINTS + 5 runtime
  classes; replay coverage over 358 historical failures **71.2% → 100%**
  (scripts/replay_hint_coverage.py, runs on the ledger COPY).
- **Knowledge graph, commit c7a71ad:** stdlib-only apps/dottie/dottie/kg/
  (Graphify/Rootly/DeepRefine ideas, natively): 208 nodes/504 edges over
  incidents+experiments+events, every claim cited; `python -m dottie.kg.query`
  (preceded/hints/incidents/refine). Design: tasks/artifacts/kg_native_design.md.
- **Flywheel exporters, commit 084781b:** repair-transcript + gridiron
  forecast corpora → tasks/artifacts/corpus_proposals/ (proposal-only,
  nothing auto-ingests).
- **Console, commit 7fb2b29 (DEPLOYED + re-aliased):** contract checks 59→76;
  steer_poll selftest 10→32 (duplicate-ack no-op, clock-skew, audit schema).
- **Readiness pack, commit fde2fb7:** additive tool-selection probes,
  probe_error_analysis.py (14 tests), publisher hardening.
- **Publisher SWAPPED live (verified):** hardened version now runs the 10-min
  task (retry/backoff, stale-markers); rollback = copy
  scripts/publish_live_status_prev.py back over publish_live_status.py.
- **agent-eval repo (C:\Users\jcdav\agent-eval), commit e5c46a7:**
  expected_trajectory in all 8 tasks + presence-based matcher.
- **vector-pitch, commit 54e32a7:** rotation honors difficulty flag (6→13 tests).
- **vector-equities:** eval_sector_coherence.json now carries a structured
  `placeholder_contamination` block (2,200 rows, upward-bias stated);
  UNCOMMITTED pending its suite run; re-export plan:
  tasks/artifacts/equities_reexport_plan.md.
- **Disk watchdog, commit 601f02c:** scripts/disk_watchdog.ps1 (propose-only
  prunes); task registration is PROPOSED not performed
  (tasks/artifacts/disk_watchdog_proposal.md).
- Plan of record + critique log: tasks/plan.md (v2).

## Mission
Build SOTA models faster by researching every piece of the stack → generate
insights with those models → turn insights into revenue. The org runs
autonomously on this box (RTX 4080, Windows + WSL2 Docker); the operator
steers from anywhere.

## What exists (all live)
- **Consoles:** amber terminal https://bluehenre-campus.vercel.app (mobile
  PWA) and org console https://www.bhenre.com/. Source: apps/bluehenre.
  Tests: `node apps/bluehenre/public/js/twin.contract.test.mjs` (76 checks).
- **Feed chain:** trainer → :8000/pipeline/status → publish_live_status.py
  (task "Dottie Status publisher", 10 min) → gist 929c3c0b… → hosted APIs
  (30-min caps).
- **Steer channel:** comments on gist c899ef776dcb81e99319239efa0f92ba;
  OWNER (jcdavis131) comments = directives; poll
  `python apps/bluehenre/scripts/steer_poll.py`, ack `🤖 ack <id>: <status>`.
  Fleet grammar: `fleet: start|stop|restart <container>` (closed allowlist).
  GitHub login IS the auth. Agents may only ever run it with `--selftest`.
- **Vector sites:** measured eval artifacts live (gridiron .690 Spearman;
  hoops 36.3% top-5; equities 1.56x w/ contamination block; pitch 61%
  in-band + rotation gate). Repos C:\Users\jcdav\vector-*.

## Runbooks (critical)
- **Deploy consoles:** `cd apps/bluehenre; vercel deploy --prod --yes` then
  **ALWAYS** `vercel alias set <deployment-url> www.bhenre.com`. Vercel CLI,
  never the MCP connector. (PowerShell 5.1: no `&&`.)
- **Trainer watch:** trust
  `docker exec dottie-factory-trainer-1 sh -c "tail /reports/metrics_mini.jsonl"`
  (docker logs can serve a stale stream after engine crashes).
- **Trainer `done` (exit 0) = schedule complete, NOT a crash.** Resume spikes
  loss (lr rewind) — recovers ~50 steps; never panic-revert. mb=1 is a FAILED
  experiment — never repeat.
- **WSL/disk crash:** free disk, `wsl --shutdown`, relaunch Docker Desktop,
  `docker start` all containers (trainer auto-resumes).
- **dottie test suite:** cd apps/dottie; set
  AVA_FACTORY_ROOT=C:\Users\jcdav\dottie\apps\ava-factory; .venv pytest.
  **36-40 engine/RL tests fail regardless** — they need ava/rl/codeact_loop.py
  which exists only in ava-agi-factory-v6-4's git HISTORY, not any working
  tree (pre-existing; operator open item). Today's scopes are green:
  test_eval_gates, test_validate_hints, test_research, test_kg,
  test_export_*.

## Standing orders (operator-approved, in force)
1. Completion sequence on `done` — see CURRENT STATE above.
2. p5 crash #3 ⇒ HOLD + page via steer.
3. Max 2 heavyweight builders while training; RAM ≥900 MB before any suite;
   keep ≥13 GB free on C:.
4. Propose-first for revenue surfaces (dumbmodel.com, bhenre apex) and for
   curriculum changes (Leg-1 diff posts AFTER eval).
5. Weekly STATE OF THE ORG digest on steer.

## Confirm-why doctrine (operator, 2026-07-22)
**"ALWAYS CONFIRM: why it is true."** Decompose every mechanism/state claim
into components (code path, config, runtime state, data); verify each against
its source; label assumed-not-confirmed components; state corrections plainly.

## Honesty doctrine (non-negotiable)
Numbers render only from real sources; stale = history, not telemetry;
unreachable = offline; nothing auto-ingests into training; contaminated
metrics carry machine-readable contamination blocks.

## Verify (fresh session)
```bash
docker exec dottie-factory-trainer-1 sh -c "tail -2 /reports/metrics_mini.jsonl"
curl -s https://bluehenre-campus.vercel.app/api/twin-status   # source:"local"
node apps/bluehenre/public/js/twin.contract.test.mjs           # 76 checks
python apps/bluehenre/scripts/steer_poll.py                    # steer queue
```

## Open items (operator decides)
- ava/rl/codeact_loop.py restoration (36-40 dottie engine tests unrunnable).
- agent-eval: scoreboard.md/results dirt from an earlier nano-chat run left
  uncommitted (it clobbers the qwen baseline detail — restore or accept).
- Gridiron: TWO unrelated histories on one remote (S2 scout's reconciliation
  proposal in the workflow journal); repo dirty on a claude/* branch.
- Hoops: gate parked on RAM (edits committed-ready in working tree,
  pipeline/ suite must pass first) — run post-`done`.
- Equities re-export post-GPU (tasks/artifacts/equities_reexport_plan.md).
- Disk-watchdog task registration (proposal ready); permanent
  www.bhenre.com project move; monorepo CI `|| true` (design note ready);
  ckpt-promotion eval gate (design note ready).
- Revenue instrumentation proposal awaiting operator read
  (tasks/artifacts/revenue_instrumentation_proposal.md).

Deeper context: HANDOFF.md (session log), apps/bluehenre/SPEC.md (spec of
record), tasks/plan.md (hill-climb plan + critique log), memory dir.
