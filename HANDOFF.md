# HANDOFF — pick up and execute this session's work

**THE single handoff file.** For any assistant (or the operator) resuming Dottie
work: start at the top block, then the durable brief. Consolidated 2026-07-26 —
`CURSOR_HANDOFF.md` was merged in and archived, so there is no second handoff to
reconcile against. All open work AND the full reasoning log live in one file: [`TODO.md`](TODO.md).

⚠ **Curation is a standing discipline, not a one-time cleanup (operator, 2026-07-31):**
this top block and TODO.md's `▶ NEXT` section must be re-verified against real git
history each time meaningful work lands here, not just written once and left. The
2026-07-26 block below sat unrevised through **40+ merged commits** before this
refresh — including two items (`▶ NEXT` #1 and #2) that were fixed on the *same day*
the list was written and never marked done. A stale "current state" block is worse
than none, because it is trusted at face value. Verify against `git log`, not memory,
before writing "current" anywhere in this file.

---

## 📌 Session continuation — 2026-07-31 (supersedes every block below)

**Measured, not carried forward.** HEAD `f274be8`, pushed, tree clean, no divergence
from `origin/main`. Docker Desktop **not running** — no active trainer, no live
bind-mount of the FROZEN `apps/ava-factory/dottie/**` paths right now. 50 GB free on
`C:` (932 GB, 95% used — watch this, not the WSL-volume figure the 07-26 block
quoted, which measures something narrower).

### What actually happened between 07-26 and now (40+ commits, git-verified)

The 07-26 block's `▶ NEXT` items 1–2 were closed **same-day**, by one commit
(`41afb54`, an ultracode 3-fixer/3-verifier run) that the top list was never updated
to reflect:
- **minhash single-linkage bug (item 1a) — fixed.** Star/leader partitioning
  re-verified on exact Jaccard; worst drop-vs-survivor 0.7143 → 0.8000 (0 drops now
  below the advertised 0.8 threshold, was 1).
- **`mcp/cli.py::_check_sdk` duplicate-def bug (item 1b) — fixed.** Key-collision
  overwrite closed; 4,566 → 4,567 documents.
- **Task-shaped eval slice (item 2) — built, and it changes item 6's target.**
  `task_eval_slice.py` mines TODO.md's own items as task-shaped queries (paths
  stripped so the query can't contain its own answer): **NDCG@10 = 0.429** (87
  queries, median 36 words) vs the commit-message slice's 0.622 (209 queries).
  0.622 flattered lexical retrieval — **0.429 is the real bar any embedding model
  must beat**, not 0.622. Item 6 below is corrected to match.

Since then, a long, disciplined "fix + `docs(TODO): close`" pairing closed roughly
20 more items — the honesty/no-silent-loss doctrine got applied repo-wide:
- **Silent-total-loss bugs, same shape, three stores fixed this pass:** secrets
  vault (`3e301cb`) → `auth.json` (`38e7127`) → **`telemetry.py` (`f274be8`, this
  session)**. All three: a tolerant read swallowing a corrupt file, then a
  read-modify-write callsite cementing the loss with no trace. **Two stores left,
  same shape, still queued:** `apps/scout-cli/bigbang/plugins/tasks/cli.py`,
  `packages/personal-graphify/src/personal_graphify/query.py`.
- **Herd ledger race fixed** (`0ae2dc6`) — every process shared one `sessions.tmp`;
  now per-PID temp names (the same fix telemetry's `_write_live_status` needed and
  got, above).
- **Symlink escape in the `fs_write` allowlist closed** (`5b02e15`).
- **Auth gated**: 16 → 15 ungated write-capable plugins (`df11ca3`).
- **stack_v3_code curriculum weight activated** (`85067ad`): P2 0.06 / P3 0.03,
  taken from same-modality siblings (`github_code`), every phase still sums to
  ~1.0. The 07-26 block's "waiting on operator" item for this is **resolved** —
  drop it.
