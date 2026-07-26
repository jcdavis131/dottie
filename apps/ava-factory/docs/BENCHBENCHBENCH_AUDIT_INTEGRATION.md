# benchbenchbench → Ava v6.4 eval harness + hill-climb integration

**Source:** https://github.com/emollick/benchbenchbench — Decision-level holdout audits for benchmark-generation evaluators. Idea: public scoring should select models that still win on held-out faults it didn't see.

**Relevance to Ava-agi-factory-v6-4:** High. Current harness (`evals/run_harness.py`, `evals/common.py`, `evals/eval_sets.py`) mixes public probes + J-Space tests with no separation between development-visible and hidden selection. Hill-climb loop (`tasks/plan-hillclimb.md`, `specs/11_arch_hillclimb.md`) climbs single scalar `Score` with no audit that Score predicts hidden utility. Same failure mode benchbenchbench calls out: overfitting to cheap judge.

**Current gap audit (read-only review):**
- `evals/eval_sets.py`: 4 sets (j_space, capability, needle, systems) all public, all decontaminated from training but not from each other. No hidden holdout.
- `evals/run_harness.py`: writes `branch_eval_results_real.json` + `REPORT_REAL.md` with jspace + probes + ppl. No public/hidden split.
- `eval_harness.py` (root): needle-only stub.
- Hill-climb: Score = w1·(-log PPL) + w2·probe_acc + w3·route_KL_sep + w4·hl_fit − … — no correlation check vs frozen capability.
- `ava-open-harness` already has `frontier_rubric.py` (11-category) — good candidate for cheap public judge, but no hidden fault tracking.

## Minimal free-tier proposal — no new deps, HOME-only, offline-first

**Principle:** Keep public judge cheap (fast CPU / nano mock), add hidden fault set that never leaks to hill-climb selection, track decision-level audit metrics.

### 1. Add hidden fault set (data-only, no training)

Create `evals/hidden_faults/` git-ignored mirror of `eval_sets.py` structure, locally seeded but not published:

- `evals/hidden_faults/j_space_hidden.jsonl` — 30-50 new swap-intervention probes written in same style as J_SPACE_PROMPTS but never added to `EVAL_SETS`. Keep offline in `data/<preset>/heldout_hidden_phaseN.bin` style? Actually reuse `evals/eval_sets.py` comment: keep distinct surface-form.
- `evals/hidden_faults/capability_hidden.jsonl` — arithmetic / modus ponens variants with new numbers.
- `evals/hidden_faults/systems_hidden.jsonl` — db_mechanics / compression stems never used in generators.
- `evals/hidden_faults/needle_hidden.jsonl` — new passcodes/keywords.

Implementation rule: `ava.pipeline.decontaminate` already filters `all_eval_texts()`. Extend to filter hidden too, but **do not** add hidden prompts to public EVAL_SETS registry. Train crew never sees hidden.

File count target: <100 hidden items total, deterministic generation, manual review for >=5 words.

**Free-tier guard:** All generation via existing `probe_items_gen.py` logic, seeded `EVAL_SEED=1234` variant `EVAL_SEED+1`. No API calls.

### 2. Keep public judge cheap

Current `score_probes(n_per_set=200)` is already cheap. Keep as public:

- Public = `evals/probe_items/` + J-Space canonical 5 tests + perplexity.

Hidden stays off fast path:

- Only run hidden on: nightly cron, `T9.3` base1b GO/NO-GO, or `spec 11` arch candidate adoption gate.

Spec change: In `plan-hillclimb.md` Phase 4 wording: "Freeze eval set; compare to previous best" → split to "Freeze public eval for hill selection; freeze hidden eval for audit only (never selection)."

### 3. Decision-level audit metrics (match benchbenchbench paper)

Benchbenchbench headline metrics (README): Spearman rho, Pairwise accuracy, Regret@k, Utility recovery. Adapt to Ava branch selection:

Define for each hill-climb tick t with candidates C_t = {c0...ck} (nano checkpoints, arch variants, or anneal branches):

- `public_score(c)` = scalar Score from `plan-hillclimb.md` (existing).
- `hidden_score(c)` = accuracy on hidden faults only (no public items).

Compute per `benchbenchbench/` audit:

