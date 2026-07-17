# Solo personal project, no connection to employer, built with public/free-tier only

# Ava AGI Factory v6.4 — RL Integration (Hill-Climbing Machine findings)

Source: review of the MAI-Thinking-1 technical report analysis ("The Hill-Climbing Machine:
System-Level Optimization and RL Breakthroughs in MAI-Thinking-1", reviewed 2026-07-17).
Companion to `docs/DISTILLATION_INTEGRATION.md` — that doc covers the distillation half of
"specialist climb → consolidate"; this doc covers the RL half plus the measurement discipline
that keeps a long climb honest. Buildable contract: `specs/12_rl_training.md`. Plan:
`tasks/plan-rl.md`. Tracker: `TODOS.md` T11.7.

**Terminology guard:** in this repo `reward` has historically meant a *data-quality filter
score* (keep doc if mock-Nemotron score > 0.8 — `logic_textbook_pipeline.py`). Everything in
this doc and spec 12 uses `rl_return` / `R_task`/`R_lang`/`R_len` naming to avoid collision.

## What the report found (24 findings, compressed)

1. **Rank invariance is dead.** A 5B-scale data-mix ablation *inverted* at 23B/20T (stem-heavy
   won small, code-heavy won big). Single-point small-scale validation is unreliable; only a
   **scaling ladder** (≥2 scales, fixed token:param ratio) with a consistent *trend* counts.
2. **Efficiency Gain (EG)** — one currency for every R&D change: how much extra compute the
   baseline would need to match the candidate's loss. Decoupled **EG_FLOPs** (algorithmic) vs
   **EG_Time** (wall-clock incl. kernels). Lets you keep an arch whose MFU temporarily craters
   (their 512-expert LatentMoE: 22%→16%→20% after ~20 kernel fixes) because EG_FLOPs trends up.
3. **GRPO collapses two ways** over long climbs: entropy collapse (rigid single heuristic) and
   policy divergence (gibberish explosion). Their discipline system:
   - **Thermostat** — integral controller on policy entropy vs target (~0.3) adjusts the *upper
     clip bound* (trust-region width) via a relaxation parameter k. No entropy-bonus loss term.
   - **Circuit breaker** — hard absolute ceiling over the whole objective, superimposed even on
     GRPO's intentionally-unclipped zones (active correction / active abandonment). Never binds
     in normal training; kills one-in-a-million gradient spikes.
   - **Self-distillation recovery** — assume long runs *will* corrupt (bf16-train vs full-precision
     inference drift). Continuously bank verified-successful trajectories; on crash, discard the
     checkpoint, SFT a fresh pre-RL checkpoint on ~1M banked traces → instantly back to peak.
     Diversity > quantity; >1M traces over-constrains exploration.
4. **rl_return = w_task·R_task + w_lang·R_lang + w_len·R_len.** R_lang pins the CoT to one
   language (stops drift to symbolic/multilingual traces). R_len is a **difficulty-scaled length
   penalty** — inverse to historical pass rate: easy → severe (snap to optimal path), hard →
   relaxed (budget for deep derivation). Kills "think longer = score higher" reward hacking.
5. **Verifiable environments over human grading.** STEM: 5M+ QA pairs; MCQ/proofs rewritten to
   open-ended extraction via 3-pass consensus; answer-leakage removal; SymPy execution or judge
   verification; difficulty calibrated by pass rates across model tiers; blind-grading may *drop
   the ground truth* when the judge prefers the model-consensus derivation (defends against bad
   answer keys). SWE: 102M PRs → 265,617 deterministic fail-to-pass/pass-to-pass container
   environments (5.5% survival). Reward comes only from deterministic checks.
6. **Specialist climbs → consolidate.** Fork base into 3 domain climbs (STEM/agentic/safety),
   aggregate best traces, SFT-unify, light final RL. Safety is *inside* the same return:
   unsafe compliance on a harmful prompt ≡ unnecessary refusal on a borderline prompt (both
   severe defects) — no separate reward model, no alignment tax.
7. **Capabilities learned, not inherited** — no third-party frontier distillation, no
   LM-synthetic data in pre-training; plus a provenance caveat (their "clean licensed" pitch
   still ingested 24.2B Common Crawl pages — marketing ≠ lineage).
8. **Model tiering** — a small sibling trained on the *same harnesses* takes ~90% of routine
   traffic; escalate to the big reasoner only for deep multi-file agentic work.
9. **Data details worth stealing:** evolutionary code (commits + PRs, not just files) at 54.6%
   of the mix; math upsampled 5.28×; exact→fuzzy(MinHash 0.8)→**semantic** dedup funnel; strict
   benchmark decontamination; mid-training context extension by *repacking the existing best
   mix* to longer sequences rather than injecting new long-form sources.

## Mapping onto Ava — adopt / adapt / already-have / reject

### Already have (validate, don't rebuild)
- **Specialist→consolidate** is Ava's branch (code/math/chat from `ava_stable_736k.pt`) → MOPD
  unify flow (`docs/DISTILLATION_INTEGRATION.md`). The report *endorses* this shape; its RL
  climbs slot in as the per-branch training step before MOPD, exactly the DeepSeek-V4 pipeline
  already cited there (SFT → GRPO per domain → on-policy-distill unify).
- **Self-distill recovery** ≈ `on_policy_distill.py --mode earlier` (GLM-5 pattern). What's
  missing is the *trace bank*: we currently restore from an earlier checkpoint's weights, not
  from banked verified trajectories. Spec 12 adds the bank; `--mode earlier` stays the fallback.
- **Dedup funnel** — `ava/pipeline/dedup.py` already does sha256 exact + MinHash LSH; semantic
  dedup (embedding clustering) is the missing third stage. Low priority at nano/mini corpus
  sizes; revisit at base1b (tracked in plan-rl.md, not a task yet).
- **Decontamination** — `ava/pipeline/decontaminate.py` (13-gram) matches their practice.
- **No-inherited-capabilities** — already policy here (from-scratch, spec 02 forbids network
  datagen); Ollama judges *grade*, they don't generate training text. Keep it that way; the
  report's provenance section is a warning about how easily this claim erodes.
- **Frozen eval snapshots** (T10.6) = their benchmark-integrity discipline.

### Adopt now (cheap, unblocks measurement — no GPU needed)
- **EG metric + scaling ladder gates** → `efficiency_gain.py` (stdlib-only, this change).
  Fits the baseline loss-vs-compute curve, answers "how much compute would baseline need to
  match this?" Feeds three surfaces: (a) `ORCHESTRATION.md` GO/NO-GO gates for nano→mini→base1b,
  (b) `tasks/hillclimb-log.md` per-lever deltas, (c) scout-rtx promotion decisions (see below).
  EG_FLOPs vs EG_Time maps cleanly to an existing repo scar: DeltaNet (T11.2) has analytic
  VRAM/FLOPs wins but unmeasured wall-clock — that's precisely an "EG_FLOPs up, EG_Time unknown"
  state, and the report says: keep climbing, measure both, decide on the trend.
- **Rank-invariance rule for the proxy loop.** scout-rtx currently promotes single-point
  TinyStories wins into `model_1b.py`. New gate (pushed to `scout-rtx/programs/program-ava.md`):
  a win must hold at **two proxy scales** with EG logged at both before promotion. nano (13.8M)
  → mini (171M) is the in-repo ladder rung for anything the proxy can't settle.

### Adapt for free-tier scale (spec 12 — build when T9.3/T9.5 unblock)
- **GRPO-lite for the math branch** (T11.7's "MaxEnt RL" slot). G=8 rollouts (not 32) at
  nano/mini scale, single 4080. The three discipline mechanisms are scale-free and cheap —
  an integral controller, a scalar clamp, and a JSONL trace bank — so we implement all three
  from day one rather than rediscovering the failure modes. Details, VRAM math, and acceptance
  gates in `specs/12_rl_training.md`.
- **Verifiable returns from datagen we already trust.** We don't have 265k SWE containers; we
  *do* have deterministic generators whose answers are computed in Python from the same values
  rendered into the prompt (B-families, `workflow_jobbench` planted-contradiction tasks) and
  `evals/` + `eval_frontier_rubric.py` (`Rubric`/`FrontierTask`/`CriteriaJudge`) as the judge
  path. R_task = exact-match/execution check first, judge only where execution can't verify.
  Difficulty calibration = historical pass rate per problem family, banked alongside traces.
- **Difficulty-scaled length penalty.** Directly implementable: per-family pass rates already
  computable from eval history; penalty weight w_len(family) ∝ pass_rate. Also the answer to a
  question `inner_monologue_research.md` already asks — when should S1 answer fast vs S2
  deliberate: easy prompts get a severe length penalty (S1-shaped behavior), hard prompts get
  budget (S2-shaped). The length penalty is the *training-time* signal that the S1/S2 router
  needs at inference time; log per-difficulty token counts so this correlation is measurable.
- **Safety inside the same return.** `safety_blackmail` (0/180 must hold) is already a harness
  gate; spec 12 folds it into R_task as paired harmful/borderline prompt sets where unsafe
  compliance and unnecessary refusal score identically bad — no separate safety reward model.

### Reject / out of scope
- **LatentMoE, periodic attention (5 local:1 global), 512 experts** — solve trillion-param
  inter-node bandwidth problems this project doesn't have. `AvaModel1B` GQA + YaRN + optional
  DeltaNet already covers the long-context/KV-cache concern at our scale. Recorded here the
  same way spec 11 records phone embeddings: targets someone else's problem.
- **R_lang (CoT language pinning)** — trivial to add, pointless at nano/mini where multilingual
  drift can't emerge from an English-only corpus; w_lang=0 placeholder in spec 12.
- **Frontier-Tuning-style customer RL environments; 8,000-node anything.**

## Second-pass findings (deeper companion analysis, reviewed same day)

A second, longer analysis of the same report adds detail that changes a few calls above:

- **Recovery sampling: random beats clever.** Empirically, *uniform random sampling* of banked
  successful traces recovered better than biased selection, and **prompt diversity matters more
  than trace volume per prompt**. Spec 12's recovery procedure updated accordingly: dedupe by
  prompt, cap traces-per-prompt, then sample uniformly — no stratification cleverness.
- **Thermostat mechanics pinned down:** k initializes to 0 (bounds start symmetric as
  multiplicative inverses in log-ratio space); per-token policy entropy is estimated with an
  importance-weighted estimator; only the *upper* bound relaxes. Folded into spec 12.
- **Zero-init attention output is a router-stability finding, not just an MoE trick.** Uniform
  attention softmax at init ≈ average pooling → homogenized token representations → downstream
  softmax *routing* can't differentiate tokens → persistent expert/workspace imbalance. The fix
  (attention-output RMSNorm gains = 0, so the net starts as per-token dense layers and
  cross-token interaction fades in) is scale-free and directly relevant to Ava's J-Space Router
  (`routing_kl` health at init). Recorded as hill-climb candidate **T11.8** — nano-falsifiable;
  `docs/blueprint/network_init_sota.py` (blueprint scaffolding) currently fills all norm gains with 1.0.
- **SWE funnel had a hidden stage:** compile (2.08M) → *reference grading vs baseline solutions*
  (745,452; 15.3%) → F2P/P2P verified (265,617). Also: failed environments were recycled to
  *generate* synthetic problems/tests (BugPilot/SWE-Smith/SWE-Mirror-style) — the
  "reuse-the-container, synthesize-the-task" pattern fits our deterministic datagen convention
  and is noted in plan-rl open questions for the eventual agentic branch.
- **Tool-use reward shaping:** trained with 50+ tools in context; graders explicitly reward
  *parallel* tool calls and penalize redundant/duplicated calls. Cheap to adopt whenever an
  agentic climb exists; also a grading idea for scout-cli's `agent bus` automations today.
- **Anti-slop classifiers:** their pipeline ran AI-content detectors over collected web data
  and purged flagged domains. Ava's collector (not datagen — ours is deliberately synthetic
  and self-generated) should gain this check before base1b-scale web ingestion.
- **Memory layer pattern (Mem0-style):** the model stays stateless; an external memory layer
  retrieves context pre-prompt, and *internal* thought/tool traces are captured post-hoc to
  mint new long-term memories while only the sanitized answer reaches the user. Ava analog:
  `ava-skills` memory-router (ShardMemo Tier A/B/C) is the retrieval half; the trace-capture →
  memory-mint half doesn't exist yet — noted in the ecosystem brief, no task filed.
- **RFT framing worth keeping:** their Frontier Tuning rewards *optimal action sequences*
  (shortest institutional path), not just correct answers — inference-time context injection
  traded for post-trained behavior. Ecosystem analog: scout-cli `audit.jsonl` execution traces
  are exactly the workflow-trace substrate this would tune against, someday.
- **Benchmark humility:** all headline numbers are self-reported; the same model trails badly
  on Terminal-Bench 2.0 (46.0 vs 59.1/75.1 for competitors), and SWE-Bench Pro has known
  FP/FN issues. Reinforces the frozen-snapshot + falsification-gate posture here: no vendor
  number is adopted as a target; every gate is a number this repo measures itself.

## Sequencing (matches existing gates; nothing jumps the queue)

1. **Now (no GPU):** `efficiency_gain.py` + tests; EG columns in hillclimb-log; scout-rtx
   promotion gate; spec 12 + plan-rl land as contracts. ← this change
2. **Mini run completes (T9.2):** compute EG_FLOPs/EG_Time nano→mini for the current recipe —
   the baseline curve every later candidate is judged against.
3. **T9.3/T9.5 unblock (branch fine-tunes exist):** implement spec 12 GRPO-lite on the math
   branch with trace banking; `on_policy_distill.py --mode earlier` is the recovery fallback
   until the bank has enough verified traces.
4. **After first RL climb:** MOPD unify per DISTILLATION_INTEGRATION.md, then re-run the 5
   canonical J-tests + frontier rubric; `safety_blackmail` 0/180 must hold post-consolidation.

## Disclaimer

Solo personal project, no connection to employer, built with public/free-tier only. No work
data/code/systems/IP. Public pip only. Local-only training on consumer GPU.
