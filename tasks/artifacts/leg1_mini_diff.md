# Leg 1 — tool-branch depth extension to TPP ~20 (PROPOSAL, not applied)

## ⚠ REVISED 2026-07-23 after the completion eval — read this first

The original draft leaned on the precedent "extension won last time (7,814 →
276)." The completion A/B inverted that precedent for the p4/p5 phases:
**275.95 (step 1487, through p3) → 2,341 (stable_p4) → 4,103 (step 2861,
through p5 anneal)** on identical p0–p3 bins. The p3-extension precedent
remains positive — the damage is specific to the seq-4096 phases and the
narrow anneal (and bin 1 actually improved during p5: 1,150 → 617, so it is
mix-narrowing, not global decay). Three consequences baked into this
revision:

1. **Replay is mandatory.** The p4/p5 mixes below now carry explicit
   early-phase replay shares (logic/math/encyclopedia/code) so the tail
   phases stop training away p0–p3 competence. TPP-only reasoning is dead:
   p4/p5 proved tokens can subtract on the measured axis.
2. **The doubled anneal is cut back.** The draft doubled p5 to 400M at an
   even narrower mix — that would amplify the measured failure mode. p5 stays
   200M with replay keys added.
3. **New prerequisite: long-seq bins.** Before boot, build a long-seq bin set
   (target-bytes bumped so p4/p5 bins hold >4096 contiguous tokens), stash
   the current comparable bins aside, and score BOTH finals — otherwise the
   gate cannot see what seq-4096 training buys, only what it costs.