```python
# pseudocode — to be added to `evals/run_harness.py` or new `evals/audit_metrics.py`, pure python stdlib
def spearman_rho(public_rank, hidden_rank): ...  # no scipy — rank diff implementation
def pairwise_accuracy(public_scores, hidden_scores): # fraction of pairs agreeing order
def regret_at_k(public_scores, hidden_scores, k=8): # max_hidden - max_hidden among top-k public
def utility_recovery(public_scores, hidden_scores): # (top-public-hidden - mean_hidden)/(max_hidden-mean_hidden)
```

Logging target (reuse existing `reports/`):

- `reports/branch_eval_results_real.json` → add key `"audit": {"public_rank": [...], "hidden_rank": [...], "spearman_rho": float, "pairwise_acc": float, "regret@8": float, "utility_recovery": float}`
- `REPORT_REAL.md` → add section "## Decision-level holdout audit (benchbenchbench-style)" with 4 numbers + frozen-vs-hidden interpretation note.

**No new deps:** Implement Spearman via manual rank + Pearson correlation using Python math only. Keep <50 LOC.

### 4. Integrate into hill-climb loop

Edit `tasks/hillclimb-log.md` + `tasks/plan-hillclimb.md` tick contract:

- Every 5m tick: public_score only (no hidden cost).
- Every nightly / T9.3 gate: run hidden audit, log `audit` JSON, **do not** use to pick candidate unless `regret@8 > threshold` triggers alarm.
- Alert rule: if `utility_recovery < 0.93` (benchbenchbench hidden-only baseline 93.1%) or `spearman_rho < 0.58` (their hidden-only), flag in `dottie_telemetry.jsonl` as `bench_audit_degraded` — same channel as existing telemetry, no new system.

Maps to Spec 11 ordering: T11.4 MatFormer and T11.2 DeltaNet are arch candidates — they must pass hidden audit before adoption, not just public Score.

### 5. Wiring checklist (docs-only, zero code exec needed for this PR)

- [ ] Add `evals/hidden_faults/README.md` stub: explains off-limits rule, file count, that these are never added to `EVAL_SETS`.
- [ ] Amend `specs/06_evaluation.md` (create if missing) to describe public/hidden split, reference benchbenchbench repo link.
- [ ] Amend `specs/11_arch_hillclimb.md` acceptance: "candidate must show Spearman rho >= 0.55 and utility_recovery >= 0.93 on hidden audit before base1b adoption".
- [ ] Amend `tasks/plan-hillclimb.md` to note benchbenchbench-style tracking.
- [ ] Update `docs/HARNESS_SKILL_INTEGRATION.md` with audit flow.

### 6. Example patch sketch (not applied in docs-only mode)

```diff
# evals/run_harness.py
- results["meta"] = {...}
+ results["audit"] = compute_audit(results["public_scores"], hidden_scores)
```

Hidden loader:

```python
def load_hidden(preset):
    p = Path(__file__).parent / "hidden_faults" / f"{preset}_hidden.jsonl"
    if not p.exists(): return []
    return [json.loads(l) for l in p.read_text().splitlines()]
```

All file I/O local, free-tier, HOME-only (`~/workspace/dottie/...`), no PaaS, no network.

## Why this fits Ava

- J-Space tests (spider->ant, France->China) are exactly the kind of swap-intervention probes benchbenchbench would treat as hidden faults. We already have decontamination infra — reuse.
- Existing `heldout_path(preset, phase)` in `common.py` hints at phase-wise holdout; hidden faults extend naturally.
- Hill-climb Score already aggregates multiple signals — bench audit answers: does climbing Score actually recover utility on truly unseen probes?
- Zero cost daily, high signal for T9.3 base1b decision.

## Non-goals (explicit)

- No new evaluator LLM judge, no OpenRouter API (benchbenchbench runner needs it, we don't).
- No training on hidden set, no publication of hidden set, no git commit of hidden items.
- No scipy / pandas — keep stdlib only.
- No Vercel / cloud, no paid APIs.

## References

- https://github.com/emollick/benchbenchbench
- Local: `evals/eval_sets.py`, `evals/run_harness.py`, `evals/common.py`, `specs/11_arch_hillclimb.md`, `tasks/plan-hillclimb.md`