- **Hoops promote justification: retracted claim was itself wrong** (`99a8104`).
  The original worry ("`0.363 → 0.757` lives in a comment and in no artifact") was
  false — it's a protocol-matched, same-field, sha256-pinned artifact comparison
  across the promote commit. What's actually true and narrower: the *baseline*
  side isn't visible at HEAD, so a reader can't check it without `git show
  53d35ad^:assets/eval_scoreboard.json` — a discoverability gap, not fabrication.
- **httpx 0.28 server-endpoint tests restored** (`03b2b3c`) — the 07-26 block's
  "factory 21 errors, pre-existing httpx.Client(app=...) break" is ~~very likely
  fixed now; not re-run this pass to confirm the count~~ **CONFIRMED FIXED
  2026-08-01**: full factory suite re-run = **859 passed / 33 skipped / 0 errors**
  (the 07-26 table said 553/21-errors). The flag-for-next-session was honoured.

### What's actually next (corrected — do not use the 07-26 numbering)

1. **Train the encoder** — one encoder + per-domain LoRA adapters + Matryoshka
   (per the domain-embedding review, `42db5a0`), hard negatives from sibling
   functions in the same class (`ast_pairs.py` already tracks the enclosing class)
   plus adjacent-commit files, pre-registered target **beating NDCG@10 0.429**
   (corrected — not 0.622). This is the only item from the 07-26 "NEXT" list that
   is still genuinely open.
   **2026-08-01: run done, root-caused, base-swapped — best 0.265 vs 0.429 target.**
   Operator go-ahead ("go ahead with step 5 and beyond"). Two rounds: (1) MiniLM with
   3 configs (3ep / 4ep / 4ep+10x lr) all landed 0.194-0.199, and the decisive
   diagnostic — `embed_eval.py --base-only`, new flag, scores the frozen base with
   ZERO LoRA — showed the untrained base alone scores 0.186, i.e. fine-tuning was
   barely contributing. That correctly identified the BASE MODEL as the binding
   constraint. (2) Swapped it: `bge-small-en-v1.5` scores **0.235 zero-shot, beating
   every trained MiniLM config with no training**, and **0.265 trained** — the best
   result of the effort, +33% over the MiniLM best. Also learned bigger≠better
   (`bge-base` 768-d scored 0.215, below its small sibling).
   **The load-bearing conclusion:** across 3 bases, 2 trained configs, an LR sweep and
   an epoch sweep, every dense result lands 0.19-0.27 while plain FTS5/BM25 scores
   **0.429 on the identical eval**. Lexical beats dense here by ~1.6x under every
   variation tried — strong measured evidence that the **Option C decision (scout-cli
   stays lexical) was right**. Full numbers, the pre-registered decision rule and how
   it resolved, and the one untried lever: TODO.md item 6.
2. **`personal_graphify/query.py`'s read-modify-write fixed 2026-07-31** — same shape
   as telemetry.py (corrupt `cost.json` preserved + announced on stderr, write made
   atomic), 4 new tests, full 72-test suite green. `tasks/cli.py`'s half of this item
   turned out not to reproduce — re-read whole file, no local JSON state is ever
   read-then-written-back there. See TODO.md for the full detail either way.
3. **httpx 0.28 fix re-confirmed 2026-07-31.** TODO.md's own verify command —
   `cd apps/ava-factory && AVA_FACTORY_ROOT="$PWD" python -m pytest
   tests/test_server_endpoints.py tests/test_httpx_compat_shim.py -q` → **32 passed**,
   0 errors, matching the number `03b2b3c` recorded. Holds. This closes out every item
   in this list — nothing left here that isn't either done or the step-5 go-ahead (item 1).

### Still open, operator decides (unchanged since 07-26 — no matching commits found)