Open question for the steer thread: init Leg 1 from `tool_final.pt` @2861
(resume the damaged-but-long-ctx-trained state; the 350M p3 re-entry may
repair short-ctx — that is what the gate measures) vs from `stable_p4.pt` or
even step-1487 (discard p5's narrowing). Recommendation: resume from
tool_final @2861 WITH the replay mixes — one honest experiment, gated.

Status: **proposal only.** `apps/ava-factory/configs/` is bind-mounted into the
live trainer and has not been touched. This posts to the steer thread; the
operator applies the diff and boots the tool-fork compose after the current run
finishes and the post-run eval A/B baseline is recorded.

Source doc: `apps/ava-factory/docs/CURRICULUM_EXPANSION.md` (Leg 1). Every
number below is derived from the current `configs/mini.yaml` and
`dottie/train.py` semantics, cited inline.

## The numbers, reconciled

- CURRICULUM_EXPANSION's "TPP 12.5" back-solves to the **171M** param count
  (2.14B tokens trained at doc time / 12.5 = 171M — the original spec's count;
  the mini.yaml header's arithmetic says ~162M). On the doc's own basis:
  **3.4B / 171M = TPP 19.9 ≈ 20** (162M basis: 21.0). Either way, "+0.9B
  tokens" is exactly the doc's Leg 1 number: 2.5B → **3.4B** cumulative.
- Branch steps: `total_steps = branch.tokens // tokens_per_step`
  (train.py:487-490) → 1_650_000_000 // 262_144 = **6294 steps** (was
  750M → 2861, matching the yaml's own "~2861 steps" comment — cross-check).
  Fresh work: 0.9B = **3433 steps**.
- Wall clock: ~1 GPU-day at the measured ~10.5k tok/s (0.9e9/10.5e3 = 23.8h);
  CURRICULUM_EXPANSION plans **~1.3 GPU-days** (derated for p4/p5 seq-4096) —
  use 1.3 for scheduling.
- Phase walk of the resumed branch (`phase_for_step`, cumulative over
  `phases[]`; branch `mix:` is descriptive only — nothing in train.py reads it):
  resume at tokens_done 2.5B → **p3 until 3.05B** (550M at the new mix — the
  proven-positive seq-2048 regime), **p4 3.05–3.2B** (replay added), **p5
  anneal 3.2–3.4B** (200M, replay added, kept last). Sum of phases = 3.4B ✅.

## Unified diff against `apps/ava-factory/configs/mini.yaml`

Mechanically generated from the live file by `tasks/artifacts/leg1_diffgen.py`
and verified with `git apply --check` (exit 0) on 2026-07-23. Regenerate any
time with: `python tasks/artifacts/leg1_diffgen.py out.patch`.

```diff
--- a/apps/ava-factory/configs/mini.yaml
+++ b/apps/ava-factory/configs/mini.yaml
@@ -54,7 +54,11 @@
                                    # leave false on live mini; try on mini_overtrain smoke first.                   # NOT WIRED: ava/train.py never calls torch.compile, so
                                    # `true` here only misled perf estimates (6-10k tok/s assumed
                                    # compiled; eager reality at P2 is ~3k). Wire it before enabling.
-  tokens_total: 2_500_000_000
+  # Leg 1 (docs/CURRICULUM_EXPANSION.md): 2.5B + 0.9B = 3.4B -- TPP ~20 on the
+  # 171M-param basis the doc's own "TPP 12.5" figure uses.
+  # HAZARD: cfg.total_steps() for a BASE-preset boot grows with this value; do
+  # NOT boot the base compose service after applying (see Risks #1).
+  tokens_total: 3_400_000_000
   tokens_per_step: 262_144         # e.g. micro 16 x seq 1024 x accum 16
   # Telemetry verdict (2026-07-14, torch_peak_alloc_mb): steady-state peak
   # 12,486MB on the 12,282MB card -- every P2 step runs ~1.7GB into WDDM
@@ -71,17 +75,22 @@
   # change the running trainer until a new run / recreate.
   tokens_per_param_target: 40.0
 
-phases:                            # same 6-phase shape, 2.5B budget
+phases:                            # same 6-phase shape, 3.4B budget (Leg 1)
   - {name: p0_logic,      tokens: 400_000_000, seq: 512,  rope_base: 10000,  ntk: 1.0, mix: {logic: 1.0}}
   - {name: p1_math,       tokens: 500_000_000, seq: 512,  rope_base: 10000,  ntk: 1.0, mix: {math: 0.85, logic: 0.15}}
   # tool_use = agentic workflows / harness skills (react_tools generator):
   # foundation vocabulary in P2, multi-step tool workflows in P3, and
   # grounding-heavy (notfound/cite) anneal in P5.
   - {name: p2_foundation, tokens: 850_000_000, seq: 1024, rope_base: 10000,  ntk: 1.0, mix: {encyclopedia: 0.30, code: 0.20, tool_use: 0.15, math: 0.15, logic: 0.10, chat: 0.10}}
-  - {name: p3_reasoning,  tokens: 400_000_000, seq: 2048, rope_base: 50000,  ntk: 1.0, mix: {math_reasoning: 0.30, tool_use: 0.30, logic: 0.15, temporal: 0.15, code: 0.10}}
+  # Leg 1 depth REVISED: +900M in p3 (the seq-2048 regime with the POSITIVE
+  # extension precedent; the eval killed the draft's p5 doubling). weights
+  # sum to 1.0. phase_for_step() puts the resumed branch (tokens_done 2.5B)
+  # back in p3 until 3.05B: 550M fresh at this mix, then p4, then anneal.
+  - {name: p3_reasoning,  tokens: 1_300_000_000, seq: 2048, rope_base: 50000,  ntk: 1.0, mix: {math_reasoning: 0.35, tool_use: 0.35, logic: 0.10, temporal: 0.10, code: 0.10}}
   # tool_use in P4 = long-context search/cite (tool_curriculum L2/L3 + p4_search_cite).
-  - {name: p4_long,       tokens: 150_000_000, seq: 4096, rope_base: 100000, ntk: 1.2, mix: {long_docs: 0.55, needle: 0.25, tool_use: 0.20}}
-  - {name: p5_anneal,     tokens: 200_000_000, seq: 4096, rope_base: 100000, ntk: 1.2, mix: {tool_use: 0.25, proofs_verified: 0.20, chat: 0.20, safety: 0.20, math_reasoning: 0.15}}
+  # REVISED: p4/p5 carry early-phase REPLAY shares (the completion eval showed
+  # these phases cost 275.95->4,103 weighted ppl on p0-p3 bins without them).
+  # Replay keys are existing generators — no collector/source edits needed.
+  - {name: p4_long,       tokens: 150_000_000, seq: 4096, rope_base: 100000, ntk: 1.2, mix: {long_docs: 0.40, needle: 0.20, tool_use: 0.20, encyclopedia: 0.10, math: 0.10}}
+  # Anneal stays 200M (the draft's doubling would amplify the measured
+  # narrowing); tool_use .25->.30; logic+math replay .15 funded by
+  # proofs_verified .20->.10 and chat .20->.15. safety untouched.
+  - {name: p5_anneal,     tokens: 200_000_000, seq: 4096, rope_base: 100000, ntk: 1.2, mix: {tool_use: 0.30, proofs_verified: 0.10, chat: 0.15, safety: 0.20, math_reasoning: 0.15, logic: 0.05, math: 0.05}}
 
 # Tool/chat forks from mini base_final (T9.3 gate before base1b).
 # --branch tool --init /ckpt/base_final.pt --run /ckpt/tool  (no --resume)
@@ -89,20 +98,23 @@
 branches:
   tool:
     init: /ckpt/base_final.pt
-    tokens: 750_000_000            # extended 2026-07-22 (was 390M/1487 steps, done): ~2861
-                                   # steps @ 262144 tok/step. Completes the FULL curriculum:
-                                   # p3 tail (2.14->2.15B) then p4_long + p5_anneal to 2.5B.
-                                   # p4/p5 seq-4096 is proven on this GPU in bf16 (base run's
-                                   # stable_p4 exists); AVA_MAX_MICRO_BATCH is the relief valve.
-                                   # Operator 2026-07-22: "get training up and running" for the
-                                   # live dashboard + game twin. Prior leg (390M) logged below.
-                                   # was: 300M->390M 2026-07-21, +343 steps within p3 for the
-                                   # scout_cli (tool_use) + zk_math (math_reasoning) curriculum.
+    tokens: 1_650_000_000          # Leg 1 (was 750M/2861 steps, done): +0.9B to 3.4B cum
+                                   # = ~6294 steps @ 262144 tok/step. WSD horizon
+                                   # re-extends: plateau to step ~5790 (0.92), then
+                                   # decay -- the same move as the 390M->750M
+                                   # extension that took weighted heldout ppl
+                                   # 7,814 -> 276. ~1-1.3 GPU-days at ~10.5k tok/s;
+                                   # AVA_MAX_MICRO_BATCH stays the p4/p5 seq-4096
+                                   # relief valve.
+                                   # was: 750M 2026-07-22 (full curriculum to 2.5B);
+                                   # 390M 2026-07-21 (+343 steps within p3).
     start_tokens: 1_750_000_000    # cum through p0+p1+p2 → enter p3
     freeze: [system1, system2]
     finetune: [critic, planner, router, arbitration]
     router_bias: [0.10, 0.35, 0.10, 0.45]   # tool_selection prior
-    mix: {math_reasoning: 0.30, tool_use: 0.30, logic: 0.15, temporal: 0.15, code: 0.10}
+    # descriptive only -- train.py never reads branch mix; the sampler follows
+    # phases[] via phase_for_step(). Mirrors the new p3 mix.
+    mix: {math_reasoning: 0.35, tool_use: 0.35, logic: 0.10, temporal: 0.10, code: 0.10}
 
 branch_chat:
   init: /ckpt/base_final.pt
```

## Rationale per change

1. **`branches.tool.tokens` 750M → 1_650M.** The one number that actually
   extends the run (train.py:487-490 derives branch `total_steps` from it).
   +0.9B fresh tokens lands cumulative at 3.4B = TPP ~20 — the doc's Leg 1
   target. Restart semantics are proven: resume restores step/tokens_done and
   the extended horizon re-opens the WSD plateau (lr 6.0e-4 until step ~5790,
   cosine to 6.0e-5 by 6294). Same maneuver as the 390M→750M extension, whose
   result (weighted heldout ppl 7,814 → 276) is the measured precedent.
2. **p3 `tokens` 400M → 1_300M, mix `math_reasoning/tool_use` .30→.35 each.**
   Puts the resumed branch back inside p3 for 550M fresh tokens at a mix
   shifted toward the two weakest measured axes (probes 0/200 tool-selection,
   agent-eval 0%) — and concentrates the +0.9B in the ONLY regime with a
   positive extension precedent (7,814→276 was a within-p3 move). Mix keys
   unchanged as a SET — no collector/source edits (collector-spin gotcha
   avoided by construction). Weights sum to 1.0.
3. **p4/p5 get REPLAY, p5 stays 200M (draft's doubling reverted).** The
   completion eval measured what p4/p5 without replay cost: 275.95→2,341→4,103
   weighted on p0–p3 bins. p4 funds encyclopedia+math replay (.10+.10) from
   long_docs/needle; p5 funds logic+math replay (.05+.05) from proofs_verified
   and chat. safety weight untouched to protect the general-mix
   non-regression half of the tool gate.
4. **`tokens_total` 2.5B → 3.4B.** Keeps `sum(phases) == tokens_total` and the
   dashboard/status run-fraction honest (pipeline_status derives run progress
   from it). Branch step math does NOT use it. See Risk #1 for the hazard; if
   the steer thread prefers, variant B = leave it at 2.5B and accept a >100%
   run-fraction display during the extension.
5. **p4 untouched.** seq-4096 long-context is proven on this GPU
   (stable_p4 exists) and its tool_use share (0.20) already serves search/cite.
6. **Branch `mix:` comment fix.** Grep-verified: `mix` is a `PhaseConfig` field
   only; train.py/StreamingShardSampler take the phase mix. Mirroring the new
   p3 mix keeps the yaml from lying to the next reader.

## Prerequisites (check before boot)

- [ ] Current run reports `already_done` / `tool_final.pt` written at 2.5B.
- [ ] **Baseline A/B recorded first**: run the eval harness on `tool_final.pt`
      @2.5B and COPY `reports/branch_eval_results_real.json` +
      `REPORT_REAL.md` out of the way (the harness overwrites them — known
      footgun). Fill the "baseline" column below from that run.
- [ ] Packed runway: doc says 3.16B ready overall; confirm p3-claimable
      tool_use/math_reasoning shards exist (manifest `tokens_ready(3)`), else
      collectors need lead time before the trainer boots.
- [ ] Copy `/ckpt/tool/stable_p3.pt` and `stable_p4.pt` aside if wanted: the
      resumed run crosses p3→p4→p5 again and OVERWRITES both stable ckpts.

## Risks

1. **tokens_total hazard.** `cfg.total_steps()` for a BASE-preset boot grows
   from 9536 to 12969 steps; a base compose boot with `--resume` would train
   past 2.5B instead of exiting `already_done`. Mitigation: only boot the
   tool-fork compose after applying (comment now in the yaml); or take
   variant B (leave tokens_total).
2. **LR re-plateau from a decayed state.** The 750M leg already decayed to
   6e-5; the extension jumps back to 6e-4. Precedented (390M→750M did exactly
   this and won), but it is part of why the A/B gate is mandatory.
3. **Old-region relabeling.** 2.15–2.5B was trained as p4+p5 under the old
   boundaries; the new schedule labels that span p3. Harmless for the resumed
   run (only forward tokens matter) but expect dashboard phase history to read
   differently across the boundary.
4. **seq-4096 flake exposure.** p4/p5 return at the tail. `checkpoint_every_steps: 8`
   still caps the blast radius (restore 50 once on charger, per the existing
   yaml comment); `AVA_MAX_MICRO_BATCH` is the OOM relief valve.

## Eval placeholders (fill after baseline + Leg 1 runs)

Gate rule (from CURRICULUM_EXPANSION): harness A/B + probe delta vs the
post-run baseline; **no graduation without a win**. Tool-gate rule (TODOS
1.2.c): beats base on both tool metrics AND general-mix CE regression <= 2%.

| Metric | Baseline: tool_final @2.5B | Leg 1: tool_final @3.4B | Delta | Gate |
|---|---|---|---|---|
| weighted heldout ppl (10x bins, same build) | TBD | TBD | TBD | improve |
| p3 bin ppl | TBD | TBD | TBD | improve |
| p4 / p5 bin ppl (bins need >4096 contiguous tok) | TBD | TBD | TBD | report |
| exact-match probes, 6 legacy sets | TBD (expect 0/200) | TBD | TBD | non-regress |
| NEW `tool_selection` probe set (20 items, additive — unscored by harness; score via a generations dump + `scripts/probe_error_analysis.py`) | TBD | TBD | TBD | report + failure-mode mix |
| tool_gate `tool_ce` | TBD | TBD | TBD | improve |
| tool_gate `tool_planner_rate` | TBD | TBD | TBD | improve |
| tool_gate `general_ce` regression % | — | TBD | TBD | <= 2% |

A/B discipline: ppl numbers are comparable only within one heldout-bin build;
copy reports out between runs.

## Companion pieces landed with this proposal (host-side, additive only)

- `apps/ava-factory/evals/probe_items/tool_selection.jsonl` — 20 tool-selection
  probes in the existing `{"prompt","answer"}` schema, gold answers drawn from
  tool_curriculum's L3 catalog, surface form distinct from training templates.
  Existing 6 probe files byte-identical; `evals/probes.py` deliberately NOT
  rewired (A/B comparability). Follow-ups after the A/B: wire the set into
  `score_probes`, and register the fixed stem "the single right tool for this
  is" in `evals/eval_sets.py` before the next corpus build (decon discipline).
- `apps/ava-factory/scripts/probe_error_analysis.py` — post-run failure-mode
  classifier (wrong-tool / malformed-call / refusal / other) over a per-probe
  generations dump; `--dry-run` fixture demo; tests in
  `tests/test_probe_error_analysis.py` + `tests/test_tool_selection_probes.py`.
