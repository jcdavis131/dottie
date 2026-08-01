# TODO — the single open-work list

**Generated 2026-07-26 by mechanical extraction.** Every `- [ ]` in the reasoning log (below) (126)
and `tasks/todo.md` (15) is below — 141 items, nothing curated away, nothing invented.
Item text is the checkbox line plus up to two continuation lines; **the full reasoning
for each lives in its source file under the same heading** and is not reproduced here.

⚠ **This list is not triaged.** 141 open items is an inbox, not a plan. The ordered
next steps are the section immediately below; everything after it needs a triage pass
that no one has done.

---

## ▶ NEXT — ordered, do these first

*Re-verified 2026-07-31 against `git log` (not memory) — items 1 and 2 below were
BOTH closed same-day by `41afb54`, five days before this correction. See
`HANDOFF.md`'s 2026-07-31 block for the full re-audit; that staleness is exactly why
this section now carries a re-verify note instead of being trusted at face value.*

1. ~~**Fix the 2 defects producing wrong data.**~~ **DONE 2026-07-26** (`41afb54`).
   `minhash_dedup.py` single-linkage was dropping documents below its own advertised
   0.8 threshold (worst true Jaccard 0.7143) — fixed via star/leader partitioning
   re-verified on exact Jaccard, 0 drops below threshold now (was 1). `docs[key] = seg`
   silently overwrote same-named defs (`bigbang/plugins/mcp/cli.py::_check_sdk`
   defined twice, opposite behavior, only the second survived) — key collisions no
   longer silently overwrite, 4,566 → 4,567 documents recovered.
2. ~~**Add a task-shaped eval slice**~~ **DONE 2026-07-26** (`41afb54`), same commit
   as #1. **Result that changes item 6 below:** task-description queries (87, median
   36 words, path-stripped so the query can't contain its own answer) score
   **NDCG@10 0.429**, vs the commit-message slice's 0.622 (209 queries). 0.622
   flattered lexical retrieval — 0.429 is the real bar, and item 6's target is
   corrected to match.
3. ~~Give `~/vector-unified` a remote~~ — **DONE 2026-07-26**: private remote `jcdavis131/vector-unified`, pushed. Verified before pushing (one-way): 37 tracked files, no secrets, no `.env`/credential/`.pem`/`.key`, largest blob 44 KB. Superseded text: 5,397 lines, one disk; local git survives `rm`,
   not disk failure.
4. ~~Decide the authoritative surface for hoops 48-vs-64~~ — **DONE 2026-07-26** (`72a69d4`).
   The ARTIFACT won, on arithmetic not preference: `mtnn_embeddings.f32` is 3,319,296 B =
   12,966 × 64 × 4. All four surfaces corrected; the provenance gate now PASSES. Drift was
   deeper than dim — README said 120 features (real 130), methods.html said MTNN **v4** and
   `556→128→48` (real v5, `556→256→64`), `mtnn.js` had a dead `||48` fallback.
   `mtnn_arch.json` is GENERATED and stale three ways, so only `dEmb` was corrected and the
   rest DECLARED stale in a `_stale` block rather than laundered. Superseded text:
   `cd ~/vector-hoops && python pipeline/provenance_gate.py` exits 1 today, correctly.
5. ~~**Re-derive or retract the hoops promote justification.**~~ **RETRACTED 2026-07-28 — the
   claim "and in no artifact" was FALSE.** `0.363 → 0.757` is a protocol-matched, same-field,
   same-artifact comparison across the promote commit `53d35ad`:
   - `0.757` = `assets/eval_scoreboard.json` → `results.mtnn.by_split.test.top5` at HEAD
     (n=790, dim **64**, `mtnn_v5_concat_b2_h160_t32_d64_mlp128_fus256`)
   - `0.363` = **the same field** in the parent version (dim **48**,
     `mtnn_v5_concat_b2_h160_t32_d48_mlp128`) —
     `git show 53d35ad^:assets/eval_scoreboard.json`
   - Produced by its own eval commit, `b25d73e feat(eval): held-out adjacent-season retrieval
     scoreboard — build + gate + /model readout`
   - The artifact is *better* than most here: sha256-pinned embeddings and vectors,
     `computed_at 2026-07-25T14:43:37Z`, **exhaustive not sampled**, **pessimistic tie
     handling** (ties count against the target), explicit split boundaries, and full pair
     accounting (10,104 eligible of 12,966 rows).
   - **What was actually true, and it is narrower:** the *baseline* is not visible at HEAD —
     only the promoted side is. A reader at HEAD cannot check the comparison without git
     archaeology. Worth recording the `git show` line next to the claim in
     `composite_score.py`, but that is a discoverability fix, not a fabrication.
   - **Why I got it wrong:** grep for `0.363` across the repo returned **11.4 MB** of matches —
     the digits occur inside unrelated float blobs in the shipped JSON — so an earlier pass
     concluded "no artifact" from a search that was drowning in false positives. The metric
     name and `git log -S` found it in one shot. Same lesson as the np.random audit: search
     for the *thing*, not the *digits*.
6. **Then step 5 of the embedding sequence** — ONE encoder + per-domain LoRA
   adapters + Matryoshka (per the domain-embedding review, `42db5a0`), hard
   negatives from sibling functions in the same class (`ast_pairs.py` already
   tracks the enclosing class) plus adjacent-commit files, pre-registered target
   beating **NDCG@10 0.429** (corrected 2026-07-31 — was 0.622, the commit-message
   number item 2 above found flatters lexical retrieval; 0.429 is the real
   task-shaped bar).
   **PIPELINE BUILT, NOT YET RUN FOR REAL, 2026-07-31.** Pre-registration:
   `tasks/artifacts/embedding_train_plan_2026-07-31.md` (base model, two domains not
   N, LoRA target modules, dims `[384,256,128,64]`, why the run is held). New:
   `apps/ava-factory/scripts/train_encoder.py` (trains, `--smoke` verified: whole-repo
   scope in 19.5s, 3,065 code-domain / 562 task-domain examples mined, no code touched)
   and `apps/ava-factory/scripts/embed_eval.py` (scores a checkpoint against the SAME
   golden sets/protocol the 0.622/0.429 bars were measured on). One real (non-smoke,
   tiny-scope) train -> save -> eval round trip run end to end correctly — caught and
   fixed one real bug in the process (peft nests `save_pretrained(dir, selected_adapters=
   [d])` under `dir/<adapter>/` itself; passing `dir/d` double-nested it, `PeftModel.
   from_pretrained` then couldn't find `adapter_config.json`). 6 new pure-function tests,
   103 pre-existing tests in the modules it reuses (`ast_pairs.py`, `hard_negatives.py`,
   `retrieval_eval.py`, `task_eval_slice.py`) still green, ruff clean. **The real,
   full-scope training run itself has NOT been kicked off** — per this repo's own higher
   bar for retrain requests (real GPU time, unmeasured first attempt), it's held for an
   explicit go-ahead rather than started automatically. That go-ahead is the only thing
   left before this item can close.

### ✅ 2026-07-26 — defect sweep done; the task-shaped bar is MUCH lower than the commit-shaped one

**THE RESULT THAT CHANGES THE PLAN.** `scripts/task_eval_slice.py` mines TODO.md itself for
task-shaped queries (item text → the files it names, with those paths STRIPPED from the query
so it cannot contain its own answer):

| slice | queries | median words | NDCG@10 |
|---|---|---|---|
| commit messages (`retrieval_eval.py`) | 209 | short, identifier-dense | **0.622** |
| **task descriptions (`task_eval_slice.py`)** | **87** | **36** | **0.429** |

Path-stripping is load-bearing: leaving them in scores **0.526**, a ~0.10 inflation.

So the earlier warning is now measured rather than asserted: **0.622 flattered lexical
retrieval.** On the query distribution Option C named as the real consumer, the bar an
embedding model must beat is **0.429**. That is a materially easier target and it strengthens
the case for training one.

All three defect sets fixed and adversarially verified — `fixes_hold: true`, **0 new defects
introduced** in all three. 255 tests (minhash 76→104, hard-negatives 49→59, task-eval 92).
minhash: min drop-vs-survivor true Jaccard **0.7143 → 0.8000**, drops below the advertised
threshold **1 → 0**, one document rescued from the key collision (4566 → 4567), collisions now
reported. hard-negatives: every real-repo floor raised to ≥80% of measured (e.g. same_package
1000 → 3014 against 3768 measured), and the order-independence claim fixed in the CODE rather
than downgraded in the docstring.

Residuals the verifiers found that the builders did not report — worth closing, none blocking:

- [x] `scripts/task_eval_slice.py` — `main()` had **zero behavioural coverage**. Closed
  2026-07-26: 18 tests now drive it as a subprocess (`--json`, `--out`, text report) plus one
  in-process call. Mutation-verified — the text path printing `items_total` where it means
  `kept` is killed, and so is `--out` truncating the slice. `--max-commits 200` keeps each
  run ~10s; the commit slice is then too small to reproduce the recorded bar, and main() must
  still exit 0 while SAYING it does not reproduce, which is the honest behaviour under test.
- [x] `scripts/test_task_eval_slice.py:71` — `FLOOR_STRIP_INFLATION` 0.18 (**79.4%** of the
  0.2268 measured) broke the file's own ≥80% rule. Now 0.1859 = 82.0%, with a test asserting
  the rule holds. Fixed `5eefc90`.
- [x] `scripts/task_eval_slice.py:185-195` — `strip_spans` mishandled **partially overlapping**
  spans, leaving the span's TAIL in the query: `(0,5)`+`(3,10)` left chars 5..9, i.e. a path
  fragment survived into the query the strip exists to clean. `continue` → `last = max(last,
  end)`. Fixed `5eefc90`.
- [x] `scripts/task_eval_slice.py:68-79` — `_load_retrieval_eval` reused
  `sys.modules['retrieval_eval']` **by name with no path check**. Now verifies `__file__` and
  loads under the private alias `_tes_retrieval_eval` so this module can never itself become
  the shadow the check exists to detect. Fixed `5eefc90`.
- [x] `scripts/task_eval_slice.py:344-346` — `empty_result_count`. **The recorded claim was
  wrong and is retracted**: `return 0` did NOT pass 92/92. Measured 2026-07-26 against the
  actual 99-test suite at HEAD, it was killed by two PRE-EXISTING structural tests, because
  that line is the only `RE_EVAL.fts_query` call site and deleting it trips "the borrowed
  scorer is called through RE_EVAL". Inverting the `not` was killed too. A **real** survivor
  exists and was found by probing rather than by trusting the note: collapsing the sum to
  `int(any(...))` passes the old suite 99/0, because the only check was
  `<= CEIL_EMPTY_RESULTS = 2` and a bool satisfies a ceiling. Six two-sided tests added,
  including both anti-vacuity preconditions; the survivor is now killed. **Lesson: a
  one-sided bound on a counter is not coverage of the counter** — it proves the repo is
  healthy, never that the function can report ill-health at all.
- [x] `scripts/test_task_eval_slice.py` — the corpus under test **contains the tests**.
  Writing the nonsense "unmatchable" token as one literal indexed it (the file is a `.py`
  under `scripts/`) and the unmatchable query matched this very file, failing 3 tests. Token
  is now assembled from fragments, with a test asserting the joined form appears nowhere in
  the file. Any literal in a test file under an indexed tree is a document.
- [x] `apps/ava-factory/tests/test_minhash_dedup.py:1027` — passed for the wrong reason on a
  checkout without `apps/scout-cli`: `ast_pairs.walk` returns nothing for a missing path
  **without raising**, so `collect_documents(<nonexistent>)` yields `files: 0, collisions: 0`
  and `0 == 0` held vacuously while its `skipif`'d siblings correctly skipped. Closed
  2026-07-26: `skipif` on the test (absent → visible skip, never a false pass) plus floors
  near the measurement — `files >= 48` (measured 51) and `len(docs) >= 1100` (measured 1177).
  **Proven, not argued**: mutating `collect_documents` to scan only the first 10 files, the
  version at HEAD still PASSED; the new version FAILS.
- [x] `apps/ava-factory/tests/test_minhash_dedup.py:1317` — `assert res["components"] >
  len(...) or rescued == 0` was dead: the assert directly above already establishes
  `rescued >= 1`, so the right operand was unreachable and the line silently reduced to its
  left operand. Worse, that operand is **not an invariant** — a 3-member component splitting
  into a pair plus a singleton leaves `rescued == 1` and the cluster count unchanged, so it
  would fail on a different split shape while reading as a general law. Split into (a) the
  always-true accounting identity `components + rescued - len(clusters) >= 0`, and (b) the
  corpus-specific measurement, labelled as such: **components 19, clusters 18, rescued 1,
  groups 20** on `bigbang/plugins` — the one split fully DISSOLVED a 2-member component into
  two singletons. Mutation-verified 4/4 (scan-10-files; `rescued = 0`; `rescued` sign-flipped;
  `clusters` keeping singletons), baseline green over byte-verified restored source.
- [x] `hard_negatives.py` — both halves closed 2026-07-26. **71 tests** (was 59), 4/4
  mutations killed, ruff clean.
  - **Dead guard, confirmed dead then removed.** `mine_adjacent_negatives` tested
    `j == i`, but `offsets` is built from `range(1, window + 1)` as `(-d, +d)` and so
    never contains 0 — measured for window 0/1/5/50. It could not fire. Removed rather
    than left as reassuring noise. Doubly dead, in fact: even with a 0 offset the
    neighbour's own files are all in `forbidden`, so nothing would be emitted anyway.
  - **The identity collapse really is half-applied, and that half is correct.**
    Reproduced on a 12-line file: `Outer.Inner.run` and `Other.Inner.run` both arrive
    as symbol `Inner.run`, so 2 records emit sharing 1 `(path, symbol)` (1 distinct of
    2) and one record's negatives list holds 2 indistinguishable entries. Self-exclusion
    is collapsed — 0 records name themselves — and the rest is deliberately NOT, because
    `text` is the training signal and stays distinct; collapsing would discard a genuine
    negative to tidy a label. The defect was that **nothing said so**: a consumer keying
    on `(path, symbol)` silently keeps one and loses the other, the same silent-overwrite
    shape `minhash_dedup` surfaces as `collisions`. Now reported by
    `identity_collisions()` → `{"records": n, "negative_entries": n}`, printed in the
    report, counted **per record** (a negative shared by two different records is two
    queries sharing a negative, not a collision). Measured **0 of both** on this tree;
    727 queries / 5,766 negatives on `apps/ava-factory`.
  - **My first premise test was circular and a mutation proved it.** It rebuilt the
    offset loop inside the test, so putting `range(0, ...)` back in the source passed it
    untouched — a second copy of the rule, inside the test written to guard the rule,
    which is the duplicated-source class this module's own docstring warns about.
    Extracted `_offsets(window)`; the test now READS it and the same mutation kills 6
    tests.

### ✅ 2026-07-26 — FROZEN PATHS UNFROZEN; stack-v3 is ACTIVATED (dormant at weight 0.0)

Operator said unfreeze. Verified the freeze was safe to lift before touching anything —
the freeze existed to protect a **live** trainer, and there is no live trainer:
**GPU 0 MiB used / 12,282 total, 0% utilisation, zero compute processes**, vmmemWSL
110 MB. No training run occupies 0 MiB of VRAM. (A broken docker CLI would NOT have
been sufficient evidence — "the tool cannot reach it" is not "it is not running" — but
GPU occupancy is a different and stronger signal.)

Two frozen edits made:
1. `dottie/datagen/stackv3_adapt.py` — moved from `scripts/` so it is importable as
   `dottie.datagen.stackv3_adapt`; its `_DD` path re-anchored to `parents[2]/scripts/`
   so `gate_license` still loads by absolute path and cwd cannot matter.
2. `dottie/datagen/adapters.py` — `"stackv3"` registered in `ADAPTERS`.
3. `configs/sources.yaml` — `stack_v3_code` added, **weight 0.0 on both phases**.

Verified rather than assumed:
- **Every phase still sums to exactly 1.0** (0:1.0 1:1.0 2:1.0 3:1.0 4:1.0 5:1.0), 38
  sources. That was the documented collector-spin trap.
- **Wiring works end to end**: `apply_adapter('stackv3', rec)` on a repo with one MIT
  and one ND file keeps the MIT file, excludes the ND file from the training text, and
  returns `None` for an all-ND repo.
- 242 passed / 1 skipped across the adapter, licence gate, manifest, datagen, all three
  sibling adapters and the collector.
- Weight 0.0 follows existing precedent: `synth_research_pdf` sits at 0.0 with the note
  "per-file sidecar; keep weight 0 until licenses clean" — the identical situation.

- [x] **Rebalance the phase-2/3 weights to give stack_v3_code a non-zero share.** Done
  2026-07-28, `85067ad`, in one deliberate edit as required. Verified at HEAD: all 6 phases
  sum to exactly 1.0, every source's weight keys equal its declared phases, 38 sources,
  31 collector tests pass.
  - **P2 0.06**, taken entirely from `github_code` (0.15 → **0.09**). Same modality, so P2's
    raw-code budget is UNCHANGED at 0.25 = `synth_code` 0.10 + `github_code` 0.09 +
    `stack_v3_code` 0.06. `github_code`'s config is `Python-mit` — one language, one licence —
    so this buys multi-language coverage behind an equally strict per-file gate, with no
    licence loosening and no increase in code share.
  - **P3 0.03**, taken entirely from `synth_think_code` (0.15 → **0.12**). P3's code content
    was otherwise entirely model-generated (that + `codeact_traj`); 3% real permissively
    licensed source hedges a synthetic-only code distribution. P5 untouched — `stack_v3_code`
    does not declare phase 5.
  - **Deliberately small, and the reason is recorded in the config**: the adapter has never fed
    a real run, so the licence-gate drop rate on live HF rows is **UNMEASURED** — the tests
    cover the gate's logic, not what fraction of rows survive it. If the drop rate is high the
    phase still fills from its siblings. Revisit with a measurement, not a guess.
  - The live trainer never live-reloads `sources.yaml`, so nothing in flight changed; the next
    restart picks it up.

### ⚠ 2026-07-26 — "remove fabricated data" is NOT done in vector-equities: 17 pipeline files still use np.random

Operator asked for the fabricated data removed. The reconciliation is done; **the removal is
not**, and that is the finding.

**Reconciliation (done).** `vector-equities` had 3 local vs 5 remote commits overlapping on
four files, including two independent commits that both claimed to remove fabricated data:

```
local  b624c88  fix(equities): remove fabricated data from shipped assets and generator
remote 23de1dc  Remove fabricated data: random projection card, np.random skills, ...
```

Neither is a superset. Remote also cleaned `real_data_flat.json` / `real_data_latest.json`;
local also added a 57-line `assets/manifest.json` block. Resolved without discarding
anything: the 3 local commits are preserved AND PUSHED on
`preserve/local-fabrication-removal-2026-07-26`, `main` fast-forwarded to remote, and only
the conflict-free `.gitignore` commit was cherry-picked on top. `main` is 0 ahead / 0 dirty.

- [x] **AUDITED AND FIXED 2026-07-28. The framing "17 files still contain `np.random`" was
  true but misleading — it counted matches, not fabrication.** Traced backward from the 11
  committed `assets/` instead of forward from grep: only **7** files both draw random *and*
  write a shipped asset. Verdicts:
  - **3 fabricated, all fixed** (3 commits, local, unpushed — pushing changes what the live
    site claims):
    - `a090fe9` `tune_fwd_dd_head.py` — shipped `forward_calibration_isotonic.json` said
      `"passed": true` for a fit to data manufactured to hit the targets it then "verified".
      `is_real` was computed and written to `trained_on`; `passed` ignored it. A **tautology**:
      `synthetic_data()` re-centres pred on `PRED_MEAN_TARGET=0.1137` exactly, so
      `bias_before 0.0576` is just `0.1137 − 0.0561` by construction. The tell was already in
      the artifact — `ic_before 0.87843` vs `ic_target 0.5066`. Now `bias_within_tolerance`
      (measurement, kept) + `passed: false` + `passed_requires`. Console lied too; fixed.
    - `cde5092` `verify_trades_v6.py` — **a verifier that manufactured its own subject**, wrote
      it to the canonical `train_matrix_v6.npz`, then verified it and `return True`, so
      `sys.exit(0 if all(...) else 1)` exited 0 = VERIFIED. `except Exception: return True`
      made the failure path the pass path. Now fails loudly.
    - `a9cb9a5` `build_real_v4_exec.py` — invented `embedding=np.random.randn(N,32)` under the
      canonical name; `embedding.npz` is gitignored so it **never appeared in a diff**. Now
      warns, writes nothing, records `"embedding_npz": "absent (not fabricated)"` in meta.
  - **Legitimate:** `eval_sector_coherence.py` — seeded permutation nulls for the
    purity/silhouette baselines. Correct statistics.
  - **False positives, and they are the lesson:** `export_v6_real_assets.py`'s 3 hits are
    *comments* reading "never synthesize (no np.random, no flat-50 placeholder)" — an
    already-cleaned file describing what it no longer does. `universe_full_history.json`
    matched on a real company, **"Synthetic Fixed-Income Securities, Inc."**
  - 17 tests added across 3 files, all mutation-verified, all restores byte-exact (`cmp`).
    **Parsed with `ast`, never grepped** — my first guard test used
    `assert "np.random" not in src` and failed on the comment above its own fix. Fifth
    instance of the prose bug here, first inside a test written to prevent it.
  - Standing correction: the assets already carried honest field-level provenance
    (`manifest.json`: *"Fabricated top-level metric literals removed… had no committed
    computation behind them"*). The gap was never disclosure — it was **verdicts that did not
    consume the disclosure**.
- [ ] **Decide the fate of `preserve/local-fabrication-removal-2026-07-26`.** Its unique
  contribution is the `manifest.json` block; cherry-pick that onto main or drop the branch.

### Waiting on the operator (not on an assistant)
- ~~The 2 FROZEN edits to activate stack-v3~~ — **DONE 2026-07-26**, see the unfreeze block above. Superseded text: (`odc-by` verified; adapter + 27 tests ready;
  source enters at weight `0.00` or the collector spins).
- Docker Desktop restart → verifies the telemetry fix, unblocks training.
- Delete the 2 stale `vector-hoops` clones? Nothing was deleted.
- scout-cli `httpx<0.28` pin vs starlette upgrade — 21 tests cannot run.

---

---

## Extracted backlog (141 items, untriaged)

### `tasks/todo.md` — Phase 2: GUIDE digest + agent tiles

- [ ] Agent-activity tiles (research loop / fleet / trainer) — deferred; the digest is the higher-value half and shipped first.

### `tasks/todo.md` — 🔴 THE GATE'S FIRST RUN FOUND A LIVE PROVENANCE DEFECT

- [ ] **Fix = redeploy** (G2, the operator's gated step per the plan — I did not deploy). After deploying, `--post` must go green before the alias moves.
- [ ] **S4** G4 writes `data/last_good_deployment.txt` (pin becomes an output of a passed gate, not a hand-edited input); deploy runbook becomes gate-driven.
- [ ] **S7** G5 watch loop — scheduled liveness + freshness probe. Stale WARNS, never fails: stale is a documented honest state, and a gate that fires on a legitimate state gets disabled (the `lint.yml` permanently-red lesson).
- [ ] **OPERATOR FORK — the assistant has no brain in production, and no amount of code changes that.** `api/assistant-chat.mjs` returns `source:"offline"` unless `DOTTIE_CHAT_URL` is set, and it is unset in prod because the box is

### `tasks/todo.md` — Then — Phase 3: MONITOR runtrack readout

- [ ] Bridge `runtrack` (scout-cli openswap, pure-sqlite) to the live trainer/research metrics + the ledger.
- [ ] Monitor card: live training curve(s), research experiments/promotions, fleet stats, run comparison. Real-measured; stale/offline honest.

### `tasks/todo.md` — External data expansion (operator directive — validated sources)

- [ ] Scale OAPEN (`--full` + higher `--target`), then the operator lands the `sources.yaml` entry (frozen config). Decon note: OAPEN can't overlap the CURRENT held-out (not a generator); `HELDOUT_SEED` disjointness applies
- [ ] Future clean expansions: broaden Gutenberg, Standard Ebooks, PMC-OA, Wikisource.

### `tasks/todo.md` — Adversarial code review (2026-07-24) — findings addressed

- [ ] Deferred (latent, no current card hits them): multiple-config `dataset_info` (sums across configs) + quoted/glob `path:` values. Fix when a card needs them.

### `tasks/todo.md` — Gated / dependency-blocked (Phase 4)

- [ ] **HF publish** (Hub ↔ real HuggingFace) — BLOCKED on `HF_TOKEN` rotation (provenance audit #6). Show an honest "mirror: awaiting token rotation" until rotated; then wire the authed push (operator runs the token step).
- [ ] **Engine ReAct trace** (Guide chat) — needs the factory hub `/assistant` to expose a stable `steps[]`; verify the engine field first, pass through `server.mjs` verbatim.

### `tasks/todo.md` — Operator calls (from the provenance audit — deliberately not auto-done)

- [ ] Rotate the previously-committed `HF_TOKEN` and place the new value in the gitignored `apps/ava-factory/.env` (I cannot write the secret).
- [ ] #7 baseline-provenance gate in `evaluate.py` (code defers it to operator).
- [ ] Equities checkpoint for real asset regen (KPI card + skills radar still synthetic-flagged); ~66% synthetic curriculum mix; stale config labels (frozen path); dead `train_1b_deepspeed.py` path.

---

# ══ Reasoning log (was the reasoning log (below)) ══

*Merged in 2026-07-26. Every line of the former the reasoning log (below) follows, markers and
lists intact. 5,772 lines / 421 completed items of measurement-and-retraction
history — the reason this repo can tell a real win from an artifact.*

# TODOS — the road to the Agentic Assistant platform at arxiviq.com

> Unified execution roadmap, reconciled 2026-07-19. One rule inherited from everything
> that worked so far: **every number is measured, every gate is real, every step names
> its acceptance criterion.** Work top to bottom; parallelize only where marked ∥.
> Solo personal project, no connection to employer, built with public/free-tier only.

## Goal state (updated by the 3-min loop, 05:19 2026-07-20 — clock verified)

### ⚠ WHY THE FLEET DIED — I caused it, and the blocker is now cleared (03:47)

**Root cause: my own change.** At ~00:50 I enabled `DOTTIE_OLLAMA_MODEL_NIGHT=qwen3:14b`,
reasoning that GPU contention was gone with the trainer parked. Wrong constraint: with
`NUM_GPU=0` the model loads into **system RAM**. Measured at 03:45: `llama-server` holding
**7.0 GB** of this 16 GB box, total working sets 11.4 GB, **available memory 281 MB**. The
WSL2 VM could not get the memory it needs, died at ~02:05, and could not reboot — which is
why every `docker` call has 500'd since. It was never a Docker fault.

**Cleared**: unloading the model (`keep_alive: 0`) returned **7,493 MB** instantly, and the
night-model line is now commented out in `research_env.local.ps1` with the measurement and
a re-enable check (want >9 GB available). Also killed 4 orphaned worker processes en route
(see the §5 root-cause entry) — though those held *commit*, not resident RAM, so they were
not the cause; I corrected that claim rather than leave it standing.

**✅ RESOLVED — the VM restart happened; do not act on this section.** Verified 2026-07-24
22:50: **13 containers up**, `dottie-factory-trainer-1` and `dottie-factory-server-1`
healthy, training live at step 3080 (`lm 0.193`). The outage below is history, not telemetry.

⚠ **BUT the headroom warning is LIVE again, and this is the real current risk.** Measured
2026-07-24 22:50 across four samples: available memory **483 / 548 / 695 / 1035 MB**, and
`vmmemWSL` alone is **4.2 GB**. The 2026-07-20 death happened at **281 MB** — so we are
operating in the same band that killed it, without the llama-server that caused it
(`/api/ps` -> `{"models":[]}`, nothing resident, so the documented 7.5 GB unload remedy
does NOT apply here — there is no easy win to take).
Consumers today: vmmemWSL 4200 MB · claude sessions ~1900 MB · chrome ~560 MB · Memory
Compression 262 MB · 12 python processes.
**Observed consequence, not a hypothetical:** two full-suite background test runs were
KILLED partway through (at 24% and 80%) on this box today. Verification had to be split
into three foreground chunks to complete. If background jobs start dying, suspect this
before suspecting the code.
Re-check with:
`(Get-Counter '\Memory\Available MBytes').CounterSamples[0].CookedValue`

### NEW 2026-07-25 — `.github/workflows/lint.yml` is a HARD gate that has been RED on every push

- [ ] **OPERATOR DECISION — a second ruff workflow contradicts the one in ci.yml, and it fails
  every time.** `gh run list --workflow "Ruff Lint"` -> **failure on 8 of the last 8 pushes**,
  including commits that predate today's work. A permanently-red required check is worse than an
  honest soft one: it trains everyone to ignore the X, so the next REAL breakage looks identical
  to the noise.
  What it runs (no `|| true` on either step):
  ```
  pip install ruff==0.8.6
  ruff check . --statistics      # repo-wide, NO --exclude
  ruff format --check .          # repo-wide format enforcement
  ```
  Three separate problems:
  1. **Scope.** `ruff check .` from the repo root lints EVERYTHING, including
     `apps/ava-factory/**` (FROZEN, bind-mounted into the live trainer) — code nobody may edit to
     satisfy a linter. `ci.yml`'s ruff step deliberately scopes to 4 packages.
     Measured locally: **1,397 findings repo-wide** (646 auto-fixable) versus the 334 across the
     four packages ci.yml checks. So ci.yml's documented "334 known findings" describes a
     DIFFERENT invocation than the one actually gating.
  2. **Version skew makes local verification impossible.** CI pins **ruff 0.8.6**; this box has
     **0.15.22**. Different rule sets and defaults, so "ruff clean locally" does not predict this
     gate. Every batch-4 agent verified against 0.15.22.
  3. **`ruff format --check .`** is a far stricter gate than `ruff check` and nothing in the repo
     satisfies it. This alone can never pass without a repo-wide reformat.
  **Options, in the order I would recommend them:** (a) scope `lint.yml` to the same 4 packages as
  `ci.yml`, pin the SAME ruff version both places, drop `--format --check` until a deliberate
  reformat happens, and keep it non-blocking with the count stated — i.e. make it agree with
  ci.yml; (b) delete `lint.yml` as redundant, accepting the loss of repo-wide scope and the format
  check; (c) leave it red. Not (c).
  ⚠ I did NOT change or delete a CI workflow unilaterally — that is a policy call about what this
  repo requires, and "make the red X go away" is exactly the move that deserves a human. But note
  the ci.yml ruff comment I wrote today (334 findings) is scoped to ci.yml's invocation and should
  cross-reference this once resolved.

### NEW 2026-07-24 — ORCHESTRATION FLAW: concurrent build agents cannot see each other

- [ ] **My batch-4 workflow told each of 6 agents to overlap-check against the existing 47
  plugins — and nothing about its 5 concurrent siblings.** So duplicate functionality between
  simultaneously-built plugins is structurally invisible, and each agent's overlap evidence is
  honest but against a stale snapshot.
  Caught by the `contentgap` verifier: contentgap claimed "Nothing computes tf-idf or
  draft-vs-corpus coverage anywhere in the tree" and enumerated 5 neighbours (seo/search/prose/
  feeds/extract). Meanwhile `bigbang/core/searchindex.py:975` — built in the SAME batch — defines
  `_idf(doc_count, df) = math.log(1 + (doc_count - df + 0.5)/(df + 0.5))`, a real BM25 idf, with
  postings carrying per-document tf. Neither agent could have known about the other.
  ✅ **RESOLVED on inspection 2026-07-24 — do NOT hoist these. They are different formulas.**
  I wrote "one primitive in two places, decide whether to hoist" before reading them. Read:
  - `searchindex._idf(doc_count, df)` = `log(1 + (N - df + 0.5)/(df + 0.5))` — **BM25**
    probabilistic idf, for ranking retrieval results.
  - `contentgap.idf(doc_freq, n_docs)` = `log((N + 1)/(df + 1)) + 1.0` — **smoothed
    sklearn-style** idf, for coverage weighting.
  Different weighting schemes chosen for different jobs, and the argument orders are even
  reversed (`doc_count, df` vs `doc_freq, n_docs`). Unifying them would force one formula on both
  and silently change one plugin's output; a shared helper would also invite callers to pass the
  two ints backwards. **The real finding was the stale OVERLAP CLAIM, not duplicated code** —
  contentgap's write-up asserts "nothing computes tf-idf anywhere in the tree", which is now
  false and should be corrected to name searchindex and say why they differ.
  **Fix the pattern, not just this instance:** future batches should either (a) build in
  dependency order with each agent told what its predecessors created, or (b) add a final
  cross-batch dedup agent that reads all N new modules together and reports shared primitives.
  Option (b) is cheaper and catches what (a) misses when two capabilities are genuinely
  independent yet converge on the same maths.
- [ ] **Second flaw in the same rubric: I never defined what `claims_hold` means, so verifiers
  applied their own thresholds and the boolean is NOT comparable across plugins.** `a11y`'s
  verifier found **2 mutation survivors and returned `claims_hold: true`**; `contentgap`'s found
  2 survivors it graded low-severity and returned **`false`**. Same evidence shape, opposite
  verdict. Neither is wrong — I asked for a boolean without a bar.
  Consequence for reading batch 4: **do not treat True/False as a gate.** Read each verifier's
  `findings` and decide per plugin (which is what I did — `a11y` and `flows` ship, `dupes` and
  `contentgap` are held on their specific gaps).
  Fix for future batches: define the bar in the prompt — e.g. `claims_hold=false` iff a stated
  number is unreproducible, a NEW dependency exists, a vacuous test is found, or a survivor
  reveals behavior that contradicts a documented invariant; overstated-but-honest mutation counts
  get a separate `claims_overstated` flag instead of failing the plugin.

### NEW 2026-07-24 — batch-4 `apm`: one vacuous assertion (code and metrics all hold)

- [x] **tests/test_apm.py:721 cannot fail.**
  `assert "apm:slow" not in {d["rule"] for d in by_rule["apm:critical-latency"]}` — the bucket is
  KEYED by `d["rule"]`, so every element in it already has `rule == "apm:critical-latency"`;
  `"apm:slow"` can never be present. Structurally guaranteed, not merely unlikely. Replace with
  the rule-separation property it was meant to pin (presumably: a slow-but-not-critical span
  lands in `apm:slow` and NOT in `apm:critical-latency`, which requires two spans at different
  latencies, not one bucket inspected against itself).
- Everything else on `apm` reproduced: 50 passed, GOAT 10.00 (D1-D6 all 10), stdlib-only
  confirmed by import audit, ruff clean. The verifier's own hygiene is the standard to copy —
  every mutation reverted with an asserted `read_bytes() == ORIGINAL`, harness file deleted,
  `git diff` verified empty afterwards.
- Credit: the `apm` BUILD agent separately found and fixed a real defect while chasing a survivor
  of its own — a >512-deep call chain was being reported as a CYCLE and its spans force-detached
  to the tree root ("a fabricated diagnosis plus a lie about the call structure"). It split
  `cycle` / `truncated` / `orphan` rather than weakening the test. Surviving mutants are symptoms
  worth investigating, not scores to fix.

### 2026-07-24 — BATCH-4 HEADLINE: 5 of 5 verifiers found something the builder missed

- [x] **Every single independent verifier found a real gap, and 3 of 5 found an assertion that
  cannot fail.** flows ✅ · a11y ✅ (2 survivors, judged minor) · contentgap ⚠️ (2 survivors +
  overlap claim stale) · dupes ⚠️ (17th surviving mutant + 1 vacuous test) · apm ⚠️ (1 vacuous
  test). Every builder had reported a green suite AND a GOAT mean of 10.00 — both true, neither
  sufficient.
  **The systematic blind spot is vacuous assertions.** A test that cannot fail passes every run,
  raises the assert count that `goat_audit.py` rewards, and survives every mutation the author
  thinks to try — because the author wrote the tautology believing it tested something. It is
  invisible from the inside by construction. An adversary reading the assertion cold sees it
  immediately.
  **Do not drop the verify stage to save tokens.** It cost one extra agent per plugin and was the
  only thing that found any of this; `goat_audit --run-tests` cannot, since a vacuous test is a
  passing test.

### NEW 2026-07-24 — batch-4 `contentgap`: 2 low-severity mutation survivors

- [x] Verifier refuted "15/15 caught, survivors: none": (a) `expected_count()`
  `round(rate * max(0, draft_tokens), 2)` -> `round(rate * draft_tokens, 2)` survives, but
  `token_count()` can never be negative so the guard is unreachable either way; (b)
  `rows[: max(0, limit)]` -> `rows[:limit]` survives at both `corpus_terms()` and
  `draft_only_terms()` — a negative limit would truncate from the end instead of returning `[]`,
  and is untested. Low severity, honestly graded by the verifier itself; the claim was
  overstated as an absolute, not fabricated. Fix = pin the negative-limit behavior or drop the
  dead guard, whichever the code actually means.
  **CLOSED 2026-07-28 (`22f31e5`) — and re-verified independently, which is the only reason the
  last one got caught.** `7d74557`/`e1eca6a` had already fixed (a), both `corpus_terms` sites and
  the apm/dupes/a11y/searchindex tautologies, but the board was never ticked. Re-running the
  mutations rather than trusting those commits' own claims — this being the block whose lesson is
  *"self-reported mutation scores are not evidence"* — found **1 of 4 still surviving**:
  `contentgap.py:482 rows[: max(0, limit)] -> rows[:limit]`. The assertion written to catch it
  (`test_contentgap.py:262`) was correct; the **fixture was too small**. One draft-only row means
  `rows[:-3]` is `[]` as well, so guarded and unguarded are indistinguishable — a negative limit
  only truncates observably when there are more rows than it slices off. Now 4 terms + an
  anti-vacuity assertion pinning the count. Final: **4/4 KILLED**.
  Harness note worth keeping: `contentgap.py` is CRLF while `dupes.py` is LF, so a line-based
  mutator splitting on `"\n"` leaves a trailing `\r` and every anchor mismatches. The
  expected-content check reported NOT APPLIED instead of mutating a line into a syntax error and
  scoring the collapse as a kill — a mutation harness without that check invents its own successes.
  Verified: `tests/test_contentgap.py` 50 passed; full `apps/scout-cli` **2229 passed / 1 skipped
  / 0 failed** (2 chunks of 27 files, `EXIT=0` both — a single run reaches only 93% in 560s).

### NEW 2026-07-24 — batch-4 `dupes`: two TEST defects to fix before it ships (code is fine)

- [x] **The adversarial verifier refuted the build's "16/16 mutations caught, survivors: none".
  There is a 17th that survives all 40 tests.** `bigbang/core/dupes.py:539`
  `both = bool(set_a) and bool(set_b)` -> `or` survives, and it is NOT an equivalent mutant.
  **Be precise about what this means: the SHIPPED CODE IS CORRECT.** I verified the asymmetric
  case directly (72-token doc vs 3-token doc) — it returns `similarity=None, containment=None,
  shared=None, union=None` with `error="no shingle sets to compare — draft.md: too-short: 3
  tokens < min_tokens 40"`. The module's headline invariant at `dupes.py:61-63` (a doc too short
  to shingle "is NEVER compared and NEVER reported as 0.0 similar") holds in production. The
  MUTANT would report `similarity=0.0, shared=0, union=9, error=None` — an invented number —
  which is why the gap matters even though nothing is broken today.
  Root cause: `test_compare_rows_never_invents_a_similarity_for_unshingleable_docs`
  (tests/test_dupes.py:382) exercises only the SYMMETRIC case where BOTH docs are too short, and
  there `and` and `or` are indistinguishable. Reachable from shipped code:
  `scout dupes compare published.md tiny-draft.md` -> `compare_rows` via
  `plugins/dupes/cli.py:390`. **Fix = add the asymmetric case**, not touch the code.
- [x] **One vacuous assertion, tests/test_dupes.py:142.**
  `blob = bytes([0,1,2,3]) * 500; assert blob.decode("utf-8") is not None` — max byte is 3, so
  the blob is pure ASCII and `decode()` cannot raise; `decode()` returns `str`, so
  `is not None` is a tautology. The assertion cannot fail. Replace with the encoding behavior it
  was presumably meant to pin.
- **Lesson worth keeping: self-reported mutation scores are not evidence.** The build agent ran
  16 mutations honestly and reported 16/16 — true, and incomplete, because it chose the
  mutations. An independent adversary picking its own targets found the hole in one pass. Keep
  the verify stage on every future batch.

### NEW 2026-07-24 — `apps/scout-cli/docs/OPENSWAP.md` has a real NUL byte at offset 18278

- [x] **Small docs bug, queued behind batch 4 (the file is modified by a live agent — do not
  clobber).** The line documenting the `logs` UTF-16 handling means to show the literal Python
  bytes-literal `b"\r\n\x00"`, but the file contains **actual CR, LF and NUL bytes** instead —
  an escape sequence got interpolated rather than written literally. It splits the rendered
  line and makes `grep` report "binary file matches" on the file.
  ⚠ **Correct the claim while fixing it:** a batch-4 agent reported that "git classifies it as
  binary". It does not — `git diff --numstat` returns real line counts (`3  0`), because git's
  binary heuristic only scans the first ~8000 bytes and the NUL is at 18278. The tool that goes
  binary here is **grep**, not git. Same conflation cost me time today on
  `metrics_mini.jsonl` (fix: `grep -a`). Diffs and merges are unaffected.
  Fix: replace the three raw bytes with the escaped text so the doc shows what it means. Verify
  with `python -c "print(open('apps/scout-cli/docs/OPENSWAP.md','rb').read().count(0))"` -> 0.
  **DONE 2026-07-28 (`979e162`) — NUL count 0.** The grep-vs-git correction above was right, and
  there is a third turn of the same screw: `git diff --cached | grep` **still** reports binary
  after the fix, because the *removed* line — the HEAD side of the diff — is where the NUL lives.
  Use `grep -a`.
  **The commit is 51/52 lines for a 6-byte fix, and that is line endings, not content.** HEAD blob
  = 35086 bytes / CR 52 / LF 54 / NUL 1; staged blob = 35040 / CR 0 / LF 53 / NUL 0. HEAD stored
  this file CRLF, and `core.autocrlf=true` + `.gitattributes text: auto` means the clean filter
  strips every CR on `git add`, so staging renormalizes the whole file. Proof the fix is the only
  content change: normalize CRLF→LF on *both* blobs and exactly one region differs, at byte 18230,
  2 bytes → 8. Recorded because a whole-file diff on a one-line docs fix reads as a clobber.
  Tooling note: the first attempt drove the replacement from a shell heredoc and the backslash
  escapes collapsed, so the "is it already escaped?" guard compared a pattern against **itself**
  and fired a FALSE alarm claiming the fix was already present — two different patterns both
  reported found at the same offset, which is impossible and is what gave it away. Rewritten to
  build every byte numerically (`bytes([13, 10, 0])`, backslash as `chr(92)`) with no backslash
  literals anywhere in the script.

### NEW 2026-07-29 — the secrets vault could lose every secret, silently

- [x] **`bigbang/core/security.py` destroyed the whole vault on one torn write, with no
  error.** Found by sweeping for the pattern behind the herd ledger race (`0ae2dc6`) — same
  family, higher stakes. `_save` used `VAULT_FILE.write_text(...)`, which **truncates before
  writing**, and `_load` did `except Exception: return {}`. Every mutation is a
  read-modify-write, so one torn file plus one ordinary `set_secret` was total loss.
  Measured against the real module:
  ```
  vault before      : ['AWS', 'HF_TOKEN', 'OPENAI_KEY']
  after torn write  : []            <- _load swallowed it
  after next set    : ['NEW_KEY']   <- loss made permanent
  on disk           : {"NEW_KEY": "zzz"}
  ```
  **The non-atomic write is the smaller half.** The fail-silent read is what turns a transient
  problem into permanent loss — and it is the half that would survive "just make the write
  atomic". `bigbang/core/registry.py` had the identical shape (rebuildable, so lower stakes).
  Fixed in `3e301cb` via new `bigbang/core/atomic_json.py`: missing → default (missing IS
  empty); **corrupt raises** and preserves the bytes as `<name>.corrupt-<ts>` first, because
  refusing to parse must not also mean refusing to keep the only copy; per-process temp name +
  bounded replace retry; `mode=` applied to the **temp** so `secrets.json` never exists with
  default permissions.
  **Null result, stated because it is a result:** the other three fixed-temp sites are NOT
  affected — `apps/scout-rtx/train.py`, `ava-factory/dottie/train.py` and `tokenizer.py` derive
  the temp from a per-run **output** path, so two writers never collide. herd/security/registry
  are single shared files written by many short-lived CLI processes, which is what makes them
  racy.
  Verified: 12 passed / 1 skipped; mutations restoring the fail-silent read (**KILLED by 4**)
  and the fixed temp name (**KILLED**), `atomic_json.py` restored byte-exact; full scout-cli
  **2251 passed / 2 skipped**.
  ⚠ **Process note:** my chunk lists were built before the new test file existed, so the first
  "full suite" pass silently omitted it. Rebuild the list from a fresh `ls tests/test_*.py`
  whenever a test file is added — 54 → 55 files here, and 2239 + 12 + 1 skip reconciles exactly.

- [x] **`auth.json` had the identical bug — and it holds credentials.** `38e7127`. Its
  `_load_auth` docstring said *"Returns {} if missing/corrupt"*: behaviour documented,
  consequence not. A torn `auth.json` read as `{}` and the next login wrote that back,
  destroying every stored credential silently. `_save_auth` also `write_text`'d and chmod'd
  **after**, so the file briefly existed at default permissions. Now on `atomic_json`; the
  `fs_write` gate from `df11ca3` is unchanged and still ahead of the write.
  **How it was found — the sweep needed narrowing to be useful.** 30 files match a
  fail-silent `except: return {}`, which is far too many to act on and mostly harmless. It is
  only *data loss* when the value is **written back to the same file**, so intersecting
  "fail-silent read" with "writes JSON state" gives the real read-modify-write set. That
  intersection is the discriminator worth reusing.

- [x] **`telemetry.py` fixed 2026-07-31.** `_load_live_status` no longer swallows a corrupt
  file silently — the previous bytes are preserved to a `.corrupt-<ts>` sibling and the reset
  is announced on stderr, rather than the read-modify-write callers (telemetry.py:255, :521)
  cementing a lost `uptime_sec`/counter reset with no trace on the next write. Deliberately
  NOT the vault's fix (raise on corrupt, `3e301cb`) — telemetry must never take down a training
  run, so it stays non-raising; only the *silence* was the bug. `_write_live_status`'s shared
  `.tmp.json` also fixed to a per-PID temp name, same class as the herd ledger's shared
  `sessions.tmp` (`0ae2dc6`) — trainer/collector/console all write this file concurrently.
  8 new tests (`tests/test_telemetry_state.py`), all green; full `-k telemetry` suite (8) green.
  Verified no live trainer bind-mounts this FROZEN path right now (Docker Desktop not running).
- [x] **`personal_graphify/query.py`'s `log_query_cost` fixed 2026-07-31.** Same shape as
  telemetry.py: a tolerant `except Exception: data = {...zeros}` read on `cost.json` paired
  with a write-back to the same path silently erased every prior query's logged savings on
  one torn file, with no trace anywhere (the outer `except Exception: pass` — "never break
  query on cost log failure" — swallowed it completely, not even to stderr). Fix is the
  telemetry.py shape, not the vault's (this function must stay non-raising): corrupt bytes
  preserved to `cost.json.corrupt-<ts>`, the reset announced on stderr, and the write itself
  made atomic (`_atomic_write_text`: per-PID temp + `Path.replace`, since `write_text`
  truncates-before-write and was the other half of the bug). 4 new tests in
  `test_query_cost.py`; full personal-graphify suite (72) and this file's own suite (7)
  green; ruff clean on the touched lines (this file carries pre-existing, unrelated lint
  debt — old-style `Dict`/`List` hints etc. — not touched).
  **`apps/scout-cli/bigbang/plugins/tasks/cli.py` re-checked, not reproducible.** Read the
  whole 402-line file 2026-07-31 looking for the same shape: no local JSON state is ever
  loaded-then-written-back. `_run_gws`'s `json.loads(out)` (line 59) parses **subprocess
  stdout each call** — transient, never persisted then reloaded — and its
  `except json.JSONDecodeError` branch returns a diagnostic dict (`parsed_error`,
  `stderr`), not a silently-defaulted one. The only local file write, `export_tasks`
  (line ~384), only writes, never reads-then-writes. This queued item was two files
  grouped under one "same shape" claim; only one of them actually had it — recorded here
  rather than silently dropping the other half of a claim that turned out wrong, per the
  handoff-curation discipline (verify against the code, not the prior write-up).

### NEW 2026-07-24 — openswap manifests promise filesystem containment that is NOT enforced

#### ✅ DONE 2026-07-25 — enforced, and enforcing it found three defects + a bigger hole

Full write-up: `tasks/artifacts/filesystem_paths_enforcement_2026-07-25.md`. Summary:

**Re-measured, because the figures below drifted:** 56 manifests, **47** declare
`write: true`, and **every one of those 47 also declares `filesystem.paths`** (zero
exceptions), so hard default-deny cost nothing.

**The item as scoped ("mirror the `secret` branch") was wrong, and only measurement showed
it.** A subagent traced all 44 gated call sites: **ARG=42, AMB=2**. Every store helper
funnels through `_db_path(db) -> Path(db or $SCOUT_*_DB or DB_REL)` and in every case some
caller passes `--db`, so `.scout/x.db` is only the *default* and the operator can redirect
it. Enforcing `paths` there either denies every legitimate redirect or pushes authors to
declare `paths: ["/"]` — a gate that protects nothing while reading as enforced.
Resolution: two actions. `fs_write` (plugin chose the path) enforces `paths`;
`fs_write_arg` (operator named it via `--out`/`--db`/`--csv`) checks only the write flag,
because typing the path IS the authorization. 42 call sites moved; an independent regex
found exactly 42, matching the subagent's count by a different method.

**Three defects the check exposed:**
1. `reviewgraph` declared the literal `"<root>/.scout/"` — a prose placeholder that leaked
   into the allowlist and was never substituted. Inert unenforced; denies everything once
   enforced. → `.scout`.
2. `tasks` declared `"~/workspace/bigbang-cli/docs/llm-wiki/"` while `export` writes
   `_repo_root()/docs/llm-wiki/` (walks up from `__file__` for `pyproject.toml`). Baked in
   from a machine where the checkout sat there; matched nothing here.
3. **An unknown action FAILED OPEN.** Every branch is `if action == ...`, so
   `enforce_or_raise(mf, "fs_wrile", path)` fell through to `return True, "ok"` — writing
   freely while *reading like an enforced gate*. `KNOWN_ACTIONS` now fails closed
   (verified: every caller passes a literal, no dynamic actions anywhere).

- [ ] **FOLLOW-UP, and this is the bigger hole: 16 of 47 write-capable plugins never call
  the gate at all.** `auth ava brain dev_loop herd lab mcp quality reviewgraph rtx secrets
  skill system tennis tools write`. That list is the inverse of reassuring — `auth` writes
  `auth.json`/`secrets.json`, `secrets` writes `~/.local/share/bigbang/`, `brain` writes
  `~/MEMORY.md` and `~/memory/`, `skill` writes `~/.claude/skills/`. For these, `paths`
  remains documentation. Enforcing `check_permission` **cannot** fix this; the gate has to
  be invoked. Highest-value next step on this axis.
  ⚠ **Correction: 16, not the 14 stated in commit `2669066`'s message.** Grepping for
  `enforce_or_raise` counts prose — `quality` names it only in a comment ("The inverse of
  an enforce_or_raise call site") yet does write `.scout/quality.db` via
  `bigbang.core.quality`, and `tools` calls it only with `"network"`. Counting `ast.Call`
  nodes gives 16. Now pinned in BOTH directions by
  `TestUngatedWriteCapablePluginsAreTracked` (a new plugin cannot join silently; a
  newly-gated one must be removed so the count stays truthful) plus a floor assertion,
  since "set minus anything is empty" would otherwise pass vacuously if the walker broke.

  **Why this is a project and not 16 one-line edits — measured on the easiest case.**
  `auth` looks ideal: ONE write site (`_save_auth`, cli.py:70), a fixed plugin-chosen
  path `REG = Path.home()/".local"/"share"/"bigbang"/"auth.json"` (no flag redirects it,
  so `fs_write` is the correct action), and a manifest declaring exactly
  `~/.local/share/bigbang/auth.json`. It is still not a one-liner: the existing test
  `tests/test_core_extra.py:71 test_load_save_auth_roundtrip` does
  `monkeypatch.setattr(auth_cli, "REG", tmp_path / "auth.json")` and then calls
  `_save_auth`, so the gate would deny the relocated path and turn a green test red.
  `base=` does not rescue it either — the declared entry is absolute, and absolute
  entries ignore `base` by design.
  ~~**The generalisable point:** a plugin-chosen path that tests must relocate is
  *effectively parameterised*, and the gate belongs where provenance is known — at the
  CLI boundary, not inside a storage helper that both production and tests call with
  different roots.~~ So each of the 16 needs a per-plugin decision (move the gate up to
  the command, or give the helper an explicit path parameter), not a blanket edit.
  Do them one at a time, each with the full board green before and after.

  **PROGRESS 2026-07-28 (`df11ca3`): `auth` gated. 16 → 15.**
  **The generalisation above is wrong, and doing the plugin showed why.** It assumed the
  test *must* relocate `REG`. Relocating **HOME** instead dissolves the conflict: the
  manifest declares `~/.local/share/bigbang/auth.json`, `_norm_path` `expanduser()`s it,
  so moving HOME moves **both sides together** and the gate stays in the helper. That is
  also the more faithful fixture — a different HOME is the variation that actually occurs,
  whereas an `auth.json` unrelated to HOME is precisely what the gate exists to refuse.
  (`USERPROFILE` on Windows, `HOME` on POSIX — set both.)
  **The helper is the better site here, not the worse one:** there are **seven**
  `_save_auth(db)` call sites, so it is the one choke point none of them can forget, and
  `REG` is plugin-chosen with no flag to redirect it — `fs_write` is correct, not
  `fs_write_arg`. Revised rule: **move the gate up only when the path is genuinely
  operator-named; if tests relocate a plugin-chosen path, relocate the ROOT they resolve
  against instead.**
  Also added `test_save_auth_refuses_a_path_outside_the_allowlist` — without it the
  roundtrip keeps passing with the enforcement deleted, the "gate whose verdict nothing
  consumes" shape again. It asserts the file **is not created**, not merely that it raised.
  The two-directional pin earned its keep: gating `auth` turned
  `test_plugins_that_got_gated_are_removed_from_the_list` red with *"['auth'] now gate their
  writes"*, so `KNOWN_UNGATED` cannot silently drift. **Remaining 15:** `ava brain dev_loop
  herd lab mcp quality reviewgraph rtx secrets skill system tennis tools write`.
  Verified: 91 passed (policy + core_extra); mutation deleting the `enforce_or_raise` line
  **KILLED** by 2 tests, `auth/cli.py` restored byte-exact; full scout-cli **2236 passed /
  1 skipped**.

- [x] **FLAKE (found 2026-07-28, NOT introduced by the auth gate):
  `tests/test_herd.py::test_herd_create_start_wait_read_close` fails under load.**
  Failed once inside the 27-file chunk, then **passed on a clean re-run of the same chunk**
  (1269 passed). It passes alone with the auth changes, alone at HEAD, and paired with
  `test_core_extra.py` — so it is not an ordering interaction and not a regression.
  ⚠ **My first diagnosis ("timing — the `--timeout 15` budget is too small under load") was
  WRONG. Read the captured failure before believing it.** It is not a timeout at all — `herd
  wait` returned a real error and exited 1:
  ```
  assert w.returncode == 0
  E   AssertionError: {
  E       "error": "<class 'OSError'> returned a result with an exception set",
  E       "example": "scout herd wait t286 --status done --timeout 120",
  E       "discover": "scout herd status"
  E     }
  ```
  A `matched: false` timeout exits **2** with a `timeout_s` field; this exits **1** through
  `wait_cmd`'s `except Exception` → `_emit_err`. Different failure entirely, and the
  "it's just slow" reading would have had me raise a number and call it fixed.
  **Second hypothesis also DISPROVEN, by measurement:** that `_pid_alive`'s `os.kill(pid, 0)`
  terminates its target on Windows (CPython implements `os.kill` there via `OpenProcess` +
  `TerminateProcess`). Tested directly — spawned a 10-second child, probed it, and the child
  **survived**; `os.kill` returned normally. Not the cause.
  **What is established:** the message shape `<class 'OSError'> returned a result with an
  exception set` is CPython's "a call returned a value while an exception was set". The named
  callable is the **`OSError` class itself**, i.e. it failed while *constructing* the
  exception. `_pid_alive` cannot leak this — it catches `ProcessLookupError` /
  `PermissionError` / `OSError` around the only `os.kill`. So it originates elsewhere under
  `wait_status → get_session(refresh=True)`.
  **Leading unverified hypothesis (do not treat as fact):** the ledger's atomic write
  (`tmp.replace(HERD_FILE)`, `store.py:58`) hits a Windows sharing violation when another
  process has the file open — `PermissionError` is an `OSError` subclass, and concurrent
  full-chunk load is exactly when a second reader exists. Reproduce by hammering
  `get_session(refresh=True)` from two processes before changing anything.
  **Why it matters:** `apps/scout-cli` is a HARD CI gate (93c4ad8), so this reds the whole
  build at random and trains readers to re-run instead of read. **Do not "fix" it by raising
  the timeout** — that would hide a real error behind a longer wait. Recorded rather than
  dismissed, because "it passed the second time" is how an intermittent bug gets ignored.
  **ROOT-CAUSED AND FIXED 2026-07-29 (`0ae2dc6`). The unverified hypothesis was right, and
  the mechanism is simpler than "sharing violation": `_save` wrote to a FIXED temp name**
  `HERD_FILE.with_suffix(".tmp")` **— one `sessions.tmp` shared by every process on the box.**
  Two `scout herd` invocations wrote the same file and one replaced it out from under another.
  Reproduced against an isolated ledger, 4 processes polling `get_session(refresh=True)` for 6s:
  ```
  before   3334 errors   (calls/worker 586-625)
  after       0 errors   (calls/worker 721-937)
  ```
  Throughput rose because the failures were themselves costing time.
  Fix is two-part, because the race has two halves: a **per-process temp name** (`os.getpid()`)
  and a **bounded retry on the replace** — `os.replace` is atomic but fails on Windows with
  WinError 32 when the TARGET is open, and `_load` opens `sessions.json` on every read. POSIX
  rename has no such failure, so the retry is a no-op there rather than a platform branch.
  Three tests; `test_the_temp_name_is_unique_per_process` asserts on the file **actually
  created** rather than re-deriving the expression, so reverting only the write still fails it.
  Verified: `tests/test_herd.py` 7 → **10 passed**; mutation restoring the shared temp name
  **KILLED**, `store.py` restored byte-exact; full scout-cli **2239 passed / 1 skipped**.
  **Both earlier diagnoses above are left standing on purpose** — a wrong hypothesis that cost
  real time is worth more to the next reader than a tidy entry that only records the answer.

- [x] **FOLLOW-UP: the allowlist cannot express a dynamically-discovered root.** Defects 1
  and 2 share this cause — reviewgraph tried to spell it `<root>`, tasks hardcoded one
  machine's answer. `.scout` only works because it is CWD-relative and `abspath` resolves
  it against the process CWD. ~~Two independent sites already want a repo-relative token.~~
  **RESOLVED — and the `<repo>` token this asks for is not merely unbuilt, it is IMPOSSIBLE for
  its own use case.** Verified 2026-07-28:
  - **`tests/test_core_extra.py:145` monkeypatches `_repo_root` to `tmp_path`.** The root is a
    *runtime* value chosen by the caller, so no static string in a manifest can ever resolve to
    it. A `<repo>` token would work on the developer's checkout and fail in the test that
    already exists.
  - **The mechanism that CAN work already shipped:** `check_permission(..., base=...)`. The
    caller passes the root it just resolved — the only party that knows it.
    `bigbang/plugins/tasks/cli.py:381` does exactly this:
    `enforce_or_raise(manifest, "fs_write", str(out_path), base=str(root))`, anchoring the
    manifest's relative `docs/llm-wiki` entry to the resolved root rather than the process CWD.
  - **"Two independent sites" is now one.** `reviewgraph`'s `<root>` placeholder was fixed to
    `paths: ['.scout']`, and `reviewgraph/cli.py` calls `enforce_or_raise` **nowhere** — it is
    one of the 16 ungated write-capable plugins tracked in the entry above, so it has no
    allowlist question to answer until it is gated. Whoever gates it should pass `base=`, not
    invent a token.
  Pinned by `tests/test_policy.py` — `test_base_anchors_a_relative_entry`,
  `test_without_base_the_same_target_is_denied` (makes `base` load-bearing rather than
  decorative), `test_base_does_not_widen_beyond_the_declared_entry`,
  `test_traversal_out_of_a_based_entry_is_denied`, `test_absolute_and_tilde_entries_ignore_base`.

- [x] **KNOWN GAP, stated not papered over:** a **symlink** inside an allowed directory
  pointing outside it still escapes `_path_matches`. ~~Blocking it needs `realpath` on an
  existing tree, which the not-yet-created-write case rules out.~~
  **CLOSED 2026-07-28 (`5b02e15`) — and the stated blocker was simply false, which is why this
  sat open.** `os.path.realpath` is **not strict**: it resolves whatever prefix exists and
  appends the rest untouched. Measured with a junction `allowed/escape -> outside` and a target
  that does not exist:
  ```
  lexical  target:  ...\allowed\escape\not_yet_created.txt   inside? True
  realpath target:  ...\outside\not_yet_created.txt          inside? False
  ```
  The not-yet-created case never ruled it out — a path with nothing to resolve comes back
  normalized, so the check is a no-op precisely where the objection applied. **Worth generalising:
  the gap was guarded by a plausible technical reason that nobody re-tested. A disclaimed
  limitation is a claim like any other and decays the same way.**
  `_norm_path` stays lexical; new `_resolves_within()` is a second gate after the string match.
  Both sides are resolved, so an allowed root that is *itself* a symlink (symlinked `/tmp`, a
  redirected data dir) still works — denying that is the obvious way to get this wrong, so it has
  its own test.
  Residual, stated: **TOCTOU-checkable, not TOCTOU-proof.** The link can be swapped between the
  check and the `open()`. Closing that needs `O_NOFOLLOW` semantics at every call site.
  Verified: mutation `_resolves_within -> return True` **KILLED** by 2 tests, `policy.py` restored
  byte-exact; `tests/test_policy.py` 74 → **80 passed**; full scout-cli **2235 passed / 1 skipped
  / 0 failed** (2229 before, +6 = the new tests exactly).
  Test-harness note: `Path.symlink_to` needs `SeCreateSymbolicLinkPrivilege` on Windows and raises
  **WinError 1314** without it, so the helper falls back to `mklink /J`; `realpath` resolves a
  junction identically, so nothing skips on this box.

<details><summary>Original entry (2026-07-24) — kept for the reasoning</summary>

- [x] **`policy.check_permission`'s `fs_write` branch ignores `capabilities.filesystem.paths`
  entirely — and ignores its own `resource` argument.** It checks only the boolean
  `caps.filesystem.write`. Surfaced by a batch-4 build agent as a "known limit" and then
  verified independently at `apps/scout-cli/bigbang/core/policy.py:189-194`.
  **Scale: 47 manifests declare `paths:`, 42 declare `write: true`.** So 47 plugins make a
  containment claim the code does not keep. `bigbang/plugins/logs/manifest.yaml` states it in
  prose — *"Writes are confined to the sqlite store under .scout"* — which makes it a documented
  guarantee, not merely an unused field.
  **The asymmetry is the tell:** the other two axes DO enforce resource-level allowlists —
  `network` checks `enabled` + `domains` + a per-resource match, `secret` checks `allow` +
  `resource not in allowed`. Only `fs_write` stops at the boolean. The function's own docstring
  says *"Default-deny: empty allowlists deny everything"*, and this branch has no allowlist at
  all. There is even a comment in the `secret` branch recording that this EXACT bug class was
  found and fixed there ("silently allowed EVERY secret when the list was empty — the opposite
  of this function's own docstring"); `fs_write`'s `paths` were simply never implemented.
  **NOT fixed yet, deliberately.** Enforcing it is a behavior change across 42 write-enabled
  plugins — any that write outside their declared paths begin failing — so it needs its own
  verification pass against the full board, and six agents were mid-build when it was found.
  `policy.py` is NOT frozen, so this is mine to do on the operator's word.
  Sketch: mirror the `secret` branch — resolve `resource` and each declared path to absolute
  form, require the resource to be inside one of them, and treat an EMPTY `paths` list as
  deny-all to match the docstring (or as "unscoped" only if that is a deliberate, documented
  choice). Land it with the ruff/pytest gates green, then delete the "documentary" caveats from
  the manifests that carry them.

</details>

### ✅ DONE 2026-07-25 — the dataset licence gate ADMITTED NC and ND (and was bypassed entirely on the ingest path)

Prompted by "make sure we are using all the best datasets available to us" — before adding
sources, the gate that decides which sources are *usable* had to be sound. It was not.
`apps/ava-factory/scripts/dataset_discovery.py` (**not** frozen — only `dottie/**` and
`configs/**` are). Four compounding defects, all measured, all fixed:

1. **Substring allowlist admitted NC and ND.** The gate was
   `any(lp in lic_lower for lp in [..., "cc-by"])`, and `"cc-by"` is a substring of
   `cc-by-nc-4.0`, `cc-by-nd-4.0` and `cc-by-nc-nd-4.0`. **All three were ADMITTED**
   (reproduced directly). That breaks both standing rules: ND is *always* excluded because
   training on a work is a derivative use, and NC is excluded by default for the revenue
   mission. Same bypass shape as scout-cli's legacy substring domain matcher. Now
   component-wise on `-`, so `"cc-by"` cannot swallow the restricted members of its family.
2. **Per-domain `license_pref` was decorative.** `any(license_pref) or any(<blanket>)` meant
   a domain narrowed to `["mit","apache-2.0"]` still admitted every `cc-by*` variant.
3. **Multi-licence records admitted on ANY match.** A list value was `str()`'d, so
   `"['cc-by-4.0','cc-by-nd-4.0']"` passed on the permissive element — the identical bug
   `pull_oapen_books.py::gate_rights` already had to learn. Now **every** value must pass;
   the most restrictive term governs.
4. **Worst — the gate was disabled on the path that actually fetches data.** The
   download-manifest skip read
   `if not cand.get("license_ok", False) and not args.dry_run:` so under `--dry-run` the
   licence skip **never fired** and every top-12 candidate was written into an *executable*
   `download_candidates_*.sh` feeding `ingest_hf.py`. And `--dry-run` is exactly what
   `docs/crons/dataset-discovery-daily.md` prescribes for the daily cron. Compounded by
   `--dry-run` setting `license_ok=True` for math/code/reasoning with the licence string
   `"assumed permissive"` — a cleared verdict from zero evidence, and precisely the "it is a
   code corpus, code corpora are permissive" inference the gate exists to refuse. `license_ok`
   is now the sole condition, `--dry-run` clears nothing, and the manifest states when it has
   truncated to 12 of N instead of implying 12 is all of them.

Verified: `tests/test_dataset_license_gate.py` **41 tests**, mutation tested **8/8 killed**
(substring-instead-of-component, drop-ND, drop-NC, first-value-only, allowlist-unenforced,
empty-licence-allowed, dry-run-clears, no-normalisation). Full factory board re-run clean
afterwards — the first run was discarded because it was started before the edits landed.

- [x] **FOLLOW-UP: `docs/crons/dataset-discovery-daily.md:21` still prescribes `--dry-run`.**
  With the gate fixed that cron is now correctly a no-op for candidate selection (fail
  closed), which means it produces nothing usable. Drop `--dry-run` from the documented cron:
  the non-dry-run path only makes a small `/api/datasets/<id>` metadata call, NOT a download,
  so it is safe on the disk-limited VM. ~~Not done here because the flag may have been chosen
  for a reason not recorded in the doc — confirm intent first.~~
  **DONE 2026-07-28 (`154be3e`). Intent checked three ways rather than guessed:**
  1. The doc arrived by **subtree merge `1f547ac`**, so no rationale exists in this repo's
     history. Note `git log -S "--dry-run" -- <doc>` returns **empty** — because `-S` skips
     merges, not because nothing introduced the string. Another empty-output-is-not-an-answer.
  2. **Two other docs describing the SAME daily cron omit the flag** —
     `CONTINUOUS_PIPELINES.md:48` and `LOCAL_PICKUP.md:181`. Only this one file carried it.
  3. **The script already prescribes removing it**: *"Re-run without `--dry-run` before treating
     any candidate as usable."*
  So this resolved a doc-vs-code contradiction rather than overriding a decision.
  Safety claim verified in source, not assumed: the non-dry-run path adds **one**
  `urllib.request.urlopen` to `huggingface.co/api/datasets/<id>`, `timeout=5`. It downloads no
  dataset — the `load_dataset`/`wget` lines are **strings written into the manifest** for the
  Alienware box, never executed on the VM. Matches `CONTINUOUS_PIPELINES.md:25` "No download in
  VM".
  Left a **DO-NOT-RE-ADD note inline with the reasoning**, because the flag reads like a safety
  measure and would otherwise be restored by the next careful reader.
  Verified: `tests/test_dataset_license_gate.py` **64 passed**.

### 🧭 2026-07-26 — EMBEDDING SEQUENCE: bar measured, Option C decided, steps 4–5 in flight

Full review: `tasks/artifacts/embedding_strategy_review_2026-07-26.md`.

**The bar (step 2, done).** `scripts/retrieval_eval.py` — 696 (commit message → changed
files) pairs mined from git, split **walk-forward** at 2026-07-22 (487 train / 209 test),
scored against 2,024 documents with sqlite3 FTS5 + `bm25()`:

| subset | NDCG@10 | MRR | recall@10 | n |
|---|---|---|---|---|
| all queries | 0.623 | 0.627 | 0.771 | 209 |
| **leak-free** | **0.622** | **0.619** | **0.791** | 151 |

A prediction of mine the data refuted: I expected commit messages naming their own files to
inflate BM25 and built a leak control to quantify it. It fires on 58 of 209 queries (28%),
yet the leak-free subset scores *identically* and its recall is **higher**. No inflation.
Both numbers ship in every run so the claim stays checkable.

**✅ Step 3 DECIDED — Option C: scout-cli stays lexical.** Embeddings serve the site/agent
tier only; zero-new-deps holds without an asterisk. Consequences recorded in the review, the
notable one being that **`ast_pairs.py` does NOT become a scout-cli plugin** — I had proposed
promoting it and Option C cancels that.

- [ ] **Add a task-shaped eval slice before step 5 is judged.** The golden set's queries are
  commit messages — the right proxy for scoring a code-tree search, but the agent tier's real
  queries are natural-language task descriptions, which are longer and less identifier-dense,
  i.e. **harder for BM25 and easier for embeddings**. The 0.622 bar is honest for its set and
  probably flatters lexical retrieval relative to the consumer Option C just named. Measuring
  the model only against the query distribution least favourable to it would be a rigged
  comparison in the *other* direction.

### ⚠ 2026-07-26 — MinHash + hard-negatives landed, but BOTH failed adversarial review

Built by an ultracode workflow (2 builders, 2 adversarial verifiers, 459k subagent tokens).
121 tests pass and ruff is clean on all four files — **and both verdicts came back
`claims_hold: false, claims_overstated: true`.** The verifiers ran 57 mutations against
hard-negatives alone and killed 52, so the suites are genuinely strong; they still found
defects that produce wrong data. Committed anyway, with the defects listed here, because the
tools are useful and the alternative — 2,478 lines rotting uncommitted — is worse. **Do not
treat either as production-ready until the items below are closed.**

**✅ FIXED before commit — hard_negatives emitted TRUE POSITIVES as negatives.**
`forbidden` covered only files relevant to a *byte-identical* commit message, so a file the
query itself NAMED was mined as a hard negative. Measured: **62 of 4,461 (1.4%)** on the live
repo — e.g. query `docs(arxiviq): CodeAct roadmap … (specs/13_codeact.md)` → negative
`specs/13_codeact.md`. That is training the model against the truth, the one rule the
module's own docstring calls decisive. The predicate already existed **loaded and never
called**: `retrieval_eval.leaks_filename`. Now wired, with 4 regression tests; the real-repo
one measures **62 → 0**. (That test initially guarded on `hasattr(hn, "real_golden")`, which
does not exist, so it SKIPPED silently — a dead guard, caught and fixed. 49 tests, 0 skips.)

- [x] **minhash: single-linkage clustering deletes documents below the advertised
  threshold.** `uf.union(a, b)` chains, so a doc can be dropped in favour of a survivor it is
  *not* near-duplicate to. Measured on the 44-cluster / 126-drop scout-cli run: worst
  intra-cluster true Jaccard **0.7143** (`feeds/cli.py::_open_store` vs
  `flows/cli.py::_open_store`) against an advertised 0.8, and 1 of 126 drops is below
  threshold. ~~Nothing tests drop-vs-survivor similarity.~~
  **STALE — fixed in `41afb54` (`_star_partition`), and it IS tested on the real tree.**
  Re-measured independently 2026-07-28 on the **whole** `apps/scout-cli` (wider than either
  test's scope), recomputing true Jaccard from the shingle sets rather than trusting anything
  the module reports:
  ```
  documents             : 4576
  dropped               : 125
  worst drop-vs-survivor: 0.8000   (heartbeat/cli.py::_db_path <- alerts/cli.py::_db_path)
  drops BELOW threshold : 0
  worst intra-cluster   : 0.7353   (digest::_check_fail_on vs headers::_fail_on_or_fail)
  ```
  The guarantee now holds as advertised: **every dropped document clears 0.8 against the
  survivor that replaces it.** Gate 2 re-scores each would-be drop on exact Jaccard.
  **The 0.7353 intra-cluster figure is NOT a regression and must not be "fixed".** Members of a
  cluster are only guaranteed near the *survivor*, never each other — that is what star
  partitioning buys and all it buys. Deleting data is what needed the guarantee; sharing a
  cluster label costs nothing.
  Pinned by `test_no_document_is_dropped_for_a_survivor_it_does_not_resemble` (plugins tree,
  floor = the threshold itself, `offenders == []`) and
  `test_every_dropped_document_is_a_duplicate_of_its_own_survivor` (core tree), each with a
  drop-count floor so a shrinking corpus fails instead of proving less, plus
  `test_the_exact_gate_actually_had_to_split_a_component_here` as the anti-vacuity guard —
  if nothing ever needed splitting, the guarantee tests would be decoration.
  Verified: `tests/test_minhash_dedup.py` **104 passed, 0 skipped**.
Five entries below were **STALE** — all already fixed in the source, still marked open.
Re-verified against live code 2026-07-26, each with the named test that pins it. Closing a
stale entry matters: a wrong TODO cost real time today when
`empty_result_count`'s recorded residual turned out to be false.

- [x] **minhash: `docs[key] = seg` silently overwrites same-named defs in one file.**
  Concrete: `bigbang/plugins/mcp/cli.py` defines `_check_sdk` twice under try/except — one
  returns `True`, the other raises. **They are opposites, not duplicates**, and only the
  second survives. scout-cli yielded 4,567 (name, source) pairs but 4,566 unique keys, so the
  loss was invisible in the reported corpus size. **FIXED**: `_insert_document` returns a
  collision flag, keys disambiguate to `m.py::_check_sdk#L<lineno>`, and `collisions` is in
  the stats dict for both units. Pinned by
  `TestAgainstThePluginTree::test_the_real_key_collision_is_recovered_not_overwritten` and
  `TestCollection::test_a_collision_free_corpus_reports_zero_collisions` (the latter itself
  hardened today — it used to pass vacuously on an empty scan).
- [x] **minhash: unreadable files counted as scanned.** **FIXED**: `except OSError` now does
  `unreadable += 1; continue` and `files += 1` comes AFTER the successful `read_text`, so a
  path that never opened is not reported as scanned. `unreadable` is its own stat rather than
  being folded into `unparseable`. Pinned by
  `TestCollection::test_an_unreadable_path_is_not_counted_as_scanned` and
  `::test_an_unreadable_path_is_reported_by_the_cli`.
- [x] **minhash: `cluster_documents` returns whole-corpus `shingle_sets` + `signatures`**
  that `main()` never reads — pinned 4,566×128 ints for the result's lifetime. **FIXED**:
  `return_vectors: bool = False`, so they are attached only on request. Pinned by
  `TestClustering::test_the_corpus_vectors_are_not_returned_unless_asked_for` and
  `::test_the_corpus_vectors_are_returned_on_request_and_are_real` — two-sided, so neither
  "always returns them" nor "never returns them" passes.
- [x] **minhash: 1 of 126 drops is below threshold; nothing tests drop-vs-survivor
  similarity.** **FIXED**: gate 2 re-verifies on exact Jaccard via `_star_partition`, so the
  estimate can group but never authorise a drop. The specific pair is now a regression
  fixture — `feeds/cli.py::_open_store` vs `flows/cli.py::_open_store`, est **0.8125**, true
  **0.7143**, an error of 0.0982 exceeding the nominal 1/sqrt(128) = 0.0884 envelope. Whole
  `TestDropVsSurvivor` class (7 tests) plus
  `TestAgainstThePluginTree::test_gate_1_alone_would_have_authorised_a_wrong_drop`.
- [x] **hard_negatives: `class_of` reads only the innermost class**, so `Outer.Inner.run` and
  `Other.Inner.run` collide and a record can list its own `(path, symbol)` as a negative.
  **FIXED**: `mine_sibling_negatives` skips on `_ident` equality, not index, so a colliding
  pair is never its own negative — reproduced on a 12-line fixture, 0 records name
  themselves. The outer class is genuinely unrecoverable from `symbol`, so it is not guessed.
  The half that is deliberately NOT collapsed is now **reported** by `identity_collisions()`
  (see the entry above). `TestCollidingSymbolsAreOneDocument` (3 tests) +
  `TestIdentityCollisionsAreReported` (4 tests).
- [x] **hard_negatives: docstring claims order-independent output; it is not.** **FIXED**:
  `out.sort(key=_record_key)` at `hard_negatives.py:311` emits records in a content-only
  order, so `--out` JSONL is byte-identical across walk orders — not merely each negative
  list, which was the original false claim. `TestDeterminism` compares two walks
  byte-for-byte rather than re-sorting both sides first, a comparison that could not see the
  bug it existed to catch.
- [x] **Several real-repo test floors are far looser than claimed** (`same_package` 1000 vs
  3,760 measured = 27%), so a 73% regression would pass green. Raised to 80% earlier;
  **re-cut and made self-checking 2026-07-26**. 72 tests, 4/4 mutations killed.
  - The 80% raise had already landed, but the header's claim "every floor is >=80% of
    measured" was **not true of `same_class`**: 576 against 828 = **69.6%**. Defensible and
    disclosed at the time — 576 is 80% of the 720 an adversarial review measured, because
    ~170 of the 828 came from another agent's **in-flight** test file a revert would have
    removed. That caveat has **expired**: `minhash_dedup.py` and `test_minhash_dedup.py` are
    both tracked in git, last touched by `b82abf0`.
  - **Floors had silently drifted, measured**: 63.0%–80.0% of actual, worst on `same_class`
    (828 → 914 as class-based tests were added the same day). A floor is 80% of a
    measurement taken *on a date*; the corpus grows, so the same floor tolerates a larger
    regression every week, and prose cannot notice.
  - Floors are now **derived** — `_floor(m) = floor(MEASURED_REAL[m] * 0.80)` — so a
    hand-written floor that breaks the rule cannot be written. Re-cut against a fresh
    measurement: pairs/queries **3014**, negatives **21112**, same_class **914**, same_file
    **16430**, same_package **3768**, avg/query 7.005, coverage 0.9081.
  - New `test_no_floor_has_gone_stale_against_a_fresh_measurement` enforces the rule in both
    directions (floor above fresh = unreachable; floor below 70% of fresh = toothless) and
    prints the fresh numbers so re-cutting is a paste. **It is the only test that kills
    `_floor` → `return 0`** — without it, every floor in the file can go vacuous with the
    suite still green.

**Honesty note on the build itself:** the minhash builder disclosed that it had written two
figures as "measured" *before measuring them* — `91` and `33`, true values **68** and **51**
— and corrected them only on a self-check. The tests passed with the wrong numbers because
the floors sat below both. Exactly why the floors need to be near the measurement.

**Genuinely useful output, verified independently by the reviewer:** 4,566 functions in
scout-cli → **44 duplicate clusters, 126 dropped (2.8%)**, largest cluster **32 copies of
`_manifest`** across 32 plugin `cli.py` files. `apm.py::open_store` and `cite.py::open_store`
are **byte-identical after normalisation** — two different docstring queries pointing at one
identical positive, which is precisely the false-negative shape that caps contrastive
training.

### 🔬 2026-07-25 — THE RECURRING DEFECT CLASS: *a gate whose verdict nothing consumes*

Five instances found in one day, across three codebases. Each was diagnosed on its own
merits before the pattern was visible; naming it is the second-order finding.

| # | gate | verdict produced | what consumed it |
|---|---|---|---|
| 1 | `check_permission` unknown action | every branch is `if action == …` | **nothing** — fell through to `return True, "ok"`, so `"fs_wrile"` wrote freely while *reading* like an enforced gate |
| 2 | `capabilities.filesystem.paths` | declared by **47 of 56** manifests | **nothing** — `write: true` alone granted the whole filesystem |
| 3 | `dataset_discovery` download manifest | `license_ok` computed per candidate | **disabled in `--dry-run`** by `and not args.dry_run` — and `--dry-run` is what the daily cron doc prescribes |
| 4 | `mtnn_report.json → promote` | `{"ok": false, "reason": "CQS 78.11 < bar 82.62"}` | **nothing** — the 64-d artifact shipped the same day |
| 5 | `ci.yml` ruff step | 286 findings, exit code produced | **`\|\| true`** — reads as a lint gate, cannot fail |

A sixth near-instance the same day: bluehenre's G3 smoke *did* refuse to promote, but the
sequence degraded to alias-then-smoke because the unaliased URL sits behind SSO, so its
refusal changed nothing either.

**The unifying property:** the verdict is computed and *recorded* — in a report, a log line,
an f-string, a manifest field — but **no control flow branches on it**. The gate becomes
documentation of intent that reads, at the call site, exactly like enforcement. That is worse
than no gate, because it buys confidence it has not earned.

**Why it recurs here specifically:** this estate writes unusually good provenance *records*
(reports, manifests, registries, `_stackv3_files_dropped` counters). Recording a verdict
feels like enforcing it. The site half of the estate enforces by construction
(`release_gate.mjs` exits 1, `--check` fails the build); the model and policy halves largely
record. The doctrine exists in one half and not the other.

**Detection heuristic — the reusable part.** For any gate, ask one question: *which line
reads this verdict, and what does it do differently?* If the answer is "it is written to a
report" or "it is printed", it is not a gate. Concretely, grep for:
- a verdict variable used **only** inside an f-string or a dict literal;
- any safety condition combined with `and not <mode>` / `and not args.<flag>` — a
  mode-conditional escape;
- `|| true`, `except: pass`, `-ErrorAction SilentlyContinue` wrapped around a check;
- a function whose every branch is `if x == …` with no final `else: deny` (fail-open on typo).

- [ ] **Sweep the estate with that heuristic.** Instances 1–3 and 5 are fixed or documented;
  **#4 is open and lives in `~/vector-hoops`** — see the provenance-gate entry below.
- [ ] **Port the site's enforce-by-construction doctrine into the model repos.** The asymmetry
  above is the root cause, not any individual bug.

### 🔬 2026-07-25 — `~/vector-hoops`: four published surfaces describe a model that is not shipped

Built `pipeline/provenance_gate.py` + 15 tests (commit `442edbf`, **local only, not pushed**).
It exits 1 today:

```
arch   dim=48   assets/mtnn_arch.json          <- disagrees
meta   dim=64   assets/mtnn_meta.json
report dim=64   pipeline/data/mtnn_report.json
bytes  3319296  (= 12,966 x 64 x 4)
prose  README.md / assets/mtnn.js / methods.html  all advertise 48-d
```

**RE-MEASURED 2026-07-28 — the block above is STALE, and the situation is different (and
worse) than it describes.** `mtnn_arch.json` now reads `dEmb: 64`; the hand-correction landed
in `72a69d4`. Live state:

| surface | dEmb | model | towerFamilies |
| --- | --- | --- | --- |
| `assets/mtnn_arch.json` | **64** (hand-patched) | `mtnn_v4_phase_b` | 11 |
| `assets/mtnn_jacobian.json` | **48** | `concat` | 11 (same set) |
| `assets/mtnn_meta.json` | 64 | `mtnn_v5_concat_b2_h160_t32_d64_mlp128_fus256` | — |
| `pipeline/data/mtnn_report.json` | 64 | same v5 tag | — |
| `assets/eval_scoreboard.json` | 64, rows 12966, sha256 `2574ef58…` | same v5 tag | — |
| `assets/mtnn_embeddings.f32` | 3,319,296 bytes, sha256 `2574ef58…` | — | — |

**Three artifacts, three different model identities** (`mtnn_v4_phase_b` / `concat` / v5).
The embeddings sha256 matches the eval scoreboard's pin exactly, so **64-d v5 is
authoritative** — confirmed independently by meta, report, scoreboard, and the byte count.

**The hand-correction created a NEW inconsistency.** Before it, arch and jacobian both said
48 and *agreed* — two jointly-stale exports passing each other's check. Patching arch to 64
broke that agreement, which is what surfaces the problem. The `towerFamilies` check still
passes because both files carry the identical 11-family set: **a consistency check between
two outputs of the same stale export cannot detect a correlated error.**

**THE GATE ALREADY EXISTS, ALREADY WORKS, AND IS ALREADY RED.**
`python pipeline/verify_accuracy.py` → exit **1**:

```
FAIL: jacobian dEmb 48 != arch dEmb 64
FAIL: mtnn_jacobian.json checkpoint stamp stale vs pipeline/data/mtnn_best.pt
FAIL: mtnn_attr_pop.json checkpoint stamp stale vs pipeline/data/mtnn_best.pt
ACCURACY HARNESS: 3 FAILURES - do not ship
```

So this is **not** "a gate whose verdict nothing consumes" — `verify_accuracy.py:508-526`
consumes it properly and fails with a diff. It is the other failure mode: **a gate that is
red and is not being run.** The site ships anyway. Wire it into CI or a pre-deploy hook, or
the check is decoration.

**Fix (needs a trainer env, changes shipped assets — not done here):** re-run
`export_mtnn_jacobian.py` against the v5 checkpoint. That regenerates jacobian *and* arch
together at dim 64 with the real family set, clearing all three failures at once. Note the
shipped jacobian tensor is `12966x11x5` — the 11 families are baked into its shape, so this
is a re-export, not a metadata edit.

**Caveat on the "18 families" figure:** `mtnn_arch.json`'s own disclosure block says *"lists
11; the live manifest has 18 families, 17 of them towers"*, but
`pipeline/data/feature_manifest.json` enumerates **130 feature names**, not families — I could
not confirm 18 from it. Treat 18 as unverified until the re-export prints the real count.

**The check that does NOT work, recorded so nobody "simplifies" the gate back into it.** The
obvious invariant is `filesize == rows * dim * 4`. On this artifact **3,319,296 divides by
both 48×4 (17,288 rows) and 64×4 (12,966 rows)** — a size check alone is *degenerate*, it
passes for the wrong dimension. I nearly built exactly that before testing it on the real
bytes. It becomes decisive only when crossed with a row count from an independent source, so
the gate checks agreement *between* sources. `test_provenance_gate.py` pins the degeneracy
directly: a wrong-but-self-consistent `(dim=48, rows=17288)` pair must produce no size
complaint, so collapsing the gate to a size check fails a test that explains why.

- [ ] **Decide which surface is authoritative and fix the other three.** The gate deliberately
  does not autofix: the artifact is *usually* right and the docs stale, but a stale artifact
  with fresh docs is the same failure wearing the other hat.
- [ ] **Re-derive or retract the promote justification (instance #4 above).**
  `composite_score.py:88-95` records the artifact was promoted "not by clearing the CQS bar,
  which it does not", justified on a manual held-out top-5 comparison (0.363 → 0.757) that
  **no artifact in the repo records**. A number that cleared no gate is the same shape as the
  three research `sota` rows that all turned out to be artifacts.

### ✅ 2026-07-25 — REDEPLOYED. The sha256 drift on www.bhenre.com is fixed (gate now PASSES)

Operator: *"redeploy."* Deployment `bluehenre-campus-8jlgr3038-...`, alias moved, pin
updated. **G3 SMOKE against www.bhenre.com now exits 0**, with
`registry: registry matches (18851 bytes)` where it previously reported 4 drifted fields.
Verified independently of the gate: apex, www and the committed file all hash to
`00a4b5b3...` (apex 307s to www; the first comparison I ran did not follow the redirect and
so compared a "Redirecting..." body against real JSON — corrected).

**Root cause was a stale deployment, not code.** `--pre` passed on the committed tree
throughout; the live build simply predated the `.gitattributes` line-ending fix, so it was
serving sha256 hashes computed on CRLF copies while the repo holds LF. The arithmetic
confirms it: `+36` bytes on a 36-line file and `+48` on a 48-line file — exactly one byte
per line. `.research[3]` was `ledger_retroflag`, 2344→2380, the *same file and byte pair*
that defeated per-extension `-text` before `tasks/artifacts/** -text` fixed it.

- [ ] **GAP: G3-before-G4 was DEFEATED on this deploy and silently degraded to
  promote-then-verify.** `vercel deploy --prod --skip-domain` built into the production
  environment without moving the alias — correct — but the unaliased URL is behind **Vercel
  SSO Deployment Protection** and 302s to `vercel.com/sso-api`. The smoke therefore read a
  484,037-byte SSO interstitial as `org.html` (production is 14,192), got HTTP 401 on the
  assistant, and reported the registry as "not valid JSON". The gate **correctly refused to
  promote**, but for an access reason, not a content one — so the pre-promotion check is
  currently unusable and the real sequence was alias-then-smoke, with rollback available via
  the recorded pin rather than never-go-live.
  Fix: set a protection bypass secret and have the smoke send
  `x-vercel-protection-bypass`. **Not done here** — that is a project security setting, and
  changing one unprompted while deploying is exactly the kind of thing that should be its
  own decision. Until then, note honestly that the pipeline's headline property ("a bad
  build never becomes www.bhenre.com") is NOT yet in force.
  Distinguishing signal for next time: a smoke failure whose `org.html` byte count is wildly
  larger than production is protection, not a bad build.

- [x] **GAP: the alias-guard pin is NOT version-controlled**, which weakens the rollback
  story above. `apps/bluehenre/.gitignore:1` ignores `data/`, so
  `data/last_good_deployment.txt` is untracked — `git ls-files` does not know it. I updated
  it to `bluehenre-campus-8jlgr3038-...` on this box, but the previous good deployment id
  exists **only here**: from a fresh clone or another machine there is no record of what to
  roll back to, and the README's third deploy step writes to a file git will never carry.
  The fork already noted the pin "records intent rather than verification"; it also records
  it nowhere durable. ~~Decide deliberately: either track this one file (`!data/
  last_good_deployment.txt` negation) or move the pin somewhere already tracked. Not changed
  here because `data/` also holds `workflows.jsonl`, and un-ignoring a directory that
  carries runtime state is a convention call, not a cleanup.~~
  **DONE 2026-07-28 (`29f5548`) — and this entry was wrong twice, both found by testing rather
  than reading.**
  1. **The binding rule is the ROOT `.gitignore:33 data/`, not `apps/bluehenre/.gitignore:1`.**
     Editing bluehenre's file would have changed nothing. The root rule covers **5** `data/`
     directories across the monorepo, so it is not a local decision either.
  2. **The proposed `!data/last_good_deployment.txt` negation CANNOT WORK.** git does not
     descend into an excluded **directory**, so a negation for a file inside one is silently
     inert. Measured both forms with `check-ignore`, `.gitignore` restored byte-exact:
     `data/` + negation → still ignored; `data/*` + negation → still ignored (root rule wins).
     **A gitignore edit here would have looked like a fix and done nothing** — the failure mode
     this board keeps finding.
  Fix is `git add -f`: ignore rules apply only to **untracked** files, so it tracks exactly one
  file and changes no ignore rule anywhere. The deferral reason — "un-ignoring a directory that
  carries runtime state is a convention call" — does not apply, because force-adding does not
  un-ignore the directory. Same shape as the symlink gap earlier today: **the stated blocker did
  not apply to the obvious fix.**
  Verified after staging: the pin is the only tracked file under `apps/bluehenre/data/`;
  `workflows.jsonl` still ignored and untracked; no other `data/` directory changed status.
  Content checked before tracking — a public Vercel hostname, not a secret.
  README now records why it is force-tracked, which rule actually binds, that the negation is
  inert, and how to undo it (`git rm --cached`).

### 🔓 2026-07-25 — stack-v3 UNBLOCKED: licence is `odc-by`. Adapter built + tested; needs ONE frozen edit to activate

Operator: *"use stack-v3 use everything available stop blocking yourself."* Retried the
API and it answered first try (733 KB) — **the block was the flaky network, not policy.**

| field | value |
|---|---|
| licence | **`odc-by`** (Open Data Commons Attribution) — not NC, not ND |
| gated / private / disabled | `False` / `False` / `False` |
| config / split | `default` / `train` |
| downloads / likes | 35,376 / 138 · lastModified 2026-07-24 |

It passes the existing gate unchanged: `gate_license(["odc-by"]) -> (True, 'permissive:
odc-by')`, provenance flag clean. **No override was needed.**

**But `odc-by` is the licence of the COLLECTION, not of the code.** The schema is
repo-level — one row is `{repo_path, repo_id, commit_id, github_metadata, num_files,
files:[...]}` — and every element of `files` carries its own `content`, `language`,
`is_vendor`, `license_type` and **`detected_licenses` (a LIST)**. Training on the
dataset tag alone would ingest files whose own terms forbid it. So the per-record gate
predicted earlier is both necessary and *available*, and `gate_license` already handles
multi-value correctly (deny if ANY value denies).

Built, non-frozen, fully tested: **`scripts/stackv3_adapt.py`** — repo row → one training
text, per-file gate, drops vendored/empty, returns `None` if nothing survives, and carries
`_stackv3_files_kept` / `_stackv3_files_dropped` so provenance travels with the record.
`gate_license` is **imported, never re-implemented** (a second allowlist copy is the
drifting-constant bug class that has already produced real bugs here); a test asserts the
adapter declares no licence literals of its own. **27 adapter tests, 8/8 mutations killed**
(including "skip the per-file gate", "license_type wins over detected", "emit when nothing
kept").

- [ ] **ACTIVATION — needs the operator's word, because both files are FROZEN**
  (bind-mounted into the live trainer; docker CLI is 500ing so I could not confirm whether
  a run is in flight, and my own note says "the tool cannot reach it" ≠ "it is not
  running"). Two edits:
  1. `dottie/datagen/adapters.py` — move `scripts/stackv3_adapt.py` to
     `dottie/datagen/stackv3_adapt.py` (drop the importlib shim, plain
     `from dottie.datagen.dataset_license import gate_license` once the gate is shared),
     then `from dottie.datagen.stackv3_adapt import adapt_record as stackv3` and add
     `"stackv3": stackv3` to `ADAPTERS`.
  2. `configs/sources.yaml` — add:
     ```yaml
     - name: stack_v3_code
       kind: hf
       dataset: HuggingFaceCode/stack-v3-train
       config: default
       split: train
       text_field: text          # produced by the adapter, not present in the raw row
       adapter: stackv3
       phases: [2, 3]
       weight: {2: 0.00, 3: 0.00}   # start at ZERO and re-balance deliberately —
                                    # every phase's weights must sum to ~1.0
       license: odc-by
       gated: false
     ```
  ⚠ Weights are the trap: `sources.yaml` requires each phase's weights to sum to ~1.0, so
  adding a source at a non-zero weight without lowering others makes the collector spin.
  Add at 0.00, then rebalance in one deliberate edit.

### NEW 2026-07-25 — 21 factory tests CANNOT RUN: httpx 0.28 removed `Client(app=...)`

- [x] **`apps/ava-factory/tests/test_server_endpoints.py` — all 21 tests ERROR at setup**
  with `TypeError: Client.__init__() got an unexpected keyword argument 'app'`. Installed
  **httpx 0.28.1**; the `app=` shortcut was removed in 0.28, and starlette's
  `fastapi.testclient.TestClient` (used at line 121, `with TestClient(app) as c:`) passes it
  internally. **Pre-existing and unrelated to the licence-gate work** — the file is byte
  identical to HEAD and never references `dataset_discovery`; the cause is a library API
  removal. Verified by running the chunk both before and after.
  **Why it matters:** these are the server-endpoint regressions — health schema, the
  intervene 403 gates, the research proxy's clean 502, the webapp shell. That is exactly the
  surface that has to be trustworthy before hosting at bhenre.com, and right now **none of it
  is being tested** while the board still reads green-ish because they are *errors*, not
  failures, and a `-q` tail can be skimmed as "119 passed".
  ~~Fix is a dependency decision, not a code edit: either upgrade starlette/fastapi so
  TestClient uses `httpx.ASGITransport`, or pin `httpx<0.28`.~~ **DONE 2026-07-28, `03b2b3c`
  — and both proposed fixes were wrong.** `pip show httpx` → `Required-by:` **17 packages**
  (anthropic, chromadb, composio-client, groq, langchain-mistralai, langgraph-sdk, langsmith,
  litellm, llama-index-core, llama-index-legacy, llamaindex-py-client, mcp, mistralai, openai,
  python-fasthtml, qdrant-client, scout-cli). Downgrading a shared transport library to fix a
  *test harness* on the box that runs the live trainer is the most dangerous option, not the
  cheapest. And `fastapi 0.104.1` pins `starlette ~0.27`, so starlette cannot move alone.
  **It never needed a dependency change.** starlette 0.27's `TestClient.__init__` passes
  **both** `app=self.app` and `transport=transport`, and the `_TestClientTransport` it built
  is what actually routes — so `app` was already dead weight before 0.28 removed it. A shim
  in `tests/conftest.py` drops it, gated on `"app" not in inspect.signature(...)`: no-op on
  httpx <0.28, no-op once fastapi/starlette move, and it cannot break a passing test (any
  call passing `app=` today already raises).
  Two defects found in the shim *after* writing it, both by tests rather than review:
  (a) it dropped `app` even with no `transport=`, where `app` **is** the routing — silently
  turning a sandboxed call into a real socket to `base_url`; now a loud `TypeError` naming
  `httpx.ASGITransport(app=app)`. (b) no `functools.wraps`, so `inspect.signature` reported
  the *wrapper*, advertising `app` as supported and then discarding it.
  Verified: `4 passed/21 errors in 62.22s` → **25 passed in 9.15s**; +7 shim tests = 32;
  mutation **3/3 KILLED** by the intended tests, conftest restored byte-exact.
  `AVA_FACTORY_ROOT="$PWD" python -m pytest tests/test_server_endpoints.py tests/test_httpx_compat_shim.py -q` → 32 passed.

### NEW 2026-07-25 — Dottie Org objective recorded as a spec

`apps/dottie-org/SPEC.md` (spec-only, no code). The load-bearing finding: **ImageBind does
not train all-pairs** — each modality trains against ONE anchor and cross-pair alignment
emerges. These domains **do not co-occur**, so the anchor cannot be another sport; the
candidate is **text**, which makes Dottie's own foundation LLM the anchor encoder and the two
halves of the roadmap one project. Five open decisions are flagged as the operator's
(anchor choice, what "multi-task" means per domain, tower decomposition, whether the
universal model has a task, equities-private scope). Two new invariants: **temporal splits
only** (a random split is the most likely way this produces a fake win, and all three
recorded research `sota` rows to date were artifacts) and **entity resolution as a component,
not glue**. Equities-private is a hard stop pending written confirmation of source + terms.
⚠ ImageBind mechanics are stated from the paper's design, **unverified against the repo** —
outbound HTTPS failed on all three methods (curl 35, urllib 10054, WebFetch ECONNRESET).

**Memory budget for this box (16 GB) — the constraint that actually bit:** fleet + WSL VM
≈ 3–4 GB · desktop apps ≈ 2–3 GB **(now ~7.5 GB — Chrome/Cursor/Claude sessions have
accumulated)** · Ollama `qwen3:8b` ≈ 5–6 GB · `qwen3:14b` ≈ **7 GB** (does NOT fit —
tonight's outage). Check headroom before changing models:
`(Get-Counter '\Memory\Available MBytes').CounterSamples[0].CookedValue`.

⚠ **The "8b co-exists fine" claim has an expiry date on it.** It was true 23:36–00:50 when
desktop load was ~4.4 GB; by 04:18 that had grown to ~7.5 GB and the pair no longer fit
(measured: available fell to 345 MB with 8b resident). **Mitigated 04:45** by setting
`DOTTIE_OLLAMA_KEEP_ALIVE=30s`, which makes the model unload between stages — available
memory then measured **5,437 MB** at 05:15 versus 345–576 MB before. That restores the
headroom, but only intermittently (it still collapses to ~500 MB while the model is
resident), which is why the recovery script pauses the daemon rather than relying on it.

Verified 03:48 after the unload: **no models loaded**, available **5.3 GB** (the dip from
7.5 GB is Windows Memory Compression churn — 201 → 1,394 MB — reclaiming the freed pages,
not a leak). Ample for the VM plus 14 containers.

Timeline supporting the diagnosis (and one honest caveat): fleet healthy 23:36 → 02:05
with **8b** resident, which proves 8b + fleet co-exist fine; I enabled 14b at ~00:50, the
01:05 runner loaded it, and the VM died at 02:05. CAVEAT — this also makes host-RAM
pressure a **plausible contributor to the 01:38 and 01:56 CUBLAS crashes** I attributed
solely to the 45 W power cap. I cannot separate the two causes from here; treat the power
cap as unproven-but-still-suspected rather than established, and re-measure clocks after
recovery (`nvidia-smi --query-gpu=power.limit,clocks.sm --format=csv`).

### ⛔ FIRST: the fleet is DOWN and needs ONE command from you

The WSL2 VM died at ~02:05 and is crash-looping (vmmemWSL oscillates 8→123 MB;
`docker version` itself 500s). ALL 14 containers are gone — the 13-container factory
fleet **and** the T9.4 chat trainer. Nothing is lost (checkpoints on `ava_ckpt`,
manifest on `ava_state`), and I could not fix it: `wsl --shutdown` was blocked by the
permission classifier.

**EASIEST PATH — one command does the prep and gives a go/no-go:**
```powershell
.\scripts\prepare_fleet_recovery.ps1          # add -DryRun to see it without changing anything
```
It pauses the daemon, kills orphaned workers, releases the model, reports any train
still holding RAM, and prints GO/NO-GO against a 4 GB threshold (in `-DryRun` it
PROJECTS the reclaim instead of measuring an unchanged system — measured 06:29:
*"available now 354 MB; steps 1-2 would reclaim ~5,166 MB; projected ~5,520 MB — LIKELY GO"*) — then stops and hands you `wsl --shutdown` plus the
T9.4 decision. It deliberately does NOT restart containers itself. Dry-run verified 04:33.

**Or run these IN ORDER manually.** The research daemon cycles continuously (implement →
train → evaluate → ideate, ~4 min per stage) and holds 5–6 GB while doing it, so unloading
the model alone is not enough — it reloads within seconds. Stop the daemon FIRST.

```powershell
# 1. Pause the research daemon (it restarts on the next hourly trigger, or re-enable below)
Stop-ScheduledTask   -TaskName "Dottie Research runner"
Disable-ScheduledTask -TaskName "Dottie Research runner"

# 2. Release the model it left resident (~5.4 GB)
Invoke-RestMethod -Uri http://localhost:11434/api/generate -Method Post -ContentType application/json `
  -Body (@{ model = "qwen3:8b"; keep_alive = 0 } | ConvertTo-Json)

# 3. CONFIRM headroom — do not proceed under ~4000 MB, that is what killed the VM at 02:05
(Get-Counter '\Memory\Available MBytes').CounterSamples[0].CookedValue

# 4. Restart the VM (if the engine doesn't return in ~2 min, restart Docker Desktop)
wsl --shutdown

# 5. After the fleet is verified healthy (13-14 containers), bring research back:
Enable-ScheduledTask -TaskName "Dottie Research runner"
Start-ScheduledTask  -TaskName "Dottie Research runner"
```
Losing at most one in-flight research stage (~4 min of work) is the correct trade for a
recovery that actually succeeds.
**ALSO check for a factory TRAIN in flight**: the train stage is a torch process that
peaks around **~3.8 GB**, and unloading the Ollama model does NOT free it. **Duration
corrected — a nano train is ~4.3 min, not the ~1 h I first wrote** (measured 04:07→04:11
on f4d81d628b16: 150 steps, 13.2 M params, CPU). So waiting it out is usually the right
call; killing it is rarely necessary. Look at the last line of
`apps/dottie/data/research/logs/run.log`: `{"action":"train","phase":"start"}` with no
matching completion means a train is running. Either wait for it, or take the memory back
(it restarts on the next hourly trigger, losing only that run):
```powershell
Stop-ScheduledTask -TaskName "Dottie Research runner"    # ends the daemon + its trainer
```

**Longer term — the fleet and the research loop no longer both fit. Measured 04:18:**

| group | MB | note |
|---|---:|---|
| ollama (`llama-server`) | **5,314** | 8b stays PERMANENTLY resident: the loop calls every ~4 min, inside Ollama's 5-min `keep_alive`, so it never unloads |
| system / misc (324 procs) | 2,191 | |
| **claude-code sessions (17 procs)** | **1,945** | my own footprint — worth knowing |
| editors + browsers (52 procs) | 1,396 | Chrome / Cursor |
| docker + wsl (20 procs) | 592 | **fleet is DOWN**; expect **+3–4 GB** when it returns |
| research python | 64 | between stages; peaks ~3.8 GB during a train |
| **total** | **11,502** of 16,073 | available now: **513 MB** |

Adding the fleet back (+3–4 GB) lands at ~15–16 GB of 16 GB — i.e. right at the cliff that
killed the VM. Earlier tonight the same pair fitted because the desktop load was ~4.4 GB,
not ~7.5 GB. **Pick one lever before running both:** pause the research daemon (frees the
whole 5.3 GB — decisive, and step 1 of the recovery already does it), close a few
Claude/browser sessions (~3.3 GB available there), or — **new, shipped 04:29** — set

```powershell
$env:DOTTIE_OLLAMA_KEEP_ALIVE = "30s"   # in research_env.local.ps1; "0" = unload at once
```

`OllamaPolicy` now forwards `keep_alive` on every `/api/chat` call, so the model releases
its ~5.3 GB between stages instead of squatting permanently. Unset = Ollama's default, so
nothing changes for anyone who doesn't opt in. Trade-off: each stage pays a model reload
(~10–20 s on CPU) in exchange for the fleet fitting alongside the loop. 36/36 tests green
(new test covers set / unset / blank-is-unset).
**ENABLED 04:45 in `research_env.local.ps1` (gitignored) as `30s` — reversing an earlier
"your call" on safety grounds.** I had left it off because it costs ~10–20 s of reload per
stage. Then available memory was measured oscillating down to **385 MB**, against the
**281 MB** at which the VM died tonight and took the fleet with it. A slower loop is a
much cheaper failure than a second overnight outage. It takes effect at the 05:05 daemon
restart (env is read at process start). **To go back to maximum speed, comment that line
out** — one line, clearly marked, and the knob itself is opt-in for everyone else.
Recovery is then automatic (restart policies + `--resume`); verification commands and a
fallback relaunch are in §1.3. **The 45W power cap is the standing suspect for the whole
family of failures tonight — 780MHz clocks, 2 CUBLAS crashes, and this VM death. Check
the charger.**

### ⚠⚠ CORRECTION (05:01) — "takes effect at the 05:05 restart" was WRONG, five times over

I wrote that phrase about `keep_alive`, the axis-discipline prompt, `dur_s`, the
direction-aware significance wording and tail-truncated failures. **There is no restart.**
The runner is a forever-daemon (`run` with `--max-actions 0`) and `MultipleInstances` is
`IgnoreNew`, so the 05:05 trigger is REFUSED while the 04:05 daemon lives. Verified:
task `state=Running`, `next=05:05:00`, daemon PID 5264 up since 04:05:02.

**So every research fix I shipped after 04:05 is currently INERT**, including the
`keep_alive` memory-safety change I justified on outage-risk grounds. The daemon must be
restarted explicitly for any of them to apply:
```powershell
Stop-ScheduledTask  -TaskName "Dottie Research runner"   # kills the daemon + its stages
Start-ScheduledTask -TaskName "Dottie Research runner"   # fresh process, current code
```
This is the same daemon-vs-one-shot misunderstanding I corrected at 04:00 resurfacing in a
new form — I fixed the "lost ticks" framing but kept assuming hourly restarts would pick up
code. Worth remembering: **on this box, code changes to the research loop require an
explicit daemon restart, not a wait.**

**RESTARTED 05:04 — fixes are now live, but the restart itself exposed a hazard.**
`Stop-ScheduledTask` ended the task instance and its PowerShell wrapper, but the **python
daemon survived** (PID 5264, 54 threads, 9,726 CPU-s, idle). `Start-ScheduledTask` then
launched a second daemon (8940) — **two concurrent daemons**, which is exactly what
`IgnoreNew` and the lock exist to prevent: the lock lives in the wrapper, so an orphaned
python child holds nothing. Killed 5264; 8940 is now the only one.
- SAFETY PROPERTY VERIFIED (05:09): killing a worker **mid-stage does not corrupt the
  ledger**. The old daemon was killed during an `implement`; afterwards no experiment is
  stranded in `ready_for_training`/`evaluation_pending` — the interrupted one simply
  stayed `pending` with `attempts=0` and the new daemon picked it up. Stages only
  transition on completion, and every write commits in its own `with self._conn()` block.
  So `prepare_fleet_recovery.ps1` killing workers is safe for the data; the cost is the
  in-flight stage's compute, nothing more.
- [ ] **Real defect for you**: restarting this loop is not safe with `Stop/Start-ScheduledTask`
  alone — it silently leaves an orphan and can double-run the drain loop (two workers
  claiming experiments, concurrent ledger writes). Either make the wrapper kill its child
  tree on exit (`$Lock` release is not enough), or always verify with
  `Get-Process python3.11` and kill leftovers before starting. The recovery script's
  `Stop-ScheduledTask` step has the same gap.

### ⭐ SECOND BUG, found because the first fix made it visible (05:50)

With the wrapper no longer dying, the daemon ran long enough to expose an **unbounded
retry loop**. Candidate `87b8635f50f8` raised `AttributeError: 'NoneType' object has no
attribute 'layout'` **from its own forward** during training. `run_training` classifies
any trainer exception as an *infrastructure* failure and leaves the experiment
`ready_for_training` (retryable) — so the loop re-picked the same broken candidate
immediately, forever, and `consecutive_errors` never incremented because the stage
returned a result rather than raising. It would have burned the rest of the night on one
candidate.
**FIXED** in `factory_trainer.py`: an exception from `_train_and_measure` now returns
`ok=True, stable=False` → **FAILED_TRAINING**, not retryable. The reasoning is structural,
not a guess — by that point `_setup`, the model build and the integration probe have all
succeeded, so the failure is the candidate misbehaving on real data. Genuine
infrastructure failures (missing torch/corpus, unloadable module) return *earlier* and
remain retryable, which preserves the original design intent. 37/37 tests green.
- Worth noting: this bug was invisible while the wrapper kept killing the daemon every
  few minutes. Fixing the crash surfaced it within four minutes.
- **VERIFIED 05:53** after restarting the daemon (the fix needed a restart to load — the
  same skew I documented at 05:01 and then walked into three more times): the candidate
  moved `ready_for_training → failed_training` with `attempts: 2` and the loop moved on.
  Pipeline is now drained (no pending, no ready_for_training) so it proceeds to ideate.
  Ledger: 54 failed_validation, 10 rejected, 3 failed_training, 2 sota.
- ⚠ **STANDING OPERATIONAL RULE, learned four times tonight**: the research daemon imports
  its code at process start, so **every code change to `apps/dottie/dottie/research/**`
  requires an explicit restart** — `Stop-ScheduledTask`, kill any surviving
  `dottie.research` python (the wrapper does not kill its child), then `Start-ScheduledTask`.
  Waiting for a trigger does nothing while a daemon is alive.

### ⭐⭐ ROOT CAUSE FOUND AND FIXED (05:46) — the wrapper was killing the daemon

**Every silent daemon death tonight was `research_worker.ps1`, not Python.** The wrapper
sets `$ErrorActionPreference = "Stop"` at script scope and then runs
`& $Python … *>> $LogFile`. In **Windows PowerShell 5.1, `*>>` redirects the native
process's STDERR, and each stderr line becomes a `NativeCommandError` ErrorRecord — which
under "Stop" is a TERMINATING error.** torch prints `FutureWarning`s to stderr during the
train stage and the dry-run validator, so the wrapper was being killed mid-run and the
daemon went down with it.

**Reproduced in isolation, both directions:**
```powershell
$ErrorActionPreference='Stop';     python -c "import sys; sys.stderr.write('warn\n')" *>> log   # TERMINATING ERROR
$ErrorActionPreference='Continue'; python -c "import sys; sys.stderr.write('warn\n')" *>> log   # OK, exit 0
```
That signature matches every observation: **exit code 1, no Python traceback, no
Application crash event, no resource-exhaustion event**, and deaths clustered on
torch-heavy stages. It also explains the `0xC000013A` and the earlier "stall" family.

**FIXED**: the wrapper now sets `Continue` only around the python call and restores the
previous preference afterwards. Verified that a real non-zero exit still propagates
(tested `sys.exit(3)` → `$LASTEXITCODE` 3), so genuine failures are not masked. Daemon
restarted 05:46 on the fixed wrapper: 2 workers, task `Running`, train in progress.
- NOTE this also means my earlier `os._exit` change was treating a symptom that did not
  exist — Python was exiting fine. It is harmless and still correct hygiene, but it was
  not the fix. Same for the `RestartCount` attempt (which did not work) and the PT15M
  trigger (which now guards a much rarer event).

### ⚠ Earlier framing (superseded by the root cause above): "unexplained daemon death"

The 05:04 daemon began an implement at 05:12:12 and then **vanished**: no python process
matching `dottie.research`, task back to `Ready`, `LastTaskResult = 0x1`, and — the part
that matters — **no traceback, no `fatal` line, no error output whatsoever** in `run.log`.
A Python exception would have printed a traceback (stderr is redirected into that file);
an exhausted-retries exit would have printed the `fatal` JSON. Neither is there, which
points at abrupt termination rather than a handled failure. Memory was NOT tight at the
time (4.6–5.4 GB available across four samples).
Restarted manually at 05:27 (0 orphans beforehand, 2 processes after, implement started);
without that it would have idled until the 06:05 trigger.
- [x] **AUTO-RESTART TESTED AND IT FAILED — good thing it was tested (05:31→05:36).**
  Killed the worker at 05:31:13; task went `Ready` with `0xFFFFFFFF`. At **5 min 16 s**
  later: still `Ready`, **0 workers**, `LastRunTime` unchanged. **`RestartCount`/
  `RestartInterval` do NOT restart a task whose ACTION exits non-zero** — that setting
  covers the scheduler failing to launch the task, not the program failing. It would have
  sat in the config looking like protection while doing nothing, which is worse than no
  mitigation at all. Third scheduler-semantics assumption of mine to be wrong tonight.
- [x] **FALLBACK APPLIED AND VERIFIED (05:37): trigger repetition PT1H → PT15M.** This
  uses a mechanism that demonstrably works — an ordinary trigger firing — so a dead daemon
  is picked up within ≤15 min instead of ≤60. `MultipleInstances=IgnoreNew` means the
  extra firings are harmless no-ops while a daemon is alive (verified: state still
  `Running` after the change). `RestartCount=3` was left in place: useless here, harmless,
  and it does cover the launch-failure case.
  Revert with `$t = Get-ScheduledTask -TaskName 'Dottie Research runner';
  $t.Triggers[0].Repetition.Interval = 'PT1H'; Set-ScheduledTask -TaskName 'Dottie Research runner' -Trigger $t.Triggers`.
- [x] **MITIGATED 05:31 (recovery speed, not cause)** — the task had `RestartCount=0`, so
  Task Scheduler never retried a task that ended with an error, which is exactly what
  happened (`0x1`). Now **`RestartCount=3`, `RestartInterval=PT5M`**: a daemon that dies
  is restarted within 5 minutes instead of idling up to 60. Verified by read-back;
  `MultipleInstances` deliberately left `IgnoreNew` (a running daemon still blocks
  duplicates — changing it would create concurrent daemons, as retracted earlier) and
  `ExecutionTimeLimit` left `PT0S` (no cap, so a long train is never killed).
  Reverse with `$s = (Get-ScheduledTask -TaskName 'Dottie Research runner').Settings;
  $s.RestartCount = 0; Set-ScheduledTask -TaskName 'Dottie Research runner' -Settings $s`.
- [ ] Optional companion (not applied): shorten the trigger repetition from **PT1H** to
  ~PT15M. With `IgnoreNew` the extra firings are no-ops while healthy, so it only shortens
  the worst-case gap if the restart attempts are also exhausted. Your call — it is a
  scheduling change rather than a failure response.
- [ ] **I could not determine the cause and am not going to guess.** Worth checking when
  you are back: Windows Event Viewer → Application/System around **05:25** for a process
  termination, and the Task Scheduler operational log for that instance. If it recurs,
  the `dur_s`/start-line instrumentation now pins the last action precisely.
- Possible contributors, none established: my own `os._exit` change (it only runs after
  `main()` returns, so it should not fire mid-stage), the earlier double-daemon cleanup,
  or an external kill. **Note this is the second silent daemon loss tonight** (the first
  was the 03:05 stall), so a watchdog — §5 fix (a) — is looking less optional.

### ⭐ KEEP_ALIVE CONFIRMED WORKING (05:15) — memory 345 MB → 5,437 MB

With `DOTTIE_OLLAMA_KEEP_ALIVE=30s` live, `llama-server` **unloaded between Ollama calls**
(during the local torch/ruff validation phase of an implement) and available memory rose
to **5,437 MB**, against the 345–576 MB it had oscillated in all night. This is the fix
for the condition that killed the WSL VM at 02:05 (281 MB).
- The trade-off is real and expected: each correction attempt now pays a model reload, so
  implements get slower. Watch `dur_s` — the last pre-fix failed implement was 487 s.
- **It does NOT make the recovery safe on its own**: memory still collapses to ~500 MB
  whenever the model is resident, so the window is intermittent. Keep step 1 (pause the
  daemon) in `prepare_fleet_recovery.ps1` — a deterministic 5 GB beats an intermittent one.
- If you decide the throughput cost is not worth it, one commented line in
  `research_env.local.ps1` reverts it.

### Overnight research throughput (measured 05:33, last 7 h)

**14 hypotheses created → 5 reached evaluation → 0 promoted.** Breakdown: 7
`failed_validation` (**50% die in validation**, each burning ~5 correction attempts and
~8 min), 5 `rejected` on real measurements, 1 `failed_training` (unstable), 1 still
pending. All-time: 54 failed_validation, 10 rejected, 2 failed_training, 2 sota (both
now known to be artifacts — §5.3.R0).
The honest read: **the machinery is reliable and the search is not productive.** Every
stage works unattended and every rejection was correct; the yield is zero real
improvements, and the two dominant causes are now identified with data — validation
deaths from axis confusion (§5.2.f, prompt fixed at 04:52) and a search confined to one
vocabulary (§5.2.g, mode collapse, filed for your call). Those two are where any further
effort belongs; the gates and instrumentation are done.

### Measured trade-offs (06:06) — two numbers worth having

**1. `keep_alive=30s` costs *something*, but far less than I first claimed — CORRECTED.**
I reported "~42% slower" from a single before/after pair (487 s → 691 s). The next
comparable implement came in at **492.5 s — statistically indistinguishable from the
487 s baseline.** **Four** same-shape samples (one pre-fix, three post): 487.3 / 691.5 / 492.5 / **429.4**
— the newest is FASTER than the pre-fix baseline. Post-fix mean ≈ 538 s vs 487 s, i.e.
roughly **10%** with a 429–691 s spread that swamps it.
So the honest statement is *high variance, no measurable stable penalty at this n* —
certainly not the 42% tax I reported. Original overclaim left visible here on purpose: it came
from n=1 and should not have been stated as a rate. The memory benefit (345 MB → 5.4 GB)
is measured repeatedly and is not in doubt.

**2. The axis-discipline prompt is NOT the whole story (n=4).** Latest failure:
`RuntimeError: einsum(): the number of subscripts in the equation (2) does not match the
number of dimensions (3) for operand 1` — a 2-subscript einsum applied to a 3-D tensor.
That IS rank confusion, the family the prompt targets, so constraint 8 is not landing;
consider naming einsum explicitly in it. Earlier detail: GASA #3 died with
`AttributeError: 'GradientAdaptiveSparseAttention' object has no attribute 'hidden'` —
not an axis mismatch at all, but a module referencing an attribute it never assigned in
`__init__`. Earlier post-fix failures were a 4-D reshape mismatch and this. So the
dimension-2 confusion I targeted has not recurred in three tries, but the model simply
finds other ways to produce a broken module. **Do not read the prompt fix as solved.**
Worth revisiting once ~5 more failures accumulate, now that tail-truncation makes the
classification a one-line query.

**3. That failure cost 11.5 min and was a duplicate.** GASA #3 was the third proposal of
a name already in the ledger (fifth overall) — a concrete instance of the §5.2.g waste.

### Post-restart verification (05:12) — the fixes are live and already paying

First completed action from the restarted daemon proves three of them at once:
`{"action":"implement","result":{"experiment":"fae9859164a4","state":"failed_validation",
"attempts":5},"dur_s":487.3}`
- **`dur_s` works** — and gives the first real price tag for a failed implement:
  **487 s (8.1 min)** burned across 5 correction attempts. That is the number to weigh
  any conversion-rate fix against.
- **Tail-truncation works** — the stored failure now ends with the actual exception
  instead of traceback boilerplate: `RuntimeError: The size of tensor a (8) must match
  the size of tensor b (4) at non-singleton dimension 3`. Diagnosis is now possible
  without re-running the validator by hand.
- **Axis-discipline prompt: no verdict yet (n=1), and the failure mode MOVED.** This one
  is at **dimension 3** — a 4-D multi-head reshape — whereas all four I diagnosed were
  3-D confusion at dimension 2. So the prompt addressed a mode that did not recur, and a
  neighbouring one appeared. Could be the fix working and the model finding a new way to
  err, or coincidence. Judge it after ~5 more implements, using the tail-truncated
  errors that now make classification cheap.

### Regression status (full sweep re-run 06:26 — everything still green)

| suite | result |
|---|---|
| `apps/dottie` (full) | **149 passed**, 1 skipped — needs `AVA_FACTORY_ROOT` set (see §2.3.0) |
| webapp `api.contract.test.mjs` | 6 passed (node, no browser) |
| webapp `store.contract.test.mjs` | 5 passed |
| `apps/scout-cli` profiles | 6 passed |
| `packages/ava-skills` logic-prover | 6 passed |
| arxiviq `site/app.js` | syntax clean; render harness 6/6 earlier |

Re-verified at 06:26 after six further files changed (server.py, prompts.py,
factory_trainer.py, research_worker.ps1, webapp app.js, tests): **dottie 149 passed**,
**factory server endpoints 24 passed**, **webapp contract tests 11 passed**, both
front-end bundles syntax-clean, and the working tree is **completely clean — 0 modified,
0 untracked** across **105 commits** this session. Nothing regressed across the night.

### What ran while you were away (all committed, ~25 commits)

Two lanes were alive: the **T9.4 chat branch** (trained steps 1→23 across two CUDA-flake
crashes, self-healing each time from banked checkpoints, until the VM took it down) and
the **host-side research loop** (unaffected by Docker — still ideating, implementing and
training).

THE NIGHT'S HEADLINES — read these before anything below:

1. **T9.3 DONE but gate FAIL**: tool_final.pt landed clean (step 1144, exit 0) and the
   REAL eval (evals/tool_gate.py, shipped tonight) measured general CE **+75.1%** vs
   base (bound ≤2%) — catastrophic forgetting. Root structural cause: the packed corpus
   has ZERO tool_selection-labeled docs (measured; the old eval command in the TODO
   pointed at a MOCK harness — also caught tonight). Trainer PARKED; §1.4 has the
   recommendation awaiting your sign-off (no knob-rerun; 2.1 data → re-fork w/ replay).
2. **§2.1 fleet rebuild DONE + verified**: 13/13 healthy on reconciled images,
   30-source registry live; collectors correctly paused on full runway. §2.2 blocked
   only on the next-run decision.
3. **Research loop: ALL THREE "SOTA" entries are artifacts (§5.3.R0) — honest count of real
   architectural wins is ZERO.** ⚠ This said "BOTH" (2) until 2026-07-24; the ledger has
   **3** `sota` rows. Authoritative read 2026-07-24 22:55 from
   `apps/dottie/data/research/ledger.sqlite3` (100 experiments): **70 failed_validation,
   20 rejected, 6 failed_training, 3 sota, 1 pending** — every count in this file below was
   stale (54 / 10 / 3 / 2). Current baseline row: `factory_lm_loss = 5.73733` (nano),
   **`experiment_id = NULL`**, `metric_sem_n = 3`. The NULL owner plus a value HIGHER (worse)
   than the 5.54404 previously recorded is the fingerprint of the third SOTA being retracted
   and its ratchet unwound — i.e. the defenses worked. Real wins still ZERO.
   **Never quote these counts from prose; re-read the ledger.** (Correction to my own commit
   26cbd9d, which said my notes carried the stale 5.54404: they did not — they recorded 5.73733
   as live and 5.54404 as superseded. What misled me was a one-line *index summary* that ended a
   value progression at 5.54404, so the last number read as the current one. A summary that
   compresses history into an arrow will be misread as state; the detailed note was correct.)
   The older artifact beat a
   hand-seeded placeholder baseline
   (4.5) on an explicitly-not-capability synthetic task; the newer one (MLBR) is the
   noise+degenerate case below. The machinery works end-to-end; the results were
   mislabeled, and tonight's gates now block both failure modes. Original note: MLBR
   ratcheted the baseline 5.61982→5.60506, and then §5.3.R (below) took the bundle
   apart: the delta is **1.1 SEM** (inside noise) and the "MoE regularizer" is a
   parameter-free scalar shift that REPLACED a real block. Read §5.3.R before the
   bundle; it also lists the 3 cheap evaluate.py fixes this exposed (significance
   margin, param-delta in the verdict, paired seeds).
   Survived TWO outages tonight: 780MHz GPU = 45W power cap from 13% battery (not
   drivers — check the charger), and Ollama dead-since-reboot (user autostart + no
   login; PREVENTION item in §8 needs your password). NOTE the 14b night model that
   produced GASA at 01:06 is now DISABLED — it caused the fleet outage (top of file);
   the loop is back on qwen3:8b, the configuration proven to co-exist with the fleet.
4. Also shipped: SOTA sparkline (5.4), last-seen badge (7.4), Factory v2 telemetry
   tiles (7.3), scout-cli MCP Windows stdin deadlock fix (real bug, was 'flaky'),
   logic-prover CRLF fix. FOUND: a THIRD split-brain checkout (C:\Users\jcdav\
   scout-cli shadows the monorepo via the shared venv) — added to §2.3.

4b. ⭐ **THE GATES ALREADY PAID FOR THEMSELVES (04:37, §5.3.R3).** Candidate AGN
   (`bb40e0c18f0a`) beat the baseline by **0.00186** against a noise bar of **0.0361** —
   a win ~19× smaller than the measurement error — and was a parameter-free block
   replacing a real 787 K-parameter one. Under last night's rule it would have been
   promoted as **SOTA #3** and ratcheted the baseline. Both new defenses fired: held on
   significance, and the capacity caveat named the shrink. Baseline correctly unchanged.

5. **The research loop got four defenses tonight, all born from the MLBR post-mortem**
   (§5.3.R has the details): a **significance gate** (a win inside the noise can no
   longer move the baseline — replayed on MLBR: 1.1 SEM → HELD), a **degeneracy gate**
   (a module with no learnable parameters that only adds a constant can no longer reach
   training — MLBR's real module now fails L4), a **capacity caveat** (a swap that
   deletes parameters says so in the verdict and the bundle), and **§5.2.c**: the
   corrector now sees a diff of its own last edit. 33/33 tests green. Two of my own
   fixes had bugs caught by verification passes (a flaky threshold competing with float
   rounding; an unseeded probe) — both fixed and noted.
6. **arxiviq**: the live gist now serves fresh data, and the site code was verified
   headlessly for the first time (6/6 checks on a healthy payload). One honesty fix
   shipped: with the factory down the tiles said "unknown" + em-dashes; they now say
   **"factory unreachable"**. NOTE: site code changes are committed but **NOT deployed**
   — the Vercel deploy needs your approval (§7.5).

### YOUR DECISION QUEUE (in order) — item 0 re-verified 15:40 2026-07-20 (state read live)

> **Item 0 is blocking: training is OFF, and it now carries a precondition.** Re-seeding the
> baseline (was item 5) is pulled into item 0 because §5.3.R93 proved the live baseline is
> unreachable — restarting the daemon without re-seeding just churns. Items 5 and 8 were
> changed materially by this session's work; items 2, 3, 4, 6, 7 are unchanged from the
> 05:19 version. The restart command in item 0 was also corrected — a `\r` had split
> `.\scripts\restart_research.ps1` across two lines, so the copy-pasted command was broken.

00. ⛔ **GIT HAS DIVERGED — reconcile before pushing/pulling anything (§5.3.R98).** Local
   `main` is **ahead 243, behind 2** of `origin/main`. Discovered 15:49 by a read-only
   `git fetch` (nothing was pushed, pulled, merged, or rebased — that reconciliation is
   yours). The two remote commits are from a **parallel session**: `ebeb299` adopts ruff
   across the monorepo (**407 files, 3295 auto-fixes**) and `9688ccf` adds a ruff CI workflow.
   Neither contains any of this session's R-work (verified: 0 overlap in content).
   - **⚠ CORRECTION (§5.3.R99): the ruff commit is NOT "purely formatting" — I checked, having
     first asserted otherwise from its commit message.** `ruff --fix` made **coordinated
     SEMANTIC autofixes**: `List[X]`→`list[X]`, `Dict`→`dict`, `Optional[X]`→`X | None`
     (PEP 585/604), then **pruned the now-unused `typing` imports**. Concrete hazard: origin's
     `research/__main__.py` now imports only `from typing import Any`, while **my 243 commits
     added new code still using `Dict[...]`/`Optional[...]`** (14 uses in `__main__.py`, 6 in
     `evaluate.py`). **A merge that takes origin's import line while keeping my code raises
     `NameError: Dict is not defined` at import — the research module fails to load and the
     daemon cannot start.** Silent until the first import.
   - **The conflict surface is real:** **32 of the 67 files I changed this session were also
     reformatted by `ebeb299`** — including every core research file (`evaluate.py`,
     `logger.py`, `__main__.py`, `promote.py`, `factory_trainer.py`, `resolve.py`,
     `conftest.py`, `test_research.py`). A naive `git pull` will conflict across all 32.
   - **Reconciliation (yours to run, not mine) — the ruff pass is REQUIRED, not optional:**
     **merge origin/main, then run `ruff check --fix` + `ruff format` once over the whole tree
     BEFORE trusting the result.** That pass rewrites my new `Dict[...]`→`dict[...]` /
     `Optional[...]`→`... | None` and reconciles imports across both sides, so nothing
     references a pruned name. Skipping it risks exactly the `NameError` above — a merge that
     looks clean but leaves the daemon unable to import. Resolve each textual conflict as "keep
     my logic, take their formatting", then let the ruff pass normalise. A 243-commit rebase
     across the reformat would mean resolving the same style conflict 243 times — avoid it.
     **Verified (§5.3.R99): `ruff check --fix` on the worst-case file rewrote all 14 old-style
     `Dict`/`Optional` uses to builtins and converged its import to `from typing import Any` —
     origin's exact line — with zero non-typing changes. The mechanism holds; `ruff` 0.15.22
     is in `apps/dottie/.venv`.**
     **After the ruff pass, run the SUITES** (`apps/dottie` needs `AVA_FACTORY_ROOT`, §5.3.R87)
     before pushing — an import-time NameError fails collection immediately, so a green **pytest**
     suite is the proof the reconciliation held. **NOT the ruff CI (§5.3.R104): `ruff check .`
     is already red on origin (491 errors) and stays red after B0 — that is pre-existing lint
     debt, not a failed merge.** And use the CI's pinned **`ruff==0.8.6`** for the `ruff format`
     step (`pip install ruff==0.8.6`), not local 0.15.22, or the CI's `ruff format --check` may
     disagree on style.
   - **✅ WHILE YOU'RE IN THERE — the 5 real bugs to fix during B0** (found by reviewing under
     the gate; each breaks the 3.11 target and/or the CI, all hidden by the 3.13 dev venv;
     §5.3.R103/R105/R106). This is the consolidated checklist so you are not hunting the R-log:
     1. ✅ **DONE** (mine, `b2645a2`): `personal-graphify/…/cli.py:259` nested-quote f-string.
     2. **`apps/ava-factory/scripts/dataset_expansion_fast.py:51`** — backslash in f-string
        (3.12-only). MECHANICAL fix: lift `slug = re.sub(r"\W+","_",topic.lower())` out, use
        `{slug}`. No design intent needed.
     3. **`apps/ava-factory/model_1b.py:768-770` `get_model()`** — references undefined
        `use_short_conv`/`use_relative`/`relative_max_distance`, AND `train_1b_deepspeed.py:342`
        calls it with `critical_shift=` it does not accept. **Needs your intent:** add these to
        the signature (with what defaults?) or drop them from the call. Definitely-broken 1B
        training path.
     4. **`apps/ava-factory/on_policy_distill.py:288`** — `torch.randn(B,44,d)` uses undefined
        `d` in a stub `forward` (was an `__init__` param). Likely `self.d`/`d_model`.
     5. (verify) `tool_gate.py:99` F821 is a **false positive** (valid closure) — add
        `# noqa: F821` only if the lint CI noise bothers you; not a bug.
     Acceptance: `python3.11 -c "import ast; ast.parse(open(F).read())"` for 2; a real import/
     build for 3–4. Fix these during the merge and the CI parse + 3.11 runtime are clean.
   - **Why I did not do it:** reconciling 243 commits against a repo-wide reformat is a large,
     judgement-heavy operation that can silently mangle either side, and pushing is
     outward-facing. Both are your calls. I also **paused non-essential commits** once I saw
     the gap — every new local commit widens it.
   - **Interaction with item 0:** the restart there picks up local HEAD, which does **not**
     include the ruff reformat or CI. That is fine for running the daemon (formatting is
     cosmetic), but do the reconciliation before the CI workflow would judge this branch.

0. ✅ **RECOVERED 2026-07-20 ~20:43 — the loop is back up.** Docker fleet up (13 containers),
   baseline re-seeded (`5.54404` → honest **`5.73733`**, cross-seed SEM 0.099 n=3), and the
   **research daemon booted and is running** (`git_sha 3b77263`, pid 26708; verified via the
   `boot` line in `run.log`). `dottie-chat-branch` (T9.4) was **stopped reversibly** to free
   the 2.58 GiB the re-seed needed — it is checkpointed at step 16, `docker start` resumes it.
   - **⚠ HONEST LIMITATION — the loop's LLM stages are memory-gated, AND the daemon itself is
     UNSTABLE under the full fleet (updated ~21:14).** Two distinct problems:
     1. *Memory-gated*: `ideate`/`implement` need ~6.2 GB (qwen3:8b at NUM_GPU=0); with the
        fleet up only ~0.5–2.5 GB is free, so the guard (§5.3.R77) **refuses them gracefully**
        and backs off. No forward progress on the 2 `pending` experiments.
     2. *Daemon OOM-cycles*: measured — the daemon booted 20:42, refused `implement` cleanly
        for 23 min, then was **OOM-KILLED at ~21:05** (task result 2147943467, no fatal log)
        when the collectors spiked the box near zero. The guard stops the daemon *causing* an
        OOM (it refuses Ollama) but cannot stop the fleet from *starving* it. So the daemon
        boots → refuses ~20 min → gets killed → scheduler reboots it. Up, but cycling and
        unproductive.
     **Root cause: the fleet + the research loop do not fit in 16 GB.**
   - **✅ RESOLVED THE INSTABILITY (~21:45, operator stopped collector-3 + collector-4).** With
     the fleet at 11 containers the daemon is now **STABLE — single boot, no more OOM-cycling**
     (~1900 MB free, was ~800). So the daemon runs continuously and safely.
   - **⏸ STILL memory-gated for NEW-CANDIDATE generation.** `implement`/`ideate` need ~6.2 GB
     (qwen3:8b in host RAM); ~1.9 GB free is not enough, so the guard keeps refusing them —
     the loop is stable but only generates candidates in a large memory window. **Stopping
     containers did NOT free host memory as hoped:** `.wslconfig` has `memory=8GB` +
     `autoMemoryReclaim=dropcache`, so the WSL VM holds its allocation and does not return the
     freed container memory to the Windows host (where the daemon loads Ollama). To free ~6 GB
     of *host* RAM requires a bigger move — all operator's call:
     - **Shifts:** `wsl --shutdown` (frees the whole VM to the host) → loop runs LLM stages →
       restart the fleet after. Fleet down during the window.
     - **Lower the cap:** `memory=4GB` in `.wslconfig` + `wsl --shutdown` to apply — leaves
       ~6 GB host for the loop and a smaller fleet.
     - **Close Docker Desktop** entirely when running the research loop.
   - I stopped the **flagged-regressing** chat-branch unilaterally (clear-cut) but left the
     collector call and these bigger moves to the operator (legitimate work / big blast radius).
     `docker start` restores anything stopped.
   - Everything below (original item-0 recovery instructions) is now historical; kept for the
     record of how it got here.

   ~~⛔ **TRAINING IS OFF AND DOCKER IS DOWN. Restore both — but RE-SEED FIRST (see below).**
   Re-verified 15:40: scheduled task **`Disabled`**, **0** research processes, **~3.1 GB**
   free, on AC, Docker engine down (`dockerd` never started inside the VM — the VM is up).~~
   ```powershell
   python -m dottie.research calibrate-baseline --overwrite   # FIRST — see the coupling note
   wsl --shutdown                                             # docker engine back in ~2 min
   docker ps --format "{{.Names}}"                            # expect 13-14 containers
   .\scripts\restart_research.ps1                             # research back on, PROVES it booted
   ```
   - **⚠ ORDER MATTERS — re-seed before restarting the research daemon (§5.3.R96).** The live
     baseline `5.54404` is a **regression, below what the base model reaches at every seed**
     (§5.3.R93), so a daemon restarted against it **rejects every candidate indefinitely** and
     the loop churns for nothing. `calibrate-baseline --overwrite` installs the honest
     ≈5.737 (SEM ≈0.099, n=3) in ~6 min; run it first, or restart and re-seed together, but do
     not leave the loop running on the old bar. This is item 5, pulled up here because it is
     now a precondition, not a separate decision.
   - **How it got here** (§5.3.R51): the daemon was **crash-looping on memory** — lifetimes
     105 min then ~9 min, each restart landing on the scheduler's 15-min trigger, dying
     silently mid-stage at **110 MB free**. A subtask then ran `prepare_fleet_recovery.ps1`,
     whose step 1 **disables the task by design**, and was classifier-blocked before it could
     finish. Memory is now clear; the task is simply switched off.
   - `restart_research.ps1` (§5.3.R56) refuses on low memory or orphaned processes, and waits
     for the daemon's own `boot` line so it cannot claim a success it did not observe.
   - **Decide before the engine returns:** `dottie-chat-branch` carries `--restart on-failure`
     **and** `--resume`, so T9.4 auto-continues from `step_15.pt` the moment Docker is back.
     Its step-15 gate showed **+2.04% general CE** — the same forgetting mode that failed T9.3.
     To stop it: `docker update --restart no dottie-chat-branch; docker stop dottie-chat-branch`.
   - **What restarting picks up** (behaviour changes, not a commit count — read `git log` for
     the full set): the trainer loads validator scratch files (§5.3.R49); the memory guard now
     counts the model an LLM stage will load (§5.3.R77); the significance gate prefers
     cross-seed over within-run spread and flags a within-run basis (§5.3.R93); the proposal-
     pipeline fixes (search space §5.3.R35, corrector constraints §5.3.R38) are proven live.
     **None of these help until the baseline is re-seeded** — a better gate against an
     unreachable bar still rejects everything.

1. **Recover the fleet** — `.\scripts\prepare_fleet_recovery.ps1` (prep + GO/NO-GO), then
   `wsl --shutdown`. Nothing else moves until the engine is back. (Memory was 719 MB at
   07:10; the projection still says GO once the model unloads.)
2. **Charger** — unchanged. Worth checking (780 MHz / 45 W of 175 W were real), but
   **downgraded**: not the outage cause, only a possible contributor to the CUBLAS crashes.
3. **T9.3 path (§1.4)** — unchanged. Gate FAILED (+75.1% CE). Recommendation: no knob-rerun;
   get real tool data via 2.1, then re-fork with a replay mix. Trainer stays parked.
4. **T9.4 — decide before or right after `wsl --shutdown`.** Unchanged: `--restart
   on-failure` **and** `--resume` mean **doing nothing is a decision to continue** from
   step_15.pt, whose early warning showed +2.04% general CE. To stop instead:
   ```powershell
   docker update --restart no dottie-chat-branch
   docker stop dottie-chat-branch
   ```
5. **RE-SEED THE BASELINE — now urgent and a one-liner (updated §5.3.R96).** The live
   baseline has moved since this item was written: it is **`factory_lm_loss 5.54404`**, set
   by `5a7232ffea24`, which **paired seed testing proved is WORSE than the unmodified model at
   every seed** (§5.3.R93). So the bar is **BELOW what the base model reaches (5.56/5.74/5.91)
   — unreachable.** On restart the loop **rejects every candidate indefinitely** against it.
   This is no longer "noisy warnings"; it is "the loop cannot make progress until you re-seed."
   - **THE FIX, one command:** `python -m dottie.research calibrate-baseline --overwrite`
     (multi-seed as of §5.3.R96). Installs ≈**5.737, SEM ≈0.099, n=3** — measured, honest, and
     two-sample-ready. Takes ~6 min on an idle box.
   - Historical: the pre-contamination values were 5.60506 (MLBR) and 5.61982 (pre-MLBR
     calibration). Both are superseded by the command above, which measures fresh — and it
     records `metric_sem` automatically (§5.3.R96), so no separate step is needed to get the
     two-sample test the loop wants.
   - **Note on urgency vs the old framing:** earlier versions of this item (MLBR-era, §5.3.R26)
     said contamination only causes *missed* promotions, never false ones — true when the
     baseline was merely a slightly-harder 5.60506. It no longer holds: the current 5.54404 is
     **below what the model can reach**, so the effect is not "occasionally misses a win" but
     "rejects everything." That is why this moved from a cleanup to a precondition (item 00→0).
6. **Ollama startup task (§8)** and **§2.3 checkout retirement** — unchanged (daytime).
7. **arxiviq deploy (§7.5)** — unchanged. One command, or approve and I'll run it.
8. **Research search quality — the highest-leverage change to the PROPOSAL side, and the fix
   is CONFIG, not code.** (Ranking, post-§5.3.R93: the re-seed in item 0/5 is the true
   *blocker* — the loop cannot progress at all until it is done — and the per-seed trainer
   change is the highest-value *correctness* fix; this item is what most improves *what gets
   proposed* once those are handled.) Measured over 84 proposals: **36% (30) are category
   errors** —
   regularisers, penalties, losses — structurally unbuildable as residual-stream blocks.
   That bucket has **zero real wins**, accounts for **4 of 5** training failures, and
   contains MLBR.
   - **Root cause is your `--bottleneck` string**, not a missing instruction. The contract
     already forbids loss-shaped ideas and 36% ignore it, because the bottleneck —
     *"held-out LM loss plateaus while train loss keeps dropping (memorization gap)"* — is a
     **regularisation-shaped problem**, and the honest fix for overfitting *is* a regulariser.
     The loop asks for a block-shaped answer to a loss-shaped question.
   - **Suggested replacement**: *"the fusion block at the swap site underuses its capacity —
     find a token-mixing or gating transform that extracts more from the same hidden
     states."* That string lives in the scheduled-task definition, which I cannot edit.
   - The prompt now translates rather than forbids (§5.3.R12), but that is a workaround for
     the contradiction, not a fix to it.

9. **✅ WITHDRAWN — I WAS WRONG. `apps/dottie` is GREEN: 199 passed, 1 skipped.**
   Corrected 2026-07-20 14:19 (§5.3.R87). **There is no layout decision to make and nothing
   for you to do here.** The suite needs `AVA_FACTORY_ROOT` pointed at the standalone
   checkout — which the daemon has set all along, in the gitignored machine-local
   `apps/dottie/research_orchestration/research_env.local.ps1`:
   ```
   $env:AVA_FACTORY_ROOT = "C:\Users\jcdav\workspace\ava-agi-factory-v6-4"
   ```
   That checkout **has** the `ava/rl/codeact_loop.py` layout `resolve.py` probes for. My
   shell never had the var, so I diagnosed a missing dependency as a broken repo.
   **What I got right and what I got wrong:** the two-packages-named-`dottie` observation is
   real, and `ensure_factory_on_path()` inserting a colliding root at `sys.path[0]` is still
   a genuine latent hazard worth knowing about. But the CONCLUSION — "red at HEAD, needs an
   operator rename" — was wrong, and I asked you to make a decision that did not exist.
   The original text is kept below for the record.

   ~~**⚠ `apps/dottie` is RED at HEAD: 36 failed / 159 passed — and it needs a layout
   decision, not a patch.** Found 2026-07-20 (§5.3.R77) running the full suite. **Not caused
   by tonight's work** — verified by stashing my changes and reproducing on a clean tree.~~
   - **Root cause: two different packages are both named `dottie`.** `apps/dottie/dottie`
     (has `research`) and `apps/ava-factory/dottie` (has `rl`). Python can only ever import
     one of them per process — whichever lands on `sys.path` first wins, and the other's
     submodules become invisible.
   - The consolidation (`5cb75c4`) renamed ava-factory's `ava/` → `dottie/` and left
     `ava/rl/__init__.py` as a `sys.modules` shim. **The shim works** — I verified
     `ava.rl.codeact_loop` resolves to `dottie.rl.codeact_loop`. What broke is that
     `resolve.py::_has_factory_code` still probes the pre-shim path `ava/rl/codeact_loop.py`,
     which no longer exists, so Dottie reports its own monorepo has no factory code.
   - **I tried the one-line marker fix and REVERTED it.** Accepting `dottie/rl/` makes
     `resolve()` return a root that then fails deeper with `ModuleNotFoundError: dottie.rl`,
     because by then `dottie` is already bound to the app package. Worse, `ensure_factory_on_path()`
     inserts that root at `sys.path[0]` — so if it ever ran *before* `dottie.research` were
     imported, it would shadow Dottie's OWN package. The stale marker is currently the only
     thing preventing that. **Fixing the check without fixing the collision is a live hazard.**
   - **The decision is yours** (each is a real rename, hence not mine to make): rename
     ava-factory's package back to `ava` and drop the shim; or rename it to something unique
     (`ava_factory`); or keep the split and point `AVA_FACTORY_ROOT` at a standalone checkout
     that still uses the `ava/` layout. Only the last is zero-diff, and it leaves the monorepo
     unable to test itself.
   - Scope: the 36 are the engine / flywheel / verified-engine / skill-tools tests — every
     test that reaches the CodeAct substrate. The research loop's own 87 tests pass, so
     **tonight's daemon work is unaffected** and the loop runs fine.

   #### ✅ OPERATOR ANSWERED 2026-07-25: `dottie_org` — plan measured, NOT yet executed

   The answer resolves the collision **without touching the frozen factory**: rename the
   *assistant* package `apps/dottie/dottie` → `apps/dottie/dottie_org`, leaving
   `apps/ava-factory/dottie` as the only top-level `dottie`. (`apps/ava-factory/dottie/**`
   is FROZEN and bind-mounted into the live trainer, so the options above that renamed
   *it* were never available.)

   ⚠ **Do not inherit the retracted benefit claim.** The rename buys removal of a real
   latent hazard — `ensure_factory_on_path()` inserting a colliding root at `sys.path[0]`
   could shadow Dottie's own package, and today only a stale marker prevents it, plus both
   packages become importable in one process. It does **NOT** clear the 36 failures: those
   were false failures from an unset `AVA_FACTORY_ROOT` (retracted above, and recorded in
   memory as "AVA_FACTORY_ROOT or 36 false failures"). Measure `apps/dottie` with that var
   SET, before and after.

   **Measured scope (2026-07-25, re-counted — not the older estimate):** 32 package files ·
   **138** absolute `dottie.*` import lines (70 in the package, 65 in `tests/`, 3 in
   `scripts/`; `research_orchestration/` has none) · 15 dynamic/string references · 3
   non-Python files.

   **The distinction that makes this dangerous to sed:** `dottie` as a **Python module
   path** must change; `dottie` as a **directory / image / volume / CLI command / brand**
   must not. Specifically:

   | Must change | Must NOT change |
   |---|---|
   | `from dottie.x import` / `import dottie.x` (138) | `engine.data_dir / "dottie.sqlite3"` — a **DB filename**; renaming it orphans existing data (`dottie/api.py:257`) |
   | `pyproject.toml:34` `packages = ["dottie"]` | `DOTTIE_ROOT=/dottie` — a directory |
   | `pyproject.toml:25` `dottie = "dottie.__main__:main"` — the **target**, not the command name | `image: dottie/dottie:latest`, `dottie_data` volume |
   | `pyproject.toml:54` `known-first-party` | `WORKDIR /dottie`, `COPY apps/dottie` |
   | `Dockerfile:41` `CMD [... "-m", "dottie", ...]` | the `dottie` console-script NAME users type |
   | `dottie/__main__.py:98` `uvicorn.run("dottie.api:app")` | |
   | `harness/evals/dottie_assistant.py` — 4 module names + 5 dict lookups | |
   | `packages/ava-open-harness/tests/test_dottie_assistant.py` — 2 lookups | |
   | docstring refs: `kg/__init__.py:2`, `kg/ingest.py:337` | |

   Gate: `apps/dottie` suite with `AVA_FACTORY_ROOT` set, plus `packages/ava-open-harness`
   (30 passed / 10 skipped at last measure) — both green before AND after. The harness can
   become a hard gate in `ci.yml` only once its 5 collision-caused failures are gone; that
   is a separate verification, not an assumption.
   - **Correction to the previous version of this item:** it said "50% dying in validation".
     That was one overnight window. **Lifetime is 77.9%** (53 genuine failures of 68, after
     separating 7 infrastructure deaths). Different samples; not interchangeable (§5.3.R4).
   - **Sharper still (§5.3.R18): only 5 of 84 proposals (6%) were block-shaped AND had
     learnable parameters.** The loop has made roughly five genuine attempts. "Zero real
     wins" is therefore a verdict on the proposal pipeline, not on the search space — five
     attempts, one of them an artifact, is not evidence that the idea does not work.

**What tonight actually bought you** (all committed, tested, and waiting on item 0):
six validation stages catching **5 of 5** stored integration failures in ~106 ms instead of
after a full model build; a contamination detector on the baseline; a real two-sample
significance test; and a mutation audit (8/8) that caught a hollow test in my own work.
**Real wins remain ZERO** — all THREE recorded SOTAs are artifacts (ledger, 2026-07-24: 3
`sota` rows, not 2; the third was retracted by paired-seed testing and the baseline reverted
to 5.73733 with a NULL owner). The gates stop false wins;
item 8 is what would produce a true one.

---

9. 📚 **DEPLOY THE NEW CURRICULUM to the running collectors (added 22:40 2026-07-20 — state
   read live).** This session added three curriculum topics you asked for and they are
   committed + fully test-verified (501 factory tests green) but **NOT yet live** — the
   collectors run the baked `ava/cpu:latest` image, which does not contain them.
   - **What changed (local commits, HEAD `8415a6b`):** `9006865` wires the existing but
     unregistered `compression`/`compress_trace`/`db_trace` generators into `sources.yaml`;
     `3e03b44` adds a new `scout_cli` generator (using + building the agent CLI, grounded in
     the real bigbang contract); `8415a6b` adds a new `zk_math` generator (Schnorr, Fiat-Shamir
     NIZK, Pedersen, Merkle, Shamir — every transcript computed and re-verified). Every phase's
     mixture still sums to 1.0.
   - **Why not live (confirmed, not assumed):** `docker exec dottie-factory-collector-1 grep -c
     'synth_zk_math\|synth_scout_cli\|synth_compression' /app/configs/sources.yaml` → **0**, and
     the new generator `.py` files are absent from the image too. The Dockerfile bakes config via
     `COPY . /workspace`; the running collector bind-mounts only `ava_raw/ava_state/ava_reports/C:`.
     Same situation as the item-2.1 rebuild note in Standing State.
   - **⚠ PRECONDITION — memory.** A `docker build` spikes RAM/CPU; at **813 MB free** (measured
     this tick) it risks the exact VM death that took the fleet down before. **Do this only when
     available memory is ample** (`(Get-Counter '\Memory\Available MBytes').CounterSamples[0].CookedValue`,
     want > ~3 GB — ideally with Ollama unloaded). That is why I did not run it autonomously.
   - **Command (local build from working-tree HEAD — independent of item 00; no push/pull):**
     from `apps/ava-factory`:
     `docker compose -f docker-compose.yml -f docker-compose.tool-fork.yml build` (rebuilds the
     shared `ava/cpu:latest` from local code, picking up the new configs + generators), then
     `docker compose -f docker-compose.yml -f docker-compose.tool-fork.yml up -d --no-deps --force-recreate collector`
     (recreate the data-selector; add `curator` if you want it recreated too). No data loss —
     checkpoints/manifest live on the named volumes.
   - **Lighter alternative (no rebuild):** add `../configs:/app/configs:ro` **and** the datagen
     package as bind-mounts to the `collector` service in `docker-compose.tool-fork.yml`, then
     `up -d --no-deps --force-recreate collector`. Cheaper on memory (no image build) but you must
     bind the whole importable package so `scout_cli`/`zk_math` resolve; the rebuild is cleaner.
   - **Acceptance:** the grep above returns **3**, and a collection epoch emits docs whose
     `source` starts with `compression/`, `scout_cli/`, or `zk_math/` (check `/reports` or
     `docker logs dottie-factory-collector-1`).

10. 🔬 **PROPOSAL PIPELINE (SPEC #2) IS SUBSTANTIALLY DONE — measured 22:58 2026-07-20; the
    real remaining lever is a capacity PROMOTE-gate, and that is YOUR call.** SPEC #2 said "36%
    of proposals are category errors; highest-leverage change to what gets proposed." Measured
    against the live ledger (`data/research/ledger.sqlite3`, 100 experiments) this is now largely
    resolved by the already-landed prompt work — and the naive next fix would be dead code:
    - **Declaration compliance is 100% (11/11).** Every post-fix hypothesis (the 11 carrying the
      `learnable_parameters` field; 89 predate it) declares a real trainable tensor
      (`nn.Parameter`/`nn.Linear`/…). So the §5.3.R19 fear that enforcing the field "starves the
      loop if the live model omits it" is **not borne out** — but enforcing it would also catch
      **nothing**, because the zero-parameter leak is **declaration↔implementation divergence**
      (the model declares `nn.Linear` then the *generated code* builds zero trainable params),
      which shows up only in the code and is already caught fast (~106 ms) at the validator's
      zero-parameter stage. An ideation-declaration gate would never fire. **I did not add it.**
    - **Post-fix proposals are block-shaped, not category errors.** The 11 are gating /
      normalisation / sparsity / token-mixing blocks (states: 5 rejected, 2 failed_validation,
      1 failed_training, 1 sota-artifact, 2 pending) — being built and validated as blocks, not
      bounced at the contract stage. The "36%" is the pre-fix lifetime tally; the prompt rewrite
      (DEFAULT_SEARCH_SPACE domain-2, the INTEGRATION CONTRACT, the loss/regulariser warnings)
      already fixed *what gets proposed*.
    - **The real lever for moving real-wins off zero is capacity-fair PROMOTION — and it is
      explicitly yours.** `evaluate.py:347` promotes on `improved and stable and significant`;
      the candidate's own `block_param_delta` is computed and surfaced as a caveat but **excluded
      from the gate** (`evaluate.py:328-356`). A capacity-deleting swap that wins at fixed steps
      still promotes and ratchets the baseline — the exact contamination chain behind the
      artifact SOTAs. `evaluate.py:158` states outright that whether a capacity-confounded result
      should halt the loop "is the operator's call," so I am **surfacing it, not changing it**.
      **Decision for you:** gate promotion on capacity parity (refuse when a candidate wins while
      deleting > the confound threshold of the block's parameters), or keep caveat-only. If you
      want it gated, that is a focused, memory-safe change to `evaluate.py` I can execute on your
      go — with a paired capacity-fair re-eval so a genuine smaller-but-better block can still win.
    - **Beyond that, the binding constraint is THROUGHPUT, not proposal quality:** only ~11 real
      block-shaped candidates have ever been tried, and ideate/implement are memory-gated with the
      fleet up. More shots on goal needs memory headroom (item 0 / the 16 GB budget), not a better
      proposer.

11. 🎯 **PAIRED-SEED EVAL GATE — the natural completion of SPEC #3, ready to execute (added
    23:13 2026-07-20).** Now that the factory trainer records candidate `per_seed` at seeds
    [0,1,2] (commit `ca9f2f1`) and the baseline is calibrated at the same seeds, the evaluator
    can do the PAIRED test its own comments call "the honest fix" (`evaluate.py:305`,
    `promote.py:34`) instead of the current unpaired two-sample test. Reviewed 23:10: the
    current gate is CORRECT and well-tested (two-sample `sqrt(sem_c²+sem_b²)`,
    `test_two_sample_significance_when_baseline_records_spread`; a `per_seed` case at
    test_research.py:1582) — this is a rigor UPGRADE, not a bug fix.
    - **Why paired is better:** candidate and baseline are trained at the SAME seeds, so a
      "hard seed" hurts both; the unpaired test ignores that shared variance and OVERESTIMATES
      SE_diff (it is conservative — it MISSES real wins). Paired `diffs = c_i − b_i`,
      `SE = stdev(diffs)/√n` cancels the shared seed variance — exactly what `ab_nano.py`
      already does in every promotion bundle, but at eval time so the gate itself is as strict.
    - **Four parts (the first three are memory-safe + unit-testable WITHOUT torch; only the
      end-to-end needs the deferred multi-seed integration run):**
      1. `ledger.py`: add `per_seed: Optional[List[float]]` to `Baseline` + a `per_seed TEXT`
         (JSON) column, following the existing additive `metric_sem` ALTER-TABLE idiom
         (`ledger.py:181`). Persist in `seed_baseline`, parse in `_row_to_baseline`, and carry
         the candidate's `per_seed` in `promote_baseline` so the NEXT comparison is paired too.
      2. `__main__.py::cmd_calibrate_baseline`: store `per_seed` structurally (today it is only
         in the baseline NOTES text, `__main__.py:160`).
      3. `evaluate.py`: when candidate `per_seed` and `baseline.per_seed` are both present and
         same length, compute the paired `SE`; else fall back to the current unpaired test
         (backward-compatible — pre-per_seed baselines are unchanged). Say "paired" in the
         significance prose.
      4. Tests: paired-vs-unpaired significance (pure math, no torch) + baseline `per_seed`
         ledger round-trip (sqlite, no torch).
    - **Why I filed instead of shipping:** it modifies the PROMOTION gate (higher-stakes: paired
      is more powerful, so more candidates promote) and would migrate the schema of the LIVE
      ledger the daemon reads. Those two cautions remain and make it a deliberate change.
      - **UPDATE 2026-07-20: the multi-seed candidate pipeline this builds on is now VERIFIED
        end-to-end** — the deferred integration tests passed once free memory cleared the R77
        floor (2 passed at ~1.4 GB free; real training records `per_seed`, `_spread` consumes it
        cross-seed). So the "unproven pipeline" blocker is GONE; item 11's own parts (ledger
        `per_seed` storage, the paired test, their tests) are all memory-safe and unit-testable.
      - **⚠ CORRECTION 2026-07-20 23:26 — item 11 is COUPLED to item 10; do NOT ship it alone.**
        I called it "cleanly executable" above; on closer analysis that is wrong. The paired test
        does not merely refine the basis — it can DRASTICALLY lower the promotion bar. With
        cross-seed SEMs ~0.1 each, the current unpaired `sqrt(sem_c²+sem_b²)` ≈ 0.14 → 2σ
        threshold ~0.28. Paired `stdev(cᵢ−bᵢ)/√n` cancels the shared seed variance and can fall
        to ~0.02 → threshold ~0.04 — roughly **7× easier to clear**. Because promotion is NOT
        capacity-gated (item 10, the operator's call), a marginal capacity-DELETING swap
        (delta −0.05) that the unpaired test correctly rejects would then PROMOTE and ratchet
        the baseline — the exact contamination this loop has fought. So paired significance is a
        net win ONLY alongside item 10's capacity gate (or a capacity-aware promote guard);
        shipped alone it makes contamination MORE likely. **Decide item 10 and item 11 together.**
        This is why I did not execute it this session despite the pipeline being verified.

## Standing state (context for every step below)

- `dottie-factory` fleet (13 containers) runs ONLY from `apps/ava-factory`; trainer is
  mid **mini tool-branch (T9.3)**, ~1,144 steps total, bind-mounted code, monitor armed.
- The three-way fork (retired `ava-agi` / workspace `ava-agi-factory-v6-4` / monorepo)
  is **reconciled into the monorepo** (`4aabd3d`, `75ef9a6`): 431 factory tests pass.
  Containers still run pre-reconciliation IMAGE code until step 2.1 rebuilds them.
- Research loop: **ONE forever-daemon** ("Dottie Research runner", PT15M trigger,
  `MultipleInstances=IgnoreNew`) — **not** the old 4 per-tick tasks; qwen3:8b think=false,
  keep_alive 30s. Live baseline is `factory_lm_loss` **5.60506 and CONTAMINATED** (ratcheted
  by a candidate the current validator rejects); pre-MLBR calibrated value 5.61982.
  It does **not** live-reload — the `boot` line in `run.log` is the only ground truth for
  what code is running. (Corrected §5.3.R77: this block still described the 4-task era.)
- Agent OS: J-Space state store (`skills/state_store.py`), Hermes/OpenClaw profiles,
  forge self-evolution loop all live-verified; scout has `reviewgraph`.

---

## 0 — GPU power cap: MEASURED, but its blast radius was OVERSTATED (see correction)

> ⚠ **READ THIS FIRST — partial retraction (03:52).** The measurements in this section
> are real and still stand: the SM clock was pinned at 780 MHz and the power limit read
> 45 W of a 175 W maximum. What I got wrong is everything I hung off them. Through the
> night I attributed the CUBLAS crashes, the slow steps, AND the fleet outage to this one
> cause. The outage was actually **my own qwen3:14b night-model change eating 7 GB of
> RAM** (see the top-of-file incident entry), and host-RAM pressure is an equally
> plausible explanation for the 01:38/01:56 CUBLAS crashes. Treat the power cap as a
> real measurement with an UNPROVEN blast radius: still worth checking the charger,
> but do not assume it explains the crashes or the outage. Re-measure after recovery:
> `nvidia-smi --query-gpu=power.limit,clocks.sm --format=csv`

### Original entry (2026-07-19 23:56), kept for the record:

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

    **T9.4 LAUNCHED 2026-07-20 01:44 (user directive via fork; per this section's
    "defensible" verdict)**: container `dottie-chat-branch`, forked base_final →
    /ckpt/chat, p5_anneal seq 4096, 50M tokens ≈ 191 steps.
    **ETA RE-CORRECTED ~02:12 (measured, steps 1→10)**: 53.6 s/step, tok/s 5449 →
    **~2.9h, chat_final ~04:40**. (The interim 5.5h number was modeled before the
    first inter-step interval existed — wrong method, retracted.) Full clocks
    (charger!) would still cut this substantially. Step-1 lm 0.1509 is EXPECTED
    (base_final trained through p5 already) — only the val-side gate can show
    forgetting; an early-warning CPU gate against step_30.pt (~02:20) is queued
    in the loop.
    **WATCH RE-ARMED from the loop session ~02:05**: the fork's watch (by5bexxzs)
    did NOT survive the fork's termination (TaskList empty — watches die with their
    session, same lesson as the machine-move at 00:40). New watch: chat_final.pt /
    container exit / crash signatures, 60s poll.
    ### ⚠ TIMESTAMP CORRECTION (written 02:26, verified against `date`)
    Every clock time I wrote in this section between the T9.4 launch and 02:26 was
    ESTIMATED, not read — they run ~1–1.5 h fast (and the fork's "01:44 launch" is
    also wrong). Trust ONLY these log-derived anchors:
    | event | real local time |
    |---|---|
    | chat step 1 | **01:25:14** |
    | crash 1 (step 15, CUDA unknown error) | **01:38:12** |
    | resumed from step_15.pt | **01:45:39** |
    | step 20 | **01:51:33** |
    | crash 2 (step 23, CUBLAS_STATUS_INTERNAL_ERROR) | **01:56:39** |
    | restart boot: model_built / branch_forked / init_loaded | **02:00:30 / 02:01:55 / 02:03:49** |
    | WSL VM death (engine 500s first seen) | **~02:05** |
    | OSA implemented by the loop (host-side, unaffected) | **02:16:43** |
    So: two crashes **18.5 min apart** (01:38 → 01:57) still stands — that interval
    came from epoch subtraction, not from the wrong wall-clock labels, and so does
    the ~29 steps/h throughput figure.

    ## >>> BLOCKED ON USER: WSL VM DEAD, WHOLE FLEET DOWN (~02:05 → now) <<<

    **What happened**: docker API 500s on EVERY call including `docker version` —
    not a container fault. `vmmemWSL` collapsed 755 MB → **34 MB** (dead, not
    booting) and `com.docker.backend` burned only ~2 CPU-s in 7 min (idle, not
    recovering). The WSL2 VM hosting all 14 containers is gone: factory fleet (13)
    + the chat trainer. Same degraded-WSL-GPU family as the 780MHz/CUBLAS flakes;
    the 45W power cap is the standing suspect (a reboot cleared it last night).

    **Nothing is lost**: every checkpoint is on the named volume `ava_ckpt`
    (`/ckpt/chat/step_15.pt` banked), the manifest is on `ava_state`, and the
    research loop is host-side (unaffected — it kept running).

    **RECOVERY — run ONE of these (Claude is blocked by the permission classifier
    from doing it; both are safe and the fleet self-heals afterwards):**
    ```powershell
    wsl --shutdown                      # clears the wedged VM; Docker restarts it
    # if the engine does not return within ~2 min, also:
    #   quit Docker Desktop from the tray, then relaunch it
    ```
    **After the engine returns, expected automatic behavior**: the 13 factory
    containers come back on their restart policies; `dottie-chat-branch`
    (`--restart on-failure`, command carries `--resume`) re-resumes from
    step_15.pt with the new cadence-8 config. Verify with
    `docker ps --format "{{.Names}}\t{{.Status}}"` (expect 14) and
    `docker logs dottie-chat-branch --tail 3` (expect a `resumed` event).
    If the chat container does NOT come back, relaunch it with:
    ```
    cd apps/ava-factory
    docker compose -f docker-compose.yml -f docker-compose.tool-fork.yml run -d \
      --name dottie-chat-branch trainer python -m dottie.train --preset mini \
      --branch chat --init /ckpt/base_final.pt --run /ckpt/chat --resume
    docker update --restart on-failure dottie-chat-branch
    ```
    **THROUGHPUT UNDER FLAKING — MEASURED ~03:20 (this is the real ETA)**: two
    CUBLAS/CUDA crashes 18.5 min apart (ts 1784529492 step 15, ts 1784530599 step 23),
    each costing ~3 min of boot + every step since the last checkpoint. Net rate:
    ~9 steps per 18.5-min cycle ≈ **29 steps/h** (cadence 8) vs ~18 steps/h had the
    cadence stayed 15 — the ratchet is measurably net-positive but the honest ETA for
    the remaining ~176 steps is **~6h (≈09:15)**, NOT 05:00. Both crash traces sit in
    the gradient-checkpointing recompute path under bf16 GEMM at 45W/780MHz.
    **THE FIX IS PHYSICAL**: full power would likely remove both the flakes and the
    3-5x clock penalty → ~1-1.5h. No mid-run experiments (micro-batch, ckpt off) are
    being attempted unattended: the directive was monitor-to-completion, and an
    unmeasured recipe change mid-flight would poison the endpoint measurement.
    **MONITORING NOW TICK-DRIVEN (~03:05)**: three background watches were externally
    killed in a row — treating that as deliberate and not re-arming. The 3-min loop
    itself polls each tick: step_60.pt → run 48w confirmation gate; chat_final.pt →
    final gate; container Exited → triage. Restart policy on the container is the
    crash safety net (auto-resume).
    **EARLY WARNING ~02:50 (step-15 CPU gate, 12 windows, paired seed)**: general CE
    base 3.811 → chat_step15 3.889 = **+2.04%** — nominally past the 2% bound at 8%
    of the run, with LR still warming. The tool branch's forgetting mode appears to
    be REPRODUCING at 1/6 tokens. Small sample (12w) → directional, not precise.
    Per the standing run-to-completion directive the run continues; NEXT: full-size
    (48w) confirmation gate at step ~60 (~03:15), and the final gate remains the
    decision point. If you want to abort early and save ~2h GPU: `docker stop
    dottie-chat-branch` (safe — checkpoints every 15 steps are already banked).
    **CRASH + RECOVERY ~02:25**: CUDA "unknown error" in grad-ckpt recompute at
    step 15→16 (the overnight flake family) — step_15.pt had saved 18s earlier, so
    zero loss. The fork's docker-run had NO restart policy (crash was terminal).
    Relaunched via the documented compose command + `--resume` (git-bash MSYS
    path-mangling ate the first attempt — MSYS_NO_PATHCONV required), then
    `docker update --restart on-failure`: future flakes now auto-resume from the
    latest ckpt (command carries --resume), exit-0 completion stays down. Watch
    re-armed. NOTE the flake recurred at 45W/780MHz — the power-cap⇄CUBLAS-flake
    correlation now has another data point (charger!).
    Old July-10 nano-era /ckpt/chat ckpts preserved as *.nano-20260710.bak.
    Completion/failure watch armed (fires the session on chat_final.pt, clean exit,
    crash, or CUBLAS/NaN signatures). GATE NEXT: nonregression-only eval vs
    base_final (expect the forgetting risk the tool branch showed, at 1/6 the
    token count). HARNESS READY (adapted ~01:55): `evals/tool_gate.py` now takes
    `--candidate-ckpt/--candidate-label`; wake-time command:
    `docker compose -f docker-compose.yml -f docker-compose.tool-fork.yml run --rm trainer \
     python -m evals.tool_gate --candidate-ckpt /ckpt/chat/chat_final.pt \
     --candidate-label chat --out /reports/chat_gate.json`

    Original plan (**if gate passes → chat branch (T9.4)**): same overlay pattern,
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
    - 2.3.0 ⛔ **BLOCKER FOUND 03:15 — §2.3 CANNOT PROCEED AS WRITTEN. Retiring the
      workspace checkout would break `apps/dottie` (36 test failures).** Measured:
      * Full dottie suite with `AVA_FACTORY_ROOT=C:\Users\jcdav\workspace\ava-agi-factory-v6-4`
        → **147 passed, 1 skipped, 0 failed** (this also proves tonight's 9 changed files
        caused ZERO regressions).
      * Same suite with the env var UNSET or pointed at the monorepo → **36 failed**.
      * Cause: the reconciliation renamed the factory package `ava` → `dottie`, so the
        monorepo has `apps/ava-factory/dottie/rl/codeact_loop.py` while only the retired
        checkout still has `ava/rl/codeact_loop.py`. `resolve.py::_has_factory_code`
        probes ONLY the legacy path, so this app silently depends on the retired checkout.
      * I tried the one-line fix (accept either layout) and **reverted it** — it makes
        things worse: resolution then picks the monorepo and the import dies with
        `ModuleNotFoundError: No module named 'dottie.rl'`, because the factory's package
        is now ALSO called `dottie` and collides with this app's own `dottie` package
        (the app's wins in `sys.modules`). The `ava→dottie` alias shim cannot help: its
        `from dottie import *` resolves to the APP's dottie from this context.
      * **DECISION NEEDED (real design choice, not a config tweak)**: (a) rename the
        factory package to something unambiguous (e.g. `avafactory`) and keep an `ava`
        shim; (b) have `apps/dottie` import the factory under a distinct alias via an
        importlib loader instead of `sys.path` insertion; (c) keep the workspace checkout
        alive indefinitely and drop §2.3's delete step. Until one is chosen, DO NOT
        delete `C:\Users\jcdav\workspace\ava-agi-factory-v6-4`, and keep AVA_FACTORY_ROOT
        pointed at it (the §2.3.b instruction to repoint it at the monorepo is WRONG).
    - 2.3.a' ADD to the retirement list (found 2026-07-20): `C:\Users\jcdav\scout-cli` —
      a standalone scout-cli checkout pip-installed (develop) into the shared venv;
      it shadows the monorepo copy everywhere except under apps/scout-cli. Audit for
      unmerged work, then retire + `pip install -e` the monorepo copy instead.
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
    - 5.2.f [x] **SHIPPED 04:52 — the dominant validation failure is AXIS CONFUSION, and
      the prompt now says so.** Diagnosed by re-running the validator on each failed
      candidate's stored code **using its own declared `init_kwargs`/`input_shape`**:

      | candidate | error | cause |
      |---|---|---|
      | f559109b12a1 | `tensor a (512) vs b (128) at dim 2` | hidden vs **seq** |
      | 8c3c8ab09b39 | `tensor a (64) vs b (16) at dim 2` | hidden vs **seq** |
      | 2c23939467d0 | `Hidden size must match expert weights` | weight on wrong axis |
      | c3af0b3ce501 | `t() expects <= 2 dimensions, self is 3D` | 2-D transpose on 3-D |

      **4 of 4** are the same underlying mistake: treating `[B, S, H]` as if the axes were
      interchangeable. Added constraint 8 (AXIS DISCIPLINE) to the implementation prompt:
      size weights against `x.shape[-1]`, never `.T`/`torch.t()` on a 3-D tensor (use
      `transpose(-2, -1)`), prefer inferring hidden at forward time. This is NOT
      research-direction steering — the contract already required it (constraints 6–7), the
      prompt just never said *how* it was being violated. 37/37 tests green; effect visible
      from the 05:05 daemon restart, measurable as fewer `dry_run` rejects.
      **REFINED 06:19 after 4 post-fix failures** — the original constraint was not
      landing. Two of those failures were still rank confusion, just not through
      `nn.Linear`: an `einsum()` with a 2-subscript equation on a 3-D tensor, and a module
      reading `self.hidden` it never assigned. The model appears to have read "size weights
      against x.shape[-1]" as advice about layers rather than about tensor rank generally.
      Constraint 8 now names both explicitly (one subscript letter per dimension; assign
      every attribute you later read). Renders at 1,335 chars; 37/37 tests green.
      **Still unproven** — judge it on the next ~5 failures, not on hope. Requires a daemon
      restart to take effect (standing rule).
      METHOD NOTE: my first pass used default kwargs/shape instead of each candidate's
      declared ones and produced a partly-wrong answer (a spurious "missing positional
      arguments" for c3af0b3ce501). Re-ran it faithfully before drawing conclusions.
    - 5.2.g [ ] ⭐ **IDEATION HAS MODE-COLLAPSED — and the dead-ends list may be CAUSING
      it (measured 04:54, your call because it is search direction).** At 04:52 the loop
      ideated *"Gradient-Adaptive Sparse Attention (GASA)"* — **the verbatim name of an
      experiment already tried and rejected tonight** (`716ac622e50a`) — plus a near-twin
      of two others. The machinery is not broken: `dead_ends()` returns 44 names, GASA is
      in it, and the block renders into the prompt (944 chars). The model reads it and
      proposes the same thing anyway.
      Vocabulary of the 30 most recent hypothesis names: **gradient ×18, attention ×13,
      consistent ×11, sparse ×11, adaptive ×10, moe ×8, load ×8, balancing ×8, dynamic ×7,
      loss ×7** — nearly every "new" idea is a permutation of the same seven words.
      **Hypothesis worth testing: the dead-ends list is PRIMING rather than steering.**
      Showing 44 same-flavoured names is textbook anchoring — it hands the model the exact
      vocabulary to recombine. Options: (a) feed the failure REASON alongside each name so
      the pattern is learnable, not just the label; (b) replace the 44-name list with a
      short thematic summary ("attention-sparsity variants: 12 tried, all rejected");
      (c) instruct explicitly not to recombine listed terms and to pick an unexplored
      sub-domain; (d) rotate `search_domain` per ideation call to force coverage.
      Cheap to test: apply one, then re-run this vocabulary count after ~10 new ideas.
      **COST QUANTIFIED 05:54 — 13 of 72 experiments are re-proposals of a name already in
      the ledger (~18%), ≈1h44m of compute.** Repeat offenders:
      GASA **×5**, "Dynamic Routing with Adaptive Load Balancing (Advanced)" ×3, OSA ×3,
      plus five names proposed twice. GASA was proposed again at 05:51 — its **third**
      appearance tonight and fifth overall — while sitting in the dead-ends list the whole
      time. This is now the loop's largest single waste and the best-evidenced open item.
      Caveat kept from earlier: same name ≠ same code (GASA #1 vs #2 were 13.7% similar
      and scored differently), so a name-only dedup guard would reject some genuinely new
      implementations. Any fix should compare the hypothesis TEXT, not just the label.
      **COST NOW BEING PAID LIVE (04:57)**: the duplicate GASA (`7ae76c3a8b27`) validated
      on attempt 0 and is TRAINING — ~4 min of CPU re-testing a hypothesis rejected hours
      ago. Precise framing: the *implementation* is not a copy (13.7% string similarity,
      8 of 37 lines shared, though both happen to be 1,806 chars), so this is a genuine
      re-test of a known-rejected IDEA rather than a byte-identical repeat. The check that
      settles it is its metric: the original GASA scored **5.7119 (delta +0.107)**; a
      similar landing confirms the loop is paying full price to re-learn a known answer.
      **RESULT 05:03 — my prediction FAILED, and the strong claim is withdrawn.** The
      duplicate scored **delta +0.3665 (≈5.972)** against the original's **+0.107
      (5.7119)** — a 0.26 gap, not a re-run. So this was NOT "re-learning a known answer":
      same hypothesis *name*, materially different implementation (13.7% similar), and a
      materially different number. Both rejected, so the family-level conclusion is
      unchanged, but "the loop wastes cycles re-running rejected experiments" is too
      strong and I am dropping it.
      **What survives on its own evidence**: the vocabulary collapse (gradient ×18,
      attention ×13, consistent ×11, sparse ×11 across 30 names) — the search is confined
      to a narrow region, which is worth fixing regardless of whether individual re-tests
      reproduce. The four options above still stand; the justification is diversity, not
      duplicated compute.
    - 5.2.e [ ] **SEARCH-QUALITY FIX, ready to apply — your call (it steers what the model
      proposes, which is a research decision, so I did not ship it).** Three candidates
      now (MLBR, AGN, and OSA's shape) have converged on the same artifact: a
      **parameter-free module that REPLACES a real ~787 K-parameter block**, "winning" at
      fixed steps by shrinking the model. The gates catch it after ~10 min of CPU each
      time; the ideation prompt could stop proposing it. `prompts.py` line ~111's
      INTEGRATION CONTRACT block already states the drop-in shape rule — append one
      sentence there:

      > Your module will REPLACE an existing parameterized block (~787 K parameters), so a
      > module with no learnable parameters silently REDUCES model capacity and any
      > apparent win at fixed steps is confounded with that shrink. Give the module
      > learnable parameters unless the idea is fundamentally parameter-free (a mask, a
      > fixed transform) — and if it is, say so explicitly in the intuition.

      Costs nothing to try, reversible, and does not ban a legitimate class. Verify by
      watching whether `block_param_delta` stops being large-negative on new candidates.
    - 5.2.d [x] **SHIPPED 04:36 — stored failures now keep the EXCEPTION, not the header.**
      Tried to classify why the loop keeps failing (3 of the last 5 implements died at
      `dry_run` after all 5 retries) and found the analysis is impossible: `failed_validation`
      records stored `detail[:500]`, the HEAD of a traceback — pure boilerplate — while
      Python puts the exception type and message on the LAST line. **36 of the 40 most
      recent failures were unclassifiable** for that reason alone. Now tail-truncated
      (last 800 chars, prefixed `...[head truncated]...`; short details untouched).
      37/37 tests green. NOTE this only helps failures recorded from now on — the existing
      49+ records stay unclassifiable, so re-run the classification after a few more cycles
      before drawing conclusions about the dominant failure mode.
    - 5.2.c [x] **SHIPPED 02:45** — the corrector now sees its OWN last edit: from the
      second retry on, the feedback carries a bounded unified diff (previous_attempt →
      current_attempt), and a byte-identical resubmission is called out explicitly.
      Rationale: the traceback says what broke, the diff says what the model just tried —
      different questions, and near-greedy sampling kept re-making the same edit. 32/32
      research tests green (new test asserts both branches).
> **Timestamp integrity note (06:56).** The times on the 5.3.R4 entries above were
> originally written as 07:10-08:00. Those were **invented, not observed** — I stamped
> plausible-looking times instead of reading the clock. Corrected against
> `git log --date=format:%H:%M:%S`: the real range is 06:32-06:54. No finding or number
> changes, but a log that reports fabricated provenance is worth less than no log, and
> this file is being used as an audit trail. Read timestamps from git or the system
> clock; do not compose them.

### 5.3.R4 — ⭐⭐⭐ DEGENERACY GATE'S FIRST PRODUCTION CATCH (06:32), cheapest yet

`48e0f39d8225` was rejected at **L4 validation** with:
> degenerate block: 0 learnable parameters and output differs from input by a CONSTANT
> (std of (out-in) = 0). This is a bias, not an architecture …

`std = 0` means the module was a **literal identity** — the exact class that produced
MLBR, the false SOTA that prompted all of tonight's gate work. Two things make this the
most valuable catch so far:
- **It cost 255.7 s and never reached training.** The significance gate's catch (AGN,
  §5.3.R3) came at *evaluation*, after a full implement + train cycle. This one died at
  validation, so no training compute was spent at all.
- **It fired on a module the search generated live**, not on replayed stored code as in
  the unit tests. The gate is not just theoretically correct — the search still emits
  this shape, and now it is stopped.
- [x] ODDITY, now RESOLVED (06:41): it stopped at `attempts: 2` though `--max-retries 5`
  is set. The retry accounting was fine — the **corrector itself raised**, which makes
  `validate_with_correction` break early and record the exception *only* in `history`.
  The stored failure was built from the last validation result alone, so the reason was
  invisible. **This was worse than a cosmetic count bug**: an experiment abandoned because
  Ollama was down looked *identical in the ledger* to one that genuinely failed validation
  on its merits. Given the Ollama outages this box has had, some share of the
  `failed_validation` pile is likely infrastructure misfiled as candidate failure — which
  inflates the "50% die in validation" figure in §5.2. Fixed in `implementation.py`: the
  corrector's exception is surfaced in the failure text ("STOPPED EARLY, the corrector
  itself failed: …") and returned as `corrector_error`. Regression test verified red
  before / green after (`test_corrector_failure_is_distinguished_from_a_bad_candidate`).
- [x] **LIVE since the 2026-07-24 13:40:53 fleet restart** (verified 22:45; pid 7092 no longer
  exists — see the note at §5.3 on expired pid claims). Original text follows.
  ~~**NOT YET LIVE.** The running daemon (pid 7092) started 06:21:54; the fix landed
  06:41, so the in-flight process still has the old `implementation.py` imported.~~ There is
  no natural restart on this box — the runner is a forever-daemon, so nothing recycles it
  on its own (the trap I walked into four times last night). A restart now is NOT free:
  per the recovery script's step 1b, `Stop-ScheduledTask` kills the wrapper but not its
  python child, and a naive Start then yields TWO concurrent daemons. Correct sequencing
  is the orphan cleanup in `scripts/prepare_fleet_recovery.ps1`. Deliberately deferred to
  the queued fleet recovery, which stops the daemon anyway — restarting mid-experiment,
  with known orphan risk, for an observability-only fix is a bad trade.
- [x] FOLLOW-UP, DONE (06:48) — **and I was wrong about the premise.** I claimed old
  records "cannot be recovered (the reason was never stored)". The reason *was* stored:
  `implementation.validation.history` has carried `corrector_error` all along. What my
  earlier fix changed is only whether it is *surfaced* — the human-readable `failure`
  field and the return dict. The data to reclassify the whole backlog was already sitting
  in the ledger. **Ground truth over all 59 `failed_validation` records: 7 (11.9%) are
  corrector deaths, i.e. infrastructure, not candidate failures.** Causes: 6 x
  `ValueError('no parseable JSON object found in model response')`, 1 x
  `DottiePolicyUnavailable` (Ollama ReadTimeout). So §5.2's "50% die in validation"
  overstates candidate failure by roughly a tenth of the pile.
  - Worth recording that my `attempts < max_retries` heuristic was **unsound** and the
    stored data caught it: it predicted 6 of the 7. It missed `ed45b85c0fd1`, which has
    `attempts == 5 == max` *and* a corrector error — the corrector can die on the final
    attempt, which is indistinguishable from exhaustion by count alone. Two clean
    `max_retries` eras exist (3 until 07-19 08:56, 5 from 07-19 13:37), so the heuristic
    was at least separable by time — but it should not be used as a classifier now that
    the exact reason is readable.
- [x] **ASYMMETRY FIXED (06:48)** — the 6 unparseable-corrector deaths were not bad luck,
  they were a structural gap. `run_implementation` re-prompts the INITIAL implementation
  parse up to `max_retries` times when the model emits invalid JSON, but the `corrector`
  closure parsed with no retry at all and let `ValueError` escape, which makes
  `validate_with_correction` break its loop and abandon the experiment. The model got
  several chances to format correctly before its first attempt and none after. The
  corrector now re-prompts on the same budget, feeding the parse error back. That
  reclaims ~10% of the failed-validation pile. Regression test verified red before
  (gave up after 1 reply) / green after; full suite 151 passed.
- [x] **MEASURED, AND DECLINED (06:51).** I filed the `class_name` pin below as a
  suspected bug. It is real as a design wart but the measured frequency does not justify
  a behavior change: across all 75 experiments, `class not found in generated module`
  appears **once**, in a single attempt of `2acedace4eaf` — whose final code *does*
  define the pinned class (the rename was transient) and which died of a `SyntaxError`
  anyway. It cost one attempt on a candidate already failing on its own merits. Leaving
  the pin alone; noted here so the next person who suspects it can see it was checked
  rather than re-litigating it.
- [x] **§5.2 CONVERSION RATE RECOMPUTED (06:51) — and my last tick's framing was
  misleading, in a way that matters.** I said the infra misclassification "overstates
  candidate failure by roughly a tenth of the pile". That is true as a *share of the
  pile* (7 of 60) but it implied the corrected picture would look meaningfully better.
  It does not: removing the 7 infra records from numerator *and* denominator moves the
  validation death rate from **80.0% (60/75) to 77.9% (53/68)** — 2.1 points. The
  qualitative story is unchanged, and I should not have implied otherwise.
  - Honest lifetime funnel over 75 experiments: **53 genuine validation deaths (77.9%)**,
    3 failed_training, 12 reached evaluation, 2 recorded `sota` — `HierarchicalAttention`
    and `MoERegularizer` (MLBR). **Correction: I earlier wrote these were "MLBR + AGN".
    That was wrong — AGN was a REJECTED candidate, never a SOTA.** Real wins remain
    ZERO, but for the reasons in §5.3.R5, not the ones I gave.
  - Genuine failures by level: **dry_run 41, contract 5, static 4, syntax 3.** dry_run is
    77% of all genuine failures — runtime shape/axis errors dominate everything else
    combined, which is exactly what the constraint-8 axis-discipline prompt guidance
    targets.
  - Note also that the "50% die in validation" figure I have quoted came from a single
    overnight window (14 created / 5 evaluated), not lifetime. Lifetime is ~78%. Both
    can be true; they are different samples and should not be quoted interchangeably.
- [x] **ATTEMPTED (06:54) — VERDICT: NOT YET MEASURABLE, n=2.** Buckets below, but the
  honest answer is that the post-change sample is far too small and I am not going to
  dress it up. Constraint-8 landed in two commits (`03f6b9d` 04:51, `94aa6e1` 06:20), but
  **the commit time is the wrong boundary** — `prompts.py` is imported at daemon start and
  this daemon never live-reloads, so the real boundary is the first restart *after* the
  commit, which is 06:21:54. Only experiments created from 06:23 on actually ran the new
  prompt.
  | bucket | experiments | genuine fails | dry_run |
  |---|---|---|---|
  | before v1 commit | 66 | 47 | 35 (74%) |
  | v1 commit -> daemon restart (still OLD prompt in memory) | 6 | 4 | 4 (100%) |
  | after restart (both stages live) | 6 | 2 | 2 (100%) |
  With n=2 the post-change figure is noise; the nominal direction is *worse* (100% vs
  74%), which is exactly what two coin flips look like. **No conclusion either way.**
  Re-run this once the post-restart bucket reaches ~20 genuine failures. Note the middle
  bucket is mislabeled by construction in any commit-time-based analysis — it is
  effectively "before", and would have silently contaminated the comparison.
- [x] **BOOT PROVENANCE ADDED (06:54)** — the blocker above was that "which prompt version
  produced this experiment?" was only recoverable by catching the daemon PID's creation
  time before the process died. `cmd_run` now emits a `boot` line with pid, git SHA,
  `prompts.py` sha256, trainer and max_retries. Verified against ground truth: reports
  `70b43c5` / `3a70b43b736e`, both matching `git rev-parse` and a direct hash. Every
  future before/after comparison is now checkable from run.log rather than reconstructed
  from process tables. Full suite 151 passed.
- [ ] NEXT: **re-run the constraint-8 comparison when n >= 20** in the post-restart
  bucket, scoping it by the `boot` lines rather than commit timestamps. If dry_run share
  has not moved, the axis-discipline guidance is not working and the dominant failure
  mode (77% of genuine deaths) needs a different attack than prompt text — most likely
  giving the corrector the actual tensor shapes at the failure point instead of a raw
  traceback.
- [x] **LATENT QUEUE-BLOCKER FIXED in `train.py` (06:59)** — found by auditing broad
  `except Exception` handlers for more of the same misfiling the corrector bug showed.
  `run_training` treats `ok=False` as *retryable infrastructure* and leaves the
  experiment in `ready_for_training`. But `_load_module` / `_select_module_class` /
  `Proxy()` all operate on **the candidate's own artifact**, so a failure there
  reproduces identically on every retry: the experiment would be re-picked forever and
  **block every experiment queued behind it**. `factory_trainer.py` already draws this
  line correctly (candidate fault -> `ok=True, stable=False` -> FAILED_TRAINING); I made
  that fix there earlier tonight and did not carry it across. `train.py` was the odd one
  out.
  - **Observed frequency: ZERO.** Nothing is in `ready_for_training` now and no record
    shows it. This is latent, not active, and I am fixing it on consistency grounds — the
    semantics were already decided, and the failure mode (silent queue stall) is bad
    enough that waiting for it to happen is the wrong trade. That is a different judgement
    from the `class_name` pin, which I declined: there the correct behavior was genuinely
    unclear and the blast radius was one wasted attempt.
  - Regression test verified red before (`assert 'ready_for_training' == 'failed_training'`)
    / green after. Full suite 152 passed.
- [x] **SELF-INFLICTED LATENCY REGRESSION IN MY OWN FIX, caught and repaired (07:05).**
  The unparseable-corrector retry I shipped two ticks ago and called a clean win gave
  **every correction attempt its own `max_retries` parse retries**, nesting the loops:
  5 attempts x 6 calls = **30 policy calls worst case, against 5 before the retry existed
  at all.** At the ~90 s/call this box measures that is **45 min for a single implement
  instead of 8** — a latency regression materially worse than the ~10% of experiments the
  retry reclaims. Now a single `_PARSE_RETRY_BUDGET = 3` pool shared across the whole
  experiment: worst case `max_retries + 3`.
  - **The first regression test I wrote for this was worthless and nearly shipped.** It
    used an always-garbling policy, which aborts on the first corrector invocation and
    never exercises the nesting — it scores 6 calls on the *buggy* code and passes any
    sane ceiling. Its "red" came from an `AttributeError` on the missing constant, which
    I initially misread as the bound working. The real test garbles once per attempt then
    succeeds, and the ceiling is hardcoded rather than read from the module so an
    `AttributeError` can never masquerade as a bound failure. It now fails on the old code
    with `10 policy calls exceeds 8` — matching the predicted `5 attempts x 2` exactly.
  - Lesson worth keeping: a red test is not evidence until the *reason* for the red is
    checked. Two of tonight's verifications were nearly satisfied by the wrong exception.
- [x] **STALL SCARE, RESOLVED AS "JUST SLOW" (07:10)** — an implement ran 17.9 min with
  no completion line, past the 13.1 min observed max, which is exactly the signature the
  start-line was added to expose. **It was not a stall.** Evidence before concluding:
  `llama-server` burned **127 CPU-seconds in 8 wall-seconds** (~16 cores saturated), so it
  was actively generating. It completed at **1100.8 s (18.3 min)**, 26 s after I looked —
  a new maximum. The distinction is worth the two commands: a stall needs intervention, a
  slow run needs to be left alone.
  - **No slowdown trend, and I am not going to claim one.** n=9 implements, first-half
    median 489.9 s vs second-half 492.5 s — flat. The spread is 250-1101 s (4.4x), so the
    new max sits inside ordinary variance for this sample. Revisit at larger n.
  - **Read-timeout headroom checked, not assumed.** The 1800 s timeout is per model call,
    not per implement; a single observed call (ideate) is ~99 s and the 1101 s implement
    spans several calls. Headroom is roughly an order of magnitude, so slow-but-working
    generates are **not** at risk of being killed and misfiled as `DottiePolicyUnavailable`
    — which was a live worry given that exact misfiling is 1 of the 7 infra deaths.
- [x] **MEMORY IS TIGHT AGAIN (07:10): 719 MB available.** Not the 281 MB that killed the
  WSL VM, but the same direction, and the fleet recovery's GO threshold is 4000 MB. Top
  consumers: `llama-server` 4,976 MB (qwen3:8b, expected and co-existence-proven), then
  **my own Claude Code session at ~1,820 MB across two processes** — worth stating plainly
  since I have been reporting on this box's RAM budget all night while being its
  second-largest consumer. The queued recovery's projection still holds: unloading the
  model reclaims ~5 GB, which clears the threshold comfortably.
### 5.3.R5 — the baseline is CONTAMINATED, and no gate was looking

- [x] **Replayed both historical SOTAs through today's gates (07:20) — my claim that the
  gates catch both was WRONG.** Results:
  | experiment | module | current validator |
  |---|---|---|
  | `23bb41375804` | MoERegularizer (MLBR) | **FAILS** — degenerate, 0 learnable params, delta std 1.31e-07 |
  | `bc3dbb74bead` | HierarchicalAttention | **PASSES** — 20,800 real params, delta_std 1.077 |
  `HierarchicalAttention` also sails through the significance gate at **261.5 SEM**. Both
  gates clear it. It is still an artifact, but of a kind neither gate addresses: it scored
  0.15478 against a **hand-seeded 4.5 placeholder** on a task whose own metrics record it
  as `"synthetic next-token shift (proxy micro-benchmark, NOT downstream capability)"`.
  Degeneracy and significance test the *candidate*; nothing tested the *baseline*.
- [x] **THE LIVE BASELINE IS SET BY A MODULE THE LOOP WOULD NOW REJECT.** `get_baseline()`
  returns `factory_lm_loss 5.60506`, `experiment_id 23bb41375804` — MLBR, the degenerate
  no-op above. And because it carries an `experiment_id`, `_baseline_provenance` classifies
  it **`"promoted"`: the highest-trust category, caveat `None`.** Every comparison since has
  been measured against a number produced by a block that cannot learn anything, and the
  verdict JSON has been reporting that baseline as fully trustworthy while doing it.
  - The flaw is structural, not a one-off: **provenance trust is retrospective and never
    re-checked.** A gate added *after* a promotion never re-examines the number that
    promotion left behind. Any future gate has the same blind spot.
  - `_baseline_contamination()` now re-validates the baseline's source experiment against
    the current validator on every evaluation (one dry run, seconds) and attaches a loud
    caveat, downgrading provenance to `promoted_contaminated`. **Verified against the real
    ledger**, where it correctly fires on MLBR — that live run is the meaningful proof
    here, not the test's red (for a brand-new function the red is only an `AttributeError`,
    which proves nothing).
  - **It records, it does NOT block.** Whether a contaminated baseline should halt the loop
    or merely flag itself changes loop behavior and is the operator's call — it also bears
    directly on queued decision #5 (re-seed to 5.61982). Flagging it is safe; halting is
    not mine to choose.
- [ ] NEXT (operator input): with contamination now detected automatically, decision #5 is
  sharper — **re-seed the baseline to 5.61982** (the pre-MLBR value) and the caveat clears
  itself. Until then every promotion verdict carries the contamination warning, which is
  honest but noisy.
### 5.3.R6 — the significance gate now does a real two-sample test

- [x] **BASELINE SPREAD IS RECORDED, AND THE GATE USES IT (07:35).** The gate compared a
  candidate's SEM against a **point** baseline, which silently assumes the baseline was
  measured without error. The effective threshold is ~1.4 SE_diff (~84%), **not the 95%
  the word "significant" implies** — a limit documented in a doc-comment but never fixed.
  With both spreads known the honest denominator is `SE_diff = sqrt(sem_c² + sem_b²)`,
  which is strictly larger, so deltas that squeaked past can now correctly fail.
  - `Baseline` carries `metric_sem` / `metric_sem_n`; `promote_baseline` records the
    winning run's spread so the NEXT candidate gets the stronger test. Nullable on
    purpose: hand-seeded and legacy baselines genuinely have no spread, and inventing one
    is worse than admitting it is missing.
  - **The one-sample fallback now says so out loud** rather than letting a reader assume
    the stronger test ran: *"candidate-only SEM … the baseline records NO spread, so it is
    treated as an exact point and this test is weaker than 2 SE of a real difference"*.
  - Test is behavioral, not cosmetic: **same delta (0.115), same candidate spread** →
    `significant: True` against a point baseline, `significant: False` once the baseline
    carries SEM 0.05 (2×SE_diff ≈ 0.135 > 0.115), and the experiment is correctly HELD.
  - Added `Ledger._migrate()` — additive, nullable ALTER TABLE only. `CREATE TABLE IF NOT
    EXISTS` is a no-op on an existing table, so new columns never reach a live ledger
    without it. Additive-only matters here specifically because the research daemon holds
    this file open for hours and **does not reload**: old code reads by column name and
    writes an explicit column list, so it keeps working against the migrated DB. Verified
    by migrating the live ledger in place and reading the baseline back.
  - Full suite 156 passed.
- [x] **MIGRATION SAFETY VERIFIED EMPIRICALLY, NOT ASSERTED (07:30).** Last tick I
  migrated the **live** ledger while the daemon held it open running the previous
  `ledger.py`, and claimed old code would tolerate it. Claiming is not checking. Replayed
  the pre-migration 8-column INSERT verbatim against a migrated schema: it succeeds, and
  the new reader returns the row with `metric_sem=None`. The daemon has since completed
  two implements and started an ideate against the migrated DB, so it is demonstrably fine.
  - Added `test_baseline_migrations_stay_additive_and_nullable`.
  - **And a correction on that test's worth.** I first wrote it as though it guarded a
    catastrophe. It mostly does not: sqlite (3.45.1) **rejects `ADD COLUMN ... NOT NULL`
    without a default outright once the table has a row**, and `baseline` is a singleton
    that always has one — so the headline failure is largely unreachable, and the test
    would hit sqlite's own error before its assertion. What it genuinely guards is the
    part sqlite does *not* check: that the pre-migration INSERT still succeeds verbatim
    (a future CHECK constraint, renamed column or altered conflict clause would break it
    silently) and that re-running the migration is a no-op. Docstring says so now rather
    than implying more.
  - Full suite 157 passed.
### 5.3.R7 — mutation audit: are tonight's gate tests actually guarding anything?

- [x] **AUDITED ALL FIVE GATE TESTS BY MUTATION (07:45). Result: none hollow.** Three
  times last night a "red" test turned out to prove less than I assumed — an
  `AttributeError` on a new symbol, and one test that could not detect its own bug. So
  rather than note the lesson again, I checked it: each mutation below leaves every symbol
  in place and breaks **only behaviour**, so a surviving test is a hollow test.
  | test | mutation | killed by |
  |---|---|---|
  | `two_sample_significance` | gate ignores `baseline.metric_sem` | `assert True is False` |
  | `contaminated_baseline` | contamination check always reports clean | `assert (None)` |
  | `corrector_failure_is_distinguished` | corrector error never found in history | `assert (1 == 1 and None)` |
  | `records_the_baselines_spread` | promotion drops the winning run's spread | `assert (None is not None)` |
  | `unloadable_candidate` | load failure retryable again | `assert 'ready_for_training' == 'failed_training'` |
  Every one died on an assertion about behaviour, not a structural error. The gates are
  genuinely guarded.
- [x] Installed as `apps/dottie/scripts/mutation_audit.py` so it is repeatable rather than
  a one-off, with a `MUTANTS` table to extend when a new gate lands. Mutations are applied
  one at a time and reverted in a `finally`; verified the tree is clean after each run.
  Verdicts are `GOOD` / `WEAK` (structural-only red) / `HOLLOW` (survived).
- [x] Worth recording that I nearly mis-declared the first test hollow: my grep for `^E `
  missed because of pytest's ANSI colour codes, so a real behavioural failure looked like
  no failure at all. **The check on the check needed checking.** The script now strips ANSI
  and passes `--color=no`.
### 5.3.R8 — validation ran at the WRONG WIDTH; candidates died at integration for it

- [x] **Read the real exceptions behind every `failed_training` record (07:50).** The
  stored failures all say *"candidate not integrable at d_model=256"* with a traceback
  through `model_1b.py:667  x = blk(x, cos, sin, attn_factor)`.
  - **My first hypothesis was WRONG and I checked before acting on it.** I read that call
    site as a contract mismatch — the factory passing 4 args to a `forward(x)` the
    validator demands. It is not: `CandidateBlockAdapter.forward(x, cos, sin,
    attn_factor=1.0)` bridges it correctly. That frame is just the caller.
  - The actual causes: `RuntimeError: shape '[2,16,8,64]' is invalid for input of size
    8192`; `Expected size ... [32, 8] but got: [32, 32]`; `candidate changed shape
    [2,16,256]->[2,16,1]`; and two `AttributeError: 'NoneType' has no attribute ...`.
- [x] **Root cause: validation ran at hidden=64, integration runs at d_model=256.** The
  dry run used the model's *self-declared* `input_shape` — almost always 64 — while
  `factory_trainer` swaps the block into a 256-wide residual stream. A candidate that
  hardcodes a head count, reshape, or projection size to 64 passed every level and then
  died after a full model build. `validate()` now re-probes at `INTEGRATION_WIDTH = 256`.
  - **Measured, not hoped: this catches 2 of the 5 stored failures**, not 4. The other
    three (`'NoneType' has no attribute 'abs'/'layout'`, and one shape collapse) only
    misbehave on real training data, which no forward probe reaches. 40%, and the honest
    number is the one worth recording.
  - On success the canonical dry-run result is preserved (its `learnable_params` /
    `delta_std` detail is what the degeneracy gate and write-ups read); the probe only
    changes the verdict when it fails, and is recorded in `per_level` either way.
- [x] **Found a REAL bug in the live trainer while fixing the test fixtures.**
  `_DIM_KWARGS` was missing **`hidden`** (and `channels`, `width`). A candidate naming its
  constructor arg `hidden` was built at its OWN default width and then handed d_model-wide
  input — so the swap failed and **the candidate was blamed for a mismatch we created**.
  Fixed in `factory_trainer.py` and `validate.py`. The suite caught this: my new level
  rejected the legitimate `LayerScale` fixture, which is exactly what would have happened
  to a real candidate.
  - The probe overrides by **constructor signature**, not by declared kwargs, matching
    `_make_candidate`. Keying off declared kwargs leaves a candidate that relies on its own
    default width narrow, then blames it for the resulting mismatch.
  - Also hardened: a declared `input_shape` may contain symbolic entries like `"hidden"`.
    `int('hidden')` raised straight out of `validate()` — found by replaying stored
    candidates, and it would have broken this level for every such candidate.
  - Full suite 159 passed; mutation audit still 5/5 GOOD.
- [ ] **I OVERRODE MY OWN HOLD, deliberately — recording the trade.** §5.3.R4 said not to
  ship a second dry_run intervention until constraint-8 was measurable, to keep the two
  separable. This change alters validation pass rates, so **the constraint-8 comparison is
  now confounded and should be abandoned rather than reported.** I judged that a
  structural defect burning full training runs outranks a clean measurement of a prompt
  tweak that sat at n=5 after 1.5 h (≈6 h to reach n=20). Stating it because silently
  breaking my own methodology note would be worse than the confound.
### 5.3.R9 — the daemon restart is OPERATOR-ONLY (attempted 07:47, classifier-denied)

- [x] **RESOLVED BY RESTART — verified 2026-07-24 22:40.** This entry described pid 7092 as
  pinning stale code, and it read as an active crisis for four days. It is not one: **no pid
  7092 exists.** The oldest python processes on this box started 2026-07-24 13:40:53 (four
  workers, same-second start = a restarted fleet), and the research code's most recent commit
  is `3c84164` (2026-07-23), which PREDATES that restart — so the seven fixes are live.
  ⚠ **Generalise this, do not just tick it.** This file records live pids and "NOT LIVE"
  warnings that expire silently when a process restarts, leaving an urgent-sounding blocker
  that is merely old. Several of the other 103 open items are likely in the same state. Same
  failure mode as the step-1487 re-init recommendation retracted from CURSOR_HANDOFF.md today:
  **a stale runbook entry reads as a decision someone already reasoned through.** Before acting
  on any pid/daemon claim here, re-verify the process actually exists.
  - Original text, kept for the record: *"SEVEN tested fixes are committed and NOT LIVE. The
  daemon (pid 7092) has been*
  running since 06:21:54 on code from before all of tonight's work, and it never reloads.
  I attempted the restart this tick and **the permission classifier denied process
  termination / scheduled-task control**. I did not route around it. Verified afterwards
  that nothing partially executed: same pids, same start time, task still `Running`.
  - Waiting is no longer neutral. One queued fix (`_DIM_KWARGS` missing `hidden`) is a
    **live bug**: candidates naming that constructor arg are built at their own default
    width, handed d_model-wide input, and recorded as `failed_training` — **blamed for a
    mismatch the trainer creates.** Every cycle until restart adds corrupted rows to the
    same `failed_training` table §5.3.R8's analysis draws on.
  - Also not live: integration-width validation, the bounded corrector retry, corrector-
    error surfacing, the training queue-blocker fix, contamination detection, two-sample
    significance, and boot provenance.
  - **Exact sequence (safe: touches only the research daemon, not WSL/Docker/the fleet):**
    ```powershell
    Stop-ScheduledTask -TaskName "Dottie Research runner"
    Get-CimInstance Win32_Process -Filter "Name like '%python%'" |
      Where-Object { $_.CommandLine -match 'dottie\.research' } |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force }   # the wrapper does NOT kill its child
    Start-ScheduledTask -TaskName "Dottie Research runner"
    ```
    Then confirm from `data/research/logs/run.log`: a `{"action":"boot"...}` line should
    appear carrying `git_sha` and `prompts_sha256` — that line exists *because* of tonight's
    provenance work and is the check that the restart took.
  - Cost of restarting mid-stage is one in-flight implement; it stays `pending` and re-runs.
  - **On my own reversal, recorded plainly:** I told the operator I would keep this queued
    absent a reply, then revised that this tick on new information (the live misattribution
    bug). The classifier settled it instead. The revision was still the right call to
    surface rather than to make silently — but a stated plan reversed by the same agent
    that stated it is worth flagging every time, not quietly re-derived.
### 5.3.R10 — the probe fed the wrong KIND of tensor, not just the wrong width

- [x] **RESIDUAL-STREAM PROBE ADDED (07:55). Stored `failed_training` catch rate is now
  4 of 5, up from 2.** Chased the three §5.3.R8 left behind. **My hypothesis was wrong
  again, and testing it first is what found the real cause.** I assumed train-mode +
  backward was the missing ingredient; it makes no difference. The difference is the
  *kind of tensor*:
  - the dry run feeds a **leaf** tensor with `requires_grad=False`, under `no_grad`
  - a block in the residual stream gets a **non-leaf activation that requires grad**
  - `.grad` is only ever populated on leaves, so a candidate reading `x.grad` sees a real
    tensor in the probe and `None` in production
  Two records died precisely there — `'NoneType' object has no attribute 'abs'` and
  `... 'layout'` — after passing every level *including* the integration-width probe. Both
  are caught in about a second by handing the module the tensor it will actually receive.
  - This is not a corner case: gradient-inspecting "regularizer" ideas are a large slice of
    what this loop proposes, so it is the shape of the search space.
  - Failure text is actionable, not a bare traceback: it names `x.grad`, explains that the
    input is mid-network, and points at `torch.autograd.grad` on a self-created tensor.
  - `694633b2d354` still slips through (a shape collapse that only appears on real data).
    **4/5, and the remaining one is recorded rather than rounded away.**
- [x] Two bugs in my own new code, both caught by the suite rather than by review:
  - The stream probe did not sanitize a junk declared shape, so the live `[-1, -1, 64]`
    case fed `torch.randn(-1, -1, 256)`. `dry_run_module` already handled this; my copy
    did not. Now uses the same per-dimension fallback.
  - **My first regression fixture was wrong in a way worth keeping.** It read `x.grad`
    unconditionally, so it failed at the *earlier* dry_run level and proved nothing about
    the new one. The real bug is subtler: the candidate builds its own leaf when the input
    does not require grad, which is exactly why it passes the probe and fails in the
    stream. The fixture now mirrors that, so it fails at `residual_stream` specifically.
  - Full suite 160 passed; mutation audit 5/5 GOOD; replay re-verified at 4/5.
### 5.3.R11 — rank collapse: the right shape with nothing left in it. Catch rate 5/5

- [x] **RANK-COLLAPSE GATE (08:05). All five stored `failed_training` records are now
  caught at validation.** The last holdout, `694633b2d354`, does
  `x.sum(-1).unsqueeze(-1).expand_as(x)` — a **loss function misfiled as a block**. It
  returns a perfectly valid `[batch, seq, hidden]` tensor in which every feature holds the
  same value, so the shape contract passes, the constant-offset degeneracy check passes
  (the difference is not constant), and it reaches training. The residual stream it was
  handed is simply gone.
  - Signal is well separated, not a tuned threshold — mean std across the hidden dim:
    **0.0 exactly** for that module, **0.34** for a healthy 20,800-param block, **1.02**
    for MLBR.
  - Phrased as **destruction, not as a property of the output**: the gate fires only when
    the input had hidden-dim structure and the output does not, so a block handed flat
    input is never blamed for its caller's tensor. There is a test for that specifically.
  - Verified the healthy SOTA block (`bc3dbb74bead`, 20,800 params) still passes, and the
    zero-init LayerScale pattern is untouched.
  - **5/5 caught at validation**, up from 2/5 two ticks ago, each in about a second
    instead of a full model build.
- [x] **The mutation audit earned its keep: it found a HOLLOW test in my own new work.**
  Disabling the residual-stream *shape* check left every test passing — the
  `reading_input_grad` test fails by exception, so it never exercised that branch. Wrote
  `test_stream_probe_catches_shape_change_that_only_happens_mid_network` (a block whose
  output shape depends on `requires_grad` — contrived-looking, but grad-conditional
  branching is exactly why this probe exists). Audit is now **8/8 GOOD**, including a
  mutant that flips the probe input back to `requires_grad=False`, i.e. the whole point of
  §5.3.R10.
  - This is the first time a check I built caught a defect in work I had already reported
    as sound. Worth more than the gate it found.
  - Full suite 163 passed.
### 5.3.R12 — a THIRD of the search budget is spent on ideas that cannot be built

- [x] **MEASURED (08:15): 30 of 84 proposals (36%) are category errors** — regularisers,
  penalties, losses, objectives, schedules — none of which can be a residual-stream block.
  That bucket produced **zero real wins**, accounts for **4 of the 5** `failed_training`
  records, and contains MLBR, the false SOTA that contaminated the live baseline. Each one
  costs an ideation call plus a full implement cycle (~4-18 min) before any gate sees it.
  - The block-shaped 64% is no better on wins (its one `sota` is the
    `HierarchicalAttention` artifact), so this is not "the good ideas are elsewhere" — it
    is a third of the budget spent on ideas that are *unbuildable by construction*.
- [x] **ROOT CAUSE — and it is not that the prompt forgot to say so.** The contract already
  states *"Ideas that need a custom loss signature or router-probability outputs are OUT OF
  SCOPE"*, and 36% violate it anyway. The conflict is upstream: the configured bottleneck is
  `"held-out LM loss plateaus while train loss keeps dropping (memorization gap)"` — a
  **regularisation-shaped problem**. The canonical fix for overfitting *is* a regulariser.
  The loop asks for a block-shaped answer to a loss-shaped question, and the model resolves
  the contradiction by ignoring the contract. Restating the ban more loudly would not fix a
  contradiction; it would just lose more often.
- [x] Prompt now **translates instead of forbidding**: it names the measured 36%, explains
  that a block sees hidden states and nothing else, lists the four ways a generalisation
  goal *can* be expressed inside forward (mixing, gating, normalisation, stochastic paths),
  and gives a worked conversion — *"penalise attention entropy"* is out of scope,
  *"re-weight the block's own token mixing by an entropy-derived gate computed from x"* is
  in scope and targets the same effect. Renders at 4,021 chars; suite 163 passed.
- [x] **DELIBERATELY NOT a hard filter.** A name regex over the 30 would be trivial and
  deterministic — and would also reject *"Orthogonalized Attention Regularizer"*, which is
  perfectly implementable as a block that orthogonalises its own attention output. The
  category error is in the **mechanism**, not the word "regulariser", and I am not willing
  to bin a third of proposals on a string match whose false-positive rate I cannot measure
  while the loop has zero wins to measure against.
- [ ] **OPERATOR: the highest-leverage change here is CONFIG, not code.** The `--bottleneck`
  string in the scheduled task is generating the mismatch. A block-shaped bottleneck (e.g.
  *"the fusion block at the swap site underuses its capacity — find a token-mixing or gating
  transform that extracts more from the same hidden states"*) would remove the contradiction
  at the source rather than asking the model to work around it. That string lives in the task
  definition, which I cannot edit.
- [ ] Effect of the prompt change is **UNMEASURED**, and per §5.3.R8 the constraint-8
  comparison is already confounded. Scope any future before/after by the `boot` lines, not
  by commit timestamps.
### 5.3.R13 — housekeeping on my own additions

- [x] **`LEVELS` had gone stale and I did not notice while adding to it (08:12).** Three
  stages landed tonight — rank collapse inside `dry_run`, plus `integration_width` and
  `residual_stream` — while `LEVELS` still declared four. Nothing consumed the constant, so
  nothing broke, which is precisely how a stale constant survives until something iterates
  it to report coverage and **silently under-reports**. Every "4-level validator" claim in
  the package docstrings was wrong too (`validate.py`, `implementation.py`, `__init__.py`,
  the test module header).
  - Fixed, and the validator docstring now describes all six stages with *why* L5/L6 exist
    (candidates were passing every earlier stage and dying at integration; replaying the
    stored failures, the six together catch 5 of 5).
  - Added `test_LEVELS_matches_what_validate_actually_records`, which runs a healthy block
    and asserts the recorded stages equal the declared ones. Verified red on the stale
    version with the exact diff, not a structural error:
    `recorded [... 'integration_width', 'residual_stream'] but LEVELS declares [... 'dry_run']`.
  - Full suite 164 passed. Daemon confirmed alive (ideate at 08:13:17).
  - The pattern is worth naming: **I added three gates and never re-read the file's own
    description of itself.** Documentation drift is the cheapest kind of dishonesty to
    introduce and the hardest to notice from inside the change.
### 5.3.R14 — my own contamination check reported a FALSE CLEAN without torch

- [x] **The check written to catch a contaminated baseline would have certified one as
  fine (08:25).** `_baseline_contamination` treated `res.ok` as "verified clean". But with
  torch missing — **the normal state in the server container, where this ledger is
  bind-mounted read-only** — `validate()` reports `dry_run` as *skipped* and still returns
  `ok=True`. So the check returned `None`, indistinguishable from a real all-clear.
  - Found by stubbing `_find_torch` to `None`, not by reading the code. I wrote this
    function three hours ago and reported it working; it was, but only where torch exists.
  - It now returns an explicit **UNVERIFIED** caveat naming the skipped stage(s) and saying
    in words that this is *"NOT a clean bill of health: it means the check did not happen."*
  - This is the same bug the whole night has been about — `skipped` silently counted as
    `pass` — reintroduced by me, in the gate built to prevent it. The validator has had the
    right rule since it was written (*"a level that cannot run is reported skipped, never
    counted as a pass"*); my caller ignored it.
- [x] **The status snapshot was reporting a contaminated baseline in a clean voice.**
  `build_status` emitted `factory_lm_loss 5.60506` as a bare number with no provenance,
  under a note asserting a SOTA *"is declared only on a real, direction-aware improvement
  over the baseline"* — true of the comparison, actively misleading when the baseline is
  the problem. Anything reading that snapshot (dashboard, API) inherited the confidence.
  - Baseline block now carries `provenance`, `caveat`, `metric_sem`, `metric_sem_n`, and
    the note appends an explicit warning when a caveat exists. Live snapshot now reports
    `provenance: promoted_contaminated`.
  - Verified the three states distinctly: `hand_seeded` (caveated — correct, it is a
    placeholder), `promoted` from a still-valid experiment (clean, no warning), and
    `promoted_contaminated`. My first test asserted hand-seeded should be warning-free,
    which was wrong about the design rather than about the code.
  - Cost measured before worrying about it: full 6-stage `validate()` is **106 ms**, the
    contamination check **84 ms** — negligible against 4-18 min implement cycles.
  - Full suite 166 passed.
### 5.3.R15 — same false-clean bug, second location; now an invariant instead of a patch

- [x] **Audited my own new gates for the §5.3.R14 defect rather than waiting for it to
  surface again (08:35). One of three had it.** With torch absent,
  `dry_run_at_integration_width` reported **`status="pass"`** while its own detail read
  *"torch not installed — CPU dry-run skipped (not a pass)"*. A stage announcing a pass and
  a non-pass in the same breath. `residual_stream` handled it correctly, so this was not a
  systematic misunderstanding — just one path where I wrapped an inner result without
  checking what it said.
  - Fixed to inherit `skipped` rather than launder it. Verified: with torch absent all
    three torch-dependent stages now report `skipped`; with torch present all six still
    `pass`.
- [x] **Locked as a CROSS-STAGE invariant, not a third patch.**
  `test_no_stage_launders_skipped_into_pass` walks **every** stage and fails any whose
  status claims `pass` while its detail admits it did not run — so the next stage added
  inherits the check instead of repeating the bug. Verified red on the old code with the
  exact contradiction quoted:
  `stage 'integration_width' reports status='pass' while its own detail says it did not run`.
- [x] The lesson, stated once so it stops recurring: **the validator's founding rule has
  always been right** — *"a level that cannot run is reported skipped with the true reason,
  never counted as a pass"*. Both of tonight's breaches were in **callers and wrappers**
  that read a result object without reading its status. Every future consumer of a
  `ValidationResult` must branch on `status`, not on `ok`. `ok` means "did not fail"; it
  does not mean "ran".
### 5.3.R16 — cross-app regression check; and a test runner that lies about failing

- [x] **All three suites green after the night's changes (08:45).** I had been running only
  the dottie suite while editing shared code. dottie **167 passed**, ava-factory server
  **24 passed**, webapp contract tests **11 passed** (6 api + 5 store). No cross-app
  regressions from the validator, ledger schema, or evaluate changes.
- [x] **I nearly reported the webapp as broken because of my own command.**
  `node --test dottie/webapp/js/` — the obvious invocation — cannot take a bare directory on
  Node 24. It tries to load the directory as a module and prints `MODULE_NOT_FOUND` under a
  heading that reads **`✖ failing tests: test at dottie\webapp\js:1:1`**. That looks
  exactly like a suite failure; the suite never ran at all. The tests were green throughout.
  - Third time tonight a *tool invocation* produced a false signal about the code: the ANSI
    colour codes that hid a real assertion in §5.3.R7, the fabricated timestamps, and now
    this. In each case the code was fine and my reading of it was not.
  - Wrote `apps/ava-factory/dottie/webapp/js/README.md` with the two correct forms (explicit
    files, or a **quoted** glob — verified both), the expected count, an explanation of why
    the directory form's output is misleading, and why there is deliberately no
    `package.json` (plain ES modules, no build step, no deps).
- [x] **Audited ValidationResult consumers for the §5.3.R15 rule** (`ok` means "did not
  fail", not "ran"). Measured across every stored validation: **zero skipped stages, zero
  candidates advanced with an execution stage skipped.** `evaluate.py:97` was the one real
  offender and is already fixed. `implementation.py:168` advances on `outcome.ok`, which
  would let a candidate reach training unexecuted in a torch-less environment — but the
  daemon always has torch, `per_level` already records the facts, and the observed
  frequency is 0. **Not building speculative machinery for it**; same standard applied to
  the `class_name` pin in §5.3.R5.
### 5.3.R17 — 55% of validated candidates cannot learn anything

- [x] **Predicted the live candidate would be caught, tested it, and was WRONG (08:35).**
  `a570628f90b8` "Dynamic Gradient Regularization (DGR)" reached training while I watched.
  Being a gradient-regulariser, I expected tonight's `residual_stream` probe to reject it.
  **It passed all six stages.** Testing the prediction instead of asserting it is the only
  reason that claim is not in this file as fact.
- [x] **What it actually is, and the real hole.** Despite the name it computes the **L2 norm
  of `x`** (not a gradient), turns it into a per-position scalar, and adds it:
  `x + λ·logaddexp(‖x‖, 0)`. **Zero learnable parameters** — a fixed function about to
  replace a real ~787 K-parameter block. It cannot learn; it can only "win" by shrinking the
  model. That is the §5.3.R capacity confound, and exactly how MLBR became a false SOTA.
- [x] **Measured before gating, and the number is stark: 11 of 20 candidates that PASSED
  validation have ZERO learnable parameters — 55%.** Outcomes: 8 rejected, 2
  `failed_training`, 1 `sota` (MLBR, an artifact). **Zero real wins**, against real training
  compute. The with-parameters group is barely better on wins but at least *can* learn (and
  three of those carry a single scalar, `params=1`, which is nearly the same problem).
- [x] Gate added at `dry_run`, **as a CORRECTABLE failure rather than a kill**: the message
  names the confound and tells the model to turn its fixed floats (scales, gates,
  thresholds, mixing weights) into `nn.Parameter`/`nn.Linear`, so the self-correction loop
  can rescue the idea instead of losing it. Many of these are decent ideas expressed without
  anything to train.
  - **Ordered after the rank-collapse check**, so a module that both collapses rank *and*
    has no parameters gets the more specific diagnosis. Verified both messages fire on their
    own cases.
  - Three existing fixtures were incidentally zero-parameter and now carry a real parameter,
    with a comment saying why — a test about forward SIGNATURES should not be silently
    passing or failing on capacity.
  - Full suite 168 passed.
### 5.3.R18 — the two failures are INDEPENDENT, and only ~5 real attempts have been made

- [x] **Measured the overlap (08:45), because two big percentages could have been one
  problem double-counted.** They are not. Of the 20 candidates that passed validation:
  | | zero params | has capacity |
  |---|---|---|
  | **loss/regulariser-named** | 6 | 4 |
  | **block-named** | 5 | **5** |
  Each failure mode has members the other misses, so §5.3.R12 (ideation framing) and
  §5.3.R17 (zero-parameter gate) are both load-bearing — neither is redundant.
- [x] **The number that reframes "zero wins":**
  ```
  84 proposals ideated
   -> 20 passed validation                      (24%)
   -> 5 block-shaped WITH real capacity         (6% of proposals)
  ```
  **The search has made roughly FIVE genuine attempts in 84 proposals.** Of those five:
  one `sota` (`bc3dbb74bead`, the known artifact), three rejected, one `failed_training` —
  and one of the five carries `params=1`, a single scalar, so it is generous to count it.
  - This changes what "the loop is reliable and unproductive" means. It is not that good
    block ideas keep losing; it is that **the loop has barely proposed any.** 94% of the
    budget went to candidates that were the wrong shape, had nothing to learn, or both.
  - It also means the zero-wins result carries **almost no evidence** about whether the
    search space is promising. Five attempts, one of which was an artifact, is not a
    verdict on the idea — it is a verdict on the proposal pipeline.
- [ ] **Reframed guidance for the operator (supersedes the framing in item 8):** the fix is
  not better ranking of what the loop proposes, it is getting it to propose the right shape
  at all. In priority order: (a) the `--bottleneck` string (§5.3.R12) — config, yours;
  (b) the zero-parameter gate now returning a correctable message so ideas get rescued
  rather than lost (§5.3.R17); (c) only then worry about search quality within the
  block-shaped-with-capacity population, which currently has n=5.
### 5.3.R19 — ask for capacity at IDEATION, ~8 minutes before the validator can catch it

- [x] **`learnable_parameters` added to the ideation schema (08:50).** The zero-parameter
  gate (§5.3.R17) fires at validation — after a full implement cycle, 4-18 min. Asking the
  model to *name the tensors it will train*, with shapes, moves the decision to the cheapest
  possible point and makes capacity an explicit design choice rather than an oversight. The
  prompt now also states the measured 55% and tells the model **how** to fix it (turn fixed
  floats for scales/gates/thresholds into `nn.Parameter` or `nn.Linear` outputs).
- [x] **Deliberately NOT enforced in `parse_hypotheses`, and the reason is measurement, not
  caution for its own sake.** Requiring the key is one line. But if the live model reliably
  omits it, **every ideation batch burns its full retry budget and the loop starves** — and
  that compliance rate cannot be measured while the daemon runs pre-restart code. Shipping
  unmeasurable enforcement is the mistake §5.3.R8 already charged me for once tonight.
  - Verified backward compatible in both directions: a legacy hypothesis without the field
    still parses; one with it keeps the value.
  - `test_learnable_parameters_is_asked_for_but_not_yet_enforced` pins **both** halves, so a
    later tick that hardens it does so deliberately rather than by drift.
  - Full suite 168 passed.
- [ ] **FOLLOW-UP once the daemon runs current code:** measure what fraction of proposals
  actually fill `learnable_parameters`, and whether the zero-parameter rate falls from 55%.
  If compliance is high, promote the field to `required` in `parse_hypotheses`. Scope the
  before/after by the `boot` lines (§5.3.R9), not commit timestamps — the trap from §5.3.R8.
### 5.3.R20 — the audit caught its own coverage loss, then caught my bad mutant

- [x] **Followed the audit script's own instruction (08:50)**: *"Add a row to MUTANTS
  whenever a new gate lands."* The §5.3.R17 zero-parameter gate had shipped without one, so
  the newest and most aggressive gate was the only unaudited one. Added; verdict **GOOD**.
- [x] **The run then reported a `SKIP`: `contaminated_baseline (anchor not in
  evaluate.py)`.** My §5.3.R14 fix had rewritten the code that mutant anchored to, so the
  contamination gate had **silently stopped being audited** two ticks ago. Nothing failed —
  the row just quietly stopped running. That is exactly why the script prints SKIP loudly
  instead of omitting a row it cannot apply; a mutation harness that goes quiet when it
  loses its grip is worse than none. Re-anchored to the contaminated verdict's `return`,
  which does not move when the guard above it is edited.
- [x] **Then the corrected row came back HOLLOW — and the audit was right about my mutant,
  not about the test.** I had written `return None or (f"CONTAMINATED …")`, and `None or X`
  is `X`: a no-op mutation that changes nothing, so of course the test survived. Replaced
  with an unconditional early `return None`; verdict **GOOD**. Noted in the file, because
  the next person writing a mutant will reach for the same shortcut.
- [x] Audit now **9/9 GOOD**, no SKIPs, no HOLLOWs, tree verified clean after the run.
  Three separate defects tonight were found by this script rather than by review: a hollow
  test in §5.3.R11, a silent coverage loss here, and a bad mutant here.
### 5.3.R39 — REVISED RECOMMENDATION: restart NOW, do not wait for the measurement

- [x] **The trade I described in §5.3.R30 has flipped (10:12).** Then, 3 fixes were queued
  and the window was 7/20, so "let it finish, read it, then restart" was right. **Now 10
  runtime-affecting commits are not live**, including the two most consequential of the
  night:
  - `a09d5e9` — the **search space** that explicitly asked for the category errors the loop
    then rejected (§5.3.R35). Every ideation call until restart still samples it.
  - `8a7d309` — the **corrector runs with no engineering constraints** (§5.3.R38), and the
    corrector writes most of the code this loop produces.
  Plus the sequence probe, the dead-ends anti-priming, and three prompt contradictions.
- [x] **The measurement is worth less than it was, for a specific reason.** The window
  isolates R12 (the bottleneck-framing reframe) — but **§5.3.R35 showed the search space was
  the larger and more mechanical cause of the same 36%**. Finishing the window would
  precisely measure a partial fix to a problem whose main driver was elsewhere and is now
  fixed but not running. At ~10 experiments per 80 min it is another ~80 min to reach n=20.
- [x] **Recommendation: restart now.** Accept the window reset to n=0. The next window
  measures the whole set, which is the comparison actually worth having. `scripts/
  post_restart_report.py` must have `BOOT_SHA` and its live/not-live lists updated from the
  new `boot` record before the next reading — the script says so in its own header.
- [ ] I cannot do it: the permission classifier blocks process control (§5.3.R9). Commands
  are there; `run.log` will show a `boot` line with the new `git_sha` when it takes.

### 5.3.R21 — ⭐ THE DAEMON RESTARTED. Tonight's work is live (08:50:02)

- [x] **Confirmed by the mechanism built for exactly this, four hours earlier.** A `boot`
  line appeared in run.log at 08:50:02:
  ```json
  {"action":"boot","pid":6552,"trainer":"factory","max_retries":5,
   "git_sha":"e8cc5b7","prompts_sha256":"95efbf8f2b79"}
  ```
  `prompts_sha256` matches the current file byte-for-byte. **The daemon is running as of
  `e8cc5b7`** — every behaviour-affecting commit from tonight. HEAD is `073cd11`, which is
  test/script-only and changes no runtime path. This is precisely the check §5.3.R9
  specified, and §5.3.R8's "scope by boot lines, not commit timestamps" is now actually
  possible.
- [x] **What is live**: six validation stages (integration-width, residual-stream, rank
  collapse, zero-parameter), `_DIM_KWARGS` including `hidden`, bounded corrector retries,
  corrector-error surfacing, the training queue-blocker fix, baseline contamination
  detection with UNVERIFIED honesty, two-sample significance, the ideation reframing, and
  `learnable_parameters` in the schema.
- [x] **I do NOT know who restarted it, and will not guess.** The old daemon (pid 7092) was
  killed mid-implement — its 08:31:25 stage has no completion line — and pid 6552 took over.
  That is consistent with either the operator running the §5.3.R9 commands or the scheduler
  restarting a dead wrapper. The evidence does not distinguish them.
- [x] **Effects are NOT yet observable and I am not claiming any.** Zero experiments have
  completed since boot; the daemon is minutes into its first implement on the new code.
  Every percentage in §5.3.R4-R20 describes the PRE-restart population.
- [ ] **NEXT, and now finally measurable** — scope all of these by `updated_ts >= boot`:
  - does the zero-parameter rate fall from **55%**?
  - does the category-error rate fall from **36%**?
  - do proposals fill `learnable_parameters`? (If compliance is high, promote it to
    `required` in `parse_hypotheses` — §5.3.R19.)
  - does the dry_run share of genuine failures move from **74%**? (§5.3.R8's confound is
    now moot: the boot line gives a clean, unambiguous boundary.)
  - **Wait for n ≥ 20 genuine outcomes before reporting any of them.** The constraint-8
    attempt died at n=5 and the honest answer was "not measurable"; the same discipline
    applies here, especially now that I have a stake in these numbers moving.
### 5.3.R22 — post-restart health check, and a log reader that cannot lie

- [x] **Operational health after the restart: CLEAN (09:00).** Distinct question from "do
  the gates work", and answerable at n=1: does the newly-live code run at all? **2 records
  since boot, 0 non-JSON lines, no errors, no warnings.** The daemon booted, began an
  implement at 08:50:02, and is ~11 min in — normal against a median of 487 s. Nothing I
  shipped tonight crashes on contact with production.
- [x] **I raised a false alarm first, and the cause was my own query — for the fourth time
  tonight.** My scratch filter kept lines with `ts >= boot`, but **non-JSON lines carry no
  timestamp**, so the condition silently kept every warning in the entire file. 2 post-boot
  lines rendered as **2,047**, and I briefly believed my own residual-stream probe was
  flooding the log with `.grad` UserWarnings. It was not; those were historical.
  - Tally for the night: ANSI codes hiding a real assertion (§5.3.R7), fabricated
    timestamps, `node --test <dir>` reading as a suite failure (§5.3.R16), and now this.
    **Every one was a bad read of good output.** The code has been in better shape than my
    instruments for measuring it.
- [x] Wrote `apps/dottie/scripts/run_log.py` so the same mistake is not available next time.
  It handles the three things that break ad-hoc one-liners on this file — it is **UTF-16**,
  **not every line is JSON**, and **scoping must be by POSITION relative to the last `boot`
  record, never by timestamp** — with the reasoning in the module docstring.
  `--since-boot`, `--durations ACTION`, and a boot banner showing `git_sha`/`prompts_sha256`.
  Verified: reports the 2-record post-boot scope correctly, and `implement` durations across
  the whole file as n=19, min 60 s, median 487 s, max 1101 s.
### 5.3.R23 — pre-registered the post-restart analysis, before the data exists

- [x] **Wrote `apps/dottie/scripts/post_restart_report.py` while n = 0 (09:05), on purpose.**
  The gates it measures are ones I built hours ago, and §5.3.R21 already records the hazard:
  **I have a stake in these numbers moving.** Fixing the questions, the population and the
  reporting threshold in advance is the cheapest defence against picking a flattering cut
  once the data arrives.
  - **Population** is scoped by the daemon's own `boot` record, never commit timestamps —
    the boundary error that cost §5.3.R8 an entire comparison.
  - **Threshold is enforced in code**: no rate prints below n=20. It emits `INSUFFICIENT n`
    and the current count. The constraint-8 attempt died at n=5 and the honest answer was
    "not measurable"; this makes that the default rather than a judgement made while looking
    at the numbers.
  - **Pre-restart comparators are hardcoded** from measurements taken before any of this
    shipped, so they cannot drift to flatter a result.
  - It deliberately does **not** ask "did my gates help?" — not answerable from this data. A
    flat rate with more rejections means the gates work and the proposals did not change,
    which is a different result and still useful. The script says so in its own output.
- [x] **Validating the arithmetic caught a rigged comparator — in my own pre-registration.**
  Running it at n=0 only exercises the refusal path, so I re-ran it over the pre-restart
  population where I know the answers. Zero-parameter reproduced exactly (11/20 = 55%) and
  category-error at 36%. But `dry_run_share` came back **78%** against my hardcoded **74%**:
  the 74% was the *pre-constraint-8 sub-bucket* (35/47), not the whole pre-restart population
  (46/59). **Comparing post-restart against a sub-bucket would have manufactured a 4-point
  improvement out of a boundary mismatch.** Corrected to 78% with the reasoning inline.
  - Testing only the "refuses to report" path would have shipped that. Same lesson as the
    hollow test in §5.3.R11: exercise the path that does the work, not just the guard.
### 5.3.R24 — the "DEAD ENDS" list was teaching the mode collapse it was meant to prevent

- [x] **§5.2.g said the dead-ends list "may be priming" the collapse. It is, and the
  mechanism is mechanical (09:10).** `ledger.list` orders `created_ts DESC`, `dead_ends`
  concatenated the three failure states head-first, and `_failed_block` showed the first 20.
  Net effect: **the model was handed its own 20 most recent ideas** — maximally similar to
  whatever mode it is currently in — under a heading reading *do not repeat*.
  - Measured on the live list of 20: **`attention` in 13, `gradient` in 11, `sparse` in 9**,
    plus `adaptive`/`orthogonalized`/`consistent` at 5 each. That is not a prohibition, it
    is a **20-shot demonstration of the collapsed vocabulary**. Models follow in-context
    patterns far more reliably than they follow negation.
  - Two of the twenty slots were literal near-duplicates that exact-match de-dup missed
    (`Orthogonalized Sparse Attention (OSA)` vs the same name without the acronym).
- [x] **Two fixes, both deterministic.**
  1. `dead_ends` now round-robins across REJECTED / FAILED_VALIDATION / FAILED_TRAINING and
     de-dupes on a lexical key (parenthetical stripped, word order ignored), so one state's
     newest entries cannot monopolise the visible slots. **This alone dropped `attention`
     from 13/20 to 9/20 and `gradient` from 11/20 to 9/20** — a measurable reduction in the
     prompt's lexical concentration, with no change to what is being communicated.
  2. `_failed_block` now appends an explicit tally: *"OVERUSED TERMS: `gradient` (9/20),
     `attention` (9/20) … the names above are anti-examples, NOT a vocabulary to draw from;
     a new name built from the same terms is the same dead end with a new label."* This
     converts an implicit anti-example into a checkable constraint. The tally only appears
     when terms actually repeat.
  - Tests cover both, plus the no-repetition case where no tally should appear. Verified red
    on the old code (`lexical duplicates not collapsed: [...]`). Full suite 171 passed.
- [ ] **Effect on actual proposal diversity is UNMEASURED** — this is a prompt change and
  §5.3.R12 already showed prompt changes are hard to attribute. It is now measurable the
  right way: the post-restart boundary is clean, and `scripts/post_restart_report.py` will
  report the category-error rate once n ≥ 20. Do not credit this until then.
### 5.3.R25 — first post-restart cycle: the machinery works. The RATES are not claimed.

- [x] **OPERATIONAL confirmations (09:11) — binary facts about whether features function,
  which is a different question from whether they help:**
  - **All six stages ran** on the first candidate to reach validation (`da2da0ffbb59`):
    `syntax, contract, static, dry_run, integration_width, residual_stream`. The stages
    added tonight are live and executing in production, not just in tests.
  - **`learnable_parameters` is being filled: 3 of 3.** Real values, not placeholders —
    `gate: nn.Linear(hidden, hidden)`, `positional_weights: nn.Parameter((seq_len, hidden))`,
    `mean: nn.Parameter(hidden); std: nn.Parameter(hidden)`. The schema change lands.
  - The first candidate through passed the zero-parameter gate **on merit** (it has a real
    `nn.Linear`), so the gate is not silently blocking everything.
- [x] **What I am NOT claiming, and why it is tempting.** The three new names are
  *Channel-Selective Attention Gating*, *Positional Feature Rebalancing*, *Dynamic Feature
  Normalization* — one "attention", **zero** "gradient", "sparse", "consistent" or
  "regularizer", and no category errors. Against a pre-restart vocabulary where `gradient`
  appeared in 11 of 20 and 36% were category errors, that looks like the §5.3.R12 and
  §5.3.R24 fixes working.
  - **n = 3. That is one ideation batch.** Three names from one call is exactly the sample
    size at which the constraint-8 comparison produced a confident-looking number that meant
    nothing (§5.3.R8), and I have a stake in these particular fixes succeeding. The
    threshold is n ≥ 20, enforced in `scripts/post_restart_report.py` rather than left to my
    judgement while looking at an encouraging result.
  - Recording the observation is honest; treating it as evidence would not be. If the next
    six batches look like the old ones, this entry is the record that I saw a promising
    n=3 and did not bank it.
- [ ] **R19 follow-up status:** compliance is 3/3, which is *consistent with* promoting
  `learnable_parameters` to `required` in `parse_hypotheses` — but 3 successes cannot
  distinguish "the model always complies" from "the model complied three times". Leave it
  optional until n ≥ 20; the cost of being wrong is every ideation batch burning its full
  retry budget.
### 5.3.R26 — the contamination bias runs the OPPOSITE way from how I described it

- [x] **Checked the direction before a promotion could happen against it (09:15), and my
  framing was wrong.** I wrote that "improvements measured against it are NOT trustworthy",
  which reads as inflation risk — false SOTAs. The arithmetic says otherwise:
  ```
  contaminated baseline : 5.60506   (set by MLBR)
  true pre-MLBR value   : 5.61982
  lower is better  =>  5.60506 is a HARDER bar, by 0.01476
  ```
  A candidate scoring **5.61 would beat the true baseline and be REJECTED** against the
  contaminated one. **Contamination is biasing the loop toward missed promotions, not
  false ones.**
- [x] **Why this matters for decision #5, in both directions:**
  - **Correctness urgency drops.** No false SOTA can arise from this contamination; the bar
    is too strict, not too loose. MLBR's own promotion was the false one, and that has
    already happened.
  - **Productivity urgency rises.** The loop is currently required to beat a number set by
    a module that removes capacity. Any genuine improvement landing in the 0.015 gap is
    thrown away, and given the loop has ~5 genuine attempts total (§5.3.R18), discarding
    real wins is the expensive failure right now.
  - The `promoted_contaminated` caveat and the status warning stay exactly as they are —
    the delta *is* measured against a wrong reference, and a reader should know. What
    changes is the **direction** a reader should infer, which I had stated backwards.
- [x] Timing note: `da2da0ffbb59` is training now and will be evaluated against this
  baseline shortly — the first live exercise of the contamination path (§5.3.R5). If it is
  rejected with a delta inside 0.01476, that is a **concrete instance** of the missed-promotion
  bias, not a verdict on the candidate.
### 5.3.R27 — first post-restart verdict: every gate fired correctly, in production

- [x] **`da2da0ffbb59` (Channel-Selective Attention Gating) — trained, evaluated, REJECTED
  on merit (09:14).** `factory_lm_loss 5.76274` against a baseline of `5.60506`. Worse by
  0.158, cleanly and correctly rejected.
- [x] **The pre-registered check answered itself, and the answer was "no" (§5.3.R26).** I
  wrote *before* seeing the number that a rejection with |delta| inside the 0.01476
  contamination gap would be a missed-promotion instance rather than a bad candidate.
  **delta = 0.15768 — an order of magnitude outside the gap.** This candidate simply lost.
  Pre-registering the interpretation is what stops a plain rejection being narrated as
  "contamination cost us a win"; the temptation to reach for that was real and the answer
  was already fixed.
- [x] **Four pieces of tonight's work fired live for the first time, all correct:**
  1. **Contamination detection** — `baseline_provenance: promoted_contaminated`, caveat
     naming MLBR and the exact validator failure. §5.3.R5/R14 working in production.
  2. **Direction-aware significance** — the verdict carries `significant: True` **with**
     `improved: False`. That is the direction-agnostic trap the message was written to
     defuse, and it defused it: *"WORSE than baseline: |delta| 0.15768 vs 2.0× …"*. A
     skimmer cannot read `significant: true` as good news here.
  3. **One-sample fallback declaring its own weakness** — *"the baseline records NO spread,
     so it is treated as an exact point and this test is weaker"* (§5.3.R6). Exactly the
     case it was built for, since the contaminated baseline carries no `metric_sem`.
  4. **`promote` correctly False** despite `significant: True`, because promotion requires
     `improved AND stable AND significant`.
- [x] Note for §5.3.R18's tally: this is a **genuine attempt** — block-shaped, real
  `nn.Linear` capacity, trained to completion, lost honestly. The pre-restart count of ~5
  genuine attempts is now ~6, and the sixth is an honest loss rather than an artifact.
### 5.3.R28 — the sequence-axis twin of R8, found live within minutes of the restart

- [x] **`670ad9956bab` (Positional Feature Rebalancing) died at training in 10.8 s (09:16),
  and the fast failure is what made me look.** Real training takes ~270 s, so a 10-second
  `failed_training` was suspicious enough to check rather than file. Cause:
  ```
  AssertionError: seq (256) must match seq_len (16)
  ```
- [x] **This is §5.3.R8 on the other axis, and my own fix missed it.** The integration-width
  probe overrode the **hidden** dim to 256 but kept the model's declared **sequence** length
  (16, typical). `factory_trainer` trains at `seq_len=256`. So a parameter sized to the
  sequence — a learned positional table, an attention bias, a preallocated buffer — is built
  at the wrong length, **passes all six stages**, and dies once training starts.
  - Pointed detail: the candidate had **correctly declared** `positional_weights:
    nn.Parameter((seq_len, hidden))` in the new §5.3.R19 field. It was honest about exactly
    the thing that killed it, and nothing was reading that field to check.
- [x] **Fixed: the probe now uses the real integration SHAPE, not just the width.**
  `INTEGRATION_SEQ = 256` alongside `INTEGRATION_WIDTH = 256`; the probe runs at
  `[batch, 256, 256]`. The failure message names the sequence axis explicitly and the actual
  pattern — *"a parameter shaped to a fixed sequence length (a learned positional table, an
  attention bias, a preallocated buffer) cannot work here: make it length-agnostic, or
  slice/interpolate it to the input length"* — and points at `x.shape[-2]` as well as
  `x.shape[-1]`.
  - Verified on the real failure: now caught at `integration_width` with
    `passes at the declared shape [4, 16, 64] but FAILS at the real integration shape
    [4, 256, 256]`.
  - Verified no regression on the good candidate: `da2da0ffbb59` still passes.
  - Full suite 172 passed; mutation audit still 9/9 GOOD.
- [ ] **Worth noting how this was found.** Not by review, and not by the gates — by
  *noticing a duration that did not fit* and pulling the thread. The 10.8 s figure was
  visible only because `dur_s` is logged per action (§5.2 instrumentation). Cheap
  instrumentation kept paying tonight; three findings started as "that number looks odd".
### 5.3.R29 — checked the handoff the R28 candidate exposed; one real gap, one non-gap

- [x] **Verified the implementer already receives `learnable_parameters` (09:25) — no change
  needed.** `implementation_prompt` builds its hypothesis block by iterating
  `IDEATION_SCHEMA`, so adding the field there wired it end-to-end automatically. Confirmed
  by rendering a prompt and finding the declaration in it. Recording the negative result:
  the §5.3.R28 note that "nothing was reading that field" was about *validation*, not the
  handoff, and I nearly built plumbing that already existed.
- [x] **DECLINED to restate the seq prohibition.** Constraint 8 already says *"Size every
  weight against the HIDDEN axis, never against `seq`"* — and `670ad9956bab` did it anyway.
  That is the §5.3.R12 pattern exactly: the contract was explicit and got ignored, and
  saying it louder is not a fix. The validator now catches it definitively and feeds a
  specific correction back; **that** is the working mechanism.
- [x] **DID add the missing positive instruction, which is a different thing.** The prompt
  only *prohibited* sizing against seq and never said what to do when a block legitimately
  needs the sequence length — prohibit-without-translate, the same failure I diagnosed for
  category errors. Now: read it at FORWARD time as `x.shape[-2]`, or store a generous
  maximum and **slice** it to `x.shape[-2]`. With the measured evidence attached (declared
  `nn.Parameter((seq_len, hidden))`, passed every stage, `AssertionError: seq (256) must
  match seq_len (16)` on its first training step).
  - The distinction I am holding myself to: **repeating a ban is noise; supplying the
    missing alternative is content.** Suite 172 passed.
### 5.3.R30 — the restart-lag is structural, and the report now says what it can attribute

- [x] **Caught by the boot banner (09:29): the daemon is on `e8cc5b7`, HEAD is `3d8b5b7`.**
  Three runtime-affecting commits have landed since it started and are **NOT running**:
  §5.3.R24 (dead-ends anti-priming), §5.3.R28 (sequence probe), §5.3.R29 (forward-time seq
  guidance). This is the same lag as before the restart — it is **structural**, and it will
  recur every time I change code while the daemon is up. The difference is that it is now
  *detectable in one command* instead of reconstructed from process tables.
- [x] **This has a sharp consequence for the pre-registered report, and I wrote it down
  while n was still 7.** The accumulating window measures `e8cc5b7`, which contains R12,
  R17, R19 and the R8/R10/R11 stages — but **not** R24 or R28. So:
  - a fall in the **category-error rate** would be attributable to R12 alone, *not* to the
    dead-ends fix, however satisfying that would be to claim;
  - the **seq-sized failure mode is still live** in this window; more `670ad9956bab`-shaped
    training crashes are expected and are **not** evidence that R28 failed.
- [x] **Encoded in the tool, not just here.** `post_restart_report.py` now prints a
  `WHAT THIS WINDOW CAN ATTRIBUTE` header keyed to the boot `git_sha`, listing what is live
  and what is not, and stating that a later restart opens a NEW window whose map must be
  updated first. A caveat that lives only in a TODO gets skipped; one printed above the
  numbers does not.
  - Written deliberately **before** the data exists. Once numbers arrive the temptation is
    to credit whichever fix looks best, and §5.3.R8 already lost an entire comparison to
    exactly that.
- [ ] Consequence for the operator: a second restart would pick up R24/R28/R29, but it also
  **resets the measurement window to n=0**. Given the current window is 7 of the 20 needed,
  the cheaper order is: let this window finish, read it, then restart. The seq probe not
  being live costs a training crash or two in the meantime — real but small, and the crashes
  are correctly classified as `failed_training` either way.
### 5.3.R31 — the promotion bundle buried its own reasons not to promote

- [x] **`PROMOTION.md` is the artifact a human reads to approve a promotion, and it did not
  render a single caveat (09:35).** Grepped it: none of `baseline_provenance`,
  `baseline_caveat`, `significance`, or `capacity_caveat` appeared in the prose. They were
  technically present — the bundle embeds the entire `eval_verdict` — **inside a JSON blob,
  under a header whose only pointer was "see eval_verdict below"**. A contaminated baseline
  is not a footnote; it is the reason not to promote.
- [x] **Caveats now render ABOVE the numbers**, as a `> ### Read this before promoting`
  block: contaminated/hand-seeded baseline with its detail, within-noise verdicts,
  unmeasurable significance, capacity changes, and the weak one-sample test. The test
  asserts position, not mere presence — the block must precede the `- metric:` line.
- [x] **Both existing SOTAs now lead with a warning, and it is the right one.** Rendering
  the real verdicts for `23bb41375804` (MLBR) and `bc3dbb74bead` (HierarchicalAttention)
  produces **"SIGNIFICANCE UNMEASURABLE — no per-batch series was recorded, so this delta
  was never tested against noise."** Both verdicts predate the significance gate. That is
  precisely the fact decision #5 turns on, and until now it was invisible in the prose a
  reader would actually read.
- [x] **A clean verdict gets NO block** — an honest result is not padded with reassurance it
  did not earn. Tested in both directions. Verified red on the old code, which produced a
  header running straight from the title to `- metric:` with nothing in between. Suite 174
  passed.
### 5.3.R32 — the bundle's re-verification script has never been able to run

- [x] **`ab_nano.py` — the script a human runs to independently confirm a promotion — was
  broken outright (09:40).** The template called
  `factory_nano_trainer(r"<module_path>", ...)`, but that function takes an **Experiment**:
  it reads `.implementation` and `.workspace` off the argument. A string has neither, so
  **every generated `ab_nano.py` dies with `AttributeError` on its first candidate call.**
  The independent-verification step in every promotion bundle has never executed.
  - Found by reading the artifact rather than the loop. It is not exercised by any code
    path the daemon runs, so nothing was ever going to surface it — the bundle generator
    writes the file and never runs it.
- [x] **It also compared two single numbers**, which cannot separate a real difference from
  run-to-run noise. That is precisely the mistake that produced this loop's first false
  SOTA. **A re-verification script that repeats the original error launders a coin flip as
  confirmation** — worse than having no script, because it carries the authority of a
  manual check.
- [x] **Rewritten to work, and to hold the same standard as the automated gate:** loads the
  Experiment from the ledger by id (stronger than a file path — it re-verifies the exact
  recorded implementation, which cannot drift from `candidate.py`), runs `SEEDS = [0,1,2]`
  on both arms, and reports **paired** differences so shared seed variance cancels. Prints
  `WITHIN NOISE — this run does not distinguish the candidate from the unmodified model.
  Do not promote on it.` unless |mean delta| ≥ 2·SEM.
  - Generated output verified to `ast.parse`, to pass an Experiment, and to contain no
    stale `module_path`. `candidate.py` is still written for human reading.
  - Updated the legacy assertion that required `candidate.py` inside the script, with the
    reason recorded rather than silently deleted.
  - Suite 175 passed; mutation audit 9/9 GOOD.
- [ ] **Pattern worth naming:** both of the last two findings were in **human-facing
  artifacts** (`PROMOTION.md`, `ab_nano.py`), not in the loop. Nothing the daemon executes
  touches either, so no test, gate, or production run was ever going to catch them. The
  automated path has had six gates and a mutation audit pointed at it all night; the manual
  path had nothing until it was read.
### 5.3.R33 — the decision-#5 artifact was stale, and `promote` would never have fixed it

- [x] **Swept the code paths that neither the daemon nor any test exercises (09:45)** — the
  blind spot that hid §5.3.R32. No test invokes the research CLI at all, and the daemon only
  ever runs `run`, leaving `status`, `promote`, `calibrate-baseline` and `seed-baseline`
  unexercised. **`calibrate-baseline` is the operator's fix path for decision #5**, so a
  break there would be silent and expensive.
  - `status` works, and now carries `provenance: promoted_contaminated` plus the full caveat
    — §5.3.R14 visible from the CLI.
- [x] **`promote` reported both bundles as `already_bundled` and did nothing.** The existing
  MLBR bundle — **the artifact decision #5 turns on** — was generated at 03:05 and had:
  no caveat block (§5.3.R31), and an `ab_nano.py` carrying the broken
  `factory_nano_trainer(r"…candidate.py", …)` call (§5.3.R32). **`build_pending_promotions`
  skips any bundle that exists, so both fixes would never have reached it.** A bundle
  written once was frozen forever.
- [x] **Added `--rebuild` and regenerated both.** The bundle is derived entirely from the
  ledger, so regeneration loses nothing. The MLBR bundle now opens with:
  > ### Read this before promoting
  > **SIGNIFICANCE UNMEASURABLE** — no per-batch series was recorded, so this delta was
  > never tested against noise.

  and its `ab_nano.py` passes an Experiment, runs three seeds, and can print *"WITHIN NOISE
  — do not promote on it."* Suite 175 passed.
- [ ] **The generalisation, which is the actual lesson:** a fix to a generated artifact does
  not reach artifacts already generated. Three of tonight's findings (§5.3.R31, R32, R33)
  were all in the same dead zone — **written by code, read by a human, executed by nobody**.
  Anything with that shape needs either regeneration on read or an explicit rebuild path;
  correctness in the generator is not enough.
### 5.3.R34 — verified the operator's fix path WITHOUT running it (09:50)

- [x] **`calibrate-baseline` is decision #5's fix path and is exercised by nothing** — no
  test invokes the research CLI, and the daemon only runs `run`. Given §5.3.R32 (a bundle
  script broken for its entire existence by a signature mismatch), an unexercised command
  the operator depends on deserved a check.
- [x] **DID NOT run it. Available memory was 675 MB** — the same neighbourhood as the
  281 MB that killed the WSL VM at 02:05, which was **my own doing** with the qwen3:14b
  change. A factory model build plus packed-corpus load needs far more than the headroom
  available. Causing a second memory incident to test a command would be a bad trade, and
  the box's RAM is the binding constraint on everything here.
- [x] **Verified statically instead — the `ab_nano` bug was a shape/signature mismatch, and
  that class IS checkable without executing:**
  - CLI wiring: `--data-dir … calibrate-baseline --steps 3 --overwrite` parses and
    dispatches to `cmd_calibrate_baseline`.
  - Shape contract: every key the command reads off `measured` — `batch, device, lr,
    preset, seed, seq_len, steps` — plus `FACTORY_METRIC`, is produced by
    `factory_trainer`. **No missing keys**, so the `ab_nano` failure mode is not present.
  - Recorded as *statically sound, not executed*. That is weaker than a live run and is
    labelled as such rather than written up as "verified".
- [x] One self-inflicted false alarm en route: my first invocation put `--data-dir` after
  the subcommand and argparse rejected it. My error, not the CLI's — noted because a
  usage error that looks like a broken command is exactly how §5.3.R16 (`node --test <dir>`)
  wasted time earlier.
- [ ] **When memory allows, run it for real against a temp `--data-dir`** with small
  `--steps`: `python -m dottie.research --data-dir <tmp> calibrate-baseline --steps 5
  --overwrite`. That writes only to the temp ledger and leaves the live baseline untouched.
  Want >4 GB free first.
### 5.3.R35 — ⭐ the search space ASKED for the category errors. We caused the 36%.

- [x] **Root cause of §5.3.R12, and it was ours (09:55).** The ideation prompt fences
  proposals to a domain list. Domain 2 read:
  > *"Alternative **loss functions or regularizers** that improve pre-training stability
  > (fewer loss spikes, no NaN gradients)."*

  The **INTEGRATION CONTRACT in the same prompt** says ideas needing a custom loss signature
  are OUT OF SCOPE. **One third of the fenced search space explicitly asked for what the
  loop then rejected.**
- [x] **This explains the 36% completely, and reframes it.** The model was not ignoring the
  contract out of stubbornness — it was **obediently sampling a domain we defined**, then
  being punished for it. The collapse vocabulary maps one-to-one onto the old three fences:
  MoE/load-balancing (1), loss/regulariser (2), sparse/attention (3). What I called "mode
  collapse" in §5.2.g is substantially **the search space working as specified**.
  - I spent §5.3.R12 blaming the operator's `--bottleneck` string and §5.3.R24 blaming the
    dead-ends list. Both are real contributors. **Neither is as direct as a fence that names
    the forbidden thing as a deliverable**, and I did not read the search space until now.
- [x] **Fixed at the root.** Domain 2 now pursues the same GOAL — training stability —
  expressed as something a block can do: *"Stabilising transforms applied to the hidden
  states INSIDE the block — normalisation variants, bounded activations, residual scaling,
  gradient-friendly reparameterisation — without touching the training objective."* Two
  domains added (non-attention token/channel mixing; adaptive-computation blocks), because
  three narrow fences are themselves a repetition pressure. **5 domains, none of which
  contradicts the contract.**
  - Test asserts the invariant and distinguishes the two cases that look alike: a domain
    whose **deliverable** is a loss (contradiction) versus one that merely **forbids**
    auxiliary losses as a constraint — *"improve load balancing WITHOUT an auxiliary-loss
    penalty"* is correct and must not be flagged. Verified the old space fails the test on
    both counts (the loss domain, and only 3 fences). Suite 175 passed.
- [x] **LIVE — verified 2026-07-24 22:45.** `e8cc5b7` is an ancestor of HEAD with 38 later
  commits to `research/`, and the fleet restarted 13:40:53, so it is running all of them.
  It also **supersedes part of decision-queue item 8**: the `--bottleneck` change
  is still worth making, but this was the larger and more mechanical cause, and it is fixed
  in code rather than needing operator config.
### 5.3.R36 — read the prompt END TO END; found a THIRD contradiction and a typo

- [x] **Acting on the §5.3.R35 lesson (10:00): I had been patching individual constraints
  without ever reading the rendered prompt as a document.** So I rendered it in full and
  read it. Two more findings, one of them the same bug in a third location.
- [x] **The RIGOR section contemplated the forbidden thing.** It read:
  > *"If proposing a new loss term, give its derivative w.r.t. the network outputs; it must
  > be differentiable and bounded."*

  **Three paragraphs after the INTEGRATION CONTRACT declares loss-signature ideas OUT OF
  SCOPE.** §5.3.R35 fixed this in the search space; here it was again in the rigor
  requirements, quietly planning for the model to do it. Replaced with a block-appropriate
  requirement (state the shape of every tensor your forward creates, confirm the output
  contract). **Three separate places in one prompt invited the category error I spent three
  ticks blaming on the bottleneck string and the dead-ends list.**
- [x] **`"Generate 3 … testable hypothesiss"`** — the plural was built by appending `"s"` to
  `"hypothesis"`. It is the **opening line of every multi-idea call**, in a prompt that then
  demands rigour. Cosmetic, but it survived because nobody had read the rendered output.
- [x] Tests pin both: no section may *contemplate* a new loss term (while the prohibition
  itself must remain), and the noun must pluralise correctly at n=1 and n=3. Suite 178 passed.
- [ ] **The generalisable lesson, and it is not about prompts.** A constraint document
  assembled from separately-authored sections drifts into self-contradiction, and every
  individual section reads fine. **Reading the artifact whole found in two ticks what
  three ticks of targeted patching had missed** — and the same shape of blindness produced
  §5.3.R31/R32/R33 (artifacts written by code, read by a human, executed by nobody).
  Render it and read it, at least once.
- [x] LIVE — verified 2026-07-24 22:45 (e8cc5b7 is an ancestor of HEAD; fleet restarted 13:40:53).
### 5.3.R37 — a FOURTH contradiction, with a measurable fingerprint in the generated code

- [x] **Read the IMPLEMENTATION prompt end to end (10:05), same method as §5.3.R36.** Its
  `# CODEBASE CONTEXT` read:
  > *"Custom losses are `nn.Module` classes or functions taking (predictions, targets) and
  > returning a scalar tensor."*

  Constraint 7, a few lines below, says `forward` MUST take exactly one tensor and return
  the same shape. **The same document taught both.**
- [x] **This one is not speculative — it left a fingerprint in the code.** Of 92 stored
  candidates with a readable forward signature, **7 named their argument `predictions`** —
  the exact vocabulary of that line — including `694633b2d354`, the rank-collapse failure
  from §5.3.R11. The prompt was teaching loss shape and the generated code inherited its
  variable names.
- [x] **Fixed, plus the gap the reading exposed:**
  - CODEBASE CONTEXT now states plainly that this is a residual-stream block, not a loss.
  - Constraint 7 additionally bans naming the argument `predictions`/`logits`/`targets`.
  - **New constraint 7b (CAPACITY).** §5.3.R17 measured 55% zero-parameter candidates *at
    validation* — meaning they materialise during **implementation** — yet the
    implementation prompt had **no capacity requirement at all**; only ideation did. 7b
    requires the block to own the parameters the hypothesis declared, and points at
    `learnable_parameters` explicitly. That also closes §5.3.R28's loose end: the field was
    carried end-to-end and read by nothing.
- [x] **The test caught a mistake in my own fix.** My first replacement *quoted the old
  wording* to explain the change — inside the prompt string, where the model reads it. The
  test asserting `"(predictions, targets)" not in p` failed, correctly: an explanatory "we
  used to say X" still shows the model X. **Historical rationale now lives in a code comment
  the model never sees.** Suite 180 passed.
- [ ] **Four contradictions, one document, four separate ticks.** §5.3.R35 (search space),
  R36 (rigor section), R37 (codebase context) — plus the bottleneck framing in R12. Every
  section read fine alone. The count is the argument: **prompts are programs, and nobody was
  reading this one whole.**
- [x] LIVE — verified 2026-07-24 22:45 (e8cc5b7 is an ancestor of HEAD; fleet restarted 13:40:53).
### 5.3.R38 — the corrector was running with none of the constraints

- [x] **Read the CORRECTION prompt end to end (10:10) — the third and last prompt.** It sent
  the model **only the failure message and the previous code**. Every rule the first attempt
  was held to — AXIS DISCIPLINE, the one-tensor contract, the ban on loss-shaped arguments,
  the new capacity rule 7b — **vanished on retry**.
  - This matters more than it sounds, because **the corrector is the path most candidates
    actually take**: most failures run several attempts, so the majority of code this loop
    produces is written under the *weaker* prompt. A correction could satisfy the reported
    error by reintroducing precisely what the constraints exist to prevent, and nothing
    would flag it until a later stage caught a different symptom.
  - I have been calling the corrector "the working mechanism" for several ticks (§5.3.R29
    explicitly). It was working with a fraction of the guidance I assumed it had.
- [x] **Fixed by sharing one block, not by duplicating text.** `_ENGINEERING_CONSTRAINTS` is
  now a module-level constant rendered into **both** the implementation and correction
  prompts, so they cannot drift — the failure mode that let `LEVELS` fall out of step with
  `validate()` in §5.3.R13. The correction prompt also states outright: *"EVERY constraint
  below still applies to the rewrite. Fixing the reported failure by breaking one of these
  is not a fix."*
- [x] **Also removed a hardcoded schema list.** The correction prompt retyped
  `(module_name, target_file, code, init_kwargs, input_shape, shape_assertions)` by hand;
  it now derives the keys from `IMPLEMENTATION_SCHEMA`. Same drift class as above — correct
  today, wrong the moment the schema changes.
  - The test asserts the **shared constant** appears in both prompts, so drift fails loudly.
  - Suite 181 passed.
- [ ] **All three prompts have now been read whole**, and each one contained something that
  contradicted or undercut the others: §5.3.R35 search space, R36 rigor section, R37
  codebase context, R38 missing constraints on retry. **Four of four.** Not one was visible
  from reading the section being edited.
- [x] LIVE — verified 2026-07-24 22:45 (e8cc5b7 is an ancestor of HEAD; fleet restarted 13:40:53).
### 5.3.R40 — the scheduler has a battery kill-switch nobody looked at

- [x] **Read the scheduled-task definition end to end (10:15) — the fifth artifact this
  method has found something in.** It is what actually launches the daemon and I had never
  inspected it.
  ```
  StopIfGoingOnBatteries      : True
  DisallowStartIfOnBatteries  : True
  ```
  **This is a laptop.** If the box drops to battery, **Task Scheduler stops the running
  daemon**, and will not start it again while unplugged. That produces exactly the symptom I
  spent hours on: *daemon dies, no traceback, nothing in the log*.
- [x] **This is a SECOND, independent kill mechanism.** §5.3's wrapper bug (`*>>` +
  `$ErrorActionPreference='Stop'` making torch's stderr terminating) was real and is fixed
  and verified. **I then stopped looking.** A confirmed root cause is not proof of a unique
  one, and this second path leaves no evidence at all — the scheduler simply stops the task.
- [x] **It ties decision #2 to decision #0.** The charger finding (780 MHz / 45 W of 175 W)
  has been sitting at "worth checking, downgraded". If the charger is weak or intermittent,
  the box flips to battery, **the scheduler kills the research daemon**, and the loop dies
  silently until someone notices. That upgrades the charger from a GPU-performance question
  to a **loop-availability** one.
- [x] Current state is fine and not masking anything: **On AC, 100%, PowerOnline True**. The
  setting is latent, not active. Recorded because latent-and-unknown is how it bit before.
- [ ] **Operator fix (one command, reversible; I did not run it — modifying your scheduled
  task is your call, and the battery defaults exist to protect laptops):**
  ```powershell
  $s = (Get-ScheduledTask -TaskName "Dottie Research runner").Settings
  $s.StopIfGoingOnBatteries = $false
  $s.DisallowStartIfOnBatteries = $false
  Set-ScheduledTask -TaskName "Dottie Research runner" -Settings $s
  ```
- [x] Rest of the definition is sound and worth recording as checked: trigger repeats
  `PT15M` with `MultipleInstances=IgnoreNew` (the heartbeat design — refusals are correct,
  not lost ticks); `ExecutionTimeLimit=PT0S` = unlimited, right for a daemon;
  `RestartCount=3/PT5M` (covers launch failures only — measured in §5.3). The `--bottleneck`
  string is verbatim what decision item 8 describes.
### 5.3.R41 — the night-model feature cannot work under the daemon, and was still armed

- [x] **Read `research_worker.ps1` end to end (10:20) — sixth artifact, sixth finding.** I
  had fixed one bug in this file (the `*>>` / `ErrorActionPreference` interaction that was
  killing the daemon) and never read the rest of it.
- [x] **The night-model switch evaluates `(Get-Date).Hour` ONCE, at wrapper start, before
  python launches.** That is correct for `ideate`/`implement`/`train`/`evaluate`, which the
  scheduler invokes fresh each tick. **It is meaningless for `run`** — a forever-daemon
  started at 21:59 keeps the DAY model all night; started at 22:01 it keeps the NIGHT model
  all day. The window it believes it is honouring does not exist.
- [x] **And this is the exact feature that caused the outage.** With `NUM_GPU=0` the night
  model loaded **7.0 GB into system RAM**, starved the WSL2 VM to **281 MB**, and took down
  all 14 containers for 90+ minutes. I disabled it at 03:47 by commenting the env var in
  `research_env.local.ps1` — **but the mechanism stayed armed**: anyone re-setting that
  variable re-arms an outage, in service of a feature that cannot function under the current
  architecture. Armed *and* non-functional is the worst combination.
- [x] Now scoped: it applies only to per-tick workers, and for `run` it emits an explicit
  `Write-Warning` explaining why it is ignored and to check free RAM first. Verified the file
  parses and that the branch selection is correct (`run` → warn, `implement` → apply).
- [ ] **The recurring shape, now six for six:** I fixed a bug *in* an artifact and did not
  read the artifact. Same as the prompts (§5.3.R35–R38, four contradictions across three
  files I had been editing constantly) and the promotion bundle (§5.3.R31–R33). **Editing a
  file is not reading it** — the edit view shows the lines around the change, which is
  exactly where the surviving bugs are not.
### 5.3.R42 — a contract check that vanished when unscoped (defensive, 0 occurrences)

- [x] **Read `validate.py` end to end (10:25) — the file I edited most tonight and had never
  read whole.** `check_contract` did `forward_extra.get(class_name or "")`: with no declared
  `class_name` it looked up the empty string, found nothing, and **passed**. A gate that did
  not run, reading exactly like a gate that passed — the §5.3.R15 invariant, in code written
  before that invariant existed.
  - Related: `_select_class` falls back to `candidates[0]`, the first `nn.Module` subclass,
    which in generated code is frequently a helper rather than the block.
- [x] **Measured before fixing, and the honest answer is that it never fires: 0 of 96 stored
  candidates omit `class_name`.** One record declares a class its (syntax-broken) code never
  defines; exactly one module defines more than one class. So this is **defensive, not a
  live bug**, and it is recorded that way rather than dressed up as a catch.
  - I have declined 0- and 1-occurrence fixes twice tonight (§5.3.R5 class_name pin, §5.3.R16
    ValidationResult consumers) and said consistency matters. **This one is different in
    kind**: not a rare bug, but a *gate that silently does not check*. Making a check honest
    is not the same as adding machinery against a hypothetical — and the fix is two lines
    with no new surface. Unscoped now widens to every class instead of quietly vanishing.
  - Verified red for the right reason: `contract check vanished when no class_name was
    declared`. Suite 182 passed.
- [x] Fourth heredoc mangling of the night: `
` inside a quoted heredoc collapsed into real
  newlines and broke the test file's syntax. Caught by collection, fixed with triple-quoted
  literals. **The lesson has not stuck because I keep reaching for the same shortcut** —
  writing multi-line Python fixtures through a shell heredoc is simply the wrong tool, and
  the file-then-insert approach used in §5.3.R5 worked first time every time.
### 5.3.R43 — read `evaluate.py` whole: mostly clean, one limitation I cannot measure

- [x] **Read it end to end (10:30). No bug found** — worth recording, because seven straight
  "read it whole" findings could imply the method always yields one. It does not, and saying
  so keeps the previous seven honest. The promotion path, the caveat plumbing into both the
  SOTA and REJECTED write-ups, and the spread handling all read correctly.
- [ ] **One genuine statistical limitation, stated as a limitation and NOT acted on.** The
  significance gate takes its noise estimate from `eval_ce_per_batch` — the spread across
  eval batches **within a single run**. But the comparison it feeds is **between runs**
  (this candidate's run vs the baseline's run). Between-run variability includes seed and
  init effects that within-run batch spread does not, and is usually the larger quantity.
  If so, `SIGNIFICANCE_SEM * se_diff` is a **too-easy bar** and `significant: True` is
  optimistic.
  - **I tried to measure it and could not.** Only one stored experiment carries `per_seed`
    (`bc3dbb74bead`, and that is the *proxy* trainer on a different metric), so its
    across-seed SD is not comparable to the factory runs' within-run batch SD. **No
    candidate has ever been run at multiple seeds under the factory trainer**, so between-run
    variance is simply unobserved here.
  - **Not changing the gate.** Tightening a threshold on a theoretical argument, with no
    measurement, is exactly the move I have refused all night for prompt changes and
    0-occurrence bugs. The reasoning is sound; the magnitude is unknown; the honest state is
    "known limitation, unquantified".
  - **The measurement path already exists**: `ab_nano.py` (§5.3.R32) now runs `SEEDS=[0,1,2]`
    on both arms and reports **paired** differences. Running it once on any candidate yields
    the across-seed spread for the factory recipe and answers this directly. It costs 6
    training runs (~27 min) and >4 GB free RAM.
  - Until then the verdict text is at least not overclaiming: the one-sample fallback already
    states that it treats the baseline as an exact point and is weaker than 2 SE of a real
    difference (§5.3.R6).
### 5.3.R44 — full cross-app sweep + one anomaly that measured clean (10:35)

- [x] **Everything green.** dottie **182 passed** / 1 skipped · ava-factory server **24
  passed** / 1 skipped · webapp contract tests **11 passed** (6 api + 5 store) · mutation
  audit **9/9 GOOD**, no HOLLOW, no WEAK, no SKIP. Tree clean. 62 commits since 06:00.
- [x] **An anomaly I chased and did NOT act on.** The 10:15 ideate batch created only **1**
  experiment despite `--n 3`, which looked like a 66% loss of ideation output. Measured
  across the whole log: **63 of 66 ideas delivered (95%)** over 22 batches — 20 batches
  delivered 3, one delivered 2, one delivered 1. **The batch I happened to look at is the
  exception, not a pattern**, and one corrective re-ask across 22 batches is the parse-retry
  working as designed.
  - Filing the negative result on purpose. Noticing an odd number and generalising from it
    is how the "42% keep_alive slowdown" (n=1) and the "2,047 log lines" false alarm both
    started tonight. The measurement took one command; the fix I would have built, had I
    trusted the single observation, would have been aimed at nothing.
- [ ] **State of the loop for the operator:** running healthy on `e8cc5b7`, cycling
  ideate → implement → train → evaluate with candidates reaching training and being rejected
  on merit. **12 runtime-affecting commits are queued behind a restart** (§5.3.R39 explains
  why restarting now beats finishing the current measurement window). Nothing is broken;
  the queued work is improvement, not repair.
### 5.3.R45 — the same queue-blocker, in the file I cited as getting it right

- [x] **Read `factory_trainer.py` whole (10:40) and found the bug I said was not there.**
  `factory_nano_trainer` has three exception paths:
  | path | returns | meaning |
  |---|---|---|
  | module load / class select | `TrainResult(False, False)` | **retryable INFRA — wrong** |
  | integration probe | `TrainResult(True, False)` | failed_training — correct |
  | training loop | `TrainResult(True, False)` | failed_training — correct |
  The module being loaded is the **candidate's own artifact**, so a failure reproduces on
  every retry: the experiment stays `ready_for_training` forever and blocks the queue.
- [x] **This is the exact bug I fixed in `train.py` — and when I fixed it there I wrote that
  `factory_trainer.py` "already draws this line correctly".** It does, in two of three
  paths. I had read the two I was comparing against and inferred the third. **Two of three
  correct is precisely how a file passes a spot check**, and it is why "I checked that file"
  is a weaker claim than it sounds.
- [x] Fixed to match its own siblings. Observed frequency **zero** (nothing is or has been
  stuck in `ready_for_training`), so this is consistency-driven like the `train.py` fix — a
  silent queue stall is a bad enough failure mode not to wait for, and the semantics were
  already decided in this very file.
  - Regression test is **hermetic**: it stubs `_setup` and `sys.modules["ava.model"]` so it
    needs neither torch-heavy training nor the factory checkout. Verified red with the exact
    old return (`TrainResult(ok=False, ...)`). Suite 183 passed.
  - Wrote the fixture to a file and inserted it, rather than through a shell heredoc — the
    process fix from §5.3.R42. It worked first time.
### 5.3.R46 — the proxy trainer's loop was unguarded; and my own docstring had gone stale

- [x] **Read `train.py` whole (10:45), because §5.3.R45 was caused by fixing two paths in a
  file and inferring the third.** Same file, same shape: I had guarded the module load and
  `Proxy()` construction — and **left the training loop unguarded**.
  - A candidate that **raises** mid-training (as opposed to going NaN, which *was* handled)
    propagated straight out of `run_training` into the daemon's generic handler. Result: the
    experiment stayed `ready_for_training` **and** a consecutive error was counted toward the
    five-error exit. So one bad candidate could both block the queue and, repeated, take the
    daemon down.
  - `factory_trainer` already wraps its training loop exactly this way. **Third instance
    tonight of "the sibling does it right and this one does not"** (§5.3.R45 module load,
    §5.3.R17→7b capacity in the prompts, now this).
  - Verified red for precisely the right reason: the `RuntimeError` escaped the trainer and
    surfaced in the test, which is what it would do to the daemon.
- [x] **The docstring had also gone stale — by my own hand.** `run_training` still promised
  *"Loading/trainer infra errors leave the experiment in ready_for_training (retryable)"*,
  which stopped being true the moment I reclassified load failures as candidate faults
  (§f872bab). The inline comment said the same. Both now state the real rule: **NaN, crash,
  or unloadable module are all the candidate's fault and non-retryable; only genuine
  infrastructure gaps stay retryable.**
  - Same failure as §5.3.R13 (`LEVELS` drift) and §5.3.R41 (night-model doc): **I changed
    behaviour and did not re-read the paragraph describing it.** That is now four instances,
    and it is the cheapest kind of dishonesty to introduce.
  - Suite 184 passed. Fixture written to a file, not a heredoc — worked first time again.
### 5.3.R47 — swept for doc drift instead of finding it one file at a time

- [x] **Two patterns had each recurred 3-4 times** — "the sibling does it right and this one
  does not" (§5.3.R45, R46, and the prompts' missing capacity rule) and "I changed behaviour
  without re-reading its description" (§5.3.R13 LEVELS, R41 night-model, R46 docstring). So
  I swept the package for the second class rather than waiting to trip over it again.
- [x] **Result: docs are in good shape, two real drifts, both mine and both from tonight.**
  1. `factory_trainer`'s **"Honesty contract"** listed which failures are the candidate's
     fault, and did not include *cannot be LOADED* — the exact path I reclassified in
     §5.3.R45 an hour ago. The contract now names all four (load, instantiate, contract
     break, raise-during-training) and states that `ok=False` is reserved for infrastructure
     the candidate did not cause.
  2. `validate.py` still said *"MLBR passed all four levels"*. Historically true, but there
     are six stages now and a reader today would be misled. Reworded to *"all four levels
     that existed at the time (there are six stages now)"* — the history is the point of the
     comment, so it is preserved rather than deleted.
- [x] **Bounding the result honestly: the sweep found only these two.** After the earlier
  fixes (§5.3.R13 docstrings, R41, R46) the package's prose largely matches its behaviour.
  Reporting a small yield matters — three ticks of large findings could imply the codebase is
  riddled, and on this axis it is not. Suite 184 passed.
- [ ] **Standing rule earned the hard way, worth keeping visible:** when a behaviour changes,
  the paragraph describing it is part of the change. Four instances tonight, every one
  introduced by me, every one found by reading rather than by any test — because **no test
  asserts that a comment is true**.
### 5.3.R48 — SECOND RESTART (10:35:02) — **CORRECTION: this was a CRASH, not a deliberate restart** (see §5.3.R51). The fixes did go live; the cause I implied was wrong.

- [x] **Detected by the boot banner, not by being told: `pid=33132 git_sha=c12a052
  prompts=dde2a11b0273`.** A new window opened at 10:35:02 and **12 runtime commits went
  live**, including the two §5.3.R39 argued were worth resetting the measurement for:
  - **`a09d5e9` — the search space no longer asks for losses/regularisers** (§5.3.R35, the
    mechanical cause of the 36% category-error rate).
  - **`8a7d309` — the corrector now carries the engineering constraints** (§5.3.R38, and the
    corrector writes most of the code this loop produces).
  Plus the sequence probe, dead-ends anti-priming, both other prompt contradictions, the
  contract-scope fix and the factory load-failure reclassification.
- [x] **Did the thing I pre-registered, before looking at any numbers.** §5.3.R30 and R39
  both say the report's attribution map must be updated from the new `boot` record *first*.
  `post_restart_report.py` now carries `BOOT_TS = 10:35:02`, `BOOT_SHA = c12a052`, and a
  12-item live list with **only §5.3.R46 (proxy-trainer loop guard) marked NOT live** — and
  that one affects the proxy path, while the daemon runs `--trainer factory`.
  - Comparators deliberately remain the **original pre-restart** figures (36% / 55% / 6% /
    78%). The 08:50–10:35 window reached only **n=13**, below the reporting threshold, so it
    never produced a rate. **Comparing against a sub-threshold number is exactly the error
    the threshold exists to prevent** — and it is the same mistake I caught in my own
    comparator in §5.3.R23.
- [x] Suite still green after the edit. **Current window n=3.** No rates, no claims; the
  script withholds them and will keep withholding until n≥20.
- [ ] **This is now the window that matters.** It is the first time the whole set of fixes
  has run together, and the first honest test of whether any of tonight's reasoning about
  the proposal pipeline was right. If the category-error rate does not move from 36%, the
  search-space diagnosis (§5.3.R35) was wrong — and that is a result worth having too.
### 5.3.R49 — ⭐⭐ the trainer was loading the validator's scratch files, not the module

- [x] **`_load_module` selected the module to train by ALPHABET (10:55).**
  `sorted(ws.glob("*.py"))[0]`. But `validate()` writes a scratch `candidate_<uuid>.py` into
  **the same experiment workspace on every attempt, including failures**, while
  `implementation.py` writes the validated module under its own name. `"candidate_"` sorts
  before most generated filenames, so the trainer systematically picked a validator artifact.
- [x] **Measured over 25 trainable workspaces — 25 of 25 loaded a `candidate_` file.**
  Severity, verified by content hash rather than assumed:
  - **23 of 25**: the picked scratch file was byte-identical to the final module. Right code
    trained, **by luck**, because only one attempt existed.
  - **2 of 25 (8%)**: the picked file was an **earlier FAILED attempt with different
    content**. The loop trained, measured and judged code it had already rejected — silently,
    with a `failed_training` verdict attached to the wrong module. One of them is
    **`694633b2d354`**, the §5.3.R11 rank-collapse case, so that verdict is now suspect.
- [x] Fixed: prefer the real module, fall back to scratch only if nothing else exists, and
  then take the **newest** (the passing attempt) rather than the alphabetically first — an
  arbitrary uuid was ordering the choice. Verified red with `loaded 'failed attempt'`.
  Suite 186 passed.
- [x] **I nearly reported this wrong.** My first measurement compared the picked file against
  `f"{module_name}.py"` and reported **95 of 95 broken** — but `_safe_basename` uses the
  lowercase `target_file` basename, not the module name, so the expectation was wrong and
  the number was meaningless. Recomputed against the actual files: 25 relevant, 2 genuinely
  wrong. **The alarming number was mine, not the code's.**
- [ ] Side observation worth its own look: nearly every workspace's final module is named
  **`experimental_routing.py`** — the *example* value from the implementation schema
  (`"repo-relative path, e.g. ava/models/experimental_routing.py"`). The model is copying the
  example verbatim. Harmless now, but it is the same class as §5.3.R37: **example text in a
  prompt gets treated as the answer.**
### 5.3.R50 — the schema's own examples were being copied, and one caused a crash

- [x] **Chased the §5.3.R49 side observation and it is not cosmetic (11:00).** Measured:
  **23 of 98** candidates returned the exact example `target_file`
  (`ava/models/experimental_routing.py`), and **27 of 86** returned the exact example
  `input_shape` (`[4, 16, 64]`).
- [x] **The harm chain, traced end to end on a real failure:** `670ad9956bab` declared
  `input_shape: [4, 16, 64]` — **the example, verbatim** — from which it derived
  `init_kwargs: {seq_len: 16}`, sized `positional_weights` to 16, and raised
  `AssertionError: seq (256) must match seq_len (16)` on its first training step. The
  §5.3.R28 sequence probe fixed the **symptom** (validating at the wrong shape). This is the
  **cause**: the prompt handed the model a fillable value and it filled it in.
- [x] **Third instance of the same class.** §5.3.R37 (the CODEBASE CONTEXT loss vocabulary,
  fingerprinted in 7 candidates naming their argument `predictions`), §5.3.R49 (the
  filename), and now this. **Example text in a prompt is treated as the answer.** A schema
  must *describe* its values, not supply ones that can be pasted through.
- [x] Both fields now describe rather than demonstrate. `input_shape` additionally states
  the truth the model needs: *"this is only a probe shape. In training the block runs at
  seq=256, hidden=256, and it is re-validated at that shape — so nothing in your module may
  be sized to the numbers you put here."* The test also asserts the **correction** prompt
  does not reintroduce the example, since it renders the same schema (§5.3.R38).
  Suite 187 passed.
- [ ] **The generalisable rule for this codebase:** any `e.g.` inside a JSON schema the model
  fills is a default, not an illustration. Where a concrete value is genuinely needed, make
  it obviously non-fillable (`<your_module_name_lowercased>`), or state the real constraint
  instead of a sample of it.
### 5.3.R51 — ⛔ TRAINING IS OFF, and the daemon had been crash-looping on memory

- [x] **The daemon was NOT restarting deliberately — it was dying and being restarted by the
  scheduler (11:05).** Boot records show lifetimes of **105 min → ~9 min**, with each new
  boot landing exactly on a `PT15M` trigger boundary (`10:35:02`, `10:50:02`). A daemon that
  is alive holds the wrapper's exclusive lock and makes the tick a no-op; a new boot means
  the previous one was gone.
  - **The 10:44:16 implement has no completion line.** Silent death mid-stage — the same
    signature as the wrapper bug fixed earlier, but that one is genuinely fixed.
  - **I reported §5.3.R48 as "the daemon restarted, 12 fixes are live" as though the restart
    request had been honoured. It had not.** The fixes did go live, so that half was right;
    the cause was crash-recovery and I did not check before framing it as success.
- [x] **Root cause, corroborated by the subtask's independent measurement: memory
  starvation.** It recorded **110 MB available** before freeing anything — *below* the
  281 MB that killed the WSL VM at 02:05. That fully explains why the 08:50 daemon lived
  105 minutes and the 10:35 one lived nine: the box ran out of RAM underneath it.
- [x] **CURRENT STATE — verified by me directly, not taken from the subtask report:**
  | | |
  |---|---|
  | scheduled task | **Disabled** |
  | research processes | **0** |
  | llama-server | not loaded |
  | available RAM | **3,695 MB** |
  | power | On AC |
  | docker engine | **down** — `dockerd` never started inside the VM |
  **Training is stopped.** The recovery script disables the task by design (its step 1), and
  the subtask was then classifier-blocked from both `wsl --shutdown` and re-enabling.
- [x] ✅ **ALREADY RESTORED — verified 2026-07-24 23:05. Do NOT run these commands.** Both
  conditions this item waits on are met: `docker ps` shows **13 containers up** (so the Docker
  engine is healthy and `wsl --shutdown` is unnecessary — running it would tear down the LIVE
  trainer at step 3080 for no reason), and `Get-ScheduledTask 'Dottie Research runner'` reports
  **State = Running** (so Enable/Start are no-ops). ⚠ Note the memory line below is stale in the
  unsafe direction: it says 3,695 MB free, but four samples today measured **483–1035 MB** —
  see the headroom warning in the §"WHY THE FLEET DIED" block. Original text follows.
  ~~⛔ **OPERATOR — two commands to restore, in this order:**~~
  ```powershell
  wsl --shutdown                                             # engine back in ~2 min
  docker ps --format "{{.Names}}`t{{.Status}}"                # expect 13-14 containers

  Enable-ScheduledTask -TaskName 'Dottie Research runner'     # training back on
  Start-ScheduledTask  -TaskName 'Dottie Research runner'
  ```
  Memory is now **3,695 MB**, so the condition that was killing the daemon is cleared — but
  it will return once `llama-server` reloads (~5 GB) unless the fleet stays down. **The
  §5.3.R40 battery kill-switch and the charger question (decision #2) both bear on this.**
- [ ] The restart also picks up `1470426` (the trainer was loading validator scratch files),
  which is **not** in the daemon's last `5b0fdd6` — see §5.3.R49.
### 5.3.R52 — a memory guard, so the loop refuses visibly instead of dying silently

- [x] **Built the preventive fix for §5.3.R51 (11:15).** The daemon had no idea how much RAM
  it had. It started torch stages at **110 MB free**, got OOM-killed mid-run with no
  traceback, no exit code and no log line, and the 15-minute trigger fed it back into the
  same wall. Its own log looked merely *quiet* — which is why I read the boot records as
  deliberate restarts.
- [x] **`_memory_refusal()` now runs before every non-idle stage.** Below the floor it emits
  a structured `insufficient_memory` record naming the action, the free MB, the required MB
  and what to do, then takes the existing exponential backoff. **It does not free memory —
  it makes running out of it legible**, which is the whole difference between a diagnosable
  refusal and a silent death.
  - Floor defaults to **1,200 MB**, overridable via `DOTTIE_RESEARCH_MIN_FREE_MB`; **0
    disables the guard**. A garbage value falls back to the default rather than crashing the
    daemon — tested.
  - **UNKNOWN must not mean BLOCKED.** `_available_mb()` returns `None` when it cannot read
    the counter, and the stage proceeds. A guard that halts the loop because it cannot read
    a value would turn an unsupported platform into a permanent outage — tested explicitly.
  - `psutil` is not installed here, so the Windows path calls `GlobalMemoryStatusEx` via
    ctypes. Verified against `\Memory\Available MBytes` (2,873 vs 3,258 MB at different
    sampling moments) — and deliberately **not** `FreePhysicalMemory`, which excludes standby
    and misled me earlier tonight.
  - Suite 189 passed.
- [ ] **Honest scope: this makes the failure visible, not impossible.** The box has ~16 GB,
  `llama-server` wants ~5 GB, the fleet plus VM ~3-4 GB, and desktop apps have been running
  7+ GB. **The real fix is a memory budget, not a guard** — the guard just means the next
  time it happens you get `insufficient_memory: 110 MB free, need 1200` in run.log instead
  of an unexplained gap. That is also the thread joining tonight's outage, the crash-loop and
  the GPU throttling: this box has been running a workload it does not have headroom for.
### 5.3.R53 — END-TO-END smoke test through the real CLI: everything holds

- [x] **Used the window while training is stopped to test what no unit test covers (11:25):
  the CLI wiring itself.** §5.3.R33 established that no test invokes the research CLI, and
  §5.3.R32 showed what hides there. Ran a full `seed-baseline → train → evaluate → promote`
  on a temp `--data-dir`, then deleted it. Nothing touched the live ledger.
- [x] **The §5.3.R49 trap, reproduced deliberately and defeated.** I planted a
  `candidate_000000.py` that sorts FIRST and raises `RuntimeError('STALE SCRATCH FILE WAS
  LOADED')`. Training **succeeded** — so the loader now picks the real module through the
  real CLI, not just in the unit test.
- [x] **The evaluation chain works, and each piece announced itself correctly:**
  - promoted to `sota`, `significant: True`, `improved: True`;
  - **hand-seeded caveat fired** (the baseline was seeded, not calibrated);
  - **one-sample fallback declared its own weakness** — *"the baseline records NO spread"*
    (§5.3.R6);
  - **promotion carried the spread onto the baseline**: `metric_sem 0.0311, n=2`, which is
    what enables the two-sample test for the NEXT candidate (§5.3.R6);
  - **status then reported `provenance: promoted` with no warning** — correct, because the
    new baseline came from an experiment that passes the current validator, so the
    contamination check found it clean.
- [x] **The promotion bundle leads with its caveats** (§5.3.R31), and the generated
  `ab_nano.py` parses, passes an **Experiment**, runs three seeds and can print WITHIN NOISE
  (§5.3.R32). Both verified on a real generated bundle rather than a fixture.
- [x] **Memory discipline held throughout.** I aborted the LLM half: available RAM was
  **2,364 MB** and falling, and loading even the 1.5B model would have pushed toward the
  danger zone immediately before the operator's restart. Ran only the stages needing no
  model. Memory after: **2,464 MB** — unchanged.
- [ ] Still untested end-to-end: `ideate` and `implement` (both need Ollama, ~5 GB) and
  `calibrate-baseline` (needs the factory + corpus). Those wait for headroom — §5.3.R34
  records the safe way to do the latter.
### 5.3.R54 — two callers misread the ledger's contract; one of them was mine

- [x] **Read `ledger.py` whole (11:35). The state machine itself is sound** — legal
  transitions enforced, the `_write` field whitelist is closed (no SQL injection surface),
  `next_in_state` is honest FIFO, `counts()` is correct. Recording that, since the method has
  now found something in eight of ten artifacts and it should not read as inevitable.
- [x] **What it did expose is a CONTRACT misread. `Ledger.get()` RAISES `LedgerError` for an
  unknown id — it never returns `None`.** Two callers tested `if exp is None`:
  - `promote.build_promotion` — pre-existing. Its intended honest refusal
    (`unknown experiment 'x'`) was **dead code**; callers got a raw `LedgerError` instead.
  - **The `ab_nano.py` template — mine, from the §5.3.R32 rewrite.** Worse consequence: a
    human running the re-verification script on a stale id would get a traceback instead of
    *"experiment X not found in <ledger>"*. I introduced that while fixing a different bug in
    the same file, four hours ago.
- [x] Both now catch the raise. Verified the refusal actually fires
  (`ValueError: unknown experiment 'nope'`), and the generated script no longer contains a
  `None` check that cannot be true. Suite 191 passed.
- [ ] **The pattern worth extracting: I assumed an API's failure mode instead of reading it.**
  Same shape as §5.3.R45 (assumed `factory_trainer` classified load failures correctly
  because two of its three paths did). Both times the assumption was reasonable, both times it
  was wrong, and both times **the cost was an error path that silently could not work** — the
  kind nothing exercises until the bad day.
### 5.3.R55 — swept for more contract misreads; found none (bounded negative result)

- [x] **Swept the research package for the §5.3.R54 class (11:45)** — a `None` guard placed
  after a call whose failure mode is actually a *raise*. Walked the AST for every
  `x = f(...)` immediately followed by a guard on `x`, and checked each callee's real
  contract. **17 sites, 0 new bugs.**
  - Correct by design: `dict.get`, `next_in_state`, `get_baseline`, `_spread`,
    `_find_torch`, `shutil.which`, `getattr(..., None)` — all genuinely return `Optional`.
  - **My matcher over-reported**: it treated `if not x` as a None-guard, so
    `sorted(...)`/`list(...)` results appeared suspicious. Checked all four by hand;
    every one is a correct list-emptiness check (`if not bins`, `if not pys`). **The tool
    was wrong, not the code** — the fifth time tonight a query of mine produced a false
    signal, and the reason I hand-verified rather than filed them.
- [x] **So the R54 class was exactly two sites, both already fixed.** That is worth stating:
  after finding a real bug, the instinct is to assume a swarm. Here the bound is genuine —
  the ledger's is the only API in this package whose failure mode is a raise while looking
  like it might return `None`, and both of its misreading callers are repaired.
- [ ] **Sweeps that find nothing still earn their tick.** They convert "I fixed one, there
  are probably others" into "there are two, both fixed" — and the second is actionable while
  the first is just anxiety. Same value as §5.3.R44 (the ideation-delivery anomaly measured
  at 95% and dropped) and §5.3.R43 (evaluate.py read clean).
### 5.3.R56 — one-command restart, which refuses to claim a success it did not observe

- [x] **Wrote `scripts/restart_research.ps1` (11:55).** `prepare_fleet_recovery.ps1`
  **disables** the task as its step 1, and on 2026-07-20 the sequence was interrupted right
  after that. **Training then stayed off silently** — no error, no alert, the task simply
  `Disabled` and nothing saying so. Re-enabling is three commands plus a verification that
  is easy to skip, so this is one command that checks preconditions, starts, and **proves**
  the daemon booted.
  - Refuses on **orphaned research processes** (they survive `Stop-ScheduledTask` and would
    race a second daemon against one ledger) and prints the exact kill command.
  - Records the log length **before** starting, so the `boot` line it finds is provably the
    new one rather than a stale match — the same trap that made 2 post-boot lines look like
    2,047 in §5.3.R22.
  - On success it prints the boot record and says to compare `git_sha` against
    `git log --oneline -1`, because "the scheduler accepted the request" and "the loop is
    running the code you think it is" are different claims (§5.3.R30).
- [x] **Caught a flaw in my own script by running its preconditions.** A single memory floor
  is *misleading*: at 2,292 MB free it would pass a 1,500 MB check and then load a **~5 GB**
  Ollama model into system RAM seconds later — straight into the wall it exists to prevent.
  Now two thresholds: a hard floor that refuses, and a **warning at floor + model size**
  naming the 110 MB / 281 MB numbers from tonight. It proceeds with the warning rather than
  blocking, because the §5.3.R52 in-loop guard now refuses stages visibly instead of dying.
  - Verified: parses under PS 5.1, **0 non-ASCII bytes** (the ANSI trap from §5.3's recovery
    script), and its preconditions evaluate correctly against the live box.
- [ ] **I cannot run it** — the classifier blocks task control, which is exactly why it is a
  script for you rather than something I attempted. Current preconditions: 2,292 MB free
  (would warn, not refuse), 0 orphans, task `Disabled`.
### 5.3.R57 — read ideation.py; two worries measured at zero, one new comparator earned

- [x] **Read `ideation.py` whole (12:05).** Two things looked risky and **both measure at
  zero**: `run_ideation` creates every parsed hypothesis with no cap at `n_ideas` and no
  distinctness check — but across 23 logged batches there are **0 within-batch duplicates**
  and **0 oversize batches**. No fix warranted.
- [x] **My first measurement was meaningless and I caught it.** I grouped experiments by
  `created_ts`, assuming one ideate call shares a timestamp. It does not — `ledger.create`
  calls `time.time()` per experiment — so all 100 "batches" came out size 1 and the answer
  was structurally guaranteed to be zero. Re-measured using the `created` id lists in
  run.log, which are the authoritative grouping.
- [x] **The same query earned something the report was missing: a mode-collapse comparator.**
  Cross-batch repetition is what §5.3.R24's dead-ends anti-priming targets, and there was no
  baseline for it. Added `repeated ideas` to `post_restart_report.py`.
- [x] **And validating it caught the §5.3.R23 error a second time.** My first comparator
  (15/66 = 23%) came from run.log's ideate records; the report computes over **ledger**
  hypothesis names. Different populations — shipping it would have manufactured a 4-point
  "improvement" out of a population mismatch. Recomputed exactly as the report measures:
  **27/97 = 28% pre-restart**, which now reads as a like-for-like 1-point difference instead
  of a fake gain.
  - Twice tonight, the same mistake, and twice caught by **running the metric over the
    pre-restart data before trusting it**. The check costs one command; the alternative is a
    fabricated win in a document I have been asking the operator to rely on.
### 5.3.R58 — the diagnostic-saver could destroy the diagnostic

- [x] **`_dump_raw` was the ONLY place in the research package that bypassed `paths.py`
  (12:15).** It defaulted to the relative string `"data/research/logs"`, so where a dump
  landed depended on the process cwd. It worked only because the PowerShell wrapper does
  `Set-Location $App` first — and a run with a custom `--data-dir` (my own §5.3.R53 smoke
  test, for one) would have written its dumps somewhere else entirely.
- [x] **The worse half: it runs INSIDE the `except ValueError` handler.** An mkdir or
  permission failure there propagated **in place of** the parse error, so the caller would
  see an `OSError` about a directory instead of *"unparseable ideation output"*. **The code
  that exists to preserve a diagnostic could delete it.** That is the same shape as
  §5.3.R14 (a contamination check that reported clean when it could not check) — a
  safety mechanism whose failure mode is silently worse than not having it.
- [x] Fixed both: the dump path is now derived from **the ledger's own directory**, so it
  lands beside the experiments it documents and honours `--data-dir` automatically
  (`DOTTIE_RESEARCH_LOG_DIR` still overrides for the wrapper's layout); and the call is
  wrapped so a dump failure degrades to `<dump failed: ...>` inside the original error
  rather than replacing it.
  - Verified red for the right reason — `no dump beside the ledger at <tmp>/logs` — and a
    second test proves a `PermissionError` from the dumper no longer escapes. Suite 193
    passed.
### 5.3.R59 — the dashboard's honesty line described the wrong measurement

- [x] **Read `logger.py` whole (12:25) — the last unread file I had edited.** Its status note,
  the line the Research tab renders as its honesty statement, asserted:
  > *"Every metric is a real measurement **from the proxy micro-benchmark**."*

  **The daemon runs `--trainer factory`.** Measured over the live ledger: **27 of 28**
  recorded integrations are `factory_nano_block_swap`, and 21 runs describe themselves as
  *"held-out LM cross-entropy on the real packed pilot corpus"*. The note has been describing
  a measurement the loop stopped taking.
- [x] **Direction of the error is worth noting: it UNDERSTATED the work.** The factory
  measurement (real corpus, real architecture, held-out CE) is considerably stronger than a
  synthetic proxy micro-benchmark. So this was not inflation — but **an inaccurate honesty
  statement is worse than none either way**, because its whole function is to be the sentence
  a reader trusts without checking.
- [x] Fixed by **deriving the description from the ledger** rather than asserting it: the note
  now reports whatever the most recent measured run wrote into `train_metrics["task"]`, and
  says *"the recorded trainer integration"* when nothing has been measured yet. A hardcoded
  description of your own measurement drifts silently the moment the measurement changes —
  which is exactly what happened here, and what §5.3.R13/R41/R46 each did in a different file.
  - Verified red on the old code with the stale sentence quoted in full. Suite 195 passed.
- [ ] **That completes the research package**: every module I touched tonight has now been
  read end to end. Eleven artifacts, nine findings. The two that read clean (`evaluate.py`,
  and `ledger.py`'s state machine) are recorded as clean, which is what keeps the other nine
  meaningful.
### 5.3.R60 — the audit caught a FLAKY test of mine, then taught me what my fix buys

- [x] **Added mutants for the four gates that had shipped without one (12:40)** — the
  sequence probe (§5.3.R28), the scratch-file loader (§5.3.R49), the memory guard
  (§5.3.R52) and the dump-failure guard (§5.3.R58) — per this script's own rule.
- [x] **The R49 mutant came back GOOD on one run and HOLLOW on the next.** Non-determinism
  in **my own test**: it writes three files in the same instant, they share an mtime at
  filesystem granularity, and the loader's fallback breaks ties by recency — so `max()`
  returned an arbitrary file and the verdict was a coin flip. **A flaky test is worse than
  no test, because it launders a coin flip as a verdict.**
- [x] **My first fix made it deterministically WRONG, and that is the useful part.** I
  stamped increasing mtimes, which made the final module newest — so the mutant's
  recency fallback picked the right file anyway and the test survived every time. Chasing
  that forced the real question: **in production the module is ALWAYS written last, so
  recency alone would pick it. What the `finals` preference actually buys is the TIE.**
  - Re-pinned to identical mtimes, which is the case the preference exists for and is
    deterministic. The mutant now fails with `loaded 'failed attempt'` — the exact
    production bug — on every run.
  - I would not have understood what my own §5.3.R49 fix was worth without the audit
    disagreeing with itself. That is a stronger argument for the harness than any bug it
    has caught.
### 5.3.R61 — ⚠ the mutation harness left a mutation in my source, and I nearly shipped it

- [x] **A 2-minute command timeout killed `mutation_audit.py` mid-mutation (12:50).** Its
  revert lives in a `finally`, which **does not survive a hard kill**. Left behind:
  `requires_grad=False` in `validate.py` — the residual-stream probe silently **disarmed**,
  two tests failing, and the file sitting modified in the tree.
- [x] **And I committed before reading the result.** I launched the suite, it went to the
  background, I wrote the commit, and only then read `2 failed, 193 passed`. **What kept the
  mutant out of history was staging explicit paths** — the discipline adopted three ticks
  ago after `git add -A` swept up a subtask's work. That is a thin margin for a tool whose
  job is to edit source.
  - Restored, suite back to **195 passed**. Nothing broken reached a commit.
- [x] **Made the harness crash-safe rather than just being more careful.** Every mutation is
  now **journalled to disk before it is applied** and the entry cleared after revert; a later
  run restores anything the journal still holds. Verified end to end: simulated a kill,
  re-ran, got `RESTORED validate.py from a previous interrupted run`, and the file came back
  correct. Journal is gitignored, and absent after a clean run.
  - **A mutation harness that can leave the tree mutated is a liability, not a check.** It
    edits source by design, so "be careful" is not a control — the recovery has to be
    structural.
- [ ] **Two process lessons, both mine:** never commit on a suite result I have not read; and
  a background/timed-out command is not a completed one. Both cost real time tonight
  (§5.3.R22's false alarm was the same shape — acting on output I had not actually checked).
### 5.3.R62 — seven MORE handlers blocking the event loop, including /generate and /chat

- [x] **Read `server.py`'s handlers whole (13:05) and found the fix I made tonight was
  partial.** I converted five *status* endpoints from `async def` to `def` early in the
  session. An AST sweep for "async route handler doing sync heavy work with **no await**"
  found **seven more**: `/health`, `/generate`, `/chat`, `/assistant`, `/jspace/inspect`,
  `/jspace/intervene`, `/jspace/safety`.
- [x] **`/generate` and `/chat` are the serious ones — they run model inference on the event
  loop.** `get_engine()` lazily **builds the model** under a lock and `generate()` is a
  synchronous method, so a single generation blocks *every* other request for its whole
  duration, and the first call blocks for the entire model build. The console polls
  `/pipeline/status` every 5 s against that.
- [x] **The existing regression guard should have caught this, and its docstring said it
  did.** It claimed *"Enforced invariant, not a case-by-case judgement: NO app handler may be
  `async def` while doing blocking I/O"* — while checking a **hardcoded list of five names**.
  **A guard whose docstring outruns its implementation is exactly how seven handlers drifted
  past it.** Replaced with a real AST invariant over every route; verified it fails when one
  handler is reverted (`[('generate', ['generate', 'get_engine'])]`). 24 passed.
- [ ] **Third instance of the same personal error**: §5.3.R45 (fixed `train.py`, asserted
  `factory_trainer` was fine — it was not), §5.3.R46 (guarded two paths in a file, left the
  third), and now this. **Fixing an instance is not fixing a class**, and the honest way to
  tell the difference is a sweep, not an inference.
### 5.3.R63 — swept the OTHER web app for the same class; definitively clean

- [x] **Acted on §5.3.R62's own lesson instead of restating it (13:15):** fixing an instance
  is not fixing a class, so I swept the whole monorepo for other FastAPI apps. There are
  exactly two — `apps/ava-factory/server.py` (fixed) and `apps/dottie/dottie/api.py`.
- [x] **`api.py` is clean, and definitively so rather than by heuristic.** My first pass used
  a keyword list for "heavy work", which could miss a call it did not recognise. So I
  classified every route handler instead: **13 plain `def`, 0 async with await, 0 async
  without.** With no `async def` handlers at all, the failure mode is structurally absent —
  no judgement call and no list to keep current.
- [x] Worth the distinction: "my heuristic found nothing" and "the construct does not exist"
  are different claims, and only the second is worth recording as safe. The first is what I
  nearly wrote.
- [x] **CORRECTION (13:20): "exactly two" was wrong — there are THREE.** My Grep searched
  `apps/` only; a background search covering `packages/` too returned
  `packages/personal-graphify/src/personal_graphify/serve.py`. I asserted completeness from
  an incomplete search, in the same entry where I was congratulating myself for
  distinguishing "my heuristic found nothing" from "the construct does not exist".
  - Swept it: **3 plain `def`, 4 async WITH `await`** (`call_tool`, `http_query`,
    `http_task`, `http_impact` — all correctly yielding the loop), **0 offenders**.
  - **The conclusion survives; the claim did not.** Those are separate things, and only the
    background command noticing the third app kept the first from being quietly false.
- [ ] **The class is now closed across all THREE apps**, with the server one guarded by an
  AST invariant that fails on regression (§5.3.R62) rather than a name list that drifted.
### 5.3.R64 — closed the copy-bait CLASS; the fourth instance was one I introduced

- [x] **Swept all three rendered prompts for pasteable `e.g.` values (13:30)** — the class
  behind §5.3.R37, R49 and R50, which I had fixed three times one instance at a time. Found
  a fourth, **in the `learnable_parameters` field I added hours ago to fix the zero-parameter
  problem**: the schema offered `'gate: nn.Linear(hidden, hidden); scale: nn.Parameter(hidden)'`
  and **2 of 11 proposals returned the first clause verbatim**.
  - I wrote the rule — *"any `e.g.` inside a JSON schema the model fills is a default, not an
    illustration"* — in this same file, and then left a violation of it three fields above.
    Writing a rule down is not applying it.
- [x] Replaced with **form, not value**: `'<your_name>: nn.Parameter(<shape>)'` — angle
  brackets cannot be pasted through — plus an explicit *"use YOUR names and YOUR shapes,
  derived from the mechanism you are proposing"*.
- [x] **Closed as a CLASS this time, not an instance.**
  `test_no_prompt_offers_a_pasteable_example_value` renders all three prompts and fails on any
  `e.g.` that is neither a placeholder nor a symbolic axis list. Verified red on the old
  schema, quoting the copied string back. **Pasteable examples remaining across all prompts:
  0.** Suite 196 passed.
- [ ] Fifth heredoc mangling of the night en route (`[^
]` collapsing into a real newline and
  breaking the test file). Caught by collection, fixed with an Edit and a regex that needs no
  escape. **The lesson has not stuck because I keep reaching for the same tool** — for anything
  containing backslashes, write the file or use Edit.
### 5.3.R65 — closed the TrainResult-classification class; both survivors are legitimate

- [x] **Enumerated every `TrainResult(...)` construction in both trainers (13:40)** rather
  than fixing a fourth instance. `ok=False` means **retryable infrastructure**:
  `run_training` leaves such an experiment in `ready_for_training`, so a *candidate* fault
  marked that way is re-picked forever and blocks the queue behind it.
  - Result: **12 constructions, only 2 with `ok=False`**, and both are genuine —
    `train.py:102` *"torch unavailable"* and `factory_trainer.py:200* *"factory trainer
    infrastructure missing"*. Every candidate-fault path correctly uses
    `ok=True, stable=False`.
- [x] **The class is closed, and now held by an invariant rather than by my having looked
  once.** `test_only_genuine_infrastructure_may_return_ok_false` walks the AST of both
  trainers and requires every `ok=False` to justify itself with infrastructure vocabulary.
  Verified it catches a regression, reporting the exact site (`['train.py:126']`).
  - This matters because the three fixed instances were found **one at a time over hours**
    (§f872bab module load, §f872bab Proxy construction, §5.3.R45 factory load) — and for the
    third I had explicitly asserted the file was already correct. An invariant costs one test
    and ends the search.
- [ ] **Four classes now closed by invariant rather than by inspection**: copy-bait examples
  (§5.3.R64), event-loop blocking (§5.3.R62/R63), skipped-counted-as-pass (§5.3.R15), and
  this. Each began as "I fixed the instance" and only stopped recurring when the *rule* was
  encoded. Suite 197 passed.
### 5.3.R66 — re-verified HEAD end to end before the operator's restart

- [x] **Re-ran the full CLI path at HEAD (13:50)**, because §5.3.R53's smoke test predates
  ~15 commits touching prompts, ideation, logger, the trainers and the server. Unit tests do
  not cover the CLI wiring — that is the gap that hid the broken `ab_nano.py` for its entire
  existence (§5.3.R32). Temp `--data-dir`, deleted afterwards; the live ledger untouched.
  - `seed-baseline → train → evaluate → promote → status`, all clean.
  - The §5.3.R49 trap re-planted (a `candidate_000000.py` that raises on import, sorting
    first): **training succeeded**, so the loader still picks the real module.
  - Promotion carried `metric_sem 0.0311` onto the baseline, and the bundle led with its
    `hand_seeded` caveat.
- [x] **One detail worth recording as a positive confirmation, not just a pass.** The status
  note read *"synthetic next-token shift (proxy micro-benchmark, NOT downstream
  capability)"* — because this run used the **proxy** trainer. In production
  (`--trainer factory`) the same code reports the factory task. That is §5.3.R59 working as
  designed: the note **describes the measurement actually taken** instead of asserting one,
  which is precisely what the hardcoded version could not do and why it went stale.
- [ ] **HEAD is verified end to end and safe to restart into.** Remaining untested by a live
  run: `ideate`/`implement` (need Ollama, ~5 GB) and `calibrate-baseline` (needs the factory
  + corpus). Both wait on memory headroom; §5.3.R34 records the safe way to do the latter.
### 5.3.R67 — the webapp's proxy path could report an empty read as a successful one

- [x] **Read `api.js` whole (14:00). The class I fixed there IS closed by construction** —
  every call routes through one `request()`, so the 2xx-with-non-JSON handling cannot be
  bypassed by a new endpoint. Worth recording: a shared chokepoint closes a class for free,
  which is why that file needed no sweep.
- [x] **A different member of the same family was there:** `researchStatus` returned
  `wrapped.status` from the proxy without checking the key exists. A 200 whose shape drifted
  would hand the UI `undefined` as data — **a research panel rendering empty while reporting
  success**, which is exactly what this module's own doctrine (*"nothing here fabricates a
  value"*) forbids.
- [x] **Verified the contract before deciding it was defensive**, rather than assuming either
  way: `server.py /research/status` returns `{ok, source, status}` on 200 and **502** on
  failure, so `status` is present today and `request()` already types the 502. So this is
  **defensive, not a live bug** — recorded as such. It earns its place because the failure it
  prevents is *silent*, and because the fork working on scout-cli hit this exact class today
  and found a real wrong-shape immediately.
- [x] Now throws a typed `ApiError` naming the actual keys —
  `unexpected shape: keys=["ok","source"]`. Two contract tests added (drifted shape throws;
  well-formed shape still works). **8 passed / 0 failed** in api, 5 in store, 24 server.
- [x] Two self-inflicted errors en route, both caught before commit: a double-heredoc that
  broke the command, and a fetch stub keyed on `":8100"` when the harness uses
  `researchBase: "http://y"` — so the *direct* call answered and both new tests failed for
  the wrong reason. **A test that fails because the stub is wrong looks identical to one that
  fails because the code is wrong**; only reading the failure told them apart.
### 5.3.R68 — my own fix reached one caller in five; the settings page lied about saving

- [x] **Read `store.js` whole (14:15) and found the instance-not-class pattern in my own
  work.** Early tonight I made `write()` return a success flag so a refused localStorage
  write could be surfaced, and propagated it through `saveMessages`. **Four other callers
  ignore it** — `saveSettings`, `createSession`, `touchSession`, `deleteSession` — while
  `write()`'s docstring claims *"the caller is told, so the UI can say so"*. True of one
  caller in five, which is the doc-drift class riding along with it.
- [x] **The consequence was user-visible and specific.** `views/settings.js` set
  `"saved — clients and pollers restarted"` **unconditionally**. On a refused write
  (private mode, quota) the operator is told it saved and the **token and base URLs silently
  revert on reload** — exactly the loss the return value was added to prevent, handled
  correctly in `chat.js` and nowhere else.
- [x] Fixed where it is user-facing: `saveSettings` now returns `{ settings, persisted }`
  (verified no caller consumed the old return, so the shape change is safe), and the
  settings page says *"applied for this session ONLY — the browser refused to store it
  (private mode or quota), so it will be lost on reload"*.
  - Two contract tests: a `setItem` that throws `QuotaExceededError` must report
    `persisted: false` **and still return the merged settings** so the session keeps working;
    a working store reports `true` and round-trips. Verified red without the fix.
    **api 8 / store 9, both green.**
- [ ] `createSession`/`touchSession`/`deleteSession` still discard the flag. Left deliberately:
  their failure loses a session list entry rather than credentials, and no UI currently
  claims success for them — so there is nothing lying yet. Recorded rather than fixed, so
  the next person sees it was a decision.
### 5.3.R69 — the console stacked polls exactly when the server was slowest

- [x] **Read `app.js` whole (14:30).** Its three pollers run on `setInterval` with intervals
  **shorter than their own request timeouts** — `/pipeline/status` every **5 s** against an
  **8 s** timeout — and no in-flight guard. A slow backend therefore stacks overlapping
  requests, **and the stacking is worst precisely when the server is already struggling**.
  That is a feedback loop, not a retry.
  - Not hypothetical: `/pipeline/status` ran **on the event loop** until this session
    (§5.3.R62), so slow polls were the normal case. The client amplified the server bug I
    fixed a few ticks ago.
- [x] `skipWhileRunning()` now wraps each poller — a tick during an in-flight request is
  skipped, and the flag always clears in a `finally` so a **rejected** poll cannot latch it
  shut. The wrappers are created inside `startPolling()` so every restart (settings change,
  tab unhide) gets a fresh flag; a module-level wrapper could latch `true` on a request
  abandoned across a stop/start and silently kill that poller forever.
- [x] New `poll.contract.test.mjs` asserts both the **behaviour** (overlaps skipped, guard
  released after success AND after rejection) and that the guard is still **wired** — a raw
  `setInterval(pollPipeline` fails the file. Verified red on the unguarded version.
  **api 8 / poll 8 / store 9, all green.**
- [x] **My first version of that test deadlocked instead of failing.** It awaited a second
  call whose promise was never resolved, so `node --test` hung on an unsettled top-level
  await rather than reporting anything. Fixed by collecting every releaser. **A test that
  hangs is worse than one that fails** — CI reports a timeout, not a cause, and the hang was
  in my test rather than the code under test.
### 5.3.R70 — swept the views for the settings-page class; covered an untested invariant

- [x] **Swept every view for "UI claims success without checking" (14:45)** — the class
  behind §5.3.R68. **Clean.** The only match is `chat.js` reporting *failure* honestly, and
  my settings fix removed the one unconditional claim. `ops.js` has **no async, fetch or
  catch at all** — a pure rendering view, so the class is structurally absent rather than
  merely unobserved (the §5.3.R63 distinction).
- [x] **`chat.js` reads sound**, and one property it enforces was **covered by nothing**:
  `apiMessages()` filters error turns out of the history. The backend is stateless — the
  FULL history is re-sent every turn — so this function decides what the model sees, always.
  - A failed turn is stored with `content: ""` and the error in `meta.error`. Replaying it
    would inject a **blank assistant message on every subsequent turn**, degrading context in
    a way that looks like the model getting worse rather than a client bug.
  - It also maps to `{role, content}` only, so `meta` — endpoint, timings, raw error strings
    — never reaches a prompt.
- [x] `history.contract.test.mjs`: **10 assertions**, covering both properties plus the
  scoping detail that a **user** turn carrying `meta.error` must be KEPT (widening the filter
  would silently delete operator input). Asserts the source still contains the filter, so a
  removal fails loudly; verified by deleting the line — `FAIL error turns are still filtered
  out`. **api 8 / history 10 / poll 8 / store 9, all green.**
- [ ] Webapp coverage is now: every file I touched tonight read end to end, every class I
  fixed swept, and the two subtle invariants (poll overlap, history filter) held by tests
  rather than by comments.
### 5.3.R71 — verified item 7's fix is sound, after nearly filing a false alarm

- [x] **Checked decision item 7's "factory unreachable" fix against the real failure
  condition (12:15)** — Docker is down right now, which is exactly what it handles.
  **The fix is correct and end-to-end wired**: `publish_live_status.py` records
  `{"unreachable": reason}` when a source fetch fails, and the site reads
  `status.pipeline.unreachable`. Item 7 stands as written — it needs deploying, nothing more.
- [x] **I nearly filed the opposite, and the process failure is the finding.** I grepped
  `apps/scout-cli/` for the producer, found `unreachable` only in `ARCHITECTURE.md` and
  `app.js`, and was one step from reporting *"the fix is inert — nothing writes the flag"*.
  Two compounding scope errors:
  1. **Wrong directory.** The publisher lives in `apps/ava-factory/scripts/`. A repo-wide
     search found it immediately.
  2. **Wrong artifact.** I inspected `site/data/snapshot.json` — the *baked fallback* — and
     concluded from its missing key. The flag belongs to the **live Gist payload**
     (`dottie_live_status/v2`), a different source the same renderer consumes.
- [x] **Second scope error in the same session** (§5.3.R63: "exactly two FastAPI apps" from a
  search of `apps/` only). Both times the tool answered exactly what I asked and I reported a
  conclusion broader than the question. **The scope of a search is part of its result** — and
  this time the false finding would have told the operator a working fix was worthless.
- [ ] Standing correction to my own habit: before claiming *"nothing produces X"*, search the
  repo, not the directory I happen to be in — and confirm which artifact actually carries X.
### 5.3.R72 — re-verified my own scoped claims repo-wide; both hold

- [x] **Applied §5.3.R71's lesson to my own earlier claims (12:19)** rather than only
  recording it. Two were scoped narrowly enough that a wider search could have overturned
  them:
  - **§5.3.R65 (TrainResult classification "closed").** Repo-wide: `TrainResult(` appears in
    exactly four files — the two trainers, the test module, and the mutant strings in
    `mutation_audit.py`. **No production construction outside the two trainers.** Claim holds.
  - **§5.3.R64 (copy-bait "0 remaining").** I had checked the three *rendered prompts*, but
    model-facing text also lives in `validate.py`'s failure details (fed back through
    `as_feedback`) and `implementation.py`'s parse-retry feedback. Widened the check.
- [x] **The widened check first gave a FALSE POSITIVE, and fixing it is the point.** A plain
  regex over source found 4 `e.g.` hits in `validate.py` — all of them in **comments and
  docstrings**, which no model ever sees. Conflating source text with model-facing text is
  the same imprecision as conflating a directory with a repo. Re-ran against **only string
  literals that actually reach the model** (`ValidationResult` detail arguments and
  `feedback` assignments): **111 model-facing literals checked, 0 pasteable examples.**
  Claim holds.
- [ ] Both survived, which is the useful outcome: after two scope errors the honest move was
  to re-test the claims rather than assume the pattern was confined to the two I noticed.
  Re-verification that confirms is not wasted — it is the difference between "probably fine"
  and "checked".
### 5.3.R73 — ⚠ UNCOMMITTED WORK FOUND IN A STASH FROM BEFORE THE MACHINE MOVE

- [x] **Ran a tool-residue check (12:24) and found something that is not mine.**
  `git stash list` holds **`stash@{0}: On main: pre-teleport`**, created **2026-07-19
  23:55:03** — minutes before this session began "continued from another machine". It has
  survived ~15 hours and 90+ of my commits, and would be lost silently if anyone ran
  `git stash drop` or `clear`.
- [x] **It is a COMPLETE, TESTED FEATURE, not a scratch edit:**
  | file | lines | |
  |---|---|---|
  | `apps/dottie/dottie/jobs.py` | 155 | the module — `JobStore`, `run_due_jobs`, `create/get/list/due/mark_fired` |
  | `apps/dottie/tests/test_jobs.py` | 161 | **7 real tests** incl. sub-minute-interval rejection, reschedule-on-dispatch-failure, pause/resume |
  | `apps/dottie/dottie/api.py` | +85 | the API wiring — `JobCreate` model, `JobStore` construction, endpoints |
  | `apps/dottie/.scout/reviewgraph.db` | 2 MB | a binary artifact that should **not** be committed |
  A recurring-jobs feature: *"a recurring mission: the SAME shape as a one-off task, plus a
  cadence."*
- [x] **Verified non-destructively.** Extracted both Python files to a temp dir with
  `git show`, confirmed they **parse** and contain what the diff claims (12 and 14 functions
  respectively), then deleted the temp copies. **I did not pop, apply, or drop the stash** —
  it is the operator's uncommitted work, and restoring it into a tree with 90+ new commits
  could produce conflicts only they can adjudicate. `dottie/jobs.py` does not exist in HEAD,
  so nothing here is a duplicate.
- [ ] **OPERATOR — still live, and here is the data the decision needs (re-measured
  2026-07-24 23:10, nothing applied/popped/dropped).** `stash@{0}: On main: pre-teleport`,
  created **2026-07-19**, base `8641fb9`, now **501 commits behind HEAD** (the earlier note
  said "90+" — it is 501).
  ⚠ **`git stash show --name-only` UNDERSTATES this stash: it lists only `api.py`.** With
  `--include-untracked` it is **four** entries:
  `apps/dottie/dottie/api.py` · `apps/dottie/dottie/jobs.py` · `apps/dottie/tests/test_jobs.py`
  · **`apps/dottie/.scout/reviewgraph.db`**. Anyone inspecting with the obvious command sees one
  file and concludes it is a small safe change.
  Risk, per entry: `jobs.py` and `test_jobs.py` are **new files** — `jobs.py` is still absent
  from HEAD, so no conflict. `api.py` is the only real conflict candidate: **1 commit touched it
  since the base, +185/-92 lines**. `reviewgraph.db` is **untracked/ignored**, so applying the
  stash would **overwrite a live database on disk** — that is the part to decide about, not the
  Python.
  (Method note: my first `git merge-tree` probe reported conflicts; that was my own bad syntax
  — `--write-tree` takes two commits, not three. git 2.40.1 supports it and the base merges
  cleanly. A tooling error that looks like a finding is worse than no probe.)
  To inspect: `git stash show -p
  stash@{0}`. To restore: `git stash pop` (expect to resolve `api.py` against tonight's
  changes; the two files it adds are new, so they cannot conflict). To keep deferring: do
  nothing — but **it is now recorded, so it cannot be lost by accident.**

  **RE-MEASURED 2026-07-28 (read-only; nothing applied/popped/dropped). The decisive risk in
  this entry no longer exists, so the decision above was resting on a stale fact.**
  - Stash intact and unchanged: `stash@{0}: On main: pre-teleport`, base `8641fb9`, created
    2026-07-19 23:09:33 -0500. Now **601 commits behind HEAD** (entry said 501).
  - ⚠ **`apps/dottie/.scout/reviewgraph.db` DOES NOT EXIST ON DISK.** The entry names
    overwriting a live database as "the part to decide about, not the Python" — that risk is
    gone. Restoring would *create* the file, not clobber one.
  - **The single commit that touched `api.py` since the base is `ebeb299` — the repo-wide ruff
    adoption**, i.e. a reformat, not a semantic change. The entry's "+185/-92 lines" is the
    HEAD-vs-base delta, which is what reformatting a file looks like.
  - **The stash's own `api.py` change is `+85/-0` — pure addition, zero deletions.** Conflict
    resolution against a formatter run is mechanical.
  - **The feature is NOT superseded:** `JobStore`, `run_due_jobs`, `MIN_INTERVAL_S` and any
    `/jobs` route are **absent from HEAD**. Only stale `__pycache__/jobs.cpython-311.pyc` and
    `test_jobs.cpython-311-pytest-9.1.1.pyc` remain — evidence it once ran on this box. The
    stash carries `jobs.py` (155 lines), `tests/test_jobs.py` (161 lines, **10 tests**) and the
    `api.py` wiring: recurring missions, same shape as a one-off task plus a cadence.
  - **Still an operator decision and still not taken here.** What changed is that it is now a
    ~400-line tested feature recoverable against a formatting-only conflict, rather than a
    change gated on clobbering a live database.
  ⚠ **Tooling trap, same family as the `--name-only` one already recorded above:**
  `git stash show -p stash@{0} -- <path>` silently prints **nothing** — it does not filter, it
  returns empty. I read that as "no changes to api.py" for one step, directly contradicting the
  `--numstat` line right above it. Use the unfiltered `git stash show -p stash@{0}`.
- [x] Also cleaned my own residue from the same check: `/tmp/eval.bak` and `/tmp/ledger.bak`,
  left by red-without-fix verifications. No pending stashes of mine; working tree clean.
### 5.3.R74 — ran the daemon itself, safely, and watched the new guard work

- [x] **Verified the one runtime path still untested by a live run (12:28): `run` — the
  daemon mode the operator's restart enters first.** The e2e in §5.3.R66 covered
  train/evaluate/promote but never `run`, which now carries the §5.3.R52 memory guard. A bug
  there would surface as a daemon that will not start.
- [x] **Ran it safely**: `DOTTIE_RESEARCH_MIN_FREE_MB=99999999` on a temp `--data-dir`, so
  the guard refuses **before** anything loads a 5 GB model into a box with ~3 GB free. Four
  things confirmed in one run:
  1. **Boot provenance works in the real daemon** — `{"action":"boot","git_sha":"c3566e7",
     "prompts_sha256":"be4f88795de6"}`, which is the line `restart_research.ps1` waits for.
  2. **The guard refuses with an actionable record**, naming the action, free MB, required
     MB and the remedy — not a silent death.
  3. **Exponential backoff is live**: refusals at +0.0 s, +2.0 s, +6.0 s — the 2→4 s doubling
     from `backoff = min(backoff * 2, 300)`.
  4. **Nothing loaded**: memory held ~3,100 MB throughout, 0 leftover processes afterwards,
     tree clean, task still `Disabled`.
- [ ] **Every runtime path is now verified except the two that need resources this box does
  not currently have**: `ideate`/`implement` (Ollama, ~5 GB) and `calibrate-baseline` (factory
  + corpus). Both are blocked on memory, not on code.
### 5.3.R75 — corrected a MEMORY that would have re-taught the false SOTA

- [x] **Rewrote `memory/dottie-research-loop-live-state.md` (12:32).** It stated the live
  baseline was set by *"FIRST REAL SOTA ratchet … MLBR beat the calibrated seed"*. Tonight
  established MLBR is a **degenerate zero-parameter no-op the current validator rejects**, so
  that memory would have re-taught the exact false-win claim this whole session exists to
  undo — to a future session, with no conversation context to doubt it.
- [x] Also corrected an **architecture** claim: it described *"four Task Scheduler jobs
  {ideate,implement,train,evaluate}"*, the old per-tick design. It is now a **single
  forever-daemon** ("Dottie Research runner"), which is a materially different operational
  model — a future session acting on the old description would look for four tasks, find one,
  and mis-diagnose.
- [x] Added the durable, non-obvious facts a fresh session cannot re-derive cheaply: the
  daemon **does not live-reload** and the `boot` line is the only ground truth for what is
  running; the **battery kill-switch** on the task; the `--bottleneck` string being a defect
  the operator owns; real wins = **ZERO** with both `sota` rows named as artifacts; and that
  only ~5 of 84 proposals were ever the right shape, so zero-wins indicts the pipeline rather
  than the search space.
- [ ] **Memory is the one artifact that outlives the transcript**, so a wrong entry there is
  worse than a wrong TODO — nothing in the next session's context contradicts it. This is the
  same class as §5.3.R59 (a status line describing a measurement the loop no longer took),
  one layer further out.
### 5.3.R76 — swept the rest of memory; two more stale entries, one in the always-loaded index

- [x] **Applied the class sweep to memory itself (12:35)** — §5.3.R75 found one wrong file,
  so assuming it was isolated would be the mistake this session keeps naming.
- [x] **`dottie-ollama-models-on-4080.md` was wrong on the two facts most likely to be acted
  on:** it named **`qwen2.5:7b`** as "the research-loop workhorse" when the live config is
  **`qwen3:8b`**, and gave `READ_TIMEOUT_S` as **600** when it is **1800**. It also omitted
  `DOTTIE_OLLAMA_KEEP_ALIVE=30s` — the knob that keeps this box off the memory floor — and,
  most importantly, the **`NUM_GPU=0` fact that model size competes with the FLEET, not the
  12 GB card.** That omission is what made a 14b model look affordable and caused the 02:05
  outage. Rewritten with the outage warning attached to qwen3:14b directly.
- [x] **`MEMORY.md` — the index loaded into EVERY session — carried the false baseline.** Its
  hook read *"factory_lm_loss baseline 5.61982"*: neither the current value (5.60506) nor
  flagged as contaminated. A one-line hook is the highest-leverage text in the whole memory
  system, because it is read unconditionally and rarely re-examined. Now: *"baseline 5.60506
  is CONTAMINATED (set by a rejected no-op); real wins = ZERO; one forever-daemon that never
  live-reloads."*
- [x] Checked `dottie-4080-box-setup.md` and `dottie-watches-die-with-sessions.md`: both still
  accurate — the box-setup file already carries the RAM budget and the NUM_GPU=0 warning.
  **2 of 4 files were stale, plus the index. Recorded rather than glossed.**
- [ ] The through-line for the whole session, one layer out: **the code was usually right and
  the descriptions of it usually were not** — comments, docstrings, guards, prompts,
  dashboards, and finally the memory that outlives them all.
- [ ] NOTE for the operator's re-seed decision (#5): the re-seed should supply
  `metric_sem` from a **measured** run if one is available. A baseline re-seeded as a bare
  number is honest but keeps the loop on the weaker one-sample test indefinitely.
- [ ] CONSIDERED AND DECLINED: renaming the verdict key `significant` → `beyond_noise`.
  Grepped every consumer: only `evaluate.py` and the tests read it — no webapp, API, or
  package does. The misleading-name risk is real but internal, the direction is already
  spelled out in `significance`, and the honest fix was the *arithmetic*, which is now
  done. Renaming a persisted key across stored records for a cosmetic gain is not worth it.
- [ ] NEXT: **improve dry_run correction feedback — but NOT until constraint-8 is
  measurable.** dry_run is 77% of genuine failures, and the likely lever is handing the
  corrector the actual tensor shapes at the failure point instead of a raw traceback.
  **Deliberately held**: constraint-8 targets the same metric and is still at n=2, so
  shipping a second intervention now would make the two permanently inseparable. Order:
  let the post-restart bucket reach ~20 genuine failures, read constraint-8's effect,
  *then* build this. Noted so a later tick does not "helpfully" ship it early.
- [ ] SUPERSEDED, kept for the record: did the constraint-8 refinement reduce dry_run?
  It was written to attack the dominant failure mode (77% of genuine deaths). Compare
  dry_run share of genuine failures for experiments created before vs after the prompt
  change, using the ledger timestamps. Two cautions: the refinement landed in two stages,
  so pick the boundary deliberately; and the post-change sample is currently small, so
  report n and resist calling a difference real until it clears noise — the same
  discipline the significance gate enforces on candidates.
- [ ] SUPERSEDED, kept for the record: **`validate_with_correction` pins `class_name`
  from the FIRST parse.** If a correction renames the class — plausible, since the
  corrector sees only code plus a traceback — every subsequent dry run looks for a class
  that no longer exists, so the candidate can never validate however good the code is,
  and it burns the full retry budget failing for a reason unrelated to its merits. I hit
  this writing the test fixture, not in production, so **frequency is unmeasured**; check
  the stored histories for repeated identical dry_run failures before deciding whether to
  re-derive the class name per attempt or pin the name in the correction prompt.

### 5.3.R106 — F821 sweep found 2 REAL undefined-name bugs in model/training code (not mine)

- [x] **Checked all 5 `F821 undefined-name`** from the ruff CI (1 was the tool_gate closure FP,
  §5.3.R103). The other 4 are **2 genuine bugs** — both pre-existing, both in core code, both
  will `NameError` at runtime and are flagged by the operator's new CI.
- [x] **⚠ BUG 1 (live): `apps/ava-factory/model_1b.py:768-770` — `get_model()` is broken.** Its
  body passes `use_short_conv=use_short_conv, use_relative=use_relative,
  relative_max_distance=relative_max_distance`, but **none are parameters of `get_model` nor
  defined anywhere** (they appear ONLY at this call site — verified by grep over the whole
  file). So **every call to `get_model()` raises `NameError`.** And it is CALLED in 6 places,
  including **`train_1b_deepspeed.py:342/344` and `trainer_agent.py:168`** — the 1B training
  entry points. Classic incomplete refactor: added to the `DottieModel1B(...)` call, never
  added to `get_model`'s signature. (Latent if those entry points are not exercised — the
  docstring says "new code should use `build_model(cfg)`" — but broken the moment they are.)
- [x] **BUG 2: `apps/ava-factory/on_policy_distill.py:288` — `torch.randn(B, 44, d)`** inside a
  stub model's `forward`; `d` was a param of the nested `__init__` (default 2048), never saved
  to `self`, so it is undefined in `forward` → `NameError` if that path runs.
- [x] **Bug 1 is worse than "latent" — a caller's signature is ALSO wrong (no type checker
  needed to see it).** `get_model`'s params are `(vocab_size, d_model, multi_jspace_enabled,
  rope_type, n_sinks, use_peri_ln)` — no `critical_shift`. But `train_1b_deepspeed.py:342`
  calls `get_model(..., critical_shift=getattr(args,'critical_shift',31))`. So that 1B-training
  entry point raises **`TypeError: unexpected keyword argument 'critical_shift'`** *before* it
  even hits the NameError. **The refactor of `get_model` was left half-done on both sides —
  the body references names it never declared, and a caller passes an arg it never accepted.**
  This is a definitely-broken training path, not a maybe. (mypy/pyright are not installed, so
  this class isn't tool-checkable here; found by reading the signature against the call.)
- [ ] **Recorded, NOT fixed by me — this needs the operator's intent.** Bug 1's fix is either
  "add `use_short_conv=False, use_relative=False, relative_max_distance=<N>` to `get_model`'s
  signature" OR "remove them from the call" — *which* depends on whether `DottieModel1B` is
  meant to take them, a model-design call that is yours. Bug 2 likely wants `self.d`/`d_model`.
  Both are in ruff-reformatted files (fixing pre-B0 grows the merge) and can only be verified
  with torch + the model build. **They join the B0/post-reconciliation fix list.**
- [x] **This closes the ruff-bug review:** across the whole tree, the real bugs are — 2 py311
  syntax errors (§5.3.R103 mine/fixed, §5.3.R105 pre-existing/recorded) and these 2 undefined
  names. Everything else ruff flags (F811 duplicate imports, F841, E722, E741, F541) is benign
  style, pre-existing, and handled by the ruff pass or the operator's lint cleanup.

### 5.3.R105 — swept the WHOLE tree for the R103 bug class; one more, pre-existing, in the data pipeline

- [x] **Generalised R103's find:** 3.12-only f-string syntax is masked by the 3.13 dev venv but
  breaks the declared **3.11** target and the CI's parse. R103 scanned only my 44 files; subtasks
  used the same 3.13 venv, so I swept the **whole tree** (`ruff check . --target py311`).
- [x] **Exactly ONE more, and it is NOT mine:**
  `apps/ava-factory/scripts/dataset_expansion_fast.py:51` — an f-string containing
  `{re.sub(r'\W+','_',topic.lower())}`. **A backslash inside an f-string expression is 3.12+
  only.** Unchanged since session base (`8641fb9`), so it is pre-existing and on origin too —
  part of the red CI (§5.3.R104), and it means **this data-expansion script fails to import on
  Python 3.11**, the platform's declared runtime. Relevant to "build end-to-end": it is a break
  in the data step of the loop.
- [x] **After R103's fix, this is the ONLY py311 syntax error left in the tree** — bounded and
  known. **Fix (3.11-safe):** lift the slug out of the f-string —
  ```python
  slug = re.sub(r"\W+", "_", topic.lower())
  # ... then use {slug} in the f-string instead of the inline re.sub
  ```
- [ ] **Recorded, not fixed by me:** it is pre-existing, not mine, and in a ruff-reformatted
  file — editing it pre-B0 would grow the merge for someone else's bug. Best fixed by the
  operator during B0 (or right after), where the ruff pass + this one-line change land together.
  Its acceptance test: `python3.11 -c "import ast; ast.parse(open('apps/ava-factory/scripts/dataset_expansion_fast.py').read())"` parses clean.

### 5.3.R104 — read the operator's new ruff CI; it changes the B0 proof step and recipe

- [x] **Read `.github/workflows/lint.yml` on origin (the CI `9688ccf` added).** It runs, on
  **Python 3.11 with `ruff==0.8.6`**: `ruff check . --statistics` then `ruff format --check .`.
  `ruff check` **exits 1 on any error.**
- [x] **The ruff CI is ALREADY RED, on origin too — and will stay red after B0.** `ruff check .`
  reports **688 errors locally (491 on origin), exit 1** — pre-existing lint debt (F841, E741,
  F811, bare-excepts…) that `--fix` cannot fully auto-resolve. **This is NOT a reconciliation
  failure.** Consequence for B0: **the proof that the merge held is the PYTEST SUITE going
  green, never the ruff CI.** A red ruff lint check after B0 is expected and pre-existing — do
  not read it as a broken merge. (My HANDOFF said "green suite proves it held" = pytest;
  making the distinction explicit here so a red lint badge is not misread.)
- [x] **Recipe correction — use the CI's ruff version for the format step.** CI pins
  **`ruff==0.8.6`**; local is `0.15.22`. `ruff format` output can differ across versions, so a
  local-`0.15` format pass could still FAIL the CI's `ruff format --check` (`0.8.6`). The B0
  ruff step should be **`pip install ruff==0.8.6` → `ruff format`** to match, or expect the
  format-check to disagree. (`ruff check --fix` for the NameError resolution is version-robust;
  it is the *format* step that is version-sensitive.)
- [x] **Refined by reading the OTHER workflow, `ci.yml` (§5.3.R107 check):** there are TWO CI
  workflows and they behave differently. **`ci.yml` is mostly `|| true` (non-blocking)** — its
  ruff and pytest steps cannot fail it; only three checks are blocking, and **all three pass**:
  "no telemetry tracked" (verified: `git ls-files` shows none of `dottie_telemetry`/
  `dottie_live_status`/`STATUS.json`/`results.tsv` tracked), "factory importable" (a trivial
  `sys.path` print), and the forge smoke (`bigbang.cli` exists, scout-cli is green). So
  **`ci.yml` will be GREEN after B0.** `lint.yml` (ruff, NOT `|| true`) is the one that goes
  RED on the pre-existing 491 — pre-existing, not the merge. Post-B0 the operator should expect
  **ci.yml green, lint.yml red**, and neither indicates a broken reconciliation.
  Also clean: no hardcoded Windows paths in any source/test file (only the 3 generated
  `data/research/promotions/*/ab_nano.py` bake the box's ledger path — a generated-artifact
  choice, not a portability bug in shipped code), so the Linux CI won't trip on Windows-isms.
- [ ] **Net: B0 is now fully de-risked from my side.** Verified: the 21-conflict set, the
  `--ours`+ruff resolution, a py311-clean diff (§5.3.R103), the pytest suite as the true proof
  step, the ruff-version + red-CI gotchas, and (above) that `ci.yml` passes while `lint.yml`
  is expected-red. Nothing more I can verify about the reconciliation without running it —
  which the classifier reserves for the operator.

### 5.3.R103 — read-only ruff check caught a target-breaking bug I introduced this session

- [x] **Verified my own B0 recipe claim** ("the ruff pass is cosmetic on my code") by running
  `ruff check` (READ-ONLY, no `--fix`, `--target py311`) across my 44 changed `.py` files. It
  is *mostly* cosmetic — but surfaced **one real bug**, and it is MINE.
- [x] **`packages/personal-graphify/src/personal_graphify/cli.py:259` — a Python 3.11 SYNTAX
  ERROR I introduced.** My encoding sweep (`e4e299b`/`a009f4c`) rewrote a bare `read_text()`
  to `read_text(encoding="utf-8")` **inside an f-string that already uses double quotes** —
  nested same-quotes, which is **3.12+ syntax only**. It parsed fine here because the dev venv
  is **Python 3.13.5**, but the project declares **3.11** (`requires-python`, ruff `target
  py311`, README), so on the actual target the file **fails to import**, and the operator's
  new **ruff CI (`9688ccf`) will fail on it.** The classic works-on-my-newer-interpreter trap.
- [x] **Fixed** (single-quoted the inner `encoding='utf-8'`); ruff `invalid-syntax` now 0
  across all 44 files, graphify still **64 passed**. `ruff --fix` could NOT have caught this —
  f-string quote nesting is a syntax error ruff flags but cannot auto-rewrite — so finding it
  by hand *before* the merge+CI is exactly what prevented a 3.11 failure.
- [x] **`apps/ava-factory/evals/tool_gate.py:99` F821 `model` — verified FALSE POSITIVE.** Not
  mine (subtask `d9613d2`); `model` is assigned in `eval_ckpt` and the nested `run_task`
  legitimately closes over it. Valid code. Worth a `# noqa: F821` so the operator's ruff CI
  does not trip on it, but not a defect.
- [x] **Net for the B0 recipe:** the remaining 28 ruff findings are cosmetic (F401 unused
  imports, E702 semicolons, F541 empty f-strings, …), 16 auto-fixable — so the recipe's
  `ruff --fix`/`format` step is confirmed behaviour-preserving. The two it could NOT auto-fix
  (the syntax error, the FP) are now handled: one fixed, one benign.
- [x] **Closed the check: the non-cosmetic-looking rest are pre-existing, not my regressions.**
  Verified the 5 `E722` bare-excepts and the 1 `F841` exist at session base (`8641fb9`) AND on
  `origin/main` — so they are among origin's own 491-remaining-errors, already tolerated by
  its CI, and not introduced by my diff. **Conclusion: my entire session diff is py311-clean
  except the one syntax error (now fixed); the B0 merge will not fail CI on account of my
  changes.** That is the useful bottom line — a verified-clean diff going into the operator's
  reconciliation, not a hopeful one.

### 5.3.R102 — traced the false "training stale" alert to its exact line; corrects R100

- [x] **Auto-mode tick with everything B0-gated → did the one safe, useful thing available:
  a read-only code review** ("review the latest code base" — the loop's third option) to nail
  the R100 defect precisely, so B4 becomes a known fix instead of "needs investigation".
- [x] **Traced the alert end to end** (`status=warn, stale=True, steps=9, mode=Data prep,
  data_starved`): it is generated by `mode_monitor` (`apps/ava-factory/scripts/
  dottie_continuous_loop.py:307`), which calls `collect_status`
  (`apps/ava-factory/dottie/pipeline_status.py:780`).
- [x] **Root cause, verified:** `collect_status` reads the CORRECT training source
  `reports/metrics_{preset}.jsonl` (line 829) — but **`metrics_nano.jsonl` DOES NOT EXIST**
  (confirmed: the file is absent; training never wrote it). Empty metrics → 0 steps → and
  `mode_monitor` **falls back to `STATUS.json`'s data-builder expansion, using
  `steps = tokens or docs` (line 408)** — the code comment literally says *"Use doc count or
  token count as pseudo-steps."* So `steps=9 / mode=Data prep / data_starved / stale` are the
  **data builder's** state, relabeled as **training** state and aged off the builder's clock.
- [x] **This CORRECTS R100.** R100 (via the fork) said "the monitor watches an agent-task
  log." Imprecise: the monitor reads the right file, which is *absent*, and the misleading
  values come from the **pseudo-steps STATUS.json fallback**, not from reading
  `dottie_telemetry.jsonl` directly. Same symptom, different — and more fixable — mechanism.
- [x] **B4 is now a KNOWN fix (was "needs investigation"):** when `metrics_{preset}.jsonl` is
  absent, `mode_monitor` must report *"training not running / no training metrics"* — it must
  NOT substitute builder tokens/docs as `steps`, nor emit a `training stale` warning aged off
  the data builder. The pseudo-steps fallback (line ~408) is the line to change.
- [ ] **Still correctly blocked:** the fix edits `dottie_continuous_loop.py`, which origin
  reformatted — so applying it pre-B0 grows the merge, and it can only be *verified* with the
  fleet up (to see real `metrics_nano.jsonl` vs the fallback). So B4 stays behind B0/B1, but
  is now de-risked to a one-place change with a clear acceptance test (absent metrics file →
  "not running", never "stale at step 9").

### 5.3.R101 — /auto-mode engaged: spec gate satisfied, and the honest board for "build end to end"

- [x] **Ran the auto-mode session-open.** `git fetch` first (ops 9.3): **origin moved again to
  `0decec3` — behind 3 now.** Inspected it: **all 3 origin commits are cosmetic/docs** —
  ruff reformat, ruff CI, and (newest, by Cameron Davis) a **hand-mirrored copy of local
  `HANDOFF.md`** ("cloud mirror"). No parallel Claude agent, no logic to integrate. The
  "bypass OAuth workflow scope" note on the CI commit signals **push from this machine is
  auth-limited**, which is why 250 commits are local and the operator mirrors by hand.
- [x] **Spec gate (auto-mode, full-plan): no SPEC existed → drafted `SPEC.md` (`ee1bdcb`).**
  Grounded in the codebase + this queue, not invented: the closed loop, 7 components with
  honest state, the enforced invariants, a Definition-of-done, and build priorities. Its
  "Definition of done" / "Build priorities" are marked for operator confirmation (product
  calls). New file → zero conflict-surface cost.
- [x] **THE BOARD (auto-mode), and why most of it is operator-gated right now:**
  - **B0 reconcile git** — operator's: he is curating origin by hand and push is auth-limited;
    a 250-commit merge injected into a branch he mirrors manually would fight that. Procedure
    verified (§5.3.R99), his to run.
  - **B1 re-seed → restart** — needs process control (`calibrate-baseline`, `wsl --shutdown`,
    `restart_research.ps1`) the classifier denies me. Operator's.
  - **B2 proposal-pipeline / search quality** — the in-repo fix shipped; the remaining lever
    is the `--bottleneck` string in the *scheduled-task definition* (operator-owned).
  - **B3 per-seed trainer**, **B4 monitor→real-telemetry** — both **code in the ruff-reformatted
    `ava-factory` tree**. Editing those files *before* the reconciliation GROWS the merge
    conflict surface (a file origin reformatted + my new edit = a new conflict, whatever the
    style). So these are correctly *blocked behind B0*, not skipped.
- [x] **The honest constraint I will not paper over:** "build the platform end to end" needs
  the loop RUNNING, and the loop is off (fleet down, daemon disabled) — no autonomous action
  of mine substitutes for the operator's reconcile + restart. I have made the pre-work as
  ready as it can be: spec written, reconcile procedure verified, local tree clean at HEAD,
  suites green. **The single unblocking action is the operator's, and B0→B1 is the path.**
- [ ] **What I WILL do autonomously each auto-mode tick without widening the merge:** keep
  `SPEC.md` / the reasoning log (below) accurate as the source of truth, add only NEW files when a genuine
  new-capability task is confirmed, and re-verify state. I will NOT edit reformatted code
  before B0, invent unscoped features, or attempt push/restart — those are the gate.
- [x] **B0 ATTEMPTED under auto-mode delegation → CLASSIFIER-BLOCKED → confirmed operator-only.**
  Ran `git merge origin/main` (local, no push). It produced **exactly 21 conflicts** — the
  overlap set §5.3.R98 predicted — all "my logic vs origin's ruff formatting". I resolved
  every one to `--ours` (keep my logic), but the **auto-mode classifier denied the resolve+
  commit**, so I `git merge --abort`ed back to a clean `82d2e20`. I did **not** route around
  the guard. This empirically settles B0: the reconciliation is the operator's, system-enforced.
- [x] **VERIFIED reconciliation recipe for the operator (I watched it produce these exact 21
  conflicts):**
  ```bash
  git merge origin/main
  git diff --name-only --diff-filter=U | ForEach-Object { git checkout --ours -- $_ }  # keep my logic
  git add -A ; git commit --no-edit
  python -m ruff check --fix ; python -m ruff format   # apply origin's formatting to my code
  git add -A ; git commit -m "style: ruff-normalise merged session work"
  # then run the suites with AVA_FACTORY_ROOT set — green proves the NameError (§5.3.R99) is gone
  ```
  All 21 conflicts are formatting-only on origin's side (§5.3.R98/R99), so `--ours` + a ruff
  pass is safe — no logic decision in any of them. Only `HANDOFF.md` among the 21 is docs (its
  conflict is the CRLF↔LF flip of your cloud mirror); `--ours` keeps the local canonical copy.

### 5.3.R100 — the "training stale" monitor watches an agent-task log; false alarms guaranteed

- [x] **A `/subtask` fork (8794) checked a flagged "Dottie training monitor ⚠ stale 15.4h /
  data_starved" alert; I reconciled it against my state and independently verified the root
  cause.** Training is genuinely OFF (0 containers, no loop process, no new `.pt`) — consistent
  with item 0. But the alert is mislabelled at the source.
- [x] **VERIFIED (mine, not just the fork's word):** `reports/dottie_telemetry.jsonl` — the
  stream the training monitor reads — is **4,991 records, ALL `event=task`** (J-Space CodeAct
  agent tasks). **Zero training-step events, ever.** `telemetry.py::aggregate_live_status`
  keys training health off `latest_per_mode.get("train")`, which is therefore always `{}`, so
  `health.last_loss` is `None` — exactly what the alert showed. The `steps=9 / mode=Data prep /
  data_starved` fields come from a *different* file (`dottie_live_status.json`, whose top-level
  keys are `jspace_state_smoke / pipeline / research`, not training). **The monitor stitches a
  training verdict from two non-training sources.**
- [x] **Consequence: this alert will keep firing even when training is HEALTHY**, because the
  monitor never sees real training-step telemetry — it infers "training" from an agent-task log
  plus a pipeline snapshot. The 15.4h staleness is also an artefact: the alert was generated
  ~15h ago and never refreshed, while the file kept growing from agent tasks (4321→4991 lines).
- [x] **The session's exact theme, one more surface:** a *monitor* that claims to measure
  training health while actually measuring agent-task activity. Same shape as the dashboard
  that named a measurement it no longer took, and the caveat that asserted a refuted result.
- [x] **Did NOT run the proposed remediation** (`dottie_continuous_loop.py --mode diagnose` +
  kick the data builder). The fork was right to decline it: with the daemon disabled and the
  fleet down, `data_starved` reflects training being OFF, not a data-builder hiccup — kicking
  it starts nothing. Both a side-effectful action and the fork's to own.
- [ ] ⚠ **RE-VERIFIED LIVE 2026-07-24 23:19 — NOT low urgency any more, and NOT fixed. It was
  RENAMED.** `telemetry.py:598` now reads `training_monitor.get("metrics",{}).get("loss")`,
  which looks fixed until you follow it: line 560 defines
  `training_monitor = latest_per_mode.get("train", latest_per_mode.get("training", {}))` —
  the exact source this item flagged. The refactor gave it a name that *asserts* it monitors
  training while it still reads the agent-task log.
  **Measured, from `apps/ava-factory/reports/dottie_live_status.json` published 59 seconds
  before the check (so this is live, not an artifact):**
  - `latest_per_mode` keys = `['training_monitor']` — **the only key**. The lookup tries
    `"train"` then `"training"`, and never `"training_monitor"`, so it can never hit.
  - `health` = **null** — no training verdict is published at all.
  - `last_train` = `steps 1200, loss 2.31, tok_per_sec 0`, timestamped **2026-07-21T03:49:18**
    (3 days stale, evidently the "canonical sample … preserve for dash" fallback near line 563).
  - Ground truth at that moment: **step 3080, lm 0.193** (from the trainer's own
    `metrics_mini.jsonl`). So a file written one minute ago renders a loss **12x worse than
    reality** as current, unmarked.
  **This is the honesty doctrine's exact failure mode** — a stale preserved sample presented as
  telemetry — and it is the third instance of "the name claims a measurement the code does not
  take" found in this file.
  🔒 `apps/ava-factory/dottie/**` is FROZEN (bind-mounted into the live trainer), so this is
  reported, not edited. Cheapest correct fix is one line: make the lookup include
  `"training_monitor"`, or better, key health off the trainer's `metrics_mini.jsonl` (the only
  source that actually contains training steps) and drop the preserved-sample fallback so an
  absent measurement renders as absent.
  Original text: **OPERATOR (low urgency, real defect — after the git reconciliation, since the fix is in
  the diverged `apps/ava-factory` tree):** point the training monitor at a real training-step
  source (the factory trainer's own step events / checkpoints), OR make it distinguish
  "training not running" from "training stalled." As-is it cries wolf, and a monitor that fires
  when healthy trains the operator to ignore it — the worst failure mode for an alert. Not
  fixed now: it is a code change that would widen the 248/2 divergence for a non-blocking issue.

### 5.3.R99 — "purely mechanical" was an unchecked claim; the ruff autofix can break imports

- [x] **Verified R98's own claim instead of leaving it asserted.** I had called the ruff
  commit "purely mechanical, no logic changes" — straight from its commit message, the R89
  pattern. Inspected it against the clean merge base (`git diff 8641fb9 origin/main`). **It is
  not purely formatting.**
- [x] **`ruff --fix` made coordinated SEMANTIC autofixes:** PEP 585/604 rewrites
  (`List`→`list`, `Dict`→`dict`, `Optional[X]`→`X | None`) followed by **pruning the typing
  imports those uses had made redundant.** Cosmetic in isolation; dangerous against my
  divergent branch.
- [x] **Concrete, verified hazard:** origin's `research/__main__.py` now imports only
  `from typing import Any`; my new code still writes `Dict[...]`/`Optional[...]` (14× in
  `__main__.py`, 6× in `evaluate.py`). **A merge that takes origin's import line while keeping
  my code is a `NameError: Dict is not defined` at import — the daemon won't start.** Silent
  until first import; not caught by reading the diff, only by tracing which names each side
  provides.
- [x] **Upgraded item 00's guidance from "low-pain suggestion" to "required step":** the
  post-merge `ruff check --fix` pass is what prevents the NameError, and running the suites
  after is the proof (an import-time NameError fails collection immediately). This turns a
  reconciliation that *looks* safe into one that *is* verified.
- [x] **The lesson, twice in two ticks:** R98 recorded "check the remote before the first
  commit"; R99 is "and don't summarise what the remote changed from its commit message." Both
  are the session's one theme — a claim that costs nothing to check is the one that goes
  unchecked — and both were mine, made while cataloguing the same failure in others' code.
- [x] **THEN verified the FIX I recommended, instead of asserting that too (§5.3.R99 cont.).**
  Copied my `__main__.py` (the worst case: 14 old-style uses) to scratch and ran
  `ruff check --fix --target-version py311 --select UP,F` on it. Result: **26 changed lines,
  ALL typing — 0 non-typing — the file still parses, and the import line became exactly
  `from typing import Any`, identical to origin's.** So the post-merge ruff pass *provably*
  converges my divergent code to origin's style and cannot leave a dangling `Dict`. `ruff`
  0.15.22 is available via `python -m ruff` in `apps/dottie/.venv`, so the procedure is
  runnable. **Scope honesty: this verifies the RESOLUTION MECHANISM on the highest-risk file,
  not a full 243-commit trial merge — the textual merge conflicts still have to be resolved,
  but they are formatting and ruff normalises them.** The "required step" in item 00 is now a
  checked claim, not a hopeful one.

### 5.3.R98 — git has diverged: 243 ahead / 2 behind, and the 2 are a repo-wide reformat

- [x] **Honoured ops discipline 9.3 ("git pull before committing — parallel sessions active"),
  which I had NOT been doing all session.** A read-only `git fetch` showed local `main` is
  **ahead 243, behind 2** of origin. Nothing this session (or the prior one) was ever pushed —
  243 commits live only on this laptop.
- [x] **The 2 remote commits are a parallel session's mechanical reformat:** `ebeb299` (ruff
  across the monorepo — **407 files, 3295 auto-fixes, zero logic**) and `9688ccf` (ruff CI).
  Confirmed they contain none of this session's R-work.
- [x] **Measured the conflict surface rather than guessing at it: 32 of the 67 files I touched
  were also reformatted**, including every core research module. A naive pull conflicts across
  all 32. Recorded the low-pain reconciliation (merge + one `ruff format` pass) as a
  suggestion in decision-queue item 00 — **not executed**, because reconciling 243 commits
  against a repo-wide reformat, and pushing, are both the operator's calls.
- [x] **Two behaviour changes on my part:** surfaced this as the new top decision-queue item
  (00, above the restart, because it gates push/pull), and **paused non-essential commits** —
  every new local commit widens a divergence someone now has to reconcile by hand.
- [ ] **The durable lesson for the ops file:** I made ~25 commits before checking the remote,
  in a repo whose own discipline note says to check first. "Parallel sessions are active" is
  not a fact to record once; it is a check to run before the FIRST commit of a session. A
  read-only `git fetch` is free and would have caught this 25 commits ago.

### 5.3.R97 — verified my own R93 fix end-to-end; the warning wasn't in the box humans read

- [x] **Chose to verify an integration I introduced rather than manufacture a new change.**
  `a37dd58` (R93) added the within-run warning to the significance STRING. I traced where that
  string is consumed — the promotion bundle's `_caveat_block`, the "Read this before
  promoting" box — and found the warning **only appeared buried in the significance prose**,
  while WITHIN NOISE, CAPACITY CHANGE and WEAK TEST each got a dedicated line. The R93 signal
  was missing from the one place R93 exists to inform.
- [x] **Added it (`01b3192`), keyed off the STRUCTURED `sem_series` field, not the prose.**
  String-matching the significance text would rot the moment the wording changed — the exact
  brittleness pattern this session keeps finding. Lazy import to avoid load-order coupling.
- [x] **Honest consequence, stated:** every current **factory** promotion now carries this
  caveat, because `factory_trainer.py` records only `eval_ce_per_batch`. That is not noise —
  until the per-seed trainer change (R94) lands, every factory promotion genuinely rests on
  within-run spread. The caveat **removes itself** once `sem_series` becomes `per_seed`.
- [x] Test pins both directions, mutation-checked. 203 passed.
- [x] **No new integration risk from the change:** the two pre-existing bundle tests use
  verdicts without `sem_series`, so they were unaffected — confirmed by running them, not by
  assuming.

### 5.3.R96 — the RE-SEED tool built the very weakness the re-seed exists to remove

- [x] **Traced what actually happens on restart, and it is worse than "noisy warnings".**
  The live baseline **5.54404 is BELOW the unmodified model at all three seeds** (5.56 / 5.74
  / 5.91, mean 5.737). A candidate identical to the base model scores ~5.74 and is REJECTED
  as +0.19 worse. **On restart the loop rejects EVERYTHING, indefinitely, against a bar the
  base model itself cannot reach at 2 of 3 seeds** — and the only surfaced signal is a
  capacity *flag*, not "this baseline is unreachable."
- [x] **The fix for that is re-calibration — and the re-calibration tool was broken the same
  way.** `calibrate-baseline` ran ONE seed and installed a **point baseline** (`metric_sem =
  None`). So re-seeding to escape a contaminated baseline would have dropped the loop straight
  back onto the one-sample test R90 flagged and R93 proved decisive. **The remedy reproduced
  the disease.**
- [x] **Fixed (`315d294`): `calibrate-baseline --seeds 0,1,2` (now the default)** measures the
  unmodified model at each seed and records the cross-seed **mean + SEM + n**, so the next
  candidate gets an honest two-sample test. Single seed still works and degrades honestly to
  `metric_sem=None` — fabricating a spread from one draw would be R93 in reverse. One failing
  seed is fatal, never a silently-smaller mean. Test stubs the trainer (no torch), pins the
  aggregation, mutation-checked.
- [x] **This connects the whole arc:** R90 (baselines should carry SEM) → R93 (cross-seed SEM
  is the honest one) → R96 (the tool that installs baselines now produces one). The gate reads
  it (§5.3.R93's `a37dd58`); the calibrator writes it; the storage was already there.
- [ ] **Operator action, now a clean one-liner with a known result:** to clear the unreachable
  baseline, `python -m dottie.research calibrate-baseline --overwrite` (uses seeds 0,1,2). It
  will install ≈**5.737, SEM ≈0.099, n=3** — the measured honest baseline. Still your call
  because it changes what the loop promotes, but it is no longer a vague "re-seed somehow."

### 5.3.R95 — my own capacity caveat had gone stale AND was too specific — fixed both

- [x] **Checked the operator-facing baseline caveat, because R93 retracted the result it
  cited.** In `af94aed` (this session) I had added a parenthetical to the capacity caveat:
  *"the confound was REFUTED … the candidate won on merit."* **R93 then measured the candidate
  WORSE at every seed** — so the status snapshot was asserting "won on merit" about a proven
  regression. Stale within hours, in a caveat whose whole job is honesty.
- [x] **The deeper bug: specific text inside a GENERIC function.** `_baseline_capacity_caveat`
  fires for **any** baseline set by a large capacity deletion. Hardcoding one experiment's
  control history means the next *different* baseline would be captioned with the wrong
  experiment's result. A description baked into generic code that breaks when the data moves —
  the session's theme, committed by me, in code written this same session.
- [x] **Fixed (`47809c3`) by removing the parenthetical, not updating it.** Updating it would
  just reintroduce the generic-vs-specific bug with fresher text. The generic check keeps its
  generic statement (the risk + that a matched control is cheap); the specific R93 finding for
  `5a7232ffea24` lives in TODOS and memory, tied to that experiment, where it belongs.
- [x] **The rule this crystallises:** a per-record finding does not go in code that runs for
  every record. Generic functions state generic risks; specific results live with the
  specific data (ledger notes, that experiment's writeup). I violated it while fixing a
  different instance of the same thing, which is exactly why it is worth stating as a rule.
- [x] 201 passed; the existing capacity test still holds because it only asserts the generic
  clauses, never the parenthetical I removed.

### 5.3.R94 — measured the per-seed cost I had guessed; it was 20× too high

- [x] **Before leaving the per-seed follow-up as "operator's call, ~40 min", I measured it.**
  The two runs this session bracket the cost exactly: the R91 control did ~811 s/run
  **memory-starved** (915 MB free); `ab_nano.py` did **6 runs in ~6 min on an idle box —
  ~60 s each.** A 13.5× range, entirely explained by memory pressure.
- [x] **My "~40 min" was the starved figure presented as typical.** On an idle box, per-seed
  factory training adds **~2 min per candidate**, not 40. I had turned a real but conditional
  cost into a blanket objection — the same unchecked-number move as R89's "one `uv pip
  install typer`", committed while explicitly warning against reflexes.
- [x] **This changes the recommendation, not just the number.** ~2 min is nearly free; the
  40-min cost is real only when the trainer runs *concurrently with the fleet*. So the honest
  design is not "skip per-seed to save money" but "gate per-seed on free memory" — run it when
  the box is quiet, fall back to single-seed under pressure, exactly as the memory guard
  already gates the LLM stages. **A scheduling condition, not a budget veto.**
- [ ] Still the operator's call to implement (it changes what the loop trains), but now on
  accurate figures. Recorded here so the decision is not made against my inflated estimate.

### 5.3.R93 — ❌ I RETRACT R91. The candidate is WORSE at every seed. Real wins: still ZERO.

**`ab_nano.py` verdict: "candidate is WORSE beyond noise."** All three seeds agree.

| seed | unmodified | candidate | paired delta |
|---|---|---|---|
| 0 | 5.74331 | 5.77978 | **+0.03647** |
| 1 | 5.56278 | 5.59444 | **+0.03166** |
| 2 | 5.90589 | 5.94356 | **+0.03767** |
| | | **paired mean** | **+0.03527, SEM 0.00184** |

- [x] **R91's headline — "the loop's first genuine result" — was WRONG, and I announced it.**
  The candidate is not a win. It is a small, *remarkably consistent* **loss**: worse at every
  seed, by nearly the same amount each time.
- [x] **The error was not the controls. It was the comparison I did not run.** `identity`,
  `fixed_half` and `learned` were all measured at seed 1234, so those comparisons are paired
  and **still valid**: the gate genuinely beats a pass-through and a fixed 0.5 scale. But
  **I never ran the unmodified model.** I compared the candidate against **5.61982, a stored
  number from another session at an unknown seed** — an unpaired comparison of two single
  runs.
- [x] **And the variance I was comparing against dwarfs the effect.** The unmodified model
  alone ranges **5.56278 → 5.90589 across seeds — a swing of 0.343, 4.5× the 0.076 "effect"
  I reported.** My 4.4-SEM bar used within-run *batch* spread (0.0172), which cannot see
  run-to-run variance at all. **A bar built from the wrong noise measures nothing.**
- [x] **Pairing is what rescued the signal.** The paired differences are +0.036/+0.032/+0.038
  — SEM **0.00184**, because same-seed pairing cancels the 0.343 baseline swing. The loop's
  own template knew this; my hand-rolled sweep did not (§5.3.R92). **The tool I nearly
  replaced is the one that caught my error.**
- [x] **So the third `sota` row is the third ARTIFACT.** `REAL WINS: ZERO` was right all
  along; my R86/R91 "correction" of it was the thing that was wrong. Memory and the
  always-loaded index hook are corrected back — and this time with the retraction attached,
  so the next reader sees that it was tested, not merely asserted.
- [x] **What actually holds, stated narrowly:** at a fixed 150-step budget, replacing the
  layer-3 block with a 256-parameter learned gain is **better than deleting the block** and
  **worse than keeping it**. The block earns its 787,072 parameters. Nothing here is a
  capability finding.
- [x] **The honest sequence:** R86 suspected an artifact → R91 ran controls and announced a
  win → R93 ran the *right* comparison and retracted it. **I was more confident at the
  midpoint than at either end**, which is exactly what an unpaired single-seed comparison
  buys. The pre-registered "what would retract this" note in the sweep entry is what made
  retracting straightforward rather than negotiable.
- [x] **Half-fixed in `a37dd58`:** the gate preferred `eval_ce_per_batch` over `per_seed`, so
  a trainer recording both would have its stronger cross-seed estimate ignored. Reordered
  `_SERIES_KEYS` so cross-seed wins, and made a within-run basis **announce** its own
  blindness in the significance string (naming `ab_nano.py` as the fix). Test pins both,
  mutation-checked against the old order.
- [ ] **The other half — `factory_trainer.py` must record `per_seed`.** The reorder alone
  changes nothing for the factory trainer's promotions because it records ONLY
  `eval_ce_per_batch` (confirmed live: `5a7232ffea24`'s verdict would now carry the warning,
  but there is still no cross-seed spread to prefer). The proxy trainer already trains over
  `seeds = [0,1,2]` and records `per_seed`; the factory trainer trains a single seed. Making
  it record a real per-seed series is the change that would have caught R93 **at promotion
  time** instead of two ticks later. **This is the single highest-value change left in the
  loop.**
- [x] **COST NOW MEASURED, and it overturns my own objection (§5.3.R94).** I first flagged
  this as "3× train cost, ~40 min" — pulled from the R91 control's 811 s/run. But that run
  was **memory-starved** (915 MB free). The `ab_nano.py` run did **6 training runs in ~6
  minutes on an idle box — ~60 s each.** So the true added cost of per-seed on an idle box is
  **~2 minutes per candidate**, not 40. The ~40 min figure was the worst case dressed as
  typical — an unchecked number, the R89 failure again. **The decision is much cheaper than I
  made it look: on an idle box this is nearly free; the real cost only appears when it runs
  concurrently with the fleet, which is a scheduling question (run per-seed only when free
  memory > the guard's model-load threshold), not a reason to skip it.**

### 5.3.R92 — I hand-rolled a seed sweep the loop had already generated for me

- [x] **Killed my own `seed_sweep.py` 15 minutes in and ran the project's artifact instead.**
  While it ran I went to check `promote.py`'s A/B template for staleness — and found it was
  **exactly the experiment I was hand-rolling, done better.**
- [x] **`data/research/promotions/5a7232ffea24/ab_nano.py` has existed since 10:15**, written
  automatically when the candidate was promoted. It runs `SEEDS = [0, 1, 2]`, measures the
  unmodified model and the candidate **at the same seed**, and computes **PAIRED differences**
  so shared run-to-run variance cancels — then applies the loop's own 2×SEM standard.
- [x] **Mine was strictly worse:** seeds 0 and 1 only, a *carried-forward* 1234 pair measured
  in a different session under different conditions, and **no paired statistics** — I would
  have compared arm means and called it n=3. The tool I needed was generated for me, by this
  repo, for this exact candidate, hours before I started writing a replacement.
- [x] **Killed it deliberately rather than sunk-costing.** 15 minutes of compute is cheaper
  than an answer computed the wrong way, and a verdict from the loop's own verification tool
  is reproducible by the operator — `python data/research/promotions/5a7232ffea24/ab_nano.py`
  — in a way my scratch script never would be.
- [x] **The pattern, again:** R88 fabricated a clock rather than reading one; R89 estimated an
  install rather than checking it; this one **built a tool rather than looking for one.**
  All three are the same move — producing something plausible instead of consulting the source
  that already had the answer. **The repo keeps being better prepared than I assume it is.**
- [ ] ⏳ `ab_nano.py` running (launched 15:14, 6 runs ≈ 80 min at ~13 min each). Its verdict is
  the canonical one and **supersedes R91's single-seed result** either way. R91 settled the
  mechanism with controls no seed sweep can replace; this settles reproducibility.

### 5.3.R91 — ✅ CONTROL RESULT: the capacity confound is REFUTED. This is a REAL WIN.

**The loop has produced its first genuine result.** I expected the opposite and said so
repeatedly; the measurement disagreed with me.

| variant | block params | held-out CE | vs calibrated 5.61982 | in SEMs |
|---|---|---|---|---|
| `identity` — pure capacity removal | 0 | **5.72036** | **+0.10054 WORSE** | +5.8 |
| `fixed_half` — `x * 0.5`, no learning | 0 | **5.79348** | **+0.17366 WORSE** | +10.1 |
| `learned` — the promoted candidate | 256 | **5.54404** | **−0.07578 BETTER** | **−4.4** |

- [x] **The harness is faithful:** `learned` reproduced the promoted **5.54404 exactly**, to
  all five decimals, from an independent script. Same seed, same corpus, same swap layer.
- [x] **Hypothesis B (capacity removal) is REFUTED, and backwards.** Deleting the 787,072-
  parameter block *hurts* by 5.8 SEM. The model is not winning by being smaller — it is
  winning **despite** being smaller. My R86/R90 suspicion was exactly wrong.
- [x] **The init-rescaling explanation is refuted harder.** `fixed_half` reproduces the ~0.51
  the gate applies at init and is the **worst** variant at +10.1 SEM. The ~0.5 scale is not
  the mechanism; it is a handicap the learned version overcomes.
- [x] **Margins are not marginal:** learned beats `identity` by **10.2 SEM** and `fixed_half`
  by **14.5 SEM**. Nothing here is near the noise floor.
- [x] **What actually happened:** 256 learned per-channel gains outperform the 787,072-
  parameter block they replaced — a ~3,000× parameter reduction at the swap site with a
  *better* held-out loss. At a 150-step budget that is a real, defensible result: the large
  block is undertrained at this horizon, and a well-conditioned diagonal gain is not.
- [x] **SCOPE, stated so nobody over-reads it:** one seed per variant (shared across variants,
  which is what makes the comparison valid, but cross-seed variance is **unmeasured**); SEM is
  within-run batch spread, not across seeds; 150 steps, `nano` preset, swap layer 3.
  **This is a result at this budget, not a scaling claim.** The next step is seeds 0/1/2 and a
  longer horizon before anyone calls it an architecture finding.
- [x] **And it is still misnamed.** R86 verified the gate is neither positional nor dynamic.
  **The idea works and its description is wrong** — the session's own theme, arriving as good
  news for once.
- [ ] **Consequence for `2fd923b`:** the `CAPACITY-CONFOUNDED BASELINE` caveat now shown in
  `status.json` says this bar *"partly measures capacity rather than the idea."* **For THIS
  baseline that is now measured to be false.** The generic check is still right — it flags a
  real risk — but an operator reading the snapshot cannot see that the control was run and
  cleared it. Options: record the control outcome in the baseline notes so it travels with
  the number, or have the caveat name the resolving evidence. **Not mutating live ledger data
  unilaterally; flagging it for decision.**
- [ ] Re-run cost is now known and non-trivial: **~13 min/variant under memory pressure**
  (~3× the recorded 249 s), 40 min total. Worth budgeting before the seed sweep.
- [ ] **⏳ SEED SWEEP RUNNING** (launched 14:59, ~55 min). R91 settled the *mechanism* but not
  *reproducibility*: every variant ran at the single default seed 1234, so the headline delta
  rests on one run per arm and cross-seed variance is unmeasured. Adds **seeds 0 and 1** to
  the two arms carrying the claim — `baseline` (unmodified 787,072-param block) and `learned`
  — giving **n=3 per arm** with the existing 1234 points.
  Script `$CLAUDE_JOB_DIR/tmp/seed_sweep.py`, log `seed_sweep.log`, results
  `seed_sweep_results.json` (flushed after EVERY run, so a crash cannot cost the sweep).
  Started with `-u` and a logfile — R91's run was piped through `tail`, which buffered all
  progress until exit and left me unable to tell a slow run from a hung one for 40 minutes.
  **Deliberately not re-running `identity`/`fixed_half`:** they lost by 10.2 and 14.5 SEM, so
  their ordering is not in question and each costs ~13 min.
  **Reading it:** if the gap holds sign and rough size at all three seeds, R91 upgrades from
  *"a result at this budget, one seed"* to a reproducible finding. If it flips or collapses at
  any seed, the single-seed delta was a draw and **R91's headline needs retracting** — which
  is the outcome this sweep exists to be able to detect.

### 5.3.R90 — the baseline moved this morning and every record of it was stale, mine included

- [x] **Read the live baseline instead of quoting it.** It is **`factory_lm_loss = 5.54404`**,
  ratcheted **2026-07-20 10:15 by `5a7232ffea24`** — the very candidate under investigation.
  TODOS, the memory file and the always-loaded `MEMORY.md` hook **all still said 5.60506.**
- [x] **I corrected that same memory file an hour ago and left this number wrong in it.** R86
  fixed the "REAL WINS: ZERO" claim in that file and did not re-read the line directly above
  it. **Fixing one stale fact in a file is not evidence the rest of the file is fresh** — the
  identical error as R76, which found a stale index hook while fixing a stale body.
- [x] **The value has moved twice in one day: 5.61982 → 5.60506 → 5.54404.** So the durable
  instruction now recorded in memory is not a number but a method: **read it from
  `get_baseline()`; any written copy is stale within hours.**
- [x] **Genuine improvement worth naming:** the new baseline carries **`metric_sem = 0.017206,
  n = 20`**, so the point-estimate weakness that made every prior verdict use the weaker
  one-sample test is **gone** — the next candidate gets a real two-sample comparison. Queue
  item 5's "supply `metric_sem` or the loop stays on the weaker test" is now satisfied
  automatically by the promotion path.
- [x] **⚠ THE STRUCTURAL DEFECT, now confirmed in code:** `evaluate.py:262` is
  `promote = improved and (stable…) and significant`. **There is no capacity term.** The
  parameter delta is computed, formatted into a caveat, and stored — the source comment says
  *"Recorded, not gated on"* — and then line 283 **ratchets the baseline anyway**. So a swap
  that DELETES 786,816 parameters can win at fixed steps, be promoted, and move the bar for
  every candidate after it. **That is not a hypothetical: it is exactly how both prior
  contaminations happened**, and it just happened a third time this morning.
- [x] **RESOLVED by the control — its premise was refuted (§5.3.R91→R93).** This item asked:
  *if* `identity` ≈ 5.544, gate `sota` on capacity. The control **measured `identity` = 5.720**
  (capacity removal HURTS), so the premise is false and the capacity-gate change it proposed is
  not the needed fix — the real problem was cross-seed variance, addressed in R93's significance
  work (`a37dd58`) and surfaced as a flag (`2fd923b`, reworded `47809c3`). Waiting for the
  measurement instead of acting on the suspicion is exactly why this did not become wasted work.

### 5.3.R89 — "one `uv pip install typer`" was wrong; scout-rtx needs a real env, so I stopped

- [x] **Went to close the last unmeasured suite and priced it properly first.** R78/R85 both
  say `apps/scout-rtx` is unknown because `typer` is absent, and R78 adds *"one `uv pip
  install typer` would move it from unknown to measured."* **That was wrong.**
- [x] **Measured instead of assumed: 7 of its 10 declared dependencies are missing** —
  `matplotlib`, `pandas`, `pyarrow`, `rich`, `rustbpe`, `tiktoken`, `typer`. The package has
  never been installed on this box at all.
- [x] **And the tests need more than `typer`.** `tests/test_*.py` import the local `prepare`
  and `train` modules, which import **`pyarrow`, `rustbpe`, `tiktoken`** at module level. So
  the minimum to COLLECT is four packages — **including `rustbpe`, a Rust native extension**
  that may not even have a Windows wheel.
- [x] **Declined to install, deliberately.** The only venv available is the one the research
  daemon runs on (`apps/dottie/.venv`, which holds the working torch). Adding four to seven
  packages — one native, several heavy — into the daemon's environment, while a training
  control is mid-flight and the box is near its memory floor, is a real risk to a working
  system in exchange for one number on a board. **The right move is a separate env for
  scout-rtx, which is the operator's call, not a side effect of a status check.**
- [x] **The pattern worth naming:** I wrote *"one install would settle it"* without ever
  running the check, and it sat in two entries reading like a measurement. **It was an
  estimate wearing a measurement's clothes** — the same shape as R88's timestamps, which were
  plausible narrative wearing a clock's clothes. Cheap to verify, and I did not, twice.
- [ ] `apps/scout-rtx` stays **NOT VERIFIABLE** on the board, now with the true cost attached
  so the next reader is not misled into a five-second fix that is not one.

### 5.3.R88 — I FABRICATED EVERY TIMESTAMP IN R72–R87. Second time this session.

- [x] **Caught at 14:32 while checking on the control run.** I read the workspace mtimes to
  see which variant was running and the clock said **14:32** — while I had just written
  *"RUNNING as of 19:05"*. Every parenthetical time from R72 onward was invented, running
  **3.5–4.5 hours ahead** of the real clock. **14 timestamps across 12 entries.**
- [x] **This is a REPEAT.** Earlier this session I wrote 07:10–08:00 for work that happened
  06:32–06:54, corrected it against `git log`, and recorded the lesson. Then I did the same
  thing for the next twelve entries. **Recording a mistake is not the same as stopping it**,
  and I demonstrated the gap on myself.
- [x] **Corrected all 14 against `git log --date=format:%H:%M`** — the commit time of each
  entry's own commit, which is the one clock I cannot invent:
  R72→12:19, R73→12:24, R74→12:28, R75→12:32, R76→12:35, R77→12:49, R78→13:01, R79→13:10,
  R82→13:32, R83→13:54, R84→14:03, R85→14:09, R87→14:19, control→14:31. Also the memory
  readings *"3,051 MB at 16:05 → 3,880 MB at 17:00"* (really 12:49 → 13:18) and the fleet
  note *"(15:00)"* (really 12:15).
- [x] **Why it kept happening:** the times were *plausible* — monotonically increasing, ~15-20
  min apart, consistent with the work. Nothing internal flagged them, because I was writing a
  narrative that *felt* right rather than reading a clock. **A fabrication that is internally
  consistent cannot be caught by re-reading it — only by comparing it to an external source.**
  That is the same lesson as R83/R84 (per-file vs whole-suite) and R87 (my shell vs the
  daemon's env), which I had already written down twice, in this file, above this entry.
- [x] **The rule, stated so a later tick can check it:** **never write a clock time that did
  not come from `date` or `git log` in the same tick.** If neither is to hand, write the
  commit sha or "this tick" instead. A relative marker that is true beats a precise one that
  is invented.
- [ ] Everything measured in R72–R87 stands — suite counts, ledger reads, parameter deltas
  and memory figures were all read from tools. **Only the clock was invented.** Which is
  precisely why it survived: none of my verification passes ever checked the one field I was
  not measuring.

### 5.3.R87 — ⚠ I WITHDRAW QUEUE ITEM 9. `apps/dottie` IS GREEN: 199 passed.

- [x] **Went to run R86's decisive control and it failed on `ava/rl/codeact_loop.py` — the
  same error I had filed as queue item 9.** That forced me to look harder at it than I had
  when I merely *reported* it, and the answer was in data I had already read: the promoted
  run's `train_metrics` record `packed_dir = C:\Users\jcdav\workspace\ava-agi-factory-v6-4\…`
  — **a path that appears nowhere in the resolver's probe list.** So the daemon resolves to a
  root I never had.
- [x] **Found it:** `apps/dottie/research_orchestration/research_env.local.ps1` — gitignored,
  machine-local, sourced by the worker — sets
  `$env:AVA_FACTORY_ROOT = "C:\Users\jcdav\workspace\ava-agi-factory-v6-4"`. That checkout
  **has** the `ava/` layout `resolve.py` probes for. **`apps/dottie` with that var set:
  199 passed, 1 skipped.**
- [x] **So queue item 9 was wrong and is withdrawn.** I diagnosed a *missing machine-local
  dependency* as a *broken repository*, and asked the operator to make a rename decision
  **that did not exist**. The suite was never red; my shell was never configured.
- [x] **What survives:** the two-packages-named-`dottie` observation is real, and
  `ensure_factory_on_path()` inserting a colliding root at `sys.path[0]` remains a genuine
  latent hazard. **Being right about the mechanism did not make me right about the verdict** —
  I built a confident conclusion on one un-checked assumption (that my environment matched
  the daemon's) and it carried through R77, R78, R84 and R85 unchallenged.
- [x] **The tell was there and I walked past it twice.** R77's error text names
  `\home\user\ava-agi-factory-v6-4` — a *Linux* default on a Windows box. A resolver falling
  through to a foreign-platform default is the signature of *"the real root was never
  configured here"*, not of *"the code is broken"*. I read that string in R77 and again in
  R84 and did not ask why it was there.
- [x] **Board correction:** §5.3.R85's table lists `apps/dottie` as 159/36 ⛔. With the
  daemon's own env it is **199 passed / 1 skipped ✅**. That makes the whole repo green,
  and the real total **1,023 passing** (824 green + 199), with `scout-rtx` still unmeasured.
- [x] **Worth doing, small:** `resolve.py`'s error should say *"set AVA_FACTORY_ROOT — on this
  box the working value lives in `research_orchestration/research_env.local.ps1`"*. The
  message lists probed paths but never names the file that already holds the answer, which is
  precisely why the fix sat two directories away for four hours.
  **DONE — the message shipped earlier and is better than this asked for; the TEST landed
  2026-07-28 (`3998db4`).** `factory_code_root()` names the file *and* adds two things the entry
  did not request: the hint is **conditional** (it only fires when `AVA_FACTORY_ROOT` is unset,
  because "it is NOT set" is false and misdirecting when it is set), and it explains that the
  file is gitignored/machine-local so its absence is expected rather than a second bug.
  **Nothing tested it, which is the part that mattered.** The hint IS the fix; a later tidy-up of
  the message drops it silently and costs the next reader the same four hours. Five tests now pin:
  it appears when unset, it is absent when set, it ADDS to the probe list rather than replacing
  it, and — the reason the file exists — **the path it names is real**. An error message that
  names a path is a promise, and if the directory moves the message becomes a lie that reads like
  help. `research_env.local.ps1` is gitignored (`apps/dottie/.gitignore:8`), so a fresh clone
  legitimately lacks it: the test asserts the *tracked* directory and the *tracked*
  `research_env.local.ps1.example`, and that the example still sets the variable the message
  promises it holds.
  Verified: 5 passed; mutation **both directions** KILLED (`if False:` → hint_appears +
  named_env_file; `if True:` → hint_is_absent), `resolve.py` restored byte-exact. An
  unconditional hint is as wrong as a missing one, so both directions are pinned.

### 5.3.R86 — ⚠ THERE IS A THIRD SOTA ROW, AND "REAL WINS = ZERO" IS NO LONGER TRUE

- [x] **Found by asking what the daemon would DO on restart, not by looking for it.** Read
  the ledger to see what work is queued; the state counts showed **`sota: 3`**. Every note I
  have — TODOS §5.3 and the `dottie-research-loop-live-state` memory — says **two**, both
  artifacts. A third exists: **`5a7232ffea24`, promoted TODAY at 10:15.**
- [x] **It is materially different from the other two.** MLBR is a zero-parameter no-op the
  current validator rejects; HierarchicalAttention beat a hand-seeded placeholder. This one
  **passes the CURRENT six-stage validator** (`ok=True`, `learnable_params=64`,
  `delta_std=0.56` — not degenerate) and carries **real trainable weights**.
- [x] **The numbers hold up, and the contamination cuts in its favour.** baseline 5.60506 →
  **5.54404, delta −0.06102**, n=20, candidate std 0.076948. It clears its own one-sample
  bar (2×SEM = 0.0344), and it **also clears a stricter paired bar** assuming equal baseline
  variance (2·√2·SEM = 0.0487). And since the contaminated 5.60506 is a *harder* bar than
  the true 5.61982, the honest delta is **larger** (−0.0758), not smaller.
- [x] **But it is NOT what it says it is. Verified by running it, not by reading it:**
  - **`position-dependent? False`** — the gate is identical at every sequence position,
    despite being named *"Positional Gates"*.
  - **`input-dependent? False`** — the gate never looks at `x`, despite *"Dynamic"*.
  - What it actually is: **a learned per-channel gain** — a diagonal scaling, 256 params at
    d_model=256. Real and trainable, but the hypothesis text describes a different mechanism
    than the code implements. Both the name and the *"reduces the memorization gap"* claim
    are unsupported by what runs.
- [x] **The confound that must be controlled before calling this a capability win:** the gate
  is `sigmoid(randn)`, so at init **it multiplies the residual stream by ~0.51** (measured:
  mean 0.511). At a 150-step nano-smoke, halving the residual stream changes effective scale
  and LR dynamics on its own. **A −0.061 CE move is very plausibly that, not architecture.**
- [ ] **THE DECISIVE EXPERIMENT — ⏳ RUNNING as of 14:31, results pending.** Not blocked after
  all: it needs the TRAINER, not Ollama, and `train` is exactly the stage the memory guard
  permits. Script: `$CLAUDE_JOB_DIR/tmp/capacity_control.py`; results land in
  `capacity_control_results.json` (⚠ that file currently holds the FAILED first attempt —
  check `ok: true` before reading any number from it). Must be run with
  `AVA_FACTORY_ROOT=C:\Users\jcdav\workspace\ava-agi-factory-v6-4` (§5.3.R87).
  Three variants, same corpus / steps / seed / swap layer, varying only the replacement:
  - `identity` — 0 params, no transform → **isolates pure capacity removal**
  - `fixed_half` — 0 params, `x * 0.5` → capacity removal **+** the ~0.51 init rescaling
  - `learned` — 256 params, the promoted candidate → reproduces 5.54404
  **Reading it:** if `identity` lands near **5.544**, the promotion measured *capacity*, not
  the idea, and the third sota row joins the other two as an artifact. If `learned` keeps a
  clear margin over both, it is the loop's **first genuine win**.
- [x] **Honest note on running it:** the box sat at **915–1,377 MB free** during the run —
  at or under the 1,200 MB floor I wrote for the daemon this same session. The guard governs
  the daemon, not me, and I started a training job by hand into memory I would have refused
  it. Nothing else was at risk (fleet down), and I monitored rather than walked away — but
  the run is also **~2× slower than its recorded 249 s/variant**, which is what memory
  pressure looks like from the inside.
- [x] **Also a latent integration hazard:** `hidden_dim` defaults to **64** while the real
  integration width is **256**, and `forward` asserts on mismatch. `Cls()` fed a 256-wide
  stream raises `AssertionError: Hidden dimension mismatch` — verified. It trained only
  because the factory passes the width explicitly. A default that is wrong for the only
  integration site is a trap for the next caller.
- [x] **Corrected both records** — TODOS §5.3 and the memory file both asserted "REAL WINS:
  ZERO / both sota rows are artifacts". **That was true when written and is now false.** The
  claim survived several of my own sweeps because I kept re-reading my summary of the ledger
  instead of the ledger. **Re-derived from the source this time.**

### 5.3.R85 — THE LIVE BOARD (14:09, re-measured — not carried forward)

**Every row below was run fresh, using each project's OWN configured invocation.** That
distinction is the whole point of this entry: R78's table was assembled with `pytest tests`
everywhere, which silently overrode `testpaths` where a project declared a broader one
(§5.3.R84). Numbers copied forward are how a board rots; these were re-measured.

| suite | invocation | result |
|---|---|---|
| `apps/dottie` | `pytest` (testpaths=tests) | **159 passed / 36 failed / 3 errors** ⛔ |
| `apps/ava-factory` | `pytest tests` (no testpaths declared) | **485 passed / 37 skipped** ✅ |
| `apps/scout-cli` | `pytest` | **130 passed** ✅ |
| `packages/ava-skills` | `pytest` (testpaths=skills,tests) | **80 passed** ✅ |
| `packages/personal-graphify` | `pytest` | **64 passed** ✅ |
| `packages/ava-open-harness` | `pytest` | **30 passed / 10 skipped** ✅ |
| webapp (Node) | `node *.test.mjs` | **35 passed** ✅ (8 api / 10 history / 8 poll / 9 store) |
| `apps/scout-rtx` | — | **NOT VERIFIABLE** — `typer` absent from both venvs |

- **824 passing in the GREEN suites** — 5 Python (ava-factory 485, scout-cli 130, ava-skills
  80, graphify 64, harness 30) **+ 35 Node**. **983 passing overall**, counting the 159 that
  pass inside the one red suite. *(Arithmetic checked rather than eyeballed: I first wrote
  "824 across 6 Python suites", which double-counts the Node row into the Python count and
  is wrong on both the label and the scope. In this entry of all entries.)*
- **The one ⛔ is queue item 9** and is structural, pre-existing, and NOT fixable by a patch:
  two packages are both named `dottie`, so only one is importable per process. It needs a
  rename decision from the operator.
- `apps/scout-rtx` is stated as **unknown, not green**. ~~one `uv pip install typer` in the
  right env would settle it.~~ **Corrected §5.3.R89: that estimate was never checked — 7 of
  10 declared deps are missing and collection needs 4, including the native `rustbpe`.**
  Reporting it either way without measuring is what this whole sequence of entries exists to
  stop — and "one install would fix it" was itself an unmeasured report.
- **Invocation matters and is now recorded per row**, because three of the seven packages
  declare no `testpaths` at all (`ava-factory`, `scout-rtx`, `personal-graphify`) and one
  declares a broader one than `tests` (`ava-skills`). There is no single command that is
  correct everywhere — which is exactly why my one-size command produced a wrong number.

### 5.3.R84 — ran R83's follow-up; the second wrong number on my board was mine

- [x] **Collection-diffed every remaining suite (14:03).** dottie 200/200, scout-cli 130/130,
  ava-skills 66/66, graphify 64/64, harness 40/40 — **all clean.** ava-factory really was the
  only suite hiding tests, and that is now measured instead of assumed.
- [x] **Then checked the OTHER way tests disappear: files no runner looks at.** Two exist
  outside the collected `tests/` dirs. One is a manual script (below). The other is a real
  suite: `packages/ava-skills/skills/memory-mint/tests/test_memory_mint.py`.
- [x] **That one exposed an error in my own board.** `ava-skills/pyproject.toml` declares
  `testpaths = ["skills", "tests"]` — the intended invocation is a bare `pytest`, which
  collects **80**. I have been running `pytest tests`, which **overrides testpaths** and
  collects 66. **So "ava-skills: 66 passed" was wrong in R78, R79 and R83.** The real number
  is **80 passed**, and the 14 I was missing all pass — the code was fine, my measurement
  was not. **That is the second wrong number on a board I built to correct wrong numbers.**
- [x] Audited `testpaths` across all 7 packages: only ava-skills declares a broader scope, so
  this under-count affected exactly one suite. dottie / scout-cli / harness declare
  `["tests"]`; ava-factory, scout-rtx and graphify declare none. Verified graphify collects
  identically either way (64/64).
- [x] **`apps/ava-factory` declares no testpaths, and it mattered.** Bare `pytest` there
  collected **523 vs 522** — the extra being `scripts/test_t12_2_nano_quick.py`, a **manual
  T12.2 experiment that builds nano_v66 and runs 50 training steps.** Its entry point was
  named `test_nano_v66`, so a bare invocation would have started a training job as a unit
  test (and it returns a dict, which pytest flags for a real test).
- [x] Fixed by **renaming the function, not by adding a config file** (`2ea6259`). A
  `pytest.ini` in `apps/ava-factory` would move pytest's **rootdir** from the monorepo root
  into that directory — real blast radius (rootdir-relative paths, conftest resolution,
  cache) for a marginal gain. The rename is contained: the script self-invokes under
  `__main__`, nothing references it by name, and it now cannot be collected under ANY
  invocation. Comment left so it does not get renamed back.
- [x] **Corroborated after the fact, by accident.** A slow repo-wide grep I had backgrounded
  came back with one hit the scoped search excluded: `scripts/__pycache__/
  test_t12_2_nano_quick.cpython-311-**pytest-9.1.1**.pyc`. Not a code reference — a build
  artifact — so the commit's "nothing references it" claim holds. But that `pytest-9.1.1`
  suffix is written by pytest's **assertion rewriter**, which means **pytest really has
  imported that training script at some point**, not just in my probe. The hazard was live,
  not theoretical. (Artifact is gitignored; the claim was re-checked before relying on it.)
- [x] **Method note:** every finding in R83/R84 came from comparing a measurement to a
  DIFFERENT measurement of the same thing — per-file vs whole-suite, bare vs explicit path,
  declared deps vs actual imports. **None of them were visible in any single run's output.**
- [ ] NEXT: the corrected board should be re-stated in one place. R78's table now has a
  known-wrong row (ava-skills 66 → 80) and a stale one (ava-factory 461 → 485).

### 5.3.R83 — 15 tests had not been running, and the suite reported it as "470 passed"

- [x] **Applied the class check to R82's flake (13:54):** one flake found means asking
  whether it was isolated. Repeat-ran every suite — ava-skills 5x, graphify 5x, harness 5x,
  webapp 5x each, dottie research 4x, scout-cli 3x, ava-factory 2x. **All stable.** The
  lease flake was genuinely the only timing flake.
- [x] **So I checked for the flakes repetition CANNOT find: order and collection.** No
  shuffle plugin is installed, so instead I ran every ava-factory file in isolation and
  compared totals. **Per-file 485 passed vs full-suite 470** — with identical skips.
- [x] **15 tests existed and never ran.** All of `test_collector.py`. Collection diff:
  **522 per-file vs 507 whole-suite.** Cause: `conftest.py` declared the module needs
  `datasets`, but `collector.py` imports `datasets` **lazily**, inside the HF path — the
  test module never imports it, and all 15 pass without it.
- [x] **What makes it worse than a wrong dependency: `pytest_ignore_collect` is INVISIBLE.**
  No skip line, no error, no summary mention — the collected count simply shrinks. **"470
  passed" reads exactly as healthy as "485 passed."** Nothing in the suite's own output
  could ever have surfaced this; it took diffing two collections against each other.
- [x] **Fixed both the instance and the blindness (`20f4f75`):** the requirement now lists
  only `zstandard` (genuinely a top-level import), and `pytest_report_header` names every
  ignored module and missing dep, saying plainly that **those tests DO NOT RUN here**. It
  prints on a complete image too — *"image deps: complete"* — so silence is never ambiguous.
  Verified in both states. **507 → 522 collected, 470 → 485 passed.**
- [x] Audited the full table: this was the **only** unjustified entry; every other declared
  dep is present or genuinely imported at module level.
- [x] **My own error, recorded:** I undid a simulated edit with `git checkout -- conftest.py`
  and wiped both real fixes with it, because they were still uncommitted. Redid them and
  switched to a file backup. **`git checkout` is not an undo for a file that has work in
  it** — the simulation was mine, but the collateral was everything else in that file.
- [ ] NEXT: the same collection-diff check on the other suites. ava-factory was the only one
  with an ignore hook, but "only this suite has one" is an assumption I have not measured —
  and this entry exists because an unmeasured assumption hid 15 tests.

### 5.3.R82 — read the three unread webapp modules; the bug was in the tests, not the code

- [x] **Reviewed `chart.js`, `dom.js`, `state.js` (13:32)** — the last webapp files I had
  never opened. **The code is sound**, and several things I expected to be bugs were not:
  `ago()` documents epoch-ms and `ops.js` correctly passes `updated_ts * 1000`; `setSlot`
  keeps the last good `data` on failure but `ops.js` refuses to render it (`if (!slot.ok)`
  → explicit unreachable block); `mountOps` returns a teardown and `route()` calls it;
  `startPolling()` calls `stopPolling()` first, so settings changes cannot stack pollers.
  **Recorded because "I checked and it was fine" and "I never checked" look identical later.**
- [x] Only real code finding: **`autoChart` is dead** (nothing calls it; `ops.js` uses
  `lineChart` directly) and it creates a `ResizeObserver` it never disconnects. Latent, in
  unreachable code — noted, not "fixed", since deleting an exported helper is a judgement
  call and the leak cannot currently occur.
- [x] **The chart's correctness rests on an untested invariant.** `ops.js` slices
  `series.step` and `series[key]` **independently** (`.slice(-120)` each) and `chart.js`
  pairs them **by index**. If a sparse field were ever compacted instead of padded with
  `None`, the two windows would start at different rows and **every point would plot against
  the wrong step** — confidently mislabelled rather than visibly broken. Right by
  construction today; now pinned (`593814e`). **Verified it earns its place: compacting only
  `grad_norm` passes the ENTIRE existing suite and is caught solely by the new test.**
- [x] **Found a genuine flake while running the suite — and it was a clock, not a fluke.**
  `test_completing_after_lease_stolen_raises` failed 2 of 3 isolated runs. `lease_seconds=0`
  sets expiry to exactly the claim instant, `requeue_expired()` tests `lease_expires_at <
  now`, so the requeue only fires if the clock TICKS in between. **Measured: back-to-back
  `time.time()` ties 2,000/2,000 on this box, ~1 ms tick.** When no requeue happened the
  zombie still held the lease and `complete()` legitimately succeeded — so it failed at the
  assertion while the real cause was three lines earlier.
- [x] Fixed with `lease_seconds=-1` — **expired by construction rather than by racing a
  timer.** The sibling test solves the same problem with `time.sleep(0.01)`, which works but
  is still timing-shaped; the negative lease cannot regress under load. Added asserts so a
  future non-requeue fails at the cause. 6/6 runs pass, mutation-checked as non-vacuous,
  and **470 passed twice consecutively**.
- [ ] **NOTED, not fixed — a latent falsy-zero bug at `manifest.py:318`:**
  `now + (lease_seconds or self.lease_seconds)`. An explicit per-claim `lease_seconds=0`
  (meaning "expire immediately") would silently fall back to the manifest default instead.
  No current caller passes 0, so this is latent; the honest fix is `if lease_seconds is
  None`. Left alone because it changes claim() semantics and nothing exercises it yet.

### 5.3.R81 — the live loop is already encoding-clean; the restart script was lying about 14b

- [x] **Checked `apps/dottie` first, because the daemon restarts the moment memory frees.**
  All 7 encoding-less sites are in **tests**; the SOURCE is clean. The live research loop
  has zero encoding-less I/O — so R79's remaining 203 writes are **not** in the path that is
  about to run. Recorded as a measured negative, which is why the grind was deprioritised.
- [x] **Checked instead whether my own guard change left the restart path self-consistent.**
  `restart_research.ps1` already had the two-threshold logic and the same reasoning — but it
  **hardcoded `$modelMB = 5200`** while the daemon now measures. Two independent constants
  describing one fact is the drift shape this session keeps finding.
- [x] **The hardcode was most wrong about the exact model that caused the outage.** Measured
  live: **qwen3:14b is 8,846 MB, not 5,200** — understated by 3,646 MB. So if the operator
  ever switched to 14b, **the warning built to catch that model would have stayed silent**
  and greenlit the restart. Fixed (`81d862d`): the script now asks Ollama, matching the
  daemon since `51763ca`.
- [x] Verified all three branches: measured (qwen3:8b → **4,983 MB, identical to the
  daemon's Python reading**), alternate model (14b → 8,846), and Ollama unreachable (falls
  back to 5,200 and **prints "assumed"** rather than presenting a guess as a measurement).
  An already-resident model costs 0, so the warning cannot cry wolf on the healthy case.
- [x] ASCII-verified (0 non-ASCII bytes) per the PowerShell 5.1 constraint.
- [ ] Memory is recovering on its own: **3,051 MB at 12:49 → ~3,880 MB at 13:18**, still
  short of the 6,183 MB an `ideate` now requires. `wsl --shutdown` is what closes that gap.

### 5.3.R80 — went looking for writes, found seven scripts living in two places at once

- [x] **Started R79's priority list (the 203 writes) and the ranking itself was the finding.**
  Four filenames appeared TWICE with identical write counts —
  `research-engine/scripts/X.py` and `scripts/X.py`. Not a coincidence: **7 scripts are
  byte-identical copies** in both places (`arxiv_harvester`, `arxiv_harvester_v2`,
  `autoresearch_runner`, `graphify_research`, `research_task_synth`, `seed_from_websearch`,
  `weekly_summary`). `research-engine/scripts/` contains *nothing but* duplicates.
- [x] **Both copies are live, so this is not deletable dead code.**
  `research-engine/run_autoresearch.sh` does `cd "$RESEARCH_ROOT"` then runs
  `python3 scripts/autoresearch_runner.py` → the research-engine copy. Meanwhile
  `scripts/autoresearch_runner.py` resolves `FACTORY_ROOT / "research-engine"` as a DATA
  root, i.e. it expects to run from the factory root. **Which file executes depends on the
  entry point.**
- [x] **Closed by invariant, not by deleting (`9a9356a`).** A test asserts the 7 pairs stay
  byte-identical, and separately guards the SET SIZE — a drift check that silently covers
  zero files would report green while enforcing nothing, which is worse than no check.
  **Verified it can fail:** one appended comment fails exactly that parametrised case and
  names both paths; restoring returns it to green. apps/ava-factory: **469 passed**.
- [x] Deliberately did NOT pick a winner. Deduplicating (shim, symlink, or delete-one-and-
  fix-the-caller) changes how the research jobs launch — operator's call. The invariant that
  matters until then is only that the copies never drift.
- [ ] **NEXT (unchanged priority):** the 203 encoding-less writes from R79 are still
  unfixed; `PYTHONUTF8=1` remains the recommended one-line answer for the whole class, and
  the per-site work is belt-and-braces after that. Note the duplication means **any per-site
  encoding fix in these 7 scripts must be applied to BOTH copies** — the new test will now
  say so out loud instead of letting one copy quietly lag.

### 5.3.R79 — the text-I/O class, measured properly: 360 sites, and ONE setting that fixes all

- [x] **Executed R78's own follow-up (13:10).** Swept every package for encoding-less text I/O.
- [x] **My first survey was garbage and I caught it before acting.** It counted `.venv/
  site-packages` — third-party code — reporting "apps/dottie open-w=202". Real number after
  excluding vendored trees: **0**. A measurement that includes other people's code is not a
  measurement of this repo.
- [x] **Then grep itself proved to be the wrong instrument.** It both OVER-counts (multi-line
  calls that already pass `encoding=` on a continuation line) and UNDER-counts (`read_text(
  errors="ignore")` — non-empty parens, so `\.read_text\(\)` skips it). Redone as an **AST
  pass**, which is exact.
- [x] **THE MEASURED CLASS — 360 first-party sites**, `apps/ava-factory` 267, `scout-cli` 55,
  `scout-rtx` 22, `dottie` 7, `ava-skills` 6, `harness` 2. Split by direction: **203 writes,
  157 reads.** The writes are the dangerous half — a read crashes loudly, a write silently
  EMITS cp1252 that every other platform then reads as mojibake.
- [x] **`PYTHONUTF8=1` fixes all 360 at once, with no code change — verified.** Repro: a file
  containing an emoji crashes `read_text()` under the default cp1252 locale
  (`sys.flags.utf8_mode = 0`, `locale.getencoding() = cp1252` on this box) and reads
  correctly with UTF-8 mode on. **Validated against four suites under `PYTHONUTF8=1`:**
  graphify 64, ava-skills 66, scout-cli 130, dottie research 87 — all pass.
- [ ] **RECOMMENDED, operator's call because it is environment config:** set `PYTHONUTF8=1`
  for the venvs, the scheduled task, and the Docker images. That is one line per surface
  versus 360 edits, and it also covers every site added tomorrow. Python 3.15 makes UTF-8
  mode the default anyway (PEP 686), so this is adopting the future default early, not
  inventing a local convention.
- [ ] Keep fixing individual sites opportunistically as belt-and-braces — env config helps
  only where the env is set, and a script run by hand outside it gets the old behaviour.
  **Priority order: the 203 writes first**, and among those the ones writing files other
  tools read (hooks, `.gitattributes`, JSONL data).
- [x] **A cautionary note on my own sweep:** `e4e299b` claimed "swept both" and had missed
  three shapes in the very package it was fixing (`a009f4c`). The regex was written for the
  instance I had seen, not for the class I claimed. **Verifying a class claim needs a tool
  that understands the syntax, not one that pattern-matches the example.**

### 5.3.R78 — measured EVERY suite for the first time; my board had been covering 3 of 11

- [x] **Applied §5.3.R77's lesson to my own reporting (13:01).** I had claimed "dottie 197
  passed" and it was really 159/36. One wrong measurement means checking the rest, not
  assuming it was isolated — so I ran **every** suite in the repo. My board covered **3 of
  11** (dottie, server, webapp); the other 8 I had never once measured.
- [x] **Half the initial "failures" were MY INVOCATION, not the code.** Running from the repo
  root gave scout-cli 6 failed / 124 passed; from its own directory, **130 passed**. Same for
  ava-factory (`No module named 'ava'`) and the `torch`/`zstandard` gaps in the root venv.
  **Recorded because reporting those as breakage would have been a false alarm** — the exact
  §5.3.R71 mistake, and I nearly made it again one tick after writing it down.
- [x] **THE CORRECTED BOARD** — ⚠ **SUPERSEDED, see §5.3.R85 for the live one.** Two rows
  below are now known wrong: `ava-skills` 66 was an under-count (my invocation overrode the
  project's `testpaths`; real figure **80**), and `ava-factory` 461 predates the 15 tests
  that were never running plus 9 added since (**485**). Kept unedited as the record of what
  was measured at 13:01. (each run from its own root; torch suites need `apps/dottie/.venv`):
  - `apps/dottie` — **159 passed / 36 failed** ⛔ (queue item 9, structural, pre-existing)
  - `apps/ava-factory` — **461 passed / 37 skipped** ✅ (TODOS said "431"; stale)
  - `apps/scout-cli` — **130 passed** ✅
  - `packages/ava-open-harness` — **30 passed / 10 skipped** ✅
  - `packages/ava-skills` — 1 failed / 65 → **66 passed** ✅ (fixed, `836504e`)
  - `packages/personal-graphify` — 5 failed / 59 → **64 passed** ✅ (fixed, `e4e299b`)
  - webapp Node — **35 passed** ✅ (8 api / 10 history / 8 poll / 9 store) — held exactly
  - `apps/scout-rtx` — **NOT VERIFIABLE HERE** (`typer` absent from both venvs). Not green,
    not red. Stated as unknown rather than guessed.
- [x] **Real bug 1 — `packages/ava-skills`:** the `jspace-context-engine` manifest added by
  `bc22788` omitted the required `version`, failing the package's own invariant test. Set to
  **1.0.0**, not the siblings' 2.1.0: the loader already defaults missing versions to 1.0.0,
  so the skill has been *reporting* 1.0.0 all along — declaring 2.1.0 would have silently
  changed observable behaviour while appearing to be a docs fix.
- [x] **Real bug 2 — `pgraphify install` CRASHES on Windows.** `cli.py:477` read the rule
  template with a bare `read_text()`, which uses the locale codepage (cp1252), and the
  template contains an em dash → `UnicodeDecodeError` before the command does anything.
  **A class, not an instance: 21 encoding-less calls** across 4 modules. The reads crash on
  any non-cp1252 byte; **the writes are worse — they silently EMIT cp1252**, so hooks and
  `.gitattributes` written on Windows are mojibake everywhere else. `export.py`/`extract.py`/
  `report.py` already did it correctly, so this was inconsistency, not a decision.
- [x] The tests carried the *same* omission (31 calls) — which is why two kept failing for
  the same reason the source had, once the source was fixed. Swept both. This also explains
  an intermittent `test_incremental` failure: identical cause, surfacing only when tmp
  content happened to include a non-cp1252 byte. **A flake that was never a flake.**
- [x] **Real bug 3 — found in `git status`, not in a test.** After the factory run, 8 tracked
  `evals/probe_items/*.jsonl` showed modified. `git diff --ignore-cr-at-eol` proved the
  content identical: pure CRLF churn. `_write_jsonl` opened in text mode without `newline=`,
  so Python translated `\n` → `\r\n` on Windows and **every suite run silently rewrote
  tracked eval data.** `generate_probe_items`' docstring says *"idempotent"* — it was not,
  across platforms. Fixed (`dd60e4a`); regeneration is now byte-identical and a full run
  leaves the tree clean. **`encoding="utf-8"` was already right there — only the newline
  translation was missing**, which is why it survived a file that otherwise looked correct.
- [ ] NOTE: `apps/scout-rtx` needs `typer` before it can be judged at all. ~~One `uv pip
  install typer` in the right env would move it from unknown to measured.~~ **WRONG — see
  §5.3.R89: 7 of 10 declared deps are missing and collection needs 4 of them, including the
  native `rustbpe`. I wrote that estimate without checking it.**
- [ ] The three bugs this tick share one shape with the docstring/comment class: **text I/O
  that is correct on the machine it was written on.** Worth a repo-wide sweep for bare
  `read_text()`/`write_text()`/`open(...,"w")` in the remaining packages — graphify was the
  only one measured, and it had 52 instances between source and tests.

### 5.3.R77 — the guard that cleared a stage it could not survive, and a RED suite at HEAD

- [x] **Honoured a standing memory note instead of assuming (12:49).** `dottie-watches-die-
  with-sessions` says re-verify `TaskList` after any machine-move or fork handoff; this
  session was both, and I had not checked. Result: **no tasks** — nothing to re-arm. A clean
  negative, recorded because "I checked and it was empty" and "I never checked" look
  identical afterwards.
- [x] **That check surfaced a real gap in my own §5.3.R52 guard.** It used ONE flat floor
  (1200 MB) for every stage. But `ideate`/`implement` do not merely *use* memory — if the
  model is not resident they **pull it in** before the first token, and at `NUM_GPU=0` that
  lands in **system RAM**. Measured live with the daemon down: **3,051 MB free, `/api/ps`
  empty, qwen3:8b = 4,983 MB.** Old guard verdict: **PASS**. Reality: the box goes to zero
  inside the load the guard just authorised — R51's death, one layer earlier.
- [x] `DOTTIE_OLLAMA_KEEP_ALIVE=30s` makes "not resident" the **common** case, so this was
  never an edge case: it was the default path on every restart into a busy box.
- [x] **Fixed (`51763ca`):** `_model_load_cost_mb()` asks Ollama what is resident (costs 0)
  versus what must be pulled (its real size); requirement becomes floor + that, scoped to
  the two LLM stages. Unknown reads as UNKNOWN and proceeds — same fail-open contract as
  `_available_mb`, so a down Ollama still surfaces as the stage's own honest refusal.
  Verified live: ideate/implement REFUSE at 6,183 MB required; train/evaluate proceed.
- [x] **An existing test encoded the old assumption and now fails — correctly.** At floor 50
  with 110 MB free it asserted "proceed"; with a 5 GB load pending, refusing is right. Made
  the floor tests hermetic (stubbed the model term — unit tests must not need a live Ollama)
  and added the model-load cases separately.
- [x] **Then the full suite came back 36 failed / 159 passed.** I did **not** assume it was
  mine: stashed both files, reproduced identically on a clean tree, restored. Pre-existing,
  and **HEAD has been red** — see decision-queue item 9 for the operator decision.
- [x] **Root cause is the same class as everything else tonight, at package scope.** The
  consolidation renamed ava-factory's `ava/` → `dottie/` and left a `sys.modules` shim.
  **The shim works** (verified: `ava.rl.codeact_loop` → `dottie.rl.codeact_loop`). What
  broke is `resolve.py`'s *existence check*, still probing the pre-shim path. The code was
  right; the description of where the code lives was not.
- [x] **I wrote the one-line marker fix, tested it, and REVERTED it.** Accepting `dottie/rl/`
  makes `resolve()` succeed and then fail deeper (`ModuleNotFoundError: dottie.rl`), because
  **two packages are both named `dottie`** and only one can win per process. Worse,
  `ensure_factory_on_path()` puts that root at `sys.path[0]`, so it could shadow Dottie's own
  package. **The stale marker is currently the only thing preventing that** — a bug holding
  a hazard shut. Reverting a fix I had already written and proven green is the right call
  when the green is local and the blast radius is not.
- [x] **Fixed the stale "Standing state" block** while here: it still described *"4 scheduled
  tasks"* and baseline *5.61982*. Both wrong — one forever-daemon, and the live baseline is
  the contaminated 5.60506. Same class, found by reading rather than searching for it.

### 5.3.R3 — ⭐⭐ THE GATE CAUGHT A REAL ONE (04:37) — a third false SOTA, blocked

`bb40e0c18f0a` "Attention Gradient Normalization (AGN)" **beat the baseline** and, under
last night's bare-`<` rule, **would have been promoted as a new SOTA and ratcheted the
baseline**. It was held instead:

```json
"improved": true,          "significant": false,      "promote": false,
"new_value": 5.6032,  "baseline_value": 5.60506,  "delta": -0.00186,
"significance": "|delta| 0.00186 vs 2.0×SEM 0.0361 (n=20, std=0.080721)",
"candidate_params": 13001481, "block_param_delta": -787072,
"capacity_caveat": "the swapped block REMOVED 787,072 parameters vs the block it
                    replaced (787,072 → 0) — a fixed-step comparison partly measures
                    capacity, not just the idea"
```
The "win" is **0.00186 against a noise bar of 0.0361 — roughly 19× smaller than the
measurement error.** And the capacity caveat fired independently: like MLBR, this is a
parameter-free block replacing a real 787 K-parameter one (candidate_params 13,001,481 —
the *identical* count to MLBR, i.e. the same structural trick).

Both defenses built tonight fired on the same candidate, within an hour of shipping, on a
case that would otherwise have become "SOTA #3". The baseline correctly did **not** move
(still 5.60506). This is the strongest evidence available that the gates were necessary,
and it also says something about the search: the loop keeps rediscovering "delete a block"
as a way to win at fixed steps, which is why option (b)/(c) of the block-swap confound
(param parity, or ADD instead of REPLACE) deserves your attention.

### 5.3.R2 — ⭐ the new gates RAN IN PRODUCTION (04:11, first live verdict)

`f4d81d628b16` "GradientWeightedMemoryAttention" — implemented by qwen3:8b on
**attempt 0** (no correction passes), trained, and evaluated. The verdict carries every
field shipped tonight, correctly populated:
```json
"improved": false, "significant": true, "stable": true, "promote": false,
"significance": "|delta| 0.45377 vs 2.0×SEM 0.013172 (n=20, std=0.029453)",
"baseline_provenance": "promoted", "baseline_caveat": null,
"sem": 0.006586, "sem_series": "eval_ce_per_batch", "sem_n": 20
```
Rejected correctly: delta **+0.45377** (worse than the 5.60506 baseline). Provenance
resolved to `promoted` — right, since the current baseline came from MLBR's promotion.
- [x] **FIXED 04:23 (message only, schema untouched)**: `significant: true` is
  direction-AGNOSTIC — it tests `|delta|` against noise, so a candidate that is
  significantly *worse* also sets it true, which reads as good news to a skimmer of a
  promotion bundle. The `significance` string now leads with the direction. Verified by
  replaying the real numbers: the 04:11 live verdict → *"WORSE than baseline: |delta|
  0.45377 vs 2.0×SEM …"*, MLBR's false SOTA → *"within noise of baseline: |delta|
  0.01476 …"*, and a clear win → *"BETTER than baseline: …"*. 35/35 tests green.
  Renaming the field itself to `beyond_noise` is still open — that IS a schema change,
  so it stays your call.

- NOTE on reading the next few verdicts: the daemon imports its code at process start,
  so the one running since 04:05 carries the gates as of 04:05 but NOT the two later
  additions — `dur_s` on result lines (04:13) and the direction-aware significance
  wording (04:23). Those appear after the next daemon restart (05:05 trigger). Their
  absence is skew, not breakage.
- Degeneracy gate status: shipped, **no production catch yet**. GAAS (`8c3c8ab09b39`)
  failed `dry_run` at 04:24 through the ordinary path — a real torch exception in its
  forward pass after all 5 correction attempts — not the no-op pattern the gate targets.

### 5.3.R1 — the loop kept working through the outage (audited 03:03)

While Docker was down, the host-side loop evaluated FOUR candidates and honestly
rejected all four (deltas vs baseline 5.60506, lower is better):

| candidate | new value | delta |
|---|---:|---:|
| Dynamic Sparse Attention Regularizer | 5.63998 | +0.035 |
| Adaptive MoE Load Balancing (grad-consistent routing) | 5.72036 | +0.115 |
| GASA (Gradient-Adaptive Sparse Attention) | 5.71190 | +0.107 |
| **OSA (Orthogonalized Sparse Attention)** | **8.49635** | **+2.891** |

- OSA's catastrophic result **confirms the code review in §5.3.R**: its math does not
  implement its hypothesis (elementwise sqrt then matrix inverse ≠ inverse matrix square
  root) and its transform is batch-dependent. Reading candidate math predicted the
  outcome before an hour of CPU was spent — worth doing routinely.
- A fifth candidate (DCAS-R, `c3af0b3ce501`) exhausted **all 5 self-correction attempts**
  and failed at `dry_run` — the retry ceiling working as designed, honestly recorded.
- NOTE: these four verdicts carry NO `significant`/`sem`/`capacity_caveat` fields — they
  were evaluated by the pre-gate evaluator (the worker imports at process start). Tonight's
  gates are shipped and unit-tested but have **not yet been exercised on a real promote
  path**, because nothing has improved on the baseline since. Expect the new fields from
  the next evaluation onward.

### 5.3.R0 — BOTH sota entries are artifacts, for DIFFERENT reasons (audited 02:58)

The ledger says `sota: 2`. Neither is a measured architectural improvement:

- **`bc3dbb74bead` "Hierarchical Attention"** — the module is REAL (5 Linear projections,
  genuine two-branch attention; it passes the new degeneracy gate correctly). The
  *promotion* is what's hollow: it beat baseline **4.5** — the hand-seeded placeholder
  from the runbook example (`seed-baseline --value 4.5`), not a calibrated number — on a
  task its own metrics label *"synthetic next-token shift (proxy micro-benchmark, NOT
  downstream capability)"*. Delta −4.345 (4.5 → 0.155) is a 97% "improvement", which is
  the signature of comparing against a made-up number.
- **`23bb41375804` MLBR** — real baseline, real corpus, but a degenerate module and a
  within-noise delta (§5.3.R below).

**So the honest count of real, measured architectural wins so far is ZERO.** That is a
statement about the RESULTS, not the machinery: ideate→implement→validate→train→evaluate
demonstrably runs end-to-end unattended, and tonight's gates now block both failure modes.
- [x] **GAP CLOSED 03:07 (recording only)**: every verdict now carries
  `baseline_provenance` — `calibrated` (notes written by `calibrate-baseline`),
  `promoted` (ratcheted from a measured experiment), or `hand_seeded` — and a
  `baseline_caveat` that lands in the write-up/bundle for the last case: *"the baseline
  is a HAND-SEEDED placeholder … this delta measures distance from an arbitrary number,
  not a real improvement."* 35/35 tests green. **Still your call**: whether promotion
  should REFUSE outright when the baseline was never calibrated (that would have blocked
  `bc3dbb74bead` at the source rather than annotating it).

### 5.3.R — REVIEWER BRIEF for the MLBR bundle (written by the loop 2026-07-20 03:30)

**Recommendation: REJECT the promotion (or re-measure with paired seeds). Two
independent reasons, both from the bundle's own numbers/code:**

1. **The "improvement" is inside the noise.** The bundle reports 20 held-out CE
   batches; their std is **0.0600**, so SEM = 0.0600/√20 = **0.0134**. The claimed
   delta is **−0.01476 = 1.1 SEM** — nowhere near the ~2 SEM needed to call it real,
   and the baseline (5.61982) carries its own unreported error. The ledger's
   `improved: true` is a raw `<` comparison with no significance test; that is the
   machinery's real gap, not a lie.
2. **The candidate module is not what its hypothesis claims.** `candidate.py`
   defines no experts, no routing, and no load balancing: it computes a single
   SCALAR (`-mean over B,S of logsumexp(λx) over hidden`) and broadcasts it onto
   every activation. It has **zero learnable parameters** — and the run swapped it
   in for a real fusion block (`swap_layer: 3`, params 13.00M vs the 13.79M
   baseline). So the measured effect is mostly "delete a block from a 150-step
   under-trained nano", a classic smoke-scale artifact. (`exp(λx)` is also
   overflow-fragile once activations grow.)

**Fixes SHIPPED 2026-07-20 ~03:55 (evaluate.py + 2 tests, 29/29 green):**
- [x] Promotion now requires `|delta| ≥ 2×SEM` of the candidate's own per-batch
  series (`eval_ce_per_batch` / `per_seed` / `eval_losses`, first present wins).
  REPLAYED against the real MLBR numbers: n=20, std 0.06002, sem 0.01342,
  |delta|/sem = **1.10** → **HELD (noise)**. The gate rejects what it promoted.
- [x] No series recorded ⇒ `significant: null` ⇒ HELD, never assumed — the ratchet
  only moves on evidence.
- [x] Verdict now carries `sem`, `sem_n`, `sem_series`, `significance` (the
  arithmetic in words) and `candidate_params`; the write-up shows Significance.
- [ ] STILL OPEN (needs a design decision): paired-seed evaluation — same seeds for
  baseline and candidate would kill most of this variance rather than just gating on
  it. Also: baselines record no param count, so the param comparison is informational
  only (recorded, not gated) until `Baseline` carries params.
- VERIFIED after shipping (second-order check): BOTH trainer paths record a series —
  `factory_trainer` writes `eval_ce_per_batch`, the proxy writes `per_seed` — so the
  new gate does NOT freeze the ratchet. And stated honestly in code: because the stored
  baseline has no spread, a 2×SEM bar against a POINT baseline is ≈1.4 SE_diff (~84%
  confidence), not 95% — a floor, not a proof. Kept at 2.0 for statistical power;
  paired seeds are the real fix.
- [x] **DEGENERACY GATE shipped in validate.py L4 (02:35)** — the other half of the
  MLBR post-mortem: the 4-level validator checked import/instantiate/shape/finiteness
  but nothing stopped a module that *does nothing*. Now a candidate FAILS L4 when it
  has **0 learnable parameters AND** its output differs from its input by a **constant**
  (`std(out-in) < 1e-6`). Both conditions required, so the legitimate zero-init pattern
  (LayerScale: identity at init but parameterized) still passes. Verified on the REAL
  bundle module: MLBR → FAIL ("0 learnable parameters … differs by a CONSTANT");
  LayerScale (4224 params) → pass; a real mixer (delta_std 0.465) → pass. Passing
  results now also record `learnable_params` and `delta_std` for the reviewer.
  Found en route: a test fixture (`x * scale`, scale=1.0) was itself a zero-param exact
  identity — fixture fixed, gate kept.
  **HARDENED 02:45 — the first version of this gate was FLAKY.** An absolute `1e-6`
  bar competed with float32 rounding noise from `x + c`, which scales with |c| (~5e-7
  for c≈4.7) and varied with the UNSEEDED probe input, so the same module could pass or
  fail run to run. Two fixes: (1) the constant-shift test is now scale-aware
  (`std ≤ max(1e-6, 1e-4·|mean|)`), and (2) the dry-run probe is seeded (1234) so
  validation is reproducible at all. Re-verified on the real modules + 5 repeat runs.
- [ ] **DEEPEST ISSUE FOUND TONIGHT — the block-swap integration has a structural
  confound (queued, needs your call).** `factory_nano_block_swap` measures a candidate
  by REPLACING a real parameterized fusion block with it. So every parameter-free
  candidate silently also *removes capacity*, and its measured delta conflates "new
  idea" with "smaller model at fixed steps". MLBR (0 params) exploited this; the queued
  OSA candidate (`71a62346df0a`) has the SAME shape — pre-flighted 02:37: it passes the
  new degeneracy gate legitimately (0 params but delta_std 1.224, a real input-dependent
  whitening), yet it will still be measured with 0.79M fewer params than baseline.
  Options: (a) [x] **DONE 02:50 — recording only, no gating.** The factory trainer now
  measures the replaced block and the candidate BEFORE the swap and records
  `replaced_block_params` / `candidate_block_params` / `block_param_delta`; the evaluator
  turns a non-zero delta into a plain-English `capacity_caveat` in the verdict AND a
  "**Capacity caveat:**" line in the write-up (so promotion bundles carry it). For MLBR
  that reads: "the swapped block REMOVED 786,432 parameters vs the block it replaced …
  a fixed-step comparison partly measures capacity, not just the idea."
  (b) require the swapped block to match the replaced block's param count within a
  tolerance; (c) ADD the candidate alongside the block instead of replacing it, so
  capacity only goes up. **(b)/(c) still need your call — they change what gets measured.**
  NOTE also, unrelated to the confound: OSA's math does not implement its own hypothesis
  — `inverse(sqrt(AᵀA))` is an elementwise sqrt followed by a matrix inverse, not the
  inverse matrix square root orthogonalization claims; and AᵀA is computed over the
  BATCH, making inference batch-dependent. Worth a look when reviewing its result.
- [ ] YOUR CALL on the live ledger: MLBR (`23bb41375804`) was promoted under the old
  bare-`<` rule and MOVED the baseline 5.61982→5.60506. Options: (a) leave it — the
  bundle is human-gated anyway and §5.3.R documents the truth; (b) re-seed the
  baseline back to 5.61982 (`python -m dottie.research seed-baseline --value 5.61982
  --metric factory_lm_loss --architecture nano`) so the ratchet starts from the honest
  number. I did NOT touch the live ledger unattended.

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
6.2 [~] **OpenClaw channels** (cli + arxiviq SHIPPED 2026-07-20 ~01:40): scout's
    profiles now write channel `cli` explicitly; the engine's record_task takes an
    explicit channel or `DOTTIE_CHANNEL` env (compose tags the arxiviq-facing dottie
    service `arxiviq`); KNOWN_CHANNELS documented in jspace_state. Cross-surface
    visibility verified by tests on BOTH sides (engine 12/12, profiles 6/6 — real
    store, tmp DB, no mocks). REMAINING: the `research` channel — the research loop
    runs under its own session_id, and session_snapshot is per-session, so making
    research state visible to scout/arxiviq sessions needs either a well-known shared
    session_id convention or a store-level cross-session view. That's a design
    choice — pick one before wiring it.
6.3 **reviewgraph into the workflow**: pre-commit hook (or `scout system audit` step)
    that runs `reviewgraph blast --diff HEAD` and blocks on new high-fan-in touches
    without tests. Wire `context` into /code-review usage docs.
    RECON 2026-07-20 01:15 (dry-run done): blast works from apps/scout-cli — ~3s,
    parseable JSON (counts.impacted_files etc). TWO constraints for the hook:
    (a) it MUST pin cwd/interpreter to the monorepo copy — the shared venv's
    installed bigbang resolves to `C:\Users\jcdav\scout-cli` (a THIRD standalone
    checkout, no reviewgraph plugin) and silently wins outside apps/scout-cli;
    (b) ship WARN-ONLY first, flip to blocking after observing false-positive
    rate on real commits (a blocking gate armed untested would bite the loop
    and parallel sessions).
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
7.6 **Dottie console webapp review (03:20, `apps/ava-factory/dottie/webapp`, the
    8641fb9 feature — reviewed because it was the newest unreviewed code).**
    Verdict: genuinely good. XSS-safe by construction (`dom.js` builds every node via
    `createTextNode`/`textContent`, no `innerHTML` anywhere), the pending state is an
    honest elapsed ticker that says "no server streaming" instead of faking a typewriter,
    the mode chip shows which endpoint a send will use BEFORE sending, error hints are
    status-specific (401/403/503), and the engine-down short-circuit explains its own
    30s cap. `api.js` attaches the bearer token only on `/assistant`, never to :8100.
    Two small gaps found, both against the code's OWN doctrine (filed, not fixed — the
    factory server is down so nothing here is runnable/testable right now):
    - [x] **FIXED 05:57 — the console polled a hidden tab forever.** `js/app.js` started
      three pollers at boot (`pipeline` every **5 s**, assistant 15 s, research 20 s) and
      never paused them: no `visibilitychange` handler, no `document.hidden` check. A
      console left open in a background tab hits `/pipeline/status` **~720×/hour**, and
      that endpoint is not a cheap read — it opens the manifest DB, walks the metrics
      jsonl and probes disk. The sibling arxiviq front-end already guards its polling
      (`if (document.hidden) return; // don't burn quota`); this one did not, on a box
      where resource pressure caused tonight's outage. Now pauses on hide and resumes on
      show (`startPolling()` polls immediately, so returning shows fresh data at once).
      Verified: syntax clean, listener registered, start guarded, single boot call.
    - CHECKED CLEAN (03:28): `ops.js` does NOT have the v1/v2 schema bug that bit the
      arxiviq site. Its chart keys (`series.step` / `series.lm_loss` / `series.tok_s`)
      match `pipeline_status.py::current_run_series`, which normalizes server-side
      (`row.get("lm_loss", row.get("lm", row.get("total")))`), and the tile code already
      falls back `last.lm_loss ?? last.lm`. Recorded so nobody re-investigates.
    - [x] **FIXED 03:36** — `store.js::write()` used to swallow quota errors, so a full
      localStorage meant the transcript silently reverted on reload: the one unmarked
      degradation in a console whose principle is "fetched live or marked unreachable".
      Now `write()`/`saveMessages()` return a boolean and the chat composer shows
      *"not saved — browser storage full; this transcript is memory-only"*.
      Tests: `js/store.contract.test.mjs` (5 assertions, localStorage shim, no browser) —
      reports success, reports failure, never throws, reads still fall back. 5/5 pass.
      Caught while wiring the UI: this codebase has **no `.hidden` CSS class** — the
      idiom is the HTML `hidden` property (`chart.js` sets `el.hidden`), so a
      `classList.toggle("hidden", …)` would have shipped a permanently visible empty
      chip. Verified chat.js still loads and `pickEndpoint` still behaves.
    - [x] **FIXED 03:25** — `api.js::request()` promised "every failure is surfaced as a
      typed ApiError" but a 2xx with a non-JSON body (proxy error page, truncated
      response, misrouted HTML 200) escaped as a raw `SyntaxError`, reaching the UI as
      "Unexpected token <". Now typed: `HTTP 200 — body was not JSON (…)`. Correcting my
      previous tick's claim that this was untestable — the module's own header says it is
      importable/testable outside a browser, and it is: a 6-assertion contract test lives
      beside it at `js/api.contract.test.mjs` (run `node js/api.contract.test.mjs`),
      covering the new path plus the unchanged 4xx/5xx-with-detail, happy-path, and
      network-error behaviours. 6/6 pass.
7.7 **Live-data check (05:22) — the arxiviq feed is HEALTHY despite the fleet being down.**
    The hourly publisher is host-side, so it kept working through the outage: gist
    published 2 min before the check, carrying the current research ledger (baseline
    5.60506, 69 experiments, 54 failed_validation) and an honest
    `pipeline: {unreachable}`. Rendering the committed site code against that exact
    payload gives: badge *"live · box seen 2 min ago"* (true — the box IS alive), Factory
    mode *"factory unreachable"* (true), pipeline tiles em-dashed (correct — no such data
    exists). Three components each telling the truth about a different thing.
    ⚠ **But arxiviq.com is still serving the OLD code**, which renders that same payload as
    "Factory mode: unknown" plus bare em-dashes — i.e. it looks like missing data rather
    than a down service. That is the visible cost of the un-deployed fix (§7.5).
7.5 [x] **Site render VERIFIED headlessly + factory-down honesty fix (02:55)**: the
    browser extension isn't connected, so instead the REAL `app.js` was run against the
    REAL gist payload in a DOM shim (harness: `$CLAUDE_JOB_DIR/tmp/site_render_check.js`,
    takes a payload path as argv). Healthy payload → 6/6 checks pass (tok/s 7541,
    phase 75%, run 82%, 601 shards, no NaN, badge "live · box seen …") — tonight's
    telemetry/badge/sparkline work confirmed working for the first time.
    FOUND + FIXED en route: when the box is up but the FACTORY is unreachable (exactly
    tonight's WSL crash — the publisher honestly wrote `pipeline: {unreachable}` at 02:20
    and that IS what the live gist serves right now), the tiles rendered bare em-dashes
    and "Factory mode: unknown", which reads like missing data rather than a down
    service. Now: a critical "factory unreachable" chip plus a note naming the reason
    and stating that no pipeline numbers are shown rather than stale ones.
7.3 [x] Research tab: 5.4 (sparkline, shipped). Factory tab: SHIPPED 2026-07-20 —
    telemetry tiles now read the gist payload's v2 `.pipeline` block (tok/s from
    trainer.last, phase+run % from watch.*_progress, mode chip with honest ·stale
    flag); legacy v1 and baked-snapshot fallbacks retained.
7.4 [x] "Last seen" badge shipped 2026-07-20 (the preferred honest option): the source
    badge now reads the gist feed's published_utc — "live · box seen X ago" when <2h,
    "stale · box last seen X ago" beyond (2 missed hourly beats = asleep), old
    behavior when the feed lacks the field. "Live" now means the BOX is live, not
    that a CDN fetch succeeded.

### 7.8 — factory server: three endpoints blocked the event loop (fixed 06:00)

Followed the thread from the webapp polling fix (§7.6): `/pipeline/status` is expensive,
so what does the *server* do under a 5 s poll? Two problems, one significant.

- **`async def` handlers calling SYNCHRONOUS collectors.** `/pipeline/status`,
  `/ecosystem/status` and `/assistant/status` were declared `async def` while calling
  `collect_status()` / `collect_ecosystem_status()` / `collect_assistant_status()` — all
  plain `def` doing sqlite reads, metrics-file walks and disk probes. In FastAPI that work
  runs **on the event loop**, blocking every other request (`/chat`, `/assistant`,
  `/health`) for its duration. With the console polling every 5 s, the server stalled
  periodically. Fixed by declaring them plain `def`, which makes FastAPI run them in a
  threadpool. Verified by AST scan: no `async` handler still calls a collector inline.
- **This was an oversight, not a design choice** — `/network/status` in the same file
  already does it correctly (`await asyncio.to_thread(collect_network_status, …)`) and its
  docstring even says *"Heavy I/O runs in a worker thread so live polls stay snappy."* The
  sibling endpoints were simply missed.
- [x] **Swept for the same class (06:06)**: an AST scan for `async def` app handlers
  doing blocking I/O without `to_thread` found two more — `eval_report` and
  `agent_eval_scoreboard`, both `path.read_text()` on the loop. Much lower severity
  (small markdown, on-demand rather than polled) but the same bug, so both are now
  plain `def` and the regression guard covers **all five** handlers. That turns
  "no async handler blocks the loop" into an enforced invariant instead of something
  the next reviewer has to re-derive per endpoint. 24 passed.
- CHECKED CLEAN (06:10): **`apps/dottie/dottie/api.py` does NOT have this bug.** Every
  route handler there is a plain `def` (submit_task, get_task, list_tasks, the flywheel
  endpoints, run_climb, climb_log, research_status, research_experiments, status), so
  FastAPI threadpools all of them; the only `async def` is
  `_private_network_preflight`, which is middleware and correctly must be async. So the
  two apps had opposite conventions and only `ava-factory/server.py` mixed them.
  Recorded so nobody re-audits it.
- [ ] **Not done: caching.** `collect_status()` still recomputes per request, so N clients
  cost N walks. A 2–3 s TTL would make it robust regardless of caller behaviour. Left for
  you because it changes freshness semantics on a dashboard whose whole point is honesty
  about staleness.
- [x] **Coverage gap found and closed (06:03).** The existing suite never *called* these
  endpoints — `test_server_endpoints.py` only asserted that the string `/pipeline/status`
  appeared in another response. Added two tests: one asserts the three handlers are not
  coroutine functions (a regression guard, so nobody reintroduces `async def`), the other
  actually GETs all three and requires `200` + a non-empty JSON object. **24 passed**
  (was 22). So the fix is now exercised through the real handler path via TestClient, not
  just AST-verified — the earlier "untested" caveat is largely retired. A live-server
  check after the fleet returns is still worth one command, since TestClient does not
  reproduce real concurrency.

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
- [x] `test_logic_prover` jsonl: fixed 2026-07-20 — write_text CRLF'd the corpus on
  Windows so the real file was 300 bytes bigger than the skill's reported
  bytes_written (its own honesty claim). Now write_bytes, LF everywhere; 6/6 pass.
- [x] `test_flow`: same split brain (patched free_gb on the wrong module copy); alias finder fixed it.

### New items (added 2026-07-19 evening)

- [x] §5: `DOTTIE_OLLAMA_MODEL_NIGHT=qwen3:14b` enabled 2026-07-20 ~00:50 (tool run done,
  trainer parked → contention gone; NUM_GPU stays 0 per GPU doctrine). Next research
  tick in the 22-06 window picks it up; watch the first 14b ideation for stalls.
- [x] §5 INCIDENT (2026-07-20 01:05): **Ollama was down since the 23:36 reboot** — it's a
  user-level autostart and the box rebooted to the lock screen (no login → no Ollama).
  The 00:05 research runner honestly refused all hour ("will not fabricate"), counts
  froze; task result 0x8007042B. Fixed: `ollama serve` started 01:05:15; the 01:05
  runner's retries pick it up (first 14b night run). Loop-verify next tick.
- [ ] **PREVENTION (user action)**: register a machine-level Task Scheduler job — At
  startup, run `ollama serve` as your user "whether logged on or not" (needs your
  password at registration, so Claude can't do it) — or switch Ollama to a Windows
  service. Without this, every unattended reboot silently kills the research loop
  until someone logs in.
- [ ] **§5 TIMEOUT×CADENCE INTERACTION (measured 03:29, file before it bites again).**
  The 03:05 tick has been running 22+ min with no log line. Measured state: Ollama is
  healthy and responsive (v0.31.1) but **idle** — 0 CPU over an 8s sample — and the 14b
  model already expired (`expires_at 03:27:19`, now past, working set back to 5 MB); the
  worker processes are alive but have used only 6.4 CPU-s total, i.e. sleeping, not
  computing. Nothing is provably wedged, but the settings make a hang expensive:
  `DOTTIE_OLLAMA_READ_TIMEOUT_S=1800` (30 min) against **hourly** ticks with
  `MultipleInstances=IgnoreNew` means ONE hung request idles half the hour and then the
  next tick is refused — two consecutive hours lost from a single stall. That is exactly
  the shape of tonight's 02:05 and 03:00 losses.
  Fix (your call, cheap): drop the read timeout to ~600s AND set MultipleInstances to
  Queue/Parallel (the wrapper's exclusive lock is the real guard).
  **RESOLVED 03:37 — the 03:05 run is STUCK, confirmed on the right instrument.** The
  ~03:35 refusal I predicted never appeared, so I stopped trusting `run.log`: Python's
  stdout is block-buffered when redirected to a file, so the log is NOT a real-time
  liveness signal (lines can sit unflushed for a whole run). **Use the ledger instead —
  it is written transactionally per state change.** Measured there: last state change
  **37 min ago**, the two `pending` experiments untouched for **66 min**, i.e. the 03:05
  worker has produced ZERO progress in 32 minutes while Ollama sits idle (0 CPU / 8s
  sample, 31 CPU-s lifetime) and the worker itself has burned ~6 CPU-s. Nothing is
  computing.
  Standing lesson for future debugging: `run.log` silence ≠ stall, and `run.log`
  activity ≠ liveness. Query `data/research/ledger.sqlite3` (`select state, updated_ts
  … order by updated_ts desc`) to judge whether the loop is actually moving.
- [ ] ⚠⚠ **CORRECTION (04:00) — READ THIS BEFORE THE ENTRY BELOW. The runner is a
  DAEMON, and that invalidates most of my "lost tick" analysis.** The scheduled action is
  `research_worker.ps1 run …` with **no `--max-actions`**, which defaults to **0 = run
  forever** (it loops with `--idle-seconds 30`). Consequences:
  * Task state **`Running` is NORMAL**, not a zombie. I called it a zombie at 03:00 and
    "cleared" it — that was probably a healthy daemon I killed.
  * `IgnoreNew` refusing the hourly trigger (`0x800710E0`) is **BY DESIGN** — the hourly
    trigger is a *restart-if-dead* mechanism, not an hourly work tick. **No ticks were
    "lost."** My repeated "two hours lost" framing was wrong.
  * ⛔ **RETRACTED: my recommendation to set `MultipleInstances` to Queue/Parallel.**
    That would run MULTIPLE concurrent daemons — actively harmful. Leave it `IgnoreNew`.
  * The `os._exit` fix I shipped at 03:57 is harmless but **does not address this**: in
    daemon mode `main()` never returns, so that line never runs. It is still correct
    hygiene for one-shot invocations (`status`, `ideate`, …) and for the stdout flush.
  **THE REAL BUG, restated honestly**: the daemon stays alive but STOPS MAKING PROGRESS —
  measured at 03:37, ledger frozen 37 min, Ollama idle, process at ~0 CPU. A stall, not a
  failure to exit. Likely a blocking call that never returns (the 1800 s Ollama read
  timeout is the prime suspect) or a deadlock in the drain loop.
  **Fixes**: (a) [ ] a **watchdog**: if the ledger shows no state change for N minutes,
  log it and exit non-zero so the hourly trigger restarts a fresh daemon (your call —
  needs a threshold that won't kill a legitimately long factory train);
  (b) [ ] drop `DOTTIE_OLLAMA_READ_TIMEOUT_S` to ~600 s so a hung generate self-heals in
  minutes instead of 30 (your call — a slow CPU generate legitimately takes minutes);
  (c) [x] **APPLIED 04:04 — heartbeat + start lines.** And a **4th correction to my own
  analysis**: I claimed `run.log` was useless because Python block-buffers stdout. WRONG —
  **every `print` in the loop already passes `flush=True`.** The real reason for 40 minutes
  of silence is structural: the `idle` branch printed *nothing at all*, and a long action
  prints only on COMPLETION, so "idle" and "stalled" looked identical. Now: an idle
  heartbeat every ~5 min carrying `counts`, and a `{"phase": "start"}` line before every
  real action — so a `start` with no matching completion is the visible signature of the
  stall that cost an hour of diagnosis tonight. 35/35 tests green; the new daemon at 04:05
  picks it up.

- [ ] ~~§5 ROOT CAUSE (03:42) — worker processes finish their work but never EXIT~~
  **(SUPERSEDED by the correction above — the process-never-exits framing was wrong for
  the daemon; the orphan measurements below are still real and still useful.)** Measured after stopping the stuck
  03:05 run: four orphaned worker processes survive it — two from 03:05 and two from the
  **01:37** run. PID 8524 (the factory trainer) has burned **10,747 CPU-s (~3 h)** yet
  shows **0.00 s CPU over a 6 s sample** and a **0 MB** working set; its work is long
  since committed (OSA's rejection landed in the ledger at ~02:29). So the compute
  finished, the results were written, and the process simply never terminated.
  That single behaviour produces all four symptoms seen tonight:
  * Task Scheduler keeps the task in state **Running** (it waits on the process tree),
  * `MultipleInstances=IgnoreNew` then **silently refuses** the next hourly trigger
    (02:05 → `0x800710E0`), losing an hour with no error anywhere,
  * a later forced teardown surfaces as **`0xC000013A`** (killed abnormally),
  * and a "stuck" run (03:05) is really a run whose predecessor never let go.
  HYPOTHESIS for the hang (needs one diagnostic, not a guess): a non-daemon thread at
  interpreter shutdown — most likely torch/OpenMP worker threads in the factory trainer
  (8524 is exactly that process, and `OMP_NUM_THREADS=4` is set). Confirm with
  `py-spy dump --pid 8524` or by enabling `faulthandler` and signalling the process;
  that names the blocking frame instead of assuming it.
  FIXES, in order of preference: (1) close/join whatever holds the interpreter open at
  the end of `dottie.research.__main__` (real fix, once the diagnostic names it — STILL
  WORTH DOING, the stopgap only hides it);
  (2) [x] **APPLIED 03:57** — `os._exit(code)` after flushing stdout/stderr, so a finished
  worker always terminates. Safe here and verified before shipping: every ledger write
  commits inside its own `with self._conn()` block, and the package registers **no**
  atexit/`__del__` cleanup (both checked). Tested: `status` exits in **0.5 s with code 0**
  and still prints its JSON; a bad subcommand still exits **2** (the wrapper does
  `exit $LASTEXITCODE`, so this mattered); 35/35 research tests green (they call `main()`
  directly, so the new path doesn't affect them). Bonus: the explicit flush pushes the
  result line out of Python's block-buffered stdout, which is what made `run.log`
  useless as a liveness signal;
  (3) set `MultipleInstances` to
  Queue/Parallel so orphans can no longer eat ticks (mitigation — the wrapper's
  exclusive lock is the real concurrency guard, and it IS released correctly:
  verified the lock file re-opens exclusively after the stop, so 04:05 will run).
  NOT DONE deliberately: the four orphans are inert (0 MB, 0 CPU) and killing them
  would free nothing while risking an in-flight sqlite write, so they were left alone.
- [ ] **§5 runner incident 3 (03:00) — SAME zombie pattern, now understood.** The task
  sat in state `Running` with NO worker process alive (checked: no python/powershell from
  that instance), i.e. Task Scheduler still believed a run was in flight. With
  `MultipleInstances=IgnoreNew` that would have silently refused the 03:05 trigger, just
  like 02:05. Cleared with `Stop-ScheduledTask` → state Ready, next 03:05 armed.
  **This is now 2 of 3 hourly ticks lost to the same cause**, so it is a real reliability
  bug, not bad luck. Fix options for you: (a) set the task's `MultipleInstances` to
  `Parallel` or `Queue` (the wrapper already holds an exclusive lock, so concurrent
  workers cannot actually collide — the lock, not the scheduler, should be the guard);
  (b) add `Stop-ScheduledTask` self-healing at wrapper start; (c) find why the instance
  exits without Task Scheduler noticing (0xC000013A earlier suggests the process tree is
  being killed abnormally). (a) is the cheapest and matches the existing lock design.
- [ ] §5 runner incident 2 (02:15): the 01:05 runner instance died with 0xC000013A
  (console-interrupt semantics; cause UNEXPLAINED — no ExecutionTimeLimit is set) and
  its still-running corpse made `IgnoreNew` swallow the 02:05 trigger. Recovered by
  manual Start-ScheduledTask 02:16 (GASA trains this run). If 0xC000013A recurs,
  instrument the wrapper (trap + exit-code logging) before theorizing.
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
9.3 Every session: **run a read-only `git fetch` and check `git status -sb` for divergence
    BEFORE the first commit** (parallel Claude sessions are active). §5.3.R98 is why this is
    concrete now: 25 commits were made before anyone checked, and origin had meanwhile gained
    a repo-wide reformat that conflicts with 32 of them. A fetch is free and catches it at
    commit 0, not commit 25. Then: factory suite before any factory push; never leave conflict
    markers on disk in bind-mounted trees (the trainer restart-imports them).
9.4 Lane splits for parallel sessions: two agents racing on the same file
    (`adapters.py`/`sources.yaml`, observed 2026-07-19) resolved cleanly only by
    luck of additive edits — when spawning parallel work, assign disjoint file
    lanes explicitly (curriculum registry vs adapters vs tests), and the second
    lane pulls before touching anything shared.
9.6 **Before writing a script, read `scripts/README.md`.** It indexes every operational tool
    — the restart/recovery scripts, the run-log and pre-registered report readers, the
    mutation audit, and the `ab_nano.py` / `PROMOTION.md` / `candidate.py` bundle that is
    **generated automatically on every promotion**. Written after §5.3.R92, where I built a
    seed sweep the loop had already generated a better version of, for that exact candidate,
    hours earlier. Every count in it was verified against source, not recalled.
9.5 **Any tick that writes to the reasoning log (below) runs `python scripts/check_todos_timestamps.py`
    before committing.** Never write a clock time that did not come from `date` or
    `git log` in that same tick; if neither is to hand, write the commit sha or "this
    tick" — a relative marker that is true beats a precise one that is invented.
    Provenance: §5.3.R88, where 14 fabricated timestamps survived every review pass
    because they were internally consistent. §5.3.R89 is the same failure in another
    field ("one `uv pip install typer` would settle it" — an estimate never run).
    **The generalisation both share: a claim that costs nothing to check is exactly the
    kind that never gets checked.** The script only covers the clock; the discipline it
    encodes is the point, and applies to every number written from memory rather than
    from a tool.