- `ava/rl/codeact_loop.py` restoration (36-40 dottie engine tests unrunnable).
- agent-eval scoreboard.md dirt from an earlier nano-chat run, uncommitted.
- Gridiron: two unrelated histories on one remote, repo dirty on a `claude/*` branch.
- ~~Hoops gate parked on RAM~~ — **STALE, RESOLVED 2026-07-31.** This tracks
  `~/vector-hoops`, a separate repo dottie's own `git log` can't see, which is
  exactly why it sat unverified since 07-26. Checked directly: `531fc19` (this
  session, re-anchors the CQS promote-gate baseline on the current hustle-defense +
  system-tags recipe) is committed and pushed, working tree clean. Re-ran all three
  gates fresh: `pipeline/test_feature_hygiene.py` (142 features, 19 families,
  clean), `pipeline/provenance_gate.py` (PASSED, all four surfaces agree, dim=64),
  `pipeline/test_composite_gate.py` (16/16). Nothing left parked here.
- ~~Equities re-export post-GPU~~ — **STALE PLAN, SUPERSEDED 2026-07-31.**
  `tasks/artifacts/equities_reexport_plan.md` targeted the wrong (abandoned) export
  script and a placeholder-contamination problem already fixed by a different,
  more thorough rebuild on 07-30 (`ba50cda`+`15e2fd1` — full real SEC/market data,
  zero synthetic rows, per the shipped artifact's own provenance block). Full
  correction in the plan doc itself. **New, genuinely open item this surfaced:**
  `assets/real_data.json` (vector-equities) is still the 07-30 18:56 UTC build —
  it predates this session's `c6b5c2d` (coverage-aware fusion + DEF14A comp) and
  has not been re-exported to pick it up. That's real standing work, but it's a
  fresh decision (touches a live public site, standing order 6 wants propose-first
  before any public deploy) — not something to fold into this stale plan's steps.
  Operator call: green-light the re-export + re-eval, or leave it for now.
- Disk-watchdog task registration, permanent bhenre.com project move, monorepo CI
  `|| true`, ckpt-promotion eval gate — all design notes ready, none actioned.
- Revenue instrumentation proposal awaiting operator read.
- Whether to delete the 2 stale `vector-hoops` clones (`~/workspace`,
  `~/Documents/projects`) — nothing deleted.

---

## 📌 Session continuation — 2026-07-26 (supersedes every block below for live state)

Caveman brief. Short lines. Numbers exact.

### Live state — measured, not remembered

| thing | value | when |
|---|---|---|
| HEAD | `ca91bac`, pushed, tree clean | 2026-07-26 |
| CI on main | green (`da5f717`, both jobs) | 2026-07-25 |
| www.bhenre.com | G3 smoke **PASSES**, exit 0 | after redeploy `8jlgr3038` |
| scout-cli board | ~~2226 passed~~ → **2260 passed / 1 skipped / 0 failed** | re-read 2026-08-01 from the CI gate's own log (7m20s), not a dev-box run |
| factory board | ~~553 passed / 33 skipped / **21 errors**~~ → **859 passed / 33 skipped / 0 errors** | re-run 2026-08-01, 3m21s, one command not three chunks |
| factory 21 errors | **RESOLVED** by `03b2b3c` (httpx 0.28 compat shim); re-verified 2026-08-01, `test_server_endpoints.py` + `test_httpx_compat_shim.py` = 32 passed | |
| retrieval bar (new) | **NDCG@10 0.622 · MRR 0.619 · recall@10 0.791** leak-free, 209 walk-forward queries, 2,024 docs | 2026-07-26 |
| training | **NOT running.** `pipeline: TimeoutError`. Docker CLI 500s | |
| research loop | ALIVE. baseline `factory_lm_loss = 5.73733`. **real wins = ZERO** (3 sota rows all artifacts) | |
| box | ~~1,896 MB RAM free · 23.6 GB disk~~ → **16.9 GB RAM total / 6.7 GB free · 59 GB disk free (94% used) · RTX 4080 12 GB idle** | re-measured 2026-08-01 |
| box — why it matters | 16.9 GB is TOTAL RAM, not free. Any proposal needing ≥25 GB RAM or ≥500 GB disk is out on this hardware — see `tasks/artifacts/colibri_moe_streaming_review_2026-08-01.md` for a worked example | |

### Vector estate — separate repos, NOT in this monorepo

| repo | domain | commits | remote |
|---|---|---|---|
| `~/vector-hoops` | NBA | **318** CANONICAL | yes |
| `~/vector-gridiron` | NFL | 20 | yes |
| `~/vector-pitch` | Soccer | 14 | yes |
| `~/vector-equities` | Equities | 12 | yes |
| `~/vector-unified` | **the binder** | 1 | **private** `jcdavis131/vector-unified` (created 2026-07-26) |
| `~/vector-hub` | dumbmodel.com landing page | 3 | no |

⚠ Two STALE `vector-hoops` clones exist (`~/workspace`, `~/Documents/projects`). Use `~/vector-hoops`.
✅ `~/vector-unified` now has a **private** remote and is pushed — 5,397 lines are no longer on one disk. Private, not public: it protects unreleased research, and private→public is reversible while public→private does not un-publish.

### Gate commands — run these, do not trust memory

```bash
# scout-cli (11 min)
cd apps/scout-cli && python -m pytest tests -q ; echo "EXIT=$?"

# factory — THREE FOREGROUND CHUNKS. background runs get KILLED by memory pressure
cd apps/ava-factory && AVA_FACTORY_ROOT="$PWD" python -m pytest tests -q

# site, before and after deploy
cd apps/bluehenre && node scripts/release_gate.mjs --pre
cd apps/bluehenre && node scripts/release_gate.mjs --post https://www.bhenre.com

# the retrieval bar an embedding model must beat
python scripts/retrieval_eval.py

# find gates whose verdict nothing consumes
python scripts/gate_audit.py --path apps/scout-cli

# hoops provenance: PASSES as of 2026-07-26 (all four surfaces corrected to 64-d)
cd ~/vector-hoops && python pipeline/provenance_gate.py
```

### Doctrines that WILL bite you

- **`AVA_FACTORY_ROOT` unset → 36 false failures.** Always set it.
- **Background full-suite runs get KILLED.** 3 killed on 2026-07-25. Use foreground chunks.
- **`| tail` masks pytest's exit code.** Bit me 5× in one day. Use `echo "EXIT=${PIPESTATUS[0]}"`.
- **FROZEN: `apps/ava-factory/dottie/**` + `apps/ava-factory/configs/**`.** Bind-mounted into the live trainer. `scripts/` is NOT frozen.
- **Parse with `ast`, never grep.** This repo's comments quote the code they discuss. Grep-counting-prose gave 3 wrong answers in one day.
- **`subprocess.run([sys.executable, ...])`.** Bare `'python'` resolves a different interpreter here and every mutation "kill" becomes a fake.
- **Never edit source while a suite runs.** CLI tests spawn subprocesses that re-read from disk.
- **Test floors must sit NEAR the measurement.** A floor below the truth passes with fabricated numbers. Happened 2026-07-26.
- **Run scout tests from `apps/scout-cli`.** A stale `.pth` shadows `bigbang` from the repo root → 8 phantom failures.
- **Licence gate is deny-by-default.** Any `-nd` denied (training is derivative use). Any `-nc` denied. Unverified ≠ permissive. Shadow libraries forbidden regardless of tag.

### The one lens that found the most bugs

**"A gate whose verdict nothing consumes."** 5 instances in one day: fail-open action dispatch; 47 manifests declaring `paths` enforced by 0; a licence skip disabled by `and not args.dry_run`; `promote {"ok": false}` shipping anyway; `|| true` on a lint gate. Ask of any gate: *which line reads this verdict, and what does it do differently?* If the answer is "writes it to a report", it is not a gate. Detector: `scripts/gate_audit.py`.

### NEXT STEPS — ordered

1. **Fix the 2 defects that produce wrong data** (the reasoning log (below), 2026-07-26 block).
   `minhash_dedup.py` single-linkage drops docs below its own 0.8 threshold (worst true J **0.7143**); `docs[key] = seg` silently overwrites same-named defs — `mcp/cli.py::_check_sdk` exists twice, one returns `True`, one raises, **opposites**, only the second survives.
2. **Task-shaped eval slice.** Golden-set queries are commit messages. Agent-tier queries are task descriptions — longer, less identifier-dense, **harder for BM25, easier for embeddings**. 0.622 probably flatters lexical. Judging a model only on commit messages is rigged the other way.
3. ~~Remote for `~/vector-unified`~~ — **DONE 2026-07-26**, private remote pushed.
4. ~~Decide the authoritative surface for hoops 48-vs-64~~ — **DONE 2026-07-26** (`72a69d4`). The ARTIFACT won, on arithmetic not preference: `mtnn_embeddings.f32` is 3,319,296 B = 12,966 × 64 × 4. Drift was deeper than dim — README said 120 features (real 130), methods.html said MTNN **v4** and `556→128→48` (real v5, `556→256→64`), and `mtnn.js` carried a dead `||48` fallback. `mtnn_arch.json` is GENERATED and stale three ways, so only `dEmb` was corrected and the rest DECLARED stale in a `_stale` block rather than laundered.
5. **Re-derive or retract the hoops promote justification.** `0.363 → 0.757` lives in a comment and in no artifact. Same shape as the 3 artifact sota rows.
6. **Then step 5 of the embedding sequence** — ONE encoder + LoRA adapters, hard negatives, pre-registered target beating 0.622.

**Waiting on operator:** whether to delete the 2 stale `vector-hoops` clones (nothing deleted), and a Docker Desktop restart to verify the telemetry fix. **stack-v3 is ACTIVATED** as of 2026-07-26 — frozen paths were unfrozen after verifying no live trainer (GPU **0 MiB used, 0% util, zero compute procs**), the adapter is registered in `ADAPTERS`, and `stack_v3_code` sits in `sources.yaml` at **weight 0.0** with every phase still summing to exactly 1.0. Giving it a real share is the one remaining curriculum edit.

---

## Durable brief — mission, runbooks, standing orders, doctrines

*Carried verbatim from `CURSOR_HANDOFF.md` on 2026-07-26 when the two handoff
files were consolidated into this one. That file had 870 lines, 6 NUL bytes (which
is why `grep` called it binary — use `grep -a`), and a stack of dated session blocks
from 07-23 to 07-25. Its history is preserved at
`tasks/archive/CURSOR_HANDOFF_2026-07-25.md`; the sections below were its unique,
still-in-force content. NULs stripped in transit.*

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
6. **Curate HANDOFF.md's top block + TODO.md's `▶ NEXT` section every session that
   lands meaningful work here** (operator, 2026-07-31) — not a one-time cleanup.
   Re-verify against `git log`/`git show`, never against memory of a prior session's
   claims: this exact drift (items closed same-day, never marked, sitting stale for
   5 days and 40+ commits) is what triggered the rule. A "current state" block that
   isn't re-verified is worse than none, because the next reader trusts it at face
   value.

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

The living source of truth is [the reasoning log (below)](./the reasoning log (below)) — read its **"YOUR DECISION QUEUE"**
section (search that header) and the **§5.3.R98–R100** entries at the top of the R-log. This
file is just the entry point; the reasoning log (below) has the detail and stays current.

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
- **`python scripts/check_todos_timestamps.py`** before committing any the reasoning log (below) edit — it
  rejects fabricated clock times.
- **Read [`scripts/README.md`](./scripts/README.md)** before writing a new script — the
  operational tooling (restart/recovery, run-log reader, mutation audit, and the per-promotion
  `ab_nano.py` verifier) is indexed there.
- Never write a clock time that did not come from `date` or `git log` in the same tick.

## Status note

This file and the reasoning log (below) are **local-only until item 00 is done** — `origin/main` does not yet
contain this session's work. After the git reconciliation pushes, this handoff becomes visible
to anyone with the repo. Until then, "pick up" means on this machine.
